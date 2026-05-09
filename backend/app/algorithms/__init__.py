# app/algorithms/__init__.py
import logging
from typing import Dict, Type

from app.algorithms.apf import PotentialFieldsCoverage
from app.algorithms.base import BaseSearchAlgorithm
from app.algorithms.boustrophedon import VoronoiBoustrophedon
from app.algorithms.voronoi import VoronoiACOCoverage, VoronoiCoverage
from app.algorithms.vaco import VoronoiACOHybridCoverage


logger = logging.getLogger(__name__)

# Class registry — ``get_algorithm`` returns a new instance each time so stateful
# strategies (e.g. VoronoiACOCoverage pheromone) do not leak across missions.
_ALGORITHM_CLASSES: Dict[str, Type[BaseSearchAlgorithm]] = {
    "voronoi": VoronoiCoverage,
    "apf": PotentialFieldsCoverage,
    "voronoi_aco": VoronoiACOCoverage,
    "sweep": VoronoiBoustrophedon,
    "acs": VoronoiACOHybridCoverage,
}


def get_algorithm(name: str) -> BaseSearchAlgorithm:
    """Return a new algorithm instance for this mission run."""
    cls = _ALGORITHM_CLASSES.get(name)
    if cls is None:
        logger.warning(
            "Unknown coverage algorithm %r; using voronoi. Valid keys: %s",
            name,
            sorted(_ALGORITHM_CLASSES.keys()),
        )
        cls = VoronoiCoverage
    return cls()


def list_algorithm_keys() -> list[str]:
    return sorted(_ALGORITHM_CLASSES.keys())
