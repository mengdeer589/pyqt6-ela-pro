"""``ElaPagination`` 测试：初值 / 页码夹取 / 可见页计算 / 跳转框 / hover。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, Qt, QPointF
from PyQt6.QtGui import QMouseEvent
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.ela_pagination import ElaPagination


@pytest.fixture
def p(make):
    return make(ElaPagination)


class TestElaPaginationInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_current_page", 1),
            ("_total_pages", 1),
            ("_button_size", 28),
            ("_pager_count", 11),
            ("_jumper_visible", False),
            ("_hover_index", -1),
        ],
    )
    def test_initialization_with_defaults(self, p, attr, expected):
        assert getattr(p, attr) == expected

    def test_has_current_page_changed_signal(self, p):
        assert callable(p.currentPageChanged)


class TestElaPaginationCurrentPage:
    def test_current_page_default(self, p):
        assert p.currentPage() == 1

    def test_set_current_page(self, p):
        p.setTotalPages(5)
        p.setCurrentPage(3)
        assert p.currentPage() == 3

    @pytest.mark.parametrize(
        "requested", [0, 10, -1], ids=["below-min", "above-max", "negative"]
    )
    def test_set_current_page_clamps(self, p, requested):
        """越界一律夹回 1（``setTotalPages`` 之后 current 尚未被修正）。"""
        p.setTotalPages(5)
        p.setCurrentPage(requested)
        assert p.currentPage() == 1

    def test_set_current_page_emits_signal(self, p):
        p.setTotalPages(5)
        received = []
        p.currentPageChanged.connect(received.append)
        p.setCurrentPage(3)
        assert 3 in received

    def test_set_current_page_same_value_no_emit(self, p):
        p.setTotalPages(5)
        p.setCurrentPage(1)
        received = []
        p.currentPageChanged.connect(received.append)
        p.setCurrentPage(1)
        assert received == []


class TestElaPaginationTotalPages:
    def test_total_pages_default(self, p):
        assert p.totalPages() == 1

    def test_set_total_pages(self, p):
        p.setTotalPages(20)
        assert p.totalPages() == 20

    @pytest.mark.parametrize("total", [0, -5], ids=["zero", "negative"])
    def test_set_total_pages_clamps_to_min_1(self, p, total):
        p.setTotalPages(total)
        assert p.totalPages() == 1

    def test_set_total_pages_corrects_current_page(self, p):
        p.setTotalPages(3)
        p.setCurrentPage(3)
        p.setTotalPages(1)
        assert p.currentPage() == 1


class TestElaPaginationAppearance:
    @pytest.mark.parametrize(
        ("setter", "getter", "value"),
        [
            (ElaPagination.setButtonSize, ElaPagination.buttonSize, 36),
            (ElaPagination.setPagerCount, ElaPagination.pagerCount, 7),
        ],
    )
    def test_setter_roundtrip(self, p, setter, getter, value):
        setter(p, value)
        assert getter(p) == value

    @pytest.mark.parametrize(
        ("getter", "expected"),
        [
            (ElaPagination.buttonSize, 28),
            (ElaPagination.pagerCount, 11),
            (ElaPagination.isJumperVisible, False),
        ],
    )
    def test_getter_default(self, p, getter, expected):
        assert getter(p) == expected

    def test_set_button_size_updates_height(self, p):
        p.setButtonSize(36)
        assert p.height() >= 36

    def test_jumper_edit_hidden_by_default(self, p):
        assert p._jumper_edit.isVisible() is False

    def test_jumper_edit_visible_after_set(self, p):
        p.setJumperVisible(True)
        assert p._jumper_edit.isHidden() is False


class TestElaPaginationPageLabel:
    def test_page_label_exists(self, p):
        assert hasattr(p, "_page_label")

    def test_page_label_hidden_by_default(self, p):
        assert p._page_label.isVisible() is False

    def test_page_label_visible_with_jumper(self, p):
        p.setJumperVisible(True)
        assert p._page_label.isHidden() is False

    def test_page_label_text_format(self, p):
        p.setTotalPages(50)
        p.setJumperVisible(True)
        assert "1" in p._page_label.text()
        assert "50" in p._page_label.text()

    def test_page_label_updates_on_set_current(self, p):
        p.setTotalPages(50)
        p.setJumperVisible(True)
        p.setCurrentPage(25)
        assert "25" in p._page_label.text()
        assert "50" in p._page_label.text()


class TestElaPaginationVisiblePages:
    @pytest.mark.parametrize(
        ("total", "expected"),
        [(1, [1]), (5, [1, 2, 3, 4, 5])],
        ids=["single", "few"],
    )
    def test_visible_pages_without_ellipsis(self, p, total, expected):
        p.setTotalPages(total)
        assert p._getVisiblePages() == expected

    @pytest.mark.parametrize(
        ("current", "left_gap", "right_gap"),
        [
            (1, None, -1),  # 首页：只有右侧省略号
            (50, -3, None),  # 末页：只有左侧省略号
            (25, -3, -1),  # 中间：两侧都有
        ],
        ids=["first", "last", "middle"],
    )
    def test_visible_pages_with_ellipsis(self, p, current, left_gap, right_gap):
        p.setTotalPages(50)
        p.setPagerCount(11)
        p.setCurrentPage(current)

        pages = p._getVisiblePages()

        assert 1 in pages
        assert 50 in pages
        assert current in pages
        if left_gap is not None:
            assert left_gap in pages
        else:
            assert -3 not in pages
        if right_gap is not None:
            assert right_gap in pages
        else:
            assert -1 not in pages


class TestElaPaginationButtonRects:
    @pytest.fixture
    def rects(self, p):
        p.setTotalPages(5)
        return p._getButtonRects()

    def test_returns_pairs(self, rects):
        assert len(rects) > 0
        assert all(len(item) == 2 for item in rects)

    def test_first_rect_is_prev_button(self, rects):
        assert rects[0][1] == 0  # prev button

    def test_last_rect_is_next_button(self, rects):
        assert rects[-1][1] == -2  # next button


class TestElaPaginationJumperEntered:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [("5", 5), ("abc", 1), ("999", 1)],
        ids=["valid", "not-a-number", "out-of-range"],
    )
    def test_on_jumper_entered(self, p, text, expected):
        p.setTotalPages(10)
        p._jumper_edit.setText(text)
        p._onJumperEntered()
        assert p.currentPage() == expected


class TestElaPaginationTheme:
    def test_on_theme_changed_updates_mode(self, p):
        p._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert p._theme_mode == ElaThemeType.ThemeMode.Dark


class TestElaPaginationDeleteLater:
    def test_delete_later_cleans_up(self, p):
        p.deleteLater()


class TestElaPaginationHoverReset:
    """指针移出后必须清掉 hover 高亮（此前没有 leaveEvent）。"""

    @staticmethod
    def _mouse(qapp, widget, event_type, pos, glob):
        qapp.sendEvent(
            widget,
            QMouseEvent(
                event_type,
                QPointF(pos),
                QPointF(glob),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )

    def test_leave_event_clears_hover_index(self, make, qapp):
        p = make(ElaPagination)
        p.setTotalPages(10)
        p.resize(420, 40)
        p.show()
        qapp.processEvents()

        pos = p._getButtonRects()[2][0].center()
        glob = p.mapToGlobal(pos)

        self._mouse(qapp, p, QEvent.Type.MouseMove, pos, glob)
        assert p._hover_index == 2

        self._mouse(qapp, p, QEvent.Type.Leave, pos, glob)
        assert p._hover_index == -1, "Leave 之后 hover 高亮必须复位"

        p.close()

    def test_class_defines_leave_event(self):
        assert "leaveEvent" in vars(ElaPagination)


class TestElaPaginationPagerCountClamp:
    """F16 回归：``setPagerCount`` 最小 7。

    更小时 ``_getVisiblePages`` 的中间分支 ``side = (pc-4)//2`` 变负，
    会产出空窗 + **相邻双省略号**（旧实现实测 [1, -3, -1, 50]）。
    """

    @pytest.mark.parametrize("requested", [3, 5, 7, 11, 0, -2])
    def test_clamped_to_min_7(self, p, requested):
        p.setPagerCount(requested)
        assert p.pagerCount() == max(7, requested)

    @pytest.mark.parametrize("count", [7, 9, 11, 13])
    def test_no_adjacent_ellipsis_and_no_empty_window(self, p, count):
        p.setTotalPages(100)
        p.setPagerCount(count)
        for current in (1, 2, 50, 99, 100):
            p.setCurrentPage(current)
            pages = p._getVisiblePages()
            assert pages, f"页码窗口为空: count={count} current={current}"
            for a, b in zip(pages, pages[1:]):
                assert not (a < 0 and b < 0), f"相邻省略号: {pages}"

    def test_invalid_value_keeps_current(self, p):
        p.setPagerCount(9)

        p.setPagerCount("x")
        p.setPagerCount(float("inf"))

        assert p.pagerCount() == 9
