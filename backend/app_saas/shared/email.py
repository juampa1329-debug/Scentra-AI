from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app_saas.config import settings


def smtp_is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from_email)


def send_plain_email(*, to_email: str, subject: str, body: str) -> bool:
    if not smtp_is_configured():
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = str(to_email or "").strip()
    message["Subject"] = str(subject or "").strip()
    message.set_content(str(body or ""))

    with smtplib.SMTP(settings.smtp_host, int(settings.smtp_port or 587), timeout=12) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)
    return True
