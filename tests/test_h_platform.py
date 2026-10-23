"""平台兼容：数据目录规则、中文路径、GBK 控制台输出、GBK 编码 CSV、--porcelain、命令行入口。"""
import os
import subprocess
import sys

from worldos import db

from .helpers import Base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PlatformTest(Base):
    def test_data_dir_rules(self):
        p, d = db.resolve_paths(os.path.join(self.dir, "a.db"))
        self.assertEqual(d, self.dir)
        os.environ["WORLDOS_HOME"] = os.path.join(self.dir, "家")
        p, d = db.resolve_paths(None)
        self.assertEqual(p, os.path.join(self.dir, "家", "worldos.db"))
        os.environ["WORLDOS_DB"] = os.path.join(self.dir, "b.db")
        self.assertEqual(db.resolve_paths(None)[0], os.path.join(self.dir, "b.db"))
        del os.environ["WORLDOS_DB"], os.environ["WORLDOS_HOME"]
        self.assertEqual(db.resolve_paths(None)[1], os.path.join(os.path.expanduser("~"), "worldos-data"))

    def test_gbk_csv_import(self):
        path = os.path.join(self.dir, "中文表格.csv")
        with open(path, "w", encoding="gbk", newline="") as f:
            f.write("title,source,url\n羽毛球馆订场,自己观察,https://a.com\n")
        self.assertIn("新增 1 条", self.ok("item-import", path))
        self.assertEqual(self.scalar("SELECT title FROM items"), "羽毛球馆订场")

    def test_id_lists_accept_commas_or_spaces(self):
        # PowerShell 包装函数或不同 shell 可能把 1,2 拆成多个参数
        for i in range(3):
            self.new_id("item-add", "--title", f"t{i}", "--source", "s")
        self.assertIn("手动模式", self.ok("extract", "--manual", "--ids", "1,2"))
        self.assertIn("手动模式", self.ok("extract", "--manual", "--ids", "1", "3"))
        self.fail("extract", "--manual", "--ids", "1,x", contains="id 列表")

    def test_porcelain_prints_only_id(self):
        code, o, e = self._porcelain("item-add", "--title", "t", "--source", "s")
        self.assertEqual((code, o.strip()), (0, "1"))

    def _run(self, args, encoding):
        env = {k: v for k, v in os.environ.items() if not k.startswith("WORLDOS_")}
        env.update(PYTHONIOENCODING=encoding, PYTHONPATH=ROOT)
        env.pop("PYTHONUTF8", None)
        return subprocess.run([sys.executable, "-m", "worldos", "--db", self.path, *args],
                              capture_output=True, env=env, cwd=self.dir, timeout=60)

    def test_module_entry_and_gbk_console(self):
        """模拟中文 Windows 控制台被重定向时的 GBK 编码：不能因字符无法编码而崩溃。"""
        r = self._run(["item-add", "--title", "羽毛球✔馆", "--source", "观察"], "gbk")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self._run(["brief"], "gbk")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = r.stdout.decode("gbk")
        self.assertIn("每日简报", text)
        self.assertIn("羽毛球", text)
        r = self._run(["status", "999", "researching"], "gbk")
        self.assertEqual(r.returncode, 1)
        self.assertIn("不存在", r.stderr.decode("gbk"))

    def test_help(self):
        r = self._run(["-h"], "utf-8")
        self.assertEqual(r.returncode, 0)
        self.assertIn("evidence-verify", r.stdout.decode("utf-8"))
