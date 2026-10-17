"""Broadsheet PDF renderer for The Morning Paper. render_pdf(edition) -> bytes."""
import io
import re
import html as _html
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.lib.pagesizes import A3
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
                                KeepTogether, Table, TableStyle, Image, FrameBreak,
                                NextPageTemplate, HRFlowable, Flowable)

INK = colors.HexColor("#1a1a1a")
GREY = colors.HexColor("#666666")
RED = colors.HexColor("#8a1c1c")
PAPER = colors.HexColor("#faf6ec")

# ---- fonts -------------------------------------------------------------
_FD = "/usr/share/fonts/truetype/liberation/"
_DJ = "/usr/share/fonts/truetype/dejavu/"
SERIF, SERIF_B, SERIF_I, SERIF_BI = "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic"
TITLE_FONT = "Times-Bold"
try:
    pdfmetrics.registerFont(TTFont("LSerif", _FD + "LiberationSerif-Regular.ttf"))
    pdfmetrics.registerFont(TTFont("LSerif-B", _FD + "LiberationSerif-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("LSerif-I", _FD + "LiberationSerif-Italic.ttf"))
    pdfmetrics.registerFont(TTFont("LSerif-BI", _FD + "LiberationSerif-BoldItalic.ttf"))
    pdfmetrics.registerFontFamily("LSerif", normal="LSerif", bold="LSerif-B",
                                  italic="LSerif-I", boldItalic="LSerif-BI")
    SERIF, SERIF_B, SERIF_I, SERIF_BI = "LSerif", "LSerif-B", "LSerif-I", "LSerif-BI"
    pdfmetrics.registerFont(TTFont("DJSerif-B", _DJ + "DejaVuSerif-Bold.ttf"))
    TITLE_FONT = "DJSerif-B"
except Exception:
    pass


# ---- helpers -----------------------------------------------------------
def _clean(s, limit=None):
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    s = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0].rstrip(",;:. ") + "…"
    return s


def _e(s, limit=None):
    return _clean(s, limit).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _short_url(u):
    u = _clean(u)
    u = re.sub(r"^https?://(www\.)?", "", u)
    return u if len(u) <= 48 else u[:45] + "..."


def _fmt_date(d):
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").strftime("%A, %-d %B %Y")
    except Exception:
        return _clean(d) or datetime.now().strftime("%A, %-d %B %Y")


def _fetch_image(url, maxw, maxh):
    if not url or not str(url).startswith("http"):
        return None
    try:
        import httpx
        r = httpx.get(url, timeout=4, follow_redirects=True)
        r.raise_for_status()
        data = r.content
        ir = ImageReader(io.BytesIO(data))
        w, h = ir.getSize()
        if not w or not h:
            return None
        sc = min(maxw / w, maxh / h)
        return Image(io.BytesIO(data), width=w * sc, height=h * sc)
    except Exception:
        return None


def _S(name, **kw):
    base = dict(fontName=SERIF, fontSize=9, leading=11, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


ST = {
    "body": _S("body", alignment=TA_JUSTIFY, spaceAfter=2, hyphenationLang=None),
    "meta": _S("meta", fontName=SERIF_I, fontSize=7.5, leading=9, textColor=GREY),
    "link": _S("link", fontSize=7, leading=8.5, textColor=RED, spaceAfter=7),
    "h1": _S("h1", fontName=SERIF_B, fontSize=14, leading=15.5, spaceAfter=2),
    "h2": _S("h2", fontName=SERIF_B, fontSize=11.5, leading=12.5, spaceAfter=2),
    "h3": _S("h3", fontName=SERIF_B, fontSize=10, leading=11, spaceAfter=2),
    "sec": _S("sec", fontName=SERIF_B, fontSize=11, leading=13, textColor=colors.white,
              alignment=TA_CENTER),
    "boxh": _S("boxh", fontName=SERIF_B, fontSize=10, leading=12, alignment=TA_CENTER,
               spaceAfter=3),
    "small": _S("small", fontSize=8, leading=9.5, spaceAfter=3),
    "smalli": _S("smalli", fontName=SERIF_I, fontSize=7.5, leading=9, textColor=GREY, spaceAfter=3),
    "lead_h": _S("lead_h", fontName=SERIF_B, fontSize=30, leading=33, spaceAfter=4),
    "lead_s": _S("lead_s", fontName=SERIF, fontSize=12, leading=15, spaceAfter=4,
                 alignment=TA_JUSTIFY),
    "lead_m": _S("lead_m", fontName=SERIF_B, fontSize=8.5, leading=10.5, spaceAfter=2,
                 textColor=RED),
    "greet": _S("greet", fontName=SERIF_I, fontSize=11, leading=13, alignment=TA_CENTER),
}


def _sec_header(name):
    t = Table([[Paragraph(_e(name).upper(), ST["sec"])]], colWidths=["100%"])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), INK),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, 0), (-1, 0), 2, INK),
    ]))
    return [Spacer(1, 4), t, HRFlowable(width="100%", thickness=0.5, color=INK, spaceBefore=1,
                                       spaceAfter=4)]


def _article(a, rank):
    out = []
    style = ST["h2"] if rank == 0 else ST["h3"]
    title = _e(a.get("title")) or "Untitled"
    out.append(Paragraph(title, style))
    summ = _e(a.get("summary") or a.get("body"), 600)
    if summ:
        out.append(Paragraph(summ, ST["body"]))
    bits = [_e(a.get("source"))]
    if a.get("read_minutes"):
        bits.append("%s min read" % _e(a.get("read_minutes")))
    meta = " · ".join(b for b in bits if b)
    if meta:
        out.append(Paragraph(meta, ST["meta"]))
    url = _clean(a.get("url"))
    if url:
        safe = url.replace("&", "&amp;").replace('"', "%22").replace("<", "%3C").replace(">", "%3E")
        out.append(Paragraph('<a href="%s" color="#8a1c1c">%s</a>' % (safe, _e(_short_url(url))),
                             ST["link"]))
    else:
        out.append(Spacer(1, 6))
    return KeepTogether(out)


def _box(title, items, width=None):
    """items: list of flowables; returns a bordered table."""
    rows = [[Paragraph(_e(title).upper(), ST["boxh"])]] + [[i] for i in items]
    t = Table(rows, colWidths=[width] if width else None)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.2, INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1ead6")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return [Spacer(1, 4), t, Spacer(1, 8)]


class MoodBar(Flowable):
    def __init__(self, mood, width, h=9):
        super().__init__()
        self.mood, self.width, self.height = mood, width, h

    def wrap(self, aw, ah):
        return self.width, self.height + 11

    def draw(self):
        c = self.canv
        pos, neu, neg = (int(self.mood.get(k) or 0) for k in ("positive", "neutral", "negative"))
        tot = pos + neu + neg
        if not tot:
            return
        x = 0
        for n, col in ((pos, "#3d6b3a"), (neu, "#9a9a8a"), (neg, "#8a1c1c")):
            w = self.width * n / tot
            c.setFillColor(colors.HexColor(col))
            c.rect(x, 10, w, self.height, stroke=0, fill=1)
            x += w
        c.setFillColor(INK)
        c.setFont(SERIF_I, 7)
        c.drawString(0, 1, "%d positive · %d neutral · %d negative" % (pos, neu, neg))


def _sidebar(ed, w):
    inner = w - 12
    out = []
    briefs = ed.get("briefs") or []
    if briefs:
        items = []
        for b in briefs[:8]:
            t = _e(b.get("title"))
            u = _clean(b.get("url"))
            if u:
                t = '<a href="%s" color="#1a1a1a">%s</a>' % (u.replace("&", "&amp;").replace('"', "%22"), t)
            items.append(Paragraph("▪ <b>%s</b> <font color='#666666' size=7>%s</font>"
                                   % (t, _e(b.get("source"))), ST["small"]))
        out += _box("In Brief", items, w)
    ser = ed.get("serendipity") or []
    if ser:
        items = []
        for s in ser[:3]:
            u = _clean(s.get("url"))
            t = _e(s.get("title"))
            if u:
                t = '<a href="%s" color="#8a1c1c">%s</a>' % (u.replace("&", "&amp;").replace('"', "%22"), t)
            items.append(Paragraph("<b>%s</b>" % t, ST["small"]))
            rs = s.get("reasons") or []
            if rs:
                items.append(Paragraph(_e("; ".join(str(r) for r in rs[:2]), 160), ST["smalli"]))
        out += _box("Off Your Beaten Path", items, w)
    threads = [t for t in (ed.get("threads") or []) if t.get("articles")]
    if threads:
        items = []
        for th in threads[:4]:
            items.append(Paragraph("<b>%s</b>" % _e(th.get("entity")), ST["small"]))
            for a in th["articles"][:4]:
                items.append(Paragraph("<font color='#8a1c1c'>●</font> <font size=7 color='#666666'>%s</font> %s"
                                       % (_e(str(a.get("date") or "")[:10]), _e(a.get("title"), 90)),
                                       ST["small"]))
        out += _box("Following the Story", items, w)
    mood = ed.get("mood") or {}
    if any(mood.get(k) for k in ("positive", "neutral", "negative")):
        out += _box("Today's Mood", [MoodBar(mood, inner)], w)
    nodes = (ed.get("kg") or {}).get("nodes") or []
    if nodes:
        nodes = sorted(nodes, key=lambda n: (not n.get("liked"), -(n.get("weight") or 0)))[:12]
        parts = []
        for n in nodes:
            lab = _e(n.get("label") or n.get("id"))
            parts.append("<b>%s</b>" % lab if n.get("liked") else lab)
        out += _box("Your Knowledge Map", [Paragraph(" · ".join(parts), ST["small"]),
                                           Paragraph("Bold = topics you have liked.", ST["smalli"])], w)
    wd = ed.get("word_of_day")
    if wd:
        txt = wd if isinstance(wd, str) else " - ".join(str(v) for v in wd.values()) if isinstance(wd, dict) else str(wd)
        out += _box("Word of the Day", [Paragraph(_e(txt, 300), ST["small"])], w)
    return out


# ---- main --------------------------------------------------------------
def render_pdf(edition: dict) -> bytes:
    ed = edition or {}
    buf = io.BytesIO()
    PW, PH = A3
    M = 28
    GUT = 14
    W = PW - 2 * M
    colw = (W - 2 * GUT) / 3.0
    user = _clean((ed.get("user_name") or "")) or ""
    greeting = _clean(ed.get("greeting"))
    title = _clean(ed.get("title")) or "The Morning Post"
    m = re.search(r"The (.+?) Morning", title)
    name = user or (m.group(1) if m else "") or "you"
    date_s = _fmt_date(ed.get("date"))
    no = ed.get("edition_no")
    stats = ed.get("stats") or {}
    signals = stats.get("events_learned", 0) or 0

    MAST_H = 150
    top = PH - M - MAST_H
    lead = ed.get("lead") or None

    def masthead(c, d):
        c.saveState()
        c.setFillColor(PAPER)
        c.rect(0, 0, PW, PH, stroke=0, fill=1)
        c.setFillColor(INK)
        y = PH - M
        c.setStrokeColor(INK)
        c.setLineWidth(3)
        c.line(M, y, PW - M, y)
        c.setLineWidth(0.6)
        c.line(M, y - 4, PW - M, y - 4)
        c.setFont(TITLE_FONT, 50 if len(title) < 32 else 38)
        c.drawCentredString(PW / 2, y - 60, title)
        c.setLineWidth(0.6)
        c.line(M, y - 76, PW - M, y - 76)
        c.setLineWidth(2)
        c.line(M, y - 79, PW - M, y - 79)
        c.setFont(SERIF_B, 9.5)
        parts = []
        if no:
            parts.append("No. %s" % no)
        parts.append(date_s)
        left = " · ".join(parts) + " · Personal Edition"
        c.drawString(M, y - 94, left.upper())
        c.drawRightString(PW - M, y - 94, ("Edited for %s · Price: your attention" % name).upper())
        c.setLineWidth(0.6)
        c.line(M, y - 99, PW - M, y - 99)
        if greeting:
            c.setFont(SERIF_I, 12)
            g = greeting if len(greeting) < 150 else greeting[:147] + "..."
            c.drawCentredString(PW / 2, y - 116, g)
        c.setLineWidth(1)
        c.line(M, y - 126, PW - M, y - 126)
        c.restoreState()
        footer(c, d)

    def footer(c, d):
        c.saveState()
        c.setStrokeColor(INK)
        c.setLineWidth(0.5)
        c.line(M, M - 4, PW - M, M - 4)
        c.setFont(SERIF_I, 8)
        c.setFillColor(GREY)
        c.drawString(M, M - 14, "Personalised for %s · learned from %s signals" % (name, signals))
        c.drawCentredString(PW / 2, M - 14, title)
        c.drawRightString(PW - M, M - 14, "Page %d" % d.page)
        c.restoreState()

    def later(c, d):
        c.saveState()
        c.setFillColor(PAPER)
        c.rect(0, 0, PW, PH, stroke=0, fill=1)
        c.setStrokeColor(INK)
        c.setLineWidth(1.5)
        c.line(M, PH - M, PW - M, PH - M)
        c.setFont(TITLE_FONT, 14)
        c.setFillColor(INK)
        c.drawString(M, PH - M - 16, title)
        c.setFont(SERIF_I, 9)
        c.drawRightString(PW - M, PH - M - 16, date_s)
        c.setLineWidth(0.5)
        c.line(M, PH - M - 22, PW - M, PH - M - 22)
        c.restoreState()
        footer(c, d)

    bottom = M + 4
    y0 = PH - M - 134  # below masthead

    def cols(ytop, ybot, prefix):
        fr = []
        for i in range(3):
            x = M + i * (colw + GUT)
            fr.append(Frame(x, ybot, colw, ytop - ybot, leftPadding=0, rightPadding=0,
                            topPadding=0, bottomPadding=0, id="%s%d" % (prefix, i)))
        return fr

    lead_flow = None
    lead_h = 0
    if lead:
        lh = _clean(lead.get("title")) or "Untitled"
        fs = 30 if len(lh) < 70 else 26 if len(lh) < 110 else 22 if len(lh) < 150 else 18
        right = [Paragraph("LEAD STORY \u00b7 " + _e(lead.get("section") or "").upper(), ST["lead_m"]),
                 Paragraph(_e(lh), _S("lh", fontName=SERIF_B, fontSize=fs, leading=fs * 1.1, spaceAfter=4))]
        summ = _e(lead.get("summary") or lead.get("body"), 450)
        if summ:
            right.append(Paragraph(summ, ST["lead_s"]))
        by = ["By " + _e(lead.get("source") or "staff")]
        if lead.get("read_minutes"):
            by.append("%s min read" % _e(lead.get("read_minutes")))
        right.append(Paragraph(" \u00b7 ".join(by), ST["lead_m"]))
        rs = lead.get("reasons") or []
        if rs:
            right.append(Paragraph("Why this story: " + _e("; ".join(str(r) for r in rs[:3]), 240),
                                   _S("lr", fontName=SERIF_I, fontSize=9, leading=11, textColor=GREY,
                                      spaceAfter=3)))
        u = _clean(lead.get("url"))
        if u:
            right.append(Paragraph('<a href="%s" color="#8a1c1c">%s</a>' % (
                u.replace("&", "&amp;").replace('"', "%22"), _e(_short_url(u))), ST["link"]))
        img = _fetch_image(lead.get("image"), W * 0.38, 230)
        if img:
            lead_flow = Table([[img, right]], colWidths=[W * 0.4, W * 0.6 - 4])
        else:
            lead_flow = Table([[right]], colWidths=[W])
        lead_flow.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                       ("RIGHTPADDING", (0, 0), (0, 0), 12 if img else 0),
                                       ("RIGHTPADDING", (1, 0), (-1, -1), 0),
                                       ("TOPPADDING", (0, 0), (-1, -1), 0),
                                       ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        lead_h = lead_flow.wrap(W, 10000)[1] + 6

    lead_frame = Frame(M, y0 - lead_h, W, lead_h, leftPadding=0, rightPadding=0,
                       topPadding=0, bottomPadding=0, id="lead")
    first_frames = ([lead_frame] if lead_flow else []) + cols(y0 - lead_h - 8, bottom, "f")
    doc = BaseDocTemplate(buf, pagesize=A3, leftMargin=M, rightMargin=M, topMargin=M,
                          bottomMargin=M, title=title, author="The Morning Paper")
    doc.addPageTemplates([
        PageTemplate(id="first", frames=first_frames, onPage=masthead),
        PageTemplate(id="later", frames=cols(PH - M - 30, bottom, "l"), onPage=later),
    ])

    story = [NextPageTemplate("later")]
    if lead_flow:
        story += [lead_flow, FrameBreak()]

    side = _sidebar(ed, colw)
    # put the first half of the sidebar (briefs, serendipity) at the head of column one
    head, tail = side[:6], side[6:]
    story += head

    first = True
    for sec in ed.get("sections") or []:
        arts = [a for a in (sec.get("articles") or []) if isinstance(a, dict)]
        if not arts:
            continue
        hdr = _sec_header(sec.get("name") or "News")
        story.append(KeepTogether(hdr + [_article(a, 0) for a in arts[:1]]))
        for i, a in enumerate(arts[1:], 1):
            story.append(_article(a, i))
    story += tail
    if not story or len(story) < 2:
        story.append(Paragraph("No stories today.", ST["body"]))
    doc.build(story)
    return buf.getvalue()


if __name__ == "__main__":
    import random
    random.seed(3)
    lorem = ("The government announced a sweeping set of measures on Friday, with officials saying "
             "the changes would take effect within weeks. Analysts remained divided on the impact, "
             "pointing to <b>mixed</b> signals from markets & households alike. ") * 4
    secs = ["technology", "business", "world", "pakistan", "science", "sports"]
    n = 0

    def card(sec, i):
        global n
        n += 1
        return {"id": "a%d" % n, "title": "%s story %d: a fairly long headline about developments" % (sec.title(), i),
                "summary": "<p>" + lorem + "</p>", "url": "https://example.com/news/%s/%d?utm=1&x=2" % (sec, n),
                "source": random.choice(["Dawn", "BBC", "Ars Technica"]), "section": sec,
                "read_minutes": random.randint(1, 8), "reasons": ["You like " + sec],
                "image": None, "score": 0.5}
    ed = {"id": "u-2026-10-17", "user_id": "u", "date": "2026-10-17", "title": "The Usaid Morning Post",
          "edition_no": 7, "greeting": "Good morning, Usaid. Here is what mattered overnight.",
          "lead": dict(card("technology", 0), image="https://picsum.photos/600/400",
                       reasons=["You follow AI", "Trending in your city"]),
          "sections": [{"name": s, "articles": [card(s, i) for i in range(3)]} for s in secs],
          "briefs": [card("world", i) for i in range(6)],
          "serendipity": [card("culture", i) for i in range(2)],
          "threads": [{"entity": "OpenAI", "articles": [{"id": "x", "title": "Model released", "date": "2026-10-%02d" % d, "url": "u"} for d in (10, 13, 16)]}],
          "kg": {"nodes": [{"id": str(i), "label": l, "type": "ORG", "weight": 1 - i / 20, "liked": i % 3 == 0}
                           for i, l in enumerate(["OpenAI", "Pakistan", "Imran Khan", "NASA", "Tesla", "IMF", "Karachi", "Lahore"])],
                 "edges": []},
          "mood": {"positive": 5, "neutral": 9, "negative": 6}, "stats": {"events_learned": 42}}
    open("/tmp/morning_test.pdf", "wb").write(render_pdf(ed))
    print("ok")
