"""变异抽查：在临时副本里逐个故意破坏关键规则，再跑全部测试，确认测试会失败。

用法（项目根目录）：python scripts/mutation_check.py
不修改项目文件；全部被发现时退出码 0，否则 1。每一处约需几秒。
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (规则, 文件, 原代码, 破坏后的代码)
MUTATIONS = [
    # 审查 001 时建立的 16 处
    ("AI 证据入库时强制未核实", "worldos/evidence.py", "        verified = False  # AI 证据入库时一律未核实", "        pass"),
    ("AI 证据入库时只能是 AI 推断", "worldos/evidence.py", '    if origin != "manual" and evidence_type != "ai_inference":\n        raise', '    if False:\n        raise'),
    ("月度预算闸门", "worldos/llm.py", "if spent + est > budget:", "if False:"),
    ("每日次数上限", "worldos/llm.py", "    if calls_today(conn) >= limit:", "    if False:"),
    ("模拟调用费用为 0 且标记 simulated", "worldos/llm.py", 'cost=0.0, simulated=True)', 'cost=0.01, simulated=False)'),
    ("状态流转白名单", "worldos/cards.py", "    if new not in TRANSITIONS[old]:", "    if False:"),
    ("淘汰卡不能继续推进", "worldos/cards.py", '    if card["status"] == "killed":\n        raise', '    if False:\n        raise'),
    ("证据只能引用本批条目", "worldos/extract.py", "            if item_id not in allowed_item_ids:", "            if item_id is None:"),
    ("模型输出非法字段告警", "worldos/extract.py", "        if extra:\n            warnings.append", "        if False:\n            warnings.append"),
    ("中和伪造的 <item> 标签", "worldos/prompts.py", '.replace("<item", "‹item").replace("</item", "‹/item")', ''),
    ("独立来源 ≥2 才算达到某档", "worldos/evidence.py", "t if len(sources_at[t]) >= 2 else t - 1", "t"),
    ("支付意愿上限", "worldos/scoring.py", '    if s["pain"] > pain_cap:', '    if False:'),
    ("重评必须写原因", "worldos/scoring.py", '    if prev and not (reason and reason.strip()):', '    if False:'),
    ("恢复覆盖需要 --force", "worldos/backup.py", "        if not force:", "        if False:"),
    ("信息必须有来源", "worldos/importers.py", "    if not source:\n        raise", "    if False:\n        raise"),
    ("简报只推荐已审核、通过过滤的研究/验证中卡片", "worldos/brief.py",
    'if r["status"] in ACTIVE and r["reviewed"] == 1 and r["filter_flag"] == "ok" and r["total"] is not None]',
    'if r["total"] is not None]'),
    # 审查 002 整改新增的 15 处
    ("预算按上限预留", "worldos/llm.py", "if spent + est > budget:", "if spent >= budget:"),
    ("缺用量按上限计", "worldos/llm.py", '_update(conn, call_id, status="ok", error="响应没有有效的 usage 用量，已按上限计入预算，待对账")',
    '_update(conn, call_id, status="ok", cost_usd=0, usage_known=1)'),
    ("失败按上限计", "worldos/llm.py", '_update(conn, call_id, status="error", error=', '_update(conn, call_id, status="error", cost_usd=0, error='),
    ("配置拒绝 NaN/Inf", "worldos/llm.py", "if not math.isfinite(v) or v < 0:", "if v < 0:"),
    ("pending 计入预算", "worldos/llm.py", 'BILLABLE = ("pending", "ok", "error")', 'BILLABLE = ("ok", "error")'),
    ("usage 格式校验", "worldos/llm.py", "    if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (tin, tout)):\n        return None\n",
    "    tin, tout = int(tin or 0), int(tout or 0)\n"),
    ("次数上限校验", "worldos/llm.py", "    if v < 0:\n        raise ModelUnavailable(f\"WORLDOS_MAX_CALLS_PER_DAY", "    if False:\n        raise ModelUnavailable(f\"WORLDOS_MAX_CALLS_PER_DAY"),
    ("金额必须 > 0", "worldos/records.py", "    if kind in POSITIVE_MONEY_LOGS and amount <= 0:", "    if False:"),
    ("金额必须有限", "worldos/records.py", "    if amount is not None and not math.isfinite(amount):", "    if False:"),
    ("行动金额有限", "worldos/records.py", "    if money is not None and not math.isfinite(money):", "    if False:"),
    ("won 需正回款", "worldos/cards.py", 'if new == "won" and received(conn, card_id) <= 0:',
    'if new == "won" and not conn.execute("SELECT COUNT(*) FROM logs WHERE card_id=? AND kind=\'payment\'", (card_id,)).fetchone()[0]:'),
    ("成交状态只认正金额", "worldos/evidence.py", 'if r["kind"] == "intent" or positive_amount(r["amount"])}', '}'),
    ("评分过期提示", "worldos/scoring.py", "    if s is None:\n        return []", "    if True:\n        return []"),
    ("证据变化判定", "worldos/scoring.py", 'if (set(p["evidence_ids"]) != set(json.loads(s["evidence_ids"] or "[]")) or reverified', 'if (False'),
    ("升级时旧失败调用待对账", "worldos/db.py", "        \"UPDATE llm_calls SET usage_known=0 WHERE status='error' AND simulated=0\"],", "    ],"),
]


def main():
    caught = 0
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "w")
        for name, path, old, new in MUTATIONS:
            shutil.rmtree(work, ignore_errors=True)
            shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.db"))
            target = os.path.join(work, path)
            with open(target, encoding="utf-8") as f:
                src = f.read()
            if src.count(old) != 1:
                print(f"无法应用 ✘ {name}：{path} 中找不到唯一的原代码，脚本需要随代码更新")
                continue
            with open(target, "w", encoding="utf-8") as f:
                f.write(src.replace(old, new))
            r = subprocess.run([sys.executable, "-m", "unittest"], cwd=work, capture_output=True, text=True)
            ok = r.returncode != 0
            caught += ok
            print(("测试失败 ✔ " if ok else "未被发现 ✘ ") + name)
    print(f"{caught}/{len(MUTATIONS)} 处破坏被测试发现")
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == "__main__":
    sys.exit(main())
