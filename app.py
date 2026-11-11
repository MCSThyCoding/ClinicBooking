"""
app.py — ClinicBook MVP backend + UI server.

Run:   python app.py
Open:  http://127.0.0.1:5000

Demo accounts (password: demo123):
    admin@clinicbook.kh   -> Admin portal
    sokha@clinicbook.kh   -> Doctor dashboard (Dr. Sokha Chan)
    demo@demo.com         -> Patient booking  (Demo Patient)
"""

import sqlite3
import uuid
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash

import db

app = Flask(__name__)
app.secret_key = "clinicbook-dev-secret-change-me"  # TODO: use env var in production


# ---------------------------------------------------------------- helpers

def current_user():
    """Return the logged-in user row, or None."""
    uid = session.get("user_id")
    if not uid:
        return None
    conn = db.get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    return user


def doctor_for_user(user_id):
    conn = db.get_db()
    row = conn.execute(
        "SELECT d.* FROM doctors d JOIN users u ON u.id = d.user_id"
        " WHERE u.id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def require_role(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                return redirect(url_for("login"))
            if user["role"] not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def doctor_owns_appointment(user, appt):
    """True if a DOCTOR user owns this appointment's doctor record.
    Staff/admin always pass."""
    if user["role"] in ("ADMIN", "CLINIC_STAFF"):
        return True
    if user["role"] != "DOCTOR":
        return False
    mine = doctor_for_user(user["id"])
    return bool(mine) and mine["id"] == appt["doctor_id"]


def minutes(t):
    """'HH:MM' -> minutes since midnight."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def hhmm(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"


def slots_for(doctor_id, day):
    """
    Return every bookable start time (HH:MM) for a doctor on a date.

    A slot is bookable when:
      - the clinic is open that weekday
      - a doctor_schedules row covers that weekday
      - the slot does not overlap an existing non-cancelled appointment
    """
    dow = (day.weekday() + 1) % 7  # Python Mon=0..Sun=6 -> spec Sun=0..Sat=6

    conn = db.get_db()
    schedule = conn.execute(
        "SELECT * FROM doctor_schedules WHERE doctor_id = ? AND day_of_week = ?",
        (doctor_id, dow)).fetchall()
    booked = conn.execute(
        "SELECT appointment_time FROM appointments"
        " WHERE doctor_id = ? AND appointment_date = ? AND status != 'CANCELLED'",
        (doctor_id, day.isoformat())).fetchall()
    conn.close()

    taken = {r["appointment_time"] for r in booked}
    slots = []
    for s in schedule:
        cur = minutes(s["start_time"])
        end = minutes(s["end_time"])
        while cur + s["slot_duration_mins"] <= end:
            t = hhmm(cur)
            slots.append({"time": t, "available": t not in taken})
            cur += s["slot_duration_mins"]
    return slots


def upcoming_dates(days=7):
    """Next `days` dates, skipping Sundays (clinic closed)."""
    out = []
    d = date.today()
    while len(out) < days:
        d += timedelta(days=1)
        if d.isoweekday() != 7:  # Sunday closed
            out.append(d)
    return out


# ---------------------------------------------------------------- auth

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        conn = db.get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ? OR phone = ?",
            (email, email)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        flash("Invalid email/phone or password. Try admin@clinicbook.kh / demo123")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- pages

@app.route("/")
def index():
    return redirect(url_for("dashboard") if current_user() else url_for("login"))


@app.route("/dashboard")
@require_login
def dashboard():
    user = current_user()
    conn = db.get_db()

    doctors = conn.execute(
        "SELECT d.*, u.name AS doctor_name FROM doctors d"
        " JOIN users u ON u.id = d.user_id ORDER BY u.name").fetchall()

    # Doctor tab: today's queue. Staff/admin can inspect any doctor via ?doc=
    my_doctor = doctor_for_user(user["id"])
    requested_doc = request.args.get("doc")
    can_view_others = user["role"] in ("ADMIN", "CLINIC_STAFF")
    if (requested_doc and can_view_others
            and requested_doc in {d["id"] for d in doctors}):
        queue_doctor_id = requested_doc
    else:
        queue_doctor_id = my_doctor["id"] if my_doctor else doctors[0]["id"]
    queue_doctor = conn.execute(
        "SELECT d.*, u.name AS doctor_name, u.id AS user_id FROM doctors d"
        " JOIN users u ON u.id = d.user_id WHERE d.id = ?",
        (queue_doctor_id,)).fetchone()

    today = date.today().isoformat()
    queue = conn.execute(
        """SELECT a.*, u.name AS patient_name, u.phone AS patient_phone
           FROM appointments a JOIN users u ON u.id = a.patient_id
           WHERE a.doctor_id = ? AND a.appointment_date = ?
             AND a.status != 'CANCELLED'
           ORDER BY a.appointment_time""",
        (queue_doctor_id, today)).fetchall()

    # All doctors' queues (for the dropdown on the doctor tab)
    all_queues = {}
    for doc in doctors:
        rows = conn.execute(
            """SELECT a.*, u.name AS patient_name, u.phone AS patient_phone
               FROM appointments a JOIN users u ON u.id = a.patient_id
               WHERE a.doctor_id = ? AND a.appointment_date = ?
                 AND a.status != 'CANCELLED'
               ORDER BY a.appointment_time""",
            (doc["id"], today)).fetchall()
        all_queues[doc["id"]] = rows

    # Patient tab: my upcoming bookings
    my_bookings = conn.execute(
        """SELECT a.*, d.specialization, d.consultation_fee,
                  u.name AS doctor_name
           FROM appointments a
           JOIN doctors d ON d.id = a.doctor_id
           JOIN users u ON u.id = d.user_id
           WHERE a.patient_id = ? AND a.appointment_date >= ?
             AND a.status != 'CANCELLED'
           ORDER BY a.appointment_date, a.appointment_time""",
        (user["id"], today)).fetchall() if user["role"] == "PATIENT" else []

    # Admin stats
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    stats = {
        "appointments_week": conn.execute(
            "SELECT COUNT(*) c FROM appointments WHERE appointment_date >= ?",
            (week_ago,)).fetchone()["c"],
        "deposits": conn.execute(
            "SELECT COALESCE(SUM(deposit_amount),0) s FROM appointments"
            " WHERE payment_status = 'PAID'").fetchone()["s"],
        "no_shows": conn.execute(
            "SELECT COUNT(*) c FROM appointments WHERE status = 'NO_SHOW'"
        ).fetchone()["c"],
        "active_doctors": conn.execute(
            "SELECT COUNT(*) c FROM doctors").fetchone()["c"],
    }
    total_appts = conn.execute("SELECT COUNT(*) c FROM appointments").fetchone()["c"]
    stats["no_show_rate"] = round(100 * stats["no_shows"] / total_appts) if total_appts else 0

    # Appointments per day, last 7 days (for the bar chart)
    chart = []
    for i in range(6, -1, -1):
        d = date.today() - timedelta(days=i)
        c = conn.execute(
            "SELECT COUNT(*) c FROM appointments WHERE appointment_date = ?",
            (d.isoformat(),)).fetchone()["c"]
        chart.append({"label": d.strftime("%a"), "count": c,
                      "is_today": i == 0})

    # Doctor schedules for admin table
    schedules = conn.execute(
        """SELECT s.*, u.name AS doctor_name FROM doctor_schedules s
           JOIN doctors d ON d.id = s.doctor_id
           JOIN users u ON u.id = d.user_id
           ORDER BY u.name, s.day_of_week""").fetchall()

    # Medical records for the queue (latest per patient today)
    records = conn.execute(
        """SELECT r.*, u.name AS patient_name FROM medical_records r
           JOIN users u ON u.id = r.patient_id
           JOIN appointments a ON a.id = r.appointment_id
           WHERE a.doctor_id = ? AND a.appointment_date = ?""",
        (queue_doctor_id, today)).fetchall()
    record_by_patient = {r["appointment_id"]: r for r in records}
    recordable = [a for a in queue
                  if a["status"] in ("CONFIRMED", "IN_CONSULTATION", "COMPLETED")]

    # Group schedule rows per doctor for the admin table
    groups = {}
    for s in schedules:
        groups.setdefault(s["doctor_name"], []).append(s)
    schedule_groups = [
        (name, [{**dict(r), "day_name": db.DAY_NAMES[r["day_of_week"]]}
                for r in rows])
        for name, rows in groups.items()
    ]

    # Role-based tabs: patients book; clinical staff see the queue; admins see all
    role = user["role"]
    tabs = ["patient"]
    if role in ("DOCTOR", "CLINIC_STAFF", "ADMIN"):
        tabs.append("doctor")
    if role in ("ADMIN", "CLINIC_STAFF"):
        tabs.append("admin")
    default_tab = {"PATIENT": "patient", "DOCTOR": "doctor",
                   "CLINIC_STAFF": "doctor", "ADMIN": "admin"}[role]

    conn.close()

    return render_template(
        "dashboard.html",
        user=user,
        doctors=doctors,
        queue_doctor=queue_doctor,
        queue=queue,
        all_queues=all_queues,
        my_bookings=my_bookings,
        stats=stats,
        chart=chart,
        schedules=schedules,
        record_by_patient=record_by_patient,
        recordable=recordable,
        schedule_groups=schedule_groups,
        tabs=tabs,
        default_tab=default_tab,
        dates=upcoming_dates(6),
        day_names=db.DAY_NAMES,
        today=today,
    )


# ---------------------------------------------------------------- APIs

@app.route("/api/doctors/<doctor_id>/slots")
def api_slots(doctor_id):
    """GET ?date=YYYY-MM-DD -> list of {time, available}"""
    try:
        day = date.fromisoformat(request.args.get("date", ""))
    except ValueError:
        return jsonify({"error": "bad date"}), 400
    return jsonify(slots_for(doctor_id, day))


@app.route("/api/appointments", methods=["POST"])
@require_login
def create_appointment():
    """Patient books a slot. Body: doctor_id, date, time."""
    user = current_user()
    if user["role"] != "PATIENT":
        return jsonify({"error": "Only patients can book"}), 403

    data = request.get_json(force=True)
    doctor_id = data.get("doctor_id")
    try:
        day = date.fromisoformat(data.get("date", ""))
    except ValueError:
        return jsonify({"error": "bad date"}), 400
    if day < date.today():
        return jsonify({"error": "Cannot book a past date"}), 400
    t = data.get("time", "")

    # Verify the slot is actually available (never trust the client)
    slot = next((s for s in slots_for(doctor_id, day)
                 if s["time"] == t and s["available"]), None)
    if not slot:
        return jsonify({"error": "That time is no longer available"}), 409

    conn = db.get_db()
    appt_id = uuid.uuid4().hex[:12]
    try:
        conn.execute(
            """INSERT INTO appointments
               (id,patient_id,doctor_id,appointment_date,appointment_time,
                status,payment_status,deposit_amount,created_at)
               VALUES (?,?,?,?,?,'PENDING','UNPAID',0,?)""",
            (appt_id, user["id"], doctor_id, day.isoformat(), t,
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Unique index idx_one_active_booking_per_slot caught a race:
        # someone else booked this exact slot a moment ago.
        conn.close()
        return jsonify({"error": "That time was just booked — pick another"}), 409
    row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    conn.close()
    return jsonify({"ok": True, "appointment": dict(row)})


@app.route("/api/appointments/<appt_id>/pay", methods=["POST"])
@require_login
def pay_appointment(appt_id):
    """Simulated KHQR deposit payment (MVP: no real gateway)."""
    user = current_user()
    conn = db.get_db()
    appt = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    if not appt:
        conn.close()
        return jsonify({"error": "not found"}), 404
    if appt["status"] == "CANCELLED":
        conn.close()
        return jsonify({"error": "appointment cancelled"}), 400
    if appt["patient_id"] != user["id"] and user["role"] not in ("ADMIN", "CLINIC_STAFF"):
        conn.close()
        return jsonify({"error": "forbidden"}), 403

    deposit = appt["deposit_amount"] or 0
    if deposit == 0:
        fee = conn.execute(
            "SELECT consultation_fee FROM doctors WHERE id = ?",
            (appt["doctor_id"],)).fetchone()["consultation_fee"]
        deposit = round(fee * 0.5, 2)  # 50% deposit, like the mockup implies

    conn.execute(
        "UPDATE appointments SET payment_status='PAID', deposit_amount=? WHERE id=?",
        (deposit, appt_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "deposit": deposit})


@app.route("/api/appointments/<appt_id>/status", methods=["POST"])
@require_login
def update_status(appt_id):
    """Doctor/staff moves an appointment through the queue."""
    user = current_user()
    if user["role"] not in ("DOCTOR", "CLINIC_STAFF", "ADMIN"):
        return jsonify({"error": "forbidden"}), 403
    new_status = request.get_json(force=True).get("status")
    allowed = {"PENDING", "CONFIRMED", "IN_CONSULTATION", "COMPLETED",
               "CANCELLED", "NO_SHOW"}
    if new_status not in allowed:
        return jsonify({"error": "bad status"}), 400

    conn = db.get_db()
    appt = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
    if not appt or not doctor_owns_appointment(user, appt):
        conn.close()
        return jsonify({"error": "forbidden"}), 403
    conn.execute("UPDATE appointments SET status=? WHERE id=?",
                 (new_status, appt_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/appointments/<appt_id>/cancel", methods=["POST"])
@require_login
def cancel_appointment(appt_id):
    """Patient cancels their own booking."""
    user = current_user()
    conn = db.get_db()
    appt = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    if not appt or (appt["patient_id"] != user["id"] and user["role"] != "ADMIN"):
        conn.close()
        return jsonify({"error": "forbidden"}), 403
    if appt["appointment_date"] < date.today().isoformat():
        conn.close()
        return jsonify({"error": "Cannot cancel a past appointment"}), 400
    conn.execute("UPDATE appointments SET status='CANCELLED' WHERE id=?", (appt_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/records", methods=["POST"])
@require_login
def save_record():
    """Doctor saves diagnosis/prescription for an appointment."""
    user = current_user()
    if user["role"] not in ("DOCTOR", "CLINIC_STAFF", "ADMIN"):
        return jsonify({"error": "forbidden"}), 403

    data = request.get_json(force=True)
    appt_id = data.get("appointment_id")
    conn = db.get_db()
    appt = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
    if not appt or not doctor_owns_appointment(user, appt):
        conn.close()
        return jsonify({"error": "forbidden"}), 403

    conn.execute(
        """INSERT INTO medical_records
           (id,appointment_id,patient_id,diagnosis,prescription,attachment_url,created_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(appointment_id) DO UPDATE SET
             diagnosis=excluded.diagnosis,
             prescription=excluded.prescription,
             attachment_url=excluded.attachment_url""",
        (uuid.uuid4().hex[:12], appt_id, appt["patient_id"],
         data.get("diagnosis", ""), data.get("prescription", ""),
         data.get("attachment_url"),
         datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------- run

if __name__ == "__main__":
    db.init_db()
    app.run(debug=True, port=5000)
