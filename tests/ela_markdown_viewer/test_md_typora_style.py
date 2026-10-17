"""Typora（github.css）风格还原测试：排版规格与自绘装饰。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QTextCursor, QTextFormat
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.ela_markdown_viewer import (
    _HEADING_RULE_WIDTH,
    _HR_MARK,
    _INLINE_CODE_MARK,
    ElaMarkdownViewer,
)

MD = """# 一级标题

正文 with `inline` 结尾。

## 二级标题

> 引用第一行
> 引用第二行

---

```python
x = 1
```
"""


def _viewer(qapp, markdown: str = MD, size=(640, 520)) -> ElaMarkdownViewer:
    v = ElaMarkdownViewer()
    v.resize(*size)
    v.show()
    v.setMarkdown(markdown)
    for _ in range(20):
        qapp.processEvents()
    return v


def _blocks(viewer: ElaMarkdownViewer) -> list:
    result = []
    block = viewer.document().begin()
    while block.isValid():
        result.append(block)
        block = block.next()
    return result


def _find_block(viewer: ElaMarkdownViewer, needle: str):
    return next(b for b in _blocks(viewer) if b.text().strip().startswith(needle))


def _block_rect(viewer: ElaMarkdownViewer, block):
    return viewer.document().documentLayout().blockBoundingRect(block)


def _inline_code_rect(viewer: ElaMarkdownViewer, needle: str):
    """含标记片段在 viewport 中的真实 ``(x1, x2, top, height)``（cursorRect 反推）。"""
    document = viewer.document()
    browser = viewer.textBrowser()
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if (
                fragment.isValid()
                and fragment.text() == needle
                and fragment.charFormat().property(_INLINE_CODE_MARK)
            ):
                start = QTextCursor(document)
                start.setPosition(fragment.position())
                end = QTextCursor(document)
                end.setPosition(fragment.position() + fragment.length())
                start_rect = browser.cursorRect(start)
                end_rect = browser.cursorRect(end)
                return (
                    start_rect.left(),
                    end_rect.left(),
                    start_rect.top(),
                    start_rect.height(),
                )
            iterator += 1
        block = block.next()
    raise AssertionError(needle)


def _count_color(image, color, x0, x1, y0, y1) -> int:
    return sum(
        1
        for x in range(int(x0), int(x1))
        for y in range(int(y0), int(y1))
        if image.pixelColor(x, y).name() == color.name()
    )


def _grab_image(viewer: ElaMarkdownViewer):
    for _ in range(10):
        viewer.repaint()
    return viewer.grab().toImage()


class TestTypograhySpec:
    def test_heading_sizes_match_typora(self, qapp):
        v = _viewer(
            qapp, "# 一\n\n## 二\n\n### 三\n\n#### 四\n\n##### 五\n\n###### 六\n"
        )
        # **基准取 h6 的实际字号，不取 ``defaultFont().pointSizeF()``**。
        # 后者在字体没有显式 pointSize 时返回 Qt 的哨兵 ``-1``，于是
        # ``base * expected`` 变成负数、断言恒假（本机实测 h1 实际21.9375pt
        # 恰好等于 9.75 × 2.25，比例完全正确，却因为基准取错而红）。
        # Typora 阶梯本身就是「相对基准的比例」，用 h6（比例 1.0）当基准
        # 钉的正是同一条不变量，且与基准字号从哪来无关。
        expected = {1: 2.25, 2: 1.75, 3: 1.5, 4: 1.25, 5: 1.0, 6: 1.0}
        sizes: dict[int, float] = {}
        for level, needle in enumerate(("一", "二", "三", "四", "五", "六"), start=1):
            block = _find_block(v, needle)
            cursor = QTextCursor(block)
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
            )
            sizes[level] = cursor.charFormat().fontPointSize()
            assert int(cursor.charFormat().fontWeight()) == int(QFont.Weight.Bold)
        base = sizes[6]
        assert base > 0, sizes
        for level, ratio in expected.items():
            assert abs(sizes[level] - base * ratio) < 0.01, (level, sizes, base)
        v.deleteLater()

    def test_heading_margins_and_h6_color(self, qapp):
        v = _viewer(qapp, "# 一\n\n###### 六\n")
        h1 = _find_block(v, "一")
        h6 = _find_block(v, "六")
        assert h1.blockFormat().topMargin() == 16.0
        assert h1.blockFormat().bottomMargin() == 16.0
        cursor = QTextCursor(h6)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        assert cursor.charFormat().foreground().color().name() == v._muted_color.name()
        v.deleteLater()

    def test_hr_marked_and_spaced(self, qapp):
        v = _viewer(qapp)
        hr = next(b for b in _blocks(v) if b.blockFormat().property(_HR_MARK))
        assert not hr.blockFormat().hasProperty(
            QTextFormat.Property.BlockTrailingHorizontalRulerWidth
        )
        assert hr.blockFormat().topMargin() == 16.0
        assert hr.blockFormat().bottomMargin() == 16.0
        v.deleteLater()


class TestPaintedDecorations:
    def _grab(self, viewer: ElaMarkdownViewer):
        for _ in range(10):
            viewer.repaint()
        return viewer.grab().toImage()

    def test_heading_rule_pixels(self, qapp):
        v = _viewer(qapp)
        image = _grab_image(v)
        for needle in ("一级标题", "二级标题"):
            block = _find_block(v, needle)
            rect = _block_rect(v, block)
            x = int(rect.x() + 40)
            # 分隔线自绘在 [bottom - _HEADING_RULE_WIDTH, bottom) 这条带上。
            # blockBoundingRect() 可能是亚像素（如 h2 的 bottom=142.59375），
            # 直接 int(bottom-1) 会向下取整到带外而误报；这里按带取整后扫描。
            band = range(
                int(rect.bottom()) - int(_HEADING_RULE_WIDTH),
                int(rect.bottom()) + 1,
            )
            rows = [
                y
                for y in band
                if image.pixelColor(x, y).name() == v._heading_rule_color.name()
            ]
            assert rows, (
                f"{needle}: 未在分隔线带 {list(band)} 找到 "
                f"{v._heading_rule_color.name()}，实际 "
                f"{ {y: image.pixelColor(x, y).name() for y in band} }"
            )
        v.deleteLater()

    def test_hr_pixels(self, qapp):
        v = _viewer(qapp)
        image = _grab_image(v)
        hr = next(b for b in _blocks(v) if b.blockFormat().property(_HR_MARK))
        rect = _block_rect(v, hr)
        x = int(rect.x() + 60)
        rows = [
            y
            for y in range(int(rect.top()), int(rect.bottom()) + 1)
            if image.pixelColor(x, y).name() == v._hr_color.name()
        ]
        assert len(rows) == 1  # opencode TUI hr 为 1px 正文色线
        v.deleteLater()

    def test_quote_rail_pixels(self, qapp):
        v = _viewer(qapp)
        image = _grab_image(v)
        quote = _find_block(v, "引用第一行")
        rect = _block_rect(v, quote)
        x = int(rect.x() + 4 + 2)
        y = int(rect.top() + 10)
        assert image.pixelColor(x, y).name() == v._quote_rail_color.name()
        # 竖线宽 4px：内侧仍是竖线色，再往右回到页面底色
        assert image.pixelColor(x + 1, y).name() == v._quote_rail_color.name()
        assert image.pixelColor(x + 3, y).name() == v._base_bg.name()
        # 引用块不再有底色
        assert quote.blockFormat().background().style() == Qt.BrushStyle.NoBrush
        v.deleteLater()

    def test_inline_code_pixels(self, qapp):
        v = _viewer(qapp)
        image = _grab_image(v)
        block = _find_block(v, "正文 with inline 结尾。")
        rect = _block_rect(v, block)
        found_bg = False
        for x in range(int(rect.x()), int(rect.right())):
            for y in range(int(rect.top()), int(rect.bottom())):
                if image.pixelColor(x, y).name() == v._inline_code_bg.name():
                    found_bg = True
                    break
            if found_bg:
                break
        assert found_bg
        v.deleteLater()

    def test_decorations_adapt_to_dark_theme(self, qapp):

        v = _viewer(qapp)
        light_rule = v._heading_rule_color.name()
        light_rail = v._quote_rail_color.name()
        v._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        for _ in range(10):
            qapp.processEvents()
        assert v._heading_rule_color.name() != light_rule
        assert v._quote_rail_color.name() != light_rail
        image = _grab_image(v)
        block = _find_block(v, "一级标题")
        rect = _block_rect(v, block)
        y = int(rect.bottom() - 1)
        assert (
            image.pixelColor(int(rect.x() + 40), y).name()
            == v._heading_rule_color.name()
        )
        v.deleteLater()

    def test_code_card_soft_edge_and_corner(self, qapp):
        v = _viewer(qapp)
        image = _grab_image(v)
        table = next(t for t in v._code_buttons_tables if v._is_code_table(t))
        rect = v._code_table_viewport_rect(table)
        assert not rect.isNull()
        # 软卡片：无描边，卡片边缘直接是代码底色
        x = int(rect.left())
        y = int(rect.center().y())
        assert image.pixelColor(x, y).name() == v._code_bg.name()
        # 左上角被页面底色遮成圆角（最角上像素完全在圆角之外）
        assert image.pixelColor(int(rect.left()), int(rect.top())).name() == (
            v._base_bg.name()
        )
        v.deleteLater()


class TestInlineCodeAlignment:
    """行内代码底色必须贴合文字（列表 / 引用缩进不得重复计入）。"""

    def test_aligned_in_list_item(self, qapp):
        v = _viewer(qapp, "1. 选取基准值 `pivot`；\n2. 把小于基准的元素放到左边。\n")
        image = _grab_image(v)
        x1, x2, top, height = _inline_code_rect(v, "pivot")
        inside = _count_color(
            image, v._inline_code_bg, x1 - 2, x2 + 2, top, top + height
        )
        assert inside > 0
        # 旧 bug：底色整体右移一个列表缩进（40px），文字右侧不应出现底色
        shifted = _count_color(
            image, v._inline_code_bg, x2 + 6, x2 + 40, top, top + height
        )
        assert shifted == 0
        v.deleteLater()

    def test_aligned_in_quote(self, qapp):
        v = _viewer(qapp, "> 引用里的 `code` 文本\n")
        image = _grab_image(v)
        x1, x2, top, height = _inline_code_rect(v, "code")
        inside = _count_color(
            image, v._inline_code_bg, x1 - 2, x2 + 2, top, top + height
        )
        assert inside > 0
        # 引用缩进 20px，同样不得重复计入
        shifted = _count_color(
            image, v._inline_code_bg, x2 + 6, x2 + 20, top, top + height
        )
        assert shifted == 0
        v.deleteLater()

    def test_aligned_in_table_cell(self, qapp):
        v = _viewer(qapp, "| 列 | 说明 |\n| --- | --- |\n| `code` | 普通 |\n")
        image = _grab_image(v)
        x1, x2, top, height = _inline_code_rect(v, "code")
        assert x1 > 4  # 单元格内边距，不能画到文档边缘
        inside = _count_color(
            image, v._inline_code_bg, x1 - 2, x2 + 2, top, top + height
        )
        assert inside > 0
        v.deleteLater()


class TestInlineCodeMark:
    def test_mark_property_without_qt_background(self, qapp):
        v = _viewer(qapp, "行内 `code` 文本")
        frags = []
        block = v.document().begin()
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.text() == "code":
                frags.append(fragment)
            iterator += 1
        assert len(frags) == 1
        fmt = frags[0].charFormat()
        assert fmt.property(_INLINE_CODE_MARK) is True
        assert fmt.background().style() == Qt.BrushStyle.NoBrush
        assert QColor(fmt.foreground().color()).isValid()
        v.deleteLater()
