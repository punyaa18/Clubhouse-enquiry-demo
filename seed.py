"""Inserts made-up enquiries covering every status, at different ages, with a few
conversations, so follow-up flags and the reply thread show immediately.
Run with: flask seed  (or: python seed.py). The app also runs this when the database is empty.
"""
from datetime import datetime, timedelta

import db
import mailer

# name, email, type, message, days ago, status, [(days after enquiry, staff reply)]
DEMO_ENQUIRIES = [
    ("Alice Brennan", "alice.brennan@example.com", "Membership",
     "Hi, I'd like to enquire about full membership rates for next season.", 0, "New", []),
    ("Tom O'Carroll", "tom.ocarroll@example.com", "Society day",
     "We're looking to book a society day for 24 golfers in June.", 1, "New", []),
    ("Fiona Walsh", "fiona.walsh@example.com", "Event",
     "Could you tell me about hosting a 40th birthday party at the clubhouse?", 3, "New", []),
    ("Declan Murphy", "declan.murphy@example.com", "Membership",
     "What's included in junior membership this year?", 5, "Contacted", []),
    ("Grace Kelly", "grace.kelly@example.com", "Society day",
     "Enquiring about a corporate golf day for 16 people in September.", 2, "Awaiting reply",
     [(1, "Thanks for getting in touch. September works well - could you let us know "
          "your preferred date and whether you'd like lunch included?")]),
    ("Liam Fitzgerald", "liam.fitzgerald@example.com", "Event",
     "Do you cater for wedding receptions on site?", 7, "Booked",
     [(1, "Yes, we cater for receptions of up to 120 guests. Would you like to visit "
          "for a tour?"),
      (3, "Great to meet you both today. Your date of 14 August is now confirmed.")]),
    ("Niamh Byrne", "niamh.byrne@example.com", "Membership",
     "Is there a waiting list for family membership?", 6, "Closed",
     [(1, "There's no waiting list at the moment - the application form is attached "
          "on our website. Let us know if you have any questions.")]),
]


def confirmation_for(name, enquiry_type):
    subject = f"We received your {enquiry_type} enquiry"
    body = (f"Hi {name},\n\nThanks for your {enquiry_type} enquiry. A member of our team "
            f"will be in touch soon.\n\nClubhouse")
    return subject, mailer.with_footer(body)


def run_seed(conn):
    now = datetime.now()
    club = mailer.from_address()
    for name, email, enquiry_type, message, days_ago, status, replies in DEMO_ENQUIRIES:
        created = now - timedelta(days=days_ago)
        stamp = created.isoformat(timespec="seconds")
        enquiry_id = db.insert_enquiry(conn, name, email, enquiry_type, message, stamp, status)
        db.insert_email(conn, enquiry_id=enquiry_id, direction="inbound", kind="enquiry",
                        to_address=club, from_address=email,
                        subject=f"{enquiry_type} enquiry", body=message,
                        sent_at=stamp, status="received")
        subject, body = confirmation_for(name, enquiry_type)
        db.insert_email(conn, enquiry_id=enquiry_id, direction="outbound", kind="confirmation",
                        to_address=email, from_address=club, subject=subject, body=body,
                        sent_at=stamp, status="simulated")
        for days_after, text in replies:
            sent = (created + timedelta(days=days_after)).isoformat(timespec="seconds")
            db.insert_email(conn, enquiry_id=enquiry_id, direction="outbound", kind="reply",
                            to_address=email, from_address=club,
                            subject=f"Re: Your {enquiry_type} enquiry",
                            body=mailer.with_footer(f"Hi {name},\n\n{text}\n\nBest regards,\nClubhouse"),
                            sent_at=sent, status="simulated")


if __name__ == "__main__":
    connection = db.get_connection()
    db.init_db(connection)
    run_seed(connection)
    connection.close()
    print("Seeded database with demo enquiries.")
