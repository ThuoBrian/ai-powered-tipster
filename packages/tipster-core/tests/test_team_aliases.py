"""Tests for the (unverified, seeded) team-name alias table (ADR 0008)."""

from __future__ import annotations

from tipster_core.leagues import LeagueCode
from tipster_core.team_aliases import resolve_team_name

PL = LeagueCode.PREMIER_LEAGUE


def test_resolves_known_alias() -> None:
    assert resolve_team_name(PL, "Manchester United") == "Man United"
    assert resolve_team_name(PL, "Nottingham Forest") == "Nott'm Forest"


def test_accented_live_api_names_resolve() -> None:
    # Real Odds API spellings (accents, club prefixes) seen in a live response.
    assert resolve_team_name(LeagueCode.LA_LIGA, "Málaga") == "Malaga"
    assert resolve_team_name(LeagueCode.LA_LIGA, "Deportivo La Coruña") == "La Coruna"


def test_unmapped_name_passes_through_unchanged() -> None:
    assert resolve_team_name(PL, "Arsenal") == "Arsenal"
    assert resolve_team_name(PL, "Some Future Club FC") == "Some Future Club FC"


def test_aliases_are_scoped_per_league() -> None:
    # "Bayern Munich" only means something in the Bundesliga alias table.
    assert resolve_team_name(LeagueCode.BUNDESLIGA, "FC Bayern München") == "Bayern Munich"
    assert resolve_team_name(PL, "FC Bayern München") == "FC Bayern München"
