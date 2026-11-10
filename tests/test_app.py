import sqlite3
from datetime import datetime, timedelta

import db
import mailer
from conftest import CSRF

VALID_FORM = {
    "name": "Alice Brennan",
    "email": "alice@example.com",
    "enquiry_type": "Membership",
    "message": "Hello, enquiring about membership.",
    "website": "",
    "csrf_token": CSRF,
}


def submit(client, **overrides):
    return client.post("/", data={**VALID_FORM, **overrides})


def outbound(conn):
    return [e for e in db.list_emails(conn) if e["direction"] == "outbound"]


def make_enquiry(client, conn, **overrides):
    submit(client, **overrides)
    return db.list_enquiries(conn)[0]


def reply(client, enquiry_id, **fields):
    data = {"subject": "Re: Your Membership enquiry", "body": "Hi Alice, happy to help.",
            "csrf_token": CSRF, **fields}
    return client.post(f"/staff/{enquiry_id}/reply", data=data)


# --- enquiry form ---

def test_rejects_bad_email(client):
    response = submit(client, email="not-an-email")
    assert response.status_code == 400
    assert b"valid email" in response.data


def test_rejects_empty_fields(client):
    response = client.post("/", data={"name": "", "email": "", "enquiry_type": "",
                                      "message": "", "website": "", "csrf_token": CSRF})
    assert response.status_code == 400
    assert b"Please enter your name" in response.data


def test_honeypot_filled_submission_is_rejected(client, conn):
    response = submit(client, website="http://spam.example.com")
    assert response.status_code == 200
    assert len(db.list_enquiries(conn)) == 0
    assert len(db.list_emails(conn)) == 0


def test_missing_csrf_token_rejected(client, conn):
    response = client.post("/", data={**VALID_FORM, "csrf_token": ""})
    assert response.status_code == 400
    assert len(db.list_enquiries(conn)) == 0


def test_rate_limit_five_per_minute(client):
    for i in range(5):
        assert submit(client, email=f"user{i}@example.com").status_code == 302
    assert submit(client).status_code == 429


def test_header_injection_in_name_rejected(client, conn, fake_sender):
    response = submit(client, name="Alice\r\nBcc: victim@example.com")
    assert response.status_code == 400
    assert b"line breaks" in response.data
    assert fake_sender.sent == []


def test_header_injection_in_email_rejected(client, conn, fake_sender):
    response = submit(client, email="alice@example.com\nBcc: victim@example.com")
    assert response.status_code == 400
    assert fake_sender.sent == []


def test_user_text_is_escaped(client, conn):
    submit(client, name="<script>alert(1)</script>")
    page = client.get("/staff").data
    assert b"<script>alert(1)</script>" not in page
    assert b"&lt;script&gt;" in page


def test_privacy_notice_on_form(client):
    assert b"Please use a throwaway address" in client.get("/").data


# --- confirmation emails ---

def test_confirmation_sent_to_entered_address(client, conn, fake_sender):
    response = submit(client, email="punyaa@yopmail.com")

    assert response.status_code == 302
    assert len(fake_sender.sent) == 1
    sent = fake_sender.sent[0]
    assert sent["to"] == "punyaa@yopmail.com"
    assert sent["subject"] == "We received your Membership enquiry"
    assert mailer.FOOTER in sent["body"]
    stored = outbound(conn)[0]
    assert stored["status"] == "sent" and stored["to_address"] == "punyaa@yopmail.com"
    assert b"emailed a confirmation" in client.get("/thanks").data


def test_any_valid_address_accepted(client, conn, fake_sender):
    for address in ["someone@gmail.com", "first.last+tag@sub.example.co.uk"]:
        assert submit(client, email=address).status_code == 302
    assert [s["to"] for s in fake_sender.sent] == ["someone@gmail.com",
                                                   "first.last+tag@sub.example.co.uk"]


def test_visitor_cannot_choose_email_content(client, fake_sender):
    submit(client, subject="Buy now", body="spam")
    assert fake_sender.sent[0]["subject"] == "We received your Membership enquiry"
    assert "spam" not in fake_sender.sent[0]["body"]


def test_simulated_when_smtp_not_configured(client, conn):
    submit(client)
    stored = outbound(conn)[0]
    assert stored["status"] == "simulated"
    assert b"SIMULATED, not really sent" in client.get("/thanks").data


def test_kill_switch_forces_simulated(client, conn, fake_sender, monkeypatch):
    monkeypatch.setenv("EMAILS_ENABLED", "false")
    submit(client)
    assert fake_sender.sent == []
    assert outbound(conn)[0]["status"] == "simulated"
    assert b"EMAILS_ENABLED=false" in client.get("/staff").data


def test_failed_send_stored_with_error_and_enquiry_kept(client, conn, fake_sender, auth_error):
    fake_sender.error = auth_error
    response = submit(client)

    assert response.status_code == 302
    assert len(db.list_enquiries(conn)) == 1
    stored = outbound(conn)[0]
    assert stored["status"] == "failed"
    assert "SMTPAuthenticationError" in stored["error"] and "535" in stored["error"]
    assert b"SMTPAuthenticationError" in client.get("/staff/emails").data


def test_error_text_never_contains_password(app_module, monkeypatch):
    monkeypatch.setenv("SMTP_PASSWORD", "abcd efgh ijkl mnop")
    text = mailer.describe_error(OSError("login abcdefghijklmnop failed"))
    assert "abcdefghijklmnop" not in text
    assert "[hidden]" in text


def test_daily_cap(client, conn, fake_sender, monkeypatch):
    monkeypatch.setenv("MAX_EMAILS_PER_DAY", "1")
    submit(client, email="one@example.com")
    response = submit(client, email="two@example.com")

    assert response.status_code == 302
    assert len(fake_sender.sent) == 1
    assert len(db.list_enquiries(conn)) == 2
    assert outbound(conn)[0]["status"] == "skipped"
    assert b"reached its email limit" in client.get("/thanks").data


def test_per_recipient_cap(client, conn, fake_sender):
    for _ in range(3):
        submit(client, email="same@example.com")

    assert len(fake_sender.sent) == 2
    assert len(db.list_enquiries(conn)) == 3
    assert [e["status"] for e in outbound(conn)] == ["skipped", "sent", "sent"]


def test_caps_ignore_simulated_clock(client, conn, fake_sender):
    submit(client, email="same@example.com")
    submit(client, email="same@example.com")
    client.post("/staff/advance-day", data={"csrf_token": CSRF})
    submit(client, email="same@example.com")
    assert len(fake_sender.sent) == 2


def test_smtp_send_uses_starttls_reply_to_and_strips_password_spaces(app_module, monkeypatch):
    log = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            log.append(("connect", host, port))
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def starttls(self):
            log.append("starttls")
        def login(self, user, password):
            log.append(("login", user, password))
        def send_message(self, msg):
            log.append(msg)

    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "punyaa184@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)

    mailer.send("someone@yopmail.com", "Subject", "Body")

    msg = log[-1]
    assert log[:3] == [("connect", "smtp.gmail.com", 587), "starttls",
                       ("login", "punyaa184@gmail.com", "abcdefghijklmnop")]
    assert msg["From"] == "punyaa184@gmail.com"
    assert msg["Reply-To"] == "punyaa184@gmail.com"
    assert msg.get_content_type() == "text/plain"


def test_test_email_command_reports_missing_config(app_module):
    result = app_module.app.test_cli_runner().invoke(args=["test-email"])
    assert result.exit_code == 1
    assert "SMTP is not configured" in result.output


def test_test_email_command_sends_to_yopmail(app_module, fake_sender):
    result = app_module.app.test_cli_runner().invoke(args=["test-email"])
    assert result.exit_code == 0
    assert fake_sender.sent[0]["to"] == "punyaa@yopmail.com"


# --- status ---

def test_status_change_saved_with_timestamp(client, conn):
    enquiry = make_enquiry(client, conn)
    client.post("/staff/advance-day", data={"csrf_token": CSRF})

    response = client.post(f"/staff/{enquiry['id']}/status",
                           data={"status": "Booked", "next": "/staff", "csrf_token": CSRF})

    assert response.status_code == 302
    updated = db.get_enquiry(conn, enquiry["id"])
    assert updated["status"] == "Booked"
    assert updated["status_changed_at"] > enquiry["status_changed_at"]


def test_invalid_status_rejected(client, conn):
    enquiry = make_enquiry(client, conn)
    response = client.post(f"/staff/{enquiry['id']}/status",
                           data={"status": "Deleted", "csrf_token": CSRF})
    assert response.status_code == 400
    assert b"not a valid status" in response.data
    assert db.get_enquiry(conn, enquiry["id"])["status"] == "New"


def test_status_change_needs_csrf(client, conn):
    enquiry = make_enquiry(client, conn)
    response = client.post(f"/staff/{enquiry['id']}/status", data={"status": "Closed"})
    assert response.status_code == 400
    assert db.get_enquiry(conn, enquiry["id"])["status"] == "New"


def test_status_redirect_stays_on_site(client, conn):
    enquiry = make_enquiry(client, conn)
    response = client.post(f"/staff/{enquiry['id']}/status",
                           data={"status": "Closed", "next": "https://evil.example/", "csrf_token": CSRF})
    assert response.headers["Location"].endswith("/staff")


def test_follow_up_badge_cleared_by_status_change(client, conn):
    enquiry = make_enquiry(client, conn)
    db.set_day_offset(conn, 3)
    assert b"Follow-up due</span>" in client.get("/staff").data

    client.post(f"/staff/{enquiry['id']}/status", data={"status": "Contacted", "csrf_token": CSRF})

    assert b"Follow-up due</span>" not in client.get("/staff").data


def seed_rows(conn):
    from seed import run_seed

    run_seed(conn)


def test_filters_and_overdue_first(client, conn):
    seed_rows(conn)
    page = client.get("/staff").data.decode()
    # Fiona (3 days, New) is overdue and listed above Alice (today) despite being older
    assert page.index("Fiona Walsh") < page.index("Alice Brennan")

    due = client.get("/staff?filter=Follow-up+due").data.decode()
    assert "Fiona Walsh" in due and "Alice Brennan" not in due

    booked = client.get("/staff?filter=Booked").data.decode()
    assert "Liam Fitzgerald" in booked and "Fiona Walsh" not in booked


def test_seed_covers_every_status(app_module, conn):
    seed_rows(conn)
    statuses = {row["status"] for row in db.list_enquiries(conn)}
    assert statuses == set(app_module.STATUSES)


def test_migrates_old_database(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE enquiries (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT NOT NULL, type TEXT NOT NULL, message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'New', created_at TEXT NOT NULL, contacted_at TEXT);
        CREATE TABLE emails (id INTEGER PRIMARY KEY AUTOINCREMENT, to_address TEXT NOT NULL,
            subject TEXT NOT NULL, body TEXT NOT NULL, sent_at TEXT NOT NULL,
            delivery TEXT NOT NULL DEFAULT 'Logged only');
        INSERT INTO enquiries (name, email, type, message, status, created_at, contacted_at)
            VALUES ('Old', 'old@example.com', 'Event', 'Hi', 'Contacted', '2026-01-01T10:00:00', '2026-01-02T10:00:00');
        INSERT INTO emails (to_address, subject, body, sent_at, delivery)
            VALUES ('old@example.com', 'S', 'B', '2026-01-01T10:00:00', 'Failed: SMTPAuthenticationError: 535');
    """)
    old.commit()
    old.close()

    conn = db.get_connection(path)
    db.init_db(conn)

    enquiry = db.list_enquiries(conn)[0]
    assert enquiry["status"] == "Contacted"
    assert enquiry["status_changed_at"] == "2026-01-02T10:00:00"
    assert enquiry["inserted_at"] is not None
    email = db.list_emails(conn)[0]
    assert email["status"] == "failed"
    assert email["error"] == "SMTPAuthenticationError: 535"
    assert email["direction"] == "outbound"
    conn.close()


# --- replies ---

def test_detail_page_prefills_reply(client, conn):
    enquiry = make_enquiry(client, conn)
    page = client.get(f"/staff/{enquiry['id']}").data
    assert b"Re: Your Membership enquiry" in page
    assert b"Hi Alice Brennan," in page
    assert b"alice@example.com" in page


def test_valid_reply_sent_stored_and_status_awaiting(client, conn, fake_sender):
    enquiry = make_enquiry(client, conn)

    response = reply(client, enquiry["id"])

    assert response.status_code == 302
    sent = fake_sender.sent[-1]
    assert sent["to"] == "alice@example.com"
    assert sent["body"].startswith("Hi Alice, happy to help.")
    assert mailer.FOOTER in sent["body"]
    assert db.get_enquiry(conn, enquiry["id"])["status"] == "Awaiting reply"
    kinds = [m["kind"] for m in db.list_conversation(conn, enquiry["id"])]
    assert kinds == ["enquiry", "confirmation", "reply"]


def test_reply_always_goes_to_enquirer(client, conn, fake_sender):
    enquiry = make_enquiry(client, conn)
    reply(client, enquiry["id"], to="someone-else@example.com")
    assert fake_sender.sent[-1]["to"] == "alice@example.com"


def test_reply_keeps_booked_status(client, conn):
    enquiry = make_enquiry(client, conn)
    db.set_status(conn, enquiry["id"], "Booked", "2026-01-01T00:00:00")
    reply(client, enquiry["id"])
    assert db.get_enquiry(conn, enquiry["id"])["status"] == "Booked"


def test_empty_reply_rejected(client, conn):
    enquiry = make_enquiry(client, conn)
    response = reply(client, enquiry["id"], body="   ")
    assert response.status_code == 400
    assert b"Please write a message" in response.data


def test_over_length_reply_rejected_and_text_kept(client, conn):
    enquiry = make_enquiry(client, conn)
    response = reply(client, enquiry["id"], body="x" * 5001, subject="My subject")
    assert response.status_code == 400
    assert b"under 5,000 characters" in response.data
    assert b"My subject" in response.data


def test_reply_subject_header_injection_rejected(client, conn, fake_sender):
    enquiry = make_enquiry(client, conn)
    response = reply(client, enquiry["id"], subject="Hi\r\nBcc: victim@example.com")
    assert response.status_code == 400
    assert len(fake_sender.sent) == 1  # only the confirmation


def test_failed_reply_keeps_text_and_shows_error(client, conn, fake_sender, auth_error):
    enquiry = make_enquiry(client, conn)
    fake_sender.error = auth_error

    response = reply(client, enquiry["id"], body="Please keep this text")

    assert response.status_code == 502
    assert b"Please keep this text" in response.data
    assert b"SMTPAuthenticationError" in response.data
    assert db.get_enquiry(conn, enquiry["id"])["status"] == "New"
    assert outbound(conn)[0]["status"] == "failed"


def test_reply_subject_to_per_recipient_cap(client, conn, fake_sender):
    enquiry = make_enquiry(client, conn)  # confirmation = email 1 today
    reply(client, enquiry["id"])  # email 2
    response = reply(client, enquiry["id"], body="Third email today")

    assert response.status_code == 429
    assert b"2 emails per address per day" in response.data
    assert b"Third email today" in response.data
    assert len(fake_sender.sent) == 2


def test_max_three_replies_per_enquiry(client, conn):
    enquiry = make_enquiry(client, conn)
    for _ in range(3):
        assert reply(client, enquiry["id"]).status_code == 302
    response = reply(client, enquiry["id"])
    assert response.status_code == 400
    assert b"already has 3 replies" in response.data


def test_reply_needs_csrf(client, conn, fake_sender):
    enquiry = make_enquiry(client, conn)
    response = reply(client, enquiry["id"], csrf_token="")
    assert response.status_code == 400
    assert len(fake_sender.sent) == 1


def test_simulated_reply_labelled(client, conn):
    enquiry = make_enquiry(client, conn)
    reply(client, enquiry["id"])
    page = client.get(f"/staff/{enquiry['id']}").data
    assert b"SIMULATED" in page
    assert outbound(conn)[0]["status"] == "simulated"


# --- retention, auto-seed ---

def test_data_older_than_24_hours_deleted(client, conn):
    enquiry = make_enquiry(client, conn)
    old = (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")
    conn.execute("UPDATE enquiries SET inserted_at = ?", (old,))
    conn.execute("UPDATE emails SET inserted_at = ?", (old,))
    conn.commit()

    client.get("/staff")

    assert db.get_enquiry(conn, enquiry["id"]) is None
    assert db.list_emails(conn) == []


def test_empty_database_is_reseeded(app_module, client, conn):
    app_module.app.config["AUTO_SEED"] = True
    client.get("/")
    assert db.count_enquiries(conn) == 7
