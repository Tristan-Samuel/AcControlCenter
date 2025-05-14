#!/usr/bin/env python3
"""
AC Controller Client for Raspberry Pi

This script runs on a Raspberry Pi with an IR receiver and transmitter to:
1. Monitor window open/close status using a magnetic reed sensor
2. Intercept AC remote commands using the IR receiver
3. Send commands to the AC unit using the IR transmitter
4. Communicate with the central server to obey global policies

Hardware Requirements:
- Raspberry Pi with GPIO pins
- IR receiver (e.g., TSOP38238)
- IR transmitter (e.g., IR LED with transistor driver)
- Magnetic reed switch (for window status)
- Temperature/humidity sensor (e.g., DHT22/AM2302)

Dependencies:
- RPi.GPIO: For GPIO control
- pigpio: For precise IR timing
- LIRC: For IR code learning and playback
- requests: For API communication

Setup:
1. Install required libraries:
   sudo apt-get update
   sudo apt-get install python3-pip python3-rpi.gpio lirc
   sudo pip3 install pigpio requests

2. Configure LIRC for your IR receiver and transmitter
   Edit /etc/lirc/lirc_options.conf and /boot/config.txt accordingly

3. Learn your AC remote codes using:
   irrecord -d /dev/lirc0 ac_remote.conf

4. Update the ROOM_NUMBER and SERVER_URL constants below
"""

import os
import sys
import time
import json
import signal
import logging
import threading
import RPi.GPIO as GPIO
import pigpio
import requests
from datetime import datetime

# Configuration
ROOM_NUMBER = "7"  # Update this to your room number
SERVER_URL = "http://example.com:5000"  # Update with your server URL
API_ENDPOINT = f"{SERVER_URL}/api/receive_data"

# GPIO Pin Configuration
WINDOW_SENSOR_PIN = 17  # GPIO pin for window sensor
TEMPERATURE_SENSOR_PIN = 4  # GPIO pin for temperature sensor
IR_RECEIVER_PIN = 18  # GPIO pin for IR receiver
IR_TRANSMITTER_PIN = 22  # GPIO pin for IR transmitter

# AC State
ac_state = {
    "power": "off",
    "temperature": 24,
    "mode": "cool",
    "fan_speed": "auto"
}

# Current status
current_status = {
    "room_number": ROOM_NUMBER,
    "window_state": "closed",
    "ac_state": "off",
    "temperature": 22.0,
    "last_update": datetime.now().isoformat()
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ac_controller.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("AC_Controller")

# Initialize GPIO
def setup_gpio():
    """Initialize GPIO pins"""
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(WINDOW_SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    # Setup interrupt for window sensor
    GPIO.add_event_detect(WINDOW_SENSOR_PIN, 
                          GPIO.BOTH, 
                          callback=window_state_changed, 
                          bouncetime=300)
    
    logger.info("GPIO initialized")

# Window state change handler
def window_state_changed(channel):
    """Handle window state changes"""
    time.sleep(0.1)  # Debounce
    
    # Read window state (LOW when closed, HIGH when open with pull-up resistor)
    window_state = "opened" if GPIO.input(WINDOW_SENSOR_PIN) else "closed"
    
    logger.info(f"Window state changed to: {window_state}")
    current_status["window_state"] = window_state
    
    # Send update to server
    send_status_update()

# Read temperature from sensor
def read_temperature():
    """Read temperature from DHT22 sensor"""
    # In a real implementation, use Adafruit_DHT or similar library
    # For simulation, we'll add a small random variation
    import random
    base_temp = 22.5
    variation = random.uniform(-0.5, 0.5)
    return round(base_temp + variation, 1)

# IR command handler
def handle_ir_command(code):
    """Process received IR command"""
    logger.info(f"IR command received: {code}")
    
    # Example mapping of IR codes to actions
    # In a real implementation, you would decode the IR signals properly
    commands = {
        "POWER": toggle_power,
        "TEMP_UP": lambda: change_temperature(1),
        "TEMP_DOWN": lambda: change_temperature(-1),
        "MODE": cycle_mode,
        "FAN": cycle_fan_speed
    }
    
    # Check if we should intercept this command
    should_intercept = check_server_policy(code)
    
    if should_intercept:
        logger.info(f"Command {code} intercepted due to policy restrictions")
        # Optionally provide user feedback (beep, LED flash, etc.)
    else:
        # Process the command
        if code in commands:
            commands[code]()
        
        # Update server with new state
        send_status_update()

# Check if command should be intercepted based on server policy
def check_server_policy(command):
    """Check with server if the command should be intercepted"""
    try:
        response = requests.get(
            f"{SERVER_URL}/api/check_policy/{ROOM_NUMBER}", 
            params={"command": command, "current_temp": current_status["temperature"]}
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get("intercept", False)
        
    except Exception as e:
        logger.error(f"Error checking policy: {e}")
    
    # Default to not intercepting if we can't reach the server
    return False

# AC control functions
def toggle_power():
    """Toggle AC power state"""
    ac_state["power"] = "on" if ac_state["power"] == "off" else "off"
    current_status["ac_state"] = ac_state["power"]
    logger.info(f"AC power toggled to: {ac_state['power']}")
    
    # Send IR command to AC
    send_ir_command("POWER")

def change_temperature(delta):
    """Change AC temperature setting"""
    ac_state["temperature"] += delta
    # Limit temperature range
    ac_state["temperature"] = max(18, min(30, ac_state["temperature"]))
    logger.info(f"AC temperature changed to: {ac_state['temperature']}°C")
    
    # Send IR command to AC
    send_ir_command(f"TEMP_{ac_state['temperature']}")

def cycle_mode():
    """Cycle through AC modes (cool, heat, fan, dry)"""
    modes = ["cool", "heat", "fan", "dry"]
    current_index = modes.index(ac_state["mode"])
    ac_state["mode"] = modes[(current_index + 1) % len(modes)]
    logger.info(f"AC mode changed to: {ac_state['mode']}")
    
    # Send IR command to AC
    send_ir_command(f"MODE_{ac_state['mode'].upper()}")

def cycle_fan_speed():
    """Cycle through fan speeds (auto, low, medium, high)"""
    speeds = ["auto", "low", "medium", "high"]
    current_index = speeds.index(ac_state["fan_speed"])
    ac_state["fan_speed"] = speeds[(current_index + 1) % len(speeds)]
    logger.info(f"AC fan speed changed to: {ac_state['fan_speed']}")
    
    # Send IR command to AC
    send_ir_command(f"FAN_{ac_state['fan_speed'].upper()}")

# Send IR command to AC
def send_ir_command(command):
    """Send IR command to AC unit"""
    logger.info(f"Sending IR command: {command}")
    # In a real implementation, use LIRC to send the command
    # os.system(f"irsend SEND_ONCE ac_remote {command}")
    
    # Simulate IR transmission
    logger.info(f"IR signal sent: {command}")

# Send status update to server
def send_status_update():
    """Send current status to the central server"""
    # Update temperature reading
    current_status["temperature"] = read_temperature()
    current_status["last_update"] = datetime.now().isoformat()
    
    try:
        response = requests.post(API_ENDPOINT, json=current_status)
        if response.status_code == 200:
            data = response.json()
            logger.info(f"Status update sent: {data}")
            
            # Check if server wants us to force a state change
            if "force_ac_state" in data:
                forced_state = data["force_ac_state"]
                logger.info(f"Server forcing AC state to: {forced_state}")
                
                # Update local state
                ac_state["power"] = forced_state
                current_status["ac_state"] = forced_state
                
                # Send command to AC
                if forced_state == "on":
                    send_ir_command("POWER_ON")
                else:
                    send_ir_command("POWER_OFF")
        else:
            logger.error(f"Failed to send status update: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Error sending status update: {e}")

# Background thread for regular status updates
def status_update_thread():
    """Background thread to periodically update status"""
    while True:
        try:
            send_status_update()
            time.sleep(60)  # Update every minute
        except Exception as e:
            logger.error(f"Error in status update thread: {e}")
            time.sleep(60)  # Retry after a minute

# Cleanup function
def cleanup():
    """Clean up GPIO and other resources"""
    logger.info("Cleaning up resources...")
    GPIO.cleanup()

# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    """Handle termination signals"""
    logger.info("Shutdown signal received")
    cleanup()
    sys.exit(0)

# Main function
def main():
    """Main function"""
    try:
        # Register signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Setup GPIO
        setup_gpio()
        
        # Start status update thread
        updater = threading.Thread(target=status_update_thread)
        updater.daemon = True
        updater.start()
        
        logger.info(f"AC Controller started for Room {ROOM_NUMBER}")
        logger.info(f"Connecting to server at {SERVER_URL}")
        
        # Initial status update
        send_status_update()
        
        # In a real implementation, you would start an IR receiver loop here
        # For the example, we'll simulate by just keeping the script running
        while True:
            time.sleep(1)
            
    except Exception as e:
        logger.error(f"Error in main function: {e}")
    finally:
        cleanup()

if __name__ == "__main__":
    main()