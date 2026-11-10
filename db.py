"""SQLite helpers. One connection per request, row access by column name."""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "enquiries.db"

# created_at / sent_at use the app's simulated clock (for the follow-up demo).
# inserted_at is always real wall-clock time: used for email caps and the 24h purge,
# so "Advance 1 day" can't reset a cap or delete fresh data.
SCHEMA = """
CREATE TABLE IF NOT EXISTS enquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    type TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'New',
    created_at TEXT NOT NULL,
    contacted_at TEXT,
    status_changed_at TEXT,
    inserted_at TEXT
);

CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enquiry_id INTEGER,
    direction TEXT NOT NULL DEFAULT 'outbound',
    kind TEXT NOT NULL DEFAULT 'confirmation',
    to_address TEXT NOT NULL,
    from_address TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'simulated',
    error TEXT,
    inserted_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# columns added after the first release; older databases get them on startup
MIGRATIONS = [
    ("enquiries", "status_changed_at", "TEXT"),
    ("enquiries", "inserted_at", "TEXT"),
    ("emails", "enquiry_id", "INTEGER"),
    ("emails", "direction", "TEXT NOT NULL DEFAULT 'outbound'"),
    ("emails", "kind", "TEXT NOT NULL DEFAULT 'confirmation'"),
    ("emails", "from_address", "TEXT NOT NULL DEFAULT ''"),
    ("emails", "status", "TEXT NOT NULL DEFAULT 'simulated'"),
    ("emails", "error", "TEXT"),
    ("emails", "inserted_at", "TEXT"),
]


def real_now():
    return datetime.now().isoformat(timespec="seconds")


def get_connection(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def init_db(conn):
    conn.executescript(SCHEMA)
    added = set()
    for table, column, ddl in MIGRATIONS:
        if column not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            added.add((table, column))

    # backfill migrated rows
    conn.execute(
        "UPDATE enquiries SET status_changed_at = COALESCE(contacted_at, created_at) "
        "WHERE status_changed_at IS NULL"
    )
    if ("emails", "status") in added and "delivery" in _columns(conn, "emails"):
        # the previous version kept a free-text 'delivery' column
        conn.execute("UPDATE emails SET status = 'sent' WHERE delivery LIKE 'Sent%'")
        conn.execute(
            "UPDATE emails SET status = 'failed', error = substr(delivery, 9) "
            "WHERE delivery LIKE 'Failed:%'"
        )
    conn.execute("UPDATE enquiries SET inserted_at = ? WHERE inserted_at IS NULL", (real_now(),))
    conn.execute("UPDATE emails SET inserted_at = ? WHERE inserted_at IS NULL", (real_now(),))

    # simulated day offset starts at 0 (= real "now")
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('day_offset', '0')"
    )
    conn.commit()


def get_day_offset(conn):
    row = conn.execute("SELECT value FROM settings WHERE key = 'day_offset'").fetchone()
    return int(row["value"]) if row else 0


def set_day_offset(conn, offset):
    conn.execute(
        "UPDATE settings SET value = ? WHERE key = 'day_offset'", (str(offset),)
    )
    conn.commit()


def insert_enquiry(conn, name, email, enquiry_type, message, created_at, status="New"):
    cur = conn.execute(
        """INSERT INTO enquiries
               (name, email, type, message, status, created_at, status_changed_at, inserted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, email, enquiry_type, message, status, created_at, created_at, real_now()),
    )
    conn.commit()
    return cur.lastrowid


def insert_email(conn, *, enquiry_id, direction, kind, to_address, from_address,
                 subject, body, sent_at, status, error=None):
    cur = conn.execute(
        """INSERT INTO emails (enquiry_id, direction, kind, to_address, from_address,
                               subject, body, sent_at, status, error, inserted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (enquiry_id, direction, kind, to_address, from_address,
         subject, body, sent_at, status, error, real_now()),
    )
    conn.commit()
    return cur.lastrowid


def list_enquiries(conn):
    return conn.execute(
        "SELECT * FROM enquiries ORDER BY created_at DESC, id DESC"
    ).fetchall()


def count_enquiries(conn):
    return conn.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0]


def list_emails(conn):
    return conn.execute(
        """SELECT emails.*, enquiries.name AS enquiry_name
           FROM emails LEFT JOIN enquiries ON enquiries.id = emails.enquiry_id
           ORDER BY emails.sent_at DESC, emails.id DESC"""
    ).fetchall()


def list_conversation(conn, enquiry_id):
    return conn.execute(
        "SELECT * FROM emails WHERE enquiry_id = ? ORDER BY sent_at, id",
        (enquiry_id,),
    ).fetchall()


def get_enquiry(conn, enquiry_id):
    return conn.execute(
        "SELECT * FROM enquiries WHERE id = ?", (enquiry_id,)
    ).fetchone()


def set_status(conn, enquiry_id, status, changed_at):
    """Change status; status_changed_at only moves when the status really changes."""
    conn.execute(
        """UPDATE enquiries
           SET status = ?, status_changed_at = ?,
               contacted_at = CASE WHEN ? = 'New' THEN contacted_at
                                   ELSE COALESCE(contacted_at, ?) END
           WHERE id = ? AND status != ?""",
        (status, changed_at, status, changed_at, enquiry_id, status),
    )
    conn.commit()


def count_real_emails_today(conn, to_address=None):
    """Emails actually sent over SMTP today (real calendar day), optionally to one address."""
    sql = ("SELECT COUNT(*) FROM emails WHERE direction = 'outbound' AND status = 'sent' "
           "AND substr(inserted_at, 1, 10) = ?")
    params = [real_now()[:10]]
    if to_address is not None:
        sql += " AND lower(to_address) = lower(?)"
        params.append(to_address)
    return conn.execute(sql, params).fetchone()[0]


def count_replies(conn, enquiry_id):
    """Replies that went out (or were simulated) for one enquiry; failures don't count."""
    return conn.execute(
        "SELECT COUNT(*) FROM emails WHERE enquiry_id = ? AND kind = 'reply' "
        "AND status IN ('sent', 'simulated')",
        (enquiry_id,),
    ).fetchone()[0]


def purge_older_than(conn, cutoff):
    """Delete enquiries and emails stored before `cutoff` (real time, ISO string)."""
    conn.execute("DELETE FROM enquiries WHERE inserted_at < ?", (cutoff,))
    conn.execute(
        "DELETE FROM emails WHERE inserted_at < ? "
        "OR (enquiry_id IS NOT NULL AND enquiry_id NOT IN (SELECT id FROM enquiries))",
        (cutoff,),
    )
    conn.commit()
