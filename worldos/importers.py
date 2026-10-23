"""信息入口：人工录入、JSON/CSV 文件、RSS（本地文件或公开 URL）。全部保留来源。"""
import csv
import json
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET

from . import db

CARD_FIELDS = [
    "name", "bug_type", "domain", "problem", "affected", "competitors", "why_unsolved", "why_now",
    "payers", "solution", "resources", "revenue_model", "cost_risk", "min_validation", "kill_condition",
]


def add_item(conn, title, url=None, source=None, content=None, credibility="C", published_at=None):
    """返回 (id, created)。重复内容不重复入库。"""
    h = db.content_hash(title, url, content)
    try:
        iid = db.insert(conn, "items", {
            "title": title, "url": url, "source": source, "content": content,
            "credibility": credibility, "published_at": published_at,
            "added_at": db.now(), "content_hash": h,
        })
        return iid, True
    except sqlite3.IntegrityError:
        row = conn.execute("SELECT id FROM items WHERE content_hash=?", (h,)).fetchone()
        return row["id"], False


def import_file(conn, path, source=None):
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
    elif path.lower().endswith(".csv"):
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    elif path.lower().endswith((".xml", ".rss", ".atom")):
        with open(path, "rb") as f:
            rows = parse_feed(f.read())
    else:
        raise ValueError("支持 .json / .csv / .xml(.rss/.atom)")
    return _add_rows(conn, rows, source)


def import_rss_url(conn, url, source=None):
    req = urllib.request.Request(url, headers={"User-Agent": "worldos-personal/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        rows = parse_feed(resp.read())
    return _add_rows(conn, rows, source or url)


def _add_rows(conn, rows, source):
    new = dup = 0
    for r in rows:
        if not r.get("title"):
            continue
        _, created = add_item(conn, r["title"], r.get("url"), r.get("source") or source,
                              r.get("content"), r.get("credibility") or "C", r.get("published_at"))
        new += created
        dup += not created
    return new, dup


def parse_feed(raw):
    """极简 RSS 2.0 / Atom 解析，只取标题、链接、时间、摘要。"""
    root = ET.fromstring(raw)
    out = []
    for it in root.iter("item"):
        out.append({
            "title": (it.findtext("title") or "").strip(),
            "url": (it.findtext("link") or "").strip(),
            "published_at": it.findtext("pubDate"),
            "content": (it.findtext("description") or "").strip()[:4000],
        })
    ns = "{http://www.w3.org/2005/Atom}"
    for e in root.iter(ns + "entry"):
        link = e.find(ns + "link")
        out.append({
            "title": (e.findtext(ns + "title") or "").strip(),
            "url": link.get("href") if link is not None else None,
            "published_at": e.findtext(ns + "updated"),
            "content": (e.findtext(ns + "summary") or e.findtext(ns + "content") or "").strip()[:4000],
        })
    return out


def add_card(conn, data, origin="manual"):
    row = {k: data.get(k) for k in CARD_FIELDS}
    if not row["name"]:
        raise ValueError("机会卡必须有 name")
    row.update(origin=origin, reviewed=0 if origin == "ai" else 1, created_at=db.now())
    cid = db.insert(conn, "cards", row)
    for ev in data.get("evidence", []) or []:
        item = None
        if ev.get("item_id"):
            item = conn.execute("SELECT * FROM items WHERE id=?", (ev["item_id"],)).fetchone()
        db.insert(conn, "evidence", {
            "card_id": cid,
            "item_id": item["id"] if item else None,
            "url": ev.get("url") or (item["url"] if item else None),
            "claim": ev["claim"],
            "kind": ev.get("kind", "inference"),
            # AI 给出的证据一律从 E0 开始，人工核实后再提升
            "level": 0 if origin == "ai" else int(ev.get("level", 1)),
            "observed_at": ev.get("observed_at") or (item["published_at"] if item else None),
            "verified": 0 if origin == "ai" else int(ev.get("verified", 0)),
            "created_at": db.now(),
        })
    return cid


def similar_cards(conn, name, threshold=0.6):
    from difflib import SequenceMatcher
    hits = []
    for r in conn.execute("SELECT id, name FROM cards WHERE status!='killed'"):
        ratio = SequenceMatcher(None, name, r["name"]).ratio()
        if ratio >= threshold:
            hits.append((r["id"], r["name"], round(ratio, 2)))
    return hits
