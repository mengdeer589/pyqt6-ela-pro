"""``ElaGhostBox`` 测试：分组 / 幽灵外观 / 弹层底栏 / 过滤与交互。"""

from __future__ import annotations

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, Qt, QPointF
from PyQt6.QtGui import QMouseEvent, QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget
from PyQt6ElaWidgetTools import ElaIconType
from _qthelpers import wait_until

from pyqt6_ela_pro._ownership import ElaWidgetOwnershipType
from pyqt6_ela_pro.ela_ghost_box import ElaGhostBox


@pytest.fixture
def box(make):
    # 挂一个父控件：无父控件的 ElaComboBox 关闭弹窗动画时上游 C++ 会空指针崩溃
    return make(ElaGhostBox, make(QWidget))


def _click_row(box: ElaGhostBox, qapp, row: int) -> None:
    """向列表指定行发左键 press / release（直投 viewport，绕过命中路由）。"""
    view = box.view()
    pos = view.visualRect(box.model().index(row, 0)).center()
    global_pos = view.viewport().mapToGlobal(pos)
    for event_type in (
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
    ):
        event = QMouseEvent(
            event_type,
            QPointF(pos),
            QPointF(global_pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        qapp.sendEvent(view.viewport(), event)
    qapp.processEvents()


class TestElaGhostBoxInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_placeholder", ""),
            ("_leading_icon", None),
            ("_popup_open", False),
            ("_footer", None),
            ("_footer_close_on_click", True),
            ("_expand_icon_rotate", 0.0),
        ],
    )
    def test_initialization_with_defaults(self, box, attr, expected):
        assert getattr(box, attr) == expected

    def test_default_height_is_30(self, box):
        """与上游 ElaComboBox V3.0（35→30）的触发框同高。"""
        assert box.height() == 30

    def test_items_empty(self, box):
        assert box.items == []

    def test_footer_triggered_signal(self, box):
        assert callable(box.footerTriggered)


class TestElaGhostBoxAppearance:
    @pytest.mark.parametrize(
        ("setter", "getter", "value"),
        [
            ("setPlaceholderText", "placeholderText", "选择模型"),
            ("setLeadingIcon", "leadingIcon", ElaIconType.IconName.AngleDown),
            ("setPopupFooterCloseOnClick", "popupFooterCloseOnClick", False),
        ],
    )
    def test_setter_getter_roundtrip(self, box, setter, getter, value):
        getattr(box, setter)(value)
        assert getattr(box, getter)() == value

    def test_expand_icon_rotate_property(self, box):
        box.expandIconRotate = -90.0
        assert box.expandIconRotate == -90.0

    def test_render_does_not_crash(self, box):
        box.resize(200, 28)
        pixmap = QPixmap(box.size())
        box.render(pixmap)
        assert pixmap.isNull() is False


class TestElaGhostBoxGroups:
    def test_add_group_returns_row(self, box):
        assert box.addGroup("Anthropic") == 0
        assert box.addGroup("OpenAI") == 1

    def test_header_flag_and_labels(self, box):
        box.addGroup("A")
        box.addItems(["a1", "a2"])
        box.addGroup("B")
        box.addItem("b1")
        assert box.isGroupHeader(0) is True
        assert box.isGroupHeader(1) is False
        assert box.groupLabels() == ["A", "B"]

    def test_items_excludes_group_headers(self, box):
        box.addGroup("A")
        box.addItems(["a1", "a2"])
        box.addItem("x")
        assert box.items == ["a1", "a2", "x"]

    def test_group_of(self, box):
        box.addGroup("A")
        box.addItems(["a1", "a2"])
        box.addGroup("B")
        box.addItem("b1")
        assert box.groupOf(0) == "A"
        assert box.groupOf(2) == "A"
        assert box.groupOf(3) == "B"
        assert box.groupOf(4) == "B"
        assert box.groupOf(99) is None
        assert box.isGroupHeader(99) is False

    def test_group_of_without_header_is_none(self, box):
        box.addItem("x")
        assert box.groupOf(0) is None

    def test_first_group_does_not_become_current(self, box):
        box.addGroup("A")
        assert box.currentIndex() == -1

    def test_set_current_index_skips_header(self, box):
        box.addGroup("A")
        box.addItems(["a1", "a2"])
        box.setCurrentIndex(0)
        assert box.currentIndex() == 1
        assert box.currentText() == "a1"

    def test_set_current_index_header_without_items_clears(self, box):
        box.addGroup("A")
        box.setCurrentIndex(0)
        assert box.currentIndex() == -1

    def test_set_current_text_ignores_header_text(self, box):
        box.addGroup("A")
        box.addItem("a1")
        box.setCurrentText("a1")
        assert box.currentText() == "a1"
        box.setCurrentText("A")
        assert box.currentText() == "a1"


class TestElaGhostBoxSearch:
    @pytest.fixture
    def grouped(self, box):
        box.addGroup("Cities")
        box.addItems(["北京", "上海"])
        box.addGroup("Langs")
        box.addItems(["Python"])
        return box

    def test_filter_keeps_header_with_visible_items(self, grouped):
        grouped._onSearchTextChanged("bj")
        view = grouped.view()
        assert view.isRowHidden(0) is False  # Cities 组有命中
        assert view.isRowHidden(1) is False
        assert view.isRowHidden(2) is True
        assert view.isRowHidden(3) is True  # Langs 组无命中
        assert view.isRowHidden(4) is True

    def test_filter_hides_header_without_visible_items(self, grouped):
        grouped._onSearchTextChanged("python")
        view = grouped.view()
        assert view.isRowHidden(0) is True
        assert view.isRowHidden(3) is False

    def test_filter_matches_ignoring_punctuation(self, box):
        box.addItem("gpt-4o")
        box._onSearchTextChanged("gpt4o")
        assert box.view().isRowHidden(0) is False

    def test_clear_keyword_restores_all_rows(self, grouped):
        grouped._onSearchTextChanged("bj")
        grouped._onSearchTextChanged("")
        view = grouped.view()
        assert all(not view.isRowHidden(i) for i in range(grouped.count()))


class TestElaGhostBoxSearchToggle:
    def test_search_visible_default(self, box):
        assert box.searchVisible() is True

    def test_disable_search_skips_widget(self, box, qapp):
        box.addItem("a")
        box.setSearchVisible(False)
        box.resize(240, 28)
        box.show()
        qapp.processEvents()
        box.showPopup()
        qapp.processEvents()
        assert box.searchVisible() is False
        assert box._searchWidget is None
        box.hidePopup()
        qapp.processEvents()

    def test_disable_search_restores_rows(self, box):
        box.addGroup("G")
        box.addItems(["a", "b"])
        box._onSearchTextChanged("a")
        box.setSearchVisible(False)
        view = box.view()
        assert all(not view.isRowHidden(i) for i in range(box.count()))

    def test_toggle_while_popup_open(self, box, qapp):
        box.addItem("a")
        box.resize(240, 28)
        box.show()
        qapp.processEvents()
        box.showPopup()
        qapp.processEvents()
        assert box._searchWidget is not None
        box.setSearchVisible(False)
        assert box._searchWidget.isHidden() is True
        box.setSearchVisible(True)
        assert box._searchWidget.isHidden() is False
        box.hidePopup()
        qapp.processEvents()


class TestElaGhostBoxInteraction:
    @pytest.fixture
    def grouped(self, box, qapp):
        box.addGroup("G1")
        box.addItems(["a", "b"])
        box.addGroup("G2")
        box.addItems(["c", "d"])
        box.resize(240, 28)
        box.show()
        qapp.processEvents()
        box.showPopup()
        qapp.processEvents()
        yield box
        box.hidePopup()
        qapp.processEvents()

    def test_header_click_is_swallowed(self, grouped, qapp):
        hits = []
        grouped.activated.connect(hits.append)
        _click_row(grouped, qapp, 3)  # 标题行 G2
        assert hits == []
        assert grouped.currentIndex() == -1

    def test_item_click_still_selects(self, grouped, qapp):
        _click_row(grouped, qapp, 4)
        assert grouped.currentText() == "c"

    def test_keyboard_navigation_skips_headers(self, grouped, qapp):
        view = grouped.view()
        rows = []
        for _ in range(4):
            QTest.keyClick(view, Qt.Key.Key_Down)
            qapp.processEvents()
            rows.append(view.currentIndex().row())
        assert rows == [2, 4, 5, 5]


class TestElaGhostBoxFooter:
    def test_footer_is_none_when_empty(self, box):
        assert box._footer is None

    def test_add_button_creates_footer(self, box):
        button = box.addPopupFooterButton("管理模型", key="manage")
        assert button.footerKey() == "manage"
        footer = box.popupFooter()
        assert footer.hasContent() is True
        assert footer.buttons() == [button]

    def test_remove_button_by_key(self, box):
        box.addPopupFooterButton("A", key="a")
        box.addPopupFooterButton("B", key="b")
        assert box.removePopupFooterButton("a") is True
        assert box.removePopupFooterButton("missing") is False
        assert [b.footerKey() for b in box.popupFooter().buttons()] == ["b"]

    def test_remove_button_by_handle(self, box):
        button = box.addPopupFooterButton("A", key="a")
        assert box.removePopupFooterButton(button) is True
        assert box.popupFooter().hasContent() is False

    def test_button_visible_toggle(self, box):
        button = box.addPopupFooterButton("A", key="a")
        assert box.setPopupFooterButtonVisible("a", False) is True
        assert button.isHidden() is True
        assert box.setPopupFooterButtonVisible("missing", False) is False

    def test_custom_widget_roundtrip(self, make, box):
        widget = make.track(QWidget())
        box.setPopupFooterWidget(widget)
        assert box.popupFooter().customWidget() is widget
        box.setPopupFooterWidget(None)
        assert box.popupFooter().customWidget() is None

    def test_footer_triggered_and_close_on_click(self, box, qapp):
        button = box.addPopupFooterButton("管理", key="manage")
        box.addItem("a")
        box.resize(240, 28)
        box.show()
        qapp.processEvents()
        box.showPopup()
        qapp.processEvents()
        received = []
        box.footerTriggered.connect(received.append)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert received == ["manage"]
        assert box._popup_open is False
        box.hidePopup()
        qapp.processEvents()

    def test_footer_keeps_open_when_close_on_click_disabled(self, box, qapp):
        box.setPopupFooterCloseOnClick(False)
        button = box.addPopupFooterButton("刷新", key="refresh")
        box.addItem("a")
        box.resize(240, 28)
        box.show()
        qapp.processEvents()
        box.showPopup()
        qapp.processEvents()
        received = []
        box.footerTriggered.connect(received.append)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert received == ["refresh"]
        assert box._popup_open is True
        box.hidePopup()
        qapp.processEvents()

    def test_footer_ordered_after_list(self, box, qapp):
        box.addItem("a")
        box.addPopupFooterButton("管理", key="manage")
        box.resize(240, 28)
        box.show()
        qapp.processEvents()
        box.showPopup()
        container = box.findChild(QWidget, "ElaComboBoxContainer")
        layout = container.layout()
        view = box.view()
        footer = box.popupFooter()
        ordered = wait_until(
            qapp,
            lambda: (
                layout.indexOf(view) >= 0
                and layout.indexOf(footer) == layout.count() - 1
            ),
            timeout_ms=3000,
        )
        assert ordered is True
        box.hidePopup()
        wait_until(qapp, lambda: container.isVisible() is False, timeout_ms=3000)
        qapp.processEvents()


class TestElaGhostBoxLifecycle:
    def test_parentless_hide_does_not_crash(self, qapp):
        """无父控件时 hidePopup 走原生路径：上游 C++ 关闭动画会空指针解引用。"""
        box = ElaGhostBox()
        box.addItem("a")
        box.resize(240, 28)
        box.show()
        qapp.processEvents()
        box.showPopup()
        qapp.processEvents()
        box.hidePopup()
        hidden = wait_until(
            qapp, lambda: box.view().isVisible() is False, timeout_ms=2000
        )
        assert hidden is True
        box.deleteLater()
        qapp.processEvents()

    def test_delete_later_is_safe(self, qapp):
        box = ElaGhostBox()
        box.addItem("a")
        box.addPopupFooterButton("m", key="k")
        box.showPopup()
        box.hidePopup()
        box.deleteLater()
        qapp.processEvents()


class TestElaGhostBoxPopupGeometry:
    """底栏在 C++ 动画结束后插入，且不得把 view 压扁 / 让列表跳一下。"""

    def test_footer_does_not_move_view(self, qapp, box):
        box.setFixedWidth(250)
        box.addGroup("Anthropic")
        box.addItems(["Claude 3.7 Sonnet", "Claude 3.5 Haiku"])
        box.addGroup("OpenAI")
        box.addItems(["GPT-4o", "o3", "GPT-4.1"])
        box.addPopupFooterButton("管理模型", key="manage")
        box.setMaxVisibleItems(10)
        box.show()
        qapp.processEvents()
        box.showPopup()
        # 动画起点必须在 processEvents 之前取（之后动画已经往前走了）。
        start_y = box.view().y()
        qapp.processEvents()

        container = box.findChild(QWidget, "ElaComboBoxContainer")
        assert container is not None
        view = box.view()
        footer = box.popupFooter()
        layout = container.layout()
        assert layout is not None

        rows = min(box.count(), box.maxVisibleItems())
        margins = layout.contentsMargins()
        contents = container.contentsRect()
        expected_x = contents.x() + margins.left()
        expected_y = contents.y() + margins.top() + 40
        expected_w = contents.width() - margins.left() - margins.right()
        expected_h = rows * 35
        assert start_y == expected_y - expected_h
        assert (view.x(), view.width()) == (expected_x, expected_w)
        assert view.height() == expected_h
        assert layout.indexOf(footer) == -1
        assert footer.isVisible() is False

        assert wait_until(
            qapp,
            lambda: layout.indexOf(footer) >= 0 and footer.isVisible(),
            timeout_ms=2500,
            use_qwait=True,
        )
        assert (view.x(), view.y(), view.width(), view.height()) == (
            expected_x,
            expected_y,
            expected_w,
            expected_h,
        )
        assert container.height() == expected_h + 8 + 40 + footer.height()

        box.hidePopup()
        wait_until(
            qapp,
            lambda: not container.isVisible(),
            timeout_ms=2000,
            use_qwait=True,
        )


class TestElaGhostBoxFooterOrder:
    @staticmethod
    def _row_types(box):
        row = box._footer._row
        return [type(row.itemAt(i).widget()).__name__ for i in range(row.count())]

    def test_custom_widget_stays_after_buttons_when_added_first(self, make, box):
        """???????????????????????????"""
        box.addPopupFooterButton("A", key="a")
        box.setPopupFooterWidget(make(QWidget))
        assert self._row_types(box) == ["_GhostFooterButton", "QWidget"]

    def test_custom_widget_stays_after_late_buttons(self, make, box):
        box.setPopupFooterWidget(make(QWidget))
        box.addPopupFooterButton("B", key="b")
        assert self._row_types(box) == ["_GhostFooterButton", "QWidget"]


class TestElaGhostBoxFooterOwnership:
    def test_borrowed_widget_is_released_not_deleted(self, make, box):
        widget = make.track(QWidget())
        box.setPopupFooterWidget(widget)
        box.setPopupFooterWidget(None)
        assert not sip.isdeleted(widget)
        assert widget.parent() is None

    def test_reparented_widget_returns_to_original_parent(self, make, box):
        parent = make.track(QWidget())
        widget = make.track(QWidget())
        widget.setParent(parent)
        box.setPopupFooterWidget(widget, ownership=ElaWidgetOwnershipType.Reparented)
        box.setPopupFooterWidget(None)
        assert not sip.isdeleted(widget)
        assert widget.parent() is parent

    def test_owned_widget_is_deleted(self, make, box, qapp):
        widget = make.track(QWidget())
        box.setPopupFooterWidget(widget, ownership=ElaWidgetOwnershipType.Owned)
        box.setPopupFooterWidget(None)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        assert sip.isdeleted(widget)

    def test_combo_destruction_releases_borrowed_widget(self, make, qapp):
        widget = make.track(QWidget())
        box = ElaGhostBox()
        box.setPopupFooterWidget(widget)
        sip.delete(box)
        qapp.processEvents()
        assert not sip.isdeleted(widget)
        assert widget.parent() is None
