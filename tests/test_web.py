import re


def new_calendar(client) -> int:
    r = client.post("/kalenders", data={"ruleset_code": "test-5", "label": "Mijn lot"}, follow_redirects=False)
    assert r.status_code == 303
    return int(r.headers["location"].rsplit("/", 1)[1])


def test_requires_a_name(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/naam")
    r = client.get("/", headers={"HX-Request": "true"}, follow_redirects=False)
    assert r.headers["HX-Redirect"].startswith("/naam")


def test_pick_name_rejects_offsite_next(client):
    r = client.post("/naam", data={"new_name": "Piet", "next": "//evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/"


def test_full_flow(named):
    cid = new_calendar(named)
    page = named.get(f"/kalenders/{cid}")
    assert page.status_code == 200 and "Mijn lot" in page.text

    for day in (1, 2, 3):
        r = named.post(f"/kalenders/{cid}/dag/{day}", data={"symbol": "a"})
        assert r.status_code == 200
    assert "28 vakjes nog te krassen" in r.text
    assert "behaald" in r.text

    r = named.post(f"/kalenders/{cid}/feestdag/5", data={"a0": "10", "a1": "25", "a2": "10", "a3": ""})
    assert "Gewonnen: € 10,-" in r.text

    r = named.post(f"/kalenders/{cid}/extra/1", data={"a0": "20"})
    # gratis lot (€5) + feestdag €10 + extra €20
    assert "€ 35,-" in r.text

    r = named.post(f"/kalenders/{cid}/feestdag/5", data={"a0": "tien"})
    assert "Ongeldig bedrag" in r.text

    r = named.post(f"/kalenders/{cid}/dag/1", data={"symbol": "s"})
    assert "Dag 1: 🍎 Appel → ⭐ Ster" in r.text
    assert "Sanne" in r.text

    assert named.post(f"/kalenders/{cid}/dag/1", data={"symbol": "zzz"}).status_code == 400
    assert named.post(f"/kalenders/{cid}/dag/32", data={"symbol": "a"}).status_code == 404
    assert named.post(f"/kalenders/{cid}/feestdag/6", data={"a0": "1"}).status_code == 404


def test_version_check_detects_other_users(client, tmp_path):
    client.post("/naam", data={"new_name": "A"})
    cid = new_calendar(client)
    version = int(re.search(r'id="cal-version" name="v" value="(\d+)"', client.get(f"/kalenders/{cid}").text).group(1))
    assert "Vernieuwen" not in client.get(f"/kalenders/{cid}/versie", params={"v": version}).text
    client.post(f"/kalenders/{cid}/dag/7", data={"symbol": "b"})
    assert "Vernieuwen" in client.get(f"/kalenders/{cid}/versie", params={"v": version}).text


def test_reset_clear_log_and_delete(named):
    cid = new_calendar(named)
    named.post(f"/kalenders/{cid}/dag/4", data={"symbol": "a"})
    r = named.post(f"/kalenders/{cid}/reset")
    assert "31 vakjes nog te krassen" in r.text and "gereset" in r.text
    r = named.post(f"/kalenders/{cid}/log/wissen")
    assert "Logboek gewist" in r.text and "gereset" not in r.text
    r = named.post(f"/kalenders/{cid}/verwijderen")
    assert r.headers["HX-Redirect"] == "/"
    assert named.get(f"/kalenders/{cid}").status_code == 404


def test_overview_and_export(named):
    cid = new_calendar(named)
    named.post(f"/kalenders/{cid}/dag/1", data={"symbol": "a"})
    assert "Mijn lot" in named.get("/").text
    assert "Testkalender" in named.get("/regels").text
    data = named.get("/export.json").json()
    assert data["boxes"][0]["symbol_key"] == "a"


def test_finish_locks_the_calendar_and_counts_money_only(named):
    cid = new_calendar(named)
    named.post(f"/kalenders/{cid}/dag/1", data={"symbol": "a"})
    assert "Kalender afronden" in named.get(f"/kalenders/{cid}/afronden").text

    bad = named.post(f"/kalenders/{cid}/afronden", data={"total": "veel"})
    assert "Ongeldig bedrag" in bad.text

    done = named.post(f"/kalenders/{cid}/afronden", data={"total": "12,50"})
    assert done.status_code == 204 and done.headers["HX-Redirect"] == f"/kalenders/{cid}"
    page = named.get(f"/kalenders/{cid}").text
    assert "Afgerond" in page and "€ 12,50" in page and "Heropenen" in page

    # alleen-lezen: vakjes, spellen en reset worden geweigerd
    assert "afgerond" in named.post(f"/kalenders/{cid}/dag/2", data={"symbol": "a"}).text
    assert "afgerond" in named.post(f"/kalenders/{cid}/feestdag/5", data={"a0": "5"}).text
    assert "afgerond" in named.post(f"/kalenders/{cid}/reset").text
    assert named.get("/export.json").json()["boxes"] == [
        b for b in named.get("/export.json").json()["boxes"] if b["day"] == 1
    ]

    overview = named.get("/").text
    assert "€ 12,50" in overview and "alleen totaal" in overview  # afgerond, niet alle vakjes ingevuld
    assert "afgerond" in named.get("/", params={"status": "done"}).text
    assert "Mijn lot" not in named.get("/", params={"status": "active"}).text

    named.post(f"/kalenders/{cid}/heropenen")
    assert "Afronden" in named.get(f"/kalenders/{cid}").text
    assert "gekrast" in named.post(f"/kalenders/{cid}/dag/2", data={"symbol": "a"}).text


def test_serial_number_warning_and_search(named):
    first = new_calendar(named)
    second = new_calendar(named)
    named.post(f"/kalenders/{first}/serienummer", data={"serial": "AB-1234"})
    r = named.post(f"/kalenders/{second}/serienummer", data={"serial": "ab-1234"})
    assert "staat al bij" in r.text and "Serienummer: ab-1234" in r.text
    assert "staat al bij" in named.get(f"/kalenders/{second}").text
    assert "staat al bij" not in named.post(f"/kalenders/{second}/serienummer", data={"serial": "ZZ-9"}).text
    assert "AB-1234" in named.get("/", params={"q": "1234"}).text
    assert "ZZ-9" not in named.get("/", params={"q": "1234"}).text
    assert "Geen kalenders gevonden" in named.get("/", params={"q": "%"}).text


def test_statistics_page(named):
    assert "Nog geen kalenders" in named.get("/statistieken").text
    cid = new_calendar(named)
    for day in range(1, 32):
        named.post(f"/kalenders/{cid}/dag/{day}", data={"symbol": "a" if day <= 3 else "x"})
    named.post(f"/kalenders/{cid}/afronden", data={"total": "5"})
    page = named.get("/statistieken").text
    assert "Testkalender" in page and "1 kalender(s)" in page
    assert "1 van 1" in page  # appels: 1 van 1 volledige kalender haalde de prijs
    assert "te weinig" in page


def test_impossible_symbol_combinations_are_flagged_with_the_official_rules(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(db_path=tmp_path / "real.db")) as c:  # de echte regels in rules/
        c.post("/naam", data={"new_name": "Sanne"})
        r = c.post("/kalenders", data={"ruleset_code": "dk-2026-5"}, follow_redirects=False)
        cid = int(r.headers["location"].rsplit("/", 1)[1])
        for day in (1, 2, 3):
            ok = c.post(f"/kalenders/{cid}/dag/{day}", data={"symbol": "ster"})
        assert "komt in geen enkel lot" not in ok.text
        top = ok.text[ok.text.index("Kans op hoofdprijs"):][:400]
        assert "1 op" in top or "%" in top  # drie sterren: nog gewoon een kans

        for day in range(4, 14):  # 13 sterren: meer dan de 11 die bestaan
            bad = c.post(f"/kalenders/{cid}/dag/{day}", data={"symbol": "ster"})
        assert "komt in geen enkel lot" in bad.text
        assert "—" in bad.text[bad.text.index("Kans op hoofdprijs"):][:400]
