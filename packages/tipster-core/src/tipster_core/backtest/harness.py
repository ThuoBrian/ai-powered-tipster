"""The walk-forward backtest harness (ADR 0003, ADR 0005).

The only accepted evaluation protocol: train on the past, predict the next
block, roll forward. No random splits — leakage in sports data is silent
and fatal.

Blocks are rolling date windows of ``block_days`` days anchored on the
first evaluable date (the data carries no gameweek column). All leagues are
pooled per block; a league with no fixtures in a block simply contributes
nothing. Arms are refitted from scratch every block, so an arm's
prediction for block *k* is provably independent of every match from block
*k* onwards.

Arms:

- ``gbm-poisson``: the hybrid, isotonic-calibrated (ADR 0003)
- ``dixon-coles``: the pure DC reference, isotonic-calibrated — the
  benchmark the hybrid must beat
- ``closing-favourite``: the degenerate odds-fed baseline

Odds coverage note (ADR 0005): the store's odds columns are 1X2 only, so
flat-stake ROI and CLV are computed on the 1X2 market only. O/U and BTTS
are scored probabilistically (Brier, log loss, reliability).

The gate is reported, never asserted: on synthetic data the comparison is
meaningless; on the real corpus it is ADR 0003's complexity justification.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from tipster_core.backtest import metrics
from tipster_core.backtest.baselines import (
    closing_favourite_predictions,
    closing_odds,
    opening_odds,
)
from tipster_core.backtest.metrics import OutcomeVariant
from tipster_core.backtest.results import (
    ArmReport,
    BacktestReport,
    ClvSummary,
    FamilyMetrics,
    FixtureRecord,
    GateComparison,
    GateResult,
    PickRecord,
    ReliabilityBin,
    ReliabilityCurve,
    RoiSummary,
)
from tipster_core.contracts import MatchPrediction, MatchResult, OutcomeOdds
from tipster_core.model import DixonColesPredictor, GbmPoissonPredictor
from tipster_core.model.calibration import CalibratedPredictor
from tipster_core.predictor import Predictor

_HYBRID = "gbm-poisson"
_DC = "dixon-coles"
_BASELINE = "closing-favourite"

#: Arm factories: fresh (uncalibrated) predictors, fitted once per block.
DEFAULT_ARM_FACTORIES: dict[str, Callable[[], Predictor]] = {
    _HYBRID: lambda: CalibratedPredictor(GbmPoissonPredictor()),
    _DC: lambda: CalibratedPredictor(DixonColesPredictor()),
}

_VARIANTS: tuple[OutcomeVariant, ...] = ("home", "draw", "away", "over25", "btts")


@dataclass(frozen=True)
class BacktestConfig:
    """Walk-forward knobs (ADR 0005)."""

    block_days: int = 7
    min_training_matches: int = 400
    arms: tuple[str, ...] = (_HYBRID, _DC, _BASELINE)
    start_date: date | None = None
    end_date: date | None = None


def _blocks(
    played: Sequence[MatchResult], config: BacktestConfig
) -> list[tuple[date, list[MatchResult]]]:
    """Group evaluable matches into rolling ``block_days`` date windows."""
    all_ordered = sorted(played, key=lambda match: match.date)
    dates = [match.date for match in all_ordered]

    evaluable = [
        match
        for match in all_ordered
        if config.start_date is None or match.date >= config.start_date
    ]
    evaluable = [m for m in evaluable if config.end_date is None or m.date <= config.end_date]
    evaluable = [
        match
        for match in evaluable
        if bisect_left(dates, match.date) >= config.min_training_matches
    ]
    if not evaluable:
        return []

    anchor = evaluable[0].date
    blocks: dict[date, list[MatchResult]] = {}
    for match in evaluable:
        offset = (match.date - anchor).days
        start = anchor + timedelta(days=(offset // config.block_days) * config.block_days)
        blocks.setdefault(start, []).append(match)
    return sorted(blocks.items(), key=lambda item: item[0])


def _outcome_1x2(match: MatchResult) -> Literal[0, 1, 2]:
    """0 = home, 1 = draw, 2 = away — the (home, draw, away) index order."""
    if match.home_goals > match.away_goals:
        return 0
    if match.home_goals == match.away_goals:
        return 1
    return 2


def _variant_value(prediction: MatchPrediction, variant: OutcomeVariant) -> float:
    values = {
        "home": prediction.markets.home,
        "draw": prediction.markets.draw,
        "away": prediction.markets.away,
        "over25": prediction.markets.over25,
        "btts": prediction.markets.btts_yes,
    }
    return values[variant]


def _variant_outcome(match: MatchResult, variant: OutcomeVariant) -> bool:
    home_goals, away_goals = match.home_goals, match.away_goals
    outcomes = {
        "home": home_goals > away_goals,
        "draw": home_goals == away_goals,
        "away": home_goals < away_goals,
        "over25": home_goals + away_goals >= 3,
        "btts": home_goals >= 1 and away_goals >= 1,
    }
    return outcomes[variant]


def _pick_1x2(prediction: MatchPrediction) -> tuple[str, int]:
    """The arm's 1X2 argmax as ``(label, outcome index)``."""
    probs = (
        ("home", 0, prediction.markets.home),
        ("draw", 1, prediction.markets.draw),
        ("away", 2, prediction.markets.away),
    )
    label, index, _p = max(probs, key=lambda item: item[2])
    return label, index


def _odds_for(odds: OutcomeOdds | None, index: int) -> float | None:
    """The 1X2 odds for an outcome index, or None."""
    if odds is None:
        return None
    return (odds.home, odds.draw, odds.away)[index]


def _score_arm(
    model: str, pairs: list[tuple[date, MatchResult, MatchPrediction]]
) -> tuple[ArmReport, list[FixtureRecord]]:
    """All metrics for one arm from its ``(block_start, match, prediction)`` pairs."""
    n = len(pairs)
    probs_1x2 = [(p.markets.home, p.markets.draw, p.markets.away) for _, _, p in pairs]
    outcomes_1x2 = [_outcome_1x2(m) for _, m, _ in pairs]
    over_probs = [p.markets.over25 for _, _, p in pairs]
    over_outs = [m.home_goals + m.away_goals >= 3 for _, m, _ in pairs]
    btts_probs = [p.markets.btts_yes for _, _, p in pairs]
    btts_outs = [m.home_goals >= 1 and m.away_goals >= 1 for _, m, _ in pairs]
    # Correct-score mass beyond the matrix (a 9-goal thriller vs an 8-cap
    # grid, or any true score vs the baseline's degenerate 2x2) counts as
    # zero — the clip in log_loss handles the rest.
    correct_cells = [
        p.matrix.p(m.home_goals, m.away_goals)
        if m.home_goals < len(p.matrix.rows) and m.away_goals < len(p.matrix.rows)
        else 0.0
        for _, m, p in pairs
    ]

    families: dict[str, FamilyMetrics] = {
        "1x2": FamilyMetrics(
            brier=metrics.brier_1x2(probs_1x2, outcomes_1x2),
            log_loss=metrics.log_loss_1x2(probs_1x2, outcomes_1x2),
            n=n,
        ),
        "over25": FamilyMetrics(
            brier=metrics.brier_binary(over_probs, over_outs),
            log_loss=metrics.log_loss_binary(over_probs, over_outs),
            n=n,
        ),
        "btts": FamilyMetrics(
            brier=metrics.brier_binary(btts_probs, btts_outs),
            log_loss=metrics.log_loss_binary(btts_probs, btts_outs),
            n=n,
        ),
        # Correct score has no Brier analogue at cell granularity; scored by
        # observed-cell log loss only (ADR 0005).
        "correct-score": FamilyMetrics(
            brier=0.0,
            log_loss=metrics.log_loss_correct_score(correct_cells),
            n=n,
        ),
    }

    reliability: dict[str, ReliabilityCurve] = {}
    for variant in _VARIANTS:
        bins = metrics.reliability(
            [_variant_value(p, variant) for _, _, p in pairs],
            [_variant_outcome(m, variant) for _, m, _ in pairs],
        )
        reliability[variant] = ReliabilityCurve(
            family=variant,
            bins=tuple(
                ReliabilityBin(
                    bin_midpoint=b[0], predicted_mean=b[1], observed_rate=b[2], count=b[3]
                )
                for b in bins
            ),
        )

    # 1X2 flat-stake ROI and CLV (the only market with settled odds).
    picks: list[PickRecord] = []
    staked = 0.0
    profit = 0.0
    n_bets = 0
    clv_values: list[float] = []
    clv_beats = 0

    for _, match, prediction in pairs:
        label, index = _pick_1x2(prediction)
        pick_probability = (
            prediction.markets.home,
            prediction.markets.draw,
            prediction.markets.away,
        )[index]
        won = _outcome_1x2(match) == index
        chosen = closing_odds(match)
        odds_value = _odds_for(chosen[0], index) if chosen else None
        source = chosen[1] if (chosen and odds_value is not None) else None
        if odds_value is not None:
            bet_profit = metrics.flat_stake(odds_value, won)
            staked += 1.0
            profit += bet_profit
            n_bets += 1
            picks.append(
                PickRecord(
                    family="1x2",
                    pick=label,
                    probability=pick_probability,
                    odds=odds_value,
                    odds_source=source,
                    won=won,
                    profit=bet_profit,
                )
            )
        else:
            picks.append(
                PickRecord(
                    family="1x2",
                    pick=label,
                    probability=pick_probability,
                    odds=None,
                    odds_source=None,
                    won=won,
                    profit=0.0,
                )
            )

        opened = opening_odds(match)
        pinnacle_closing = match.odds.pinnacle_closing if match.odds else None
        if opened and pinnacle_closing is not None:
            taken = _odds_for(opened[0], index)
            closed = _odds_for(pinnacle_closing, index)
            if taken is not None and closed is not None:
                value = metrics.clv(taken, closed)
                clv_values.append(value)
                if value > 0:
                    clv_beats += 1

    roi = RoiSummary(
        total_staked=staked,
        total_profit=profit,
        roi_pct=(profit / staked * 100.0) if staked > 0 else 0.0,
        n_bets=n_bets,
    )
    clv_summary = ClvSummary(
        n=len(clv_values),
        mean_clv_pct=(sum(clv_values) / len(clv_values) * 100.0) if clv_values else 0.0,
        beat_rate=(clv_beats / len(clv_values)) if clv_values else 0.0,
    )

    records = [
        FixtureRecord(
            league=match.league.value,
            season=match.season,
            date=match.date,
            home_team=match.home_team,
            away_team=match.away_team,
            block_start=block_start,
            true_home_goals=match.home_goals,
            true_away_goals=match.away_goals,
            model=model,
            home=prediction.markets.home,
            draw=prediction.markets.draw,
            away=prediction.markets.away,
            over25=prediction.markets.over25,
            under25=prediction.markets.under25,
            btts_yes=prediction.markets.btts_yes,
            btts_no=prediction.markets.btts_no,
            picks=(pick,),
        )
        for (block_start, match, prediction), pick in zip(pairs, picks, strict=True)
    ]

    return (
        ArmReport(
            model=model,
            n_fixtures=n,
            families=families,
            reliability=reliability,
            roi=roi,
            clv=clv_summary,
            hit_rate_1x2=(sum(pick.won for pick in picks) / n) if n else 0.0,
        ),
        records,
    )


def run_backtest(
    played: Sequence[MatchResult],
    config: BacktestConfig | None = None,
    arm_factories: dict[str, Callable[[], Predictor]] | None = None,
) -> BacktestReport:
    """Run the walk-forward protocol over the played corpus.

    *played* must already be validated ``MatchResult`` objects. Every arm is
    refitted per block on strictly-past matches only.
    """
    config = config or BacktestConfig()
    factories = dict(DEFAULT_ARM_FACTORIES)
    if arm_factories:
        factories.update(arm_factories)

    blocks = _blocks(played, config)
    all_ordered = sorted(played, key=lambda match: match.date)

    arm_pairs: dict[str, list[tuple[date, MatchResult, MatchPrediction]]] = {
        arm: [] for arm in config.arms
    }
    for block_start, block_matches in blocks:
        train = [match for match in all_ordered if match.date < block_start]
        fixtures = [match.to_fixture() for match in block_matches]
        for arm in config.arms:
            if arm == _BASELINE:
                pred_by_fixture = {
                    prediction.fixture: prediction
                    for prediction in closing_favourite_predictions(block_matches)
                }
                for match, fixture in zip(block_matches, fixtures, strict=True):
                    prediction = pred_by_fixture.get(fixture)
                    if prediction is not None:
                        arm_pairs[arm].append((block_start, match, prediction))
            else:
                factory = factories.get(arm)
                if factory is None:
                    msg = f"unknown arm {arm!r}; known model arms: {sorted(factories)}"
                    raise ValueError(msg)
                predictor = factory()
                predictor.fit(train)
                predictions = predictor.predict(fixtures)
                arm_pairs[arm].extend(
                    zip(
                        [block_start] * len(block_matches),
                        block_matches,
                        predictions,
                        strict=True,
                    )
                )

    reports: dict[str, ArmReport] = {}
    all_records: list[FixtureRecord] = []
    for arm in config.arms:
        arm_report, records = _score_arm(arm, arm_pairs[arm])
        reports[arm] = arm_report
        all_records.extend(records)

    gate = _gate(reports, config)
    return BacktestReport(
        started=blocks[0][0] if blocks else date.min,
        ended=max(block_start for block_start, _ in blocks) if blocks else date.min,
        block_days=config.block_days,
        n_blocks=len(blocks),
        arms=reports,
        gate=gate,
        records=tuple(all_records),
    )


def _gate(reports: dict[str, ArmReport], config: BacktestConfig) -> GateResult:
    """ADR 0003's gate: the hybrid must beat every benchmark on 1X2 quality."""
    hybrid = reports.get(_HYBRID)
    comparisons: list[GateComparison] = []
    if hybrid is not None:
        hybrid_loss = hybrid.families["1x2"].log_loss
        hybrid_brier = hybrid.families["1x2"].brier
        for benchmark in (_DC, _BASELINE):
            other = reports.get(benchmark)
            if other is None:
                continue
            comparisons.append(
                GateComparison(
                    benchmark=benchmark,
                    hybrid_1x2_log_loss=hybrid_loss,
                    benchmark_1x2_log_loss=other.families["1x2"].log_loss,
                    hybrid_1x2_brier=hybrid_brier,
                    benchmark_1x2_brier=other.families["1x2"].brier,
                    hybrid_wins=hybrid_loss < other.families["1x2"].log_loss
                    and hybrid_brier < other.families["1x2"].brier,
                )
            )
    return GateResult(
        hybrid=_HYBRID,
        comparisons=tuple(comparisons),
        passes=all(c.hybrid_wins for c in comparisons) if comparisons else False,
    )
