"""SQLite storage shared by every module. See docs/CONTRACT.md for shapes."""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "paper.db"
SECTIONS = ["world", "pakistan", "politics", "business", "technology",
            "science", "health", "climate", "sports", "culture"]

_lock = threading.Lock()
_JSON_COLS = ("entities", "keywords", "sentiment")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS articles(
          id TEXT PRIMARY KEY, title TEXT, summary TEXT, body TEXT, url TEXT, source TEXT,
          section TEXT, published TEXT, image TEXT, entities TEXT, keywords TEXT,
          sentiment TEXT, origin TEXT, fetched TEXT);
        CREATE INDEX IF NOT EXISTS ix_art_pub ON articles(published);
        CREATE TABLE IF NOT EXISTS profiles(user_id TEXT PRIMARY KEY, data TEXT);
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, article_id TEXT,
          action TEXT, value TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS editions(id TEXT PRIMARY KEY, user_id TEXT, date TEXT, data TEXT);
        """)


def _row_to_article(r) -> dict:
    d = dict(r)
    for k in _JSON_COLS:
        d[k] = json.loads(d[k]) if d.get(k) else ([] if k != "sentiment" else {})
    return d


def upsert_articles(articles: list) -> int:
    rows = []
    for a in articles:
        rows.append((a["id"], a.get("title", ""), a.get("summary", ""), a.get("body", ""),
                     a.get("url", ""), a.get("source", ""), a.get("section", "world"),
                     a.get("published") or now_iso(), a.get("image"),
                     json.dumps(a.get("entities", [])), json.dumps(a.get("keywords", [])),
                     json.dumps(a.get("sentiment", {})), a.get("origin", "live"), now_iso()))
    with _lock, conn() as c:
        c.executemany("INSERT OR REPLACE INTO articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def get_articles(since_iso: str | None = None, limit: int = 2000, ids: list | None = None) -> list:
    with conn() as c:
        if ids:
            q = f"SELECT * FROM articles WHERE id IN ({','.join('?' * len(ids))})"
            return [_row_to_article(r) for r in c.execute(q, ids)]
        if since_iso:
            rs = c.execute("SELECT * FROM articles WHERE published >= ? ORDER BY published DESC LIMIT ?",
                           (since_iso, limit))
        else:
            rs = c.execute("SELECT * FROM articles ORDER BY published DESC LIMIT ?", (limit,))
        return [_row_to_article(r) for r in rs]


def get_article(aid: str) -> dict | None:
    got = get_articles(ids=[aid])
    return got[0] if got else None


def count_articles() -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM articles").fetchone()[0]


def save_profile(p: dict):
    p["updated"] = now_iso()
    with _lock, conn() as c:
        c.execute("INSERT OR REPLACE INTO profiles VALUES (?,?)", (p["user_id"], json.dumps(p)))


def get_profile(uid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT data FROM profiles WHERE user_id=?", (uid,)).fetchone()
        return json.loads(r[0]) if r else None


def list_profiles() -> list:
    with conn() as c:
        return [json.loads(r[0]) for r in c.execute("SELECT data FROM profiles")]


def log_event(user_id: str, article_id: str | None, action: str, value=None):
    with _lock, conn() as c:
        c.execute("INSERT INTO events(user_id,article_id,action,value,ts) VALUES (?,?,?,?,?)",
                  (user_id, article_id, action, None if value is None else str(value), now_iso()))


def get_events(user_id: str, limit: int = 5000) -> list:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM events WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))]


def save_edition(e: dict):
    with _lock, conn() as c:
        c.execute("INSERT OR REPLACE INTO editions VALUES (?,?,?,?)",
                  (e["id"], e["user_id"], e["date"], json.dumps(e)))


def get_edition(eid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT data FROM editions WHERE id=?", (eid,)).fetchone()
        return json.loads(r[0]) if r else None


def list_editions(uid: str) -> list:
    with conn() as c:
        return [json.loads(r[0]) for r in c.execute(
            "SELECT data FROM editions WHERE user_id=? ORDER BY date DESC", (uid,))]


init()
