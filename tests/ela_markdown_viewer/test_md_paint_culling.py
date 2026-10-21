"""自绘装饰按「本次暴露区间」裁剪的回归守卫。

嵌入模式（聊天正文 / 思考）的查看器高度等于整篇文档，``viewport()`` 拿不到
真实可见范围 —— 自绘三趟（行内代码底 / 装饰线 / 代码卡圆角）若按它裁剪，
等于每帧给全文算一遍几何：单个上千行的长块是 O(行 × 标记)，几百张代码卡则
每帧都要 ``cursorRect``。

这里不钉墙钟，钉的是**几何等价**：整段一次画出来的矩形集合，必须等于按任意
区间分段画出来的并集，且每段只画与该区间相交的几何。
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, QRectF

from _qthelpers import wait_until as _wait_until

from pyqt6_ela_pro.chat import ElaChatRoleType, ElaChatWidget
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer

_EPS = 0.05


class _RecordingPainter:
    """鸭子类型的 painter 替身：只记录本库自绘产生的几何。"""

    def __init__(self) -> None:
        self.rects: list[QRectF] = []
        self.fills: list[QRectF] = []
        self.clips: list[QRectF] = []

    def setRenderHint(self, *_args) -> None:  # noqa: N802 (Qt 命名)
        pass

    def setPen(self, *_args) -> None:  # noqa: N802
        pass

    def setBrush(self, *_args) -> None:  # noqa: N802
        pass

    def setClipping(self, *_args) -> None:  # noqa: N802
        pass

    def save(self) -> None:
        pass

    def restore(self) -> None:
        pass

    def setClipRect(self, rect) -> None:  # noqa: N802
        self.clips.append(QRectF(rect))

    def drawRoundedRect(self, rect, *_args) -> None:  # noqa: N802
        self.rects.append(QRectF(rect))

    def fillRect(self, rect, *_args) -> None:  # noqa: N802
        self.fills.append(QRectF(rect))

    def drawPath(self, _path) -> None:  # noqa: N802
        pass


def _signature(rect: QRectF) -> tuple:
    return (
        round(rect.x() / _EPS),
        round(rect.y() / _EPS),
        round(rect.width() / _EPS),
        round(rect.height() / _EPS),
    )


def _same_set(left: list[QRectF], right: list[QRectF]) -> bool:
    """比较矩形**集合**（相邻区间各多画一行边界会重复，几何相同即等价）。"""
    return set(map(_signature, left)) == set(map(_signature, right))


def _first_block(viewer: ElaMarkdownViewer):
    block = viewer.document().begin()
    assert block.isValid()
    return block


def _block_top(viewer: ElaMarkdownViewer, block) -> float:
    layout = viewer.document().documentLayout()
    offset = viewer._text_browser.verticalScrollBar().value()
    return layout.blockBoundingRect(block).top() - offset


def _inline_code_document(lines: int = 60) -> str:
    return "".join(f"第 {i} 行：`value_{i}` 是配置项。\n" for i in range(lines))


class TestVisibleLineRange:
    def test_full_band_covers_every_line(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setMarkdown(_inline_code_document(40))
        qapp.processEvents()

        block = _first_block(viewer)
        text_layout = block.layout()
        top = _block_top(viewer, block)
        height = viewer.document().documentLayout().blockBoundingRect(block).height()

        first, last = viewer._visible_line_range(text_layout, top, -1e6, 1e6)
        assert (first, last) == (0, text_layout.lineCount() - 1)
        # 长块里二分只该返回窄窄一段
        narrow_first, narrow_last = viewer._visible_line_range(
            text_layout, top, top, top + height / 4
        )
        assert 0 <= narrow_first <= narrow_last < text_layout.lineCount()
        assert narrow_last - narrow_first + 1 < text_layout.lineCount()

    def test_band_above_block_is_empty(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setMarkdown(_inline_code_document(10))
        qapp.processEvents()
        block = _first_block(viewer)
        assert viewer._visible_line_range(block.layout(), 5000.0, 0.0, 400.0) == (
            0,
            -1,
        )


class TestInlineCodeCulling:
    def test_painted_rects_equal_full_paint_split_in_bands(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setMarkdown(_inline_code_document(80))
        qapp.processEvents()

        block = _first_block(viewer)
        block_top = _block_top(viewer, block)
        height = viewer.document().documentLayout().blockBoundingRect(block).height()

        full = _RecordingPainter()
        viewer._paint_block_inline_codes(
            viewer._text_browser, full, block, block_top, block_top + 1e6, block_top
        )
        assert len(full.rects) >= 40, "每个行内代码标记都应画出一个底"

        merged: list[QRectF] = []
        steps = 8
        for index in range(steps):
            top = block_top + height * index / steps
            bottom = block_top + height * (index + 1) / steps
            part = _RecordingPainter()
            viewer._paint_block_inline_codes(
                viewer._text_browser, part, block, top, bottom, block_top
            )
            merged.extend(part.rects)
            # 每段只画与该段相交的几何（允许一行余量）
            for rect in part.rects:
                assert rect.bottom() >= top - 40.0
                assert rect.top() <= bottom + 40.0

        assert _same_set(merged, full.rects), "分段绘制必须与整段绘制逐矩形一致"

    def test_narrow_band_paints_fewer_rects(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setMarkdown(_inline_code_document(100))
        qapp.processEvents()

        block = _first_block(viewer)
        block_top = _block_top(viewer, block)
        height = viewer.document().documentLayout().blockBoundingRect(block).height()

        full = _RecordingPainter()
        viewer._paint_block_inline_codes(
            viewer._text_browser, full, block, block_top, block_top + 1e6, block_top
        )
        narrow = _RecordingPainter()
        viewer._paint_block_inline_codes(
            viewer._text_browser,
            narrow,
            block,
            block_top + height / 2,
            block_top + height / 2 + 80.0,
            block_top,
        )
        assert 0 < len(narrow.rects) < len(full.rects) / 2


class TestDecorationCulling:
    def test_decorations_follow_exposed_band(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 600)
        viewer.show()
        viewer.setMarkdown(
            "".join(
                f"## 标题 {i}\n\n段落 {i}。\n\n> 引用 {i}\n\n---\n\n" for i in range(60)
            )
        )
        qapp.processEvents()

        browser = viewer._text_browser
        browser.verticalScrollBar().setValue(0)
        qapp.processEvents()
        viewport = browser.viewport().height()
        assert viewport > 0

        full = _RecordingPainter()
        viewer._paint_document_decorations(browser, full, QRect(0, 0, 600, viewport))
        assert len(full.fills) >= 6

        narrow = _RecordingPainter()
        viewer._paint_document_decorations(browser, narrow, QRect(0, 0, 600, 120))
        assert 0 < len(narrow.fills) < len(full.fills)
        for rect in narrow.fills:
            assert rect.bottom() >= -40.0
            assert rect.top() <= 160.0


class TestPaintIndex:
    def test_plain_document_skips_inline_pass(self, qapp, make, monkeypatch):
        """无行内代码的纯文本不该逐块扫片段（Win7 上跨绑定取值很贵）。"""
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setMarkdown("纯文本段落。\n\n第二段。\n")
        qapp.processEvents()

        calls: list = []
        monkeypatch.setattr(
            type(viewer),
            "_paint_block_inline_codes",
            lambda *args, **kwargs: calls.append(args),
        )
        painter = _RecordingPainter()
        viewer._paint_inline_code_backgrounds(
            viewer._text_browser, painter, QRect(0, 0, 600, 400)
        )
        assert calls == []
        assert viewer._paint_index_inline == {}

    def test_index_follows_document_revision(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setMarkdown("纯文本段落。\n")
        qapp.processEvents()
        viewer._ensure_paint_index()
        assert viewer._paint_index_inline == {}
        assert viewer._paint_index_decorations == set()

        viewer.setMarkdown("带 `行内代码` 的段落。\n")
        qapp.processEvents()
        viewer._ensure_paint_index()
        assert viewer._paint_index_inline
        assert viewer._paint_index_revision == viewer.document().revision()

    def test_indented_decorations_are_indexed(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 600)
        viewer.show()
        viewer.setMarkdown("## 标题\n\n> 引用\n\n---\n\n正文\n")
        qapp.processEvents()
        viewer._ensure_paint_index()
        assert len(viewer._paint_index_decorations) >= 3


class TestCodeCardCulling:
    def test_code_card_chrome_only_paints_visible_tables(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 600)
        viewer.show()
        viewer.setMarkdown(
            "".join(f"段落 {i}\n\n```python\nprint({i})\n```\n\n" for i in range(40))
        )
        qapp.processEvents()

        tables = viewer._code_buttons_tables
        assert len(tables) == 40
        browser = viewer._text_browser
        browser.verticalScrollBar().setValue(0)
        qapp.processEvents()
        viewport = browser.viewport().height()
        assert viewport > 0

        full = _RecordingPainter()
        viewer._paint_code_card_chrome(browser, full, 0, viewport)
        assert 0 < len(full.clips) < len(tables)

        narrow = _RecordingPainter()
        viewer._paint_code_card_chrome(browser, narrow, 0, 120)
        assert len(narrow.clips) < len(full.clips)
        for rect in narrow.clips:
            assert rect.bottom() >= -100.0
            assert rect.top() <= 220.0

    def test_position_buttons_skips_offscreen_tables(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(600, 400)
        viewer.show()
        viewer.setMarkdown(
            "".join(f"段落 {i}\n\n```python\nprint({i})\n```\n\n" for i in range(40))
        )
        qapp.processEvents()

        viewer._position_code_buttons()
        placed = [rect for rect in viewer._code_button_rects if not rect.isNull()]
        assert 0 < len(placed) < len(viewer._code_buttons_tables)


class TestEmbeddedVisibleBand:
    def test_band_uses_outer_scroll_viewport(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.resize(520, 420)
        chat.show()
        view = chat.chatView()
        mid = view.addMessage(ElaChatRoleType.Assistant, "段落内容 " * 300)
        qapp.processEvents()

        def _laid_out():
            viewer = view.bubble(mid).markdownViewer()
            bar = view._scroll.verticalScrollBar()
            return viewer is not None and viewer.height() > 0 and bar.maximum() > 0

        assert _wait_until(qapp, _laid_out)
        viewer = view.bubble(mid).markdownViewer()
        bar = view._scroll.verticalScrollBar()
        before = viewer._visible_band()
        assert before[1] - before[0] <= chat.height()
        # 嵌入查看器自身视口 = 整篇文档高度：真实可见带必须远小于它
        assert before[1] - before[0] < viewer._text_browser.viewport().height()

        bar.setValue(120)
        qapp.processEvents()
        after = viewer._visible_band()
        assert after[0] < before[0] - 50, "滚下去后可见带应整体上移"

    def test_paint_event_culls_to_exposed_rect(self, qapp, make):
        """嵌入式查看器整块重绘时，只在暴露区间内产生几何。"""
        chat = make(ElaChatWidget)
        chat.resize(520, 420)
        chat.show()
        view = chat.chatView()
        mid = view.addMessage(ElaChatRoleType.Assistant, _inline_code_document(200))
        qapp.processEvents()

        def _ready():
            viewer = view.bubble(mid).markdownViewer()
            return viewer is not None and viewer.height() > 0

        assert _wait_until(qapp, _ready)
        viewer = view.bubble(mid).markdownViewer()
        browser = viewer._text_browser
        top, bottom = viewer._visible_band()
        top = max(0, top)

        # 只给可见带：geometry 必须落在这段里
        recorded = _RecordingPainter()
        band = QRect(0, top, 600, max(1, bottom - top))
        viewer._paint_inline_code_backgrounds(browser, recorded, band)
        assert recorded.rects, "可见带内应至少画出行内代码底"
        for rect in recorded.rects:
            assert rect.bottom() >= top - 40.0
            assert rect.top() <= bottom + 40.0
