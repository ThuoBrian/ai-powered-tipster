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
SPORTS_URL = "https://api.the-odds-api.com/v4/sports"

#: League -> The Odds API sport key (soccer only). Leagues missing here have
#: no live feed; they can still be priced from typed-in odds.
SPORT_KEYS: Mapping[LeagueCode, str] = {
    LeagueCode.PREMIER_LEAGUE: "soccer_epl",
    LeagueCode.LA_LIGA: "soccer_spain_la_liga",
    LeagueCode.BUNDESLIGA: "soccer_germany_bundesliga",
    LeagueCode.SERIE_A: "soccer_italy_serie_a",
    LeagueCode.LIGUE_1: "soccer_france_ligue_one",
    LeagueCode.EREDIVISIE: "soccer_netherlands_eredivisie",
    # Verified against the Odds API sports list, 2026-09-23 (ADR 0011).
    LeagueCode.CHAMPIONSHIP: "soccer_efl_champ",
    LeagueCode.SCOTTISH_PREMIERSHIP: "soccer_spl",
    LeagueCode.PRIMEIRA_LIGA: "soccer_portugal_primeira_liga",
    LeagueCode.BELGIAN_PRO_LEAGUE: "soccer_belgium_first_div",
    LeagueCode.SUPER_LIG: "soccer_turkey_super_league",
    LeagueCode.GREEK_SUPER_LEAGUE: "soccer_greece_super_league",
    LeagueCode.BRAZIL: "soccer_brazil_campeonato",
    LeagueCode.ARGENTINA: "soccer_argentina_primera_division",
    LeagueCode.USA: "soccer_usa_mls",
    LeagueCode.JAPAN: "soccer_japan_j_league",
    LeagueCode.MEXICO: "soccer_mexico_ligamx",
    LeagueCode.NORWAY: "soccer_norway_eliteserien",
    LeagueCode.SWEDEN: "soccer_sweden_allsvenskan",
    LeagueCode.DENMARK: "soccer_denmark_superliga",
    LeagueCode.AUSTRIA: "soccer_austria_bundesliga",
    LeagueCode.SWITZERLAND: "soccer_switzerland_superleague",
    LeagueCode.POLAND: "soccer_poland_ekstraklasa",
    LeagueCode.CHINA: "soccer_china_superleague",
    LeagueCode.FINLAND: "soccer_finland_veikkausliiga",
    LeagueCode.IRELAND: "soccer_league_of_ireland",
    LeagueCode.RUSSIA: "soccer_russia_premier_league",
}

#: National-team tournaments: sport key -> (label, played at neutral venues?).
#: Final tournaments are treated as neutral and qualifiers/Nations League as
#: home games; the API doesn't say who is hosting, so a host nation's
#: tournament games are priced as neutral too (ADR 0011).
INT_TOURNAMENTS: Mapping[str, tuple[str, bool]] = {
    "soccer_fifa_world_cup": ("FIFA World Cup", True),
    "soccer_fifa_world_cup_qualifiers_europe": ("World Cup qualifiers - Europe", False),
    "soccer_fifa_world_cup_qualifiers_south_america": (
        "World Cup qualifiers - South America",
        False,
    ),
    "soccer_uefa_european_championship": ("UEFA Euro", True),
    "soccer_uefa_euro_qualification": ("Euro qualifiers", False),
    "soccer_uefa_nations_league": ("UEFA Nations League", False),
    "soccer_conmebol_copa_america": ("Copa America", True),
    "soccer_africa_cup_of_nations": ("Africa Cup of Nations", True),
    "soccer_concacaf_gold_cup": ("CONCACAF Gold Cup", True),
}

_H2H = "h2h"


def odds_url(league: LeagueCode, sport_key: str | None = None) -> str:
    """The Odds API endpoint for one league's (or one tournament's) live 1X2 odds."""
    key = sport_key or SPORT_KEYS.get(league)
    if key is None:
        hint = " — pick a tournament" if league is LeagueCode.INTERNATIONAL else ""
        msg = f"no live odds feed for {league.label}{hint}"
        raise ValueError(msg)
    return BASE_URL.format(sport_key=key)


def active_sport_keys(api_key: str, *, timeout: float = 30.0) -> set[str]:
    """Sport keys currently in season. Free: this endpoint doesn't use quota."""
    response = httpx.get(SPORTS_URL, params={"apiKey": api_key}, timeout=timeout)
    response.raise_for_status()
    return {sport["key"] for sport in response.json() if sport.get("active")}


def fetch_odds(
    league: LeagueCode,
    api_key: str,
    *,
    sport_key: str | None = None,
    regions: str = "uk,eu",
    timeout: float = 30.0,
) -> bytes:
    """Fetch every upcoming fixture's 1X2 odds, as raw JSON bytes.

    Costs one request per region (``uk,eu`` = 2) against the monthly quota.
    """
    response = httpx.get(
        odds_url(league, sport_key),
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


def parse_odds_response(
    content: bytes, league: LeagueCode, *, neutral: bool = False
) -> list[tuple[Fixture, MatchOdds]]:
    """Parse one Odds API response into ``(Fixture, MatchOdds)`` pairs.

    *neutral* marks every fixture as a neutral-venue game (tournaments).
    """
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
            season=season_from_date(commence.date(), league),
            date=commence.date(),
            home_team=resolve_team_name(league, home_team),
            away_team=resolve_team_name(league, away_team),
            neutral=neutral,
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
