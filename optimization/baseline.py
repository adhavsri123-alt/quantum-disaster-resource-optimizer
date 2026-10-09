"""
baseline.py
-----------
Greedy baseline solver for the QDO optimisation problem.

The baseline uses a priority-first, greedy allocation strategy:
  1. Rank active emergencies using a priority score based on:
     - emergency severity
     - number of people affected
     - travel time from depot
     - total resource requirements
  2. For each emergency (in priority order), allocate available resources up to requirement.
  3. Deduct allocated resources from available capacity pool.
  4. Record allocations and compute performance metrics.

This provides a reference benchmark that the QUBO solver aims to beat.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from simulation.simulation import SimulationState

from simulation.emergencies import AllocationRecord
from optimization.solver import AllocationPlan
from utils.metrics import full_metrics_report
from utils.explainability import generate_allocation_explanations


class GreedyBaselineSolver:
    """
    Greedy priority-based resource allocation baseline.
    """

    def __init__(self) -> None:
        self.name = "Greedy Baseline"
        self._last_result: Optional[AllocationPlan] = None

    def solve(self, state: SimulationState) -> AllocationPlan:
        """
        Run the greedy allocation strategy on the given SimulationState.

        Parameters
        ----------
        state : SimulationState
            The current simulation environment.

        Returns
        -------
        AllocationPlan
            The complete allocation plan and associated metrics.
        """
        start_time = time.perf_counter()

        # Read current resource availability and total capacity
        available = dict(state.resource_vector())
        capacity = dict(state.resource_manager.capacity())

        depot = "main_gate"

        def priority_score(em) -> float:
            """
            Compute composite priority score for greedy ordering.
            Higher score = higher priority.
            """
            tt = state.travel_time(depot, em.location_id)
            tt_penalty = 0.0 if math.isinf(tt) else (tt / 10.0)
            req_total = (
                em.ambulances_required
                + em.rescue_teams_required
                + em.medical_supplies_required
                + em.medical_personnel_required
            )
            return (em.severity * 3.0) + (em.people_affected * 0.1) - tt_penalty - (req_total * 0.05)

        # Sort active emergencies descending by priority score
        sorted_emergencies = sorted(state.active_emergencies, key=priority_score, reverse=True)

        allocations: Dict[str, AllocationRecord] = {}

        for em in sorted_emergencies:
            # Allocate available resources up to requirements
            alloc_amb = min(available["ambulances"], em.ambulances_required)
            alloc_res = min(available["rescue_teams"], em.rescue_teams_required)
            alloc_sup = min(available["medical_supplies"], em.medical_supplies_required)
            alloc_per = min(available["medical_personnel"], em.medical_personnel_required)

            # Deduct allocated resources from available pool
            available["ambulances"] -= alloc_amb
            available["rescue_teams"] -= alloc_res
            available["medical_supplies"] -= alloc_sup
            available["medical_personnel"] -= alloc_per

            # Calculate arrival time
            tt = state.travel_time(depot, em.location_id)
            arr_time = tt if not math.isinf(tt) else None

            record = AllocationRecord(
                emergency_id=em.id,
                ambulances_assigned=alloc_amb,
                rescue_teams_assigned=alloc_res,
                medical_supplies_assigned=alloc_sup,
                medical_personnel_assigned=alloc_per,
                dispatch_time_minutes=0.0,
                estimated_arrival_minutes=arr_time,
            )
            allocations[em.id] = record

        solve_time_ms = (time.perf_counter() - start_time) * 1000.0

        # Compute full performance metrics
        metrics = full_metrics_report(
            emergencies=state.active_emergencies,
            allocations=allocations,
            travel_times=state.travel_times,
            capacity=capacity,
            depot_id=depot,
            solver_name=self.name,
        )

        plan = AllocationPlan(
            solver_name=self.name,
            allocations=allocations,
            metrics=metrics,
            solver_metadata={"solve_time_ms": solve_time_ms},
        )
        plan.explanations = generate_allocation_explanations(plan, state)

        self._last_result = plan
        return plan

    def last_result(self) -> Optional[AllocationPlan]:
        """Return the most recently generated AllocationPlan."""
        return self._last_result
