# Clubhouse Enquiry Demo

A small Flask + SQLite app for handling golf club enquiries (membership, society days, events), with a staff page to track and follow up on them. Built as a take-home task — made-up data only.

## 1. How to run it

Requires Python 3.11+.

```bash
# set up
python -m venv .venv
source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# seed some demo data (optional but recommended)
export FLASK_APP=app.py         # Windows: set FLASK_APP=app.py
flask seed
# or: python seed.py

# run
flask run
# or: python app.py

# tests
pytest
```

Then visit `http://127.0.0.1:5000/` for the enquiry form and `http://127.0.0.1:5000/staff` for the staff view.

**Optional: send real confirmation emails.** Set `SMTP_HOST`, `SMTP_PORT` (default 587, STARTTLS), `SMTP_USER`, `SMTP_PASSWORD` and optionally `SMTP_FROM` before running, and confirmations are also delivered over SMTP (e.g. Gmail with an app password). Submitting with a disposable address like `test@yopmail.com` lets you check delivery at yopmail.com. Without `SMTP_HOST`, emails are only logged and stored as before; an SMTP failure never loses the enquiry.

## 2. Main decisions I made

- **Flask + SQLite (stdlib `sqlite3`)**: the task is small and single-user (no concurrent writers to worry about), so a zero-config file database avoids any setup friction while still forcing me to write real parameterised SQL rather than hiding it behind an ORM. Flask keeps routing, templating, and validation visible and easy to talk through line by line.
- **A stored "day offset" instead of mocking the real clock**: the follow-up rule is time-based ("2+ days since submission"), but a demo needs to show that rule working *now*, not two days from now. Rather than faking `datetime.now()` throughout the app, I store a single offset in a `settings` table and compute `simulated_now = real_now + offset`. Everything (saving enquiries, checking follow-ups, marking contacted) uses this one simulated clock, and `is_follow_up_due(enquiry, now)` takes `now` as a parameter so the rule itself is pure and trivially testable without touching the database or the clock at all.
- **Emails are logged and stored, not actually sent**: real SMTP needs credentials and an external service, which is unnecessary risk and noise for a take-home. Printing to the console shows the "send" happening in real time, and writing to an `emails` table means the result is inspectable and persistent — both are useful for an interview walkthrough and for the "Mark as Contacted" flow to feel real.

## 3. What I'd build next

- Real email sending (e.g. via an SMTP provider or a transactional email API), with retry/failure handling.
- A scheduled job (cron, or a worker queue) that periodically scans for follow-ups due and notifies staff, instead of computing it on page load.
- Staff logins and roles, so the `/staff` page isn't open to anyone who finds the URL.
- Multi-club support: one deployment serving several clubs, each with its own branding and enquiry list.
- An audit log of who contacted whom and when, beyond just the single `contacted_at` timestamp.
- Pagination/search/filtering on the staff table once enquiry volume grows.

## 4. AI tools used and how

> _(Placeholder — fill in honestly: which AI tools you used, for what parts, and how you reviewed/edited the output.)_

## 5. Adding this form to a golf club's existing website (WordPress or Wix)

This section explains the approach only — nothing here needs building.

**What the club or its web person does:** nothing to the club's own site's code. The enquiry form stays hosted on its own small server (this app), and the club embeds it with either an `<iframe src="https://enquiries.exampleclub.com/">` pointed at the hosted form, or a one-line script snippet that injects the same thing. Both WordPress and Wix support dropping in a raw HTML/embed block, so no plugin development or site rebuild is needed.

**How it matches the club's colours and works on phones:** the stylesheet defines its palette as CSS variables (`--brand`, `--accent`, etc.) at the top of `style.css`, so retheming is a handful of value changes. For an embedded iframe, the hosted form can also read optional URL query parameters (e.g. `?brand=%231b4332&accent=%23d4af37`) and apply them as inline style overrides, so each club's embed URL can carry its own colours without touching the shared codebase. The layout is already responsive (fluid widths, a mobile viewport meta tag, large tap targets), so it holds up at phone width inside an iframe just as it does standalone.

**Keeping it simple for enquirers and protected from spam:** the form only asks for name, email, enquiry type, and a message — no account, no unnecessary fields. Spam protection is layered: a hidden honeypot field (bots tend to fill every input, humans never see it), a per-IP rate limit (max 5 submissions/minute) to blunt scripted abuse, and if spam becomes a real problem in practice, a CAPTCHA (e.g. hCaptcha/Turnstile) can be added to the form without changing anything else about the flow.

**What happens if the club redesigns its website:** since the form is hosted separately and only *embedded*, a full site redesign doesn't break it — the new site just needs the same iframe/snippet dropped into wherever the "Contact" or "Enquiries" page now lives. The only work is finding the new embed location, not rebuilding the form, its validation, or its data.
