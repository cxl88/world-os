"""测试公共设施：每个测试一个全新的临时数据目录，隔离所有 WORLDOS_* 环境变量。"""
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from worldos import cli, db

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


class Base(unittest.TestCase):
    env = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # 目录名带中文和空格，顺便覆盖 Windows 常见的路径情况
        self.dir = os.path.join(self.tmp.name, "数据 目录")
        os.makedirs(self.dir)
        self.path = os.path.join(self.dir, "worldos.db")
        clean = {k: v for k, v in os.environ.items() if not k.startswith("WORLDOS_")}
        clean.update(self.env)
        self.env_patch = mock.patch.dict(os.environ, clean, clear=True)
        self.env_patch.start()
        self.conn = db.connect(self.path)

    def tearDown(self):
        self.conn.close()
        self.env_patch.stop()
        self.tmp.cleanup()

    def cli(self, *args):
        """运行 CLI，返回 (退出码, stdout, stderr)。"""
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            code = cli.main(["--db", self.path, *[str(x) for x in args]])
        return code, o.getvalue(), e.getvalue()

    def ok(self, *args):
        code, o, e = self.cli(*args)
        self.assertEqual(code, 0, f"命令失败：{args}\nstdout={o}\nstderr={e}")
        return o

    def fail(self, *args, contains=None):
        code, o, e = self.cli(*args)
        self.assertEqual(code, 1, f"命令应失败但成功了：{args}\nstdout={o}")
        if contains:
            self.assertIn(contains, e)
        return e

    def new_id(self, *args):
        """用 --porcelain 取新记录 id，不假设 id 从 1 开始。"""
        code, o, e = self._porcelain(*args)
        self.assertEqual(code, 0, f"命令失败：{args}\nstderr={e}")
        return int(o.strip().splitlines()[-1])

    def _porcelain(self, *args):
        o, e = io.StringIO(), io.StringIO()
        with redirect_stdout(o), redirect_stderr(e):
            code = cli.main(["--db", self.path, "--porcelain", *[str(x) for x in args]])
        return code, o.getvalue(), e.getvalue()

    def q(self, sql, *params):
        return self.conn.execute(sql, params).fetchall()

    def scalar(self, sql, *params):
        return self.conn.execute(sql, params).fetchone()[0]
