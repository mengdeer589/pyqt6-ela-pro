"""Mermaid 渲染性能相关行为测试：视口优先调度、跨主题降级、自适应倍率、预热。

用注入的假渲染器，不需要真实 mermaidx。
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from _qthelpers import wait_until as _wait_until
from PyQt6.QtGui import QColor, QImage

import pyqt6_ela_pro.mermaid_support as support
from pyqt6_ela_pro.ela_markdown_viewer import (
    _MERMAID_PENDING_PREFIX,
    ElaMarkdownViewer,
)
from pyqt6_ela_pro.mermaid_support import (
    ElaMermaidRenderer,
    adaptive_zoom,
    svg_size,
)

BLOCK = "```mermaid\nflowchart LR\n    A --> B\n```"
THREE_BLOCKS = "\n\n".join(
    f"文本 {i}\n\n```mermaid\nflowchart LR\n    A{i} --> B{i}\n```" for i in range(3)
)


def _images(viewer: ElaMarkdownViewer) -> list:
    result = []
    block = viewer.document().begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                fmt = fragment.charFormat()
                if fmt.isImageFormat() and fmt.toImageFormat().name().startswith(
                    "elamermaid://"
                ):
                    result.append(fragment)
            iterator += 1
        block = block.next()
    return result


def _fake_image(theme: str) -> QImage:
    image = QImage(200, 100, QImage.Format.Format_ARGB32)
    image.fill(QColor("steelblue" if theme == "dark" else "gold"))
    return image


SVG_NARROW = '<svg width="100" height="50" viewBox="0 0 100 50"></svg>'
SVG_WIDE = '<svg width="2000" height="300" viewBox="0 0 2000 300"></svg>'
SVG_HUGE = '<svg viewBox="0 0 8000 400"></svg>'


class TestAdaptiveZoom:
    def test_svg_size_viewbox_and_attributes(self):
        assert svg_size(SVG_NARROW) == (100.0, 50.0)
        assert svg_size('<svg width="320px" height="200px"></svg>') == (320.0, 200.0)
        assert svg_size("<svg></svg>") == (0.0, 0.0)
        assert svg_size("") == (0.0, 0.0)

    def test_narrow_keeps_supersampling(self):
        assert adaptive_zoom(SVG_NARROW, 700) == 2.0

    def test_wide_diagram_downscaled(self):
        zoom = adaptive_zoom(SVG_WIDE, 700)
        assert 0.5 <= zoom < 2.0
        assert abs(zoom - 0.7) < 0.01  # 700 * 2 / 2000

    def test_huge_diagram_clamped_to_min(self):
        assert adaptive_zoom(SVG_HUGE, 700) == 0.5

    def test_unknown_target_or_size_uses_default(self):
        assert adaptive_zoom(SVG_NARROW, None) == 2.0
        assert adaptive_zoom(SVG_NARROW, 0) == 2.0
        assert adaptive_zoom("<svg></svg>", 700) == 2.0

    def test_max_image_width_roundtrip(self, qapp):
        renderer = ElaMermaidRenderer()
        assert renderer.maxImageWidth() is None
        renderer.setMaxImageWidth(640)
        assert renderer.maxImageWidth() == 640.0
        renderer.setMaxImageWidth(None)
        assert renderer.maxImageWidth() is None
        renderer.deleteLater()


class TestCrossThemeLookup:
    def test_other_theme_hit(self, qapp):
        renderer = ElaMermaidRenderer()
        renderer.setRenderer(lambda code, theme: _fake_image(theme))
        done = []
        renderer.request("graph LR\nA-->B", "light", done.append)
        assert _wait_until(qapp, lambda: bool(done))

        known, theme, image = renderer.lookupAnyTheme("graph LR\nA-->B", "dark")
        assert known and theme == "light" and image is not None
        assert renderer.lookupAnyTheme("graph LR\nA-->B", "light") == (
            False,
            None,
            None,
        )
        assert renderer.lookupAnyTheme("other", "dark") == (False, None, None)
        renderer.deleteLater()

    def test_failure_reported_as_known_without_image(self, qapp):
        renderer = ElaMermaidRenderer()

        def failing(code, theme):
            raise RuntimeError("boom")

        renderer.setRenderer(failing)
        done = []
        renderer.request("graph LR\nA-->B", "light", done.append)
        assert _wait_until(qapp, lambda: bool(done))
        known, theme, image = renderer.lookupAnyTheme("graph LR\nA-->B", "dark")
        assert known and theme == "light" and image is None
        renderer.deleteLater()


class TestPrewarm:
    def test_skipped_with_custom_renderer(self, qapp):
        renderer = ElaMermaidRenderer()
        renderer.setRenderer(lambda code, theme: _fake_image(theme))
        assert renderer.prewarm() is False
        renderer.deleteLater()

    def test_prewarm_once_uses_tiny_diagram(self, qapp, monkeypatch):

        renderer = ElaMermaidRenderer()
        calls = []
        monkeypatch.setattr(support, "mermaidx_available", lambda: True)
        monkeypatch.setattr(
            renderer,
            "_render_function",
            lambda: lambda code, theme: calls.append((code, theme)),
            raising=False,
        )
        assert renderer.prewarm() is True
        assert renderer.prewarm() is False
        assert _wait_until(qapp, lambda: bool(calls))
        assert calls[0] == (support._PREWARM_CODE, "light")
        renderer.deleteLater()

    def test_viewer_toggle_and_forwarding(self, qapp, monkeypatch):

        # 同类用例都把可选依赖抹掉（见 test_prewarm_once_uses_tiny_diagram）。
        # 本用例验证的是**viewer 的转发**，不是 mermaidx 装没装；不抹的话
        # 未装可选依赖的机器上``mermaidRenderer()`` 恒为 None，本条永久红。
        monkeypatch.setattr(support, "mermaidx_available", lambda: True)
        viewer = ElaMarkdownViewer()
        assert viewer.mermaidPrewarm() is False
        with patch.object(
            ElaMermaidRenderer, "prewarm", autospec=True, return_value=True
        ) as mocked:
            viewer.setMermaidPrewarm(True)
            assert viewer.mermaidPrewarm() is True
            renderer = viewer.mermaidRenderer()
            assert renderer is not None
            mocked.assert_called_once_with(renderer)
        viewer.setMermaidPrewarm(False)
        viewer.deleteLater()


class _FakeRenderer:
    """记录请求顺序的最小渲染器替身（供调度测试注入）。"""

    def __init__(self, hits=None):
        self.requested: list = []
        self.hits = hits or {}
        self.max_widths: list = []

    def lookup(self, code, theme):
        if code in self.hits:
            return True, self.hits[code]
        return False, None

    def lookupAnyTheme(self, code, theme):
        return False, None, None

    def setMaxImageWidth(self, width):
        self.max_widths.append(width)

    def request(self, code, theme, callback=None):
        self.requested.append((code, theme))


class TestViewportPriority:
    def _viewer_with_jobs(self, qapp, monkeypatch, positions, hits=None):
        viewer = ElaMarkdownViewer()
        fake = _FakeRenderer(hits)
        monkeypatch.setattr(viewer, "_ensure_mermaid_renderer", lambda: fake)
        monkeypatch.setattr(viewer, "_mermaid_anchor_positions", lambda: positions)
        monkeypatch.setattr(viewer, "_replace_mermaid_pending", lambda *a, **k: None)
        viewer._mermaid_disabled = False
        viewer._mermaid_jobs = [
            {
                "index": index,
                "code": f"code {index}",
                "digest": f"d{index}",
                "anchor": f"{_MERMAID_PENDING_PREFIX}d{index}-{index}",
                "theme": "light",
                "distance": float("inf"),
            }
            for index in range(len(positions))
        ]
        return viewer, fake

    def test_picks_nearest_to_viewport_then_next(self, qapp, monkeypatch):
        viewer = ElaMarkdownViewer()
        height = viewer.textBrowser().viewport().height()
        near = height / 2
        positions = {
            f"{_MERMAID_PENDING_PREFIX}d0-0": near + 400,
            f"{_MERMAID_PENDING_PREFIX}d1-1": near + 10,
            f"{_MERMAID_PENDING_PREFIX}d2-2": near + 200,
        }
        viewer, fake = self._viewer_with_jobs(qapp, monkeypatch, positions)
        viewer._pump_mermaid()
        assert fake.requested == [("code 1", "light")]
        viewer._mermaid_active = 0
        viewer._pump_mermaid()
        assert fake.requested == [("code 1", "light"), ("code 2", "light")]
        viewer._mermaid_active = 0
        viewer._pump_mermaid()
        assert fake.requested[-1] == ("code 0", "light")
        viewer.deleteLater()

    def test_stale_theme_jobs_dropped(self, qapp, monkeypatch):
        positions = {
            f"{_MERMAID_PENDING_PREFIX}d{index}-{index}": 10.0 for index in range(2)
        }
        viewer, fake = self._viewer_with_jobs(qapp, monkeypatch, positions)
        viewer._mermaid_jobs[0]["theme"] = "dark"
        viewer._mermaid_jobs[1]["theme"] = "light"
        viewer._pump_mermaid()
        assert fake.requested == [("code 1", "light")]
        assert viewer._mermaid_jobs == []
        viewer.deleteLater()

    def test_cache_hit_does_not_hit_renderer(self, qapp, monkeypatch):
        positions = {
            f"{_MERMAID_PENDING_PREFIX}d{index}-{index}": 10.0 for index in range(2)
        }
        viewer, fake = self._viewer_with_jobs(
            qapp, monkeypatch, positions, hits={"code 0": _fake_image("light")}
        )
        replaced = []
        monkeypatch.setattr(
            viewer, "_replace_mermaid_pending", lambda *args: replaced.append(args)
        )
        viewer._pump_mermaid()
        assert [args[0] for args in replaced] == ["code 0"]
        assert fake.requested == [("code 1", "light")]
        viewer.deleteLater()

    def test_only_one_request_in_flight_for_many_blocks(self, qapp):
        viewer = ElaMarkdownViewer()
        state = {"active": 0, "max": 0}
        lock = threading.Lock()

        def slow(code, theme):
            with lock:
                state["active"] += 1
                state["max"] = max(state["max"], state["active"])
            time.sleep(0.03)
            with lock:
                state["active"] -= 1
            return _fake_image(theme)

        viewer.setMermaidRenderer(slow)
        viewer.setMarkdown(THREE_BLOCKS)
        assert _wait_until(qapp, lambda: len(_images(viewer)) == 3)
        assert state["max"] == 1
        viewer.deleteLater()


class TestCrossThemeFallbackViewer:
    def test_theme_switch_shows_stale_image_immediately(self, qapp):
        viewer = ElaMarkdownViewer()

        def render(code, theme):
            if theme == "dark":
                time.sleep(0.3)  # 新主题慢渲染：期间应看到旧主题图
            return _fake_image(theme)

        viewer.setMermaidRenderer(render)
        viewer.setMarkdown(THREE_BLOCKS)
        assert _wait_until(qapp, lambda: len(_images(viewer)) == 3)

        viewer._is_dark_theme = True
        viewer._render()
        # 尚未处理任何事件：旧主题图应已顶替占位
        assert len(_images(viewer)) == 3
        for fragment in _images(viewer):
            names = fragment.charFormat().anchorNames()
            assert names and names[0].startswith(_MERMAID_PENDING_PREFIX)

        # 新主题渲染完成后：pending 锚点消失（全部换成本主题图）
        assert _wait_until(
            qapp,
            lambda: (
                len(_images(viewer)) == 3
                and all(not f.charFormat().anchorNames() for f in _images(viewer))
            ),
        )
        viewer.deleteLater()
