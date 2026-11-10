"""SQLite helpers. One connection per request, row access by column name."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "enquiries.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS enquiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    type TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'New',
    created_at TEXT NOT NULL,
    contacted_at TEXT
);

CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    to_address TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    delivery TEXT NOT NULL DEFAULT 'Logged only'
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def get_connection(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    # databases created before delivery status was tracked lack this column
    email_columns = [row["name"] for row in conn.execute("PRAGMA table_info(emails)")]
    if "delivery" not in email_columns:
        conn.execute(
            "ALTER TABLE emails ADD COLUMN delivery TEXT NOT NULL DEFAULT 'Logged only'"
        )
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


def insert_enquiry(conn, name, email, enquiry_type, message, created_at):
    cur = conn.execute(
        """INSERT INTO enquiries (name, email, type, message, status, created_at)
           VALUES (?, ?, ?, ?, 'New', ?)""",
        (name, email, enquiry_type, message, created_at),
    )
    conn.commit()
    return cur.lastrowid


def insert_email(conn, to_address, subject, body, sent_at, delivery="Logged only"):
    conn.execute(
        """INSERT INTO emails (to_address, subject, body, sent_at, delivery)
           VALUES (?, ?, ?, ?, ?)""",
        (to_address, subject, body, sent_at, delivery),
    )
    conn.commit()


def list_enquiries(conn):
    return conn.execute(
        "SELECT * FROM enquiries ORDER BY created_at DESC, id DESC"
    ).fetchall()


def list_emails(conn):
    return conn.execute(
        "SELECT * FROM emails ORDER BY sent_at DESC, id DESC"
    ).fetchall()


def get_enquiry(conn, enquiry_id):
    return conn.execute(
        "SELECT * FROM enquiries WHERE id = ?", (enquiry_id,)
    ).fetchone()


def mark_contacted(conn, enquiry_id, contacted_at):
    conn.execute(
        "UPDATE enquiries SET status = 'Contacted', contacted_at = ? WHERE id = ?",
        (contacted_at, enquiry_id),
    )
    conn.commit()
