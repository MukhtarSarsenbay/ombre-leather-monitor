import asyncio
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from app.config import Settings


class NotificationError(RuntimeError):
    pass


def _email(settings: Settings, text: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Ombré Leather — price monitor"
    message["From"] = settings.email_from
    message["To"] = settings.email_to
    message.set_content(text)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
            refused = smtp.send_message(message)
            if refused:
                raise NotificationError("Email recipient refused")
    except (OSError, smtplib.SMTPException):
        raise NotificationError("Email delivery failed") from None


async def send_notification(settings: Settings, text: str) -> None:
    settings.require_notifications()
    if settings.notification_channel == "email":
        await asyncio.to_thread(_email, settings, text)
        return
    token = settings.telegram_bot_token.get_secret_value()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": settings.telegram_chat_id, "text": text,
                      "link_preview_options": {"is_disabled": True}},
            )
            if response.status_code != 200 or response.json().get("ok") is not True:
                raise NotificationError("Telegram rejected the notification")
    except (httpx.HTTPError, ValueError):
        # Never log request URLs: Telegram embeds the bot token in the URL.
        raise NotificationError("Telegram delivery failed") from None
