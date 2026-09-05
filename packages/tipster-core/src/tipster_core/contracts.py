"""Canonical domain contracts for the tipster.

These pydantic models define the language every phase speaks: what a played
match looks like and what a set of 1X2 odds looks like. The ingest layer
normalises raw source data into this shape; the model, value engine, and UI
consume it.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tipster_core.leagues import LeagueCode, validate_season


class OutcomeOdds(BaseModel):
    """Decimal (European) odds for the three 1X2 outcomes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    home: float = Field(gt=1.0)
    draw: float = Field(gt=1.0)
    away: float = Field(gt=1.0)


class MatchOdds(BaseModel):
    """Odds recorded for a match, by source and point in time.

    Opening odds are the initial pre-match prices; closing odds are the last
    prices before kickoff and are the reference for closing line value
    (docs/design.md).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    b365: OutcomeOdds | None = None
    pinnacle: OutcomeOdds | None = None
    avg: OutcomeOdds | None = None
    max: OutcomeOdds | None = None
    b365_closing: OutcomeOdds | None = None
    pinnacle_closing: OutcomeOdds | None = None
    avg_closing: OutcomeOdds | None = None
    max_closing: OutcomeOdds | None = None


class MatchResult(BaseModel):
    """A played match with its result and (optionally) its recorded odds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    league: LeagueCode
    season: str
    date: date
    home_team: str = Field(min_length=1)
    away_team: str = Field(min_length=1)
    home_goals: int = Field(ge=0)
    away_goals: int = Field(ge=0)
    odds: MatchOdds | None = None

    @field_validator("season")
    @classmethod
    def _check_season(cls, value: str) -> str:
        validate_season(value)
        return value

    @property
    def fixture(self) -> str:
        """An ``"Arsenal v West Ham"`` style label."""
        return f"{self.home_team} v {self.away_team}"
