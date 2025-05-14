import os
from app import app
import ngrok_tunnel

# Auth token provided by user
NGROK_AUTH_TOKEN = "2x4U0FjbqGDPTQPGYti7s49AAVd_Zu9aWMWdyNx4uy3nANCA"

if __name__ == "__main__":
    # Check if user wants to use ngrok (default to True)
    use_ngrok = os.environ.get('USE_NGROK', 'true').lower() in ('true', 'yes', '1', 't')
    
    if use_ngrok:
        # Use provided token
        ngrok_tunnel.init_ngrok(NGROK_AUTH_TOKEN)
        
        # Start ngrok tunnel
        ngrok_url = ngrok_tunnel.start_tunnel(port=5000)
        
        if ngrok_url:
            print(f"🌐 Public URL: {ngrok_url}")
            print("📱 Raspberry Pi clients can connect from anywhere!")
            
            # Start monitoring thread to keep tunnel alive
            ngrok_tunnel.start_monitor_thread()
        else:
            print("⚠️ Ngrok tunnel not established. Running in local mode only.")
    else:
        print("🖥️ Running in local mode only (ngrok disabled)")
    
    # Start the Flask app
    app.run(host="0.0.0.0", port=5000, debug=True)