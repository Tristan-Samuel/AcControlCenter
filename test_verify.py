"""
Script to verify temperature changes to Fahrenheit
"""
import requests
from pprint import pprint
import re

# Base URL
BASE_URL = "http://localhost:5001"

def login_and_check_temps():
    """Login and check temperatures"""
    
    # Start a session to maintain cookies
    session = requests.Session()
    
    # Login with admin credentials
    login_data = {
        "username": "admin",
        "password": "password",
        "login_type": "password"  # This was missing before
    }
    
    # Login to get session cookie
    login_resp = session.post(f"{BASE_URL}/login", data=login_data, allow_redirects=True)
    
    print(f"Login response status: {login_resp.status_code}")
    
    # Check if we redirected to dashboard
    if '/admin_dashboard' in login_resp.url:
        print("Login successful - redirected to admin dashboard")
    else:
        print(f"Login might have failed - redirected to {login_resp.url}")
    
    # Check the room_status API directly
    status_resp = session.get(f"{BASE_URL}/api/room_status/7")
    if status_resp.status_code == 200:
        print("\nRoom Status API response (room 7):")
        room_data = status_resp.json()
        pprint(room_data)
        
        # Check if Fahrenheit temperature is present
        if 'temperature_f' in room_data:
            print(f"\nSuccess! Found Fahrenheit temperature: {room_data['temperature_f']}°F")
            print(f"Original Celsius temperature: {room_data['temperature']}°C")
            
            # Verify the conversion is correct
            calculated_f = round((room_data['temperature'] * 9/5) + 32, 1)
            if abs(calculated_f - room_data['temperature_f']) < 0.1:
                print("✓ Conversion math is correct!")
            else:
                print(f"✗ Conversion math might be wrong: calculated {calculated_f} vs API {room_data['temperature_f']}")
        else:
            print("✗ Fahrenheit temperature not found in API response")
    else:
        print(f"Failed to get room status: {status_resp.status_code}")
    
    # Check the temperature API
    temp_resp = session.get(f"{BASE_URL}/api/temperature/7")
    if temp_resp.status_code == 200:
        print("\nTemperature API response (room 7):")
        temp_data = temp_resp.json()
        pprint(temp_data)
        
        # Check if Fahrenheit temperature is present
        if 'temperature_f' in temp_data:
            print(f"\nSuccess! Found Fahrenheit temperature in temperature API: {temp_data['temperature_f']}°F")
            if temp_data.get('unit') == 'F':
                print("✓ Default unit is correctly set to Fahrenheit!")
            else:
                print(f"✗ Default unit is not set to Fahrenheit: {temp_data.get('unit', 'not set')}")
        else:
            print("✗ Fahrenheit temperature not found in temperature API response")
    else:
        print(f"Failed to get temperature: {temp_resp.status_code}")
    
if __name__ == "__main__":
    login_and_check_temps()