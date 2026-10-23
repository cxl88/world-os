"""每日简报：确定性规则生成，不调用模型。

内容：行动警报 → 今日机会 → 今日行动 → 少量新信息 → 本月账本。
已淘汰、暂停、未审核、未通过过滤的卡不会被推荐。
评分之后证据或卡片内容有变化的卡仍会出现，但会明确标出“评分可能已过期”。
"""
from datetime import datetime, timedelta

from . import evidence, llm, scoring

ACTIVE = ("researching", "validating")


def _days_since(iso):
    if not iso:
        return None
    return (datetime.now().astimezone() - datetime.fromisoformat(iso)).days


def recommendable(conn):
    return [r for r in scoring.latest_scores(conn)
            if r["status"] in ACTIVE and r["reviewed"] == 1 and r["filter_flag"] == "ok" and r["total"] is not None]


def build(conn, today=None):
    today = today or datetime.now().astimezone().date().isoformat()
    month = today[:7]
    lines = [f"# WORLD OS 每日简报 {today}", ""]

    # 1. 警报：防止“研究越来越多、行动越来越少”
    lines.append("## 警报")
    alerts = []
    last = conn.execute(
        "SELECT MAX(created_at) FROM logs WHERE kind IN ('interview','quote','intent','contract','payment')"
    ).fetchone()[0]
    d = _days_since(last)
    if d is None:
        alerts.append("还没有任何客户访谈或报价记录。今天先联系一个潜在付费方。")
    elif d >= 3:
        alerts.append(f"已经 {d} 天没有和潜在客户交流。")
    week_ago = (datetime.now().astimezone() - timedelta(days=7)).isoformat()
    t = {r[0]: r[1] for r in conn.execute(
        "SELECT category, SUM(minutes) FROM logs WHERE kind='time' AND created_at>=? GROUP BY category", (week_ago,))}
    build_m, out_m = t.get("build") or 0, t.get("outreach") or 0
    if build_m > 0 and build_m > 2 * out_m:
        alerts.append(f"近 7 天开发 {build_m} 分钟，客户触达 {out_m} 分钟。开发时间超过触达的 2 倍，暂停加功能。")
    for a in conn.execute("SELECT id, title, due FROM actions WHERE status='open' AND due IS NOT NULL AND due < ?",
                          (today,)):
        alerts.append(f"行动 #{a['id']}「{a['title']}」已过期（截止 {a['due']}）。")
    unreviewed = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE reviewed=0 AND status NOT IN ('killed','won')").fetchone()[0]
    if unreviewed:
        alerts.append(f"{unreviewed} 张 AI 生成的机会卡还没人工审核，审核前不会被推荐。")
    suspicious = conn.execute(
        "SELECT COUNT(*) FROM items WHERE flags LIKE '%possible_injection%' AND processed_at IS NULL").fetchone()[0]
    if suspicious:
        alerts.append(f"{suspicious} 条未处理信息含疑似指令文本，分析时只作数据看待。")
    ranked = recommendable(conn)
    stale = {r["id"]: scoring.stale_reasons(conn, r["id"]) for r in ranked}
    stale_ids = [f"#{cid}" for cid, why in stale.items() if why]
    if stale_ids:
        alerts.append(f"{len(stale_ids)} 张候选卡（{'、'.join(stale_ids)}）评分后证据或内容有变化，"
                      "排序用的是旧分数，请重新评分。")
    lines += [f"- {a}" for a in alerts] or ["- 无"]
    lines.append("")

    # 2. 今日机会
    lines.append("## 今日机会")
    pick = ranked[0] if ranked else None
    if pick:
        p = evidence.profile(conn, pick["id"])
        lines.append(f"**#{pick['id']} {pick['name']}**（{pick['bug_type'] or '未分类'}｜{pick['total']} 分）")
        if stale[pick["id"]]:
            lines.append(f"- 【注意】评分可能已过期：{'；'.join(stale[pick['id']])}。"
                         f"请用 score {pick['id']} … --reason 重新评分")
        lines += [
            f"- 证据强度：{evidence.TIER_NAMES[p['tier']]}，独立来源 {p['independent_sources']} 个",
            f"- 成交状态：{evidence.DEAL_NAMES[p['deal_stage']]}",
            f"- 问题：{pick['problem'] or '未填'}",
            f"- 潜在付费方（假设）：{pick['payers'] or '未知'}",
            f"- 放弃条件：{pick['kill_condition'] or '未填，请补上'}",
        ]
    else:
        lines.append("- 暂无。把一张已审核并评分的卡状态设为 researching 或 validating。")
    lines.append("")

    # 3. 今日行动
    lines.append("## 今日行动")
    if pick:
        act = conn.execute(
            "SELECT * FROM actions WHERE card_id=? AND status='open' ORDER BY COALESCE(due,'9999'), id LIMIT 1",
            (pick["id"],)).fetchone()
        if act:
            lines += [
                f"- #{act['id']} {act['title']}（截止 {act['due'] or '未设'}，预算 {act['minutes_budget'] or '?'} 分钟"
                f" / {act['money_budget'] or 0} 元）",
                f"- 验证的假设：{act['hypothesis'] or '未填'}",
                f"- 验收标准：{act['acceptance'] or '未填'}",
            ]
        else:
            lines.append(f"- 该卡没有待办行动。建议创建：{pick['min_validation'] or '找到并联系 3 个潜在付费方'}")
    else:
        lines.append("- 从候选卡里挑一张，补证据、评分，然后安排一次客户访谈。")
    lines.append("")

    # 4. 新信息
    lines.append("## 新信息（最多 3 条）")
    items = conn.execute(
        "SELECT id, title, source, credibility, flags FROM items WHERE processed_at IS NULL "
        "ORDER BY credibility ASC, id DESC LIMIT 3").fetchall()
    lines += [f"- [{i['credibility']}] #{i['id']} {i['title']}（{i['source']}）"
              + ("［疑似指令文本］" if i["flags"] else "") for i in items] or ["- 无未处理信息"]
    lines.append("")

    # 5. 本月账本
    g = llm.ledger(conn, month)
    sim = conn.execute("SELECT COUNT(*) FROM llm_calls WHERE simulated=1 AND substr(created_at,1,7)=?",
                       (month,)).fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM llm_calls WHERE status!='ok' AND substr(created_at,1,7)=?",
                          (month,)).fetchone()[0]
    money = {r[0]: r[1] for r in conn.execute(
        "SELECT kind, COALESCE(SUM(amount),0) FROM logs WHERE kind IN ('cost','quote','payment') "
        "AND substr(created_at,1,7)=? GROUP BY kind", (month,))}
    talks = conn.execute("SELECT COUNT(*) FROM logs WHERE kind='interview' AND substr(created_at,1,7)=?",
                         (month,)).fetchone()[0]
    mins = {r[0]: r[1] for r in conn.execute(
        "SELECT category, COALESCE(SUM(minutes),0) FROM logs WHERE kind='time' AND substr(created_at,1,7)=? "
        "GROUP BY category", (month,))}
    lines += [
        "## 本月账本",
        f"- 真实模型调用 {g['ok']} 次，${g['spend']:.4f}"
        + (f"（其中 {g['unknown_n']} 笔用量未知，按上限预估 ${g['unknown']:.4f}，待对账）" if g["unknown_n"] else "")
        + f"；模拟调用 {sim} 次（不计费）；失败或被拦截 {failed} 次",
        f"- 其他成本 {money.get('cost', 0):.2f} 元；报价金额 {money.get('quote', 0):.2f} 元；实际回款 {money.get('payment', 0):.2f} 元",
        f"- 客户访谈 {talks} 次",
        "- 工时（分钟）：" + ("，".join(f"{k or '未分类'} {v}" for k, v in mins.items()) or "未记录"),
    ]
    return "\n".join(lines) + "\n"
