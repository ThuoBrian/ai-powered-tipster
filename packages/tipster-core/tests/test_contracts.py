"""Contract tests: the domain language is validated, frozen, and strict."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from tipster_core.contracts import (
    Fixture,
    MarketProbabilities,
    MatchOdds,
    MatchResult,
    OutcomeOdds,
    ScoreMatrix,
)
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


def test_to_fixture_strips_goals_and_odds() -> None:
    fixture = _result().to_fixture()
    assert isinstance(fixture, Fixture)
    assert fixture.home_team == "Arsenal"
    assert fixture.away_team == "West Ham"
    assert fixture.date == date(2025, 8, 16)
    assert not hasattr(fixture, "home_goals")
    assert not hasattr(fixture, "odds")


def _matrix() -> ScoreMatrix:
    # 3x3 grid, hand-checked:
    #   p_home = (1,0)+(2,0)+(2,1) = 0.45
    #   p_draw = (0,0)+(1,1)+(2,2) = 0.35
    #   p_away = (0,1)+(0,2)+(1,2) = 0.20
    #   over25 = (1,2)+(2,1)+(2,2) = 0.25
    #   btts   = (1,1)+(1,2)+(2,1)+(2,2) = 0.35
    return ScoreMatrix(
        max_goals=2,
        rows=(
            (0.15, 0.10, 0.05),
            (0.20, 0.10, 0.05),
            (0.15, 0.10, 0.10),
        ),
    )


def test_score_matrix_derives_markets() -> None:
    matrix = _matrix()
    assert matrix.p(1, 0) == pytest.approx(0.20)
    assert matrix.p_home == pytest.approx(0.45)
    assert matrix.p_draw == pytest.approx(0.35)
    assert matrix.p_away == pytest.approx(0.20)
    assert matrix.p_over25 == pytest.approx(0.25)
    assert matrix.p_under25 == pytest.approx(0.75)
    assert matrix.p_btts == pytest.approx(0.35)
    assert matrix.p_btts_no == pytest.approx(0.65)


def test_score_matrix_market_sums() -> None:
    matrix = _matrix()
    assert matrix.p_home + matrix.p_draw + matrix.p_away == pytest.approx(1.0)
    assert matrix.p_over25 + matrix.p_under25 == pytest.approx(1.0)
    assert matrix.p_btts + matrix.p_btts_no == pytest.approx(1.0)


def test_score_matrix_rejects_bad_mass() -> None:
    with pytest.raises(ValidationError):
        ScoreMatrix(max_goals=1, rows=((0.5, 0.2), (0.2, 0.0)))  # sums to 0.9

    with pytest.raises(ValidationError):
        ScoreMatrix(max_goals=1, rows=((0.5, 0.5), (0.5, -0.5)))

    with pytest.raises(ValidationError):
        ScoreMatrix(max_goals=1, rows=((0.5, 0.5), (0.5,)))

    with pytest.raises(ValidationError):
        ScoreMatrix(max_goals=1, rows=((1.0,)))


def test_market_probabilities_from_matrix() -> None:
    markets = MarketProbabilities.from_matrix(_matrix())
    assert markets.home == pytest.approx(0.45)
    assert markets.draw == pytest.approx(0.35)
    assert markets.away == pytest.approx(0.20)
    assert markets.over25 == pytest.approx(0.25)
    assert markets.under25 == pytest.approx(0.75)
    assert markets.btts_yes == pytest.approx(0.35)
    assert markets.correct_scores[0].home_goals == 1
    assert markets.correct_scores[0].away_goals == 0
    assert markets.correct_scores[0].probability == pytest.approx(0.20)


def test_market_probabilities_must_be_coherent() -> None:
    with pytest.raises(ValidationError):
        MarketProbabilities(
            home=0.4,
            draw=0.3,
            away=0.2,  # sums to 0.9
            over25=0.5,
            under25=0.5,
            btts_yes=0.5,
            btts_no=0.5,
        )
