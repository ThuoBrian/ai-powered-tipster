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
    season_from_date,
    season_label,
    validate_season,
)
from tipster_core.predictor import Predictor
from tipster_core.storage import (
    DEFAULT_DB_PATH,
    connect,
    load_match_results,
    match_counts,
    recent_matches,
    replace_season,
)
from tipster_core.team_aliases import resolve_team_name
from tipster_core.value import (
    OddsSource,
    ValueTip,
    expected_value,
    find_value_tips,
    kelly_fraction,
    shin_probabilities,
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
    "OddsSource",
    "OutcomeOdds",
    "Predictor",
    "ScoreMatrix",
    "ScorelineProbability",
    "ValueTip",
    "connect",
    "expected_value",
    "find_value_tips",
    "kelly_fraction",
    "load_match_results",
    "match_counts",
    "recent_matches",
    "replace_season",
    "resolve_team_name",
    "season_code",
    "season_from_date",
    "season_label",
    "shin_probabilities",
    "validate_season",
]
