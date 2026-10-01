"""Policy helpers shared by the scheduler, heartbeat ingest, and device checks."""

from __future__ import annotations

from datetime import datetime, time

from ac_control.models import GlobalPolicy


def time_in_range(start: time, end: time, current: time) -> bool:
    """True if current is in [start, end], including ranges that wrap midnight."""
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def in_scheduled_shutoff(policy: GlobalPolicy | None, now: datetime | None = None) -> bool:
    if not policy or not policy.scheduled_shutoff_active:
        return False
    now = now or datetime.now()
    if now.weekday() >= 5 and not policy.apply_shutoff_weekends:
        return False
    return time_in_range(
        policy.scheduled_shutoff_time,
        policy.scheduled_startup_time,
        now.time(),
    )


def effective_min_celsius(policy: GlobalPolicy | None) -> float | None:
    if not policy or not policy.policy_active:
        return None
    minimum = policy.min_allowed_temp
    if policy.energy_conservation_active and policy.conservation_threshold is not None:
        minimum = max(minimum, policy.conservation_threshold)
    return minimum


def assess_temperature(
    temperature_c: float,
    policy: GlobalPolicy | None,
) -> tuple[bool, str | None]:
    """Return (compliant, issue). Cooling-focused: too-cold is the main AC violation."""
    if not policy or not policy.policy_active:
        return True, None
    min_c = effective_min_celsius(policy)
    if min_c is not None and temperature_c < min_c:
        return False, f"Temperature too cold: {temperature_c:.1f}°C (min {min_c:.1f}°C)"
    if temperature_c > policy.max_allowed_temp:
        return False, f"Temperature too hot: {temperature_c:.1f}°C (max {policy.max_allowed_temp:.1f}°C)"
    return True, None


def clamp_setpoint_c(
    temp_c: float,
    policy: GlobalPolicy | None,
    min_floor_c: float | None = None,
) -> float:
    """Clamp an IR setpoint to global policy and an optional room cooling floor."""
    value = float(temp_c)
    if min_floor_c is not None:
        value = max(value, float(min_floor_c))
    if policy and policy.policy_active:
        value = max(value, float(policy.min_allowed_temp))
        value = min(value, float(policy.max_allowed_temp))
        if policy.energy_conservation_active and policy.conservation_threshold is not None:
            value = max(value, float(policy.conservation_threshold))
    return value


def policy_payload(policy: GlobalPolicy | None) -> dict:
    if not policy:
        return {}
    return {
        "active": policy.policy_active,
        "min_temp_c": policy.min_allowed_temp if policy.policy_active else None,
        "max_temp_c": policy.max_allowed_temp if policy.policy_active else None,
        "conservation_active": policy.energy_conservation_active,
        "conservation_threshold_c": policy.conservation_threshold,
        "scheduled_shutoff": policy.scheduled_shutoff_active,
        "shutoff_time": policy.scheduled_shutoff_time.strftime("%H:%M")
        if policy.scheduled_shutoff_time
        else None,
        "startup_time": policy.scheduled_startup_time.strftime("%H:%M")
        if policy.scheduled_startup_time
        else None,
    }
