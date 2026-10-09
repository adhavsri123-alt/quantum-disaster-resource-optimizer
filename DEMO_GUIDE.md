# QDO System — Step-by-Step Live Demonstration Guide

This guide provides an exact walkthrough to demonstrate that the **Quantum Disaster Resource Optimizer (QDO)** frontend and backend integration are working correctly.

---

## 🚀 Quick Prerequisites Check
1. **Python FastAPI Backend**: Ensure running on port 8000:
   ```bash
   python -m uvicorn server:app --reload --port 8000
   ```
2. **Web Frontend**: Running on port 3000 (or open `QDO - Campus Emergency Dispatch.html` / `index.html` in browser).

---

## 📋 Step-by-Step Demonstration Walkthrough

### Step 1: Initial State Verification (All Buildings Normal / No Threat)
- **What to observe:**
  - On page load, the 3D campus loads with **no active incidents**.
  - All location pins across campus are **Green (Normal)**.
  - Active Incidents KPI reads `0`.
  - Fleet readiness reads `100% Ready` (all 3 ambulances & 2 rescue teams stationed idle at depot).
  - Activity feed displays: `✓ System initialized: All campus sectors normal. Select a scenario or inject incident to dispatch.`
- **Action to show:**
  - Hover over any building (e.g., **Block 17**, **Auditorium**, or **Heritage Block**).
  - **Result:** The glassmorphic card displays:
    - Status: `SECURE` (Green badge)
    - Threat Level: `Level 0 · Normal`
    - Danger Meter: Safe green level
    - Active Incidents: `None`

---

### Step 2: Role Authentication & Viewer Presence
- **Action:**
  - Click **Role** or **Switch Mode** in the top navigation bar.
  - Choose **Viewer Mode**:
    - Notice only the 3D model canvas is interactive (admin incident injection controls are hidden).
    - Top bar displays: `👁️ Viewer viewing` badge.
  - Switch to **Admin Mode**:
    - Click Admin and enter credentials to authenticate.
    - Top bar immediately displays `🛡️ Admin Active` alongside any connected viewer badges.
    - Incident injection, scenario selectors, and solver algorithm controls unlock.

---

### Step 3: Triggering a Predefined Incident Scenario
- **Action:**
  - In the Scenario panel, click **ALPHA** (or **BETA**, **GAMMA**, **STRESS**).
- **What to observe:**
  - Dynamic emergency rings immediately appear on the campus buildings.
  - Relevant building pins shift from **Green** to **Yellow (Elevated)** or **Red (Critical)**.
  - Hover over an affected building (e.g., Block 17 or Auditorium) to show:
    - Incident type (Fire / Medical / Flood / Accident).
    - Severity score (e.g., `Level 4` or `Level 5`).
    - People affected and requested dispatch demand.

---

### Step 4: Dispatch Execution via Quantum QUBO
- **Action:**
  - Select **Quantum QUBO** solver mode.
  - Watch the dispatch execution:
    - 3D emergency fleet vehicles automatically depart the depot.
    - Blue pulsed Dijkstra navigation routes light up the campus pathways.
    - Vehicles navigate along road networks, reach the target buildings, and resolve the incidents.
    - KPI panel dynamically updates:
      - **Average Response Time**
      - **Critical Sector Coverage (100%)**
      - **Resource Utilization** (Ambulance & Fire/Rescue capacity)

---

### Step 5: Side-by-Side Algorithm Benchmark (QUBO vs. Greedy)
- **Action:**
  - Click the **"Compare Both"** button in the algorithm toggle bar.
- **What to observe in the Modal:**
  - A comprehensive comparison table displays side-by-side:
    - **Neal Simulated Annealing QUBO** vs **Greedy Baseline**.
    - Energy score, variable count ($x_{i,r,k}$ BQM decision variables), quadratic couplings.
    - Formulation time, Sampler execution time, and post-sampling feasibility verification.
    - Average response time reduction and unmet-demand penalty comparisons.
  - **Explainability (XAI) section**:
    - Explains why the QUBO solver selected each allocation based on severity weighting, depot distance, and capacity bottlenecks.

---

### Step 6: Dynamic Real-Time Incident Injection
- **Action:**
  - Select a building from the dropdown (e.g., `Library Block`).
  - Choose Type: `Fire`, Severity: `5`, People Affected: `80`.
  - Click **Inject Emergency** (or click **Random Emergency**).
- **What to observe:**
  - Live incident instantly appears in the 3D scene.
  - Solver re-evaluates the fleet allocation in real time and re-routes idle vehicles.
