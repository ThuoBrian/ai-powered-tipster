"""Tests for the dashboard's shared helpers."""

from __future__ import annotations

from collections import Counter

from tipster_core.leagues import LeagueCode
from tipster_ui.shared import REGIONS


def test_every_competition_is_in_exactly_one_region() -> None:
    counts = Counter(league for leagues in REGIONS.values() for league in leagues)
    assert set(counts) == set(LeagueCode)
    assert all(n == 1 for n in counts.values())
