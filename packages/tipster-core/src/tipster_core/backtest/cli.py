"""``tipster-backtest`` — walk-forward backtest over the tipster DuckDB.

Usage::

    tipster-backtest [--db PATH] [--leagues E0,...] [--seasons 2425,...]
                     [--start-date 2025-01-01] [--end-date 2025-05-01]
                     [--block-days 7] [--min-training-matches 400]
                     [--arms gbm-poisson,dixon-coles,closing-favourite]
                     [--out data/backtests]

Trains on the past, predicts each block, rolls forward (ADR 0005), then
prints per-arm Brier / log loss per market family, flat-stake ROI, CLV, and
the ADR 0003 gate verdict. Artifacts land under ``--out``:

- ``report.json`` — config, per-arm metrics, gate
- ``predictions.parquet`` — per-fixture records
- ``reliability.parquet`` — reliability-curve bins
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from tipster_core.backtest.harness import BacktestConfig, run_backtest
from tipster_core.backtest.results import BacktestReport
from tipster_core.contracts import MatchOdds, MatchResult, OutcomeOdds
from tipster_core.leagues import BIG_5, LeagueCode
from tipster_core.storage import DEFAULT_DB_PATH, connect, load_matches

DEFAULT_ARMS = "gbm-poisson,dixon-coles,closing-favourite"
DEFAULT_OUT = Path("data") / "backtests"


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="tipster-backtest",
        description="Run the walk-forward backtest over the tipster DuckDB.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"DuckDB path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--leagues",
        default=",".join(league.value for league in BIG_5),
        help="comma-separated league codes (default: big 5)",
    )
    parser.add_argument(
        "--seasons",
        default="",
        help="comma-separated season codes (default: all in store)",
    )
    parser.add_argument(
        "--start-date",
        type=_parse_date,
        default=None,
        help="first evaluable match date (default: warm-up decides)",
    )
    parser.add_argument(
        "--end-date",
        type=_parse_date,
        default=None,
        help="last evaluable match date (default: none)",
    )
    parser.add_argument(
        "--block-days",
        type=int,
        default=7,
        help="block length in days (default: 7)",
    )
    parser.add_argument(
        "--min-training-matches",
        type=int,
        default=400,
        help="warm-up: matches before the first evaluable block (default: 400)",
    )
    parser.add_argument(
        "--arms",
        default=DEFAULT_ARMS,
        help=f"comma-separated arms (default: {DEFAULT_ARMS})",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help=f"artifact directory (default: {DEFAULT_OUT})",
    )
    return parser


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _odds_from_row(row: dict[str, Any]) -> MatchOdds | None:
    """Build the MatchOdds from the frame's 24 odds columns, if any group is full."""

    def outcome(source: str, closing: str) -> OutcomeOdds | None:
        home, draw, away = (
            row[f"odds_{source}{closing}_h"],
            row[f"odds_{source}{closing}_d"],
            row[f"odds_{source}{closing}_a"],
        )
        if home is None or draw is None or away is None:
            return None
        return OutcomeOdds(home=float(home), draw=float(draw), away=float(away))

    odds = MatchOdds(
        b365=outcome("b365", ""),
        pinnacle=outcome("pinnacle", ""),
        avg=outcome("avg", ""),
        max=outcome("max", ""),
        b365_closing=outcome("b365", "_c"),
        pinnacle_closing=outcome("pinnacle", "_c"),
        avg_closing=outcome("avg", "_c"),
        max_closing=outcome("max", "_c"),
    )
    if all(getattr(odds, attr) is None for attr in MatchOdds.model_fields):
        return None
    return odds


def _load_results(args: argparse.Namespace) -> list[MatchResult]:
    leagues = [LeagueCode.from_code(code) for code in _split(args.leagues)]
    seasons = _split(args.seasons) or None
    con = connect(args.db, read_only=True)
    try:
        frame = load_matches(con, leagues=leagues, seasons=seasons)
    finally:
        con.close()
    return [
        MatchResult(
            league=row["league"],
            season=row["season"],
            date=row["date"],
            home_team=row["home_team"],
            away_team=row["away_team"],
            home_goals=row["home_goals"],
            away_goals=row["away_goals"],
            odds=_odds_from_row(row),
        )
        for row in frame.iter_rows(named=True)
    ]


def _print_report(report: BacktestReport) -> None:
    print(
        f"Walk-forward: {report.n_blocks} blocks x {report.block_days} days, "
        f"{report.started} .. {report.ended}"
    )
    for name, arm in report.arms.items():
        print(f"\n[{name}] {arm.n_fixtures} fixtures")
        for family, metrics in arm.families.items():
            print(f"  {family:>14}: brier {metrics.brier:.4f}  log loss {metrics.log_loss:.4f}")
        print(
            f"  ROI: {arm.roi.roi_pct:+.2f}% on {arm.roi.n_bets} flat 1-unit bets"
            f" (profit {arm.roi.total_profit:+.2f})"
        )
        print(
            f"  CLV vs Pinnacle close: {arm.clv.mean_clv_pct:+.2f}% mean,"
            f" beat rate {arm.clv.beat_rate:.1%} on {arm.clv.n} picks"
        )
    print("\nGate (hybrid must beat every benchmark on 1X2):")
    for comparison in report.gate.comparisons:
        verdict = "WINS" if comparison.hybrid_wins else "loses"
        print(
            f"  vs {comparison.benchmark}: log loss"
            f" {comparison.hybrid_1x2_log_loss:.4f} vs {comparison.benchmark_1x2_log_loss:.4f},"
            f" brier {comparison.hybrid_1x2_brier:.4f} vs {comparison.benchmark_1x2_brier:.4f}"
            f" -> hybrid {verdict}"
        )
    print(f"  gate {'PASSED' if report.gate.passes else 'NOT PASSED'}")


def _write_artifacts(report: BacktestReport, out_dir: Path) -> Path:
    run_dir = out_dir / f"run-{datetime.now():%Y%m%d-%H%M}"
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "report.json").write_text(
        json.dumps(
            report.model_dump(exclude={"records"}),
            default=str,
            indent=2,
        )
        + "\n"
    )

    predictions = pl.DataFrame([record.model_dump() for record in report.records])
    if predictions.height:
        predictions.write_parquet(run_dir / "predictions.parquet")

    reliability_rows = [
        {
            "model": arm.model,
            "variant": variant,
            "bin_midpoint": b.bin_midpoint,
            "predicted_mean": b.predicted_mean,
            "observed_rate": b.observed_rate,
            "count": b.count,
        }
        for arm in report.arms.values()
        for variant, curve in arm.reliability.items()
        for b in curve.bins
    ]
    if reliability_rows:
        pl.DataFrame(reliability_rows).write_parquet(run_dir / "reliability.parquet")

    return run_dir


def main(argv: Sequence[str] | None = None) -> int:
    """Run the backtest; returns a process exit code."""
    args = build_parser().parse_args(argv)
    results = _load_results(args)
    if not results:
        print(f"No matches found in {args.db} — run `make ingest` first.")
        return 1

    config = BacktestConfig(
        block_days=args.block_days,
        min_training_matches=args.min_training_matches,
        arms=tuple(_split(args.arms)),
        start_date=args.start_date,
        end_date=args.end_date,
    )
    report = run_backtest(results, config)
    _print_report(report)
    run_dir = _write_artifacts(report, Path(args.out))
    print(f"\nArtifacts written to {run_dir}")
    return 0
