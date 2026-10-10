# Fertility Clinic Follow-up Management

FastAPI + Supabase / SQLite backend with a dependency-free modern JavaScript frontend.

---

## 🚀 Deploying to Vercel

This repository is pre-configured for **one-click deployment to Vercel**:

### 1. Push to GitHub
Initialize git and push this folder to your GitHub account:
```powershell
git init
git add .
git commit -m "Prepare fertility clinic for Vercel deployment"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo-name>.git
git push -u origin main
```

### 2. Import into Vercel
1. Go to [vercel.com/new](https://vercel.com/new) and import your repository.
2. Under **Environment Variables**, add the following settings (values from your `.env`):

| Variable Name | Recommended Value / Source |
|---|---|
| `DATABASE_BACKEND` | `supabase` |
| `SUPABASE_URL` | `https://bvrwbwzeczgizgirsrzi.supabase.co` |
| `SUPABASE_KEY` | *(your Supabase secret key from `.env`)* |
| `DOCTOR1_PASSWORD` | *(12+ character password from `.env`)* |
| `DOCTOR2_PASSWORD` | *(12+ character password from `.env`)* |
| `RECEPTION_PASSWORD` | *(12+ character password from `.env`)* |
| `ADMIN_PASSWORD` | *(12+ character password from `.env`)* |
| `SESSION_SECRET` | *(random 32+ character secret string)* |
| `CLINIC_TIMEZONE` | `America/New_York` |
| `COOKIE_SECURE` | `true` |
| `MOCK_WHATSAPP` | `true` |

3. Click **Deploy**. Vercel will build the frontend assets on its Edge CDN and run the FastAPI server via Serverless Python runtime at `/api`.

---

## 💻 Local Development

1. Open the project root in your terminal:
```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```
2. Open http://localhost:8000 in your browser.

---

## 🔐 Demo Accounts

| Account | Email | Role |
|---|---|---|
| Doctor 1 | `doctor1@clinic.demo` | Clinical Follow-ups & Assigned Patients |
| Doctor 2 | `doctor2@clinic.demo` | Clinical Follow-ups & Assigned Patients |
| Receptionist | `reception@clinic.demo` | Registration, Scheduling, WhatsApp Reminders |
| Admin | `admin@clinic.demo` | Clinic Oversight, System Logs, Analytics |

*(Passwords are set via environment variables in `.env` / Vercel Environment Variables).*

---

## ⚙️ Architecture & Features

- **Frontend**: Clean Vanilla JavaScript SPA using hash-based navigation (`#/doctor/dashboard`, `#/patients`, etc.). Served directly via Vercel Edge CDN.
- **Backend**: FastAPI with Python Serverless Function entry point (`api/index.py`).
- **Authentication**: Stateless HMAC-SHA256 signed session cookies, eliminating session drops across serverless instances and cold starts.
- **Database**: Supabase PostgREST layer (persistent in cloud) with seamless fallback to SQLite.
- **Routing**: `vercel.json` rewrites send `/api/*` to the Python serverless function and all other routes to the static frontend.
