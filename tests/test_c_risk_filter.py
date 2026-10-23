"""测试 C：风险过滤。被标记为非法、未经授权或有害的机会，不能被推荐，也不能进入后续验证流程。"""
from worldos import brief, cards

from .helpers import Base


class RiskFilterTest(Base):
    def _scored_active_card(self, name):
        cid = self.new_id("card-add", "--name", name)
        self.new_id("score", cid, "--pain", 2, "--access", 5, "--feasibility", 5, "--reuse", 5, "--risk", 5,
                    "--basis", "演示")
        self.ok("status", cid, "researching")
        return cid

    def test_kill_flags_block_everything(self):
        for flag in sorted(cards.KILL_FLAGS):
            with self.subTest(flag=flag):
                cid = self._scored_active_card(f"【演示数据】{flag} 机会")
                self.assertIn(f"{flag} 机会", self.ok("brief"))
                self.ok("filter", cid, flag, "--reason", "测试")
                self.assertEqual(self.scalar("SELECT status FROM cards WHERE id=?", cid), "killed")
                self.assertNotIn(f"{flag} 机会", self.ok("brief"))
                self.assertNotIn(cid, [r["id"] for r in brief.recommendable(self.conn)])
                self.fail("score", cid, "--pain", 1, "--access", 1, "--feasibility", 1, "--reuse", 1,
                          "--risk", 1, "--basis", "x", "--reason", "y", contains="已淘汰")
                self.fail("action-add", cid, "--title", "继续推进", contains="已淘汰")
                for st in ("candidate", "researching", "validating", "won"):
                    self.fail("status", cid, st)
                self.fail("filter", cid, "ok", contains="不能撤销")
                self.fail("evidence-add", cid, "--type", "public", "--claim", "c", "--url", "https://x.y",
                          contains="已淘汰")
                self.fail("log", "interview", "--card", cid, "--who", "A", contains="已淘汰")
                self.fail("card-set", cid, "problem", "改一下", contains="已淘汰")
                # 修改记录里有系统写入的淘汰原因
                self.assertTrue(self.q("SELECT 1 FROM card_revisions WHERE card_id=? AND field='status' "
                                       "AND new_value='killed' AND actor='system'", cid))

    def test_pause_flags_pause_and_block_research(self):
        cid = self._scored_active_card("【演示数据】找不到付费方的机会")
        self.ok("filter", cid, "no_payer")
        self.assertEqual(self.scalar("SELECT status FROM cards WHERE id=?", cid), "paused")
        self.fail("status", cid, "researching", contains="前置过滤未通过")
        self.fail("action-add", cid, "--title", "x", contains="未通过前置过滤")
        self.assertNotIn("找不到付费方", self.ok("brief"))
        # 人工确认找到付费方后可以恢复
        self.ok("filter", cid, "ok", "--reason", "找到了付费方")
        self.ok("status", cid, "researching")

    def test_action_kill_decision_kills_card(self):
        cid = self._scored_active_card("【演示数据】验证失败的机会")
        aid = self.new_id("action-add", cid, "--title", "访谈")
        self.ok("action-done", aid, "--result", "没人愿意付钱", "--decision", "kill")
        self.assertEqual(self.scalar("SELECT status FROM cards WHERE id=?", cid), "killed")
