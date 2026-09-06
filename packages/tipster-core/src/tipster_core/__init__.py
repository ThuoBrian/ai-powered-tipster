"""tipster-core: the domain library for the AI-powered football tipster.

Phase 0 scope: league/season identifiers, pydantic contracts,
football-data.co.uk ingestion, and DuckDB storage. Phase 1 adds the
feature builder, the GBM → Poisson model, and the walk-forward backtest
harness; the value engine and reasoning layer come later (see docs/design.md
in the repo root).
"""

from tipster_core.contracts import (
    Fixture,
    MarketProbabilities,
    MatchOdds,
    MatchPrediction,
    MatchResult,
    OutcomeOdds,
    ScorelineProbability,
    ScoreMatrix,
)
from tipster_core.leagues import (
    BIG_5,
    LeagueCode,
    season_code,
    season_label,
    validate_season,
)
from tipster_core.predictor import Predictor
from tipster_core.storage import (
    DEFAULT_DB_PATH,
    connect,
    match_counts,
    recent_matches,
    replace_season,
)

__version__ = "0.1.0"

__all__ = [
    "BIG_5",
    "DEFAULT_DB_PATH",
    "Fixture",
    "LeagueCode",
    "MarketProbabilities",
    "MatchOdds",
    "MatchPrediction",
    "MatchResult",
    "OutcomeOdds",
    "Predictor",
    "ScoreMatrix",
    "ScorelineProbability",
    "connect",
    "match_counts",
    "recent_matches",
    "replace_season",
    "season_code",
    "season_label",
    "validate_season",
]
