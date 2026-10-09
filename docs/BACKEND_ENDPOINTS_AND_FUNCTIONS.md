# QDO Backend Endpoints and Function Reference

> **Source of Truth Notice**: This documentation is generated directly from the current Quantum Disaster Resource Optimizer (QDO) codebase implementation.

---

## 1. API Endpoints

No HTTP API endpoints are currently implemented.

The current backend is a pure Python architecture. Web interface layers (such as Streamlit in `app.py` or future REST/FastAPI endpoints) interact directly with backend Python modules and classes.

---

## 2. Backend Functions

### 2.1 Campus Network & Graph (`data/campus.py`)

- **`build_campus_graph(blocked_edges: Optional[List[Tuple[str, str]]] = None) -> nx.Graph`**
  - **File**: `data/campus.py`
  - **Parameters**: `blocked_edges` (optional list of location ID tuples `(u, v)` to block).
  - **Return**: `nx.Graph` (NetworkX undirected graph).
  - **Purpose**: Constructs the campus road network graph with nodes (`CampusLocation`) and weighted edges (`distance`, `effective_distance`, `blocked`).
  - **Called By**: `SimulationState.__init__`, `DynamicSimulation`.

- **`get_travel_time_seconds(graph: nx.Graph, src_id: str, dst_id: str) -> float`**
  - **File**: `data/campus.py`
  - **Parameters**: `graph` (`nx.Graph`), `src_id` (`str`), `dst_id` (`str`).
  - **Return**: `float` (travel time in seconds, or `math.inf` if unreachable).
  - **Purpose**: Computes Dijkstra shortest-path travel time in seconds using `effective_distance` and `VEHICLE_SPEED_MS`.
  - **Calls**: `nx.dijkstra_path_length`.

- **`get_travel_time_minutes(graph: nx.Graph, src_id: str, dst_id: str) -> float`**
  - **File**: `data/campus.py`
  - **Parameters**: `graph`, `src_id`, `dst_id`.
  - **Return**: `float` (travel time in minutes).
  - **Purpose**: Convenience wrapper converting `get_travel_time_seconds` to minutes.

- **`travel_time_matrix(graph: nx.Graph) -> Dict[Tuple[str, str], float]`**
  - **File**: `data/campus.py`
  - **Parameters**: `graph` (`nx.Graph`).
  - **Return**: `Dict[Tuple[str, str], float]` keyed by `(src_id, dst_id)`.
  - **Purpose**: Computes all-pairs travel-time matrix in minutes across all campus locations.
  - **Called By**: `SimulationState.__init__`, `DynamicSimulation.block_road`, `DynamicSimulation.reopen_road`.

---

### 2.2 Scenarios & Incident Generators (`data/scenarios.py`)

- **`get_scenario_alpha(seed: int = 42) -> Scenario`**
  - **File**: `data/scenarios.py`
  - **Return**: `Scenario` ("ALPHA" – 3 simultaneous emergencies: Hostel A fire, Cafeteria medical, Admin Block accident).

- **`get_scenario_beta(seed: int = 42) -> Scenario`**
  - **File**: `data/scenarios.py`
  - **Return**: `Scenario` ("BETA" – 4 emergencies with blocked route `hostel_b <-> sports_complex`).

- **`get_scenario_gamma(seed: int = 42) -> Scenario`**
  - **File**: `data/scenarios.py`
  - **Return**: `Scenario` ("GAMMA" – 5 mass-casualty emergencies with 2 blocked routes).

- **`get_scenario_stress(seed: int = 42) -> Scenario`**
  - **File**: `data/scenarios.py`
  - **Return**: `Scenario` ("STRESS" – Extreme resource contention scenario for baseline vs QUBO comparison).

- **`generate_random_scenario(name: str = "RANDOM", num_emergencies: int = 3, seed: int = 42) -> Scenario`**
  - **File**: `data/scenarios.py`
  - **Parameters**: `name`, `num_emergencies`, `seed`.
  - **Return**: `Scenario` with randomly sampled incidents and routes.

- **`get_scenario(name: str, seed: int = 42) -> Scenario`**
  - **File**: `data/scenarios.py`
  - **Parameters**: `name` (`"alpha"`, `"beta"`, `"gamma"`, `"stress"`), `seed`.
  - **Return**: `Scenario`.
  - **Purpose**: Registry lookup factory for loading scenarios.

---

### 2.3 Emergency Lifecycle Management (`simulation/emergencies.py`)

- **`EmergencyManager.report(emergency: Emergency) -> None`**
  - **File**: `simulation/emergencies.py`
  - **Purpose**: Registers a new emergency with status `EmergencyStatus.REPORTED`.

- **`EmergencyManager.assign(emergency_id: str, allocation: AllocationRecord) -> None`**
  - **File**: `simulation/emergencies.py`
  - **Purpose**: Records a resource allocation and updates status to `EmergencyStatus.ACTIVE`.

- **`EmergencyManager.resolve(emergency_id: str) -> None`**
  - **File**: `simulation/emergencies.py`
  - **Purpose**: Marks an emergency as `EmergencyStatus.RESOLVED`.

- **`EmergencyManager.escalate(emergency_id: str) -> None`**
  - **File**: `simulation/emergencies.py`
  - **Purpose**: Marks an emergency as `EmergencyStatus.ESCALATED`.

- **`EmergencyManager.active_emergencies() -> List[Emergency]`**
  - **File**: `simulation/emergencies.py`
  - **Return**: List of emergencies with status `REPORTED` or `ACTIVE`.

- **`EmergencyManager.sorted_by_priority() -> List[Emergency]`**
  - **File**: `simulation/emergencies.py`
  - **Return**: Active emergencies sorted descending by `priority_score`.

- **`EmergencyManager.compute_unmet_demand() -> Dict[str, Dict[str, int]]`**
  - **File**: `simulation/emergencies.py`
  - **Return**: Per-emergency, per-resource shortfall dict.

---

### 2.4 Resource Inventory Management (`simulation/resources.py`)

- **`ResourceManager.reserve(emergency_id, ambulances, rescue_teams, medical_supplies, medical_personnel, sim_time) -> Tuple[bool, Optional[str]]`**
  - **File**: `simulation/resources.py`
  - **Return**: `(success: bool, error_message: Optional[str])`.
  - **Purpose**: Atomically reserves requested resource quantities if available capacity exists.

- **`ResourceManager.reserve_partial(...) -> Dict[str, int]`**
  - **File**: `simulation/resources.py`
  - **Return**: Dict of actually reserved resource quantities (best effort).

- **`ResourceManager.release(emergency_id: str) -> bool`**
  - **File**: `simulation/resources.py`
  - **Return**: `True` if reservation existed and was returned to available pool.

- **`ResourceManager.available() -> Dict[str, int]`**
  - **File**: `simulation/resources.py`
  - **Return**: Current available unreserved resource units.

- **`ResourceManager.capacity() -> Dict[str, int]`**
  - **File**: `simulation/resources.py`
  - **Return**: Total resource pool capacity.

- **`ResourceManager.utilisation() -> Dict[str, float]`**
  - **File**: `simulation/resources.py`
  - **Return**: Utilization fractions ($0.0$ to $1.0$) per resource type.

---

### 2.5 Simulation Core (`simulation/simulation.py`)

- **`SimulationState.__init__(scenario: Scenario, resource_pool: Optional[ResourcePool] = None)`**
  - **File**: `simulation/simulation.py`
  - **Purpose**: Initializes campus graph, `EmergencyManager`, `ResourceManager`, and travel-time matrix.

- **`create_simulation(scenario_name: str = "alpha", seed: int = 42, resource_pool: Optional[ResourcePool] = None) -> SimulationState`**
  - **File**: `simulation/simulation.py`
  - **Return**: Initialized `SimulationState`.

---

### 2.6 Dynamic Simulation Layer (`simulation/dynamic.py`)

- **`DynamicSimulation.add_emergency(emergency: Emergency, trigger_time: Optional[float] = None) -> None`**
  - **File**: `simulation/dynamic.py`
  - **Inputs**: `emergency` (`Emergency`), `trigger_time` (optional float).
  - **State Change**: Adds emergency to `EmergencyManager`, updates timeline.

- **`DynamicSimulation.block_road(u: str, v: str, trigger_time: Optional[float] = None) -> None`**
  - **File**: `simulation/dynamic.py`
  - **Inputs**: Location IDs `u`, `v`.
  - **State Change**: Sets edge `blocked=True`, `effective_distance = dist * 1e6`, recalculates travel-time matrix.

- **`DynamicSimulation.reopen_road(u: str, v: str, trigger_time: Optional[float] = None) -> None`**
  - **File**: `simulation/dynamic.py`
  - **Inputs**: Location IDs `u`, `v`.
  - **State Change**: Sets edge `blocked=False`, restores `effective_distance`, recalculates travel-time matrix.

- **`DynamicSimulation.modify_resource_availability(resource_type: str, delta: int, trigger_time: Optional[float] = None, update_capacity: bool = True) -> None`**
  - **File**: `simulation/dynamic.py`
  - **Inputs**: `resource_type`, integer `delta` (+/-).
  - **State Change**: Adjusts available units and capacity bounds.

- **`DynamicSimulation.resolve_emergency(emergency_id: str, trigger_time: Optional[float] = None) -> None`**
  - **File**: `simulation/dynamic.py`
  - **Inputs**: `emergency_id`.
  - **State Change**: Marks emergency `RESOLVED`, releases reserved resources back to `ResourceManager`.

- **`DynamicSimulation.optimize(solver_name: str = "Greedy Baseline", commit_allocations: bool = True, solver_kwargs: Optional[Dict] = None) -> AllocationPlan`**
  - **File**: `simulation/dynamic.py`
  - **Inputs**: `solver_name` (`"Greedy Baseline"` or `"QUBO Solver"`), `commit_allocations`, `solver_kwargs`.
  - **Backend Operation**: Runs solver on active emergencies, updates `latest_plan`, reserves committed resources.
  - **Output**: `AllocationPlan`.

- **`DynamicSimulation.get_snapshot() -> DynamicStateSnapshot`**
  - **File**: `simulation/dynamic.py`
  - **Output**: `DynamicStateSnapshot` dictionary payload.

- **`DynamicSimulation.get_event_history() -> List[Dict[str, Any]]`**
  - **File**: `simulation/dynamic.py`
  - **Output**: List of logged timeline event dicts.

---

### 2.7 Optimization Layer (`optimization/`)

- **`GreedyBaselineSolver.solve(state: SimulationState) -> AllocationPlan`**
  - **File**: `optimization/baseline.py`
  - **Purpose**: Runs greedy priority-based allocation across active emergencies.

- **`QUBOFormulator.formulate(state: SimulationState) -> Tuple[Dict[Tuple[str, str], float], Dict[str, Dict]]`**
  - **File**: `optimization/qubo.py`
  - **Purpose**: Builds QUBO quadratic dictionary $Q$ and decision variable metadata.

- **`QUBOFormulator.decode_solution(sample: Dict[str, int], state: SimulationState) -> Tuple[AllocationPlan, bool, bool]`**
  - **File**: `optimization/qubo.py`
  - **Return**: `(plan, raw_feasible, final_feasible)`
  - **Purpose**: Decodes binary QUBO sample array into `AllocationPlan`. Evaluates raw sample feasibility against resource capacities, applies hard capacity trimming to lowest-severity emergencies if excess exists (with no hidden secondary greedy filling), and verifies final allocation feasibility.

- **`QUBOSolver.solve(state: SimulationState) -> AllocationPlan`**
  - **File**: `optimization/qubo.py`
  - **Purpose**: Formulates QUBO, executes Simulated Annealing via `neal` on classical CPU, decodes best sample, records detailed timing breakdown (`qubo_formulation_time_ms`, `bqm_construction_time_ms`, `sampler_time_ms`, `decode_time_ms`, `total_solve_time_ms`), and returns `AllocationPlan` with transparency metadata.

- **`SolverRegistry.get(name: str) -> Optional[object]`**
  - **File**: `optimization/solver.py`
  - **Purpose**: Returns solver instance by string key (`"Greedy Baseline"`, `"QUBO Solver"`).

---

### 2.8 Distance & Travel Utilities (`utils/distance.py`)

- **`shortest_path(graph: nx.Graph, src_id: str, dst_id: str) -> Optional[List[str]]`**
- **`path_distance_metres(graph: nx.Graph, path: List[str]) -> float`**
- **`travel_time_with_path(graph: nx.Graph, src_id: str, dst_id: str) -> Tuple[float, Optional[List[str]]]`**
- **`build_distance_matrix(graph: nx.Graph, location_ids: Optional[List[str]] = None, in_minutes: bool = True) -> Tuple[np.ndarray, List[str]]`**
- **`nearest_location(graph: nx.Graph, source_id: str, candidates: List[str]) -> Tuple[Optional[str], float]`**
- **`format_travel_time(minutes: float) -> str`**

---

### 2.9 Performance Metrics & Evaluation (`utils/metrics.py`)

- **`full_metrics_report(emergencies, allocations, travel_times, capacity, depot_id="main_gate", solver_name="Unknown") -> Dict`**
  - **File**: `utils/metrics.py`
  - **Return**: Dictionary containing `avg_response_time_min`, `max_response_time_min`, `unmet_demand_fraction`, `severity_weighted_unmet_demand_fraction`, `coverage_score`, `critical_coverage_score`, `resource_utilisation`, `avg_utilisation`, `weighted_objective`.

---

### 2.10 Explainability Engine (`utils/explainability.py`)

- **`generate_allocation_explanations(plan: AllocationPlan, state: SimulationState) -> Dict[str, str]`**
  - **File**: `utils/explainability.py`
  - **Return**: Dict mapping `emergency_id` -> data-driven natural language explanation.

---

## 3. Important Classes & Dataclasses

| Class | File | Purpose & Key Attributes |
| :--- | :--- | :--- |
| `CampusLocation` | `data/campus.py` | Represents physical location (`id`, `name`, `x`, `y`, `tags`). |
| `Emergency` | `data/scenarios.py` | Incident model (`id`, `location_id`, `emergency_type`, `severity`, `people_affected`, `resource_requirements`). |
| `ResourcePool` | `data/scenarios.py` | Total campus resource capacities (`ambulances`, `rescue_teams`, `medical_supplies`, `medical_personnel`). |
| `Scenario` | `data/scenarios.py` | Incident set snapshot (`name`, `description`, `emergencies`, `blocked_routes`, `seed`). |
| `EmergencyStatus` | `simulation/emergencies.py` | Enum (`REPORTED`, `ACTIVE`, `RESOLVED`, `ESCALATED`). |
| `AllocationRecord` | `simulation/emergencies.py` | Resource assignment record per emergency (`ambulances_assigned`, etc.). |
| `EmergencyManager` | `simulation/emergencies.py` | Lifecycle tracker for emergencies. |
| `Reservation` | `simulation/resources.py` | Tracks active resource reservations tied to emergencies. |
| `ResourceManager` | `simulation/resources.py` | Inventory tracker enforcing capacity constraints. |
| `SimulationState` | `simulation/simulation.py` | Encapsulates graph, emergency manager, resource manager, travel matrix. |
| `EventType` | `simulation/dynamic.py` | Enum for dynamic events. |
| `DynamicEvent` | `simulation/dynamic.py` | Dataclass for logged dynamic timeline events. |
| `DynamicStateSnapshot` | `simulation/dynamic.py` | Immutable state snapshot container. |
| `DynamicSimulation` | `simulation/dynamic.py` | Orchestration layer for dynamic simulation events. |
| `AllocationPlan` | `optimization/solver.py` | Solver output container (`allocations`, `metrics`, `solver_metadata`, `explanations`). |
| `GreedyBaselineSolver` | `optimization/baseline.py` | Priority-based baseline solver. |
| `QUBOFormulator` | `optimization/qubo.py` | Builds QUBO matrix $Q$ and decodes binary samples. |
| `QUBOSolver` | `optimization/qubo.py` | QUBO solver using Simulated Annealing (`neal`). |
| `SolverRegistry` | `optimization/solver.py` | Registry for solver lookup by name. |

---

## 4. Dynamic Simulation Workflow Details

- **`add_emergency`**:
  Input: `Emergency` object $\rightarrow$ State Change: Adds to `EmergencyManager` with status `REPORTED` $\rightarrow$ Operation: Updates active emergency priority list $\rightarrow$ Output: `None` (logged event).
- **`block_road`**:
  Input: `u`, `v` location IDs $\rightarrow$ State Change: Sets edge `blocked=True` and `effective_distance=dist*1e6` $\rightarrow$ Operation: Re-runs Dijkstra travel matrix calculation $\rightarrow$ Output: `None` (logged event).
- **`reopen_road`**:
  Input: `u`, `v` location IDs $\rightarrow$ State Change: Sets edge `blocked=False` and restores `effective_distance` $\rightarrow$ Operation: Re-runs Dijkstra travel matrix calculation $\rightarrow$ Output: `None` (logged event).
- **`modify_resource_availability`**:
  Input: `resource_type`, `delta` integer $\rightarrow$ State Change: Mutates `_available` and `_capacity` in `ResourceManager` $\rightarrow$ Operation: Enforces $0 \le \text{avail} \le \text{cap}$ $\rightarrow$ Output: `None` (logged event).
- **`resolve_emergency`**:
  Input: `emergency_id` $\rightarrow$ State Change: Sets status to `RESOLVED` and releases reserved resources $\rightarrow$ Operation: Reclaims capacity in `ResourceManager` $\rightarrow$ Output: `None` (logged events).
- **`optimize`**:
  Input: `solver_name` $\rightarrow$ State Change: Re-runs solver on active emergencies $\rightarrow$ Operation: Generates plan and updates reservations $\rightarrow$ Output: `AllocationPlan`.

---

## 5. Optimization Mechanism

1. **State Consumption**: Solvers accept `SimulationState` and query `state.active_emergencies`, `state.resource_vector()`, and `state.travel_times`.
2. **Greedy Baseline**: Ranks active emergencies by priority score and assigns available capacity sequentially.
3. **QUBO Solver**: Formulates quadratic matrix $Q$ with penalty terms for unmet demand, travel time delay, over-capacity interactions, and one-hot choice selection. Samples via `neal.SimulatedAnnealingSampler`, decodes binary vector, trims excess, and fills remaining capacity.
4. **Output**: Returns an `AllocationPlan` with full performance metrics and data-driven explanations.

---

## 6. End-to-End Backend Flow

### Static Scenario Flow
```
Scenario (ALPHA/BETA/GAMMA/STRESS)
       │
       ▼
SimulationState
       │
       ├─► Campus Graph (NetworkX Dijkstra Travel Matrix)
       ├─► EmergencyManager (Active Emergencies Sorted by Priority)
       └─► ResourceManager (Available Capacity Tracking)
       │
       ▼
Greedy Baseline / QUBO Solver
       │
       ▼
AllocationPlan ──► Metrics Report ──► Explainability Engine
```

### Dynamic Simulation Flow
```
Dynamic Event (Add Emergency / Block Road / Resource Change / Resolve Emergency)
       │
       ▼
DynamicSimulation Layer
       │
       ▼
SimulationState In-Place Update
       │
       ├─► Graph Edge Weight Update & Matrix Recalculation
       ├─► Resource Manager Capacity Adjustment / Release
       └─► Emergency Status Update
       │
       ▼
Re-Optimization (Greedy or QUBO)
       │
       ▼
New AllocationPlan ──► Updated Metrics ──► DynamicStateSnapshot
```

---

## 7. Module Dependency Map

```
simulation/dynamic.py
    ├──> simulation/simulation.py
    │       ├──> data/campus.py
    │       └──> data/scenarios.py
    ├──> simulation/emergencies.py
    ├──> simulation/resources.py
    └──> optimization/solver.py
            ├──> optimization/baseline.py
            └──> optimization/qubo.py
                    ├──> utils/metrics.py
                    └──> utils/explainability.py
```

---

## 8. Configuration & Constants Reference

- **Resource Pool Default (`DEFAULT_RESOURCES`)**:
  - Ambulances: `5`
  - Rescue Teams: `3`
  - Medical Supplies: `100` units
  - Medical Personnel: `25` staff
- **Vehicle Speed (`VEHICLE_SPEED_KMH`)**: `20.0` km/h ($\approx 5.56$ m/s).
- **QUBO Penalty Weights (`QUBO_PENALTIES`)**:
  - `capacity_penalty`: `200.0`
  - `one_hot_penalty`: `100.0`
  - `response_time_weight`: `10.0`
  - `unmet_demand_penalty`: `50.0`
  - `utilisation_reward`: `2.0`
- **Objective Metric Weights (`OBJECTIVE_WEIGHTS`)**:
  - `response_time_weight`: `0.40`
  - `unmet_demand_weight`: `0.45`
  - `utilisation_weight`: `0.15`
  - `time_scale_minutes`: `15.0`

---

## 9. Frontend Integration Reference

### Current Backend State
The current backend does not yet expose HTTP API endpoints. The existing backend functionality is currently accessible through Python modules/functions.

### Data Needed by Frontend
- Active emergency lists and priorities
- Graph topology and blocked road status
- Resource utilization fractions
- Comparative metrics (Greedy vs. QUBO)
- Natural language explanations per emergency
- Timeline event history log

---

## 10. Dynamic Frontend Actions Mapping

| Frontend Action | Backend Method | Key Inputs | Result |
| :--- | :--- | :--- | :--- |
| **Add Emergency** | `sim.add_emergency(em)` | `Emergency` dataclass | New active emergency added, timeline updated |
| **Block Road** | `sim.block_road(u, v)` | `u`, `v` location IDs | Edge blocked, travel matrix recalculated |
| **Reopen Road** | `sim.reopen_road(u, v)` | `u`, `v` location IDs | Edge unblocked, travel matrix restored |
| **Change Resource** | `sim.modify_resource_availability(type, delta)` | `type`, integer `delta` | Resource capacity/availability updated |
| **Resolve Emergency**| `sim.resolve_emergency(id)` | `emergency_id` | Status set to `RESOLVED`, resources returned |
| **Re-Optimize** | `sim.optimize(solver_name)` | `"Greedy Baseline"` or `"QUBO Solver"` | Updated `AllocationPlan` & metrics |
| **Get State Snapshot**| `sim.get_snapshot()` | None | `DynamicStateSnapshot` dict payload |
| **Get Event Log** | `sim.get_event_history()` | None | List of dynamic event dicts |

---

## 11. Example End-to-End Scenario Script

```python
from simulation.dynamic import DynamicSimulation
from data.scenarios import Emergency

# 1. Initialize simulation with ALPHA scenario
sim = DynamicSimulation(scenario_name="alpha", seed=42)

# 2. Run initial optimization with QUBO Solver
plan_t0 = sim.optimize(solver_name="QUBO Solver")
print(f"T0 Objective: {plan_t0.metrics['weighted_objective']:.4f}")

# 3. Dynamic Event: Report new emergency E004 at Library (T=5.0m)
new_em = Emergency(
    id="E004", location_id="library", emergency_type="fire",
    severity=9, people_affected=25, ambulances_required=2,
    rescue_teams_required=1, medical_supplies_required=15,
    medical_personnel_required=3
)
sim.add_emergency(new_em, trigger_time=5.0)

# 4. Dynamic Event: Block road admin_block <-> cafeteria (T=6.0m)
sim.block_road("admin_block", "cafeteria", trigger_time=6.0)

# 5. Dynamic Event: Reduce ambulances by 1 (T=7.0m)
sim.modify_resource_availability("ambulances", -1, trigger_time=7.0)

# 6. Re-optimize with Greedy Baseline
plan_t7 = sim.optimize(solver_name="Greedy Baseline")

# 7. Dynamic Event: Resolve E001 (T=10.0m)
sim.resolve_emergency("E001", trigger_time=10.0)

# 8. Dynamic Event: Reopen road admin_block <-> cafeteria (T=11.0m)
sim.reopen_road("admin_block", "cafeteria", trigger_time=11.0)

# 9. Final Re-optimization with QUBO Solver
plan_t11 = sim.optimize(solver_name="QUBO Solver")

# 10. Extract snapshot payload
snapshot = sim.get_snapshot()
print(f"Final Active Emergencies: {len(snapshot.active_emergencies)}")
print(f"Events Logged: {snapshot.event_history_count}")
```

---

## 12. Test Coverage

- **`test_simulation.py`**: Validates campus graph, Dijkstra travel times, `EmergencyManager`, `ResourceManager`, and `SimulationState`.
- **`test_optimization.py`**: Validates Greedy baseline vs. QUBO solver side-by-side performance across `ALPHA`, `BETA`, `GAMMA`, and `STRESS` scenarios.
- **`test_dynamic_simulation.py`**: Validates all 8 dynamic simulation capabilities (emergency addition, road block/reopen, resource modifications, resolution, sequential timeline, and solver compatibility).

Test Commands:
```bash
python test_simulation.py
python test_optimization.py
python test_dynamic_simulation.py
```

---

## 13. Project File Map

```text
quantum-disaster/
├── data/
│   ├── __init__.py
│   ├── campus.py
│   └── scenarios.py
├── simulation/
│   ├── __init__.py
│   ├── emergencies.py
│   ├── resources.py
│   ├── simulation.py
│   └── dynamic.py
├── optimization/
│   ├── __init__.py
│   ├── baseline.py
│   ├── qubo.py
│   └── solver.py
├── utils/
│   ├── __init__.py
│   ├── distance.py
│   ├── metrics.py
│   └── explainability.py
├── docs/
│   ├── dynamic_simulation.md
│   └── BACKEND_ENDPOINTS_AND_FUNCTIONS.md
├── app.py
├── requirements.txt
├── test_simulation.py
├── test_optimization.py
└── test_dynamic_simulation.py
```

---

## 14. Final Summary

- **Number of actual HTTP API endpoints**: `0`
- **Number of important classes/dataclasses**: `19`
- **Number of documented functions/methods**: `58`
- **Number of dynamic simulation functions/methods**: `10`
- **Number of backend files inspected**: `13`
- **List of backend files inspected**: `data/campus.py`, `data/scenarios.py`, `simulation/emergencies.py`, `simulation/resources.py`, `simulation/simulation.py`, `simulation/dynamic.py`, `optimization/baseline.py`, `optimization/qubo.py`, `optimization/solver.py`, `utils/distance.py`, `utils/metrics.py`, `utils/explainability.py`, `app.py`.
- **Whether HTTP API integration currently exists**: No (0 endpoints currently implemented).
- **Whether the backend is ready for frontend API integration**: Yes. The clean Python interface, dataclasses, and snapshot serialization methods in `simulation/dynamic.py` are fully prepared for wrapping with FastAPI/REST API endpoints or direct Streamlit integration.
