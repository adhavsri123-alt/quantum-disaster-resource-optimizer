"""
app.py
------
Streamlit entry point for the Quantum Disaster Resource Optimizer (QDO).

Stage 1: Placeholder — will be implemented in Stage 3.

Run:
    streamlit run app.py
"""

import streamlit as st

st.set_page_config(
    page_title="QDO — Quantum Disaster Resource Optimizer",
    page_icon="🚨",
    layout="wide",
)

st.title("🚨 Quantum Disaster Resource Optimizer")
st.markdown(
    """
    **Stage 1 complete** — simulation and data layer are operational.

    The full Streamlit UI will be implemented in **Stage 3**.

    To test the simulation layer, run:
    ```bash
    python test_simulation.py
    python test_simulation.py --scenario beta
    python test_simulation.py --scenario gamma
    python test_simulation.py --scenario random --seed 99 --n 4
    ```
    """
)
