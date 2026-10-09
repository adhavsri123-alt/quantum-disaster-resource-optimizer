"""
emergencies.py
--------------
Runtime emergency management.  This module tracks the lifecycle of an
emergency from 'reported' through 'resources assigned' to 'resolved'.
It is intentionally decoupled from the optimisation layer so that both
the baseline and QUBO solvers can consume the same emergency state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from data.scenarios import Emergency, EMERGENCY_TYPES


# ---------------------------------------------------------------------------
# Emergency status enum
# ---------------------------------------------------------------------------

class EmergencyStatus(str, Enum):
    REPORTED  = "reported"    # Emergency confirmed, awaiting resources
    ACTIVE    = "active"      # Resources dispatched, not yet resolved
    RESOLVED  = "resolved"    # Emergency contained / handled
    ESCALATED = "escalated"   # Worsened due to delayed response


# ---------------------------------------------------------------------------
# Resource allocation snapshot for a single emergency
# ---------------------------------------------------------------------------

@dataclass
class AllocationRecord:
    """Records what resources were assigned to a specific emergency."""
    emergency_id: str
    ambulances_assigned: int = 0
    rescue_teams_assigned: int = 0
    medical_supplies_assigned: int = 0
    medical_personnel_assigned: int = 0
    dispatch_time_minutes: Optional[float] = None  # sim-clock at dispatch
    estimated_arrival_minutes: Optional[float] = None

    # Computed shortfalls
    @property
    def ambulances_unmet(self) -> int:
        return 0  # Filled after comparing with emergency requirement

    def coverage_vector(self) -> Dict[str, int]:
        return {
            "ambulances": self.ambulances_assigned,
            "rescue_teams": self.rescue_teams_assigned,
            "medical_supplies": self.medical_supplies_assigned,
            "medical_personnel": self.medical_personnel_assigned,
        }


# ---------------------------------------------------------------------------
# Emergency Manager
# ---------------------------------------------------------------------------

class EmergencyManager:
    """
    Maintains the current set of active emergencies, their statuses, and
    any allocations made by a solver.

    Usage
    -----
    >>> manager = EmergencyManager(emergencies)
    >>> manager.report(emergency)
    >>> manager.assign(emergency_id, allocation_record)
    >>> manager.resolve(emergency_id)
    """

    def __init__(self, emergencies: Optional[List[Emergency]] = None) -> None:
        self._emergencies: Dict[str, Emergency] = {}
        self._statuses: Dict[str, EmergencyStatus] = {}
        self._allocations: Dict[str, AllocationRecord] = {}

        if emergencies:
            for em in emergencies:
                self.report(em)

    # -----------------------------------------------------------------------
    # Lifecycle methods
    # -----------------------------------------------------------------------

    def report(self, emergency: Emergency) -> None:
        """Register a new emergency as REPORTED."""
        if emergency.id in self._emergencies:
            raise ValueError(f"Emergency '{emergency.id}' already registered.")
        self._emergencies[emergency.id] = emergency
        self._statuses[emergency.id] = EmergencyStatus.REPORTED

    def assign(self, emergency_id: str, allocation: AllocationRecord) -> None:
        """Record a resource allocation and mark the emergency as ACTIVE."""
        self._validate_id(emergency_id)
        self._allocations[emergency_id] = allocation
        self._statuses[emergency_id] = EmergencyStatus.ACTIVE

    def resolve(self, emergency_id: str) -> None:
        """Mark an emergency as RESOLVED."""
        self._validate_id(emergency_id)
        self._statuses[emergency_id] = EmergencyStatus.RESOLVED

    def escalate(self, emergency_id: str) -> None:
        """Mark an emergency as ESCALATED (response took too long)."""
        self._validate_id(emergency_id)
        self._statuses[emergency_id] = EmergencyStatus.ESCALATED

    # -----------------------------------------------------------------------
    # Query methods
    # -----------------------------------------------------------------------

    def get_emergency(self, emergency_id: str) -> Emergency:
        self._validate_id(emergency_id)
        return self._emergencies[emergency_id]

    def get_status(self, emergency_id: str) -> EmergencyStatus:
        self._validate_id(emergency_id)
        return self._statuses[emergency_id]

    def get_allocation(self, emergency_id: str) -> Optional[AllocationRecord]:
        return self._allocations.get(emergency_id)

    def all_emergencies(self) -> List[Emergency]:
        return list(self._emergencies.values())

    def active_emergencies(self) -> List[Emergency]:
        return [
            e for e in self._emergencies.values()
            if self._statuses[e.id] in (EmergencyStatus.REPORTED, EmergencyStatus.ACTIVE)
        ]

    def unresolved_emergencies(self) -> List[Emergency]:
        return [
            e for e in self._emergencies.values()
            if self._statuses[e.id] != EmergencyStatus.RESOLVED
        ]

    def sorted_by_priority(self) -> List[Emergency]:
        """Return active emergencies sorted descending by priority_score."""
        return sorted(
            self.active_emergencies(),
            key=lambda e: e.priority_score,
            reverse=True,
        )

    # -----------------------------------------------------------------------
    # Shortfall analysis
    # -----------------------------------------------------------------------

    def compute_unmet_demand(self) -> Dict[str, Dict[str, int]]:
        """
        For every active emergency, compute per-resource shortfall
        (required − assigned).  Returns a nested dict keyed by emergency ID.
        """
        unmet: Dict[str, Dict[str, int]] = {}
        for em in self.active_emergencies():
            alloc = self._allocations.get(em.id)
            if alloc is None:
                # Nothing assigned yet
                unmet[em.id] = em.resource_summary()
            else:
                unmet[em.id] = {
                    "ambulances": max(0, em.ambulances_required - alloc.ambulances_assigned),
                    "rescue_teams": max(0, em.rescue_teams_required - alloc.rescue_teams_assigned),
                    "medical_supplies": max(0, em.medical_supplies_required - alloc.medical_supplies_assigned),
                    "medical_personnel": max(0, em.medical_personnel_required - alloc.medical_personnel_assigned),
                }
        return unmet

    def summary(self) -> Dict[str, int]:
        """High-level counts by status."""
        counts = {s.value: 0 for s in EmergencyStatus}
        for status in self._statuses.values():
            counts[status.value] += 1
        return counts

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _validate_id(self, emergency_id: str) -> None:
        if emergency_id not in self._emergencies:
            raise KeyError(f"Unknown emergency ID: '{emergency_id}'")

    def __repr__(self) -> str:
        return (
            f"EmergencyManager("
            f"total={len(self._emergencies)}, "
            f"active={len(self.active_emergencies())}, "
            f"resolved={self.summary().get('resolved', 0)})"
        )
