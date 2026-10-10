import asyncio
import os
import sys
import httpx

sys.path.insert(0, r"C:\Users\keert\Downloads\fertility-clinic\fertility-clinic")

from main import app, ACCOUNTS
from supabase_client import db

DOC1_EMAIL = "doctor1@clinic.demo"
DOC2_EMAIL = "doctor2@clinic.demo"
RECEP_EMAIL = "reception@clinic.demo"
ADMIN_EMAIL = "admin@clinic.demo"

async def run_tests():
    transport = httpx.ASGITransport(app=app)
    base_url = "http://localhost:8000"

    print("--- [TEST 1] LOGIN DOCTOR 1 & VERIFY PATIENT SCOPING ---")
    doc1_pwd = os.getenv("DOCTOR1_PASSWORD", "DefaultSecurePassword123!")
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        # Login Doctor 1
        resp = await client.post("/api/auth/login", json={"email": DOC1_EMAIL, "password": doc1_pwd}, headers={"origin": "http://localhost:8000"})
        assert resp.status_code == 200, f"Doctor 1 login failed: {resp.text}"
        doc1_user = resp.json()
        assert doc1_user["role"] == "doctor"
        print(f"Doctor 1 logged in successfully: {doc1_user['name']} (ID: {doc1_user['id']})")

        # Get Doctor 1 Patients
        p_resp = await client.get("/api/patients")
        assert p_resp.status_code == 200
        doc1_patients = p_resp.json()
        print(f"Doctor 1 retrieved {len(doc1_patients)} patients.")
        for p in doc1_patients:
            assert str(p["doctor_id"]) == str(doc1_user["id"]), f"Data leakage! Patient {p['name']} assigned to doctor {p['doctor_id']}"
        print("[PASS] Doctor 1 patient scoping verified (0 leakage from Doctor 2)")

        # Verify Doctors endpoint for Doctor 1 returns only Doctor 1
        d_resp = await client.get("/api/doctors")
        assert d_resp.status_code == 200
        docs = d_resp.json()
        assert len(docs) == 1 and docs[0]["id"] == doc1_user["id"]
        print("[PASS] Doctor 1 doctors endpoint correctly scoped to self")

        # Remember a patient ID belonging to Doctor 1
        doc1_patient_id = doc1_patients[0]["id"]

    print("\n--- [TEST 2] LOGIN DOCTOR 2 & VERIFY STRICT ACCESS CONTROL ---")
    doc2_pwd = os.getenv("DOCTOR2_PASSWORD", "DefaultSecurePassword123!")
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        resp = await client.post("/api/auth/login", json={"email": DOC2_EMAIL, "password": doc2_pwd}, headers={"origin": "http://localhost:8000"})
        assert resp.status_code == 200
        doc2_user = resp.json()
        print(f"Doctor 2 logged in successfully: {doc2_user['name']} (ID: {doc2_user['id']})")

        # Doctor 2 attempts to directly access Doctor 1's patient by ID
        unauth_resp = await client.get(f"/api/patients/{doc1_patient_id}")
        assert unauth_resp.status_code == 404, f"Security violation! Expected 404, got {unauth_resp.status_code}"
        print(f"[PASS] Doctor 2 access to Doctor 1's patient correctly denied with 404 Not Found")

    print("\n--- [TEST 3] LOGIN RECEPTIONIST & VERIFY CLINIC-WIDE ACCESS ---")
    recep_pwd = os.getenv("RECEPTION_PASSWORD", "DefaultSecurePassword123!")
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        resp = await client.post("/api/auth/login", json={"email": RECEP_EMAIL, "password": recep_pwd}, headers={"origin": "http://localhost:8000"})
        assert resp.status_code == 200
        recep_user = resp.json()
        print(f"Receptionist logged in successfully: {recep_user['name']}")

        # Receptionist retrieves all patients
        p_resp = await client.get("/api/patients")
        assert p_resp.status_code == 200
        all_patients = p_resp.json()
        print(f"Receptionist can see all {len(all_patients)} clinic patients.")
        assert len(all_patients) >= 12
        print("[PASS] Receptionist clinic-wide patient list verified")

        # Receptionist adds a new patient with Tamil preference
        new_patient_payload = {
            "name": "TEST - Priya Devi",
            "phone": "+919876543210",
            "preferred_language": "Tamil",
            "doctor_id": doc1_user["id"],
            "treatment_stage": "Consultation",
            "whatsapp_opt_in": True
        }
        create_resp = await client.post("/api/patients", json=new_patient_payload, headers={"origin": "http://localhost:8000"})
        assert create_resp.status_code == 201, f"Create patient failed: {create_resp.text}"
        new_patient = create_resp.json()
        print(f"[PASS] Receptionist created patient '{new_patient['name']}' with language '{new_patient['preferred_language']}' and opt-in: {new_patient['whatsapp_opt_in']}")

        # Record an appointment for this new patient
        apt_resp = await client.post(
            f"/api/patients/{new_patient['id']}/appointments",
            json={"appointment_date": "2026-10-25", "status": "SCHEDULED", "note": "Initial fertility consult"},
            headers={"origin": "http://localhost:8000"}
        )
        assert apt_resp.status_code == 201, f"Add appointment failed: {apt_resp.text}"
        print("[PASS] Receptionist recorded patient appointment successfully")

    print("\n--- [TEST 4] LOGIN ADMIN & VERIFY AUDIT LOGGING ---")
    admin_pwd = os.getenv("ADMIN_PASSWORD", "DefaultSecurePassword123!")
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        resp = await client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": admin_pwd}, headers={"origin": "http://localhost:8000"})
        assert resp.status_code == 200
        admin_user = resp.json()
        print(f"Admin logged in successfully: {admin_user['name']}")

        dash_resp = await client.get("/api/dashboard")
        assert dash_resp.status_code == 200
        dash = dash_resp.json()
        print("Admin Dashboard stats:", dash["counts"])
        assert dash["counts"]["total_patients"] >= 13
        assert dash["mock_mode"] is True
        print("[PASS] Admin dashboard statistics and mock mode active")

        act_resp = await client.get("/api/activity")
        assert act_resp.status_code == 200
        activities = act_resp.json()
        print(f"Admin retrieved {len(activities)} audit records.")
        assert len(activities) >= 1
        print(f"[PASS] Audit trail verified: Latest action '{activities[0]['action']}' by '{activities[0]['actor_name']}'")

    print("\n=======================================================")
    print("ALL PHASE 4 RBAC & API TESTS COMPLETED AND PASSED 100%!")
    print("=======================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())
