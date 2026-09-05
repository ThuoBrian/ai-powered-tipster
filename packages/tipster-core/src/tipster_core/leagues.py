"""League and season identifiers used across the tipster domain.

League codes follow football-data.co.uk's division naming because that is
the primary historical source (ADR 0002).
"""

from __future__ import annotations

from enum import StrEnum


class LeagueCode(StrEnum):
    """football-data.co.uk division codes for the leagues we cover."""

    PREMIER_LEAGUE = "E0"
    LA_LIGA = "SP1"
    BUNDESLIGA = "D1"
    SERIE_A = "I1"
    LIGUE_1 = "F1"
    EREDIVISIE = "N1"

    @property
    def label(self) -> str:
        """Human-readable league name."""
        return _LABELS[self]

    @classmethod
    def from_code(cls, code: str) -> LeagueCode:
        """Look up a league by its football-data.co.uk code (e.g. ``"E0"``)."""
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
}

#: The leagues ingested by default (ADR 0002): the big five European leagues.
BIG_5: tuple[LeagueCode, ...] = (
    LeagueCode.PREMIER_LEAGUE,
    LeagueCode.LA_LIGA,
    LeagueCode.BUNDESLIGA,
    LeagueCode.SERIE_A,
    LeagueCode.LIGUE_1,
)


def season_code(start_year: int) -> str:
    """Return the football-data.co.uk season code for a start year.

    >>> season_code(2025)
    '2526'
    """
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def season_label(code: str) -> str:
    """Return the human-readable label for a season code (``"2526"`` → ``"2025/26"``)."""
    validate_season(code)
    return f"20{code[:2]}/{code[2:]}"


def validate_season(code: str) -> None:
    """Raise ``ValueError`` unless *code* is a valid 4-digit season code."""
    if len(code) != 4 or not code.isdigit() or int(code[2:]) != (int(code[:2]) + 1) % 100:
        msg = f"invalid season code {code!r}; expected the form '2526' (2025/26)"
        raise ValueError(msg)
