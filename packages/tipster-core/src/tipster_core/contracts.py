"""Canonical domain contracts for the tipster.

These pydantic models define the language every phase speaks: what a played
match looks like, what a set of 1X2 odds looks like, and (phase 1) what a
priced fixture looks like. The ingest layer normalises raw source data into
this shape; the model, value engine, and UI consume it.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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

    def to_fixture(self) -> Fixture:
        """The same match with goals and odds stripped.

        The single choke point where the backtest harness hands a played
        match to a model: models only ever see a :class:`Fixture`, so they
        cannot read results or the closing line.
        """
        return Fixture(
            league=self.league,
            season=self.season,
            date=self.date,
            home_team=self.home_team,
            away_team=self.away_team,
        )


class Fixture(BaseModel):
    """An upcoming match: identity only — no goals, no odds.

    Deliberately impoverished. The model contract (``tipster_core.predictor``)
    only accepts fixtures, which is what keeps closing-line-value honest
    (docs/design.md): a model that could read the closing line would make
    the CLV metric self-referential.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    league: LeagueCode
    season: str
    date: date
    home_team: str = Field(min_length=1)
    away_team: str = Field(min_length=1)

    @field_validator("season")
    @classmethod
    def _check_season(cls, value: str) -> str:
        validate_season(value)
        return value

    @property
    def fixture(self) -> str:
        """An ``"Arsenal v West Ham"`` style label."""
        return f"{self.home_team} v {self.away_team}"


class ScorelineProbability(BaseModel):
    """One cell of a score matrix: a scoreline and its probability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    home_goals: int = Field(ge=0)
    away_goals: int = Field(ge=0)
    probability: float = Field(ge=0.0, le=1.0)


class ScoreMatrix(BaseModel):
    """A full scoreline probability matrix — the single source for every market.

    ``rows[i][j]`` is the probability of a ``home_goals=i, away_goals=j``
    finish (row-major, ``(max_goals + 1) x (max_goals + 1)`` cells). All
    market probabilities in the tipster are derived from this one object,
    so no arm can price markets inconsistently (ADR 0003).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_goals: int = Field(ge=1)
    rows: tuple[tuple[float, ...], ...]

    @field_validator("rows")
    @classmethod
    def _check_rows(cls, value: tuple[tuple[float, ...], ...]) -> tuple[tuple[float, ...], ...]:
        size = len(value)
        if size < 2:
            msg = "score matrix must have at least 2 rows"
            raise ValueError(msg)
        if any(len(row) != size for row in value):
            msg = f"score matrix rows must all have {size} cells"
            raise ValueError(msg)
        if any(cell < 0.0 for row in value for cell in row):
            msg = "score matrix cells must be non-negative"
            raise ValueError(msg)
        total = sum(cell for row in value for cell in row)
        if abs(total - 1.0) > 1e-6:
            msg = f"score matrix must sum to 1.0, got {total!r}"
            raise ValueError(msg)
        return value

    def p(self, home_goals: int, away_goals: int) -> float:
        """The probability of an exact scoreline."""
        return self.rows[home_goals][away_goals]

    @property
    def p_home(self) -> float:
        """Probability of a home win (any scoreline)."""
        return sum(self.rows[i][j] for i in range(len(self.rows)) for j in range(i))

    @property
    def p_draw(self) -> float:
        """Probability of a draw (any scoreline)."""
        return sum(self.rows[i][i] for i in range(len(self.rows)))

    @property
    def p_away(self) -> float:
        """Probability of an away win (any scoreline)."""
        return sum(
            self.rows[i][j] for i in range(len(self.rows)) for j in range(i + 1, len(self.rows))
        )

    @property
    def p_over25(self) -> float:
        """Probability of over 2.5 goals."""
        return sum(
            self.rows[i][j]
            for i in range(len(self.rows))
            for j in range(len(self.rows))
            if i + j >= 3
        )

    @property
    def p_under25(self) -> float:
        """Probability of under 2.5 goals."""
        return 1.0 - self.p_over25

    @property
    def p_btts(self) -> float:
        """Probability of both teams scoring."""
        return sum(
            self.rows[i][j] for i in range(1, len(self.rows)) for j in range(1, len(self.rows))
        )

    @property
    def p_btts_no(self) -> float:
        """Probability of at least one team failing to score."""
        return 1.0 - self.p_btts

    def scorelines(self) -> list[ScorelineProbability]:
        """All cells, most probable first."""
        cells = [
            ScorelineProbability(home_goals=i, away_goals=j, probability=self.rows[i][j])
            for i in range(len(self.rows))
            for j in range(len(self.rows))
        ]
        return sorted(cells, key=lambda cell: cell.probability, reverse=True)


class MarketProbabilities(BaseModel):
    """Per-market probabilities derived from one :class:`ScoreMatrix`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    home: float = Field(ge=0.0, le=1.0)
    draw: float = Field(ge=0.0, le=1.0)
    away: float = Field(ge=0.0, le=1.0)
    over25: float = Field(ge=0.0, le=1.0)
    under25: float = Field(ge=0.0, le=1.0)
    btts_yes: float = Field(ge=0.0, le=1.0)
    btts_no: float = Field(ge=0.0, le=1.0)
    correct_scores: tuple[ScorelineProbability, ...] = Field(default=())

    @model_validator(mode="after")
    def _check_coherent(self) -> MarketProbabilities:
        """Each market's outcomes must partition the probability mass."""
        for label, total in (
            ("home + draw + away", self.home + self.draw + self.away),
            ("over25 + under25", self.over25 + self.under25),
            ("btts_yes + btts_no", self.btts_yes + self.btts_no),
        ):
            if abs(total - 1.0) > 1e-6:
                msg = f"{label} must sum to 1.0, got {total!r}"
                raise ValueError(msg)
        return self

    @classmethod
    def from_matrix(cls, matrix: ScoreMatrix) -> MarketProbabilities:
        """Derive every market exactly from the one matrix (ADR 0003)."""
        return cls(
            home=matrix.p_home,
            draw=matrix.p_draw,
            away=matrix.p_away,
            over25=matrix.p_over25,
            under25=matrix.p_under25,
            btts_yes=matrix.p_btts,
            btts_no=matrix.p_btts_no,
            correct_scores=tuple(matrix.scorelines()),
        )


class MatchPrediction(BaseModel):
    """A priced fixture: the score matrix, its market view, and the lambdas.

    ``markets`` is the calibrated truth when a calibrator is wrapped around
    the model; ``matrix`` stays the uncalibrated structural source.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fixture: Fixture
    matrix: ScoreMatrix
    markets: MarketProbabilities
    model: str
    lambda_home: float | None = None
    lambda_away: float | None = None
