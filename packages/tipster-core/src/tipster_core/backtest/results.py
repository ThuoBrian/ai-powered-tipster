"""Typed backtest artifacts — the cross-phase output language.

These are the structures the Streamlit UI and the phase-2 value engine
consume: ``model_dump()``-able pydantic models, one per backtest run, plus
per-fixture records for deeper slicing.
"""

from __future__ import annotations

# Imported as the module: a field named ``date`` would shadow the class
# if the bare name were imported.
import datetime

from pydantic import BaseModel, ConfigDict, Field

from tipster_core.backtest.metrics import Family, OddsSource, OutcomeVariant


class ReliabilityBin(BaseModel):
    """One decile of a reliability curve: predicted vs observed rate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bin_midpoint: float = Field(ge=0.0, le=1.0)
    predicted_mean: float = Field(ge=0.0, le=1.0)
    observed_rate: float = Field(ge=0.0, le=1.0)
    count: int = Field(ge=0)


class ReliabilityCurve(BaseModel):
    """A reliability diagram for one binary variant of one arm."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    family: OutcomeVariant
    bins: tuple[ReliabilityBin, ...]


class FamilyMetrics(BaseModel):
    """Probabilistic quality for one market family."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    brier: float = Field(ge=0.0)
    log_loss: float = Field(ge=0.0)
    n: int = Field(ge=0)


class RoiSummary(BaseModel):
    """Flat-stake profit: one unit per bet, on the argmax pick per family."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_staked: float
    total_profit: float
    roi_pct: float
    n_bets: int = Field(ge=0)


class ClvSummary(BaseModel):
    """Closing line value vs Pinnacle closing, on the arm's 1X2 picks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    n: int = Field(ge=0)
    mean_clv_pct: float
    beat_rate: float = Field(ge=0.0, le=1.0)


class PickRecord(BaseModel):
    """One settled bet of one arm."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    family: Family
    pick: str
    probability: float = Field(ge=0.0, le=1.0)
    odds: float | None = Field(default=None, gt=1.0)
    odds_source: OddsSource | None = None
    won: bool
    profit: float


class FixtureRecord(BaseModel):
    """One fixture as one arm saw it: prediction, truth, odds, and picks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    league: str
    season: str
    date: datetime.date
    home_team: str
    away_team: str
    block_start: datetime.date
    true_home_goals: int = Field(ge=0)
    true_away_goals: int = Field(ge=0)
    model: str
    home: float
    draw: float
    away: float
    over25: float
    under25: float
    btts_yes: float
    btts_no: float
    picks: tuple[PickRecord, ...] = Field(default=())


class GateComparison(BaseModel):
    """The hybrid vs one benchmark on the primary metrics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark: str
    hybrid_1x2_log_loss: float
    benchmark_1x2_log_loss: float
    hybrid_1x2_brier: float
    benchmark_1x2_brier: float
    hybrid_wins: bool


class GateResult(BaseModel):
    """ADR 0003's evaluation gate: the hybrid must beat every benchmark.

    Reported, never CI-asserted — on synthetic data the comparison is
    meaningless. On the real corpus this is the decision aid that justifies
    (or rejects) the hybrid's complexity.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hybrid: str
    comparisons: tuple[GateComparison, ...]
    passes: bool


class ArmReport(BaseModel):
    """Everything one model arm did over the walk-forward window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    n_fixtures: int = Field(ge=0)
    families: dict[str, FamilyMetrics]
    reliability: dict[str, ReliabilityCurve]
    roi: RoiSummary
    clv: ClvSummary
    hit_rate_1x2: float = Field(ge=0.0, le=1.0)
    """Share of fixtures where the arm's most likely 1X2 outcome happened."""
    gate: GateResult | None = None


class BacktestReport(BaseModel):
    """The full walk-forward result, ready for the UI and the value engine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    started: datetime.date
    ended: datetime.date
    block_days: int = Field(ge=1)
    n_blocks: int = Field(ge=0)
    arms: dict[str, ArmReport]
    gate: GateResult
    records: tuple[FixtureRecord, ...] = Field(default=())
