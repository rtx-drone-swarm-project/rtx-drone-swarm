# app/algorithms/__init__.py
from app.algorithms.voronoi import VoronoiCoverage
# from .lawnmower import LawnmowerSearch

ALGORITHMS = {
    "voronoi": VoronoiCoverage(),
    #aco,
    #etc.
}

def get_algorithm(name: str):
    """Returns the requested algorithm, defaulting to Voronoi if not found."""
    return ALGORITHMS.get(name, ALGORITHMS["voronoi"])