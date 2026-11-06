"""chat 包懒加载守卫：数据模型导入不能拉起 UI；内部块仍可显式导入。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_data_import_does_not_load_ui():
    code = """
import sys
import pyqt6_ela_pro.chat as chat

loaded = sorted(
    name for name in sys.modules
    if name.startswith((
        "pyqt6_ela_pro.chat.widget",
        "pyqt6_ela_pro.chat.view",
        "pyqt6_ela_pro.chat.input",
        "pyqt6_ela_pro.chat.bubble",
        "pyqt6_ela_pro.chat.blocks",
        "pyqt6_ela_pro.markdown_viewer",
    ))
)
print(loaded)
"""
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_ui_import_and_internal_block_import_still_work():
    code = """
from pyqt6_ela_pro.chat import ElaChatWidget, MessageHeader, ElaChatFileChanges

assert ElaChatWidget.__name__ == "ElaChatWidget"
assert MessageHeader.__name__ == "MessageHeader"
assert ElaChatFileChanges.__name__ == "ElaChatFileChanges"
print("ok")
"""
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_dir_exposes_stable_and_lazy_names():
    code = """
import pyqt6_ela_pro.chat as chat

names = dir(chat)
assert "ElaChatMessage" in names
assert "ElaChatWidget" in names
assert "MessageHeader" in names
assert "ElaChatMessage" in chat.__all__
assert "MessageHeader" not in chat.__all__
print("ok")
"""
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
