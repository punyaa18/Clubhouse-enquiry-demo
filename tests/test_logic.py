from datetime import datetime, timedelta

from logic import is_follow_up_due


def test_not_due_at_one_day():
    now = datetime(2026, 1, 10)
    enquiry = {"status": "New", "created_at": (now - timedelta(days=1)).isoformat()}
    assert is_follow_up_due(enquiry, now) is False


def test_due_at_two_days():
    now = datetime(2026, 1, 10)
    enquiry = {"status": "New", "created_at": (now - timedelta(days=2)).isoformat()}
    assert is_follow_up_due(enquiry, now) is True


def test_not_due_if_contacted():
    now = datetime(2026, 1, 10)
    enquiry = {"status": "Contacted", "created_at": (now - timedelta(days=10)).isoformat()}
    assert is_follow_up_due(enquiry, now) is False


def test_only_new_enquiries_are_due():
    now = datetime(2026, 1, 10)
    old = (now - timedelta(days=10)).isoformat()
    for status in ["Contacted", "Awaiting reply", "Booked", "Closed"]:
        assert is_follow_up_due({"status": status, "created_at": old}, now) is False


def test_due_after_advancing_simulated_time():
    created_at = datetime(2026, 1, 10)
    enquiry = {"status": "New", "created_at": created_at.isoformat()}
    assert is_follow_up_due(enquiry, created_at + timedelta(days=1)) is False
    assert is_follow_up_due(enquiry, created_at + timedelta(days=2)) is True
