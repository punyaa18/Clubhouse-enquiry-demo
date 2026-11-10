import db
import mailer
from conftest import CSRF
from test_app import make_enquiry, outbound


def follow_up(client, enquiry_id, **fields):
    data = {"kind": "follow-up", "subject": "Following up on your enquiry",
            "body": "Hi Alice, do you still need help?", "csrf_token": CSRF, **fields}
    return client.post(f"/staff/{enquiry_id}/reply", data=data)


def set_status(client, enquiry_id, status, **fields):
    data = {"status": status, "csrf_token": CSRF, "next": f"/staff/{enquiry_id}", **fields}
    return client.post(f"/staff/{enquiry_id}/status", data=data)


def escalate(client, enquiry_id, **fields):
    return set_status(client, enquiry_id, "Escalated",
                      **{"note": "Refund request", "assigned_to": "Club manager",
                         "priority": "Urgent", **fields})


# --- follow-up ---

def test_follow_up_prefilled(client, conn):
    enquiry = make_enquiry(client, conn)
    page = client.get(f"/staff/{enquiry['id']}?compose=follow-up").data
    assert b'name="kind" value="follow-up"' in page
    assert b'value="Following up on your enquiry"' in page
    assert b"Hi Alice Brennan," in page
    assert b"your membership enquiry" in page
    assert b"Best regards,\nClubhouse" in page


def test_follow_up_button_on_overdue_rows_only(client, conn):
    make_enquiry(client, conn)
    assert b"Send follow-up</a>" not in client.get("/staff").data
    db.set_day_offset(conn, 3)
    assert b"compose=follow-up" in client.get("/staff").data


def test_follow_up_sent_stored_and_clears_flag(client, conn, fake_sender):
    enquiry = make_enquiry(client, conn, email="punyaa@yopmail.com")
    db.set_day_offset(conn, 3)
    assert b"Follow-up due</span>" in client.get("/staff").data

    response = follow_up(client, enquiry["id"])

    assert response.status_code == 302
    sent = fake_sender.sent[-1]
    assert sent["to"] == "punyaa@yopmail.com"
    assert sent["subject"] == "Following up on your enquiry"
    assert mailer.FOOTER in sent["body"]
    stored = outbound(conn)[0]
    assert (stored["kind"], stored["status"], stored["from_address"]) == \
        ("follow-up", "sent", "club@example.com")
    updated = db.get_enquiry(conn, enquiry["id"])
    assert updated["status"] == "Awaiting reply"
    assert updated["status_changed_at"] > enquiry["status_changed_at"]
    page = client.get(f"/staff/{enquiry['id']}").data  # first page view shows the flash
    assert b"Follow-up sent to punyaa@yopmail.com from club@example.com" in page
    assert b"Replies will arrive in that Gmail inbox" in page
    assert b"<strong>Follow-up</strong>" in page
    assert b"Follow-up due</span>" not in client.get("/staff").data


def test_follow_up_keeps_booked_and_closed(client, conn):
    for status in ["Booked", "Closed"]:
        enquiry = make_enquiry(client, conn, email=f"{status}@example.com")
        db.change_status(conn, enquiry["id"], status, "2026-01-01T00:00:00")
        follow_up(client, enquiry["id"])
        assert db.get_enquiry(conn, enquiry["id"])["status"] == status


def test_failed_follow_up_keeps_text(client, conn, fake_sender, auth_error):
    enquiry = make_enquiry(client, conn)
    fake_sender.error = auth_error

    response = follow_up(client, enquiry["id"], body="Retry me later")

    assert response.status_code == 502
    assert b"Retry me later" in response.data
    assert b'name="kind" value="follow-up"' in response.data
    assert b"SMTPAuthenticationError" in response.data
    stored = outbound(conn)[0]
    assert stored["kind"] == "follow-up" and stored["status"] == "failed"
    assert "535" in stored["error"]
    assert db.get_enquiry(conn, enquiry["id"])["status"] == "New"


def test_follow_up_respects_caps_and_keeps_draft(client, conn, fake_sender, monkeypatch):
    enquiry = make_enquiry(client, conn)  # confirmation: 1 email today to alice
    follow_up(client, enquiry["id"])  # 2nd: allowed
    response = follow_up(client, enquiry["id"], body="Third today")
    assert response.status_code == 429
    assert b"2 emails per address per day" in response.data
    assert b"Third today" in response.data

    monkeypatch.setenv("MAX_EMAILS_PER_DAY", "3")
    other = make_enquiry(client, conn, email="bob@example.com")  # 3rd email today overall
    response = follow_up(client, other["id"], body="Over the daily cap")
    assert response.status_code == 429
    assert b"Daily email limit reached" in response.data
    assert len(fake_sender.sent) == 3


def test_follow_ups_and_replies_share_per_enquiry_limit(client, conn):
    enquiry = make_enquiry(client, conn)
    for _ in range(5):
        assert follow_up(client, enquiry["id"]).status_code == 302
    response = follow_up(client, enquiry["id"])
    assert response.status_code == 400
    assert b"already has 5 replies and follow-ups" in response.data


def test_follow_up_needs_csrf(client, conn, fake_sender):
    enquiry = make_enquiry(client, conn)
    assert follow_up(client, enquiry["id"], csrf_token="").status_code == 400
    assert len(fake_sender.sent) == 1


def test_follow_up_simulated_when_kill_switch_on(client, conn, fake_sender, monkeypatch):
    monkeypatch.setenv("EMAILS_ENABLED", "false")
    enquiry = make_enquiry(client, conn)
    follow_up(client, enquiry["id"])
    assert fake_sender.sent == []
    assert outbound(conn)[0]["status"] == "simulated"
    assert b"Follow-up saved as SIMULATED" in client.get(f"/staff/{enquiry['id']}").data


def test_unknown_message_kind_rejected(client, conn, fake_sender):
    enquiry = make_enquiry(client, conn)
    assert follow_up(client, enquiry["id"], kind="newsletter").status_code == 400


# --- statuses and escalation ---

def test_every_valid_status_saved(app_module, client, conn):
    enquiry = make_enquiry(client, conn)
    for status in app_module.STATUSES:
        note = "Needed" if status == "Escalated" or \
            db.get_enquiry(conn, enquiry["id"])["status"] == "Escalated" else ""
        response = set_status(client, enquiry["id"], status, note=note)
        assert response.status_code == 302, status
        assert db.get_enquiry(conn, enquiry["id"])["status"] == status


def test_invalid_status_rejected(client, conn):
    enquiry = make_enquiry(client, conn)
    response = set_status(client, enquiry["id"], "On hold")
    assert response.status_code == 400
    assert b"not a valid status" in response.data


def test_escalation_without_reason_rejected_and_text_kept(client, conn):
    enquiry = make_enquiry(client, conn)
    response = escalate(client, enquiry["id"], note="   ", assigned_to="Head pro")
    assert response.status_code == 400
    assert b"Please give a reason for escalating" in response.data
    assert b'value="Head pro"' in response.data
    assert db.get_enquiry(conn, enquiry["id"])["status"] == "New"
    assert db.list_history(conn, enquiry["id"]) == []


def test_escalation_field_limits(client, conn):
    enquiry = make_enquiry(client, conn)
    assert escalate(client, enquiry["id"], note="x" * 501).status_code == 400
    assert escalate(client, enquiry["id"], assigned_to="x" * 101).status_code == 400
    assert escalate(client, enquiry["id"], priority="Critical").status_code == 400
    assert db.get_enquiry(conn, enquiry["id"])["status"] == "New"


def test_escalation_saved_with_details(client, conn):
    enquiry = make_enquiry(client, conn)
    assert escalate(client, enquiry["id"]).status_code == 302
    updated = db.get_enquiry(conn, enquiry["id"])
    assert (updated["status"], updated["escalation_reason"], updated["assigned_to"],
            updated["priority"]) == ("Escalated", "Refund request", "Club manager", "Urgent")
    page = client.get("/staff").data
    assert b"\xe2\x9a\xa0</span> Escalated" in page  # icon + text, not colour only
    assert b"Urgent</span>" in page
    assert b"Club manager" in page
    assert b"<strong>1</strong> escalated" in page


def test_leaving_escalated_needs_note(client, conn):
    enquiry = make_enquiry(client, conn)
    escalate(client, enquiry["id"])

    response = set_status(client, enquiry["id"], "Contacted")
    assert response.status_code == 400
    assert b"Please add a short note" in response.data
    assert db.get_enquiry(conn, enquiry["id"])["status"] == "Escalated"

    assert set_status(client, enquiry["id"], "Contacted", note="Refund approved").status_code == 302
    updated = db.get_enquiry(conn, enquiry["id"])
    assert updated["status"] == "Contacted"
    assert updated["escalation_reason"] is None and updated["assigned_to"] is None


def test_history_rows_written_on_each_change(client, conn):
    enquiry = make_enquiry(client, conn)
    set_status(client, enquiry["id"], "Contacted")
    escalate(client, enquiry["id"])
    set_status(client, enquiry["id"], "Booked", note="Resolved by manager")

    history = db.list_history(conn, enquiry["id"])  # newest first
    assert [(h["old_status"], h["new_status"]) for h in history] == [
        ("Escalated", "Booked"), ("Contacted", "Escalated"), ("New", "Contacted")]
    assert history[0]["note"] == "Resolved by manager"
    assert history[1]["assigned_to"] == "Club manager" and history[1]["priority"] == "Urgent"

    page = client.get(f"/staff/{enquiry['id']}").data.decode()
    assert page.count("Internal note") == 3
    assert "Resolved by manager" in page


def test_same_status_writes_no_history(client, conn):
    enquiry = make_enquiry(client, conn)
    set_status(client, enquiry["id"], "New")
    assert db.list_history(conn, enquiry["id"]) == []


def test_reply_does_not_move_escalated(client, conn):
    enquiry = make_enquiry(client, conn)
    escalate(client, enquiry["id"])
    follow_up(client, enquiry["id"])
    assert db.get_enquiry(conn, enquiry["id"])["status"] == "Escalated"


def test_escalated_listed_first_then_overdue(client, conn):
    from seed import run_seed

    run_seed(conn)
    page = client.get("/staff").data.decode()
    # Sean (escalated) above Fiona (overdue New) above Alice (today)
    assert page.index("Sean Doyle") < page.index("Fiona Walsh") < page.index("Alice Brennan")
    escalated = client.get("/staff?filter=Escalated").data.decode()
    assert "Sean Doyle" in escalated and "Fiona Walsh" not in escalated


def test_follow_up_flag_only_for_new(client, conn):
    enquiry = make_enquiry(client, conn)
    escalate(client, enquiry["id"])
    db.set_day_offset(conn, 5)
    assert b"Follow-up due</span>" not in client.get("/staff").data


def test_status_change_needs_csrf(client, conn):
    enquiry = make_enquiry(client, conn)
    assert escalate(client, enquiry["id"], csrf_token="").status_code == 400
    assert db.get_enquiry(conn, enquiry["id"])["status"] == "New"


def test_escalation_text_escaped(client, conn):
    enquiry = make_enquiry(client, conn)
    escalate(client, enquiry["id"], note="<img src=x onerror=alert(1)>")
    page = client.get(f"/staff/{enquiry['id']}").data
    assert b"<img src=x" not in page
    assert b"&lt;img src=x" in page


# --- manager notification ---

def test_no_notification_without_manager_email(client, conn, fake_sender):
    enquiry = make_enquiry(client, conn)
    escalate(client, enquiry["id"])
    assert [s["to"] for s in fake_sender.sent] == ["alice@example.com"]  # confirmation only


def test_notification_goes_to_manager_not_enquirer(client, conn, fake_sender, monkeypatch):
    monkeypatch.setenv("MANAGER_EMAIL", "manager@example.com")
    enquiry = make_enquiry(client, conn)
    escalate(client, enquiry["id"], note="Refund request\nfor double booking")

    alert = fake_sender.sent[-1]
    assert alert["to"] == "manager@example.com"
    assert alert["subject"] == "Enquiry escalated: Alice Brennan, Refund request for double booking"
    assert "\n" not in alert["subject"]
    assert [s["to"] for s in fake_sender.sent].count("alice@example.com") == 1
    assert outbound(conn)[0]["kind"] == "escalation-alert"


def test_notification_respects_caps(client, conn, fake_sender, monkeypatch):
    monkeypatch.setenv("MANAGER_EMAIL", "manager@example.com")
    monkeypatch.setenv("MAX_EMAILS_PER_DAY", "1")
    enquiry = make_enquiry(client, conn)  # uses the only email allowed today
    escalate(client, enquiry["id"])
    assert len(fake_sender.sent) == 1
    assert outbound(conn)[0]["status"] == "skipped"
    assert db.get_enquiry(conn, enquiry["id"])["status"] == "Escalated"


def test_notification_simulated_when_kill_switch_on(client, conn, fake_sender, monkeypatch):
    monkeypatch.setenv("MANAGER_EMAIL", "manager@example.com")
    monkeypatch.setenv("EMAILS_ENABLED", "false")
    enquiry = make_enquiry(client, conn)
    escalate(client, enquiry["id"])
    assert fake_sender.sent == []
    alert = outbound(conn)[0]
    assert alert["to_address"] == "manager@example.com" and alert["status"] == "simulated"


# --- migration ---

def test_migration_adds_history_and_escalation_columns(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE enquiries (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT NOT NULL, type TEXT NOT NULL, message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'New', created_at TEXT NOT NULL, contacted_at TEXT,
            status_changed_at TEXT, inserted_at TEXT);
        INSERT INTO enquiries (name, email, type, message, status, created_at)
            VALUES ('Old', 'old@example.com', 'Event', 'Hi', 'Booked', '2026-01-01T10:00:00');
    """)
    old.commit()
    old.close()

    conn = db.get_connection(path)
    db.init_db(conn)
    row = db.get_enquiry(conn, 1)
    assert row["status"] == "Booked" and row["name"] == "Old"
    assert row["escalation_reason"] is None and row["priority"] is None
    db.change_status(conn, 1, "Escalated", "2026-01-02T10:00:00", note="Check", priority="Urgent")
    assert db.list_history(conn, 1)[0]["old_status"] == "Booked"
    conn.close()
