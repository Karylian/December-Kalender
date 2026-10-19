# Spelregels per kalendertype

Eén JSON-bestand per kalendertype en editie, bv. `2025-5.json`. Ze worden bij het starten van de app ingeladen. Een kalender in de database verwijst naar `code`, dus **wijzig de `code` van een bestaand bestand niet**. Maak voor een nieuwe editie een nieuw bestand aan.

Bedragen zijn in euro's. Zie `tests/rules/test-5.json` voor een (fictief) voorbeeld.

| Veld | Betekenis |
|---|---|
| `code` | Unieke sleutel, bv. `dk-2025-5` |
| `name`, `edition`, `game_number` | Weergavenaam, jaar en spelnummer van Lotto B.V. |
| `price`, `top_prize` | Aankoopprijs en hoofdprijs |
| `print_run`, `overall_odds` | Oplage en officiële totale winkans "1 op X" |
| `verified` | `true` alleen als alles is gecontroleerd tegen het officiële prijzenschema |
| `sources` | Lijst van `{"title": ..., "url": ...}` |
| `holiday_days`, `holiday_amounts` | Dagen met een feestdagspel (standaard 5/25/26/31) en het aantal bedragen per spel (standaard 4) |
| `extra_games`, `extra_amounts`, `extra_rule` | Aantal extra spellen, invulvelden per spel, en `direct` (gewonnen bedrag invullen) of `match2` (2 gelijke bedragen) |
| `pool_size` | Alleen voor regels zonder `tiers`: grootte van de aangenomen symbolenpool voor het eenvoudige terugvalmodel (standaard 31000) |
| `symbols[]` | `key`, `name`, `emoji`, `needed` (aantal gelijke symbolen; weglaten = symbool zonder prijs), `prize`, optioneel `prize_label` (bv. "Gratis kraslot"), `winning_tickets` (aantal loten in de oplage met deze symboolprijs, opgeteld over alle prijsregels waarin het symbool voorkomt), `odds` (alternatief: officiële kans "1 op X"), `pool_count` (handmatige pool-aanname, overschrijft de kalibratie) en `top` (hoofdprijssymbool) |

`tiers[]` (optioneel) zijn de regels van het prijzenschema: `count` (aantal loten), `value` (totaalbedrag van de regel), `symbols` (keys van symbolen in die prijs) en `free_ticket` (gratis lot, telt niet mee in de totaalwaarde). Samen met `total_prizes` en `total_prize_value` worden ze bij het laden gecontroleerd: kloppen de sommen niet, dan start de app niet. Daaruit komen het verwachte rendement en de kans op minstens één prijs.

Het lotmodel (`app/ticketmodel.py`) gebruikt de `tiers`: elke prijsregel met symbolen levert een klasse op (de verzameling symbolen die hun drempel halen), en de rest van de oplage is de lege klasse. Een prijsregel mag alleen symbolen met een prijs (`needed`) noemen, en mag niet minder waard zijn dan de som van die symboolprijzen.

De beginkans per symbool is `print_run / winning_tickets`. Zonder `winning_tickets`, `odds` of `pool_count` toont de app voor dat symbool geen kans, alleen of het nog haalbaar is.

## Huidige bestanden

Alle getallen komen uit de officiële prijzenschema's van Lotto B.V. (links staan in elk bestand onder `sources`):

| Bestand | Spel | Oplage | Symboolprijzen |
|---|---|---|---|
| `2026-5.json` | 400 | 3.100.000 | 3× Kerstman (gratis lot) t/m 11× Ster (€ 100.000) |
| `2026-10.json` | 401 | 1.750.000 | 3× Sneeuw (€ 10) t/m 11× Ster (€ 300.000), plus 4 extra spellen |
| `2026-20.json` | 402 | 500.000 | alleen 11× Ster (€ 1.000.000), plus 15 extra spellen |
| `2025-5.json` | 376 | 3.000.000 | als 2026 |
| `2025-10.json` | 377 | 1.750.000 | als 2026 |
| `2025-20.json` | 378 | 600.000 | als 2026 |

Oudere versies van de 2025-PDF's bevatten drukfouten (spel 376, prijs 005/006; spel 378, prijs 3). De bestanden volgen de huidige, gecorrigeerde PDF's; de aantallen kloppen met de opgegeven totalen.
