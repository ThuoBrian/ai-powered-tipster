"""Team-name reconciliation: The Odds API names -> football-data.co.uk names (ADR 0008).

The Odds API and football-data.co.uk name the same club differently often
enough (full legal name vs. the short form football-data.co.uk has always
used) that a live fixture won't join to its own history without this map —
the feature builder looks up rolling form and Elo by exact team name.

**This table is seeded from general football-naming knowledge, not verified
against a live API response** — this repo has not made a real call to The
Odds API. Treat every entry as a best guess to be corrected against actual
responses once live data is flowing (ADR 0008); a wrong entry here silently
mispoints a team's history rather than raising, so it is worth checking.
"""

from __future__ import annotations

from tipster_core.leagues import LeagueCode

#: (league, The Odds API name) -> football-data.co.uk name. Teams whose name
#: already matches verbatim (e.g. "Arsenal", "Liverpool") need no entry.
_ALIASES: dict[tuple[LeagueCode, str], str] = {
    # Premier League
    (LeagueCode.PREMIER_LEAGUE, "Manchester United"): "Man United",
    (LeagueCode.PREMIER_LEAGUE, "Manchester City"): "Man City",
    (LeagueCode.PREMIER_LEAGUE, "Newcastle United"): "Newcastle",
    (LeagueCode.PREMIER_LEAGUE, "Nottingham Forest"): "Nott'm Forest",
    (LeagueCode.PREMIER_LEAGUE, "Wolverhampton Wanderers"): "Wolves",
    (LeagueCode.PREMIER_LEAGUE, "Tottenham Hotspur"): "Tottenham",
    (LeagueCode.PREMIER_LEAGUE, "West Bromwich Albion"): "West Brom",
    (LeagueCode.PREMIER_LEAGUE, "Leicester City"): "Leicester",
    (LeagueCode.PREMIER_LEAGUE, "Brighton and Hove Albion"): "Brighton",
    (LeagueCode.PREMIER_LEAGUE, "West Ham United"): "West Ham",
    (LeagueCode.PREMIER_LEAGUE, "Leeds United"): "Leeds",
    (LeagueCode.PREMIER_LEAGUE, "Norwich City"): "Norwich",
    (LeagueCode.PREMIER_LEAGUE, "AFC Bournemouth"): "Bournemouth",
    (LeagueCode.PREMIER_LEAGUE, "Ipswich Town"): "Ipswich",
    (LeagueCode.PREMIER_LEAGUE, "Coventry City"): "Coventry",  # verified 2026-09-23
    (LeagueCode.PREMIER_LEAGUE, "Hull City"): "Hull",  # verified 2026-09-23
    # La Liga
    (LeagueCode.LA_LIGA, "Real Sociedad"): "Sociedad",
    (LeagueCode.LA_LIGA, "Athletic Bilbao"): "Ath Bilbao",
    (LeagueCode.LA_LIGA, "Athletic Club"): "Ath Bilbao",
    (LeagueCode.LA_LIGA, "Atletico Madrid"): "Ath Madrid",
    (LeagueCode.LA_LIGA, "Atlético Madrid"): "Ath Madrid",
    (LeagueCode.LA_LIGA, "Real Betis"): "Betis",
    (LeagueCode.LA_LIGA, "Espanyol"): "Espanol",
    (LeagueCode.LA_LIGA, "RCD Espanyol"): "Espanol",
    (LeagueCode.LA_LIGA, "Rayo Vallecano"): "Vallecano",
    (LeagueCode.LA_LIGA, "Celta Vigo"): "Celta",
    (LeagueCode.LA_LIGA, "Deportivo Alaves"): "Alaves",
    (LeagueCode.LA_LIGA, "Deportivo Alavés"): "Alaves",
    # Verified against a live Odds API response, 2026-09-23:
    (LeagueCode.LA_LIGA, "Alavés"): "Alaves",
    (LeagueCode.LA_LIGA, "CA Osasuna"): "Osasuna",
    (LeagueCode.LA_LIGA, "Deportivo La Coruña"): "La Coruna",
    (LeagueCode.LA_LIGA, "Elche CF"): "Elche",
    (LeagueCode.LA_LIGA, "Málaga"): "Malaga",
    (LeagueCode.LA_LIGA, "Real Racing Club de Santander"): "Santander",
    # Bundesliga
    (LeagueCode.BUNDESLIGA, "FC Bayern München"): "Bayern Munich",
    (LeagueCode.BUNDESLIGA, "Borussia Dortmund"): "Dortmund",
    (LeagueCode.BUNDESLIGA, "Borussia Monchengladbach"): "M'gladbach",
    (LeagueCode.BUNDESLIGA, "Borussia Mönchengladbach"): "M'gladbach",
    (LeagueCode.BUNDESLIGA, "1. FC Koln"): "FC Koln",
    (LeagueCode.BUNDESLIGA, "1. FC Köln"): "FC Koln",
    (LeagueCode.BUNDESLIGA, "Eintracht Frankfurt"): "Ein Frankfurt",
    (LeagueCode.BUNDESLIGA, "Hertha Berlin"): "Hertha",
    (LeagueCode.BUNDESLIGA, "Hertha BSC"): "Hertha",
    (LeagueCode.BUNDESLIGA, "Bayer Leverkusen"): "Leverkusen",
    (LeagueCode.BUNDESLIGA, "TSG Hoffenheim"): "Hoffenheim",
    (LeagueCode.BUNDESLIGA, "Mainz 05"): "Mainz",
    (LeagueCode.BUNDESLIGA, "FSV Mainz 05"): "Mainz",
    (LeagueCode.BUNDESLIGA, "1. FC Union Berlin"): "Union Berlin",
    (LeagueCode.BUNDESLIGA, "FC St. Pauli"): "St Pauli",
    (LeagueCode.BUNDESLIGA, "1. FC Heidenheim"): "Heidenheim",
    # Serie A
    (LeagueCode.SERIE_A, "AC Milan"): "Milan",
    (LeagueCode.SERIE_A, "Inter Milan"): "Inter",
    (LeagueCode.SERIE_A, "FC Internazionale Milano"): "Inter",
    (LeagueCode.SERIE_A, "AS Roma"): "Roma",
    (LeagueCode.SERIE_A, "SS Lazio"): "Lazio",
    (LeagueCode.SERIE_A, "Hellas Verona"): "Verona",
    (LeagueCode.SERIE_A, "FC Torino"): "Torino",
    # Ligue 1
    (LeagueCode.LIGUE_1, "Paris Saint-Germain"): "Paris SG",
    (LeagueCode.LIGUE_1, "Paris Saint Germain"): "Paris SG",
    (LeagueCode.LIGUE_1, "Olympique Marseille"): "Marseille",
    (LeagueCode.LIGUE_1, "Olympique de Marseille"): "Marseille",
    (LeagueCode.LIGUE_1, "Olympique Lyonnais"): "Lyon",
    (LeagueCode.LIGUE_1, "AS Monaco"): "Monaco",
    (LeagueCode.LIGUE_1, "OGC Nice"): "Nice",
    (LeagueCode.LIGUE_1, "LOSC Lille"): "Lille",
    (LeagueCode.LIGUE_1, "Stade Rennais"): "Rennes",
    (LeagueCode.LIGUE_1, "AS Saint-Etienne"): "St Etienne",
    (LeagueCode.LIGUE_1, "AS Saint-Étienne"): "St Etienne",
}


def resolve_team_name(league: LeagueCode, odds_api_name: str) -> str:
    """The football-data.co.uk name for a team, given its Odds API name.

    Falls back to the input unchanged when no alias is registered — either
    the name already matches (most teams), or this table is missing an
    entry, which is indistinguishable from here (ADR 0008).
    """
    return _ALIASES.get((league, odds_api_name), odds_api_name)
