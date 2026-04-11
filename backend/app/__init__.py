"""Backend package entrypoint.

This package exposes the fully configured FastAPI application so tests and
local runners can import ``app`` directly from ``app``.
"""

from app.main import app
