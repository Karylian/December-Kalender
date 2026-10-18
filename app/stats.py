"""Statistieken over alle kalenders: geld per kalender/editie en symbolen uit het eigen record.

Het eigen record wordt naast de gepubliceerde kansen gezet, nooit gemengd. Alleen loten waarvan
alle vakjes zijn ingevuld tellen mee voor symboolstatistieken; loten die zijn afgerond met alleen
een totaalbedrag tellen wel mee voor de geldstatistieken.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from . import scoring
from .rules import Ruleset, Symbol


@dataclass(frozen=True)
class Ticket:
    calendar: dict
    ruleset: Ruleset
    summary: scoring.Summary
    boxes: dict[int, str]

    @property
    def done(self) -> bool:
        return self.calendar["status"] == "done"

    @property
    def win_cents(self) -> int:
        return scoring.effective_win_cents(
            self.calendar["status"], self.calendar["done_total_cents"], self.summary.total_win_cents
        )

    @property
    def spent_cents(self) -> int:
        return self.ruleset.price_cents

    @property
    def full_record(self) -> bool:
        return len(self.boxes) >= self.ruleset.boxes


@dataclass(frozen=True)
class Totals:
    calendars: int
    done: int
    paid_out: int
    spent_cents: int
    won_cents: int
    winners: int  # kalenders met een prijs > 0
    best: Ticket | None

    @property
    def net_cents(self) -> int:
        return self.won_cents - self.spent_cents

    @property
    def win_rate(self) -> float | None:
        return self.winners / self.calendars if self.calendars else None

    @property
    def return_rate(self) -> float | None:
        return self.won_cents / self.spent_cents if self.spent_cents else None


def build_tickets(calendars, rulesets, boxes_by_calendar, amounts) -> list[Ticket]:
    tickets = []
    for row in calendars:
        ruleset = rulesets.get(row["ruleset_code"])
        if ruleset is None:
            continue
        cid = row["id"]
        boxes = boxes_by_calendar.get(cid, {})
        summary = scoring.summarize(
            ruleset, boxes, amounts.get((cid, "holiday"), {}), amounts.get((cid, "extra"), {})
        )
        tickets.append(Ticket(calendar=dict(row), ruleset=ruleset, summary=summary, boxes=boxes))
    return tickets


def totals(tickets: list[Ticket]) -> Totals:
    return Totals(
        calendars=len(tickets),
        done=sum(t.done for t in tickets),
        paid_out=sum(bool(t.calendar["paid_out"]) for t in tickets),
        spent_cents=sum(t.spent_cents for t in tickets),
        won_cents=sum(t.win_cents for t in tickets),
        winners=sum(t.win_cents > 0 for t in tickets),
        best=max(tickets, key=lambda t: t.win_cents, default=None) if any(t.win_cents for t in tickets) else None,
    )


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95%-betrouwbaarheidsinterval voor een kans k/n (Wilson); None zonder waarnemingen."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True)
class SymbolStat:
    symbol: Symbol
    boxes: int
    box_share: float | None
    reached: int | None  # loten (met volledig record) die het benodigde aantal haalden
    recorded: float | None  # reached / tickets
    interval: tuple[float, float] | None
    published: float | None  # officiële kans dat een lot de prijs voor dit symbool bevat


@dataclass(frozen=True)
class RulesetStats:
    ruleset: Ruleset
    totals: Totals
    full_record_tickets: int
    total_boxes: int
    symbols: tuple[SymbolStat, ...]
    settled_tickets: int  # afgeronde loten
    settled_return: float | None  # won / spent over afgeronde loten


def ruleset_stats(ruleset: Ruleset, tickets: list[Ticket]) -> RulesetStats:
    mine = [t for t in tickets if t.ruleset.code == ruleset.code]
    full = [t for t in mine if t.full_record]
    box_counts: dict[str, int] = {}
    for t in full:
        for key in t.boxes.values():
            box_counts[key] = box_counts.get(key, 0) + 1
    total_boxes = sum(box_counts.values())

    stats = []
    for symbol in ruleset.symbols:
        boxes = box_counts.get(symbol.key, 0)
        reached = recorded = interval = published = None
        if symbol.needed:
            reached = sum(
                1 for t in full if sum(1 for k in t.boxes.values() if k == symbol.key) >= symbol.needed
            )
            recorded = reached / len(full) if full else None
            interval = wilson_interval(reached, len(full))
            if symbol.odds:  # winning_tickets / print_run, of de opgegeven officiële kans
                published = 1 / symbol.odds
        stats.append(
            SymbolStat(
                symbol=symbol,
                boxes=boxes,
                box_share=boxes / total_boxes if total_boxes else None,
                reached=reached,
                recorded=recorded,
                interval=interval,
                published=published,
            )
        )

    settled = [t for t in mine if t.done]
    spent = sum(t.spent_cents for t in settled)
    return RulesetStats(
        ruleset=ruleset,
        totals=totals(mine),
        full_record_tickets=len(full),
        total_boxes=total_boxes,
        symbols=tuple(stats),
        settled_tickets=len(settled),
        settled_return=(sum(t.win_cents for t in settled) / spent) if spent else None,
    )


def all_ruleset_stats(rulesets: dict[str, Ruleset], tickets: list[Ticket]) -> list[RulesetStats]:
    used = {t.ruleset.code for t in tickets}
    return [
        ruleset_stats(r, tickets)
        for r in sorted(rulesets.values(), key=lambda r: (-r.edition, r.price_cents))
        if r.code in used
    ]
