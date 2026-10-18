"""Euro-bedragen: invoer parsen en Nederlands weergeven. Intern altijd centen."""

from __future__ import annotations

import re


def parse_euros(text: str | None) -> int | None:
    """'10', '10,50', '€ 1.000', '1000.5' -> centen. Leeg -> None. Ongeldig -> ValueError."""
    if text is None:
        return None
    cleaned = re.sub(r"[€\s]", "", text)
    if not cleaned:
        return None
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", cleaned):
        cleaned = cleaned.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", cleaned):
        raise ValueError(f"Ongeldig bedrag: {text!r}")
    return round(float(cleaned) * 100)


def format_euros(cents: int | None, *, input_value: bool = False) -> str:
    if cents is None:
        return ""
    euros, rest = divmod(abs(cents), 100)
    whole = f"{euros:,}".replace(",", ".")
    if input_value:
        return f"{whole},{rest:02d}" if rest else whole
    sign = "-" if cents < 0 else ""
    return f"{sign}€ {whole},{rest:02d}" if rest else f"{sign}€ {whole},-"
