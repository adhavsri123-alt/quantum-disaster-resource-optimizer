# Quantum Disaster Resource Optimizer (QDO)

> **Hackathon Project — Smart Campus Theme**

QDO intelligently allocates limited emergency resources across a campus when multiple emergencies occur simultaneously, using quantum-inspired (QUBO-based) optimisation to minimise response time and unmet demand.

---

## Problem Statement

When several emergencies happen at once on a campus — a fire at a hostel, a medical emergency at the cafeteria, and a flood at the sports complex — limited resources (ambulances, rescue teams, medical supplies, personnel) must be allocated optimally. Manual triage is slow and suboptimal. QDO automates this using:

- **Greedy Baseline**: Priority-first, deterministic allocation (classical benchmark)
- **QUBO Solver**: Quantum-inspired optimisation via Simulated Annealing on a Binary Quadratic Model (no QPU required — runs locally)

---

## Campus Map

| Location | Coordinates (m) |
|---|---|
| Main Gate | (0, 400) |
| Admin Block | (200, 250) |
| Cafeteria | (500, 400) |
| Academic Block | (400, 600) |
| Library | (600, 700) |
| Hostel A | (900, 700) |
| Hostel B | (900, 300) |
| Sports Complex | (1100, 500) |

Vehicle speed: **20 km/h** on campus roads.

---

## Resources

| Resource | Total |
|---|---|
| Ambulances | 5 |
| Rescue Teams | 3 |
| Medical Supplies | 100 units |
| Medical Personnel | 25 staff |

---

## Scenarios

| Scenario | Description |
|---|---|
| **ALPHA** | Fire (Hostel A) + Medical Emergency (Cafeteria) + Accident (Admin Block) |
| **BETA** | Flood (Sports Complex, route blocked) + injuries (Hostel B) + Fire (Library) + Accident (Academic Block) |
| **GAMMA** | Mass-casualty structural collapse (Academic Block) + secondary fires + accident + injuries |

---

## Project Structure

```
quantum-disaster/
├── app.py                    # Streamlit UI (Stage 3)
├── requirements.txt
├── README.md
├── test_simulation.py        # Stage 1 CLI verification test
│
├── data/
│   ├── campus.py             # Campus graph, locations, travel-time utilities
│   └── scenarios.py         # Emergency types, scenarios, ResourcePool
│
├── simulation/
│   ├── emergencies.py        # Emergency lifecycle management
│   ├── resources.py          # Resource inventory and reservation
│   └── simulation.py         # SimulationState — top-level orchestrator
│
├── optimization/
│   ├── baseline.py           # Greedy baseline solver (Stage 2)
│   ├── qubo.py               # QUBO formulation (Stage 2)
│   └── solver.py             # Unified solver interface
│
└── utils/
    ├── distance.py           # Distance/path utilities
    ├── explainability.py     # Natural language allocation explanations
    └── metrics.py            # Performance metrics (response time, unmet demand, etc.)
├── scripts/
│   └── sync_backend.py       # Safe, opt-in pre-sync test verification and GitHub push
├── test_simulation.py        # Stage 1 Simulation layer test
├── test_optimization.py      # Stage 2 Optimization & Benchmark test
├── test_dynamic_simulation.py # Dynamic events & re-optimization test (8 tests)
└── test_comprehensive.py     # Comprehensive mathematical & edge-case audit test suite (43 tests)
```

---

## Installation

```bash
pip install -r requirements.txt
```

> **Python 3.9+** required.

---

## Running Verification Tests

Run each test suite independently or together:

```bash
# 1. Campus simulation, travel times, and resource lifecycle
python test_simulation.py

# 2. Side-by-side Greedy vs QUBO benchmark across Alpha, Beta, Gamma, Stress
python test_optimization.py

# 3. Dynamic events (new emergencies, road blocks, resource shifts, resolution)
python test_dynamic_simulation.py

# 4. Comprehensive audit suite (QUBO math, capacity trimming, edge cases, immutability)
python test_comprehensive.py
```

---

## Solvers & Mathematical Formulation

### 1. Greedy Baseline Solver (`optimization/baseline.py`)
Deterministic, priority-ordered allocation algorithm:
- Ranks active emergencies descending by composite priority score:
  `Priority = (Severity * 3.0) + (People * 0.1) - (TravelTime / 10.0) - (ResourceReq * 0.05)`
- Greedily allocates available resources up to each emergency's requirements.
- Strictly respects capacity limits without mutating input simulation state.

### 2. QUBO Solver (`optimization/qubo.py`)
Formulates the resource triage as a Binary Quadratic Model (BQM):
- **Decision variables**: $x_{i, r, k} \in \{0, 1\}$ representing whether emergency $i$ receives candidate level $k$ for resource $r$.
- **One-hot penalty**: For each $(i, r)$ pair, exactly one candidate level must be selected:
  $$P_{\text{onehot}} \left(\sum_k x_{i, r, k} - 1\right)^2 = -P_{\text{onehot}} \sum_k x_{i, r, k} + 2 P_{\text{onehot}} \sum_{j < k} x_{i, r, j} x_{i, r, k}$$
- **Capacity penalty**: Quadratic pairwise penalty applied to pairs of allocations across emergencies that together exceed pool capacity.
- **Formulation Limitation Note**: Pairwise quadratic terms cannot strictly constrain combinations of three or more emergencies without auxiliary slack variables. When 3+ emergencies each request resources within pairwise limits but collectively exceed capacity, the **post-sampling decoder** trims excess starting from lowest-severity emergencies.
- **Classical CPU Sampler**: Uses `neal.SimulatedAnnealingSampler` running classical CPU Simulated Annealing (heuristic classical search, NOT quantum hardware).
- **Transparency**: The solver reports both `raw_sample_feasible` (whether the raw SA sample satisfied capacity) and `final_allocation_feasible` (after decoder verification) along with execution timing breakdown (`qubo_formulation_time_ms`, `bqm_construction_time_ms`, `sampler_time_ms`, `decode_time_ms`, `total_solve_time_ms`).

---

## Safe GitHub Synchronization (`scripts/sync_backend.py`)

To ensure only verified, passing code reaches GitHub without accidental pushes to `main` or committing sensitive files:

```bash
# Pre-flight check (runs all 4 test suites without committing)
python scripts/sync_backend.py --dry-run

# Full verify and sync to origin/backend-optimization
python scripts/sync_backend.py -m "Your commit message"
```

Safety features:
- Verifies current branch is strictly `backend-optimization`.
- Aborts if any test fails across all 4 test suites.
- Aborts if unmerged git conflicts or forbidden files (`.env`, secrets, virtualenvs) are found.
- Never force-pushes or rewrites published history.

---

## Running — Stage 3 (Streamlit UI)

```bash
streamlit run app.py
```

---

## Stage Roadmap

| Stage | Status | Description |
|---|---|---|
| **1 — Simulation** | ✅ Complete | Campus graph, scenarios, resources, travel times |
| **2 — Optimisation** | ✅ Complete | Greedy baseline + QUBO solver with dimod/neal + comprehensive tests |
| **3 — Streamlit UI** | 🔲 Planned | Interactive dashboard, map, metrics, comparison |

---

## Key Design Decisions

- **Reproducible**: Fixed random seeds guarantee deterministic results across runs.
- **Fair Benchmarking**: Independent scenario copies for both solvers; no hidden greedy passes inside the QUBO decoder.
- **State Immutability**: Neither solver mutates the underlying simulation state during optimization.
- **Local Classical Execution**: No quantum cloud required; runs locally via D-Wave `neal`.

