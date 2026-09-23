"""Pieces shared by the dashboard pages: the fitted-model cache and tip tables."""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl
import streamlit as st

from tipster_core import bet_log
from tipster_core.leagues import LeagueCode
from tipster_core.model.calibration import CalibratedPredictor
from tipster_core.model.dixon_coles import DixonColesPredictor
from tipster_core.storage import connect, load_match_results, match_counts
from tipster_core.value import ValueTip

_L = LeagueCode

#: Home-page grouping; every LeagueCode appears exactly once.
REGIONS: dict[str, tuple[LeagueCode, ...]] = {
    "Europe — top flights": (
        _L.PREMIER_LEAGUE,
        _L.LA_LIGA,
        _L.BUNDESLIGA,
        _L.SERIE_A,
        _L.LIGUE_1,
        _L.EREDIVISIE,
        _L.PRIMEIRA_LIGA,
        _L.BELGIAN_PRO_LEAGUE,
        _L.SCOTTISH_PREMIERSHIP,
        _L.SUPER_LIG,
        _L.GREEK_SUPER_LEAGUE,
        _L.AUSTRIA,
        _L.SWITZERLAND,
        _L.DENMARK,
        _L.NORWAY,
        _L.SWEDEN,
        _L.POLAND,
        _L.ROMANIA,
        _L.RUSSIA,
        _L.FINLAND,
        _L.IRELAND,
    ),
    "Europe — lower leagues": (
        _L.CHAMPIONSHIP,
        _L.LEAGUE_ONE,
        _L.LEAGUE_TWO,
        _L.NATIONAL_LEAGUE,
        _L.SCOTTISH_CHAMPIONSHIP,
        _L.SCOTTISH_LEAGUE_ONE,
        _L.SCOTTISH_LEAGUE_TWO,
        _L.BUNDESLIGA_2,
        _L.SERIE_B,
        _L.LA_LIGA_2,
        _L.LIGUE_2,
    ),
    "Americas": (_L.BRAZIL, _L.ARGENTINA, _L.MEXICO, _L.USA),
    "Asia": (_L.JAPAN, _L.CHINA),
    "International": (_L.INTERNATIONAL,),
}


def leagues_with_data(totals: dict[str, int]) -> list[LeagueCode]:
    """Every competition that has matches in the store, sorted by name."""
    return sorted(
        (league for league in LeagueCode if totals.get(league.value, 0) > 0),
        key=lambda league: league.label,
    )


def league_match_totals(db_path: str) -> dict[str, int]:
    """Matches in the store per league code, summed across seasons."""
    con = connect(db_path, read_only=True)
    try:
        counts = match_counts(con)
    finally:
        con.close()
    totals: dict[str, int] = {}
    for code, _season, n in counts:
        totals[code] = totals.get(code, 0) + n
    return totals


@st.cache_resource(show_spinner="Fitting model on historical corpus...")
def fit_for_league(
    db_path: str, league_value: str, n_matches: int
) -> tuple[CalibratedPredictor, frozenset[str]]:
    """A calibrated predictor fitted on one league's full history, plus its team set.

    Cached on ``n_matches`` so a fresh ``just ingest`` invalidates the cache
    automatically; refitting is a few seconds (ADR 0005), not worth doing on
    every rerun. Shared by every page, so the model is fitted once per league.

    Dixon-Coles, not the GBM hybrid: the hybrid failed ADR 0003's gate
    against it on the 2025/26+ walk-forward (ADR 0003 amendment). Only the
    goal markets are calibrated; raw DC home/draw/away backtested better
    and stays symmetric at neutral venues (ADR 0011).
    """
    league = LeagueCode.from_code(league_value)
    con = connect(db_path, read_only=True)
    try:
        results = load_match_results(con, leagues=[league])
    finally:
        con.close()
    predictor = CalibratedPredictor(DixonColesPredictor(), calibrate_1x2=False)
    predictor.fit(results)
    known_teams = frozenset(m.home_team for m in results) | frozenset(m.away_team for m in results)
    return predictor, known_teams


def sort_by_ev(tips: Sequence[ValueTip]) -> list[ValueTip]:
    return sorted(tips, key=lambda tip: tip.ev, reverse=True)


def tips_frame(tips: Sequence[ValueTip]) -> pl.DataFrame:
    """Render *tips* in the given order — callers sort first (``sort_by_ev``).

    Row order must match ``tips`` index-for-index: ``log_tips_editor`` reads
    checkbox selections back by row position against the same list.
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


def log_tips_editor(tips: Sequence[ValueTip], key: str) -> None:
    """A tips table with a "log?" checkbox column and a button to log checked rows."""
    frame = tips_frame(tips).to_pandas()
    frame.insert(0, "log?", False)
    edited = st.data_editor(
        frame,
        disabled=[c for c in frame.columns if c != "log?"],
        hide_index=True,
        key=key,
    )
    if not st.button("Log checked tips to the bet log", key=f"{key}_log"):
        return
    checked = edited.index[edited["log?"]].tolist()
    if not checked:
        st.warning("No tips checked.")
        return
    logged, already_logged = 0, 0
    con = bet_log.connect()
    try:
        for i in checked:
            if bet_log.record_bet(con, tips[i]):
                logged += 1
            else:
                already_logged += 1
    finally:
        con.close()
    if logged:
        st.success(f"Logged {logged} bet(s) to the bet log.")
    if already_logged:
        st.info(f"{already_logged} tip(s) were already logged (skipped).")
