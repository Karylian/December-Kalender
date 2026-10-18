"""Hypergeometrische kansschatting voor de symbolen op een kalender.

Model (een *aanname*, geen officiële rekenmethode): de 31 vakjes zijn een
trekking zonder teruglegging uit een pool van ``pool_size`` symbolen, waarvan
``pool_count`` van het betreffende symbool. Na het openkrassen van ``k``
vakjes is de resterende pool ``pool_size - k`` en worden er nog ``boxes - k``
getrokken.

Officiële prijzenschema's geven alleen kansen per prijs over de hele oplage.
``calibrate_pool_count`` kiest de pool zo dat de kans *vooraf* (0 vakjes open)
gelijk is aan die officiële kans, zodat de schatting in elk geval daarmee
in lijn begint.
"""

from __future__ import annotations

from fractions import Fraction
from math import comb


def hypergeom_at_least(population: int, successes: int, draws: int, minimum: int) -> float:
    """P(X >= minimum) voor X ~ Hypergeometrisch(population, successes, draws)."""
    if minimum <= 0:
        return 1.0
    if draws <= 0 or successes <= 0 or minimum > min(successes, draws):
        return 0.0
    total = comb(population, draws)
    hits = sum(
        comb(successes, x) * comb(population - successes, draws - x)
        for x in range(minimum, min(successes, draws) + 1)
    )
    return float(Fraction(hits, total))


def calibrate_pool_count(needed: int, odds: float | None, boxes: int, pool_size: int) -> int:
    """Kleinste aantal K in de pool waarvoor P(>= needed in boxes trekkingen) >= 1/odds."""
    if not odds:
        return 0
    target = 1.0 / odds
    lo, hi = 0, pool_size
    while lo < hi:
        mid = (lo + hi) // 2
        if hypergeom_at_least(pool_size, mid, boxes, needed) >= target:
            hi = mid
        else:
            lo = mid + 1
    return lo


def symbol_chance(
    *,
    pool_size: int,
    pool_count: int,
    boxes: int,
    opened: int,
    seen_this: int,
    needed: int,
) -> float:
    """Geschatte kans dat dit symbool aan het eind ``needed`` keer is gevonden."""
    if seen_this >= needed:
        return 1.0
    remaining_boxes = boxes - opened
    if needed - seen_this > remaining_boxes:
        return 0.0
    return hypergeom_at_least(
        population=max(pool_size - opened, 0),
        successes=max(pool_count - seen_this, 0),
        draws=remaining_boxes,
        minimum=needed - seen_this,
    )
