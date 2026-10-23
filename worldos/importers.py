"""信息入口：人工录入、JSON/CSV 文件、RSS（本地文件或公开 URL）。每条信息必须有来源。"""
import csv
import json
import re
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET

from . import db

CREDIBILITY = {"A", "B", "C"}

# 常见提示词注入句式。只做标记提醒，不阻止入库：外部文本永远只是数据。
INJECTION_PATTERNS = re.compile(
    r"忽略(以上|之前|上述|前面)|无视(以上|之前|上述)|你现在是|系统提示|system prompt|"
    r"ignore (all |the )?(previous|above|prior) (instructions|rules)|disregard (the )?(previous|above)|"
    r"you are now|developer mode|把(评分|分数|证据等级|状态)(改|设)", re.I)


def detect_injection(*texts):
    return any(INJECTION_PATTERNS.search(t or "") for t in texts)


def add_item(conn, title, url=None, source=None, content=None, credibility="C", published_at=None):
    """返回 (id, created)。重复内容不重复入库。缺少标题或来源时抛 ValueError。"""
    title = (title or "").strip()
    source = (source or "").strip()
    if not title:
        raise ValueError("信息必须有标题")
    if not source:
        raise ValueError("信息必须注明来源（--source），例如 网站名、报告名、自己观察、某次访谈")
    credibility = (credibility or "C").upper()
    if credibility not in CREDIBILITY:
        raise ValueError("可信度必须是 A / B / C")
    h = db.content_hash(title, url, content)
    flags = "possible_injection" if detect_injection(title, content) else None
    try:
        iid = db.insert(conn, "items", {
            "title": title, "url": (url or "").strip() or None, "source": source, "content": content,
            "credibility": credibility, "published_at": published_at, "added_at": db.now(),
            "content_hash": h, "flags": flags,
        })
        return iid, True
    except sqlite3.IntegrityError:
        row = conn.execute("SELECT id FROM items WHERE content_hash=?", (h,)).fetchone()
        return row["id"], False


def _read_text(path):
    """先按 UTF-8（含 BOM）读，失败再按 GBK 读，兼容中文 Windows 下 Excel 另存的 CSV。"""
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path} 既不是 UTF-8 也不是 GBK 编码，请另存为 UTF-8")


def import_file(conn, path, source=None):
    low = path.lower()
    if low.endswith(".json"):
        try:
            rows = json.loads(_read_text(path))
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 格式错误：第 {e.lineno} 行第 {e.colno} 列，{e.msg}")
        if isinstance(rows, dict):
            rows = rows.get("items", [rows])
        if not isinstance(rows, list):
            raise ValueError("JSON 顶层必须是信息数组，或含 items 数组的对象")
    elif low.endswith(".csv"):
        rows = list(csv.DictReader(_read_text(path).splitlines()))
    elif low.endswith((".xml", ".rss", ".atom")):
        with open(path, "rb") as f:
            rows = parse_feed(f.read())
    else:
        raise ValueError("支持 .json / .csv / .xml(.rss/.atom)")
    return _add_rows(conn, rows, source)


def import_rss_url(conn, url, source=None):
    req = urllib.request.Request(url, headers={"User-Agent": "worldos-personal/0.2"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        rows = parse_feed(resp.read())
    return _add_rows(conn, rows, source or url)


def _add_rows(conn, rows, source):
    stats = {"new": 0, "duplicate": 0, "missing_source": 0, "invalid": 0}
    for r in rows:
        if not isinstance(r, dict) or not (r.get("title") or "").strip():
            stats["invalid"] += 1
            continue
        if not ((r.get("source") or "").strip() or (source or "").strip()):
            stats["missing_source"] += 1
            continue
        try:
            _, created = add_item(conn, r["title"], r.get("url"), r.get("source") or source,
                                  r.get("content"), r.get("credibility") or "C", r.get("published_at"))
        except ValueError:
            stats["invalid"] += 1
            continue
        stats["new" if created else "duplicate"] += 1
    return stats


def parse_feed(raw):
    """极简 RSS 2.0 / Atom 解析，只取标题、链接、时间、摘要。"""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValueError(f"RSS/Atom 解析失败：{e}")
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
