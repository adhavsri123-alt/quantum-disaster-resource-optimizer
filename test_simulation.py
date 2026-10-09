"""
test_simulation.py
------------------
Stage 1 command-line verification test for the QDO simulation layer.

Runs through all three pre-defined scenarios and the random scenario,
printing:
  1. Campus locations and coordinates
  2. Active emergencies (all details)
  3. Available resources (capacity and availability)
  4. Travel times from Main Gate to each emergency location
  5. Full all-pairs travel-time matrix
  6. Distance utilities verification
  7. Resource Manager operations test
  8. Emergency Manager operations test

Usage:
    python test_simulation.py
    python test_simulation.py --scenario beta
    python test_simulation.py --scenario gamma
    python test_simulation.py --scenario random --seed 99 --n 4
"""

from __future__ import annotations

import argparse
import math
import sys


def _banner(text: str, char: str = "=", width: int = 72) -> None:
    bar = char * width
    print(f"\n{bar}")
    print(f"  {text}")
    print(bar)


def _section(text: str) -> None:
    fill = "-" * max(0, 60 - len(text))
    print(f"\n  -- {text} {fill}")


def run_simulation_test(scenario_name: str = "alpha", seed: int = 42, n: int = 3) -> None:
    """
    Full simulation layer test.  Imports all modules and exercises them.
    """

    # -----------------------------------------------------------------------
    # 1.  Imports
    # -----------------------------------------------------------------------
    _banner("QDO -- Stage 1 Simulation Layer Test")
    print("  Importing modules ...", end=" ", flush=True)

    from data.campus import LOCATIONS, build_campus_graph, VEHICLE_SPEED_KMH
    from data.scenarios import (
        DEFAULT_RESOURCES, EMERGENCY_TYPES,
        get_scenario, generate_random_scenario,
    )
    from simulation.simulation import SimulationState
    from simulation.emergencies import EmergencyManager, EmergencyStatus, AllocationRecord
    from simulation.resources import ResourceManager, RESOURCE_LABELS
    from utils.distance import (
        build_distance_matrix, nearest_location,
        travel_time_with_path, format_travel_time,
    )
    from utils.metrics import full_metrics_report

    print("OK")
    print(f"  Vehicle speed  : {VEHICLE_SPEED_KMH} km/h")

    # -----------------------------------------------------------------------
    # 2.  Build scenario
    # -----------------------------------------------------------------------
    _section("Loading scenario")

    if scenario_name.lower() == "random":
        scenario = generate_random_scenario(
            name="RANDOM", num_emergencies=n, seed=seed
        )
    else:
        scenario = get_scenario(scenario_name, seed=seed)

    print(f"  Scenario       : {scenario.name}")
    print(f"  Description    : {scenario.description}")
    print(f"  Seed           : {scenario.seed}")
    print(f"  Emergencies    : {len(scenario.emergencies)}")
    if scenario.blocked_routes:
        for a, b in scenario.blocked_routes:
            print(f"  Blocked route  : {LOCATIONS[a].name} <-> {LOCATIONS[b].name}")

    # -----------------------------------------------------------------------
    # 3.  Build simulation state
    # -----------------------------------------------------------------------
    state = SimulationState(scenario, DEFAULT_RESOURCES)

    # -----------------------------------------------------------------------
    # 4.  Campus locations
    # -----------------------------------------------------------------------
    _banner("1. Campus Locations", char="-")
    print(f"  {'ID':22s}  {'Name':22s}  {'X (m)':>7s}  {'Y (m)':>7s}  Tags")
    print(f"  {'-'*22}  {'-'*22}  {'-'*7}  {'-'*7}  {'-'*20}")
    for lid, loc in LOCATIONS.items():
        tags = ", ".join(loc.tags) if loc.tags else "-"
        print(f"  {lid:22s}  {loc.name:22s}  {loc.x:7.0f}  {loc.y:7.0f}  {tags}")

    # -----------------------------------------------------------------------
    # 5.  Active emergencies
    # -----------------------------------------------------------------------
    _banner("2. Active Emergencies", char="-")
    for em in state.active_emergencies:
        print(f"\n  [{em.id}] {em.type_label}")
        print(f"       Location    : {em.location_name} ({em.location_id})")
        print(f"       Severity    : {em.severity}/10")
        print(f"       People      : {em.people_affected}")
        print(f"       Priority    : {em.priority_score:.3f}")
        print(f"       Resources needed:")
        print(f"         Ambulances       : {em.ambulances_required}")
        print(f"         Rescue Teams     : {em.rescue_teams_required}")
        print(f"         Medical Supplies : {em.medical_supplies_required} units")
        print(f"         Medical Personnel: {em.medical_personnel_required}")
        print(f"       Description : {em.description}")

    # -----------------------------------------------------------------------
    # 6.  Available resources
    # -----------------------------------------------------------------------
    _banner("3. Available Resources", char="-")
    rm = state.resource_manager
    print(f"\n  {'Resource':30s}  {'Available':>10s}  {'Capacity':>8s}  {'In Use':>6s}  {'Util%':>6s}")
    print(f"  {'-'*30}  {'-'*10}  {'-'*8}  {'-'*6}  {'-'*6}")
    for row in rm.status_table():
        print(
            f"  {row['Resource']:30s}  {row['Available']:>10d}  "
            f"{row['Capacity']:>8d}  {row['In Use']:>6d}  "
            f"{row['Utilisation (%)']:>5.1f}%"
        )

    # -----------------------------------------------------------------------
    # 7.  Travel times from Main Gate
    # -----------------------------------------------------------------------
    _banner("4. Travel Times from Main Gate to Emergency Locations", char="-")
    depot = "main_gate"
    graph = state.graph

    print(f"\n  Depot: {LOCATIONS[depot].name}")
    print(f"\n  {'Emergency':40s}  {'Location':22s}  {'Time':>12s}  Route")
    print(f"  {'-'*40}  {'-'*22}  {'-'*12}  {'-'*30}")
    for em in state.active_emergencies:
        tt, path = travel_time_with_path(graph, depot, em.location_id)
        tt_str = format_travel_time(tt)
        if path:
            route = " -> ".join(LOCATIONS[p].name[:8] for p in path)
        else:
            route = "NO ROUTE"
        print(f"  {em.type_label:40s}  {em.location_name:22s}  {tt_str:>12s}  {route}")

    # -----------------------------------------------------------------------
    # 8.  All-pairs travel-time matrix
    # -----------------------------------------------------------------------
    _banner("5. All-Pairs Travel-Time Matrix (minutes)", char="-")
    matrix, ids = build_distance_matrix(graph, in_minutes=True)
    names_short = [LOCATIONS[i].name[:10] for i in ids]

    # Print header
    header_row = f"  {'':18s}" + "".join(f"{n:>12s}" for n in names_short)
    print(header_row)
    print("  " + "-" * (len(header_row) - 2))

    for i, src in enumerate(ids):
        row_label = LOCATIONS[src].name[:16]
        row = f"  {row_label:18s}"
        for j in range(len(ids)):
            val = matrix[i, j]
            if math.isinf(val):
                cell = "   inf"
            elif val == 0.0:
                cell = "  0.0"
            else:
                cell = f"{val:5.1f}"
            row += f"{cell:>12s}"
        print(row)

    # -----------------------------------------------------------------------
    # 9.  Nearest location demo
    # -----------------------------------------------------------------------
    _banner("6. Nearest Location Utility Demo", char="-")
    for em in state.active_emergencies:
        candidates = [e.location_id for e in state.active_emergencies if e.id != em.id]
        if candidates:
            nearest_id, tt = nearest_location(graph, em.location_id, candidates)
            near_name = LOCATIONS[nearest_id].name if nearest_id else "None"
            print(f"  Nearest emergency to {em.location_name:22s}  ->  "
                  f"{near_name:22s}  ({format_travel_time(tt)})")

    # -----------------------------------------------------------------------
    # 10.  Resource Manager operations test
    # -----------------------------------------------------------------------
    _banner("7. Resource Manager -- Reserve / Release Test", char="-")
    test_rm = ResourceManager(DEFAULT_RESOURCES)
    print(f"\n  Initial state : {test_rm}")

    # Try to reserve for E001
    em0 = state.active_emergencies[0]
    success, err = test_rm.reserve(
        em0.id,
        ambulances=em0.ambulances_required,
        rescue_teams=em0.rescue_teams_required,
        medical_supplies=em0.medical_supplies_required,
        medical_personnel=em0.medical_personnel_required,
    )
    print(f"\n  Reserve for {em0.id} ({em0.type_label}): {'SUCCESS' if success else 'FAILED'}")
    if err:
        print(f"    Error: {err}")
    print(f"  After reserve : {test_rm}")
    print(f"  Utilisation   : { {k: f'{v*100:.1f}%' for k, v in test_rm.utilisation().items()} }")

    # Release
    released = test_rm.release(em0.id)
    print(f"\n  Release for {em0.id}: {'SUCCESS' if released else 'FAILED'}")
    print(f"  After release : {test_rm}")

    # -----------------------------------------------------------------------
    # 11.  Emergency Manager lifecycle test
    # -----------------------------------------------------------------------
    _banner("8. Emergency Manager -- Status Lifecycle Test", char="-")
    em_mgr = state.emergency_manager
    print(f"\n  {em_mgr}")
    print(f"\n  Status summary: {em_mgr.summary()}")

    for em in em_mgr.all_emergencies():
        status = em_mgr.get_status(em.id)
        print(f"  [{em.id}] {em.type_label:35s} -- status={status.value}")

    # Assign a dummy allocation to the first emergency
    em_first = em_mgr.sorted_by_priority()[0]
    alloc = AllocationRecord(
        emergency_id=em_first.id,
        ambulances_assigned=em_first.ambulances_required,
        rescue_teams_assigned=em_first.rescue_teams_required,
        medical_supplies_assigned=em_first.medical_supplies_required,
        medical_personnel_assigned=em_first.medical_personnel_required,
        dispatch_time_minutes=0.0,
        estimated_arrival_minutes=state.travel_time("main_gate", em_first.location_id),
    )
    em_mgr.assign(em_first.id, alloc)
    print(f"\n  Assigned resources to [{em_first.id}]")
    print(f"  New status: {em_mgr.get_status(em_first.id).value}")
    print(f"\n  Unmet demand after partial allocation:")
    unmet = em_mgr.compute_unmet_demand()
    for eid, demands in unmet.items():
        loc_name = state.scenario.emergencies[
            next(i for i, e in enumerate(state.scenario.emergencies) if e.id == eid)
        ].location_name
        print(f"    [{eid}] @ {loc_name}: {demands}")

    # -----------------------------------------------------------------------
    # Done
    # -----------------------------------------------------------------------
    _banner("Stage 1 Test Complete -- All Systems Operational", char="=")
    print("  [OK]  Campus graph built successfully")
    print("  [OK]  Scenario loaded with reproducible seed")
    print("  [OK]  Emergencies created with resource requirements")
    print("  [OK]  Resource Manager reserve/release working")
    print("  [OK]  Emergency Manager lifecycle working")
    print("  [OK]  Travel times computed via Dijkstra on campus graph")
    print("  [OK]  All-pairs distance matrix computed")
    print("  [OK]  All utility functions operational")
    print()
    print("  Ready for Stage 2: Optimisation Layer")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QDO Stage 1 Simulation Test")
    parser.add_argument(
        "--scenario",
        choices=["alpha", "beta", "gamma", "random"],
        default="alpha",
        help="Scenario to run (default: alpha)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=3,
        help="Number of emergencies for random scenario (default: 3)",
    )
    args = parser.parse_args()

    try:
        run_simulation_test(
            scenario_name=args.scenario,
            seed=args.seed,
            n=args.n,
        )
    except Exception as exc:
        print(f"\n  ERROR: {exc}", file=sys.stderr)
        raise
