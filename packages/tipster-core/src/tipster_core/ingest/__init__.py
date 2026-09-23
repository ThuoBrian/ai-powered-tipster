"""Ingestion layer: source-specific fetchers and parsers, plus orchestration."""

from tipster_core.ingest.football_data import csv_url, download_csv, parse_matches_csv
from tipster_core.ingest.odds_api import fetch_odds, odds_url, parse_odds_response
from tipster_core.ingest.pipeline import (
    DEFAULT_ODDS_CACHE_DIR,
    DEFAULT_RAW_DIR,
    fetch_live_odds,
    ingest_season,
)

__all__ = [
    "DEFAULT_ODDS_CACHE_DIR",
    "DEFAULT_RAW_DIR",
    "csv_url",
    "download_csv",
    "fetch_live_odds",
    "fetch_odds",
    "ingest_season",
    "odds_url",
    "parse_matches_csv",
    "parse_odds_response",
]
