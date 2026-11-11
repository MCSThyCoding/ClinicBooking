# ClinicBook — Healthcare Appointment System (MVP)

A beginner-friendly clinic booking system built with **Python + Flask + SQLite**.
No database server or build step required — just Python.

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 — the database (`clinic.db`) and demo data are
created automatically on first run.

## Demo accounts (password: `demo123`)

| Role    | Email                  | What you see                        |
|---------|------------------------|-------------------------------------|
| Admin   | admin@clinicbook.kh    | Clinic overview, stats, schedules   |
| Doctor  | sokha@clinicbook.kh    | Today's patient queue + records     |
| Patient | demo@demo.com          | Booking flow + my bookings          |

## Features

**Patient tab**
- Pick a doctor → pick a date → pick a free time slot (slots are generated
  from each doctor's weekly schedule and exclude already-booked times)
- KHQR-style deposit payment (simulated — 50% of the consultation fee)
- View / pay / cancel upcoming bookings

**Doctor tab**
- Today's queue ordered by time, with payment and status badges
- Move appointments through the workflow:
  `PENDING → CONFIRMED → IN CONSULTATION → COMPLETED` (+ NO SHOW / CANCELLED)
- Write diagnosis + prescription (medical record) per visit
- Staff/admin can switch which doctor's queue they are viewing

**Admin tab**
- Stats: appointments this week, deposits collected, no-show rate, active doctors
- "Appointments per day" bar chart (last 7 days)
- Doctor working-hours table

## Project structure

```
ClinicBooking/
├── app.py               # Flask routes + business logic (slots, stats, APIs)
├── db.py                # SQLite schema + demo seed data
├── clinic.db            # generated database (delete to reset)
├── requirements.txt
├── templates/
│   ├── base.html        # shared layout
│   ├── login.html       # sign-in page
│   └── dashboard.html   # Patient / Doctor / Admin tabs
└── static/
    ├── style.css        # medical theme
    └── app.js           # tabs, booking flow, API calls
```

## How the slot logic works

`slots_for(doctor_id, day)` in `app.py`:
1. Finds the doctor's `doctor_schedules` row matching the weekday
   (`day_of_week`: 0 = Sunday … 6 = Saturday, clinic closed Sunday)
2. Generates start times every `slot_duration_mins` between `start_time`
   and `end_time`
3. Marks any time already taken by a non-cancelled appointment as unavailable

The same function guards booking creation, so double-booking is impossible
even if two patients click at the same time.

## Taking it further (from MVP → production)

- **PostgreSQL**: swap `db.py` for SQLAlchemy + Postgres; schema in `db.py`
  maps almost 1:1 (TEXT ids → UUID, REAL → DECIMAL)
- **Real payments**: replace the simulated `/pay` endpoint with ABA PayWay / KHQR API
- **Notifications**: send booking confirmations + reminders via Telegram Bot API
- **Redis**: use it for slot locking and queue state at higher traffic
- **File uploads**: store lab results / prescriptions on S3 or Cloudinary
  instead of `attachment_url`
