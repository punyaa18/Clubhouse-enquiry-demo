"""Inserts made-up enquiries at different ages so follow-up flags show immediately.
Run with: flask seed  (or: python seed.py)
"""
from datetime import datetime, timedelta

import db

DEMO_ENQUIRIES = [
    ("Alice Brennan", "alice.brennan@example.com", "Membership", "Hi, I'd like to enquire about full membership rates for next season.", 0),
    ("Tom O'Carroll", "tom.ocarroll@example.com", "Society day", "We're looking to book a society day for 24 golfers in June.", 1),
    ("Fiona Walsh", "fiona.walsh@example.com", "Event", "Could you tell me about hosting a 40th birthday party at the clubhouse?", 3),
    ("Declan Murphy", "declan.murphy@example.com", "Membership", "What's included in junior membership this year?", 5),
    ("Grace Kelly", "grace.kelly@example.com", "Society day", "Enquiring about a corporate golf day for 16 people in September.", 2),
    ("Liam Fitzgerald", "liam.fitzgerald@example.com", "Event", "Do you cater for wedding receptions on site?", 7),
]


def run_seed(conn):
    now = datetime.now()
    for name, email, enquiry_type, message, days_ago in DEMO_ENQUIRIES:
        created_at = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
        db.insert_enquiry(conn, name, email, enquiry_type, message, created_at)


if __name__ == "__main__":
    connection = db.get_connection()
    db.init_db(connection)
    run_seed(connection)
    connection.close()
    print("Seeded database with demo enquiries.")
