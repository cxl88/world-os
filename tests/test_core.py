import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from worldos import brief, cli, db, importers, llm, scoring

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>A</title><link>https://ex.com/a</link><description>aa</description></item>
<item><title>B</title><link>https://ex.com/b</link></item>
</channel></rss>"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.path = os.path.join(self.tmp.name, "t.db")
        self.conn = db.connect(self.path)

    def tearDown(self):
        self.conn.close()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["--db", self.path, *args])
        return code, buf.getvalue()


class ScoringTest(unittest.TestCase):
    def test_full_marks_with_payment_evidence(self):
        raw, total, warns, _ = scoring.compute(dict(pain=5, access=5, feasibility=5, reuse=5, risk=5), 3)
        self.assertEqual((raw, total, warns), (100.0, 100.0, []))

    def test_weights(self):
        raw, *_ = scoring.compute(dict(pain=5, access=0, feasibility=0, reuse=0, risk=0), 3)
        self.assertEqual(raw, 30.0)

    def test_pain_capped_without_primary_evidence(self):
        raw, total, warns, s = scoring.compute(dict(pain=5, access=4, feasibility=4, reuse=4, risk=4), 1)
        self.assertEqual(s["pain"], 2)
        self.assertEqual(raw, 12 + 16 * 3 + 8)  # 68
        self.assertEqual(total, 60)  # E1 封顶
        self.assertEqual(len(warns), 2)

    def test_ai_only_evidence_cap(self):
        _, total, _, _ = scoring.compute(dict(pain=2, access=5, feasibility=5, reuse=5, risk=5), 0)
        self.assertEqual(total, 40)

    def test_out_of_range(self):
        with self.assertRaises(ValueError):
            scoring.compute(dict(pain=6, access=0, feasibility=0, reuse=0, risk=0), 0)


class FlowTest(Base):
    def test_dedupe(self):
        _, c1 = importers.add_item(self.conn, "t", "https://x.com/1")
        _, c2 = importers.add_item(self.conn, "t2", "HTTPS://x.com/1 ")
        self.assertTrue(c1)
        self.assertFalse(c2)

    def test_rss_parse_and_import(self):
        with open("f.xml", "wb") as f:
            f.write(RSS)
        self.assertEqual(importers.import_file(self.conn, "f.xml"), (2, 0))
        self.assertEqual(importers.import_file(self.conn, "f.xml"), (0, 2))

    def test_ai_card_evidence_starts_at_e0_and_needs_review(self):
        iid, _ = importers.add_item(self.conn, "羽毛球馆仍用微信群接龙订场", "https://ex.com/x")
        cid = importers.add_card(self.conn, {"name": "订场流程Bug", "evidence": [
            {"item_id": iid, "claim": "仍用接龙", "kind": "fact", "level": 3, "verified": 1}]}, origin="ai")
        self.assertEqual(scoring.evidence_level(self.conn, cid), 0)
        code, outp = self.run_cli("card-set", str(cid), "status", "validating")
        self.assertEqual(code, 1)
        self.assertIn("review", outp)

    def test_kill_filter_blocks_scoring(self):
        cid = importers.add_card(self.conn, {"name": "抓取私人数据"})
        scoring.apply_filter(self.conn, cid, "unauthorized")
        self.assertEqual(self.conn.execute("SELECT status FROM cards WHERE id=?", (cid,)).fetchone()[0], "killed")
        with self.assertRaises(ValueError):
            scoring.score_card(self.conn, cid, dict(pain=1, access=1, feasibility=1, reuse=1, risk=1))

    def test_end_to_end_cli_and_brief(self):
        self.run_cli("item-add", "--title", "某制造厂仍手工抄表", "--source", "朋友口述", "--cred", "B")
        self.run_cli("card-add", "--name", "IoT 抄表自动化", "--bug-type", "流程", "--payers", "中小工厂设备科",
                     "--kill-condition", "5 家里少于 2 家愿意付费试点")
        self.run_cli("evidence-add", "1", "--claim", "设备科长亲口说每月抄表 2 人天", "--kind", "fact",
                     "--level", "2", "--verified")
        _, o = self.run_cli("score", "1", "--pain", "4", "--access", "3", "--feasibility", "4",
                            "--reuse", "3", "--risk", "4")
        self.assertIn("记录 72.0 分", o)
        self.run_cli("card-set", "1", "status", "validating")
        self.run_cli("action-add", "1", "--title", "拜访 3 家工厂", "--hypothesis", "愿付 3000 元试点",
                     "--acceptance", "至少 1 家给出书面报价意向", "--due", "2000-01-01")
        self.run_cli("log", "time", "--category", "build", "--minutes", "300")
        text = brief.build(self.conn)
        self.assertIn("IoT 抄表自动化", text)
        self.assertIn("拜访 3 家工厂", text)
        self.assertIn("还没有任何客户访谈", text)
        self.assertIn("已过期", text)
        self.assertIn("开发时间超过触达", text)
        self.run_cli("log", "interview", "--card", "1", "--who", "工厂A", "--note", "愿意试点")
        self.assertNotIn("还没有任何客户访谈", brief.build(self.conn))
        code, _ = self.run_cli("export", "--out", "ex")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists("ex/cards/0001.md"))
        _, o = self.run_cli("backup")
        self.assertIn("已备份", o)

    def test_manual_extract_writes_prompt(self):
        importers.add_item(self.conn, "x", "https://ex.com/1")
        with mock.patch.dict(os.environ, {}, clear=True):
            _, o = self.run_cli("extract")
        self.assertIn("手动模式", o)
        self.assertEqual(len(os.listdir("prompts")), 1)


class LlmTest(Base):
    ENV = {"WORLDOS_LLM_BASE_URL": "https://api.example.com", "WORLDOS_LLM_API_KEY": "k",
           "WORLDOS_PRICE_IN": "0.3", "WORLDOS_PRICE_OUT": "1.2", "WORLDOS_MONTHLY_BUDGET_USD": "1"}

    def fake_resp(self, content, tin=1_000_000, tout=500_000):
        body = json.dumps({"choices": [{"message": {"content": content}}],
                           "usage": {"prompt_tokens": tin, "completion_tokens": tout}}).encode()
        m = mock.MagicMock()
        m.__enter__.return_value.read.return_value = body
        return m

    def test_extract_logs_cost_and_budget_guard(self):
        importers.add_item(self.conn, "x", "https://ex.com/1")
        cards = '```json\n[{"name":"测试Bug","evidence":[{"item_id":1,"claim":"c","kind":"fact"}]}]\n```'
        with mock.patch.dict(os.environ, self.ENV), \
                mock.patch("urllib.request.urlopen", return_value=self.fake_resp(cards)):
            _, o = self.run_cli("extract")
            self.assertIn("待人工审核", o)
            self.assertAlmostEqual(llm.month_spend(self.conn), 0.9)
            importers.add_item(self.conn, "y", "https://ex.com/2")
            self.run_cli("extract")  # 0.9 + 0.9 = 1.8，超过 1 美元
            importers.add_item(self.conn, "z", "https://ex.com/3")
            _, o = self.run_cli("extract")
        self.assertIn("已达到上限", o)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
