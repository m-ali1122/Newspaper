"""Rule-based voice intent grammar (regex + lexicon). No ML: every decision is explainable.
Input comes from the browser Web Speech API; output reply is spoken via speechSynthesis."""
import re
from . import db

# lexicon: spoken word -> section
LEXICON = {
    "ai": "technology", "artificial intelligence": "technology", "tech": "technology", "technology": "technology",
    "startups": "technology", "startup": "technology", "software": "technology", "gadgets": "technology",
    "chips": "technology", "openai": "technology", "crypto": "business",
    "football": "sports", "cricket": "sports", "sports": "sports", "sport": "sports", "tennis": "sports",
    "hockey": "sports", "soccer": "sports", "olympics": "sports", "psl": "sports",
    "economy": "business", "markets": "business", "market": "business", "business": "business",
    "stocks": "business", "finance": "business", "trade": "business", "inflation": "business", "oil": "business",
    "environment": "climate", "climate": "climate", "weather": "climate", "floods": "climate",
    "energy": "climate", "warming": "climate", "pollution": "climate",
    "science": "science", "space": "science", "research": "science", "nasa": "science",
    "health": "health", "medicine": "health", "covid": "health", "dengue": "health", "hospital": "health",
    "politics": "politics", "election": "politics", "elections": "politics", "government": "politics",
    "parliament": "politics",
    "world": "world", "international": "world", "global": "world", "war": "world",
    "pakistan": "pakistan", "karachi": "pakistan", "lahore": "pakistan", "islamabad": "pakistan",
    "culture": "culture", "arts": "culture", "art": "culture", "music": "culture", "film": "culture",
    "movies": "culture", "books": "culture", "entertainment": "culture", "fashion": "culture",
}
# words that are the section themselves (generic): affect the section directly, not only a keyword
GENERIC = {"technology", "tech", "sports", "sport", "business", "climate", "science", "health", "politics",
           "world", "pakistan", "culture", "environment", "economy", "international", "entertainment", "arts"}
STOP = {"the", "a", "an", "some", "more", "less", "stuff", "news", "stories", "story", "things", "about",
        "on", "of", "me", "my", "in", "to", "any", "all", "articles", "coverage", "content", "reading"}


def _clean_topics(chunk):
    chunk = re.sub(r"[.!?]+$", "", chunk.strip().lower())
    parts = re.split(r"\s*(?:,|&|\band\b|\bor\b|\bplus\b)\s*", chunk)
    out = []
    for p in parts:
        words = [w for w in re.findall(r"[a-z0-9'\-]+", p) if w not in STOP]
        t = " ".join(words).strip()
        if t and t not in out:
            out.append(t)
    return out


def _sections_of(topics):
    secs = []
    for t in topics:
        s = LEXICON.get(t)
        if not s:
            for w in t.split():
                if w in LEXICON:
                    s = LEXICON[w]
                    break
        if s and s not in secs:
            secs.append(s)
    return secs


def _result(intent, topics=(), avoid=(), reply="", **kw):
    topics = list(topics)
    d = {"intent": intent, "topics": topics, "sections": _sections_of(list(topics) + list(avoid)),
         "avoid": list(avoid), "reply": reply}
    d.update(kw)
    return d


def parse(text: str) -> dict:
    t = (text or "").strip().lower()
    t = re.sub(r"^(hey |ok |okay |please |can you |could you |paper[, ]+)+", "", t).strip()
    if not t:
        return _result("unknown", reply="I didn't catch that. Try saying: more about climate.")
    if re.search(r"\b(surpris\w*|something (different|new|random)|wild ?card|serendipit\w*|exciting)\b", t):
        return _result("surprise", reply="Here is something outside your usual reading.")
    if re.search(r"\b(headlines?|read (me )?(the )?(news|paper|front page)|brief me|what'?s (the )?news)\b", t):
        return _result("headlines", reply="Here are today's headlines.")
    if re.search(r"\bwhy (am i|are you|is this|do i|am)\b.*\b(see|seeing|show|showing|this|that)\b|\bwhy this\b|\bexplain (this|that)\b", t):
        return _result("why", reply="Let me explain why this story was picked.")
    m = re.search(r"\b(more|less)\s+(upbeat|positive|cheerful|happy|serious|sombre|balanced|negative)\b", t) or \
        re.search(r"\b(upbeat|serious|balanced)\b", t)
    if m and re.search(r"\b(make|mood|tone|feel|be|set|more|less)\b", t):
        word = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
        neg = m.group(1) == "less" if m.lastindex and m.lastindex >= 2 else False
        if word in ("upbeat", "positive", "cheerful", "happy"):
            tone = "balanced" if neg else "upbeat"
        elif word in ("serious", "sombre", "negative"):
            tone = "balanced" if neg else "serious"
        else:
            tone = "balanced"
        return _result("tone", reply=f"Okay, switching to the {tone} tone.", tone=tone)
    if re.search(r"\b(skip|next|not interested|boring|pass)\b", t) and len(t.split()) <= 5:
        return _result("skip", reply="Skipped. I'll show you less like that.")
    m = (re.search(r"\b(?:i )?(?:don'?t|do not|never|no longer)\s+(?:really\s+)?(?:care|want|like|need|follow)(?:\s+(?:about|to see|for|any|anything about))?\s+(.+)", t)
         or re.search(r"\b(?:stop|no more|hide|block|mute|avoid|remove|ignore|exclude|drop)\s+(?:showing me\s+|me\s+)?(?:any\s+)?(?:stuff\s+|news\s+|stories\s+)?(?:about\s+|on\s+)?(.+)", t)
         or re.search(r"\bnot interested in\s+(.+)", t)
         or re.search(r"\b(?:i )?(?:hate|dislike)\s+(.+)", t))
    if m:
        topics = _clean_topics(m.group(1))
        if topics:
            return _result("avoid", avoid=topics, reply=f"Understood. I'll stop showing you {_join(topics)}.")
    m = re.search(r"\b(?:less|fewer)\s+(?:of\s+)?(?:stuff\s+|news\s+|stories\s+)?(?:about\s+|on\s+)?(.+)", t)
    if m:
        topics = _clean_topics(m.group(1))
        if topics:
            return _result("less", topics=topics, reply=f"Got it. Less {_join(topics)} from now on.")
    m = re.search(r"\b(?:more|extra)\s+(?:of\s+)?(?:stuff\s+|news\s+|stories\s+)?(?:about\s+|on\s+)?(.+)", t) or \
        re.search(r"\b(?:i'?m|i am|i'?ve become|i have become)\s+(?:really\s+|very\s+)?(?:into|interested in|a fan of|keen on|following)\s+(.+)", t) or \
        re.search(r"\b(?:i )?(?:love|like|enjoy|follow|care about|am interested in|want to (?:see|read|follow))\s+(?:reading\s+|news\s+)?(?:about\s+)?(.+)", t) or \
        re.search(r"\b(?:show me|tell me|give me|focus on|add)\s+(?:stuff\s+|news\s+|stories\s+)?(?:about\s+|on\s+)?(.+)", t)
    if m:
        topics = _clean_topics(m.group(1))
        if topics:
            return _result("more", topics=topics, reply=f"Great, more {_join(topics)} coming up.")
    return _result("unknown", reply="Sorry, I didn't understand. Try: more about AI, less sports, or read me the headlines.")


def parse_multi(text: str) -> dict:
    """Parse free text with several sentences; merge topics/avoid/sections."""
    agg = {"topics": [], "avoid": [], "sections": []}
    for sent in re.split(r"[.;\n]+|\bbut\b|,?\s*\band\b(?=\s+(?:a\s+lot\s+)?(?:more|less|fewer|no|not|nothing|skip|stop|drop)\b)", text or ""):
        if not sent.strip():
            continue
        p = parse(sent)
        agg["topics"] += [x for x in p["topics"] if x not in agg["topics"]]
        agg["avoid"] += [x for x in p["avoid"] if x not in agg["avoid"]]
        agg["sections"] += [x for x in p["sections"] if x not in agg["sections"] and x not in _sections_of(p["avoid"])]
    return agg


def _join(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _pseudo(topic):
    sec = (_sections_of([topic]) or [None])[0]
    kws = [] if topic in GENERIC else [topic]
    return {"id": None, "section": sec, "keywords": kws, "entities": []}


_CLAUSE = re.compile(r"[;.]\s*|,?\s*\b(?:and|but)\b\s*(?=(?:a\s+lot\s+|much\s+)?(?:more|less|fewer|no more|stop|drop|skip)\b)|,\s*(?=(?:more|less|fewer)\b)")


def handle(user_id: str, text: str, context_article_id: str | None = None) -> dict:
    from . import profile as P
    # "more about space and less about markets" -> one command per clause, applied in order
    clauses = [c for c in _CLAUSE.split(text or "") if c and c.strip(" ,")]
    if len(clauses) > 1:
        rs = [handle(user_id, c, context_article_id) for c in clauses]
        merged = {k: [x for r in rs for x in (r.get(k) or [])] for k in ("changes", "topics", "sections", "avoid")}
        merged.update(intent="+".join(dict.fromkeys(r["intent"] for r in rs)),
                      reply=" ".join(r["reply"] for r in rs), profile=rs[-1].get("profile"))
        for r in rs:
            if r.get("headlines"):
                merged["headlines"] = r["headlines"]
        return merged
    prof = db.get_profile(user_id)
    if prof is None:
        return {"intent": "error", "reply": "I can't find your profile.", "changes": [], "profile": None}
    p = parse(text)
    intent, changes = p["intent"], []
    out = {"intent": intent, "reply": p["reply"], "changes": changes, "topics": p["topics"],
           "sections": p["sections"], "avoid": p["avoid"]}
    if intent in ("more", "less"):
        action = intent
        for tp in p["topics"]:
            delta = P.apply_event(prof, _pseudo(tp), action, tp)
            db.log_event(user_id, None, action, tp)
            changes.append({"topic": tp, "action": action, "delta": delta})
    elif intent == "avoid":
        for tp in p["avoid"]:
            if tp in GENERIC:
                sec = LEXICON.get(tp)
                if sec:
                    prof["sections"][sec] = 0.03
                    prof.setdefault("bandit", {})[sec] = {"a": 1.0, "b": 6.0}
            else:
                if tp not in prof["avoid"]:
                    prof["avoid"].append(tp)
                prof["keywords"].pop(tp, None)
            db.log_event(user_id, None, "less", tp)
            changes.append({"topic": tp, "action": "avoid"})
    elif intent == "tone":
        prof["tone"] = p["tone"]
        db.log_event(user_id, None, "more", "tone:" + p["tone"])
        changes.append({"tone": p["tone"]})
    elif intent == "skip":
        if context_article_id:
            a = db.get_article(context_article_id)
            if a:
                changes.append({"action": "skip", "delta": P.apply_event(prof, a, "skip", None)})
                db.log_event(user_id, a["id"], "skip")
    elif intent == "headlines":
        ed = db.get_edition(f"{user_id}-{db.now_iso()[:10]}")
        if ed is None:
            eds = db.list_editions(user_id)
            ed = eds[0] if eds else None
        if ed:
            hl = [ed["lead"]["title"]] + [a["title"] for s in ed["sections"] for a in s["articles"][:1]]
            hl = [h for h in hl if h][:6]
            out["headlines"] = hl
            out["reply"] = "Here are today's headlines. " + ". ".join(f"{i+1}, {h}" for i, h in enumerate(hl[:5]))
        else:
            out["headlines"] = []
            out["reply"] = "There is no edition yet. Build today's edition first."
    elif intent == "why":
        ed = db.get_edition(f"{user_id}-{db.now_iso()[:10]}")
        if ed is None:
            eds = db.list_editions(user_id)
            ed = eds[0] if eds else None
        art = db.get_article(context_article_id) if context_article_id else None
        card = None
        if ed:
            card = ed["lead"]
            if art:
                for s in ed["sections"]:
                    for c in s["articles"]:
                        if c["id"] == art["id"]:
                            card = c
        if card:
            out["reply"] = f"The story {card['title']} is here. " + " ".join(r.rstrip('.') + "." for r in card.get("reasons", [])[:3])
            out["reasons"] = card.get("reasons", [])
    elif intent == "surprise":
        ed = db.get_edition(f"{user_id}-{db.now_iso()[:10]}")
        if ed and ed.get("serendipity"):
            out["surprise"] = ed["serendipity"]
            out["reply"] = "Here is something surprising: " + ed["serendipity"][0]["title"]
    db.save_profile(prof)
    out["profile"] = prof
    return out
