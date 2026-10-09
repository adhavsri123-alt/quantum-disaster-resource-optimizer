"""
distance.py
-----------
Utility functions for distance and travel-time calculations on the campus
network.  Builds on top of campus.py and NetworkX but adds higher-level
helpers that the optimisation and UI layers need.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import networkx as nx

from data.campus import (
    LOCATIONS,
    CampusLocation,
    build_campus_graph,
    get_travel_time_minutes,
    VEHICLE_SPEED_KMH,
    VEHICLE_SPEED_MS,
)


# ---------------------------------------------------------------------------
# Euclidean (straight-line) utilities
# ---------------------------------------------------------------------------

def euclidean_distance(loc_a: CampusLocation, loc_b: CampusLocation) -> float:
    """Straight-line distance in metres between two campus locations."""
    return loc_a.euclidean_distance_to(loc_b)


def euclidean_travel_time_minutes(loc_a: CampusLocation, loc_b: CampusLocation) -> float:
    """
    Approximate travel time (minutes) via straight-line distance.
    Useful as a fast lower-bound estimate when no path exists.
    """
    dist_m = euclidean_distance(loc_a, loc_b)
    return dist_m / VEHICLE_SPEED_MS / 60.0


# ---------------------------------------------------------------------------
# Network-based travel time helpers
# ---------------------------------------------------------------------------

def shortest_path(
    graph: nx.Graph,
    src_id: str,
    dst_id: str,
) -> Optional[List[str]]:
    """
    Return the list of location IDs on the shortest path from src to dst,
    or None if no path exists.
    """
    try:
        return nx.dijkstra_path(graph, src_id, dst_id, weight="effective_distance")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def path_distance_metres(graph: nx.Graph, path: List[str]) -> float:
    """Total road distance (metres) along a given path (list of location IDs)."""
    total = 0.0
    for i in range(len(path) - 1):
        edge_data = graph.get_edge_data(path[i], path[i + 1])
        if edge_data is None:
            return math.inf
        total += edge_data.get("effective_distance", math.inf)
    return total


def travel_time_with_path(
    graph: nx.Graph,
    src_id: str,
    dst_id: str,
) -> Tuple[float, Optional[List[str]]]:
    """
    Returns (travel_time_minutes, path_list).
    path_list is None if no route exists.
    travel_time_minutes is math.inf if unreachable.
    """
    path = shortest_path(graph, src_id, dst_id)
    if path is None:
        return math.inf, None
    dist = path_distance_metres(graph, path)
    tt_min = dist / VEHICLE_SPEED_MS / 60.0
    return tt_min, path


# ---------------------------------------------------------------------------
# Distance / travel-time matrices
# ---------------------------------------------------------------------------

def build_distance_matrix(
    graph: nx.Graph,
    location_ids: Optional[List[str]] = None,
    in_minutes: bool = True,
) -> Tuple[np.ndarray, List[str]]:
    """
    Build a square (N × N) numpy matrix of travel times or distances.

    Parameters
    ----------
    graph : nx.Graph
        Campus road network.
    location_ids : list of str, optional
        Ordered list of location IDs; defaults to all campus locations.
    in_minutes : bool
        If True, values are in minutes; if False, values are in metres.

    Returns
    -------
    matrix : np.ndarray  shape (N, N)
    ordered_ids : list of str
        The location IDs corresponding to matrix rows/columns.
    """
    ids = location_ids or list(LOCATIONS.keys())
    N = len(ids)
    matrix = np.full((N, N), math.inf)

    for i, src in enumerate(ids):
        for j, dst in enumerate(ids):
            if src == dst:
                matrix[i, j] = 0.0
                continue
            try:
                dist = nx.dijkstra_path_length(graph, src, dst, weight="effective_distance")
                if in_minutes:
                    matrix[i, j] = dist / VEHICLE_SPEED_MS / 60.0
                else:
                    matrix[i, j] = dist
            except nx.NetworkXNoPath:
                matrix[i, j] = math.inf

    return matrix, ids


def nearest_location(
    graph: nx.Graph,
    source_id: str,
    candidates: List[str],
) -> Tuple[Optional[str], float]:
    """
    Find the nearest reachable location from `source_id` among `candidates`.

    Returns
    -------
    (nearest_id, travel_time_minutes) or (None, inf) if none reachable.
    """
    best_id: Optional[str] = None
    best_time: float = math.inf

    for cand in candidates:
        if cand == source_id:
            return cand, 0.0
        tt = get_travel_time_minutes(graph, source_id, cand)
        if tt < best_time:
            best_time = tt
            best_id = cand

    return best_id, best_time


# ---------------------------------------------------------------------------
# Human-readable formatting
# ---------------------------------------------------------------------------

def format_travel_time(minutes: float) -> str:
    """
    Format a travel time in minutes as a human-readable string.
    Returns '∞' for math.inf values.
    """
    if minutes == math.inf or math.isnan(minutes):
        return "∞ (unreachable)"
    total_seconds = int(minutes * 60)
    mins = total_seconds // 60
    secs = total_seconds % 60
    if mins == 0:
        return f"{secs}s"
    return f"{mins}m {secs:02d}s"
