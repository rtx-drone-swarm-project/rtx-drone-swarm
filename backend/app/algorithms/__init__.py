# app/algorithms/__init__.py
from app.algorithms.voronoi import VoronoiCoverage
from app.algorithms.apf import PotentialFieldsCoverage
# from .lawnmower import LawnmowerSearch

ALGORITHMS = {
    "voronoi": VoronoiCoverage(), #Temporary to test apf file, didnt want to mess with front end yet
    "apf": PotentialFieldsCoverage(),
    #aco,
    #etc.
}

def get_algorithm(name: str):
    """Returns the requested algorithm, defaulting to Voronoi if not found."""
    return ALGORITHMS.get(name, ALGORITHMS["voronoi"])