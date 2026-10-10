import getpass
import main

ACCOUNTS = [
    "doctor1@clinic.demo",
    "doctor2@clinic.demo",
    "reception@clinic.demo",
    "admin@clinic.demo",
]

print("\n=== Fertility Clinic Password Reset ===")

with main.local_database() as connection:
    for email in ACCOUNTS:
        user = connection.execute(
            "SELECT id FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if user is None:
            print(f"\nAccount not found: {email}")
            continue

        print(f"\nAccount: {email}")
        password = getpass.getpass("Enter a NEW password (12+ characters): ")

        if len(password) < 12:
            print("Password must contain at least 12 characters.")
            continue

        confirm = getpass.getpass("Confirm new password: ")

        if password != confirm:
            print("Passwords do not match.")
            continue

        hashed = main.password_hash(password)

        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hashed, user["id"])
        )

        print(f"Password updated for {email}")

print("\nFinished.")
