"""
campus.py
---------
Defines the Smart Campus graph: locations, coordinates, and the road/path
network between them.  NetworkX is used to store the graph so that shortest-
path distances can be computed in later modules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import networkx as nx


# ---------------------------------------------------------------------------
# Location data
# ---------------------------------------------------------------------------

@dataclass
class CampusLocation:
    """Represents a physical location on campus."""
    id: str                        # Short unique key, e.g. "main_gate"
    name: str                      # Human-readable name
    x: float                       # X-coordinate (metres from origin)
    y: float                       # Y-coordinate (metres from origin)
    description: str = ""          # Optional description
    tags: List[str] = field(default_factory=list)  # e.g. ["medical", "residential"]

    # Derived helpers --------------------------------------------------------
    def coords(self) -> Tuple[float, float]:
        return (self.x, self.y)

    def euclidean_distance_to(self, other: "CampusLocation") -> float:
        """Straight-line distance in metres."""
        return math.hypot(self.x - other.x, self.y - other.y)

    def __repr__(self) -> str:
        return f"CampusLocation(id={self.id!r}, name={self.name!r}, coords=({self.x}, {self.y}))"


# ---------------------------------------------------------------------------
# Hard-coded campus map  (coordinates in metres; origin = Main Gate)
# The layout is loosely inspired by a realistic rectangular campus
# roughly 1 200 m × 800 m.
# ---------------------------------------------------------------------------

LOCATIONS: Dict[str, CampusLocation] = {
    "main_gate": CampusLocation(
        id="main_gate",
        name="Main Gate",
        x=0,
        y=400,
        description="Primary entrance and security checkpoint",
        tags=["entrance", "security"],
    ),
    "academic_block": CampusLocation(
        id="academic_block",
        name="Academic Block",
        x=400,
        y=600,
        description="Central teaching and research building",
        tags=["academic"],
    ),
    "library": CampusLocation(
        id="library",
        name="Library",
        x=600,
        y=700,
        description="Central campus library",
        tags=["academic"],
    ),
    "hostel_a": CampusLocation(
        id="hostel_a",
        name="Hostel A",
        x=900,
        y=700,
        description="Student residential block A (north side)",
        tags=["residential"],
    ),
    "hostel_b": CampusLocation(
        id="hostel_b",
        name="Hostel B",
        x=900,
        y=300,
        description="Student residential block B (south side)",
        tags=["residential"],
    ),
    "sports_complex": CampusLocation(
        id="sports_complex",
        name="Sports Complex",
        x=1100,
        y=500,
        description="Outdoor and indoor sports facilities",
        tags=["sports"],
    ),
    "cafeteria": CampusLocation(
        id="cafeteria",
        name="Cafeteria",
        x=500,
        y=400,
        description="Main student dining hall",
        tags=["dining"],
    ),
    "admin_block": CampusLocation(
        id="admin_block",
        name="Admin Block",
        x=200,
        y=250,
        description="Administration and faculty offices",
        tags=["administrative"],
    ),
}


# ---------------------------------------------------------------------------
# Campus road / path network
# ---------------------------------------------------------------------------
# Each edge carries a "distance" attribute (metres) and an optional "blocked"
# flag that the simulation layer may set to True to model route disruptions.

# Edges: (from_id, to_id, distance_in_metres)
# Distances are slightly longer than straight-line to model actual paths.
_EDGES: List[Tuple[str, str, float]] = [
    ("main_gate",      "admin_block",    250),
    ("main_gate",      "cafeteria",      530),
    ("admin_block",    "cafeteria",      310),
    ("admin_block",    "academic_block", 420),
    ("cafeteria",      "academic_block", 250),
    ("academic_block", "library",        230),
    ("library",        "hostel_a",       310),
    ("cafeteria",      "hostel_b",       430),
    ("hostel_a",       "hostel_b",       400),
    ("hostel_a",       "sports_complex", 230),
    ("hostel_b",       "sports_complex", 250),
    ("academic_block", "hostel_b",       480),
    ("library",        "sports_complex", 530),
    ("main_gate",      "academic_block", 720),  # direct road (longer route)
]

# Average campus emergency vehicle speed (km/h → m/s)
VEHICLE_SPEED_KMH: float = 20.0          # ~20 km/h on campus roads
VEHICLE_SPEED_MS: float = VEHICLE_SPEED_KMH * 1000 / 3600  # ≈ 5.56 m/s


def build_campus_graph(blocked_edges: Optional[List[Tuple[str, str]]] = None) -> nx.Graph:
    """
    Build and return the NetworkX undirected graph for the campus.

    Parameters
    ----------
    blocked_edges : list of (from_id, to_id), optional
        Pairs of location IDs whose connecting edge should be marked as blocked
        and given an effectively infinite weight so routing avoids them.

    Returns
    -------
    nx.Graph
        Campus graph with 'distance' and 'blocked' edge attributes, plus
        'location' node attributes pointing to CampusLocation objects.
    """
    G = nx.Graph()

    # Add nodes
    for loc_id, loc in LOCATIONS.items():
        G.add_node(loc_id, location=loc, pos=loc.coords())

    blocked_set: set = set()
    if blocked_edges:
        for a, b in blocked_edges:
            blocked_set.add((a, b))
            blocked_set.add((b, a))

    # Add edges
    for src, dst, dist in _EDGES:
        is_blocked = (src, dst) in blocked_set
        effective_dist = dist if not is_blocked else dist * 1e6  # near-infinite cost
        G.add_edge(
            src, dst,
            distance=dist,
            effective_distance=effective_dist,
            blocked=is_blocked,
        )

    return G


def get_travel_time_seconds(graph: nx.Graph, src_id: str, dst_id: str) -> float:
    """
    Shortest-path travel time (in seconds) between two campus locations
    using Dijkstra on 'effective_distance'.

    Returns math.inf if no path exists.
    """
    try:
        path_dist = nx.dijkstra_path_length(graph, src_id, dst_id, weight="effective_distance")
        return path_dist / VEHICLE_SPEED_MS
    except nx.NetworkXNoPath:
        return math.inf


def get_travel_time_minutes(graph: nx.Graph, src_id: str, dst_id: str) -> float:
    """Convenience wrapper – returns travel time in minutes."""
    return get_travel_time_seconds(graph, src_id, dst_id) / 60.0


def travel_time_matrix(graph: nx.Graph) -> Dict[Tuple[str, str], float]:
    """
    Compute the all-pairs travel-time matrix (minutes) for every campus
    location pair.  Returns a dict keyed by (src_id, dst_id).
    """
    loc_ids = list(LOCATIONS.keys())
    matrix: Dict[Tuple[str, str], float] = {}
    for src in loc_ids:
        for dst in loc_ids:
            if src == dst:
                matrix[(src, dst)] = 0.0
            else:
                matrix[(src, dst)] = get_travel_time_minutes(graph, src, dst)
    return matrix
