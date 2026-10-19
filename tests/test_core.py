from math import comb

import pytest

from app import odds, scoring
from app.money import format_euros, parse_euros
from app.rules import load_rulesets

from .conftest import TEST_RULES


def test_hypergeom_matches_direct_formula():
    p = odds.hypergeom_at_least(50, 10, 5, 2)
    expected = sum(comb(10, x) * comb(40, 5 - x) for x in range(2, 6)) / comb(50, 5)
    assert p == pytest.approx(expected)


@pytest.mark.parametrize("needed,odds_x", [(3, 10), (11, 1_500_000)])
def test_calibration_matches_official_odds_before_scratching(needed, odds_x):
    k = odds.calibrate_pool_count(needed, odds_x, 31, 31_000)
    p = odds.hypergeom_at_least(31_000, k, 31, needed)
    assert p >= 1 / odds_x
    assert odds.hypergeom_at_least(31_000, k - 1, 31, needed) < 1 / odds_x


def test_chance_is_exact_at_the_edges():
    kw = dict(pool_size=31_000, pool_count=500, boxes=31)
    assert odds.symbol_chance(opened=10, seen_this=3, needed=3, **kw) == 1.0
    assert odds.symbol_chance(opened=25, seen_this=0, needed=11, **kw) == 0.0
    early = odds.symbol_chance(opened=0, seen_this=0, needed=5, **kw)
    later = odds.symbol_chance(opened=10, seen_this=4, needed=5, **kw)
    assert later > early


def test_holiday_needs_two_equal_amounts():
    assert scoring.matching_pair_win([1000, 2500, 1000, 500]) == 1000
    assert scoring.matching_pair_win([1000, 2500, 500, None]) == 0
    assert scoring.matching_pair_win([None, None, None, None]) == 0


def test_summary_adds_symbols_holidays_and_extras():
    rs = load_rulesets(TEST_RULES)["test-5"]
    boxes = {1: "a", 2: "a", 3: "a", 4: "s"}
    summary = scoring.summarize(rs, boxes, {5: {0: 1000, 1: 1000}}, {1: {0: 2000}})
    assert summary.symbol_win_cents == 500
    assert summary.holiday_win_cents == 1000
    assert summary.extra_win_cents == 2000
    assert summary.total_win_cents == 3500
    rows = {r.symbol.key: r for r in summary.rows}
    assert rows["a"].achieved and rows["a"].chance == 1.0
    assert rows["x"].chance is None  # geen odds -> geen schatting
    assert summary.remaining == 27


@pytest.mark.parametrize(
    "text,cents",
    [("10", 1000), ("10,50", 1050), ("€ 1.000", 100000), ("1.000,25", 100025), ("2.5", 250), ("", None)],
)
def test_parse_euros(text, cents):
    assert parse_euros(text) == cents


def test_parse_euros_rejects_garbage():
    with pytest.raises(ValueError):
        parse_euros("tien")


def test_format_euros():
    assert format_euros(100000) == "€ 1.000,-"
    assert format_euros(1050) == "€ 10,50"
    assert format_euros(-500) == "-€ 5,-"
    assert format_euros(100025, input_value=True) == "1.000,25"


def test_official_rules_load_and_match_their_top_prize():
    rulesets = load_rulesets()
    assert {r.game_number for r in rulesets.values()} == {376, 377, 378, 400, 401, 402}
    for r in rulesets.values():
        top = r.top_symbol
        assert r.verified and top.key == "ster" and top.needed == 11
        assert top.prize_cents == r.top_prize_cents
        # Het lotmodel begint bij de officiële kans, min de al geclaimde hoofdprijzen.
        before = scoring.summarize(r, {}, {}, {})
        row = next(row for row in before.rows if row.symbol == top)
        claimed = r.top_claims.claimed if r.top_claims else 0
        assert row.chance == pytest.approx((r.top_tickets - claimed) / (r.print_run - claimed), rel=1e-9)
        assert row.chance <= 1 / top.odds * (1 + 1e-9)


def test_twenty_euro_calendar_only_pays_for_stars():
    r = load_rulesets()["dk-2026-20"]
    assert [s.key for s in r.prize_symbols] == ["ster"]
    assert r.extra_games == 15
    summary = scoring.summarize(r, {d: "boom" for d in range(1, 12)}, {}, {})
    assert summary.symbol_win_cents == 0 and summary.opened == 11


# --- statistieken en rendement -------------------------------------------------

import copy
import json

from app import stats
from app.rules import parse_ruleset


def test_wilson_interval_brackets_the_estimate():
    lo, hi = stats.wilson_interval(3, 10)
    assert lo < 0.3 < hi
    assert stats.wilson_interval(0, 10)[0] == 0.0
    assert stats.wilson_interval(10, 10)[1] == 1.0
    assert stats.wilson_interval(0, 0) is None
    # Meer waarnemingen -> smaller interval
    narrow = stats.wilson_interval(300, 1000)
    assert narrow[1] - narrow[0] < hi - lo


def test_effective_win_uses_done_total_only_when_done():
    assert scoring.effective_win_cents("active", 700, 300) == 300
    assert scoring.effective_win_cents("done", 700, 300) == 700
    assert scoring.effective_win_cents("done", None, 300) == 300


def test_official_tiers_are_consistent_with_published_totals():
    for r in load_rulesets().values():
        assert r.has_tiers and r.total_prizes == sum(t.count for t in r.tiers)
        # totaal aantal prijzen / oplage is de gepubliceerde winkans (1 op ~2)
        assert r.win_chance == pytest.approx(1 / r.overall_odds, rel=0.01)
        assert 0.5 < r.cash_return < 0.7


def test_tier_validation_rejects_mismatching_totals():
    data = json.loads((TEST_RULES / "test-5.json").read_text())
    data.update(print_run=100, tiers=[{"count": 2, "value": 5}, {"count": 1, "value": 10}],
                total_prizes=3, total_prize_value=20)
    assert parse_ruleset(copy.deepcopy(data)).cash_return == pytest.approx(20 / (100 * 5))
    for field, value in (("total_prizes", 4), ("total_prize_value", 21)):
        bad = copy.deepcopy(data) | {field: value}
        with pytest.raises(ValueError):
            parse_ruleset(bad)
    bad = copy.deepcopy(data)
    bad["tiers"][0]["symbols"] = ["bestaat-niet"]
    with pytest.raises(ValueError):
        parse_ruleset(bad)


def _ticket(ruleset, boxes, status="active", done_total=None, label="t"):
    cal = {"id": 1, "ruleset_code": ruleset.code, "status": status, "done_total_cents": done_total,
           "paid_out": 0, "label": label}
    return stats.Ticket(cal, ruleset, scoring.summarize(ruleset, boxes, {}, {}), boxes)


def test_symbol_stats_only_use_tickets_with_every_box_logged():
    rs = load_rulesets(TEST_RULES)["test-5"]
    three_apples = {d: ("a" if d <= 3 else "x") for d in range(1, 32)}
    no_apples = {d: "x" for d in range(1, 32)}
    partial = {1: "a", 2: "a", 3: "a"}
    only_total = _ticket(rs, {}, status="done", done_total=2500)
    tickets = [_ticket(rs, three_apples), _ticket(rs, no_apples), _ticket(rs, partial), only_total]
    g = stats.ruleset_stats(rs, tickets)
    assert g.full_record_tickets == 2 and g.total_boxes == 62
    apple = next(s for s in g.symbols if s.symbol.key == "a")
    assert (apple.boxes, apple.reached, apple.recorded) == (3, 1, 0.5)
    assert apple.published == pytest.approx(1 / 10, rel=0.05)
    assert apple.interval[0] < 0.5 < apple.interval[1]
    # Geld telt wél mee voor het afgeronde lot zonder symbolen
    assert g.totals.won_cents == 500 + 500 + 2500 and g.totals.calendars == 4  # twee keer drie appels
    assert g.settled_tickets == 1 and g.settled_return == pytest.approx(2500 / 500)
