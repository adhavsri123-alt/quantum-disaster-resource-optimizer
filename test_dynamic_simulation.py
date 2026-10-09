"""
test_dynamic_simulation.py
---------------------------
Verification test suite for the Quantum Disaster Resource Optimizer (QDO)
Dynamic Simulation Layer.

Covers all 8 mandatory dynamic simulation tests:
  TEST 1: Add a new emergency.
  TEST 2: Block a road.
  TEST 3: Reopen the road.
  TEST 4: Reduce resource availability.
  TEST 5: Make resource available again.
  TEST 6: Resolve an emergency.
  TEST 7: Sequential dynamic events.
  TEST 8: Greedy and QUBO both work after dynamic changes.
"""

import math
import sys
import unittest

from data.scenarios import Emergency, get_scenario
from simulation.simulation import SimulationState
from simulation.emergencies import EmergencyStatus
from simulation.dynamic import DynamicSimulation, EventType


class TestDynamicSimulation(unittest.TestCase):

    def setUp(self):
        """Set up a standard initial dynamic simulation with scenario ALPHA."""
        self.sim = DynamicSimulation(scenario_name="alpha", seed=42, verbose=False)

    def test_01_add_new_emergency(self):
        """TEST 1: Add a new emergency dynamically while simulation is running."""
        initial_count = len(self.sim.state.active_emergencies)

        new_em = Emergency(
            id="E004",
            location_id="library",
            emergency_type="fire",
            severity=9,
            people_affected=30,
            ambulances_required=2,
            rescue_teams_required=1,
            medical_supplies_required=20,
            medical_personnel_required=4,
            description="Late-night electrical fire at Library",
            reported_at_minute=5.0,
        )

        self.sim.add_emergency(new_em, trigger_time=5.0)

        # 1. Verify emergency exists
        all_ids = [e.id for e in self.sim.state.emergency_manager.all_emergencies()]
        self.assertIn("E004", all_ids)

        # 2. Verify correct fields
        em_fetched = self.sim.state.emergency_manager.get_emergency("E004")
        self.assertEqual(em_fetched.location_id, "library")
        self.assertEqual(em_fetched.severity, 9)
        self.assertEqual(em_fetched.people_affected, 30)
        self.assertEqual(em_fetched.ambulances_required, 2)

        # 3. Verify active state count increased
        self.assertEqual(len(self.sim.state.active_emergencies), initial_count + 1)

        # 4. Verify optimization can run afterward
        plan = self.sim.optimize(solver_name="Greedy Baseline")
        self.assertIn("E004", plan.allocations)
        self.assertGreaterEqual(plan.allocations["E004"].ambulances_assigned, 0)

        # 5. Duplicate ID safety check
        with self.assertRaises(ValueError):
            self.sim.add_emergency(new_em)

    def test_02_block_road(self):
        """TEST 2: Block a road and verify shortest path/travel time updates."""
        # Initial travel time between admin_block and cafeteria
        initial_tt = self.sim.state.travel_time("admin_block", "cafeteria")
        self.assertNotEqual(initial_tt, math.inf)

        # Block direct road between admin_block and cafeteria
        self.sim.block_road("admin_block", "cafeteria")

        # 1. Edge should be marked blocked
        edge_data = self.sim.state.graph["admin_block"]["cafeteria"]
        self.assertTrue(edge_data["blocked"])

        # 2. Travel time should update to reflect alternative route
        new_tt = self.sim.state.travel_time("admin_block", "cafeteria")
        self.assertGreater(new_tt, initial_tt)
        self.assertNotEqual(new_tt, math.inf)  # Alternative route via academic_block exists

    def test_03_reopen_road(self):
        """TEST 3: Reopen a road and verify original travel time is restored."""
        initial_tt = self.sim.state.travel_time("admin_block", "cafeteria")

        self.sim.block_road("admin_block", "cafeteria")
        blocked_tt = self.sim.state.travel_time("admin_block", "cafeteria")
        self.assertGreater(blocked_tt, initial_tt)

        # Reopen road
        self.sim.reopen_road("admin_block", "cafeteria")

        # 1. Edge should no longer be marked blocked
        edge_data = self.sim.state.graph["admin_block"]["cafeteria"]
        self.assertFalse(edge_data["blocked"])

        # 2. Travel time restored to initial value
        reopened_tt = self.sim.state.travel_time("admin_block", "cafeteria")
        self.assertAlmostEqual(reopened_tt, initial_tt, places=5)

    def test_04_reduce_resource_availability(self):
        """TEST 4: Reduce resource availability and verify solver respects lower capacity."""
        initial_amb_avail = self.sim.state.resource_manager.available()["ambulances"]

        # Reduce ambulances by 3 (from 5 to 2)
        self.sim.modify_resource_availability("ambulances", -3)

        # 1. Available capacity decreases
        new_avail = self.sim.state.resource_manager.available()["ambulances"]
        self.assertEqual(new_avail, initial_amb_avail - 3)
        self.assertEqual(new_avail, 2)

        # 2. Optimization respects reduced capacity
        plan = self.sim.optimize(solver_name="Greedy Baseline")
        total_amb_assigned = sum(rec.ambulances_assigned for rec in plan.allocations.values())
        self.assertLessEqual(total_amb_assigned, 2)

        # 3. Prevent negative resource counts
        with self.assertRaises(ValueError):
            self.sim.modify_resource_availability("ambulances", -10)

    def test_05_make_resource_available_again(self):
        """TEST 5: Increase resource availability and verify solver uses new capacity."""
        # Reduce then restore
        self.sim.modify_resource_availability("ambulances", -3)
        self.assertEqual(self.sim.state.resource_manager.available()["ambulances"], 2)

        self.sim.modify_resource_availability("ambulances", +3)
        self.assertEqual(self.sim.state.resource_manager.available()["ambulances"], 5)

        # Solver can now allocate up to 5 ambulances
        plan = self.sim.optimize(solver_name="Greedy Baseline")
        total_amb_assigned = sum(rec.ambulances_assigned for rec in plan.allocations.values())
        self.assertGreater(total_amb_assigned, 2)
        self.assertLessEqual(total_amb_assigned, 5)

    def test_06_resolve_emergency(self):
        """TEST 6: Resolve an emergency, release resources, and verify state update."""
        # Initial optimization allocating resources
        plan = self.sim.optimize(solver_name="Greedy Baseline", commit_allocations=True)
        e001_amb = plan.allocations["E001"].ambulances_assigned

        avail_after_alloc = self.sim.state.resource_manager.available()["ambulances"]

        # Resolve E001
        self.sim.resolve_emergency("E001")

        # 1. Emergency status changes to RESOLVED
        status = self.sim.state.emergency_manager.get_status("E001")
        self.assertEqual(status, EmergencyStatus.RESOLVED)

        # 2. Resources released back to available pool
        avail_after_resolve = self.sim.state.resource_manager.available()["ambulances"]
        self.assertEqual(avail_after_resolve, avail_after_alloc + e001_amb)

        # 3. Resolved emergency excluded from active list
        active_ids = [e.id for e in self.sim.state.active_emergencies]
        self.assertNotIn("E001", active_ids)

    def test_07_sequential_dynamic_events(self):
        """TEST 7: Full sequential dynamic timeline sequence."""
        # T0: Initial scenario & baseline optimization
        plan_t0 = self.sim.optimize(solver_name="Greedy Baseline")
        self.assertIsNotNone(plan_t0)

        # T1: Add a new emergency E004
        new_em = Emergency(
            id="E004",
            location_id="sports_complex",
            emergency_type="flood_infrastructure",
            severity=10,
            people_affected=40,
            ambulances_required=2,
            rescue_teams_required=2,
            medical_supplies_required=30,
            medical_personnel_required=5,
            description="Flash flood at Sports Complex",
        )
        self.sim.add_emergency(new_em, trigger_time=2.0)

        # T2: Block road hostel_a <-> sports_complex
        self.sim.block_road("hostel_a", "sports_complex", trigger_time=3.0)

        # T3: Reduce ambulance availability (-1)
        self.sim.modify_resource_availability("ambulances", -1, trigger_time=4.0)

        # T4: Re-optimize with Greedy
        self.sim.current_time = 5.0
        plan_t4 = self.sim.optimize(solver_name="Greedy Baseline")
        self.assertIn("E004", plan_t4.allocations)

        # T5: Resolve emergency E003
        self.sim.resolve_emergency("E003", trigger_time=6.0)

        # T6: Reopen road hostel_a <-> sports_complex
        self.sim.reopen_road("hostel_a", "sports_complex", trigger_time=7.0)

        # T7: Re-optimize with QUBO
        plan_t7 = self.sim.optimize(solver_name="QUBO Solver")
        self.assertIsNotNone(plan_t7)

        # Verify complete event log
        events = self.sim.get_event_history()
        self.assertGreaterEqual(len(events), 8)

        # Verify snapshot integrity
        snapshot = self.sim.get_snapshot()
        self.assertEqual(snapshot.timestamp, 7.0)
        self.assertIn("E003", snapshot.resolved_emergencies)
        self.assertNotIn("E003", [e["id"] for e in snapshot.active_emergencies])

    def test_08_greedy_and_qubo_after_dynamic_changes(self):
        """TEST 8: Both Greedy and QUBO function correctly after dynamic changes."""
        # Make dynamic changes: add emergency and block road
        new_em = Emergency(
            id="E004",
            location_id="academic_block",
            emergency_type="medical_emergency",
            severity=8,
            people_affected=15,
            ambulances_required=1,
            rescue_teams_required=0,
            medical_supplies_required=10,
            medical_personnel_required=2,
        )
        self.sim.add_emergency(new_em)
        self.sim.block_road("main_gate", "cafeteria")

        # 1. Greedy solver execution
        greedy_plan = self.sim.optimize(solver_name="Greedy Baseline")
        self.assertEqual(greedy_plan.solver_name, "Greedy Baseline")
        self.assertGreater(len(greedy_plan.allocations), 0)

        # 2. QUBO solver execution
        qubo_plan = self.sim.optimize(solver_name="QUBO Solver")
        self.assertEqual(qubo_plan.solver_name, "QUBO Solver")
        self.assertGreater(len(qubo_plan.allocations), 0)

        # 3. Assert valid non-negative allocations and metrics
        for plan in (greedy_plan, qubo_plan):
            for record in plan.allocations.values():
                self.assertGreaterEqual(record.ambulances_assigned, 0)
                self.assertGreaterEqual(record.rescue_teams_assigned, 0)
                self.assertGreaterEqual(record.medical_supplies_assigned, 0)
                self.assertGreaterEqual(record.medical_personnel_assigned, 0)
            self.assertIn("weighted_objective", plan.metrics)


def run_tests():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDynamicSimulation)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
