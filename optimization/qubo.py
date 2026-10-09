"""
qubo.py
-------
QUBO (Quadratic Unconstrained Binary Optimization) problem formulation
and solver engine for the QDO resource allocation problem.

The QDO allocation problem is formulated as a QUBO where:
  - Binary variables x_{i, r, k} represent assigning discrete level k of
    resource type r to emergency i.
  - Objective terms minimise:
      1. Travel time / response delay (weighted by travel distance & emergency severity)
      2. Unmet demand penalty (weighted by emergency severity & people affected)
      3. Over-capacity interaction penalties (penalising total allocations exceeding capacity)
      4. One-hot configuration penalty per (emergency, resource) pair
      5. Resource utilisation reward

The formulation is sampled using Simulated Annealing via `neal` and `dimod`.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
import numpy as np

import dimod
import neal

if TYPE_CHECKING:
    from simulation.simulation import SimulationState

from simulation.emergencies import AllocationRecord
from simulation.resources import RESOURCE_TYPES
from optimization.solver import AllocationPlan
from utils.metrics import full_metrics_report
from utils.explainability import generate_allocation_explanations


# Documented hyperparameter penalties for QUBO formulation
QUBO_PENALTIES = {
    "capacity_penalty":      200.0,   # Penalty when paired allocations exceed capacity
    "one_hot_penalty":       100.0,   # Penalty for selecting invalid number of discrete levels
    "response_time_weight":   10.0,   # Weight for travel time / response delay
    "unmet_demand_penalty":   50.0,   # Penalty for unmet resource demand (weighted by severity)
    "utilisation_reward":      2.0,   # Reward for deploying available resources
}


def get_candidate_levels(req: int, cap: int) -> List[int]:
    """
    Generate discrete candidate allocation quantities for QUBO decision variables.

    Parameters
    ----------
    req : int
        Required quantity of resource for an emergency.
    cap : int
        Total available capacity of resource type.

    Returns
    -------
    List[int]
        Unique, sorted non-negative integer candidate quantities.
    """
    if req <= 0:
        return [0]
    # For small requirements (e.g. ambulances, rescue teams, personnel <= 5),
    # provide exact integer choices [0..min(req, cap)].
    if req <= 5:
        return list(range(0, min(req, cap) + 1))

    # For larger requirements (e.g. medical supplies), provide discrete percentage steps
    raw_levels = [
        0,
        int(round(0.25 * req)),
        int(round(0.50 * req)),
        int(round(0.75 * req)),
        req,
    ]
    quantities = sorted(list(set(min(cap, max(0, q)) for q in raw_levels)))
    return quantities


class QUBOFormulator:
    """
    Constructs the QUBO matrix Q and decodes samples for the resource allocation problem.
    """

    def __init__(self, penalties: Optional[Dict[str, float]] = None) -> None:
        self.penalties = penalties or dict(QUBO_PENALTIES)
        self._Q_dict: Dict[Tuple[str, str], float] = {}
        self._var_info: Dict[str, Dict] = {}
        self._var_list: List[str] = []

    def formulate(
        self, state: SimulationState
    ) -> Tuple[Dict[Tuple[str, str], float], Dict[str, Dict]]:
        """
        Build and return the QUBO dictionary and variable index mapping.

        Parameters
        ----------
        state : SimulationState
            The current simulation environment.

        Returns
        -------
        Tuple[Dict[Tuple[str, str], float], Dict[str, Dict]]
            - Q_dict: Map of (var_i, var_j) -> quadratic coefficient
            - var_info: Metadata dictionary for each binary variable
        """
        depot = "main_gate"
        emergencies = state.active_emergencies
        capacity = state.resource_manager.capacity()

        self._Q_dict = {}
        self._var_info = {}
        self._var_list = []

        P_cap = float(self.penalties.get("capacity_penalty", 200.0))
        P_onehot = float(self.penalties.get("one_hot_penalty", 100.0))
        P_unmet = float(self.penalties.get("unmet_demand_penalty", 50.0))
        W_travel = float(self.penalties.get("response_time_weight", 10.0))
        W_util = float(self.penalties.get("utilisation_reward", 2.0))

        # Track variables grouped by (em_id, rtype)
        em_res_vars: Dict[Tuple[str, str], List[str]] = {}

        # 1. Define decision variables and candidate allocation quantities
        for em in emergencies:
            tt = state.travel_time(depot, em.location_id)
            tt_val = 60.0 if math.isinf(tt) else tt

            reqs = {
                "ambulances": em.ambulances_required,
                "rescue_teams": em.rescue_teams_required,
                "medical_supplies": em.medical_supplies_required,
                "medical_personnel": em.medical_personnel_required,
            }

            for rtype in RESOURCE_TYPES:
                req = reqs[rtype]
                cap = capacity[rtype]
                quantities = get_candidate_levels(req, cap)

                key = (em.id, rtype)
                em_res_vars[key] = []

                for level_idx, q in enumerate(quantities):
                    var_name = f"x_{em.id}_{rtype}_L{level_idx}"
                    em_res_vars[key].append(var_name)
                    self._var_list.append(var_name)
                    self._var_info[var_name] = {
                        "emergency_id": em.id,
                        "resource_type": rtype,
                        "level_index": level_idx,
                        "quantity": q,
                        "requirement": req,
                        "severity": em.severity,
                        "people_affected": em.people_affected,
                        "travel_time": tt_val,
                    }

        def add_q(u: str, v: str, weight: float):
            if u > v:
                u, v = v, u
            pair = (u, v)
            self._Q_dict[pair] = self._Q_dict.get(pair, 0.0) + weight

        # 2. Add One-Hot Penalties: P_onehot * (sum_k x_{i, r, k} - 1)^2
        for (em_id, rtype), vars_list in em_res_vars.items():
            if len(vars_list) == 1:
                # Single option (e.g. req=0), penalise not selecting it
                add_q(vars_list[0], vars_list[0], -P_onehot)
                continue
            for i, v1 in enumerate(vars_list):
                add_q(v1, v1, -P_onehot)
                for j in range(i + 1, len(vars_list)):
                    v2 = vars_list[j]
                    add_q(v1, v2, 2.0 * P_onehot)

        # 3. Add Objective Terms (Unmet Demand, Travel Time Delay, Utilisation)
        for var_name, info in self._var_info.items():
            q = info["quantity"]
            req = info["requirement"]
            sev = info["severity"]
            people = info["people_affected"]
            tt = info["travel_time"]
            rtype = info["resource_type"]
            cap = capacity[rtype]

            obj_weight = 0.0

            # (a) Unmet demand penalty (scaled by severity and population impact)
            if req > 0:
                unmet_frac = (req - q) / float(req)
                sev_factor = (sev / 10.0) * (1.0 + (people / 50.0))
                demand_cost = P_unmet * sev_factor * unmet_frac
                obj_weight += demand_cost

            # (b) Travel time delay cost when resources are dispatched
            if q > 0:
                # Higher travel time to high-severity emergency increases cost
                travel_cost = W_travel * (tt / 15.0) * (q / float(max(1, req))) * (sev / 10.0)
                obj_weight += travel_cost

            # (c) Utilisation reward for deploying available resources
            if cap > 0 and q > 0:
                util_reward = -W_util * (q / float(cap))
                obj_weight += util_reward

            # (d) Direct capacity penalty for single variable exceeding cap
            if q > cap:
                obj_weight += P_cap * ((q - cap) / float(cap if cap > 0 else 1))

            add_q(var_name, var_name, obj_weight)

        # 4. Add Capacity Interaction Penalties when paired allocations exceed capacity
        for rtype in RESOURCE_TYPES:
            cap = capacity[rtype]
            r_vars = [v for v, info in self._var_info.items() if info["resource_type"] == rtype]

            for i, v1 in enumerate(r_vars):
                q1 = self._var_info[v1]["quantity"]
                if q1 == 0:
                    continue

                for j in range(i + 1, len(r_vars)):
                    v2 = r_vars[j]
                    # Skip interaction between different levels of the SAME emergency
                    if self._var_info[v1]["emergency_id"] == self._var_info[v2]["emergency_id"]:
                        continue
                    q2 = self._var_info[v2]["quantity"]
                    if q2 == 0:
                        continue

                    # If combined allocation exceeds capacity, add quadratic penalty
                    if q1 + q2 > cap:
                        excess = (q1 + q2) - cap
                        penalty_weight = P_cap * (excess / float(cap if cap > 0 else 1))
                        add_q(v1, v2, penalty_weight)

        return self._Q_dict, self._var_info

    def decode_solution(
        self,
        sample: Dict[str, int],
        state: SimulationState,
    ) -> Tuple[AllocationPlan, bool]:
        """
        Decode a QUBO binary sample back into a valid AllocationPlan.
        Enforces resource capacity bounds and non-negativity.
        Returns (AllocationPlan, is_feasible).
        """
        depot = "main_gate"
        emergencies = state.active_emergencies
        capacity = dict(state.resource_manager.capacity())
        available = dict(state.resource_vector())

        allocations_raw: Dict[str, Dict[str, int]] = {
            em.id: {rt: 0 for rt in RESOURCE_TYPES} for em in emergencies
        }

        # Step 1: Extract selected quantities from binary sample
        for var_name, val in sample.items():
            if val == 1 and var_name in self._var_info:
                info = self._var_info[var_name]
                em_id = info["emergency_id"]
                rtype = info["resource_type"]
                q = info["quantity"]
                allocations_raw[em_id][rtype] = max(allocations_raw[em_id][rtype], q)

        is_feasible = True

        # Step 2: Enforce hard capacity bounds across all emergencies
        for rtype in RESOURCE_TYPES:
            tot_allocated = sum(allocations_raw[em.id][rtype] for em in emergencies)
            max_cap = available[rtype]

            if tot_allocated > max_cap:
                is_feasible = False
                # Sort emergencies ascending by severity (trim lowest severity first)
                sorted_ems = sorted(emergencies, key=lambda e: e.severity)
                excess = tot_allocated - max_cap
                for em in sorted_ems:
                    if excess <= 0:
                        break
                    curr = allocations_raw[em.id][rtype]
                    if curr > 0:
                        trim = min(curr, excess)
                        allocations_raw[em.id][rtype] -= trim
                        excess -= trim

        # Step 3: Leftover capacity filling
        # If unallocated capacity remains, fill remaining capacity in order of severity & travel efficiency
        for rtype in RESOURCE_TYPES:
            current_avail = available[rtype] - sum(allocations_raw[em.id][rtype] for em in emergencies)
            if current_avail > 0:
                # Sort emergencies by efficiency score: severity * 2 - (travel_time / 5)
                def efficiency_score(e) -> float:
                    tt = state.travel_time(depot, e.location_id)
                    tt_val = 20.0 if math.isinf(tt) else tt
                    return (e.severity * 2.0) - (tt_val / 5.0)

                sorted_ems = sorted(emergencies, key=efficiency_score, reverse=True)

                for em in sorted_ems:
                    req = getattr(em, f"{rtype}_required")
                    current_assigned = allocations_raw[em.id][rtype]
                    shortfall = req - current_assigned
                    if shortfall > 0 and current_avail > 0:
                        add_amount = min(current_avail, shortfall)
                        allocations_raw[em.id][rtype] += add_amount
                        current_avail -= add_amount

        # Step 4: Construct final AllocationRecord for each emergency
        final_allocations: Dict[str, AllocationRecord] = {}

        for em in emergencies:
            alloc_dict = allocations_raw[em.id]

            a_amb = min(alloc_dict["ambulances"], em.ambulances_required)
            a_res = min(alloc_dict["rescue_teams"], em.rescue_teams_required)
            a_sup = min(alloc_dict["medical_supplies"], em.medical_supplies_required)
            a_per = min(alloc_dict["medical_personnel"], em.medical_personnel_required)

            tt = state.travel_time(depot, em.location_id)
            arr_time = tt if not math.isinf(tt) else None

            record = AllocationRecord(
                emergency_id=em.id,
                ambulances_assigned=a_amb,
                rescue_teams_assigned=a_res,
                medical_supplies_assigned=a_sup,
                medical_personnel_assigned=a_per,
                dispatch_time_minutes=0.0,
                estimated_arrival_minutes=arr_time,
            )
            final_allocations[em.id] = record

        metrics = full_metrics_report(
            emergencies=emergencies,
            allocations=final_allocations,
            travel_times=state.travel_times,
            capacity=capacity,
            depot_id=depot,
            solver_name="QUBO Solver",
        )

        plan = AllocationPlan(
            solver_name="QUBO Solver",
            allocations=final_allocations,
            metrics=metrics,
            solver_metadata={},
        )
        return plan, is_feasible


class QUBOSolver:
    """
    QUBO-based resource allocation solver using Simulated Annealing (neal).
    """

    def __init__(
        self,
        penalties: Optional[Dict[str, float]] = None,
        num_reads: int = 500,
        seed: Optional[int] = 42,
    ) -> None:
        self.name = "QUBO Solver"
        self.penalties = penalties or dict(QUBO_PENALTIES)
        self.num_reads = num_reads
        self.seed = seed
        self._last_result: Optional[AllocationPlan] = None

    def solve(self, state: SimulationState) -> AllocationPlan:
        """
        Formulate QUBO, sample using Simulated Annealing, and return AllocationPlan.
        """
        start_time = time.perf_counter()

        formulator = QUBOFormulator(self.penalties)
        Q_dict, var_info = formulator.formulate(state)

        # Build BinaryQuadraticModel
        bqm = dimod.BinaryQuadraticModel.from_qubo(Q_dict)

        # Sample using neal SimulatedAnnealingSampler
        sampler = neal.SimulatedAnnealingSampler()
        if self.seed is not None:
            sampleset = sampler.sample(bqm, num_reads=self.num_reads, seed=self.seed)
        else:
            sampleset = sampler.sample(bqm, num_reads=self.num_reads)

        # Extract best sample
        first_sample = sampleset.first
        best_sample = {k: int(v) for k, v in first_sample.sample.items()}
        energy = float(first_sample.energy)

        # Decode sample back to AllocationPlan
        plan, is_feasible = formulator.decode_solution(best_sample, state)

        solve_time_ms = (time.perf_counter() - start_time) * 1000.0

        plan.solver_metadata = {
            "energy": energy,
            "solve_time_ms": solve_time_ms,
            "num_reads": self.num_reads,
            "num_variables": len(var_info),
            "num_quadratic_terms": len(Q_dict),
            "feasibility_status": "Feasible" if is_feasible else "Adjusted by Decoder",
            "seed": self.seed,
        }

        # Generate data-driven explanations
        plan.explanations = generate_allocation_explanations(plan, state)

        self._last_result = plan
        return plan

    def last_result(self) -> Optional[AllocationPlan]:
        """Return the most recently generated AllocationPlan."""
        return self._last_result
