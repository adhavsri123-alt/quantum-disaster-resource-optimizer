"""
dynamic.py
----------
Dynamic simulation layer for the Quantum Disaster Resource Optimizer (QDO).

Provides an orchestration and event management layer on top of SimulationState,
enabling dynamic environment changes during runtime:
  - Dynamic emergency reporting / arrival
  - Resource pool fluctuations (availability & capacity changes)
  - Campus road/route blockages and reopening via NetworkX
  - Emergency resolution and resource release
  - Dynamic state snapshotting and event logging
  - Re-optimization triggering via existing solvers (Greedy & QUBO)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from data.campus import LOCATIONS, travel_time_matrix
from data.scenarios import Emergency, ResourcePool
from simulation.emergencies import EmergencyStatus, AllocationRecord
from simulation.resources import RESOURCE_TYPES, ResourceManager
from simulation.simulation import SimulationState, create_simulation
from optimization.solver import SolverRegistry, AllocationPlan
from optimization.baseline import GreedyBaselineSolver
from optimization.qubo import QUBOSolver


# ---------------------------------------------------------------------------
# Dynamic Event Types & Event Data Structure
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    EMERGENCY_REPORTED = "emergency_reported"
    EMERGENCY_ACTIVATED = "emergency_activated"
    NEW_EMERGENCY_ADDED = "new_emergency_added"
    RESOURCE_DEPLOYED = "resource_deployed"
    RESOURCE_AVAILABILITY_CHANGED = "resource_availability_changed"
    ROAD_BLOCKED = "road_blocked"
    ROAD_REOPENED = "road_reopened"
    EMERGENCY_RESOLVED = "emergency_resolved"
    RESOURCES_RELEASED = "resources_released"
    OPTIMIZATION_TRIGGERED = "optimization_triggered"


@dataclass
class DynamicEvent:
    """Represents a single dynamic event in the simulation timeline."""
    timestamp: float                       # Simulation clock time in minutes
    event_type: EventType
    description: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": round(self.timestamp, 2),
            "event_type": self.event_type.value,
            "description": self.description,
            "details": self.details,
        }

    def __repr__(self) -> str:
        return f"[EVENT T={self.timestamp:.1f}m] [{self.event_type.value.upper()}] {self.description}"


# ---------------------------------------------------------------------------
# Dynamic State Snapshot Structure
# ---------------------------------------------------------------------------

@dataclass
class DynamicStateSnapshot:
    """Encapsulates a readable snapshot of the simulation at a given moment."""
    timestamp: float
    active_emergencies: List[Dict[str, Any]]
    resolved_emergencies: List[str]
    available_resources: Dict[str, int]
    resource_capacity: Dict[str, int]
    blocked_roads: List[Tuple[str, str]]
    latest_allocations: Optional[Dict[str, Dict[str, int]]]
    latest_metrics: Optional[Dict[str, Any]]
    latest_solver: Optional[str]
    event_history_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": round(self.timestamp, 2),
            "active_emergencies": self.active_emergencies,
            "resolved_emergencies": self.resolved_emergencies,
            "available_resources": self.available_resources,
            "resource_capacity": self.resource_capacity,
            "blocked_roads": self.blocked_roads,
            "latest_allocations": self.latest_allocations,
            "latest_metrics": self.latest_metrics,
            "latest_solver": self.latest_solver,
            "event_history_count": self.event_history_count,
        }


# ---------------------------------------------------------------------------
# Dynamic Simulation Class
# ---------------------------------------------------------------------------

class DynamicSimulation:
    """
    Orchestration layer around SimulationState.

    Allows the emergency environment to change dynamically after initial setup:
      - Add new emergencies
      - Block or reopen roads on the NetworkX graph
      - Modify resource pool capacities or availability
      - Resolve emergencies and release allocated resources
      - Re-run Greedy or QUBO solvers to generate updated plans & metrics
      - Maintain event history and output state snapshots
    """

    def __init__(
        self,
        simulation_state: Optional[SimulationState] = None,
        scenario_name: str = "alpha",
        seed: int = 42,
        resource_pool: Optional[ResourcePool] = None,
        verbose: bool = True,
    ) -> None:
        if simulation_state is not None:
            self.state = simulation_state
        else:
            self.state = create_simulation(scenario_name=scenario_name, seed=seed, resource_pool=resource_pool)

        self.current_time: float = 0.0
        self.events: List[DynamicEvent] = []
        self.latest_plan: Optional[AllocationPlan] = None
        self.verbose = verbose

        # Record initial emergencies as reported events
        for em in self.state.emergencies:
            self._log_event(
                EventType.EMERGENCY_REPORTED,
                f"Emergency {em.id} ({em.type_label}) reported at {em.location_name}",
                {"emergency_id": em.id, "location_id": em.location_id, "severity": em.severity},
            )

        # Record initial blocked routes if present in scenario
        if self.state.scenario.blocked_routes:
            for u, v in self.state.scenario.blocked_routes:
                self._log_event(
                    EventType.ROAD_BLOCKED,
                    f"Road blocked: {u} <-> {v}",
                    {"u": u, "v": v},
                )

    def advance_time(self, minutes: float) -> None:
        """Advance simulation clock by `minutes`."""
        if minutes < 0:
            raise ValueError("Time step cannot be negative.")
        self.current_time += minutes

    def add_emergency(
        self,
        emergency: Emergency,
        trigger_time: Optional[float] = None,
    ) -> None:
        """
        Add a new emergency while the simulation is running.
        """
        if trigger_time is not None:
            self.current_time = trigger_time
        emergency.reported_at_minute = self.current_time

        # Ensure unique ID
        existing_ids = [e.id for e in self.state.emergency_manager.all_emergencies()]
        if emergency.id in existing_ids:
            raise ValueError(f"Emergency ID '{emergency.id}' already exists in simulation.")

        # Ensure valid location ID
        if emergency.location_id not in LOCATIONS:
            raise KeyError(f"Unknown location ID '{emergency.location_id}'.")

        # Register in emergency manager
        self.state.emergency_manager.report(emergency)

        self._log_event(
            EventType.NEW_EMERGENCY_ADDED,
            f"New emergency reported: {emergency.id} at {emergency.location_name}",
            {
                "emergency_id": emergency.id,
                "location_id": emergency.location_id,
                "type": emergency.emergency_type,
                "severity": emergency.severity,
                "people_affected": emergency.people_affected,
                "requirements": emergency.resource_summary(),
            },
        )

    def block_road(
        self,
        u: str,
        v: str,
        trigger_time: Optional[float] = None,
    ) -> None:
        """
        Block a road/edge on the campus graph.
        """
        if trigger_time is not None:
            self.current_time = trigger_time

        if not self.state.graph.has_edge(u, v):
            raise KeyError(f"No road edge exists between '{u}' and '{v}'.")

        edge_data = self.state.graph[u][v]
        edge_data["blocked"] = True
        edge_data["effective_distance"] = edge_data["distance"] * 1e6

        # Recalculate all-pairs travel-time matrix
        self.state.travel_times = travel_time_matrix(self.state.graph)

        self._log_event(
            EventType.ROAD_BLOCKED,
            f"Road blocked: {u} <-> {v}",
            {"u": u, "v": v},
        )

    def reopen_road(
        self,
        u: str,
        v: str,
        trigger_time: Optional[float] = None,
    ) -> None:
        """
        Reopen a previously blocked road/edge on the campus graph.
        """
        if trigger_time is not None:
            self.current_time = trigger_time

        if not self.state.graph.has_edge(u, v):
            raise KeyError(f"No road edge exists between '{u}' and '{v}'.")

        edge_data = self.state.graph[u][v]
        edge_data["blocked"] = False
        edge_data["effective_distance"] = edge_data["distance"]

        # Recalculate all-pairs travel-time matrix
        self.state.travel_times = travel_time_matrix(self.state.graph)

        self._log_event(
            EventType.ROAD_REOPENED,
            f"Road reopened: {u} <-> {v}",
            {"u": u, "v": v},
        )

    def get_blocked_roads(self) -> List[Tuple[str, str]]:
        """Return a list of currently blocked edges (u, v)."""
        blocked = []
        for u, v, data in self.state.graph.edges(data=True):
            if data.get("blocked", False):
                blocked.append((u, v))
        return blocked

    def modify_resource_availability(
        self,
        resource_type: str,
        delta: int,
        trigger_time: Optional[float] = None,
        update_capacity: bool = True,
    ) -> None:
        """
        Modify available units and capacity for a resource type.
        delta < 0: decrease availability (e.g. ambulance unavailable)
        delta > 0: increase availability (e.g. ambulance available again)
        """
        if trigger_time is not None:
            self.current_time = trigger_time

        if resource_type not in RESOURCE_TYPES:
            raise KeyError(f"Unknown resource type '{resource_type}'. Must be one of {RESOURCE_TYPES}.")

        mgr = self.state.resource_manager
        curr_avail = mgr.available()[resource_type]
        curr_cap = mgr.capacity()[resource_type]

        new_avail = curr_avail + delta
        if new_avail < 0:
            raise ValueError(
                f"Cannot reduce '{resource_type}' by {abs(delta)}: current available is {curr_avail}."
            )

        if update_capacity:
            new_cap = curr_cap + delta
            if new_cap < 0:
                raise ValueError(f"Cannot reduce capacity of '{resource_type}' below zero.")
            mgr._capacity[resource_type] = new_cap
            mgr._available[resource_type] = new_avail
        else:
            if new_avail > curr_cap:
                raise ValueError(
                    f"Available '{resource_type}' ({new_avail}) cannot exceed total capacity ({curr_cap})."
                )
            mgr._available[resource_type] = new_avail

        change_str = f"+{delta}" if delta > 0 else f"{delta}"
        self._log_event(
            EventType.RESOURCE_AVAILABILITY_CHANGED,
            f"Resource changed: {resource_type} {change_str} (now {mgr.available()[resource_type]}/{mgr.capacity()[resource_type]})",
            {
                "resource_type": resource_type,
                "delta": delta,
                "new_available": mgr.available()[resource_type],
                "new_capacity": mgr.capacity()[resource_type],
            },
        )

    def resolve_emergency(
        self,
        emergency_id: str,
        trigger_time: Optional[float] = None,
    ) -> None:
        """
        Resolve an active emergency and release its reserved resources.
        """
        if trigger_time is not None:
            self.current_time = trigger_time

        # Update emergency status
        self.state.emergency_manager.resolve(emergency_id)

        # Release reserved resources for this emergency
        released = self.state.resource_manager.release(emergency_id)

        self._log_event(
            EventType.EMERGENCY_RESOLVED,
            f"Emergency {emergency_id} resolved",
            {"emergency_id": emergency_id},
        )

        if released:
            self._log_event(
                EventType.RESOURCES_RELEASED,
                f"Resources released for emergency {emergency_id}",
                {"emergency_id": emergency_id},
            )

    def optimize(
        self,
        solver_name: str = "Greedy Baseline",
        commit_allocations: bool = True,
        solver_kwargs: Optional[Dict[str, Any]] = None,
    ) -> AllocationPlan:
        """
        Re-run optimization on current SimulationState using specified solver.
        """
        if "QUBO" in solver_name and solver_kwargs:
            solver = QUBOSolver(**solver_kwargs)
        elif "Greedy" in solver_name:
            solver = GreedyBaselineSolver()
        else:
            solver = SolverRegistry.get(solver_name)

        if solver is None:
            raise ValueError(f"Solver '{solver_name}' not found in registry.")

        # Release any active emergency reservations prior to re-optimization
        # so the solver can optimize across all active emergencies
        active_ids = [e.id for e in self.state.active_emergencies]
        for eid in active_ids:
            self.state.resource_manager.release(eid)

        # Solve for active emergencies
        plan = solver.solve(self.state)

        # If committing allocations, update emergency manager and reserve in resource manager
        if commit_allocations:
            for em_id, record in plan.allocations.items():
                if em_id in active_ids:
                    self.state.emergency_manager.assign(em_id, record)
                    # Reserve allocated resources
                    self.state.resource_manager.reserve(
                        emergency_id=em_id,
                        ambulances=record.ambulances_assigned,
                        rescue_teams=record.rescue_teams_assigned,
                        medical_supplies=record.medical_supplies_assigned,
                        medical_personnel=record.medical_personnel_assigned,
                        sim_time=self.current_time,
                    )
            self._log_event(
                EventType.RESOURCE_DEPLOYED,
                f"Allocation updated by {solver_name}",
                {"solver": solver_name, "allocations_count": len(plan.allocations)},
            )

        self.latest_plan = plan

        self._log_event(
            EventType.OPTIMIZATION_TRIGGERED,
            f"Re-optimization triggered: {solver_name}",
            {
                "solver": solver_name,
                "objective": plan.metrics.get("weighted_objective"),
                "solve_time_ms": plan.solver_metadata.get("solve_time_ms"),
            },
        )

        return plan

    def get_snapshot(self) -> DynamicStateSnapshot:
        """
        Provide a clean snapshot of current simulation state.
        """
        active_ems = [
            {
                "id": e.id,
                "location_id": e.location_id,
                "location_name": e.location_name,
                "type": e.emergency_type,
                "severity": e.severity,
                "people_affected": e.people_affected,
                "priority_score": e.priority_score,
                "status": self.state.emergency_manager.get_status(e.id).value,
                "requirements": e.resource_summary(),
            }
            for e in self.state.active_emergencies
        ]

        resolved_ids = [
            e.id for e in self.state.emergency_manager.all_emergencies()
            if self.state.emergency_manager.get_status(e.id) == EmergencyStatus.RESOLVED
        ]

        latest_allocs = None
        latest_mets = None
        latest_solv = None

        if self.latest_plan:
            latest_solv = self.latest_plan.solver_name
            latest_mets = self.latest_plan.metrics
            latest_allocs = {
                eid: rec.coverage_vector() for eid, rec in self.latest_plan.allocations.items()
            }

        return DynamicStateSnapshot(
            timestamp=self.current_time,
            active_emergencies=active_ems,
            resolved_emergencies=resolved_ids,
            available_resources=self.state.resource_manager.available(),
            resource_capacity=self.state.resource_manager.capacity(),
            blocked_roads=self.get_blocked_roads(),
            latest_allocations=latest_allocs,
            latest_metrics=latest_mets,
            latest_solver=latest_solv,
            event_history_count=len(self.events),
        )

    def get_event_history(self) -> List[Dict[str, Any]]:
        """Return complete list of event dicts."""
        return [e.to_dict() for e in self.events]

    def _log_event(self, event_type: EventType, description: str, details: Dict[str, Any]) -> None:
        event = DynamicEvent(
            timestamp=self.current_time,
            event_type=event_type,
            description=description,
            details=details,
        )
        self.events.append(event)
        if self.verbose:
            print(f"[EVENT] {description}")
