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
