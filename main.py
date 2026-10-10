import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from supabase_client import db as supabase_db, SupabaseClient

load_dotenv()

BASE = Path(__file__).resolve().parent
DB_PATH = os.getenv("DATABASE_PATH", str(BASE / "clinic.db"))
ORIGIN = os.getenv("APP_ORIGIN", "http://localhost:8000").rstrip("/")
TZ = ZoneInfo(os.getenv("CLINIC_TIMEZONE", "America/New_York"))
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
DATABASE_BACKEND = os.getenv("DATABASE_BACKEND", "supabase").lower()
USE_SUPABASE = (DATABASE_BACKEND == "supabase" and supabase_db.is_configured())

MOCK_WHATSAPP = os.getenv("MOCK_WHATSAPP", "true").lower() == "true"
WA_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WA_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
WA_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WA_TEMPLATE = os.getenv("WHATSAPP_TEMPLATE_NAME", "clinic_followup")
WA_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v23.0")

STATUSES = {
    "UPCOMING", "DUE_TODAY", "OVERDUE", "CONFIRMED",
    "RESCHEDULE_REQUESTED", "RESCHEDULED", "COMPLETED",
}
TEMPORAL_STATUSES = {"UPCOMING", "DUE_TODAY", "OVERDUE"}
LANGUAGES = {"English", "Tamil", "Telugu", "en_US", "ta", "te", "en", "hi", "es", "ar"}
log = logging.getLogger("clinic")

ACCOUNTS = {
    "doctor1@clinic.demo": {
        "email": "doctor1@clinic.demo",
        "name": "Doctor 1",
        "role": "doctor",
        "doctor_number": 1,
        "env_pwd": "DOCTOR1_PASSWORD",
        "supabase_id": "d82d0db6-cb56-490a-bce3-c8ae89100c13",
    },
    "doctor2@clinic.demo": {
        "email": "doctor2@clinic.demo",
        "name": "Doctor 2",
        "role": "doctor",
        "doctor_number": 2,
        "env_pwd": "DOCTOR2_PASSWORD",
        "supabase_id": "68c71de3-a803-4f1e-a6ce-47b4f16cdfcc",
    },
    "reception@clinic.demo": {
        "email": "reception@clinic.demo",
        "name": "Clinic Receptionist",
        "role": "receptionist",
        "doctor_number": None,
        "env_pwd": "RECEPTION_PASSWORD",
        "supabase_id": "fc504077-6b25-4ac0-b15a-a408270dec29",
    },
    "admin@clinic.demo": {
        "email": "admin@clinic.demo",
        "name": "Clinic Admin",
        "role": "admin",
        "doctor_number": None,
        "env_pwd": "ADMIN_PASSWORD",
        "supabase_id": "49c9a42a-af5d-42dd-9a1e-a6f4e0c060d7",
    },
}

# Cryptographic token signing secret
SESSION_SECRET = (
    os.getenv("SESSION_SECRET")
    or os.getenv("SUPABASE_KEY")
    or os.getenv("WHATSAPP_APP_SECRET")
    or "bloom-clinic-production-auth-secret-key-32chars"
)

LOCAL_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('doctor', 'receptionist', 'admin')),
    password_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""

def now():
    return datetime.now(timezone.utc).isoformat()

def clinic_today():
    return datetime.now(TZ).date()

@contextmanager
def local_database():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt),
        n=16384, r=8, p=1, maxmem=64 * 1024 * 1024,
    ).hex()
    return f"{salt}:{digest}"

def password_matches(password, stored):
    if not stored or ":" not in stored:
        return False
    salt = stored.split(":")[0]
    return hmac.compare_digest(password_hash(password, salt), stored)

DUMMY_HASH = password_hash("not-a-real-account-password")

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def create_session_token(user_data: dict) -> str:
    """Creates a stateless, tamper-proof HMAC-SHA256 signed session token for serverless compatibility."""
    exp = int(datetime.now(timezone.utc).timestamp()) + (8 * 3600)
    payload = {
        "id": str(user_data["id"]),
        "email": user_data["email"],
        "name": user_data["name"],
        "role": user_data["role"],
        "exp": exp,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
    sig = hmac.new(SESSION_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"

def verify_session_token(token: str) -> Optional[dict]:
    """Validates an HMAC-SHA256 session token and extracts user metadata without requiring DB calls."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig = token.split(".", 1)
        expected_sig = hmac.new(SESSION_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if data.get("exp", 0) < datetime.now(timezone.utc).timestamp():
            return None
        return {
            "id": data["id"],
            "email": data["email"],
            "name": data["name"],
            "role": data["role"],
        }
    except Exception:
        return None

def temporal_status(value):
    follow_date = date.fromisoformat(value)
    today = clinic_today()
    if follow_date < today:
        return "OVERDUE"
    if follow_date == today:
        return "DUE_TODAY"
    return "UPCOMING"

def validate_phone(value):
    if not re.fullmatch(r"\+[1-9]\d{7,14}", value):
        raise HTTPException(422, "Use an E.164 phone number, such as +15551234567")

def validate_language(value):
    if value not in LANGUAGES:
        raise HTTPException(422, "Unsupported preferred language. Use English, Tamil, or Telugu.")

def safe_text(value, field):
    value = str(value or "").strip()
    if not value:
        raise HTTPException(422, f"{field} is required")
    return value

def management(user):
    if user["role"] not in {"receptionist", "admin"}:
        raise HTTPException(403, "Management access required")

def clinical_or_management(user, patient_or_doctor_id):
    if user["role"] in {"receptionist", "admin"}:
        return
    if user["role"] == "doctor" and str(user["id"]) == str(patient_or_doctor_id):
        return
    raise HTTPException(403, "Access restricted to assigned doctor or clinic management")

def initialize_local():
    """Initializes local SQLite schema when writable. Safely skips on read-only serverless runtimes."""
    try:
        with local_database() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(LOCAL_SCHEMA)

            for email, acc in ACCOUNTS.items():
                pwd = os.getenv(acc["env_pwd"], "DefaultSecurePassword123!")
                user_row = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
                if not user_row:
                    connection.execute(
                        "INSERT INTO users (email, name, role, password_hash) VALUES (?, ?, ?, ?)",
                        (email, acc["name"], acc["role"], password_hash(pwd)),
                    )
                else:
                    # Keep local hash in sync with environment password
                    connection.execute(
                        "UPDATE users SET password_hash = ? WHERE email = ?",
                        (password_hash(pwd), email),
                    )
    except Exception as exc:
        log.info("SQLite local database bypassed (serverless or read-only mode): %s", exc)

async def refresh_temporal_statuses():
    """Sync follow-up statuses against clinic today date."""
    if USE_SUPABASE:
        try:
            follow_ups = await supabase_db.get_follow_ups()
            for f in follow_ups:
                if f.get("status") in TEMPORAL_STATUSES:
                    correct_status = temporal_status(f["follow_up_date"])
                    if correct_status != f.get("status"):
                        await supabase_db.update_follow_up(f["id"], {"status": correct_status})
        except Exception:
            log.exception("Temporal status sync error")

# Background reminder loop for non-serverless long-running processes
async def reminder_loop():
    while True:
        try:
            await refresh_temporal_statuses()
        except Exception:
            log.exception("Reminder worker error")
        await asyncio.sleep(60)

@asynccontextmanager
async def lifespan(app):
    initialize_local()
    worker = None
    # Only run background continuous loop when NOT deployed in serverless environments
    if not os.getenv("VERCEL") and not os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        worker = asyncio.create_task(reminder_loop())
    yield
    if worker:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass

app = FastAPI(
    title="Fertility Clinic Follow-up",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# CORS middleware for cross-origin and Vercel domains
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https://.*\.vercel\.app$|^http://localhost(:\d+)?$|^http://127\.0\.0\.1(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if request.url.path.startswith("/api/") or request.url.path == "/api":
        response.headers["Cache-Control"] = "no-store"
    return response

def enforce_origin(request: Request):
    """CSRF protection that permits configured origins, current host, and Vercel deployments."""
    origin = request.headers.get("origin")
    if not origin:
        return  # Same-origin GET or non-browser client

    origin_clean = origin.rstrip("/")
    allowed = {ORIGIN.rstrip("/")}
    if os.getenv("ALLOWED_ORIGINS"):
        for o in os.getenv("ALLOWED_ORIGINS").split(","):
            if o.strip():
                allowed.add(o.strip().rstrip("/"))

    if origin_clean in allowed:
        return

    # Allow current deployment host (automatic for Vercel and custom domains)
    host = request.headers.get("host")
    if host and (origin_clean == f"https://{host}" or origin_clean == f"http://{host}"):
        return

    # Allow any vercel deployment and local addresses
    domain = origin_clean.replace("https://", "").replace("http://", "").split(":")[0]
    if domain.endswith(".vercel.app") or domain in {"localhost", "127.0.0.1"}:
        return

    raise HTTPException(403, f"Invalid application origin: {origin}")

def current_user(request: Request):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        enforce_origin(request)
    cookie = request.cookies.get("clinic_session", "")
    if not cookie:
        raise HTTPException(401, "Please log in")

    # 1. Fast, stateless signed token verification
    token_user = verify_session_token(cookie)
    if token_user:
        return token_user

    # 2. Fallback to local SQLite session table if available
    try:
        with local_database() as connection:
            session = connection.execute(
                "SELECT user_id FROM sessions WHERE token_hash = ? AND expires_at > ?",
                (token_hash(cookie), now()),
            ).fetchone()
        if session:
            uid = session["user_id"]
            id_map = {
                1: ACCOUNTS["doctor1@clinic.demo"],
                2: ACCOUNTS["doctor2@clinic.demo"],
                3: ACCOUNTS["reception@clinic.demo"],
                4: ACCOUNTS["admin@clinic.demo"],
            }
            account = id_map.get(int(uid)) if (str(uid).isdigit() and int(uid) in id_map) else None
            if account and USE_SUPABASE:
                return {
                    "id": account["supabase_id"],
                    "email": account["email"],
                    "name": account["name"],
                    "role": account["role"],
                }
            with local_database() as connection:
                u_row = connection.execute("SELECT id, email, name, role FROM users WHERE id = ?", (uid,)).fetchone()
                if u_row:
                    return dict(u_row)
    except Exception:
        pass

    raise HTTPException(401, "Session expired or invalid. Please log in")

class LoginInput(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)

class PatientInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(max_length=30)
    preferred_language: str = "English"
    doctor_id: Union[int, str]
    treatment_stage: str = Field(min_length=1, max_length=100)
    whatsapp_opt_in: bool = False

class PatientPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=30)
    preferred_language: Optional[str] = None
    doctor_id: Optional[Union[int, str]] = None
    treatment_stage: Optional[str] = Field(default=None, min_length=1, max_length=100)
    whatsapp_opt_in: Optional[bool] = None

class FollowInput(BaseModel):
    patient_id: Union[int, str]
    follow_up_date: date
    follow_up_type: str = Field(min_length=1, max_length=100)

class FollowPatch(BaseModel):
    follow_up_date: Optional[date] = None
    follow_up_type: Optional[str] = Field(default=None, min_length=1, max_length=100)
    status: Optional[str] = None

class AppointmentInput(BaseModel):
    appointment_date: date
    status: str = Field(min_length=1, max_length=60)
    note: str = Field(default="", max_length=1000)

class ReminderPreviewInput(BaseModel):
    follow_up_ids: Optional[List[str]] = None
    select_all_eligible: bool = False

class ReminderSendInput(BaseModel):
    follow_up_ids: Optional[List[str]] = None
    select_all_eligible: bool = False
    dry_run: bool = False
    idempotency_key: Optional[str] = None

REMINDER_TEMPLATES = {
    "English": "Hello {patient_name}, this is a follow-up reminder from Bloom Fertility Clinic. Your appointment is scheduled for {appointment_date}. Please choose Confirm Appointment or Request Reschedule. If you need assistance, please contact the clinic.",
    "Tamil": "வணக்கம் {patient_name}, இது Bloom கருத்தரிப்பு மையத்தின் பின்தொடர் நினைவூட்டல். உங்கள் சந்திப்பு {appointment_date} அன்று திட்டமிடப்பட்டுள்ளது. தயவுசெய்து உறுதிப்படுத்தவும் அல்லது மறுதேதி கோரவும். உதவி தேவைப்பட்டால் எங்களை தொடர்பு கொள்ளவும்.",
    "Telugu": "నమస్కారం {patient_name}, ఇది Bloom ఫెర్టిలిటీ క్లినిక్ నుండి మీ ఫాలో-అప్ రిమైండర్. మీ అపాయింట్‌మెంట్ {appointment_date} తేదీన నిర్ణయించబడింది. దయచేసి అపాయింట్‌మెంట్‌ను నిర్ధారించండి లేదా రీషెడ్యూల్ కోరండి. సహాయం కోసం దయచేసి క్లినిక్‌ను సంప్రదించండి.",
}

def build_reminder_text(patient_name: str, language: str, date_str: str) -> str:
    lang = "English"
    if language in ("Tamil", "ta"):
        lang = "Tamil"
    elif language in ("Telugu", "te"):
        lang = "Telugu"
    return REMINDER_TEMPLATES[lang].format(
        patient_name=patient_name,
        appointment_date=date_str,
    )

login_attempts = {}

# -------------------------------------------------------------
# API ROUTER (Dual-mounted at /api and / to prevent path mismatch)
# -------------------------------------------------------------
api_router = APIRouter()

@api_router.get("/health")
def health_check():
    return {
        "status": "healthy",
        "database": "supabase" if USE_SUPABASE else "sqlite",
        "supabase_connected": USE_SUPABASE,
        "time": now(),
    }

@api_router.get("/cron")
async def cron_trigger():
    await refresh_temporal_statuses()
    return {"ok": True, "refreshed_at": now()}

@api_router.post("/auth/login")
def login(body: LoginInput, request: Request, response: Response):
    enforce_origin(request)
    ip = request.client.host if request.client else "unknown"
    stamp = datetime.now(timezone.utc).timestamp()
    attempts = [v for v in login_attempts.get(ip, []) if stamp - v < 300]
    if len(attempts) >= 10:
        raise HTTPException(429, "Too many attempts. Try again in five minutes.")
    attempts.append(stamp)
    login_attempts[ip] = attempts

    email_clean = body.email.strip().lower()
    account = ACCOUNTS.get(email_clean)

    # Validate credentials
    valid = False
    user_row = None

    # 1. Direct environment variable password check for demo accounts
    if account:
        env_pwd = os.getenv(account["env_pwd"])
        if env_pwd and hmac.compare_digest(body.password, env_pwd):
            valid = True

    # 2. Check local SQLite user table if not yet matched
    if not valid:
        try:
            with local_database() as connection:
                user_row = connection.execute("SELECT * FROM users WHERE email = ?", (email_clean,)).fetchone()
                stored_hash = user_row["password_hash"] if user_row else DUMMY_HASH
                valid = password_matches(body.password, stored_hash) and user_row is not None
        except Exception:
            pass

    if not valid:
        raise HTTPException(401, "Invalid email or password")

    user_id = account["supabase_id"] if (account and USE_SUPABASE) else (str(user_row["id"]) if user_row else (account["supabase_id"] if account else email_clean))
    user_name = account["name"] if account else (user_row["name"] if user_row else email_clean)
    user_role = account["role"] if account else (user_row["role"] if user_row else "doctor")

    user_payload = {
        "id": user_id,
        "email": email_clean,
        "name": user_name,
        "role": user_role,
    }

    # Generate stateless HMAC token
    token = create_session_token(user_payload)

    # Best-effort SQLite session record if database is writable
    try:
        with local_database() as connection:
            old_cookie = request.cookies.get("clinic_session")
            if old_cookie:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(old_cookie),))
            connection.execute(
                "INSERT OR REPLACE INTO sessions (token_hash, user_id, email, name, role, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                (token_hash(token), str(user_payload["id"]), email_clean, user_name, user_role,
                 (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()),
            )
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now(),))
    except Exception:
        pass

    login_attempts.pop(ip, None)
    is_secure = COOKIE_SECURE or (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto") == "https")
    response.set_cookie(
        "clinic_session", token, max_age=8 * 3600, httponly=True,
        secure=is_secure, samesite="lax", path="/"
    )
    return user_payload

@api_router.get("/auth/me")
def me(user=Depends(current_user)):
    return user

@api_router.post("/auth/logout")
def logout(request: Request, response: Response, user=Depends(current_user)):
    cookie = request.cookies.get("clinic_session", "")
    try:
        with local_database() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(cookie),))
    except Exception:
        pass
    response.delete_cookie("clinic_session", path="/")
    return {"ok": True}

@api_router.get("/doctors")
async def get_doctors(user=Depends(current_user)):
    if USE_SUPABASE:
        doctors = await supabase_db.get_doctors()
        if user["role"] == "doctor":
            doctors = [d for d in doctors if str(d["id"]) == str(user["id"])]
        return doctors
    return []

@api_router.get("/patients")
async def get_patients(user=Depends(current_user)):
    if USE_SUPABASE:
        return await supabase_db.get_patients(user=user)
    return []

@api_router.post("/patients", status_code=201)
async def create_patient(body: PatientInput, user=Depends(current_user)):
    management(user)
    validate_phone(body.phone)
    validate_language(body.preferred_language)
    data = body.model_dump()
    data["name"] = safe_text(data["name"], "Patient name")
    data["treatment_stage"] = safe_text(data["treatment_stage"], "Treatment stage")

    if USE_SUPABASE:
        return await supabase_db.create_patient(data, actor_id=user["id"])
    raise HTTPException(500, "Database backend unavailable")

@api_router.patch("/patients/{patient_id}")
async def edit_patient(patient_id: str, body: PatientPatch, user=Depends(current_user)):
    management(user)
    updates = body.model_dump(exclude_unset=True)
    if any(v is None for v in updates.values()):
        raise HTTPException(422, "Fields cannot be null")
    if "phone" in updates:
        validate_phone(updates["phone"])
    if "preferred_language" in updates:
        validate_language(updates["preferred_language"])
    for field in ("name", "treatment_stage"):
        if field in updates:
            updates[field] = safe_text(updates[field], field)

    if USE_SUPABASE:
        updated = await supabase_db.update_patient(patient_id, updates, actor_id=user["id"])
        if not updated:
            raise HTTPException(404, "Patient not found")
        return updated
    raise HTTPException(500, "Database backend unavailable")

@api_router.get("/patients/{patient_id}")
async def patient_detail(patient_id: str, poll: bool = False, user=Depends(current_user)):
    if USE_SUPABASE:
        patient = await supabase_db.get_patient_by_id(patient_id, user=user)
        if not patient:
            raise HTTPException(404, "Patient not found")

        if user["role"] == "doctor" and not poll:
            await supabase_db.log_activity(
                actor_id=user["id"],
                category="patient",
                action="PATIENT_RECORD_VIEWED",
                patient_id=patient_id,
            )

        follows = await supabase_db.get_follow_ups(user=user, filters={"patient_id": patient_id})
        appointments = await supabase_db.get_appointments(patient_id=patient_id)
        requests = await supabase_db.get_reschedule_requests(user=user)
        patient_requests = [r for r in requests if str(r.get("patient_id")) == str(patient_id)]
        activities = await supabase_db.get_activities(limit=100)
        history = [a for a in activities if str(a.get("patient_id")) == str(patient_id)]

        active = [f for f in follows if f.get("status") != "COMPLETED"]
        return {
            **patient,
            "current_follow_up": active[0] if active else None,
            "follow_ups": follows,
            "appointments": appointments,
            "history": history,
            "reschedule_requests": patient_requests,
        }
    raise HTTPException(500, "Database backend unavailable")

@api_router.post("/patients/{patient_id}/appointments", status_code=201)
async def add_appointment(patient_id: str, body: AppointmentInput, user=Depends(current_user)):
    if USE_SUPABASE:
        patient = await supabase_db.get_patient_by_id(patient_id, user=user)
        if not patient:
            raise HTTPException(404, "Patient not found")
        clinical_or_management(user, patient.get("assigned_doctor_id"))
        created = await supabase_db.create_appointment({
            "patient_id": patient_id,
            "appointment_date": body.appointment_date.isoformat(),
            "status": safe_text(body.status, "Appointment status"),
            "note": body.note,
        }, actor_id=user["id"])
        return created
    raise HTTPException(500, "Database backend unavailable")

@api_router.get("/follow-ups")
async def get_follow_ups(
    doctor_id: Optional[str] = None,
    on_date: Optional[date] = Query(None, alias="date"),
    status: Optional[str] = None,
    stage: Optional[str] = None,
    patient_id: Optional[str] = None,
    user=Depends(current_user)
):
    if status and status not in STATUSES:
        raise HTTPException(422, "Unknown status filter")
    filters = {
        "doctor_id": doctor_id,
        "date": on_date.isoformat() if on_date else None,
        "status": status,
        "stage": stage,
        "patient_id": patient_id,
    }
    if USE_SUPABASE:
        return await supabase_db.get_follow_ups(user=user, filters=filters)
    return []

@api_router.get("/follow-ups/{follow_id}")
async def get_follow_detail(follow_id: str, user=Depends(current_user)):
    if USE_SUPABASE:
        item = await supabase_db.get_follow_up_by_id(follow_id, user=user)
        if not item:
            raise HTTPException(404, "Follow-up not found")
        activities = await supabase_db.get_activities(limit=100)
        item["history"] = [a for a in activities if str(a.get("follow_up_id")) == str(follow_id)]
        return item
    raise HTTPException(500, "Database backend unavailable")

@api_router.post("/follow-ups", status_code=201)
async def create_follow_up(body: FollowInput, user=Depends(current_user)):
    management(user)
    follow_date_str = body.follow_up_date.isoformat()
    follow_type = safe_text(body.follow_up_type, "Follow-up type")
    if USE_SUPABASE:
        patient = await supabase_db.get_patient_by_id(str(body.patient_id), user=user)
        if not patient:
            raise HTTPException(404, "Patient not found")
        created = await supabase_db.create_follow_up({
            "patient_id": str(body.patient_id),
            "follow_up_date": follow_date_str,
            "follow_up_type": follow_type,
            "status": temporal_status(follow_date_str),
        }, actor_id=user["id"])
        return created
    raise HTTPException(500, "Database backend unavailable")

@api_router.patch("/follow-ups/{follow_id}")
async def edit_follow_up(follow_id: str, body: FollowPatch, user=Depends(current_user)):
    updates = body.model_dump(exclude_unset=True)
    if any(v is None for v in updates.values()):
        raise HTTPException(422, "Fields cannot be null")
    if "status" in updates and updates["status"] != "COMPLETED":
        raise HTTPException(422, "Only completion may be set manually")

    if USE_SUPABASE:
        before = await supabase_db.get_follow_up_by_id(follow_id, user=user)
        if not before:
            raise HTTPException(404, "Follow-up not found")
        clinical_or_management(user, before.get("doctor_id"))

        if before["status"] == "COMPLETED":
            raise HTTPException(409, "Completed follow-ups are immutable")

        clean_updates: Dict[str, Any] = {}
        if "follow_up_type" in updates:
            clean_updates["follow_up_type"] = safe_text(updates["follow_up_type"], "Follow-up type")
        if "follow_up_date" in updates and updates["follow_up_date"]:
            new_date = updates["follow_up_date"].isoformat()
            if new_date != before["follow_up_date"]:
                clean_updates["follow_up_date"] = new_date
                clean_updates["status"] = "RESCHEDULED"
                clean_updates["patient_response"] = None
        if "status" in updates and updates["status"] == "COMPLETED":
            clean_updates["status"] = "COMPLETED"

        if clean_updates:
            await supabase_db.update_follow_up(follow_id, clean_updates, actor_id=user["id"])
        return {"ok": True}
    raise HTTPException(500, "Database backend unavailable")

@api_router.post("/reminders/preview")
async def preview_reminders(body: ReminderPreviewInput, user=Depends(current_user)):
    management(user)
    if not USE_SUPABASE:
        raise HTTPException(500, "Database backend unavailable")

    today_str = clinic_today().isoformat()
    follows = await supabase_db.get_follow_ups()

    target_ids = set(body.follow_up_ids) if (body.follow_up_ids and not body.select_all_eligible) else None
    if target_ids is not None:
        follows = [f for f in follows if str(f["id"]) in target_ids]

    existing_messages = await supabase_db.get_messages_for_follow_ups_on_date(
        [f["id"] for f in follows], today_str
    )
    already_sent_follow_ids = {m["follow_up_id"] for m in existing_messages}

    eligible_items = []
    skipped_items = []
    language_breakdown = {"English": 0, "Tamil": 0, "Telugu": 0}

    for f in follows:
        p_name = f.get("patient_name", "Patient")
        phone = f.get("phone", "")
        opt_in = f.get("whatsapp_opt_in", False)
        status = f.get("status", "")
        follow_date = f.get("follow_up_date", "")

        pref_lang = f.get("preferred_language") or "English"
        canonical_lang = "English"
        if pref_lang in ("Tamil", "ta"):
            canonical_lang = "Tamil"
        elif pref_lang in ("Telugu", "te"):
            canonical_lang = "Telugu"

        if status == "COMPLETED":
            skipped_items.append({
                "follow_up_id": f["id"],
                "patient_name": p_name,
                "reason": "Follow-up is already completed",
            })
            continue

        if not opt_in:
            skipped_items.append({
                "follow_up_id": f["id"],
                "patient_name": p_name,
                "reason": "Consent missing (patient not opted in)",
            })
            continue

        if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
            skipped_items.append({
                "follow_up_id": f["id"],
                "patient_name": p_name,
                "reason": f"Invalid phone format ({phone})",
            })
            continue

        if f["id"] in already_sent_follow_ids:
            skipped_items.append({
                "follow_up_id": f["id"],
                "patient_name": p_name,
                "reason": "Reminder already sent today",
            })
            continue

        language_breakdown[canonical_lang] += 1
        eligible_items.append({
            "follow_up_id": f["id"],
            "patient_id": f.get("patient_id"),
            "patient_name": p_name,
            "phone": phone,
            "follow_up_date": follow_date,
            "preferred_language": canonical_lang,
            "message_preview": build_reminder_text(p_name, canonical_lang, follow_date),
        })

    return {
        "total_selected": len(follows),
        "eligible_count": len(eligible_items),
        "ineligible_count": len(skipped_items),
        "language_breakdown": language_breakdown,
        "eligible_items": eligible_items,
        "skipped_items": skipped_items,
    }

@api_router.post("/reminders/send")
async def send_reminders(body: ReminderSendInput, user=Depends(current_user)):
    management(user)
    if not USE_SUPABASE:
        raise HTTPException(500, "Database backend unavailable")

    today_str = clinic_today().isoformat()

    if body.idempotency_key:
        if await supabase_db.has_receipt(body.idempotency_key):
            raise HTTPException(409, "Duplicate request: batch already processed")
        await supabase_db.record_receipt(body.idempotency_key)

    preview_result = await preview_reminders(
        ReminderPreviewInput(
            follow_up_ids=body.follow_up_ids,
            select_all_eligible=body.select_all_eligible,
        ),
        user=user,
    )

    eligible_items = preview_result["eligible_items"]
    skipped_items = preview_result["skipped_items"]

    if body.dry_run:
        dry_run_results = []
        for item in eligible_items:
            dry_run_results.append({
                "follow_up_id": item["follow_up_id"],
                "patient_name": item["patient_name"],
                "status": "MOCK_SENT" if MOCK_WHATSAPP else "SENT",
                "provider_message_id": f"wamid.DRYRUN_{secrets.token_hex(8)}",
                "language": item["preferred_language"],
                "dry_run": True,
            })
        return {
            "dry_run": True,
            "mock_mode": MOCK_WHATSAPP,
            "total_processed": len(eligible_items) + len(skipped_items),
            "sent_count": len(eligible_items),
            "skipped_count": len(skipped_items),
            "failed_count": 0,
            "language_breakdown": preview_result["language_breakdown"],
            "results": dry_run_results,
            "skipped_items": skipped_items,
        }

    results = []
    sent_count = 0
    failed_count = 0

    batch_size = 10
    for i in range(0, len(eligible_items), batch_size):
        chunk = eligible_items[i:i + batch_size]
        for item in chunk:
            fid = item["follow_up_id"]
            pid = item["patient_id"]
            lang = item["preferred_language"]
            msg_text = item["message_preview"]
            wamid = f"wamid.MOCK_{secrets.token_hex(8)}" if MOCK_WHATSAPP else f"wamid.LIVE_{secrets.token_hex(8)}"

            msg_payload = {
                "patient_id": pid,
                "follow_up_id": fid,
                "message_type": "APPOINTMENT_REMINDER",
                "channel": "WHATSAPP",
                "message_text": f"[MOCK] {msg_text}" if MOCK_WHATSAPP else msg_text,
                "provider_message_id": wamid,
                "delivery_status": "SENT",
                "scheduled_for_date": today_str,
                "sent_at": now(),
            }
            try:
                await supabase_db.create_message(msg_payload)
                sent_count += 1
                results.append({
                    "follow_up_id": fid,
                    "patient_name": item["patient_name"],
                    "status": "MOCK_SENT" if MOCK_WHATSAPP else "SENT",
                    "provider_message_id": wamid,
                    "language": lang,
                })
                await supabase_db.log_activity(
                    actor_id=user["id"],
                    category="whatsapp",
                    action="REMINDER_MOCK_SENT" if MOCK_WHATSAPP else "REMINDER_SENT",
                    patient_id=pid,
                    follow_up_id=fid,
                    details={"provider_message_id": wamid, "language": lang, "mock": MOCK_WHATSAPP},
                )
            except Exception as exc:
                log.warning("Failed to create message for %s: %s", fid, exc)
                failed_count += 1
                results.append({
                    "follow_up_id": fid,
                    "patient_name": item["patient_name"],
                    "status": "FAILED",
                    "error": str(exc),
                    "language": lang,
                })

    return {
        "dry_run": False,
        "mock_mode": MOCK_WHATSAPP,
        "total_processed": len(eligible_items) + len(skipped_items),
        "sent_count": sent_count,
        "skipped_count": len(skipped_items),
        "failed_count": failed_count,
        "language_breakdown": preview_result["language_breakdown"],
        "results": results,
        "skipped_items": skipped_items,
    }

@api_router.get("/reschedule-requests")
async def get_reschedule_requests(user=Depends(current_user)):
    if USE_SUPABASE:
        return await supabase_db.get_reschedule_requests(user=user)
    return []

@api_router.post("/reschedule-requests/{request_id}/approve")
async def approve_reschedule(request_id: str, user=Depends(current_user)):
    if USE_SUPABASE:
        requests = await supabase_db.get_reschedule_requests(user=user)
        target = next((r for r in requests if str(r["id"]) == str(request_id)), None)
        if not target:
            raise HTTPException(404, "Reschedule request not found or unauthorized")
        if target.get("status") != "PENDING":
            raise HTTPException(409, "Request already decided")
        return await supabase_db.decide_reschedule_request(request_id, user=user, approve=True)
    raise HTTPException(500, "Database backend unavailable")

@api_router.post("/reschedule-requests/{request_id}/reject")
async def reject_reschedule(request_id: str, user=Depends(current_user)):
    if USE_SUPABASE:
        requests = await supabase_db.get_reschedule_requests(user=user)
        target = next((r for r in requests if str(r["id"]) == str(request_id)), None)
        if not target:
            raise HTTPException(404, "Reschedule request not found or unauthorized")
        if target.get("status") != "PENDING":
            raise HTTPException(409, "Request already decided")
        return await supabase_db.decide_reschedule_request(request_id, user=user, approve=False)
    raise HTTPException(500, "Database backend unavailable")

@api_router.get("/messages")
async def get_messages(user=Depends(current_user)):
    if USE_SUPABASE:
        return await supabase_db.get_messages(user=user)
    return []

@api_router.get("/calendar")
async def calendar_events(
    doctor_id: Optional[str] = None,
    on_date: Optional[date] = Query(None, alias="date"),
    status: Optional[str] = None,
    stage: Optional[str] = None,
    user=Depends(current_user)
):
    if USE_SUPABASE:
        filters = {"doctor_id": doctor_id, "date": on_date.isoformat() if on_date else None, "status": status, "stage": stage}
        items = await supabase_db.get_follow_ups(user=user, filters=filters)
        return [i for i in items if i.get("status") != "COMPLETED"]
    return []

@api_router.get("/dashboard")
async def dashboard(user=Depends(current_user)):
    today_str = clinic_today().isoformat()
    if USE_SUPABASE:
        patients = await supabase_db.get_patients(user=user)
        all_patients = await supabase_db.get_patients() if user["role"] == "admin" else patients
        follows = await supabase_db.get_follow_ups(user=user)
        requests = await supabase_db.get_reschedule_requests(user=user)

        counts = {
            "total_patients": len(patients),
            "doctor1_patients": sum(str(p.get("assigned_doctor_id")) == ACCOUNTS["doctor1@clinic.demo"]["supabase_id"] for p in all_patients),
            "doctor2_patients": sum(str(p.get("assigned_doctor_id")) == ACCOUNTS["doctor2@clinic.demo"]["supabase_id"] for p in all_patients),
            "today": sum(f.get("follow_up_date") == today_str and f.get("status") != "COMPLETED" for f in follows),
            "upcoming": sum(f.get("status") == "UPCOMING" for f in follows),
            "overdue": sum(f.get("status") == "OVERDUE" for f in follows),
            "confirmed": sum(f.get("status") == "CONFIRMED" for f in follows),
            "rescheduled": sum(f.get("status") == "RESCHEDULED" for f in follows),
            "pending_requests": sum(r.get("status") == "PENDING" for r in requests),
        }
        return {
            "counts": counts,
            "today": today_str,
            "timezone": str(TZ),
            "whatsapp_configured": bool(WA_TOKEN and WA_PHONE_ID and WA_APP_SECRET) or MOCK_WHATSAPP,
            "mock_mode": MOCK_WHATSAPP,
            "generated_at": now(),
        }
    return {
        "counts": {"total_patients": 0, "today": 0, "upcoming": 0, "overdue": 0, "confirmed": 0, "rescheduled": 0, "pending_requests": 0},
        "today": today_str,
        "timezone": str(TZ),
        "whatsapp_configured": False,
        "mock_mode": True,
        "generated_at": now(),
    }

@api_router.get("/activity")
async def get_activity(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    if USE_SUPABASE:
        return await supabase_db.get_activities(limit=1000)
    return []

# Dual mount api router:
# - Mounted at prefix "/api" for standard requests (e.g. /api/auth/login)
# - Mounted at root "/" for any Vercel rewrites that strip the "/api" prefix
app.include_router(api_router, prefix="/api")
app.include_router(api_router)

# Mount static files if directory exists
static_dir = BASE / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def frontend():
    index_file = BASE / "index.html"
    if not index_file.exists():
        index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return PlainTextResponse("Bloom Clinic API is running.")
