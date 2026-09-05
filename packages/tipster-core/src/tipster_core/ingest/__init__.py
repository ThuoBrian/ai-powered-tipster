"""Ingestion layer: source-specific fetchers and parsers, plus orchestration."""

from tipster_core.ingest.football_data import csv_url, download_csv, parse_matches_csv
from tipster_core.ingest.pipeline import DEFAULT_RAW_DIR, ingest_season

__all__ = [
    "DEFAULT_RAW_DIR",
    "csv_url",
    "download_csv",
    "ingest_season",
    "parse_matches_csv",
]
