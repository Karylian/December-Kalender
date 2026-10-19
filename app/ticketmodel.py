"""Kansmodel op loot-niveau, gebaseerd op het officiële prijzenschema.

Elk lot hoort bij precies één *klasse*: de verzameling symbolen die hun drempel halen (bijvoorbeeld
{4× Muts, 5× Sneeuwpop}), of de lege klasse (geen enkel symbool haalt zijn drempel; hierin zitten
ook de loten die alleen via de spellen winnen). Het aantal loten per klasse volgt uit de prijsregels
en de oplage, dus de beginkans per symbool is precies de gepubliceerde kans.

Aannames (het schema geeft geen indeling van de vakjes):
  * een symbool dat zijn drempel haalt, staat er precies zo vaak op als de drempel;
  * alle andere symbolen blijven onder hun eigen drempel;
  * binnen die grenzen zijn de vakjes willekeurig verdeeld en liggen de symbolen in willekeurige
    volgorde over de dagen.

Na het krassen van ``k`` vakjes weegt elke klasse mee naar hoe waarschijnlijk de waarneming daarin
is (Bayes). De kans dat een symbool zijn prijs haalt is dan de gezamenlijke kans van de klassen
waarin het symbool voorkomt. Zo tellen combinaties van meerdere symbolen mee, en het feit dat ze
samen maar 31 vakjes delen.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import comb, factorial

from .rules import Ruleset


@dataclass(frozen=True)
class TicketClass:
    required: tuple[tuple[str, int], ...]  # (symbool, aantal) dat precies zo vaak voorkomt
    tickets: int  # aantal loten in de oplage met deze klasse


def build_classes(ruleset: Ruleset) -> list[TicketClass]:
    """Klassen uit de prijsregels; de lege klasse krijgt de rest van de oplage.

    Al geclaimde hoofdprijzen worden uit de oplage gehaald: een geclaimd lot is al gekrast door
    iemand anders, dus jouw lot kan het niet zijn."""
    if not ruleset.has_tiers:
        raise ValueError(f"{ruleset.code} heeft geen prijsregels (tiers)")
    needed = {s.key: s.needed for s in ruleset.symbols}
    by_set: dict[frozenset[str], int] = {}
    for tier in ruleset.tiers:
        if tier.symbols:
            key = frozenset(tier.symbols)
            by_set[key] = by_set.get(key, 0) + tier.count

    claimed = ruleset.top_claims.claimed if ruleset.top_claims else 0
    removed_from_empty = 0
    if claimed:
        for tier in ruleset.tiers:
            if tier.value_cents != ruleset.top_prize_cents or not claimed:
                continue
            take = min(claimed, tier.count)
            claimed -= take
            if tier.symbols:
                by_set[frozenset(tier.symbols)] -= take
            else:
                removed_from_empty += take

    classes = []
    for keys, count in by_set.items():
        required = tuple(sorted((k, needed[k]) for k in keys))
        if sum(n for _, n in required) > ruleset.boxes:
            raise ValueError(f"{ruleset.code}: {sorted(keys)} heeft meer vakjes nodig dan er zijn")
        classes.append(TicketClass(required, count))
    symbol_tickets = sum(t.count for t in ruleset.tiers if t.symbols)
    rest = ruleset.print_run - symbol_tickets - removed_from_empty
    if rest < 0:
        raise ValueError(f"{ruleset.code}: meer prijsloten dan de oplage")
    classes.append(TicketClass((), rest))
    return classes


def _multiply(a: list[float], b: list[float], degree: int) -> list[float]:
    out = [0.0] * (degree + 1)
    for i, x in enumerate(a):
        if x:
            for j, y in enumerate(b):
                if i + j > degree:
                    break
                out[i + j] += x * y
    return out


def _class_likelihood(ruleset: Ruleset, cls: TicketClass, observed: Mapping[str, int]) -> float:
    """Waarschijnlijkheid van de waarneming in deze klasse, tot op een factor die voor alle klassen gelijk is."""
    required = dict(cls.required)
    free = ruleset.boxes - sum(required.values())
    factor = 1.0
    for key, n in required.items():
        factor *= comb(n, observed.get(key, 0))
    if factor == 0.0:
        return 0.0

    numerator = [1.0] + [0.0] * free  # polynoom in x; coëfficiënt van x^n = gewicht van n vakjes
    denominator = [1.0] + [0.0] * free
    for symbol in ruleset.symbols:
        if symbol.key in required:
            continue
        cap = free if not symbol.needed else min(free, symbol.needed - 1)
        o = observed.get(symbol.key, 0)
        weights = [1.0 / factorial(n) for n in range(cap + 1)]
        with_obs = [w * comb(n, o) for n, w in enumerate(weights)]
        numerator = _multiply(numerator, with_obs, free)
        denominator = _multiply(denominator, weights, free)
    if denominator[free] == 0.0:
        return 0.0  # deze klasse past niet binnen de grenzen (zou niet moeten kunnen)
    return factor * numerator[free] / denominator[free]


def reach_chances(ruleset: Ruleset, observed: Mapping[str, int]) -> dict[str, float] | None:
    """Kans per prijssymbool dat dit lot de prijs voor dat symbool haalt, gegeven de gekraste vakjes.

    ``observed``: symboolsleutel -> aantal keer gevonden. ``None`` als de waarneming in geen enkele
    klasse kan voorkomen (bijvoorbeeld door een invoerfout)."""
    classes = build_classes(ruleset)
    weights = [c.tickets * _class_likelihood(ruleset, c, observed) for c in classes]
    total = sum(weights)
    if total <= 0.0:
        return None
    chances = {s.key: 0.0 for s in ruleset.prize_symbols}
    for cls, weight in zip(classes, weights):
        for key, _ in cls.required:
            chances[key] += weight / total
    return chances
