"""命令行入口：python -m worldos <命令>。运行 python -m worldos -h 查看全部命令。"""
import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime

from . import brief, db, importers, llm, prompts, scoring

CARD_SET_FIELDS = set(importers.CARD_FIELDS) | {"status", "last_verified_at"}
STATUSES = ["candidate", "researching", "validating", "paused", "killed", "won"]
LOG_KINDS = ["interview", "quote", "cost", "revenue", "time", "insight", "experience"]


def out(s=""):
    sys.stdout.write(s + "\n")


# ---------- 信息 ----------
def cmd_item_add(conn, a):
    iid, created = importers.add_item(conn, a.title, a.url, a.source, a.content, a.cred, a.published)
    out(f"信息 #{iid} " + ("已录入" if created else "已存在，跳过（去重）"))


def cmd_item_import(conn, a):
    new, dup = importers.import_file(conn, a.path, a.source)
    out(f"导入 {new} 条，重复跳过 {dup} 条")


def cmd_rss(conn, a):
    new, dup = importers.import_rss_url(conn, a.url, a.source)
    out(f"RSS 导入 {new} 条，重复跳过 {dup} 条")


def cmd_items(conn, a):
    q = "SELECT * FROM items" + ("" if a.all else " WHERE processed_at IS NULL") + " ORDER BY id DESC LIMIT ?"
    for r in conn.execute(q, (a.limit,)):
        out(f"#{r['id']:<4} [{r['credibility']}] {r['title']}  ({r['source'] or '-'}) {r['url'] or ''}")


# ---------- Bug 提取 ----------
def _profile():
    p = os.environ.get("WORLDOS_PROFILE", "profile.md")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read()
    return "（未提供个人资源档案）"


def cmd_extract(conn, a):
    if a.ids:
        ids = [int(x) for x in a.ids.split(",")]
        rows = conn.execute(f"SELECT * FROM items WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    else:
        rows = conn.execute("SELECT * FROM items WHERE processed_at IS NULL ORDER BY id LIMIT ?", (a.limit,)).fetchall()
    if not rows:
        out("没有待处理的信息")
        return
    items_txt = "\n\n".join(
        f"[item_id={r['id']}] 标题：{r['title']}\n来源：{r['source'] or '未知'}（可信度 {r['credibility']}）"
        f"｜时间：{r['published_at'] or '未知'}｜链接：{r['url'] or '无'}\n内容：{(r['content'] or '')[:1500]}"
        for r in rows)
    user = prompts.EXTRACT_USER.format(profile=_profile(), items=items_txt)
    if a.manual or not llm.configured():
        os.makedirs("prompts", exist_ok=True)
        path = os.path.join("prompts", f"extract-{datetime.now():%Y%m%d-%H%M%S}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"## 系统提示\n\n{prompts.EXTRACT_SYSTEM}\n\n## 用户输入\n\n{user}\n")
        out(f"手动模式：提示词已写入 {path}")
        out("把它粘贴到你已有的聊天工具，把返回的 JSON 存成文件，然后运行：")
        out("  python -m worldos cards-import <文件.json> --ai --mark-items " + ",".join(str(r["id"]) for r in rows))
        return
    text = llm.chat(conn, "extract", prompts.EXTRACT_SYSTEM, user)
    cards = llm.parse_json(text)
    _import_cards(conn, cards, origin="ai")
    _mark(conn, [r["id"] for r in rows])


def _mark(conn, ids):
    conn.executemany("UPDATE items SET processed_at=? WHERE id=?", [(db.now(), i) for i in ids])
    conn.commit()


def _import_cards(conn, cards, origin):
    if isinstance(cards, dict):
        cards = [cards]
    for c in cards:
        sims = importers.similar_cards(conn, c.get("name", ""))
        cid = importers.add_card(conn, c, origin=origin)
        tag = "（AI 生成，待人工审核）" if origin == "ai" else ""
        out(f"机会卡 #{cid} {c.get('name')} {tag}")
        for sid, sname, ratio in sims:
            out(f"  ⚠ 与已有卡 #{sid}「{sname}」相似度 {ratio}，可能重复")
    if not cards:
        out("没有生成机会卡（模型认为信息里没有值得记录的 Bug）")


# ---------- 机会卡 ----------
def cmd_card_template(conn, a):
    tpl = {k: "" for k in importers.CARD_FIELDS}
    tpl["evidence"] = [{"url": "", "claim": "", "kind": "fact", "level": 1, "verified": 1, "observed_at": ""}]
    out(json.dumps(tpl, ensure_ascii=False, indent=2))


def cmd_cards_import(conn, a):
    with open(a.path, encoding="utf-8") as f:
        text = f.read()
    _import_cards(conn, llm.parse_json(text), origin="ai" if a.ai else "manual")
    if a.mark_items:
        _mark(conn, [int(x) for x in a.mark_items.split(",")])


def cmd_card_add(conn, a):
    data = {k: getattr(a, k) for k in importers.CARD_FIELDS if getattr(a, k, None)}
    _import_cards(conn, [data], origin="manual")


def cmd_cards(conn, a):
    for r in scoring.latest_scores(conn):
        if a.status and r["status"] != a.status:
            continue
        sc = "-" if r["total"] is None else f"{r['total']:.0f}"
        lv = "-" if r["evidence_level"] is None else f"E{r['evidence_level']}"
        rv = "" if r["reviewed"] else " [待审核]"
        out(f"#{r['id']:<4} {sc:>4}分 {lv:<3} {r['status']:<11} {r['bug_type'] or '':<5} {r['name']}{rv}")


def cmd_card(conn, a):
    c = conn.execute("SELECT * FROM cards WHERE id=?", (a.id,)).fetchone()
    if not c:
        out("不存在")
        return
    out(card_markdown(conn, c))


def card_markdown(conn, c):
    labels = {
        "bug_type": "类型", "domain": "领域", "problem": "问题", "affected": "受影响者", "competitors": "现有方案/竞争",
        "why_unsolved": "为何未解决", "why_now": "为何现在", "payers": "潜在付费方（假设）", "solution": "解决方案",
        "resources": "所需资源", "revenue_model": "盈利方式（假设）", "cost_risk": "成本与风险",
        "min_validation": "最小验证行动", "kill_condition": "放弃条件",
    }
    lines = [f"# #{c['id']} {c['name']}",
             f"状态 {c['status']}｜过滤 {c['filter_flag']}｜来源 {c['origin']}｜{'已审核' if c['reviewed'] else '待审核'}"
             f"｜创建 {c['created_at']}｜最后验证 {c['last_verified_at'] or '从未'}", ""]
    lines += [f"- **{v}**：{c[k] or '—'}" for k, v in labels.items()]
    lines += ["", "## 证据"]
    for e in conn.execute("SELECT * FROM evidence WHERE card_id=? ORDER BY id", (c["id"],)):
        mark = "✔" if e["verified"] else "✘未核实"
        lines.append(f"- [{e['id']}] E{e['level']} {e['kind']} {mark}：{e['claim']}"
                     f"（{e['url'] or ('信息#' + str(e['item_id']) if e['item_id'] else '无来源')}，{e['observed_at'] or '时间未知'}）")
    s = conn.execute("SELECT * FROM scores WHERE card_id=? ORDER BY id DESC LIMIT 1", (c["id"],)).fetchone()
    if s:
        lines += ["", f"## 最近评分 {s['total']}（原始 {s['raw_total']}，E{s['evidence_level']}，{s['created_at']}）",
                  f"痛点{s['pain']} 接触{s['access']} 技术{s['feasibility']} 复用{s['reuse']} 风险{s['risk']}｜{s['note'] or ''}"]
    lines += ["", "## 行动"]
    for t in conn.execute("SELECT * FROM actions WHERE card_id=? ORDER BY id", (c["id"],)):
        lines.append(f"- #{t['id']} [{t['status']}] {t['title']}｜假设：{t['hypothesis'] or '—'}｜验收：{t['acceptance'] or '—'}"
                     + (f"｜结果：{t['result']}｜结论：{t['decision']}" if t["status"] != "open" else ""))
    lines += ["", "## 反馈记录"]
    for g in conn.execute("SELECT * FROM logs WHERE card_id=? ORDER BY id", (c["id"],)):
        lines.append(f"- {g['created_at'][:10]} {g['kind']} {g['counterpart'] or ''} {g['amount'] or ''} {g['note'] or ''}")
    return "\n".join(lines)


def cmd_card_set(conn, a):
    if a.field not in CARD_SET_FIELDS:
        raise ValueError(f"不能修改字段 {a.field}；可改：{', '.join(sorted(CARD_SET_FIELDS))}")
    if a.field == "status" and a.value not in STATUSES:
        raise ValueError(f"状态必须是 {STATUSES}")
    c = conn.execute("SELECT reviewed FROM cards WHERE id=?", (a.id,)).fetchone()
    if c is None:
        raise ValueError(f"机会卡 {a.id} 不存在")
    if a.field == "status" and a.value in ("researching", "validating") and not c["reviewed"]:
        raise ValueError("AI 生成的卡必须先 review 才能进入研究/验证")
    conn.execute(f"UPDATE cards SET {a.field}=? WHERE id=?", (a.value, a.id))
    conn.commit()
    out(f"#{a.id} {a.field} = {a.value}")


def cmd_review(conn, a):
    conn.execute("UPDATE cards SET reviewed=1 WHERE id=?", (a.id,))
    conn.commit()
    out(f"#{a.id} 已人工审核。注意：AI 给的证据仍是 E0，需逐条 evidence-verify 才会计入证据等级。")


def cmd_filter(conn, a):
    st = scoring.apply_filter(conn, a.id, a.flag)
    out(f"#{a.id} 过滤标记 {a.flag}" + (f"，状态改为 {st}" if st else ""))


# ---------- 证据 ----------
def cmd_evidence_add(conn, a):
    eid = db.insert(conn, "evidence", {
        "card_id": a.card, "item_id": a.item, "url": a.url, "claim": a.claim, "kind": a.kind,
        "level": a.level, "observed_at": a.observed, "verified": int(a.verified), "created_at": db.now()})
    if a.verified:
        conn.execute("UPDATE cards SET last_verified_at=? WHERE id=?", (db.now(), a.card))
        conn.commit()
    out(f"证据 #{eid} 已添加到卡 #{a.card}")


def cmd_evidence_verify(conn, a):
    e = conn.execute("SELECT card_id FROM evidence WHERE id=?", (a.id,)).fetchone()
    conn.execute("UPDATE evidence SET verified=1, level=?, kind=COALESCE(?, kind) WHERE id=?", (a.level, a.kind, a.id))
    conn.execute("UPDATE cards SET last_verified_at=? WHERE id=?", (db.now(), e["card_id"]))
    conn.commit()
    out(f"证据 #{a.id} 已核实，等级 E{a.level}")


# ---------- 评分 ----------
def cmd_score(conn, a):
    raw, total, warns = scoring.score_card(
        conn, a.card, {k: getattr(a, k) for k in scoring.WEIGHTS}, note=a.note)
    for w in warns:
        out("⚠ " + w)
    out(f"#{a.card} 原始 {raw} 分 → 记录 {total} 分")


# ---------- 行动与反馈 ----------
def cmd_action_add(conn, a):
    aid = db.insert(conn, "actions", {
        "card_id": a.card, "title": a.title, "purpose": a.purpose, "hypothesis": a.hypothesis,
        "acceptance": a.acceptance, "minutes_budget": a.minutes, "money_budget": a.money,
        "due": a.due, "created_at": db.now()})
    out(f"行动 #{aid} 已创建")


def cmd_action_done(conn, a):
    conn.execute("UPDATE actions SET status=?, result=?, decision=?, done_at=? WHERE id=?",
                 ("dropped" if a.dropped else "done", a.result, a.decision, db.now(), a.id))
    row = conn.execute("SELECT card_id FROM actions WHERE id=?", (a.id,)).fetchone()
    if a.decision in ("pause", "kill") and row and row["card_id"]:
        conn.execute("UPDATE cards SET status=? WHERE id=?",
                     ("paused" if a.decision == "pause" else "killed", row["card_id"]))
    conn.commit()
    out(f"行动 #{a.id} 已关闭，结论 {a.decision or '未填'}")


def cmd_actions(conn, a):
    q = "SELECT a.*, c.name FROM actions a LEFT JOIN cards c ON c.id=a.card_id"
    q += "" if a.all else " WHERE a.status='open'"
    for r in conn.execute(q + " ORDER BY COALESCE(a.due,'9999'), a.id"):
        out(f"#{r['id']:<4} [{r['status']}] 截止 {r['due'] or '-':<10} {r['title']}  ← {r['name'] or '无关联卡'}")


def cmd_log(conn, a):
    lid = db.insert(conn, "logs", {
        "card_id": a.card, "kind": a.kind, "category": a.category, "amount": a.amount,
        "minutes": a.minutes, "counterpart": a.who, "note": a.note, "created_at": db.now()})
    out(f"记录 #{lid}（{a.kind}）已保存")


# ---------- 输出 ----------
def cmd_brief(conn, a):
    text = brief.build(conn)
    out(text)
    if a.save:
        os.makedirs("briefs", exist_ok=True)
        path = os.path.join("briefs", f"{datetime.now():%Y-%m-%d}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        out(f"已保存到 {path}")


def cmd_export(conn, a):
    os.makedirs(os.path.join(a.out, "cards"), exist_ok=True)
    dump = {}
    for t in ["items", "cards", "evidence", "scores", "actions", "logs", "llm_calls"]:
        dump[t] = [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
    with open(os.path.join(a.out, "worldos.json"), "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2)
    for c in conn.execute("SELECT * FROM cards"):
        with open(os.path.join(a.out, "cards", f"{c['id']:04d}.md"), "w", encoding="utf-8") as f:
            f.write(card_markdown(conn, c) + "\n")
    out(f"已导出到 {a.out}/（worldos.json + cards/*.md）")


def cmd_backup(conn, a):
    os.makedirs("backups", exist_ok=True)
    path = os.path.join("backups", f"worldos-{datetime.now():%Y%m%d-%H%M%S}.db")
    dst = sqlite3.connect(path)
    conn.backup(dst)
    dst.close()
    out(f"已备份到 {path}")


def cmd_cost(conn, a):
    for r in conn.execute(
            "SELECT substr(created_at,1,7) AS m, task, model, COUNT(*) AS n, SUM(input_tokens) AS i, "
            "SUM(output_tokens) AS o, SUM(cost_usd) AS c FROM llm_calls GROUP BY m, task, model ORDER BY m"):
        out(f"{r['m']} {r['task']:<8} {r['model']:<16} {r['n']} 次 输入 {r['i']} 输出 {r['o']} ${r['c']:.4f}")
    out(f"本月合计 ${llm.month_spend(conn):.4f}")


def build_parser():
    p = argparse.ArgumentParser(prog="worldos", description="WORLD OS V1 本地命令行")
    p.add_argument("--db", help="数据库路径，默认 ./worldos.db 或 $WORLDOS_DB")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    add("init", lambda c, a: out("数据库已就绪"), "初始化数据库")

    s = add("item-add", cmd_item_add, "人工录入一条信息")
    s.add_argument("--title", required=True); s.add_argument("--url"); s.add_argument("--source")
    s.add_argument("--content"); s.add_argument("--cred", default="C", choices=["A", "B", "C"])
    s.add_argument("--published")
    s = add("item-import", cmd_item_import, "从 JSON/CSV/RSS 文件导入信息")
    s.add_argument("path"); s.add_argument("--source")
    s = add("rss", cmd_rss, "从公开 RSS 地址导入")
    s.add_argument("url"); s.add_argument("--source")
    s = add("items", cmd_items, "列出信息（默认只列未处理）")
    s.add_argument("--all", action="store_true"); s.add_argument("--limit", type=int, default=30)

    s = add("extract", cmd_extract, "用模型从信息中提取候选 Bug（无 Key 时生成提示词文件）")
    s.add_argument("--ids"); s.add_argument("--limit", type=int, default=10)
    s.add_argument("--manual", action="store_true")

    add("card-template", cmd_card_template, "打印机会卡 JSON 模板")
    s = add("cards-import", cmd_cards_import, "从 JSON 文件导入机会卡")
    s.add_argument("path"); s.add_argument("--ai", action="store_true", help="来自模型输出，需人工审核")
    s.add_argument("--mark-items", help="同时把这些信息标记为已处理，如 1,2,3")
    s = add("card-add", cmd_card_add, "快速新建机会卡")
    for f in importers.CARD_FIELDS:
        s.add_argument("--" + f.replace("_", "-"), dest=f, required=(f == "name"))
    s = add("cards", cmd_cards, "按分数列出机会卡")
    s.add_argument("--status", choices=STATUSES)
    s = add("card", cmd_card, "查看机会卡详情"); s.add_argument("id", type=int)
    s = add("card-set", cmd_card_set, "修改机会卡字段/状态")
    s.add_argument("id", type=int); s.add_argument("field"); s.add_argument("value")
    s = add("review", cmd_review, "人工审核 AI 生成的卡"); s.add_argument("id", type=int)
    s = add("filter", cmd_filter, "前置过滤标记")
    s.add_argument("id", type=int)
    s.add_argument("flag", choices=["ok"] + sorted(scoring.KILL_FLAGS | scoring.PAUSE_FLAGS))

    s = add("evidence-add", cmd_evidence_add, "给机会卡添加证据")
    s.add_argument("card", type=int); s.add_argument("--claim", required=True); s.add_argument("--url")
    s.add_argument("--item", type=int); s.add_argument("--kind", default="fact", choices=["fact", "inference", "forecast"])
    s.add_argument("--level", type=int, default=1, choices=[0, 1, 2, 3]); s.add_argument("--observed")
    s.add_argument("--verified", action="store_true")
    s = add("evidence-verify", cmd_evidence_verify, "人工核实一条证据并定级")
    s.add_argument("id", type=int); s.add_argument("--level", type=int, required=True, choices=[0, 1, 2, 3])
    s.add_argument("--kind", choices=["fact", "inference", "forecast"])

    s = add("score", cmd_score, "评分（各维度 0-5）")
    s.add_argument("card", type=int)
    for k in scoring.WEIGHTS:
        s.add_argument("--" + k, type=int, required=True, help=scoring.DIMENSION_NAMES[k])
    s.add_argument("--note")

    s = add("action-add", cmd_action_add, "为机会卡创建验证行动")
    s.add_argument("card", type=int); s.add_argument("--title", required=True)
    s.add_argument("--purpose"); s.add_argument("--hypothesis"); s.add_argument("--acceptance")
    s.add_argument("--minutes", type=int); s.add_argument("--money", type=float); s.add_argument("--due")
    s = add("action-done", cmd_action_done, "关闭行动并给出结论")
    s.add_argument("id", type=int); s.add_argument("--result", required=True)
    s.add_argument("--decision", choices=["continue", "adjust", "pause", "kill"], required=True)
    s.add_argument("--dropped", action="store_true")
    s = add("actions", cmd_actions, "列出行动"); s.add_argument("--all", action="store_true")

    s = add("log", cmd_log, "记录现实反馈：访谈/报价/成本/回款/工时/认知/体验")
    s.add_argument("kind", choices=LOG_KINDS); s.add_argument("--card", type=int)
    s.add_argument("--amount", type=float, help="金额（元）"); s.add_argument("--minutes", type=int)
    s.add_argument("--category", choices=["build", "research", "outreach", "delivery"])
    s.add_argument("--who", help="对方（只写你自己能识别的代号，不写隐私信息）"); s.add_argument("--note")

    s = add("brief", cmd_brief, "生成每日简报"); s.add_argument("--save", action="store_true")
    s = add("export", cmd_export, "导出 JSON + Markdown"); s.add_argument("--out", default="export")
    add("backup", cmd_backup, "备份数据库")
    add("cost", cmd_cost, "模型调用成本统计")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    conn = db.connect(a.db)
    try:
        a.fn(conn, a)
    except (ValueError, llm.BudgetExceeded) as e:
        out(f"错误：{e}")
        return 1
    finally:
        conn.close()
    return 0
