"""Predict fixtures — price a pasted list of games (docs/design.md).

Type or paste fixtures, one per line; the fitted model prices each one.
Adding the bookmaker's 1X2 odds to a line also gives EV and a Kelly stake,
and those tips can go straight into the bet log. Team names the store has
no history for are flagged with a spelling suggestion, never guessed —
the model would otherwise price them as an average team (ADR 0008).
"""

from __future__ import annotations

import difflib
from datetime import date
from pathlib import Path

import polars as pl
import streamlit as st

from tipster_core.contracts import Fixture, MatchOdds, MatchPrediction
from tipster_core.leagues import season_from_date
from tipster_core.storage import DEFAULT_DB_PATH
from tipster_core.team_aliases import resolve_team_name
from tipster_core.value import ValueTip, find_value_tips
from tipster_ui.fixture_input import parse_fixture_lines
from tipster_ui.shared import (
    fit_for_league,
    league_match_totals,
    leagues_with_data,
    log_tips_editor,
    sort_by_ev,
)

st.title("Predict Fixtures")
st.caption(
    "Probabilities, not certainties: even strong football models pick the right "
    "result only about half the time, so judge them over many games, never one "
    "accumulator. `just backtest` shows this model's hit rate on past seasons."
)

if not Path(DEFAULT_DB_PATH).exists():
    st.info("No database yet. Run `just ingest` first, then reload this page.")
    st.stop()

match_totals = league_match_totals(str(DEFAULT_DB_PATH))
league_options = leagues_with_data(match_totals)
if not league_options:
    st.info("No match data ingested yet. Run `just ingest` first.")
    st.stop()

with st.form("fixtures_form"):
    left, right = st.columns([1, 1])
    league = left.selectbox(
        "League", league_options, format_func=lambda code: f"{code.label} ({code.value})"
    )
    match_date = right.date_input("Match date", value=date.today())
    all_neutral = st.checkbox(
        "Neutral venues",
        help="Treat every fixture as a neutral-venue game (e.g. a World Cup or AFCON). "
        "Or mark single lines with (n): `Morocco v Egypt (n)`.",
    )
    text = st.text_area(
        "Fixtures, one per line: `Home v Away`, optionally `(n)` for a neutral venue, "
        "then `, home odds, draw odds, away odds`",
        height=240,
        placeholder="Arsenal v Chelsea\nMan City v Liverpool, 1.85, 3.90, 4.20\nKenya v Uganda (n)",
    )
    submitted = st.form_submit_button("Predict")

# Kept in session state so the results survive the rerun a "log tips" click causes.
if submitted:
    st.session_state["predict_input"] = (league, match_date, all_neutral, text)
if "predict_input" not in st.session_state:
    st.stop()
league, match_date, all_neutral, text = st.session_state["predict_input"]

lines, errors = parse_fixture_lines(text)
for error in errors:
    st.error(error)
if not lines:
    st.info("Enter at least one fixture.")
    st.stop()

predictor, known_teams = fit_for_league(
    str(DEFAULT_DB_PATH), league.value, match_totals[league.value]
)
team_list = sorted(known_teams)

priced: list[tuple[Fixture, MatchOdds | None]] = []
unknown: list[str] = []
for line in lines:
    home = resolve_team_name(league, line.home)
    away = resolve_team_name(league, line.away)
    missing = [name for name in (home, away) if name not in known_teams]
    if missing:
        for name in missing:
            close = difflib.get_close_matches(name, team_list, n=1, cutoff=0.6)
            hint = f" — did you mean **{close[0]}**?" if close else ""
            unknown.append(f"`{name}` ({line.home} v {line.away}){hint}")
        continue
    fixture = Fixture(
        league=league,
        season=season_from_date(match_date, league),
        date=match_date,
        home_team=home,
        away_team=away,
        neutral=all_neutral if line.neutral is None else line.neutral,
    )
    priced.append((fixture, MatchOdds(avg=line.odds) if line.odds else None))

if unknown:
    st.warning(
        f"Not priced — no {league.label} history for these teams (check the "
        "spelling or the league):\n\n" + "\n".join(f"- {item}" for item in unknown)
    )
if not priced:
    st.stop()

predictions = predictor.predict([fixture for fixture, _odds in priced])


def _most_likely(prediction: MatchPrediction) -> str:
    fixture, markets = prediction.fixture, prediction.markets
    outcomes = (
        (markets.home, f"{fixture.home_team} win"),
        (markets.draw, "Draw"),
        (markets.away, f"{fixture.away_team} win"),
    )
    probability, label = max(outcomes)
    return f"{label} ({probability:.0%})"


def _top_scores(prediction: MatchPrediction, n: int = 3) -> str:
    return ", ".join(
        f"{cell.home_goals}-{cell.away_goals} ({cell.probability:.0%})"
        for cell in prediction.markets.correct_scores[:n]
    )


st.subheader(f"Predictions — {len(predictions)} fixture(s)")
st.dataframe(
    pl.DataFrame(
        {
            "fixture": [p.fixture.fixture for p in predictions],
            "venue": ["neutral" if p.fixture.neutral else "home" for p in predictions],
            "home %": [round(p.markets.home * 100, 1) for p in predictions],
            "draw %": [round(p.markets.draw * 100, 1) for p in predictions],
            "away %": [round(p.markets.away * 100, 1) for p in predictions],
            "most likely": [_most_likely(p) for p in predictions],
            "likeliest scores": [_top_scores(p) for p in predictions],
            "over 2.5 %": [round(p.markets.over25 * 100, 1) for p in predictions],
            "BTTS %": [round(p.markets.btts_yes * 100, 1) for p in predictions],
        }
    ),
    hide_index=True,
)

with_odds = [
    (fixture, odds, prediction)
    for (fixture, odds), prediction in zip(priced, predictions, strict=True)
    if odds is not None
]
if not with_odds:
    st.caption("Add odds to a line (`, home, draw, away`) to see EV and log it as a bet.")
    st.stop()

ev_threshold = st.slider("Minimum EV", 0.0, 0.20, 0.02, step=0.01)
tips: list[ValueTip] = [
    tip.model_copy(update={"odds_source": "manual"})
    for fixture, odds, prediction in with_odds
    for tip in find_value_tips(
        fixture, predictor.name, prediction.markets, odds, ev_threshold=ev_threshold
    )
]

st.subheader("Value tips from your odds")
if tips:
    log_tips_editor(sort_by_ev(tips), key="predict_tips_editor")
else:
    st.info("None of the entered odds beat the model by the minimum EV.")
