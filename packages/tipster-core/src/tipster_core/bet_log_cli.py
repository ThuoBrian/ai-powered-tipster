"""``tipster-bets`` — settle pending paper bets and print the ledger summary.

Usage::

    tipster-bets [--db PATH] [--bet-log PATH] [--leagues E0,...] [--seasons 2425,...]

Settlement matches a pending bet's (league, season, date, home team, away
team) against the matches DuckDB — a bet whose match hasn't been ingested
yet (or hasn't been played yet) is left pending, never guessed. Run this
after ``make ingest`` picks up newly played fixtures.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from tipster_core import bet_log
from tipster_core.leagues import LeagueCode
from tipster_core.storage import DEFAULT_DB_PATH, connect, load_match_results


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="tipster-bets",
        description="Settle pending paper bets against played matches and print the ledger.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"matches DuckDB path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--bet-log",
        default=str(bet_log.DEFAULT_BET_LOG_PATH),
        help=f"bet log SQLite path (default: {bet_log.DEFAULT_BET_LOG_PATH})",
    )
    parser.add_argument(
        "--leagues",
        default="",
        help="comma-separated league codes (default: every league in the store)",
    )
    parser.add_argument(
        "--seasons",
        default="",
        help="comma-separated season codes (default: every season in the store)",
    )
    return parser


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    """Settle bets and print the ledger summary; returns a process exit code."""
    args = build_parser().parse_args(argv)
    leagues = [LeagueCode.from_code(code) for code in _split(args.leagues)] or None
    seasons = _split(args.seasons) or None

    match_con = connect(args.db, read_only=True)
    try:
        played = load_match_results(match_con, leagues=leagues, seasons=seasons)
    finally:
        match_con.close()

    ledger_con = bet_log.connect(args.bet_log)
    try:
        settled = bet_log.settle_bets(ledger_con, played)
        summary = bet_log.summarize(ledger_con)
    finally:
        ledger_con.close()

    print(f"Settled {settled} bet(s) this run.")
    print(f"Pending: {summary.n_pending}   Settled (all-time): {summary.n_settled}")
    print(
        f"Kelly:  staked {summary.kelly.total_staked:.3f}u  "
        f"profit {summary.kelly.total_profit:+.3f}u  ROI {summary.kelly.roi_pct:+.2f}%"
    )
    print(
        f"Flat:   staked {summary.flat.total_staked:.2f}u  "
        f"profit {summary.flat.total_profit:+.2f}u  ROI {summary.flat.roi_pct:+.2f}%"
    )
    if summary.clv.n:
        print(
            f"CLV: mean {summary.clv.mean_clv_pct:+.2f}%  "
            f"beat rate {summary.clv.beat_rate:.1%} on {summary.clv.n} settled pick(s)"
        )
    return 0
