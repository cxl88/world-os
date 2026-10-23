"""SQLite 存储层：数据目录、建表、连接、通用小工具。只用标准库。

数据目录规则（Windows / macOS / Linux 一致）：
  1. 命令行 --db 指定数据库文件时，数据目录 = 该文件所在目录；
  2. 否则看环境变量 WORLDOS_DB（数据库文件路径）；
  3. 否则数据目录 = 环境变量 WORLDOS_HOME，未设置时为 用户主目录/worldos-data，
     数据库为其中的 worldos.db。
提示词文件、简报、备份、导出都放在数据目录下，不会散落在当前目录。
"""
import hashlib
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (           -- 原始信息（人工录入 / RSS / 文件导入）
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  url TEXT,
  source TEXT NOT NULL,                      -- 来源名称，必填，如 "36氪RSS"、"客户访谈"、"自己观察"
  credibility TEXT DEFAULT 'C',              -- A=一手/官方 B=可靠二手 C=未核实
  published_at TEXT,                         -- 资料本身的日期
  added_at TEXT NOT NULL,
  content TEXT,
  content_hash TEXT UNIQUE,                  -- 去重
  flags TEXT,                                -- possible_injection 等提示
  processed_at TEXT                          -- 已做过 Bug 提取
);
CREATE TABLE IF NOT EXISTS cards (           -- 机会卡
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  bug_type TEXT, domain TEXT, problem TEXT, affected TEXT, competitors TEXT,
  why_unsolved TEXT, why_now TEXT, payers TEXT, solution TEXT, resources TEXT,
  revenue_model TEXT, cost_risk TEXT, min_validation TEXT, kill_condition TEXT,
  status TEXT NOT NULL DEFAULT 'candidate',  -- candidate/researching/validating/paused/killed/won
  filter_flag TEXT NOT NULL DEFAULT 'ok',    -- ok/illegal/unauthorized/harmful/no_payer/over_budget
  origin TEXT NOT NULL DEFAULT 'manual',     -- manual / ai / ai-mock（模拟适配器，仅测试用）
  reviewed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  last_verified_at TEXT
);
CREATE TABLE IF NOT EXISTS card_revisions (  -- 机会卡字段与状态的修改记录
  id INTEGER PRIMARY KEY,
  card_id INTEGER NOT NULL REFERENCES cards(id),
  field TEXT NOT NULL, old_value TEXT, new_value TEXT,
  reason TEXT, actor TEXT NOT NULL DEFAULT 'human',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY,
  card_id INTEGER NOT NULL REFERENCES cards(id),
  item_id INTEGER REFERENCES items(id),
  log_id INTEGER REFERENCES logs(id),
  evidence_type TEXT NOT NULL,               -- 见 evidence.py：ai_inference/public/primary/customer_statement/quote/intent/contract/payment
  kind TEXT NOT NULL DEFAULT 'inference',    -- fact/inference/forecast
  claim TEXT NOT NULL,
  url TEXT,
  counterpart TEXT,                          -- 客户类证据的对方代号
  observed_at TEXT,                          -- 证据本身的时间（判断新鲜度）
  origin TEXT NOT NULL DEFAULT 'manual',     -- manual / ai / ai-mock
  verified INTEGER NOT NULL DEFAULT 0,       -- 只有人工核实过的证据才参与评分
  verified_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (          -- 只追加，不覆盖：每次评分都是一条修订记录
  id INTEGER PRIMARY KEY,
  card_id INTEGER NOT NULL REFERENCES cards(id),
  pain INTEGER NOT NULL, access INTEGER NOT NULL, feasibility INTEGER NOT NULL,
  reuse INTEGER NOT NULL, risk INTEGER NOT NULL,
  pain_input INTEGER,                        -- 人工给的痛点分（被证据规则压低前）
  evidence_tier INTEGER, independent_sources INTEGER, deal_stage TEXT,
  raw_total REAL NOT NULL, total REAL NOT NULL,
  basis TEXT NOT NULL,                       -- 评分依据（必填）
  evidence_ids TEXT,                         -- 评分时纳入计算的已核实证据 id（JSON）
  reason TEXT,                               -- 修订原因（第二次及以后评分必填）
  prev_score_id INTEGER,
  scorer TEXT NOT NULL DEFAULT 'human',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY,
  card_id INTEGER REFERENCES cards(id),
  title TEXT NOT NULL,
  purpose TEXT, hypothesis TEXT, acceptance TEXT,
  minutes_budget INTEGER, money_budget REAL,
  due TEXT,
  status TEXT NOT NULL DEFAULT 'open',       -- open/done/dropped
  result TEXT,
  decision TEXT,                             -- continue/adjust/pause/kill
  created_at TEXT NOT NULL, done_at TEXT
);
CREATE TABLE IF NOT EXISTS logs (            -- 现实反馈
  id INTEGER PRIMARY KEY,
  card_id INTEGER REFERENCES cards(id),
  kind TEXT NOT NULL,                        -- interview/quote/intent/contract/payment/cost/time/insight/experience
  category TEXT,                             -- time 用：build/research/outreach/delivery
  amount REAL, minutes INTEGER,
  counterpart TEXT, note TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY,
  task TEXT, provider TEXT, model TEXT,
  status TEXT NOT NULL,                      -- pending（已发出、未返回）/ ok / error / blocked
  error TEXT,
  input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
  cost_usd REAL DEFAULT 0,                   -- 计入预算的金额：用量已知时为实际费用，未知时为预估上限；模拟调用恒为 0
  simulated INTEGER NOT NULL DEFAULT 0,      -- 1 = 模拟适配器，不是真实账单
  created_at TEXT NOT NULL,
  est_cost_usd REAL,                         -- 发出请求前预估的单次费用上限
  usage_known INTEGER NOT NULL DEFAULT 1     -- 0 = 供应商没有返回用量（或调用失败），费用按上限预估，待与账单对账
);
"""

# 旧版本 → 升级到下一版本的语句。v1 结构差异太大，不升级。
MIGRATIONS = {
    2: ["ALTER TABLE llm_calls ADD COLUMN est_cost_usd REAL",
        "ALTER TABLE llm_calls ADD COLUMN usage_known INTEGER NOT NULL DEFAULT 1",
        # v2 的失败调用费用记为 0，实际是否计费未知
        "UPDATE llm_calls SET usage_known=0 WHERE status='error' AND simulated=0"],
}
READABLE_VERSIONS = set(MIGRATIONS) | {SCHEMA_VERSION}

TABLES = ["items", "cards", "card_revisions", "evidence", "scores", "actions", "logs", "llm_calls"]


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def resolve_paths(db_arg=None):
    """返回 (数据库文件路径, 数据目录)。"""
    db_path = db_arg or os.environ.get("WORLDOS_DB")
    if db_path:
        db_path = os.path.abspath(os.path.expanduser(db_path))
        return db_path, os.path.dirname(db_path)
    home = os.environ.get("WORLDOS_HOME") or os.path.join(os.path.expanduser("~"), "worldos-data")
    home = os.path.abspath(os.path.expanduser(home))
    return os.path.join(home, "worldos.db"), home


def connect(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    has_tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    if has_tables and version in MIGRATIONS:
        _migrate(conn, version)
    elif has_tables and version != SCHEMA_VERSION:
        conn.close()
        raise RuntimeError(
            f"数据库 {path} 是旧版结构（版本 {version}），当前程序需要版本 {SCHEMA_VERSION}。"
            "请换一个新的数据库路径，或用旧版程序 export 后重新导入。")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return conn


def _migrate(conn, version):
    """在一个事务里逐级升级；任何一步失败都整体回滚，数据库保持原版本。"""
    with conn:
        conn.execute("BEGIN")   # DDL 默认不开启事务，显式开启才能整体回滚
        while version < SCHEMA_VERSION:
            for sql in MIGRATIONS[version]:
                conn.execute(sql)
            version += 1
            conn.execute(f"PRAGMA user_version = {version}")


def content_hash(title, url, content):
    key = (url or "").strip().lower() or f"{(title or '').strip()}\n{(content or '').strip()[:500]}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def insert(conn, table, row, commit=True):
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values()))
    if commit:
        conn.commit()
    return cur.lastrowid


def dump(conn):
    """全部表内容，用于导出和一致性校验。"""
    return {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in TABLES}
