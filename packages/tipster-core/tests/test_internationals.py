"""Tests for the national-team results parser (pure — no network)."""

from __future__ import annotations

from datetime import date

import pytest

from tipster_core.ingest.internationals import parse_internationals_csv
from tipster_core.leagues import LeagueCode
from tipster_core.storage import connect, load_match_results, replace_season

_CSV = (
    b"date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
    b"2013-06-01,Kenya,Uganda,1,0,Friendly,Nairobi,Kenya,FALSE\n"
    b'2024-01-20,Egypt,Ghana,2,2,African Cup of Nations,"Abidjan, Ebimpe",Ivory Coast,TRUE\n'
    b"2025-09-05,Kenya,Gambia,3,1,FIFA World Cup qualification,Nairobi,Kenya,FALSE\n"
    b"2027-06-19,Kenya,Tanzania,NA,NA,African Cup of Nations,Nairobi,Kenya,FALSE\n"
)


def test_parses_results_with_quoted_commas_and_neutral_flag() -> None:
    frame = parse_internationals_csv(_CSV)
    # 2013 is before the window; the 2027 fixture has no score yet.
    assert frame.height == 2
    egypt = frame.row(0, named=True)
    assert egypt["league"] == "INT"
    assert egypt["season"] == "2024"
    assert egypt["date"] == date(2024, 1, 20)
    assert egypt["neutral"] is True
    assert egypt["odds_pinnacle_c_h"] is None
    kenya = frame.row(1, named=True)
    assert (kenya["home_team"], kenya["neutral"], kenya["season"]) == ("Kenya", False, "2025")


def test_round_trips_through_storage_with_neutral() -> None:
    con = connect(":memory:")
    try:
        frame = parse_internationals_csv(_CSV)
        for season in ("2024", "2025"):
            replace_season(con, frame.filter(frame["season"] == season))
        results = load_match_results(con, leagues=[LeagueCode.INTERNATIONAL])
    finally:
        con.close()
    assert [r.neutral for r in results] == [True, False]
    assert results[0].to_fixture().neutral is True


def test_empty_after_filtering_raises() -> None:
    with pytest.raises(ValueError, match="no valid international results"):
        parse_internationals_csv(_CSV, since=date(2030, 1, 1))
