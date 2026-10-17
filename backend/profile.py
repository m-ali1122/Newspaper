"""User profile: seeding + Rocchio-style online learning + Beta-bandit updates (explainable)."""
import re
from . import db

POS = {"click": 0.5, "like": 1.0, "more": 1.0}
NEG = {"skip": -0.3, "dislike": -1.0, "less": -1.0}
SEC_LR, KW_LR, ENT_LR = 0.15, 0.3, 0.2


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def new_profile(name, city="", sections=(), keywords=(), avoid=(), free_text="", tone="balanced",
                reading_minutes=15, user_id=None):
    from . import voice
    chosen = [s for s in sections if s in db.SECTIONS]
    kws = {k.strip().lower(): 1.0 for k in keywords if k and k.strip()}
    avoid = [a.strip().lower() for a in avoid if a and a.strip()]
    if free_text:
        pr = voice.parse_multi(free_text)
        for s in pr["sections"]:
            if s not in chosen:
                chosen.append(s)
        for t in pr["topics"]:
            if t not in voice.GENERIC:
                kws.setdefault(t, 1.0)
        for a in pr["avoid"]:
            if a not in avoid:
                avoid.append(a)
    avoid_secs = {voice.LEXICON.get(a) for a in avoid if a in voice.GENERIC}
    chosen = [c for c in chosen if c not in avoid_secs]
    prof = {
        "user_id": user_id or _slug(name) or "reader", "name": name, "city": city or "",
        "sections": {s: (0.8 if s in chosen else 0.2) for s in db.SECTIONS},
        "keywords": kws, "entities": {}, "avoid": avoid, "tone": tone or "balanced",
        "reading_minutes": int(reading_minutes or 15), "created": db.now_iso(),
        "bandit": {s: ({"a": 3.0, "b": 1.0} if s in chosen else {"a": 1.0, "b": 1.0}) for s in db.SECTIONS},
        "history": [],
    }
    for s in avoid_secs:
        if s:
            prof["sections"][s] = 0.03
            prof["bandit"][s] = {"a": 1.0, "b": 6.0}
    try:  # interest expansion through the knowledge graph (small weight)
        from . import kg
        for k in list(kws)[:8]:
            for r in kg.related_entities(k, k=3) or []:
                prof["entities"].setdefault(r, 0.3)
    except Exception:
        pass
    _snapshot(prof)
    return prof


def top_interests(profile, n=8):
    items = [(k, v) for k, v in profile["keywords"].items()]
    items += [(k, v) for k, v in profile["entities"].items()]
    items += [(k, v) for k, v in profile["sections"].items()]
    items.sort(key=lambda x: -x[1])
    return [[k, round(v, 3)] for k, v in items[:n]]


def _snapshot(profile):
    profile.setdefault("history", []).append({"ts": db.now_iso(), "top": top_interests(profile)})
    profile["history"] = profile["history"][-100:]


def magnitude(action, value=None):
    if action in POS:
        return POS[action]
    if action in NEG:
        return NEG[action]
    if action == "read":
        try:
            secs = float(value or 0)
        except (TypeError, ValueError):
            secs = 0.0
        return min(1.0, secs / 60.0) * 0.8 if secs >= 5 else 0.0
    return 0.0


def apply_event(profile, article, action, value=None):
    """Rocchio: p <- decay(p) + lr * m * article_vector. Returns delta for the UI."""
    m = magnitude(action, value)
    delta = {"action": action, "magnitude": round(m, 3), "section": None, "keywords_up": [],
             "keywords_down": [], "entities": []}
    if m == 0 or not article:
        return delta
    sec = article.get("section")
    if sec in profile["sections"]:
        old = profile["sections"][sec]
        new = min(1.0, max(0.02, old + SEC_LR * m))
        profile["sections"][sec] = new
        delta["section"] = {"name": sec, "from": round(old, 3), "to": round(new, 3)}
        b = profile.setdefault("bandit", {}).setdefault(sec, {"a": 1.0, "b": 1.0})
        if m > 0:
            b["a"] += abs(m)
        else:
            b["b"] += abs(m)
    # decay everything first
    for d in (profile["keywords"], profile["entities"]):
        for k in list(d):
            d[k] *= 0.98
    for kw in (article.get("keywords") or [])[:8]:
        kw = kw.lower()
        old = profile["keywords"].get(kw, 0.0)
        profile["keywords"][kw] = old + KW_LR * m
        (delta["keywords_up"] if m > 0 else delta["keywords_down"]).append(kw)
    for e in (article.get("entities") or [])[:8]:
        nm = e["text"] if isinstance(e, dict) else str(e)
        old = profile["entities"].get(nm, 0.0)
        profile["entities"][nm] = old + ENT_LR * m
        delta["entities"].append(nm)
    for d, cap in ((profile["keywords"], 60), (profile["entities"], 60)):
        for k in [k for k, v in d.items() if v < 0.05]:
            del d[k]
        if len(d) > cap:
            for k, _ in sorted(d.items(), key=lambda x: x[1])[: len(d) - cap]:
                del d[k]
    _snapshot(profile)
    delta["top"] = profile["history"][-1]["top"]
    return delta


def learn(user_id, article_id, action, value=None):
    """Load profile, log event, apply learning, save. Returns (profile, delta)."""
    prof = db.get_profile(user_id)
    if prof is None:
        raise KeyError(user_id)
    art = db.get_article(article_id) if article_id else None
    db.log_event(user_id, article_id, action, value)
    delta = apply_event(prof, art, action, value)
    db.save_profile(prof)
    return prof, delta
