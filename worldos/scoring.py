"""机会评分：100 分加权 + 证据封顶 + 修订记录。

  raw   = Σ 权重 × 分数/5 × 100          权重：痛点 .30 接触 .20 技术 .20 复用 .20 风险 .10
  痛点分 ≤ 支付意愿上限（没有客户类证据时为 2，见 evidence.py）
  total = min(raw, 证据强度上限)          T0=40 T1=60 T2=75 T3=90 T4=100
每次评分都追加一条记录：必须写评分依据；第二次及以后必须写修订原因。
"""
import json

from . import cards, db, evidence

WEIGHTS = {"pain": 0.30, "access": 0.20, "feasibility": 0.20, "reuse": 0.20, "risk": 0.10}
DIMENSION_NAMES = {
    "pain": "真实痛点及支付意愿",
    "access": "潜在客户接触难度（越容易接触分越高）",
    "feasibility": "技术可实现性",
    "reuse": "复用与复制能力",
    "risk": "成本与履约风险可控性",
}


def compute(scores, tier, pain_cap):
    """纯函数：返回 (raw_total, total, warnings, adjusted_scores)。"""
    warnings = []
    s = {}
    for k in WEIGHTS:
        v = scores.get(k)
        if isinstance(v, bool) or not isinstance(v, int):
            try:
                v = int(str(v).strip())
            except (TypeError, ValueError):
                raise ValueError(f"{DIMENSION_NAMES[k]} 必须是 0-5 的整数，收到 {scores.get(k)!r}")
        if not 0 <= v <= 5:
            raise ValueError(f"{DIMENSION_NAMES[k]} 必须在 0-5 之间，收到 {v}")
        s[k] = v
    if s["pain"] > pain_cap:
        warnings.append(f"支付意愿缺少相应的客户证据，痛点分由 {s['pain']} 降为 {pain_cap}")
        s["pain"] = pain_cap
    raw = round(sum(WEIGHTS[k] * s[k] / 5 for k in WEIGHTS) * 100, 1)
    cap = evidence.TIER_CAP[tier]
    total = float(min(raw, cap))
    if total < raw:
        warnings.append(f"证据强度 {evidence.TIER_NAMES[tier]}，总分由 {raw} 封顶为 {cap}")
    return raw, total, warnings, s


def score_card(conn, card_id, scores, basis, reason=None, scorer="human"):
    card = cards.get(conn, card_id)
    cards.ensure_open(card)
    if card["filter_flag"] in cards.KILL_FLAGS:
        raise ValueError("未通过前置过滤的卡不评分")
    if not card["reviewed"]:
        raise ValueError("AI 生成的卡必须先人工审核（review）才能评分")
    if not basis or not basis.strip():
        raise ValueError("评分必须写依据（--basis），说明每个分数从哪来")
    prev = conn.execute("SELECT id FROM scores WHERE card_id=? ORDER BY id DESC LIMIT 1", (card_id,)).fetchone()
    if prev and not (reason and reason.strip()):
        raise ValueError("这张卡已经评过分，修订评分必须写原因（--reason）")
    p = evidence.profile(conn, card_id)
    raw, total, warnings, s = compute(scores, p["tier"], p["pain_cap"])
    sid = db.insert(conn, "scores", {
        **s, "card_id": card_id, "pain_input": int(scores["pain"]), "evidence_tier": p["tier"],
        "independent_sources": p["independent_sources"], "deal_stage": p["deal_stage"],
        "raw_total": raw, "total": total, "basis": basis.strip(), "evidence_ids": json.dumps(p["evidence_ids"]),
        "reason": reason, "prev_score_id": prev["id"] if prev else None, "scorer": scorer, "created_at": db.now(),
    })
    return sid, raw, total, warnings


def stale_reasons(conn, card_id):
    """最近一次评分之后，证据或卡片内容有变化时返回原因列表；没有评分或分数仍然有效时返回 []。

    证据按“纳入计算的已核实证据 id、证据强度、独立来源数”与评分时的记录比较，不受时间精度影响；
    卡片字段修改按时间比较，精度为秒，评分后同一秒内的修改可能不提示。
    """
    s = conn.execute("SELECT * FROM scores WHERE card_id=? ORDER BY id DESC LIMIT 1", (card_id,)).fetchone()
    if s is None:
        return []
    reasons = []
    p = evidence.profile(conn, card_id)
    reverified = conn.execute("SELECT COUNT(*) FROM evidence WHERE card_id=? AND verified=1 AND verified_at > ?",
                              (card_id, s["created_at"])).fetchone()[0]
    if (set(p["evidence_ids"]) != set(json.loads(s["evidence_ids"] or "[]")) or reverified
            or (p["tier"], p["independent_sources"]) != (s["evidence_tier"], s["independent_sources"])):
        reasons.append("评分后已核实的证据有变化")
    marks = ", ".join("?" for _ in cards.FIELDS)
    fields = [r[0] for r in conn.execute(
        f"SELECT DISTINCT field FROM card_revisions WHERE card_id=? AND created_at > ? AND field IN ({marks})",
        (card_id, s["created_at"], *cards.FIELDS))]
    if fields:
        reasons.append("评分后修改了卡片内容（" + "、".join(fields) + "）")
    return reasons


def latest_scores(conn):
    """每张卡最近一次评分，按总分排序。"""
    return conn.execute(
        """SELECT c.*, s.total, s.raw_total, s.evidence_tier, s.created_at AS scored_at
           FROM cards c LEFT JOIN scores s ON s.id = (
             SELECT id FROM scores WHERE card_id=c.id ORDER BY id DESC LIMIT 1)
           ORDER BY COALESCE(s.total, -1) DESC, c.id"""
    ).fetchall()
