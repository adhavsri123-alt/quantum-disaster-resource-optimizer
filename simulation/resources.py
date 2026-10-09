"""
resources.py
------------
Resource inventory management.  Tracks availability, reservations, and
release of emergency resources during a simulation run.

Resources are tracked at two levels:
  1. Total capacity (fixed at startup from ResourcePool)
  2. Available units (depletes on allocation, restores on release)

This module does NOT make allocation decisions — that is the solver's job.
It simply enforces resource constraints and records usage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from data.scenarios import ResourcePool


# ---------------------------------------------------------------------------
# Resource types (string constants used as dict keys)
# ---------------------------------------------------------------------------

RESOURCE_TYPES: List[str] = [
    "ambulances",
    "rescue_teams",
    "medical_supplies",
    "medical_personnel",
]

RESOURCE_LABELS: Dict[str, str] = {
    "ambulances":         "Ambulances",
    "rescue_teams":       "Rescue Teams",
    "medical_supplies":   "Medical Supplies (units)",
    "medical_personnel":  "Medical Personnel",
}

RESOURCE_UNITS: Dict[str, str] = {
    "ambulances":         "vehicles",
    "rescue_teams":       "teams",
    "medical_supplies":   "units",
    "medical_personnel":  "staff",
}


# ---------------------------------------------------------------------------
# Reservation record
# ---------------------------------------------------------------------------

@dataclass
class Reservation:
    """Tracks a single resource reservation tied to an emergency."""
    emergency_id: str
    ambulances: int = 0
    rescue_teams: int = 0
    medical_supplies: int = 0
    medical_personnel: int = 0
    created_at_minute: float = 0.0
    released: bool = False

    def as_dict(self) -> Dict[str, int]:
        return {
            "ambulances": self.ambulances,
            "rescue_teams": self.rescue_teams,
            "medical_supplies": self.medical_supplies,
            "medical_personnel": self.medical_personnel,
        }

    def total_units(self) -> int:
        return (
            self.ambulances + self.rescue_teams
            + self.medical_supplies + self.medical_personnel
        )


# ---------------------------------------------------------------------------
# Resource Manager
# ---------------------------------------------------------------------------

class ResourceManager:
    """
    Manages the campus emergency resource pool.

    Enforces hard capacity constraints: you cannot reserve more of any
    resource than is currently available.  Provides methods for reserving,
    releasing, and querying resources.

    Parameters
    ----------
    pool : ResourcePool
        Initial resource capacities.
    """

    def __init__(self, pool: ResourcePool) -> None:
        self._capacity: Dict[str, int] = dict(pool.as_dict())
        self._available: Dict[str, int] = dict(pool.as_dict())
        self._reservations: Dict[str, Reservation] = {}  # keyed by emergency_id

    # -----------------------------------------------------------------------
    # Reservation operations
    # -----------------------------------------------------------------------

    def reserve(
        self,
        emergency_id: str,
        ambulances: int = 0,
        rescue_teams: int = 0,
        medical_supplies: int = 0,
        medical_personnel: int = 0,
        sim_time: float = 0.0,
    ) -> Tuple[bool, Optional[str]]:
        """
        Attempt to reserve resources for an emergency.

        Returns
        -------
        (success: bool, error_message: Optional[str])
            success=True means the reservation was recorded and availability
            decremented.  success=False means at least one resource was
            insufficient; no state is changed.
        """
        requested = {
            "ambulances": ambulances,
            "rescue_teams": rescue_teams,
            "medical_supplies": medical_supplies,
            "medical_personnel": medical_personnel,
        }

        # Validate all resources first (atomic check)
        for rtype, amount in requested.items():
            if amount < 0:
                return False, f"Negative amount requested for '{rtype}' ({amount})."
            if amount > self._available[rtype]:
                return False, (
                    f"Insufficient '{rtype}': requested {amount}, "
                    f"available {self._available[rtype]}."
                )

        # All checks passed — deduct availability
        for rtype, amount in requested.items():
            self._available[rtype] -= amount

        self._reservations[emergency_id] = Reservation(
            emergency_id=emergency_id,
            ambulances=ambulances,
            rescue_teams=rescue_teams,
            medical_supplies=medical_supplies,
            medical_personnel=medical_personnel,
            created_at_minute=sim_time,
        )
        return True, None

    def reserve_partial(
        self,
        emergency_id: str,
        ambulances: int = 0,
        rescue_teams: int = 0,
        medical_supplies: int = 0,
        medical_personnel: int = 0,
        sim_time: float = 0.0,
    ) -> Dict[str, int]:
        """
        Reserve as much as is available for each resource type (best-effort).
        Returns a dict of actually reserved amounts.

        Used when full allocation is impossible and partial response is better
        than no response.
        """
        actual = {
            "ambulances": min(ambulances, self._available["ambulances"]),
            "rescue_teams": min(rescue_teams, self._available["rescue_teams"]),
            "medical_supplies": min(medical_supplies, self._available["medical_supplies"]),
            "medical_personnel": min(medical_personnel, self._available["medical_personnel"]),
        }
        for rtype, amount in actual.items():
            self._available[rtype] -= amount

        self._reservations[emergency_id] = Reservation(
            emergency_id=emergency_id,
            ambulances=actual["ambulances"],
            rescue_teams=actual["rescue_teams"],
            medical_supplies=actual["medical_supplies"],
            medical_personnel=actual["medical_personnel"],
            created_at_minute=sim_time,
        )
        return actual

    def release(self, emergency_id: str) -> bool:
        """
        Release resources previously reserved for an emergency.
        Returns True if a reservation existed and was released.
        """
        reservation = self._reservations.get(emergency_id)
        if reservation is None or reservation.released:
            return False

        self._available["ambulances"]        += reservation.ambulances
        self._available["rescue_teams"]      += reservation.rescue_teams
        self._available["medical_supplies"]  += reservation.medical_supplies
        self._available["medical_personnel"] += reservation.medical_personnel
        reservation.released = True
        return True

    # -----------------------------------------------------------------------
    # Query methods
    # -----------------------------------------------------------------------

    def available(self) -> Dict[str, int]:
        """Current available resource counts."""
        return dict(self._available)

    def capacity(self) -> Dict[str, int]:
        """Total resource capacity (initial pool)."""
        return dict(self._capacity)

    def utilisation(self) -> Dict[str, float]:
        """
        Resource utilisation rates (fraction in use).
        Returns 0.0 for resources with zero capacity.
        """
        result: Dict[str, float] = {}
        for rtype in RESOURCE_TYPES:
            cap = self._capacity[rtype]
            used = cap - self._available[rtype]
            result[rtype] = (used / cap) if cap > 0 else 0.0
        return result

    def in_use(self) -> Dict[str, int]:
        """Resources currently reserved (capacity − available)."""
        return {
            rtype: self._capacity[rtype] - self._available[rtype]
            for rtype in RESOURCE_TYPES
        }

    def get_reservation(self, emergency_id: str) -> Optional[Reservation]:
        return self._reservations.get(emergency_id)

    def all_reservations(self) -> List[Reservation]:
        return list(self._reservations.values())

    def active_reservations(self) -> List[Reservation]:
        return [r for r in self._reservations.values() if not r.released]

    def can_fulfil(self, requirements: Dict[str, int]) -> bool:
        """Check if the current available pool can fulfil a requirement dict."""
        return all(
            self._available.get(rtype, 0) >= amount
            for rtype, amount in requirements.items()
        )

    def shortfall(self, requirements: Dict[str, int]) -> Dict[str, int]:
        """
        Return the per-resource shortfall for a given requirement dict
        (i.e., how much is missing from current availability).
        """
        return {
            rtype: max(0, amount - self._available.get(rtype, 0))
            for rtype, amount in requirements.items()
        }

    # -----------------------------------------------------------------------
    # Display helpers
    # -----------------------------------------------------------------------

    def status_table(self) -> List[Dict]:
        """
        Return a list of dicts suitable for DataFrame construction or tabular
        printing.  Each row describes one resource type.
        """
        rows = []
        for rtype in RESOURCE_TYPES:
            cap = self._capacity[rtype]
            avail = self._available[rtype]
            used = cap - avail
            util = (used / cap * 100) if cap > 0 else 0.0
            rows.append({
                "Resource": RESOURCE_LABELS[rtype],
                "Unit": RESOURCE_UNITS[rtype],
                "Capacity": cap,
                "In Use": used,
                "Available": avail,
                "Utilisation (%)": round(util, 1),
            })
        return rows

    def __repr__(self) -> str:
        avail = self._available
        return (
            f"ResourceManager("
            f"ambulances={avail['ambulances']}/{self._capacity['ambulances']}, "
            f"rescue_teams={avail['rescue_teams']}/{self._capacity['rescue_teams']}, "
            f"medical_supplies={avail['medical_supplies']}/{self._capacity['medical_supplies']}, "
            f"medical_personnel={avail['medical_personnel']}/{self._capacity['medical_personnel']})"
        )
