"""NLP enrichment: section classifier, NER, keywords, sentiment.
# Ported from NAaaS: NAaaS-python/app/services/sentiment_service.py (TextBlob+VADER hybrid)
# Ported from NAaaS: graph-building-service-newsnet/services/entity/entity_extractor.py (spaCy NER)
# Ported from NAaaS: graph-building-service-newsnet/services/entity/entity_normalizer.py
# Ported from NAaaS: NAaaS-python/app/services/topic_service.py (TF-IDF keywords)
"""
import re
from collections import Counter

from .db import SECTIONS

_nlp = None
_nlp_tried = False
_vader = None
_ENT_TYPES = {"PERSON", "ORG", "GPE", "LOC", "EVENT", "NORP", "FAC"}


def _get_nlp():
    global _nlp, _nlp_tried
    if not _nlp_tried:
        _nlp_tried = True
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm", disable=["parser", "lemmatizer", "textcat"])
        except Exception:
            _nlp = None
    return _nlp


# ---------------- sentiment ----------------
def sentiment(text: str) -> dict:
    global _vader
    text = (text or "")[:1500]
    try:
        from textblob import TextBlob
        tb = (TextBlob(text).sentiment.polarity + 1) / 2
    except Exception:
        tb = 0.5
    try:
        if _vader is None:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            _vader = SentimentIntensityAnalyzer()
        vd = (_vader.polarity_scores(text)["compound"] + 1) / 2
    except Exception:
        vd = 0.5
    s = (tb + vd) / 2
    label = "negative" if s < 0.4 else "neutral" if s < 0.6 else "positive"
    return {"score": round(s, 4), "label": label}


# ---------------- entities ----------------
_TITLES = re.compile(r"^(mr|mrs|ms|dr|prof|president|prime minister|pm|sir|chief|minister|gen|general|justice)\.?\s+", re.I)
_STOP_ENT = {"the", "a", "an", "this", "that", "monday", "tuesday", "wednesday", "thursday",
             "friday", "saturday", "sunday", "january", "february", "march", "april", "may",
             "june", "july", "august", "september", "october", "november", "december", "ai",
             "show hn", "ask hn", "hn", "read more", "photo", "express tribune", "the express tribune"}
_ALIASES = {"us": "United States", "u.s.": "United States", "usa": "United States",
            "u.s": "United States", "america": "United States", "uk": "United Kingdom",
            "u.k.": "United Kingdom", "britain": "United Kingdom", "eu": "European Union",
            "un": "United Nations", "pm": "Prime Minister"}


def normalise_entity(text: str) -> str:
    t = re.sub(r"\s+", " ", text.replace("’s", "").replace("'s", "")).strip(" .,;:-\"'()")
    t = _TITLES.sub("", t).strip()
    t = re.sub(r"^(the)\s+", "", t, flags=re.I)
    return _ALIASES.get(t.lower(), t)


_CAP = re.compile(r"\b(?:[A-Z][a-z]+|[A-Z]{2,})(?:\s+(?:of\s+|de\s+)?(?:[A-Z][a-z]+|[A-Z]{2,}))*")


def _regex_ents(text):
    out = []
    for m in _CAP.finditer(text):
        t = m.group(0)
        if len(t) > 2 and m.start() != 0 or " " in t:
            out.append({"text": t, "type": "ORG" if t.isupper() else "MISC"})
    return out


_TYPE_MAP = {"NORP": "ORG", "FAC": "LOC"}


def _clean_ents(raw):
    seen, out = set(), []
    for text, typ in raw:
        t = normalise_entity(text)
        k = t.lower()
        if len(t) < 3 or k in _STOP_ENT or k in seen or t.isdigit() or not re.search(r"[A-Za-z]", t):
            continue
        seen.add(k)
        out.append({"text": t, "type": _TYPE_MAP.get(typ, typ)})
    return out[:12]


def _doc_ents(doc):
    return _clean_ents([(e.text, e.label_) for e in doc.ents if e.label_ in _ENT_TYPES])


def _art_text(a):
    body = a.get("body") or ""
    return (f"{a.get('title', '')}. {a.get('summary', '')}. {body}")[:1500]


# ---------------- keywords ----------------
_STOPW = None


def _stop():
    global _STOPW
    if _STOPW is None:
        from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
        _STOPW = set(ENGLISH_STOP_WORDS) | {"said", "says", "new", "also", "year", "years", "just",
                                            "like", "mr", "pti", "tribune", "express", "reuters",
                                            "hn", "https", "com", "http", "www", "comments", "article",
                                            "points", "told", "according", "day", "week", "time"}
    return _STOPW


def batch_keywords(texts, k=6):
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        vec = TfidfVectorizer(stop_words=list(_stop()), ngram_range=(1, 2), min_df=1, max_df=0.5,
                              sublinear_tf=True, token_pattern=r"(?u)\b[A-Za-z][A-Za-z\-]{2,}\b")
        X = vec.fit_transform(texts)
        vocab = vec.get_feature_names_out()
        res = []
        for i in range(X.shape[0]):
            row = X.getrow(i)
            idx = row.indices[row.data.argsort()[::-1]]
            chosen = []
            for j in idx:
                w = vocab[j]
                if any(w in c or c in w for c in chosen):
                    continue
                chosen.append(w)
                if len(chosen) >= k:
                    break
            res.append(chosen)
        return res
    except Exception:
        out = []
        for t in texts:
            ws = [w for w in re.findall(r"[a-z]{4,}", t.lower()) if w not in _stop()]
            out.append([w for w, _ in Counter(ws).most_common(k)])
        return out


def batch_topics(articles, n=6):
    """NMF topic labels over a batch (topic_service style)."""
    try:
        from sklearn.decomposition import NMF
        from sklearn.feature_extraction.text import TfidfVectorizer
        texts = [f"{a.get('title','')} {a.get('summary','')}" for a in articles]
        vec = TfidfVectorizer(stop_words=list(_stop()), max_df=0.5, min_df=2)
        X = vec.fit_transform(texts)
        m = NMF(n_components=min(n, max(2, X.shape[0] // 5)), init="nndsvd", max_iter=200).fit(X)
        vocab = vec.get_feature_names_out()
        return [[vocab[i] for i in c.argsort()[::-1][:4]] for c in m.components_]
    except Exception:
        return []


# ---------------- section classifier ----------------
LEX = {
    "world": "war ceasefire un united nations nato eu european union china russia ukraine israel gaza palestine iran "
             "india usa united states trump biden putin xi embassy diplomat sanctions refugee migrants border treaty summit "
             "britain london paris washington beijing moscow tehran middle east africa europe asia syria lebanon afghanistan "
             "president prime minister foreign",
    "pakistan": "pakistan pakistani karachi lahore islamabad peshawar quetta balochistan sindh punjab khyber pakhtunkhwa "
                "rawalpindi gilgit kashmir rupee psx sbp pti pmln ppp shehbaz sharif imran khan nawaz zardari ptv isi "
                "tribune faisalabad multan hyderabad lyari",
    "politics": "election parliament senate congress vote voters party government minister cabinet coalition opposition "
                "law bill legislation court supreme judge verdict campaign mp lawmakers democracy policy president "
                "constitution amendment assembly speaker poll ballot",
    "business": "economy economic market stocks shares inflation gdp bank budget tax trade company profit revenue imf "
                "investors investment oil price prices earnings finance financial exports imports tariff interest rate "
                "currency dollar growth industry sales ceo startup billion",
    "technology": "tech software ai artificial intelligence app apps google apple microsoft meta openai chip chips "
                  "processor startup cyber hack hacker data internet linux code developer programming robot smartphone "
                  "iphone android github open source browser cloud algorithm gpu nvidia computing computer security "
                  "privacy gadget",
    "science": "scientists research study space nasa planet galaxy telescope physics chemistry biology species fossil "
               "astronomy mars moon rocket satellite quantum particle discovery experiment genome universe asteroid "
               "evolution researchers laboratory",
    "health": "health hospital doctor doctors disease virus cancer vaccine medical patients drug drugs treatment "
              "covid mental dengue polio outbreak who medicine surgery diabetes obesity nutrition clinic nhs symptoms "
              "pandemic",
    "climate": "climate warming carbon emissions flood floods monsoon heatwave drought wildfire environment pollution "
               "renewable solar wind energy glacier biodiversity deforestation cop29 cop30 weather rainfall temperature "
               "sea level fossil fuels net zero green smog",
    "sports": "cricket football match team players player coach league cup tournament goal wicket innings runs score "
              "olympic olympics tennis golf f1 formula fifa icc psl bcci champion final win won defeat season stadium "
              "batting bowler captain nba athlete medal premier",
    "culture": "film movie cinema music album artist art museum book books novel author theatre festival fashion "
               "celebrity actor actress singer drama series netflix tv television exhibition gallery culture heritage "
               "food travel review concert dance poetry",
}
_LEXSETS = {s: set(v.split()) for s, v in LEX.items()}
_HINT = {"business": "business", "sports": "sports", "sport": "sports", "international": "world", "world": "world",
         "national": "pakistan", "karachi": "pakistan", "lahore": "pakistan", "balochistan": "pakistan",
         "azad-jamu-kashmir-gilgit": "pakistan", "islamabad": "pakistan", "pakistan": "pakistan",
         "technology": "technology", "tech": "technology", "science": "science", "health": "health",
         "climate": "climate", "environment": "climate", "culture": "culture", "politics": "politics",
         "arts": "culture", "entertainment": "culture", "life": "culture", "lifestyle": "culture"}


def classify_section(title, text, hint=None) -> str:
    h = (hint or "").lower().strip()
    hinted = _HINT.get(h)
    blob = f"{title or ''} {title or ''} {text or ''}".lower()[:2500]
    toks = re.findall(r"[a-z0-9\-]+", blob)
    cnt = Counter(toks)
    bigr = Counter(" ".join(p) for p in zip(toks, toks[1:]))
    scores = {}
    for s, words in _LEXSETS.items():
        sc = 0.0
        for w in words:
            sc += cnt.get(w, 0) if " " not in w else bigr.get(w, 0)
        scores[s] = sc
    # multi-word lexicon phrases
    for s, phrases in LEX.items():
        pass
    if hinted:
        # strong hint: only override with text if hint is generic ('world'/'pakistan') and another section wins big
        scores[hinted] += 3
        if hinted == "pakistan":
            scores["pakistan"] += 1
    best = max(scores, key=scores.get)
    if scores[best] <= 0:
        return hinted or "world"
    return best


# ---------------- enrich ----------------
def _finish(a, ents, kws):
    a["entities"] = ents
    a["keywords"] = kws
    a["sentiment"] = sentiment(_art_text(a))
    if not a.get("section") or a["section"] not in SECTIONS or a.get("_reclassify"):
        a["section"] = classify_section(a.get("title"), f"{a.get('summary','')} {a.get('body','')[:800]}",
                                        a.get("_hint"))
    a.pop("_hint", None)
    a.pop("_reclassify", None)
    return a


def enrich(article: dict) -> dict:
    return enrich_batch([article])[0]


def enrich_batch(articles: list) -> list:
    if not articles:
        return articles
    texts = [_art_text(a) for a in articles]
    nlp = _get_nlp()
    if nlp is not None:
        ents = [_doc_ents(d) for d in nlp.pipe(texts, batch_size=64)]
    else:
        ents = [_clean_ents([(e["text"], e["type"]) for e in _regex_ents(t)]) for t in texts]
    kws = batch_keywords(texts)
    for a, e, k in zip(articles, ents, kws):
        _finish(a, e, k)
    return articles
