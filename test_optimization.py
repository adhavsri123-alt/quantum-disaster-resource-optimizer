"""
test_optimization.py
--------------------
Backend optimization engine audit, improvement, and verification script.

Evaluates GreedyBaselineSolver and QUBOSolver across:
  - Scenario ALPHA  (3 emergencies, light load)
  - Scenario BETA   (4 emergencies, flood + blocked route)
  - Scenario GAMMA  (5 emergencies, mass casualty)
  - Scenario STRESS (5 emergencies, extreme resource contention)

Prints detailed side-by-side performance comparison, QUBO energy & variable metadata,
emergency-by-emergency allocation differences, data-driven explanations, and runs
strict verification assertions.
"""

from __future__ import annotations

import sys
import math
from typing import Dict, List

from simulation.simulation import create_simulation
from optimization.baseline import GreedyBaselineSolver
from optimization.qubo import QUBOSolver
from optimization.solver import SolverRegistry, AllocationPlan


def run_comparison() -> List[Dict]:
    """Run solvers on all 4 scenarios and return aggregated comparison records."""
    scenarios = ["alpha", "beta", "gamma", "stress"]
    results = []

    greedy_solver = GreedyBaselineSolver()
    qubo_solver = QUBOSolver(num_reads=500, seed=42)

    solvers = [
        ("Greedy Baseline", greedy_solver),
        ("QUBO Solver", qubo_solver),
    ]

    print("=" * 90)
    print("  QUANTUM DISASTER RESOURCE OPTIMIZER (QDO) — BACKEND OPTIMIZATION VERIFICATION")
    print("=" * 90)

    for scenario_name in scenarios:
        # Create a fresh reference state to inspect scenario metadata
        ref_state = create_simulation(scenario_name=scenario_name, seed=42)
        total_capacity = ref_state.resource_manager.capacity()

        print(f"\n>>> Scenario: {scenario_name.upper()} ({len(ref_state.emergencies)} emergencies)")
        print("-" * 90)

        plans: Dict[str, AllocationPlan] = {}

        for name, solver in solvers:
            # Provide equivalent, independently created copy of scenario for each solver
            solver_state = create_simulation(scenario_name=scenario_name, seed=42)
            plan: AllocationPlan = solver.solve(solver_state)
            plans[name] = plan
            metrics = plan.metrics
            metadata = plan.solver_metadata

            avg_rt = metrics.get("avg_response_time_min", 0.0)
            avg_rt_str = "Inf" if math.isinf(avg_rt) else f"{avg_rt:.2f}"

            max_rt = metrics.get("max_response_time_min", 0.0)
            max_rt_str = "Inf" if math.isinf(max_rt) else f"{max_rt:.2f}"

            unmet_pct = metrics.get("unmet_demand_fraction", 0.0) * 100.0
            sev_unmet_pct = metrics.get("severity_weighted_unmet_demand_fraction", 0.0) * 100.0
            util_pct = metrics.get("avg_utilisation", 0.0) * 100.0
            cov_pct = metrics.get("coverage_score", 0.0) * 100.0
            crit_cov_pct = metrics.get("critical_coverage_score", 0.0) * 100.0
            obj_score = metrics.get("weighted_objective", 0.0)
            runtime_ms = metadata.get("solve_time_ms", 0.0)

            # ------------------------------------------------------------------
            # Verification Assertions
            # ------------------------------------------------------------------
            assert isinstance(plan, AllocationPlan), f"[{name}] plan is not AllocationPlan"
            assert plan.solver_name == name, f"[{name}] solver name mismatch"
            assert len(plan.allocations) == len(ref_state.emergencies), (
                f"[{name}] Allocation count ({len(plan.allocations)}) != emergency count ({len(ref_state.emergencies)})"
            )

            # Assert non-negativity and capacity constraints
            total_deployed = {
                "ambulances": 0,
                "rescue_teams": 0,
                "medical_supplies": 0,
                "medical_personnel": 0,
            }

            for em_id, record in plan.allocations.items():
                assert record.ambulances_assigned >= 0, f"[{name}] negative ambulance allocation"
                assert record.rescue_teams_assigned >= 0, f"[{name}] negative rescue team allocation"
                assert record.medical_supplies_assigned >= 0, f"[{name}] negative medical supplies allocation"
                assert record.medical_personnel_assigned >= 0, f"[{name}] negative medical personnel allocation"

                total_deployed["ambulances"] += record.ambulances_assigned
                total_deployed["rescue_teams"] += record.rescue_teams_assigned
                total_deployed["medical_supplies"] += record.medical_supplies_assigned
                total_deployed["medical_personnel"] += record.medical_personnel_assigned

            for rtype, deployed_cnt in total_deployed.items():
                cap_cnt = total_capacity[rtype]
                assert deployed_cnt <= cap_cnt, (
                    f"[{name}] Resource '{rtype}' capacity exceeded: deployed {deployed_cnt} > capacity {cap_cnt}"
                )

            # Assert valid metrics
            assert not math.isnan(unmet_pct), f"[{name}] unmet demand is NaN"
            assert 0.0 <= unmet_pct <= 100.0001, f"[{name}] unmet demand % out of range: {unmet_pct}"
            assert 0.0 <= util_pct <= 100.0001, f"[{name}] utilisation % out of range: {util_pct}"

            rec = {
                "scenario": scenario_name,
                "solver": name,
                "avg_response_time_min": avg_rt,
                "avg_rt_str": avg_rt_str,
                "max_rt_str": max_rt_str,
                "unmet_demand_pct": unmet_pct,
                "sev_unmet_demand_pct": sev_unmet_pct,
                "utilisation_pct": util_pct,
                "coverage_pct": cov_pct,
                "critical_coverage_pct": crit_cov_pct,
                "objective_score": obj_score,
                "runtime_ms": runtime_ms,
                "qubo_vars": metadata.get("num_variables", 0),
                "qubo_energy": metadata.get("energy", 0.0),
                "feasibility": metadata.get("feasibility_status", "N/A"),
            }
            results.append(rec)

            extra_meta = ""
            if name == "QUBO Solver":
                extra_meta = f" | Vars: {metadata.get('num_variables',0):2d} | Energy: {metadata.get('energy',0.0):8.2f}"

            print(
                f"  [{name:15s}]  Avg RT: {avg_rt_str:>6s} min | Max RT: {max_rt_str:>6s} min | "
                f"Unmet: {unmet_pct:5.1f}% | SevUnmet: {sev_unmet_pct:5.1f}% | "
                f"Util: {util_pct:5.1f}% | Obj: {obj_score:7.4f} | Time: {runtime_ms:6.2f} ms{extra_meta}"
            )

            if name == "QUBO Solver":
                print(
                    f"     |-- Breakdown : Formulate: {metadata.get('qubo_formulation_time_ms', 0):.2f}ms | "
                    f"BQM: {metadata.get('bqm_construction_time_ms', 0):.2f}ms | "
                    f"SA Sampler (CPU): {metadata.get('sampler_time_ms', 0):.2f}ms | "
                    f"Decode: {metadata.get('decode_time_ms', 0):.2f}ms"
                )
                print(
                    f"     |-- Properties: {metadata.get('num_variables', 0)} vars, "
                    f"{metadata.get('num_quadratic_terms', 0)} quadratic terms | "
                    f"Feasibility: {metadata.get('feasibility_status', 'N/A')}"
                )

        # Print per-emergency allocation differences
        g_alloc = plans["Greedy Baseline"].allocations
        q_alloc = plans["QUBO Solver"].allocations

        print("\n  Detailed Allocation Comparison (Emergency-by-Emergency):")
        diff_count = 0
        for em in ref_state.emergencies:
            gr = g_alloc[em.id]
            qr = q_alloc[em.id]

            match = (
                gr.ambulances_assigned == qr.ambulances_assigned
                and gr.rescue_teams_assigned == qr.rescue_teams_assigned
                and gr.medical_supplies_assigned == qr.medical_supplies_assigned
                and gr.medical_personnel_assigned == qr.medical_personnel_assigned
            )
            if not match:
                diff_count += 1
                status = "DIFFERENT"
            else:
                status = "MATCH"

            print(
                f"    [{em.id}] {em.type_label:<32s} @ {em.location_name:<18s} (Sev {em.severity}/10, Req Amb:{em.ambulances_required} Res:{em.rescue_teams_required} Sup:{em.medical_supplies_required} Per:{em.medical_personnel_required})"
            )
            print(
                f"       Greedy : Amb={gr.ambulances_assigned} Res={gr.rescue_teams_assigned} Sup={gr.medical_supplies_assigned} Per={gr.medical_personnel_assigned}"
            )
            print(
                f"       QUBO   : Amb={qr.ambulances_assigned} Res={qr.rescue_teams_assigned} Sup={qr.medical_supplies_assigned} Per={qr.medical_personnel_assigned}  [{status}]"
            )
            print(f"       Explan : {plans['QUBO Solver'].explanations.get(em.id, '')}")

        if diff_count == 0:
            print("    -> Solvers produced identical allocations across all emergencies.")
        else:
            print(f"    -> Solvers differed on {diff_count} out of {len(ref_state.emergencies)} emergencies.")

    # Print summary comparison table
    print("\n" + "=" * 110)
    print("  SIDE-BY-SIDE COMPARISON SUMMARY TABLE")
    print("=" * 110)
    header = (
        f"{'Scenario':<10s} {'Solver':<18s} {'Avg RT':<10s} {'Max RT':<10s} "
        f"{'Unmet%':<9s} {'SevUnmet%':<11s} {'Util%':<9s} {'CritCov%':<10s} {'Obj Score':<11s} {'Time(ms)':<9s}"
    )
    print(header)
    print("-" * 110)

    for r in results:
        row = (
            f"{r['scenario'].upper():<10s} "
            f"{r['solver']:<18s} "
            f"{r['avg_rt_str']:<10s} "
            f"{r['max_rt_str']:<10s} "
            f"{r['unmet_demand_pct']:<9.1f} "
            f"{r['sev_unmet_demand_pct']:<11.1f} "
            f"{r['utilisation_pct']:<9.1f} "
            f"{r['critical_coverage_pct']:<10.1f} "
            f"{r['objective_score']:<11.4f} "
            f"{r['runtime_ms']:<9.2f}"
        )
        print(row)

    print("-" * 110)
    print("  ALL BACKEND VERIFICATION TESTS PASSED SUCCESSFULLY! [OK]")
    print("=" * 110 + "\n")
    return results


if __name__ == "__main__":
    run_comparison()
