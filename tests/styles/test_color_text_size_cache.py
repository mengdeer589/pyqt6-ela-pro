"""``ColorText`` 尺寸查询缓存：重复查询不重算、键变化后失效、结果与 Qt 一致。

动机：思考折叠 / 工具卡正文都是「一个 ColorText 装全文」，展开时布局链会把
``heightForWidth`` 问十几遍，每次都重新折行整段文字（18KB 文本单次 5-15ms，
展开实测 343ms）。缓存键 = 文本摘要 + 宽度 + 字体 + 外观，不持有全文引用。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from pyqt6_ela_pro._styles import ColorText, _COLOR_TEXT_SIZE_CACHE_MAX

TEXT = "这一段用于测试尺寸查询缓存的文本，包含中文与 code 片段。\n" * 200


class _CountingText(ColorText):
    """记录 ``_compute_size_metric`` 的调用（= 真实重算次数）。"""

    def __init__(self):
        super().__init__()
        self.computes: list[tuple[str, int]] = []

    def _compute_size_metric(self, kind: str, width: int):
        self.computes.append((kind, width))
        return super()._compute_size_metric(kind, width)


def _prepare(label) -> None:
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setText(TEXT)


class TestColorTextSizeCache:
    def test_height_for_width_reuses_cache(self, make):
        label = make(_CountingText)
        _prepare(label)
        first = label.heightForWidth(500)
        second = label.heightForWidth(500)
        assert first == second
        assert label.computes == [("h", 500)]

    def test_width_change_recomputes(self, make):
        label = make(_CountingText)
        _prepare(label)
        label.heightForWidth(500)
        label.heightForWidth(400)
        assert label.computes == [("h", 500), ("h", 400)]

    def test_text_change_invalidates(self, make):
        label = make(_CountingText)
        _prepare(label)
        label.heightForWidth(500)
        label.setText("短文本" * 20)
        label.heightForWidth(500)
        assert [c for c in label.computes if c[0] == "h"] == [("h", 500), ("h", 500)]

    def test_font_change_invalidates(self, make):
        label = make(_CountingText)
        _prepare(label)
        label.heightForWidth(500)
        font = label.font()
        font.setPointSizeF(font.pointSizeF() + 2)
        label.setFont(font)
        label.heightForWidth(500)
        assert [c for c in label.computes if c[0] == "h"] == [("h", 500), ("h", 500)]

    def test_size_hint_and_minimum_hint_are_cached(self, make):
        label = make(_CountingText)
        _prepare(label)
        label.sizeHint()
        label.sizeHint()
        label.minimumSizeHint()
        label.minimumSizeHint()
        assert label.computes == [("s", -1), ("m", -1)]

    def test_non_wrapped_minimum_hint_reuses_size_hint(self, make):
        """非换行标签的 minimumSizeHint 与 sizeHint 同值，不应再算一遍。"""
        label = make(_CountingText)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(False)
        label.setText(TEXT)
        assert label.minimumSizeHint() == QLabel.minimumSizeHint(label)
        assert label.computes == [("s", -1)]

    def test_cache_is_bounded(self, make):
        label = make(ColorText)
        _prepare(label)
        for width in range(200, 200 + _COLOR_TEXT_SIZE_CACHE_MAX * 30, 10):
            label.heightForWidth(width)
        assert len(label._size_cache) <= _COLOR_TEXT_SIZE_CACHE_MAX

    def test_matches_qt_computation(self, make):
        """缓存只复用结果，不能改变数值。"""
        label = make(ColorText)
        _prepare(label)
        assert label.heightForWidth(500) == QLabel.heightForWidth(label, 500)
        assert label.sizeHint() == QLabel.sizeHint(label)
        assert label.minimumSizeHint() == QLabel.minimumSizeHint(label)
        # 缓存命中后仍与 Qt 一致
        assert label.heightForWidth(500) == QLabel.heightForWidth(label, 500)

    def test_empty_text(self, make):
        label = make(ColorText)
        assert label.heightForWidth(300) == QLabel.heightForWidth(label, 300)
        assert label.sizeHint() == QLabel.sizeHint(label)
