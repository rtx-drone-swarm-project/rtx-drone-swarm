"""Pydantic models shared across mission and dispatch endpoints."""

from typing import Optional, List, Literal, Dict, Tuple, Set
from dataclasses import dataclass
from pydantic import BaseModel
import numpy as np

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

@dataclass
class Mission:
    id: str
    name: str
    status: Literal["idle", "searching", "search_complete", "recalling", "paused", "mission_complete"]
    progress: float
    elapsed_seconds: int
    completion_elapsed_seconds: int
    algorithm: str
    bounds: Dict[str, float]
    drones: List[Dict]
    hikers: List[Dict]
    targets: List[Dict]
    grid: np.ndarray or None

    _dense_coverage_grid: np.ndarray or None
    _dense_grid_size: int
    _dense_covered_count: int
    _found_target_ids: Set[str]

    sweep_paths: Dict[str, List[Tuple[float, float]]]
    sweep_centroids: Dict[str, Tuple[float, float]]
    sweep_phase: Dict[str, str]
    sweep_reached_radius: float

    covered_set: Set[Tuple[int, int]]

    def __init__(self, mission_id: str, mission_data: MissionCreate):
        self.id = mission_id
        self.name = mission_data.name
        self.status = "idle"
        self.progress = 0.0
        self.elapsed_seconds = 0
        self.completion_elapsed_seconds = 0
        self.algorithm = getattr(mission_data, "algorithm", "voronoi")
        self.bounds = mission_data.bounds.model_dump()
        self.drones = [d.model_dump() for d in mission_data.drones]
        self.hikers = [m.model_dump() for m in mission_data.hikers] if mission_data.hikers else []
        self.targets = []
        self.grid = None

        self._dense_coverage_grid = None
        self._dense_grid_size = 0
        self._dense_covered_count = 0
        self._found_target_ids = set()

        self.sweep_paths = {}
        self.sweep_centroids = {}
        self.sweep_phase = {}
        self.sweep_reached_radius = None

        self.covered_set = set()

    def to_dict(self):
        data = {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "progress": self.progress,
            "elapsed_seconds": self.elapsed_seconds,
            "completion_elapsed_seconds": self.completion_elapsed_seconds,
            "algorithm": self.algorithm,
            "bounds": self.bounds,
            "drones": self.drones,
            "hikers": self.hikers,
            "targets": self.targets,
            "grid": self.grid,
        }

        if self.grid is not None and type(self.grid) is np.ndarray:
            data["grid"] = self.grid.tolist()

        return data

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
