"""Home — what the tipster does, where to start, and how fresh its data is."""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

import polars as pl
import streamlit as st

from tipster_core import bet_log
from tipster_core.leagues import LeagueCode
from tipster_core.storage import DEFAULT_DB_PATH, connect, league_summary, recent_matches
from tipster_ui.shared import REGIONS

#: Results older than this get a "run just ingest" nudge.
_STALE_AFTER_DAYS = 7
_CARD_HEIGHT = 210

st.title("⚽ Football Tipster")
st.caption(
    "Price, don't predict: find bets where the bookmaker pays more than the "
    "model thinks a result is worth. Club and international football."
)

if not Path(DEFAULT_DB_PATH).exists():
    st.info(
        "**Getting started**\n\n"
        "1. In a terminal in the project folder, run `just start`. The first run "
        "downloads about 40 competitions (a few minutes).\n"
        "2. Reload this page.\n\n"
        "For live odds, also copy `.env.example` to `.env` and set `THE_ODDS_API_KEY`."
    )
    st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def _summary() -> pl.DataFrame:
    con = connect(DEFAULT_DB_PATH, read_only=True)
    try:
        return league_summary(con)
    finally:
        con.close()


@st.cache_data(ttl=300, show_spinner=False)
def _recent(league_codes: tuple[str, ...], n: int = 15) -> pl.DataFrame:
    con = connect(DEFAULT_DB_PATH, read_only=True)
    try:
        return recent_matches(con, n=n, leagues=[LeagueCode(code) for code in league_codes])
    finally:
        con.close()


def _bets() -> bet_log.BetLogSummary | None:
    """The ledger summary, without creating an empty ledger just by visiting."""
    if not bet_log.DEFAULT_BET_LOG_PATH.exists():
        return None
    con = bet_log.connect()
    try:
        return bet_log.summarize(con)
    finally:
        con.close()


def _ago(moment: date) -> str:
    days = (date.today() - moment).days
    if days <= 0:
        return "today"
    return "yesterday" if days == 1 else f"{days} days ago"


# --- What do you want to do? -------------------------------------------------

predict, value, log = st.columns(3)
with predict.container(border=True, height=_CARD_HEIGHT):
    st.markdown("#### :material/sports_soccer: Predict fixtures")
    st.write("Paste a list of games — club or international — and get win, draw and loss chances.")
    st.page_link(
        "pages/3_Predict_Fixtures.py", label="Predict games", icon=":material/arrow_forward:"
    )

with value.container(border=True, height=_CARD_HEIGHT):
    st.markdown("#### :material/trending_up: Value finder")
    st.write("Live bookmaker odds against the model — only bets worth taking.")
    if os.environ.get("THE_ODDS_API_KEY"):
        st.badge("Live odds on", icon=":material/check_circle:", color="green")
    else:
        st.badge("No API key: cached odds only", icon=":material/warning:", color="orange")
    st.page_link("pages/1_Value_Finder.py", label="Find value", icon=":material/arrow_forward:")

with log.container(border=True, height=_CARD_HEIGHT):
    st.markdown("#### :material/receipt_long: Bet log")
    bets = _bets()
    if bets is None or bets.n_pending + bets.n_settled == 0:
        st.write("No bets logged yet. Tick tips on the other pages to paper-trade them.")
    else:
        st.write(f"**{bets.n_pending}** pending · **{bets.n_settled}** settled")
        if bets.clv.n:
            st.write(
                f"Beat the closing price on **{bets.clv.beat_rate:.0%}** of bets "
                f"(CLV {bets.clv.mean_clv_pct:+.1f}%)"
            )
    st.page_link("pages/2_Bet_Log.py", label="Open bet log", icon=":material/arrow_forward:")

# --- Data status ----------------------------------------------------------------

summary = _summary()
if summary.is_empty():
    st.warning("The database is empty. Run `just ingest` in the project folder.")
    st.stop()

latest: date = summary["last_date"].max()  # type: ignore[assignment]
last_ingest: datetime = summary["last_ingest"].max()  # type: ignore[assignment]

matches, competitions, newest, updated = st.columns(4)
matches.metric("Matches", f"{summary['matches'].sum():,}")
competitions.metric("Competitions", summary.height)
newest.metric("Latest result", latest.strftime("%d %b %Y"))
updated.metric("Data updated", _ago(last_ingest.date()))

if (date.today() - latest).days > _STALE_AFTER_DAYS:
    st.warning(
        f"The newest result is {_ago(latest)}. Run `just ingest` to pull the latest "
        "results — predictions and bet settlement both depend on them.",
        icon=":material/update:",
    )

# --- Coverage by region ------------------------------------------------------------

st.subheader("What's covered")
region = st.segmented_control(
    "Region", list(REGIONS), default=next(iter(REGIONS)), label_visibility="collapsed"
) or next(iter(REGIONS))
codes = tuple(league.value for league in REGIONS[region])

rows = summary.filter(pl.col("league").is_in(codes))
if rows.is_empty():
    st.info(f"No {region} data yet. Run `just ingest`.")
else:
    order = {code: i for i, code in enumerate(codes)}
    rows = rows.with_columns(
        pl.col("league")
        .replace_strict({c: LeagueCode(c).label for c in codes})
        .alias("Competition"),
        pl.col("league").replace_strict(order).alias("_order"),
    ).sort("_order")
    left, right = st.columns(2)
    with left:
        st.dataframe(
            rows.select(
                "Competition",
                pl.col("seasons").alias("Seasons"),
                pl.col("matches").alias("Matches"),
                pl.col("last_date").alias("Latest match"),
            ),
            hide_index=True,
            column_config={"Latest match": st.column_config.DateColumn(format="D MMM YYYY")},
        )
    with right:
        recent = _recent(codes)
        st.dataframe(
            pl.DataFrame(
                {
                    "Date": recent["date"],
                    "Competition": [LeagueCode(c).label for c in recent["league"]],
                    "Result": [
                        f"{r['home_team']} {r['home_goals']}-{r['away_goals']} {r['away_team']}"
                        for r in recent.iter_rows(named=True)
                    ],
                }
            ),
            hide_index=True,
            column_config={"Date": st.column_config.DateColumn(format="D MMM")},
        )

with st.expander("How it works", icon=":material/help:"):
    st.markdown(
        """
        1. **Get data** — `just start` (first time) or `just ingest` (to refresh)
           downloads results for every competition.
        2. **Price games** — *Predict fixtures* for any list of games, or
           *Value finder* for live bookmaker odds. A tip appears when the odds pay
           more than the model's probability says they should.
        3. **Log bets** — tick the tips you'd take. Everything is paper-traded.
        4. **Settle** — after the games, run `just ingest`, then *Settle* on the
           Bet log. Judge it by closing-line value, not short-term profit.

        Probabilities, not certainties: even good models pick the right result
        only about half the time.
        """
    )
