"""命令行入口：python -m worldos <命令>。运行 python -m worldos -h 查看全部命令。

全局参数：
  --db PATH     指定数据库文件（数据目录 = 其所在目录）
  --porcelain   新建类命令只输出新记录的 id，方便在 PowerShell / Bash 脚本里取值
"""
import argparse
import json
import os
import sys

from . import (backup, brief, cards, db, evidence, extract, importers, llm, records, scoring)

CTX = {}


def out(s=""):
    if not CTX.get("porcelain"):
        sys.stdout.write(s + "\n")


def created(new_id, message):
    """新建类命令统一出口：porcelain 模式只打印 id。"""
    if CTX.get("porcelain"):
        sys.stdout.write(f"{new_id}\n")
    else:
        sys.stdout.write(message + "\n")


def _ids(text):
    try:
        return [int(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise ValueError(f"id 列表格式应为 1,2,3，收到 {text!r}")


# ---------- 初始化 ----------
def cmd_init(conn, a):
    out(f"数据库：{CTX['db_path']}")
    out(f"数据目录：{CTX['data_dir']}（提示词、简报、备份、导出都在这里）")
    out(f"结构版本：{db.SCHEMA_VERSION}")


# ---------- 信息 ----------
def cmd_item_add(conn, a):
    iid, is_new = importers.add_item(conn, a.title, a.url, a.source, a.content, a.cred, a.published)
    flags = conn.execute("SELECT flags FROM items WHERE id=?", (iid,)).fetchone()[0]
    msg = f"信息 #{iid} " + ("已录入" if is_new else "已存在，跳过（去重）")
    if flags:
        msg += "；[注意] 内容含疑似指令文本，分析时只作数据看待"
    created(iid, msg)


def _print_stats(stats):
    out(f"新增 {stats['new']} 条，重复跳过 {stats['duplicate']} 条，缺少来源跳过 {stats['missing_source']} 条，"
        f"格式无效跳过 {stats['invalid']} 条")


def cmd_item_import(conn, a):
    _print_stats(importers.import_file(conn, a.path, a.source))


def cmd_rss(conn, a):
    _print_stats(importers.import_rss_url(conn, a.url, a.source))


def cmd_items(conn, a):
    q = "SELECT * FROM items" + ("" if a.all else " WHERE processed_at IS NULL") + " ORDER BY id DESC LIMIT ?"
    for r in conn.execute(q, (a.limit,)):
        flag = " [疑似指令文本]" if r["flags"] else ""
        out(f"#{r['id']:<4} [{r['credibility']}] {r['published_at'] or '日期未知':<10} {r['title']}"
            f"  ({r['source']}) {r['url'] or ''}{flag}")


# ---------- Bug 提取 ----------
def _profile():
    p = os.environ.get("WORLDOS_PROFILE") or os.path.join(CTX["data_dir"], "profile.md")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read()
    return "（未提供个人资源档案）"


def cmd_extract(conn, a):
    r = extract.run(conn, CTX["data_dir"], _profile(), ids=_ids(a.ids) if a.ids else None,
                    limit=a.limit, manual=a.manual)
    if r["mode"] == "none":
        out("没有待处理的信息")
        return
    if r["mode"] == "manual":
        out(f"手动模式（{r['reason']}）：提示词已写入 {r['prompt_path']}")
        out("把它粘贴到你已有的聊天工具，把返回的 JSON 存成文件，然后运行：")
        out(f"  python -m worldos cards-import <文件.json> --ai --items {','.join(map(str, r['item_ids']))}")
        return
    for w in r["warnings"]:
        out("[!] " + w)
    tag = "模拟适配器输出，仅供测试，不是研究结论" if r["origin"] == "ai-mock" else "AI 生成，待人工审核"
    for cid in r["card_ids"]:
        created(cid, f"机会卡 #{cid}（{tag}）")
    if not r["card_ids"]:
        out("没有生成机会卡（模型认为信息里没有值得记录的 Bug）")


# ---------- 机会卡 ----------
def cmd_card_template(conn, a):
    tpl = {k: "" for k in cards.FIELDS}
    tpl["evidence"] = [{"evidence_type": "public", "claim": "", "kind": "fact", "url": "", "who": "",
                        "observed_at": "", "verified": True}]
    sys.stdout.write(json.dumps(tpl, ensure_ascii=False, indent=2) + "\n")


def cmd_cards_import(conn, a):
    raw = llm.parse_json(importers._read_text(a.path))
    if a.ai:
        if not a.items:
            raise ValueError("导入 AI 输出必须用 --items 说明这批输出对应哪些信息 id（extract 会打印）")
        item_ids = _ids(a.items)
        ids, warnings = extract.import_cards(conn, raw, item_ids, origin="ai")
        extract.mark_processed(conn, item_ids)
        for w in warnings:
            out("[!] " + w)
        for cid in ids:
            created(cid, f"机会卡 #{cid}（AI 生成，待人工审核）")
        return
    rows = raw if isinstance(raw, list) else [raw]
    new_ids = []
    try:
        for c in rows:
            if not isinstance(c, dict):
                raise ValueError("每张卡必须是 JSON 对象")
            cid = cards.create(conn, c, origin="manual", commit=False)
            for e in c.get("evidence") or []:
                evidence.add(conn, cid, e.get("evidence_type", "public"), e.get("claim", ""),
                             kind=e.get("kind", "fact"), url=e.get("url") or None,
                             counterpart=e.get("who") or None, item_id=e.get("item_id"),
                             observed_at=e.get("observed_at") or None, verified=bool(e.get("verified")),
                             commit=False)
            new_ids.append(cid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    for cid in new_ids:
        created(cid, f"机会卡 #{cid} 已导入")


def cmd_card_add(conn, a):
    data = {k: getattr(a, k) for k in cards.FIELDS if getattr(a, k, None)}
    sims = _similar(conn, data["name"])
    cid = cards.create(conn, data)
    created(cid, f"机会卡 #{cid} {data['name']}")
    for sid, sname, ratio in sims:
        out(f"[!] 与已有卡 #{sid}「{sname}」相似度 {ratio}，可能重复")


def _similar(conn, name, threshold=0.6):
    from difflib import SequenceMatcher
    return [(r["id"], r["name"], round(SequenceMatcher(None, name, r["name"]).ratio(), 2))
            for r in conn.execute("SELECT id, name FROM cards WHERE status!='killed'")
            if SequenceMatcher(None, name, r["name"]).ratio() >= threshold]


def cmd_cards(conn, a):
    for r in scoring.latest_scores(conn):
        if a.status and r["status"] != a.status:
            continue
        sc = "-" if r["total"] is None else f"{r['total']:.0f}"
        tier = "-" if r["evidence_tier"] is None else f"T{r['evidence_tier']}"
        rv = "" if r["reviewed"] else " [待审核]"
        sim = " [模拟]" if r["origin"] == "ai-mock" else ""
        out(f"#{r['id']:<4} {sc:>4}分 {tier:<3} {r['status']:<11} {r['bug_type'] or '':<5} {r['name']}{rv}{sim}")


def cmd_card(conn, a):
    out(card_markdown(conn, cards.get(conn, a.id)))


def card_markdown(conn, c):
    labels = {
        "bug_type": "类型", "domain": "领域", "problem": "问题", "affected": "受影响者", "competitors": "现有方案/竞争",
        "why_unsolved": "为何未解决", "why_now": "为何现在", "payers": "潜在付费方（假设）", "solution": "解决方案",
        "resources": "所需资源", "revenue_model": "盈利方式（假设）", "cost_risk": "成本与风险",
        "min_validation": "最小验证行动", "kill_condition": "放弃条件",
    }
    origin = {"manual": "人工", "ai": "AI 生成", "ai-mock": "模拟适配器（测试用，非研究结论）"}[c["origin"]]
    p = evidence.profile(conn, c["id"])
    lines = [f"# #{c['id']} {c['name']}",
             f"状态 {c['status']}｜过滤 {cards.FLAG_NAMES[c['filter_flag']]}｜来源 {origin}｜"
             f"{'已审核' if c['reviewed'] else '待审核'}｜创建 {c['created_at']}｜最后核实 {c['last_verified_at'] or '从未'}",
             f"证据强度 {evidence.TIER_NAMES[p['tier']]}｜独立来源 {p['independent_sources']}｜"
             f"支付意愿分上限 {p['pain_cap']}｜成交状态 {evidence.DEAL_NAMES[p['deal_stage']]}", ""]
    lines += [f"- **{v}**：{c[k] or '—'}" for k, v in labels.items()]
    lines += ["", "## 证据"]
    for e in conn.execute("SELECT * FROM evidence WHERE card_id=? ORDER BY id", (c["id"],)):
        mark = "已核实" if e["verified"] else "未核实"
        src = e["url"] or (f"对方 {e['counterpart']}" if e["counterpart"] else None) or \
            (f"信息#{e['item_id']}" if e["item_id"] else "无来源")
        lines.append(f"- [{e['id']}] {evidence.TYPES[e['evidence_type']][1]}｜{e['kind']}｜{mark}：{e['claim']}"
                     f"（{src}，{e['observed_at'] or '时间未知'}）")
    lines += ["", "## 评分记录（新→旧）"]
    for s in conn.execute("SELECT * FROM scores WHERE card_id=? ORDER BY id DESC", (c["id"],)):
        lines.append(f"- [{s['id']}] {s['created_at'][:16]} 总分 {s['total']}（原始 {s['raw_total']}，T{s['evidence_tier']}）"
                     f" 痛点{s['pain']}(填{s['pain_input']}) 接触{s['access']} 技术{s['feasibility']} 复用{s['reuse']} "
                     f"风险{s['risk']}｜依据：{s['basis']}" + (f"｜修订原因：{s['reason']}" if s["reason"] else ""))
    lines += ["", "## 行动"]
    for t in conn.execute("SELECT * FROM actions WHERE card_id=? ORDER BY id", (c["id"],)):
        lines.append(f"- #{t['id']} [{t['status']}] {t['title']}｜假设：{t['hypothesis'] or '—'}｜验收：{t['acceptance'] or '—'}"
                     + (f"｜结果：{t['result']}｜结论：{t['decision']}" if t["status"] != "open" else ""))
    lines += ["", "## 反馈记录"]
    for g in conn.execute("SELECT * FROM logs WHERE card_id=? ORDER BY id", (c["id"],)):
        amt = f" {g['amount']:.2f}元" if g["amount"] is not None else ""
        lines.append(f"- {g['created_at'][:10]} {records.LOG_NAMES[g['kind']]} {g['counterpart'] or ''}{amt} {g['note'] or ''}")
    lines += ["", "## 修改记录"]
    for r in conn.execute("SELECT * FROM card_revisions WHERE card_id=? ORDER BY id", (c["id"],)):
        lines.append(f"- {r['created_at'][:16]} {r['actor']} {r['field']}: {r['old_value']} → {r['new_value']}"
                     + (f"（{r['reason']}）" if r["reason"] else ""))
    return "\n".join(lines)


def cmd_card_set(conn, a):
    cards.set_field(conn, a.id, a.field, a.value, a.reason)
    out(f"#{a.id} {a.field} 已更新")


def cmd_status(conn, a):
    cards.set_status(conn, a.id, a.status, a.reason)
    out(f"#{a.id} 状态 → {a.status}")


def cmd_review(conn, a):
    changed = cards.review(conn, a.id, a.reason)
    out(f"#{a.id} 已人工审核。" if changed else f"#{a.id} 之前已审核。")
    out("注意：AI 给出的证据仍是“AI 推断/未核实”，需逐条打开原文后用 evidence-verify 核实。")


def cmd_filter(conn, a):
    st = cards.apply_filter(conn, a.id, a.flag, a.reason)
    out(f"#{a.id} 前置过滤：{cards.FLAG_NAMES[a.flag]}" + (f"，状态改为 {st}" if st else ""))


# ---------- 证据 ----------
def cmd_evidence_add(conn, a):
    c = cards.get(conn, a.card)
    cards.ensure_open(c)
    eid = evidence.add(conn, a.card, a.type, a.claim, kind=a.kind, url=a.url, counterpart=a.who,
                       item_id=a.item, observed_at=a.observed, verified=a.verified)
    created(eid, f"证据 #{eid} 已添加到卡 #{a.card}（{evidence.TYPES[a.type][1]}，{'已核实' if a.verified else '未核实'}）")


def cmd_evidence_verify(conn, a):
    evidence.verify(conn, a.id, a.type, url=a.url, kind=a.kind)
    out(f"证据 #{a.id} 已人工核实，类型：{evidence.TYPES[a.type][1]}")


# ---------- 评分 ----------
def cmd_score(conn, a):
    sid, raw, total, warns = scoring.score_card(
        conn, a.card, {k: getattr(a, k) for k in scoring.WEIGHTS}, a.basis, a.reason)
    for w in warns:
        out("[!] " + w)
    created(sid, f"#{a.card} 原始 {raw} 分 → 记录 {total} 分（评分记录 #{sid}）")


# ---------- 行动与反馈 ----------
def cmd_action_add(conn, a):
    aid = records.add_action(conn, a.card, a.title, a.purpose, a.hypothesis, a.acceptance, a.minutes, a.money, a.due)
    created(aid, f"行动 #{aid} 已创建")


def cmd_action_done(conn, a):
    records.close_action(conn, a.id, a.result, a.decision, a.dropped)
    out(f"行动 #{a.id} 已关闭，结论 {a.decision}")


def cmd_actions(conn, a):
    q = "SELECT a.*, c.name FROM actions a LEFT JOIN cards c ON c.id=a.card_id"
    q += "" if a.all else " WHERE a.status='open'"
    for r in conn.execute(q + " ORDER BY COALESCE(a.due,'9999'), a.id"):
        out(f"#{r['id']:<4} [{r['status']}] 截止 {r['due'] or '-':<10} {r['title']}  <- {r['name'] or '无关联卡'}")


def cmd_log(conn, a):
    lid, eid = records.add_log(conn, a.kind, a.card, a.amount, a.minutes, a.category, a.who, a.note, a.claim)
    msg = f"记录 #{lid}（{records.LOG_NAMES[a.kind]}）已保存"
    if eid:
        msg += f"，并生成已核实证据 #{eid}"
    created(lid, msg)


# ---------- 输出与数据安全 ----------
def cmd_brief(conn, a):
    text = brief.build(conn)
    sys.stdout.write(text)
    if a.save:
        from datetime import datetime
        folder = os.path.join(CTX["data_dir"], "briefs")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{datetime.now():%Y-%m-%d}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        out(f"已保存到 {path}")


def cmd_export(conn, a):
    target = a.out or os.path.join(CTX["data_dir"], "export")
    counts = backup.export(conn, target, card_markdown)
    out(f"已导出到 {target}（worldos.json + cards/*.md）：" + "，".join(f"{k} {v}" for k, v in counts.items()))


def cmd_backup(conn, a):
    path = backup.backup(conn, CTX["data_dir"])
    created(path, f"已备份到 {path}")


def cmd_cost(conn, a):
    for r in conn.execute(
            "SELECT substr(created_at,1,7) AS m, task, provider, model, status, simulated, COUNT(*) AS n, "
            "SUM(input_tokens) AS i, SUM(output_tokens) AS o, SUM(cost_usd) AS c FROM llm_calls "
            "GROUP BY m, task, provider, model, status, simulated ORDER BY m"):
        tag = "模拟(不计费)" if r["simulated"] else "真实"
        out(f"{r['m']} {r['task']:<8} {r['provider']:<7} {r['model']:<18} {r['status']:<7} {tag} "
            f"{r['n']} 次 输入 {r['i']} 输出 {r['o']} ${r['c']:.4f}")
    out(f"本月真实花费合计 ${llm.month_spend(conn):.4f}；今日已调用 {llm.calls_today(conn)} 次")


def build_parser():
    p = argparse.ArgumentParser(prog="worldos", description="WORLD OS V1 本地命令行")
    p.add_argument("--db", help="数据库文件路径；默认 %%WORLDOS_HOME%%\\worldos.db 或 ~/worldos-data/worldos.db")
    p.add_argument("--porcelain", action="store_true", help="新建类命令只输出 id，便于脚本取值")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init, "初始化数据库并显示数据位置")

    s = add("item-add", cmd_item_add, "人工录入一条信息（必须有来源）")
    s.add_argument("--title", required=True); s.add_argument("--source", required=True)
    s.add_argument("--url"); s.add_argument("--content")
    s.add_argument("--cred", default="C", choices=["A", "B", "C"], help="A=一手/官方 B=可靠二手 C=未核实")
    s.add_argument("--published", help="资料本身的日期，如 2026-10-01")
    s = add("item-import", cmd_item_import, "从 JSON/CSV/RSS 文件导入信息")
    s.add_argument("path"); s.add_argument("--source", help="文件里没写来源时使用的默认来源")
    s = add("rss", cmd_rss, "从公开 RSS 地址导入")
    s.add_argument("url"); s.add_argument("--source")
    s = add("items", cmd_items, "列出信息（默认只列未处理）")
    s.add_argument("--all", action="store_true"); s.add_argument("--limit", type=int, default=30)

    s = add("extract", cmd_extract, "从信息中提取候选 Bug（未配置模型或调用失败时自动生成提示词文件）")
    s.add_argument("--ids", help="指定信息 id，如 1,2,3"); s.add_argument("--limit", type=int, default=10)
    s.add_argument("--manual", action="store_true", help="不调用模型，直接生成提示词文件")

    add("card-template", cmd_card_template, "打印人工机会卡 JSON 模板")
    s = add("cards-import", cmd_cards_import, "从 JSON 文件导入机会卡")
    s.add_argument("path")
    s.add_argument("--ai", action="store_true", help="文件是模型输出：按 AI 推断处理并进入待审核")
    s.add_argument("--items", help="--ai 时必填：这批输出对应的信息 id，如 1,2,3")
    s = add("card-add", cmd_card_add, "快速新建机会卡")
    for f in cards.FIELDS:
        s.add_argument("--" + f.replace("_", "-"), dest=f, required=(f == "name"))
    s = add("cards", cmd_cards, "按分数列出机会卡")
    s.add_argument("--status", choices=cards.STATUSES)
    s = add("card", cmd_card, "查看机会卡详情（含证据、评分记录、修改记录）"); s.add_argument("id", type=int)
    s = add("card-set", cmd_card_set, "修改机会卡字段（记入修改记录）")
    s.add_argument("id", type=int); s.add_argument("field"); s.add_argument("value"); s.add_argument("--reason")
    s = add("status", cmd_status, "变更机会卡状态（按允许的流转规则）")
    s.add_argument("id", type=int); s.add_argument("status", choices=cards.STATUSES); s.add_argument("--reason")
    s = add("review", cmd_review, "人工审核 AI 生成的卡")
    s.add_argument("id", type=int); s.add_argument("--reason")
    s = add("filter", cmd_filter, "前置过滤：illegal/unauthorized/harmful 直接淘汰，no_payer/over_budget 暂缓")
    s.add_argument("id", type=int); s.add_argument("flag", choices=list(cards.FLAG_NAMES)); s.add_argument("--reason")

    types = list(evidence.TYPES)
    s = add("evidence-add", cmd_evidence_add, "给机会卡添加证据")
    s.add_argument("card", type=int); s.add_argument("--type", required=True, choices=types)
    s.add_argument("--claim", required=True); s.add_argument("--url"); s.add_argument("--who", help="对方代号")
    s.add_argument("--item", type=int); s.add_argument("--kind", default="fact", choices=sorted(evidence.KINDS))
    s.add_argument("--observed", help="证据本身的日期"); s.add_argument("--verified", action="store_true")
    s = add("evidence-verify", cmd_evidence_verify, "人工核实一条证据（AI 证据最多升级为 public/primary）")
    s.add_argument("id", type=int); s.add_argument("--type", required=True, choices=types)
    s.add_argument("--url"); s.add_argument("--kind", choices=sorted(evidence.KINDS))

    s = add("score", cmd_score, "评分（各维度 0-5，必须写依据；再次评分必须写修订原因）")
    s.add_argument("card", type=int)
    for k in scoring.WEIGHTS:
        s.add_argument("--" + k, required=True, help=scoring.DIMENSION_NAMES[k])
    s.add_argument("--basis", required=True, help="评分依据"); s.add_argument("--reason", help="修订原因")

    s = add("action-add", cmd_action_add, "为机会卡创建验证行动")
    s.add_argument("card", type=int); s.add_argument("--title", required=True)
    s.add_argument("--purpose"); s.add_argument("--hypothesis"); s.add_argument("--acceptance")
    s.add_argument("--minutes", type=int); s.add_argument("--money", type=float); s.add_argument("--due")
    s = add("action-done", cmd_action_done, "关闭行动并给出结论")
    s.add_argument("id", type=int); s.add_argument("--result", required=True)
    s.add_argument("--decision", choices=records.DECISIONS, required=True)
    s.add_argument("--dropped", action="store_true")
    s = add("actions", cmd_actions, "列出行动"); s.add_argument("--all", action="store_true")

    s = add("log", cmd_log, "记录现实反馈")
    s.add_argument("kind", choices=records.LOG_KINDS); s.add_argument("--card", type=int)
    s.add_argument("--amount", type=float, help="金额（元）"); s.add_argument("--minutes", type=int)
    s.add_argument("--category", choices=records.TIME_CATEGORIES)
    s.add_argument("--who", help="对方代号（不写真实姓名等隐私信息）"); s.add_argument("--note")
    s.add_argument("--claim", help="同时生成一条已核实的客户类证据，写对方的原话或事实")

    s = add("brief", cmd_brief, "生成每日简报"); s.add_argument("--save", action="store_true")
    s = add("export", cmd_export, "导出 JSON + Markdown"); s.add_argument("--out")
    add("backup", cmd_backup, "备份数据库到数据目录 backups/")
    s = add("restore", cmd_restore, "从备份恢复数据库（覆盖前自动另存当前库）")
    s.add_argument("path"); s.add_argument("--force", action="store_true")
    add("cost", cmd_cost, "模型调用成本统计")
    return p


def cmd_restore(conn, a):
    raise AssertionError("restore 在 main 中单独处理")


def _safe_stdout():
    """中文 Windows 控制台或重定向时可能是 GBK 编码：遇到无法编码的字符用 ? 代替，不让程序崩溃。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    _safe_stdout()
    a = build_parser().parse_args(argv)
    db_path, data_dir = db.resolve_paths(a.db)
    CTX.clear()
    CTX.update(db_path=db_path, data_dir=data_dir, porcelain=a.porcelain)
    try:
        if a.cmd == "restore":
            counts, safety = backup.restore(a.path, db_path, a.force)
            if safety:
                out(f"原数据库已另存为 {safety}")
            out(f"已从 {a.path} 恢复：" + "，".join(f"{k} {v}" for k, v in counts.items()))
            return 0
        conn = db.connect(db_path)
    except (ValueError, RuntimeError) as e:
        sys.stderr.write(f"错误：{e}\n")
        return 1
    try:
        a.fn(conn, a)
    except (ValueError, llm.BudgetExceeded, llm.CallLimitExceeded) as e:
        sys.stderr.write(f"错误：{e}\n")
        return 1
    finally:
        conn.close()
    return 0
