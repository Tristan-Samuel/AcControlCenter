import requests
import json
import time
import random

# URL of your Flask application's receive_data endpoint
url = "http://127.0.0.1:5000/receive_data"

def send_test_data(room_number, window_state, ac_state, temp):
    """Send test data to the Flask application"""
    
    data = {
        "room_number": room_number,
        "window_state": window_state,
        "ac_state": ac_state,
        "temperature": temp
    }
    
    try:
        headers = {"Content-Type": "application/json"}
        response = requests.post(url, data=json.dumps(data), headers=headers)
        
        if response.status_code == 200:
            print(f"Data sent successfully: {data}")
            print(f"Response: {response.json()}")
        else:
            print(f"Failed to send data. Status code: {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error sending data: {str(e)}")

if __name__ == "__main__":
    # Specify a room number for testing
    room_number = "7"  # Change this to match an existing room in your system
    
    # Send a window opened event
    send_test_data(
        room_number=room_number,
        window_state="opened",
        ac_state="on",
        temp=random.uniform(20.0, 28.0)
    )
    
    # Wait a moment
    time.sleep(2)
    
    # Send a window closed event
    send_test_data(
        room_number=room_number,
        window_state="closed",
        ac_state="off",
        temp=random.uniform(20.0, 28.0)
    )
    
    print("Test data sent. Check your Flask application for logged events.")