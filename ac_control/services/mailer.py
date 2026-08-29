"""Email helpers. Fail closed (log + False) when mail is not configured."""

from __future__ import annotations

import logging

from flask import current_app
from flask_mail import Message

from ac_control.extensions import mail
from ac_control.temperature import format_temp_f

logger = logging.getLogger(__name__)


def send_email(subject: str, recipients: list[str] | str, body: str) -> bool:
    sender = current_app.config.get("MAIL_DEFAULT_SENDER") or current_app.config.get(
        "MAIL_USERNAME"
    )
    if not sender or not current_app.config.get("MAIL_PASSWORD"):
        logger.warning("Mail is not configured; skipping send of %s", subject)
        return False
    to_list = recipients if isinstance(recipients, list) else [recipients]
    try:
        msg = Message(subject=subject, sender=sender, recipients=to_list)
        msg.body = body
        mail.send(msg)
        return True
    except Exception:
        logger.exception("Failed to send email %s", subject)
        return False


def send_window_alert(email: str, room_number: str) -> bool:
    return send_email(
        f"Window open while AC is on — Room {room_number}",
        email,
        (
            f"Room {room_number}: a window is open while the AC is running. "
            "The unit will shut off according to policy if the window stays open.\n\n"
            "— AC Control Center"
        ),
    )


def send_temperature_alert(email: str, room_number: str, temperature_c: float) -> bool:
    return send_email(
        f"Temperature alert — Room {room_number}",
        email,
        (
            f"Room {room_number} temperature is {format_temp_f(temperature_c)} "
            f"({temperature_c:.1f}°C), outside the allowed range.\n\n"
            "— AC Control Center"
        ),
    )
