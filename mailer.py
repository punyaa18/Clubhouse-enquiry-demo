"""Outgoing email over SMTP, configured by environment variables (.env locally, the
host's settings in production). Nothing here ever prints or returns the password."""
import os
import smtplib
from email.message import EmailMessage

FOOTER = "Sent from a demo application. If this reached you by mistake, ignore it."


def emails_enabled():
    """Kill switch: EMAILS_ENABLED=false forces simulated mode without a redeploy."""
    value = os.environ.get("EMAILS_ENABLED", "true").strip().lower()
    return value not in ("false", "0", "no", "off")


def is_configured():
    return bool(os.environ.get("SMTP_HOST"))


def sending_for_real():
    return emails_enabled() and is_configured()


def simulated_reason():
    if not emails_enabled():
        return "real sending is switched off (EMAILS_ENABLED=false)"
    if not is_configured():
        return "SMTP is not configured"
    return None


def from_address():
    return os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "clubhouse@example.com"


def reply_to_address():
    return os.environ.get("REPLY_TO") or from_address()


def _password():
    # Google shows app passwords in groups of four; the spaces aren't part of it
    return os.environ.get("SMTP_PASSWORD", "").replace(" ", "")


def with_footer(body):
    return f"{body.rstrip()}\n\n--\n{FOOTER}"


def send(to_address, subject, body):
    """Send one plain-text email. Raises smtplib.SMTPException / OSError on failure."""
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = _password()

    msg = EmailMessage()
    msg["From"] = from_address()
    msg["To"] = to_address
    msg["Reply-To"] = reply_to_address()
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=20) as server:
        if port != 25:
            server.starttls()
        if user and password:
            server.login(user, password)
        server.send_message(msg)


def describe_error(exc):
    """Exact error text for logs and the staff page, with any secret masked."""
    text = f"{type(exc).__name__}: {exc}"
    for secret in {_password(), os.environ.get("SMTP_PASSWORD", "")}:
        if secret:
            text = text.replace(secret, "[hidden]")
    return text
