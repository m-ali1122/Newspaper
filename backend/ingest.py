"""Ingest: live RSS + news archive CSVs -> enrich -> db."""
import os
import csv
import hashlib
import html
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import db, nlp

csv.field_size_limit(10_000_000)
ARCHIVE_ROOT = Path(os.environ.get("ARCHIVE_ROOT", "data/archive"))

# name -> (url, source, section hint or None)
FEEDS = {
    "bbc_world": ("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC News", "world"),
    "bbc_business": ("https://feeds.bbci.co.uk/news/business/rss.xml", "BBC News", "business"),
    "bbc_tech": ("https://feeds.bbci.co.uk/news/technology/rss.xml", "BBC News", "technology"),
    "bbc_science": ("https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "BBC News", "science"),
    "bbc_health": ("https://feeds.bbci.co.uk/news/health/rss.xml", "BBC News", "health"),
    "bbc_sport": ("https://feeds.bbci.co.uk/sport/rss.xml", "BBC Sport", "sports"),
    "guardian_world": ("https://www.theguardian.com/world/rss", "The Guardian", "world"),
    "guardian_env": ("https://www.theguardian.com/environment/rss", "The Guardian", "climate"),
    "guardian_culture": ("https://www.theguardian.com/culture/rss", "The Guardian", "culture"),
    "guardian_sport": ("https://www.theguardian.com/sport/rss", "The Guardian", "sports"),
    "ars": ("https://feeds.arstechnica.com/arstechnica/index", "Ars Technica", "technology"),
    "sciencedaily": ("https://www.sciencedaily.com/rss/top/science.xml", "ScienceDaily", "science"),
    "nasa": ("https://www.nasa.gov/news-release/feed/", "NASA", "science"),
    "dawn": ("https://www.dawn.com/feeds/home", "Dawn", "pakistan"),
    "tribune": ("https://tribune.com.pk/feed/home", "The Express Tribune", "pakistan"),
    "aljazeera": ("https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera", "world"),
    "hn": ("https://hnrss.org/frontpage", "Hacker News", "technology"),
}
# feeds whose hint is a loose default; let text decide (classifier treats hint as soft bonus)
_TAG = re.compile(r"<[^>]+>")


def _clean(s):
    s = html.unescape(_TAG.sub(" ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def _aid(url):
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def _iso(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if t:
        return datetime(*t[:6], tzinfo=timezone.utc).isoformat(timespec="seconds")
    return db.now_iso()


def _image(e):
    for key in ("media_content", "media_thumbnail"):
        for m in e.get(key, []) or []:
            if m.get("url"):
                return m["url"]
    for enc in e.get("enclosures", []) or []:
        if (enc.get("type") or "").startswith("image") and enc.get("href"):
            return enc["href"]
    for l in e.get("links", []) or []:
        if (l.get("type") or "").startswith("image") and l.get("href"):
            return l["href"]
    m = re.search(r'<img[^>]+src="([^"]+)"', e.get("summary", "") or "")
    return m.group(1) if m else None


def _fetch_feed(item):
    name, (url, source, hint) = item
    try:
        import feedparser
        import httpx
        r = httpx.get(url, timeout=8, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (MorningPaper/1.0)"})
        r.raise_for_status()
        fp = feedparser.parse(r.content)
    except Exception:
        return []
    return [(e, source, hint) for e in fp.entries]


def fetch_live(max_per_feed=25):
    arts, seen = [], set()
    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(_fetch_feed, FEEDS.items()))
    for entries in results:
        for e, source, hint in entries[:max_per_feed]:
            url = e.get("link")
            title = _clean(e.get("title"))
            if not url or not title or url in seen:
                continue
            seen.add(url)
            summ = _clean(e.get("summary") or "")
            if source == "Hacker News":
                summ = ""
            arts.append({"id": _aid(url), "title": title, "summary": summ[:600], "body": "", "url": url,
                         "source": source, "section": None, "_hint": hint, "published": _iso(e),
                         "image": _image(e), "origin": "live"})
    return arts


def _archive_dates(n):
    dates = []
    if not ARCHIVE_ROOT.exists():
        return dates
    for y in sorted((p for p in ARCHIVE_ROOT.iterdir() if p.is_dir()), reverse=True):
        for d in sorted((p for p in y.iterdir() if p.is_dir()), reverse=True):
            dates.append(d)
            if len(dates) >= n:
                return dates
    return dates


def fetch_archive(archive_days=3, per_day=150):
    arts, seen = [], set()
    for d in _archive_dates(archive_days):
        day = []
        for f in sorted(d.glob("*.csv")):
            cat = f.stem
            try:
                with open(f, newline="", encoding="utf-8", errors="replace") as fh:
                    for r in csv.DictReader(fh):
                        url = (r.get("Link") or "").strip()
                        title = _clean(r.get("Header"))
                        if not url or not title or url in seen:
                            continue
                        seen.add(url)
                        body = _clean(r.get("Detail"))
                        summ = _clean(r.get("Summary")) or body[:300]
                        pub = (r.get("CreationDate") or "").strip() or d.name
                        try:
                            pub = datetime.fromisoformat(pub.replace("Z", "+00:00")).isoformat(timespec="seconds")
                        except Exception:
                            pub = f"{d.name}T08:00:00+00:00"
                        day.append({"id": _aid(url), "title": title, "summary": summ[:600], "body": body[:2000],
                                    "url": url, "source": "The Express Tribune (archive)", "section": None,
                                    "_hint": (r.get("Category") or cat).lower() if cat not in ("back", "front", "back-page", "front-page") else None,
                                    "published": pub, "image": (r.get("Pic_url") or "").strip() or None,
                                    "origin": "archive"})
            except Exception:
                continue
        arts.extend(day[:per_day * 3])
    return arts


def refresh(max_per_feed=25, archive_days=3) -> dict:
    live = []
    try:
        live = fetch_live(max_per_feed)
    except Exception:
        live = []
    arch = fetch_archive(archive_days) if archive_days else []
    allarts = live + arch
    if allarts:
        nlp.enrich_batch(allarts)
        db.upsert_articles(allarts)
    return {"live": len(live), "archive": len(arch), "total": len(allarts)}


if __name__ == "__main__":
    t = time.time()
    print(refresh(), f"{time.time()-t:.1f}s", "db:", db.count_articles())
