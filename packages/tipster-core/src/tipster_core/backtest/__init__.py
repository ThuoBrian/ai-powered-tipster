"""Walk-forward backtesting: harness, metrics, baselines, and typed reports."""

from tipster_core.backtest.harness import BacktestConfig, run_backtest
from tipster_core.backtest.results import ArmReport, BacktestReport, FixtureRecord

__all__ = [
    "ArmReport",
    "BacktestConfig",
    "BacktestReport",
    "FixtureRecord",
    "run_backtest",
]
