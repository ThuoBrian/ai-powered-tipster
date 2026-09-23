"""Tests for live-odds ingest orchestration: caching and refresh (ADR 0007)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tipster_core.ingest import pipeline
from tipster_core.leagues import LeagueCode

PL = LeagueCode.PREMIER_LEAGUE

_EVENT = [
    {
        "id": "abc123",
        "sport_key": "soccer_epl",
        "commence_time": "2026-01-15T15:00:00Z",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "bookmakers": [
            {
                "key": "bet365",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Arsenal", "price": 1.85},
                            {"name": "Draw", "price": 3.5},
                            {"name": "Chelsea", "price": 4.0},
                        ],
                    }
                ],
            }
        ],
    }
]


def test_fetch_live_odds_writes_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_fetch(league: LeagueCode, api_key: str, **_kwargs: object) -> bytes:
        calls["n"] += 1
        return json.dumps(_EVENT).encode()

    monkeypatch.setattr(pipeline, "fetch_odds", fake_fetch)

    cache_dir = tmp_path / "live_odds"
    results = pipeline.fetch_live_odds(PL, "test-key", cache_dir=cache_dir)

    assert calls["n"] == 1
    assert len(results) == 1
    assert (cache_dir / "E0.json").exists()


def test_fetch_live_odds_no_refresh_reuses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def fake_fetch(league: LeagueCode, api_key: str, **_kwargs: object) -> bytes:
        calls["n"] += 1
        return json.dumps(_EVENT).encode()

    monkeypatch.setattr(pipeline, "fetch_odds", fake_fetch)
    cache_dir = tmp_path / "live_odds"

    pipeline.fetch_live_odds(PL, "test-key", cache_dir=cache_dir, refresh=True)
    pipeline.fetch_live_odds(PL, "test-key", cache_dir=cache_dir, refresh=False)

    assert calls["n"] == 1  # second call replayed the cache, no new API request


def test_fetch_live_odds_no_refresh_fetches_when_nothing_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def fake_fetch(league: LeagueCode, api_key: str, **_kwargs: object) -> bytes:
        calls["n"] += 1
        return json.dumps(_EVENT).encode()

    monkeypatch.setattr(pipeline, "fetch_odds", fake_fetch)
    cache_dir = tmp_path / "live_odds"

    pipeline.fetch_live_odds(PL, "test-key", cache_dir=cache_dir, refresh=False)

    assert calls["n"] == 1
