"""Explainable ranker: TF-IDF cosine + section weight + Thompson sampling + recency + source prior,
then avoid-filter, near-duplicate removal and MMR diversity re-ranking."""
import math
import random
import re
from datetime import datetime, timezone

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

W_SIM, W_SEC, W_TS, W_REC, W_SRC = 0.40, 0.20, 0.15, 0.20, 0.05
HALF_LIFE_H = 24.0
SRC_PRIOR = {"bbc": 1.0, "reuters": 1.0, "dawn": 0.9, "guardian": 0.9, "tribune": 0.8, "ap": 0.9}


def parse_dt(s):
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def text_of(a):
    return f"{a.get('title','')}. {a.get('title','')}. {a.get('summary','')} {(a.get('body') or '')[:1500]}"


def interest_doc(profile):
    parts = []
    for k, w in profile.get("keywords", {}).items():
        parts += [k] * max(1, int(round(w * 3)))
    for k, w in profile.get("entities", {}).items():
        parts += [k] * max(1, int(round(w * 3)))
    return " ".join(parts)


def hits_avoid(a, avoid):
    if not avoid:
        return False
    t = (a.get("title", "") + " " + a.get("summary", "")).lower()
    return any(re.search(r"\b" + re.escape(x.lower()) + r"s?\b", t) for x in avoid)


def read_minutes(a):
    words = len(((a.get("body") or "") + " " + (a.get("summary") or "")).split())
    return max(1, int(round(words / 220)))


def rank(candidates, profile, k=None, seed=None, lam=0.7, uid_salt=""):
    """Returns ArticleCards (dicts) ordered by MMR. Each card has score, reasons, read_minutes, _sec_weight."""
    rng = random.Random(seed)
    avoid = profile.get("avoid", [])
    pool = [a for a in candidates if not hits_avoid(a, avoid)]
    if not pool:
        return []
    docs = [text_of(a) for a in pool]
    idoc = interest_doc(profile)
    try:
        vec = TfidfVectorizer(stop_words="english", sublinear_tf=True, max_features=20000, min_df=1)
        X = vec.fit_transform(docs + ([idoc] if idoc else []))
        A = X[: len(pool)]
        sim_mat = (A @ A.T).toarray()
        interest = (A @ X[len(pool)].T).toarray().ravel() if idoc else np.zeros(len(pool))
    except ValueError:
        sim_mat = np.eye(len(pool))
        interest = np.zeros(len(pool))
    if interest.max() > 0:
        interest = interest / interest.max()
    newest = max(parse_dt(a.get("published")) for a in pool)
    # trend: how many distinct sources carry a similar story
    trend = []
    for i, a in enumerate(pool):
        srcs = {pool[j].get("source") for j in np.where(sim_mat[i] > 0.35)[0]}
        trend.append(len(srcs))
    pos_tone = profile.get("tone", "balanced")
    cards = []
    for i, a in enumerate(pool):
        sec = a.get("section", "world")
        sw = profile["sections"].get(sec, 0.2)
        b = profile.get("bandit", {}).get(sec, {"a": 1, "b": 1})
        ts = rng.betavariate(max(b["a"], 0.1), max(b["b"], 0.1))
        age_h = max(0.0, (newest - parse_dt(a.get("published"))).total_seconds() / 3600)
        rec = 0.5 ** (age_h / HALF_LIFE_H)
        src = SRC_PRIOR.get((a.get("source") or "").lower().split()[0] if a.get("source") else "", 0.6)
        score = W_SIM * interest[i] + W_SEC * sw + W_TS * ts + W_REC * rec + W_SRC * src
        sent = (a.get("sentiment") or {}).get("label")
        if pos_tone == "upbeat":
            score += 0.08 if sent == "positive" else (-0.06 if sent == "negative" else 0)
        elif pos_tone == "serious":
            score += 0.04 if sent == "negative" else 0
        score += min(0.06, 0.02 * (trend[i] - 1))
        reasons = []
        liked_ents = [e["text"] for e in a.get("entities", []) if profile.get("entities", {}).get(e["text"], 0) >= 0.2]
        liked_kws = [x for x in a.get("keywords", []) if profile.get("keywords", {}).get(x.lower(), 0) >= 0.3]
        if liked_ents:
            reasons.append(f"Mentions '{liked_ents[0]}' which you liked")
        elif liked_kws:
            reasons.append(f"Matches your interest in '{liked_kws[0]}'")
        if sw >= 0.5:
            reasons.append(f"Because you follow {sec.title()}")
        if trend[i] >= 3:
            reasons.append(f"Trending across {trend[i]} sources")
        if rec > 0.85:
            reasons.append("Fresh this morning")
        if not reasons:
            reasons.append("Top story in the pool" if score > 0.6 else f"A solid {sec.title()} read")
        cards.append(dict(a, score=round(float(score), 4), reasons=reasons, read_minutes=read_minutes(a),
                          _i=i, _trend=trend[i]))
    # dedupe near-duplicates (greedy by score)
    order = sorted(cards, key=lambda c: -c["score"])
    kept = []
    for c in order:
        if all(sim_mat[c["_i"], d["_i"]] <= 0.8 for d in kept):
            kept.append(c)
    # MMR re-rank
    smax = max(c["score"] for c in kept) or 1.0
    remaining, sel = list(kept), []
    k = k or len(kept)
    while remaining and len(sel) < k:
        best, bv = None, -1e9
        for c in remaining:
            red = max((sim_mat[c["_i"], s["_i"]] for s in sel), default=0.0)
            v = lam * (c["score"] / smax) - (1 - lam) * red
            if v > bv:
                best, bv = c, v
        sel.append(best)
        remaining.remove(best)
    return sel


def serendipity(ranked, profile, exclude_ids=(), n=2, eps=0.3, seed=None):
    """Epsilon-greedy exploration: low-weight sections, ranked by global salience (trend + base score)."""
    rng = random.Random(seed)
    low = [c for c in ranked if c["id"] not in exclude_ids and profile["sections"].get(c["section"], 0.2) < 0.4]
    low.sort(key=lambda c: -(c["_trend"] + c["score"]))
    picks, seen = [], set()
    while low and len(picks) < n:
        c = rng.choice(low) if rng.random() < eps else low[0]
        low.remove(c)
        if c["section"] in seen and len(low) > 0 and any(x["section"] not in seen for x in low):
            continue
        seen.add(c["section"])
        c = dict(c)
        c["reasons"] = [f"Exploring: you haven't read {c['section'].title()} lately"] + \
                       ([f"Trending across {c['_trend']} sources"] if c["_trend"] >= 2 else [])
        picks.append(c)
    return picks


def clean(card):
    return {k: v for k, v in card.items() if not k.startswith("_")}
