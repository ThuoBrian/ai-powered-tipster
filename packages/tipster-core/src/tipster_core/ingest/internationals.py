"""National-team results: martj42/international_results (CC0, ADR 0011).

One CSV of every men's international since 1872:
``date,home_team,away_team,home_score,away_score,tournament,city,country,neutral``.
Scheduled fixtures appear with ``NA`` scores and are dropped; ``neutral``
is ``TRUE``/``FALSE``; some city names contain quoted commas (a real CSV
parser handles them). There are no odds, so internationals are scored
probabilistically only.

All national teams form one pool (``LeagueCode.INTERNATIONAL``): they meet
across tournaments, so per-tournament ratings would split thin data further.
The season is the calendar year.
"""

from __future__ import annotations

import io
from datetime import date

import polars as pl

from tipster_core.ingest.football_data import ODDS_COLUMNS
from tipster_core.leagues import LeagueCode

INTERNATIONALS_URL = (
    "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
)

#: National teams play 8-12 games a year, so they need a longer window than
#: clubs; Dixon-Coles time decay still weights recent form most.
INTERNATIONALS_SINCE = date(2014, 1, 1)

_REQUIRED_COLUMNS = {"date", "home_team", "away_team", "home_score", "away_score", "neutral"}


def parse_internationals_csv(
    content: bytes,
    *,
    since: date = INTERNATIONALS_SINCE,
    source_file: str | None = None,
) -> pl.DataFrame:
    """Parse the results CSV into the canonical matches schema (odds all null)."""
    raw = pl.read_csv(io.BytesIO(content), infer_schema_length=0)
    missing = _REQUIRED_COLUMNS - set(raw.columns)
    if missing:
        msg = f"international results CSV is missing columns: {sorted(missing)}"
        raise ValueError(msg)

    df = raw.with_columns(
        pl.col("date").str.to_date("%Y-%m-%d", strict=False),
        pl.col("home_team").str.strip_chars(),
        pl.col("away_team").str.strip_chars(),
        pl.col("home_score").cast(pl.Int64, strict=False).alias("home_goals"),
        pl.col("away_score").cast(pl.Int64, strict=False).alias("away_goals"),
        (pl.col("neutral").str.strip_chars().str.to_uppercase() == "TRUE").alias("neutral"),
    ).filter(
        pl.col("date").is_not_null()
        & (pl.col("date") >= since)
        & pl.col("home_goals").is_not_null()
        & pl.col("away_goals").is_not_null()
        & (pl.col("home_team") != "")
        & (pl.col("away_team") != "")
    )
    if df.is_empty():
        msg = "no valid international results parsed"
        raise ValueError(msg)

    return df.select(
        pl.lit(LeagueCode.INTERNATIONAL.value).alias("league"),
        pl.col("date").dt.year().cast(pl.String).alias("season"),
        "date",
        "home_team",
        "away_team",
        "home_goals",
        "away_goals",
        "neutral",
        *(pl.lit(None, dtype=pl.Float64).alias(name) for name in ODDS_COLUMNS),
        pl.lit(source_file, dtype=pl.String).alias("source_file"),
    ).sort("date")
