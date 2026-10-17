# The Morning Paper — build contract

Every module owner MUST honour these names/shapes. Do not edit files you don't own;
if you need something from another module, code against this contract.

Repo: `/home/usaid/Desktop/morning-paper`  ·  venv: `.venv/bin/python`  ·  server port **8900**
Run: `.venv/bin/uvicorn backend.app:app --port 8900` from repo root (backend is a package).
Storage: SQLite at `data/paper.db` via `backend/db.py` (owned by orchestrator, already written).
NO paid LLM API keys are available — everything is classical AI / NLP / IR / graphs.

## NLP building blocks
- Sentiment: TextBlob+VADER hybrid.
- Topics: TF-IDF + NMF.
- NER: spaCy `en_core_web_sm`, with entity normalisation.
- Story chains: entity-overlap chains over time.
- Archive corpus: `data/archive/<year>/<YYYY-MM-DD>/<section>.csv` (override with `ARCHIVE_ROOT`)
  columns `Header,Summary,Detail,Link,Category,CreationDate,Pic_url` (Express Tribune).

## Sections (closed vocabulary)
`SECTIONS = ["world","pakistan","politics","business","technology","science","health","climate","sports","culture"]`
(defined in `backend/db.py`).

## Article dict (DB table `articles`, returned by `db.get_articles`)
```
id: str (sha1 of url, 16 hex)   title  summary  body  url  source  section (in SECTIONS)
published: ISO str   image: str|None   entities: [{"text","type"}]   keywords: [str]
sentiment: {"score":0..1,"label":"negative|neutral|positive"}   origin: "live"|"archive"
```
ArticleCard = Article + `score: float`, `reasons: [str]` (human "why you're seeing this"), `read_minutes: int`.

## Profile dict (`db.get_profile/save_profile`)
```
user_id, name, city, sections:{section:weight 0..1}, keywords:{kw:weight}, entities:{name:weight},
avoid:[kw], tone:"balanced"|"upbeat"|"serious", reading_minutes:int, created, updated,
bandit:{section:{"a":float,"b":float}}   # Beta params for Thompson sampling
history:[{"ts","top":[[name,weight],...]}]  # snapshots after each learning update (for insights)
```

## Events (`db.log_event(user_id, article_id, action, value=None)`)
actions: `click` (opened original), `read` (dwell secs in value), `like`, `dislike`, `skip`,
`more` / `less` (voice, article_id may be None and value = topic text), `pdf`.

## Edition dict (`db.save_edition/get_edition`), id = f"{user_id}-{YYYY-MM-DD}"
```
id, user_id, date, generated_at, title (e.g. "The Ali Morning Post"), edition_no:int,
greeting: str, lead: ArticleCard, sections:[{"name":str,"articles":[ArticleCard]}],
briefs:[ArticleCard] (short "in brief" column), serendipity:[ArticleCard] (exploration picks, reasons say why),
threads:[{"entity":str,"articles":[{"id","title","date","url"}]}]  (story chains),
kg:{"nodes":[{"id","label","type","weight","liked":bool}],"edges":[{"source","target","weight"}]},
mood:{"positive":n,"neutral":n,"negative":n}, word_of_day? (optional), stats:{candidates,sources,events_learned}
```

## Module ownership & function signatures
- `backend/db.py` — orchestrator (done).
- `backend/nlp.py` + `backend/ingest.py` + `backend/kg.py` — **Agent Ingest/KG**
  - `nlp.enrich(article: dict) -> dict` (fills section if missing, entities, keywords, sentiment)
  - `nlp.classify_section(title, text, hint=None) -> str`
  - `ingest.refresh(max_per_feed=25, archive_days=3) -> {"live":n,"archive":n,"total":n}` (live RSS + news archive; must work offline via archive)
  - `kg.build_graph(articles, profile=None) -> {"nodes","edges"}`  (entity co-occurrence, networkx, PageRank weights, top ~40 nodes)
  - `kg.story_threads(articles_today, all_articles, max_threads=4) -> [threads]`
  - `kg.related_entities(entity, k=5) -> [str]` (neighbours in global KG; used for interest expansion)
- `backend/profile.py`, `backend/ranker.py`, `backend/edition.py`, `backend/voice.py`, `backend/app.py` — **Agent Brain/API**
  - `voice.parse(text) -> {"intent", "topics":[...], "sections":[...], "avoid":[...], "reply"}` rule-based grammar
  - Ranking = TF-IDF content similarity + section weights + Thompson sampling + recency + MMR diversity + avoid filter; serendipity slot.
  - Learning = Rocchio-style profile update + Beta bandit update from events.
  - API endpoints below.
- `backend/pdf.py` — **Agent PDF**: `render_pdf(edition: dict) -> bytes` (reportlab, broadsheet layout).
- `frontend/` (index.html, app.js, style.css; vanilla JS, no build) — **Agent Frontend**.

## HTTP API (FastAPI, `backend/app.py`)
```
GET  /                       -> frontend/index.html ; static at /static -> frontend/
POST /api/users              {name, city?, sections:[], keywords:[], avoid:[], free_text?, tone?, reading_minutes?} -> profile
GET  /api/users              -> [profile summaries]
GET  /api/users/{uid}/profile -> profile
POST /api/ingest/refresh     -> counts
POST /api/users/{uid}/editions/today?force=0|1 -> Edition (auto-refreshes ingest if DB empty)
GET  /api/users/{uid}/editions -> [{id,date,title,edition_no,count}]
GET  /api/editions/{eid}     -> Edition
GET  /api/editions/{eid}/pdf -> application/pdf (attachment)
POST /api/events             {user_id, article_id?, action, value?} -> {ok, profile_delta}
POST /api/voice              {user_id, text} -> {intent, reply, changes, profile}
GET  /api/users/{uid}/insights -> {top_sections, top_keywords, history, event_counts, bandit}
GET  /r/{eid}/{aid}          -> logs click, 302 to original url
GET  /api/kg?user_id=        -> global KG for the user (kg.build_graph over last 3 days)
```
