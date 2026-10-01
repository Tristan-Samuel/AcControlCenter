"""Allow/deny physical remote (IR) commands. Policy lives on the server."""

from __future__ import annotations

from ac_control.models import ACSettings, GlobalPolicy
from ac_control.services.policy import clamp_setpoint_c, in_scheduled_shutoff, policy_payload


def evaluate_remote_command(
    *,
    settings: ACSettings,
    command: str,
    door_state: str,
    ac_state: str,
    temperature: float,
    set_temperature: float,
    policy: GlobalPolicy | None,
) -> dict:
    command = (command or "").upper().strip()
    door_state = (door_state or "closed").lower()
    ac_state = (ac_state or "off").lower()
    setpoint = (
        set_temperature
        if set_temperature is not None
        else (settings.min_temperature if settings else 20.0)
    )

    if not command:
        return {"allowed": False, "reason": "Missing command"}

    if settings.settings_locked and command not in {"REPORT_STATUS"}:
        return {
            "allowed": False,
            "reason": "Room settings locked by administrator",
            "alternative_action": "REPORT_STATUS",
            "buzz": bool(settings.buzz_on_open and door_state == "opened"),
            "set_temperature_c": setpoint,
        }

    if command in {"POWER", "POWER_ON"} and door_state == "opened" and ac_state == "off":
        return {
            "allowed": False,
            "reason": "Cannot turn on AC while the door is open",
            "alternative_action": "REPORT_STATUS",
            "buzz": True if settings.buzz_on_open else False,
            "set_temperature_c": setpoint,
        }

    if policy and policy.policy_active:
        if command == "TEMP_DOWN":
            new_temp = setpoint - 1
            if new_temp < policy.min_allowed_temp:
                return {
                    "allowed": False,
                    "reason": f"Temperature cannot be set below {policy.min_allowed_temp}°C",
                    "alternative_action": f"SET_TEMP_{int(policy.min_allowed_temp)}",
                    "set_temperature_c": setpoint,
                }
        if command == "TEMP_UP":
            new_temp = setpoint + 1
            if new_temp > policy.max_allowed_temp:
                return {
                    "allowed": False,
                    "reason": f"Temperature cannot be set above {policy.max_allowed_temp}°C",
                    "alternative_action": f"SET_TEMP_{int(policy.max_allowed_temp)}",
                    "set_temperature_c": setpoint,
                }

    if (
        policy
        and command in {"POWER", "POWER_ON"}
        and ac_state == "off"
        and in_scheduled_shutoff(policy)
        and not settings.schedule_override
    ):
        return {
            "allowed": False,
            "reason": "AC usage not allowed during scheduled shutoff hours",
            "alternative_action": "REPORT_STATUS",
            "set_temperature_c": setpoint,
        }

    if command in {"POWER", "POWER_ON"} and settings.min_temp_locked:
        if setpoint > settings.min_temperature:
            return {
                "allowed": False,
                "reason": f"Temperature above allowed minimum cooling floor ({settings.min_temperature}°C)",
                "alternative_action": "REPORT_STATUS",
                "set_temperature_c": setpoint,
            }

    if command in {"POWER", "POWER_ON"} and not settings.force_on_enabled:
        return {
            "allowed": False,
            "reason": "Force turn ON has been disabled by administrator",
            "alternative_action": "REPORT_STATUS",
            "set_temperature_c": setpoint,
        }

    result: dict = {
        "allowed": True,
        "policy_status": "compliant",
        "policy": policy_payload(policy),
        "set_temperature_c": setpoint,
        "buzz": bool(settings.buzz_on_open and door_state == "opened"),
    }
    if command in {"POWER", "POWER_ON"}:
        clamped = clamp_setpoint_c(setpoint, policy, settings.min_temperature)
        result["set_temperature_c"] = clamped
        result["commands"] = ["POWER_ON", f"SET_TEMP_{int(round(clamped))}"]
    elif command == "TEMP_UP":
        new_temp = clamp_setpoint_c(setpoint + 1, policy, settings.min_temperature)
        result["set_temperature_c"] = new_temp
        result["commands"] = [f"SET_TEMP_{int(round(new_temp))}"]
    elif command == "TEMP_DOWN":
        new_temp = clamp_setpoint_c(setpoint - 1, policy, settings.min_temperature)
        result["set_temperature_c"] = new_temp
        result["commands"] = [f"SET_TEMP_{int(round(new_temp))}"]
    elif command == "POWER_OFF":
        result["commands"] = ["POWER_OFF"]
    return result
