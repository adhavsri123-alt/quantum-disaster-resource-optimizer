"""
optimization package
--------------------
Exports solvers, formulator, registry, and allocation plan.
"""

from optimization.baseline import GreedyBaselineSolver
from optimization.qubo import QUBOFormulator, QUBOSolver
from optimization.solver import AllocationPlan, SolverRegistry

__all__ = [
    "GreedyBaselineSolver",
    "QUBOFormulator",
    "QUBOSolver",
    "AllocationPlan",
    "SolverRegistry",
]
