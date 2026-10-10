import httpx

client = httpx.Client(base_url="http://127.0.0.1:8000")

# 1. Fetch frontend index.html
r_index = client.get("/")
assert r_index.status_code == 200, f"Expected 200, got {r_index.status_code}"
assert '<div id="app">' in r_index.text
print("[PASS] 1. Frontend HTML served successfully at /")

# 2. Fetch static assets
r_css = client.get("/static/styles.css")
r_app = client.get("/static/app.js")
r_api = client.get("/static/api.js")
assert r_css.status_code == 200 and r_app.status_code == 200 and r_api.status_code == 200
print("[PASS] 2. All static assets (CSS, app.js, api.js) served successfully with 200 OK")

# 3. Initial me check (boot in app.js)
r_me_init = client.get("/api/auth/me")
assert r_me_init.status_code == 401
print("[PASS] 3. Unauthenticated me returns 401 (triggers login view in frontend)")

# 4. Login flow
r_login = client.post(
    "/api/auth/login",
    json={"email": "doctor1@clinic.demo", "password": "2sLkJM8ICNAVx4cw"},
    headers={"origin": "http://127.0.0.1:8000"},
)
assert r_login.status_code == 200, f"Login failed: {r_login.text}"
user = r_login.json()
print(f"[PASS] 4. Login successful for: {user['name']} ({user['role']})")
assert "clinic_session" in client.cookies
print("[PASS] 5. Session cookie received and stored")

# 5. Dashboard reload (reload() in app.js)
r_dash = client.get("/api/dashboard")
assert r_dash.status_code == 200
dash = r_dash.json()
print(f"[PASS] 6. Dashboard loaded: {dash['counts']['total_patients']} patients, {dash['counts']['today']} due today")

# 6. Patients list
r_patients = client.get("/api/patients")
assert r_patients.status_code == 200
patients = r_patients.json()
print(f"[PASS] 7. Patients list loaded: {len(patients)} patient records retrieved from Supabase")

# 7. Follow-ups list
r_follows = client.get("/api/follow-ups")
assert r_follows.status_code == 200
follows = r_follows.json()
print(f"[PASS] 8. Follow-ups loaded: {len(follows)} records retrieved")

# 8. Calendar events
r_cal = client.get("/api/calendar")
assert r_cal.status_code == 200
print("[PASS] 9. Calendar events loaded")

# 9. Logout flow
r_logout = client.post("/api/auth/logout", headers={"origin": "http://127.0.0.1:8000"})
assert r_logout.status_code == 200
r_me_after = client.get("/api/auth/me")
assert r_me_after.status_code == 401
print("[PASS] 10. Logout successful and session cleared")

print("\n=======================================================")
print("ALL 10 FRONTEND-BACKEND INTEGRATION CHECKS PASSED 100%!")
print("=======================================================")
