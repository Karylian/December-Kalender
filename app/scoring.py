"""Winst- en kansberekening voor één kalender (puur, zonder database)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from . import odds
from .rules import Ruleset, Symbol


@dataclass(frozen=True)
class SymbolRow:
    symbol: Symbol
    seen: int
    achieved: bool
    reachable: bool
    chance: float | None  # None = geen pool-aanname bekend


@dataclass(frozen=True)
class GameResult:
    game: int  # dagnummer voor feestdagspellen, volgnummer voor extra spellen
    amounts: tuple[int | None, ...]
    win_cents: int


@dataclass(frozen=True)
class Summary:
    opened: int
    remaining: int
    rows: tuple[SymbolRow, ...]
    holidays: tuple[GameResult, ...]
    extras: tuple[GameResult, ...]
    symbol_win_cents: int
    holiday_win_cents: int
    extra_win_cents: int

    @property
    def total_win_cents(self) -> int:
        return self.symbol_win_cents + self.holiday_win_cents + self.extra_win_cents


def effective_win_cents(status: str, done_total_cents: int | None, computed_cents: int) -> int:
    """Winst voor de geldstatistieken: bij een afgerond lot telt het ingevulde totaal."""
    if status == "done" and done_total_cents is not None:
        return done_total_cents
    return computed_cents


def matching_pair_win(amounts) -> int:
    """Feestdagspel: twee (of meer) gelijke bedragen winnen dat bedrag."""
    counts = Counter(a for a in amounts if a)
    pairs = [amount for amount, n in counts.items() if n >= 2]
    return max(pairs, default=0)


def extra_game_win(amounts, rule: str) -> int:
    if rule == "match2":
        return matching_pair_win(amounts)
    return sum(a for a in amounts if a)


def summarize(
    ruleset: Ruleset,
    boxes: dict[int, str],
    holiday_amounts: dict[int, dict[int, int]],
    extra_amounts: dict[int, dict[int, int]],
) -> Summary:
    """``boxes``: dag -> symbol_key. ``*_amounts``: spel -> slot -> bedrag in centen."""
    opened = len(boxes)
    counts = Counter(boxes.values())
    rows = []
    for symbol in ruleset.prize_symbols:
        seen = counts.get(symbol.key, 0)
        pool_count = ruleset.pool.get(symbol.key)
        chance = (
            None
            if pool_count is None
            else odds.symbol_chance(
                pool_size=ruleset.pool_size,
                pool_count=pool_count,
                boxes=ruleset.boxes,
                opened=opened,
                seen_this=seen,
                needed=symbol.needed,
            )
        )
        rows.append(
            SymbolRow(
                symbol=symbol,
                seen=seen,
                achieved=seen >= symbol.needed,
                reachable=symbol.needed - seen <= ruleset.boxes - opened,
                chance=chance,
            )
        )

    def games(numbers, n_slots, stored, win):
        results = []
        for game in numbers:
            amounts = tuple(stored.get(game, {}).get(slot) for slot in range(n_slots))
            results.append(GameResult(game=game, amounts=amounts, win_cents=win(amounts)))
        return tuple(results)

    holidays = games(
        ruleset.holiday_days, ruleset.holiday_amounts, holiday_amounts, matching_pair_win
    )
    extras = games(
        range(1, ruleset.extra_games + 1),
        ruleset.extra_amounts,
        extra_amounts,
        lambda amounts: extra_game_win(amounts, ruleset.extra_rule),
    )
    return Summary(
        opened=opened,
        remaining=ruleset.boxes - opened,
        rows=tuple(rows),
        holidays=holidays,
        extras=extras,
        symbol_win_cents=sum(r.symbol.prize_cents for r in rows if r.achieved),
        holiday_win_cents=sum(g.win_cents for g in holidays),
        extra_win_cents=sum(g.win_cents for g in extras),
    )
