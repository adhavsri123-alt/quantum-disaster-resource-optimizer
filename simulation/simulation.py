"""
simulation.py
-------------
Top-level simulation runner.  Wires together the campus graph,
scenario emergencies, and resource pool into a SimulationState object
that the optimisation layer and Streamlit UI can query.

The SimulationState does NOT run any solver — it simply provides the
complete, self-consistent environment the solver needs:
  - Campus graph (with optional blocked routes)
  - Active emergencies (sorted by priority)
  - Resource manager (with availability tracking)
  - Travel-time matrix between all locations

Usage
-----
    from simulation.simulation import SimulationState
    from data.scenarios import get_scenario, DEFAULT_RESOURCES

    scenario = get_scenario("alpha")
    state = SimulationState(scenario, DEFAULT_RESOURCES)
    state.summary()
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from data.campus import (
    LOCATIONS,
    build_campus_graph,
    get_travel_time_minutes,
    travel_time_matrix,
)
from data.scenarios import Emergency, ResourcePool, Scenario, DEFAULT_RESOURCES
from simulation.emergencies import EmergencyManager, AllocationRecord, EmergencyStatus
from simulation.resources import ResourceManager, RESOURCE_TYPES


# ---------------------------------------------------------------------------
# Simulation State
# ---------------------------------------------------------------------------

class SimulationState:
    """
    Encapsulates a single simulation run derived from a Scenario.

    Attributes
    ----------
    scenario : Scenario
        The source scenario (name, emergencies, blocked routes, seed).
    graph : nx.Graph
        Campus road network with blocked routes applied.
    emergency_manager : EmergencyManager
        Lifecycle tracker for all emergencies.
    resource_manager : ResourceManager
        Inventory tracker for all resources.
    travel_times : Dict[(str, str), float]
        All-pairs travel time matrix in minutes.
    """

    def __init__(
        self,
        scenario: Scenario,
        resource_pool: Optional[ResourcePool] = None,
    ) -> None:
        self.scenario = scenario
        self._resource_pool = resource_pool or DEFAULT_RESOURCES

        # Build the campus graph (respects blocked routes)
        self.graph = build_campus_graph(blocked_edges=scenario.blocked_routes)

        # Initialise managers
        self.emergency_manager = EmergencyManager(scenario.emergencies)
        self.resource_manager = ResourceManager(self._resource_pool)

        # Pre-compute travel times
        self.travel_times: Dict[Tuple[str, str], float] = travel_time_matrix(self.graph)

    # -----------------------------------------------------------------------
    # Convenience accessors
    # -----------------------------------------------------------------------

    @property
    def emergencies(self) -> List[Emergency]:
        return self.emergency_manager.all_emergencies()

    @property
    def active_emergencies(self) -> List[Emergency]:
        return self.emergency_manager.sorted_by_priority()

    @property
    def location_ids(self) -> List[str]:
        return list(LOCATIONS.keys())

    def travel_time(self, src: str, dst: str) -> float:
        """Travel time in minutes between two location IDs."""
        return self.travel_times.get((src, dst), math.inf)

    # -----------------------------------------------------------------------
    # State query helpers used by solvers
    # -----------------------------------------------------------------------

    def resource_vector(self) -> Dict[str, int]:
        """Available resource counts at this point in time."""
        return self.resource_manager.available()

    def demand_matrix(self) -> np.ndarray:
        """
        Returns an (E × R) numpy array where:
          E = number of active emergencies (sorted by priority)
          R = 4 resource types  [ambulances, rescue_teams, medical_supplies, medical_personnel]

        Each cell is the *required* amount of that resource for that emergency.
        """
        active = self.active_emergencies
        E = len(active)
        R = len(RESOURCE_TYPES)  # 4
        matrix = np.zeros((E, R), dtype=int)
        for i, em in enumerate(active):
            matrix[i, 0] = em.ambulances_required
            matrix[i, 1] = em.rescue_teams_required
            matrix[i, 2] = em.medical_supplies_required
            matrix[i, 3] = em.medical_personnel_required
        return matrix

    def travel_time_vector(self, depot_id: str = "main_gate") -> np.ndarray:
        """
        Travel times (minutes) from `depot_id` to each active emergency
        location, in priority-sorted order.
        """
        active = self.active_emergencies
        return np.array(
            [self.travel_time(depot_id, em.location_id) for em in active],
            dtype=float,
        )

    def severity_vector(self) -> np.ndarray:
        """Severity scores for active emergencies, priority-sorted."""
        return np.array(
            [em.severity for em in self.active_emergencies], dtype=float
        )

    def people_affected_vector(self) -> np.ndarray:
        """People-affected counts for active emergencies, priority-sorted."""
        return np.array(
            [em.people_affected for em in self.active_emergencies], dtype=float
        )

    # -----------------------------------------------------------------------
    # Summary / display
    # -----------------------------------------------------------------------

    def summary(self) -> None:
        """Print a human-readable state summary to stdout."""
        _print_header(f"Simulation — Scenario {self.scenario.name}")

        # --- Scenario description ---
        print(f"  Description : {self.scenario.description}")
        print(f"  Seed        : {self.scenario.seed}")
        if self.scenario.blocked_routes:
            blocked_str = ", ".join(f"{a}↔{b}" for a, b in self.scenario.blocked_routes)
            print(f"  Blocked     : {blocked_str}")
        print()

        # --- Campus locations ---
        _print_header("Campus Locations")
        for loc_id, loc in LOCATIONS.items():
            print(f"  [{loc_id:20s}]  {loc.name:22s}  coords=({loc.x:5.0f}, {loc.y:5.0f})")
        print()

        # --- Active emergencies ---
        _print_header("Active Emergencies")
        for em in self.active_emergencies:
            print(f"  [{em.id}] {em.type_label:35s} @ {em.location_name}")
            print(f"          severity={em.severity}/10  people={em.people_affected}"
                  f"  priority={em.priority_score:.2f}")
            print(f"          requires: ambulances={em.ambulances_required}, "
                  f"rescue_teams={em.rescue_teams_required}, "
                  f"supplies={em.medical_supplies_required}, "
                  f"personnel={em.medical_personnel_required}")
            print()

        # --- Available resources ---
        _print_header("Available Resources")
        for row in self.resource_manager.status_table():
            print(f"  {row['Resource']:30s}  {row['Available']:3d} / {row['Capacity']:3d} "
                  f"({row['Utilisation (%)']:5.1f}% in use)  [{row['Unit']}]")
        print()

        # --- Travel times (from Main Gate to each emergency) ---
        _print_header("Travel Times from Main Gate to Emergency Locations")
        depot = "main_gate"
        for em in self.active_emergencies:
            tt = self.travel_time(depot, em.location_id)
            if tt == math.inf:
                tt_str = "UNREACHABLE (route blocked)"
            else:
                tt_str = f"{tt:.2f} min"
            print(f"  Main Gate → {em.location_name:22s}: {tt_str}")
        print()

        # --- Full travel time matrix (relevant pairs) ---
        _print_header("All-pairs Travel Time Matrix (minutes)")
        loc_ids = self.location_ids
        loc_names = [LOCATIONS[lid].name[:12] for lid in loc_ids]

        # Header row
        header = f"{'':20s}" + "".join(f"{n:>14s}" for n in loc_names)
        print("  " + header)
        print("  " + "-" * len(header))

        for src in loc_ids:
            src_name = LOCATIONS[src].name[:18]
            row_str = f"{src_name:20s}"
            for dst in loc_ids:
                tt = self.travel_times[(src, dst)]
                if tt == math.inf:
                    cell = "   ∞"
                elif tt == 0.0:
                    cell = "  0.0"
                else:
                    cell = f"{tt:5.1f}"
                row_str += f"{cell:>14s}"
            print("  " + row_str)
        print()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _print_header(title: str, width: int = 72) -> None:
    bar = "─" * width
    print(f"\n  {'─'*3} {title} {'─'*(width - len(title) - 5)}")


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

def create_simulation(
    scenario_name: str = "alpha",
    seed: int = 42,
    resource_pool: Optional[ResourcePool] = None,
) -> SimulationState:
    """
    Convenience factory: load a named scenario and return a SimulationState.

    Parameters
    ----------
    scenario_name : str
        One of 'alpha', 'beta', 'gamma'.
    seed : int
        Random seed for reproducibility.
    resource_pool : ResourcePool, optional
        Defaults to DEFAULT_RESOURCES (5 amb, 3 teams, 100 supplies, 25 personnel).
    """
    from data.scenarios import get_scenario
    scenario = get_scenario(scenario_name, seed=seed)
    return SimulationState(scenario, resource_pool or DEFAULT_RESOURCES)
