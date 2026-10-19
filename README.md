# December Kalender Tracker

Webapp voor het bijhouden van de December Kalender-krasloten (€5, €10 en €20) met meerdere gebruikers. Je ziet per kalender:

- welke symbolen er zijn gekrast
- de feestdagspellen en extra spellen
- de totale winst en het netto resultaat
- een live kansschatting per prijs
- een logboek van wie wat heeft gewijzigd

**Stack:** FastAPI, Jinja2 en HTMX, met één SQLite-bestand als opslag. Er is geen build-stap en geen JavaScript-framework.

> Er is bewust geen login: iedereen kiest zijn naam en ziet en bewerkt alle kalenders. Draai de app daarom **alleen op je thuisnetwerk** en zet hem niet open op internet.

## Functies

- **Kalender bijhouden:** symbool per vakje, feestdagspellen en extra spellen, met logboek en automatisch opslaan.
- **Serienummer:** typ het nummer van het lot in; je krijgt een waarschuwing bij een dubbel nummer (zelfde type), en je kunt zoeken op serienummer of naam.
- **Afronden:** sluit een kalender af met alleen het totaal dat je hebt gewonnen. Dat bedrag telt mee in de geldstatistieken; de symbolen en spellen worden vergrendeld tot je hem heropent.
- **Statistieken** (`/statistieken`): geld per kalender, per editie en totaal; per symbool het aantal vakjes en het aantal loten dat de prijs haalde.
- **Kans uit eigen record naast de gepubliceerde kans:** beide worden naast elkaar getoond, niet gemengd. Het eigen record telt alleen kalenders met alle vakjes ingevuld, en toont de steekproefgrootte en een 95%-interval.
- **Verwacht rendement** (op de pagina Spelregels): uit de officiële prijsregels, zoals het uitbetaalde deel van de inleg en de kans op minstens één prijs.

## Updates: nieuwe editie en geclaimde hoofdprijzen

Op de pagina **Updates** (of met `python -m app.update`) controleert de app bij de Nederlandse Loterij:

1. **Is er een nieuwe December Kalender?** De lijst van geldige series wordt vergeleken met wat er in `rules/` staat. Van een nieuwe editie wordt het prijzenschema (pdf) uitgelezen en worden de spelregels, prijsregels en kansen daaruit opgebouwd.
2. **Kloppen de gegevens?** Het aantal prijzen, de totale waarde en de winkans uit het schema moeten overeenkomen met wat er is uitgelezen, de bedragen in elke prijsregel moeten optellen, en het kansmodel moet bij de gepubliceerde kansen beginnen. Een editie die één controle niet haalt kan niet worden toegepast.
3. **Wat zijn de actuele geclaimde hoofdprijzen?** Dat overzicht wordt ook opgehaald.

Er wordt niets aangepast voordat je het voorstel hebt bekeken en op **Toepassen** hebt geklikt. Daarna gelden de nieuwe regels meteen, zonder herstart, en worden de kansen in alle kalenders met de nieuwe gegevens berekend. Bestaande kalenders en invoer blijven ongewijzigd.

- Nieuwe regels komen in `<update-dir>/rules/`, geclaimde hoofdprijzen in `<update-dir>/claims.json` (standaard `data/updates`, in Docker `/data/updates`, dus bewaard bij een nieuwe image). De bestanden in `rules/` van de repository blijven ongemoeid en gaan voor bij dezelfde code.
- Symbolen **zonder prijs** (bij de €20) en de iconen staan niet in het schema, maar alleen als plaatje op het lot. Die worden overgenomen van de vorige editie en met een waarschuwing getoond; controleer ze op het lot. Onbekende symboolnamen krijgen een `❔` en de editie blijft "niet geverifieerd".
- Oudere kalenders die niet zijn geïnstalleerd worden niet vanzelf toegevoegd: `python -m app.update --game NUMMER`.
- Het uitlezen gebruikt `pdftotext` (poppler-utils); in de Docker-image zit het al. Er wordt alleen met hosts van de loterij gecommuniceerd.

`python -m app.update` toont het voorstel; `--apply` vraagt daarna om bevestiging (of `--yes`). De app zelf is bedoeld voor je thuisnetwerk zonder login: iedereen die erbij kan, kan een update toepassen.

## Starten

Met Docker:

```sh
docker compose up -d --build
# open http://<ip-van-de-machine>:8000
```

De database staat in `./data/december-kalender.db`. Maak een back-up door dat bestand te kopiëren, of via **Export** in de app (JSON).

Zonder Docker:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000
```

Omgevingsvariabelen:

- `DK_DB_PATH`: pad naar de database (standaard `data/december-kalender.db`)
- `DK_RULES_DIR`: map met spelregels (standaard `rules/`)
- `DK_UPDATE_DIR`: map voor gedownloade edities en claims (standaard `data/updates`)

## Tests

```sh
.venv/bin/python -m pytest
```

## Spelregels en kansen

De regels per kalendertype staan in `rules/*.json`. Zie [`rules/README.md`](rules/README.md) voor het formaat.

Wat de app toont:

- **Exact:** "gevonden / nodig" en "niet meer haalbaar".
- **Schatting:** de **kans** per symbool, met het lotmodel in `app/ticketmodel.py`. Het officiële prijzenschema geeft per prijsregel het aantal loten, ook voor combinaties (meerdere symbolen tegelijk, of een symbool plus een spelprijs). Elk lot hoort daardoor bij één klasse, met de oplage als totaal. Na elk gekrast vakje wordt (Bayes) bijgewerkt welke klassen nog mogelijk zijn. Vooraf is de kans precies de gepubliceerde kans.
- **Aannames** (het schema zegt niets over de verdeling van de vakjes): een symbool dat zijn drempel haalt staat er precies zo vaak op; alle andere symbolen blijven onder hun drempel; verder is de verdeling willekeurig. Een combinatie die in geen enkele klasse past wordt gemeld als mogelijke invoerfout. Behandel de percentages als indicatie.
- **Geclaimde hoofdprijzen:** het overzicht van de loterij (hoeveel hoofdprijzen al zijn uitgekeerd) wordt uit de oplage gehaald. Is alles geclaimd, dan is de kans op de hoofdprijs 0. Hoeveel andere loten al verkocht of gekrast zijn is niet bekend en wordt dus niet meegenomen. Verversen via de pagina **Updates** (zie hieronder).
- **Zonder prijsregels** (`tiers`) valt de app terug op een eenvoudiger poolmodel (zie `rules/README.md`).
