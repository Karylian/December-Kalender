"""Opdrachtregel voor de update-controle.

    python -m app.update                 # zoekt naar nieuwe edities en claims, toont het voorstel
    python -m app.update --apply         # vraagt daarna of het mag worden toegepast
    python -m app.update --apply --yes   # zonder vraag (alleen als alle controles zijn gehaald)
    python -m app.update --game 354      # installeer een oudere kalender expliciet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import rules, updater


def render(proposal: updater.Proposal) -> str:
    lines = [f"Controle van {proposal.checked_at}"]
    lines += [f"FOUT: {e}" for e in proposal.errors]
    for e in proposal.editions:
        lines.append(f"\nNieuwe editie: December Kalender €{e.price} ({e.edition}), spel {e.game} -> {e.code}")
        lines += [f"  [{'ok' if c.ok else 'MIS'}] {c.label}  {c.detail}" for c in e.checks]
        lines += [f"  PROBLEEM: {p}" for p in e.problems]
        lines += [f"  Let op: {n}" for n in e.notes]
        if e.ruleset:
            lines.append("  Symbolen: " + ", ".join(
                f"{s['name']} {s['needed']}x = €{s['prize']}" if s.get("needed") else f"{s['name']} (geen prijs)"
                for s in e.ruleset["symbols"]))
        lines.append("  " + ("Kan worden toegepast." if e.ok else "Kan NIET worden toegepast."))
    for c in proposal.claims:
        lines.append(f"Geclaimde hoofdprijzen spel {c.game} ({c.name}): {c.old if c.old is not None else '-'} -> {c.new} van {c.total} (stand {c.as_of})")
    if proposal.older:
        lines.append("Oudere, niet geïnstalleerde kalenders: " + ", ".join(str(o["game"]) for o in proposal.older))
    if not proposal.editions and not proposal.claims and not proposal.errors:
        lines.append("Alles is up-to-date.")
    return "\n".join(lines)


def main(argv: list[str] | None = None, source=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="pas het voorstel toe (met bevestiging)")
    parser.add_argument("--yes", action="store_true", help="geen bevestiging vragen")
    parser.add_argument("--game", type=int, action="append", help="installeer dit spelnummer, ook als het ouder is")
    parser.add_argument("--rules-dir", type=Path, default=rules.RULES_DIR)
    parser.add_argument("--update-dir", type=Path, default=rules.UPDATE_DIR)
    args = parser.parse_args(argv)

    installed = rules.load_all(args.rules_dir, args.update_dir)
    proposal = updater.check_for_updates(source or updater.LiveSource(), installed, games=args.game)
    print(render(proposal))
    if proposal.errors and not proposal.has_changes:
        return 1
    if not args.apply or not proposal.has_changes:
        return 0
    if not args.yes and input("\nToepassen? [j/N] ").strip().lower() not in ("j", "ja", "y", "yes"):
        print("Niets aangepast.")
        return 0
    for line in updater.apply_proposal(proposal, args.update_dir):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
