"""Qt 定时器槽 / 信号槽异常自保（异常穿出 = 0xC0000409）。"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from PyQt6.QtCore import QUrl

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer

_VIEWER_DIR = Path(__file__).resolve().parents[2] / "pyqt6_ela_pro" / "markdown_viewer"

#: 允许裸 connect 的例外：内建 C++ 槽 / 需要按身份断开的渲染器信号
_RAW_CONNECT_ALLOW = {
    ("interaction.py", "copy.triggered"),
    ("interaction.py", "select_all.triggered"),
    ("mermaid.py", "renderer.rendered"),
}


class _BoomRenderer:
    """``request`` 必抛的假 Mermaid 渲染器。"""

    def setMaxImageWidth(self, _width):  # noqa: N802
        pass

    def lookup(self, _code, _theme):
        return False, None

    def request(self, _code, _theme):
        raise RuntimeError("boom")


def test_ensure_rendered_swallows_render_errors(make, mocker, caplog):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown("body")
    viewer._needs_render = True
    mocker.patch.object(viewer, "_render", side_effect=RuntimeError("boom"))

    with caplog.at_level(logging.ERROR):
        viewer._ensure_rendered()

    assert "懒渲染失败" in caplog.text


def test_large_render_step_falls_back_and_finishes(make, mocker, caplog):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown("fallback body")
    finished = []
    viewer.renderingFinished.connect(lambda: finished.append(True))
    viewer._large_render_chunks = ["broken chunk"]
    viewer._large_render_index = 0
    mocker.patch.object(viewer, "_render_fragment", side_effect=RuntimeError("boom"))

    with caplog.at_level(logging.ERROR):
        viewer._render_large_step()

    assert "fallback body" in viewer.toPlainText()
    assert finished == [True]
    assert viewer._large_render_chunks == []
    assert "分块渲染失败" in caplog.text


def test_pump_mermaid_failure_resets_active_and_degrades(make, mocker, caplog):
    viewer = make(ElaMarkdownViewer)
    theme = viewer._theme_key()
    viewer._mermaid_jobs = [{"code": "graph TD", "theme": theme, "distance": 0.0}]
    mocker.patch.object(
        viewer, "_ensure_mermaid_renderer", return_value=_BoomRenderer()
    )
    degraded = mocker.patch.object(viewer, "_replace_mermaid_pending")

    with caplog.at_level(logging.ERROR):
        viewer._pump_mermaid()

    assert viewer._mermaid_active == 0
    assert viewer._mermaid_jobs == []
    degraded.assert_called_once_with("graph TD", theme, None)
    assert "Mermaid 任务调度失败" in caplog.text


def test_refresh_mermaid_priorities_swallows_errors(make, mocker, caplog):
    viewer = make(ElaMarkdownViewer)
    job = {"anchor": "a", "distance": 0.0}
    viewer._mermaid_jobs = [job]
    mocker.patch.object(
        viewer, "_mermaid_anchor_positions", side_effect=RuntimeError("boom")
    )

    with caplog.at_level(logging.ERROR):
        viewer._refresh_mermaid_priorities()

    assert job["distance"] == 0.0
    assert "Mermaid 优先级刷新失败" in caplog.text


def test_mermaid_rendered_slot_swallows_errors_and_pumps(make, mocker, caplog):
    viewer = make(ElaMarkdownViewer)
    viewer._mermaid_active = 1
    mocker.patch.object(
        viewer, "_replace_mermaid_pending", side_effect=RuntimeError("boom")
    )
    pump = mocker.patch.object(viewer, "_schedule_mermaid_pump")

    with caplog.at_level(logging.ERROR):
        viewer._on_mermaid_rendered("graph TD", viewer._theme_key(), None)

    assert viewer._mermaid_active == 0
    pump.assert_called_once()
    assert "Mermaid 结果替换失败" in caplog.text


def test_anchor_slot_exception_does_not_escape(make, mocker):
    viewer = make(ElaMarkdownViewer)
    viewer.setMarkdown("# h")
    mocker.patch.object(viewer, "_render", side_effect=RuntimeError("boom"))

    with pytest.warns(RuntimeWarning, match="槽异常"):
        viewer.textBrowser().anchorClicked.emit(QUrl("#elafold-0"))


def test_signal_connections_are_guarded():
    """新增的 Python 槽连接必须走 safe_connect（例外显式登记）。"""
    offenders = []
    for path in sorted(_VIEWER_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
            ):
                chain = ast.unparse(node.func.value)
                if (path.name, chain) not in _RAW_CONNECT_ALLOW:
                    offenders.append(f"{path.name}:{node.lineno}: {chain}.connect")
    assert not offenders, "裸 connect（槽异常会 0xC0000409）：\n" + "\n".join(offenders)
