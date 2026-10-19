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
- **Zonder prijsregels** (`tiers`) valt de app terug op een eenvoudiger poolmodel (zie `rules/README.md`).
