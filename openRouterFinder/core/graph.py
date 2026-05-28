"""Graph data structures and geographic utilities."""

import math
from dataclasses import dataclass, field
from typing import List, Tuple

PI = 3.1415926535898
EARTH_RADIUS = 6378.137


def rad(x: float) -> float:
    return x * PI / 180.0


def great_circle_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two points in kilometers."""
    rlat1 = rad(lat1)
    rlat2 = rad(lat2)
    a = rlat1 - rlat2
    b = rad(lon1) - rad(lon2)
    s = 2 * math.asin(
        math.sqrt(
            math.pow(math.sin(a / 2), 2)
            + math.cos(rlat1) * math.cos(rlat2) * math.pow(math.sin(b / 2), 2)
        )
    )
    return s * EARTH_RADIUS


def _haversine_a(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the haversine 'a' value (sin²(Δlat/2) + cos(lat1)*cos(lat2)*sin²(Δlon/2)).

    This is proportional to the great-circle distance (via monotonic asin(sqrt(a))),
    but avoids the expensive asin and sqrt calls. Use for comparison-only scenarios.
    """
    rlat1 = rad(lat1)
    rlat2 = rad(lat2)
    dlat = rlat1 - rlat2
    dlon = rad(lon1) - rad(lon2)
    return (
        math.sin(dlat / 2) ** 2
        + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    )


def heuristic_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """A* heuristic: straight-line distance."""
    return great_circle_distance_km(lat1, lon1, lat2, lon2)


@dataclass(slots=True)
class Edge:
    """Directed edge between two nodes."""
    nfrom: int  # source node IID
    nend: int   # target node IID
    name: str   # airway name
    color: Tuple[int, int, int] = (0, 0, 0)


@dataclass(slots=True)
class Node:
    """Navigation node (waypoint or airport)."""
    iid: int
    name: str
    px: float   # latitude
    py: float   # longitude
    next_list: List[Edge] = field(default_factory=list)

    def node_key(self) -> Tuple[str, float, float]:
        """Unique key for node lookup."""
        return (self.name, round(self.px, 6), round(self.py, 6))


@dataclass(slots=True)
class SearchingNode:
    """Mutable state during A* search."""
    iid: int
    name: str
    route: str = ""
    dist: float = 0.0
    route_list: List[Tuple[str, str, int]] = field(default_factory=list)
    # (edge_name, node_name, node_iid)
