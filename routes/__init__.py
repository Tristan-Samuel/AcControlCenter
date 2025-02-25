# Initialize routes package
from app import app
from routes.admin import admin  # Import the blueprint from admin.py
import routes.main  # Import all main routes

# Register blueprints
app.register_blueprint(admin)
app.register_blueprint(routes.main.main)