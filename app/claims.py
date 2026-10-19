"""Geclaimde hoofdprijzen uit het hoofdprijzenoverzicht van de Nederlandse Loterij.

Het overzicht is een pdf die periodiek wordt bijgewerkt. Dit script leest hem uit (met
``pdftotext`` van poppler), controleert de aantallen tegen de prijsregels in ``rules/`` en schrijft
``top_prize_claims`` in de bijbehorende regelbestanden. Daarna de app herstarten.

    python -m app.claims                 # haalt het overzicht op via de productpagina
    python -m app.claims --pdf bestand.pdf
    python -m app.claims --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import rules

PAGE_URL = "https://krasloten.nederlandseloterij.nl/krasloten/december-kalender-{slug}"
SOURCE = "https://krasloten.nederlandseloterij.nl/hoofdprijzen"  # de pdf-link zelf verloopt bij elke update
USER_AGENT = "Mozilla/5.0"

_AS_OF = re.compile(r"bijgewerkt t/m\s+(\d{2})-(\d{2})-(\d{4})")
# spelnummer  naam ... prijs  geldig-tot  hoofdprijs  totaal  geclaimd  niet-geclaimd
_ROW = re.compile(r"^\s*(\d{3})\s+(.+?)\s+€\s*[\d.,]+\s+\d{2}-\d{2}-\d{4}\s+€\s*([\d.]+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$")


@dataclass(frozen=True)
class ClaimRow:
    game: int
    name: str
    top_prize: int  # euro
    total: int
    claimed: int
    unclaimed: int


def parse_overview(text: str) -> tuple[date, dict[int, ClaimRow]]:
    """Leest de tekst van het overzicht; geeft de peildatum en de rijen per spelnummer."""
    match = _AS_OF.search(text)
    if not match:
        raise ValueError("Peildatum ('bijgewerkt t/m') niet gevonden in het overzicht")
    as_of = date(int(match[3]), int(match[2]), int(match[1]))
    rows: dict[int, ClaimRow] = {}
    for line in text.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        game, name, prize, total, claimed, unclaimed = m.groups()
        row = ClaimRow(int(game), name.strip(), int(prize.replace(".", "")), int(total), int(claimed), int(unclaimed))
        if row.claimed + row.unclaimed != row.total:
            raise ValueError(f"Spel {game}: geclaimd + niet geclaimd is niet gelijk aan het totaal")
        rows[row.game] = row
    if not rows:
        raise ValueError("Geen rijen gevonden in het overzicht")
    return as_of, rows


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def find_overview_url(page_html: str) -> str:
    match = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(?:(?!</a>).)*?Hoofdprijzen overzicht', page_html, re.S)
    if not match:
        raise ValueError("Link 'Hoofdprijzen overzicht' niet gevonden op de productpagina")
    return match[1].replace("&amp;", "&")


def fetch_overview(slug: str) -> tuple[str, str]:
    """Haalt het overzicht op via de productpagina van een kalender; geeft (tekst, url)."""
    html = _get(PAGE_URL.format(slug=slug)).decode("utf-8")
    url = find_overview_url(html)
    return pdf_to_text(_get(url)), url


def pdf_to_text(pdf: bytes) -> str:
    try:
        done = subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf, capture_output=True, check=True)
    except FileNotFoundError:
        raise SystemExit("pdftotext (poppler-utils) is niet geïnstalleerd; of geef --pdf met een tekstbestand op")
    return done.stdout.decode("utf-8", errors="replace")


def update_rules(rules_dir: Path, as_of: date, rows: dict[int, ClaimRow], source: str, dry_run: bool = False) -> list[str]:
    """Schrijft ``top_prize_claims`` in elk regelbestand waarvan het spelnummer in het overzicht staat."""
    report = []
    for path in sorted(rules_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        row = rows.get(data.get("game_number"))
        if row is None:
            continue
        top_tickets = sum(t["count"] for t in data.get("tiers", ()) if round(t["value"] * 100) == round(data["top_prize"] * 100))
        if top_tickets != row.total:
            report.append(f"{path.name}: OVERGESLAGEN, prijsregels hebben {top_tickets} hoofdprijzen, overzicht {row.total}")
            continue
        data["top_prize_claims"] = {"claimed": row.claimed, "as_of": as_of.isoformat(), "source": source}
        # de uitkomst moet door dezelfde controle als bij het laden van de app
        rules.parse_ruleset(data)
        report.append(f"{path.name}: spel {row.game}, {row.claimed} van {row.total} geclaimd (stand {as_of})")
        if not dry_run:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", type=Path, help="lokaal bestand (pdf of de tekst ervan) in plaats van downloaden")
    parser.add_argument("--rules-dir", type=Path, default=rules.RULES_DIR)
    parser.add_argument("--dry-run", action="store_true", help="alleen tonen wat er zou veranderen")
    args = parser.parse_args(argv)

    if args.pdf:
        raw = args.pdf.read_bytes()
        text = raw.decode("utf-8", errors="replace") if args.pdf.suffix == ".txt" else pdf_to_text(raw)
    else:
        newest = max(
            (r for r in rules.load_rulesets(args.rules_dir).values() if r.price_cents == 500),
            key=lambda r: r.edition,
        )
        text, _ = fetch_overview(f"5-{newest.game_number}")
    as_of, rows = parse_overview(text)
    for line in update_rules(args.rules_dir, as_of, rows, SOURCE, args.dry_run):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
