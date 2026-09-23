"""``tipster-odds`` — fetch live 1X2 odds from The Odds API (ADR 0002, ADR 0007).

Usage::

    tipster-odds [--leagues E0,SP1,D1,I1,F1] [--cache-dir PATH] [--no-refresh]

Reads the API key from ``THE_ODDS_API_KEY`` (see ``.env.example``). Each
league is fetched independently — one failure does not stop the rest. Live
odds are never written to the matches DuckDB (that table is played-match
history); this CLI is a manual/scheduled check, piping straight into the
value engine (``tipster_core.value.find_value_tips``).
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from tipster_core.contracts import MatchOdds
from tipster_core.ingest.pipeline import DEFAULT_ODDS_CACHE_DIR, fetch_live_odds
from tipster_core.leagues import BIG_5, LeagueCode

DEFAULT_LEAGUES = ",".join(league.value for league in BIG_5)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="tipster-odds",
        description="Fetch live 1X2 odds from The Odds API.",
    )
    parser.add_argument(
        "--leagues",
        default=DEFAULT_LEAGUES,
        help="comma-separated league codes (default: big 5)",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_ODDS_CACHE_DIR),
        help=f"raw JSON cache directory (default: {DEFAULT_ODDS_CACHE_DIR})",
    )
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="replay the last cached response instead of spending an API request",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the live-odds fetch; returns a process exit code."""
    args = build_parser().parse_args(argv)
    api_key = os.environ.get("THE_ODDS_API_KEY")
    if not api_key:
        print("THE_ODDS_API_KEY is not set (see .env.example)")
        return 1

    leagues = [LeagueCode.from_code(code) for code in _split(args.leagues)]
    failures: list[str] = []
    total = 0
    for league in leagues:
        try:
            pairs = fetch_live_odds(
                league, api_key, cache_dir=args.cache_dir, refresh=not args.no_refresh
            )
        except Exception as error:
            failures.append(league.value)
            print(f"  {league.value}: FAILED ({error})")
            continue
        total += len(pairs)
        print(f"  {league.value}: {len(pairs)} fixtures priced")
        for fixture, odds in pairs:
            print(f"    {fixture.fixture} ({fixture.date}) — sources: {_sources(odds)}")

    print(f"Fetched odds for {total} fixtures")
    if failures:
        print(f"Failed: {', '.join(failures)}")
        return 1
    return 0


def _sources(odds: MatchOdds) -> str:
    names = [
        name
        for name, value in (
            ("pinnacle", odds.pinnacle),
            ("b365", odds.b365),
            ("avg", odds.avg),
            ("max", odds.max),
        )
        if value is not None
    ]
    return ", ".join(names) or "none"


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
