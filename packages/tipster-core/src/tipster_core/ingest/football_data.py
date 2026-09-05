"""football-data.co.uk CSV fetching and parsing.

Source format notes (ADR 0002):

- CSVs live at ``https://www.football-data.co.uk/mmz4281/{season}/{league}.csv``
- Column sets drift between seasons; every odds column is optional.
- Dates appear as ``dd/mm/yyyy`` or ``dd/mm/yy`` depending on the season.
- Missing odds are blank cells; a literal ``0`` also means missing.

The parser is pure: bytes in, canonical polars frame out. Its output column
order matches ``tipster_core.storage.MATCHES_COLUMNS`` (minus ``ingested_at``).
"""

from __future__ import annotations

import io
from collections.abc import Mapping

import httpx
import polars as pl

from tipster_core.leagues import LeagueCode, validate_season

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"

_SOURCES = ("b365", "pinnacle", "avg", "max")
_OUTCOMES = ("h", "d", "a")
_SOURCE_PREFIX = {"b365": "B365", "pinnacle": "PS", "avg": "Avg", "max": "Max"}

#: Canonical odds columns, opening block first, then closing (order = storage).
ODDS_COLUMNS: tuple[str, ...] = (
    *(f"odds_{source}_{outcome}" for source in _SOURCES for outcome in _OUTCOMES),
    *(f"odds_{source}_c_{outcome}" for source in _SOURCES for outcome in _OUTCOMES),
)

#: Canonical column -> football-data.co.uk source column.
COLUMN_MAP: Mapping[str, str] = {
    "home_goals": "FTHG",
    "away_goals": "FTAG",
    **{
        f"odds_{source}_{outcome}": f"{_SOURCE_PREFIX[source]}{outcome.upper()}"
        for source in _SOURCES
        for outcome in _OUTCOMES
    },
    **{
        f"odds_{source}_c_{outcome}": f"{_SOURCE_PREFIX[source]}C{outcome.upper()}"
        for source in _SOURCES
        for outcome in _OUTCOMES
    },
}

_REQUIRED_SOURCE_COLUMNS = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}


def csv_url(league: LeagueCode, season: str) -> str:
    """Return the download URL for one league-season CSV."""
    validate_season(season)
    return BASE_URL.format(season=season, league=league.value)


def download_csv(url: str, *, timeout: float = 30.0) -> bytes:
    """Download one CSV, guarding against HTML error pages masquerading as 200s."""
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    content = response.content
    if b"HomeTeam" not in content[:8192]:
        msg = f"{url} did not return a football-data.co.uk CSV"
        raise ValueError(msg)
    return content


def parse_matches_csv(
    content: bytes,
    league: LeagueCode,
    season: str,
    *,
    source_file: str | None = None,
) -> pl.DataFrame:
    """Parse one football-data.co.uk CSV into the canonical matches schema.

    Rows with unparsable dates, teams, or goals are dropped (the source
    occasionally carries junk lines); a frame with zero valid rows raises.
    """
    validate_season(season)
    raw = pl.read_csv(
        io.StringIO(_decode(content)),
        infer_schema_length=0,
        truncate_ragged_lines=True,
    )
    missing = _REQUIRED_SOURCE_COLUMNS - set(raw.columns)
    if missing:
        msg = f"CSV for {league.value} {season} is missing core columns: {sorted(missing)}"
        raise ValueError(msg)

    df = raw.with_columns(
        pl.col("HomeTeam").str.strip_chars().alias("home_team"),
        pl.col("AwayTeam").str.strip_chars().alias("away_team"),
        _parse_dates(pl.col("Date")).alias("date"),
        pl.col("FTHG").cast(pl.Int64, strict=False).alias("home_goals"),
        pl.col("FTAG").cast(pl.Int64, strict=False).alias("away_goals"),
    ).filter(
        pl.col("home_team").is_not_null()
        & (pl.col("home_team") != "")
        & pl.col("away_team").is_not_null()
        & (pl.col("away_team") != "")
        & pl.col("date").is_not_null()
        & pl.col("home_goals").is_not_null()
        & pl.col("away_goals").is_not_null()
    )
    if df.is_empty():
        msg = f"no valid match rows parsed for {league.value} {season}"
        raise ValueError(msg)

    # Odds: cast to float under canonical names, keep only values > 1.0
    # (0 is the source's "missing" marker), and null out absent columns.
    odds_exprs: list[pl.Expr] = []
    for name in ODDS_COLUMNS:
        source = COLUMN_MAP[name]
        if source in df.columns:
            cast = pl.col(source).cast(pl.Float64, strict=False)
            odds_exprs.append(pl.when(cast > 1.0).then(cast).otherwise(None).alias(name))
        else:
            odds_exprs.append(pl.lit(None, dtype=pl.Float64).alias(name))
    df = df.with_columns(odds_exprs)

    return df.select(
        pl.lit(league.value).alias("league"),
        pl.lit(season).alias("season"),
        "date",
        "home_team",
        "away_team",
        "home_goals",
        "away_goals",
        *ODDS_COLUMNS,
        pl.lit(source_file, dtype=pl.String).alias("source_file"),
    ).sort("date")


def _parse_dates(col: pl.Expr) -> pl.Expr:
    """Parse ``dd/mm/yyyy`` or ``dd/mm/yy`` into dates.

    Polars' ``%Y`` accepts two-digit years as literal AD years (``25``, ``8``),
    so a plain null-fallback would silently misdate whole seasons. The ``%Y``
    parse is therefore only trusted when the year is plausible; otherwise the
    ``%y`` parse is used, which pivots 69-99 to the 1900s, 00-68 to the 2000s,
    and rejects four-digit years outright.
    """
    full_year = col.str.to_date(format="%d/%m/%Y", strict=False)
    short_year = col.str.to_date(format="%d/%m/%y", strict=False)
    return pl.when(full_year.dt.year() >= 1900).then(full_year).otherwise(short_year)


def _decode(content: bytes) -> str:
    """Decode CSV bytes; some older seasons are latin-1 rather than utf-8."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("latin-1")
