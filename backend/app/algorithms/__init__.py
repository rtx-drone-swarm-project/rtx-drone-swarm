# app/algorithms/__init__.py
from app.algorithms.voronoi import VoronoiCoverage, VoronoiACOCoverage
from app.algorithms.apf import PotentialFieldsCoverage
from app.algorithms.boustrophedon import VoronoiBoustrophedon

ALGORITHMS = {
    "voronoi": VoronoiCoverage(),
    "apf": PotentialFieldsCoverage(),
    "voronoi_aco": VoronoiACOCoverage(),
    "sweep": VoronoiBoustrophedon()
}

def get_algorithm(name: str):
    """Returns the requested algorithm, defaulting to Voronoi if not found."""
    return ALGORITHMS.get(name, ALGORITHMS["voronoi"])