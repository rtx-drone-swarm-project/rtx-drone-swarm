from pydantic import BaseModel
from typing import Optional, List

class Bounds(BaseModel):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

class Drone(BaseModel):
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
    id: str
    lat: float
    lon: float
    alt: Optional[float] = None
    found: bool = False

class MissionCreate(BaseModel):
    name: str
    bounds: Bounds
    drones: List[Drone]
    hikers: Optional[List[Hiker]] = None

class MissionStart(BaseModel):
    drones: Optional[List[Drone]] = None
    algorithm: Optional[str] = None
    hikers: Optional[List[Hiker]] = None


class DispatchAssignment(BaseModel):
    drone_id: Optional[str] = None
    sysid: Optional[int] = None
    lat: float
    lon: float
    alt: Optional[float] = None


class DispatchTargetsRequest(BaseModel):
    assignments: List[DispatchAssignment]
    host: Optional[str] = None
    count: Optional[int] = None
    timeout_seconds: Optional[float] = None


class DispatchResult(BaseModel):
    drone_id: Optional[str] = None
    sysid: Optional[int] = None
    success: bool
    message: str
