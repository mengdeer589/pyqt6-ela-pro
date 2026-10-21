"""Tests for ElaMarkdownViewer new features: task lists, highlighting, math, streaming."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextTable
from PyQt6.QtTest import QTest

from pyqt6_ela_pro import ela_markdown_viewer as viewer_module
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer
from pyqt6_ela_pro.example.markdown_page import (
    _MARKDOWN_ALL,
    _MARKDOWN_ANSWER,
    MarkdownPage,
)


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
    """代码块包裹表（表格式标记 / 底色判定）。"""
    return [table for table in _tables(viewer) if viewer._is_code_table(table)]


def _cell_fragments(viewer: ElaMarkdownViewer, table) -> list:
    """代码单元格内的全部文本片段（跳过语言标签行）。"""
    document = viewer.document()
    cell = table.cellAt(table.rows() - 1, 0)
    first = cell.firstCursorPosition().blockNumber()
    last = cell.lastCursorPosition().blockNumber()
    result = []
    for n in range(first, last + 1):
        block = document.findBlockByNumber(n)
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                result.append(fragment)
            iterator += 1
    return result


class TestElaMarkdownViewerTaskList:
    def test_unchecked_and_checked(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("- [ ] todo\n- [x] done\n- [X] upper")

        text = v.document().toPlainText()
        assert "□" in text
        assert text.count("■") == 2
        v.deleteLater()

    def test_task_marker_inside_code_fence_untouched(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("```\n- [x] not a task\n```")

        code = "".join(f.text() for f in _fragments(v) if f.charFormat().fontFamilies())
        assert "[x] not a task" in code
        assert "■" not in v.document().toPlainText()
        v.deleteLater()


class TestElaMarkdownViewerHighlight:
    def test_python_code_highlighted(self):
        pytest.importorskip("pygments")
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\ndef foo(x):\n    return x + 1\n```")

        tables = _code_tables(v)
        assert len(tables) == 1
        colors = {
            f.charFormat().foreground().color().name()
            for f in _cell_fragments(v, tables[0])
            if f.text().strip()
        }
        # 关键字 / 函数名 / 数字等应有多种着色
        assert len(colors) >= 2
        v.deleteLater()

    def test_unknown_language_falls_back(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("```nosuchlang\nplain code\n```")

        assert "plain code" in v.document().toPlainText()
        v.deleteLater()

    def test_missing_pygments_degrades_gracefully(self, monkeypatch):
        monkeypatch.setattr(
            viewer_module, "_PYGMENTS_STATE", {"loaded": True, "module": None}
        )
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\ndef foo():\n    pass\n```")

        assert "def foo():" in v.document().toPlainText()
        v.deleteLater()


class TestElaMarkdownViewerMath:
    def test_inline_formula_embedded_as_image(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("质能方程 $E=mc^2$ 很有名")

        images = [f for f in _fragments(v) if f.charFormat().isImageFormat()]
        assert len(images) == 1
        assert "elamath" not in v.document().toPlainText()
        assert "质能方程" in v.document().toPlainText()
        v.deleteLater()

    def test_display_formula_centered(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("$$\n\\frac{a}{b}\n$$")

        images = [f for f in _fragments(v) if f.charFormat().isImageFormat()]
        assert images
        block = v.document().begin()
        found_center = False
        while block.isValid():
            if block.blockFormat().alignment() & Qt.AlignmentFlag.AlignHCenter:
                found_center = True
                break
            block = block.next()
        assert found_center
        v.deleteLater()

    def test_equation_environment_supported(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("\\begin{equation}\na^2+b^2=c^2\n\\end{equation}")

        images = [f for f in _fragments(v) if f.charFormat().isImageFormat()]
        assert len(images) == 1
        v.deleteLater()

    def test_unsupported_formula_falls_back_to_source(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("$x^{$ 与 $x^2$")

        # 未闭合分组属于结构性错误：保留源码文本；x^2 支持：图片
        assert "x^{" in v.document().toPlainText()
        images = [f for f in _fragments(v) if f.charFormat().isImageFormat()]
        assert len(images) == 1
        v.deleteLater()

    def test_dollar_in_code_fence_not_extracted(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("```\necho $HOME\n```")

        code = "".join(f.text() for f in _fragments(v) if f.charFormat().fontFamilies())
        assert "$HOME" in code
        images = [f for f in _fragments(v) if f.charFormat().isImageFormat()]
        assert images == []
        v.deleteLater()


class TestElaMarkdownViewerStreaming:
    SOURCE = (
        "# 标题\n\n"
        "第一段包含 **粗体** 与 `行内代码`。\n\n"
        "```python\n"
        "def add(a, b):\n"
        "    return a + b\n"
        "```\n\n"
        "| 列1 | 列2 |\n|-----|-----|\n| A | B |\n\n"
        "公式 $x^2+1$ 与引用：\n\n"
        "> 引用文本\n"
    )

    def _stream(self, viewer: ElaMarkdownViewer, chunks, wait: bool = True):
        viewer.beginStream()
        for chunk in chunks:
            viewer.appendMarkdown(chunk)
            if wait:
                QTest.qWait(60)
        viewer.endStream()

    def test_final_text_matches_oneshot(self):
        reference = ElaMarkdownViewer()
        reference.setMarkdown(self.SOURCE)

        for chunk_size in (1, 7, 64):
            v = ElaMarkdownViewer()
            chunks = [
                self.SOURCE[i : i + chunk_size]
                for i in range(0, len(self.SOURCE), chunk_size)
            ]
            self._stream(v, chunks, wait=False)
            assert v.markdown() == self.SOURCE
            assert v.document().toPlainText() == reference.document().toPlainText()
            v.deleteLater()
        reference.deleteLater()

    def test_incremental_flush_keeps_document_consistent(self):
        v = ElaMarkdownViewer()
        v.beginStream()
        for chunk in (
            "# Ti",
            "tle\n\npara",
            " one\n\n",
            "```py\nx=1\n```\n\n",
            "| a |\n|---|\n| 1 |\n",
        ):
            v.appendMarkdown(chunk)
            QTest.qWait(70)
        assert v.isStreaming()
        text = v.document().toPlainText()
        assert "elacode" not in text
        assert "Title" in text
        v.endStream()
        assert "elacode" not in v.document().toPlainText()
        v.deleteLater()

    def test_unclosed_fence_previewed_as_code(self):
        v = ElaMarkdownViewer()
        v.beginStream()
        v.appendMarkdown("intro\n\n```python\ndef part(")
        QTest.qWait(80)

        tables = _code_tables(v)
        assert tables
        code_text = "".join(f.text() for t in tables for f in _cell_fragments(v, t))
        assert "def part(" in code_text
        v.endStream()
        v.deleteLater()

    def test_table_arrives_in_chunks(self):
        v = ElaMarkdownViewer()
        v.beginStream()
        for chunk in ("before\n\n", "| a | b |\n", "|---|---|\n", "| 1 | 2 |\n"):
            v.appendMarkdown(chunk)
            QTest.qWait(70)
        v.endStream()

        assert len(_tables(v)) == 1
        assert "before" in v.document().toPlainText()
        v.deleteLater()

    def test_append_without_begin_seeds_existing_content(self):
        v = ElaMarkdownViewer()
        v.setMarkdown("existing\n\n")
        v.appendMarkdown("appended")
        v.endStream()

        text = v.document().toPlainText()
        assert "existing" in text and "appended" in text
        assert v.markdown() == "existing\n\nappended"
        v.deleteLater()

    def test_set_markdown_resets_streaming(self):
        v = ElaMarkdownViewer()
        v.beginStream()
        v.appendMarkdown("partial")
        v.setMarkdown("# fresh")

        assert not v.isStreaming()
        assert v.document().toPlainText().strip() == "fresh"
        v.deleteLater()

    def test_stick_to_bottom_follows(self, qapp):
        v = ElaMarkdownViewer()
        v.resize(360, 120)
        v.show()
        qapp.processEvents()
        v.beginStream()
        for i in range(30):
            v.appendMarkdown(f"第 {i} 行内容\n\n")
            QTest.qWait(50)
        v.endStream()
        QTest.qWait(50)
        bar = v.textBrowser().verticalScrollBar()
        assert bar.value() >= bar.maximum() - 4

        # 上翻后不再被拽回
        bar.setValue(0)
        v.appendMarkdown("追加一段新内容\n\n")
        QTest.qWait(100)
        v.endStream()
        assert bar.value() == 0
        v.close()
        v.deleteLater()

    def test_stick_to_bottom_disabled(self, qapp):
        v = ElaMarkdownViewer()
        v.resize(360, 120)
        v.show()
        v.setStickToBottom(False)
        qapp.processEvents()
        v.beginStream()
        for i in range(20):
            v.appendMarkdown(f"line {i}\n\n")
            QTest.qWait(40)
        v.endStream()
        bar = v.textBrowser().verticalScrollBar()
        assert bar.value() < bar.maximum()
        v.close()
        v.deleteLater()


class TestExampleSamples:
    def test_example_samples_render(self):
        v = ElaMarkdownViewer()
        v.setMermaidEnabled(False)
        v.setMarkdown(_MARKDOWN_ALL)
        assert v.document().blockCount() > 3
        text = v.document().toPlainText()
        for token in (
            "elacode",
            "elamark",
            "elafn",
            "elatoc",
            "elacallout",
            "elamermaid",
        ):
            assert token not in text
        v.deleteLater()

    def test_example_all_sample_covers_features(self):
        v = ElaMarkdownViewer()
        v.setMermaidEnabled(False)
        v.setLineNumbersEnabled(True)
        v.setCodeBlockCollapseLines(12)
        v.setMarkdown(_MARKDOWN_ALL)

        text = v.document().toPlainText()
        assert "■" in text and "□" in text  # 任务列表
        for label in ("提示", "技巧", "重要", "警告", "注意"):  # 五种 Callout
            assert label in text
        assert "[^design]" not in text and "脚注定义行" in text  # 脚注
        assert "+ 展开其余" in text  # 超长代码折叠
        assert "[图片]" in text  # 远程图片拦截占位
        assert "Mermaid 渲染中…" not in text  # 禁用后回退代码卡片

        images = [f for f in _fragments(v) if f.charFormat().isImageFormat()]
        assert len(images) >= 4  # 本地图 + 矩阵/组合数/cases 公式
        v.deleteLater()

    def test_example_stream_sample_parity(self):
        reference = ElaMarkdownViewer()
        reference.setMermaidEnabled(False)
        reference.setCodeBlockCollapseLines(12)
        reference.setMarkdown(_MARKDOWN_ALL)
        v = ElaMarkdownViewer()
        v.setMermaidEnabled(False)
        v.setCodeBlockCollapseLines(12)
        v.beginStream()
        for i in range(0, len(_MARKDOWN_ALL), 13):
            v.appendMarkdown(_MARKDOWN_ALL[i : i + 13])
        v.endStream()

        assert v.document().toPlainText() == reference.document().toPlainText()
        v.deleteLater()
        reference.deleteLater()

    def test_example_stream_uses_same_sample(self):
        payload = MarkdownPage._build_stream_chunks(_MARKDOWN_ALL)
        assert "".join(payload) == _MARKDOWN_ALL
        assert len(payload) > 50

    def test_example_chat_answer_streams_with_prefix(self):
        chunks = MarkdownPage._build_stream_chunks(_MARKDOWN_ANSWER)
        assert "".join(chunks) == _MARKDOWN_ANSWER

        v = ElaMarkdownViewer()
        v.setMarkdown("**你：** 什么是流式渲染？\n\n---\n\n")
        for chunk in chunks:
            v.appendMarkdown(chunk)
        v.endStream()

        text = v.document().toPlainText()
        assert "你：" in text and "什么是流式渲染" in text
        assert "核心流程" in text and "进入流式模式" in text
        v.deleteLater()
