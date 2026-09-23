"""Tipster dashboard entry point: page config and navigation.

Run from the repo root with ``just start`` (or ``just run-ui``). Each page
lives in ``pages/``; ``st.navigation`` sets their names, icons, grouping
and order (it also turns off Streamlit's automatic ``pages/`` discovery).
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Football Tipster", page_icon="⚽", layout="wide")

st.navigation(
    {
        "": [st.Page("pages/home.py", title="Home", icon=":material/home:", default=True)],
        "Find bets": [
            st.Page(
                "pages/3_Predict_Fixtures.py",
                title="Predict fixtures",
                icon=":material/sports_soccer:",
            ),
            st.Page("pages/1_Value_Finder.py", title="Value finder", icon=":material/trending_up:"),
        ],
        "Track": [
            st.Page("pages/2_Bet_Log.py", title="Bet log", icon=":material/receipt_long:"),
        ],
    }
).run()
