import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from app import claims, scoring, ticketmodel
from app.rules import RULES_DIR, load_rulesets, parse_ruleset

SAMPLE = (Path(__file__).parent / "data" / "hoofdprijzen-sample.txt").read_text(encoding="utf-8")


def test_parse_overview_reads_date_and_rows():
    as_of, rows = claims.parse_overview(SAMPLE)
    assert as_of == date(2026, 10, 9)
    assert (rows[376].total, rows[376].claimed, rows[376].unclaimed) == (2, 1, 1)
    assert (rows[402].top_prize, rows[402].total, rows[402].claimed) == (1_000_000, 1, 0)
    assert rows[355].name == "December Kalender €10"  # 2024-editie met ander naamformaat
    assert 376 in rows and 9999 not in rows


def test_parse_overview_rejects_inconsistent_or_empty_input():
    with pytest.raises(ValueError):
        claims.parse_overview("niets bruikbaars")
    bad = SAMPLE.replace("2                  0                2", "2                  0                1", 1)
    with pytest.raises(ValueError, match="niet gelijk"):
        claims.parse_overview(bad)


def test_find_overview_url_from_product_page():
    html = '<a href="https://cdn.example/assets/abc?x=0&amp;y=0&amp;c=1" class="l"><span>Hoofdprijzen overzicht</span></a>'
    assert claims.find_overview_url(html) == "https://cdn.example/assets/abc?x=0&y=0&c=1"
    with pytest.raises(ValueError):
        claims.find_overview_url("<a href='x'>Prijzenschema</a>")


def test_update_rules_writes_claims_and_skips_mismatches(tmp_path):
    for path in RULES_DIR.glob("*.json"):
        shutil.copy(path, tmp_path / path.name)
    as_of, rows = claims.parse_overview(SAMPLE)
    rows[400] = claims.ClaimRow(400, "x", 100_000, 3, 0, 3)  # totaal wijkt af van de prijsregels
    report = claims.update_rules(tmp_path, as_of, rows, "bron")
    assert any("2025-5.json: spel 376, 1 van 2" in line for line in report)
    assert any("2026-5.json: OVERGESLAGEN" in line for line in report)
    written = json.loads((tmp_path / "2025-5.json").read_text())["top_prize_claims"]
    assert written == {"claimed": 1, "as_of": "2026-10-09", "source": "bron"}
    assert load_rulesets(tmp_path)["dk-2025-5"].top_claims.claimed == 1


def test_official_files_carry_claims_that_match_the_prize_lines():
    for r in load_rulesets().values():
        assert r.top_claims and r.top_claims.as_of
        assert 0 <= r.top_claims.claimed <= r.top_tickets
    assert load_rulesets()["dk-2025-5"].top_claims.claimed == 1


def _with_claims(code, claimed):
    data = json.loads(next(p for p in RULES_DIR.glob("*.json") if json.loads(p.read_text())["code"] == code).read_text())
    data["top_prize_claims"] = {"claimed": claimed, "as_of": "2026-10-09"}
    return parse_overview_ruleset(data)


def parse_overview_ruleset(data):
    return parse_ruleset(data)


def test_claimed_top_prizes_are_removed_from_the_pool():
    none = _with_claims("dk-2026-5", 0)
    one = _with_claims("dk-2026-5", 1)
    both = _with_claims("dk-2026-5", 2)
    p0 = ticketmodel.reach_chances(none, {})["ster"]
    p1 = ticketmodel.reach_chances(one, {})["ster"]
    p2 = ticketmodel.reach_chances(both, {})["ster"]
    n = none.print_run
    assert p0 == pytest.approx(2 / n, rel=1e-9)
    assert p1 == pytest.approx(1 / (n - 1), rel=1e-9)  # (T-c)/(N-c)
    assert p2 == 0.0
    # Met sterren al gekrast blijft het effect: een geclaimd lot telt dubbel mee
    obs = {"ster": 6}
    assert ticketmodel.reach_chances(one, obs)["ster"] < ticketmodel.reach_chances(none, obs)["ster"]
    # De andere symbolen veranderen praktisch niet
    assert ticketmodel.reach_chances(one, {})["muts"] == pytest.approx(ticketmodel.reach_chances(none, {})["muts"], rel=1e-5)


def test_claims_cannot_exceed_the_number_of_top_prizes():
    with pytest.raises(ValueError, match="geclaimde hoofdprijzen"):
        _with_claims("dk-2026-5", 3)


def test_summary_uses_the_claims(tmp_path):
    all_claimed = _with_claims("dk-2026-5", 2)
    summary = scoring.summarize(all_claimed, {1: "ster", 2: "ster"}, {}, {})
    top = next(row for row in summary.rows if row.symbol.key == "ster")
    assert top.chance == 0.0 and not summary.inconsistent
