"""``tipster-ingest`` — pull match data into the tipster DuckDB (ADR 0002, ADR 0011).

Usage::

    tipster-ingest [--leagues E0,SP1,BRA,INT,...] [--seasons 2425,2526,2627]
                   [--db PATH] [--raw-dir PATH] [--refresh]

Default is every competition. Main football-data.co.uk divisions ingest one
file per (league, season); extra leagues (``BRA``, ``USA``, ...) and
internationals (``INT``) are one all-seasons file each, so ``--seasons``
doesn't apply to them. The current season's file is always re-downloaded
(new results land in it every week); finished seasons reuse the raw cache
unless ``--refresh``. Each file is ingested independently — one failure
does not stop the rest.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import date
from functools import partial

import polars as pl

from tipster_core.ingest.pipeline import (
    DEFAULT_RAW_DIR,
    ingest_extra_league,
    ingest_internationals,
    ingest_season,
)
from tipster_core.leagues import EXTRA_LEAGUES, LeagueCode, season_from_date

DEFAULT_LEAGUES = ",".join(league.value for league in LeagueCode)
DEFAULT_SEASONS = "2425,2526,2627"


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="tipster-ingest",
        description="Ingest football-data.co.uk and international results into the DuckDB.",
    )
    parser.add_argument(
        "--leagues",
        default=DEFAULT_LEAGUES,
        help="comma-separated league codes (default: every competition)",
    )
    parser.add_argument(
        "--seasons",
        default=DEFAULT_SEASONS,
        help="comma-separated season codes for main divisions (default: 2425,2526,2627)",
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
        help="re-download finished seasons too (the current season always refreshes)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ingest; returns a process exit code."""
    args = build_parser().parse_args(argv)
    leagues = [LeagueCode.from_code(code) for code in _split(args.leagues)]
    seasons = _split(args.seasons)
    current = season_from_date(date.today())

    failures: list[str] = []
    total = 0

    def run(label: str, job: Callable[[], pl.DataFrame]) -> None:
        nonlocal total
        try:
            frame = job()
        except Exception as error:
            failures.append(label)
            print(f"  {label}: FAILED ({error})")
            return
        total += frame.height
        print(f"  {label}: {frame.height} matches")

    where = {"db_path": args.db, "raw_dir": args.raw_dir}
    for league in leagues:
        if league is LeagueCode.INTERNATIONAL:
            run(league.value, partial(ingest_internationals, **where))
        elif league in EXTRA_LEAGUES:
            run(league.value, partial(ingest_extra_league, league, **where))
        else:
            for season in seasons:
                refresh = args.refresh or season == current
                run(
                    f"{league.value} {season}",
                    partial(ingest_season, league, season, refresh=refresh, **where),
                )

    print(f"Ingested {total} matches into {args.db}")
    if failures:
        print(f"Failed: {', '.join(failures)}")
        return 1
    return 0


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
