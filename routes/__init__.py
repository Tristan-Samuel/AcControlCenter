# Initialize routes package

from routes.admin import admin  # Import the blueprint from admin.py
import routes.main  # Import all main routes

#The blueprint registration should happen in app.py to avoid circular imports.
#This file only initializes the routes package.