"""机会评分：前置过滤 + 100 分加权 + 证据等级封顶。

规则要点：
- 五个维度 0-5 分，按权重换算为 100 分（raw_total）。
- 证据等级取该卡“已人工核实”证据的最高等级；未核实证据不计。
- 证据不足时总分封顶（total），并且“痛点与支付意愿”在没有一手证据（<2）时最高只能记 2 分。
"""
from . import db

WEIGHTS = {"pain": 0.30, "access": 0.20, "feasibility": 0.20, "reuse": 0.20, "risk": 0.10}
DIMENSION_NAMES = {
    "pain": "真实痛点及支付意愿",
    "access": "潜在客户接触难度（越易接触分越高）",
    "feasibility": "技术可实现性",
    "reuse": "复用与复制能力",
    "risk": "成本与履约风险可控性",
}
# 证据等级 -> 总分上限
EVIDENCE_CAP = {0: 40, 1: 60, 2: 85, 3: 100}
EVIDENCE_NAMES = {0: "E0 仅AI推断/无来源", 1: "E1 公开二手来源", 2: "E2 一手来源/客户亲述", 3: "E3 报价/付款/意向书"}
PAIN_CAP_WITHOUT_PRIMARY = 2

KILL_FLAGS = {"illegal", "unauthorized", "harmful"}   # 直接淘汰
PAUSE_FLAGS = {"no_payer", "over_budget"}             # 暂缓


def evidence_level(conn, card_id):
    row = conn.execute(
        "SELECT MAX(level) AS lv FROM evidence WHERE card_id=? AND verified=1", (card_id,)
    ).fetchone()
    return row["lv"] if row and row["lv"] is not None else 0


def compute(scores, ev_level):
    """纯函数：返回 (raw_total, total, warnings, adjusted_scores)。"""
    warnings = []
    s = {}
    for k in WEIGHTS:
        v = int(scores[k])
        if not 0 <= v <= 5:
            raise ValueError(f"{k} 必须在 0-5 之间，收到 {v}")
        s[k] = v
    if ev_level < 2 and s["pain"] > PAIN_CAP_WITHOUT_PRIMARY:
        warnings.append(
            f"没有已核实的一手证据（当前 {EVIDENCE_NAMES[ev_level]}），痛点/支付意愿从 {s['pain']} 降为 {PAIN_CAP_WITHOUT_PRIMARY}"
        )
        s["pain"] = PAIN_CAP_WITHOUT_PRIMARY
    raw = round(sum(WEIGHTS[k] * s[k] / 5 for k in WEIGHTS) * 100, 1)
    cap = EVIDENCE_CAP[ev_level]
    total = min(raw, cap)
    if total < raw:
        warnings.append(f"证据等级 {EVIDENCE_NAMES[ev_level]}，总分由 {raw} 封顶为 {cap}")
    return raw, total, warnings, s


def score_card(conn, card_id, scores, scorer="human", note=None):
    card = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
    if card is None:
        raise ValueError(f"机会卡 {card_id} 不存在")
    if card["filter_flag"] in KILL_FLAGS:
        raise ValueError(f"机会卡 {card_id} 未通过前置过滤（{card['filter_flag']}），不评分")
    lv = evidence_level(conn, card_id)
    raw, total, warnings, s = compute(scores, lv)
    db.insert(conn, "scores", {
        **s, "card_id": card_id, "evidence_level": lv, "raw_total": raw, "total": total,
        "scorer": scorer, "note": note, "created_at": db.now(),
    })
    return raw, total, warnings


def apply_filter(conn, card_id, flag):
    status = None
    if flag in KILL_FLAGS:
        status = "killed"
    elif flag in PAUSE_FLAGS:
        status = "paused"
    elif flag != "ok":
        raise ValueError(f"未知过滤标记 {flag}")
    if status:
        conn.execute("UPDATE cards SET filter_flag=?, status=? WHERE id=?", (flag, status, card_id))
    else:
        conn.execute("UPDATE cards SET filter_flag=? WHERE id=?", (flag, card_id))
    conn.commit()
    return status


def latest_scores(conn):
    """每张卡最近一次评分。"""
    return conn.execute(
        """SELECT c.*, s.total, s.raw_total, s.evidence_level, s.created_at AS scored_at
           FROM cards c LEFT JOIN scores s ON s.id = (
             SELECT id FROM scores WHERE card_id=c.id ORDER BY id DESC LIMIT 1)
           ORDER BY COALESCE(s.total, -1) DESC, c.id"""
    ).fetchall()
