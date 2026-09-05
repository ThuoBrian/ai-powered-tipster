"""``tipster-ingest`` — pull football-data.co.uk data into the tipster DuckDB.

Usage::

    tipster-ingest [--leagues E0,SP1,D1,I1,F1] [--seasons 2425,2526,2627]
                   [--db PATH] [--raw-dir PATH] [--refresh]

Each (league, season) pair is ingested independently — one failure (e.g. a
season file that does not exist yet) does not stop the rest.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from tipster_core.ingest.pipeline import DEFAULT_RAW_DIR, ingest_season
from tipster_core.leagues import BIG_5, LeagueCode

DEFAULT_LEAGUES = ",".join(league.value for league in BIG_5)
DEFAULT_SEASONS = "2425,2526,2627"


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="tipster-ingest",
        description="Ingest football-data.co.uk CSVs into the tipster DuckDB.",
    )
    parser.add_argument(
        "--leagues",
        default=DEFAULT_LEAGUES,
        help="comma-separated league codes (default: big 5)",
    )
    parser.add_argument(
        "--seasons",
        default=DEFAULT_SEASONS,
        help="comma-separated season codes (default: 2425,2526,2627)",
    )
    parser.add_argument(
        "--db",
        default="data/tipster.duckdb",
        help="DuckDB path (default: data/tipster.duckdb)",
    )
    parser.add_argument(
        "--raw-dir",
        default=str(DEFAULT_RAW_DIR),
        help=f"raw CSV cache directory (default: {DEFAULT_RAW_DIR})",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="re-download CSVs even if cached",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ingest; returns a process exit code."""
    args = build_parser().parse_args(argv)
    leagues = [LeagueCode.from_code(code) for code in _split(args.leagues)]
    seasons = _split(args.seasons)

    failures: list[str] = []
    total = 0
    for league in leagues:
        for season in seasons:
            label = f"{league.value} {season}"
            try:
                frame = ingest_season(
                    league,
                    season,
                    db_path=args.db,
                    raw_dir=args.raw_dir,
                    refresh=args.refresh,
                )
            except Exception as error:
                failures.append(label)
                print(f"  {label}: FAILED ({error})")
                continue
            total += frame.height
            print(f"  {label}: {frame.height} matches")

    print(f"Ingested {total} matches into {args.db}")
    if failures:
        print(f"Failed: {', '.join(failures)}")
        return 1
    return 0


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
