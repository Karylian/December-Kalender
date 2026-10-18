# December Kalender Tracker

Webapp voor het bijhouden van de December Kalender-krasloten (€5, €10 en €20) met meerdere gebruikers. Je ziet per kalender:

- welke symbolen er zijn gekrast
- de feestdagspellen en extra spellen
- de totale winst en het netto resultaat
- een live kansschatting per prijs
- een logboek van wie wat heeft gewijzigd

**Stack:** FastAPI, Jinja2 en HTMX, met één SQLite-bestand als opslag. Er is geen build-stap en geen JavaScript-framework.

> Er is bewust geen login: iedereen kiest zijn naam en ziet en bewerkt alle kalenders. Draai de app daarom **alleen op je thuisnetwerk** en zet hem niet open op internet.

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
- **Schatting:** de **kans** per symbool. Officiële prijzenschema's vermelden alleen kansen per prijs over de hele oplage, niet hoeveel van elk symbool er op een lot zitten. Het model trekt de vakjes daarom zonder teruglegging uit een aangenomen symbolenpool (hypergeometrisch). Die pool is per symbool afgestemd op de officiële kans op die prijs. Echte loten worden niet willekeurig samengesteld, dus behandel de percentages als indicatie.
