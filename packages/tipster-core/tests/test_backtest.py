"""Backtest tests: metric math, odds ladders, baseline, harness leakage."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from synthetic import synthetic_matches, to_match_results

from tipster_core.backtest.baselines import (
    closing_favourite_predictions,
    closing_odds,
    opening_odds,
)
from tipster_core.backtest.harness import BacktestConfig, run_backtest
from tipster_core.backtest.metrics import (
    brier_1x2,
    brier_binary,
    clv,
    flat_stake,
    log_loss_1x2,
    log_loss_binary,
    reliability,
)
from tipster_core.contracts import MatchOdds, MatchResult, OutcomeOdds

# --- Metric math, hand-computed -------------------------------------------


def test_brier_1x2_hand_computed() -> None:
    probs = [(0.5, 0.3, 0.2)]
    assert brier_1x2(probs, [0]) == pytest.approx(0.25 + 0.09 + 0.04)
    assert brier_1x2(probs, [2]) == pytest.approx(0.25 + 0.09 + 0.64)
    assert brier_1x2(probs, [1]) == pytest.approx(0.25 + 0.49 + 0.04)


def test_log_loss_1x2_hand_computed() -> None:
    import math

    assert log_loss_1x2([(0.5, 0.3, 0.2)], [0]) == pytest.approx(-math.log(0.5))
    # Hard 1.0 predictions are clipped, not infinite.
    assert log_loss_1x2([(1.0, 0.0, 0.0)], [0]) == pytest.approx(-math.log(1.0 - 1e-6))
    assert log_loss_1x2([(1.0, 0.0, 0.0)], [1]) == pytest.approx(-math.log(1e-6))


def test_brier_binary_hand_computed() -> None:
    assert brier_binary([0.7], [True]) == pytest.approx(0.09)
    assert brier_binary([0.7], [False]) == pytest.approx(0.49)
    # Brier is never clipped: hard predictions get their full penalty.
    assert brier_binary([1.0], [False]) == pytest.approx(1.0)


def test_log_loss_binary_clipped() -> None:
    import math

    assert log_loss_binary([1.0], [True]) == pytest.approx(-math.log(1.0 - 1e-6))
    assert log_loss_binary([0.0], [False]) == pytest.approx(-math.log(1.0 - 1e-6))


def test_reliability_bins() -> None:
    probs = [0.05, 0.05, 0.95]
    outs = [True, False, True]
    bins = reliability(probs, outs)
    # Two bins: [0.0, 0.1) with midpoint 0.05, [0.9, 1.0) with midpoint 0.95.
    assert len(bins) == 2
    assert bins[0][0] == pytest.approx(0.05)
    assert bins[0][2] == pytest.approx(0.5)  # one of two true
    assert bins[0][3] == 2
    assert bins[1][0] == pytest.approx(0.95)
    assert bins[1][2] == pytest.approx(1.0)
    assert bins[1][3] == 1


def test_flat_stake_and_clv() -> None:
    assert flat_stake(2.5, True) == pytest.approx(1.5)
    assert flat_stake(2.5, False) == pytest.approx(-1.0)
    assert clv(2.0, 2.2) == pytest.approx(0.1)
    assert clv(2.2, 2.0) == pytest.approx(-0.0909090909)


# --- Odds ladders ----------------------------------------------------------


def _match_with_odds(**odds_kwargs: object) -> MatchResult:
    return MatchResult(
        league="E0",
        season="2425",
        date=date(2025, 1, 1),
        home_team="Arsenal",
        away_team="Spurs",
        home_goals=2,
        away_goals=1,
        odds=MatchOdds(**odds_kwargs),  # type: ignore[arg-type]
    )


def test_closing_odds_ladder_prefers_pinnacle() -> None:
    match = _match_with_odds(
        pinnacle_closing=OutcomeOdds(home=1.5, draw=4.0, away=6.0),
        avg_closing=OutcomeOdds(home=1.6, draw=4.0, away=5.5),
    )
    chosen = closing_odds(match)
    assert chosen is not None
    assert chosen[0].home == 1.5
    assert chosen[1] == "pinnacle"


def test_closing_odds_falls_back_to_avg_then_b365() -> None:
    match = _match_with_odds(
        avg_closing=OutcomeOdds(home=1.6, draw=4.0, away=5.5),
        b365_closing=OutcomeOdds(home=1.7, draw=4.0, away=5.0),
    )
    chosen = closing_odds(match)
    assert chosen is not None
    assert chosen[1] == "avg"

    match_b365 = _match_with_odds(b365_closing=OutcomeOdds(home=1.7, draw=4.0, away=5.0))
    chosen_b365 = closing_odds(match_b365)
    assert chosen_b365 is not None
    assert chosen_b365[1] == "b365"

    assert closing_odds(_match_with_odds()) is None


def test_opening_odds_never_uses_closing_columns() -> None:
    match = _match_with_odds(
        pinnacle_closing=OutcomeOdds(home=1.5, draw=4.0, away=6.0),
        b365=OutcomeOdds(home=2.1, draw=3.5, away=3.2),
    )
    chosen = opening_odds(match)
    assert chosen is not None
    assert chosen[1] == "b365"
    assert chosen[0].home == 2.1


def test_closing_favourite_picks_lowest_odds() -> None:
    match = _match_with_odds(
        pinnacle_closing=OutcomeOdds(home=4.0, draw=3.5, away=1.9),
    )
    prediction = closing_favourite_predictions([match])[0]
    assert prediction.model == "closing-favourite"
    assert prediction.markets.away == pytest.approx(1.0)
    assert prediction.markets.home == pytest.approx(0.0)
    assert prediction.markets.over25 == pytest.approx(0.0)  # 0-1 = 1 goal


def test_closing_favourite_skips_oddsless_matches() -> None:
    match = _match_with_odds()
    assert closing_favourite_predictions([match]) == []


# --- Harness: blocks, leakage, ROI plumbing --------------------------------


def _corpus_results(seed: int = 21) -> list[MatchResult]:
    return to_match_results(synthetic_matches(seed=seed, leagues=("E0",), n_teams=8, n_weeks=30))


def test_blocks_skip_warmup_and_roll_forward() -> None:
    results = _corpus_results()
    config = BacktestConfig(block_days=7, min_training_matches=40, arms=("dixon-coles",))
    report = run_backtest(results, config)
    assert report.n_blocks >= 2
    first_block_matches = sum(
        1 for record in report.records if record.block_start == report.started
    )
    assert first_block_matches > 0
    # Warm-up: no record predates the training minimum.
    all_dates = [match.date for match in results]
    for record in report.records:
        prior = sum(1 for d in all_dates if d < record.date)
        assert prior >= config.min_training_matches


def test_harness_leakage_later_matches_do_not_affect_earlier_blocks() -> None:
    results = _corpus_results(seed=21)
    config = BacktestConfig(block_days=7, min_training_matches=40, arms=("dixon-coles",))

    baseline_report = run_backtest(results, config)
    first_block_start = baseline_report.started

    # Corrupt everything from the second block onwards.
    second_block_start = first_block_start + timedelta(days=config.block_days)
    corrupted = [
        match
        if match.date < second_block_start
        else match.model_copy(update={"home_goals": 9, "away_goals": 9})
        for match in results
    ]
    corrupted_report = run_backtest(corrupted, config)

    first = [
        record for record in baseline_report.records if record.block_start == first_block_start
    ]
    second = [
        record for record in corrupted_report.records if record.block_start == first_block_start
    ]
    assert [r.home for r in first] == [r.home for r in second]


def test_roi_counts_bets_and_settles_with_closing_odds() -> None:
    results = _corpus_results(seed=5)
    config = BacktestConfig(block_days=7, min_training_matches=40, arms=("dixon-coles",))
    report = run_backtest(results, config)
    arm = report.arms["dixon-coles"]
    assert arm.roi.n_bets > 0
    assert arm.roi.total_staked == pytest.approx(arm.roi.n_bets)
    # Every bet's profit is settled from odds > 1.
    for record in report.records:
        for pick in record.picks:
            if pick.odds is not None:
                expected = (pick.odds - 1.0) if pick.won else -1.0
                assert pick.profit == pytest.approx(expected)


def test_clv_summary_present() -> None:
    results = _corpus_results(seed=5)
    config = BacktestConfig(block_days=7, min_training_matches=40, arms=("dixon-coles",))
    report = run_backtest(results, config)
    clv = report.arms["dixon-coles"].clv
    assert clv.n >= 0
    assert 0.0 <= clv.beat_rate <= 1.0


def test_gate_reported_not_asserted() -> None:
    results = _corpus_results(seed=5)
    config = BacktestConfig(block_days=14, min_training_matches=40)
    report = run_backtest(results, config)
    assert report.gate.hybrid == "gbm-poisson"
    assert len(report.gate.comparisons) == 2  # dixon-coles + closing-favourite
    for comparison in report.gate.comparisons:
        assert comparison.hybrid_1x2_log_loss >= 0.0
        assert comparison.benchmark_1x2_log_loss >= 0.0
        # A boolean verdict exists either way.
        assert isinstance(comparison.hybrid_wins, bool)


def test_unknown_arm_raises() -> None:
    results = _corpus_results()
    config = BacktestConfig(block_days=7, min_training_matches=40, arms=("no-such-arm",))
    with pytest.raises(ValueError, match="unknown arm"):
        run_backtest(results, config)
