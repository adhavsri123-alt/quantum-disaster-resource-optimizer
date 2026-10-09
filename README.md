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
    └── metrics.py            # Performance metrics (response time, unmet demand, etc.)
```

---

## Installation

```bash
pip install -r requirements.txt
```

> **Python 3.9+** required.

---

## Running — Stage 1 (Simulation Test)

```bash
# Default: Scenario ALPHA, seed=42
python test_simulation.py

# Scenario BETA
python test_simulation.py --scenario beta

# Scenario GAMMA
python test_simulation.py --scenario gamma

# Random scenario with 4 emergencies, seed=99
python test_simulation.py --scenario random --seed 99 --n 4
```

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
| **2 — Optimisation** | 🔲 Planned | Greedy baseline + QUBO solver with dimod/neal |
| **3 — Streamlit UI** | 🔲 Planned | Interactive dashboard, map, metrics, comparison |

---

## Key Design Decisions

- **Reproducible**: All scenarios use a fixed seed — same input always produces the same scenario.
- **Modular**: Simulation, optimisation, and UI are fully decoupled.
- **Extensible**: New emergency types, locations, or solvers require only adding to the relevant registry dict.
- **No hardcoded results**: All metrics (response time, utilisation) are computed dynamically from the actual allocation.
- **Local-only**: No cloud/QPU dependency — QUBO solved via Simulated Annealing (dwave-neal).
