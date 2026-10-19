"""Geclaimde hoofdprijzen uit het hoofdprijzenoverzicht van de Nederlandse Loterij.

Het overzicht is een pdf die periodiek wordt bijgewerkt. Dit script leest hem uit (met
``pdftotext`` van poppler), controleert de aantallen tegen de prijsregels en schrijft ze naar
``<update-dir>/claims.json``. Die waarden gaan voor op de standen in ``rules/`` zodra ze nieuwer zijn.
Daarna de app herstarten (of gebruik de pagina Updates).

    python -m app.claims                 # haalt het overzicht op en schrijft claims.json
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
from dataclasses import dataclass, replace
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


def load_store(path: Path) -> dict:
    """Leest ``claims.json`` ({spelnummer: {claimed, as_of, source}}); een ontbrekend bestand is leeg."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_store(rulesets: dict[str, rules.Ruleset], store: dict) -> dict[str, rules.Ruleset]:
    """Zet de claims uit de opslag in de regels, maar alleen als ze nieuwer zijn dan wat er al in staat."""
    result = {}
    for code, ruleset in rulesets.items():
        entry = store.get(str(ruleset.game_number)) if ruleset.game_number else None
        try:
            claimed, as_of = int(entry["claimed"]), str(entry["as_of"])
        except (TypeError, KeyError, ValueError):
            result[code] = ruleset
            continue
        current = ruleset.top_claims
        if (current and current.as_of >= as_of) or not 0 <= claimed <= ruleset.top_tickets:
            result[code] = ruleset
            continue
        result[code] = replace(ruleset, top_claims=rules.TopPrizeClaims(claimed, as_of, str(entry.get("source", ""))))
    return result


def update_store(path: Path, as_of: date, rows: dict[int, ClaimRow], rulesets: dict[str, rules.Ruleset], dry_run: bool = False) -> list[str]:
    """Schrijft de claims van de bekende spellen naar ``claims.json``."""
    store = load_store(path)
    report = []
    for ruleset in sorted(rulesets.values(), key=lambda r: r.game_number or 0):
        row = rows.get(ruleset.game_number)
        if row is None:
            continue
        if row.total != ruleset.top_tickets:
            report.append(f"spel {row.game}: OVERGESLAGEN, prijsregels hebben {ruleset.top_tickets} hoofdprijzen, overzicht {row.total}")
            continue
        store[str(row.game)] = {"claimed": row.claimed, "as_of": as_of.isoformat(), "source": SOURCE}
        report.append(f"spel {row.game}: {row.claimed} van {row.total} geclaimd (stand {as_of})")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", type=Path, help="lokaal bestand (pdf of de tekst ervan) in plaats van downloaden")
    parser.add_argument("--update-dir", type=Path, default=rules.UPDATE_DIR, help="map waar claims.json komt te staan")
    parser.add_argument("--dry-run", action="store_true", help="alleen tonen wat er zou veranderen")
    args = parser.parse_args(argv)

    all_rules = rules.load_all()
    if args.pdf:
        raw = args.pdf.read_bytes()
        text = raw.decode("utf-8", errors="replace") if args.pdf.suffix == ".txt" else pdf_to_text(raw)
    else:
        newest = max((r for r in all_rules.values() if r.price_cents == 500), key=lambda r: r.edition)
        text, _ = fetch_overview(f"5-{newest.game_number}")
    as_of, rows = parse_overview(text)
    for line in update_store(args.update_dir / "claims.json", as_of, rows, all_rules, args.dry_run):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
