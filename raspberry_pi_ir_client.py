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

# Server URL - will be updated dynamically if ngrok is available
SERVER_URL = "http://localhost:5000"  # Local server URL (fallback)
API_ENDPOINT = None  # Will be set once SERVER_URL is determined

# Flag to indicate if we should try to get ngrok URL
USE_NGROK = True

# Helper function to handle HTTP/HTTPS requests safely
def send_request(method, url, **kwargs):
    """
    Send HTTP/HTTPS request with fallback to HTTP if HTTPS fails
    
    Args:
        method: 'get' or 'post'
        url: Target URL
        **kwargs: Additional arguments for requests
        
    Returns:
        Response object or None on failure
    """
    # Force HTTPS to HTTP in offline mode if needed
    if url.startswith("https://") and not url.startswith("https://ngrok"):
        # Only convert non-ngrok URLs to HTTP (local dev URLs)
        fallback_url = url.replace("https://", "http://")
    else:
        fallback_url = url
        
    try:
        # Try the original URL first
        if method.lower() == 'get':
            response = requests.get(url, **kwargs)
        else:
            response = requests.post(url, **kwargs)
        return response
    except requests.exceptions.SSLError:
        # If SSL error, try with HTTP instead
        logger.warning(f"SSL error with {url}, trying HTTP fallback")
        if method.lower() == 'get':
            return requests.get(fallback_url, **kwargs)
        else:
            return requests.post(fallback_url, **kwargs)
    except Exception as e:
        logger.error(f"Request error: {e}")
        return None

def update_server_url():
    """Update the server URL to use ngrok if available"""
    global SERVER_URL, API_ENDPOINT
    
    if USE_NGROK:
        try:
            # Try to get the ngrok URL from the server using our safe request helper
            response = send_request('get', f"{SERVER_URL}/api/tunnel_url", timeout=5)
            if response and response.status_code == 200:
                data = response.json()
                if data.get("url") and data.get("status") == "active":
                    SERVER_URL = data["url"]
                    logger.info(f"Using ngrok tunnel URL: {SERVER_URL}")
                elif data.get("url") and data.get("status") == "offline" and data.get("supports_https", False):
                    # If offline mode but HTTPS is supported, use HTTP anyway
                    SERVER_URL = data["url"]
                    # Replace https with http if present - this fixes the offline HTTPS issue
                    if SERVER_URL.startswith("https://"):
                        SERVER_URL = SERVER_URL.replace("https://", "http://")
                    logger.info(f"Using offline mode with HTTP URL: {SERVER_URL}")
        except Exception as e:
            logger.warning(f"Could not get ngrok URL, using local URL: {e}")
    
    # Update API endpoint with current SERVER_URL
    API_ENDPOINT = f"{SERVER_URL}/receive_data"
    logger.info(f"Server URL set to: {SERVER_URL}")
    logger.info(f"API endpoint set to: {API_ENDPOINT}")

# Initialize server URL
update_server_url()

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
    
    # Report the command to the server and ask for permission
    # This is a more secure approach, letting the server decide what to do
    allowed, server_response = request_server_permission(code)
    
    if not allowed:
        logger.warning(f"Command {code} intercepted by server: {server_response.get('reason', 'Policy violation')}")
        # Provide user feedback (beep, LED flash, etc.)
        
        # If the server wants us to do something else instead, do it
        if 'alternative_action' in server_response:
            logger.info(f"Executing server-recommended alternative: {server_response['alternative_action']}")
            execute_server_action(server_response['alternative_action'])
            
        return False
    else:
        # Server allowed the command, execute it locally
        execute_command(code)
        
        # Update server with new state
        send_status_update()
        
        return True

def request_server_permission(code):
    """Ask the server for permission to execute a command"""
    try:
        payload = {
            "room_number": ROOM_NUMBER,
            "command": code,
            "window_state": current_status["window_state"],
            "ac_state": current_status["ac_state"],
            "temperature": current_status["temperature"]
        }
        
        response = requests.post(f"{SERVER_URL}/api/check_command", json=payload, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            return data.get("allowed", False), data
        else:
            # Connection issue or server error - fail closed (more secure)
            logger.error(f"Server returned error {response.status_code}. Failing closed.")
            return False, {"reason": "Server communication error"}
            
    except Exception as e:
        logger.error(f"Error requesting permission: {e}")
        # On any exception, fail closed (secure)
        return False, {"reason": "Connection error"}

def execute_command(code):
    """Execute a command after server approval"""
    # Example mapping of IR codes to actions
    commands = {
        "POWER": toggle_power,
        "TEMP_UP": lambda: change_temperature(1),
        "TEMP_DOWN": lambda: change_temperature(-1),
        "MODE": cycle_mode,
        "FAN": cycle_fan_speed
    }
    
    # Process the command
    if code in commands:
        logger.info(f"Executing approved command: {code}")
        commands[code]()
    else:
        logger.warning(f"Unknown command code: {code}")
        
def execute_server_action(action):
    """Execute an action recommended by the server"""
    if action == "TURN_OFF":
        if current_status["ac_state"] == "on":
            toggle_power()  # Turn off the AC
            
    elif action == "TURN_ON":
        if current_status["ac_state"] == "off":
            toggle_power()  # Turn on the AC
            
    elif action.startswith("SET_TEMP_"):
        try:
            temp = int(action.split("_")[-1])
            # Set temperature to what the server wants
            current_temp = ac_state["temperature"]
            if temp > current_temp:
                for _ in range(temp - current_temp):
                    change_temperature(1)
            elif temp < current_temp:
                for _ in range(current_temp - temp):
                    change_temperature(-1)
        except (ValueError, IndexError):
            logger.error(f"Invalid temperature in server action: {action}")
            
    elif action == "REPORT_STATUS":
        # Just report status without changing anything
        send_status_update()
    else:
        logger.warning(f"Unknown server action: {action}")

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
            
            # If server says to intercept, log the reason
            if data.get("intercept", False):
                reason = data.get("reason", "Policy violation")
                logger.warning(f"Command {command} intercepted: {reason}")
                
                # Display reason on LCD or LED indicator if available
                # TODO: Add code for LCD display
                
                return True, reason
            
            # If there are policy limits, adjust our local settings
            policy = data.get("policy", {})
            if policy.get("min_temp") is not None:
                logger.info(f"Policy min temperature: {policy.get('min_temp')}°C")
            if policy.get("max_temp") is not None:
                logger.info(f"Policy max temperature: {policy.get('max_temp')}°C")
                
            return False, None
        
    except Exception as e:
        logger.error(f"Error checking policy: {e}")
    
    # If server is unreachable or any error occurs, default to allowing the command
    return False, None

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

# Send IR command event to server
def send_ir_command_event(command):
    """Send IR command information to the server"""
    try:
        # Include command information
        payload = {
            "room_number": ROOM_NUMBER,
            "command": command,
            "temperature": current_status["temperature"]
        }
        
        response = requests.post(f"{SERVER_URL}/receive_data", json=payload)
        
        if response.status_code == 200:
            logger.info(f"IR command {command} sent to server successfully")
            data = response.json()
            
            # Check if command was successful
            if not data.get("success", True):
                logger.warning(f"Server rejected command: {data.get('message', 'Unknown reason')}")
                return False, data.get("message")
            
            return True, None
            
        else:
            logger.error(f"Failed to send IR command to server: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Error sending IR command to server: {e}")
        
    return False, "Server communication error"

# Send status update to server
def send_status_update():
    """Send current status to the central server"""
    # Update temperature reading
    current_status["temperature"] = read_temperature()
    current_status["last_update"] = datetime.now().isoformat()
    
    try:
        # Include all relevant status information
        payload = {
            "room_number": ROOM_NUMBER,
            "window_state": current_status["window_state"],
            "ac_state": current_status["ac_state"],
            "temperature": current_status["temperature"]
        }
        
        response = requests.post(f"{SERVER_URL}/receive_data", json=payload)
        
        if response.status_code == 200:
            data = response.json()
            logger.info("Status update sent successfully")
            
            # Check if server wants us to force a state change
            if "force_ac_state" in data:
                forced_state = data["force_ac_state"]
                logger.info(f"Server forcing AC state to: {forced_state}")
                
                # Only change state if it's different
                if current_status["ac_state"] != forced_state:
                    # Update local state
                    ac_state["power"] = forced_state
                    current_status["ac_state"] = forced_state
                    
                    # Send command to AC
                    if forced_state == "on":
                        send_ir_command("POWER_ON")
                    else:
                        send_ir_command("POWER_OFF")
            
            # Check for any actions required by the server
            if data.get("action") == "turn_off_ac" and current_status["ac_state"] == "on":
                logger.warning("Server requested AC turn off")
                toggle_power()  # Turn off the AC
                
            return True
        else:
            logger.error(f"Failed to send status update: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Error sending status update: {e}")
        
    return False

# Background thread for regular status updates
def status_update_thread():
    """Background thread to periodically update status"""
    update_counter = 0
    while True:
        try:
            # Send regular status update
            send_status_update()
            
            # Every 10 updates (10 minutes), check if ngrok URL has changed
            update_counter += 1
            if update_counter >= 10:
                logger.info("Checking for ngrok URL updates...")
                update_server_url()
                update_counter = 0
                
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