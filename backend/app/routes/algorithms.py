"""Routes exposing discovered search algorithms to frontend controls."""

from fastapi import APIRouter

from app.algorithms import list_algorithms


router = APIRouter(prefix="/algorithms", tags=["algorithms"])


@router.get("")
def get_algorithms():
    """Return discovered algorithm metadata for mission and benchmark UIs."""
    return {"algorithms": list_algorithms()}
