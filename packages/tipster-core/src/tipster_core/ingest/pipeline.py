"""Ingest orchestration: fetch (with raw caching) → parse → store."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from tipster_core.contracts import Fixture, MatchOdds
from tipster_core.ingest.football_data import csv_url, download_csv, parse_matches_csv
from tipster_core.ingest.odds_api import fetch_odds, parse_odds_response
from tipster_core.leagues import LeagueCode
from tipster_core.storage import DEFAULT_DB_PATH, connect, replace_season

DEFAULT_RAW_DIR = Path("data") / "raw"
DEFAULT_ODDS_CACHE_DIR = DEFAULT_RAW_DIR / "live_odds"


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


def fetch_live_odds(
    league: LeagueCode,
    api_key: str,
    *,
    cache_dir: str | Path = DEFAULT_ODDS_CACHE_DIR,
    refresh: bool = True,
) -> list[tuple[Fixture, MatchOdds]]:
    """Fetch and parse one league's live 1X2 odds from The Odds API.

    Unlike ``ingest_season``'s historical CSVs, a live snapshot goes stale
    immediately, so ``refresh`` defaults to ``True``: every call spends one
    of the free tier's 500 monthly requests (ADR 0002) and overwrites the
    cache. Pass ``refresh=False`` to replay the last cached response instead
    (or fetch once if nothing is cached yet) — useful for UI development
    without burning quota.
    """
    cache = Path(cache_dir) / f"{league.value}.json"
    if not refresh and cache.exists():
        content = cache.read_bytes()
    else:
        content = fetch_odds(league, api_key)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(content)
    return parse_odds_response(content, league)
