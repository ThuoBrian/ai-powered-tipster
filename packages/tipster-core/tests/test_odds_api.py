"""Tests for The Odds API parser (pure — no network) (ADR 0007)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from tipster_core.ingest import odds_api
from tipster_core.ingest.odds_api import odds_url, parse_odds_response
from tipster_core.leagues import LeagueCode

PL = LeagueCode.PREMIER_LEAGUE


def _event(
    home: str = "Arsenal",
    away: str = "Chelsea",
    commence: str = "2026-01-15T15:00:00Z",
    bookmakers: list[dict] | None = None,
) -> dict:
    return {
        "id": "abc123",
        "sport_key": "soccer_epl",
        "commence_time": commence,
        "home_team": home,
        "away_team": away,
        "bookmakers": [] if bookmakers is None else bookmakers,
    }


def _bookmaker(key: str, home_price: float, draw_price: float, away_price: float) -> dict:
    return {
        "key": key,
        "title": key,
        "markets": [
            {
                "key": "h2h",
                "outcomes": [
                    {"name": "Arsenal", "price": home_price},
                    {"name": "Draw", "price": draw_price},
                    {"name": "Chelsea", "price": away_price},
                ],
            }
        ],
    }


def test_parses_event_with_multiple_bookmakers() -> None:
    payload = [
        _event(
            bookmakers=[
                _bookmaker("pinnacle", 1.9, 3.6, 4.2),
                _bookmaker("bet365", 1.85, 3.5, 4.0),
                _bookmaker("williamhill", 1.95, 3.7, 4.33),
            ]
        )
    ]
    results = parse_odds_response(json.dumps(payload).encode(), PL)
    assert len(results) == 1
    fixture, odds = results[0]

    assert fixture.league == PL
    assert fixture.season == "2526"
    assert fixture.date == date(2026, 1, 15)
    assert fixture.home_team == "Arsenal"
    assert fixture.away_team == "Chelsea"

    assert odds.pinnacle is not None
    assert odds.pinnacle.home == pytest.approx(1.9)
    assert odds.b365 is not None
    assert odds.b365.home == pytest.approx(1.85)
    # avg/max computed across all three bookmakers.
    assert odds.avg is not None
    assert odds.avg.home == pytest.approx((1.9 + 1.85 + 1.95) / 3)
    assert odds.max is not None
    assert odds.max.home == pytest.approx(1.95)


def test_event_with_no_bookmakers_is_dropped() -> None:
    payload = [_event(bookmakers=[])]
    assert parse_odds_response(json.dumps(payload).encode(), PL) == []


def test_bookmaker_missing_draw_price_is_ignored() -> None:
    incomplete = {
        "key": "sportsbet",
        "markets": [
            {
                "key": "h2h",
                "outcomes": [
                    {"name": "Arsenal", "price": 1.9},
                    {"name": "Chelsea", "price": 4.2},
                ],
            }
        ],
    }
    payload = [_event(bookmakers=[incomplete, _bookmaker("bet365", 1.85, 3.5, 4.0)])]
    results = parse_odds_response(json.dumps(payload).encode(), PL)
    _fixture, odds = results[0]
    assert odds.b365 is not None
    # Only bet365 contributed, so avg/max equal its price exactly.
    assert odds.avg is not None
    assert odds.avg.home == pytest.approx(1.85)


def test_bookmaker_with_implausible_price_is_ignored() -> None:
    glitchy = _bookmaker("glitchy", 0.9, 3.5, 4.0)  # price <= 1.0 is never valid decimal odds
    payload = [_event(bookmakers=[glitchy, _bookmaker("bet365", 1.85, 3.5, 4.0)])]
    results = parse_odds_response(json.dumps(payload).encode(), PL)
    _, odds = results[0]
    assert odds.avg is not None
    assert odds.avg.home == pytest.approx(1.85)


def test_team_names_reconciled_via_alias_table() -> None:
    payload = [
        _event(
            home="Manchester United",
            away="Wolverhampton Wanderers",
            bookmakers=[
                {
                    "key": "bet365",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Manchester United", "price": 1.85},
                                {"name": "Draw", "price": 3.5},
                                {"name": "Wolverhampton Wanderers", "price": 4.0},
                            ],
                        }
                    ],
                }
            ],
        )
    ]
    fixture, _odds = parse_odds_response(json.dumps(payload).encode(), PL)[0]
    assert fixture.home_team == "Man United"
    assert fixture.away_team == "Wolves"


def test_season_inferred_from_commence_time() -> None:
    payload = [
        _event(
            commence="2025-07-02T18:00:00Z",
            bookmakers=[_bookmaker("bet365", 1.85, 3.5, 4.0)],
        )
    ]
    fixture, _odds = parse_odds_response(json.dumps(payload).encode(), PL)[0]
    assert fixture.season == "2526"


def test_odds_url_shape() -> None:
    assert odds_url(PL) == "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"


def test_fetch_odds_calls_the_odds_api(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        content = b"[]"

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, *, params: dict, timeout: float) -> FakeResponse:
        captured["url"] = url
        captured["params"] = params
        return FakeResponse()

    monkeypatch.setattr(odds_api.httpx, "get", fake_get)
    content = odds_api.fetch_odds(PL, "test-key")

    assert content == b"[]"
    assert captured["url"] == odds_url(PL)
    assert captured["params"]["apiKey"] == "test-key"
    assert captured["params"]["markets"] == "h2h"
