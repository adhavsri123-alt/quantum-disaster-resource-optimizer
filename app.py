"""
app.py
------
Streamlit Dashboard for the Quantum Disaster Resource Optimizer (QDO).

Secured with Twilio Verify SMS OTP Authentication.
Unauthenticated users cannot access dashboard functionality, simulation data,
or solver operations.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from auth import (
    is_authenticated,
    render_authenticated_navbar,
    render_login_page,
)
from simulation.simulation import SimulationState, create_simulation
from simulation.dynamic import DynamicSimulation
from simulation.emergencies import AllocationRecord
from simulation.resources import RESOURCE_TYPES
from data.campus import LOCATIONS, _EDGES
from data.scenarios import DEFAULT_RESOURCES, SCENARIO_REGISTRY
from optimization.baseline import GreedyBaselineSolver
from optimization.qubo import QUBOSolver
from utils.explainability import generate_allocation_explanations


# ---------------------------------------------------------------------------
# Page Configuration & Master Theme
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="QDO — Quantum Disaster Resource Optimizer",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling for Dashboard
DASHBOARD_CSS = """
<style>
/* Main Dark Navy Intelligence Theme */
.stApp {
    background-color: #0A1128;
    color: #F8FAFC;
}
[data-testid="stSidebar"] {
    background-color: #0F172A;
    border-right: 1px solid rgba(0, 240, 255, 0.15);
}
.metric-card {
    background: linear-gradient(135deg, rgba(16, 31, 66, 0.8) 0%, rgba(10, 17, 40, 0.9) 100%);
    border: 1px solid rgba(0, 240, 255, 0.2);
    border-radius: 8px;
    padding: 1rem 1.2rem;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}
.metric-title {
    font-size: 0.8rem;
    color: #94A3B8;
    text-transform: uppercase;
    letter-spacing: 1px;
    font-weight: 600;
}
.metric-value {
    font-size: 1.6rem;
    font-weight: 800;
    color: #00F0FF;
    margin-top: 0.2rem;
}
.metric-sub {
    font-size: 0.75rem;
    color: #64748B;
}
.status-pill-active {
    display: inline-block;
    padding: 3px 10px;
    background: rgba(16, 185, 129, 0.15);
    border: 1px solid #10B981;
    color: #10B981;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 700;
}
.status-pill-blocked {
    display: inline-block;
    padding: 3px 10px;
    background: rgba(239, 68, 68, 0.15);
    border: 1px solid #EF4444;
    color: #EF4444;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 700;
}
</style>
"""
st.markdown(DASHBOARD_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Authentication Guard
# ---------------------------------------------------------------------------

# Halt execution immediately if not verified through Twilio Verify SMS
if not render_login_page():
    st.stop()

# Render top navigation bar with responder profile & sign-out control
render_authenticated_navbar()


# ---------------------------------------------------------------------------
# Helper: Plotly Campus Map Visualizer
# ---------------------------------------------------------------------------

def render_campus_network_map(
    state: SimulationState,
    blocked_edges: Optional[List[Tuple[str, str]]] = None,
) -> go.Figure:
    """Build an interactive Plotly graph of the campus road network and incident sites."""
    fig = go.Figure()
    blocked_set = set()
    if blocked_edges:
        for u, v in blocked_edges:
            blocked_set.add((u, v))
            blocked_set.add((v, u))

    # 1. Road Edges
    for u, v, dist in _EDGES:
        if u not in LOCATIONS or v not in LOCATIONS:
            continue
        loc_u = LOCATIONS[u]
        loc_v = LOCATIONS[v]
        is_blocked = (u, v) in blocked_set

        line_color = "#EF4444" if is_blocked else "#334155"
        line_width = 3 if is_blocked else 2
        line_dash = "dash" if is_blocked else "solid"

        fig.add_trace(
            go.Scatter(
                x=[loc_u.x, loc_v.x],
                y=[loc_u.y, loc_v.y],
                mode="lines",
                line=dict(color=line_color, width=line_width, dash=line_dash),
                hoverinfo="text",
                hovertext=f"Road: {loc_u.name} ↔ {loc_v.name} ({dist}m){' [BLOCKED]' if is_blocked else ''}",
                showlegend=False,
            )
        )

    # 2. Campus Building Nodes
    node_x = [loc.x for loc in LOCATIONS.values()]
    node_y = [loc.y for loc in LOCATIONS.values()]
    node_names = [f"{loc.name} ({loc.id})" for loc in LOCATIONS.values()]

    fig.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            marker=dict(size=14, color="#00F0FF", line=dict(color="#0A1128", width=2)),
            text=[loc.name for loc in LOCATIONS.values()],
            textposition="top center",
            textfont=dict(color="#CBD5E1", size=11),
            hoverinfo="text",
            hovertext=node_names,
            name="Campus Facilities",
        )
    )

    # 3. Emergency Incident Sites
    active_ems = state.active_emergencies
    if active_ems:
        em_x = []
        em_y = []
        em_text = []
        em_colors = []
        em_sizes = []

        type_color_map = {
            "fire": "#EF4444",
            "medical_emergency": "#F97316",
            "accident": "#FBBF24",
            "flood_infrastructure": "#06B6D4",
        }

        for em in active_ems:
            loc = LOCATIONS.get(em.location_id)
            if loc:
                em_x.append(loc.x)
                em_y.append(loc.y)
                em_colors.append(type_color_map.get(em.emergency_type, "#EF4444"))
                em_sizes.append(18 + em.severity * 2)
                em_text.append(
                    f"<b>[{em.id}] {em.type_label}</b><br>"
                    f"Location: {loc.name}<br>"
                    f"Severity: {em.severity}/10 | Casualties: {em.people_affected}<br>"
                    f"Demands: Amb:{em.ambulances_required} Res:{em.rescue_teams_required} "
                    f"Sup:{em.medical_supplies_required} Per:{em.medical_personnel_required}"
                )

        fig.add_trace(
            go.Scatter(
                x=em_x,
                y=em_y,
                mode="markers",
                marker=dict(
                    symbol="star",
                    size=em_sizes,
                    color=em_colors,
                    line=dict(color="#FFFFFF", width=1.5),
                ),
                hoverinfo="text",
                hovertext=em_text,
                name="Active Incidents",
            )
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(10, 17, 40, 0.8)",
        plot_bgcolor="rgba(15, 23, 42, 0.6)",
        xaxis=dict(showgrid=True, gridcolor="#1E293B", zeroline=False, title="East-West (m)"),
        yaxis=dict(showgrid=True, gridcolor="#1E293B", zeroline=False, title="North-South (m)"),
        margin=dict(l=20, r=20, t=30, b=20),
        height=480,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


# ---------------------------------------------------------------------------
# Sidebar Controls & Scenario Selection
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 🎛️ Incident Scenario")
    scenario_choice = st.selectbox(
        "Active Disaster Scenario",
        options=["ALPHA", "BETA", "GAMMA", "STRESS"],
        index=1,
        help="Select a benchmark disaster scenario.",
    )

    sc_fn = SCENARIO_REGISTRY[scenario_choice.lower()]
    scenario_data = sc_fn()

    st.caption(f"**Description:** {scenario_data.description}")
    if scenario_data.blocked_routes:
        st.markdown(
            f"<div class='status-pill-blocked'>🚫 Blocked Routes: {len(scenario_data.blocked_routes)}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown("<div class='status-pill-active'>🟢 All Corridors Open</div>", unsafe_allow_html=True)

    st.divider()

    st.markdown("### ⚙️ Solver Configuration")
    solver_mode = st.radio(
        "Solver Mode",
        options=["Side-by-Side Comparison", "Greedy Baseline Only", "QUBO Optimizer Only"],
        index=0,
    )

    qubo_reads = st.slider("Simulated Annealing Reads", min_value=100, max_value=1000, value=500, step=100)
    qubo_seed = st.number_input("RNG Seed", value=42, step=1)

    run_clicked = st.button("🚀 Run Resource Optimization", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Simulation State Setup
# ---------------------------------------------------------------------------

state = SimulationState(scenario_data, DEFAULT_RESOURCES)
active_emergencies = state.active_emergencies
caps = state.resource_manager.capacity()


# ---------------------------------------------------------------------------
# Main Dashboard Tabs
# ---------------------------------------------------------------------------

tab_command, tab_opt, tab_dynamic = st.tabs([
    "📍 Incident Command & Campus Map",
    "⚡ Optimization & Comparison",
    "🔄 Dynamic Contingency Simulation",
])


# ---------------------------------------------------------------------------
# TAB 1: Incident Command & Campus Map
# ---------------------------------------------------------------------------

with tab_command:
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f"""<div class="metric-card">
                <div class="metric-title">Active Emergencies</div>
                <div class="metric-value">{len(active_emergencies)}</div>
                <div class="metric-sub">Across Campus Grounds</div>
            </div>""",
            unsafe_allow_html=True,
        )
    with c2:
        tot_people = sum(e.people_affected for e in active_emergencies)
        st.markdown(
            f"""<div class="metric-card">
                <div class="metric-title">Population Impact</div>
                <div class="metric-value">{tot_people}</div>
                <div class="metric-sub">Casualties & Trapped Persons</div>
            </div>""",
            unsafe_allow_html=True,
        )
    with c3:
        crit_count = sum(1 for e in active_emergencies if e.severity >= 7)
        st.markdown(
            f"""<div class="metric-card">
                <div class="metric-title">Critical Incidents</div>
                <div class="metric-value">{crit_count}</div>
                <div class="metric-sub">Severity ≥ 7 / 10</div>
            </div>""",
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f"""<div class="metric-card">
                <div class="metric-title">Emergency Fleet</div>
                <div class="metric-value">{caps['ambulances']} / {caps['rescue_teams']}</div>
                <div class="metric-sub">Ambulances / Rescue Teams</div>
            </div>""",
            unsafe_allow_html=True,
        )

    st.markdown("#### 🗺️ Campus Road Network & Incident Map")
    map_fig = render_campus_network_map(state, scenario_data.blocked_routes)
    st.plotly_chart(map_fig, use_container_width=True)

    st.markdown("#### 📋 Active Incident Queue")
    em_table_data = []
    for em in active_emergencies:
        loc_name = LOCATIONS[em.location_id].name if em.location_id in LOCATIONS else em.location_id
        tt = state.travel_time("main_gate", em.location_id)
        tt_str = f"{tt:.2f} min" if not math.isinf(tt) else "BLOCKED"
        em_table_data.append({
            "Incident ID": em.id,
            "Type": em.type_label,
            "Location": loc_name,
            "Severity": f"{em.severity}/10",
            "Casualties": em.people_affected,
            "Depot Travel Time": tt_str,
            "Amb Req": em.ambulances_required,
            "Rescue Req": em.rescue_teams_required,
            "Supplies Req": em.medical_supplies_required,
            "Personnel Req": em.medical_personnel_required,
        })
    st.dataframe(pd.DataFrame(em_table_data), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# TAB 2: Optimization Engine & Solver Comparison
# ---------------------------------------------------------------------------

with tab_opt:
    st.markdown("### ⚡ Resource Dispatch Optimization")
    st.caption(
        "Solves the disaster resource allocation problem by balancing response time, "
        "severity-weighted unmet demand, and capacity limits. Classical CPU Simulated Annealing via `neal`."
    )

    greedy_solver = GreedyBaselineSolver()
    qubo_solver = QUBOSolver(num_reads=qubo_reads, seed=qubo_seed)

    # Solve on fresh states
    state_greedy = SimulationState(scenario_data, DEFAULT_RESOURCES)
    plan_greedy = greedy_solver.solve(state_greedy)

    state_qubo = SimulationState(scenario_data, DEFAULT_RESOURCES)
    plan_qubo = qubo_solver.solve(state_qubo)

    m_g = plan_greedy.metrics
    m_q = plan_qubo.metrics
    meta_q = plan_qubo.solver_metadata

    # Metric Comparison Cards
    mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
    with mcol1:
        st.metric(
            label="Unmet Demand %",
            value=f"{m_q['unmet_demand_fraction']*100:.1f}%",
            delta=f"{(m_g['unmet_demand_fraction'] - m_q['unmet_demand_fraction'])*100:+.1f}% vs Greedy",
            delta_color="inverse",
        )
    with mcol2:
        st.metric(
            label="Severity-Weighted Unmet",
            value=f"{m_q['severity_weighted_unmet_demand_fraction']*100:.1f}%",
            delta=f"{(m_g['severity_weighted_unmet_demand_fraction'] - m_q['severity_weighted_unmet_demand_fraction'])*100:+.1f}% vs Greedy",
            delta_color="inverse",
        )
    with mcol3:
        st.metric(
            label="Critical Incident Coverage",
            value=f"{m_q['critical_coverage_score']*100:.1f}%",
            delta=f"{(m_q['critical_coverage_score'] - m_g['critical_coverage_score'])*100:+.1f}% vs Greedy",
        )
    with mcol4:
        st.metric(
            label="Avg Response Time",
            value=f"{m_q['avg_response_time_min']:.2f} min",
            delta=f"{m_q['avg_response_time_min'] - m_g['avg_response_time_min']:+.2f} min vs Greedy",
            delta_color="inverse",
        )
    with mcol5:
        st.metric(
            label="Avg Resource Utilization",
            value=f"{m_q['avg_utilisation']*100:.1f}%",
            delta=f"{(m_q['avg_utilisation'] - m_g['avg_utilisation'])*100:+.1f}% vs Greedy",
        )

    st.markdown("#### 📊 Side-by-Side Performance Comparison")
    comp_df = pd.DataFrame([
        {
            "Solver": "Greedy Baseline",
            "Unmet Demand %": f"{m_g['unmet_demand_fraction']*100:.2f}%",
            "Sev-Weighted Unmet %": f"{m_g['severity_weighted_unmet_demand_fraction']*100:.2f}%",
            "Crit Coverage %": f"{m_g['critical_coverage_score']*100:.1f}%",
            "Avg Response (min)": f"{m_g['avg_response_time_min']:.2f}",
            "Max Response (min)": f"{m_g['max_response_time_min']:.2f}",
            "Utilisation %": f"{m_g['avg_utilisation']*100:.1f}%",
            "Objective Score": f"{m_g['weighted_objective']:.4f}",
            "Solve Time (ms)": f"{plan_greedy.solver_metadata.get('solve_time_ms', 0):.2f}",
            "Feasibility": "Feasible",
        },
        {
            "Solver": "QUBO Optimizer (SA)",
            "Unmet Demand %": f"{m_q['unmet_demand_fraction']*100:.2f}%",
            "Sev-Weighted Unmet %": f"{m_q['severity_weighted_unmet_demand_fraction']*100:.2f}%",
            "Crit Coverage %": f"{m_q['critical_coverage_score']*100:.1f}%",
            "Avg Response (min)": f"{m_q['avg_response_time_min']:.2f}",
            "Max Response (min)": f"{m_q['max_response_time_min']:.2f}",
            "Utilisation %": f"{m_q['avg_utilisation']*100:.1f}%",
            "Objective Score": f"{m_q['weighted_objective']:.4f}",
            "Solve Time (ms)": f"{meta_q.get('solve_time_ms', 0):.2f}",
            "Feasibility": meta_q.get("feasibility_status", "Feasible"),
        },
    ])
    st.dataframe(comp_df, use_container_width=True, hide_index=True)

    # QUBO Solver Timing Breakdown
    with st.expander("⏱️ QUBO Solve Time & Variable Metadata Breakdown", expanded=False):
        c_t1, c_t2, c_t3, c_t4 = st.columns(4)
        c_t1.metric("Formulation Time", f"{meta_q.get('qubo_formulation_time_ms', 0):.2f} ms")
        c_t2.metric("BQM Construction", f"{meta_q.get('bqm_construction_time_ms', 0):.2f} ms")
        c_t3.metric("SA Sampler (CPU)", f"{meta_q.get('sampler_time_ms', 0):.2f} ms")
        c_t4.metric("Decoding & Repair", f"{meta_q.get('decode_time_ms', 0):.2f} ms")
        st.caption(
            f"**Variables:** {meta_q.get('num_variables', 0)} | "
            f"**Quadratic Couplings:** {meta_q.get('num_quadratic_terms', 0)} | "
            f"**Ground State Energy:** {meta_q.get('energy', 0):.2f}"
        )

    # Detailed Per-Emergency Allocation
    st.markdown("#### 📦 Per-Incident Allocation Plan (Emergency-by-Emergency)")
    alloc_rows = []
    for em in active_emergencies:
        rec_g = plan_greedy.allocations[em.id]
        rec_q = plan_qubo.allocations[em.id]
        loc_name = LOCATIONS[em.location_id].name if em.location_id in LOCATIONS else em.location_id

        alloc_rows.append({
            "ID": em.id,
            "Incident": f"{em.type_label} @ {loc_name}",
            "Sev": em.severity,
            "Required": f"Amb:{em.ambulances_required} Res:{em.rescue_teams_required} Sup:{em.medical_supplies_required} Per:{em.medical_personnel_required}",
            "Greedy Assigned": f"Amb:{rec_g.ambulances_assigned} Res:{rec_g.rescue_teams_assigned} Sup:{rec_g.medical_supplies_assigned} Per:{rec_g.medical_personnel_assigned}",
            "QUBO Assigned": f"Amb:{rec_q.ambulances_assigned} Res:{rec_q.rescue_teams_assigned} Sup:{rec_q.medical_supplies_assigned} Per:{rec_q.medical_personnel_assigned}",
            "Match": "✅ MATCH" if (
                rec_g.ambulances_assigned == rec_q.ambulances_assigned
                and rec_g.rescue_teams_assigned == rec_q.rescue_teams_assigned
                and rec_g.medical_supplies_assigned == rec_q.medical_supplies_assigned
                and rec_g.medical_personnel_assigned == rec_q.medical_personnel_assigned
            ) else "⚡ DIFFERENT",
        })
    st.dataframe(pd.DataFrame(alloc_rows), use_container_width=True, hide_index=True)

    # Explainability Cards
    st.markdown("#### 🧠 Dispatch Explainability & Tactical Rationale")
    explanations = plan_qubo.explanations or generate_allocation_explanations(plan_qubo, state_qubo)
    for em_id, expl in explanations.items():
        with st.expander(f"Incident [{em_id}] Rationale", expanded=False):
            st.write(expl)


# ---------------------------------------------------------------------------
# TAB 3: Dynamic Simulation & Contingency Engine
# ---------------------------------------------------------------------------

with tab_dynamic:
    st.markdown("### 🔄 Real-Time Dynamic Contingency Engine")
    st.caption("Test the impact of unexpected road collapses, newly reported mass casualties, and resource reductions.")

    dyn_engine = DynamicSimulation(create_simulation(scenario_choice.lower(), seed=42))

    col_dyn1, col_dyn2 = st.columns(2)

    with col_dyn1:
        st.markdown("#### 🚧 Block or Unblock Campus Corridors")
        edge_options = [f"{u} ↔ {v}" for u, v, _ in _EDGES]
        selected_edge_str = st.selectbox("Corridor Segment", options=edge_options, key="dyn_edge_select")
        u_sel, v_sel = [s.strip() for s in selected_edge_str.split("↔")]

        col_b1, col_b2 = st.columns(2)
        if col_b1.button("🚫 Block Road Segment", use_container_width=True):
            try:
                dyn_engine.block_road(u_sel, v_sel)
                st.success(f"Corridor between {u_sel} and {v_sel} is now blocked. Dijkstra routing recalculated.")
            except Exception as e:
                st.warning(str(e))

        if col_b2.button("🟢 Clear / Reopen Segment", use_container_width=True):
            try:
                dyn_engine.reopen_road(u_sel, v_sel)
                st.success(f"Corridor between {u_sel} and {v_sel} restored to normal service.")
            except Exception as e:
                st.warning(str(e))

    with col_dyn2:
        st.markdown("#### 🚨 Inject Dynamic Emergency Incident")
        inj_loc = st.selectbox(
            "Incident Location",
            options=list(LOCATIONS.keys()),
            format_func=lambda k: LOCATIONS[k].name,
            key="dyn_inj_loc",
        )
        inj_type = st.selectbox("Type", ["fire", "medical_emergency", "accident", "flood_infrastructure"], key="dyn_inj_type")
        inj_sev = st.slider("Severity Level", 1, 10, 8, key="dyn_inj_sev")
        inj_people = st.number_input("Affected Casualties", min_value=1, max_value=200, value=20, key="dyn_inj_people")

        if st.button("⚡ Inject Incident into Live Queue", type="primary", use_container_width=True):
            new_em = dyn_engine.add_emergency(
                location_id=inj_loc,
                emergency_type=inj_type,
                severity=inj_sev,
                people_affected=inj_people,
                ambulances_required=2,
                rescue_teams_required=1,
                medical_supplies_required=15,
                medical_personnel_required=3,
            )
            st.success(f"Dynamic Incident [{new_em.id}] successfully queued for optimization.")

    st.markdown("#### 🔄 Updated Dynamic Map State")
    dyn_fig = render_campus_network_map(dyn_engine.state, dyn_engine.state.scenario.blocked_routes)
    st.plotly_chart(dyn_fig, use_container_width=True)
