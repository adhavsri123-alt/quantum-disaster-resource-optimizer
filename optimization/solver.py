"""
solver.py
---------
Unified solver interface and registry for QDO.

This module provides the SolverRegistry and a common AllocationPlan
dataclass so the Streamlit UI and test scripts can swap between the
Greedy Baseline and the QUBO solver without changing calling code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from simulation.simulation import SimulationState
from simulation.emergencies import AllocationRecord


# ---------------------------------------------------------------------------
# AllocationPlan — unified output of any solver
# ---------------------------------------------------------------------------

@dataclass
class AllocationPlan:
    """
    The complete output produced by a solver.

    Attributes
    ----------
    solver_name : str
        Name of the solver that produced this plan.
    allocations : dict
        Mapping of emergency_id -> AllocationRecord.
    metrics : dict
        Performance metrics computed from the plan.
    solver_metadata : dict
        Optional solver-specific metadata (e.g., QUBO energy, solve time).
    explanations : dict
        Mapping of emergency_id -> human-readable explanation string.
    """

    solver_name: str
    allocations: Dict[str, AllocationRecord] = field(default_factory=dict)
    metrics: Dict = field(default_factory=dict)
    solver_metadata: Dict = field(default_factory=dict)
    explanations: Dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        obj = self.metrics.get("weighted_objective", "?")
        if isinstance(obj, float):
            obj_str = f"{obj:.4f}"
        else:
            obj_str = str(obj)
        return (
            f"AllocationPlan(solver={self.solver_name!r}, "
            f"emergencies_covered={len(self.allocations)}, "
            f"objective={obj_str})"
        )


# ---------------------------------------------------------------------------
# Solver registry — maps solver names to solver instances
# ---------------------------------------------------------------------------

class SolverRegistry:
    """
    Registry mapping solver names to solver instances.
    """

    _registry: Dict[str, object] = {}

    @classmethod
    def register(cls, name: str, solver: object) -> None:
        cls._registry[name] = solver

    @classmethod
    def _ensure_defaults(cls) -> None:
        if not cls._registry:
            from optimization.baseline import GreedyBaselineSolver
            from optimization.qubo import QUBOSolver

            cls._registry["Greedy Baseline"] = GreedyBaselineSolver()
            cls._registry["QUBO Solver"] = QUBOSolver()

    @classmethod
    def get(cls, name: str) -> Optional[object]:
        cls._ensure_defaults()
        return cls._registry.get(name)

    @classmethod
    def available(cls) -> List[str]:
        cls._ensure_defaults()
        return list(cls._registry.keys())
