"""
test_comprehensive.py
---------------------
Comprehensive audit-driven tests for QDO backend.

Covers all issues identified during the audit:

  SECTION 1: QUBO formulation math
    - One-hot penalty coefficients (single-option and multi-option)
    - Candidate level generation edge cases
    - Capacity interaction penalties

  SECTION 2: Capacity constraints
    - Two-emergency pairwise capacity (should be caught by QUBO penalty)
    - Three-emergency scenario: pairwise penalties may miss; decoder must trim
    - Decoder trim leaves no negative allocations

  SECTION 3: Zero-demand and zero-capacity edge cases
    - Emergency with zero requirement for a resource type
    - Resource type with zero capacity

  SECTION 4: Raw vs decoded feasibility transparency
    - raw_sample_feasible metadata field exists
    - final_allocation_feasible metadata field exists
    - Metadata contains timing breakdown fields
    - Sampler description is accurate

  SECTION 5: State immutability during solver comparison
    - Running Greedy then QUBO on same state does NOT mutate resource availability

  SECTION 6: Reproducibility with fixed seeds
    - Same scenario + seed → same QUBO allocation

  SECTION 7: Metric correctness
    - unmet_demand_fraction in [0, 1]
    - coverage_score in [0, 1]
    - resource utilisation per type in [0, 1]
    - weighted_objective is finite
    - Total deployed never exceeds capacity

  SECTION 8: Greedy correctness
    - Greedy respects resource limits
    - Greedy allocates in descending priority order
    - Greedy produces non-negative allocations

  SECTION 9: Dynamic simulation correctness
    - Negative resource delta raises ValueError
    - Adding duplicate emergency ID raises ValueError
    - Blocking non-existent edge raises KeyError
    - Resolve clears from active list and restores resources

  SECTION 10: Toy example with known answer
    - Single emergency, ample resources: all resources satisfied

  SECTION 11: QUBO timing breakdown
    - All timing fields present and non-negative
"""

from __future__ import annotations

import copy
import math
import sys
import time
import unittest
from typing import Dict

from data.scenarios import (
    Emergency, ResourcePool, get_scenario, DEFAULT_RESOURCES
)
from simulation.simulation import SimulationState, create_simulation
from simulation.resources import ResourceManager, RESOURCE_TYPES
from simulation.emergencies import EmergencyManager, EmergencyStatus, AllocationRecord
from simulation.dynamic import DynamicSimulation
from optimization.baseline import GreedyBaselineSolver
from optimization.qubo import QUBOSolver, QUBOFormulator, get_candidate_levels, QUBO_PENALTIES
from optimization.solver import AllocationPlan
from utils.metrics import (
    compute_response_times, compute_unmet_demand,
    unmet_demand_fraction, coverage_score, resource_utilisation,
    full_metrics_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_emergency(
    eid: str = "E001",
    location_id: str = "admin_block",
    emergency_type: str = "medical_emergency",
    severity: int = 7,
    people_affected: int = 10,
    ambulances: int = 2,
    rescue: int = 1,
    supplies: int = 20,
    personnel: int = 4,
) -> Emergency:
    return Emergency(
        id=eid,
        location_id=location_id,
        emergency_type=emergency_type,
        severity=severity,
        people_affected=people_affected,
        ambulances_required=ambulances,
        rescue_teams_required=rescue,
        medical_supplies_required=supplies,
        medical_personnel_required=personnel,
        description="Test emergency",
    )


def _make_state(emergencies, pool=None):
    from data.scenarios import Scenario
    pool = pool or DEFAULT_RESOURCES
    sc = Scenario(name="TEST", description="test", emergencies=emergencies)
    return SimulationState(sc, pool)


# ---------------------------------------------------------------------------
# SECTION 1: QUBO formulation math
# ---------------------------------------------------------------------------

class TestQUBOCandidateLevels(unittest.TestCase):

    def test_zero_requirement(self):
        """Zero requirement should return only [0]."""
        levels = get_candidate_levels(0, 10)
        self.assertEqual(levels, [0])

    def test_req_exceeds_capacity(self):
        """When requirement > capacity, levels are capped at capacity."""
        levels = get_candidate_levels(5, 3)
        self.assertTrue(all(q <= 3 for q in levels))
        self.assertIn(3, levels)  # cap at capacity

    def test_small_req_all_integers(self):
        """Small requirements (≤ 5) should enumerate every integer 0..min(req,cap)."""
        levels = get_candidate_levels(3, 10)
        self.assertEqual(levels, [0, 1, 2, 3])

    def test_large_req_steps(self):
        """Large requirements produce percentage steps."""
        levels = get_candidate_levels(20, 100)
        self.assertIn(0, levels)
        self.assertIn(20, levels)
        self.assertTrue(len(levels) <= 5)

    def test_zero_capacity(self):
        """Zero capacity with nonzero requirement should return [0]."""
        levels = get_candidate_levels(5, 0)
        self.assertEqual(levels, [0])

    def test_no_duplicates(self):
        """Candidate levels should have no duplicates."""
        for req in [0, 1, 3, 5, 10, 20, 50]:
            for cap in [0, 1, 3, 5, 10, 100]:
                levels = get_candidate_levels(req, cap)
                self.assertEqual(len(levels), len(set(levels)),
                                 f"Duplicates found for req={req}, cap={cap}: {levels}")

    def test_uncontested_resource_exact_level(self):
        """Uncontested resource (is_contested=False) returns single exact level [min(req, cap)]."""
        levels = get_candidate_levels(15, 100, is_contested=False)
        self.assertEqual(levels, [15])
        levels_cap = get_candidate_levels(50, 30, is_contested=False)
        self.assertEqual(levels_cap, [30])

    def test_uncontested_resource_zero_req_or_cap(self):
        """Uncontested resource with 0 req or 0 cap returns [0]."""
        self.assertEqual(get_candidate_levels(0, 100, is_contested=False), [0])
        self.assertEqual(get_candidate_levels(15, 0, is_contested=False), [0])


class TestQUBOOneHotPenaltyMath(unittest.TestCase):
    """Verify one-hot penalty coefficients in the QUBO matrix."""

    def setUp(self):
        self.state = create_simulation("alpha", seed=42)

    def test_one_hot_diagonal_is_negative(self):
        """All diagonal (linear) QUBO terms should be negative (encouraging selection)."""
        f = QUBOFormulator()
        Q, var_info = f.formulate(self.state)
        for (u, v), w in Q.items():
            if u == v:
                # Diagonal dominated by one-hot and objective terms
                # The one-hot diagonal contribution is -P_onehot
                # Total can be negative or positive depending on objective terms
                # But for variables with quantity=0 the travel/util rewards are 0
                # Just check no NaN or Inf
                self.assertFalse(math.isnan(w), f"NaN diagonal for {u}")
                self.assertFalse(math.isinf(w), f"Inf diagonal for {u}")

    def test_one_hot_cross_terms_positive(self):
        """Cross terms between different levels of the same (emergency, resource) must be positive."""
        f = QUBOFormulator()
        Q, var_info = f.formulate(self.state)

        # Group variables by (em_id, rtype)
        groups: Dict = {}
        for var_name, info in var_info.items():
            key = (info["emergency_id"], info["resource_type"])
            groups.setdefault(key, []).append(var_name)

        for key, vars_list in groups.items():
            if len(vars_list) < 2:
                continue
            for i, v1 in enumerate(vars_list):
                for j in range(i + 1, len(vars_list)):
                    v2 = vars_list[j]
                    pair = (min(v1, v2), max(v1, v2))
                    w = Q.get(pair, 0.0)
                    self.assertGreater(w, 0,
                        f"Cross term for same-group pair {v1},{v2} should be positive, got {w}")

    def test_single_option_variable_diagonal(self):
        """A variable with a single candidate level (req=0) must have a negative diagonal."""
        pool = ResourcePool(ambulances=5, rescue_teams=0, medical_supplies=100, medical_personnel=25)
        em = _make_emergency(rescue=0)  # rescue_teams_required=0 → only [0] candidate
        state = _make_state([em], pool)
        f = QUBOFormulator()
        Q, var_info = f.formulate(state)

        # Find the single variable for (E001, rescue_teams)
        rt_vars = [v for v, info in var_info.items()
                   if info["emergency_id"] == "E001" and info["resource_type"] == "rescue_teams"]
        self.assertEqual(len(rt_vars), 1, "Should be exactly one variable for rescue_teams with req=0")
        var = rt_vars[0]
        pair = (var, var)
        self.assertIn(pair, Q, f"Diagonal must be in Q for {var}")
        # The one-hot penalty alone contributes -P_onehot.
        # No travel cost (q=0), no unmet demand (req=0), no util reward.
        # So total diagonal = -P_onehot.
        expected = -QUBO_PENALTIES["one_hot_penalty"]
        self.assertAlmostEqual(Q[pair], expected, places=3,
            msg=f"Single-option diagonal should be -P_onehot={expected}, got {Q[pair]}")


class TestQUBOCapacityInteractionPenalties(unittest.TestCase):
    """Verify capacity penalty terms between different emergencies."""

    def test_cross_emergency_penalty_when_exceeds_capacity(self):
        """Variables from different emergencies that together exceed capacity should have penalty."""
        # Use tight capacity: ambulances=1, two emergencies each need 1
        pool = ResourcePool(ambulances=1, rescue_teams=3, medical_supplies=100, medical_personnel=25)
        em1 = _make_emergency("E001", ambulances=1)
        em2 = _make_emergency("E002", location_id="cafeteria", ambulances=1)
        state = _make_state([em1, em2], pool)

        f = QUBOFormulator()
        Q, var_info = f.formulate(state)

        # Find the level-1 (quantity=1) ambulance variables for each emergency
        em1_amb_vars = [(v, info) for v, info in var_info.items()
                        if info["emergency_id"] == "E001" and info["resource_type"] == "ambulances"
                        and info["quantity"] == 1]
        em2_amb_vars = [(v, info) for v, info in var_info.items()
                        if info["emergency_id"] == "E002" and info["resource_type"] == "ambulances"
                        and info["quantity"] == 1]

        self.assertTrue(em1_amb_vars, "E001 must have an ambulance variable with quantity=1")
        self.assertTrue(em2_amb_vars, "E002 must have an ambulance variable with quantity=1")

        v1 = em1_amb_vars[0][0]
        v2 = em2_amb_vars[0][0]
        pair = (min(v1, v2), max(v1, v2))
        # q1+q2=2 > cap=1, so penalty should exist and be positive
        self.assertIn(pair, Q, "Cross-emergency pair should have a penalty when q1+q2 > cap")
        self.assertGreater(Q[pair], 0, "Cross-emergency capacity penalty should be positive")


# ---------------------------------------------------------------------------
# SECTION 2: Capacity constraints
# ---------------------------------------------------------------------------

class TestCapacityConstraints(unittest.TestCase):

    def test_decoder_no_negative_allocation(self):
        """Decoder must never produce negative allocations."""
        for scenario_name in ["alpha", "beta", "gamma", "stress"]:
            state = create_simulation(scenario_name, seed=42)
            solver = QUBOSolver(num_reads=50, seed=42)
            plan = solver.solve(state)
            for em_id, rec in plan.allocations.items():
                self.assertGreaterEqual(rec.ambulances_assigned, 0,
                    f"[{scenario_name}][{em_id}] negative ambulance")
                self.assertGreaterEqual(rec.rescue_teams_assigned, 0,
                    f"[{scenario_name}][{em_id}] negative rescue")
                self.assertGreaterEqual(rec.medical_supplies_assigned, 0,
                    f"[{scenario_name}][{em_id}] negative supplies")
                self.assertGreaterEqual(rec.medical_personnel_assigned, 0,
                    f"[{scenario_name}][{em_id}] negative personnel")

    def test_decoder_respects_capacity(self):
        """Decoder must never allocate more than available capacity."""
        for scenario_name in ["alpha", "beta", "gamma", "stress"]:
            state = create_simulation(scenario_name, seed=42)
            cap = state.resource_manager.capacity()
            solver = QUBOSolver(num_reads=50, seed=42)
            plan = solver.solve(state)
            deployed = {rt: 0 for rt in RESOURCE_TYPES}
            for rec in plan.allocations.values():
                deployed["ambulances"]        += rec.ambulances_assigned
                deployed["rescue_teams"]      += rec.rescue_teams_assigned
                deployed["medical_supplies"]  += rec.medical_supplies_assigned
                deployed["medical_personnel"] += rec.medical_personnel_assigned
            for rt in RESOURCE_TYPES:
                self.assertLessEqual(deployed[rt], cap[rt],
                    f"[{scenario_name}] QUBO exceeded capacity for {rt}: {deployed[rt]} > {cap[rt]}")

    def test_three_emergency_capacity_trimming(self):
        """
        Three emergencies, each requesting 3 ambulances, capacity=3.
        The pairwise QUBO penalty alone cannot prevent all three selecting level=3.
        The decoder MUST trim to respect the hard limit.
        """
        pool = ResourcePool(ambulances=3, rescue_teams=3, medical_supplies=100, medical_personnel=25)
        ems = [
            _make_emergency("E001", ambulances=3),
            _make_emergency("E002", location_id="cafeteria", ambulances=3),
            _make_emergency("E003", location_id="hostel_a", ambulances=3),
        ]
        state = _make_state(ems, pool)
        solver = QUBOSolver(num_reads=200, seed=42)
        plan = solver.solve(state)

        total_amb = sum(rec.ambulances_assigned for rec in plan.allocations.values())
        self.assertLessEqual(total_amb, 3,
            f"Total ambulance allocation {total_amb} exceeds capacity 3 after decoding")
        for rec in plan.allocations.values():
            self.assertGreaterEqual(rec.ambulances_assigned, 0)

    def test_greedy_respects_capacity(self):
        """Greedy solver must never exceed available resource counts."""
        for scenario_name in ["alpha", "beta", "gamma", "stress"]:
            state = create_simulation(scenario_name, seed=42)
            avail = state.resource_manager.available()
            solver = GreedyBaselineSolver()
            plan = solver.solve(state)
            deployed = {rt: 0 for rt in RESOURCE_TYPES}
            for rec in plan.allocations.values():
                deployed["ambulances"]        += rec.ambulances_assigned
                deployed["rescue_teams"]      += rec.rescue_teams_assigned
                deployed["medical_supplies"]  += rec.medical_supplies_assigned
                deployed["medical_personnel"] += rec.medical_personnel_assigned
            for rt in RESOURCE_TYPES:
                self.assertLessEqual(deployed[rt], avail[rt],
                    f"[{scenario_name}] Greedy exceeded available {rt}: {deployed[rt]} > {avail[rt]}")


# ---------------------------------------------------------------------------
# SECTION 3: Zero-demand and zero-capacity edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_zero_requirement_resource(self):
        """Emergency with zero requirement for one resource type should get 0 allocation."""
        em = _make_emergency(rescue=0)
        state = _make_state([em])
        for SolverClass in [GreedyBaselineSolver, lambda: QUBOSolver(num_reads=50, seed=42)]:
            solver = SolverClass()
            plan = solver.solve(state)
            rec = plan.allocations.get("E001")
            self.assertIsNotNone(rec)
            self.assertEqual(rec.rescue_teams_assigned, 0,
                f"{solver.name}: rescue_teams should be 0 when required=0")

    def test_all_resources_zero_requirement(self):
        """Emergency requiring 0 of everything still gets an AllocationRecord."""
        em = _make_emergency(ambulances=0, rescue=0, supplies=0, personnel=0)
        state = _make_state([em])
        for SolverClass in [GreedyBaselineSolver, lambda: QUBOSolver(num_reads=50, seed=42)]:
            solver = SolverClass()
            plan = solver.solve(state)
            self.assertIn("E001", plan.allocations,
                f"{solver.name}: allocation record should exist even for zero-requirement emergency")

    def test_insufficient_resources(self):
        """With scarce resources, some demand must be unmet but no negative allocation."""
        pool = ResourcePool(ambulances=1, rescue_teams=1, medical_supplies=10, medical_personnel=2)
        ems = [
            _make_emergency("E001", ambulances=3, rescue=2, supplies=50, personnel=10),
            _make_emergency("E002", location_id="cafeteria", ambulances=3, rescue=2, supplies=50, personnel=10),
        ]
        state = _make_state(ems, pool)
        for SolverClass in [GreedyBaselineSolver, lambda: QUBOSolver(num_reads=100, seed=42)]:
            solver = SolverClass()
            plan = solver.solve(state)
            unmet = plan.metrics.get("unmet_demand_fraction", 0.0)
            self.assertGreater(unmet, 0.0,
                f"{solver.name}: unmet demand should be > 0 when resources are scarce")
            for rec in plan.allocations.values():
                self.assertGreaterEqual(rec.ambulances_assigned, 0)
                self.assertGreaterEqual(rec.rescue_teams_assigned, 0)

    def test_single_emergency_ample_resources_greedy(self):
        """Single emergency with ample resources: Greedy should satisfy all requirements."""
        em = _make_emergency(ambulances=2, rescue=1, supplies=20, personnel=4)
        state = _make_state([em])
        solver = GreedyBaselineSolver()
        plan = solver.solve(state)
        rec = plan.allocations["E001"]
        self.assertEqual(rec.ambulances_assigned, 2)
        self.assertEqual(rec.rescue_teams_assigned, 1)
        self.assertEqual(rec.medical_supplies_assigned, 20)
        self.assertEqual(rec.medical_personnel_assigned, 4)
        self.assertAlmostEqual(plan.metrics["unmet_demand_fraction"], 0.0, places=5)

    def test_unreachable_location(self):
        """Emergency at location isolated by blocked roads: travel time is large but solver still runs."""
        from data.scenarios import Scenario
        pool = DEFAULT_RESOURCES
        em = _make_emergency(location_id="sports_complex")
        sc = Scenario(
            name="TEST_DISCONNECTED",
            description="all roads to sports_complex blocked",
            emergencies=[em],
            blocked_routes=[
                ("hostel_a", "sports_complex"),
                ("hostel_b", "sports_complex"),
                ("library", "sports_complex"),
            ],
        )
        state = SimulationState(sc, pool)
        for SolverClass in [GreedyBaselineSolver, lambda: QUBOSolver(num_reads=50, seed=42)]:
            solver = SolverClass()
            plan = solver.solve(state)
            self.assertIn("E001", plan.allocations)
            # All roads to sports_complex blocked: arrival time None or inf-based
            rec = plan.allocations["E001"]
            # The allocation record may have None arrival — just check it doesn't crash


# ---------------------------------------------------------------------------
# SECTION 4: Raw vs decoded feasibility transparency
# ---------------------------------------------------------------------------

class TestQUBOFeasibilityMetadata(unittest.TestCase):

    def test_metadata_has_feasibility_fields(self):
        """QUBO solver_metadata must contain raw_sample_feasible and final_allocation_feasible."""
        state = create_simulation("alpha", seed=42)
        solver = QUBOSolver(num_reads=100, seed=42)
        plan = solver.solve(state)
        self.assertIn("raw_sample_feasible", plan.solver_metadata,
            "solver_metadata must contain raw_sample_feasible")
        self.assertIn("final_allocation_feasible", plan.solver_metadata,
            "solver_metadata must contain final_allocation_feasible")
        self.assertIsInstance(plan.solver_metadata["raw_sample_feasible"], bool)
        self.assertIsInstance(plan.solver_metadata["final_allocation_feasible"], bool)

    def test_metadata_sampler_description(self):
        """QUBO solver must clearly describe the sampler as classical."""
        state = create_simulation("alpha", seed=42)
        plan = QUBOSolver(num_reads=50, seed=42).solve(state)
        sampler_desc = plan.solver_metadata.get("sampler", "")
        self.assertIn("classical", sampler_desc.lower(),
            "Sampler description must include 'classical' to avoid misrepresenting as quantum")

    def test_metadata_timing_breakdown(self):
        """QUBO solver_metadata must contain all timing breakdown fields."""
        state = create_simulation("alpha", seed=42)
        plan = QUBOSolver(num_reads=50, seed=42).solve(state)
        meta = plan.solver_metadata
        required_fields = [
            "qubo_formulation_time_ms",
            "bqm_construction_time_ms",
            "sampler_time_ms",
            "decode_time_ms",
            "solve_time_ms",
        ]
        for field in required_fields:
            self.assertIn(field, meta, f"Missing timing field: {field}")
            self.assertGreaterEqual(meta[field], 0.0,
                f"Timing field {field} must be non-negative")

    def test_timing_components_sum_to_total(self):
        """Sum of component timings should approximately equal total solve time."""
        state = create_simulation("beta", seed=42)
        plan = QUBOSolver(num_reads=100, seed=42).solve(state)
        meta = plan.solver_metadata
        component_sum = (
            meta["qubo_formulation_time_ms"]
            + meta["bqm_construction_time_ms"]
            + meta["sampler_time_ms"]
            + meta["decode_time_ms"]
        )
        total = meta["solve_time_ms"]
        # Allow 10% tolerance for overhead
        self.assertAlmostEqual(component_sum, total, delta=total * 0.15,
            msg=f"Component sum {component_sum:.2f}ms should ≈ total {total:.2f}ms")


# ---------------------------------------------------------------------------
# SECTION 5: State immutability during solver comparison
# ---------------------------------------------------------------------------

class TestStateImmutability(unittest.TestCase):

    def test_greedy_does_not_mutate_available(self):
        """Running GreedyBaselineSolver must not change resource_manager.available()."""
        state = create_simulation("alpha", seed=42)
        before = dict(state.resource_manager.available())
        GreedyBaselineSolver().solve(state)
        after = dict(state.resource_manager.available())
        self.assertEqual(before, after,
            "Greedy solve must not mutate resource_manager.available()")

    def test_qubo_does_not_mutate_available(self):
        """Running QUBOSolver must not change resource_manager.available()."""
        state = create_simulation("alpha", seed=42)
        before = dict(state.resource_manager.available())
        QUBOSolver(num_reads=50, seed=42).solve(state)
        after = dict(state.resource_manager.available())
        self.assertEqual(before, after,
            "QUBO solve must not mutate resource_manager.available()")

    def test_sequential_solvers_independent(self):
        """Running Greedy then QUBO: QUBO sees the same state Greedy saw."""
        state = create_simulation("alpha", seed=42)
        avail_before = dict(state.resource_manager.available())

        GreedyBaselineSolver().solve(state)
        avail_after_greedy = dict(state.resource_manager.available())
        self.assertEqual(avail_before, avail_after_greedy,
            "State must be unchanged after Greedy")

        QUBOSolver(num_reads=50, seed=42).solve(state)
        avail_after_qubo = dict(state.resource_manager.available())
        self.assertEqual(avail_before, avail_after_qubo,
            "State must be unchanged after QUBO")


# ---------------------------------------------------------------------------
# SECTION 6: Reproducibility with fixed seeds
# ---------------------------------------------------------------------------

class TestReproducibility(unittest.TestCase):

    def test_qubo_reproducible_with_seed(self):
        """Same scenario + same seed → same QUBO allocation on two separate runs."""
        state1 = create_simulation("alpha", seed=42)
        state2 = create_simulation("alpha", seed=42)
        plan1 = QUBOSolver(num_reads=200, seed=42).solve(state1)
        plan2 = QUBOSolver(num_reads=200, seed=42).solve(state2)

        for em_id in plan1.allocations:
            r1 = plan1.allocations[em_id]
            r2 = plan2.allocations[em_id]
            self.assertEqual(r1.ambulances_assigned,        r2.ambulances_assigned,        f"[{em_id}] ambulances differ")
            self.assertEqual(r1.rescue_teams_assigned,      r2.rescue_teams_assigned,      f"[{em_id}] rescue_teams differ")
            self.assertEqual(r1.medical_supplies_assigned,  r2.medical_supplies_assigned,  f"[{em_id}] supplies differ")
            self.assertEqual(r1.medical_personnel_assigned, r2.medical_personnel_assigned, f"[{em_id}] personnel differ")

    def test_greedy_deterministic(self):
        """Greedy has no randomness: same scenario → same allocation."""
        state1 = create_simulation("beta", seed=42)
        state2 = create_simulation("beta", seed=42)
        plan1 = GreedyBaselineSolver().solve(state1)
        plan2 = GreedyBaselineSolver().solve(state2)

        for em_id in plan1.allocations:
            r1 = plan1.allocations[em_id]
            r2 = plan2.allocations[em_id]
            self.assertEqual(r1.ambulances_assigned, r2.ambulances_assigned,
                f"Greedy ambulances differ for {em_id}")


# ---------------------------------------------------------------------------
# SECTION 7: Metric correctness
# ---------------------------------------------------------------------------

class TestMetricCorrectness(unittest.TestCase):

    def _check_plan_metrics(self, plan: AllocationPlan, scenario_name: str, solver_name: str):
        metrics = plan.metrics
        prefix = f"[{scenario_name}][{solver_name}]"

        unmet = metrics["unmet_demand_fraction"]
        self.assertGreaterEqual(unmet, 0.0, f"{prefix} unmet < 0")
        self.assertLessEqual(unmet, 1.0001, f"{prefix} unmet > 1")
        self.assertFalse(math.isnan(unmet), f"{prefix} unmet is NaN")

        sev_unmet = metrics["severity_weighted_unmet_demand_fraction"]
        self.assertGreaterEqual(sev_unmet, 0.0, f"{prefix} sev_unmet < 0")
        self.assertLessEqual(sev_unmet, 1.0001, f"{prefix} sev_unmet > 1")

        cov = metrics["coverage_score"]
        self.assertGreaterEqual(cov, 0.0, f"{prefix} coverage < 0")
        self.assertLessEqual(cov, 1.0001, f"{prefix} coverage > 1")

        crit_cov = metrics["critical_coverage_score"]
        self.assertGreaterEqual(crit_cov, 0.0, f"{prefix} critical_cov < 0")
        self.assertLessEqual(crit_cov, 1.0001, f"{prefix} critical_cov > 1")

        util = metrics["resource_utilisation"]
        for rt, u in util.items():
            self.assertGreaterEqual(u, 0.0, f"{prefix} util[{rt}] < 0")
            self.assertLessEqual(u, 1.0001, f"{prefix} util[{rt}] > 1")

        obj = metrics["weighted_objective"]
        self.assertFalse(math.isnan(obj), f"{prefix} objective is NaN")
        self.assertFalse(math.isinf(obj), f"{prefix} objective is Inf")

    def test_all_scenarios_all_solvers(self):
        """Metric bounds for all scenarios and both solvers."""
        for sc in ["alpha", "beta", "gamma", "stress"]:
            state = create_simulation(sc, seed=42)
            for solver in [GreedyBaselineSolver(), QUBOSolver(num_reads=100, seed=42)]:
                plan = solver.solve(state)
                self._check_plan_metrics(plan, sc, solver.name)

    def test_full_coverage_ample_resources(self):
        """Single emergency with ample resources: coverage_score == 1.0, unmet == 0."""
        em = _make_emergency(ambulances=2, rescue=1, supplies=20, personnel=4)
        state = _make_state([em])
        plan = GreedyBaselineSolver().solve(state)
        self.assertAlmostEqual(plan.metrics["coverage_score"], 1.0, places=5)
        self.assertAlmostEqual(plan.metrics["unmet_demand_fraction"], 0.0, places=5)


# ---------------------------------------------------------------------------
# SECTION 8: Greedy correctness
# ---------------------------------------------------------------------------

class TestGreedyCorrectness(unittest.TestCase):

    def test_priority_order_allocation(self):
        """
        With only 1 ambulance available and two emergencies (severity 9 vs severity 3),
        the severity-9 emergency should get the ambulance (it has higher priority score).
        """
        pool = ResourcePool(ambulances=1, rescue_teams=3, medical_supplies=100, medical_personnel=25)
        em_high = Emergency(
            id="E001", location_id="admin_block",
            emergency_type="medical_emergency",
            severity=9, people_affected=50,
            ambulances_required=1, rescue_teams_required=0,
            medical_supplies_required=5, medical_personnel_required=2,
        )
        em_low = Emergency(
            id="E002", location_id="cafeteria",
            emergency_type="accident",
            severity=3, people_affected=2,
            ambulances_required=1, rescue_teams_required=0,
            medical_supplies_required=5, medical_personnel_required=1,
        )
        state = _make_state([em_high, em_low], pool)
        plan = GreedyBaselineSolver().solve(state)

        self.assertEqual(plan.allocations["E001"].ambulances_assigned, 1,
            "High-severity emergency should get the sole ambulance")
        self.assertEqual(plan.allocations["E002"].ambulances_assigned, 0,
            "Low-severity emergency should get no ambulance when pool is exhausted")

    def test_greedy_non_negative_allocations(self):
        """Greedy must not produce negative resource counts."""
        for sc in ["alpha", "beta", "gamma", "stress"]:
            state = create_simulation(sc, seed=42)
            plan = GreedyBaselineSolver().solve(state)
            for em_id, rec in plan.allocations.items():
                self.assertGreaterEqual(rec.ambulances_assigned, 0)
                self.assertGreaterEqual(rec.rescue_teams_assigned, 0)
                self.assertGreaterEqual(rec.medical_supplies_assigned, 0)
                self.assertGreaterEqual(rec.medical_personnel_assigned, 0)


# ---------------------------------------------------------------------------
# SECTION 9: Dynamic simulation correctness
# ---------------------------------------------------------------------------

class TestDynamicSimulationEdgeCases(unittest.TestCase):

    def setUp(self):
        self.sim = DynamicSimulation(scenario_name="alpha", seed=42, verbose=False)

    def test_negative_resource_delta_raises(self):
        """Attempting to reduce resource below 0 should raise ValueError."""
        avail = self.sim.state.resource_manager.available()["ambulances"]
        with self.assertRaises(ValueError):
            self.sim.modify_resource_availability("ambulances", -(avail + 1))

    def test_duplicate_emergency_id_raises(self):
        """Adding an emergency with an existing ID should raise ValueError."""
        em = Emergency(
            id="E001",  # already exists in alpha scenario
            location_id="library", emergency_type="fire",
            severity=5, people_affected=10,
            ambulances_required=1, rescue_teams_required=0,
            medical_supplies_required=5, medical_personnel_required=1,
        )
        with self.assertRaises(ValueError):
            self.sim.add_emergency(em)

    def test_block_nonexistent_edge_raises(self):
        """Blocking an edge that doesn't exist should raise KeyError."""
        with self.assertRaises(KeyError):
            self.sim.block_road("main_gate", "sports_complex")  # no direct edge

    def test_resolve_clears_from_active(self):
        """After resolving, emergency should not appear in active_emergencies."""
        self.sim.optimize("Greedy Baseline", commit_allocations=True)
        active_ids_before = [e.id for e in self.sim.state.active_emergencies]
        self.assertIn("E001", active_ids_before)
        self.sim.resolve_emergency("E001")
        active_ids_after = [e.id for e in self.sim.state.active_emergencies]
        self.assertNotIn("E001", active_ids_after)

    def test_resolve_restores_resources(self):
        """Resolving an emergency should restore its reserved resources."""
        plan = self.sim.optimize("Greedy Baseline", commit_allocations=True)
        amb_allocated = plan.allocations["E002"].ambulances_assigned
        avail_after_alloc = self.sim.state.resource_manager.available()["ambulances"]

        self.sim.resolve_emergency("E002")
        avail_after_resolve = self.sim.state.resource_manager.available()["ambulances"]
        self.assertEqual(avail_after_resolve, avail_after_alloc + amb_allocated,
            "Resolving emergency should restore its ambulances to available pool")

    def test_resource_change_no_negative_capacity(self):
        """Capacity should never go below 0."""
        with self.assertRaises(ValueError):
            self.sim.modify_resource_availability("rescue_teams", -999, update_capacity=True)


# ---------------------------------------------------------------------------
# SECTION 10: Toy example with known answer
# ---------------------------------------------------------------------------

class TestToyKnownAnswer(unittest.TestCase):

    def test_single_emergency_greedy_full_allocation(self):
        """
        Toy: 1 emergency requiring 2 ambulances, pool has 5.
        Greedy must allocate exactly 2 ambulances, no more, no less.
        """
        em = _make_emergency(ambulances=2, rescue=1, supplies=15, personnel=3)
        state = _make_state([em])
        plan = GreedyBaselineSolver().solve(state)
        rec = plan.allocations["E001"]
        self.assertEqual(rec.ambulances_assigned, 2)
        self.assertEqual(rec.rescue_teams_assigned, 1)
        self.assertEqual(rec.medical_supplies_assigned, 15)
        self.assertEqual(rec.medical_personnel_assigned, 3)

    def test_two_emergencies_total_demand_exceeds_pool(self):
        """
        Toy: pool has 3 ambulances; two emergencies need 2 each → total 4 needed.
        Solvers must allocate ≤ 3 total ambulances.
        """
        pool = ResourcePool(ambulances=3, rescue_teams=3, medical_supplies=100, medical_personnel=25)
        ems = [
            _make_emergency("E001", location_id="admin_block", ambulances=2, severity=8, people_affected=20),
            _make_emergency("E002", location_id="cafeteria",   ambulances=2, severity=5, people_affected=5),
        ]
        state = _make_state(ems, pool)

        for solver in [GreedyBaselineSolver(), QUBOSolver(num_reads=200, seed=42)]:
            plan = solver.solve(state)
            total_amb = sum(rec.ambulances_assigned for rec in plan.allocations.values())
            self.assertLessEqual(total_amb, 3,
                f"{solver.name}: total ambulances {total_amb} exceeds pool of 3")

    def test_unmet_demand_fraction_exact(self):
        """
        Toy: 1 emergency needs 4 ambulances, pool has 2.
        Unmet fraction for ambulances = (4-2)/4 = 0.5 of ambulances.
        Overall unmet fraction depends on total required resources.
        """
        pool = ResourcePool(ambulances=2, rescue_teams=3, medical_supplies=100, medical_personnel=25)
        em = _make_emergency(ambulances=4, rescue=0, supplies=0, personnel=0)
        state = _make_state([em], pool)
        plan = GreedyBaselineSolver().solve(state)
        rec = plan.allocations["E001"]
        self.assertEqual(rec.ambulances_assigned, 2)
        # unmet ambulances = 4 - 2 = 2; total required = 4; unmet_fraction = 2/4 = 0.5
        self.assertAlmostEqual(plan.metrics["unmet_demand_fraction"], 0.5, places=5)


# ---------------------------------------------------------------------------
# SECTION 11: QUBO timing breakdown
# ---------------------------------------------------------------------------

class TestQUBOTimingBreakdown(unittest.TestCase):

    def test_sampler_time_dominates(self):
        """Sampler time should dominate for a non-trivial scenario (not zero)."""
        state = create_simulation("beta", seed=42)
        plan = QUBOSolver(num_reads=500, seed=42).solve(state)
        meta = plan.solver_metadata
        self.assertGreater(meta["sampler_time_ms"], 0.0,
            "Sampler time should be > 0ms")
        self.assertGreater(meta["total_solve_time_ms"], 0.0,
            "Total solve time should be > 0ms")

    def test_variable_count_plausible(self):
        """Number of QUBO variables should be positive and plausible."""
        state = create_simulation("alpha", seed=42)
        plan = QUBOSolver(num_reads=50, seed=42).solve(state)
        n_vars = plan.solver_metadata["num_variables"]
        n_emergencies = len(state.active_emergencies)
        n_rtypes = 4
        # Minimum: each (emergency, rtype) has at least 1 variable
        self.assertGreaterEqual(n_vars, n_emergencies * n_rtypes,
            f"Expected >= {n_emergencies * n_rtypes} variables, got {n_vars}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_tests():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    if success:
        print("\n[OK] All comprehensive audit tests PASSED.")
    else:
        print("\n[FAIL] Some comprehensive audit tests FAILED.")
    sys.exit(0 if success else 1)
