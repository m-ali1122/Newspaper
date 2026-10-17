"""Assemble the daily edition from ranked cards."""
from datetime import datetime, timedelta, timezone
from . import db, profile as P, ranker


def _greeting(prof, uid, picked):
    hour = datetime.now().hour
    tod = "Good morning" if hour < 12 else ("Good afternoon" if hour < 18 else "Good evening")
    name = prof.get("name", "reader")
    evs = [e for e in db.get_events(uid, 200) if e["action"] in ("like", "more")]
    topic, nmoved = None, 0
    for e in evs:
        t = e["value"]
        a = db.get_article(e["article_id"]) if e["article_id"] else None
        if a:
            t = a["section"]
        if t and not t.startswith("tone:"):
            topic = t.lower()
            break
    if topic:
        nmoved = sum(1 for c in picked if any(topic in r.lower() for r in c.get("reasons", [])) or
                     topic in (c.get("title", "") + c.get("summary", "")).lower() or c.get("section") == topic)
    if topic and nmoved:
        return f"{tod}, {name} — {nmoved} stories moved up because you liked {topic} recently."
    return f"{tod}, {name} — your paper is ready, {prof.get('reading_minutes', 15)} minutes of reading."


def build_edition(user_id, force=False):
    today = datetime.now().strftime("%Y-%m-%d")
    eid = f"{user_id}-{today}"
    if not force:
        ex = db.get_edition(eid)
        if ex:
            return ex
    prof = db.get_profile(user_id)
    if prof is None:
        raise KeyError(user_id)
    if db.count_articles() == 0:
        from . import ingest
        ingest.refresh()
    since = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    cands = db.get_articles(since_iso=since, limit=1500)
    if len(cands) < 30:
        cands = db.get_articles(limit=600)
    nev = len(db.get_events(user_id, 100000))
    ranked = ranker.rank(cands, prof, seed=hash((eid, nev)) & 0xFFFF)
    if not ranked:
        raise RuntimeError("no articles available")
    # a front page should open on a strong, broadly readable story: among the top picks prefer
    # one that is not negative-toned and has a picture, else fall back to the top score
    _grim = ("csam", "abuse", "rape", "murder", "killed", "suicide", "child sex")
    def _lead_ok(a):
        t = (a.get("title", "") + " " + a.get("summary", "")).lower()
        return a.get("sentiment", {}).get("label") != "negative" and not any(g in t for g in _grim)
    top = ranked[:8]
    lead = next((a for a in top if _lead_ok(a) and a.get("image")), None) \
        or next((a for a in top if _lead_ok(a)), ranked[0])
    used = {lead["id"]}
    # sections: top 4-6 by profile weight that have candidates
    bysec = {}
    for c in ranked:
        if c["id"] not in used:
            bysec.setdefault(c["section"], []).append(c)
    secw = sorted(((s, w) for s, w in prof["sections"].items() if s in bysec), key=lambda x: -x[1])
    nsec = 4 + (prof.get("reading_minutes", 15) >= 15) + (prof.get("reading_minutes", 15) >= 25)
    per = 3 + (prof.get("reading_minutes", 15) >= 10) + (prof.get("reading_minutes", 15) >= 20)
    sections = []
    for s, w in secw[:nsec]:
        arts = bysec[s][:per]
        sections.append({"name": s, "articles": arts})
        used.update(a["id"] for a in arts)
    rest = [c for c in ranked if c["id"] not in used]
    briefs = rest[:6]
    used.update(c["id"] for c in briefs)
    sero = ranker.serendipity(ranked, prof, exclude_ids=used, n=2, seed=nev)
    used.update(c["id"] for c in sero)
    selected = [lead] + [a for s in sections for a in s["articles"]] + briefs + sero
    threads, graph = [], {"nodes": [], "edges": []}
    try:
        from . import kg
        threads = kg.story_threads(selected, cands, max_threads=4)
    except Exception:
        pass
    try:
        from . import kg
        graph = kg.build_graph(selected + ranked[:40], prof)
    except Exception:
        pass
    mood = {"positive": 0, "neutral": 0, "negative": 0}
    for c in selected:
        mood[(c.get("sentiment") or {}).get("label", "neutral")] = mood.get((c.get("sentiment") or {}).get("label", "neutral"), 0) + 1
    prev = db.list_editions(user_id)
    no = len({e["date"] for e in prev if e["id"] != eid}) + 1
    cl = ranker.clean
    from collections import Counter
    kc = Counter(k.lower() for c in selected for k in c.get("keywords", []))
    wod = None
    if kc:
        w, n = kc.most_common(1)[0]
        wod = {"word": w, "note": f"appears in {n} of today's stories"}
    ed = {
        "id": eid, "user_id": user_id, "date": today, "generated_at": db.now_iso(),
        "user_name": prof["name"], "word_of_day": wod,
        "title": f"The {prof['name']} Morning Post", "edition_no": no,
        "greeting": _greeting(prof, user_id, selected),
        "lead": cl(lead),
        "sections": [{"name": s["name"], "articles": [cl(a) for a in s["articles"]]} for s in sections],
        "briefs": [cl(c) for c in briefs], "serendipity": [cl(c) for c in sero],
        "threads": threads, "kg": graph, "mood": mood,
        "stats": {"candidates": len(cands), "sources": len({c.get("source") for c in cands}),
                  "events_learned": nev, "ranked": len(ranked)},
    }
    db.save_edition(ed)
    return ed
