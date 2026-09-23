"""The Odds API live-odds fetching and parsing (ADR 0002, ADR 0007).

Source format notes:

- One request per league fetches every upcoming fixture's h2h (1X2) market in
  a single call — the free tier is 500 requests/month (ADR 0002), so this
  is explicitly not a polling loop; callers decide when to spend a request.
- Bookmaker coverage varies by fixture. ``avg``/``max`` are computed across
  whatever bookmakers responded with a complete 3-way price; ``b365``/
  ``pinnacle`` are read from those specific bookmakers when present. A
  fixture with no complete bookmaker price is dropped — there is nothing to
  devig without at least one full price (ADR 0007).
- Team names are reconciled against football-data.co.uk's naming via
  ``tipster_core.team_aliases`` (ADR 0008) before a ``Fixture`` is built —
  the alias table is best-effort and unverified against a live response, so
  an unmapped name simply passes through unchanged rather than raising.

The parser is pure: bytes in, ``(Fixture, MatchOdds)`` pairs out.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC
from datetime import datetime as dt
from typing import Any

import httpx

from tipster_core.contracts import Fixture, MatchOdds, OutcomeOdds
from tipster_core.leagues import LeagueCode, season_from_date
from tipster_core.team_aliases import resolve_team_name

BASE_URL = "https://api.the-odds-api.com/v4/sports/{sport_key}/odds"

#: football-data.co.uk league -> The Odds API sport key (soccer only).
SPORT_KEYS: Mapping[LeagueCode, str] = {
    LeagueCode.PREMIER_LEAGUE: "soccer_epl",
    LeagueCode.LA_LIGA: "soccer_spain_la_liga",
    LeagueCode.BUNDESLIGA: "soccer_germany_bundesliga",
    LeagueCode.SERIE_A: "soccer_italy_serie_a",
    LeagueCode.LIGUE_1: "soccer_france_ligue_one",
    LeagueCode.EREDIVISIE: "soccer_netherlands_eredivisie",
}

_H2H = "h2h"


def odds_url(league: LeagueCode) -> str:
    """The Odds API endpoint for one league's live 1X2 odds."""
    return BASE_URL.format(sport_key=SPORT_KEYS[league])


def fetch_odds(
    league: LeagueCode, api_key: str, *, regions: str = "uk,eu", timeout: float = 30.0
) -> bytes:
    """Fetch every upcoming fixture's 1X2 odds for one league, as raw JSON bytes."""
    response = httpx.get(
        odds_url(league),
        params={
            "apiKey": api_key,
            "regions": regions,
            "markets": _H2H,
            "oddsFormat": "decimal",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.content


def parse_odds_response(content: bytes, league: LeagueCode) -> list[tuple[Fixture, MatchOdds]]:
    """Parse one league's The Odds API response into ``(Fixture, MatchOdds)`` pairs."""
    events = json.loads(content)
    results: list[tuple[Fixture, MatchOdds]] = []
    for event in events:
        home_team = event["home_team"]
        away_team = event["away_team"]
        prices = _prices_by_bookmaker(event, home_team, away_team)
        if not prices:
            continue

        commence = dt.fromisoformat(event["commence_time"]).astimezone(UTC)
        fixture = Fixture(
            league=league,
            season=season_from_date(commence.date()),
            date=commence.date(),
            home_team=resolve_team_name(league, home_team),
            away_team=resolve_team_name(league, away_team),
        )
        odds = MatchOdds(
            b365=prices.get("bet365"),
            pinnacle=prices.get("pinnacle"),
            avg=_average(list(prices.values())),
            max=_maximum(list(prices.values())),
        )
        results.append((fixture, odds))
    return results


def _prices_by_bookmaker(
    event: dict[str, Any], home_team: str, away_team: str
) -> dict[str, OutcomeOdds]:
    """Complete 3-way h2h prices, keyed by the API's bookmaker key.

    A bookmaker missing the draw price, or quoting a price of 1.0 or below
    (a data glitch — decimal odds are never that low), is skipped entirely
    rather than partially trusted.
    """
    prices: dict[str, OutcomeOdds] = {}
    for bookmaker in event.get("bookmakers", []):
        market = next(
            (m for m in bookmaker.get("markets", []) if m.get("key") == _H2H),
            None,
        )
        if market is None:
            continue
        by_name = {outcome["name"]: outcome["price"] for outcome in market.get("outcomes", [])}
        if home_team not in by_name or away_team not in by_name or "Draw" not in by_name:
            continue
        home_p, draw_p, away_p = by_name[home_team], by_name["Draw"], by_name[away_team]
        if home_p <= 1.0 or draw_p <= 1.0 or away_p <= 1.0:
            continue
        prices[bookmaker["key"]] = OutcomeOdds(home=home_p, draw=draw_p, away=away_p)
    return prices


def _average(prices: Sequence[OutcomeOdds]) -> OutcomeOdds:
    n = len(prices)
    return OutcomeOdds(
        home=sum(p.home for p in prices) / n,
        draw=sum(p.draw for p in prices) / n,
        away=sum(p.away for p in prices) / n,
    )


def _maximum(prices: Sequence[OutcomeOdds]) -> OutcomeOdds:
    return OutcomeOdds(
        home=max(p.home for p in prices),
        draw=max(p.draw for p in prices),
        away=max(p.away for p in prices),
    )
