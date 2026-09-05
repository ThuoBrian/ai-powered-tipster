"""Contract tests: the domain language is validated, frozen, and strict."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from tipster_core.contracts import MatchOdds, MatchResult, OutcomeOdds
from tipster_core.leagues import LeagueCode


def _result() -> MatchResult:
    return MatchResult(
        league="E0",
        season="2526",
        date=date(2025, 8, 16),
        home_team="Arsenal",
        away_team="West Ham",
        home_goals=3,
        away_goals=0,
        odds=MatchOdds(
            b365=OutcomeOdds(home=1.85, draw=3.6, away=4.5),
            pinnacle_closing=OutcomeOdds(home=1.9, draw=3.6, away=4.4),
        ),
    )


def test_valid_result_with_odds() -> None:
    result = _result()
    assert result.league is LeagueCode.PREMIER_LEAGUE
    assert result.fixture == "Arsenal v West Ham"
    assert result.odds is not None
    assert result.odds.b365 is not None
    assert result.odds.b365.home == 1.85
    assert result.odds.pinnacle_closing is not None
    assert result.odds.pinnacle is None


def test_results_are_frozen() -> None:
    with pytest.raises(ValidationError):
        _result().home_goals = 2  # type: ignore[misc]


def test_odds_must_be_greater_than_one() -> None:
    with pytest.raises(ValidationError):
        OutcomeOdds(home=1.0, draw=3.6, away=4.5)


def test_negative_goals_rejected() -> None:
    with pytest.raises(ValidationError):
        MatchResult(
            league="E0",
            season="2526",
            date=date(2025, 8, 16),
            home_team="Arsenal",
            away_team="West Ham",
            home_goals=-1,
            away_goals=0,
        )


def test_invalid_season_rejected() -> None:
    with pytest.raises(ValidationError):
        MatchResult(
            league="E0",
            season="2527",
            date=date(2025, 8, 16),
            home_team="Arsenal",
            away_team="West Ham",
            home_goals=0,
            away_goals=0,
        )
