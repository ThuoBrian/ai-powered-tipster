"""Competition and season identifiers used across the tipster domain (ADR 0011).

Codes follow the source file names: football-data.co.uk division codes
(``E0``), its "extra leagues" country codes (``BRA``), and ``INT`` for
national-team matches. Members are only ever *appended*: the feature
builder's ``league_code`` is the enum position, so reordering would
silently change every existing league's feature value.

Seasons keep each source's native format, which never collide because the
shapes differ: ``2526`` (football-data.co.uk main files), ``2026``
(calendar-year leagues and internationals), ``2025/2026`` (split-season
extra leagues).
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum


class LeagueCode(StrEnum):
    """Codes for every competition we cover."""

    PREMIER_LEAGUE = "E0"
    LA_LIGA = "SP1"
    BUNDESLIGA = "D1"
    SERIE_A = "I1"
    LIGUE_1 = "F1"
    EREDIVISIE = "N1"
    CHAMPIONSHIP = "E1"
    LEAGUE_ONE = "E2"
    LEAGUE_TWO = "E3"
    NATIONAL_LEAGUE = "EC"
    SCOTTISH_PREMIERSHIP = "SC0"
    SCOTTISH_CHAMPIONSHIP = "SC1"
    SCOTTISH_LEAGUE_ONE = "SC2"
    SCOTTISH_LEAGUE_TWO = "SC3"
    BUNDESLIGA_2 = "D2"
    SERIE_B = "I2"
    LA_LIGA_2 = "SP2"
    LIGUE_2 = "F2"
    BELGIAN_PRO_LEAGUE = "B1"
    PRIMEIRA_LIGA = "P1"
    SUPER_LIG = "T1"
    GREEK_SUPER_LEAGUE = "G1"
    ARGENTINA = "ARG"
    AUSTRIA = "AUT"
    BRAZIL = "BRA"
    CHINA = "CHN"
    DENMARK = "DNK"
    FINLAND = "FIN"
    IRELAND = "IRL"
    JAPAN = "JPN"
    MEXICO = "MEX"
    NORWAY = "NOR"
    POLAND = "POL"
    ROMANIA = "ROU"
    RUSSIA = "RUS"
    SWEDEN = "SWE"
    SWITZERLAND = "SWZ"
    USA = "USA"
    INTERNATIONAL = "INT"

    @property
    def label(self) -> str:
        """Human-readable competition name."""
        return _LABELS[self]

    @classmethod
    def from_code(cls, code: str) -> LeagueCode:
        """Look up a competition by its code (e.g. ``"E0"``, ``"BRA"``, ``"INT"``)."""
        try:
            return cls(code.strip().upper())
        except ValueError:
            valid = ", ".join(member.value for member in cls)
            msg = f"unknown league code {code!r}; valid codes: {valid}"
            raise ValueError(msg) from None


_LABELS: dict[LeagueCode, str] = {
    LeagueCode.PREMIER_LEAGUE: "Premier League",
    LeagueCode.LA_LIGA: "La Liga",
    LeagueCode.BUNDESLIGA: "Bundesliga",
    LeagueCode.SERIE_A: "Serie A",
    LeagueCode.LIGUE_1: "Ligue 1",
    LeagueCode.EREDIVISIE: "Eredivisie",
    LeagueCode.CHAMPIONSHIP: "Championship",
    LeagueCode.LEAGUE_ONE: "League One",
    LeagueCode.LEAGUE_TWO: "League Two",
    LeagueCode.NATIONAL_LEAGUE: "National League",
    LeagueCode.SCOTTISH_PREMIERSHIP: "Scottish Premiership",
    LeagueCode.SCOTTISH_CHAMPIONSHIP: "Scottish Championship",
    LeagueCode.SCOTTISH_LEAGUE_ONE: "Scottish League One",
    LeagueCode.SCOTTISH_LEAGUE_TWO: "Scottish League Two",
    LeagueCode.BUNDESLIGA_2: "2. Bundesliga",
    LeagueCode.SERIE_B: "Serie B",
    LeagueCode.LA_LIGA_2: "La Liga 2",
    LeagueCode.LIGUE_2: "Ligue 2",
    LeagueCode.BELGIAN_PRO_LEAGUE: "Belgian Pro League",
    LeagueCode.PRIMEIRA_LIGA: "Primeira Liga",
    LeagueCode.SUPER_LIG: "Super Lig",
    LeagueCode.GREEK_SUPER_LEAGUE: "Greek Super League",
    LeagueCode.ARGENTINA: "Argentina Liga Profesional",
    LeagueCode.AUSTRIA: "Austrian Bundesliga",
    LeagueCode.BRAZIL: "Brasileirao Serie A",
    LeagueCode.CHINA: "Chinese Super League",
    LeagueCode.DENMARK: "Danish Superliga",
    LeagueCode.FINLAND: "Veikkausliiga (Finland)",
    LeagueCode.IRELAND: "League of Ireland Premier Division",
    LeagueCode.JAPAN: "J1 League (Japan)",
    LeagueCode.MEXICO: "Liga MX",
    LeagueCode.NORWAY: "Eliteserien (Norway)",
    LeagueCode.POLAND: "Ekstraklasa (Poland)",
    LeagueCode.ROMANIA: "Romanian Superliga",
    LeagueCode.RUSSIA: "Russian Premier League",
    LeagueCode.SWEDEN: "Allsvenskan (Sweden)",
    LeagueCode.SWITZERLAND: "Swiss Super League",
    LeagueCode.USA: "MLS (USA)",
    LeagueCode.INTERNATIONAL: "International (national teams)",
}

#: The leagues backtested by default (ADR 0002): the big five European leagues.
BIG_5: tuple[LeagueCode, ...] = (
    LeagueCode.PREMIER_LEAGUE,
    LeagueCode.LA_LIGA,
    LeagueCode.BUNDESLIGA,
    LeagueCode.SERIE_A,
    LeagueCode.LIGUE_1,
)

#: football-data.co.uk "extra leagues": one CSV per country, every season.
EXTRA_LEAGUES: frozenset[LeagueCode] = frozenset(
    {
        LeagueCode.ARGENTINA,
        LeagueCode.AUSTRIA,
        LeagueCode.BRAZIL,
        LeagueCode.CHINA,
        LeagueCode.DENMARK,
        LeagueCode.FINLAND,
        LeagueCode.IRELAND,
        LeagueCode.JAPAN,
        LeagueCode.MEXICO,
        LeagueCode.NORWAY,
        LeagueCode.POLAND,
        LeagueCode.ROMANIA,
        LeagueCode.RUSSIA,
        LeagueCode.SWEDEN,
        LeagueCode.SWITZERLAND,
        LeagueCode.USA,
    }
)

#: Competitions whose season is a calendar year (``2026``).
CALENDAR_SEASON_LEAGUES: frozenset[LeagueCode] = frozenset(
    {
        LeagueCode.BRAZIL,
        LeagueCode.CHINA,
        LeagueCode.FINLAND,
        LeagueCode.IRELAND,
        LeagueCode.JAPAN,
        LeagueCode.NORWAY,
        LeagueCode.SWEDEN,
        LeagueCode.USA,
        LeagueCode.INTERNATIONAL,
    }
)

_LONG_SEASON = re.compile(r"^(\d{4})/(\d{4})$")


def season_code(start_year: int) -> str:
    """Return the football-data.co.uk season code for a start year.

    >>> season_code(2025)
    '2526'
    """
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def season_from_date(day: date, league: LeagueCode | None = None) -> str:
    """The season a date falls in, in *league*'s native season format.

    Split seasons run roughly August-May; July is the cutoff (pre-season
    fixtures can appear that early). Calendar-year competitions use the
    year. Only used to label new fixtures — models and settlement don't
    depend on it.

    >>> season_from_date(date(2026, 1, 15))
    '2526'
    >>> season_from_date(date(2025, 7, 1))
    '2526'
    >>> season_from_date(date(2026, 7, 1), LeagueCode.BRAZIL)
    '2026'
    >>> season_from_date(date(2026, 1, 15), LeagueCode.MEXICO)
    '2025/2026'
    """
    if league in CALENDAR_SEASON_LEAGUES:
        return str(day.year)
    start_year = day.year if day.month >= 7 else day.year - 1
    if league in EXTRA_LEAGUES:
        return f"{start_year}/{start_year + 1}"
    return season_code(start_year)


def _is_short_split(code: str) -> bool:
    return len(code) == 4 and code.isdigit() and int(code[2:]) == (int(code[:2]) + 1) % 100


def _is_year(code: str) -> bool:
    return len(code) == 4 and code.isdigit() and 1870 <= int(code) <= 2100


def season_label(code: str, league: LeagueCode | None = None) -> str:
    """Human-readable season: ``"2526"`` → ``"2025/26"``, ``"2026"`` → ``"2026"``.

    A code like ``"2021"`` fits both 4-digit shapes; *league* settles it
    (calendar-year competitions read it as a year).
    """
    validate_season(code)
    long_match = _LONG_SEASON.match(code)
    if long_match:
        return f"{long_match.group(1)}/{long_match.group(2)[2:]}"
    if league in CALENDAR_SEASON_LEAGUES or not _is_short_split(code):
        return code
    return f"20{code[:2]}/{code[2:]}"


def validate_season(code: str) -> None:
    """Raise ``ValueError`` unless *code* is a season in one of the three shapes."""
    long_match = _LONG_SEASON.match(code)
    if long_match and int(long_match.group(2)) == int(long_match.group(1)) + 1:
        return
    if _is_short_split(code) or _is_year(code):
        return
    msg = (
        f"invalid season code {code!r}; expected '2526' (2025/26), "
        "'2026' (a calendar year) or '2025/2026'"
    )
    raise ValueError(msg)
