"""Parse pasted fixture lists for the Predict Fixtures page.

One fixture per line, ``Home v Away``, optionally marked ``(n)`` for a
neutral venue, optionally followed by the bookmaker's decimal 1X2 odds::

    Arsenal v Chelsea
    Man City vs Liverpool, 1.85, 3.90, 4.20
    Morocco v Egypt (n), 2.10, 3.20, 3.90

Blank lines and lines starting with ``#`` are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tipster_core.contracts import OutcomeOdds

_SEPARATOR = re.compile(r"\s+vs?\.?\s+", flags=re.IGNORECASE)
_NEUTRAL_MARK = re.compile(r"\s*\((?:n|neutral)\)\s*$", flags=re.IGNORECASE)


@dataclass(frozen=True)
class FixtureLine:
    home: str
    away: str
    odds: OutcomeOdds | None
    #: True when the line is marked ``(n)``; None means "use the page default".
    neutral: bool | None = None


def parse_fixture_lines(text: str) -> tuple[list[FixtureLine], list[str]]:
    """Parsed fixtures, plus one error message per line that couldn't be read."""
    fixtures: list[FixtureLine] = []
    errors: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fixture_part, *odds_parts = (part.strip() for part in line.split(","))
        neutral: bool | None = None
        if _NEUTRAL_MARK.search(fixture_part):
            neutral = True
            fixture_part = _NEUTRAL_MARK.sub("", fixture_part)
        teams = _SEPARATOR.split(fixture_part)
        if len(teams) != 2 or not all(teams):
            errors.append(f"Line {number}: expected 'Home v Away', got {fixture_part!r}")
            continue
        odds: OutcomeOdds | None = None
        if odds_parts:
            try:
                home_odds, draw_odds, away_odds = (float(part) for part in odds_parts)
            except ValueError:
                errors.append(
                    f"Line {number}: odds must be three decimal numbers "
                    f"(home, draw, away), got {', '.join(odds_parts)!r}"
                )
                continue
            if min(home_odds, draw_odds, away_odds) <= 1.0:
                errors.append(f"Line {number}: decimal odds must all be above 1.0")
                continue
            odds = OutcomeOdds(home=home_odds, draw=draw_odds, away=away_odds)
        fixtures.append(FixtureLine(home=teams[0], away=teams[1], odds=odds, neutral=neutral))
    return fixtures, errors
