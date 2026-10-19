import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from app import rules, updater
from app.update import main as update_main, render

from .fake_source import DATA, FakeSource

TODAY = date(2026, 10, 19)
FILES = {"376": "2025-5", "377": "2025-10", "378": "2025-20", "400": "2026-5", "401": "2026-10", "402": "2026-20"}


def scheme(game):
    return (DATA / f"scheme-{game}.txt").read_text(encoding="utf-8")


def rules_without(tmp_path, *drop):
    """Kopie van de echte regels zonder de genoemde bestanden."""
    target = tmp_path / "rules"
    target.mkdir()
    for path in rules.RULES_DIR.glob("*.json"):
        if path.stem not in drop:
            shutil.copy(path, target / path.name)
    return target


# --- schema lezen: de parser moet de met de hand overgenomen regels exact reproduceren --------------

@pytest.mark.parametrize("game,name", FILES.items())
def test_parser_reproduces_the_hand_transcribed_prize_lines(game, name):
    parsed = updater.parse_scheme(scheme(game))
    ref = json.loads((rules.RULES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert parsed.problems == []
    got = sorted((t.count, t.value_cents, tuple(sorted(updater.normalize_name(n) for n, _ in t.symbols)), t.free_ticket) for t in parsed.tiers)
    expected = sorted((t["count"], round(t["value"] * 100), tuple(sorted(t.get("symbols", []))), bool(t.get("free_ticket"))) for t in ref["tiers"])
    assert got == expected
    assert (parsed.game, parsed.price, parsed.print_run, parsed.total_prizes) == (
        ref["game_number"], ref["price"], ref["print_run"], ref["total_prizes"])
    assert (parsed.holiday_days, parsed.holiday_amounts, parsed.extra_games) == (
        ref["holiday_days"], ref["holiday_amounts"], ref["extra_games"])
    assert updater.edition_from(parsed) == ref["edition"]


def test_parser_rejects_text_that_is_not_a_prize_scheme():
    with pytest.raises(updater.UpdateError):
        updater.parse_scheme("Dit is geen prijzenschema")


def test_parser_flags_a_row_whose_amounts_do_not_add_up():
    import re

    broken = re.sub(r"(€ 5 \(4 x MUTS\) \+ € )5(?=\s)", r"\g<1>7", scheme("400"), count=1)
    assert broken != scheme("400")
    assert any("tellen op" in p for p in updater.parse_scheme(broken).problems)


def test_series_discovery_and_links():
    entries = updater.discover((DATA / "series.html").read_text(encoding="utf-8"))
    assert [(e.game, e.price) for e in entries] == [(354, 5), (355, 10), (356, 20), (376, 5), (377, 10), (378, 20), (400, 5), (401, 10), (402, 20)]
    html = '<a href="https://x/assets/a?x=0&amp;y=1"><span>Prijzenschema</span></a>'
    assert updater.find_link(html, "Prijzenschema") == "https://x/assets/a?x=0&y=1"
    with pytest.raises(updater.UpdateError):
        updater.find_link(html, "Hoofdprijzen overzicht")


def test_live_source_refuses_foreign_hosts():
    source = updater.LiveSource()
    for url in ("https://evil.example/x.pdf", "http://krasloten.nederlandseloterij.nl/x", "https://nederlandseloterij.nl.evil.example/x"):
        with pytest.raises(updater.UpdateError, match="niet toegestaan"):
            source._get(url)


# --- controleren -------------------------------------------------------------------------------------------

def test_everything_installed_means_nothing_to_do():
    proposal = updater.check_for_updates(FakeSource(), rules.load_all(update_dir=Path("/nonexistent")), today=TODAY)
    assert proposal.editions == [] and proposal.claims == [] and proposal.errors == []
    assert [o["game"] for o in proposal.older] == [354, 355, 356]
    assert not proposal.has_changes


def test_a_missing_edition_is_rebuilt_exactly_like_the_hand_made_rules(tmp_path):
    installed = rules.load_rulesets(rules_without(tmp_path, "2026-5", "2026-10", "2026-20"))
    proposal = updater.check_for_updates(FakeSource(), installed, today=TODAY)
    assert [e.game for e in proposal.editions] == [400, 401, 402]
    for edition in proposal.editions:
        assert edition.ok, [c for c in edition.checks if not c.ok] + edition.problems
        ref = json.loads((rules.RULES_DIR / f"2026-{edition.price}.json").read_text(encoding="utf-8"))
        got = edition.ruleset
        for key in ("code", "name", "edition", "game_number", "price", "top_prize", "print_run", "overall_odds",
                    "holiday_days", "holiday_amounts", "extra_games", "total_prizes", "total_prize_value", "tiers", "symbols", "verified"):
            assert got[key] == ref[key], key
    # symbolen zonder prijs staan niet in het schema: overgenomen van vorig jaar, met een waarschuwing
    twenty = next(e for e in proposal.editions if e.price == 20)
    assert any("zijn overgenomen" in n for n in twenty.notes)


def test_a_scheme_that_fails_the_checks_is_not_applicable(tmp_path):
    installed = rules.load_rulesets(rules_without(tmp_path, "2026-5"))
    bad = scheme("400").replace("380.000", "381.000", 1)  # één aantal verkeerd overgenomen
    proposal = updater.check_for_updates(FakeSource(schemes={"400": bad}), installed, today=TODAY)
    (edition,) = proposal.editions
    assert not edition.ok and any(not c.ok for c in edition.checks)
    assert updater.apply_proposal(proposal, tmp_path / "upd")[0].startswith("Overgeslagen")
    assert not (tmp_path / "upd" / "rules").exists()


def test_network_errors_become_messages_not_crashes():
    proposal = updater.check_for_updates(FakeSource(fail_series=True), {}, today=TODAY)
    assert proposal.errors and "timed out" in proposal.errors[0] and not proposal.has_changes


def test_new_claim_counts_are_proposed_and_applied(tmp_path):
    newer = (DATA / "overview-2026-10-09.txt").read_text().replace("09-10-2026", "20-11-2026")
    newer = newer.replace("400                   €5 DECEMBER KALENDER                                         € 5,00     01-11-2028           € 100.000                2                  0                2",
                          "400                   €5 DECEMBER KALENDER                                         € 5,00     01-11-2028           € 100.000                2                  1                1")
    (tmp_path / "newer.txt").write_text(newer, encoding="utf-8")
    source = FakeSource(overview="overview-2026-10-09.txt")
    source.overview = "../" + (tmp_path / "newer.txt").name  # niet gebruikt; zie hieronder
    fake = FakeSource()
    original = fake.pdf_text
    fake.pdf_text = lambda url: newer if url.endswith("overview?x=0&y=0") else original(url)
    installed = rules.load_all(update_dir=Path("/nonexistent"))
    proposal = updater.check_for_updates(fake, installed, today=TODAY)
    assert proposal.claims_as_of == "2026-11-20"
    changes = {c.game: (c.old, c.new) for c in proposal.claims}
    assert changes[400] == (0, 1)
    updater.apply_proposal(proposal, tmp_path / "upd")
    after = rules.load_all(update_dir=tmp_path / "upd")
    assert after["dk-2026-5"].top_claims.claimed == 1 and after["dk-2026-5"].top_claims.as_of == "2026-11-20"
    # een tweede controle ziet geen verschil meer
    again = updater.check_for_updates(fake, after, today=TODAY)
    assert again.claims == []


def test_applied_edition_is_loaded_next_time_and_repository_files_win(tmp_path):
    installed = rules.load_rulesets(rules_without(tmp_path, "2026-5"))
    proposal = updater.check_for_updates(FakeSource(), installed, today=TODAY)
    updater.apply_proposal(proposal, tmp_path / "upd")
    loaded = rules.load_all(tmp_path / "rules", tmp_path / "upd")
    assert "dk-2026-5" in loaded and loaded["dk-2026-5"].game_number == 400 and loaded["dk-2026-5"].has_tiers
    # dezelfde code in de repository gaat voor op een eerder gedownload bestand
    shutil.copy(rules.RULES_DIR / "2026-5.json", tmp_path / "rules" / "2026-5.json")
    assert rules.load_all(tmp_path / "rules", tmp_path / "upd")["dk-2026-5"].notes == rules.load_rulesets()["dk-2026-5"].notes
    # een kapot bestand in de update-map blokkeert niets
    (tmp_path / "upd" / "rules" / "kapot.json").write_text("{niet json", encoding="utf-8")
    assert "dk-2026-5" in rules.load_all(tmp_path / "rules", tmp_path / "upd")


def test_proposal_survives_json_roundtrip(tmp_path):
    installed = rules.load_rulesets(rules_without(tmp_path, "2026-20"))
    proposal = updater.check_for_updates(FakeSource(), installed, today=TODAY)
    again = updater.Proposal.from_json(proposal.to_json())
    assert again == proposal and again.editions[0].checks[0].label


def test_cli_prints_the_proposal_and_applies_after_confirmation(tmp_path, capsys, monkeypatch):
    rules_dir = rules_without(tmp_path, "2026-10")
    args = ["--rules-dir", str(rules_dir), "--update-dir", str(tmp_path / "upd")]
    assert update_main(args, source=FakeSource()) == 0
    out = capsys.readouterr().out
    assert "Nieuwe editie: December Kalender €10 (2026), spel 401" in out and "Kan worden toegepast" in out
    assert not (tmp_path / "upd").exists()
    monkeypatch.setattr("builtins.input", lambda _: "n")
    update_main(args + ["--apply"], source=FakeSource())
    assert not (tmp_path / "upd").exists()
    update_main(args + ["--apply", "--yes"], source=FakeSource())
    assert (tmp_path / "upd" / "rules" / "dk-2026-10.json").exists()
    assert "Nieuwe editie toegevoegd" in capsys.readouterr().out
    assert render(updater.check_for_updates(FakeSource(), rules.load_all(rules_dir, tmp_path / "upd"), today=TODAY)).endswith("Alles is up-to-date.")


# --- webpagina ------------------------------------------------------------------------------------------------

def make_client(tmp_path, *drop, source=None):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(
        db_path=tmp_path / "w.db", rules_dir=rules_without(tmp_path, *drop),
        update_dir=tmp_path / "upd", update_source=source or FakeSource(),
    )
    client = TestClient(app)
    client.post("/naam", data={"new_name": "Sanne"})
    return client


def test_updates_page_check_preview_apply(tmp_path):
    with make_client(tmp_path, "2026-5", "2026-10") as c:
        assert "Controleer op updates" in c.get("/updates").text
        assert "Er staat een update klaar" not in c.get("/").text

        r = c.post("/updates/controleren", follow_redirects=False)
        assert r.status_code == 303
        page = c.get("/updates").text
        assert "Nieuwe editie: December Kalender €5 (2026), spel 400" in page and "controles gehaald" in page
        assert "Nieuwe editie: December Kalender €10 (2026), spel 401" in page
        assert "Gratis kraslot" in page and "Toepassen" in page
        assert "Er staat een update klaar" in c.get("/").text          # banner op het overzicht
        assert "December Kalender €5 (2026)" not in c.get("/regels").text  # nog niets toegepast

        # snel opnieuw controleren wordt afgeremd
        assert "gedaan=wacht" in c.post("/updates/controleren", follow_redirects=False).headers["location"]

        proposal_id = int(__import__("re").search(r"/updates/(\d+)/toepassen", page)[1])
        done = c.post(f"/updates/{proposal_id}/toepassen", follow_redirects=False)
        assert done.headers["location"].endswith("gedaan=toegepast")
        # zonder herstart: nieuwe regels, nieuwe kansen en nieuwe keuze bij het toevoegen van een kalender
        assert "December Kalender €5 (2026)" in c.get("/regels").text
        overview = c.get("/").text
        assert "dk-2026-5" in overview and "Er staat een update klaar" not in overview
        cal = c.post("/kalenders", data={"ruleset_code": "dk-2026-5"}, follow_redirects=False)
        calendar = c.get(cal.headers["location"]).text
        assert "Kans op hoofdprijs" in " ".join(calendar.split())
        assert "0 van 2 hoofdprijzen al geclaimd (stand 2026-10-09)" in " ".join(calendar.replace("<br>", " ").split())
        # dezelfde beslissing nogmaals nemen kan niet
        assert "gedaan=beslist" in c.post(f"/updates/{proposal_id}/toepassen", follow_redirects=False).headers["location"]
        assert (tmp_path / "upd" / "rules" / "dk-2026-5.json").exists()


def test_updates_page_dismiss_and_errors(tmp_path):
    with make_client(tmp_path, "2026-20", source=FakeSource(fail_series=True)) as c:
        c.post("/updates/controleren")
        page = c.get("/updates").text
        assert "timed out" in page and "Toepassen" not in page
    (tmp_path / "second").mkdir()
    with make_client(tmp_path / "second", "2026-20") as c:
        c.post("/updates/controleren")
        row_id = int(__import__("re").search(r"/updates/(\d+)/negeren", c.get("/updates").text)[1])
        assert c.post(f"/updates/{row_id}/negeren", follow_redirects=False).headers["location"].endswith("gedaan=genegeerd")
        assert "Er staat een update klaar" not in c.get("/").text
        assert not (tmp_path / "second" / "upd").exists()
