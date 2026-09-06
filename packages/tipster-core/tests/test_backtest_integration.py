"""End-to-end: DuckDB → load → walk-forward with all arms over synthetic data."""

from __future__ import annotations

import polars as pl
import pytest
from synthetic import synthetic_matches, to_match_results

from tipster_core.backtest.harness import BacktestConfig, run_backtest
from tipster_core.leagues import LeagueCode
from tipster_core.model.calibration import CalibratedPredictor
from tipster_core.model.dixon_coles import DixonColesPredictor
from tipster_core.model.hybrid import GbmPoissonConfig, GbmPoissonPredictor
from tipster_core.storage import connect, load_matches, replace_season


@pytest.fixture(scope="module")
def corpus():
    """The full path a real run takes: synthetic frame → DuckDB → load → validate."""
    frame = synthetic_matches(seed=13, leagues=("E0", "SP1"), n_teams=10, n_weeks=26)
    con = connect(":memory:")
    try:
        # replace_season expects exactly one league+season per frame.
        for league in ("E0", "SP1"):
            replace_season(con, frame.filter(pl.col("league") == league))
        loaded = load_matches(con, leagues=(LeagueCode.PREMIER_LEAGUE, LeagueCode.LA_LIGA))
    finally:
        con.close()
    return loaded


def test_load_matches_filters_and_sorts(corpus: pl.DataFrame) -> None:
    assert corpus.height > 200
    assert set(corpus["league"].unique()) == {"E0", "SP1"}
    assert corpus["date"].is_sorted()
    assert corpus.schema["date"] == pl.Date


def test_full_walk_forward_run(corpus: pl.DataFrame) -> None:
    results = to_match_results(corpus)
    config = BacktestConfig(block_days=14, min_training_matches=60)
    # A tiny GBM keeps the suite inside its time budget: the harness paths
    # (per-block refit, 4-fold calibration replay, scoring, gate) are
    # identical — only tree count differs. The real corpus run uses defaults.
    factories = {
        "gbm-poisson": lambda: CalibratedPredictor(
            GbmPoissonPredictor(
                gbm_config=GbmPoissonConfig(
                    n_estimators=20,
                    num_leaves=4,
                    min_data_in_leaf=5,
                    learning_rate=0.1,
                    num_threads=1,
                )
            )
        ),
        "dixon-coles": lambda: CalibratedPredictor(DixonColesPredictor()),
    }
    report = run_backtest(results, config, arm_factories=factories)

    assert report.n_blocks >= 2
    assert report.block_days == 14
    assert set(report.arms) == {"gbm-poisson", "dixon-coles", "closing-favourite"}
    for name, arm in report.arms.items():
        assert arm.model == name
        assert arm.n_fixtures > 0
        assert set(arm.families) == {"1x2", "over25", "btts", "correct-score"}
        for family in arm.families.values():
            assert family.n == arm.n_fixtures
            assert family.brier >= 0.0
            assert family.log_loss >= 0.0
        assert set(arm.reliability) == {"home", "draw", "away", "over25", "btts"}
        assert arm.roi.n_bets > 0
        assert 0.0 <= arm.clv.beat_rate <= 1.0

    # The gate compares the hybrid to both benchmarks.
    assert {c.benchmark for c in report.gate.comparisons} == {"dixon-coles", "closing-favourite"}
    assert isinstance(report.gate.passes, bool)

    # Records exist for every (arm, fixture) the arm predicted, coherent.
    assert len(report.records) == sum(arm.n_fixtures for arm in report.arms.values())
    for record in report.records:
        assert record.home + record.draw + record.away == pytest.approx(1.0)
        assert record.over25 + record.under25 == pytest.approx(1.0)
        assert record.btts_yes + record.btts_no == pytest.approx(1.0)
