"""验证记录：行动（假设—验收—结论）与现实反馈日志（访谈、报价、意向、合同、回款、成本、工时、认知、体验）。"""
from . import cards, db, evidence

LOG_KINDS = ["interview", "quote", "intent", "contract", "payment", "cost", "time", "insight", "experience"]
LOG_NAMES = {"interview": "访谈", "quote": "报价", "intent": "合作意向", "contract": "合同", "payment": "实际回款",
             "cost": "成本", "time": "工时", "insight": "认知", "experience": "体验"}
# 这些日志代表与真实客户的接触，必须写对方代号；可同时生成一条已核实的客户类证据
CUSTOMER_LOGS = {"interview": "customer_statement", "quote": "quote", "intent": "intent",
                 "contract": "contract", "payment": "payment"}
MONEY_LOGS = {"quote", "contract", "payment", "cost"}
TIME_CATEGORIES = ["build", "research", "outreach", "delivery"]
DECISIONS = ["continue", "adjust", "pause", "kill"]


def add_action(conn, card_id, title, purpose=None, hypothesis=None, acceptance=None,
               minutes=None, money=None, due=None):
    if not (title or "").strip():
        raise ValueError("行动必须有标题")
    if card_id is not None:
        c = cards.get(conn, card_id)
        cards.ensure_open(c)
        if c["filter_flag"] != "ok":
            raise ValueError(f"机会卡 #{card_id} 未通过前置过滤，不能安排验证行动")
    if minutes is not None and minutes < 0 or money is not None and money < 0:
        raise ValueError("预算不能为负数")
    return db.insert(conn, "actions", {
        "card_id": card_id, "title": title.strip(), "purpose": purpose, "hypothesis": hypothesis,
        "acceptance": acceptance, "minutes_budget": minutes, "money_budget": money, "due": due,
        "created_at": db.now()})


def close_action(conn, action_id, result, decision, dropped=False):
    a = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
    if a is None:
        raise ValueError(f"行动 {action_id} 不存在")
    if a["status"] != "open":
        raise ValueError(f"行动 #{action_id} 已经关闭")
    if decision not in DECISIONS:
        raise ValueError(f"结论必须是 {DECISIONS}")
    if not (result or "").strip():
        raise ValueError("关闭行动必须写实际结果")
    conn.execute("UPDATE actions SET status=?, result=?, decision=?, done_at=? WHERE id=?",
                 ("dropped" if dropped else "done", result, decision, db.now(), action_id))
    conn.commit()
    if a["card_id"] and decision in ("pause", "kill"):
        target = "paused" if decision == "pause" else "killed"
        c = cards.get(conn, a["card_id"])
        if c["status"] != target and target in cards.TRANSITIONS[c["status"]]:
            cards.set_status(conn, a["card_id"], target, f"行动 #{action_id} 结论：{decision}")


def add_log(conn, kind, card_id=None, amount=None, minutes=None, category=None, counterpart=None,
            note=None, claim=None):
    """返回 (log_id, evidence_id 或 None)。"""
    if kind not in LOG_KINDS:
        raise ValueError(f"记录类型必须是 {LOG_KINDS}")
    if kind in CUSTOMER_LOGS and not (counterpart or "").strip():
        raise ValueError(f"{LOG_NAMES[kind]}记录必须写对方代号（--who），只写你自己能识别的代号")
    if kind in ("quote", "contract", "payment") and amount is None:
        raise ValueError(f"{LOG_NAMES[kind]}记录必须写金额（--amount）")
    if amount is not None and amount < 0:
        raise ValueError("金额不能为负数")
    if kind == "time":
        if minutes is None or minutes <= 0:
            raise ValueError("工时记录必须写正的分钟数（--minutes）")
        if category not in TIME_CATEGORIES:
            raise ValueError(f"工时记录必须写类别 --category {TIME_CATEGORIES}")
    if card_id is not None:
        c = cards.get(conn, card_id)
        if c["status"] == "killed" and kind in CUSTOMER_LOGS:
            raise ValueError(f"机会卡 #{card_id} 已淘汰，不能再记录客户推进")
    if claim and (card_id is None or kind not in CUSTOMER_LOGS):
        raise ValueError("--claim 只用于关联到机会卡的访谈/报价/意向/合同/回款记录")
    try:
        lid = db.insert(conn, "logs", {
            "card_id": card_id, "kind": kind, "category": category, "amount": amount, "minutes": minutes,
            "counterpart": (counterpart or "").strip() or None, "note": note, "created_at": db.now()},
            commit=False)
        eid = None
        if claim:
            # 人亲自录入的真实接触记录，视为人工核实
            eid = evidence.add(conn, card_id, CUSTOMER_LOGS[kind], claim, kind="fact",
                               counterpart=counterpart.strip(), log_id=lid, origin="manual", verified=True,
                               commit=False)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return lid, eid
