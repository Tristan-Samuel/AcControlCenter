#!/usr/bin/env python3
"""Classroom Raspberry Pi agent for AC Control Center.

Talks to the central server with a per-room device API key. Hardware (GPIO,
IR, DHT) is optional: set SIMULATE=1 to run without a Pi.

Environment (see config.example.env):
  SERVER_URL       https://your-static-domain.ngrok.app  or http://10.0.0.5:5000
  ROOM_NUMBER      7
  DEVICE_API_KEY   from admin Users page or `python -m ac_control.cli create-room`
  SIMULATE         1 to skip GPIO/LIRC
"""

from __future__ import annotations

import logging
import os
import random
import signal
import sys
import time
from datetime import datetime

import requests

SERVER_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:5000").rstrip("/")
ROOM_NUMBER = os.environ.get("ROOM_NUMBER", "7")
DEVICE_API_KEY = os.environ.get("DEVICE_API_KEY", "")
SIMULATE = os.environ.get("SIMULATE", "1").lower() in {"1", "true", "yes"}
HEARTBEAT_SECONDS = int(os.environ.get("HEARTBEAT_SECONDS", "15"))
WINDOW_SENSOR_PIN = int(os.environ.get("WINDOW_SENSOR_PIN", "17"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ac_client")

ac_state = {"power": "off", "temperature": 24, "mode": "cool", "fan_speed": "auto"}
current_status = {
    "room_number": ROOM_NUMBER,
    "window_state": "closed",
    "ac_state": "off",
    "temperature": 22.0,
}


def _headers() -> dict[str, str]:
    return {"X-API-Key": DEVICE_API_KEY, "Content-Type": "application/json"}


def read_temperature() -> float:
    if SIMULATE:
        return round(22.5 + random.uniform(-0.4, 0.4), 1)
    # Optional: Adafruit_DHT / lgpio DHT22 on TEMPERATURE_SENSOR_PIN
    return round(22.5 + random.uniform(-0.4, 0.4), 1)


def read_window_state() -> str:
    if SIMULATE:
        return current_status["window_state"]
    try:
        import RPi.GPIO as GPIO  # type: ignore

        return "opened" if GPIO.input(WINDOW_SENSOR_PIN) else "closed"
    except Exception:
        logger.exception("Window sensor read failed")
        return current_status["window_state"]


def send_ir_command(command: str) -> None:
    logger.info("IR command: %s", command)
    if SIMULATE:
        return
    # Wire LIRC here, e.g. os.system(f"irsend SEND_ONCE ac_remote {command}")


def execute_command(command: str) -> None:
    if command == "POWER_OFF":
        ac_state["power"] = "off"
        current_status["ac_state"] = "off"
        send_ir_command("POWER_OFF")
    elif command == "POWER_ON":
        ac_state["power"] = "on"
        current_status["ac_state"] = "on"
        send_ir_command("POWER_ON")
    elif command.startswith("SET_TEMP_"):
        try:
            ac_state["temperature"] = int(command.split("_")[-1])
            send_ir_command(command)
        except ValueError:
            logger.error("Bad SET_TEMP command: %s", command)
    elif command == "REPORT_STATUS":
        pass
    else:
        logger.warning("Unknown command: %s", command)


def heartbeat() -> None:
    current_status["temperature"] = read_temperature()
    current_status["window_state"] = read_window_state()
    payload = {
        "room_number": ROOM_NUMBER,
        "window_state": current_status["window_state"],
        "ac_state": current_status["ac_state"],
        "temperature_c": current_status["temperature"],
    }
    try:
        response = requests.post(
            f"{SERVER_URL}/api/v1/heartbeat",
            json=payload,
            headers=_headers(),
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("Heartbeat failed")
        return
    if response.status_code == 401:
        logger.error("Device API key rejected. Rotate the key on the server and update DEVICE_API_KEY.")
        return
    if response.status_code != 200:
        logger.error("Heartbeat HTTP %s: %s", response.status_code, response.text[:200])
        return
    data = response.json()
    for command in data.get("commands") or []:
        logger.info("Executing server command %s", command)
        execute_command(command)


def request_permission(command: str) -> bool:
    payload = {
        "room_number": ROOM_NUMBER,
        "command": command,
        "window_state": current_status["window_state"],
        "ac_state": current_status["ac_state"],
        "temperature": current_status["temperature"],
    }
    try:
        response = requests.post(
            f"{SERVER_URL}/api/v1/check-command",
            json=payload,
            headers=_headers(),
            timeout=5,
        )
        if response.status_code != 200:
            logger.error("check-command HTTP %s", response.status_code)
            return False
        data = response.json()
        if not data.get("allowed", False):
            logger.warning("Command %s blocked: %s", command, data.get("reason"))
            alt = data.get("alternative_action")
            if alt:
                execute_command(alt)
            return False
        return True
    except requests.RequestException:
        logger.exception("check-command failed; failing closed")
        return False


def setup_gpio() -> None:
    if SIMULATE:
        logger.info("SIMULATE=1: skipping GPIO")
        return
    import RPi.GPIO as GPIO  # type: ignore

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(WINDOW_SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def on_window(_channel):
        time.sleep(0.1)
        current_status["window_state"] = read_window_state()
        logger.info("Window -> %s", current_status["window_state"])
        heartbeat()

    GPIO.add_event_detect(WINDOW_SENSOR_PIN, GPIO.BOTH, callback=on_window, bouncetime=300)


def cleanup() -> None:
    if SIMULATE:
        return
    try:
        import RPi.GPIO as GPIO  # type: ignore

        GPIO.cleanup()
    except Exception:
        pass


def main() -> None:
    if not DEVICE_API_KEY:
        logger.error("DEVICE_API_KEY is required")
        sys.exit(1)

    def handle_signal(_sig, _frame):
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    setup_gpio()
    logger.info("Room %s -> %s (simulate=%s)", ROOM_NUMBER, SERVER_URL, SIMULATE)
    while True:
        heartbeat()
        time.sleep(HEARTBEAT_SECONDS)


if __name__ == "__main__":
    main()
