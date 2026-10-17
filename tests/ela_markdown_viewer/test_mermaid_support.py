"""Tests for Mermaid support (renderer + viewer integration).

Uses injected fake renderers so mermaidx is not required; real mermaidx
rendering is covered by an importorskip test at the bottom.
"""

from __future__ import annotations

import threading
import time

import pytest
from _qthelpers import wait_for_clipboard as _wait_for_clipboard
from _qthelpers import wait_until as _wait_until
from PyQt6.QtGui import QColor, QImage, QTextCursor, QTextTable

import pyqt6_ela_pro.mermaid_support as support
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer
from pyqt6_ela_pro.mermaid_support import (
    MERMAID_THEME_VARIABLES,
    ElaMermaidRenderer,
    _build_config,
)

MERMAID_MARKDOWN = "```mermaid\nflowchart LR\n    A --> B\n```"


def _fragments(viewer: ElaMarkdownViewer) -> list:
    result = []
    block = viewer.document().begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                result.append(fragment)
            iterator += 1
        block = block.next()
    return result


def _mermaid_images(viewer: ElaMarkdownViewer) -> list:
    return [
        f
        for f in _fragments(viewer)
        if f.charFormat().isImageFormat()
        and f.charFormat().toImageFormat().name().startswith("elamermaid://")
    ]


def _tables(viewer: ElaMarkdownViewer) -> list:
    result = []
    stack = [viewer.document().rootFrame()]
    while stack:
        frame = stack.pop()
        for child in frame.childFrames():
            if isinstance(child, QTextTable):
                result.append(child)
            stack.append(child)
    return result


def _code_tables(viewer: ElaMarkdownViewer) -> list:
    return [t for t in _tables(viewer) if viewer._is_code_table(t)]


def _fake_image(theme: str) -> QImage:
    image = QImage(200, 100, QImage.Format.Format_ARGB32)
    image.fill(QColor("steelblue" if theme == "dark" else "gold"))
    return image


class TestMermaidLazyImport:
    def test_mermaidx_not_imported_at_module_level(self):
        assert "mermaidx" not in vars(support)

    def test_probe_happens_only_for_mermaid_fence(self, monkeypatch):
        calls = []

        def fake_available():
            calls.append(True)
            return False

        monkeypatch.setattr(support, "mermaidx_available", fake_available)
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\nx = 1\n```")
        assert calls == []

        v.setMarkdown("```mermaid\nflowchart LR\n    A --> B\n```")
        assert calls
        v.deleteLater()


class TestMermaidTheme:
    def test_build_config_base_theme_and_variables(self):
        config = _build_config("light")
        assert config["theme"] == "base"
        assert (
            config["themeVariables"]["primaryColor"]
            == MERMAID_THEME_VARIABLES["light"]["primaryColor"]
        )
        assert config["flowchart"]["curve"] == "basis"
        assert config["sequence"]["mirrorActors"] is False

        overridden = _build_config("dark", {"primaryColor": "#123456"})
        assert overridden["themeVariables"]["primaryColor"] == "#123456"
        assert (
            overridden["themeVariables"]["primaryTextColor"]
            == MERMAID_THEME_VARIABLES["dark"]["primaryTextColor"]
        )

    def test_set_theme_variables_override_and_reset(self):
        renderer = ElaMermaidRenderer()
        renderer.setThemeVariables("light", {"primaryColor": "#123456"})
        assert renderer.themeVariables("light")["primaryColor"] == "#123456"

        renderer.setThemeVariables("light", None)
        assert (
            renderer.themeVariables("light")["primaryColor"]
            == MERMAID_THEME_VARIABLES["light"]["primaryColor"]
        )
        renderer.deleteLater()

    def test_constructor_theme_variables(self):
        renderer = ElaMermaidRenderer(
            themeVariables={"light": {"primaryColor": "#ABCDEF"}}
        )
        assert renderer.themeVariables("light")["primaryColor"] == "#ABCDEF"
        renderer.deleteLater()


class TestMermaidRendererUnit:
    def test_last_error_reported_and_cleared(self, qapp):
        def failing(code, theme):
            raise RuntimeError("resvg 不可用")

        renderer = ElaMermaidRenderer()
        renderer.setRenderer(failing)
        renderer.request("E1", "light")
        assert _wait_until(qapp, lambda: renderer.lookup("E1", "light")[0])
        error = renderer.lastError()
        assert error is not None and "resvg 不可用" in error

        # 恢复为正常渲染后，错误被清除
        renderer.setRenderer(lambda code, theme: _fake_image(theme))
        renderer.request("E1", "light")
        assert _wait_until(qapp, lambda: renderer.lookup("E1", "light")[1] is not None)
        assert renderer.lastError() is None
        renderer.deleteLater()

    def test_unavailable_backend_reports_reason(self, qapp, monkeypatch):
        monkeypatch.setattr(support, "_AVAILABLE", False)
        monkeypatch.setattr(support, "_AVAILABLE_ERROR", "ImportError: DLL load failed")
        renderer = ElaMermaidRenderer()
        assert not renderer.available()
        assert "DLL load failed" in (renderer.lastError() or "")
        renderer.deleteLater()

    def test_dedupe_and_cache(self, qapp):
        calls = []

        def fake(code, theme):
            calls.append((code, theme))
            time.sleep(0.05)
            return _fake_image(theme)

        renderer = ElaMermaidRenderer()
        renderer.setRenderer(fake)
        assert renderer.available()

        renderer.request("A", "light")
        renderer.request("A", "light")
        assert _wait_until(qapp, lambda: renderer.lookup("A", "light")[0])
        assert len(calls) == 1
        known, image = renderer.lookup("A", "light")
        assert known and image is not None and image.width() == 200

        # 缓存命中：同步回调，不再调用渲染函数
        results = []
        renderer.request("A", "light", results.append)
        assert results and results[0] is not None
        assert len(calls) == 1

        # 不同主题走独立缓存
        renderer.request("A", "dark")
        assert _wait_until(qapp, lambda: renderer.lookup("A", "dark")[0])
        assert len(calls) == 2
        renderer.deleteLater()

    def test_failure_cached(self, qapp):
        calls = []

        def failing(code, theme):
            calls.append(theme)
            return None

        renderer = ElaMermaidRenderer()
        renderer.setRenderer(failing)
        renderer.request("B", "light")
        assert _wait_until(qapp, lambda: renderer.lookup("B", "light")[0])
        known, image = renderer.lookup("B", "light")
        assert known and image is None
        renderer.request("B", "light")
        assert len(calls) == 1
        renderer.deleteLater()

    def test_clear_cache(self, qapp):
        renderer = ElaMermaidRenderer()
        renderer.setRenderer(lambda code, theme: _fake_image(theme))
        renderer.request("C", "light")
        assert _wait_until(qapp, lambda: renderer.lookup("C", "light")[0])
        renderer.clearCache()
        assert renderer.lookup("C", "light") == (False, None)
        renderer.deleteLater()

    def test_inflight_result_of_old_backend_is_discarded(self, qapp):
        """在途渲染的结果不得回填缓存、也不得喂给新请求的回调。

        ``setRenderer`` / ``setThemeVariables`` 都走 ``clearCache``，但已提交的
        ``_RenderTask`` 照跑。没有代次判定时它回来会写缓存、还会 ``pop`` 掉同一
        key 上**新**请求的回调 —— 新请求拿到旧后端的图，它自己的真图永远送不到。
        """
        gate = threading.Event()
        old_calls = []
        new_calls = []

        def _tagged(width: int, color: str) -> QImage:
            image = QImage(width, 100, QImage.Format.Format_ARGB32)
            image.fill(QColor(color))
            return image

        def slow_old(code, theme):
            old_calls.append(theme)
            gate.wait(2.0)
            return _tagged(111, "gold")  # 旧后端：宽度 111

        def fast_new(code, theme):
            new_calls.append(theme)
            return _tagged(222, "steelblue")  # 新后端：宽度 222

        renderer = ElaMermaidRenderer()
        renderer.setRenderer(slow_old)
        first = []
        renderer.request("D", "light", first.append)  # 旧后端的在途任务
        # 确保旧任务**已经进了**旧后端（_render_function 是在工作线程里读的，
        # 换后端太早的话它会读到新的）
        assert _wait_until(qapp, lambda: bool(old_calls))

        # 换后端（= clearCache），再对同一 (code, theme) 发起新请求
        renderer.setRenderer(fast_new)
        assert first == [None], "换后端时在途回调以 None 交付"
        second = []
        renderer.request("D", "light", second.append)

        # 旧任务此刻才回来：必须被整条丢弃
        gate.set()
        assert _wait_until(qapp, lambda: bool(new_calls))
        assert _wait_until(qapp, lambda: bool(second))
        for _ in range(20):  # 给旧任务一点时间回填（若有 bug，这里会写进去）
            qapp.processEvents()
            _wait_until(qapp, lambda: False, timeout_ms=5)

        assert second and second[0] is not None, "新请求只应收到新后端的结果"
        assert second[0].width() == 222, "收到的是旧后端的图（迟到结果没被丢弃）"
        assert new_calls == ["light"]
        known, image = renderer.lookup("D", "light")
        assert known and image is not None
        assert image.width() == 222, "缓存里必须是新后端渲的图"
        renderer.deleteLater()


class TestMermaidViewerIntegration:
    def test_placeholder_then_image(self, qapp):
        themes = []
        gate = threading.Event()

        def fake(code, theme):
            themes.append(theme)
            gate.wait(timeout=3)
            return _fake_image(theme)

        v = ElaMarkdownViewer()
        v.resize(520, 360)
        v.setMermaidRenderer(fake)
        assert v.mermaidAvailable()
        v.setMarkdown(MERMAID_MARKDOWN)
        v.show()
        qapp.processEvents()

        assert "Mermaid 渲染中…" in v.document().toPlainText()
        gate.set()
        assert _wait_until(qapp, lambda: bool(_mermaid_images(v)))
        assert "Mermaid 渲染中…" not in v.document().toPlainText()

        fragment = _mermaid_images(v)[0]
        image_format = fragment.charFormat().toImageFormat()
        assert abs(image_format.width() - 100) < 1.0  # 200 / 2
        assert image_format.toolTip() == f"Mermaid: {MERMAID_MARKDOWN[11:-4]}"

        assert not _code_tables(v)
        assert themes and themes[0] in ("light", "dark")
        v.close()
        v.deleteLater()

    def test_copy_mermaid_source(self, qapp, requires_clipboard):
        v = ElaMarkdownViewer()
        v.resize(520, 360)
        v.setMermaidRenderer(lambda code, theme: _fake_image(theme))
        v.setMarkdown(MERMAID_MARKDOWN)
        v.show()
        qapp.processEvents()
        assert _wait_until(qapp, lambda: bool(_mermaid_images(v)))

        fragment = _mermaid_images(v)[0]
        cursor = QTextCursor(v.document())
        cursor.setPosition(fragment.position() + 1)
        v.textBrowser().setTextCursor(cursor)
        source = v._mermaid_source_at_cursor()
        assert source == MERMAID_MARKDOWN[11:-4]

        received = []
        v.mermaidCopied.connect(received.append)
        menu = v._create_context_menu()
        actions = {action.text(): action for action in menu.actions()}
        assert actions["复制 Mermaid 源码"].isEnabled()
        actions["复制 Mermaid 源码"].trigger()
        qapp.processEvents()
        assert received == [source]
        assert (
            _wait_for_clipboard(
                qapp, source, lambda: actions["复制 Mermaid 源码"].trigger()
            )
            == source
        )
        menu.deleteLater()
        v.close()
        v.deleteLater()

    def test_failure_falls_back_to_code_card(self, qapp):
        v = ElaMarkdownViewer()
        v.resize(520, 360)
        v.setMermaidRenderer(lambda code, theme: None)
        v.setMarkdown(MERMAID_MARKDOWN)
        v.show()
        qapp.processEvents()

        assert _wait_until(
            qapp,
            lambda: (
                bool(_code_tables(v))
                and "Mermaid 渲染中…" not in v.document().toPlainText()
            ),
        )
        tables = _code_tables(v)
        assert tables
        # Typora 风格：无语言头栏，代码内容在首格
        assert (
            "flowchart LR"
            in tables[0].cellAt(0, 0).firstCursorPosition().block().text()
        )
        assert not _mermaid_images(v)
        v.close()
        v.deleteLater()

    def test_disabled_renders_code_card(self, qapp):
        v = ElaMarkdownViewer()
        v.setMermaidEnabled(False)
        assert not v.mermaidAvailable()
        v.setMarkdown(MERMAID_MARKDOWN)

        assert "Mermaid 渲染中…" not in v.document().toPlainText()
        tables = _code_tables(v)
        assert tables
        assert "flowchart" in v.document().toPlainText()
        assert not _mermaid_images(v)
        v.deleteLater()

    def test_unclosed_fence_preview(self, qapp):
        v = ElaMarkdownViewer()
        v.setMermaidRenderer(lambda code, theme: _fake_image(theme))
        v.beginStream()
        v.appendMarkdown("```mermaid\nflowchart LR\n    A --> B")
        v._stream_timer.stop()
        v._flush_stream()

        assert not _mermaid_images(v)
        text = v.document().toPlainText()
        assert "flowchart LR" in text
        v.endStream()
        v.deleteLater()

    def test_stream_commit_then_render(self, qapp):
        v = ElaMarkdownViewer()
        v.resize(520, 360)
        v.setMermaidRenderer(lambda code, theme: _fake_image(theme))
        v.show()
        qapp.processEvents()
        v.beginStream()
        v.appendMarkdown(MERMAID_MARKDOWN + "\n\n尾部段落")
        v._stream_timer.stop()
        v._flush_stream()

        assert _wait_until(qapp, lambda: bool(_mermaid_images(v)))
        v.endStream()
        assert _mermaid_images(v)
        v.close()
        v.deleteLater()


class TestMermaidxRealRender:
    def test_real_mermaidx_render(self, qapp):
        pytest.importorskip("mermaidx")
        v = ElaMarkdownViewer()
        v.resize(560, 400)
        v.setMarkdown(MERMAID_MARKDOWN)
        v.show()
        qapp.processEvents()

        assert _wait_until(qapp, lambda: bool(_mermaid_images(v)), timeout_ms=15000)
        fragment = _mermaid_images(v)[0]
        assert fragment.charFormat().toImageFormat().width() > 10
        v.close()
        v.deleteLater()

    def test_real_mermaidx_chinese_labels(self, qapp):
        pytest.importorskip("mermaidx")
        v = ElaMarkdownViewer()
        v.resize(560, 400)
        v.setMarkdown("```mermaid\nflowchart LR\n    提出需求 --> 实现并测试\n```")
        v.show()
        qapp.processEvents()

        assert _wait_until(qapp, lambda: bool(_mermaid_images(v)), timeout_ms=15000)
        # 系统字体回退渲染中文：图片正常生成且不残留占位文本
        assert "Mermaid 渲染中…" not in v.document().toPlainText()
        v.close()
        v.deleteLater()
