# Spelregels per kalendertype

Eén JSON-bestand per kalendertype en editie, bv. `2025-5.json`. Ze worden bij het starten van de app ingeladen. Een kalender in de database verwijst naar `code`, dus **wijzig de `code` van een bestaand bestand niet**. Maak voor een nieuwe editie een nieuw bestand aan.

Bedragen zijn in euro's. Zie `tests/rules/test-5.json` voor een (fictief) voorbeeld.

| Veld | Betekenis |
|---|---|
| `code` | Unieke sleutel, bv. `dk-2025-5` |
| `name`, `edition`, `game_number` | Weergavenaam, jaar en spelnummer van Lotto B.V. |
| `price`, `top_prize` | Aankoopprijs en hoofdprijs |
| `overall_odds` | Officiële totale winkans "1 op X" |
| `verified` | `true` alleen als alles is gecontroleerd tegen het officiële prijzenschema |
| `sources` | Lijst van `{"title": ..., "url": ...}` |
| `holiday_days`, `holiday_amounts` | Dagen met een feestdagspel (standaard 5/25/26/31) en het aantal bedragen per spel (standaard 4) |
| `extra_games`, `extra_amounts`, `extra_rule` | Aantal extra spellen, invulvelden per spel, en `direct` (gewonnen bedrag invullen) of `match2` (2 gelijke bedragen) |
| `pool_size` | Grootte van de aangenomen symbolenpool voor de kansschatting (standaard 31000) |
| `symbols[]` | `key`, `name`, `emoji`, `needed` (aantal gelijke symbolen), `prize`, optioneel `prize_label` (bv. "Gratis kraslot"), `odds` (officiële kans "1 op X" op deze prijs), `pool_count` (handmatige pool-aanname, overschrijft de kalibratie op `odds`) en `top` (hoofdprijssymbool) |

Zonder `odds` of `pool_count` toont de app voor dat symbool geen kans, alleen of het nog haalbaar is.
