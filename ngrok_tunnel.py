#!/usr/bin/env python3
"""
Ngrok Tunnel Manager for AC Control System

This module provides functionality to create an ngrok tunnel to expose
the local Flask application to the internet, allowing remote Raspberry Pi 
clients to connect from anywhere.

Features:
- Creates secure HTTPS tunnel to local Flask server
- Automatically updates Raspberry Pi clients with the public URL
- Maintains connection status and logs events
- Handles authentication with ngrok service
"""

import os
import logging
import threading
import time
from pyngrok import ngrok, conf, exception
from flask import current_app

# Configure logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ngrok_tunnel")

# Global variables
public_url = None
tunnel = None
tunnel_thread = None
is_running = False

def init_ngrok(auth_token=None):
    """Initialize ngrok with optional auth token"""
    # Set auth token if provided
    if auth_token:
        conf.get_default().auth_token = auth_token
        logger.info("Ngrok configured with authentication token")
    else:
        logger.warning("No ngrok auth token provided. Using limited free tier.")
        logger.warning("Create an account at https://dashboard.ngrok.com/ to get a token")
        
    # Kill any existing ngrok processes to avoid port conflicts
    try:
        ngrok.kill()
        logger.info("Killed existing ngrok processes")
    except:
        pass
    
def start_tunnel(port=5000):
    """Start ngrok tunnel to specified port"""
    global public_url, tunnel, is_running
    
    try:
        # Create HTTP tunnel - convert port to string for pyngrok
        tunnel = ngrok.connect(addr=str(port), proto="http")
        
        # Handle public URL property
        if tunnel and hasattr(tunnel, 'public_url') and tunnel.public_url:
            public_url = tunnel.public_url
            if public_url.startswith("http://"):
                public_url = public_url.replace("http://", "https://")
            
            logger.info(f"Ngrok tunnel established: {public_url}")
            logger.info(f"Forwarding to local port: {port}")
            
            # Store public URL in environment for clients to access
            os.environ["NGROK_PUBLIC_URL"] = public_url
            
            is_running = True
            return public_url
        else:
            logger.error("Tunnel created but no public URL available")
            return None
        
    except exception.PyngrokError as e:
        logger.error(f"Ngrok tunnel error: {e}")
        return None

def stop_tunnel():
    """Stop the active ngrok tunnel"""
    global tunnel, is_running, public_url
    
    if tunnel and hasattr(tunnel, 'public_url') and tunnel.public_url:
        try:
            ngrok.disconnect(tunnel.public_url)
            logger.info("Ngrok tunnel disconnected")
        except exception.PyngrokError as e:
            logger.error(f"Error disconnecting tunnel: {e}")
            
    # Reset all state variables
    tunnel = None
    public_url = None
    is_running = False

def monitor_tunnel():
    """Background thread to keep tunnel alive and monitor status"""
    global is_running, public_url
    
    while is_running:
        try:
            # Check if tunnel is still active
            tunnels = ngrok.get_tunnels()
            if not tunnels and is_running:
                logger.warning("Tunnel appears to be down, attempting to restart...")
                start_tunnel()
                
            # Sleep for a bit
            time.sleep(30)
            
        except Exception as e:
            logger.error(f"Error in tunnel monitor: {e}")
            time.sleep(5)

def start_monitor_thread():
    """Start the background monitoring thread"""
    global tunnel_thread, is_running
    
    if not is_running or not tunnel_thread or not tunnel_thread.is_alive():
        is_running = True
        tunnel_thread = threading.Thread(target=monitor_tunnel)
        tunnel_thread.daemon = True
        tunnel_thread.start()
        logger.info("Tunnel monitor thread started")

def get_public_url():
    """Get the current public URL"""
    global public_url
    return public_url

def init_app(app, auth_token=None):
    """Initialize ngrok with Flask app"""
    # Ensure ngrok is properly initialized
    init_ngrok(auth_token)
    
    # Start the tunnel when app starts
    @app.before_first_request
    def start_ngrok():
        """Start ngrok tunnel on first request"""
        if not is_running:
            start_tunnel()
            start_monitor_thread()
            
            # Add public URL to app config
            app.config['NGROK_URL'] = public_url
    
    # When app shuts down, close the tunnel
    @app.teardown_appcontext
    def close_ngrok(exception=None):
        """Close ngrok tunnel when application context ends"""
        stop_tunnel()
    
    # Add utility route to get current tunnel URL
    @app.route('/api/tunnel_url')
    def tunnel_url():
        """Return current public URL for clients"""
        return {"url": public_url, "status": "active" if is_running else "inactive"}
    
    return app

if __name__ == "__main__":
    # Test the tunnel directly if script is run
    init_ngrok()
    url = start_tunnel()
    start_monitor_thread()
    
    print(f"Tunnel URL: {url}")
    try:
        # Keep the script running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
        stop_tunnel()