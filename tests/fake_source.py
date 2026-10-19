"""Nep-bron voor de update-tests: dezelfde pagina's en pdf-teksten als de loterij, zonder netwerk."""

from pathlib import Path

from app.updater import UpdateError

DATA = Path(__file__).parent / "data"
CDN = "https://nlo-krasloten-web-cdn.azureedge.net/assets/"


class FakeSource:
    def __init__(self, fail_series=False, schemes=None, overview="overview-2026-10-09.txt"):
        self.fail_series = fail_series
        self.schemes = schemes or {}
        self.overview = overview
        self.requests = []

    def series_html(self):
        self.requests.append("series")
        if self.fail_series:
            raise UpdateError("Ophalen mislukt (krasloten.nederlandseloterij.nl): timed out")
        return (DATA / "series.html").read_text(encoding="utf-8")

    def product_html(self, price, game):
        self.requests.append(f"product-{game}")
        return (
            f'<a href="{CDN}scheme-{game}?x=0&amp;y=0"><span>Prijzenschema</span></a>'
            f'<a href="{CDN}overview?x=0&amp;y=0"><span>Hoofdprijzen overzicht</span></a>'
        )

    def pdf_text(self, url):
        self.requests.append(url)
        name = url.removeprefix(CDN).split("?")[0]
        if name == "overview":
            return (DATA / self.overview).read_text(encoding="utf-8")
        game = name.removeprefix("scheme-")
        if game in self.schemes:
            return self.schemes[game]
        path = DATA / f"scheme-{game}.txt"
        if not path.exists():
            raise UpdateError(f"Geen prijzenschema voor spel {game}")
        return path.read_text(encoding="utf-8")
