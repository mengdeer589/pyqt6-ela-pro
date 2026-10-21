"""主题 / 配色族变更的懒渲染：隐藏时不重建、可见时补齐一次；高亮缓存跨主题保留。

宿主规模下（3×3800 行 viewer + 10k 行终端全隐藏）切一次主题要 2.3s，全部花在「整篇重
解析 + 重高亮 + 重排版」上，而隐藏的文档根本没人看。契约在 `ElaMarkdownViewer._applyThemeStyle`
与 `_ensure_rendered`：隐藏时只标记，`showEvent` 补齐；高亮缓存的 key 含主题，切回来直接命中。
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from PyQt6ElaWidgetTools import eTheme, ElaThemeType
from pyqt6_ela_pro import ElaMarkdownViewer, ela_markdown_viewer as md_module

BIG_MD = ("## 标题\n\n正文一段。\n\n```python\n" + "x = 1\n" * 10 + "```\n\n") * 20


@pytest.fixture(autouse=True)
def _restore_global_theme():
    """用例会切全局主题；不还原会污染同目录其它文件的浅色断言。"""
    previous = eTheme.getThemeMode()
    yield
    eTheme.setThemeMode(previous)


def _other_mode(mode):
    return (
        ElaThemeType.ThemeMode.Light
        if mode == ElaThemeType.ThemeMode.Dark
        else ElaThemeType.ThemeMode.Dark
    )


def _switch(qapp, mode) -> None:
    eTheme.setThemeMode(mode)
    for _ in range(5):
        qapp.processEvents()


def _page(make):
    host = make(QWidget)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    viewer = make(ElaMarkdownViewer, host)
    layout.addWidget(viewer)
    return host, viewer


def _spy_render(viewer):
    calls = {"n": 0}
    real = viewer._render

    def counting():
        calls["n"] += 1
        return real()

    viewer._render = counting
    return calls


class TestThemeLazyRender:
    def test_hidden_theme_change_does_not_render(self, qapp, make):
        _, viewer = _page(make)
        viewer.setMarkdown(BIG_MD)
        calls = _spy_render(viewer)

        _switch(qapp, _other_mode(eTheme.getThemeMode()))

        assert calls["n"] == 0
        assert viewer._needs_render is True

    def test_show_catches_up_exactly_once(self, qapp, make):
        host, viewer = _page(make)
        viewer.setMarkdown(BIG_MD)
        calls = _spy_render(viewer)
        _switch(qapp, _other_mode(eTheme.getThemeMode()))
        assert viewer._needs_render is True

        host.show()
        for _ in range(5):
            qapp.processEvents()

        assert calls["n"] == 1
        assert viewer._needs_render is False

    def test_visible_theme_change_renders_immediately(self, qapp, make):
        host, viewer = _page(make)
        viewer.setMarkdown(BIG_MD)
        host.show()
        for _ in range(5):
            qapp.processEvents()
        calls = _spy_render(viewer)

        _switch(qapp, _other_mode(eTheme.getThemeMode()))

        assert calls["n"] == 1
        assert viewer._needs_render is False


class TestOffscreenThemeLazyRender:
    """滚出视口的消息仍然 ``isVisible()``：主题重渲染不能按它判断。"""

    def _chat_like(self, qapp, make, count=6):
        from PyQt6.QtWidgets import QScrollArea

        content = make(QWidget)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        viewers = []
        for _ in range(count):
            viewer = make(ElaMarkdownViewer, content)
            viewer.setEmbeddedMode(True)
            viewer.setMarkdown(BIG_MD)
            layout.addWidget(viewer)
            viewers.append(viewer)
        area = make(QScrollArea)
        area.resize(480, 320)
        area.setWidget(content)
        area.setWidgetResizable(True)
        area.show()
        for _ in range(10):
            qapp.processEvents()
        return area, viewers

    def test_offscreen_viewers_defer_until_painted(self, qapp, make):
        area, viewers = self._chat_like(qapp, make)
        calls = [_spy_render(viewer) for viewer in viewers]
        first = viewers[0]
        last = viewers[-1]
        assert first._is_on_screen() is True
        assert last._is_on_screen() is False, "滚出视口的消息不该算「在屏幕上」"

        _switch(qapp, _other_mode(eTheme.getThemeMode()))

        assert calls[0]["n"] >= 1
        assert calls[-1]["n"] == 0
        assert last._needs_render is True

        # 滚到底：最后一条进入视口、被绘制后自动补齐
        area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
        for _ in range(20):
            qapp.processEvents()
        assert last._needs_render is False
        assert calls[-1]["n"] == 1


class TestHighlightCacheAcrossThemes:
    def test_switch_back_hits_cache(self, qapp, make, monkeypatch):
        """dark → light → dark：回到已渲染过的主题不再重新 lex（缓存 key 含主题）。"""
        pytest.importorskip("pygments")
        host, viewer = _page(make)
        viewer.setHighlightCacheSize(256)
        viewer.setMarkdown(BIG_MD)
        host.show()
        for _ in range(5):
            qapp.processEvents()

        # 词法器实例是进程级缓存的（_LEXER_CACHE），先清空才能让本用例的
        # spy 真的装上；计数点选 get_tokens（真正的词法分析）而不是
        # get_lexer_by_name（实例构造已被缓存，不再每次发生）。
        monkeypatch.setattr(md_module, "_LEXER_CACHE", {})
        lexers = {"n": 0}
        real_load = md_module._load_pygments

        def counting_load():
            pair = real_load()
            if pair is None:
                return None
            get_lexer, token_module = pair

            def counting_lexer(lang, **kwargs):
                lexer = get_lexer(lang, **kwargs)
                real_tokens = lexer.get_tokens

                def counting_tokens(code):
                    lexers["n"] += 1
                    return real_tokens(code)

                lexer.get_tokens = counting_tokens
                return lexer

            return counting_lexer, token_module

        monkeypatch.setattr(md_module, "_load_pygments", counting_load)

        current = viewer._theme_mode
        before = lexers["n"]

        _switch(qapp, _other_mode(current))  # 另一主题：块未缓存，必须 lex
        after_other = lexers["n"]
        assert after_other > before, "切换到未渲染过的主题应重新 lex"

        _switch(qapp, current)  # 回到已缓存的主题：命中缓存、不再 lex
        assert lexers["n"] == after_other, (
            "切回已渲染过的主题不该重新 lex（缓存跨主题保留）"
        )
