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

Formulation notes and limitations
-----------------------------------
Capacity enforcement:
  The model uses *pairwise* quadratic penalties to discourage pairs of
  allocations whose combined quantity exceeds capacity.  This is a common
  QUBO approximation but NOT an exact constraint: with three or more
  emergencies each pair can be within capacity while the total exceeds it.
  The decoder enforces hard capacity bounds post-sampling and reports whether
  the raw sample was already feasible.

One-hot constraints:
  For each (emergency, resource_type) pair exactly one candidate level must be
  selected.  The penalty P_onehot*(sum_k x_k - 1)^2 expands to diagonal
  terms -P_onehot (linear) and cross terms +2*P_onehot (quadratic).
  When only one candidate level exists (e.g. zero-requirement) the same
  diagonal term -P_onehot strongly encourages selecting that level.

Solver:
  The underlying sampler is neal.SimulatedAnnealingSampler — a classical
  CPU-based simulated annealing algorithm, NOT quantum hardware.  Results
  must not be described as "quantum-powered" or guaranteed optimal.

Decoder:
  The decoder reads the sampler allocation, checks raw feasibility, trims
  excess from lowest-severity emergencies if needed, and caps at requirements.
  NO secondary greedy fill is applied.  Raw and final feasibility are both
  reported transparently in solver_metadata.

The formulation is sampled using Simulated Annealing via `neal` and `dimod`."""

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


def get_candidate_levels(req: int, cap: int, is_contested: bool = True) -> List[int]:
    """
    Generate discrete candidate allocation quantities for QUBO decision variables.

    Parameters
    ----------
    req : int
        Required quantity of resource for an emergency.
    cap : int
        Total available capacity of resource type.
    is_contested : bool, optional
        Whether the resource is contested campus-wide (total demand > capacity).
        Defaults to True for backwards compatibility and unit testing.

    Returns
    -------
    List[int]
        Unique, sorted non-negative integer candidate quantities.
    """
    if req <= 0 or cap <= 0:
        return [0]

    # If the resource is uncontested campus-wide (total demand <= capacity),
    # there is zero competition among emergencies and no capacity rationing is needed.
    # Discretizing into intermediate fractional levels would create artificial local
    # energy minima separated by one-hot penalty barriers that trap MCMC/SA samplers.
    if not is_contested:
        return [min(req, cap)]

    # For small requirements (e.g. ambulances, rescue teams <= 5),
    # provide exact integer choices [0..min(req, cap)].
    if req <= 5:
        return list(range(0, min(req, cap) + 1))

    # For larger contested requirements, provide discrete percentage steps
    raw_levels = [
        0,
        int(round(0.25 * req)),
        int(round(0.50 * req)),
        int(round(0.75 * req)),
        min(req, cap),
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

        # Determine campus-wide contention per resource type.
        # A resource is contested if total demand across active emergencies exceeds capacity.
        total_demands = {
            rtype: sum(getattr(em, f"{rtype}_required") for em in emergencies)
            for rtype in RESOURCE_TYPES
        }
        contested = {
            rtype: total_demands[rtype] > capacity[rtype]
            for rtype in RESOURCE_TYPES
        }

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
                quantities = get_candidate_levels(req, cap, is_contested=contested[rtype])

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
        #
        # Expanded: P_onehot*(sum x_k)^2 - 2*P_onehot*(sum x_k) + constant
        # Diagonal (linear): x_k^2 = x_k for binary, so coeff = P_onehot - 2*P_onehot = -P_onehot
        # Cross (quadratic):  +2*P_onehot per pair (i < j)
        # Single-option case (len==1): P_onehot*(x-1)^2 gives same -P_onehot diagonal.
        for (em_id, rtype), vars_list in em_res_vars.items():
            for i, v1 in enumerate(vars_list):
                add_q(v1, v1, -P_onehot)          # diagonal term
                for j in range(i + 1, len(vars_list)):
                    v2 = vars_list[j]
                    add_q(v1, v2, 2.0 * P_onehot) # cross term

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

    def check_raw_feasibility(
        self,
        sample: Dict[str, int],
        capacity: Dict[str, int],
    ) -> Tuple[bool, Dict[str, int]]:
        """
        Check whether a raw binary sample satisfies capacity constraints.

        Returns
        -------
        (is_feasible, total_per_resource)
            is_feasible: True if no resource type is over-allocated.
            total_per_resource: total allocated units per resource type in sample.
        """
        selected: Dict[Tuple[str, str], int] = {}
        for var_name, val in sample.items():
            if val == 1 and var_name in self._var_info:
                info = self._var_info[var_name]
                key = (info["emergency_id"], info["resource_type"])
                q = info["quantity"]
                selected[key] = max(selected.get(key, 0), q)
        total: Dict[str, int] = {rt: 0 for rt in RESOURCE_TYPES}
        for (em_id, rtype), q in selected.items():
            total[rtype] += q
        is_feasible = all(total[rt] <= capacity[rt] for rt in RESOURCE_TYPES)
        return is_feasible, total

    def decode_solution(
        self,
        sample: Dict[str, int],
        state: SimulationState,
    ) -> Tuple[AllocationPlan, bool, bool]:
        """
        Decode a QUBO binary sample back into a valid AllocationPlan.

        Steps:
          1. One-hot decoding: extract per-emergency quantities from sample.
          2. Check raw sample feasibility against available capacity.
          3. Trim lowest-severity emergencies if raw sample violated capacity.
          4. Cap each allocation at the emergency's stated requirement.
          5. NO secondary greedy fill — unused capacity is NOT redistributed.

        Returns
        -------
        (plan, raw_feasible, final_feasible)
            raw_feasible: True if raw sample satisfied all capacity bounds.
            final_feasible: True if decoded allocation satisfies all bounds.
        """
        depot = "main_gate"
        emergencies = state.active_emergencies
        capacity = dict(state.resource_manager.capacity())
        available = dict(state.resource_vector())

        # Step 1: Extract selected quantities from binary sample (one-hot decoding).
        # If multiple levels selected for same (em, rtype), take max (one-hot violation).
        allocations_raw: Dict[str, Dict[str, int]] = {
            em.id: {rt: 0 for rt in RESOURCE_TYPES} for em in emergencies
        }

        for var_name, val in sample.items():
            if val == 1 and var_name in self._var_info:
                info = self._var_info[var_name]
                em_id = info["emergency_id"]
                rtype = info["resource_type"]
                q = info["quantity"]
                allocations_raw[em_id][rtype] = max(allocations_raw[em_id][rtype], q)

        # Step 2: Check raw sample feasibility.
        raw_feasible, _ = self.check_raw_feasibility(sample, available)

        # Step 3: Enforce hard capacity bounds (post-sampling trimming only).
        # Trim lowest-severity emergencies first to restore feasibility.
        for rtype in RESOURCE_TYPES:
            tot_allocated = sum(allocations_raw[em.id][rtype] for em in emergencies)
            max_avail = available[rtype]

            if tot_allocated > max_avail:
                sorted_ems = sorted(emergencies, key=lambda e: e.severity)
                excess = tot_allocated - max_avail
                for em in sorted_ems:
                    if excess <= 0:
                        break
                    curr = allocations_raw[em.id][rtype]
                    if curr > 0:
                        trim = min(curr, excess)
                        allocations_raw[em.id][rtype] -= trim
                        excess -= trim

        # Verify whether the final decoded allocation satisfies capacity bounds
        final_feasible = all(
            sum(allocations_raw[em.id][rt] for em in emergencies) <= available[rt]
            for rt in RESOURCE_TYPES
        )

        # Step 4: Build AllocationRecord per emergency, capping at requirement.
        # NOTE: No greedy fill here — unused capacity stays unallocated so that
        # the reported allocation is what the QUBO sampler actually chose.
        final_allocations: Dict[str, AllocationRecord] = {}

        for em in emergencies:
            alloc_dict = allocations_raw[em.id]

            a_amb = min(alloc_dict["ambulances"],        em.ambulances_required)
            a_res = min(alloc_dict["rescue_teams"],      em.rescue_teams_required)
            a_sup = min(alloc_dict["medical_supplies"],  em.medical_supplies_required)
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
        return plan, raw_feasible, final_feasible


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

        Timing breakdown (all in milliseconds) is stored in plan.solver_metadata:
          qubo_formulation_time_ms  - time to build the QUBO dict
          bqm_construction_time_ms  - time to build the BinaryQuadraticModel
          sampler_time_ms           - SA sampler wall time (classical CPU)
          decode_time_ms            - decoding and feasibility-repair time
          solve_time_ms / total_solve_time_ms  - end-to-end wall time
        """
        t0 = time.perf_counter()

        # Phase 1: QUBO formulation
        formulator = QUBOFormulator(self.penalties)
        Q_dict, var_info = formulator.formulate(state)
        t1 = time.perf_counter()

        # Phase 2: BinaryQuadraticModel construction
        bqm = dimod.BinaryQuadraticModel.from_qubo(Q_dict)
        t2 = time.perf_counter()

        # Phase 3: Sample using neal SimulatedAnnealingSampler (classical CPU)
        sampler = neal.SimulatedAnnealingSampler()
        if self.seed is not None:
            sampleset = sampler.sample(bqm, num_reads=self.num_reads, seed=self.seed)
        else:
            sampleset = sampler.sample(bqm, num_reads=self.num_reads)
        t3 = time.perf_counter()

        # Extract best sample (lowest energy)
        first_sample = sampleset.first
        best_sample = {k: int(v) for k, v in first_sample.sample.items()}
        energy = float(first_sample.energy)

        # Phase 4: Decode sample -> AllocationPlan
        plan, raw_feasible, final_feasible = formulator.decode_solution(best_sample, state)
        t4 = time.perf_counter()

        # Timing breakdown (milliseconds)
        qubo_ms  = (t1 - t0) * 1000.0
        bqm_ms   = (t2 - t1) * 1000.0
        sa_ms    = (t3 - t2) * 1000.0
        dec_ms   = (t4 - t3) * 1000.0
        total_ms = (t4 - t0) * 1000.0

        plan.solver_metadata = {
            "energy": energy,
            "qubo_formulation_time_ms": round(qubo_ms, 3),
            "bqm_construction_time_ms": round(bqm_ms, 3),
            "sampler_time_ms": round(sa_ms, 3),
            "decode_time_ms": round(dec_ms, 3),
            "solve_time_ms": round(total_ms, 3),          # kept for backwards compat
            "total_solve_time_ms": round(total_ms, 3),
            "num_reads": self.num_reads,
            "num_variables": len(var_info),
            "num_quadratic_terms": len(Q_dict),
            "raw_sample_feasible": raw_feasible,
            "final_allocation_feasible": final_feasible,
            "feasibility_status": (
                "Raw sample feasible" if raw_feasible
                else "Raw sample infeasible -- capacity trimming applied"
            ),
            "seed": self.seed,
            "sampler": "neal.SimulatedAnnealingSampler (classical CPU)",
        }

        # Generate data-driven explanations
        plan.explanations = generate_allocation_explanations(plan, state)

        self._last_result = plan
        return plan

    def last_result(self) -> Optional[AllocationPlan]:
        """Return the most recently generated AllocationPlan."""
        return self._last_result
