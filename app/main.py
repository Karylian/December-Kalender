"""FastAPI-app: gedeelde werkruimte, gebruikers kiezen alleen hun naam (thuisnetwerk)."""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, rules, scoring, stats, store, updater
from .money import format_euros, parse_euros

APP_DIR = Path(__file__).resolve().parent
USER_COOKIE = "dk_user"
LOG_LIMIT = 100
CLOSED_MESSAGE = "Deze kalender is afgerond. Heropen hem om te wijzigen."


class NameRequired(Exception):
    pass


def format_chance(p: float | None) -> str:
    if p is None:
        return "—"
    if p >= 1:
        return "100%"
    if p <= 0:
        return "0%"
    if p >= 0.0001:
        return f"{p * 100:.2f}%".replace(".", ",")
    return "1 op " + f"{round(1 / p):,}".replace(",", ".")


def format_pct(p: float | None, digits: int = 1) -> str:
    return "—" if p is None else f"{p * 100:.{digits}f}%".replace(".", ",")


def format_one_in(p: float | None) -> str:
    """Kans als '1 op X' (of '—' bij onbekend/0)."""
    if not p:
        return "—"
    x = 1 / p
    return "1 op " + (f"{x:,.0f}".replace(",", ".") if x >= 100 else f"{x:.2f}".replace(".", ","))


CHECK_COOLDOWN_SECONDS = 60


def create_app(
    db_path: Path | str = db.DEFAULT_DB_PATH,
    rules_dir: Path = rules.RULES_DIR,
    update_dir: Path | None = None,
    update_source=None,
) -> FastAPI:
    app = FastAPI(title="December Kalender Tracker")
    conn = db.connect(db_path)
    db.migrate(conn)
    update_dir = Path(update_dir) if update_dir else rules.UPDATE_DIR
    rulesets = rules.load_all(rules_dir, update_dir)
    update_lock = threading.Lock()
    last_check = {"at": 0.0}

    templates = Jinja2Templates(directory=APP_DIR / "templates")
    templates.env.filters["euro"] = format_euros
    templates.env.filters["euro_input"] = lambda c: format_euros(c, input_value=True)
    templates.env.filters["chance"] = format_chance
    templates.env.filters["pct"] = format_pct
    templates.env.filters["one_in"] = format_one_in
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    app.state.conn = conn
    app.state.rulesets = rulesets

    @app.exception_handler(NameRequired)
    async def _name_required(request: Request, exc: NameRequired):
        target = "/naam?next=" + quote(request.url.path)
        if request.headers.get("HX-Request"):
            return Response(status_code=204, headers={"HX-Redirect": target})
        return RedirectResponse(target, status_code=303)

    def get_conn() -> sqlite3.Connection:
        return conn

    def current_user(request: Request) -> sqlite3.Row:
        raw = request.cookies.get(USER_COOKIE, "")
        user = store.get_user(conn, int(raw)) if raw.isdigit() else None
        if user is None:
            raise NameRequired()
        return user

    def load_calendar(calendar_id: int):
        calendar = store.get_calendar(conn, calendar_id)
        if calendar is None:
            raise HTTPException(404, "Kalender niet gevonden")
        ruleset = rulesets.get(calendar["ruleset_code"])
        if ruleset is None:
            raise HTTPException(500, f"Spelregels {calendar['ruleset_code']!r} ontbreken in rules/")
        return calendar, ruleset

    def summarize(calendar, ruleset) -> scoring.Summary:
        cid = calendar["id"]
        return scoring.summarize(
            ruleset,
            store.get_boxes(conn, cid),
            store.get_amounts(conn, cid, "holiday"),
            store.get_amounts(conn, cid, "extra"),
        )

    def calendar_context(request: Request, calendar_id: int, user, **extra) -> dict:
        calendar, ruleset = load_calendar(calendar_id)
        today = date.today()
        summary = summarize(calendar, ruleset)
        serial = calendar["serial"]
        return {
            "request": request,
            "user": user,
            "calendar": calendar,
            "ruleset": ruleset,
            "summary": summary,
            "win_cents": scoring.effective_win_cents(
                calendar["status"], calendar["done_total_cents"], summary.total_win_cents
            ),
            "serial_duplicates": store.serial_duplicates(conn, ruleset.code, serial, calendar_id) if serial else [],
            "boxes": store.get_boxes(conn, calendar_id),
            "log": store.get_log(conn, calendar_id, LOG_LIMIT),
            "future_days": {
                d for d in range(1, ruleset.boxes + 1) if today < date(ruleset.edition, 12, d)
            },
            **extra,
        }

    def updates(request: Request, calendar_id: int, user, error: str | None = None):
        return templates.TemplateResponse(
            request, "partials/updates.html", calendar_context(request, calendar_id, user, error=error)
        )

    # --- naam kiezen ------------------------------------------------------

    @app.get("/naam", response_class=HTMLResponse)
    def pick_name_page(request: Request, next: str = "/"):
        return templates.TemplateResponse(
            request, "pick_name.html", {"users": store.list_users(conn), "next": next}
        )

    @app.post("/naam")
    def pick_name(user_id: int | None = Form(None), new_name: str = Form(""), next: str = Form("/")):
        if new_name.strip():
            user = store.get_or_create_user(conn, new_name.strip()[:40])
        elif user_id is not None and store.get_user(conn, user_id):
            user = store.get_user(conn, user_id)
        else:
            return RedirectResponse("/naam", status_code=303)
        response = RedirectResponse(next if next.startswith("/") and not next.startswith("//") else "/", status_code=303)
        response.set_cookie(USER_COOKIE, str(user["id"]), max_age=60 * 60 * 24 * 365, samesite="lax", httponly=True)
        return response

    @app.post("/naam/wissel")
    def switch_name():
        response = RedirectResponse("/naam", status_code=303)
        response.delete_cookie(USER_COOKIE)
        return response

    # --- overzicht --------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request, q: str = "", status: str = "", user=Depends(current_user)):
        status = status if status in ("active", "done") else ""
        rows = store.list_calendars(conn, status=status or None, q=q.strip() or None)
        tickets = stats.build_tickets(rows, rulesets, store.get_all_boxes(conn), store.get_all_amounts(conn))
        orphans = [r for r in rows if r["ruleset_code"] not in rulesets]
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "user": user,
                "tickets": tickets,
                "orphans": orphans,
                "totals": stats.totals(tickets),
                "rulesets": rulesets.values(),
                "update_available": update_available(),
                "q": q,
                "status": status,
            },
        )

    def update_available() -> bool:
        row = store.latest_proposal(conn)
        if row is None or row["status"] != "pending":
            return False
        try:
            return updater.Proposal.from_json(row["payload"]).has_changes
        except (ValueError, KeyError, TypeError):
            return False

    @app.get("/statistieken", response_class=HTMLResponse)
    def statistics(request: Request, user=Depends(current_user)):
        tickets = stats.build_tickets(
            store.list_calendars(conn), rulesets, store.get_all_boxes(conn), store.get_all_amounts(conn)
        )
        return templates.TemplateResponse(
            request,
            "statistics.html",
            {
                "user": user,
                "totals": stats.totals(tickets),
                "groups": stats.all_ruleset_stats(rulesets, tickets),
            },
        )

    @app.post("/kalenders")
    def create_calendar(
        ruleset_code: str = Form(...),
        label: str = Form(""),
        serial: str = Form(""),
        user=Depends(current_user),
    ):
        ruleset = rulesets.get(ruleset_code)
        if ruleset is None:
            raise HTTPException(400, "Onbekend kalendertype")
        cid = store.create_calendar(
            conn, ruleset_code, label.strip()[:60] or ruleset.name, serial.strip()[:40], user["id"]
        )
        return RedirectResponse(f"/kalenders/{cid}", status_code=303)

    # --- één kalender -----------------------------------------------------

    @app.get("/kalenders/{calendar_id}", response_class=HTMLResponse)
    def calendar_page(request: Request, calendar_id: int, user=Depends(current_user)):
        return templates.TemplateResponse(
            request, "calendar.html", calendar_context(request, calendar_id, user)
        )

    @app.get("/kalenders/{calendar_id}/versie", response_class=HTMLResponse)
    def version_check(request: Request, calendar_id: int, v: int = 0):
        calendar, _ = load_calendar(calendar_id)
        return templates.TemplateResponse(
            request, "partials/stale.html", {"stale": calendar["version"] != v, "calendar": calendar}
        )

    @app.get("/kalenders/{calendar_id}/dag/{day}", response_class=HTMLResponse)
    def day_modal(request: Request, calendar_id: int, day: int, user=Depends(current_user)):
        ctx = calendar_context(request, calendar_id, user, day=day)
        if not 1 <= day <= ctx["ruleset"].boxes:
            raise HTTPException(404)
        return templates.TemplateResponse(request, "partials/day_modal.html", ctx)

    @app.post("/kalenders/{calendar_id}/dag/{day}", response_class=HTMLResponse)
    def set_day(
        request: Request, calendar_id: int, day: int, symbol: str = Form(""), user=Depends(current_user)
    ):
        calendar, ruleset = load_calendar(calendar_id)
        if not 1 <= day <= ruleset.boxes:
            raise HTTPException(404)
        if calendar["status"] == "done":
            return updates(request, calendar_id, user, error=CLOSED_MESSAGE)
        new = ruleset.symbol(symbol) if symbol else None
        if symbol and new is None:
            raise HTTPException(400, "Onbekend symbool")
        old = ruleset.symbol(store.get_boxes(conn, calendar_id).get(day))
        if new and old and new != old:
            message = f"Dag {day}: {old.emoji} {old.name} → {new.emoji} {new.name}"
        elif new:
            message = f"Dag {day}: {new.emoji} {new.name} gekrast"
        else:
            message = f"Dag {day} leeggemaakt"
        if new != old:
            store.set_box(conn, calendar_id, day, new.key if new else None, user["id"], message)
        return updates(request, calendar_id, user)

    async def _save_game(request: Request, calendar_id: int, kind: str, game: int, user):
        calendar, ruleset = load_calendar(calendar_id)
        if kind == "holiday":
            valid, slots, title = game in ruleset.holiday_days, ruleset.holiday_amounts, f"Feestdagspel {game} dec"
        else:
            valid, slots, title = 1 <= game <= ruleset.extra_games, ruleset.extra_amounts, f"Extra spel {game}"
        if not valid:
            raise HTTPException(404)
        if calendar["status"] == "done":
            return updates(request, calendar_id, user, error=CLOSED_MESSAGE)
        form = await request.form()
        try:
            amounts = [parse_euros(form.get(f"a{slot}")) for slot in range(slots)]
        except ValueError as exc:
            return updates(request, calendar_id, user, error=str(exc))
        shown = ", ".join(format_euros(a) if a is not None else "—" for a in amounts)
        store.set_game_amounts(conn, calendar_id, kind, game, amounts, user["id"], f"{title}: {shown}")
        return updates(request, calendar_id, user)

    @app.post("/kalenders/{calendar_id}/feestdag/{day}", response_class=HTMLResponse)
    async def set_holiday(request: Request, calendar_id: int, day: int, user=Depends(current_user)):
        return await _save_game(request, calendar_id, "holiday", day, user)

    @app.post("/kalenders/{calendar_id}/extra/{game}", response_class=HTMLResponse)
    async def set_extra(request: Request, calendar_id: int, game: int, user=Depends(current_user)):
        return await _save_game(request, calendar_id, "extra", game, user)

    @app.post("/kalenders/{calendar_id}/uitbetaald", response_class=HTMLResponse)
    def toggle_paid(request: Request, calendar_id: int, user=Depends(current_user)):
        calendar, _ = load_calendar(calendar_id)
        store.set_paid_out(conn, calendar_id, not calendar["paid_out"], user["id"])
        return updates(request, calendar_id, user)

    @app.get("/kalenders/{calendar_id}/reset", response_class=HTMLResponse)
    def reset_modal(request: Request, calendar_id: int, user=Depends(current_user)):
        return templates.TemplateResponse(
            request, "partials/confirm_modal.html", calendar_context(request, calendar_id, user, action="reset")
        )

    @app.post("/kalenders/{calendar_id}/reset", response_class=HTMLResponse)
    def reset(request: Request, calendar_id: int, user=Depends(current_user)):
        calendar, _ = load_calendar(calendar_id)
        if calendar["status"] == "done":
            return updates(request, calendar_id, user, error=CLOSED_MESSAGE)
        store.reset_calendar(conn, calendar_id, user["id"])
        return updates(request, calendar_id, user)

    @app.get("/kalenders/{calendar_id}/afronden", response_class=HTMLResponse)
    def finish_modal(request: Request, calendar_id: int, user=Depends(current_user)):
        ctx = calendar_context(request, calendar_id, user, action="finish")
        return templates.TemplateResponse(request, "partials/confirm_modal.html", ctx)

    @app.post("/kalenders/{calendar_id}/afronden", response_class=HTMLResponse)
    def finish(
        request: Request, calendar_id: int, total: str = Form(""), user=Depends(current_user)
    ):
        calendar, _ = load_calendar(calendar_id)
        try:
            cents = parse_euros(total)
        except ValueError as exc:
            ctx = calendar_context(request, calendar_id, user, action="finish", error=str(exc), total=total)
            return templates.TemplateResponse(request, "partials/confirm_modal.html", ctx)
        if cents is None:
            cents = 0  # leeg totaal = niets gewonnen
        if calendar["status"] != "done":
            store.finish_calendar(conn, calendar_id, cents, user["id"], format_euros(cents))
        return Response(status_code=204, headers={"HX-Redirect": f"/kalenders/{calendar_id}"})

    @app.post("/kalenders/{calendar_id}/heropenen", response_class=HTMLResponse)
    def reopen(calendar_id: int, user=Depends(current_user)):
        calendar, _ = load_calendar(calendar_id)
        if calendar["status"] == "done":
            store.reopen_calendar(conn, calendar_id, user["id"])
        return Response(status_code=204, headers={"HX-Redirect": f"/kalenders/{calendar_id}"})

    @app.post("/kalenders/{calendar_id}/serienummer", response_class=HTMLResponse)
    def update_serial(
        request: Request, calendar_id: int, serial: str = Form(""), user=Depends(current_user)
    ):
        calendar, _ = load_calendar(calendar_id)
        serial = serial.strip()[:40]
        if serial != (calendar["serial"] or ""):
            store.set_serial(conn, calendar_id, serial, user["id"])
        return updates(request, calendar_id, user)

    @app.post("/kalenders/{calendar_id}/log/wissen", response_class=HTMLResponse)
    def clear_log(request: Request, calendar_id: int, user=Depends(current_user)):
        load_calendar(calendar_id)
        store.clear_log(conn, calendar_id, user["id"])
        return updates(request, calendar_id, user)

    @app.get("/kalenders/{calendar_id}/verwijderen", response_class=HTMLResponse)
    def delete_modal(request: Request, calendar_id: int, user=Depends(current_user)):
        return templates.TemplateResponse(
            request, "partials/confirm_modal.html", calendar_context(request, calendar_id, user, action="delete")
        )

    @app.post("/kalenders/{calendar_id}/verwijderen")
    def delete(calendar_id: int, user=Depends(current_user)):
        load_calendar(calendar_id)
        store.delete_calendar(conn, calendar_id)
        return Response(status_code=204, headers={"HX-Redirect": "/"})

    # --- regels & export --------------------------------------------------

    @app.get("/regels", response_class=HTMLResponse)
    def rules_page(request: Request, user=Depends(current_user)):
        return templates.TemplateResponse(
            request, "rules.html", {"user": user, "rulesets": rulesets.values()}
        )

    # --- updates: nieuwe edities en geclaimde hoofdprijzen ----------------------------------------

    def updates_page(request: Request, user, message: str | None = None):
        row = store.latest_proposal(conn)
        proposal = None
        if row is not None:
            try:
                proposal = updater.Proposal.from_json(row["payload"])
            except (ValueError, KeyError, TypeError):
                proposal = None
        return templates.TemplateResponse(
            request,
            "updates.html",
            {
                "user": user,
                "row": row,
                "proposal": proposal,
                "installed": sorted(rulesets.values(), key=lambda r: (-r.edition, r.price_cents)),
                "message": message,
            },
        )

    @app.get("/updates", response_class=HTMLResponse)
    def updates_view(request: Request, gedaan: str = "", user=Depends(current_user)):
        messages = {"toegepast": "De update is toegepast.", "genegeerd": "Het voorstel is genegeerd.",
                    "wacht": "Er is net al gecontroleerd; wacht even voor een nieuwe controle.",
                    "beslist": "Dit voorstel was al beslist."}
        return updates_page(request, user, messages.get(gedaan))

    @app.post("/updates/controleren")
    def check_updates(user=Depends(current_user)):
        with update_lock:
            if time.monotonic() - last_check["at"] < CHECK_COOLDOWN_SECONDS and last_check["at"]:
                return RedirectResponse("/updates?gedaan=wacht", status_code=303)
            last_check["at"] = time.monotonic()
            source = update_source or updater.LiveSource()
            proposal = updater.check_for_updates(source, rulesets)
            store.save_proposal(conn, proposal.to_json(), user["id"])
        return RedirectResponse("/updates", status_code=303)

    @app.post("/updates/{proposal_id}/toepassen")
    def apply_update(proposal_id: int, user=Depends(current_user)):
        with update_lock:
            row = store.get_proposal(conn, proposal_id)
            if row is None:
                raise HTTPException(404)
            if row["status"] != "pending":
                return RedirectResponse("/updates?gedaan=beslist", status_code=303)
            proposal = updater.Proposal.from_json(row["payload"])
            updater.apply_proposal(proposal, update_dir)
            store.decide_proposal(conn, proposal_id, "applied", user["id"])
            fresh = rules.load_all(rules_dir, update_dir)
            rulesets.clear()  # dezelfde dict blijven gebruiken: alle routes zien direct de nieuwe regels
            rulesets.update(fresh)
        return RedirectResponse("/updates?gedaan=toegepast", status_code=303)

    @app.post("/updates/{proposal_id}/negeren")
    def dismiss_update(proposal_id: int, user=Depends(current_user)):
        if not store.decide_proposal(conn, proposal_id, "dismissed", user["id"]):
            return RedirectResponse("/updates?gedaan=beslist", status_code=303)
        return RedirectResponse("/updates?gedaan=genegeerd", status_code=303)

    @app.get("/export.json")
    def export(user=Depends(current_user)):
        return JSONResponse(
            store.export_all(conn),
            headers={"Content-Disposition": 'attachment; filename="december-kalender-export.json"'},
        )

    return app
