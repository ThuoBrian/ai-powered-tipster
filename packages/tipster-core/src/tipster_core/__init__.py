"""tipster-core: the domain library for the AI-powered football tipster.

Phase 0 scope: league/season identifiers, pydantic contracts,
football-data.co.uk ingestion, and DuckDB storage. Later phases add the
feature builder, the GBM → Poisson model, the value engine, and backtesting
(see docs/design.md in the repo root).
"""

from tipster_core.contracts import MatchOdds, MatchResult, OutcomeOdds
from tipster_core.leagues import (
    BIG_5,
    LeagueCode,
    season_code,
    season_label,
    validate_season,
)
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
    "LeagueCode",
    "MatchOdds",
    "MatchResult",
    "OutcomeOdds",
    "connect",
    "match_counts",
    "recent_matches",
    "replace_season",
    "season_code",
    "season_label",
    "validate_season",
]
