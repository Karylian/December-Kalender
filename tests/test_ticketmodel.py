import itertools
from collections import Counter

import pytest

from app import ticketmodel
from app.rules import load_rulesets, parse_ruleset

TINY = {
    "code": "tiny", "name": "Tiny", "edition": 2026, "price": 5, "top_prize": 100,
    "boxes": 6, "print_run": 1000,
    "symbols": [
        {"key": "a", "name": "A", "needed": 3, "prize": 5},
        {"key": "b", "name": "B", "needed": 2, "prize": 10},
        {"key": "c", "name": "C"},
    ],
    "tiers": [
        {"count": 40, "value": 5, "symbols": ["a"]},
        {"count": 60, "value": 10, "symbols": ["b"]},
        {"count": 10, "value": 20, "symbols": ["a", "b"]},
    ],
}


def brute_force(ruleset, prefix):
    """Elke volgorde van symbolen over de vakjes is even waarschijnlijk binnen een klasse."""
    keys = [s.key for s in ruleset.symbols]
    needed = {s.key: s.needed for s in ruleset.symbols}
    chances = {s.key: 0.0 for s in ruleset.prize_symbols}
    total = 0.0
    for cls in ticketmodel.build_classes(ruleset):
        required = dict(cls.required)
        valid = 0
        matching = 0
        for seq in itertools.product(keys, repeat=ruleset.boxes):
            counts = Counter(seq)
            ok = all(counts[k] == n for k, n in required.items()) and all(
                counts[k] < needed[k] for k in keys if k not in required and needed[k]
            )
            if ok:
                valid += 1
                matching += seq[: len(prefix)] == tuple(prefix)
        weight = cls.tickets * matching / valid
        total += weight
        for key in required:
            chances[key] += weight
    return {k: v / total for k, v in chances.items()}


@pytest.mark.parametrize("prefix", [[], ["c"], ["a", "a"], ["b", "c", "c"], ["a", "b", "a", "c"], ["c", "c", "c", "c"]])
def test_matches_brute_force_enumeration(prefix):
    ruleset = parse_ruleset(TINY)
    got = ticketmodel.reach_chances(ruleset, Counter(prefix))
    expected = brute_force(ruleset, prefix)
    assert got.keys() == expected.keys()
    for key in got:
        assert got[key] == pytest.approx(expected[key], rel=1e-9)


def test_starts_at_the_published_odds_for_every_official_calendar():
    """Zonder geclaimde hoofdprijzen is de beginkans exact de gepubliceerde kans; anders alleen de top lager."""
    for ruleset in load_rulesets().values():
        start = ticketmodel.reach_chances(ruleset, {})
        claimed = ruleset.top_claims.claimed if ruleset.top_claims else 0
        top = ruleset.top_symbol
        for symbol in ruleset.prize_symbols:
            published = 1 / symbol.odds
            if symbol is top and claimed:
                expected = (ruleset.top_tickets - claimed) / (ruleset.print_run - claimed)
                assert start[symbol.key] == pytest.approx(expected, rel=1e-9)
            else:
                assert start[symbol.key] == pytest.approx(published, rel=1e-5 if claimed else 1e-9)


def test_combinations_share_the_boxes():
    """Vijf sterren maken de top veel waarschijnlijker en de andere prijzen minder (de vakjes zijn bezet)."""
    ruleset = load_rulesets()["dk-2026-5"]
    start = ticketmodel.reach_chances(ruleset, {})
    after_stars = ticketmodel.reach_chances(ruleset, {"ster": 5})
    assert after_stars["ster"] > start["ster"] * 10
    assert all(after_stars[k] < start[k] for k in start if k != "ster")
    assert ticketmodel.reach_chances(ruleset, {"ster": 12}) is None  # onmogelijke waarneming


def test_reached_symbols_are_certain_and_others_follow_from_the_schedule():
    ruleset = load_rulesets()["dk-2026-5"]
    chances = ticketmodel.reach_chances(ruleset, {"muts": 4})
    assert chances["muts"] == pytest.approx(1.0)
    assert chances["kerstman"] == 0.0  # het schema heeft geen lot met gratis lot én 4× Muts
    assert chances["sneeuwpop"] > 0  # wel met 5× Sneeuwpop erbij
    # Een combinatie die niet in het prijzenschema staat kan niet kloppen
    assert ticketmodel.reach_chances(ruleset, {"muts": 4, "kerstman": 3}) is None
    # Er blijft nog ruimte voor een ster-lot zolang er genoeg vakjes over zijn, anders niet meer
    full = {"kerstman": 2, "muts": 3, "sneeuwpop": 4, "slee": 5, "kaars": 6, "schaats": 7, "want": 4}
    assert sum(full.values()) == 31
    assert ticketmodel.reach_chances(ruleset, full)["ster"] == 0.0
