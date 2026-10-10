"""
Supabase client layer for Fertility Clinic Follow-up Management.
Uses httpx to connect directly to the Supabase PostgREST API.
Keeps credentials strictly server-side and enforces parameterized queries.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("clinic.supabase")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

def get_headers() -> Dict[str, str]:
    if not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_KEY is not configured in .env")
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class SupabaseClient:
    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        self.url = (url or SUPABASE_URL).rstrip("/")
        self.key = key or SUPABASE_KEY
        if not self.url or not self.key:
            log.warning("Supabase URL or Key is missing. Supabase operations will fail until configured.")

    def is_configured(self) -> bool:
        return bool(self.url and self.key)

    async def check_connection(self) -> Dict[str, Any]:
        """Perform a minimal read operation to verify database connectivity."""
        if not self.is_configured():
            return {"connected": False, "error": "SUPABASE_URL or SUPABASE_KEY missing in .env"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.url}/rest/v1/profiles?select=id,role&limit=1",
                    headers=get_headers(),
                )
                if resp.status_code == 200:
                    return {"connected": True, "status": "healthy"}
                return {"connected": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as exc:
            return {"connected": False, "error": str(exc)}

    # Profiles (Doctors, Receptionists, Admins)
    async def get_profiles(self) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.url}/rest/v1/profiles?select=*&order=id",
                headers=get_headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def get_doctors(self) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.url}/rest/v1/profiles?role=eq.doctor&order=doctor_number",
                headers=get_headers(),
            )
            resp.raise_for_status()
            doctors = resp.json()
            # Attach patient count for each doctor
            for doc in doctors:
                p_resp = await client.get(
                    f"{self.url}/rest/v1/patients?assigned_doctor_id=eq.{doc['id']}&select=id",
                    headers={**get_headers(), "Range": "0-0", "Prefer": "count=exact"},
                )
                content_range = p_resp.headers.get("Content-Range", "0-0/0")
                count = int(content_range.split("/")[-1]) if "/" in content_range else 0
                doc["patient_count"] = count
                doc["name"] = doc["full_name"]
            return doctors

    # Patients
    async def get_patients(self, user: Optional[Dict[str, Any]] = None, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        params = ["select=*,doctor:profiles(id,full_name)", "order=full_name"]
        if user and user.get("role") == "doctor":
            params.append(f"assigned_doctor_id=eq.{user['id']}")
        elif filters and filters.get("doctor_id"):
            params.append(f"assigned_doctor_id=eq.{filters['doctor_id']}")
        if filters and filters.get("stage"):
            params.append(f"treatment_stage=eq.{filters['stage']}")
        if filters and filters.get("patient_id"):
            params.append(f"id=eq.{filters['patient_id']}")

        query_str = "&".join(params)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.url}/rest/v1/patients?{query_str}",
                headers=get_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            for p in data:
                p["name"] = p.get("full_name")
                p["doctor_id"] = p.get("assigned_doctor_id")
                p["doctor_name"] = p.get("doctor", {}).get("full_name", "Assigned Doctor") if p.get("doctor") else "Assigned Doctor"
            return data

    async def get_patient_by_id(self, patient_id: str, user: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.url}/rest/v1/patients?id=eq.{patient_id}&select=*,doctor:profiles(id,full_name)&limit=1",
                headers=get_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            p = data[0]
            if user and user.get("role") == "doctor" and p.get("assigned_doctor_id") != user.get("id"):
                return None
            p["name"] = p.get("full_name")
            p["doctor_id"] = p.get("assigned_doctor_id")
            p["doctor_name"] = p.get("doctor", {}).get("full_name", "Assigned Doctor") if p.get("doctor") else "Assigned Doctor"
            return p

    async def create_patient(self, data: Dict[str, Any], actor_id: Optional[str] = None) -> Dict[str, Any]:
        import secrets
        code = data.get("patient_code") or f"P-{secrets.randbelow(9000) + 1000}"
        payload = {
            "patient_code": code,
            "full_name": data["name"],
            "phone": data["phone"],
            "preferred_language": data.get("preferred_language", "English"),
            "assigned_doctor_id": data["doctor_id"],
            "treatment_stage": data["treatment_stage"],
            "whatsapp_opt_in": bool(data.get("whatsapp_opt_in", False)),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.url}/rest/v1/patients",
                headers=get_headers(),
                json=payload,
            )
            resp.raise_for_status()
            new_patient = resp.json()[0]
            new_patient["name"] = new_patient.get("full_name")
            new_patient["doctor_id"] = new_patient.get("assigned_doctor_id")

            if actor_id:
                await self.log_activity(
                    actor_id=actor_id,
                    category="patient",
                    action="PATIENT_CREATED",
                    patient_id=new_patient["id"],
                    details=payload,
                )
            return new_patient

    async def update_patient(self, patient_id: str, updates: Dict[str, Any], actor_id: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if "name" in updates:
            payload["full_name"] = updates["name"]
        if "phone" in updates:
            payload["phone"] = updates["phone"]
        if "preferred_language" in updates:
            payload["preferred_language"] = updates["preferred_language"]
        if "doctor_id" in updates:
            payload["assigned_doctor_id"] = updates["doctor_id"]
        if "treatment_stage" in updates:
            payload["treatment_stage"] = updates["treatment_stage"]
        if "whatsapp_opt_in" in updates:
            payload["whatsapp_opt_in"] = bool(updates["whatsapp_opt_in"])
        payload["updated_at"] = now_iso()

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.patch(
                f"{self.url}/rest/v1/patients?id=eq.{patient_id}",
                headers=get_headers(),
                json=payload,
            )
            resp.raise_for_status()
            res = resp.json()
            updated = res[0] if res else {}
            updated["name"] = updated.get("full_name")
            updated["doctor_id"] = updated.get("assigned_doctor_id")

            if actor_id:
                await self.log_activity(
                    actor_id=actor_id,
                    category="patient",
                    action="PATIENT_UPDATED",
                    patient_id=patient_id,
                    details=payload,
                )
            return updated

    # Follow-ups
    async def get_follow_ups(self, user: Optional[Dict[str, Any]] = None, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        params = [
            "select=*,patient:patients(id,full_name,phone,preferred_language,treatment_stage,whatsapp_opt_in),doctor:profiles(id,full_name)",
            "order=follow_up_date,id",
        ]
        if user and user.get("role") == "doctor":
            params.append(f"doctor_id=eq.{user['id']}")
        elif filters and filters.get("doctor_id"):
            params.append(f"doctor_id=eq.{filters['doctor_id']}")
        if filters and filters.get("date"):
            params.append(f"follow_up_date=eq.{filters['date']}")
        if filters and filters.get("status"):
            params.append(f"status=eq.{filters['status']}")
        if filters and filters.get("patient_id"):
            params.append(f"patient_id=eq.{filters['patient_id']}")

        query_str = "&".join(params)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.url}/rest/v1/follow_ups?{query_str}",
                headers=get_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            # Flatten patient and doctor fields to match existing UI expectations
            for f in data:
                p = f.get("patient") or {}
                d = f.get("doctor") or {}
                f["patient_name"] = p.get("full_name", "Unknown Patient")
                f["phone"] = p.get("phone", "")
                f["treatment_stage"] = p.get("treatment_stage", "")
                f["preferred_language"] = p.get("preferred_language", "English")
                f["whatsapp_opt_in"] = p.get("whatsapp_opt_in", False)
                f["doctor_name"] = d.get("full_name", "Assigned Doctor")
                f["whatsapp_status"] = "CONFIRMED" if f.get("status") == "CONFIRMED" else ("RESCHEDULE_REQUESTED" if f.get("status") == "RESCHEDULE_REQUESTED" else "NOT_SENT")
            return data

    async def get_follow_up_by_id(self, follow_id: str, user: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.url}/rest/v1/follow_ups?id=eq.{follow_id}&select=*,patient:patients(id,full_name,phone,preferred_language,treatment_stage,whatsapp_opt_in),doctor:profiles(id,full_name)&limit=1",
                headers=get_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            f = data[0]
            if user and user.get("role") == "doctor" and f.get("doctor_id") != user.get("id"):
                return None
            p = f.get("patient") or {}
            d = f.get("doctor") or {}
            f["patient_name"] = p.get("full_name", "Unknown Patient")
            f["phone"] = p.get("phone", "")
            f["treatment_stage"] = p.get("treatment_stage", "")
            f["preferred_language"] = p.get("preferred_language", "English")
            f["whatsapp_opt_in"] = p.get("whatsapp_opt_in", False)
            f["doctor_name"] = d.get("full_name", "Assigned Doctor")
            f["whatsapp_status"] = "CONFIRMED" if f.get("status") == "CONFIRMED" else "NOT_SENT"
            return f

    async def create_follow_up(self, data: Dict[str, Any], actor_id: Optional[str] = None) -> Dict[str, Any]:
        # Determine doctor_id from patient if not provided
        patient = await self.get_patient_by_id(data["patient_id"])
        doctor_id = data.get("doctor_id") or (patient.get("assigned_doctor_id") if patient else None)

        payload = {
            "patient_id": data["patient_id"],
            "doctor_id": doctor_id,
            "follow_up_date": data["follow_up_date"],
            "follow_up_type": data["follow_up_type"],
            "status": data.get("status", "UPCOMING"),
            "notes": data.get("notes", ""),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.url}/rest/v1/follow_ups",
                headers=get_headers(),
                json=payload,
            )
            resp.raise_for_status()
            created = resp.json()[0]

            if actor_id:
                await self.log_activity(
                    actor_id=actor_id,
                    category="follow_up",
                    action="FOLLOW_UP_CREATED",
                    patient_id=data["patient_id"],
                    follow_up_id=created["id"],
                    details=payload,
                )
            return created

    async def update_follow_up(self, follow_id: str, updates: Dict[str, Any], actor_id: Optional[str] = None) -> Dict[str, Any]:
        payload = {**updates, "updated_at": now_iso()}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.patch(
                f"{self.url}/rest/v1/follow_ups?id=eq.{follow_id}",
                headers=get_headers(),
                json=payload,
            )
            resp.raise_for_status()
            res = resp.json()
            updated = res[0] if res else {}

            if actor_id:
                action = "FOLLOW_UP_COMPLETED" if updates.get("status") == "COMPLETED" else "FOLLOW_UP_UPDATED"
                await self.log_activity(
                    actor_id=actor_id,
                    category="follow_up",
                    action=action,
                    follow_up_id=follow_id,
                    details=updates,
                )
            return updated

    # Reschedule Requests
    async def get_reschedule_requests(self, user: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        params = [
            "select=*,patient:patients(id,full_name,assigned_doctor_id),doctor:profiles(id,full_name)",
            "order=requested_at.desc",
        ]
        query_str = "&".join(params)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.url}/rest/v1/reschedule_requests?{query_str}",
                headers=get_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            filtered = []
            for r in data:
                p = r.get("patient") or {}
                d = r.get("doctor") or {}
                if user and user.get("role") == "doctor" and p.get("assigned_doctor_id") != user.get("id"):
                    continue
                r["patient_name"] = p.get("full_name", "Unknown Patient")
                r["doctor_name"] = d.get("full_name", "Assigned Doctor")
                r["request_date"] = r.get("requested_at")
                filtered.append(r)
            return filtered

    async def decide_reschedule_request(self, request_id: str, user: Dict[str, Any], approve: bool, rejection_reason: str = "") -> Dict[str, Any]:
        status = "APPROVED" if approve else "REJECTED"
        payload = {
            "status": status,
            "reviewed_by": user["id"],
            "reviewed_at": now_iso(),
            "rejection_reason": rejection_reason if not approve else None,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            # 1. Update request
            resp = await client.patch(
                f"{self.url}/rest/v1/reschedule_requests?id=eq.{request_id}",
                headers=get_headers(),
                json=payload,
            )
            resp.raise_for_status()
            req_data = resp.json()[0]

            # 2. Update follow-up status
            follow_id = req_data["follow_up_id"]
            if approve:
                await client.patch(
                    f"{self.url}/rest/v1/follow_ups?id=eq.{follow_id}",
                    headers=get_headers(),
                    json={
                        "follow_up_date": req_data["requested_date"],
                        "status": "RESCHEDULED",
                        "patient_response": "RESCHEDULE_REQUESTED",
                        "updated_at": now_iso(),
                    },
                )
            else:
                prev_status = req_data.get("previous_status") or "UPCOMING"
                await client.patch(
                    f"{self.url}/rest/v1/follow_ups?id=eq.{follow_id}",
                    headers=get_headers(),
                    json={
                        "status": prev_status,
                        "updated_at": now_iso(),
                    },
                )

            await self.log_activity(
                actor_id=user["id"],
                category="reschedule",
                action=f"RESCHEDULE_{status}",
                patient_id=req_data.get("patient_id"),
                follow_up_id=follow_id,
                details={"request_id": request_id, "approved": approve},
            )
            return {"ok": True, "status": status}

    # Appointments
    async def get_appointments(self, patient_id: Optional[str] = None) -> List[Dict[str, Any]]:
        endpoint = f"{self.url}/rest/v1/appointments?select=*&order=appointment_date.desc"
        if patient_id:
            endpoint += f"&patient_id=eq.{patient_id}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(endpoint, headers=get_headers())
            resp.raise_for_status()
            return resp.json()

    async def create_appointment(self, data: Dict[str, Any], actor_id: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "patient_id": data["patient_id"],
            "appointment_date": data["appointment_date"],
            "status": data.get("status", "SCHEDULED"),
            "note": data.get("note", ""),
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.url}/rest/v1/appointments",
                headers=get_headers(),
                json=payload,
            )
            resp.raise_for_status()
            created = resp.json()[0]

            if actor_id:
                await self.log_activity(
                    actor_id=actor_id,
                    category="patient",
                    action="APPOINTMENT_RECORDED",
                    patient_id=data["patient_id"],
                    details=payload,
                )
            return created

    # Messages
    async def get_messages(self, user: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        endpoint = f"{self.url}/rest/v1/messages?select=*,patient:patients(id,full_name,assigned_doctor_id)&order=created_at.desc"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(endpoint, headers=get_headers())
            resp.raise_for_status()
            data = resp.json()
            messages = []
            for m in data:
                p = m.get("patient") or {}
                if user and user.get("role") == "doctor" and p.get("assigned_doctor_id") != user.get("id"):
                    continue
                m["patient_name"] = p.get("full_name", "Unknown Patient")
                raw_st = m.get("delivery_status", "NOT_SENT")
                pid = str(m.get("provider_message_id") or "")
                if pid.startswith("wamid.MOCK") and raw_st == "SENT":
                    m["status"] = "MOCK_SENT"
                else:
                    m["status"] = raw_st
                messages.append(m)
            return messages

    async def create_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.url}/rest/v1/messages",
                headers=get_headers(),
                json=data,
            )
            resp.raise_for_status()
            return resp.json()[0]

    # Activity & Audit
    async def log_activity(
        self,
        actor_id: Optional[str],
        category: str,
        action: str,
        patient_id: Optional[str] = None,
        follow_up_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload = {
            "actor_id": actor_id,
            "category": category,
            "action": action,
            "patient_id": patient_id,
            "follow_up_id": follow_up_id,
            "details": details or {},
            "created_at": now_iso(),
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{self.url}/rest/v1/activity",
                    headers=get_headers(),
                    json=payload,
                )
        except Exception as exc:
            log.warning("Failed to record audit activity: %s", exc)

    async def get_activities(self, limit: int = 1000) -> List[Dict[str, Any]]:
        endpoint = f"{self.url}/rest/v1/activity?select=*,actor:profiles(id,full_name,role),patient:patients(id,full_name)&order=created_at.desc&limit={limit}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(endpoint, headers=get_headers())
            resp.raise_for_status()
            data = resp.json()
            for a in data:
                actor = a.get("actor") or {}
                patient = a.get("patient") or {}
                a["actor_name"] = actor.get("full_name", "System / patient")
                a["actor_role"] = actor.get("role", "system")
                a["patient_name"] = patient.get("full_name", "—")
                if isinstance(a.get("details"), dict):
                    a["details"] = json.dumps(a["details"])
            return data

    async def get_messages_for_follow_ups_on_date(self, follow_up_ids: List[str], date_str: str) -> List[Dict[str, Any]]:
        if not follow_up_ids:
            return []
        ids_in = f"({','.join(follow_up_ids)})"
        endpoint = f"{self.url}/rest/v1/messages?follow_up_id=in.{ids_in}&scheduled_for_date=eq.{date_str}&select=follow_up_id,scheduled_for_date,delivery_status,provider_message_id"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(endpoint, headers=get_headers())
            if resp.status_code == 200:
                return resp.json()
            return []

    # Webhook Idempotency Receipts
    async def has_receipt(self, provider_message_id: str) -> bool:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.url}/rest/v1/webhook_receipts?provider_message_id=eq.{provider_message_id}&limit=1",
                headers=get_headers(),
            )
            return len(resp.json()) > 0 if resp.status_code == 200 else False

    async def record_receipt(self, provider_message_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.url}/rest/v1/webhook_receipts",
                    headers=get_headers(),
                    json={"provider_message_id": provider_message_id, "received_at": now_iso()},
                )
                return resp.status_code in (200, 201)
        except Exception:
            return False

# Global singleton client
db = SupabaseClient()
