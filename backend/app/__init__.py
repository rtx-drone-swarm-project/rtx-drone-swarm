# Backend for the search and rescue drone simulation. That currently includes:
# - FastAPI server with endpoints for creating and managing missions
# - Pydantic models for request validation and response formatting
# - In-memory "database" for storing mission data (to be replaced with Redis later)

# Re-export the fully-routed app from main so that `from app import app` works.
from app.main import app 