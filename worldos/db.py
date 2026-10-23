"""SQLite 存储层：建表、连接、通用小工具。只用标准库。"""
import hashlib
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (           -- 原始信息（人工录入 / RSS / 文件导入）
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  url TEXT,
  source TEXT,                               -- 来源名称，如 "36氪RSS"、"客户访谈"
  credibility TEXT DEFAULT 'C',              -- A=一手/官方 B=可靠二手 C=未核实
  published_at TEXT,
  added_at TEXT NOT NULL,
  content TEXT,
  content_hash TEXT UNIQUE,                  -- 去重
  processed_at TEXT                          -- 已做过 Bug 提取
);
CREATE TABLE IF NOT EXISTS cards (           -- 机会卡
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  bug_type TEXT,                             -- 信息差/时间差/价格差/技术差/流程/认知差/供需错配/软件生态
  domain TEXT,
  problem TEXT,
  affected TEXT,
  competitors TEXT,
  why_unsolved TEXT,
  why_now TEXT,
  payers TEXT,
  solution TEXT,
  resources TEXT,
  revenue_model TEXT,
  cost_risk TEXT,
  min_validation TEXT,
  kill_condition TEXT,
  status TEXT DEFAULT 'candidate',           -- candidate/researching/validating/paused/killed/won
  filter_flag TEXT DEFAULT 'ok',             -- ok/illegal/unauthorized/harmful/no_payer/over_budget
  origin TEXT DEFAULT 'manual',              -- manual / ai（ai 生成的卡必须人工审核）
  reviewed INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  last_verified_at TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY,
  card_id INTEGER NOT NULL REFERENCES cards(id),
  item_id INTEGER REFERENCES items(id),
  url TEXT,
  claim TEXT NOT NULL,
  kind TEXT DEFAULT 'fact',                  -- fact/inference/forecast
  level INTEGER DEFAULT 0,                   -- 0=AI推断/无来源 1=公开二手 2=一手来源或客户亲述 3=报价/付款/意向书
  observed_at TEXT,                          -- 证据本身的时间（判断新鲜度）
  verified INTEGER DEFAULT 0,                -- 人工核实过才计入证据等级
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
  id INTEGER PRIMARY KEY,
  card_id INTEGER NOT NULL REFERENCES cards(id),
  pain INTEGER, access INTEGER, feasibility INTEGER, reuse INTEGER, risk INTEGER,
  evidence_level INTEGER, raw_total REAL, total REAL,
  scorer TEXT DEFAULT 'human', note TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY,
  card_id INTEGER REFERENCES cards(id),
  title TEXT NOT NULL,
  purpose TEXT, hypothesis TEXT, acceptance TEXT,
  minutes_budget INTEGER, money_budget REAL,
  due TEXT,
  status TEXT DEFAULT 'open',                -- open/done/dropped
  result TEXT,
  decision TEXT,                             -- continue/adjust/pause/kill
  created_at TEXT NOT NULL, done_at TEXT
);
CREATE TABLE IF NOT EXISTS logs (            -- 现实反馈：访谈、报价、成本、回款、工时、认知、体验
  id INTEGER PRIMARY KEY,
  card_id INTEGER REFERENCES cards(id),
  kind TEXT NOT NULL,                        -- interview/quote/cost/revenue/time/insight/experience
  category TEXT,                             -- time 用：build/research/outreach/delivery
  amount REAL, minutes INTEGER,
  counterpart TEXT, note TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY,
  task TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL,
  created_at TEXT NOT NULL
);
"""


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def default_path():
    return os.environ.get("WORLDOS_DB", os.path.join(os.getcwd(), "worldos.db"))


def connect(path=None):
    conn = sqlite3.connect(path or default_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def content_hash(title, url, content):
    key = (url or "").strip().lower() or f"{(title or '').strip()}\n{(content or '').strip()[:500]}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def insert(conn, table, row):
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))
    conn.commit()
    return cur.lastrowid
