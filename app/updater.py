"""Nieuwe edities en geclaimde hoofdprijzen ophalen bij de Nederlandse Loterij.

De loterij publiceert per kalender een prijzenschema (pdf) met alle prijsregels. Dit module:

  1. ziet op de lijst van geldige series welke December Kalenders er zijn en welke nog niet in
     ``rules/`` staan;
  2. leest het prijzenschema van een nieuwe editie uit en bouwt daaruit de spelregels, inclusief de
     prijsregels waarop het kansmodel rekent;
  3. controleert alles tegen de totalen die het schema zelf noemt (aantal prijzen, totale waarde,
     winkans) en tegen de eigen validatie van de app, en
  4. haalt de actuele aantallen geclaimde hoofdprijzen op.

Er wordt niets geschreven voordat iemand het voorstel heeft bekeken (``apply``). Regels van een
nieuwe editie komen in de map ``<update-dir>/rules``, geclaimde hoofdprijzen in
``<update-dir>/claims.json``; de regels in de repository blijven ongemoeid.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import claims as claims_mod
from . import rules, ticketmodel

SERIES_URL = "https://krasloten.nederlandseloterij.nl/overzicht-geldige-series"
PRODUCT_URL = "https://krasloten.nederlandseloterij.nl/krasloten/december-kalender-{price}-{game}"
ALLOWED_HOSTS = ("nederlandseloterij.nl", "azureedge.net", "blob.core.windows.net")
USER_AGENT = "Mozilla/5.0"
MAX_DOWNLOAD = 15_000_000

MONTHS = {m: i for i, m in enumerate(
    ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
     "september", "oktober", "november", "december"], start=1)}
NUMBER_WORDS = {"een": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "zes": 6}

# Symboolnamen in de schema's zijn soms Engels (2025) en soms Nederlands (2026).
ENGLISH_NAMES = {
    "santa": "kerstman", "hat": "muts", "snowman": "sneeuwpop", "sleigh": "slee", "candle": "kaars",
    "skates": "schaats", "mittens": "want", "bell": "bel", "star": "ster", "snowflake": "sneeuw",
    "gift": "kado", "mountain": "berg", "fireplace": "openhaard", "holly": "hulst", "ribbon": "strik",
    "snowglobe": "sneeuwbol",
}
EMOJI = {
    "kerstman": "🎅", "muts": "🧢", "sneeuwpop": "⛄", "slee": "🛷", "kaars": "🕯️", "schaats": "⛸️",
    "want": "🧤", "bel": "🔔", "ster": "⭐", "sneeuw": "❄️", "kado": "🎁", "berg": "🏔️",
    "openhaard": "🔥", "hulst": "🌿", "strik": "🎀", "sneeuwbol": "🔮", "boom": "🎄", "kerstbal": "🔴",
    "zuurstok": "🍭", "sokken": "🧦", "kadootjes": "🎁", "krans": "💚", "hart": "❤️", "rendier": "🦌",
}
UNKNOWN_EMOJI = "❔"


class UpdateError(Exception):
    """Fout bij ophalen of lezen van de bronnen (netwerk, ontbrekende link, onleesbaar schema)."""


# --- bronnen -----------------------------------------------------------------------------------

class LiveSource:
    """Haalt de pagina's en pdf's echt op. Alleen hosts van de loterij zijn toegestaan."""

    def _get(self, url: str) -> bytes:
        host = urlparse(url).hostname or ""
        if urlparse(url).scheme != "https" or not host.endswith(ALLOWED_HOSTS):
            raise UpdateError(f"Adres niet toegestaan: {url}")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read(MAX_DOWNLOAD + 1)
        except OSError as exc:
            raise UpdateError(f"Ophalen mislukt ({host}): {exc}") from exc
        if len(data) > MAX_DOWNLOAD:
            raise UpdateError(f"Bestand te groot: {url}")
        return data

    def series_html(self) -> str:
        return self._get(SERIES_URL).decode("utf-8", errors="replace")

    def product_html(self, price: int, game: int) -> str:
        return self._get(PRODUCT_URL.format(price=price, game=game)).decode("utf-8", errors="replace")

    def pdf_text(self, url: str) -> str:
        pdf = self._get(url)
        try:
            done = subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf, capture_output=True, check=True, timeout=60)
        except FileNotFoundError:
            raise UpdateError("pdftotext (poppler-utils) is niet geïnstalleerd op deze machine") from None
        except subprocess.SubprocessError as exc:
            raise UpdateError(f"pdf kon niet worden gelezen: {exc}") from exc
        return done.stdout.decode("utf-8", errors="replace")


# --- lijst van series ----------------------------------------------------------------------------

@dataclass(frozen=True)
class SeriesEntry:
    game: int
    price: int  # euro


_TAG = re.compile(r"<script.*?</script>|<style.*?</style>", re.S)


def html_lines(html: str) -> list[str]:
    import html as html_lib

    text = html_lib.unescape(re.sub(r"<[^>]+>", "\n", _TAG.sub("", html)))
    return [line.strip() for line in text.splitlines() if line.strip()]


def discover(series_html: str) -> list[SeriesEntry]:
    """December Kalenders uit de lijst van geldige series: een regel met de naam, daarna het spelnummer."""
    lines = html_lines(series_html)
    entries: dict[int, SeriesEntry] = {}
    for i, line in enumerate(lines[:-1]):
        name = re.fullmatch(r"December Kalender\s*€\s*(\d+)", line)
        number = re.fullmatch(r"\d{3}", lines[i + 1])
        if name and number:
            entries[int(number[0])] = SeriesEntry(int(number[0]), int(name[1]))
    return sorted(entries.values(), key=lambda e: e.game)


def find_link(page_html: str, label: str) -> str:
    match = re.search(r'<a\b[^>]*href="([^"]+)"[^>]*>(?:(?!</a>).)*?' + re.escape(label), page_html, re.S)
    if not match:
        raise UpdateError(f"Link '{label}' niet gevonden op de productpagina")
    return match[1].replace("&amp;", "&")


# --- prijzenschema lezen -----------------------------------------------------------------------------

@dataclass
class ParsedTier:
    description: str
    value_cents: int
    count: int
    symbols: list[tuple[str, int]] = field(default_factory=list)  # (naam in het schema, aantal)
    free_ticket: bool = False


@dataclass
class ParsedScheme:
    game: int
    price: int
    print_run: int
    total_prizes: int
    total_value_cents: int
    win_odds: float
    valid_until: date
    holiday_days: list[int]
    holiday_amounts: int
    extra_games: int
    tiers: list[ParsedTier]
    problems: list[str] = field(default_factory=list)


_TAIL = re.compile(
    r"^(?P<prefix>.*?)€\s*(?P<value>\d[\d.,]*)\s+(?P<count>\d{1,3}(?:\.\d{3})+|\d+)(?:\s+1\s*:\s*[\d.,]+)?\s*$"
)
_SYMBOL = re.compile(r"\(\s*(\d+)\s*[x×]\s*([A-Za-zÀ-ÿ ]+?)\s*\)")


def _amount(token: str) -> int:
    """'5' / '5,00' / '1.000,00' / '5,000' (Engelse duizendtallen) -> centen."""
    token = token.strip().rstrip(".,")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{1,2}", token):  # 1.000,50
        whole, frac = token.replace(".", "").split(",")
        return int(whole) * 100 + int(frac.ljust(2, "0"))
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
        return int(re.sub(r"[.,]", "", token)) * 100
    if re.fullmatch(r"\d+[.,]\d{1,2}", token):
        whole, frac = re.split(r"[.,]", token)
        return int(whole) * 100 + int(frac.ljust(2, "0"))
    if re.fullmatch(r"\d+", token):
        return int(token) * 100
    raise ValueError(token)


def _number(token: str) -> int:
    return int(token.replace(".", ""))


def _excess(text: str) -> int:
    return text.count("(") - text.count(")")


def _dangling(text: str) -> bool:
    stripped = text.rstrip()
    return _excess(text) != 0 or bool(re.search(r"(\+|[x×]|€|\(\s*\d*)$", stripped))


def _merge_split_rows(lines: list[str]) -> list[str]:
    """Soms staat de prijs van een rij op de regel eronder ('€  195.000' en daarna '5,00')."""
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        m = re.search(r"€\s+(\d{1,3}(?:\.\d{3})+)\s*$", line)
        v = re.fullmatch(r"\s*(\d[\d.]*,\d{2})\s*", nxt)
        if m and v and not _TAIL.match(line):
            out.append(f"{line[:m.start()]}€ {v[1]} {m[1]}")
            i += 2
        else:
            out.append(line)
            i += 1
    return out


def _clean(description: str) -> str:
    description = re.sub(r"t\.w\.v\.?", " ", description)
    description = re.sub(r"\b(Gratis Kraslot|Free ticket)\b", " ", description, flags=re.I)
    return re.sub(r"\s+", " ", description).strip()


def _split_rows(text: str) -> list[tuple[str, int, int, bool]]:
    """Alle regels van de prijstabel: (omschrijving, prijs in centen, aantal loten, gratis lot)."""
    lines = _merge_split_rows(text.splitlines())
    rows: list[tuple[str, int, int, bool]] = []
    pending: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _TAIL.match(line)
        if not m:
            if line.strip():
                pending.append(line.strip())
            else:
                pending = []
            i += 1
            continue
        prefix = re.sub(r"^\s*\d{1,3}\s+", "", m["prefix"]).strip()
        try:
            value = _amount(m["value"])
        except ValueError:
            pending, i = [], i + 1
            continue
        count = _number(m["count"])
        description = prefix
        excess = _excess(prefix)
        if excess < 0 or (excess == 0 and pending and _dangling(" ".join(pending))):
            description = " ".join(pending + [prefix])  # rij loopt omhoog door
        elif _dangling(prefix):  # rij loopt door op de regels eronder
            j = i + 1
            while j < len(lines) and lines[j].strip() and not _TAIL.match(lines[j]) and (
                _dangling(description) or lines[j].strip()[0] in "(+"
            ):
                description += " " + lines[j].strip()
                j += 1
            i = j - 1
        free = bool(re.search(r"gratis|free", description + " " + m["prefix"], re.I))
        rows.append((_clean(re.sub(r"^\d{1,3}\s+", "", description)), value, count, free))
        pending = []
        i += 1
    return rows


def _components(description: str) -> list[int]:
    """Bedragen in een omschrijving ('€ 5 (4 x MUTS) + € 10 × 2') in centen, zonder de symboolhaakjes."""
    bare = _SYMBOL.sub(" ", description).replace("(", " ").replace(")", " ")
    amounts = []
    for term in bare.split("+"):
        m = re.search(r"€\s*(\d[\d.,]*)(?:\s*[x×]\s*(\d+))?", term)
        if not m:
            raise ValueError(term)
        amounts.append(_amount(m[1]) * int(m[2] or 1))
    return amounts


def parse_scheme(text: str) -> ParsedScheme:
    flat = re.sub(r"\s+", " ", text)

    def find(pattern: str, what: str) -> re.Match:
        m = re.search(pattern, flat, re.I)
        if not m:
            raise UpdateError(f"{what} niet gevonden in het prijzenschema")
        return m

    game = int(find(r"\(spel (\d{3})\)", "Spelnummer")[1])
    price = int(find(r"loten à €\s*(\d+)", "Prijs per lot")[1])
    print_run = _number(find(r"bedraagt ([\d.]+) loten", "Oplage")[1])
    totals = find(r"In totaal zijn er ([\d.]+) prijzen ter waarde van € ?([\d.]+,\d{2}) netto", "Totaal aantal prijzen")
    odds = float(find(r"winkans op dit lot is 1 op ([\d,.]+)", "Winkans")[1].rstrip(".").replace(",", "."))
    valid = find(r"geldig tot en met (\d{1,2}) ([a-z]+) (\d{4})", "Geldigheid")
    if valid[2].lower() not in MONTHS:
        raise UpdateError(f"Onbekende maand in geldigheidsdatum: {valid[2]}")
    valid_until = date(int(valid[3]), MONTHS[valid[2].lower()], int(valid[1]))

    days = re.search(r"Op de dagen ([\d, en]+?) december", flat)
    holiday_days = [int(d) for d in re.findall(r"\d+", days[1])] if days else [5, 25, 26, 31]
    amounts = re.search(r"staan (\w+) bedragen", flat)
    holiday_amounts = NUMBER_WORDS.get(amounts[1].lower(), 4) if amounts else 4
    extra = re.search(r"EXTRA SPEL(?:LEN)? 1 t/m (\d+)", flat, re.I)
    extra_games = int(extra[1]) if extra else 0

    parsed = ParsedScheme(
        game=game, price=price, print_run=print_run, total_prizes=_number(totals[1]),
        total_value_cents=_amount(totals[2]), win_odds=odds, valid_until=valid_until,
        holiday_days=holiday_days, holiday_amounts=holiday_amounts, extra_games=extra_games, tiers=[],
    )
    for description, value, count, free in _split_rows(text):
        tier = ParsedTier(description, value, count, [(n.strip(), int(k)) for k, n in _SYMBOL.findall(description)], free)
        if not free:
            try:
                if sum(_components(description)) != value:
                    parsed.problems.append(f"Prijsregel '{description}': de bedragen tellen op tot {sum(_components(description)) / 100:g}, de prijs is {value / 100:g}")
            except ValueError:
                parsed.problems.append(f"Prijsregel '{description}': omschrijving niet te lezen")
        parsed.tiers.append(tier)
    if not parsed.tiers:
        raise UpdateError("Geen prijsregels gevonden in het prijzenschema")
    return parsed


# --- spelregels bouwen ---------------------------------------------------------------------------------

def _nl(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def normalize_name(name: str) -> str:
    key = re.sub(r"\s+", "", name.strip().lower())
    return ENGLISH_NAMES.get(key, key)


@dataclass
class Check:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class EditionProposal:
    game: int
    price: int
    edition: int
    code: str
    ruleset: dict | None
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.ruleset is not None and not self.problems and all(c.ok for c in self.checks)


def edition_from(parsed: ParsedScheme) -> int:
    """De kalender is twee jaar geldig; de editie is het jaar waarin hij uitkwam."""
    return parsed.valid_until.year - 2


def build_edition(
    parsed: ParsedScheme,
    *,
    edition: int,
    template: rules.Ruleset | None,
    sources: list[dict],
    today: date,
) -> EditionProposal:
    code = f"dk-{edition}-{parsed.price}"
    proposal = EditionProposal(parsed.game, parsed.price, edition, code, None)
    checks, problems, notes = proposal.checks, proposal.problems, proposal.notes
    problems.extend(parsed.problems)

    cash_tiers = [t for t in parsed.tiers if not t.free_ticket]
    count_sum = sum(t.count for t in parsed.tiers)
    value_sum = sum(t.count * t.value_cents for t in cash_tiers)
    checks.append(Check("Aantal prijzen klopt met het totaal", count_sum == parsed.total_prizes,
                        f"{_nl(count_sum)} gelezen, {_nl(parsed.total_prizes)} genoemd"))
    checks.append(Check("Totale waarde klopt (zonder gratis loten)", value_sum == parsed.total_value_cents,
                        f"€ {_nl(value_sum // 100)} gelezen, € {_nl(parsed.total_value_cents // 100)} genoemd"))
    published = count_sum / parsed.print_run
    checks.append(Check("Winkans klopt met de gepubliceerde winkans",
                        abs(published * parsed.win_odds - 1) < 0.01, f"1 op {1 / published:.2f} berekend, 1 op {parsed.win_odds:.2f} genoemd".replace(".", ",")))
    checks.append(Check("Editie lijkt de nieuwste", today.year - 1 <= edition <= today.year + 1, f"editie {edition}"))

    # symbolen: aantal en prijs uit de regels met één symbool
    needed: dict[str, int] = {}
    prize: dict[str, int] = {}
    display: dict[str, str] = {}
    for tier in parsed.tiers:
        for raw, n in tier.symbols:
            key = normalize_name(raw)
            display.setdefault(key, raw)
            if needed.setdefault(key, n) != n:
                problems.append(f"Symbool {raw}: verschillende aantallen ({needed[key]} en {n})")
        if len(tier.symbols) == 1 and len(_components(tier.description) if not tier.free_ticket else [0]) == 1:
            key = normalize_name(tier.symbols[0][0])
            prize[key] = tier.value_cents
    for key in needed:
        if key not in prize:
            problems.append(f"Symbool {display[key]} heeft geen eigen prijsregel")
    ladder = sorted(needed, key=lambda k: needed[k])
    if ladder and any(prize.get(a, 0) > prize.get(b, 0) for a, b in zip(ladder, ladder[1:])):
        problems.append("De prijzen van de symbolen stijgen niet met het aantal dat nodig is")

    top_cents = max(t.value_cents for t in parsed.tiers)
    top_symbols = [k for k in prize if prize[k] == top_cents]
    checks.append(Check("Hoofdprijs hoort bij één symbool", len(top_symbols) == 1, ", ".join(top_symbols) or "geen"))

    winning: dict[str, int] = {}
    tiers_json = []
    for tier in parsed.tiers:
        keys = [normalize_name(n) for n, _ in tier.symbols]
        for k in set(keys):
            winning[k] = winning.get(k, 0) + tier.count
        item: dict = {"count": tier.count, "value": tier.value_cents // 100 if tier.value_cents % 100 == 0 else tier.value_cents / 100}
        if keys:
            item["symbols"] = keys
        if tier.free_ticket:
            item["free_ticket"] = True
        tiers_json.append(item)

    unknown = [display[k] for k in ladder if k not in EMOJI]
    symbols = []
    if template:  # symbolen zonder prijs staan alleen als plaatje op het lot: overnemen van vorige editie
        carried = [s for s in template.symbols if not s.needed]
        for s in carried:
            symbols.append({"key": s.key, "name": s.name, "emoji": s.emoji})
        if carried:
            notes.append(
                f"Symbolen zonder prijs ({', '.join(s.name for s in carried)}) zijn overgenomen van {template.name} "
                f"({template.edition}): ze staan niet in het prijzenschema. Controleer ze op het lot."
            )
    for key in ladder:
        item = {"key": key, "name": key.capitalize(), "emoji": EMOJI.get(key, UNKNOWN_EMOJI),
                "needed": needed[key], "prize": prize[key] / 100 if prize[key] % 100 else prize[key] // 100,
                "winning_tickets": winning[key]}
        if any(t.free_ticket and normalize_name(t.symbols[0][0]) == key for t in parsed.tiers if t.symbols):
            item["prize_label"] = f"Gratis kraslot (t.w.v. € {prize[key] // 100})"
        if key in top_symbols:
            item["top"] = True
        symbols.append(item)
    if unknown:
        notes.append(f"Naam of icoon niet herkend voor: {', '.join(unknown)}. Controleer ze op het lot.")
    if template and template.holiday_days != tuple(parsed.holiday_days):
        notes.append("De dagen met een feestdagspel zijn anders dan vorig jaar.")

    data = {
        "code": code,
        "name": f"December Kalender €{parsed.price}",
        "edition": edition,
        "game_number": parsed.game,
        "price": parsed.price,
        "top_prize": top_cents // 100,
        "print_run": parsed.print_run,
        "overall_odds": parsed.win_odds,
        "verified": not unknown and not problems,
        "notes": " ".join(notes),
        "sources": sources,
        "boxes": 31,
        "holiday_days": parsed.holiday_days,
        "holiday_amounts": parsed.holiday_amounts,
        "extra_games": parsed.extra_games,
        "extra_amounts": 1,
        "extra_rule": "direct",
        "symbols": symbols,
        "total_prizes": parsed.total_prizes,
        "total_prize_value": parsed.total_value_cents / 100,
        "tiers": tiers_json,
    }
    # Dezelfde controles als bij het laden van de app, plus een rekenproef met het kansmodel.
    try:
        ruleset = rules.parse_ruleset(data)
        ticketmodel.build_classes(ruleset)
        start = ticketmodel.reach_chances(ruleset, {})
        ok = start is not None and all(
            abs(start[s.key] * s.odds - 1) < 1e-6 for s in ruleset.prize_symbols if s.odds
        )
        checks.append(Check("Kansmodel start bij de gepubliceerde kansen", ok, ""))
    except (ValueError, KeyError) as exc:
        problems.append(f"Regels voldoen niet aan de controle van de app: {exc}")
    proposal.ruleset = data
    return proposal


# --- voorstel ----------------------------------------------------------------------------------------------

@dataclass
class ClaimChange:
    game: int
    name: str
    old: int | None
    new: int
    total: int
    as_of: str


@dataclass
class Proposal:
    checked_at: str
    editions: list[EditionProposal] = field(default_factory=list)
    older: list[dict] = field(default_factory=list)  # nog niet geïnstalleerde, oudere kalenders
    claims: list[ClaimChange] = field(default_factory=list)
    claims_as_of: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return any(e.ok for e in self.editions) or bool(self.claims)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, raw: str) -> "Proposal":
        data = json.loads(raw)
        return cls(
            checked_at=data["checked_at"],
            editions=[
                EditionProposal(**{**e, "checks": [Check(**c) for c in e["checks"]]}) for e in data["editions"]
            ],
            older=data["older"],
            claims=[ClaimChange(**c) for c in data["claims"]],
            claims_as_of=data["claims_as_of"],
            errors=data["errors"],
        )


def check_for_updates(
    source,
    installed: dict[str, rules.Ruleset],
    *,
    today: date | None = None,
    games: list[int] | None = None,
) -> Proposal:
    """Zoekt nieuwe edities en actuele claims. Schrijft niets. ``games`` forceert specifieke spelnummers."""
    today = today or date.today()
    proposal = Proposal(checked_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    try:
        entries = discover(source.series_html())
    except UpdateError as exc:
        proposal.errors.append(str(exc))
        return proposal
    if not entries:
        proposal.errors.append("Geen December Kalenders gevonden in de lijst van geldige series")
        return proposal

    have = {r.game_number for r in installed.values()}
    newest_by_price: dict[int, int] = {}
    for r in installed.values():
        newest_by_price[r.price_cents // 100] = max(newest_by_price.get(r.price_cents // 100, 0), r.game_number or 0)
    wanted: list[SeriesEntry] = []
    for entry in entries:
        if entry.game in have:
            continue
        if games is not None and entry.game in games or (games is None and entry.game > newest_by_price.get(entry.price, 0)):
            wanted.append(entry)
        else:
            proposal.older.append({"game": entry.game, "price": entry.price})

    for entry in wanted:
        try:
            page = source.product_html(entry.price, entry.game)
            scheme_url = find_link(page, "Prijzenschema")
            parsed = parse_scheme(source.pdf_text(scheme_url))
            if parsed.game != entry.game or parsed.price != entry.price:
                raise UpdateError(f"Prijzenschema hoort bij spel {parsed.game} (€{parsed.price}), niet bij {entry.game}")
            same_price = [r for r in installed.values() if r.price_cents // 100 == entry.price]
            template = max(same_price, key=lambda r: r.edition, default=None)
            proposal.editions.append(build_edition(
                parsed, edition=edition_from(parsed), template=template, today=today,
                sources=[{"title": f"Prijzenschema spel {entry.game} (Lotto B.V.)", "url": scheme_url},
                         {"title": f"Productpagina spel {entry.game}", "url": PRODUCT_URL.format(price=entry.price, game=entry.game)}],
            ))
        except (UpdateError, ValueError) as exc:
            proposal.errors.append(f"Spel {entry.game} (€{entry.price}): {exc}")

    # actuele claims voor alles wat er is of er na toepassen bij komt
    try:
        anchor = entries[-1]
        text = source.pdf_text(find_link(source.product_html(anchor.price, anchor.game), "Hoofdprijzen overzicht"))
        as_of, rows = claims_mod.parse_overview(text)
        proposal.claims_as_of = as_of.isoformat()
        known = {r.game_number: r for r in installed.values()}
        known.update({e.game: None for e in proposal.editions if e.ok})
        for game, row in sorted(rows.items()):
            if game not in known:
                continue
            current = known[game].top_claims if known[game] else None
            if current and current.claimed == row.claimed and current.as_of >= as_of.isoformat():
                continue
            if current and current.as_of > as_of.isoformat():
                continue
            if known[game] and not 0 <= row.claimed <= known[game].top_tickets:
                proposal.errors.append(f"Spel {game}: {row.claimed} geclaimd past niet bij {known[game].top_tickets} hoofdprijzen")
                continue
            proposal.claims.append(ClaimChange(game, row.name, current.claimed if current else None,
                                               row.claimed, row.total, as_of.isoformat()))
    except (UpdateError, ValueError) as exc:
        proposal.errors.append(f"Hoofdprijzenoverzicht: {exc}")
    return proposal


# --- toepassen -------------------------------------------------------------------------------------------------

def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def apply_proposal(proposal: Proposal, update_dir: Path) -> list[str]:
    """Schrijft de goedgekeurde editie(s) en claims naar ``update_dir``. Geeft een lijst met meldingen."""
    done = []
    for edition in proposal.editions:
        if not edition.ok:
            done.append(f"Overgeslagen: spel {edition.game} (controles niet gehaald)")
            continue
        _write_json(update_dir / "rules" / f"{edition.code}.json", edition.ruleset)
        done.append(f"Nieuwe editie toegevoegd: {edition.ruleset['name']} ({edition.edition}), spel {edition.game}")
    if proposal.claims:
        store = claims_mod.load_store(update_dir / "claims.json")
        for change in proposal.claims:
            store[str(change.game)] = {"claimed": change.new, "as_of": change.as_of, "source": claims_mod.SOURCE}
        _write_json(update_dir / "claims.json", store)
        done.append(f"Geclaimde hoofdprijzen bijgewerkt voor {len(proposal.claims)} spel(len) (stand {proposal.claims_as_of})")
    return done
