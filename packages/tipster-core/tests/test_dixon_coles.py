"""Dixon-Coles reference tests: recovery, determinism, cold start."""

from __future__ import annotations

import math

import pytest
from synthetic import synthetic_matches, to_match_results

from tipster_core.contracts import Fixture
from tipster_core.leagues import LeagueCode
from tipster_core.model.dixon_coles import DixonColesConfig, DixonColesPredictor


@pytest.fixture
def corpus():
    return to_match_results(synthetic_matches(seed=11, leagues=("E0",), n_teams=8, n_weeks=30))


def _fixtures(corpus, n: int) -> list[Fixture]:
    return [match.to_fixture() for match in corpus[-n:]]


def test_predictions_are_valid_and_extreme(corpus) -> None:
    model = DixonColesPredictor()
    model.fit(corpus)
    predictions = model.predict(_fixtures(corpus, 8))

    for prediction in predictions:
        assert prediction.model == "dixon-coles"
        assert prediction.lambda_home is None  # DC does not expose lambdas
        total = prediction.markets.home + prediction.markets.draw + prediction.markets.away
        assert total == pytest.approx(1.0)
        assert prediction.matrix.max_goals == 8

    # On a ground-truth corpus the fitted 1X2 must carry real signal: more
    # extreme than a coin flip on average.
    spreads = [abs(p.markets.home - p.markets.away) for p in predictions]
    assert sum(spreads) / len(spreads) > 0.02


def test_deterministic_across_fits(corpus) -> None:
    fixtures = _fixtures(corpus, 6)
    first = DixonColesPredictor()
    first.fit(corpus)
    second = DixonColesPredictor()
    second.fit(corpus)
    assert [p.markets for p in first.predict(fixtures)] == [
        p.markets for p in second.predict(fixtures)
    ]


def test_unseen_team_gets_league_average_lambdas(corpus) -> None:
    model = DixonColesPredictor()
    model.fit(corpus)
    fixture = Fixture(
        league="E0",
        season="2425",
        date=corpus[-1].date,
        home_team="Brand New FC",
        away_team="Also New FC",
    )
    prediction = model.predict([fixture])[0]
    # Both unseen -> league-average attack/defense: the only asymmetry left
    # is the fitted home advantage, so home is a mild favourite.
    assert prediction.markets.home > prediction.markets.away
    assert prediction.markets.home > prediction.markets.draw


def test_rho_is_fitted_within_bounds(corpus) -> None:
    model = DixonColesPredictor()
    model.fit(corpus)
    params = model._params[LeagueCode.PREMIER_LEAGUE]
    config = DixonColesConfig()
    assert config.rho_lower <= params.rho <= config.rho_upper


def test_gamma_captures_home_advantage(corpus) -> None:
    model = DixonColesPredictor()
    model.fit(corpus)
    params = model._params[LeagueCode.PREMIER_LEAGUE]
    # The synthetic corpus has a +0.25 log-rate home advantage: a positive
    # fitted gamma is the minimum we expect.
    assert params.gamma > 0.0
    league_average_lambda = math.exp(params.gamma)
    assert 0.8 < league_average_lambda < 3.0


def test_tiny_separated_slice_stays_finite() -> None:
    """Degenerate slices (calibration folds) must not break the MLE.

    Two hazards: a team that only ever appears away (the team count must not
    be inferred from the home column), and separated results that used to
    send unregularised lambdas to the millions.
    """
    matches = to_match_results(
        synthetic_matches(seed=5, leagues=("E0",), n_teams=6, n_weeks=4, with_odds=False)
    )
    # Drop every match where the away-only side is home, forcing the hazard.
    away_only = matches[0].away_team
    matches = [m for m in matches if m.home_team != away_only]
    model = DixonColesPredictor()
    model.fit(matches[:6])  # a handful of matches — the worst case
    predictions = model.predict([match.to_fixture() for match in matches[:2]])

    for prediction in predictions:
        total = prediction.markets.home + prediction.markets.draw + prediction.markets.away
        assert total == pytest.approx(1.0)
        assert all(math.isfinite(p) for p in prediction.matrix.rows[0])
