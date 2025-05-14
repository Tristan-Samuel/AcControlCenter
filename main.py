import os
from app import app
import ngrok_tunnel

# Auth token provided by user
NGROK_AUTH_TOKEN = "2x4U0FjbqGDPTQPGYti7s49AAVd_Zu9aWMWdyNx4uy3nANCA"

if __name__ == "__main__":
    # Check if user wants to use ngrok (default to FALSE for local testing)
    # Set USE_NGROK=true in environment to enable remote access
    use_ngrok = os.environ.get('USE_NGROK', 'false').lower() in ('true', 'yes', '1', 't')
    
    print("\n---------- AC Control System ----------")
    print("  Server starting in", "REMOTE" if use_ngrok else "LOCAL ONLY", "mode\n")
    
    if use_ngrok:
        try:
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
                print("   You may have another ngrok session running elsewhere.")
                print("   Check https://dashboard.ngrok.com/tunnels to verify.\n")
        except Exception as e:
            print(f"⚠️ Ngrok error: {e}")
            print("   Running in local mode only\n")
    else:
        print("🖥️ Running in local mode only (ngrok disabled)")
        print("   Set USE_NGROK=true to enable remote access\n")
    
    # Start the Flask app
    app.run(host="0.0.0.0", port=5000, debug=True)