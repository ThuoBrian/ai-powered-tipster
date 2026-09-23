"""Value finder — Phase 2: live odds vs. the fitted model (docs/design.md).

Devigs live 1X2 odds (Shin's method), compares against the GBM → Poisson
hybrid's own probabilities, and surfaces positive-EV tips sized by
fractional Kelly (``tipster_core.value``, ADR 0006). Fixtures whose teams
have no history in the store are never priced — a name the alias table
missed (ADR 0008) would otherwise get a confidently wrong, cold-start
prediction instead of a visible warning.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import polars as pl
import streamlit as st

from tipster_core import bet_log
from tipster_core.contracts import Fixture, MatchOdds
from tipster_core.ingest.pipeline import DEFAULT_ODDS_CACHE_DIR, fetch_live_odds
from tipster_core.leagues import BIG_5, LeagueCode
from tipster_core.model.calibration import CalibratedPredictor
from tipster_core.model.hybrid import GbmPoissonPredictor
from tipster_core.storage import DEFAULT_DB_PATH, connect, load_match_results, match_counts
from tipster_core.value import OddsSource, ValueTip, find_value_tips

st.set_page_config(page_title="Value Finder", layout="wide")
st.title("Value Finder")
st.caption(
    "Live 1X2 odds, devigged (Shin's method) and compared against the fitted "
    "model — positive-EV tips, sized by fractional Kelly (docs/design.md)."
)

if not Path(DEFAULT_DB_PATH).exists():
    st.info("No database yet. Run `make ingest` first, then reload this page.")
    st.stop()


@st.cache_resource(show_spinner="Fitting model on historical corpus...")
def _fit_for_league(
    db_path: str, league_value: str, n_matches: int
) -> tuple[CalibratedPredictor, frozenset[str]]:
    """A calibrated predictor fitted on one league's full history, plus its team set.

    Cached on ``n_matches`` so a fresh ``make ingest`` invalidates the cache
    automatically; refitting is a few seconds (ADR 0005), not worth doing on
    every rerun.
    """
    league = LeagueCode.from_code(league_value)
    con = connect(db_path, read_only=True)
    try:
        results = load_match_results(con, leagues=[league])
    finally:
        con.close()
    predictor = CalibratedPredictor(GbmPoissonPredictor())
    predictor.fit(results)
    known_teams = frozenset(m.home_team for m in results) | frozenset(m.away_team for m in results)
    return predictor, known_teams


def _sort_by_ev(tips: Sequence[ValueTip]) -> list[ValueTip]:
    return sorted(tips, key=lambda tip: tip.ev, reverse=True)


def _tips_frame(tips: Sequence[ValueTip]) -> pl.DataFrame:
    """Render *tips* in the given order — callers sort first (``_sort_by_ev``).

    Row order here must match ``tips`` index-for-index: the bet-logging UI
    reads a user's checkbox selections back by row position against this
    same list.
    """
    if not tips:
        return pl.DataFrame(
            schema={
                "fixture": pl.String,
                "date": pl.Date,
                "pick": pl.String,
                "model p": pl.Float64,
                "market fair p": pl.Float64,
                "odds": pl.Float64,
                "source": pl.String,
                "EV %": pl.Float64,
                "kelly stake %": pl.Float64,
            }
        )
    return pl.DataFrame(
        {
            "fixture": [t.fixture.fixture for t in tips],
            "date": [t.fixture.date for t in tips],
            "pick": [t.pick for t in tips],
            "model p": [round(t.p_model, 3) for t in tips],
            "market fair p": [round(t.p_market_fair, 3) for t in tips],
            "odds": [t.odds for t in tips],
            "source": [t.odds_source for t in tips],
            "EV %": [round(t.ev * 100, 1) for t in tips],
            "kelly stake %": [round(t.kelly_stake * 100, 2) for t in tips],
        }
    )


con = connect(DEFAULT_DB_PATH, read_only=True)
try:
    counts = match_counts(con)
finally:
    con.close()

match_totals: dict[str, int] = {}
for code, _season, n in counts:
    match_totals[code] = match_totals.get(code, 0) + n

league_options = [league for league in BIG_5 if match_totals.get(league.value, 0) > 0]
if not league_options:
    st.info("No big-5 league data ingested yet. Run `make ingest` first.")
    st.stop()

with st.sidebar:
    st.header("Settings")
    league = st.selectbox(
        "League", league_options, format_func=lambda code: f"{code.label} ({code.value})"
    )
    ev_threshold = st.slider("Minimum EV", 0.0, 0.20, 0.02, step=0.01)
    kelly_fraction_size = st.slider("Kelly fraction", 0.05, 1.0, 0.25, step=0.05)
    kelly_cap = st.slider("Per-bet stake cap", 0.01, 0.20, 0.05, step=0.01)
    source_choice = st.selectbox("Odds source", ["Auto (ladder)", "pinnacle", "avg", "b365", "max"])
    source: OddsSource | None = None if source_choice == "Auto (ladder)" else source_choice  # type: ignore[assignment]

    st.divider()
    api_key = os.environ.get("THE_ODDS_API_KEY", "")
    if not api_key:
        st.warning("THE_ODDS_API_KEY not set — showing the last cached snapshot, if any.")
    refresh_clicked = st.button("Fetch fresh odds now", disabled=not api_key)

cache_path = DEFAULT_ODDS_CACHE_DIR / f"{league.value}.json"
if not cache_path.exists() and not api_key:
    st.info(
        "No cached odds and no `THE_ODDS_API_KEY` set. Add the key to `.env` "
        "(see `.env.example`), then click **Fetch fresh odds now**, or run `make fetch-odds`."
    )
    st.stop()

try:
    pairs = fetch_live_odds(league, api_key, refresh=refresh_clicked)
except Exception as error:  # network/API errors surface directly, not a stack trace
    st.error(f"Failed to fetch live odds: {error}")
    st.stop()

if not pairs:
    st.info(f"No upcoming {league.label} fixtures with usable odds right now.")
    st.stop()

predictor, known_teams = _fit_for_league(
    str(DEFAULT_DB_PATH), league.value, match_totals[league.value]
)

matched: list[tuple[Fixture, MatchOdds]] = []
unmatched: list[Fixture] = []
for fixture, odds in pairs:
    if fixture.home_team in known_teams and fixture.away_team in known_teams:
        matched.append((fixture, odds))
    else:
        unmatched.append(fixture)

all_tips: list[ValueTip] = []
if matched:
    predictions = predictor.predict([fixture for fixture, _odds in matched])
    for (fixture, odds), prediction in zip(matched, predictions, strict=True):
        all_tips.extend(
            find_value_tips(
                fixture,
                predictor.name,
                prediction.markets,
                odds,
                source=source,
                ev_threshold=float("-inf"),  # capture every outcome; filter below
                kelly_fraction_size=kelly_fraction_size,
                kelly_cap=kelly_cap,
            )
        )

value_tips = _sort_by_ev([tip for tip in all_tips if tip.ev > ev_threshold])

st.subheader(f"Value tips — {league.label}")
if not value_tips:
    st.info("No tips clear the EV threshold right now.")
else:
    tips_frame = _tips_frame(value_tips).to_pandas()
    tips_frame.insert(0, "log?", False)
    edited = st.data_editor(
        tips_frame,
        disabled=[c for c in tips_frame.columns if c != "log?"],
        hide_index=True,
        key="value_tips_editor",
    )
    if st.button("Log checked tips to the bet log"):
        checked = edited.index[edited["log?"]].tolist()
        logged, already_logged = 0, 0
        bet_con = bet_log.connect()
        try:
            for i in checked:
                if bet_log.record_bet(bet_con, value_tips[i]):
                    logged += 1
                else:
                    already_logged += 1
        finally:
            bet_con.close()
        if not checked:
            st.warning("No tips checked.")
        else:
            if logged:
                st.success(f"Logged {logged} bet(s) to the bet log.")
            if already_logged:
                st.info(f"{already_logged} tip(s) were already logged (skipped).")

n_fixtures = len(all_tips) // 3
with st.expander(f"All priced fixtures ({n_fixtures} fixtures, every 1X2 outcome)"):
    st.dataframe(_tips_frame(_sort_by_ev(all_tips)))

if unmatched:
    with st.expander(f"{len(unmatched)} fixture(s) skipped — team not in historical corpus"):
        st.warning(
            "These fixtures were not priced: at least one team name has no history "
            "in the store. Likely a missing/incorrect alias "
            "(`tipster_core.team_aliases`, ADR 0008), not a genuinely new team — "
            "worth checking before trusting anything else on this page."
        )
        st.dataframe(
            pl.DataFrame(
                {
                    "date": [f.date for f in unmatched],
                    "home_team": [f.home_team for f in unmatched],
                    "away_team": [f.away_team for f in unmatched],
                }
            )
        )
