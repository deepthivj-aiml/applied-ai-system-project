"""Send a one-time case ID receipt when an owner reports a lost dog."""
from email.message import EmailMessage
import os
from pathlib import Path
import smtplib
import ssl
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from email.utils import formataddr

from guardrails import redact_private_info

BASE_DIR = Path(__file__).parent


def _load_local_env():
    env_path = BASE_DIR / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def email_configured():
    _load_local_env()
    return bool(os.getenv("SMTP_HOST", "").strip() and os.getenv("EMAIL_FROM", "").strip())


def send_case_id_email(recipient, case_id):
    """Send the lost-dog owner their generated ID, or return a safe status."""
    _load_local_env()
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("EMAIL_FROM", "").strip()
    if not host or not sender:
        return {
            "sent": False,
            "message": "SMTP is not configured. Keep the case ID shown above.",
        }

    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        return {"sent": False, "message": "SMTP_PORT must be a valid port number."}

    message = EmailMessage()
    message["Subject"] = f"Your PawPal lost-dog case ID: {case_id}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        f"Your lost-dog report has been saved in PawPal.\n\n"
        f"Case ID: {case_id}\n\n"
        "Use this case ID in PawPal to check for possible matches. "
        "Keep it for your records."
    )

    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as client:
                if username:
                    client.login(username, password)
                client.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as client:
                if use_tls:
                    client.starttls(context=ssl.create_default_context())
                if username:
                    client.login(username, password)
                client.send_message(message)
    except Exception:
        return {
            "sent": False,
            "message": "SMTP could not deliver the email. Keep the case ID shown above.",
        }
    return {"sent": True, "message": f"Case ID sent to {recipient}."}


def send_listing_otp(recipient, case_id, code):
    """Email a short-lived code to the private address stored on a report."""
    _load_local_env()
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("EMAIL_FROM", "").strip()
    if not host or not sender:
        return {"sent": False, "message": "Email delivery is not configured."}
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        return {"sent": False, "message": "SMTP_PORT must be a valid port number."}

    message = EmailMessage()
    message["Subject"] = f"PawPal verification code for case {case_id}"
    message["From"] = formataddr(("PawPal listing security", sender))
    message["To"] = recipient
    message.set_content(
        f"Your verification code to edit or remove PawPal report {case_id} is {code}.\n\n"
        "The code expires in 10 minutes and can only be used once. "
        "If you did not request it, ignore this email."
    )
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as client:
                if username:
                    client.login(username, password)
                client.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as client:
                if use_tls:
                    client.starttls(context=ssl.create_default_context())
                if username:
                    client.login(username, password)
                client.send_message(message)
    except Exception:
        return {"sent": False, "message": "SMTP could not deliver the verification code."}
    return {"sent": True, "message": "A verification code was sent to the report email."}


def send_account_registration_otp(recipient, code):
    """Verify a new PawPal account address before creating the account."""
    _load_local_env()
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("EMAIL_FROM", "").strip()
    if not host or not sender:
        return {"sent": False, "message": "Email delivery is not configured."}
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        return {"sent": False, "message": "SMTP_PORT must be a valid port number."}

    message = EmailMessage()
    message["Subject"] = "Verify your PawPal account"
    message["From"] = formataddr(("PawPal account verification", sender))
    message["To"] = recipient
    message.set_content(
        f"Your PawPal registration code is {code}.\n\n"
        "It expires in 10 minutes and can only be used once. "
        "If you did not request an account, ignore this email."
    )
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as client:
                if username:
                    client.login(username, password)
                client.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as client:
                if use_tls:
                    client.starttls(context=ssl.create_default_context())
                if username:
                    client.login(username, password)
                client.send_message(message)
    except Exception:
        return {"sent": False, "message": "SMTP could not deliver the registration code."}
    return {"sent": True, "message": "A registration code was sent to that email."}


def relay_url(token):
    """Build the private conversation link included in notification emails."""
    _load_local_env()
    base = os.getenv("PAWPAL_PUBLIC_URL", "http://localhost:8501").strip().rstrip("/")
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["relay"] = token
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), ""))


def send_relay_notification(
    recipient, case_id, body, token, *, is_reply=False, is_confirmation=False,
    attachment_path=None, attachment_name=None,
):
    """Email a private message and reply link without exposing the sender email."""
    _load_local_env()
    body = redact_private_info(body)
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("EMAIL_FROM", "").strip()
    if not host or not sender:
        return {
            "sent": False,
            "message": "SMTP is not configured; the recipient was not emailed.",
        }
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        return {"sent": False, "message": "SMTP_PORT must be a valid port number."}

    action = "new reply" if is_reply else "new private message"
    subject_action = "private message sent" if is_confirmation else action
    message = EmailMessage()
    message["Subject"] = f"PawPal: {subject_action} about case {case_id}"
    message["From"] = formataddr(("PawPal private message relay", sender))
    message["To"] = recipient
    if is_confirmation:
        introduction = f"Your private message about PawPal report {case_id} was saved.\n\n"
    else:
        introduction = f"You have a {action} about PawPal report {case_id}.\n\n"
    message.set_content(
        introduction + f"Message:\n{body}\n\n"
        "Open this private link to read and reply. The other person's email is not shown:\n"
        f"{relay_url(token)}\n\n"
        "For privacy, reply through the link above rather than replying to this notification."
    )
    # Attach only a file explicitly selected by the sender. Never attach a default coupon.
    if attachment_path:
        private_dir = (BASE_DIR / "data" / "uploads" / "private-messages").resolve()
        path = Path(attachment_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        path = path.resolve()
        if private_dir not in path.parents or not path.is_file():
            return {"sent": False, "message": "The optional attachment could not be loaded."}
        extension = path.suffix.lower()
        mime_types = {
            ".pdf": ("application", "pdf"),
            ".jpg": ("image", "jpeg"),
            ".jpeg": ("image", "jpeg"),
            ".png": ("image", "png"),
        }
        if extension not in mime_types:
            return {"sent": False, "message": "The optional attachment type is not supported."}
        maintype, subtype = mime_types[extension]
        message.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype,
            filename=Path(attachment_name or path.name).name,
        )

    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context()) as client:
                if username:
                    client.login(username, password)
                client.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as client:
                if use_tls:
                    client.starttls(context=ssl.create_default_context())
                if username:
                    client.login(username, password)
                client.send_message(message)
    except Exception:
        return {
            "sent": False,
            "message": "SMTP could not deliver the message notification.",
        }
    return {"sent": True, "message": "Private message notification sent."}
