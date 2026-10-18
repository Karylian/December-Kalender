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
