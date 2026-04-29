"""Pydantic models shared across mission and dispatch endpoints."""

from typing import Optional, List

from pydantic import BaseModel

class Bounds(BaseModel):
    """Latitude and longitude bounds for a mission search area."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

class Drone(BaseModel):
    """Mission-facing drone state used in REST payloads and WebSocket updates."""

    id: str
    lat: float
    lon: float
    sysid: Optional[int] = None
    alt: Optional[float] = None
    heading: Optional[float] = None
    groundspeed: Optional[float] = None
    battery_remaining: Optional[int] = None
    armed: Optional[bool] = None
    mode: Optional[str] = None
    telemetry_source: Optional[str] = None
    status: str = "idle"
    target_lat: Optional[float] = None
    target_lon: Optional[float] = None

class Hiker(BaseModel):
    """Represents a simulated missing person or target in the mission area."""

    id: str
    lat: float
    lon: float
    alt: Optional[float] = None
    found: bool = False

class MissionCreate(BaseModel):
    """Payload for creating a mission with bounds, drones, and optional hikers."""

    name: str
    bounds: Bounds
    drones: List[Drone]
    hikers: Optional[List[Hiker]] = None
    algorithm: Optional[str] = "voronoi"

class MissionStart(BaseModel):
    """Optional mission-start overrides for drones, algorithm, or hikers."""

    drones: Optional[List[Drone]] = None
    algorithm: Optional[str] = None
    hikers: Optional[List[Hiker]] = None


class DispatchAssignment(BaseModel):
    """Single direct-dispatch target for one drone."""

    drone_id: Optional[str] = None
    sysid: Optional[int] = None
    lat: float
    lon: float
    alt: Optional[float] = None


class DispatchTargetsRequest(BaseModel):
    """Batch request body for dispatching one or more drones to coordinates."""

    assignments: List[DispatchAssignment]
    host: Optional[str] = None
    count: Optional[int] = None
    timeout_seconds: Optional[float] = None


class DispatchResult(BaseModel):
    """Normalized success or failure result for a dispatch attempt."""

    drone_id: Optional[str] = None
    sysid: Optional[int] = None
    success: bool
    message: str
