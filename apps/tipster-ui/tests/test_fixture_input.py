"""Tests for the pasted-fixture-list parser."""

from __future__ import annotations

from tipster_ui.fixture_input import parse_fixture_lines


def test_parses_fixtures_with_and_without_odds() -> None:
    fixtures, errors = parse_fixture_lines(
        "Arsenal v Chelsea\nMan City vs Liverpool, 1.85, 3.90, 4.20\n"
    )
    assert errors == []
    assert [(f.home, f.away) for f in fixtures] == [
        ("Arsenal", "Chelsea"),
        ("Man City", "Liverpool"),
    ]
    assert fixtures[0].odds is None
    assert fixtures[1].odds is not None
    assert fixtures[1].odds.draw == 3.90


def test_skips_blank_and_comment_lines() -> None:
    fixtures, errors = parse_fixture_lines("\n# weekend picks\n  \nArsenal V. Chelsea\n")
    assert errors == []
    assert [(f.home, f.away) for f in fixtures] == [("Arsenal", "Chelsea")]


def test_hyphenated_team_names_are_not_split() -> None:
    fixtures, _errors = parse_fixture_lines("Saint-Etienne v Paris SG")
    assert (fixtures[0].home, fixtures[0].away) == ("Saint-Etienne", "Paris SG")


def test_neutral_marker() -> None:
    fixtures, errors = parse_fixture_lines(
        "Morocco v Egypt (n), 2.10, 3.20, 3.90\nKenya v Uganda (Neutral)\nKenya v Tanzania\n"
    )
    assert errors == []
    assert [(f.home, f.away, f.neutral) for f in fixtures] == [
        ("Morocco", "Egypt", True),
        ("Kenya", "Uganda", True),
        ("Kenya", "Tanzania", None),
    ]
    assert fixtures[0].odds is not None


def test_bad_lines_are_reported_not_dropped_silently() -> None:
    fixtures, errors = parse_fixture_lines(
        "Arsenal Chelsea\nArsenal v Chelsea, 1.9, 3.6\nArsenal v Chelsea, 0.9, 3.6, 4.2\n"
        "Arsenal v Chelsea, a, b, c\nSpurs v Everton\n"
    )
    assert [(f.home, f.away) for f in fixtures] == [("Spurs", "Everton")]
    assert len(errors) == 4
    assert errors[0].startswith("Line 1:")
    assert errors[1].startswith("Line 2:")
