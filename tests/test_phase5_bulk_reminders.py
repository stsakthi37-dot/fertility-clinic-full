import asyncio
import os
import sys
import secrets
import httpx

sys.path.insert(0, r"C:\Users\keert\Downloads\fertility-clinic\fertility-clinic")

from main import app, ACCOUNTS
from supabase_client import db

DOC1_EMAIL = "doctor1@clinic.demo"
RECEP_EMAIL = "reception@clinic.demo"

async def run_phase5_tests():
    transport = httpx.ASGITransport(app=app)
    base_url = "http://localhost:8000"

    print("=========================================================")
    print("PHASE 5 TEST: BULK WHATSAPP FOLLOW-UP REMINDERS")
    print("=========================================================")

    # 1. Login Receptionist
    recep_pwd = os.getenv("RECEPTION_PASSWORD", "DefaultSecurePassword123!")
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        login_resp = await client.post("/api/auth/login", json={"email": RECEP_EMAIL, "password": recep_pwd}, headers={"origin": "http://localhost:8000"})
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        recep_user = login_resp.json()
        print(f"Logged in as Receptionist: {recep_user['name']}")

        # 2. Test Preview Endpoint across all follow-ups
        print("\n--- [TEST 1] REMINDER PREVIEW & ELIGIBILITY VALIDATION ---")
        preview_resp = await client.post("/api/reminders/preview", json={"select_all_eligible": True}, headers={"origin": "http://localhost:8000"})
        assert preview_resp.status_code == 200, f"Preview failed: {preview_resp.text}"
        prev = preview_resp.json()

        print(f"Total Selected: {prev['total_selected']}")
        print(f"Eligible Count: {prev['eligible_count']}")
        print(f"Ineligible/Skipped Count: {prev['ineligible_count']}")
        print(f"Language Breakdown: {prev['language_breakdown']}")

        assert "English" in prev["language_breakdown"]
        assert "Tamil" in prev["language_breakdown"]
        assert "Telugu" in prev["language_breakdown"]
        print("[PASS] Multilingual breakdown (Tamil, Telugu, English) verified")

        # 3. Create a Synthetic Test Patient with WhatsApp Opt-in = True in Tamil
        print("\n--- [TEST 2] CREATE OPTED-IN TEST PATIENT (TAMIL) ---")
        doc1_id = ACCOUNTS["doctor1@clinic.demo"]["supabase_id"]
        test_patient = await db.create_patient({
            "name": "TEST - Anitha Selvam",
            "phone": "+919876500001",
            "preferred_language": "Tamil",
            "doctor_id": doc1_id,
            "treatment_stage": "Follow-up Review",
            "whatsapp_opt_in": True,
        })
        print(f"Created opted-in patient: {test_patient['name']} (ID: {test_patient['id']})")

        # Create a Follow-up for this test patient
        test_follow = await db.create_follow_up({
            "patient_id": test_patient["id"],
            "doctor_id": doc1_id,
            "follow_up_date": "2026-10-15",
            "follow_up_type": "Consultation Review",
            "status": "UPCOMING",
        })
        print(f"Created follow-up #{test_follow['id']} for test patient")

        # 4. Preview specifically with this new opted-in test patient
        print("\n--- [TEST 3] PREVIEW TARGETED REMINDER WITH LANGUAGE TEMPLATE ---")
        target_prev_resp = await client.post(
            "/api/reminders/preview",
            json={"follow_up_ids": [test_follow["id"]]},
            headers={"origin": "http://localhost:8000"}
        )
        assert target_prev_resp.status_code == 200
        target_prev = target_prev_resp.json()
        assert target_prev["eligible_count"] == 1
        assert target_prev["language_breakdown"]["Tamil"] == 1
        tamil_item = target_prev["eligible_items"][0]
        print(f"Message preview in Tamil: {tamil_item['message_preview']}")
        assert "வணக்கம்" in tamil_item["message_preview"], "Expected Tamil greeting in reminder text"
        print("[PASS] Tamil template formatting and variable replacement verified")

        # 5. Test Dry-Run Mode (Must not insert message records into database)
        print("\n--- [TEST 4] DRY-RUN MODE EXECUTION ---")
        dry_run_resp = await client.post(
            "/api/reminders/send",
            json={"follow_up_ids": [test_follow["id"]], "dry_run": True},
            headers={"origin": "http://localhost:8000"}
        )
        assert dry_run_resp.status_code == 200
        dry_res = dry_run_resp.json()
        assert dry_res["dry_run"] is True
        assert dry_res["sent_count"] == 1
        print(f"Dry-run response: {dry_res['results']}")

        # Verify no messages were created in database for this follow-up
        db_msgs = await db.get_messages_for_follow_ups_on_date([test_follow["id"]], "2026-10-10")
        assert len(db_msgs) == 0, f"Dry-run violated isolation! Found message in DB: {db_msgs}"
        print("[PASS] Dry-run safety verified (zero database modifications)")

        # 6. Test Mock Sending (MOCK_WHATSAPP=true)
        print("\n--- [TEST 5] MOCK SENDING WITH DEDUPLICATION ---")
        send_resp = await client.post(
            "/api/reminders/send",
            json={"follow_up_ids": [test_follow["id"]], "dry_run": False},
            headers={"origin": "http://localhost:8000"}
        )
        assert send_resp.status_code == 200
        send_res = send_resp.json()
        assert send_res["sent_count"] == 1
        result_item = send_res["results"][0]
        assert result_item["status"] == "MOCK_SENT"
        assert result_item["provider_message_id"].startswith("wamid.MOCK_")
        print(f"[PASS] Mock reminder sent: Status={result_item['status']}, ProviderID={result_item['provider_message_id']}")

        # 7. Test Deduplication (Second send attempt on same day must be skipped)
        print("\n--- [TEST 6] SECOND SEND ATTEMPT (DEDUPLICATION CHECK) ---")
        second_send_resp = await client.post(
            "/api/reminders/send",
            json={"follow_up_ids": [test_follow["id"]], "dry_run": False},
            headers={"origin": "http://localhost:8000"}
        )
        assert second_send_resp.status_code == 200
        second_res = second_send_resp.json()
        assert second_res["sent_count"] == 0
        assert second_res["skipped_count"] == 1
        assert "already sent today" in second_res["skipped_items"][0]["reason"].lower()
        print(f"[PASS] Duplicate reminder successfully blocked: {second_res['skipped_items'][0]['reason']}")

        # 8. Test Idempotency Key Duplicate Prevention
        print("\n--- [TEST 7] IDEMPOTENCY KEY PROTECTION ---")
        idem_key = "idemp-" + secrets.token_hex(8)
        resp1 = await client.post(
            "/api/reminders/send",
            json={"follow_up_ids": [test_follow["id"]], "dry_run": True, "idempotency_key": idem_key},
            headers={"origin": "http://localhost:8000"}
        )
        assert resp1.status_code == 200
        # Immediately send with same idempotency key
        resp2 = await client.post(
            "/api/reminders/send",
            json={"follow_up_ids": [test_follow["id"]], "dry_run": True, "idempotency_key": idem_key},
            headers={"origin": "http://localhost:8000"}
        )
        assert resp2.status_code == 409, f"Expected 409 conflict on duplicate idempotency key, got {resp2.status_code}"
        print("[PASS] Duplicate request blocked with HTTP 409 Conflict using database idempotency key")

        # 9. Clean up test records
        print("\n--- [CLEANUP] REMOVING SYNTHETIC TEST RECORDS ---")
        # Delete created message
        await db.update_follow_up(test_follow["id"], {"status": "COMPLETED"})
        async with httpx.AsyncClient(timeout=10) as c:
            await c.delete(f"{db.url}/rest/v1/messages?follow_up_id=eq.{test_follow['id']}", headers={"apikey": db.key, "Authorization": f"Bearer {db.key}"})
            await c.delete(f"{db.url}/rest/v1/follow_ups?id=eq.{test_follow['id']}", headers={"apikey": db.key, "Authorization": f"Bearer {db.key}"})
            await c.delete(f"{db.url}/rest/v1/patients?id=eq.{test_patient['id']}", headers={"apikey": db.key, "Authorization": f"Bearer {db.key}"})
        print("Cleaned up synthetic test records from Supabase.")

    print("\n=========================================================")
    print("ALL PHASE 5 BULK REMINDER TESTS PASSED 100%!")
    print("=========================================================")

if __name__ == "__main__":
    asyncio.run(run_phase5_tests())
