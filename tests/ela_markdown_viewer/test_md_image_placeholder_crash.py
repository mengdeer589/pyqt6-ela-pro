"""慢速探针：坏链图片反复重渲染不得触发原生 AV（bug #1）。

崩溃是**进程级**的（片段迭代器失效 → 0xC0000005，无 traceback），且非确定性；
放在子进程里跑，真回归时只挂子进程。确定性守卫见
``test_md_image_placeholder_safety.py`` 与 ``test_md_text_iterator_mutation.py``。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_PROBE = r"""
import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

app = QApplication([])
from PyQt6ElaWidgetTools import eApp

eApp.init()

from pyqt6_ela_pro import ElaMarkdownViewer

MD = (
    "# t\n\n"
    "<table>\n"
    '<tr><td>姓名</td><td><img src="images/missing_1.jpg" /></td></tr>\n'
    '<tr><td><img src="images/missing_2.jpg" /></td>'
    '<td><img src="images/missing_3.jpg" /></td></tr>\n'
    "</table>\n\n"
    "![a](images/missing_4.png) ![b](images/missing_5.png)\n\nend\n"
)

viewer = ElaMarkdownViewer()
viewer.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
viewer.resize(800, 600)
viewer.show()
app.processEvents()

for i in range(800):
    viewer.setMarkdown(MD)
    viewer.resize(400 + i % 300, 600)
    app.processEvents()

viewer.setMarkdown(MD)
app.processEvents()
text = viewer.document().toPlainText()
issues = viewer.renderIssues()
print(
    "FACTS "
    + json.dumps(
        {
            "placeholders": text.count("[图片]"),
            "image_issues": sum(1 for kind, _ in issues if kind == "image"),
            "has_end": "end" in text,
        }
    ),
    flush=True,
)
print("SURVIVED", flush=True)
"""


@pytest.mark.slow
class TestImagePlaceholderCrashLoop:
    def test_repeated_broken_image_render_survives(self):
        proc = subprocess.run(
            [sys.executable, "-c", _PROBE],
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
                facts = json.loads(line[len("FACTS ") :])
        assert facts, f"缺少 FACTS 输出\nstdout:\n{proc.stdout}"
        assert facts["placeholders"] == 5
        assert facts["image_issues"] == 5
        assert facts["has_end"]
