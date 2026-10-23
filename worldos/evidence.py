"""证据模型：证据类型、证据强度、独立来源、成交状态。

三件事分开记录，互不替代：
  1. 证据强度（tier）：这条机会“问题真实存在”有多可靠，用于总分封顶；
  2. 支付意愿证据：痛点/支付意愿这一维最多能打几分，只认客户类证据；
  3. 成交状态（deal stage）：来自 logs 里的报价、意向、合同、回款记录，只展示，不参与证据强度。

规则：
  - 只有人工核实（verified=1）的证据参与计算；
  - AI 产生的证据一律是 ai_inference，人工核实后最多升级为 public 或 primary，
    不能变成客户自述、报价、意向、合同或回款（这些只能由人根据真实接触录入）；
  - 一条证据不能证明整个机会：某一强度要有 ≥2 个独立来源才算达到，
    只有 1 个来源时按下一档封顶。
"""
from . import db

# 类型 -> (强度档位, 中文名)
TYPES = {
    "ai_inference": (0, "AI 推断"),
    "public": (1, "公开资料"),
    "primary": (2, "经人工核实的一手资料"),
    "customer_statement": (2, "客户自述"),
    "quote": (3, "客户报价/确认价格"),
    "intent": (3, "合作意向"),
    "contract": (4, "合同"),
    "payment": (4, "实际回款"),
}
CUSTOMER_TYPES = {"customer_statement", "quote", "intent", "contract", "payment"}
AI_UPGRADABLE = {"public", "primary"}
KINDS = {"fact", "inference", "forecast"}

TIER_CAP = {0: 40, 1: 60, 2: 75, 3: 90, 4: 100}
TIER_NAMES = {0: "T0 无已核实证据/仅AI推断", 1: "T1 公开资料", 2: "T2 一手资料或客户自述",
              3: "T3 报价或合作意向", 4: "T4 合同或回款"}

# 支付意愿（痛点维度）上限：取决于已核实的客户类证据
PAIN_CAP_BY_TYPE = {"customer_statement": 3, "quote": 4, "intent": 4, "contract": 5, "payment": 5}
PAIN_CAP_DEFAULT = 2

# 成交状态：logs.kind 的先后顺序
DEAL_STAGES = ["none", "quote", "intent", "contract", "payment"]
DEAL_NAMES = {"none": "未成交", "quote": "已报价", "intent": "有合作意向", "contract": "已签合同", "payment": "已回款"}


def check(evidence_type, url=None, counterpart=None, origin="manual", verified=False):
    """录入/核实前的规则检查，违规抛 ValueError。"""
    if evidence_type not in TYPES:
        raise ValueError(f"未知证据类型 {evidence_type}，可选：{', '.join(TYPES)}")
    if origin != "manual" and evidence_type not in ({"ai_inference"} | AI_UPGRADABLE):
        raise ValueError("AI 产生的证据只能是 AI 推断，人工核实后最多升级为公开资料或一手资料")
    if origin != "manual" and evidence_type in AI_UPGRADABLE and not verified:
        raise ValueError("AI 产生的证据必须经人工核实才能升级")
    if evidence_type == "public" and not url:
        raise ValueError("公开资料必须提供来源链接 url")
    if evidence_type == "primary" and not (url or counterpart):
        raise ValueError("一手资料必须提供链接或对方代号，说明从哪里核实")
    if evidence_type in CUSTOMER_TYPES and not counterpart:
        raise ValueError(f"{TYPES[evidence_type][1]} 必须填写对方代号（--who）")


def add(conn, card_id, evidence_type, claim, kind="fact", url=None, counterpart=None, item_id=None,
        log_id=None, observed_at=None, origin="manual", verified=False, commit=True):
    if not claim or not claim.strip():
        raise ValueError("证据必须有具体主张 claim")
    if kind not in KINDS:
        raise ValueError(f"kind 必须是 {sorted(KINDS)}")
    if origin != "manual" and evidence_type != "ai_inference":
        raise ValueError("AI 产生的证据入库时只能是 AI 推断，需人工核实后再升级类型")
    check(evidence_type, url, counterpart, origin, verified=verified and evidence_type != "ai_inference")
    if origin != "manual":
        verified = False  # AI 证据入库时一律未核实
    eid = db.insert(conn, "evidence", {
        "card_id": card_id, "item_id": item_id, "log_id": log_id, "evidence_type": evidence_type,
        "kind": kind, "claim": claim.strip(), "url": url, "counterpart": counterpart,
        "observed_at": observed_at, "origin": origin, "verified": int(bool(verified)),
        "verified_at": db.now() if verified else None, "created_at": db.now(),
    }, commit=False)
    if verified:
        conn.execute("UPDATE cards SET last_verified_at=? WHERE id=?", (db.now(), card_id))
    if commit:
        conn.commit()
    return eid


def verify(conn, evidence_id, evidence_type, url=None, kind=None):
    """人工核实一条证据，可同时修正类型。"""
    e = conn.execute("SELECT * FROM evidence WHERE id=?", (evidence_id,)).fetchone()
    if e is None:
        raise ValueError(f"证据 {evidence_id} 不存在")
    url = url or e["url"]
    check(evidence_type, url, e["counterpart"], e["origin"], verified=True)
    if kind and kind not in KINDS:
        raise ValueError(f"kind 必须是 {sorted(KINDS)}")
    conn.execute("UPDATE evidence SET verified=1, verified_at=?, evidence_type=?, url=?, kind=COALESCE(?, kind) "
                 "WHERE id=?", (db.now(), evidence_type, url, kind, evidence_id))
    conn.execute("UPDATE cards SET last_verified_at=? WHERE id=?", (db.now(), e["card_id"]))
    conn.commit()


def _source_key(e):
    return (e["counterpart"] or "").strip().lower() or (e["url"] or "").strip().lower() or f"ev:{e['id']}"


def profile(conn, card_id):
    """计算一张卡的证据画像。"""
    rows = conn.execute("SELECT * FROM evidence WHERE card_id=? AND verified=1", (card_id,)).fetchall()
    sources_at = {}
    for t in range(5):
        sources_at[t] = {_source_key(e) for e in rows if TYPES[e["evidence_type"]][0] >= t and t > 0}
    # 某档有 ≥2 个独立来源才算达到；只有 1 个来源时降一档
    tier = max([t if len(sources_at[t]) >= 2 else t - 1 for t in range(1, 5) if sources_at[t]], default=0)
    top = max((TYPES[e["evidence_type"]][0] for e in rows), default=0)
    pain_cap = max((PAIN_CAP_BY_TYPE.get(e["evidence_type"], PAIN_CAP_DEFAULT) for e in rows),
                   default=PAIN_CAP_DEFAULT)
    return {
        "tier": tier,
        "top_tier": top,
        "independent_sources": len(sources_at[1]),
        "pain_cap": pain_cap,
        "evidence_ids": [e["id"] for e in rows],
        "deal_stage": deal_stage(conn, card_id),
    }


def deal_stage(conn, card_id):
    kinds = {r["kind"] for r in conn.execute(
        "SELECT DISTINCT kind FROM logs WHERE card_id=? AND kind IN ('quote','intent','contract','payment')",
        (card_id,))}
    stage = "none"
    for s in DEAL_STAGES:
        if s in kinds:
            stage = s
    return stage
