"""Business rules kept separate from routes so they're easy to unit test."""
from datetime import datetime, timedelta

FOLLOW_UP_DAYS = 2


def is_follow_up_due(enquiry, now):
    """True if a 'New' enquiry has been waiting FOLLOW_UP_DAYS or more.

    `enquiry` is a sqlite3.Row or dict with 'status' and 'created_at'.
    `now` is passed in (not read from the clock) so this is deterministic in tests
    and respects the staff page's simulated time.
    """
    if enquiry["status"] != "New":
        return False
    created_at = datetime.fromisoformat(enquiry["created_at"])
    return now - created_at >= timedelta(days=FOLLOW_UP_DAYS)
