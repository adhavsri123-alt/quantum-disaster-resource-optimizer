# QDO System — Step-by-Step Live Demonstration Guide

This guide provides the exact demonstration flow for the **Quantum Disaster Resource Optimizer (QDO)**, highlighting:
1. **Targeted Incident Addition**: Only the exact buildings you add an incident to are affected (no automatic scenario override).
2. **Live Visual Paths**: Dynamic glowing 3D energy conduit arcs + ground laser lines physically connect **Amenity Center** to each affected building in real time.
3. **Dedicated Simulation Execution**: Clicking **"Run Simulation"** operates the solver specifically for those active buildings and dispatches fleet vehicles to resolve them.

---

## 🚀 Quick Prerequisites Check
1. **Python FastAPI Backend**: Running on port 8000:
   ```bash
   python -m uvicorn server:app --reload --port 8000
   ```
2. **Web Frontend**: Running on port 3000 (open [http://localhost:3000/#](http://localhost:3000/#) or `index.html` in browser).

---

## 📋 Recommended Live Demonstration Walkthrough

### Step 1: Initial Clean State (All Buildings Normal / No Threat)
- **What to observe:**
  - On page load, all campus buildings are **100% SECURE**.
  - All location pins across campus are **Green (Level 0 · Normal)**.
  - Active Incidents KPI reads `0`.
  - Fleet readiness reads `100% Ready` (all vehicles stationed at the depot).
  - No active energy paths exist on the map.
- **Action to show:**
  - Hover over **Block 17** or **Heritage Block**:
    - Status: `SECURE` (Green badge)
    - Danger Meter: Safe green (0 / 5)
    - Active Incidents: `None`

---

### Step 2: Add Incident to 1st Building (Witness Live Path from Amenity Center)
- **Action:**
  - Under **"Report incident"**:
    - Select **Location**: `Block 17`
    - **Type**: `Fire`, **Severity**: `4`, **People Affected**: `40`
    - Click **"Add incident"**
- **What happens immediately in the 3D Model:**
  - **Only Block 17** is affected.
  - An emergency ring appears at the base of Block 17.
  - The pin on Block 17 turns **Red (Critical/High Hazard)** with a pulsing beacon.
  - **A live, glowing 3D cyan energy conduit arc + ground laser line instantly illuminates, connecting Amenity Center directly to Block 17!**
  - Energy packets visibly stream along the conduit from Amenity Center toward Block 17.
  - Fleet vehicles remain stationed at the depot waiting for your simulation command.

---

### Step 3: Add Incident to 2nd Building (Second Live Path Appears)
- **Action:**
  - Under **"Report incident"**:
    - Select **Location**: `Heritage Block`
    - **Type**: `Accident`, **Severity**: `2`, **People Affected**: `6`
    - Click **"Add incident"**
- **What happens immediately:**
  - **Only Heritage Block** is affected (along with Block 17).
  - The pin on Heritage Block shifts to **Yellow (Elevated)**.
  - **A second distinct live conduit path instantly branches out from Amenity Center to Heritage Block!**
  - Now, two separate glowing routes radiate from Amenity Center to both incident sites.

---

### Step 4: Add Incident to 3rd Building (Optional)
- **Action:**
  - Select **Location**: `Sagar Hospital` (or `Auditorium`)
  - **Type**: `Medical`, **Severity**: `5`, **People**: `50` ➔ Click **"Add incident"**
- **What happens:**
  - A third glowing route branches from Amenity Center directly to Sagar Hospital.
  - Active Incidents count reads `3`.

---

### Step 5: Update Fleet Capacity & Choose Solver
- **Action:**
  - Under **"Fleet inventory & capacity"**, set Ambulances to `4` and click **"Update Fleet Capacity"**.
  - Under **"Optimizer & Solver"**, choose **QUBO Solver** (or **Greedy**).
  - The button reads: **`▶️ Run Simulation (QUBO Solver)`**.

---

### Step 6: Click "Run Simulation" (Execution & Resolution)
- **Action:**
  - Click the **"Run Simulation"** button.
- **What happens:**
  - Fleet vehicles dispatch along the road network specifically to the affected buildings (Block 17, Heritage Block, Sagar Hospital).
  - The live paths from Amenity Center to those buildings remain illuminated while emergency personnel work.
  - As each building's incident is resolved:
    - The building's emergency ring clears.
    - Its pin turns back to **Green (SECURE)**.
    - **Its live path from Amenity Center gracefully disappears!**
  - Once all incidents are resolved, the campus returns to 100% normal and secure.
