"""测试 B：AI 工作流（确定性模拟适配器）。
信息输入 → AI 提取 → 结构化解析 → 待审核 → 人工审核 → 商业评估 → 生成行动。
模拟适配器的输出会被标记为 ai-mock / simulated，不能冒充真实研究成果。
"""
import json
import os

from .helpers import FIXTURES, Base


class MockAiWorkflowTest(Base):
    env = {"WORLDOS_LLM_PROVIDER": "mock", "WORLDOS_MOCK_RESPONSE": os.path.join(FIXTURES, "mock_extract.json")}

    def test_mock_pipeline(self):
        i1 = self.new_id("item-add", "--title", "【演示数据】中小企业抱怨发票录入耗时", "--source", "演示源",
                         "--url", "https://example.com/a", "--published", "2026-09-30")
        i2 = self.new_id("item-add", "--title", "【演示数据】财务软件缺少开放接口", "--source", "演示源",
                         "--url", "https://example.com/b")
        # 夹具里的 item_id 写死为 1、2；这里确认全新库确实如此，否则夹具需要改
        self.assertEqual((i1, i2), (1, 2))
        o = self.ok("extract")
        self.assertIn("模拟适配器输出", o)
        card_id = self.scalar("SELECT id FROM cards")
        card = self.q("SELECT * FROM cards WHERE id=?", card_id)[0]
        self.assertEqual(card["origin"], "ai-mock")
        self.assertEqual(card["reviewed"], 0)
        evs = self.q("SELECT * FROM evidence WHERE card_id=?", card_id)
        self.assertEqual(len(evs), 2)
        self.assertTrue(all(e["evidence_type"] == "ai_inference" and e["verified"] == 0 for e in evs))
        self.assertEqual(evs[0]["url"], "https://example.com/a")      # 链接取自原始条目
        self.assertEqual(evs[0]["observed_at"], "2026-09-30")
        call = self.q("SELECT * FROM llm_calls")[0]
        self.assertEqual((call["simulated"], call["cost_usd"], call["status"]), (1, 0, "ok"))
        self.assertIsNotNone(self.scalar("SELECT processed_at FROM items WHERE id=?", i1))

        # 未审核：不能评分、不能进入研究
        self.fail("score", card_id, "--pain", 1, "--access", 1, "--feasibility", 1, "--reuse", 1, "--risk", 1,
                  "--basis", "x", contains="审核")
        self.fail("status", card_id, "researching", contains="审核")
        self.assertNotIn("发票", self.ok("brief").split("## 今日机会")[1].split("##")[0])

        self.ok("review", card_id)
        e1 = evs[0]["id"]
        self.ok("evidence-verify", e1, "--type", "public")
        o = self.ok("score", card_id, "--pain", 3, "--access", 3, "--feasibility", 4, "--reuse", 3, "--risk", 3,
                    "--basis", "仅一条公开资料，未接触客户")
        self.assertIn("记录 40", o)          # 单一公开来源 → T0 → 封顶 40
        self.ok("status", card_id, "researching")
        aid = self.new_id("action-add", card_id, "--title", "联系 3 家小企业财务", "--hypothesis", "录入耗时是真痛点")
        self.assertGreater(aid, 0)
        self.assertIn("联系 3 家小企业财务", self.ok("brief"))

    def test_default_mock_output_is_labelled(self):
        os.environ.pop("WORLDOS_MOCK_RESPONSE")
        self.new_id("item-add", "--title", "任意", "--source", "s")
        self.ok("extract")
        name = self.scalar("SELECT name FROM cards")
        self.assertIn("模拟输出", name)
        self.assertIn("[模拟]", self.ok("cards"))
        md = self.ok("card", self.scalar("SELECT id FROM cards"))
        self.assertIn("模拟适配器（测试用，非研究结论）", md)

    def test_fixture_is_valid_json(self):
        with open(os.path.join(FIXTURES, "mock_extract.json"), encoding="utf-8") as f:
            self.assertIsInstance(json.load(f), list)
