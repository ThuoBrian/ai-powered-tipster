"""Ingest orchestration: fetch (with raw caching) → parse → store."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from tipster_core.contracts import Fixture, MatchOdds
from tipster_core.ingest.football_data import (
    EXTRA_SINCE,
    csv_url,
    download_csv,
    extra_csv_url,
    parse_extra_csv,
    parse_matches_csv,
)
from tipster_core.ingest.internationals import (
    INTERNATIONALS_SINCE,
    INTERNATIONALS_URL,
    parse_internationals_csv,
)
from tipster_core.ingest.odds_api import INT_TOURNAMENTS, fetch_odds, parse_odds_response
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
    _store_by_season(frame, db_path)
    return frame


def ingest_extra_league(
    league: LeagueCode,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    raw_dir: str | Path = DEFAULT_RAW_DIR,
    since: date = EXTRA_SINCE,
) -> pl.DataFrame:
    """Ingest an extra league's all-seasons file (always re-downloaded: it grows weekly)."""
    content = download_csv(extra_csv_url(league), marker=b"Home")
    cache = _cache_raw(Path(raw_dir) / f"{league.value}.csv", content)
    frame = parse_extra_csv(content, league, since=since, source_file=cache.name)
    _store_by_season(frame, db_path)
    return frame


def ingest_internationals(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    raw_dir: str | Path = DEFAULT_RAW_DIR,
    since: date = INTERNATIONALS_SINCE,
) -> pl.DataFrame:
    """Ingest national-team results (always re-downloaded: it grows weekly)."""
    content = download_csv(INTERNATIONALS_URL, timeout=120.0, marker=b"home_team")
    cache = _cache_raw(Path(raw_dir) / "INT.csv", content)
    frame = parse_internationals_csv(content, since=since, source_file=cache.name)
    _store_by_season(frame, db_path)
    return frame


def _cache_raw(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _store_by_season(frame: pl.DataFrame, db_path: str | Path) -> None:
    """``replace_season`` once per season in *frame* (it takes one season at a time)."""
    con = connect(db_path)
    try:
        for season in frame.get_column("season").unique().sort().to_list():
            replace_season(con, frame.filter(pl.col("season") == season))
    finally:
        con.close()


def fetch_live_odds(
    league: LeagueCode,
    api_key: str,
    *,
    sport_key: str | None = None,
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

    *sport_key* picks one feed within a league — required for
    ``LeagueCode.INTERNATIONAL``, where each tournament is its own feed and
    sets whether its games are at neutral venues (``INT_TOURNAMENTS``).
    """
    cache = Path(cache_dir) / f"{sport_key or league.value}.json"
    if not refresh and cache.exists():
        content = cache.read_bytes()
    else:
        content = fetch_odds(league, api_key, sport_key=sport_key)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(content)
    _label, neutral = INT_TOURNAMENTS.get(sport_key or "", ("", False))
    return parse_odds_response(content, league, neutral=neutral)
