"""Authenticated classroom-Pi API. CSRF-exempt; requires X-API-Key."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from ac_control.extensions import db
from ac_control.models import ACSettings, GlobalPolicy, RoomStatus, utc_now
from ac_control.services.commands import pop_commands
from ac_control.services.ingest import process_heartbeat
from ac_control.services.policy import in_scheduled_shutoff, policy_payload

device_bp = Blueprint("device", __name__, url_prefix="/api/v1")


def _authenticate_room(room_number: str) -> tuple[ACSettings | None, tuple | None]:
    api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "")
    if api_key.lower().startswith("bearer "):
        api_key = api_key[7:].strip()
    if not room_number or not api_key:
        return None, (jsonify({"error": "Missing room_number or X-API-Key"}), 401)
    settings = ACSettings.query.filter_by(room_number=room_number).first()
    if not settings or not settings.check_device_key(api_key):
        return None, (jsonify({"error": "Invalid device credentials"}), 401)
    return settings, None


@device_bp.route("/heartbeat", methods=["POST"])
def heartbeat():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json(silent=True) or {}
    room_number = str(data.get("room_number") or "").strip()
    settings, error = _authenticate_room(room_number)
    if error:
        return error
    try:
        temperature_c = float(data.get("temperature_c", data.get("temperature", 22.0)))
        result = process_heartbeat(
            room_number=room_number,
            window_state=str(data.get("window_state", "closed")),
            ac_state=str(data.get("ac_state", "off")),
            temperature_c=temperature_c,
        )
        return jsonify(result)
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Failed to process heartbeat"}), 500


@device_bp.route("/check-command", methods=["POST"])
def check_command():
    if not request.is_json:
        return jsonify({"allowed": False, "reason": "Request must be JSON"}), 400
    data = request.get_json(silent=True) or {}
    room_number = str(data.get("room_number") or "").strip()
    settings, error = _authenticate_room(room_number)
    if error:
        return error
    command = data.get("command")
    window_state = str(data.get("window_state", "")).lower()
    ac_state = str(data.get("ac_state", "")).lower()
    try:
        temperature = float(data.get("temperature", 22.0))
    except (TypeError, ValueError):
        temperature = 22.0
    if not command:
        return jsonify({"allowed": False, "reason": "Missing command"}), 400

    if settings.settings_locked:
        return jsonify(
            {
                "allowed": False,
                "reason": "Room settings locked by administrator",
                "alternative_action": "REPORT_STATUS",
            }
        )

    policy = GlobalPolicy.query.first()
    if command == "POWER" and window_state == "opened" and ac_state == "off":
        return jsonify(
            {
                "allowed": False,
                "reason": "Cannot turn on AC while window is open",
                "alternative_action": "REPORT_STATUS",
            }
        )

    if policy and policy.policy_active:
        if command == "TEMP_DOWN":
            new_temp = temperature - 1
            if new_temp < policy.min_allowed_temp:
                return jsonify(
                    {
                        "allowed": False,
                        "reason": f"Temperature cannot be set below {policy.min_allowed_temp}°C",
                        "alternative_action": f"SET_TEMP_{int(policy.min_allowed_temp)}",
                    }
                )
        if command == "TEMP_UP":
            new_temp = temperature + 1
            if new_temp > policy.max_allowed_temp:
                return jsonify(
                    {
                        "allowed": False,
                        "reason": f"Temperature cannot be set above {policy.max_allowed_temp}°C",
                        "alternative_action": f"SET_TEMP_{int(policy.max_allowed_temp)}",
                    }
                )

    if (
        policy
        and command in {"POWER", "POWER_ON"}
        and ac_state == "off"
        and in_scheduled_shutoff(policy)
        and not settings.schedule_override
    ):
        return jsonify(
            {
                "allowed": False,
                "reason": "AC usage not allowed during scheduled shutoff hours",
                "alternative_action": "REPORT_STATUS",
            }
        )

    if command in {"POWER", "POWER_ON"} and settings.min_temp_locked:
        if temperature < settings.min_temperature:
            pass
        elif temperature > settings.min_temperature:
            return jsonify(
                {
                    "allowed": False,
                    "reason": f"Temperature above allowed minimum cooling floor ({settings.min_temperature}°C)",
                    "alternative_action": "REPORT_STATUS",
                }
            )

    if command in {"POWER", "POWER_ON"} and not settings.force_on_enabled:
        return jsonify(
            {
                "allowed": False,
                "reason": "Force turn ON has been disabled by administrator",
                "alternative_action": "REPORT_STATUS",
            }
        )

    return jsonify({"allowed": True, "policy_status": "compliant", "policy": policy_payload(policy)})


@device_bp.route("/commands", methods=["POST"])
def drain_commands():
    """Optional poll without a full heartbeat — still requires the device key."""
    data = request.get_json(silent=True) or {}
    room_number = str(data.get("room_number") or request.args.get("room_number") or "").strip()
    _settings, error = _authenticate_room(room_number)
    if error:
        return error
    commands = pop_commands(room_number)
    status = RoomStatus.query.filter_by(room_number=room_number).first()
    if status:
        status.last_updated = utc_now()
    db.session.commit()
    return jsonify({"commands": commands, "server_time": utc_now().isoformat()})
