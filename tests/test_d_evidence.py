"""测试 D：证据完整性。
- AI 生成内容不能自动获得高等级证据；
- 未经人工核实的内容不能被标记为真实客户反馈；
- 报价、合作意向、合同和实际回款分别记录，金额必须是正的有限数字；证据强度与成交状态分开；
- 一条证据不能证明整个机会；评分有依据、来源和修订记录。
"""
import json

from worldos import evidence, extract, scoring

from .helpers import Base

SCORES = ["--pain", 5, "--access", 4, "--feasibility", 4, "--reuse", 4, "--risk", 4]


class EvidenceTest(Base):
    def _card(self, name="【演示数据】机会"):
        return self.new_id("card-add", "--name", name)

    def test_ai_evidence_cannot_become_customer_evidence(self):
        iid = self.new_id("item-add", "--title", "t", "--source", "s", "--url", "https://ex.com/1")
        ids, _ = extract.import_cards(self.conn, [{"name": "AI 卡", "evidence": [
            {"item_id": iid, "claim": "客户已付款", "kind": "fact", "evidence_type": "payment", "verified": True}]}],
            [iid], origin="ai")
        eid = self.scalar("SELECT id FROM evidence WHERE card_id=?", ids[0])
        e = self.q("SELECT * FROM evidence WHERE id=?", eid)[0]
        self.assertEqual((e["evidence_type"], e["verified"]), ("ai_inference", 0))
        for t in ("customer_statement", "quote", "intent", "contract", "payment"):
            self.fails("evidence-verify", eid, "--type", t, contains="最多升级为公开资料或一手资料")
        self.ok("evidence-verify", eid, "--type", "public")
        self.assertEqual(self.scalar("SELECT evidence_type FROM evidence WHERE id=?", eid), "public")

    def test_ai_origin_evidence_never_stored_as_verified(self):
        # 防御层：即使调用方误传 verified=True，AI 来源的证据也以未核实入库
        cid = self._card()
        eid = evidence.add(self.conn, cid, "ai_inference", "AI 说的", origin="ai", verified=True)
        self.assertEqual(self.scalar("SELECT verified FROM evidence WHERE id=?", eid), 0)
        with self.assertRaises(ValueError):
            evidence.add(self.conn, cid, "public", "AI 说的", url="https://a.com", origin="ai", verified=True)
        self.assertEqual(evidence.profile(self.conn, cid)["tier"], 0)

    def test_unverified_customer_statement_does_not_count(self):
        cid = self._card()
        self.new_id("evidence-add", cid, "--type", "customer_statement", "--claim", "听说客户很痛", "--who", "A")
        self.new_id("evidence-add", cid, "--type", "customer_statement", "--claim", "听说客户很痛", "--who", "B")
        p = evidence.profile(self.conn, cid)
        self.assertEqual((p["tier"], p["pain_cap"]), (0, 2))
        self.fails("evidence-add", cid, "--type", "customer_statement", "--claim", "x", "--verified",
                  contains="对方代号")

    def test_single_evidence_cannot_prove_opportunity(self):
        cid = self._card()
        self.new_id("log", "payment", "--card", cid, "--who", "客户A", "--amount", 5000, "--claim", "已回款 5000 元")
        p = evidence.profile(self.conn, cid)
        self.assertEqual(p["tier"], 3)                 # 只有 1 个来源：T4 降一档
        self.assertEqual(p["deal_stage"], "payment")
        self.new_id("log", "payment", "--card", cid, "--who", "客户B", "--amount", 3000, "--claim", "已回款 3000 元")
        self.assertEqual(evidence.profile(self.conn, cid)["tier"], 4)
        # 同一个客户的两条证据不算两个独立来源
        cid2 = self._card("【演示数据】另一机会")
        self.new_id("log", "interview", "--card", cid2, "--who", "客户A", "--claim", "痛")
        self.new_id("log", "interview", "--card", cid2, "--who", "客户A", "--claim", "很痛")
        self.assertEqual(evidence.profile(self.conn, cid2)["tier"], 1)

    def test_tier_and_pain_caps(self):
        cases = [
            ([], 0, 2),
            ([("public", "https://a.com", None)], 0, 2),
            ([("public", "https://a.com", None), ("public", "https://b.com", None)], 1, 2),
            ([("customer_statement", None, "A"), ("customer_statement", None, "B")], 2, 3),
            ([("quote", None, "A"), ("intent", None, "B")], 3, 4),
            ([("contract", None, "A"), ("payment", None, "B")], 4, 5),
        ]
        for evs, tier, pain_cap in cases:
            with self.subTest(evs=evs):
                cid = self._card()
                for t, url, who in evs:
                    evidence.add(self.conn, cid, t, "c", url=url, counterpart=who, verified=True)
                p = evidence.profile(self.conn, cid)
                self.assertEqual((p["tier"], p["pain_cap"]), (tier, pain_cap))

    def test_deal_records_are_separate(self):
        cid = self._card()
        self.new_id("log", "quote", "--card", cid, "--who", "客户A", "--amount", 8000)
        self.assertEqual(evidence.deal_stage(self.conn, cid), "quote")
        self.new_id("log", "intent", "--card", cid, "--who", "客户A", "--note", "口头同意试点")
        self.assertEqual(evidence.deal_stage(self.conn, cid), "intent")
        self.new_id("log", "contract", "--card", cid, "--who", "客户A", "--amount", 8000)
        self.assertEqual(evidence.deal_stage(self.conn, cid), "contract")
        # 没有回款不能标记成交
        self.ok("status", cid, "researching"); self.ok("status", cid, "validating")
        self.fails("status", cid, "won", contains="回款")
        self.new_id("log", "payment", "--card", cid, "--who", "客户A", "--amount", 4000)
        self.ok("status", cid, "won")
        kinds = [r[0] for r in self.q("SELECT kind FROM logs WHERE card_id=? ORDER BY id", cid)]
        self.assertEqual(kinds, ["quote", "intent", "contract", "payment"])
        # 这些记录没有带 --claim，所以没有生成证据：成交状态不等于证据强度
        self.assertEqual(evidence.profile(self.conn, cid)["tier"], 0)
        self.fails("log", "payment", "--card", cid, "--who", "客户A", contains="金额")
        self.fails("log", "quote", "--card", cid, "--amount", 1, contains="对方代号")

    def test_won_requires_positive_finite_payment(self):
        cid = self._card()
        self.ok("status", cid, "researching"); self.ok("status", cid, "validating")
        for bad in ("0", "-0", "-5", "nan", "NaN", "inf", "-inf", "Infinity"):
            with self.subTest(amount=bad):
                self.fails("log", "payment", "--card", cid, "--who", "客户A", f"--amount={bad}", contains="金额")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM logs"), 0)
        # 旧版本可能留下的 0 元或 Infinity 回款：不能满足成交条件，也不算“已回款”
        for legacy in (0.0, float("inf")):
            self.conn.execute("INSERT INTO logs (card_id, kind, amount, counterpart, created_at) "
                              "VALUES (?, 'payment', ?, '客户A', '2026-10-01T00:00:00+08:00')", (cid, legacy))
        self.conn.commit()
        self.fails("status", cid, "won", contains="金额大于 0")
        self.assertEqual(evidence.deal_stage(self.conn, cid), "none")
        # 部分回款（报价 3000，先收 500）是真实回款，可以标记成交
        self.new_id("log", "quote", "--card", cid, "--who", "客户A", "--amount", 3000)
        self.new_id("log", "payment", "--card", cid, "--who", "客户A", "--amount", 500)
        self.assertEqual(evidence.deal_stage(self.conn, cid), "payment")
        self.ok("status", cid, "won")

    def test_money_amounts_must_be_positive_and_finite(self):
        cid = self._card()
        for kind in ("quote", "contract"):
            for bad in ("0", "nan", "inf", "-inf"):
                with self.subTest(kind=kind, amount=bad):
                    self.fails("log", kind, "--card", cid, "--who", "客户A", f"--amount={bad}", contains="金额")
        for bad in ("nan", "inf", "-1"):
            with self.subTest(kind="cost", amount=bad):
                self.fails("log", "cost", "--card", cid, f"--amount={bad}", contains="金额")
            with self.subTest(kind="action money", amount=bad):
                self.fails("action-add", cid, "--title", "t", f"--money={bad}", contains="预算")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM logs") + self.scalar("SELECT COUNT(*) FROM actions"), 0)
        self.new_id("log", "cost", "--card", cid, "--amount", 0, "--note", "免费试用")   # 成本可以是 0
        self.new_id("log", "quote", "--card", cid, "--who", "客户A", "--amount", 0.5)

    def test_score_requires_basis_and_revision_reason(self):
        cid = self._card()
        self.fails("score", cid, *SCORES, "--basis", "  ", contains="依据")
        sid1 = self.new_id("score", cid, *SCORES, "--basis", "只有想象")
        row = self.q("SELECT * FROM scores WHERE id=?", sid1)[0]
        self.assertEqual((row["pain_input"], row["pain"], row["total"]), (5, 2, 40))
        self.assertEqual(json.loads(row["evidence_ids"]), [])
        self.fails("score", cid, *SCORES, "--basis", "再评一次", contains="修订")
        eid = evidence.add(self.conn, cid, "customer_statement", "痛", counterpart="A", verified=True)
        evidence.add(self.conn, cid, "customer_statement", "痛", counterpart="B", verified=True)
        sid2 = self.new_id("score", cid, *SCORES, "--basis", "两家客户亲口确认", "--reason", "新增访谈证据")
        row2 = self.q("SELECT * FROM scores WHERE id=?", sid2)[0]
        self.assertEqual(row2["prev_score_id"], sid1)
        self.assertIn(eid, json.loads(row2["evidence_ids"]))
        self.assertEqual(row2["total"], 74.0)
        md = self.ok("card", cid)
        self.assertIn("修订原因：新增访谈证据", md)
        self.assertIn("依据：只有想象", md)

    def test_brief_flags_stale_score(self):
        cid = self._card()
        for i in (1, 2):
            self.new_id("evidence-add", cid, "--type", "public", "--claim", f"报道{i}",
                        "--url", f"https://ex.com/{i}", "--verified")
        later = self.new_id("evidence-add", cid, "--type", "public", "--claim", "报道3", "--url", "https://ex.com/3")
        self.new_id("score", cid, *SCORES, "--basis", "两篇报道")
        self.ok("status", cid, "researching")
        self.assertNotIn("【注意】", self.ok("brief"))
        # 评分后又核实了一条证据：提示过期
        self.ok("evidence-verify", later, "--type", "public")
        b = self.ok("brief")
        self.assertIn("【注意】评分可能已过期：评分后已核实的证据有变化", b)
        self.assertIn(f"#{cid}）评分后证据或内容有变化", b)
        self.new_id("score", cid, *SCORES, "--basis", "三篇报道", "--reason", "新核实一条")
        self.assertNotIn("【注意】", self.ok("brief"))
        # 同一链接的新证据不增加独立来源、不改变强度，但已核实证据变了，评分依据需要复看
        self.new_id("evidence-add", cid, "--type", "public", "--claim", "报道1的补充",
                    "--url", "https://ex.com/1", "--verified")
        self.assertIn("【注意】评分可能已过期", self.ok("brief"))
        self.new_id("score", cid, *SCORES, "--basis", "三篇报道", "--reason", "补充同源证据")
        # 评分后新增的已核实证据（例如访谈记录 --claim）同样提示
        self.new_id("log", "interview", "--card", cid, "--who", "客户A", "--claim", "每月人工对账 2 天")
        self.assertIn("【注意】", self.ok("brief"))
        self.new_id("score", cid, *SCORES, "--basis", "报道 + 访谈", "--reason", "新增访谈")
        # 卡片内容修改按时间比较；把评分和证据核实时间往前挪，避免同一秒内的先后无法区分
        for table, col in (("scores", "created_at"), ("evidence", "verified_at")):
            self.conn.execute(f"UPDATE {table} SET {col}='2000-01-01T00:00:00+00:00' WHERE card_id=?", (cid,))
        self.conn.commit()
        self.ok("status", cid, "validating")            # 状态变化不影响分数
        self.assertNotIn("【注意】", self.ok("brief"))
        self.ok("card-set", cid, "payers", "中小工厂设备科", "--reason", "访谈后改写")
        self.assertIn("评分后修改了卡片内容（payers）", self.ok("brief"))

    def test_compute_examples(self):
        raw, total, warns, s = scoring.compute(dict(pain=5, access=4, feasibility=4, reuse=4, risk=4), 1, 2)
        self.assertEqual((s["pain"], raw, total, len(warns)), (2, 68.0, 60, 2))
        raw, total, _, _ = scoring.compute(dict(pain=5, access=5, feasibility=5, reuse=5, risk=5), 4, 5)
        self.assertEqual((raw, total), (100.0, 100.0))
        raw, _, _, _ = scoring.compute(dict(pain=5, access=0, feasibility=0, reuse=0, risk=0), 4, 5)
        self.assertEqual(raw, 30.0)
