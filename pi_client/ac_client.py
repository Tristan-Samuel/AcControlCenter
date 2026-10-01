#!/usr/bin/env python3
"""LAN simulator of a classroom ESP32 for AC Control Center.

Talks the same protocol as firmware/ac_node. Hardware is optional:
set SIMULATE=1 to run without GPIO.

Environment (see config.example.env):
  SERVER_URL       http://10.0.0.5:5000   (Pi LAN IP, not the public hostname)
  DEVICE_API_KEY   from admin Users page, create-room, or enroll
  DEVICE_MAC       AA:BB:CC:DD:EE:FF (optional; simulated if omitted)
  ROOM_NUMBER      optional fallback if the MAC is not bound yet
  ENROLL_TOKEN     school-wide enroll secret, if the server requires one
  SIMULATE         1 to skip GPIO
"""

from __future__ import annotations

import logging
import os
import random
import signal
import sys
import time

import requests

SERVER_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:5000").rstrip("/")
ROOM_NUMBER = os.environ.get("ROOM_NUMBER", "")
DEVICE_API_KEY = os.environ.get("DEVICE_API_KEY", "")
ENROLL_TOKEN = os.environ.get("ENROLL_TOKEN", "")
DEVICE_MAC = (os.environ.get("DEVICE_MAC") or os.environ.get("MAC") or "").strip()
SIMULATE = os.environ.get("SIMULATE", "1").lower() in {"1", "true", "yes"}
HEARTBEAT_SECONDS = int(os.environ.get("HEARTBEAT_SECONDS", "10"))
DOOR_SENSOR_PIN = int(os.environ.get("DOOR_SENSOR_PIN", os.environ.get("WINDOW_SENSOR_PIN", "17")))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ac_client")

ac_state = {"power": "off", "temperature": 20, "mode": "cool", "fan_speed": "auto"}
current_status = {
    "door_state": "closed",
    "window_state": "closed",
    "ac_state": "off",
    "temperature": 22.0,
}
set_temperature_c = 20.0
buzz = False


def _simulated_mac() -> str:
    if DEVICE_MAC:
        return DEVICE_MAC.upper()
    return "02:00:00:00:00:07"


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "X-Device-Mac": _simulated_mac()}
    if DEVICE_API_KEY:
        headers["X-API-Key"] = DEVICE_API_KEY
    if ENROLL_TOKEN:
        headers["X-Enroll-Token"] = ENROLL_TOKEN
    return headers


def read_temperature() -> float:
    if SIMULATE:
        return round(22.5 + random.uniform(-0.4, 0.4), 1)
    return round(22.5 + random.uniform(-0.4, 0.4), 1)


def read_door_state() -> str:
    if SIMULATE:
        return current_status["door_state"]
    try:
        import RPi.GPIO as GPIO  # type: ignore

        return "opened" if GPIO.input(DOOR_SENSOR_PIN) else "closed"
    except Exception:
        logger.exception("Door sensor read failed")
        return current_status["door_state"]


def send_ir_command(command: str) -> None:
    logger.info("IR command: %s (setpoint=%.0f°C)", command, set_temperature_c)
    if SIMULATE:
        return


def set_buzz(on: bool) -> None:
    global buzz
    buzz = bool(on)
    logger.info("Buzzer %s", "ON" if buzz else "OFF")


def execute_command(command: str) -> None:
    global set_temperature_c
    if command == "POWER_OFF":
        ac_state["power"] = "off"
        current_status["ac_state"] = "off"
        send_ir_command("POWER_OFF")
    elif command == "POWER_ON":
        ac_state["power"] = "on"
        current_status["ac_state"] = "on"
        send_ir_command("POWER_ON")
        send_ir_command(f"SET_TEMP_{int(round(set_temperature_c))}")
    elif command.startswith("SET_TEMP_"):
        try:
            set_temperature_c = float(command.split("_")[-1])
            ac_state["temperature"] = int(set_temperature_c)
            send_ir_command(command)
        except ValueError:
            logger.error("Bad SET_TEMP command: %s", command)
    elif command == "REPORT_STATUS":
        pass
    else:
        logger.warning("Unknown command: %s", command)


def enroll() -> None:
    global DEVICE_API_KEY
    payload = {"mac": _simulated_mac(), "firmware": "ac_client/sim"}
    if ENROLL_TOKEN:
        payload["enroll_token"] = ENROLL_TOKEN
    try:
        response = requests.post(
            f"{SERVER_URL}/api/v1/enroll",
            json=payload,
            headers=_headers(),
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("Enroll failed")
        return
    if response.status_code != 200:
        logger.error("Enroll HTTP %s: %s", response.status_code, response.text[:200])
        return
    data = response.json()
    if data.get("api_key"):
        DEVICE_API_KEY = data["api_key"]
        logger.info("Stored API key for room %s", data.get("room_number"))
    elif data.get("assigned"):
        logger.info("MAC assigned to room %s (using existing key)", data.get("room_number"))
    else:
        logger.info("Pending assignment for %s", _simulated_mac())


def heartbeat(ir_event: str | None = None) -> None:
    global set_temperature_c
    current_status["temperature"] = read_temperature()
    current_status["door_state"] = read_door_state()
    payload = {
        "mac": _simulated_mac(),
        "door_state": current_status["door_state"],
        "window_state": current_status["window_state"],
        "ac_state": current_status["ac_state"],
        "temperature_c": current_status["temperature"],
    }
    if ROOM_NUMBER:
        payload["room_number"] = ROOM_NUMBER
    if ir_event:
        payload["ir_event"] = ir_event
    try:
        response = requests.post(
            f"{SERVER_URL}/api/v1/heartbeat",
            json=payload,
            headers=_headers(),
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("Heartbeat failed; fail closed")
        return
    if response.status_code == 401:
        logger.error("Device API key rejected. Enroll or rotate the key.")
        return
    if response.status_code != 200:
        logger.error("Heartbeat HTTP %s: %s", response.status_code, response.text[:200])
        return
    data = response.json()
    if data.get("set_temperature_c") is not None:
        set_temperature_c = float(data["set_temperature_c"])
    set_buzz(bool(data.get("buzz")))
    for command in data.get("commands") or []:
        logger.info("Executing server command %s", command)
        execute_command(command)


def setup_gpio() -> None:
    if SIMULATE:
        logger.info("SIMULATE=1: skipping GPIO")
        return
    import RPi.GPIO as GPIO  # type: ignore

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(DOOR_SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def on_door(_channel):
        time.sleep(0.1)
        current_status["door_state"] = read_door_state()
        logger.info("Door -> %s", current_status["door_state"])
        heartbeat()

    GPIO.add_event_detect(DOOR_SENSOR_PIN, GPIO.BOTH, callback=on_door, bouncetime=300)


def cleanup() -> None:
    if SIMULATE:
        return
    try:
        import RPi.GPIO as GPIO  # type: ignore

        GPIO.cleanup()
    except Exception:
        pass


def main() -> None:
    def handle_signal(_sig, _frame):
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    setup_gpio()
    logger.info(
        "MAC %s room=%s -> %s (simulate=%s)",
        _simulated_mac(),
        ROOM_NUMBER or "(from MAC)",
        SERVER_URL,
        SIMULATE,
    )
    if not DEVICE_API_KEY:
        enroll()
        if not DEVICE_API_KEY:
            logger.info("No API key yet; polling enroll until an admin assigns this MAC.")
    while True:
        if not DEVICE_API_KEY:
            enroll()
        else:
            heartbeat()
        time.sleep(HEARTBEAT_SECONDS)


if __name__ == "__main__":
    main()
