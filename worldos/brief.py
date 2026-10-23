"""每日简报：确定性规则生成，不调用模型。

内容：行动警报 → 今日机会 → 今日行动 → 少量新信息 → 本月账本。
"""
from datetime import datetime, timedelta

from . import db, scoring

ACTIVE = ("researching", "validating")


def _days_since(iso):
    if not iso:
        return None
    return (datetime.now().astimezone() - datetime.fromisoformat(iso)).days


def build(conn, today=None):
    today = today or datetime.now().astimezone().date().isoformat()
    month = today[:7]
    lines = [f"# WORLD OS 每日简报 {today}", ""]

    # 1. 行动警报：防止“研究越来越多、行动越来越少”
    lines.append("## 警报")
    alerts = []
    last = conn.execute(
        "SELECT MAX(created_at) AS t FROM logs WHERE kind IN ('interview','quote')"
    ).fetchone()["t"]
    d = _days_since(last)
    if d is None:
        alerts.append("还没有任何客户访谈或报价记录。今天先联系一个潜在付费方。")
    elif d >= 3:
        alerts.append(f"已经 {d} 天没有和潜在客户交流。")
    week_ago = (datetime.now().astimezone() - timedelta(days=7)).isoformat()
    t = {r["category"]: r["m"] for r in conn.execute(
        "SELECT category, SUM(minutes) AS m FROM logs WHERE kind='time' AND created_at>=? GROUP BY category",
        (week_ago,))}
    build_m, out_m = t.get("build", 0) or 0, t.get("outreach", 0) or 0
    if build_m > 0 and build_m > 2 * out_m:
        alerts.append(f"近 7 天开发 {build_m} 分钟，客户触达 {out_m} 分钟。开发时间超过触达的 2 倍，暂停加功能。")
    overdue = conn.execute(
        "SELECT id, title, due FROM actions WHERE status='open' AND due IS NOT NULL AND due < ?", (today,)
    ).fetchall()
    for a in overdue:
        alerts.append(f"行动 #{a['id']}「{a['title']}」已过期（截止 {a['due']}）。")
    unreviewed = conn.execute("SELECT COUNT(*) AS n FROM cards WHERE reviewed=0").fetchone()["n"]
    if unreviewed:
        alerts.append(f"{unreviewed} 张 AI 生成的机会卡还没人工审核，审核前不得进入验证。")
    lines += [f"- {a}" for a in alerts] or ["- 无"]
    lines.append("")

    # 2. 今日机会：处于研究/验证中、已审核、通过过滤的最高分卡
    lines.append("## 今日机会")
    ranked = [r for r in scoring.latest_scores(conn)
              if r["status"] in ACTIVE and r["reviewed"] == 1 and r["filter_flag"] == "ok" and r["total"] is not None]
    pick = ranked[0] if ranked else None
    if pick:
        lv = scoring.EVIDENCE_NAMES[pick["evidence_level"]]
        lines += [
            f"**#{pick['id']} {pick['name']}**（{pick['bug_type'] or '未分类'}｜{pick['total']} 分｜{lv}）",
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
                f"- #{act['id']} {act['title']}（截止 {act['due'] or '未设'}，预算 {act['minutes_budget'] or '?'} 分钟 / {act['money_budget'] or 0} 元）",
                f"- 验证的假设：{act['hypothesis'] or '未填'}",
                f"- 验收标准：{act['acceptance'] or '未填'}",
            ]
        else:
            lines.append(f"- 该卡没有待办行动。建议创建：{pick['min_validation'] or '找到并联系 3 个潜在付费方'}")
    else:
        lines.append("- 从候选卡里挑一张，补证据、评分，然后安排一次客户访谈。")
    lines.append("")

    # 4. 新信息（最多 3 条，未处理、可信度优先）
    lines.append("## 新信息（最多 3 条）")
    items = conn.execute(
        "SELECT id, title, source, credibility, url FROM items WHERE processed_at IS NULL "
        "ORDER BY credibility ASC, id DESC LIMIT 3").fetchall()
    lines += [f"- [{i['credibility']}] #{i['id']} {i['title']}（{i['source'] or '未知来源'}）" for i in items] or ["- 无未处理信息"]
    lines.append("")

    # 5. 本月账本
    llm = conn.execute(
        "SELECT COALESCE(SUM(cost_usd),0) AS c, COUNT(*) AS n FROM llm_calls WHERE substr(created_at,1,7)=?",
        (month,)).fetchone()
    money = {r["kind"]: r["s"] for r in conn.execute(
        "SELECT kind, COALESCE(SUM(amount),0) AS s FROM logs WHERE kind IN ('cost','revenue') "
        "AND substr(created_at,1,7)=? GROUP BY kind", (month,))}
    talks = conn.execute(
        "SELECT COUNT(*) AS n FROM logs WHERE kind='interview' AND substr(created_at,1,7)=?", (month,)).fetchone()["n"]
    mins = {r["category"]: r["m"] for r in conn.execute(
        "SELECT category, COALESCE(SUM(minutes),0) AS m FROM logs WHERE kind='time' AND substr(created_at,1,7)=? "
        "GROUP BY category", (month,))}
    lines += [
        "## 本月账本",
        f"- 模型调用 {llm['n']} 次，${llm['c']:.4f}",
        f"- 其他成本 {money.get('cost', 0):.2f} 元，回款 {money.get('revenue', 0):.2f} 元",
        f"- 客户访谈 {talks} 次",
        "- 工时（分钟）：" + ("，".join(f"{k or '未分类'} {v}" for k, v in mins.items()) or "未记录"),
    ]
    return "\n".join(lines) + "\n"
