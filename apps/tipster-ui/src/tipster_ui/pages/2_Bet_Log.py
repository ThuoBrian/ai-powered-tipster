"""Bet log — Phase 2: the paper-trading ledger (docs/design.md, ADR 0009).

Every tip logged from the Value Finder page lands here. Settlement checks
pending bets against played matches already ingested into the matches
DuckDB; a bet whose match hasn't been (re-)ingested yet stays pending.
Kelly and flat-stake profit are tracked side by side, exactly as the
walk-forward backtest judges arms — profit is the bonus, CLV is the
honest scoreboard (docs/design.md).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import streamlit as st

from tipster_core import bet_log
from tipster_core.storage import DEFAULT_DB_PATH, connect, load_match_results

st.title("Bet Log")
st.caption(
    "Paper-traded tips: fractional-Kelly stake vs. a flat 1-unit control arm, "
    "judged by ROI and closing-line value (docs/design.md)."
)

con = bet_log.connect()

if st.button("Settle pending bets now"):
    if not Path(DEFAULT_DB_PATH).exists():
        st.warning("No matches database yet — run `just ingest` first.")
    else:
        match_con = connect(DEFAULT_DB_PATH, read_only=True)
        try:
            played = load_match_results(match_con)
        finally:
            match_con.close()
        settled_count = bet_log.settle_bets(con, played)
        st.success(f"Settled {settled_count} bet(s).")

summary = bet_log.summarize(con)

col1, col2, col3 = st.columns(3)
col1.metric("Pending", summary.n_pending)
col2.metric("Settled", summary.n_settled)
col3.metric(
    "CLV (mean, beat rate)",
    f"{summary.clv.mean_clv_pct:+.2f}%" if summary.clv.n else "—",
    f"beat rate {summary.clv.beat_rate:.0%} on {summary.clv.n}" if summary.clv.n else "no data yet",
)

col1, col2 = st.columns(2)
with col1:
    st.subheader("Kelly (fractional)")
    st.metric("Staked", f"{summary.kelly.total_staked:.3f}u")
    st.metric("Profit", f"{summary.kelly.total_profit:+.3f}u")
    st.metric("ROI", f"{summary.kelly.roi_pct:+.2f}%")
with col2:
    st.subheader("Flat (control arm)")
    st.metric("Staked", f"{summary.flat.total_staked:.2f}u")
    st.metric("Profit", f"{summary.flat.total_profit:+.2f}u")
    st.metric("ROI", f"{summary.flat.roi_pct:+.2f}%")

bets = bet_log.all_bets(con)
con.close()

if not bets:
    st.info("No bets logged yet — take a tip from the Value Finder page.")
    st.stop()


def _bets_frame(rows: list[bet_log.LoggedBet]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "placed": [b.placed_at for b in rows],
            "fixture": [b.fixture_label for b in rows],
            "date": [b.match_date for b in rows],
            "model": [b.model for b in rows],
            "pick": [b.pick for b in rows],
            "odds": [b.odds for b in rows],
            "source": [b.odds_source for b in rows],
            "EV %": [round(b.ev * 100, 1) for b in rows],
            "kelly stake": [round(b.kelly_stake, 4) for b in rows],
            "won": [b.won for b in rows],
            "kelly profit": [
                round(b.kelly_profit, 4) if b.kelly_profit is not None else None for b in rows
            ],
            "flat profit": [
                round(b.flat_profit, 2) if b.flat_profit is not None else None for b in rows
            ],
            "CLV %": [round(b.clv_pct, 2) if b.clv_pct is not None else None for b in rows],
        }
    )


pending = [b for b in bets if b.settled_at is None]
settled = [b for b in bets if b.settled_at is not None]

st.subheader(f"Pending ({len(pending)})")
if pending:
    st.dataframe(_bets_frame(pending))
else:
    st.caption("Nothing pending.")

st.subheader(f"Settled ({len(settled)})")
if settled:
    st.dataframe(_bets_frame(settled))
else:
    st.caption("Nothing settled yet.")
