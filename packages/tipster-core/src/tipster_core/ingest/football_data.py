"""football-data.co.uk CSV fetching and parsing.

Source format notes (ADR 0002):

- CSVs live at ``https://www.football-data.co.uk/mmz4281/{season}/{league}.csv``
- "Extra leagues" (ADR 0011) are one file per country at
  ``new/{CODE}.csv``, every season, with ``Home``/``Away``/``HG``/``AG``,
  a ``Season`` column, a UTF-8 BOM, and closing odds only.
- Column sets drift between seasons; every odds column is optional.
- Dates appear as ``dd/mm/yyyy`` or ``dd/mm/yy`` depending on the season.
- Missing odds are blank cells; a literal ``0`` also means missing.

The parser is pure: bytes in, canonical polars frame out. Its output column
order matches ``tipster_core.storage.MATCHES_COLUMNS`` (minus ``ingested_at``).
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from datetime import date

import httpx
import polars as pl

from tipster_core.leagues import EXTRA_LEAGUES, LeagueCode, validate_season

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"
EXTRA_URL = "https://www.football-data.co.uk/new/{league}.csv"

#: Earliest match kept from the all-seasons extra-league files: roughly the
#: same ~3 seasons of history the main-league default ingests.
EXTRA_SINCE = date(2023, 1, 1)

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
_REQUIRED_EXTRA_COLUMNS = {"Season", "Date", "Home", "Away", "HG", "AG"}


def csv_url(league: LeagueCode, season: str) -> str:
    """Return the download URL for one league-season CSV."""
    validate_season(season)
    return BASE_URL.format(season=season, league=league.value)


def download_csv(url: str, *, timeout: float = 30.0, marker: bytes = b"HomeTeam") -> bytes:
    """Download one CSV, guarding against HTML error pages masquerading as 200s.

    *marker* is a header name the real file must contain (``b"Home"`` for
    the extra-league files).
    """
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    content = response.content
    if marker not in content[:8192]:
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
        pl.lit(season).alias("season"),
        pl.col("HomeTeam").str.strip_chars().alias("home_team"),
        pl.col("AwayTeam").str.strip_chars().alias("away_team"),
        _parse_dates(pl.col("Date")).alias("date"),
        pl.col("FTHG").cast(pl.Int64, strict=False).alias("home_goals"),
        pl.col("FTAG").cast(pl.Int64, strict=False).alias("away_goals"),
    )
    return _canonical(df, league, source_file, f"{league.value} {season}")


def extra_csv_url(league: LeagueCode) -> str:
    """Return the all-seasons URL for one of the "extra leagues" (e.g. ``BRA``)."""
    if league not in EXTRA_LEAGUES:
        msg = f"{league.value} is not a football-data.co.uk extra league"
        raise ValueError(msg)
    return EXTRA_URL.format(league=league.value)


def parse_extra_csv(
    content: bytes,
    league: LeagueCode,
    *,
    since: date = EXTRA_SINCE,
    source_file: str | None = None,
) -> pl.DataFrame:
    """Parse an extra-league CSV (every season in one file) into the canonical schema.

    The file carries its own ``Season`` column (``2026`` or ``2025/2026``)
    and closing odds only; opening-odds columns come out null. Matches
    before *since* are dropped.
    """
    raw = pl.read_csv(
        io.StringIO(_decode(content)),
        infer_schema_length=0,
        truncate_ragged_lines=True,
    )
    missing = _REQUIRED_EXTRA_COLUMNS - set(raw.columns)
    if missing:
        msg = f"CSV for {league.value} is missing core columns: {sorted(missing)}"
        raise ValueError(msg)

    df = raw.with_columns(
        pl.col("Season").str.strip_chars().alias("season"),
        pl.col("Home").str.strip_chars().alias("home_team"),
        pl.col("Away").str.strip_chars().alias("away_team"),
        _parse_dates(pl.col("Date")).alias("date"),
        pl.col("HG").cast(pl.Int64, strict=False).alias("home_goals"),
        pl.col("AG").cast(pl.Int64, strict=False).alias("away_goals"),
    ).filter(pl.col("date") >= since)
    for season in df.get_column("season").drop_nulls().unique().to_list():
        validate_season(season)
    return _canonical(df, league, source_file, league.value)


def _canonical(
    df: pl.DataFrame, league: LeagueCode, source_file: str | None, label: str
) -> pl.DataFrame:
    """Drop junk rows, normalise odds, and select the storage column order.

    *df* must already carry ``season``, ``date``, team and goal columns.
    Rows with an unparsable date, team, or score are dropped (the sources
    carry junk lines and future fixtures); zero valid rows raises.
    """
    df = df.filter(
        pl.col("season").is_not_null()
        & pl.col("home_team").is_not_null()
        & (pl.col("home_team") != "")
        & pl.col("away_team").is_not_null()
        & (pl.col("away_team") != "")
        & pl.col("date").is_not_null()
        & pl.col("home_goals").is_not_null()
        & pl.col("away_goals").is_not_null()
    )
    if df.is_empty():
        msg = f"no valid match rows parsed for {label}"
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
        "season",
        "date",
        "home_team",
        "away_team",
        "home_goals",
        "away_goals",
        pl.lit(False).alias("neutral"),
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
    """Decode CSV bytes (stripping any UTF-8 BOM); some older seasons are latin-1."""
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("latin-1")
