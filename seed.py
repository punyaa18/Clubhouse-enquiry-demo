"""Inserts made-up enquiries covering every status, at different ages, with a few
conversations and status histories, so flags, escalations and threads show immediately.
Run with: flask seed  (or: python seed.py). The app also runs this when the database is empty.
"""
from datetime import datetime, timedelta

import db
import mailer

# name, email, type, message, days ago,
# status changes [(days after enquiry, new status, note, assigned to, priority)],
# staff replies [(days after enquiry, text)]
DEMO_ENQUIRIES = [
    ("Alice Brennan", "alice.brennan@example.com", "Membership",
     "Hi, I'd like to enquire about full membership rates for next season.", 0, [], []),
    ("Tom O'Carroll", "tom.ocarroll@example.com", "Society day",
     "We're looking to book a society day for 24 golfers in June.", 1, [], []),
    ("Fiona Walsh", "fiona.walsh@example.com", "Event",
     "Could you tell me about hosting a 40th birthday party at the clubhouse?", 3, [], []),
    ("Declan Murphy", "declan.murphy@example.com", "Membership",
     "What's included in junior membership this year?", 5,
     [(1, "Contacted", "Called and left a voicemail.", None, None)], []),
    ("Grace Kelly", "grace.kelly@example.com", "Society day",
     "Enquiring about a corporate golf day for 16 people in September.", 2,
     [(1, "Awaiting reply", "Automatic: reply sent to the enquirer.", None, None)],
     [(1, "Thanks for getting in touch. September works well - could you let us know "
          "your preferred date and whether you'd like lunch included?")]),
    ("Liam Fitzgerald", "liam.fitzgerald@example.com", "Event",
     "Do you cater for wedding receptions on site?", 7,
     [(1, "Awaiting reply", "Automatic: reply sent to the enquirer.", None, None),
      (3, "Booked", "Deposit paid for 14 August.", None, None)],
     [(1, "Yes, we cater for receptions of up to 120 guests. Would you like to visit "
          "for a tour?"),
      (3, "Great to meet you both today. Your date of 14 August is now confirmed.")]),
    ("Niamh Byrne", "niamh.byrne@example.com", "Membership",
     "Is there a waiting list for family membership?", 6,
     [(1, "Awaiting reply", "Automatic: reply sent to the enquirer.", None, None),
      (4, "Closed", "Joined another club.", None, None)],
     [(1, "There's no waiting list at the moment - the application form is attached "
          "on our website. Let us know if you have any questions.")]),
    ("Sean Doyle", "sean.doyle@example.com", "Society day",
     "Our society was double-booked on 3 May and turned away at the first tee. "
     "We'd like a refund of the deposit.", 2,
     [(0, "Contacted", "Apologised by phone; he wants the deposit back.", None, None),
      (1, "Escalated", "Refund request for a double booking - needs manager approval.",
       "Club manager", "Urgent")], []),
]


def confirmation_for(name, enquiry_type):
    subject = f"We received your {enquiry_type} enquiry"
    body = (f"Hi {name},\n\nThanks for your {enquiry_type} enquiry. A member of our team "
            f"will be in touch soon.\n\nClubhouse")
    return subject, mailer.with_footer(body)


def run_seed(conn):
    now = datetime.now()
    club = mailer.from_address()
    for name, email, enquiry_type, message, days_ago, changes, replies in DEMO_ENQUIRIES:
        created = now - timedelta(days=days_ago)
        stamp = created.isoformat(timespec="seconds")
        # replies land at +1h, status changes a minute later (so "reply sent" notes follow them)
        at = lambda days, minutes=0: (created + timedelta(days=days, hours=1, minutes=minutes)
                                      ).isoformat(timespec="seconds")
        enquiry_id = db.insert_enquiry(conn, name, email, enquiry_type, message, stamp)
        db.insert_email(conn, enquiry_id=enquiry_id, direction="inbound", kind="enquiry",
                        to_address=club, from_address=email,
                        subject=f"{enquiry_type} enquiry", body=message,
                        sent_at=stamp, status="received")
        subject, body = confirmation_for(name, enquiry_type)
        db.insert_email(conn, enquiry_id=enquiry_id, direction="outbound", kind="confirmation",
                        to_address=email, from_address=club, subject=subject, body=body,
                        sent_at=stamp, status="simulated")
        for days_after, text in replies:
            db.insert_email(conn, enquiry_id=enquiry_id, direction="outbound", kind="reply",
                            to_address=email, from_address=club,
                            subject=f"Re: Your {enquiry_type} enquiry",
                            body=mailer.with_footer(f"Hi {name},\n\n{text}\n\nBest regards,\nClubhouse"),
                            sent_at=at(days_after), status="simulated")
        for days_after, status, note, assigned_to, priority in changes:
            db.change_status(conn, enquiry_id, status, at(days_after, 1), note=note,
                             assigned_to=assigned_to, priority=priority)


if __name__ == "__main__":
    connection = db.get_connection()
    db.init_db(connection)
    run_seed(connection)
    connection.close()
    print("Seeded database with demo enquiries.")
