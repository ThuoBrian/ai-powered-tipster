"""Tests for league and season identifiers."""

from __future__ import annotations

from datetime import date

import pytest

from tipster_core.leagues import (
    BIG_5,
    LeagueCode,
    season_code,
    season_from_date,
    season_label,
    validate_season,
)


def test_season_code_matches_source_format() -> None:
    assert season_code(2025) == "2526"
    assert season_code(2024) == "2425"
    assert season_code(1999) == "9900"


def test_season_label_roundtrip() -> None:
    assert season_label("2526") == "2025/26"
    assert season_label(season_code(2024)) == "2024/25"


@pytest.mark.parametrize("bad", ["", "2527", "252", "abcd", "2528", "3000", "2025/2027", "25/26"])
def test_invalid_season_codes_raise(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid season"):
        validate_season(bad)


@pytest.mark.parametrize("good", ["2526", "2026", "2025/2026"])
def test_all_three_season_shapes_are_valid(good: str) -> None:
    validate_season(good)


def test_season_label_per_shape() -> None:
    assert season_label("2025/2026") == "2025/26"
    assert season_label("2026") == "2026"
    # "2021" fits both 4-digit shapes: the league decides.
    assert season_label("2021") == "2020/21"
    assert season_label("2021", LeagueCode.BRAZIL) == "2021"


def test_season_from_date_uses_the_league_style() -> None:
    assert season_from_date(date(2026, 7, 1), LeagueCode.BRAZIL) == "2026"
    assert season_from_date(date(2026, 7, 1), LeagueCode.INTERNATIONAL) == "2026"
    assert season_from_date(date(2026, 1, 15), LeagueCode.MEXICO) == "2025/2026"
    assert season_from_date(date(2026, 1, 15), LeagueCode.CHAMPIONSHIP) == "2526"


def test_every_league_has_a_label() -> None:
    for league in LeagueCode:
        assert league.label


def test_existing_league_order_is_stable() -> None:
    # features.league_code is the enum position: new members must be appended.
    assert [league.value for league in LeagueCode][:6] == ["E0", "SP1", "D1", "I1", "F1", "N1"]


def test_league_lookup_is_case_insensitive() -> None:
    assert LeagueCode.from_code("e0") is LeagueCode.PREMIER_LEAGUE
    assert LeagueCode.from_code(" sp1 ").label == "La Liga"


def test_unknown_league_codes_raise() -> None:
    with pytest.raises(ValueError, match="unknown league"):
        LeagueCode.from_code("XX")


def test_big_5_contents() -> None:
    assert len(BIG_5) == 5
    assert LeagueCode.PREMIER_LEAGUE in BIG_5
    assert LeagueCode.EREDIVISIE not in BIG_5


def test_season_from_date_mid_season() -> None:
    assert season_from_date(date(2026, 1, 15)) == "2526"


def test_season_from_date_july_cutoff() -> None:
    assert season_from_date(date(2025, 7, 1)) == "2526"
    assert season_from_date(date(2025, 6, 30)) == "2425"
