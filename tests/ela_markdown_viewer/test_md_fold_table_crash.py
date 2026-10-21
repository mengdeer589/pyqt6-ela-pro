"""回归：「折叠内含 markdown 表 + 其后还有表」的确定性崩溃（bug 报告 §5）。

崩溃是**进程级**的（未物化的 frame 树被删坏 → 第一段 ``endEditBlock`` 后的
布局 ``scan_frames`` 解引用坏指针 = 0xC0000005，无 traceback），所以跑崩溃
形状的渲染一律在**子进程**里做：真回归时只挂子进程，不会带走整个 pytest
会话；子进程按阶段打印 CASE / FACTS / SURVIVED，父进程据此定位。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: 崩溃形状：折叠（内含 markdown 表）之后还有另一张表
COLLAPSED = """<details>
<summary>line</summary>
| a1 | b1 |
| --- | --- |
| INNER1 | INNER2 |
</details>

| c | d |
| --- | --- |
| OUTER1 | OUTER2 |
"""

#: 折叠内无表的对照（改坏 frame 树的必要条件之一是折叠区间含表格单元块）
FOLD_WITHOUT_TABLE = """<details>
<summary>line</summary>
纯文本内容 PLAIN1
</details>

| c | d |
| --- | --- |
| OUTER1 | OUTER2 |
"""

_PROBE = """
import json
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

app = QApplication([])
from PyQt6ElaWidgetTools import eApp

eApp.init()

from pyqt6_ela_pro import ElaMarkdownViewer

cases = json.loads(sys.argv[1])
viewer = ElaMarkdownViewer()
viewer.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
viewer.resize(800, 600)
viewer.show()
app.processEvents()


def facts(name, text):
    print(
        "FACTS "
        + json.dumps(
            {
                "case": name,
                "label": "line" in text and "elafold" not in text,
                "inner_removed": "INNER1" not in text,
                "inner_kept": "INNER1" in text,
                "outer_kept": "OUTER1" in text,
                "no_tokens": "\\ue000" not in text,
            }
        ),
        flush=True,
    )


for name, source in cases.items():
    print(f"CASE {name}", flush=True)
    viewer.setMarkdown(source)
    app.processEvents()
    viewer.textBrowser().viewport().repaint()
    app.processEvents()
    facts(name, viewer.document().toPlainText())

# 折叠点开（展开路径同样带表格）：切换后内部表回来、文档不崩
print("CASE expand", flush=True)
viewer.setMarkdown(cases["collapsed"])
app.processEvents()
viewer._toggle_fold_expanded("0")
app.processEvents()
viewer.textBrowser().viewport().repaint()
app.processEvents()
facts("expand", viewer.document().toPlainText())

# 同一文档重复渲染（主题切换 / 重设内容路径）
for _ in range(2):
    viewer.setMarkdown(cases["collapsed"])
    app.processEvents()
print("SURVIVED", flush=True)
"""


@pytest.fixture(scope="module")
def render_facts():
    """在独立子进程里渲染三种形状，返回 (case -> facts)。"""
    payload = json.dumps(
        {
            "collapsed": COLLAPSED,
            "no_table": FOLD_WITHOUT_TABLE,
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, payload],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(_REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"子进程渲染崩溃（exit={proc.returncode}）\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "SURVIVED" in proc.stdout, (
        f"子进程未跑到 SURVIVED\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    facts = {}
    for line in proc.stdout.splitlines():
        if line.startswith("FACTS "):
            item = json.loads(line[len("FACTS ") :])
            facts[item.pop("case")] = item
    return facts


class TestFoldTableCrash:
    def test_collapsed_fold_with_table_survives(self, render_facts):
        """最小崩溃形状：折叠（含表）+ 其后有表 —— 曾确定性 0xC0000005。"""
        facts = render_facts["collapsed"]
        assert facts["label"], "折叠标签应已替换（无残留占位符）"
        assert facts["inner_removed"], "折叠内的表应被删除"
        assert facts["outer_kept"], "折叠后的表应保留"
        assert facts["no_tokens"], "文档里不应残留占位符字符"

    def test_expanded_fold_renders_inner_table(self, render_facts):
        """展开路径：折叠内表应展示、折叠后的表保留。"""
        facts = render_facts["expand"]
        assert facts["label"]
        assert facts["inner_kept"], "展开后折叠内的表应出现"
        assert facts["outer_kept"]
        assert facts["no_tokens"]

    def test_fold_without_table_still_works(self, render_facts):
        facts = render_facts["no_table"]
        assert facts["label"]
        assert facts["inner_removed"]
        assert facts["outer_kept"]
        assert facts["no_tokens"]
