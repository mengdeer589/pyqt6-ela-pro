"""Tests for ElaMarkdownViewer P4 performance features.

Covers: long-paragraph streaming commit, chunked large-document render,
cache governance.
"""

from __future__ import annotations

import random

import pytest
from PyQt6.QtTest import QTest

from pyqt6_ela_pro import ela_markdown_viewer as viewer_module
from pyqt6_ela_pro import math_lite
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer


class TestLongParagraphStreaming:
    SENTENCE = "这是一个用于测试超长段落流式提交的句子。"
    CHUNK = 2000

    def test_commits_sentence_boundaries(self):
        paragraph = self.SENTENCE * 1200
        v = ElaMarkdownViewer()
        v.beginStream()
        for start in range(0, len(paragraph), self.CHUNK):
            v.appendMarkdown(paragraph[start : start + self.CHUNK])
            v._stream_timer.stop()
            v._flush_stream()

        assert v._stream_committed > 0
        tail = len(paragraph) - v._stream_committed
        assert tail <= viewer_module._STREAM_SENTENCE_MAX
        v.endStream()
        v.deleteLater()

    def test_final_parity_with_oneshot(self):
        paragraph = self.SENTENCE * 800
        v = ElaMarkdownViewer()
        v.beginStream()
        for start in range(0, len(paragraph), self.CHUNK):
            v.appendMarkdown(paragraph[start : start + self.CHUNK])
            v._stream_timer.stop()
            v._flush_stream()
        v.endStream()

        reference = ElaMarkdownViewer()
        reference._render_into(reference.document(), paragraph)
        assert v.toPlainText() == reference.document().toPlainText()
        v.deleteLater()
        reference.deleteLater()

    def test_blank_line_cut_still_prioritized(self):
        text = "第一段。\n\n第二段内容。"
        assert viewer_module._stable_cut(text, 0, allow_sentence=True)[0] == len(
            "第一段。\n\n"
        )

    def test_short_tail_not_force_cut(self):
        text = "很短的一段。"
        assert viewer_module._stable_cut(text, 0, allow_sentence=True)[0] == 0


class TestStableCutIncremental:
    """``_stable_cut`` 的增量扫描必须与全量重扫**逐值等价**。

    函数只扫 ``safe_from`` 之后：切点若落在未闭合围栏内（超长尾部兜底提交），
    第二项返回值必须回退到围栏之前，否则下一轮会把围栏中段当普通文本、
    把围栏内的空行误判成稳定边界。
    """

    TEXTS = [
        "第一段。\n\n第二段。\n\n第三段。",
        "```python\nx = 1\n```\n\n正文\n\n更多正文",
        "前言。\n\n```python\n" + "y = 2\n" * 400,  # 未闭合大围栏
        "正文。\n\n" + "长句没有句号的段落，" * 2000,  # 触发兜底提交
        "$$x^2$$\n\n正文\n\n$$\ny = 1\n\nz\n$$\n\n尾部",
        "a\n\n" + "plain " * 4000,
    ]

    def _drive(self, text, allow_sentence=True):
        """模拟流式：连续提交，增量结果必须与全量重扫一致。

        比较的是**调用方语义**：``max(cut, committed)``（无新提交时返回什么
        无关紧要，``_flush_stream`` 也会取 max）。
        """
        committed = 0
        safe_from = 0
        for _ in range(60):
            cut_inc, next_from = viewer_module._stable_cut(
                text, committed, allow_sentence, safe_from=safe_from
            )
            cut_full, _ = viewer_module._stable_cut(
                text, committed, allow_sentence, safe_from=0
            )
            assert max(cut_inc, committed) == max(cut_full, committed), (
                f"增量扫描与全量重扫不一致：{cut_inc} != {cut_full}"
                f"（committed={committed}, safe_from={safe_from}）"
            )
            assert next_from <= max(cut_inc, committed)
            if cut_inc <= committed:
                break
            committed = cut_inc
            safe_from = next_from

    @pytest.mark.parametrize("index", range(len(TEXTS)))
    def test_incremental_matches_full_scan(self, index):
        self._drive(self.TEXTS[index])

    def test_incremental_matches_full_scan_fuzz(self):
        rng = random.Random(20261014)
        pieces = [
            "段落文字。",
            "另一个句子！",
            "**加粗**与`code`。",
            "",
            "```py\ncode line\n```",
            "```py\nunclosed line",
            "$$",
            "x = y",
            "\\[",
            "> 引用",
            "- 列表项",
            "很长的一行" * 40,
        ]
        for _ in range(30):
            text = "\n".join(rng.choice(pieces) for _ in range(rng.randint(5, 120)))
            self._drive(text)


class TestLargeRender:
    BIG = (
        "# 标题小节\n\n" + "这是内容段落，包含 `代码` 与 **加粗** 文本。" * 40 + "\n\n"
    ) * 90

    def test_large_source_uses_chunking(self, qapp):
        assert len(self.BIG) > viewer_module._LARGE_RENDER_CHARS
        v = ElaMarkdownViewer()
        progress = []
        finished = []
        v.renderingProgress.connect(progress.append)
        v.renderingFinished.connect(lambda: finished.append(True))

        v.setMarkdown(self.BIG)
        assert v.isRendering()
        for _ in range(600):
            if finished:
                break
            qapp.processEvents()
            QTest.qWait(5)

        assert finished
        assert not v.isRendering()
        assert progress and progress[-1] == 100
        assert v.toPlainText() == self._oneshot_text()
        v.deleteLater()

    def test_small_source_not_chunked(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("# 小文档\n\n内容")
        assert not v.isRendering()
        v.deleteLater()

    def test_reentrant_set_markdown_cancels(self, qapp):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.BIG)
        v.setMarkdown("# 第二个文档\n\n短内容")
        for _ in range(50):
            qapp.processEvents()
            QTest.qWait(5)
        assert not v.isRendering()
        assert "第二个文档" in v.toPlainText()
        v.deleteLater()

    @classmethod
    def _oneshot_text(cls) -> str:
        reference = ElaMarkdownViewer()
        reference._render_into(reference.document(), cls.BIG)
        text = reference.document().toPlainText()
        reference.deleteLater()
        return text


class TestCacheGovernance:
    def test_highlight_cache_cleared(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\nx = 1\n```")
        assert v._highlight_cache
        v.clearCache()
        assert not v._highlight_cache
        v.deleteLater()

    def test_highlight_cache_cap(self):
        pytest.importorskip("pygments")
        v = ElaMarkdownViewer()
        v.setHighlightCacheSize(1)
        v.setMarkdown("```python\na = 1\n```\n\n```python\nb = 2\n```")
        assert len(v._highlight_cache) <= 1
        v.deleteLater()

    def test_math_cache_capacity_and_clear(self):
        old_cap = math_lite._CACHE_CAP
        try:
            math_lite.set_cache_capacity(2)
            assert math_lite._CACHE_CAP == 2
            v = ElaMarkdownViewer()
            v.setMarkdown("$x^2$ 与 $y_1$")
            assert math_lite._CACHE
            v.clearCache()
            assert not math_lite._CACHE
            v.deleteLater()
        finally:
            math_lite.set_cache_capacity(old_cap)

    def test_zero_capacity_disables_highlight_cache(self):
        pytest.importorskip("pygments")
        v = ElaMarkdownViewer()
        v.setHighlightCacheSize(0)
        v.setMarkdown("```python\na = 1\n```")
        assert not v._highlight_cache
        v.deleteLater()


class TestCodeFontFamilyCache:
    """``_default_code_font_family()`` ????????

    ``QFontDatabase().families()`` ?????????? ~1.7ms??????????
    ???????viewer ??????? / ?????????????????
    """

    def test_families_queried_once(self, monkeypatch):
        calls = {"n": 0}

        class _FakeFontDatabase:
            # ??????? ``QFontDatabase.families()``?PyQt6 ? QFontDatabase
            # ??????????????????**??** families?
            @staticmethod
            def families():
                calls["n"] += 1
                return ["Consolas"]

        monkeypatch.setattr(viewer_module, "QFontDatabase", _FakeFontDatabase)
        monkeypatch.setattr(viewer_module, "_DEFAULT_CODE_FONT_FAMILY", None)

        first = viewer_module._default_code_font_family()
        second = viewer_module._default_code_font_family()

        assert first and first == second
        assert calls["n"] == 1


class TestLexerInstanceCache:
    """Pygments 词法器实例按语言缓存（带 stripnl/ensurenl 的构造 ~0.1ms/次且
    不命中 pygments 自带缓存，逐代码块构造随块数线性变慢）。"""

    def test_lexer_constructed_once_per_language(self, monkeypatch):
        pytest.importorskip("pygments")
        monkeypatch.setattr(viewer_module, "_LEXER_CACHE", {})
        constructed = {"n": 0}
        real_load = viewer_module._load_pygments

        def counting_load():
            pair = real_load()
            if pair is None:
                return None
            get_lexer, token_module = pair

            def counting_lexer(lang, **kwargs):
                constructed["n"] += 1
                return get_lexer(lang, **kwargs)

            return counting_lexer, token_module

        monkeypatch.setattr(viewer_module, "_load_pygments", counting_load)

        v = ElaMarkdownViewer()
        # 三个**不同内容**的代码块 -> 高亮缓存不命中，必须真正走词法
        v.setMarkdown(
            "```python\na = 1\n```\n\n```python\nb = 2\n```\n\n```python\nc = 3\n```"
        )
        assert constructed["n"] == 1, (
            f"同语言词法器被构造 {constructed['n']} 次（应为 1 次、其余复用）"
        )
        v.deleteLater()


class TestCodeGeometryCulling:
    """离屏代码块不参与昂贵的 cursorRect 几何 —— 重绘 / 滚动成本与全文档
    代码块总数解耦（原先每帧为全部表算一遍，代码块一多就掉帧）。"""

    @staticmethod
    def _many_code_doc(blocks: int = 60) -> str:
        return "\n\n".join(
            f"```python\nx = {i}\n```\n\n第 {i} 段文本。" for i in range(blocks)
        )

    def test_offscreen_tables_skip_geometry(self, qapp):
        v = ElaMarkdownViewer()
        v.resize(520, 400)
        v.show()
        qapp.processEvents()
        v.setMarkdown(self._many_code_doc())
        for _ in range(10):
            qapp.processEvents()
        assert len(v._code_buttons_tables) >= 50

        calls = []
        real = v._code_table_viewport_rect

        def counting(table):
            calls.append(table)
            return real(table)

        v._code_table_viewport_rect = counting
        try:
            v._position_code_buttons()
        finally:
            del v._code_table_viewport_rect

        total = len(v._code_buttons_tables)
        assert 0 < len(calls) < 10, f"离屏代码块也被算了几何：{len(calls)}/{total}"
        nulls = [rect for rect in v._code_button_rects if rect.isNull()]
        assert nulls, "离屏代码表应记为空矩形（不参与几何）"
        v.close()
        v.deleteLater()
        qapp.processEvents()

    def test_no_image_document_skips_image_pass(self, monkeypatch):
        """无图片语法的文档不跑 ``_apply_images``（全块 × 片段遍历）。"""
        calls = {"n": 0}
        real = viewer_module.ElaMarkdownViewer._apply_images

        def counting(self, *args, **kwargs):
            calls["n"] += 1
            return real(self, *args, **kwargs)

        monkeypatch.setattr(viewer_module.ElaMarkdownViewer, "_apply_images", counting)
        v = ElaMarkdownViewer()
        v.setMarkdown("# 标题\n\n正文段落，没有图片。\n")
        assert calls["n"] == 0, "无图文档仍跑了图片遍历"
        v.setMarkdown("![pic](missing.png)\n")
        assert calls["n"] == 1, "带图片语法的文档必须跑图片处理"
        v.deleteLater()

    def test_button_widget_set_tracks_replacements(self, qapp):
        """换文档后失效表的按钮必须被回收（widget 集合与实际按钮始终一致）。"""
        v = ElaMarkdownViewer()
        v.resize(420, 320)
        v.show()
        qapp.processEvents()
        v.setMarkdown("```py\na = 1\n```")
        qapp.processEvents()
        assert set(v._code_buttons) == v._code_button_widgets
        v.setMarkdown("```js\nlet a = 1;\n```")
        qapp.processEvents()
        assert set(v._code_buttons) == v._code_button_widgets, "换文档后旧按钮没被回收"
        assert all(not b.isVisible() for b in v._code_buttons)
        v.close()
        v.deleteLater()
        qapp.processEvents()

    def test_stream_flush_reuses_buttons(self, qapp, monkeypatch):
        """流式每次 flush 不得全量重建按钮（旧实现 10 秒 2 万+ 控件创建）。"""
        created = []
        real = viewer_module.FlatIconButton

        class _Counting(real):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self)

        monkeypatch.setattr(viewer_module, "FlatIconButton", _Counting)
        v = ElaMarkdownViewer()
        v.resize(500, 400)
        v.show()
        qapp.processEvents()
        v.beginStream()
        v.appendMarkdown("```python\nx = 1\n```\n\n")
        v._stream_timer.stop()
        v._flush_stream()
        assert v._code_buttons, "前置：稳定段应已提交一个代码卡"
        committed = len(created)
        for i in range(20):
            v.appendMarkdown(f"\n更多正文 {i}。")
            v._stream_timer.stop()
            v._flush_stream()
        assert len(created) == committed, (
            f"稳定段的复制按钮被逐次重建：{len(created)} 个（首次提交后 {committed} 个）"
        )
        v.endStream()
        v.close()
        v.deleteLater()
        qapp.processEvents()
