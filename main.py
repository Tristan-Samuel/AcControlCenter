import os
import socket
from app import app
import ngrok_tunnel

# Auth token provided by user
NGROK_AUTH_TOKEN = "2x4U0FjbqGDPTQPGYti7s49AAVd_Zu9aWMWdyNx4uy3nANCA"

def get_local_ip():
    """Get the local IP address of this machine"""
    try:
        # Create a socket that connects to an external server
        # This trick helps find which network interface is used for default route
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # Google's DNS server
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"  # Fallback to localhost if can't determine

if __name__ == "__main__":
    # Check if user wants to use ngrok (default to FALSE for local testing)
    # Set USE_NGROK=true in environment to enable remote access
    use_ngrok = os.environ.get('USE_NGROK', 'false').lower() in ('true', 'yes', '1', 't')
    
    # Get local IP for LAN connections
    local_ip = get_local_ip()
    
    print("\n==================================================")
    print("            AC CONTROL SYSTEM SERVER              ")
    print("==================================================\n")
    
    # Print connection information
    print(f"📡 LOCAL ACCESS (Same Network):")
    print(f"   http://{local_ip}:5001")
    print(f"   http://localhost:5001\n")
    
    if use_ngrok:
        try:
            print("🌐 REMOTE ACCESS (Internet):")
            # Use provided token
            ngrok_tunnel.init_ngrok(NGROK_AUTH_TOKEN)
            
            # Start ngrok tunnel
            ngrok_url = ngrok_tunnel.start_tunnel(port=5001)
            
            if ngrok_url:
                print(f"   {ngrok_url}")
                print("\n📱 Raspberry Pi clients can connect from anywhere!")
                
                # Start monitoring thread to keep tunnel alive
                ngrok_tunnel.start_monitor_thread()
            else:
                print("   ⚠️ Ngrok tunnel not established!")
                print("   You may have another ngrok session running elsewhere.")
                print("   Check https://dashboard.ngrok.com/tunnels\n")
        except Exception as e:
            print(f"   ⚠️ Ngrok error: {e}")
            print("   Remote access is not available\n")
    else:
        print("🌐 REMOTE ACCESS (Internet):")
        print("   Not enabled")
        print("   Run with 'export USE_NGROK=true' to enable remote access\n")
    
    print("To allow others to connect:")
    print("1. For same network: Share your local IP address")
    print("2. For anywhere: Share your ngrok URL (when enabled)\n")
    
    print("==================================================\n")
    
    # Start the Flask app
    app.run(host="0.0.0.0", port=5001, debug=True)