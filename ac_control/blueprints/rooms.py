"""Room-user dashboard, settings, and logged-in JSON for the UI."""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ac_control.extensions import db
from ac_control.services.commands import enqueue_command
from ac_control.services.ingest import (
    get_or_create_settings,
    get_or_create_status,
    process_heartbeat,
    queue_resume_ac,
)
from ac_control.services.policy import clamp_setpoint_c
from ac_control.models import ACSettings, GlobalPolicy, RoomStatus, WindowEvent
from ac_control.temperature import celsius_to_fahrenheit, fahrenheit_to_celsius

rooms_bp = Blueprint("rooms", __name__)


def _can_access_room(room_number: str) -> bool:
    if current_user.is_admin:
        return True
    return current_user.room_number == room_number


def _room_context(room_number: str):
    status = get_or_create_status(room_number)
    settings = get_or_create_settings(room_number)
    events = (
        WindowEvent.query.filter_by(room_number=room_number)
        .order_by(WindowEvent.timestamp.desc())
        .limit(10)
        .all()
    )
    policy = GlobalPolicy.query.first()
    db.session.commit()
    return {
        "room_number": room_number,
        "settings": settings,
        "events": events,
        "room_status": status,
        "compliance_score": settings.compliance_score,
        "policy_active": bool(policy and policy.policy_active),
        "current_temp": status.current_temperature,
        "current_temp_f": celsius_to_fahrenheit(status.current_temperature),
        "set_temp": status.set_temperature,
        "set_temp_f": celsius_to_fahrenheit(status.set_temperature),
        "is_admin_view": current_user.is_admin,
        "stale": status.is_stale(),
        "device_mac": settings.device_mac,
    }


@rooms_bp.route("/room")
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for("admin.dashboard"))
    if not current_user.room_number:
        flash("This account is not assigned to a room.", "error")
        return redirect(url_for("auth.logout"))
    return render_template("room_dashboard.html", **_room_context(current_user.room_number))


@rooms_bp.route("/settings/<room_number>", methods=["POST"])
@login_required
def update_settings(room_number):
    if not _can_access_room(room_number):
        flash("You cannot change another room's settings.", "error")
        return redirect(url_for("rooms.dashboard"))

    settings = get_or_create_settings(room_number)
    is_admin = current_user.is_admin
    if settings.settings_locked and not is_admin:
        flash("Settings are locked by an administrator.", "error")
        return _after_room_change(room_number)

    if not (settings.min_temp_locked and not is_admin):
        try:
            fahrenheit_temp = float(request.form["min_temperature"])
            converted = fahrenheit_to_celsius(fahrenheit_temp)
            if converted is not None:
                settings.min_temperature = converted
        except (TypeError, ValueError, KeyError):
            pass

    settings.auto_shutoff = "auto_shutoff" in request.form
    settings.buzz_on_open = "buzz_on_open" in request.form
    try:
        delay = int(request.form.get("shutoff_delay", settings.shutoff_delay))
        settings.shutoff_delay = max(0, min(300, delay))
    except (TypeError, ValueError):
        pass
    if "set_temperature" in request.form:
        try:
            setpoint_f = float(request.form["set_temperature"])
            converted = fahrenheit_to_celsius(setpoint_f)
            if converted is not None:
                policy = GlobalPolicy.query.first()
                status = get_or_create_status(room_number)
                status.set_temperature = clamp_setpoint_c(
                    converted, policy, settings.min_temperature
                )
                enqueue_command(
                    room_number,
                    f"SET_TEMP_{int(round(status.set_temperature))}",
                )
        except (TypeError, ValueError):
            pass
    settings.email_notifications = "email_notifications" in request.form
    if is_admin:
        settings.force_on_enabled = "force_on_enabled" in request.form
        settings.schedule_override = "schedule_override" in request.form
    db.session.commit()
    flash("Settings saved.", "success")
    return _after_room_change(room_number)


@rooms_bp.route("/force/<room_number>/<state>", methods=["POST"])
@login_required
def force_ac_state(room_number, state):
    if state not in {"on", "off"}:
        flash("Invalid AC state.", "error")
        return _after_room_change(room_number)
    if not _can_access_room(room_number):
        flash("Unauthorized.", "error")
        return _after_room_change(room_number)

    settings = get_or_create_settings(room_number)
    status = get_or_create_status(room_number)
    if state == "on" and not settings.force_on_enabled and not current_user.is_admin:
        flash("Force Turn ON is disabled for this room.", "error")
        return _after_room_change(room_number)

    command = "POWER_ON" if state == "on" else "POWER_OFF"
    if state == "on":
        policy = GlobalPolicy.query.first()
        queue_resume_ac(room_number, status, settings, policy)
    else:
        enqueue_command(room_number, "POWER_OFF")
        status.ac_state = "off"
    db.session.commit()
    flash(f"Queued AC {state.upper()} for the classroom ESP32.", "success")
    return _after_room_change(room_number)


@rooms_bp.route("/test", methods=["GET", "POST"])
@login_required
def test_interface():
    room_number = request.values.get("room_number") or current_user.room_number
    if current_user.is_admin and not room_number:
        first = ACSettings.query.first()
        room_number = first.room_number if first else None
    if not room_number or not _can_access_room(room_number):
        flash("Pick a room you can access.", "error")
        return redirect(url_for("auth.index"))

    if request.method == "POST":
        try:
            temperature_c = fahrenheit_to_celsius(float(request.form.get("temperature_f", 71.6)))
            process_heartbeat(
                room_number=room_number,
                window_state=request.form.get("window_state", "closed"),
                door_state=request.form.get("door_state", "closed"),
                ac_state=request.form.get("ac_state", "off"),
                temperature_c=float(temperature_c),
            )
            flash("Test data submitted.", "success")
        except Exception as exc:
            flash(str(exc), "error")
        return redirect(url_for("rooms.test_interface", room_number=room_number))

    status = get_or_create_status(room_number)
    events = (
        WindowEvent.query.filter_by(room_number=room_number)
        .order_by(WindowEvent.timestamp.desc())
        .limit(10)
        .all()
    )
    db.session.commit()
    return render_template(
        "test_interface.html",
        room_number=room_number,
        is_admin=current_user.is_admin,
        status=status,
        events=events,
        celsius_to_fahrenheit=celsius_to_fahrenheit,
    )


@rooms_bp.route("/guide")
def user_guide():
    return render_template("user_guide.html")


@rooms_bp.route("/api/rooms/<room_number>/status")
@login_required
def room_status_api(room_number):
    if not _can_access_room(room_number):
        return jsonify({"error": "Unauthorized"}), 403
    status = RoomStatus.query.filter_by(room_number=room_number).first()
    settings = ACSettings.query.filter_by(room_number=room_number).first()
    if not status or not settings:
        return jsonify({"error": "Room not found"}), 404
    return jsonify(_status_json(status, settings))


@rooms_bp.route("/api/rooms/<room_number>/events")
@login_required
def recent_events_api(room_number):
    if not _can_access_room(room_number):
        return jsonify({"error": "Unauthorized"}), 403
    events = (
        WindowEvent.query.filter_by(room_number=room_number)
        .order_by(WindowEvent.timestamp.desc())
        .limit(10)
        .all()
    )
    return jsonify(
        {
            "events": [
                {
                    "id": event.id,
                    "timestamp": event.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "window_state": event.window_state,
                    "door_state": event.door_state,
                    "ac_state": event.ac_state,
                    "temperature": event.temperature,
                    "temperature_f": celsius_to_fahrenheit(event.temperature),
                    "unit": "F",
                }
                for event in events
            ]
        }
    )


@rooms_bp.route("/api/rooms/<room_number>/temperature")
@login_required
def temperature_api(room_number):
    if not _can_access_room(room_number):
        return jsonify({"error": "Unauthorized"}), 403
    status = RoomStatus.query.filter_by(room_number=room_number).first()
    current_temp = status.current_temperature if status else 22.0
    return jsonify(
        {
            "temperature": round(current_temp, 1),
            "temperature_f": round(celsius_to_fahrenheit(current_temp) or 0, 1),
            "unit": "F",
            "timestamp": (status.last_updated.isoformat() if status and status.last_updated else None),
        }
    )


def _status_json(status: RoomStatus, settings: ACSettings) -> dict:
    payload = {
        "min_temperature": settings.min_temperature,
        "min_temperature_f": celsius_to_fahrenheit(settings.min_temperature),
        "auto_shutoff": settings.auto_shutoff,
        "buzz_on_open": settings.buzz_on_open,
        "email_notifications": settings.email_notifications,
        "window_state": status.window_state,
        "door_state": status.door_state,
        "ac_state": status.ac_state,
        "temperature": status.current_temperature,
        "temperature_f": celsius_to_fahrenheit(status.current_temperature),
        "set_temperature": status.set_temperature,
        "set_temperature_f": celsius_to_fahrenheit(status.set_temperature),
        "unit": "F",
        "device_mac": settings.device_mac,
        "has_pending_event": status.has_pending_event,
        "pending_event_time": status.pending_event_time.isoformat()
        if status.pending_event_time
        else None,
        "non_compliant_since": status.non_compliant_since.isoformat()
        if status.non_compliant_since
        else None,
        "policy_violation_type": status.policy_violation_type,
        "stale": status.is_stale(),
        "last_updated": status.last_updated.isoformat() if status.last_updated else None,
        "buzz": bool(settings.buzz_on_open and status.door_state == "opened"),
    }
    if current_app.config.get("SIMULATION_MODE"):
        from ac_control.services.simulation import room_view

        payload["simulation"] = room_view(status.room_number)
    return payload


def _after_room_change(room_number: str):
    if current_user.is_admin:
        return redirect(url_for("admin.view_room", room_number=room_number))
    return redirect(url_for("rooms.dashboard"))
