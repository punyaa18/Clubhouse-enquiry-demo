"""Routes for the golf club enquiry demo. See db.py for storage, logic.py for rules,
mailer.py for SMTP."""
import hmac
import os
import re
import secrets
import smtplib
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from dotenv import load_dotenv
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import db
import mailer
from logic import is_follow_up_due

# SMTP_* and other settings live in a git-ignored .env locally, host env vars in production
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

app = Flask(__name__)
# behind the host's proxy, request.remote_addr would otherwise be the proxy for everyone
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "1") != "0",
    AUTO_SEED=os.environ.get("AUTO_SEED", "1") != "0",
)

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
ENQUIRY_TYPES = ["Membership", "Society day", "Event"]
STATUSES = ["New", "Contacted", "Awaiting reply", "Booked", "Closed"]
STATUS_FILTERS = ["All", *STATUSES, "Follow-up due"]
NAME_MAX_LEN = 100
EMAIL_MAX_LEN = 254
MESSAGE_MAX_LEN = 1000
REPLY_SUBJECT_MAX_LEN = 200
REPLY_BODY_MAX_LEN = 5000
MAX_REPLIES_PER_ENQUIRY = 3
MAX_EMAILS_PER_RECIPIENT_PER_DAY = 2
DATA_RETENTION = timedelta(hours=24)
TEST_EMAIL_RECIPIENT = "punyaa@yopmail.com"

# in-memory rate limiting: ip -> list of submission timestamps (real wall-clock)
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_SUBMISSIONS = 5
_submission_log = {}


def max_emails_per_day():
    return int(os.environ.get("MAX_EMAILS_PER_DAY", "50"))


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


def stamp(dt):
    return dt.isoformat(timespec="seconds")


# --- housekeeping, CSRF ---

@app.before_request
def housekeeping():
    """Drop data older than 24h (real time) and reseed when the database is empty."""
    if request.endpoint == "static":
        return
    conn = get_db()
    db.purge_older_than(conn, stamp(datetime.now() - DATA_RETENTION))
    if app.config["AUTO_SEED"] and db.count_enquiries(conn) == 0:
        from seed import run_seed

        run_seed(conn)


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def check_csrf():
    if request.method != "POST":
        return
    sent = request.form.get("csrf_token", "").encode()
    expected = session.get("csrf_token", "").encode()
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, "This form has expired. Go back, reload the page and try again.")


@app.errorhandler(400)
@app.errorhandler(404)
def show_error(error):
    return render_template(
        "message.html", title=error.name, message=error.description
    ), error.code


@app.context_processor
def email_mode():
    return {"sending_for_real": mailer.sending_for_real(),
            "simulated_reason": mailer.simulated_reason()}


def safe_next(target):
    """Only redirect back to our own staff pages."""
    parts = urlsplit(target or "")
    if not parts.scheme and not parts.netloc and parts.path.startswith("/staff"):
        return target
    return url_for("staff")


# --- rate limiting, validation ---

def is_rate_limited(ip):
    now = time.monotonic()
    recent = [t for t in _submission_log.get(ip, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
    _submission_log[ip] = recent
    return len(recent) >= RATE_LIMIT_MAX_SUBMISSIONS


def record_submission(ip):
    _submission_log.setdefault(ip, []).append(time.monotonic())


def has_line_break(value):
    return "\r" in value or "\n" in value


def validate_enquiry(form):
    """Returns a dict of field -> error message. Empty dict means valid."""
    errors = {}
    name = form.get("name", "").strip()
    email = form.get("email", "").strip()
    if not name:
        errors["name"] = "Please enter your name."
    elif has_line_break(name):
        errors["name"] = "Your name can't contain line breaks."
    elif len(name) > NAME_MAX_LEN:
        errors["name"] = f"Name must be under {NAME_MAX_LEN} characters."
    if not email:
        errors["email"] = "Please enter your email address."
    elif len(email) > EMAIL_MAX_LEN or not EMAIL_RE.fullmatch(email):
        errors["email"] = "Please enter a valid email address."
    if form.get("enquiry_type") not in ENQUIRY_TYPES:
        errors["enquiry_type"] = "Please choose an enquiry type."
    message = form.get("message", "").strip()
    if not message:
        errors["message"] = "Please enter a message."
    elif len(message) > MESSAGE_MAX_LEN:
        errors["message"] = f"Message must be under {MESSAGE_MAX_LEN} characters."
    return errors


def validate_reply(values):
    errors = {}
    if not values["subject"]:
        errors["subject"] = "Please enter a subject."
    elif has_line_break(values["subject"]):
        errors["subject"] = "The subject can't contain line breaks."
    elif len(values["subject"]) > REPLY_SUBJECT_MAX_LEN:
        errors["subject"] = f"Subject must be under {REPLY_SUBJECT_MAX_LEN} characters."
    if not values["body"]:
        errors["body"] = "Please write a message."
    elif len(values["body"]) > REPLY_BODY_MAX_LEN:
        errors["body"] = f"Message must be under {REPLY_BODY_MAX_LEN:,} characters."
    return errors


# --- sending ---

def cap_reached(conn, to_address):
    """Why this email can't go out right now, or None."""
    if db.count_real_emails_today(conn) >= max_emails_per_day():
        return "Daily email limit reached for this demo."
    if db.count_real_emails_today(conn, to_address) >= MAX_EMAILS_PER_RECIPIENT_PER_DAY:
        return f"Limit of {MAX_EMAILS_PER_RECIPIENT_PER_DAY} emails per address per day reached."
    return None


def send_email(conn, *, enquiry_id, kind, to_address, subject, body, now):
    """Send one plain-text email (or simulate it) and store it. Returns (status, error).

    Never raises: the enquiry is already saved and a mail problem mustn't lose it.
    """
    body = mailer.with_footer(body)
    status, error = "simulated", None
    if mailer.sending_for_real():
        error = cap_reached(conn, to_address)
        if error:
            status = "skipped"
        else:
            try:
                mailer.send(to_address, subject, body)
                status = "sent"
            except (smtplib.SMTPException, OSError) as exc:
                status, error = "failed", mailer.describe_error(exc)
    print(f"[EMAIL] {status} {kind} to={to_address} subject={subject!r}"
          + (f" error={error}" if error else ""))
    db.insert_email(conn, enquiry_id=enquiry_id, direction="outbound", kind=kind,
                    to_address=to_address, from_address=mailer.from_address(),
                    subject=subject, body=body, sent_at=stamp(now),
                    status=status, error=error)
    return status, error


def send_confirmation_email(conn, enquiry_id, name, email, enquiry_type, now):
    """One fixed-template confirmation per submission: visitors can't choose its content."""
    subject = f"We received your {enquiry_type} enquiry"
    body = (
        f"Hi {name},\n\n"
        f"Thanks for your {enquiry_type} enquiry. A member of our team will be "
        f"in touch soon.\n\nClubhouse"
    )
    return send_email(conn, enquiry_id=enquiry_id, kind="confirmation",
                      to_address=email, subject=subject, body=body, now=now)


# --- public form ---

def render_form(errors=None, values=None, status_code=200):
    return render_template(
        "form.html", errors=errors or {}, values=values or {}, enquiry_types=ENQUIRY_TYPES
    ), status_code


@app.route("/", methods=["GET", "POST"])
def enquiry_form():
    if request.method == "GET":
        return render_form()

    # honeypot: real users never fill this hidden field
    if request.form.get("website", ""):
        return render_form()

    ip = request.remote_addr or "unknown"
    if is_rate_limited(ip):
        errors = {"form": "Too many submissions. Please try again in a minute."}
        return render_form(errors, request.form, 429)

    errors = validate_enquiry(request.form)
    if errors:
        return render_form(errors, request.form, 400)

    record_submission(ip)
    conn = get_db()
    now = simulated_now(conn)
    name = request.form["name"].strip()
    email = request.form["email"].strip()
    enquiry_type = request.form["enquiry_type"]
    message = request.form["message"].strip()

    enquiry_id = db.insert_enquiry(conn, name, email, enquiry_type, message, stamp(now))
    db.insert_email(conn, enquiry_id=enquiry_id, direction="inbound", kind="enquiry",
                    to_address=mailer.from_address(), from_address=email,
                    subject=f"{enquiry_type} enquiry", body=message,
                    sent_at=stamp(now), status="received")
    status, _ = send_confirmation_email(conn, enquiry_id, name, email, enquiry_type, now)
    session["last_confirmation"] = {"email": email, "status": status}
    return redirect(url_for("thanks"))


@app.route("/thanks")
def thanks():
    return render_template("thanks.html", confirmation=session.pop("last_confirmation", None))


# --- staff ---

def with_flags(row, now):
    enquiry = dict(row)
    enquiry["follow_up_due"] = is_follow_up_due(row, now)
    return enquiry


@app.route("/staff")
def staff():
    conn = get_db()
    now = simulated_now(conn)
    current = request.args.get("filter", "All")
    if current not in STATUS_FILTERS:
        current = "All"
    enquiries = [with_flags(row, now) for row in db.list_enquiries(conn)]
    follow_up_count = sum(1 for e in enquiries if e["follow_up_due"])
    if current == "Follow-up due":
        enquiries = [e for e in enquiries if e["follow_up_due"]]
    elif current != "All":
        enquiries = [e for e in enquiries if e["status"] == current]
    # overdue first; the sort is stable so newest-first holds within each group
    enquiries.sort(key=lambda e: not e["follow_up_due"])
    return render_template(
        "staff.html",
        enquiries=enquiries,
        follow_up_count=follow_up_count,
        simulated_now=now,
        day_offset=db.get_day_offset(conn),
        statuses=STATUSES,
        filters=STATUS_FILTERS,
        current_filter=current,
    )


def get_enquiry_or_404(conn, enquiry_id):
    row = db.get_enquiry(conn, enquiry_id)
    if row is None:
        abort(404, "That enquiry doesn't exist (demo data is deleted after 24 hours).")
    return row


def default_reply(enquiry):
    return {
        "subject": f"Re: Your {enquiry['type']} enquiry",
        "body": f"Hi {enquiry['name']},\n\n\n\nBest regards,\nClubhouse",
    }


def render_detail(conn, row, values, errors=None, status_code=200):
    replies_used = db.count_replies(conn, row["id"])
    return render_template(
        "detail.html",
        enquiry=with_flags(row, simulated_now(conn)),
        messages=db.list_conversation(conn, row["id"]),
        statuses=STATUSES,
        values=values,
        errors=errors or {},
        replies_left=max(0, MAX_REPLIES_PER_ENQUIRY - replies_used),
        max_replies=MAX_REPLIES_PER_ENQUIRY,
        reply_to=mailer.reply_to_address(),
        subject_max=REPLY_SUBJECT_MAX_LEN,
        body_max=REPLY_BODY_MAX_LEN,
        footer=mailer.FOOTER,
    ), status_code


@app.route("/staff/<int:enquiry_id>")
def enquiry_detail(enquiry_id):
    conn = get_db()
    row = get_enquiry_or_404(conn, enquiry_id)
    return render_detail(conn, row, default_reply(row))


@app.route("/staff/<int:enquiry_id>/status", methods=["POST"])
def update_status(enquiry_id):
    conn = get_db()
    get_enquiry_or_404(conn, enquiry_id)
    status = request.form.get("status", "")
    if status not in STATUSES:
        abort(400, f"'{status}' is not a valid status. Choose one of: {', '.join(STATUSES)}.")
    db.set_status(conn, enquiry_id, status, stamp(simulated_now(conn)))
    return redirect(safe_next(request.form.get("next")))


@app.route("/staff/<int:enquiry_id>/reply", methods=["POST"])
def reply(enquiry_id):
    conn = get_db()
    row = get_enquiry_or_404(conn, enquiry_id)
    values = {
        "subject": request.form.get("subject", "").strip(),
        "body": request.form.get("body", "").strip(),
    }
    errors = validate_reply(values)
    if not errors and db.count_replies(conn, enquiry_id) >= MAX_REPLIES_PER_ENQUIRY:
        errors["form"] = f"This enquiry already has {MAX_REPLIES_PER_ENQUIRY} replies, the most this demo allows."
    if errors:
        return render_detail(conn, row, values, errors, 400)

    now = simulated_now(conn)
    # always the address that submitted the enquiry: staff can't choose a recipient
    status, error = send_email(conn, enquiry_id=enquiry_id, kind="reply",
                               to_address=row["email"], subject=values["subject"],
                               body=values["body"], now=now)
    if status in ("sent", "simulated"):
        if row["status"] not in ("Booked", "Closed"):
            db.set_status(conn, enquiry_id, "Awaiting reply", stamp(now))
        if status == "sent":
            flash(f"Reply sent to {row['email']}.")
        else:
            flash(f"Reply saved as SIMULATED ({mailer.simulated_reason()}), not really sent.")
        return redirect(url_for("enquiry_detail", enquiry_id=enquiry_id))

    errors = {"form": f"Your reply was not sent: {error} Your text is kept below."}
    return render_detail(conn, row, values, errors, 502 if status == "failed" else 429)


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
    return render_template("emails.html", emails=db.list_emails(conn))


# --- CLI ---

@app.cli.command("seed")
def seed_command():
    """Insert made-up enquiries covering every status, with a few conversations."""
    from seed import run_seed

    conn = db.get_connection()
    db.init_db(conn)
    run_seed(conn)
    conn.close()
    print("Seeded database with demo enquiries.")


@app.cli.command("test-email")
def test_email_command():
    """Send one test message over SMTP and print success or the exact error."""
    reason = mailer.simulated_reason()
    if reason:
        print(f"Not sending: {reason}. Set SMTP_HOST, SMTP_PORT, SMTP_USER and SMTP_PASSWORD in .env.")
        raise SystemExit(1)
    if not os.environ.get("SMTP_PASSWORD", "").strip():
        print("SMTP_PASSWORD is empty.")
        raise SystemExit(1)
    try:
        mailer.send(TEST_EMAIL_RECIPIENT, "Clubhouse SMTP test",
                    mailer.with_footer("This is a test message from the Clubhouse enquiry app."))
    except (smtplib.SMTPException, OSError) as exc:
        print(f"FAILED: {mailer.describe_error(exc)}")
        raise SystemExit(1)
    print(f"Sent a test email to {TEST_EMAIL_RECIPIENT} from {mailer.from_address()}.")


with app.app_context():
    db.init_db(get_db())


if __name__ == "__main__":
    app.run(debug=True)
