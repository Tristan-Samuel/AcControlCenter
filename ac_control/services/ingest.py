"""Heartbeat ingest: log events, apply policy, return queued IR commands."""

from __future__ import annotations

import logging
from datetime import timedelta

from ac_control.extensions import db
from ac_control.models import (
    ACSettings,
    GlobalPolicy,
    PendingWindowEvent,
    RoomStatus,
    User,
    WindowEvent,
    utc_now,
)
from ac_control.services.commands import enqueue_command, pop_commands
from ac_control.services.mailer import send_window_alert
from ac_control.services.policy import (
    assess_temperature,
    in_scheduled_shutoff,
    policy_payload,
)

logger = logging.getLogger(__name__)


def get_or_create_status(room_number: str) -> RoomStatus:
    status = RoomStatus.query.filter_by(room_number=room_number).first()
    if status:
        return status
    status = RoomStatus(room_number=room_number)
    db.session.add(status)
    return status


def get_or_create_settings(room_number: str) -> ACSettings:
    settings = ACSettings.query.filter_by(room_number=room_number).first()
    if settings:
        return settings
    settings = ACSettings(room_number=room_number)
    db.session.add(settings)
    return settings


def get_or_create_policy() -> GlobalPolicy:
    policy = GlobalPolicy.query.first()
    if policy:
        return policy
    policy = GlobalPolicy()
    db.session.add(policy)
    db.session.commit()
    return policy


def cancel_pending(room_number: str, event_type: str | None = None) -> None:
    query = PendingWindowEvent.query.filter_by(room_number=room_number, processed=False)
    if event_type:
        query = query.filter_by(event_type=event_type)
    for pending in query.all():
        pending.processed = True


def process_heartbeat(
    room_number: str,
    window_state: str,
    ac_state: str,
    temperature_c: float,
) -> dict:
    window_state = window_state.lower()
    ac_state = ac_state.lower()
    if window_state not in {"opened", "closed"}:
        raise ValueError("window_state must be opened or closed")
    if ac_state not in {"on", "off"}:
        raise ValueError("ac_state must be on or off")

    policy = get_or_create_policy()
    settings = get_or_create_settings(room_number)
    status = get_or_create_status(room_number)

    is_compliant, issue = assess_temperature(temperature_c, policy)
    if window_state == "opened" and ac_state == "on":
        is_compliant = False
        issue = "Window open with AC running"

    event = WindowEvent(
        room_number=room_number,
        window_state=window_state,
        ac_state=ac_state,
        temperature=temperature_c,
        policy_compliant=is_compliant,
        compliance_issue=issue,
    )
    db.session.add(event)

    status.current_temperature = temperature_c
    status.window_state = window_state
    status.ac_state = ac_state
    status.last_updated = utc_now()

    if window_state == "closed":
        cancel_pending(room_number)
        status.has_pending_event = False
        status.pending_event_time = None
        if ac_state == "off" and settings.auto_shutoff:
            enqueue_command(room_number, "POWER_ON")
            status.ac_state = "on"
    elif window_state == "opened" and ac_state == "on" and settings.auto_shutoff:
        delay = max(0, int(settings.shutoff_delay or 0))
        if delay == 0:
            enqueue_command(room_number, "POWER_OFF")
            status.ac_state = "off"
            status.has_pending_event = False
            status.pending_event_time = None
            user = User.query.filter_by(room_number=room_number).first()
            if user and settings.email_notifications:
                send_window_alert(user.email, room_number)
        else:
            scheduled = utc_now() + timedelta(seconds=delay)
            pending = PendingWindowEvent(
                room_number=room_number,
                window_state=window_state,
                ac_state=ac_state,
                temperature=temperature_c,
                scheduled_action_time=scheduled,
                processed=False,
                event_type="window_open",
            )
            db.session.add(pending)
            status.has_pending_event = True
            status.pending_event_time = scheduled

    if in_scheduled_shutoff(policy) and not settings.schedule_override and status.ac_state == "on":
        enqueue_command(room_number, "POWER_OFF")
        status.ac_state = "off"

    if not is_compliant and "too cold" in (issue or "").lower():
        if status.non_compliant_since is None:
            status.non_compliant_since = utc_now()
            status.policy_violation_type = issue
        else:
            elapsed = (utc_now() - status.non_compliant_since).total_seconds()
            if elapsed >= 10 and status.ac_state == "on":
                enqueue_command(room_number, "POWER_OFF")
                status.ac_state = "off"
    else:
        if "too cold" not in (issue or "").lower():
            status.non_compliant_since = None
            status.policy_violation_type = None

    commands = pop_commands(room_number)
    db.session.commit()

    return {
        "success": True,
        "commands": commands,
        "ac_state": status.ac_state,
        "window_state": status.window_state,
        "has_pending_event": status.has_pending_event,
        "pending_event_time": status.pending_event_time.isoformat()
        if status.pending_event_time
        else None,
        "is_compliant": is_compliant,
        "policy_message": issue,
        "policy": policy_payload(policy),
        "server_time": utc_now().isoformat(),
    }


def process_due_pending_events() -> int:
    now = utc_now()
    due = (
        PendingWindowEvent.query.filter_by(processed=False)
        .filter(PendingWindowEvent.scheduled_action_time <= now)
        .all()
    )
    count = 0
    for pending in due:
        try:
            status = get_or_create_status(pending.room_number)
            enqueue_command(pending.room_number, "POWER_OFF")
            status.ac_state = "off"
            status.has_pending_event = False
            status.pending_event_time = None
            status.last_updated = now
            pending.processed = True
            event = WindowEvent(
                room_number=pending.room_number,
                window_state=pending.window_state or status.window_state,
                ac_state="off",
                temperature=pending.temperature,
                policy_compliant=False,
                compliance_issue=f"Scheduled action: {pending.event_type}",
            )
            db.session.add(event)
            settings = ACSettings.query.filter_by(room_number=pending.room_number).first()
            user = User.query.filter_by(room_number=pending.room_number).first()
            if user and settings and settings.email_notifications:
                send_window_alert(user.email, pending.room_number)
            db.session.commit()
            count += 1
        except Exception:
            db.session.rollback()
            logger.exception("Failed processing pending event %s", pending.id)
    return count


def check_scheduled_shutoffs() -> None:
    policy = GlobalPolicy.query.first()
    if not in_scheduled_shutoff(policy):
        return
    rooms = RoomStatus.query.filter_by(ac_state="on").all()
    for status in rooms:
        settings = ACSettings.query.filter_by(room_number=status.room_number).first()
        if settings and settings.schedule_override:
            continue
        enqueue_command(status.room_number, "POWER_OFF")
        status.ac_state = "off"
    db.session.commit()


def check_temperature_compliance() -> None:
    policy = GlobalPolicy.query.first()
    if not policy or not policy.policy_active:
        return
    now = utc_now()
    for status in RoomStatus.query.filter_by(ac_state="on").all():
        compliant, issue = assess_temperature(status.current_temperature, policy)
        if not compliant and issue and "too cold" in issue.lower():
            if status.non_compliant_since is None:
                status.non_compliant_since = now
                status.policy_violation_type = issue
            elif (now - status.non_compliant_since).total_seconds() >= 10:
                enqueue_command(status.room_number, "POWER_OFF")
                status.ac_state = "off"
        else:
            status.non_compliant_since = None
            status.policy_violation_type = None
    db.session.commit()


def update_compliance_metrics() -> None:
    policy = GlobalPolicy.query.first()
    if not policy:
        return
    one_day_ago = utc_now() - timedelta(days=1)
    rooms = User.query.filter(User.room_number.isnot(None)).all()
    for room in rooms:
        settings = ACSettings.query.filter_by(room_number=room.room_number).first()
        if not settings:
            continue
        try:
            window_open_events = WindowEvent.query.filter(
                WindowEvent.room_number == room.room_number,
                WindowEvent.timestamp >= one_day_ago,
                WindowEvent.window_state == "opened",
                WindowEvent.ac_state == "on",
            ).all()
            window_open_minutes = len(window_open_events)
            temp_events = WindowEvent.query.filter(
                WindowEvent.room_number == room.room_number,
                WindowEvent.timestamp >= one_day_ago,
            ).all()
            total_deviation = 0.0
            if temp_events:
                for event in temp_events:
                    if event.temperature is None:
                        continue
                    if event.temperature < policy.min_allowed_temp:
                        total_deviation += policy.min_allowed_temp - event.temperature
                    elif event.temperature > policy.max_allowed_temp:
                        total_deviation += event.temperature - policy.max_allowed_temp
                avg_deviation = total_deviation / len(temp_events)
            else:
                avg_deviation = 0.0
            score = 100.0
            score -= min(50, window_open_minutes * 0.5)
            score -= min(50, avg_deviation * 10)
            settings.window_open_minutes = window_open_minutes
            settings.temperature_deviation = avg_deviation
            settings.compliance_score = max(0.0, score)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Compliance update failed for room %s", room.room_number)
