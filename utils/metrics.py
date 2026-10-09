"""
metrics.py
----------
Performance metrics for evaluating an allocation plan.

The metrics defined here are used by both the baseline solver and the QUBO
solver to produce comparable, objective performance numbers.

All metric functions accept a SimulationState plus an allocation mapping
(emergency_id → AllocationRecord) and return scalar or per-emergency values.

Key metrics
-----------
- Average response time        : mean travel time to all served emergencies
- Maximum response time        : worst-case response time
- Unmet demand fraction        : fraction of total required resources not fulfilled
- Resource utilisation         : fraction of each resource type deployed
- Coverage score               : fraction of emergencies with at least one resource
- Weighted objective           : combined optimisation objective (lower = better)
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from data.scenarios import Emergency
from simulation.resources import RESOURCE_TYPES


# ---------------------------------------------------------------------------
# Weights for the composite objective  (tunable)
# ---------------------------------------------------------------------------

OBJECTIVE_WEIGHTS = {
    "response_time_weight":  0.40,   # weight for average response time component
    "unmet_demand_weight":   0.45,   # weight for unmet demand component
    "utilisation_weight":    0.15,   # weight for resource utilisation (reward)
    "time_scale_minutes":    15.0,   # normalise response times against this value
}


# ---------------------------------------------------------------------------
# Core metric functions
# ---------------------------------------------------------------------------

def compute_response_times(
    emergencies: List[Emergency],
    allocations: Dict[str, object],     # emergency_id → AllocationRecord
    travel_times: Dict[Tuple[str, str], float],
    depot_id: str = "main_gate",
) -> Dict[str, Optional[float]]:
    """
    Estimated response time (minutes) for each emergency.

    Response time = travel time from depot to emergency location.
    Returns None for emergencies that received no allocation.
    """
    result: Dict[str, Optional[float]] = {}
    for em in emergencies:
        alloc = allocations.get(em.id)
        if alloc is None:
            result[em.id] = None
        else:
            # Check if any resource was actually assigned
            assigned_total = (
                alloc.ambulances_assigned
                + alloc.rescue_teams_assigned
                + alloc.medical_supplies_assigned
                + alloc.medical_personnel_assigned
            )
            if assigned_total == 0:
                result[em.id] = None
            else:
                tt = travel_times.get((depot_id, em.location_id), math.inf)
                result[em.id] = tt
    return result


def average_response_time(
    response_times: Dict[str, Optional[float]]
) -> float:
    """
    Mean response time across all served emergencies.
    Ignores emergencies with no allocation (None).
    Returns math.inf if no emergencies are served.
    """
    served = [t for t in response_times.values() if t is not None and not math.isinf(t)]
    if not served:
        return math.inf
    return float(np.mean(served))


def max_response_time(
    response_times: Dict[str, Optional[float]]
) -> float:
    """Maximum response time across all served emergencies."""
    served = [t for t in response_times.values() if t is not None and not math.isinf(t)]
    if not served:
        return math.inf
    return float(np.max(served))


def compute_unmet_demand(
    emergencies: List[Emergency],
    allocations: Dict[str, object],     # emergency_id → AllocationRecord
) -> Dict[str, Dict[str, int]]:
    """
    Per-emergency, per-resource unmet demand (required − assigned).
    Returns a nested dict: {emergency_id: {resource_type: shortfall}}.
    """
    unmet: Dict[str, Dict[str, int]] = {}
    for em in emergencies:
        alloc = allocations.get(em.id)
        if alloc is None:
            unmet[em.id] = {
                "ambulances": em.ambulances_required,
                "rescue_teams": em.rescue_teams_required,
                "medical_supplies": em.medical_supplies_required,
                "medical_personnel": em.medical_personnel_required,
            }
        else:
            unmet[em.id] = {
                "ambulances": max(0, em.ambulances_required - alloc.ambulances_assigned),
                "rescue_teams": max(0, em.rescue_teams_required - alloc.rescue_teams_assigned),
                "medical_supplies": max(0, em.medical_supplies_required - alloc.medical_supplies_assigned),
                "medical_personnel": max(0, em.medical_personnel_required - alloc.medical_personnel_assigned),
            }
    return unmet


def unmet_demand_fraction(
    emergencies: List[Emergency],
    unmet: Dict[str, Dict[str, int]],
) -> float:
    """
    Total unmet resource units / total required resource units.
    0.0 = all demand fully met; 1.0 = nothing was allocated.
    """
    total_required = 0
    total_unmet = 0
    for em in emergencies:
        total_required += (
            em.ambulances_required + em.rescue_teams_required
            + em.medical_supplies_required + em.medical_personnel_required
        )
        em_unmet = unmet.get(em.id, {})
        total_unmet += sum(em_unmet.values())
    if total_required == 0:
        return 0.0
    return total_unmet / total_required


def coverage_score(
    emergencies: List[Emergency],
    allocations: Dict[str, object],
) -> float:
    """
    Fraction of emergencies that received at least one unit of any resource.
    """
    if not emergencies:
        return 1.0
    covered = 0
    for em in emergencies:
        alloc = allocations.get(em.id)
        if alloc is not None:
            total = (
                alloc.ambulances_assigned + alloc.rescue_teams_assigned
                + alloc.medical_supplies_assigned + alloc.medical_personnel_assigned
            )
            if total > 0:
                covered += 1
    return covered / len(emergencies)


def resource_utilisation(
    capacity: Dict[str, int],
    allocations: Dict[str, object],
) -> Dict[str, float]:
    """
    Fraction of each resource type that was deployed across all emergencies.
    Returns a dict {resource_type: utilisation_fraction}.
    """
    deployed: Dict[str, int] = {rt: 0 for rt in RESOURCE_TYPES}
    for alloc in allocations.values():
        deployed["ambulances"]        += alloc.ambulances_assigned
        deployed["rescue_teams"]      += alloc.rescue_teams_assigned
        deployed["medical_supplies"]  += alloc.medical_supplies_assigned
        deployed["medical_personnel"] += alloc.medical_personnel_assigned

    return {
        rt: (deployed[rt] / capacity[rt]) if capacity[rt] > 0 else 0.0
        for rt in RESOURCE_TYPES
    }


# ---------------------------------------------------------------------------
# Composite weighted objective  (lower = better)
# ---------------------------------------------------------------------------

def weighted_objective(
    emergencies: List[Emergency],
    allocations: Dict[str, object],
    travel_times: Dict[Tuple[str, str], float],
    capacity: Dict[str, int],
    depot_id: str = "main_gate",
    weights: Optional[Dict] = None,
) -> float:
    """
    Compute the composite optimisation objective for an allocation plan.

    Objective = w1 * (avg_response_time / scale) + w2 * unmet_fraction
                - w3 * avg_utilisation

    Lower scores are better.

    Parameters
    ----------
    weights : dict, optional
        Override default OBJECTIVE_WEIGHTS.

    Returns
    -------
    float
        Composite score in [−w3, w1 + w2] (can be negative if utilisation
        dominates).
    """
    w = weights or OBJECTIVE_WEIGHTS

    resp_times = compute_response_times(emergencies, allocations, travel_times, depot_id)
    unmet = compute_unmet_demand(emergencies, allocations)

    avg_rt = average_response_time(resp_times)
    unmet_frac = unmet_demand_fraction(emergencies, unmet)
    util = resource_utilisation(capacity, allocations)
    avg_util = float(np.mean(list(util.values()))) if util else 0.0

    # Normalise response time (clamp at 1.0 for times beyond scale)
    rt_norm = min(avg_rt / w["time_scale_minutes"], 1.0) if not math.isinf(avg_rt) else 1.0

    objective = (
        w["response_time_weight"] * rt_norm
        + w["unmet_demand_weight"] * unmet_frac
        - w["utilisation_weight"] * avg_util
    )
    return objective


def severity_weighted_unmet_demand_fraction(
    emergencies: List[Emergency],
    unmet: Dict[str, Dict[str, int]],
) -> float:
    """
    Weighted unmet demand fraction where unmet demand in higher-severity
    emergencies carries proportionally higher weight.
    0.0 = all demand met; 1.0 = no demand met.
    """
    total_weighted_req = 0.0
    total_weighted_unmet = 0.0
    for em in emergencies:
        req_units = (
            em.ambulances_required + em.rescue_teams_required
            + em.medical_supplies_required + em.medical_personnel_required
        )
        em_unmet = sum(unmet.get(em.id, {}).values())
        w = em.severity / 10.0
        total_weighted_req += req_units * w
        total_weighted_unmet += em_unmet * w
    if total_weighted_req == 0.0:
        return 0.0
    return total_weighted_unmet / total_weighted_req


def critical_coverage_score(
    emergencies: List[Emergency],
    allocations: Dict[str, object],
    min_severity: int = 7,
) -> float:
    """
    Coverage fraction for critical emergencies (severity >= min_severity).
    """
    critical_ems = [em for em in emergencies if em.severity >= min_severity]
    if not critical_ems:
        return 1.0
    covered = 0
    for em in critical_ems:
        alloc = allocations.get(em.id)
        if alloc is not None:
            total = (
                alloc.ambulances_assigned + alloc.rescue_teams_assigned
                + alloc.medical_supplies_assigned + alloc.medical_personnel_assigned
            )
            if total > 0:
                covered += 1
    return covered / len(critical_ems)


# ---------------------------------------------------------------------------
# Full metrics report
# ---------------------------------------------------------------------------

def full_metrics_report(
    emergencies: List[Emergency],
    allocations: Dict[str, object],
    travel_times: Dict[Tuple[str, str], float],
    capacity: Dict[str, int],
    depot_id: str = "main_gate",
    solver_name: str = "Unknown",
) -> Dict:
    """
    Compute and return a comprehensive metrics dict for display / comparison.
    """
    resp_times = compute_response_times(emergencies, allocations, travel_times, depot_id)
    unmet = compute_unmet_demand(emergencies, allocations)
    util = resource_utilisation(capacity, allocations)

    return {
        "solver": solver_name,
        "avg_response_time_min": average_response_time(resp_times),
        "max_response_time_min": max_response_time(resp_times),
        "unmet_demand_fraction": unmet_demand_fraction(emergencies, unmet),
        "severity_weighted_unmet_demand_fraction": severity_weighted_unmet_demand_fraction(emergencies, unmet),
        "coverage_score": coverage_score(emergencies, allocations),
        "critical_coverage_score": critical_coverage_score(emergencies, allocations),
        "resource_utilisation": util,
        "avg_utilisation": float(np.mean(list(util.values()))) if util else 0.0,
        "weighted_objective": weighted_objective(
            emergencies, allocations, travel_times, capacity, depot_id
        ),
        "per_emergency_response_times": resp_times,
        "per_emergency_unmet_demand": unmet,
    }
