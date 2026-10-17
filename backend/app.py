"""FastAPI app implementing docs/CONTRACT.md."""
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import db, profile as P, voice, edition as E

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "frontend"
app = FastAPI(title="The Morning Paper")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
FRONT.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(FRONT)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    f = FRONT / "index.html"
    if f.exists():
        return HTMLResponse(f.read_text())
    return HTMLResponse("<h1>The Morning Paper</h1><p>Frontend not built yet. See /docs.</p>")


def _need(uid):
    p = db.get_profile(uid)
    if not p:
        raise HTTPException(404, "unknown user")
    return p


def _unique_id(name):
    base = P._slug(name) or "reader"
    uid, i = base, 1
    while db.get_profile(uid):
        i += 1
        uid = f"{base}-{i}"
    return uid


def _create_user(body):
    name = (body.get("name") or "Reader").strip()
    prof = P.new_profile(name, body.get("city", ""), body.get("sections") or [], body.get("keywords") or [],
                         body.get("avoid") or [], body.get("free_text", ""), body.get("tone", "balanced"),
                         body.get("reading_minutes", 15), user_id=_unique_id(name))
    db.save_profile(prof)
    return prof


@app.post("/api/users")
async def create_user(request: Request):
    return _create_user(await request.json())


@app.get("/api/users")
def users():
    return [{"user_id": p["user_id"], "name": p["name"], "city": p.get("city"), "tone": p.get("tone"),
             "updated": p.get("updated")} for p in db.list_profiles()]


@app.get("/api/users/{uid}/profile")
def profile(uid: str):
    return _need(uid)


@app.post("/api/ingest/refresh")
def refresh():
    from . import ingest
    return ingest.refresh()


@app.post("/api/users/{uid}/editions/today")
def today(uid: str, force: int = 0):
    _need(uid)
    try:
        return E.build_edition(uid, force=bool(force))
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@app.get("/api/users/{uid}/editions")
def editions(uid: str):
    return [{"id": e["id"], "date": e["date"], "title": e["title"], "edition_no": e["edition_no"],
             "count": 1 + sum(len(s["articles"]) for s in e["sections"]) + len(e["briefs"]) + len(e["serendipity"])}
            for e in db.list_editions(uid)]


@app.get("/api/editions/{eid}")
def edition(eid: str):
    e = db.get_edition(eid)
    if not e:
        raise HTTPException(404, "no such edition")
    return e


@app.get("/api/editions/{eid}/pdf")
def pdf(eid: str):
    e = db.get_edition(eid)
    if not e:
        raise HTTPException(404, "no such edition")
    from backend.pdf import render_pdf
    data = render_pdf(e)
    db.log_event(e["user_id"], None, "pdf", eid)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{eid}.pdf"'})


@app.post("/api/events")
async def events(request: Request):
    b = await request.json()
    uid = b.get("user_id")
    _need(uid)
    action = b.get("action")
    if action not in ("click", "read", "like", "dislike", "skip", "more", "less", "pdf"):
        raise HTTPException(400, "bad action")
    aid = b.get("article_id")
    if aid is None and action in ("more", "less") and b.get("value"):
        res = voice.handle(uid, f"{action} {b['value']}")
        return {"ok": True, "profile_delta": (res["changes"] or [{}])[0].get("delta", {})}
    _, delta = P.learn(uid, aid, action, b.get("value"))
    return {"ok": True, "profile_delta": delta}


@app.post("/api/voice")
async def voice_ep(request: Request):
    b = await request.json()
    _need(b.get("user_id"))
    return voice.handle(b["user_id"], b.get("text", ""), b.get("article_id"))


@app.get("/api/users/{uid}/insights")
def insights(uid: str):
    p = _need(uid)
    evs = db.get_events(uid, 100000)
    counts = {}
    for e in evs:
        counts[e["action"]] = counts.get(e["action"], 0) + 1
    srt = lambda d, n: [[k, round(v, 3)] for k, v in sorted(d.items(), key=lambda x: -x[1])[:n]]
    return {"top_sections": srt(p["sections"], 10), "top_keywords": srt(p["keywords"], 15),
            "top_entities": srt(p["entities"], 15), "avoid": p["avoid"], "tone": p["tone"],
            "history": p.get("history", []), "event_counts": counts,
            "bandit": {s: {"a": round(b["a"], 2), "b": round(b["b"], 2), "mean": round(b["a"] / (b["a"] + b["b"]), 3)}
                       for s, b in p.get("bandit", {}).items()}}


@app.get("/r/{eid}/{aid}")
def redirect(eid: str, aid: str):
    e = db.get_edition(eid)
    a = db.get_article(aid)
    if not e or not a:
        raise HTTPException(404)
    try:
        P.learn(e["user_id"], aid, "click")
    except KeyError:
        pass
    return RedirectResponse(a["url"], status_code=302)


@app.get("/api/kg")
def kg_ep(user_id: str = ""):
    from . import kg
    since = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    arts = db.get_articles(since_iso=since, limit=800) or db.get_articles(limit=400)
    return kg.build_graph(arts, db.get_profile(user_id) if user_id else None)


@app.post("/api/demo/seed")
def seed():
    uid = "usaid"
    if not db.get_profile(uid):
        db.save_profile(P.new_profile("Usaid", "Karachi", ["technology", "climate", "business", "pakistan"],
                                      ["AI", "cricket", "startups"], [], "", "balanced", 15, user_id=uid))
    try:
        ed = E.build_edition(uid, force=True)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return {"user_id": uid, "edition_id": ed["id"], "profile": db.get_profile(uid)}
