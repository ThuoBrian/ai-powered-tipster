"""Shared fixtures: realistic football-data.co.uk CSV samples.

The modern fixture mirrors a current-season file (32 columns) and exercises
both date formats, a zero "missing" price, blank closing odds, and a junk
line. The legacy fixture mirrors an old-season file with core columns only.
"""

from __future__ import annotations

import pytest

MODERN_CSV = (
    b"Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,PSH,PSD,PSA,"
    b"AvgH,AvgD,AvgA,MaxH,MaxD,MaxA,B365CH,B365CD,B365CA,PSCH,PSCD,PSCA,"
    b"AvgCH,AvgCD,AvgCA,MaxCH,MaxCD,MaxCA\n"
    b"E0,16/08/2025,12:30,Arsenal,West Ham,3,0,H,1.85,3.6,4.5,1.83,3.7,4.6,"
    b"1.86,3.65,4.55,1.95,3.8,4.8,1.95,3.5,4.2,1.9,3.6,4.4,1.9,3.6,4.5,1.99,3.75,4.9\n"
    b"E0,17/08/25,14:00,Chelsea,Liverpool,1,1,D,2.5,3.3,2.7,2.48,3.35,2.75,"
    b"2.51,3.32,2.72,2.6,3.5,2.9,2.6,3.3,2.75,2.55,3.35,2.8,2.6,3.35,2.8,2.7,3.55,2.95\n"
    b"E0,23/08/2025,15:00,Man City,Tottenham,2,1,H,0,0,0,1.5,4.0,6.5,"
    b"1.55,4.1,6.2,1.6,4.4,7.0,,,,,,,,,,,,\n"
    b",,,,,,,\n"
)

LEGACY_CSV = (
    b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
    b"E0,11/08/2008, Arsenal ,West Ham,1,0,H\n"
    b"E0,16/08/08,Chelsea,Liverpool,0,0,D\n"
)


@pytest.fixture
def modern_csv() -> bytes:
    """A modern-season CSV with the full odds column set."""
    return MODERN_CSV


@pytest.fixture
def legacy_csv() -> bytes:
    """A legacy-season CSV with core columns only."""
    return LEGACY_CSV
