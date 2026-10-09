# QDO System — Step-by-Step Live Demonstration Guide

This guide provides an exact walkthrough to demonstrate that the **Quantum Disaster Resource Optimizer (QDO)** frontend and backend integration are working correctly according to the requested interactive workflow.

---

## 🚀 Quick Prerequisites Check
1. **Python FastAPI Backend**: Running on port 8000:
   ```bash
   python -m uvicorn server:app --reload --port 8000
   ```
2. **Web Frontend**: Running on port 3000 (or open `QDO - Campus Emergency Dispatch.html` / `index.html` in browser).

---

## 📋 Recommended Live Demonstration Workflow

### Step 1: Initial State Verification (All Buildings Normal / No Threat)
- **What to observe:**
  - On page load, all campus buildings are completely **Normal / Safe**.
  - All location pins across campus are **Green (Normal / Secure)**.
  - Active Incidents KPI reads `0`.
  - Fleet readiness reads `100% Ready` (all vehicles stationed idle at the depot).
  - Activity feed displays: `✓ System initialized: All campus sectors normal. Select a scenario or inject incident to dispatch.`
- **Action to show:**
  - Hover over any building (e.g., **Block 17**, **Auditorium**, or **Heritage Block**).
  - **Result:** The glassmorphic card displays:
    - Status: `SECURE` (Green badge)
    - Threat Level: `Level 0 · Normal`
    - Danger Meter: Safe green level (0 / 5)
    - Active Incidents: `None`

---

### Step 2: Add Incidents to Different Blocks (Live Model Reflection: Green ➔ Yellow ➔ Red)
- **Action:**
  1. Under **"Report Incident"**:
     - Choose **Block 17**, Type: **Fire**, Severity: **4**, People Affected: **40**.
     - Click **"Add Incident"**.
     - **Result:**
       - An emergency ring appears around **Block 17**.
       - The pin on Block 17 instantly shifts from **Green** to **Red (Critical/High Hazard)** with a pulsing beacon.
       - The building emits an alert glow.
       - Hovering over Block 17 shows **`HIGH HAZARD`**, **`Level 4`**, and **`Active Fire · 40 affected`**.
       - *Vehicles remain stationed at the depot awaiting the Run Simulation command.*
  2. Repeat for a second block:
     - Choose **Heritage Block**, Type: **Accident**, Severity: **2**, People Affected: **5**.
     - Click **"Add Incident"**.
     - **Result:**
       - Pin turns **Yellow (Elevated)** with yellow beacon.
       - Hover card shows **`MODERATE / ELEVATED`**, **`Level 2`**.
  3. Repeat for a third block:
     - Choose **Sagar Hospital** (or **Auditorium**), Type: **Medical**, Severity: **5**, People Affected: **60**.
     - Click **"Add Incident"**.
     - **Result:**
       - Pin turns **Bright Red (Critical)** with urgent red pulsing beacon.
       - Active Incidents KPI reads `3`.

---

### Step 3: Update Fleet Inventory & Capacity
- **Action:**
  - Under **"Fleet inventory & capacity"**:
    - Increase **Ambulances** to `4` (or adjust Fire Trucks / Security).
    - Click **"Update Fleet Capacity"**.
  - **Result:**
    - The 3D vehicle fleet stationed at the depot updates in real time.
    - Live activity feed logs: `Fleet updated: 4 Ambulances, 2 Fire Trucks, 2 Security. Standing by at depot (Click "Run Simulation" to dispatch).`

---

### Step 4: Choose Optimizer Solver or Preset Scenario
- **Action:**
  - Under **"Optimizer & Solver"**:
    - Select **QUBO Solver** (or **Greedy** or **⚖️ Compare Both**).
    - Notice the **"Run Simulation"** button text dynamically updates:
      - `▶️ Run Simulation (QUBO Solver)`
      - `▶️ Run Simulation (Greedy Solver)`
      - `⚖️ Run Benchmark (Compare Both)`
    - *(Optional)* Click a scenario like **ALPHA**, **BETA**, **GAMMA**, or **STRESS** if you want to load a multi-incident preset.

---

### Step 5: Click "Run Simulation" (Execution & Dispatch)
- **Action:**
  - Click the prominent **"Run Simulation"** button.
- **What happens:**
  - The button activates with a high-tech glowing pulse.
  - The selected solver (Quantum QUBO or Greedy) executes immediately.
  - 3D emergency fleet vehicles dispatch from the depot and navigate along the blue pulsing campus road network.
  - Vehicles arrive at target buildings, perform rescue operations, and resolve incidents.
  - Real-time KPIs update:
    - **Average Response Time**
    - **Critical Sector Coverage (100%)**
    - **Resource Utilization**
  - When incidents at a building are resolved, the emergency ring clears, and the building pin turns **Green (SECURE)** again!

---

### Step 6: Benchmark Comparison Modal (QUBO vs Greedy)
- **Action:**
  - Click **⚖️ Compare Both** and click **"Run Simulation"** (or click the Compare Both button directly).
- **What to observe:**
  - Side-by-side comparison modal displays:
    - Quantum Annealing Energy score.
    - Formulation time, Sampler execution time (FastAPI / neal simulated annealing).
    - Decision variables ($x_{i,r,k}$), quadratic couplers, and post-annealing feasibility repair guarantee.
    - Explainability (XAI) rationale detailing why each allocation was selected.
