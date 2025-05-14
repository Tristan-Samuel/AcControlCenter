import os
from app import app
import ngrok_tunnel

if __name__ == "__main__":
    # Check if ngrok authentication token is available
    ngrok_token = os.environ.get('NGROK_AUTH_TOKEN')
    
    if ngrok_token:
        # Initialize ngrok with auth token if available
        ngrok_tunnel.init_ngrok(ngrok_token)
    else:
        # Initialize without token (limited functionality)
        ngrok_tunnel.init_ngrok()
    
    # Start ngrok tunnel
    ngrok_url = ngrok_tunnel.start_tunnel(port=5000)
    
    if ngrok_url:
        print(f"🌐 Public URL: {ngrok_url}")
        print("📱 Raspberry Pi clients can connect from anywhere!")
        
        # Start monitoring thread to keep tunnel alive
        ngrok_tunnel.start_monitor_thread()
    else:
        print("⚠️ Ngrok tunnel not established. Running in local mode only.")
    
    # Start the Flask app
    app.run(host="0.0.0.0", port=5000, debug=True)