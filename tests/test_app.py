import db

VALID_FORM = {
    "name": "Alice Brennan",
    "email": "alice@example.com",
    "enquiry_type": "Membership",
    "message": "Hello, enquiring about membership.",
    "website": "",
}


def test_rejects_bad_email(client):
    response = client.post("/", data={**VALID_FORM, "email": "not-an-email"})
    assert response.status_code == 400
    assert b"valid email" in response.data


def test_rejects_empty_fields(client):
    response = client.post(
        "/", data={"name": "", "email": "", "enquiry_type": "", "message": "", "website": ""}
    )
    assert response.status_code == 400
    assert b"Please enter your name" in response.data


def test_valid_submit_creates_one_enquiry_and_one_email(client, conn):
    response = client.post("/", data=VALID_FORM)
    assert response.status_code == 302

    enquiries = db.list_enquiries(conn)
    emails = db.list_emails(conn)
    assert len(enquiries) == 1
    assert len(emails) == 1
    assert enquiries[0]["status"] == "New"
    assert emails[0]["to_address"] == "alice@example.com"


def test_smtp_send_used_when_configured(client, app_module, monkeypatch):
    sent = []
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(app_module, "smtp_send", lambda *args: sent.append(args))

    client.post("/", data=VALID_FORM)

    assert len(sent) == 1
    assert sent[0][0] == "alice@example.com"


def test_smtp_failure_still_saves_enquiry(client, conn, app_module, monkeypatch):
    def failing_send(*args):
        raise OSError("connection refused")

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(app_module, "smtp_send", failing_send)

    response = client.post("/", data=VALID_FORM)

    assert response.status_code == 302
    assert len(db.list_enquiries(conn)) == 1


def test_honeypot_filled_submission_is_rejected(client, conn):
    response = client.post("/", data={**VALID_FORM, "website": "http://spam.example.com"})
    assert response.status_code == 200
    assert len(db.list_enquiries(conn)) == 0
    assert len(db.list_emails(conn)) == 0


def test_mark_contacted_changes_status_and_removes_flag(client, conn):
    client.post("/", data=VALID_FORM)
    enquiry = db.list_enquiries(conn)[0]

    db.set_day_offset(conn, 3)  # simulate enough time for a follow-up flag
    staff_before = client.get("/staff")
    assert b"Follow-up due" in staff_before.data

    client.post(f"/staff/contact/{enquiry['id']}")

    staff_after = client.get("/staff")
    assert b"Follow-up due" not in staff_after.data
    updated = db.get_enquiry(conn, enquiry["id"])
    assert updated["status"] == "Contacted"
    assert updated["contacted_at"] is not None
