"""GBM → Poisson hybrid tests: positivity, determinism, contract."""

from __future__ import annotations

import pytest
from synthetic import synthetic_matches, to_match_results

from tipster_core.model.hybrid import GbmPoissonConfig, GbmPoissonPredictor


def _tiny_config() -> GbmPoissonConfig:
    return GbmPoissonConfig(
        n_estimators=20,
        num_leaves=4,
        min_data_in_leaf=5,
        learning_rate=0.1,
        num_threads=1,
    )


@pytest.fixture(scope="module")
def corpus():
    frame = synthetic_matches(seed=3, leagues=("E0",), n_teams=8, n_weeks=26)
    return to_match_results(frame)


def test_lambdas_positive_and_matrices_valid(corpus) -> None:
    model = GbmPoissonPredictor(gbm_config=_tiny_config())
    model.fit(corpus)
    fixtures = [match.to_fixture() for match in corpus[-6:]]
    predictions = model.predict(fixtures)

    assert len(predictions) == 6
    assert [p.fixture for p in predictions] == fixtures
    for prediction in predictions:
        assert prediction.model == "gbm-poisson"
        assert prediction.lambda_home is not None and prediction.lambda_home > 0
        assert prediction.lambda_away is not None and prediction.lambda_away > 0
        total = prediction.markets.home + prediction.markets.draw + prediction.markets.away
        assert total == pytest.approx(1.0)


def test_determinism_same_seed_same_predictions(corpus) -> None:
    fixtures = [match.to_fixture() for match in corpus[-4:]]
    first = GbmPoissonPredictor(gbm_config=_tiny_config())
    first.fit(corpus)
    second = GbmPoissonPredictor(gbm_config=_tiny_config())
    second.fit(corpus)
    assert [p.lambda_home for p in first.predict(fixtures)] == [
        p.lambda_home for p in second.predict(fixtures)
    ]


def test_rho_fitted_in_bounds(corpus) -> None:
    model = GbmPoissonPredictor(gbm_config=_tiny_config())
    assert model.rho == 0.0
    model.fit(corpus)
    assert -0.2 <= model.rho <= 0.2


def test_predict_before_fit_raises() -> None:
    model = GbmPoissonPredictor(gbm_config=_tiny_config())
    with pytest.raises(ValueError, match="fit"):
        model.predict([])


def test_home_advantage_visible_in_lambdas(corpus) -> None:
    model = GbmPoissonPredictor(gbm_config=_tiny_config())
    model.fit(corpus)
    fixtures = [match.to_fixture() for match in corpus[-10:]]
    predictions = model.predict(fixtures)
    home_total = sum(p.lambda_home for p in predictions)
    away_total = sum(p.lambda_away for p in predictions)
    # With a +0.25 log-rate home advantage in the generator, home lambdas
    # must exceed away lambdas on average.
    assert home_total > away_total
