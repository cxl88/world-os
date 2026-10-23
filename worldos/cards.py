"""机会卡：字段修改、状态流转、人工审核、前置过滤。所有修改都写入 card_revisions。"""
from . import db, evidence

FIELDS = [
    "name", "bug_type", "domain", "problem", "affected", "competitors", "why_unsolved", "why_now",
    "payers", "solution", "resources", "revenue_model", "cost_risk", "min_validation", "kill_condition",
]
BUG_TYPES = ["信息差", "时间差", "价格差", "技术差", "流程", "认知差", "供需错配", "软件生态", "未分类"]
STATUSES = ["candidate", "researching", "validating", "paused", "killed", "won"]

# 允许的状态流转；killed 和 won 是终态
TRANSITIONS = {
    "candidate": {"researching", "paused", "killed"},
    "researching": {"candidate", "validating", "paused", "killed"},
    "validating": {"researching", "paused", "killed", "won"},
    "paused": {"candidate", "researching", "killed"},
    "killed": set(),
    "won": set(),
}
KILL_FLAGS = {"illegal", "unauthorized", "harmful"}   # 直接淘汰
PAUSE_FLAGS = {"no_payer", "over_budget"}             # 暂缓
FLAG_NAMES = {"ok": "通过", "illegal": "不合法", "unauthorized": "需未授权获取数据或访问系统",
              "harmful": "侵犯隐私/欺骗/损害他人", "no_payer": "找不到付费方", "over_budget": "超出资金承受能力"}


def get(conn, card_id):
    c = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
    if c is None:
        raise ValueError(f"机会卡 {card_id} 不存在")
    return c


def ensure_open(card):
    """被淘汰或已成交的卡不能再进入后续流程。"""
    if card["status"] == "killed":
        raise ValueError(f"机会卡 #{card['id']} 已淘汰（{FLAG_NAMES.get(card['filter_flag'], card['filter_flag'])}），"
                         "不能评分、建行动或改状态")
    if card["status"] == "won":
        raise ValueError(f"机会卡 #{card['id']} 已成交关闭")


def _revise(conn, card_id, field, old, new, reason, actor="human"):
    db.insert(conn, "card_revisions", {
        "card_id": card_id, "field": field, "old_value": None if old is None else str(old),
        "new_value": None if new is None else str(new), "reason": reason, "actor": actor,
        "created_at": db.now()}, commit=False)


def create(conn, data, origin="manual", commit=True):
    row = {k: (str(data[k]).strip() if data.get(k) is not None else None) for k in FIELDS}
    if not row["name"]:
        raise ValueError("机会卡必须有 name")
    if row["bug_type"] and row["bug_type"] not in BUG_TYPES:
        raise ValueError(f"bug_type 必须是 {BUG_TYPES}")
    row.update(origin=origin, reviewed=0 if origin != "manual" else 1, created_at=db.now())
    cid = db.insert(conn, "cards", row, commit=False)
    _revise(conn, cid, "created", None, origin, None, actor="system" if origin != "manual" else "human")
    if commit:
        conn.commit()
    return cid


def set_field(conn, card_id, field, value, reason=None):
    if field not in FIELDS:
        raise ValueError(f"不能直接修改 {field}；可改字段：{', '.join(FIELDS)}。状态请用 status 命令")
    if field == "bug_type" and value not in BUG_TYPES:
        raise ValueError(f"bug_type 必须是 {BUG_TYPES}")
    c = get(conn, card_id)
    ensure_open(c)
    _revise(conn, card_id, field, c[field], value, reason)
    conn.execute(f"UPDATE cards SET {field}=? WHERE id=?", (value, card_id))
    conn.commit()


def set_status(conn, card_id, new, reason=None, actor="human"):
    if new not in STATUSES:
        raise ValueError(f"状态必须是 {STATUSES}")
    c = get(conn, card_id)
    old = c["status"]
    if new == old:
        return
    if new not in TRANSITIONS[old]:
        allowed = "、".join(sorted(TRANSITIONS[old])) or "无（终态）"
        raise ValueError(f"不允许从 {old} 变为 {new}；{old} 只能变为：{allowed}")
    if new in ("researching", "validating"):
        if not c["reviewed"]:
            raise ValueError("AI 生成的卡必须先人工审核（review）才能进入研究/验证")
        if c["filter_flag"] != "ok":
            raise ValueError(f"前置过滤未通过（{FLAG_NAMES[c['filter_flag']]}），不能进入研究/验证")
    if new == "won" and received(conn, card_id) <= 0:
        raise ValueError("没有金额大于 0 的实际回款记录（log payment）的卡不能标记为 won")
    _revise(conn, card_id, "status", old, new, reason, actor)
    conn.execute("UPDATE cards SET status=? WHERE id=?", (new, card_id))
    conn.commit()


def received(conn, card_id):
    """实际回款合计：只计金额为正的有限数字（防止旧数据里的 0、NaN、Infinity 冒充回款）。"""
    amounts = [r[0] for r in conn.execute("SELECT amount FROM logs WHERE card_id=? AND kind='payment'", (card_id,))]
    return sum(a for a in amounts if evidence.positive_amount(a))


def review(conn, card_id, reason=None):
    c = get(conn, card_id)
    ensure_open(c)
    if c["reviewed"]:
        return False
    _revise(conn, card_id, "reviewed", 0, 1, reason)
    conn.execute("UPDATE cards SET reviewed=1 WHERE id=?", (card_id,))
    conn.commit()
    return True


def apply_filter(conn, card_id, flag, reason=None):
    if flag not in FLAG_NAMES:
        raise ValueError(f"未知过滤标记 {flag}，可选：{', '.join(FLAG_NAMES)}")
    c = get(conn, card_id)
    if c["status"] == "killed":
        raise ValueError(f"机会卡 #{card_id} 已淘汰，过滤结果不能撤销；如需重新研究请新建卡片")
    if c["status"] == "won":
        raise ValueError(f"机会卡 #{card_id} 已成交关闭")
    _revise(conn, card_id, "filter_flag", c["filter_flag"], flag, reason)
    conn.execute("UPDATE cards SET filter_flag=? WHERE id=?", (flag, card_id))
    new_status = "killed" if flag in KILL_FLAGS else "paused" if flag in PAUSE_FLAGS else None
    if new_status and new_status != c["status"]:
        _revise(conn, card_id, "status", c["status"], new_status, f"前置过滤：{FLAG_NAMES[flag]}", "system")
        conn.execute("UPDATE cards SET status=? WHERE id=?", (new_status, card_id))
    conn.commit()
    return new_status
