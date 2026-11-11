"""
db.py — Database layer for ClinicBook.

Uses SQLite (a file-based database) so the project runs with zero setup —
no server to install. The schema mirrors the PostgreSQL design, but uses
TEXT ids instead of UUID and INTEGER/ TEXT types SQLite understands.

Run `python db.py` once to create clinic.db and seed demo data.
The Flask app also calls init_db() automatically on startup.
"""

import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "clinic.db")

# Weekday convention: Python's date.weekday() -> Mon=0 ... Sun=6
# We store day_of_week as 0=Sunday ... 6=Saturday to match the spec.
WEEKDAY_MAP = {"monday": 1, "tuesday": 2, "wednesday": 3,
               "thursday": 4, "friday": 5, "saturday": 6, "sunday": 0}
DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    phone         TEXT UNIQUE,
    email         TEXT,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('PATIENT','DOCTOR','CLINIC_STAFF','ADMIN')),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doctors (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL UNIQUE REFERENCES users(id),
    specialization   TEXT NOT NULL,
    consultation_fee REAL NOT NULL,
    bio              TEXT
);

CREATE TABLE IF NOT EXISTS doctor_schedules (
    id                 TEXT PRIMARY KEY,
    doctor_id          TEXT NOT NULL REFERENCES doctors(id),
    day_of_week        INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time         TEXT NOT NULL,   -- "HH:MM"
    end_time           TEXT NOT NULL,   -- "HH:MM"
    slot_duration_mins INTEGER NOT NULL DEFAULT 30
);

CREATE TABLE IF NOT EXISTS appointments (
    id               TEXT PRIMARY KEY,
    patient_id       TEXT NOT NULL REFERENCES users(id),
    doctor_id        TEXT NOT NULL REFERENCES doctors(id),
    appointment_date TEXT NOT NULL,     -- "YYYY-MM-DD"
    appointment_time TEXT NOT NULL,     -- "HH:MM"
    status           TEXT NOT NULL DEFAULT 'PENDING'
                     CHECK (status IN ('PENDING','CONFIRMED','IN_CONSULTATION','COMPLETED','CANCELLED','NO_SHOW')),
    payment_status   TEXT NOT NULL DEFAULT 'UNPAID'
                     CHECK (payment_status IN ('UNPAID','PAID','REFUNDED')),
    deposit_amount   REAL NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS medical_records (
    id             TEXT PRIMARY KEY,
    appointment_id TEXT NOT NULL UNIQUE REFERENCES appointments(id),
    patient_id     TEXT NOT NULL REFERENCES users(id),
    diagnosis      TEXT,
    prescription   TEXT,
    attachment_url TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_appointments_doctor_date
    ON appointments(doctor_id, appointment_date);
CREATE INDEX IF NOT EXISTS idx_appointments_patient
    ON appointments(patient_id);

-- Prevents double-booking: one active appointment per doctor/slot.
-- Cancelled rows are excluded so the slot can be re-booked.
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_booking_per_slot
    ON appointments(doctor_id, appointment_date, appointment_time)
    WHERE status != 'CANCELLED';
"""


def get_db():
    """Open a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables if missing, then seed demo data on first run."""
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()

    has_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    if has_users == 0:
        seed(conn)
    conn.close()


def _uid():
    return uuid.uuid4().hex[:12]


def seed(conn):
    """Insert demo data: users, doctors, schedules, appointments, records."""
    from werkzeug.security import generate_password_hash

    now = datetime.now().isoformat(timespec="seconds")
    today = date.today()

    # ---------- users ----------
    # password for every account below is:  demo123
    pw = generate_password_hash("demo123")

    def add_user(name, phone, email, role):
        uid = _uid()
        conn.execute(
            "INSERT INTO users (id,name,phone,email,password_hash,role,created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (uid, name, phone, email, pw, role, now),
        )
        return uid

    admin_id = add_user("Clinic Admin", "012345678", "admin@clinicbook.kh", "ADMIN")
    staff_id = add_user("Reception Staff", "012345679", "staff@clinicbook.kh", "CLINIC_STAFF")

    # Patients that appear in the doctor's queue
    patient_names = [
        ("Srey Neang", "012111111"),
        ("Vanna Pich", "012222222"),
        ("Dara Kem", "012333333"),
        ("Sophea Lim", "012444444"),
        ("Rithy Heng", "012555555"),
        ("Demo Patient", "012000000"),
    ]
    patient_ids = []
    for name, phone in patient_names:
        email = ("demo@demo.com" if name == "Demo Patient"
                 else f"{name.lower().replace(' ', '')}@demo.com")
        patient_ids.append(add_user(name, phone, email, "PATIENT"))

    # ---------- doctors ----------
    doctor_specs = [
        ("Dr. Sokha Chan", "sokha@clinicbook.kh", "General practice", 10.0,
         "Experienced GP with 10+ years in family medicine.",
         [("monday", "08:00", "12:00", 30), ("tuesday", "08:00", "12:00", 30),
          ("wednesday", "08:00", "12:00", 30), ("thursday", "08:00", "12:00", 30),
          ("friday", "08:00", "12:00", 30)]),
        ("Dr. Bopha Vann", "bopha@clinicbook.kh", "Dentistry", 15.0,
         "Dentist specialised in cleaning, fillings and orthodontics.",
         [("monday", "13:00", "17:00", 30), ("wednesday", "13:00", "17:00", 30),
          ("friday", "13:00", "17:00", 30)]),
        ("Dr. Vibol Sar", "vibol@clinicbook.kh", "Pediatrics", 12.0,
         "Paediatrician caring for children from newborn to 12 years.",
         [("tuesday", "09:00", "13:00", 30), ("thursday", "09:00", "13:00", 30),
          ("saturday", "09:00", "12:00", 30)]),
    ]

    doctor_ids = []
    for name, email, spec, fee, bio, shifts in doctor_specs:
        uid = add_user(name, f"011{len(doctor_ids)+1:06d}", email, "DOCTOR")
        did = _uid()
        conn.execute(
            "INSERT INTO doctors (id,user_id,specialization,consultation_fee,bio)"
            " VALUES (?,?,?,?,?)",
            (did, uid, spec, fee, bio),
        )
        for day, start, end, dur in shifts:
            conn.execute(
                "INSERT INTO doctor_schedules"
                " (id,doctor_id,day_of_week,start_time,end_time,slot_duration_mins)"
                " VALUES (?,?,?,?,?,?)",
                (_uid(), did, WEEKDAY_MAP[day], start, end, dur),
            )
        doctor_ids.append(did)

    # ---------- appointments (today's queue matches the UI mockup) ----------
    # Mockup queue: 08:00 Srey Neang Paid/Completed, 08:30 Vanna Pich Paid/Completed,
    # 09:00 Dara Kem Paid/In consultation, 09:30 Sophea Lim Paid/Confirmed,
    # 10:00 Rithy Heng Unpaid/Pending — all with Dr. Sokha Chan today.
    queue = [
        (patient_ids[0], "08:00", "COMPLETED",   "PAID",   10.0),
        (patient_ids[1], "08:30", "COMPLETED",   "PAID",   10.0),
        (patient_ids[2], "09:00", "IN_CONSULTATION", "PAID", 10.0),
        (patient_ids[3], "09:30", "CONFIRMED",   "PAID",   10.0),
        (patient_ids[4], "10:00", "PENDING",     "UNPAID",  0.0),
    ]
    first_appt_id = None
    for pid, t, status, pay, dep in queue:
        aid = _uid()
        if first_appt_id is None:
            first_appt_id = aid
        conn.execute(
            "INSERT INTO appointments"
            " (id,patient_id,doctor_id,appointment_date,appointment_time,"
            "  status,payment_status,deposit_amount,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (aid, pid, doctor_ids[0], today.isoformat(), t,
             status, pay, dep, now),
        )

    # A couple of future appointments so the patient "My bookings" list isn't empty
    future = [
        (patient_ids[5], doctor_ids[1], 1, "10:00", "PENDING", "UNPAID", 0.0),
        (patient_ids[5], doctor_ids[0], 2, "09:30", "PENDING", "UNPAID", 0.0),
    ]
    for pid, did, offset, t, status, pay, dep in future:
        conn.execute(
            "INSERT INTO appointments"
            " (id,patient_id,doctor_id,appointment_date,appointment_time,"
            "  status,payment_status,deposit_amount,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (_uid(), pid, did, (today + timedelta(days=offset)).isoformat(),
             t, status, pay, dep, now),
        )

    # ---------- one sample medical record ----------
    conn.execute(
        "INSERT INTO medical_records"
        " (id,appointment_id,patient_id,diagnosis,prescription,attachment_url,created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (_uid(), first_appt_id, patient_ids[2],
         "Seasonal flu, mild fever for 2 days.",
         "Paracetamol 500mg, 1 tablet every 6 hours after meals. Rest and drink plenty of fluids.",
         None, now),
    )

    conn.commit()


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DB_PATH}")
