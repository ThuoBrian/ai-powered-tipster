"""Value finder — Phase 2: live odds vs. the fitted model (docs/design.md).

Devigs live 1X2 odds (Shin's method), compares against the fitted model's
own probabilities (``tipster_ui.shared.fit_for_league``), and surfaces positive-EV tips sized by
fractional Kelly (``tipster_core.value``, ADR 0006). Fixtures whose teams
have no history in the store are never priced — a name the alias table
missed (ADR 0008) would otherwise get a confidently wrong, cold-start
prediction instead of a visible warning.
"""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl
import streamlit as st

from tipster_core.contracts import Fixture, MatchOdds
from tipster_core.ingest.odds_api import INT_TOURNAMENTS, SPORT_KEYS, active_sport_keys
from tipster_core.ingest.pipeline import DEFAULT_ODDS_CACHE_DIR, fetch_live_odds
from tipster_core.leagues import LeagueCode
from tipster_core.storage import DEFAULT_DB_PATH
from tipster_core.value import OddsSource, ValueTip, find_value_tips
from tipster_ui.shared import (
    fit_for_league,
    league_match_totals,
    leagues_with_data,
    log_tips_editor,
    sort_by_ev,
    tips_frame,
)


@st.cache_data(ttl=3600, show_spinner=False)
def _live_tournaments(api_key: str) -> list[str]:
    """International tournaments in season now (free call, cached for an hour)."""
    active = active_sport_keys(api_key)
    return [key for key in INT_TOURNAMENTS if key in active]


st.title("Value Finder")
st.caption(
    "Live 1X2 odds, devigged (Shin's method) and compared against the fitted "
    "model — positive-EV tips, sized by fractional Kelly (docs/design.md)."
)

if not Path(DEFAULT_DB_PATH).exists():
    st.info("No database yet. Run `just ingest` first, then reload this page.")
    st.stop()

match_totals = league_match_totals(str(DEFAULT_DB_PATH))
league_options = leagues_with_data(match_totals)
if not league_options:
    st.info("No match data ingested yet. Run `just ingest` first.")
    st.stop()

api_key = os.environ.get("THE_ODDS_API_KEY", "")

with st.sidebar:
    st.header("Settings")
    league = st.selectbox(
        "League", league_options, format_func=lambda code: f"{code.label} ({code.value})"
    )
    sport_key: str | None = None
    if league is LeagueCode.INTERNATIONAL:
        if api_key:
            tournaments = _live_tournaments(api_key)
        else:  # no key: only tournaments with a cached snapshot
            tournaments = [
                key for key in INT_TOURNAMENTS if (DEFAULT_ODDS_CACHE_DIR / f"{key}.json").exists()
            ]
        if not tournaments:
            st.info("No international tournament has live odds right now.")
            st.stop()
        sport_key = st.selectbox(
            "Tournament", tournaments, format_func=lambda key: INT_TOURNAMENTS[key][0]
        )
    elif league not in SPORT_KEYS:
        st.info(
            f"No live odds feed for {league.label}. Use **Predict Fixtures** and type "
            "in the bookmaker's odds instead."
        )
        st.stop()
    ev_threshold = st.slider("Minimum EV", 0.0, 0.20, 0.02, step=0.01)
    kelly_fraction_size = st.slider("Kelly fraction", 0.05, 1.0, 0.25, step=0.05)
    kelly_cap = st.slider("Per-bet stake cap", 0.01, 0.20, 0.05, step=0.01)
    source_choice = st.selectbox("Odds source", ["Auto (ladder)", "pinnacle", "avg", "b365", "max"])
    source: OddsSource | None = None if source_choice == "Auto (ladder)" else source_choice  # type: ignore[assignment]

    st.divider()
    if not api_key:
        st.warning("THE_ODDS_API_KEY not set — showing the last cached snapshot, if any.")
    refresh_clicked = st.button("Fetch fresh odds now", disabled=not api_key)

cache_path = DEFAULT_ODDS_CACHE_DIR / f"{sport_key or league.value}.json"
if not cache_path.exists() and not api_key:
    st.info(
        "No cached odds and no `THE_ODDS_API_KEY` set. Add the key to `.env` "
        "(see `.env.example`), then click **Fetch fresh odds now**, or run `just fetch-odds`."
    )
    st.stop()

try:
    pairs = fetch_live_odds(league, api_key, sport_key=sport_key, refresh=refresh_clicked)
except Exception as error:  # network/API errors surface directly, not a stack trace
    st.error(f"Failed to fetch live odds: {error}")
    st.stop()

if not pairs:
    st.info(f"No upcoming {league.label} fixtures with usable odds right now.")
    st.stop()

predictor, known_teams = fit_for_league(
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

value_tips = sort_by_ev([tip for tip in all_tips if tip.ev > ev_threshold])

st.subheader(f"Value tips — {league.label}")
if not value_tips:
    st.info("No tips clear the EV threshold right now.")
else:
    log_tips_editor(value_tips, key="value_tips_editor")

n_fixtures = len(all_tips) // 3
with st.expander(f"All priced fixtures ({n_fixtures} fixtures, every 1X2 outcome)"):
    st.dataframe(tips_frame(sort_by_ev(all_tips)))

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
