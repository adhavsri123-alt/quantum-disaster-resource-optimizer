# Dynamic Simulation Layer Documentation

## 1. Purpose
The Dynamic Simulation Layer enables the **Quantum Disaster Resource Optimizer (QDO)** to model a dynamic, evolving emergency environment on campus. Rather than serving as a static single-shot scenario runner, this layer allows state changes *after* initial optimization, including new incident reports, road blockages, resource pool fluctuations, emergency resolution, and re-optimization using existing solvers (Greedy & QUBO).

---

## 2. Architecture
The dynamic simulation architecture acts as an orchestration and event management wrapper around the existing `SimulationState` without modifying core solver algorithms or duplicating backend domain classes.

```
       [ Campus NetworkX Graph ]       [ Emergency / Resource Pools ]
                   │                                │
                   ▼                                ▼
            ┌──────────────────────────────────────────────┐
            │               SimulationState                │
            └──────────────────────┬───────────────────────┘
                                   │
                   ┌───────────────┴───────────────┐
                   │       DynamicSimulation       │
                   └───────────────┬───────────────┘
                                   │
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
   [ Dynamic Events ]      [ State Mutators ]     [ Dynamic Snapshots ]
   - Add Emergency         - Graph Edges          - Active Emergencies
   - Block/Reopen Road     - Resource Pools       - Resource Capacity
   - Resource Change       - Emergency Status     - Event History Log
   - Resolve Emergency
           │
           ▼
    ┌──────────────┐
    │ Re-Optimize  │ ──► Greedy Baseline / QUBO Solver
    └──────────────┘
```

---

## 3. Dynamic Events Supported
The dynamic layer supports the following typed events (`EventType`):
- `EMERGENCY_REPORTED`: Initial scenario incident registration.
- `NEW_EMERGENCY_ADDED`: Dynamic mid-simulation emergency arrival.
- `ROAD_BLOCKED`: Disruption of a campus road edge on the graph.
- `ROAD_REOPENED`: Restoration of a previously blocked road edge.
- `RESOURCE_AVAILABILITY_CHANGED`: Vehicle or staff breakdown, assignment, or recovery.
- `EMERGENCY_RESOLVED`: Emergency containment/completion.
- `RESOURCES_RELEASED`: De-allocation and return of reserved resources to the available pool.
- `RESOURCE_DEPLOYED`: Resource assignment committed by a solver.
- `OPTIMIZATION_TRIGGERED`: Re-running Greedy or QUBO solvers following a state change.

---

## 4. How State Changes
When a dynamic event occurs:
1. `DynamicSimulation` updates the simulation clock (`current_time`).
2. The underlying `SimulationState` is mutated in-place (updating `EmergencyManager`, `ResourceManager`, or `Graph` edges).
3. Derived quantities (all-pairs travel times via NetworkX Dijkstra, active emergency lists, resource availability) are automatically recalculated.
4. An immutable `DynamicEvent` record is logged into `events` timeline history.
5. Solvers consume the updated `SimulationState` on re-optimization.

---

## 5. How Road Blocking Works
Road blockages manipulate edge attributes directly on the existing `nx.Graph` in `SimulationState.graph`:
- **Blocking (`block_road(u, v)`)**:
  - `graph[u][v]["blocked"] = True`
  - `graph[u][v]["effective_distance"] = distance * 1e6` (near-infinite cost penalty)
  - `SimulationState.travel_times` is recalculated using `travel_time_matrix(graph)` via Dijkstra shortest-path navigation.
  - If alternative paths exist, travel times adjust to the detour route. If unreachable, travel time is set to `math.inf`.
- **Reopening (`reopen_road(u, v)`)**:
  - `graph[u][v]["blocked"] = False`
  - `graph[u][v]["effective_distance"] = distance` (restores original metre distance)
  - `SimulationState.travel_times` is recalculated to restore original shortest-path travel times.

---

## 6. How Resource Changes Work
Resource availability fluctuations update `ResourceManager` without bypassing physical capacity constraints:
- **`modify_resource_availability(resource_type, delta)`**:
  - `delta < 0`: Decreases available units (e.g. vehicle breakdown). Checked against `available >= 0`.
  - `delta > 0`: Increases available units (e.g. vehicle repaired/returned). Checked against `available <= capacity`.
  - Non-negativity (`available >= 0`, `capacity >= 0`) is strictly enforced; invalid requests raise `ValueError`.

---

## 7. How Emergency Resolution Works
When an emergency is marked resolved via `resolve_emergency(emergency_id)`:
1. `EmergencyManager` updates the emergency status to `EmergencyStatus.RESOLVED`.
2. `ResourceManager` releases all reserved resources for `emergency_id`, returning them to the available pool.
3. `SimulationState.active_emergencies` automatically excludes resolved emergencies.
4. Subsequent re-optimizations optimize only remaining active (`REPORTED`, `ACTIVE`) emergencies.

---

## 8. How Re-Optimization Works
Re-optimization calls `DynamicSimulation.optimize(solver_name)`:
1. Temporary active emergency reservations are synced so the solver sees the full current active resource capacity.
2. The selected solver (`GreedyBaselineSolver` or `QUBOSolver`) solves `SimulationState`.
3. The new `AllocationPlan` is generated with metrics and explanations.
4. If `commit_allocations=True`, new allocations are assigned in `EmergencyManager` and reserved in `ResourceManager`.
5. An `OPTIMIZATION_TRIGGERED` event is appended to the event timeline.

---

## 9. Event/Timeline Structure
Events are stored as `DynamicEvent` instances containing:
- `timestamp`: Simulation clock time in minutes.
- `event_type`: Categorical `EventType` enum.
- `description`: Human-readable summary log.
- `details`: Metadata payload (incident parameters, delta values, solver objective).

Formatted log example:
```text
[EVENT] Emergency E001 (Fire) reported at Hostel A
[EVENT] Re-optimization triggered: QUBO Solver
[EVENT] New emergency reported: E004 at Library
[EVENT] Road blocked: admin_block <-> cafeteria
[EVENT] Resource changed: ambulances -1 (now 4/5)
[EVENT] Re-optimization triggered: Greedy Baseline
[EVENT] Emergency E001 resolved
[EVENT] Resources released for emergency E001
```

---

## 10. Test Coverage
The dynamic simulation test suite in `test_dynamic_simulation.py` covers 8 test scenarios:
- **TEST 1**: Dynamic addition of new emergency & parameter verification.
- **TEST 2**: Road blocking & NetworkX travel time detour calculation.
- **TEST 3**: Road reopening & travel time restoration.
- **TEST 4**: Resource reduction & solver capacity bound enforcement.
- **TEST 5**: Resource increase & solver capacity expansion.
- **TEST 6**: Emergency resolution, resource release & active state filtering.
- **TEST 7**: Multi-step sequential dynamic event sequence execution.
- **TEST 8**: Dual solver compatibility (Greedy & QUBO execution on dynamic state).

---

## 11. Example Dynamic Simulation Sequence
```python
from simulation.dynamic import DynamicSimulation
from data.scenarios import Emergency

# 1. Initialize simulation with ALPHA scenario
sim = DynamicSimulation(scenario_name="alpha")

# 2. Initial optimization with QUBO
plan_t0 = sim.optimize(solver_name="QUBO Solver")

# 3. Add a new fire incident at T=5m
new_em = Emergency(
    id="E004", location_id="library", emergency_type="fire",
    severity=9, people_affected=25, ambulances_required=2,
    rescue_teams_required=1, medical_supplies_required=15,
    medical_personnel_required=3
)
sim.add_emergency(new_em, trigger_time=5.0)

# 4. Block road between Main Gate and Cafeteria at T=6m
sim.block_road("main_gate", "cafeteria", trigger_time=6.0)

# 5. Re-optimize with Greedy Baseline
plan_t6 = sim.optimize(solver_name="Greedy Baseline")

# 6. Resolve initial emergency E001 and release resources
sim.resolve_emergency("E001", trigger_time=10.0)

# 7. Re-optimize with QUBO Solver
plan_t10 = sim.optimize(solver_name="QUBO Solver")

# 8. Export state snapshot for UI / reporting
snapshot = sim.get_snapshot()
print(snapshot.to_dict())
```

---

## 12. Limitations & Future Extensions
- **Continuous Vehicle Traversal**: Vehicle locations are represented node-to-node via graph Dijkstra travel times rather than continuous continuous-space physical kinetics.
- **Real-Time Quantum Hardware Hardware Access**: The QUBO solver uses `dimod` and `neal` simulated annealing; connection to physical QPU hardware (e.g., D-Wave Leap) can be plugged in by swapping the sampler in `QUBOSolver`.
