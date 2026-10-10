
import os
import sqlite3
import getpass
import hashlib
import secrets
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "clinic.db"


def make_password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt),
        n=16384,
        r=8,
        p=1,
        maxmem=64 * 1024 * 1024,
    ).hex()
    return f"{salt}:{digest}"


def ask_password(label):
    while True:
        password = getpass.getpass(f"New {label} password (hidden): ")
        if len(password) < 12:
            print("Use at least 12 characters.")
            continue
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match. Try again.")
            continue
        return password


def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("No changes made.")
        return

    print("This script preserves existing patient and follow-up records.")
    print("Use fictional data only. WhatsApp opt-in will remain OFF.")
    if input("Continue? Type YES: ").strip() != "YES":
        print("Cancelled. No changes made.")
        return

    doctor1_name = input("New display name for Doctor 1: ").strip()
    doctor2_name = input("New display name for Doctor 2: ").strip()
    if not doctor1_name or not doctor2_name:
        print("Names cannot be blank. No changes made.")
        return

    change_passwords = input(
        "Change both doctor passwords too? Type YES or NO: "
    ).strip().upper()

    passwords = {}
    if change_passwords == "YES":
        passwords[1] = ask_password("Doctor 1")
        passwords[2] = ask_password("Doctor 2")
    elif change_passwords != "NO":
        print("Please run again and answer YES or NO.")
        return

    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")

        doctors = connection.execute(
            "SELECT id, email, role FROM users WHERE role = 'doctor' ORDER BY id"
        ).fetchall()

        if len(doctors) != 2 or [d["id"] for d in doctors] != [1, 2]:
            raise RuntimeError(
                "Expected doctor accounts with IDs 1 and 2. No changes saved."
            )

        # Update names and, if requested, password hashes.
        for doctor_id, name in [(1, doctor1_name), (2, doctor2_name)]:
            if doctor_id in passwords:
                connection.execute(
                    "UPDATE users SET name = ?, password_hash = ? WHERE id = ?",
                    (name, make_password_hash(passwords[doctor_id]), doctor_id),
                )
            else:
                connection.execute(
                    "UPDATE users SET name = ? WHERE id = ?",
                    (name, doctor_id),
                )

        # These are clearly fictional demonstration records.
        # The reserved +1555 0100 number range is used for examples.
        demo_patients = [
            (
                "DEMO - Kavya Nair", "+15550100101", "en_US", 1,
                "Consultation", 0
            ),
            (
                "DEMO - Meera Kumar", "+15550100102", "hi", 2,
                "Follow-up", 0
            ),
            (
                "DEMO - Aadhya Rao", "+15550100103", "en_US", 1,
                "Review", 0
            ),
        ]

        for name, phone, language, doctor_id, stage, opt_in in demo_patients:
            existing = connection.execute(
                "SELECT id FROM patients WHERE name = ? AND phone = ?",
                (name, phone),
            ).fetchone()

            if existing:
                patient_id = existing["id"]
                print(f"Demo patient already exists: {name}")
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO patients
                    (name, phone, preferred_language, doctor_id,
                     treatment_stage, whatsapp_opt_in, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name, phone, language, doctor_id, stage, opt_in,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                patient_id = cursor.lastrowid
                print(f"Added demo patient: {name}")

            # Add one demo follow-up only if this patient has none
            # already marked with our demo follow-up type.
            follow_type = "DEMO - Routine follow-up"
            found = connection.execute(
                """
                SELECT id FROM follow_ups
                WHERE patient_id = ? AND follow_up_type = ?
                """,
                (patient_id, follow_type),
            ).fetchone()

            if not found:
                follow_date = (date.today() + timedelta(days=7)).isoformat()
                stamp = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    """
                    INSERT INTO follow_ups
                    (patient_id, follow_up_date, follow_up_type, status,
                     patient_response, created_at, updated_at)
                    VALUES (?, ?, ?, 'UPCOMING', NULL, ?, ?)
                    """,
                    (patient_id, follow_date, follow_type, stamp, stamp),
                )
                print(f"Added demo follow-up for: {name}")

        connection.commit()
        print("\nSuccess! Changes saved.")
        print("Existing patient and follow-up records were preserved.")
        print("Doctor names updated.")
        if passwords:
            print("Both doctor passwords updated.")
        else:
            print("Doctor passwords were left unchanged.")
        print("WhatsApp opt-in is OFF for all demo patients.")

    except Exception as error:
        connection.rollback()
        print(f"\nError: {error}")
        print("Changes rolled back; no partial changes were saved.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()