"""
server.py
---------
FastAPI REST API that bridges the QDO Python backend to the Three.js frontend.

Endpoints:
  GET  /api/locations        – Campus locations + edges (for map data)
  GET  /api/scenarios        – List of available scenarios
  POST /api/solve            – Run Greedy and/or QUBO solver on a given scenario
  POST /api/inject           – Inject a dynamic emergency into a running simulation
  GET  /api/health           – Health check

Run:
    uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Backend imports ────────────────────────────────────────────────────────
from data.campus import LOCATIONS, _EDGES
from data.scenarios import (
    DEFAULT_RESOURCES,
    SCENARIO_REGISTRY,
    Emergency,
    ResourcePool,
    Scenario,
)
from simulation.simulation import SimulationState, create_simulation
from optimization.baseline import GreedyBaselineSolver
from optimization.solver import AllocationPlan
from utils.explainability import generate_allocation_explanations

try:
    from optimization.qubo import QUBOSolver
    QUBO_AVAILABLE = True
except ImportError:
    QUBO_AVAILABLE = False

# ── App setup ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="QDO Backend API",
    description="Quantum Disaster Resource Optimizer – REST bridge for Three.js frontend",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════════════
# Request / Response schemas
# ═══════════════════════════════════════════════════════════════════════════

class SolveRequest(BaseModel):
    scenario: str = "alpha"          # "alpha" | "beta" | "gamma" | "stress"
    solver: str = "both"             # "greedy" | "qubo" | "both"
    seed: int = 42
    qubo_reads: int = 300            # SA sweeps / reads (passed to QUBOSolver)
    # Resource pool overrides (optional)
    ambulances: Optional[int] = None
    rescue_teams: Optional[int] = None
    medical_supplies: Optional[int] = None
    medical_personnel: Optional[int] = None


class InjectRequest(BaseModel):
    scenario: str = "alpha"
    location_id: str = "cafeteria"
    emergency_type: str = "fire"
    severity: int = 8
    people_affected: int = 20
    ambulances_required: int = 2
    rescue_teams_required: int = 1
    medical_supplies_required: int = 15
    medical_personnel_required: int = 3
    seed: int = 42


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _safe_float(v: float) -> Any:
    """Convert inf/nan to null-safe JSON value."""
    if v is None:
        return None
    if math.isinf(v) or math.isnan(v):
        return None
    return round(v, 4)


def _plan_to_dict(plan: AllocationPlan, state: SimulationState) -> Dict:
    """Serialize an AllocationPlan into a JSON-serialisable dict."""
    allocations = {}
    for em_id, rec in plan.allocations.items():
        allocations[em_id] = {
            "ambulances_assigned":       rec.ambulances_assigned,
            "rescue_teams_assigned":     rec.rescue_teams_assigned,
            "medical_supplies_assigned": rec.medical_supplies_assigned,
            "medical_personnel_assigned":rec.medical_personnel_assigned,
            "estimated_arrival_minutes": _safe_float(rec.estimated_arrival_minutes),
        }

    metrics = {}
    for k, v in plan.metrics.items():
        if isinstance(v, float):
            metrics[k] = _safe_float(v)
        elif isinstance(v, dict):
            # nested dicts (per_emergency_*, resource_utilisation)
            metrics[k] = {
                ik: (_safe_float(iv) if isinstance(iv, float) else iv)
                for ik, iv in v.items()
            }
        else:
            metrics[k] = v

    explanations = plan.explanations or {}

    solver_meta = {}
    for k, v in plan.solver_metadata.items():
        solver_meta[k] = _safe_float(v) if isinstance(v, float) else v

    return {
        "solver_name": plan.solver_name,
        "allocations": allocations,
        "metrics": metrics,
        "solver_metadata": solver_meta,
        "explanations": explanations,
    }


def _emergency_to_dict(em: Emergency) -> Dict:
    loc = LOCATIONS.get(em.location_id)
    return {
        "id": em.id,
        "location_id": em.location_id,
        "location_name": loc.name if loc else em.location_id,
        "location_x": loc.x if loc else 0,
        "location_y": loc.y if loc else 0,
        "emergency_type": em.emergency_type,
        "type_label": em.type_label,
        "severity": em.severity,
        "people_affected": em.people_affected,
        "ambulances_required": em.ambulances_required,
        "rescue_teams_required": em.rescue_teams_required,
        "medical_supplies_required": em.medical_supplies_required,
        "medical_personnel_required": em.medical_personnel_required,
        "description": em.description,
        "priority_score": round(em.priority_score, 3),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "qubo_available": QUBO_AVAILABLE,
        "locations": len(LOCATIONS),
        "scenarios": list(SCENARIO_REGISTRY.keys()),
    }


@app.get("/api/locations")
def get_locations():
    """Return campus nodes and road edges for the frontend mini-map overlay."""
    nodes = [
        {
            "id": loc.id,
            "name": loc.name,
            "x": loc.x,
            "y": loc.y,
            "description": loc.description,
            "tags": loc.tags,
        }
        for loc in LOCATIONS.values()
    ]
    edges = [
        {"from": u, "to": v, "distance_m": d}
        for u, v, d in _EDGES
    ]
    return {"nodes": nodes, "edges": edges}


@app.get("/api/scenarios")
def list_scenarios():
    """Return metadata for all available scenarios."""
    result = []
    for key, fn in SCENARIO_REGISTRY.items():
        sc: Scenario = fn()
        result.append({
            "key": key.upper(),
            "name": sc.name,
            "description": sc.description,
            "num_emergencies": len(sc.emergencies),
            "blocked_routes": sc.blocked_routes,
            "emergencies": [_emergency_to_dict(e) for e in sc.emergencies],
        })
    return result


@app.post("/api/solve")
def solve(req: SolveRequest):
    """
    Run one or both solvers on the requested scenario.

    Returns:
      {
        scenario: {...},
        emergencies: [...],
        greedy: { allocations, metrics, solver_metadata, explanations },  # if requested
        qubo:   { allocations, metrics, solver_metadata, explanations },  # if requested & available
        resource_capacity: {...},
        blocked_routes: [...],
      }
    """
    key = req.scenario.lower()
    if key not in SCENARIO_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown scenario '{req.scenario}'")

    sc: Scenario = SCENARIO_REGISTRY[key](seed=req.seed)

    # Build resource pool (with optional frontend overrides)
    res_pool = ResourcePool(
        ambulances=       req.ambulances        or DEFAULT_RESOURCES.ambulances,
        rescue_teams=     req.rescue_teams      or DEFAULT_RESOURCES.rescue_teams,
        medical_supplies= req.medical_supplies  or DEFAULT_RESOURCES.medical_supplies,
        medical_personnel=req.medical_personnel or DEFAULT_RESOURCES.medical_personnel,
    )

    result: Dict[str, Any] = {
        "scenario": {
            "key":          sc.name,
            "description":  sc.description,
            "blocked_routes": sc.blocked_routes,
        },
        "emergencies": [_emergency_to_dict(e) for e in sc.emergencies],
        "resource_capacity": res_pool.as_dict(),
    }

    solver_mode = req.solver.lower()

    # ── Greedy ──────────────────────────────────────────────────────────
    if solver_mode in ("greedy", "both"):
        state_g = SimulationState(sc, res_pool)
        greedy = GreedyBaselineSolver()
        plan_g = greedy.solve(state_g)
        result["greedy"] = _plan_to_dict(plan_g, state_g)

    # ── QUBO ────────────────────────────────────────────────────────────
    if solver_mode in ("qubo", "both"):
        if not QUBO_AVAILABLE:
            result["qubo"] = {
                "error": "QUBO solver unavailable — install dimod and dwave-neal"
            }
        else:
            state_q = SimulationState(sc, res_pool)
            qubo = QUBOSolver(num_reads=req.qubo_reads, seed=req.seed)
            plan_q = qubo.solve(state_q)
            result["qubo"] = _plan_to_dict(plan_q, state_q)

    return result


@app.post("/api/inject")
def inject_emergency(req: InjectRequest):
    """
    Inject a dynamic emergency into a running scenario and re-solve with
    both Greedy and QUBO (if available).
    """
    key = req.scenario.lower()
    if key not in SCENARIO_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown scenario '{req.scenario}'")

    if req.location_id not in LOCATIONS:
        raise HTTPException(status_code=400, detail=f"Unknown location '{req.location_id}'")

    sc: Scenario = SCENARIO_REGISTRY[key](seed=req.seed)

    new_em = Emergency(
        id=f"DYN_{int(time.time())}",
        location_id=req.location_id,
        emergency_type=req.emergency_type,
        severity=req.severity,
        people_affected=req.people_affected,
        ambulances_required=req.ambulances_required,
        rescue_teams_required=req.rescue_teams_required,
        medical_supplies_required=req.medical_supplies_required,
        medical_personnel_required=req.medical_personnel_required,
        description=f"Dynamically injected {req.emergency_type} at {LOCATIONS[req.location_id].name}",
        reported_at_minute=0.0,
    )
    sc.emergencies.append(new_em)

    state_g = SimulationState(sc, DEFAULT_RESOURCES)
    greedy = GreedyBaselineSolver()
    plan_g = greedy.solve(state_g)

    result = {
        "injected_emergency": _emergency_to_dict(new_em),
        "all_emergencies": [_emergency_to_dict(e) for e in sc.emergencies],
        "greedy": _plan_to_dict(plan_g, state_g),
    }

    if QUBO_AVAILABLE:
        state_q = SimulationState(sc, DEFAULT_RESOURCES)
        qubo = QUBOSolver(num_reads=300, seed=req.seed)
        plan_q = qubo.solve(state_q)
        result["qubo"] = _plan_to_dict(plan_q, state_q)

    return result
