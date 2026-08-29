"""Queue of IR commands for classroom Pis, consumed on heartbeat."""

from __future__ import annotations

from ac_control.extensions import db
from ac_control.models import DeviceCommand


VALID_COMMANDS = frozenset({"POWER_ON", "POWER_OFF", "REPORT_STATUS"})


def enqueue_command(room_number: str, command: str) -> DeviceCommand:
    if command.startswith("SET_TEMP_"):
        pass
    elif command not in VALID_COMMANDS:
        raise ValueError(f"Unknown command: {command}")

    existing = DeviceCommand.query.filter_by(
        room_number=room_number, command=command, delivered=False
    ).first()
    if existing:
        return existing

    queued = DeviceCommand(room_number=room_number, command=command, delivered=False)
    db.session.add(queued)
    return queued


def pop_commands(room_number: str) -> list[str]:
    pending = (
        DeviceCommand.query.filter_by(room_number=room_number, delivered=False)
        .order_by(DeviceCommand.created_at.asc())
        .all()
    )
    commands = [row.command for row in pending]
    for row in pending:
        row.delivered = True
    return commands
