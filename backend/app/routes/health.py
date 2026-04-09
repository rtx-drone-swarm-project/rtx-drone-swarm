"""Health-check endpoint for container and local readiness probes."""

from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
def health():
    """Return a minimal liveness payload when the backend process is reachable."""
    return {"ok": True}
