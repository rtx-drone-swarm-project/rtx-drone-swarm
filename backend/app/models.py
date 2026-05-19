"""Pydantic models shared across mission, benchmark, and dispatch endpoints."""

from typing import Optional, List, Literal, Dict, Tuple, Set
from dataclasses import dataclass
from pydantic import BaseModel, Field, model_validator
import numpy as np

class Bounds(BaseModel):
    """Latitude and longitude bounds for a mission search area."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    @model_validator(mode="after")
    def validate_rectangular_bounds(self):
        if not -90 <= self.min_lat <= 90 or not -90 <= self.max_lat <= 90:
            raise ValueError("Latitude must be between -90 and 90")
        if not -180 <= self.min_lon <= 180 or not -180 <= self.max_lon <= 180:
            raise ValueError("Longitude must be between -180 and 180")
        if self.min_lat >= self.max_lat:
            raise ValueError("min_lat must be less than max_lat")
        if self.min_lon >= self.max_lon:
            raise ValueError("min_lon must be less than max_lon")
        return self

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
    movement: Literal["stationary", "moving"] = "moving"

class MissionCreate(BaseModel):
    """Payload for creating a mission with bounds, drones, and optional hikers."""

    name: str
    bounds: Bounds
    drones: Optional[List[Drone]] = None
    hikers: Optional[List[Hiker]] = None
    algorithm: Optional[str] = "voronoi"

class MissionStart(BaseModel):
    """Optional mission-start overrides for drones, algorithm, or hikers."""

    drones: Optional[List[Drone]] = None
    algorithm: Optional[str] = None
    hikers: Optional[List[Hiker]] = None


class ConfirmSearchAreaRequest(BaseModel):
    """Payload for confirming mission bounds and initializing grid-edit state."""

    bounds: Bounds
    grid_side: Optional[int] = Field(default=None, gt=0)


class PreviewProbabilityRegionRequest(BaseModel):
    """Payload for previewing which probability-grid cells a rectangle will affect."""

    rect_bounds: Bounds


class ApplyProbabilityRegionRequest(BaseModel):
    """Payload for applying a region label to the probability grid."""

    label: Literal[
        "very_unlikely",
        "unlikely",
        "normal",
        "likely",
        "very_likely",
        "excluded",
    ]
    rect_bounds: Bounds

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
    grid: np.ndarray | None
    grid_shape: Tuple[int, int] | None
    probability_grid: np.ndarray | None
    probability_grid_config: Dict[str, object]
    operator_label_grid: np.ndarray | None
    searchable_mask: np.ndarray | None
    search_area_confirmed: bool
    probability_grid_confirmed: bool

    _dense_coverage_grid: np.ndarray | None
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
        self.drones = [d.model_dump() for d in mission_data.drones] if mission_data.drones else []
        self.hikers = [m.model_dump() for m in mission_data.hikers] if mission_data.hikers else []
        self.targets = []
        self.grid = None
        self.grid_shape = None
        self.probability_grid = None
        self.probability_grid_config = {
            "smoothing_passes": 1,
            "regions": [],
        }
        self.operator_label_grid = None
        self.searchable_mask = None
        self.search_area_confirmed = False
        self.probability_grid_confirmed = False

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
            "grid_shape": self.grid_shape,
            "probability_grid": self.probability_grid,
            "probability_grid_config": self.probability_grid_config,
            "operator_label_grid": self.operator_label_grid,
            "searchable_mask": self.searchable_mask,
            "search_area_confirmed": self.search_area_confirmed,
            "probability_grid_confirmed": self.probability_grid_confirmed,
        }

        if self.grid is not None and type(self.grid) is np.ndarray:
            data["grid"] = self.grid.tolist()
        if self.grid_shape is not None and type(self.grid_shape) is tuple:
            data["grid_shape"] = list(self.grid_shape)
        if self.probability_grid is not None and type(self.probability_grid) is np.ndarray:
            data["probability_grid"] = self.probability_grid.tolist()
        if self.operator_label_grid is not None and type(self.operator_label_grid) is np.ndarray:
            data["operator_label_grid"] = self.operator_label_grid.tolist()
        if self.searchable_mask is not None and type(self.searchable_mask) is np.ndarray:
            data["searchable_mask"] = self.searchable_mask.tolist()

        return data

class BenchmarkRequest(BaseModel):
    """Configuration for a paired headless algorithm benchmark run."""

    algorithms: List[str] = Field(default_factory=lambda: ["voronoi", "apf", "sweep"], min_length=1)
    iterations: int = Field(default=50, ge=1, le=500)
    bounds: Bounds
    drone_count: int = Field(default=5, ge=1, le=50)
    target_count: int = Field(default=3, ge=1, le=20)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    scenario_profile: str = "uniform_random"
    seed: Optional[int] = Field(default=None, ge=0)


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
