"""Tipster dashboard — phase 0: data status.

Run from the repo root with ``make run-ui`` (or
``uv run streamlit run apps/tipster-ui/src/tipster_ui/app.py``). Later
phases add the value finder, backtest, and bankroll pages
(docs/design.md#roadmap).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import streamlit as st

from tipster_core.leagues import LeagueCode, season_label
from tipster_core.storage import DEFAULT_DB_PATH, connect, match_counts, recent_matches

st.set_page_config(page_title="AI Tipster", layout="wide")

st.title("AI-Powered Football Tipster")
st.caption(
    "Price, don't predict — a value-betting engine for European football. Phase 0: data status."
)

_LEAGUE_NAMES = {league.value: league.label for league in LeagueCode}


def _load() -> tuple[list[tuple[str, str, int]], pl.DataFrame] | None:
    """Read coverage and recent matches; None when the database doesn't exist yet."""
    if not Path(DEFAULT_DB_PATH).exists():
        return None
    con = connect(DEFAULT_DB_PATH, read_only=True)
    try:
        return match_counts(con), recent_matches(con, n=25)
    finally:
        con.close()


loaded = _load()
if loaded is None:
    st.info(
        "No database yet. Run `make ingest` from the repo root to pull "
        "football-data.co.uk data into data/tipster.duckdb, then reload this page."
    )
    st.stop()

counts, recent = loaded
total = sum(n for _, _, n in counts)

st.metric("Matches in store", f"{total:,}")

left, right = st.columns([2, 3])

with left:
    st.subheader("Coverage by league and season")
    coverage = pl.DataFrame(
        {
            "league": [code for code, _, _ in counts],
            "league name": [_LEAGUE_NAMES.get(code, code) for code, _, _ in counts],
            "season": [season_label(season) for _, season, _ in counts],
            "matches": [n for _, _, n in counts],
        }
    )
    st.dataframe(coverage, height=min(420, 35 * len(counts) + 48))

with right:
    st.subheader("Most recent matches")
    st.dataframe(recent)

with st.expander("What's next (docs/design.md)"):
    st.markdown(
        """
        - **Phase 1** — feature builder, GBM → Poisson hybrid model,
          walk-forward backtests
        - **Phase 2** — value engine (devig, EV, Kelly), live odds,
          value finder + bet log
        - **Phase 3** — predictor service port, Ollama-generated reasoning
        - **Phase 4** — all leagues live, CLV tracking, Kenya local-book
          comparison
        """
    )
