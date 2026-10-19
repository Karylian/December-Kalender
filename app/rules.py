"""Spelregels per kalender-editie, geladen uit JSON-bestanden in ``rules/``.

Regels zijn bewust bestanden in de repo (versiebeheer per editie) en geen
database-tabellen: een kalender verwijst naar ``Ruleset.code``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import odds

RULES_DIR = Path(os.environ.get("DK_RULES_DIR", Path(__file__).resolve().parent.parent / "rules"))


@dataclass(frozen=True)
class Symbol:
    key: str
    name: str
    emoji: str
    needed: int | None  # None = symbool zonder prijs (komt wel op het lot voor)
    prize_cents: int
    prize_label: str | None = None  # bv. "Gratis kraslot"
    odds: float | None = None  # officiële kans "1 op X" dat een lot deze symboolprijs bevat
    winning_tickets: int | None = None  # aantal loten in de oplage met deze symboolprijs
    pool_count: int | None = None  # handmatige pool-aanname, overschrijft kalibratie
    top: bool = False


@dataclass(frozen=True)
class Tier:
    """Eén regel uit het officiële prijzenschema."""

    count: int
    value_cents: int
    symbols: tuple[str, ...] = ()  # symbol keys die in deze prijs voorkomen
    free_ticket: bool = False  # gratis lot: telt niet mee in de officiële totaalwaarde


@dataclass(frozen=True)
class Ruleset:
    code: str
    name: str
    edition: int
    price_cents: int
    top_prize_cents: int
    boxes: int
    holiday_days: tuple[int, ...]
    holiday_amounts: int
    extra_games: int
    extra_amounts: int
    extra_rule: str  # "direct" (gewonnen bedrag invullen) of "match2" (2 gelijke bedragen)
    symbols: tuple[Symbol, ...]
    pool_size: int
    game_number: int | None = None
    print_run: int | None = None  # oplage
    overall_odds: float | None = None
    verified: bool = False
    notes: str = ""
    sources: tuple[dict, ...] = ()
    pool: dict[str, int] = field(default_factory=dict)
    tiers: tuple[Tier, ...] = ()
    total_prizes: int | None = None
    total_prize_value_cents: int | None = None

    @property
    def has_tiers(self) -> bool:
        return bool(self.tiers and self.print_run)

    @property
    def cash_return(self) -> float | None:
        """Verwacht uitbetaald deel van de inleg (zonder gratis loten)."""
        if not self.has_tiers:
            return None
        cash = sum(t.count * t.value_cents for t in self.tiers if not t.free_ticket)
        return cash / (self.print_run * self.price_cents)

    @property
    def free_ticket_share(self) -> float | None:
        """Kans dat een lot een gratis lot oplevert."""
        if not self.has_tiers:
            return None
        return sum(t.count for t in self.tiers if t.free_ticket) / self.print_run

    @property
    def win_chance(self) -> float | None:
        """Kans op minstens één prijs, als er per lot hoogstens één prijsregel geldt."""
        if not (self.total_prizes and self.print_run):
            return None
        return self.total_prizes / self.print_run

    @property
    def top_symbol(self) -> Symbol | None:
        tops = [s for s in self.prize_symbols if s.top]
        if tops:
            return tops[0]
        return max(self.prize_symbols, key=lambda s: s.prize_cents, default=None)

    @property
    def prize_symbols(self) -> tuple[Symbol, ...]:
        return tuple(s for s in self.symbols if s.needed)

    def symbol(self, key: str | None) -> Symbol | None:
        return next((s for s in self.symbols if s.key == key), None)


def _cents(value) -> int:
    return round(float(value) * 100)


def _symbol_odds(s: dict, print_run: int | None) -> float | None:
    if s.get("odds"):
        return float(s["odds"])
    if print_run and s.get("winning_tickets"):
        return print_run / s["winning_tickets"]
    return None


def parse_ruleset(data: dict) -> Ruleset:
    print_run = data.get("print_run")
    symbols = tuple(
        Symbol(
            key=s["key"],
            name=s["name"],
            emoji=s.get("emoji", "•"),
            needed=int(s["needed"]) if s.get("needed") else None,
            prize_cents=_cents(s.get("prize", 0)),
            prize_label=s.get("prize_label"),
            odds=_symbol_odds(s, print_run),
            winning_tickets=s.get("winning_tickets"),
            pool_count=s.get("pool_count"),
            top=bool(s.get("top", False)),
        )
        for s in data["symbols"]
    )
    boxes = int(data.get("boxes", 31))
    pool_size = int(data.get("pool_size", 31_000))
    # Het poolmodel is alleen een terugval voor regels zonder prijsregels (tiers).
    pool = {} if data.get("tiers") else {
        s.key: s.pool_count
        if s.pool_count is not None
        else odds.calibrate_pool_count(s.needed, s.odds, boxes, pool_size)
        for s in symbols
        if s.needed and (s.pool_count is not None or s.odds)
    }
    if data.get("extra_rule", "direct") not in ("direct", "match2"):
        raise ValueError(f"{data['code']}: extra_rule moet 'direct' of 'match2' zijn")
    if sum(pool.values()) > pool_size:
        raise ValueError(
            f"{data['code']}: aangenomen symbolenpool ({sum(pool.values())}) "
            f"is groter dan pool_size ({pool_size})"
        )
    tiers = tuple(
        Tier(
            count=int(t["count"]),
            value_cents=_cents(t["value"]),
            symbols=tuple(t.get("symbols", ())),
            free_ticket=bool(t.get("free_ticket", False)),
        )
        for t in data.get("tiers", ())
    )
    keys = {s.key for s in symbols}
    prize_keys = {s.key for s in symbols if s.needed}
    for t in tiers:
        not_prize = (set(t.symbols) & keys) - prize_keys
        if not_prize:
            raise ValueError(f"{data['code']}: prijsregel gebruikt symbool zonder prijs {sorted(not_prize)}")
        sym_value = sum(s.prize_cents for s in symbols if s.key in t.symbols)
        if t.value_cents < sym_value:
            raise ValueError(f"{data['code']}: prijsregel {t.symbols} is minder waard dan zijn symboolprijzen")
        unknown = set(t.symbols) - keys
        if unknown:
            raise ValueError(f"{data['code']}: prijsregel verwijst naar onbekend symbool {sorted(unknown)}")
    if tiers and data.get("total_prizes") is not None:
        if sum(t.count for t in tiers) != data["total_prizes"]:
            raise ValueError(f"{data['code']}: aantal prijzen in tiers komt niet overeen met total_prizes")
    if tiers and data.get("total_prize_value") is not None:
        cash = sum(t.count * t.value_cents for t in tiers if not t.free_ticket)
        if cash != _cents(data["total_prize_value"]):
            raise ValueError(f"{data['code']}: waarde in tiers komt niet overeen met total_prize_value")
    return Ruleset(
        code=data["code"],
        name=data["name"],
        edition=int(data["edition"]),
        price_cents=_cents(data["price"]),
        top_prize_cents=_cents(data["top_prize"]),
        boxes=boxes,
        holiday_days=tuple(data.get("holiday_days", [5, 25, 26, 31])),
        holiday_amounts=int(data.get("holiday_amounts", 4)),
        extra_games=int(data.get("extra_games", 0)),
        extra_amounts=int(data.get("extra_amounts", 1)),
        extra_rule=data.get("extra_rule", "direct"),
        symbols=symbols,
        pool_size=pool_size,
        game_number=data.get("game_number"),
        print_run=print_run,
        overall_odds=data.get("overall_odds"),
        verified=bool(data.get("verified", False)),
        notes=data.get("notes", ""),
        sources=tuple(data.get("sources", [])),
        pool=pool,
        tiers=tiers,
        total_prizes=data.get("total_prizes"),
        total_prize_value_cents=(
            _cents(data["total_prize_value"]) if data.get("total_prize_value") is not None else None
        ),
    )


def load_rulesets(directory: Path = RULES_DIR) -> dict[str, Ruleset]:
    rulesets = {}
    for path in sorted(directory.glob("*.json")):
        ruleset = parse_ruleset(json.loads(path.read_text(encoding="utf-8")))
        if ruleset.code in rulesets:
            raise ValueError(f"Dubbele ruleset-code {ruleset.code!r} in {path}")
        rulesets[ruleset.code] = ruleset
    return rulesets
