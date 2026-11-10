# Clubhouse Enquiry Demo

A small Flask + SQLite app for handling golf club enquiries (membership, society days, events): a public enquiry form that sends a real confirmation email, and a staff page to track each enquiry's status, spot overdue follow-ups and reply to the enquirer by email. Built as a take-home task with made-up data only.

## Try it live (real emails)

- **Live app (real emails):** _link added once the Render deployment is live_. Emails are really sent, from punyaa184@gmail.com.
- **Static demo (simulated, no emails sent):** https://punyaa18.github.io/Clubhouse-enquiry-demo/

### Try it in 2 minutes, no install

1. Open a link above and submit an enquiry. On the live app, use a throwaway inbox such as `yourname@yopmail.com` and check it at `https://yopmail.com/?yourname` (look in the spam tab too).
2. Open **Staff** and find your enquiry at the top of the list.
3. Press **Advance 1 day** twice. Your enquiry gets a **Follow-up due** badge and moves to the top.
4. Change its status with the dropdown, for example to **Contacted**. The badge disappears.
5. Click your name, write a reply and press **Send reply**. It appears in the conversation, and on the live app it arrives in your inbox.

## What it does

- **Enquiry form** with server-side validation, a honeypot field and a per-IP rate limit. Each submission gets one fixed-template confirmation email.
- **Staff list** with five statuses (New, Contacted, Awaiting reply, Booked, Closed), a dropdown that saves on change (with a Save button when JavaScript is off), and filters for each status and for "Follow-up due". Overdue enquiries are listed first.
- **Follow-up rule**: an enquiry still **New** after 2 or more days is flagged. The rule is the pure function `is_follow_up_due(enquiry, now)` in `logic.py`.
- **Simulated clock**: "Advance 1 day" and "Reset time" let you demo the 2-day rule straight away.
- **Enquiry detail page** (`/staff/<id>`) showing the whole conversation oldest first (enquiry, confirmation, replies) and a **Reply** panel. Replies are sent as real emails to the enquirer from punyaa184@gmail.com, with Reply-To set to the same address, so the enquirer's answer lands in that Gmail inbox. A successful reply moves the enquiry to "Awaiting reply" unless it is Booked or Closed.
- **Email log** (`/staff/emails`): every message in and out, each marked SENT, SIMULATED, FAILED (with the exact SMTP error), SKIPPED (a limit was reached) or RECEIVED.

## Run it locally

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

flask --app app seed             # optional: the app also seeds itself when the database is empty
flask --app app run              # http://127.0.0.1:5000/  and  /staff
pytest                           # uses a fake email sender, never Gmail
```

Without email settings the app runs in **simulated** mode: emails are stored and shown but not sent, and every page says so.

The session cookie is HTTPS-only by default. Chrome, Edge and Firefox accept it on `http://127.0.0.1`. If your browser doesn't, and forms say "This form has expired", set `SESSION_COOKIE_SECURE=0` for local use.

## Turn on real email (Gmail)

1. Turn on 2-Step Verification for the Gmail account.
2. Create an app password at https://myaccount.google.com/apppasswords.
3. Create a `.env` file next to `app.py`. It is git-ignored; never commit it.

   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your-address@gmail.com
   SMTP_PASSWORD=your16charapppassword
   # optional
   EMAILS_ENABLED=true
   MAX_EMAILS_PER_DAY=50
   ```

   Paste the app password as one 16-character string. Spaces are stripped anyway.
4. Run `flask --app app test-email`. It sends one message to `punyaa@yopmail.com` and prints success or the exact SMTP error, for example `SMTPAuthenticationError: (535, ...)`.

Mail is sent over STARTTLS on port 587, as plain text. If a send fails, the enquiry is still saved, the error is stored, and the error is shown on the Email log. The password is never printed or shown.

On a host such as Render, put the same settings in the host's environment variables instead of a `.env` file. `render.yaml` describes the service, and `Procfile` is for other Heroku-style hosts.

## Safety limits (and why)

Anyone can type any address into a public form, so without limits the app could be used to send unwanted email from the club's Gmail account. That would annoy the recipients and could get the account suspended.

- **Fixed content.** The public form sends exactly one fixed-template confirmation per submission. Visitors can't choose its subject or body.
- **Caps.** At most `MAX_EMAILS_PER_DAY` real emails per day across the whole app (default 50), and at most 2 per recipient address per day. Both caps cover confirmations and replies.
  - When a cap is hit, the enquiry is still saved and the visitor gets a friendly message instead of an email.
  - Caps use real time, so "Advance 1 day" can't reset them.
- **Replies.** A reply only ever goes to the address that submitted that enquiry, with at most 3 replies per enquiry.
  - Replies are plain text, up to 5,000 characters, with no HTML and no attachments.
  - Every email ends with the fixed footer "Sent from a demo application. If this reached you by mistake, ignore it."
- **Kill switch.** Set `EMAILS_ENABLED=false` in the host's environment to switch to simulated mode at once, without a redeploy.
- **Abuse protection.**
  - A honeypot field catches bots.
  - Each IP can submit at most 5 enquiries per minute.
  - Every form has a CSRF token.
  - Line breaks are rejected in names, subjects and addresses, which prevents email header injection.
  - All user text is escaped when shown.
- **Privacy.** The form asks for a throwaway address. Enquiries and emails older than 24 hours are deleted automatically, and the sample data is re-added whenever the database is empty.
- **Staff pages are open** for this temporary public demo, so a reviewer can try them. A real deployment would put them behind a login (see below).

## Shutting the demo down

1. Set `EMAILS_ENABLED=false` in the host's environment, or suspend the service.
2. Delete the app password at https://myaccount.google.com/apppasswords.
3. Remove the live link from this README.

## Main decisions

- **Flask + SQLite (stdlib `sqlite3`).** The task is small, so a zero-config file database avoids setup friction and still means writing real parameterised SQL rather than hiding it behind an ORM. Flask keeps routing, templating and validation visible. New columns are added by a small migration in `db.init_db`, so older databases keep working.
- **A stored "day offset" instead of mocking the clock.** The follow-up rule is time-based, but a demo needs to show it working now. One offset in a `settings` table gives `simulated_now = real_now + offset`. The rule takes `now` as a parameter, so it is pure and easy to test. Safety caps and data retention use real time.
- **Real email that degrades safely.** Without SMTP settings, or with the kill switch on, everything still works and is clearly labelled simulated. Each email's outcome is stored, so failures are visible rather than silent.
- **One table for the conversation.** Incoming enquiries, confirmations and replies all live in `emails`, with a direction, kind and status. The detail page and the log are both simple queries on that table.

## What I'd build next

- **Reading inbound replies** (IMAP polling or an inbound-mail webhook), so enquirers' answers appear in the conversation automatically.
- **Proper threading** with `Message-ID` / `In-Reply-To` headers, so replies group together in mail clients.
- **Reply templates** for common answers (prices, availability, directions).
- **Scheduled reminders**: a job that emails staff a daily list of follow-ups due, instead of computing it on page load.
- **Staff logins and roles**, plus an audit log of who changed what.
- A transactional email provider with delivery webhooks, and a real database (Postgres) for persistence.
- Multi-club support, and pagination and search once volume grows.

## Project layout

```
app.py              routes, validation, caps, CLI commands (seed, test-email)
mailer.py           SMTP sending, kill switch, error text without secrets
db.py               schema, migrations, SQL helpers
logic.py            is_follow_up_due (pure function)
seed.py             sample enquiries covering every status, with conversations
templates/          Jinja templates (form, thanks, staff, detail, emails, macros)
static/style.css    styles; club colours are CSS variables at the top
tests/              pytest suite with a fake email sender
index.html          static GitHub Pages demo (browser-only, simulated email)
render.yaml, Procfile   hosting config (gunicorn)
```

## AI tools used and how

> _(Placeholder — fill in honestly: which AI tools you used, for what parts, and how you reviewed/edited the output.)_

## Adding this form to a golf club's existing website (WordPress or Wix)

This section explains the approach only; nothing here needs building.

**What the club or its web person does:** nothing to the club's own site's code. The enquiry form stays on its own small server (this app), and the club embeds it with either an `<iframe src="https://enquiries.exampleclub.com/">` pointing at the hosted form, or a one-line script snippet that injects the same thing. Both WordPress and Wix support a raw HTML/embed block, so no plugin development or rebuild is needed. One setting changes for this: inside a cross-site iframe, the session cookie that carries the form's CSRF token must be `SameSite=None; Secure`.

**How it matches the club's colours and works on phones:** the stylesheet defines its palette as CSS variables (`--brand`, `--accent`, etc.) at the top of `style.css`, so retheming is a handful of value changes. For an embedded iframe, the hosted form can also read optional URL query parameters (e.g. `?brand=%231b4332&accent=%23d4af37`) and apply them as inline style overrides, so each club's embed URL carries its own colours without touching the shared code. The layout is already responsive (fluid widths, a mobile viewport meta tag, large tap targets), so it works at phone width inside an iframe just as it does standalone.

**Keeping it simple for enquirers and protected from spam:** the form only asks for name, email, enquiry type and a message: no account and no unnecessary fields. Spam protection is layered: the honeypot field, the per-IP rate limit, the email caps above, and, if spam becomes a real problem, a CAPTCHA (e.g. hCaptcha or Turnstile) that can be added without changing anything else about the flow.

**What happens if the club redesigns its website:** the form is hosted separately and only *embedded*, so a full redesign doesn't break it. The new site just needs the same iframe or snippet dropped wherever the "Contact" or "Enquiries" page now lives. The only work is finding the new embed location, not rebuilding the form, its validation or its data.
