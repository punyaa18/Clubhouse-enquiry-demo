"""Routes for the golf club enquiry demo. See db.py for storage, logic.py for rules."""
import os
import re
import smtplib
import time
from datetime import datetime, timedelta
from email.message import EmailMessage

from flask import Flask, g, redirect, render_template, request, url_for

import db
from logic import is_follow_up_due

app = Flask(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ENQUIRY_TYPES = ["Membership", "Society day", "Event"]
MESSAGE_MAX_LEN = 1000

# in-memory rate limiting: ip -> list of submission timestamps (real wall-clock)
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_SUBMISSIONS = 5
_submission_log = {}


def get_db():
    if "db" not in g:
        g.db = db.get_connection()
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def simulated_now(conn):
    """Real time plus the simulated day offset stored in settings."""
    offset = db.get_day_offset(conn)
    return datetime.now() + timedelta(days=offset)


def is_rate_limited(ip):
    now = time.monotonic()
    recent = [t for t in _submission_log.get(ip, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
    _submission_log[ip] = recent
    return len(recent) >= RATE_LIMIT_MAX_SUBMISSIONS


def record_submission(ip):
    _submission_log.setdefault(ip, []).append(time.monotonic())


def validate_enquiry(form):
    """Returns a dict of field -> error message. Empty dict means valid."""
    errors = {}
    if not form.get("name", "").strip():
        errors["name"] = "Please enter your name."
    if not form.get("email", "").strip():
        errors["email"] = "Please enter your email address."
    elif not EMAIL_RE.match(form["email"].strip()):
        errors["email"] = "Please enter a valid email address."
    if form.get("enquiry_type") not in ENQUIRY_TYPES:
        errors["enquiry_type"] = "Please choose an enquiry type."
    message = form.get("message", "").strip()
    if not message:
        errors["message"] = "Please enter a message."
    elif len(message) > MESSAGE_MAX_LEN:
        errors["message"] = f"Message must be under {MESSAGE_MAX_LEN} characters."
    return errors


def send_confirmation_email(conn, name, email, enquiry_type, now):
    subject = f"We received your {enquiry_type} enquiry"
    body = (
        f"Hi {name},\n\n"
        f"Thanks for your {enquiry_type} enquiry. A member of our team will be "
        f"in touch soon.\n\nClubhouse"
    )
    sent_at = now.isoformat(timespec="seconds")
    print(f"[EMAIL] to={email} subject={subject!r}\n{body}\n")
    db.insert_email(conn, email, subject, body, sent_at)
    if os.environ.get("SMTP_HOST"):
        try:
            smtp_send(email, subject, body)
        except (smtplib.SMTPException, OSError) as exc:
            # the enquiry is already saved; a mail failure shouldn't lose it
            print(f"[EMAIL] SMTP send failed: {exc}")


def smtp_send(to_address, subject, body):
    """Send via the SMTP server configured in SMTP_* environment variables."""
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")

    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM") or user or "clubhouse@localhost"
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=15) as server:
        if port != 25:
            server.starttls()
        if user and password:
            server.login(user, password)
        server.send_message(msg)
    print(f"[EMAIL] delivered via SMTP {host}:{port}")


@app.route("/", methods=["GET", "POST"])
def enquiry_form():
    if request.method == "GET":
        return render_template(
            "form.html", errors={}, values={}, enquiry_types=ENQUIRY_TYPES
        )

    # honeypot: real users never fill this hidden field
    if request.form.get("website", ""):
        return render_template(
            "form.html", errors={}, values={}, enquiry_types=ENQUIRY_TYPES
        )

    ip = request.remote_addr or "unknown"
    if is_rate_limited(ip):
        errors = {"form": "Too many submissions. Please try again in a minute."}
        return render_template(
            "form.html", errors=errors, values=request.form, enquiry_types=ENQUIRY_TYPES
        ), 429

    errors = validate_enquiry(request.form)
    if errors:
        return render_template(
            "form.html", errors=errors, values=request.form, enquiry_types=ENQUIRY_TYPES
        ), 400

    record_submission(ip)
    conn = get_db()
    now = simulated_now(conn)
    name = request.form["name"].strip()
    email = request.form["email"].strip()
    enquiry_type = request.form["enquiry_type"]
    message = request.form["message"].strip()

    db.insert_enquiry(
        conn, name, email, enquiry_type, message, now.isoformat(timespec="seconds")
    )
    send_confirmation_email(conn, name, email, enquiry_type, now)

    return redirect(url_for("thanks"))


@app.route("/thanks")
def thanks():
    return render_template("thanks.html")


@app.route("/staff")
def staff():
    conn = get_db()
    now = simulated_now(conn)
    enquiries = list_enquiries_with_flags(conn, now)
    follow_up_count = sum(1 for e in enquiries if e["follow_up_due"])
    return render_template(
        "staff.html",
        enquiries=enquiries,
        follow_up_count=follow_up_count,
        simulated_now=now,
        day_offset=db.get_day_offset(conn),
    )


def list_enquiries_with_flags(conn, now):
    rows = db.list_enquiries(conn)
    enquiries = []
    for row in rows:
        enquiry = dict(row)
        enquiry["follow_up_due"] = is_follow_up_due(row, now)
        enquiries.append(enquiry)
    return enquiries


@app.route("/staff/contact/<int:enquiry_id>", methods=["POST"])
def mark_contacted(enquiry_id):
    conn = get_db()
    now = simulated_now(conn)
    db.mark_contacted(conn, enquiry_id, now.isoformat(timespec="seconds"))
    return redirect(url_for("staff"))


@app.route("/staff/advance-day", methods=["POST"])
def advance_day():
    conn = get_db()
    db.set_day_offset(conn, db.get_day_offset(conn) + 1)
    return redirect(url_for("staff"))


@app.route("/staff/reset-time", methods=["POST"])
def reset_time():
    conn = get_db()
    db.set_day_offset(conn, 0)
    return redirect(url_for("staff"))


@app.route("/staff/emails")
def staff_emails():
    conn = get_db()
    emails = db.list_emails(conn)
    return render_template("emails.html", emails=emails)


@app.cli.command("seed")
def seed_command():
    """Insert made-up enquiries at different ages for demoing follow-up flags."""
    from seed import run_seed

    conn = db.get_connection()
    db.init_db(conn)
    run_seed(conn)
    conn.close()
    print("Seeded database with demo enquiries.")


with app.app_context():
    db.init_db(get_db())


if __name__ == "__main__":
    app.run(debug=True)
