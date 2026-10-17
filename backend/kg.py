"""Knowledge graph: entity co-occurrence, story threads, related entities.
"""
from collections import Counter, defaultdict
from itertools import combinations

import networkx as nx

from . import db

_G = None


def _ents(a):
    return [e["text"] for e in a.get("entities", []) if e.get("text")]


def _graph(articles):
    G = nx.Graph()
    types = {}
    cnt = Counter()
    for a in articles:
        es = list(dict.fromkeys(_ents(a)))[:8]
        for e in a.get("entities", []):
            types.setdefault(e["text"], e.get("type", "MISC"))
        cnt.update(es)
        for x, y in combinations(es, 2):
            if G.has_edge(x, y):
                G[x][y]["weight"] += 1
            else:
                G.add_edge(x, y, weight=1)
    for n in G.nodes:
        G.nodes[n]["type"] = types.get(n, "MISC")
        G.nodes[n]["count"] = cnt[n]
    return G


def build_graph(articles, profile=None) -> dict:
    G = _graph(articles)
    if G.number_of_nodes() == 0:
        return {"nodes": [], "edges": []}
    try:
        pr = nx.pagerank(G, weight="weight")
    except Exception:
        pr = {n: 1.0 / G.number_of_nodes() for n in G}
    top = sorted(pr, key=pr.get, reverse=True)[:40]
    topset = set(top)
    mx = max(pr[n] for n in top) or 1
    liked_e = {k.lower() for k, v in ((profile or {}).get("entities") or {}).items() if v and v > 0}
    liked_k = {k.lower() for k, v in ((profile or {}).get("keywords") or {}).items() if v and v > 0}
    nodes = [{"id": n, "label": n, "type": G.nodes[n]["type"], "weight": round(pr[n] / mx, 4),
              "liked": n.lower() in liked_e or n.lower() in liked_k} for n in top]
    edges = [{"source": u, "target": v, "weight": d["weight"]}
             for u, v, d in G.edges(data=True) if u in topset and v in topset]
    return {"nodes": nodes, "edges": edges}


def story_threads(articles_today, all_articles, max_threads=4) -> list:
    sal = Counter()
    for a in articles_today:
        for e in a.get("entities", []):
            if e.get("type") in ("PERSON", "ORG", "GPE", "EVENT", "LOC", "MISC"):
                sal[e["text"]] += 1
    index = defaultdict(list)
    for a in all_articles:
        for e in set(_ents(a)):
            index[e].append(a)
    cands = []
    for ent, c in sal.items():
        arts = {a["id"]: a for a in index.get(ent, [])}
        if len(arts) < 2:
            continue
        dates = {(a.get("published") or "")[:10] for a in arts.values()}
        cands.append((len(dates) > 1, len(dates), c, len(arts), ent, arts))
    cands.sort(key=lambda x: (x[0], x[1], x[2], x[3]), reverse=True)
    threads, used = [], set()
    for _, _, _, _, ent, arts in cands:
        ids = set(arts)
        if ids and len(ids & used) / len(ids) > 0.5:
            continue
        ordered = sorted(arts.values(), key=lambda a: a.get("published") or "")[-6:]
        threads.append({"entity": ent, "articles": [
            {"id": a["id"], "title": a["title"], "date": (a.get("published") or "")[:10], "url": a.get("url", "")}
            for a in ordered]})
        used |= ids
        if len(threads) >= max_threads:
            break
    return threads


def reset_cache():
    global _G
    _G = None


def related_entities(entity, k=5) -> list:
    global _G
    if _G is None:
        _G = _graph(db.get_articles(limit=1500))
    key = next((n for n in _G if n.lower() == (entity or "").lower()), None)
    if key is None:
        return []
    nb = sorted(_G[key].items(), key=lambda kv: kv[1]["weight"], reverse=True)
    return [n for n, _ in nb[:k]]
