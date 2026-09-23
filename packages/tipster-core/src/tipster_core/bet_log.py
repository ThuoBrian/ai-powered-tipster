"""The paper-trading bet log: a SQLite ledger of taken tips (ADR 0009).

Design (docs/design.md): everything is paper-traded and logged until CLV
says otherwise. Two stakes are logged per bet — the fractional-Kelly stake
(the live sizing, ADR 0006) and a flat 1-unit stake (the control arm) — so
the two staking strategies can be judged side by side, exactly as the
walk-forward backtest already judges model arms.

SQLite, not DuckDB (docs/design.md is explicit about this): this is a
small, mostly-append ledger someone might open directly with any SQLite
tool — a different engine for a different job than the analytical matches
store.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from tipster_core.backtest.baselines import closing_odds
from tipster_core.backtest.metrics import clv as clv_fraction
from tipster_core.backtest.results import ClvSummary, RoiSummary
from tipster_core.contracts import MatchResult
from tipster_core.leagues import LeagueCode
from tipster_core.value import OddsSource, Outcome, ValueTip

DEFAULT_BET_LOG_PATH = Path("data") / "bets.sqlite"

_DDL = """
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    placed_at TEXT NOT NULL,
    model TEXT NOT NULL,
    league TEXT NOT NULL,
    season TEXT NOT NULL,
    match_date TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    pick TEXT NOT NULL,
    p_model REAL NOT NULL,
    p_market_fair REAL NOT NULL,
    odds REAL NOT NULL,
    odds_source TEXT NOT NULL,
    ev REAL NOT NULL,
    kelly_stake REAL NOT NULL,
    flat_stake REAL NOT NULL,
    settled_at TEXT,
    home_goals INTEGER,
    away_goals INTEGER,
    won INTEGER,
    kelly_profit REAL,
    flat_profit REAL,
    closing_odds REAL,
    clv_pct REAL,
    UNIQUE (model, league, season, match_date, home_team, away_team, pick)
)
"""


class LoggedBet(BaseModel):
    """One row of the bet log: a taken tip, settled or still pending."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    placed_at: datetime
    model: str
    league: LeagueCode
    season: str
    match_date: date
    home_team: str
    away_team: str
    pick: Outcome
    p_model: float = Field(ge=0.0, le=1.0)
    p_market_fair: float = Field(ge=0.0, le=1.0)
    odds: float = Field(gt=1.0)
    odds_source: OddsSource
    ev: float
    kelly_stake: float = Field(ge=0.0)
    flat_stake: float = Field(ge=0.0)
    settled_at: datetime | None = None
    home_goals: int | None = Field(default=None, ge=0)
    away_goals: int | None = Field(default=None, ge=0)
    won: bool | None = None
    kelly_profit: float | None = None
    flat_profit: float | None = None
    closing_odds: float | None = Field(default=None, gt=1.0)
    clv_pct: float | None = None

    @property
    def fixture_label(self) -> str:
        return f"{self.home_team} v {self.away_team}"


class BetLogSummary(BaseModel):
    """Kelly vs. flat-stake performance, plus CLV, across settled bets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    n_settled: int = Field(ge=0)
    n_pending: int = Field(ge=0)
    kelly: RoiSummary
    flat: RoiSummary
    clv: ClvSummary


def connect(db_path: str | Path = DEFAULT_BET_LOG_PATH) -> sqlite3.Connection:
    """Open the bet log, ensuring the schema exists."""
    path = str(db_path)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute(_DDL)
    con.commit()
    return con


def record_bet(con: sqlite3.Connection, tip: ValueTip, *, flat_stake: float = 1.0) -> bool:
    """Log one tip as taken. Returns ``False`` without erroring if already logged.

    A bet is identified by (model, league, season, date, home team, away
    team, pick) — logging the same tip twice (e.g. a double-click) is a
    no-op, not a duplicate row.
    """
    cursor = con.execute(
        """
        INSERT OR IGNORE INTO bets (
            placed_at, model, league, season, match_date, home_team, away_team,
            pick, p_model, p_market_fair, odds, odds_source, ev, kelly_stake, flat_stake
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(timespec="seconds"),
            tip.model,
            tip.fixture.league.value,
            tip.fixture.season,
            tip.fixture.date.isoformat(),
            tip.fixture.home_team,
            tip.fixture.away_team,
            tip.pick,
            tip.p_model,
            tip.p_market_fair,
            tip.odds,
            tip.odds_source,
            tip.ev,
            tip.kelly_stake,
            flat_stake,
        ),
    )
    con.commit()
    return cursor.rowcount > 0


def _row_to_bet(row: sqlite3.Row) -> LoggedBet:
    return LoggedBet(
        id=row["id"],
        placed_at=datetime.fromisoformat(row["placed_at"]),
        model=row["model"],
        league=LeagueCode.from_code(row["league"]),
        season=row["season"],
        match_date=date.fromisoformat(row["match_date"]),
        home_team=row["home_team"],
        away_team=row["away_team"],
        pick=row["pick"],
        p_model=row["p_model"],
        p_market_fair=row["p_market_fair"],
        odds=row["odds"],
        odds_source=row["odds_source"],
        ev=row["ev"],
        kelly_stake=row["kelly_stake"],
        flat_stake=row["flat_stake"],
        settled_at=datetime.fromisoformat(row["settled_at"]) if row["settled_at"] else None,
        home_goals=row["home_goals"],
        away_goals=row["away_goals"],
        won=bool(row["won"]) if row["won"] is not None else None,
        kelly_profit=row["kelly_profit"],
        flat_profit=row["flat_profit"],
        closing_odds=row["closing_odds"],
        clv_pct=row["clv_pct"],
    )


def all_bets(con: sqlite3.Connection) -> list[LoggedBet]:
    """The full ledger, most recently placed first."""
    rows = con.execute("SELECT * FROM bets ORDER BY placed_at DESC").fetchall()
    return [_row_to_bet(row) for row in rows]


def pending_bets(con: sqlite3.Connection) -> list[LoggedBet]:
    """Bets not yet settled, oldest fixture first."""
    rows = con.execute("SELECT * FROM bets WHERE settled_at IS NULL ORDER BY match_date").fetchall()
    return [_row_to_bet(row) for row in rows]


def _actual_outcome(match: MatchResult) -> Outcome:
    if match.home_goals > match.away_goals:
        return "home"
    if match.home_goals < match.away_goals:
        return "away"
    return "draw"


def settle_bets(con: sqlite3.Connection, played: Sequence[MatchResult]) -> int:
    """Settle every pending bet whose fixture appears in *played*.

    Matched on (league, date, home team, away team). Season is deliberately
    left out: a live fixture's season is derived from its date and can be
    labelled differently from the ingested result (calendar vs split
    seasons, ADR 0011), and a mismatch would leave the bet pending forever.
    A bet whose match hasn't been ingested yet is left pending, not guessed.
    """
    by_fixture: dict[tuple[str, date, str, str], MatchResult] = {
        (m.league.value, m.date, m.home_team, m.away_team): m for m in played
    }
    settled = 0
    for bet in pending_bets(con):
        key = (bet.league.value, bet.match_date, bet.home_team, bet.away_team)
        match = by_fixture.get(key)
        if match is None:
            continue
        _settle_one(con, bet, match)
        settled += 1
    con.commit()
    return settled


def _settle_one(con: sqlite3.Connection, bet: LoggedBet, match: MatchResult) -> None:
    won = _actual_outcome(match) == bet.pick
    kelly_profit = bet.kelly_stake * (bet.odds - 1.0) if won else -bet.kelly_stake
    flat_profit = bet.flat_stake * (bet.odds - 1.0) if won else -bet.flat_stake

    closing_price: float | None = None
    clv_value: float | None = None
    chosen = closing_odds(match)
    if chosen is not None:
        outcome_odds, _source = chosen
        closing_price = {
            "home": outcome_odds.home,
            "draw": outcome_odds.draw,
            "away": outcome_odds.away,
        }[bet.pick]
        clv_value = clv_fraction(bet.odds, closing_price) * 100.0

    con.execute(
        """
        UPDATE bets SET
            settled_at = ?, home_goals = ?, away_goals = ?, won = ?,
            kelly_profit = ?, flat_profit = ?, closing_odds = ?, clv_pct = ?
        WHERE id = ?
        """,
        (
            datetime.now().isoformat(timespec="seconds"),
            match.home_goals,
            match.away_goals,
            int(won),
            kelly_profit,
            flat_profit,
            closing_price,
            clv_value,
            bet.id,
        ),
    )


def summarize(con: sqlite3.Connection) -> BetLogSummary:
    """Kelly vs. flat ROI and CLV across every settled bet."""
    bets = all_bets(con)
    settled = [bet for bet in bets if bet.settled_at is not None]
    pending = [bet for bet in bets if bet.settled_at is None]

    kelly_staked = sum(bet.kelly_stake for bet in settled)
    kelly_profit = sum(bet.kelly_profit or 0.0 for bet in settled)
    flat_staked = sum(bet.flat_stake for bet in settled)
    flat_profit = sum(bet.flat_profit or 0.0 for bet in settled)
    clv_values = [bet.clv_pct for bet in settled if bet.clv_pct is not None]

    return BetLogSummary(
        n_settled=len(settled),
        n_pending=len(pending),
        kelly=RoiSummary(
            total_staked=kelly_staked,
            total_profit=kelly_profit,
            roi_pct=(kelly_profit / kelly_staked * 100.0) if kelly_staked > 0 else 0.0,
            n_bets=len(settled),
        ),
        flat=RoiSummary(
            total_staked=flat_staked,
            total_profit=flat_profit,
            roi_pct=(flat_profit / flat_staked * 100.0) if flat_staked > 0 else 0.0,
            n_bets=len(settled),
        ),
        clv=ClvSummary(
            n=len(clv_values),
            mean_clv_pct=(sum(clv_values) / len(clv_values)) if clv_values else 0.0,
            beat_rate=(sum(1 for v in clv_values if v > 0) / len(clv_values))
            if clv_values
            else 0.0,
        ),
    )
