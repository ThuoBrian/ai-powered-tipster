"""Tests for the paper-trading bet log: recording, idempotency, settlement (ADR 0009)."""

from __future__ import annotations

from datetime import date

import pytest

from tipster_core import bet_log
from tipster_core.contracts import Fixture, MatchOdds, MatchResult, OutcomeOdds
from tipster_core.leagues import LeagueCode
from tipster_core.value import ValueTip

PL = LeagueCode.PREMIER_LEAGUE
_FIXTURE = Fixture(
    league=PL, season="2526", date=date(2026, 1, 1), home_team="Arsenal", away_team="Chelsea"
)


def _tip(pick: str = "home", odds: float = 2.2, ev: float = 0.1) -> ValueTip:
    return ValueTip(
        fixture=_FIXTURE,
        model="gbm-poisson",
        pick=pick,  # type: ignore[arg-type]
        p_model=0.55,
        p_market_fair=0.48,
        odds=odds,
        odds_source="pinnacle",
        ev=ev,
        kelly_stake=0.04,
    )


@pytest.fixture
def con():
    connection = bet_log.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


def test_record_bet_inserts_a_pending_row(con) -> None:
    inserted = bet_log.record_bet(con, _tip())
    assert inserted is True

    pending = bet_log.pending_bets(con)
    assert len(pending) == 1
    bet = pending[0]
    assert bet.fixture_label == "Arsenal v Chelsea"
    assert bet.pick == "home"
    assert bet.odds == 2.2
    assert bet.kelly_stake == 0.04
    assert bet.flat_stake == 1.0
    assert bet.settled_at is None
    assert bet.won is None


def test_record_bet_is_idempotent(con) -> None:
    assert bet_log.record_bet(con, _tip()) is True
    assert bet_log.record_bet(con, _tip()) is False  # same tip again: no-op
    assert len(bet_log.all_bets(con)) == 1


def test_record_bet_different_picks_are_distinct(con) -> None:
    bet_log.record_bet(con, _tip(pick="home"))
    bet_log.record_bet(con, _tip(pick="away"))
    assert len(bet_log.all_bets(con)) == 2


def test_settle_bets_marks_a_win(con) -> None:
    bet_log.record_bet(con, _tip(pick="home", odds=2.2))
    played = [
        MatchResult(
            league=PL,
            season="2526",
            date=date(2026, 1, 1),
            home_team="Arsenal",
            away_team="Chelsea",
            home_goals=2,
            away_goals=0,
        )
    ]
    settled_count = bet_log.settle_bets(con, played)
    assert settled_count == 1

    bet = bet_log.all_bets(con)[0]
    assert bet.settled_at is not None
    assert bet.won is True
    assert bet.home_goals == 2
    assert bet.away_goals == 0
    assert bet.kelly_profit == pytest.approx(0.04 * (2.2 - 1.0))
    assert bet.flat_profit == pytest.approx(1.0 * (2.2 - 1.0))
    assert bet_log.pending_bets(con) == []


def test_settle_bets_marks_a_loss(con) -> None:
    bet_log.record_bet(con, _tip(pick="home", odds=2.2))
    played = [
        MatchResult(
            league=PL,
            season="2526",
            date=date(2026, 1, 1),
            home_team="Arsenal",
            away_team="Chelsea",
            home_goals=0,
            away_goals=1,
        )
    ]
    bet_log.settle_bets(con, played)
    bet = bet_log.all_bets(con)[0]
    assert bet.won is False
    assert bet.kelly_profit == pytest.approx(-0.04)
    assert bet.flat_profit == pytest.approx(-1.0)


def test_settle_bets_computes_clv_from_pinnacle_closing(con) -> None:
    bet_log.record_bet(con, _tip(pick="home", odds=2.2))
    played = [
        MatchResult(
            league=PL,
            season="2526",
            date=date(2026, 1, 1),
            home_team="Arsenal",
            away_team="Chelsea",
            home_goals=1,
            away_goals=0,
            odds=MatchOdds(pinnacle_closing=OutcomeOdds(home=2.0, draw=3.5, away=4.0)),
        )
    ]
    bet_log.settle_bets(con, played)
    bet = bet_log.all_bets(con)[0]
    assert bet.closing_odds == 2.0
    # taken 2.2, closed 2.0: CLV = (2.0 - 2.2) / 2.2 * 100 -> negative, closed shorter.
    assert bet.clv_pct == pytest.approx((2.0 - 2.2) / 2.2 * 100.0)


def test_settle_bets_ignores_a_differently_labelled_season(con) -> None:
    # The live fixture said "2526"; the ingested result is labelled "2025".
    bet_log.record_bet(con, _tip(pick="home"))
    played = [
        MatchResult(
            league=PL,
            season="2025",
            date=date(2026, 1, 1),
            home_team="Arsenal",
            away_team="Chelsea",
            home_goals=1,
            away_goals=0,
        )
    ]
    assert bet_log.settle_bets(con, played) == 1


def test_settle_bets_leaves_unplayed_fixtures_pending(con) -> None:
    bet_log.record_bet(con, _tip())
    settled_count = bet_log.settle_bets(con, played=[])
    assert settled_count == 0
    assert len(bet_log.pending_bets(con)) == 1


def test_summarize_aggregates_settled_bets_only(con) -> None:
    bet_log.record_bet(con, _tip(pick="home", odds=2.2))
    other_fixture = Fixture(
        league=PL, season="2526", date=date(2026, 1, 8), home_team="Everton", away_team="Fulham"
    )
    unplayed_tip = _tip(pick="away", odds=3.0).model_copy(update={"fixture": other_fixture})
    bet_log.record_bet(con, unplayed_tip)  # different fixture, stays pending
    played = [
        MatchResult(
            league=PL,
            season="2526",
            date=date(2026, 1, 1),
            home_team="Arsenal",
            away_team="Chelsea",
            home_goals=2,
            away_goals=0,
        )
    ]
    bet_log.settle_bets(con, played)

    summary = bet_log.summarize(con)
    assert summary.n_settled == 1
    assert summary.n_pending == 1
    assert summary.kelly.n_bets == 1
    assert summary.kelly.total_staked == pytest.approx(0.04)
    assert summary.kelly.total_profit == pytest.approx(0.04 * 1.2)
    assert summary.flat.total_staked == pytest.approx(1.0)
    assert summary.flat.roi_pct == pytest.approx(120.0)
    assert summary.clv.n == 0  # no odds on the played match -> no CLV computed
