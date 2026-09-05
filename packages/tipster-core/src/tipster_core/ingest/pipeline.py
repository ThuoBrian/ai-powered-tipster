"""Ingest orchestration: fetch (with raw caching) → parse → store."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from tipster_core.ingest.football_data import csv_url, download_csv, parse_matches_csv
from tipster_core.leagues import LeagueCode
from tipster_core.storage import DEFAULT_DB_PATH, connect, replace_season

DEFAULT_RAW_DIR = Path("data") / "raw"


def ingest_season(
    league: LeagueCode,
    season: str,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    raw_dir: str | Path = DEFAULT_RAW_DIR,
    refresh: bool = False,
) -> pl.DataFrame:
    """Ingest one league-season into DuckDB; returns the canonical frame.

    The raw CSV is cached under ``raw_dir`` (``{league}_{season}.csv``) and
    reused on later runs unless ``refresh`` is set. Storage is idempotent per
    (league, season), so re-running replaces that season's rows.
    """
    cache = Path(raw_dir) / f"{league.value}_{season}.csv"
    if refresh or not cache.exists():
        content = download_csv(csv_url(league, season))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(content)

    frame = parse_matches_csv(cache.read_bytes(), league, season, source_file=cache.name)
    con = connect(db_path)
    try:
        replace_season(con, frame)
    finally:
        con.close()
    return frame
