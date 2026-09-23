"""Tests for the football-data.co.uk parser (pure — no network)."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from tipster_core.ingest import football_data
from tipster_core.ingest.football_data import (
    csv_url,
    extra_csv_url,
    parse_extra_csv,
    parse_matches_csv,
)
from tipster_core.leagues import LeagueCode

PL = LeagueCode.PREMIER_LEAGUE


def test_parses_modern_csv(modern_csv: bytes) -> None:
    frame = parse_matches_csv(modern_csv, PL, "2526", source_file="E0_2526.csv")

    assert frame.height == 3
    assert frame.columns[:7] == [
        "league",
        "season",
        "date",
        "home_team",
        "away_team",
        "home_goals",
        "away_goals",
    ]

    arsenal = frame.filter(pl.col("home_team") == "Arsenal").row(0, named=True)
    assert arsenal["league"] == "E0"
    assert arsenal["season"] == "2526"
    assert arsenal["date"] == date(2025, 8, 16)
    assert arsenal["home_goals"] == 3
    assert arsenal["away_goals"] == 0
    assert arsenal["odds_b365_h"] == 1.85
    assert arsenal["odds_pinnacle_c_h"] == 1.9
    assert arsenal["source_file"] == "E0_2526.csv"


def test_short_date_format_fallback(modern_csv: bytes) -> None:
    frame = parse_matches_csv(modern_csv, PL, "2526")
    chelsea = frame.filter(pl.col("home_team") == "Chelsea").row(0, named=True)
    assert chelsea["date"] == date(2025, 8, 17)


def test_zero_and_missing_odds_become_null(modern_csv: bytes) -> None:
    frame = parse_matches_csv(modern_csv, PL, "2526")
    city = frame.filter(pl.col("home_team") == "Man City").row(0, named=True)
    assert city["odds_b365_h"] is None  # 0 is the source's "missing" marker
    assert city["odds_pinnacle_h"] == 1.5
    assert city["odds_b365_c_h"] is None  # blank closing odds
    assert city["odds_max_c_a"] is None


def test_junk_rows_are_dropped(modern_csv: bytes) -> None:
    frame = parse_matches_csv(modern_csv, PL, "2526")
    teams = set(frame.get_column("home_team").to_list())
    assert teams == {"Arsenal", "Chelsea", "Man City"}


def test_legacy_csv_without_odds_columns(legacy_csv: bytes) -> None:
    frame = parse_matches_csv(legacy_csv, PL, "0809")
    assert frame.height == 2
    assert frame.get_column("odds_b365_h").null_count() == 2
    # Whitespace is stripped from team names.
    assert frame.get_column("home_team").to_list() == ["Arsenal", "Chelsea"]
    # %y fallback parses the two-digit year into the correct century.
    chelsea = frame.filter(pl.col("home_team") == "Chelsea").row(0, named=True)
    assert chelsea["date"] == date(2008, 8, 16)


def test_empty_csv_raises() -> None:
    csv = b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n,,,,,,\n"
    with pytest.raises(ValueError, match="no valid match rows"):
        parse_matches_csv(csv, PL, "2526")


def test_wrong_shape_raises() -> None:
    with pytest.raises(ValueError, match="missing core columns"):
        parse_matches_csv(b"Foo,Bar\n1,2\n", PL, "2526")


def test_invalid_season_rejected_before_parse(modern_csv: bytes) -> None:
    with pytest.raises(ValueError, match="invalid season"):
        parse_matches_csv(modern_csv, PL, "2527")


def test_csv_url_shape() -> None:
    assert csv_url(PL, "2526") == "https://www.football-data.co.uk/mmz4281/2526/E0.csv"
    with pytest.raises(ValueError, match="invalid season"):
        csv_url(PL, "banana")


_EXTRA_HEADER = (
    "Country,League,Season,Date,Time,Home,Away,HG,AG,Res,PSCH,PSCD,PSCA,MaxCH,MaxCD,MaxCA,"
    "AvgCH,AvgCD,AvgCA,BFECH,BFECD,BFECA,B365CH,B365CD,B365CA\n"
)


def test_parses_extra_league_csv_with_bom_and_stray_spaces() -> None:
    csv = (
        "\ufeff"
        + _EXTRA_HEADER
        + "Brazil,Serie A ,2022,10/04/2022,21:00,Old Club,Other,1,0,H,2.0,3.3,3.8,"
        "2.1,3.4,4.0,2.0,3.3,3.8,,,,2.0,3.3,3.8\n"
        + "Brazil,Serie A ,2026,20/09/2026,22:30, Flamengo RJ ,Bragantino,2,1,H,,,,"
        "1.33,5.5,9.5,1.3,5.2,9.0,,,,1.3,5.0,9.0\n"
    ).encode()
    frame = parse_extra_csv(csv, LeagueCode.BRAZIL)
    # 2022 is before the default 2023-01-01 window.
    assert frame.height == 1
    row = frame.row(0, named=True)
    assert row["league"] == "BRA"
    assert row["season"] == "2026"
    assert row["home_team"] == "Flamengo RJ"
    assert row["date"] == date(2026, 9, 20)
    assert row["neutral"] is False
    # Closing odds map straight across; empty Pinnacle and opening odds are null.
    assert row["odds_pinnacle_c_h"] is None
    assert row["odds_max_c_h"] == 1.33
    assert row["odds_b365_c_a"] == 9.0
    assert row["odds_b365_h"] is None


def test_extra_league_split_season_format() -> None:
    csv = (
        _EXTRA_HEADER
        + "Mexico,Liga MX,2025/2026,15/01/2026,02:00,America,Tigres,1,1,D,,,,,,,,,,,,,,,\n"
    ).encode()
    frame = parse_extra_csv(csv, LeagueCode.MEXICO)
    assert frame.get_column("season").to_list() == ["2025/2026"]


def test_extra_csv_url_rejects_main_divisions() -> None:
    assert extra_csv_url(LeagueCode.BRAZIL) == "https://www.football-data.co.uk/new/BRA.csv"
    with pytest.raises(ValueError, match=r"not a football-data.co.uk extra league"):
        extra_csv_url(PL)


def test_download_rejects_html_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        content = b"<html><body>error page</body></html>"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(football_data.httpx, "get", lambda *a, **k: FakeResponse())
    with pytest.raises(ValueError, match="did not return"):
        football_data.download_csv("https://example.com/E0.csv")
