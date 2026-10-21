"""Tests for combo_box module: ElaSearchBox, ElaSearchMultiBox, ElaSearchProxyModel."""

from __future__ import annotations

from unittest.mock import MagicMock

from PyQt6.QtCore import Qt, QPoint, QRect, QStringListModel, QModelIndex
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6ElaWidgetTools import ElaComboBox

import pytest
from _qthelpers import wait_until as _wait_until

from pyqt6_ela_pro._internal import hideComboboxPopup
from pyqt6_ela_pro.combo_box import (
    ElaSearchProxyModel,
    ElaSearchMultiBox,
    ElaSearchBox,
)
from pyqt6_ela_pro.ela_tag_box import ElaTagBox
from pyqt6_ela_pro.ela_tag_multi_box import ElaTagMultiBox
from pyqt6_ela_pro.ela_tag_search_box import ElaTagSearchBox
from pyqt6_ela_pro.ela_tag_search_multi_box import ElaTagSearchMultiBox


class TestElaSearchProxyModel:
    """Test cases for ElaSearchProxyModel."""

    def test_initialization(self):
        """Test proxy model initializes with empty keyword."""
        proxy = ElaSearchProxyModel()
        assert proxy._keyword == ""
        assert proxy._tokens == []

    def test_set_keyword_lowercase(self):
        """Test setKeyword converts keyword to lowercase."""
        proxy = ElaSearchProxyModel()
        proxy.setKeyword("TEST")
        assert proxy._keyword == "test"

    def test_filter_accepts_row_without_keyword(self):
        """Test filterAcceptsRow returns True when keyword is empty."""
        proxy = ElaSearchProxyModel()
        assert proxy.filterAcceptsRow(0, QModelIndex()) is True

    def test_filter_accepts_row_with_matching_text(self):
        """Test filterAcceptsRow matches text directly."""
        proxy = ElaSearchProxyModel()
        source_model = QStringListModel(["北京", "上海", "广州"])

        proxy.setSourceModel(source_model)
        proxy.setKeyword("北京")

        assert proxy.filterAcceptsRow(0, QModelIndex()) is True
        assert proxy.filterAcceptsRow(1, QModelIndex()) is False

    def test_filter_accepts_row_with_pinyin(self):
        """Test filterAcceptsRow matches full pinyin."""
        proxy = ElaSearchProxyModel()
        source_model = QStringListModel(["北京", "上海", "广州"])

        proxy.setSourceModel(source_model)
        proxy.setKeyword("sh")

        assert proxy.filterAcceptsRow(1, QModelIndex()) is True

    def test_filter_accepts_row_with_pinyin_initials(self):
        """Test filterAcceptsRow matches pinyin initials (bj -> 北京)."""
        proxy = ElaSearchProxyModel()
        source_model = QStringListModel(["北京", "上海", "广州"])

        proxy.setSourceModel(source_model)
        proxy.setKeyword("bj")

        assert proxy.filterAcceptsRow(0, QModelIndex()) is True
        assert proxy.filterAcceptsRow(1, QModelIndex()) is False

    def test_filter_accepts_row_with_full_pinyin_substring(self):
        """Test filterAcceptsRow matches a full pinyin substring."""
        proxy = ElaSearchProxyModel()
        source_model = QStringListModel(["北京", "上海"])

        proxy.setSourceModel(source_model)
        proxy.setKeyword("beij")

        assert proxy.filterAcceptsRow(0, QModelIndex()) is True
        assert proxy.filterAcceptsRow(1, QModelIndex()) is False

    def test_filter_requires_all_space_separated_tokens(self):
        """Test multiple tokens are ANDed."""
        proxy = ElaSearchProxyModel()
        source_model = QStringListModel(["北京", "上海", "北京上海"])

        proxy.setSourceModel(source_model)
        proxy.setKeyword("bj sh")

        assert proxy.filterAcceptsRow(0, QModelIndex()) is False
        assert proxy.filterAcceptsRow(1, QModelIndex()) is False
        assert proxy.filterAcceptsRow(2, QModelIndex()) is True

    def test_filter_is_case_insensitive(self):
        """Test filter is case insensitive."""
        proxy = ElaSearchProxyModel()
        source_model = QStringListModel(["测试"])

        proxy.setSourceModel(source_model)
        proxy.setKeyword("ce")

        assert proxy.filterAcceptsRow(0, QModelIndex()) is True

    def test_filter_matches_ignoring_punctuation(self):
        """Test compact matching ignores punctuation (gpt4o -> gpt-4o)."""
        proxy = ElaSearchProxyModel()
        source_model = QStringListModel(["gpt-4o", "claude-3"])

        proxy.setSourceModel(source_model)
        proxy.setKeyword("gpt4o")

        assert proxy.filterAcceptsRow(0, QModelIndex()) is True
        assert proxy.filterAcceptsRow(1, QModelIndex()) is False

    def test_pinyin_cache_filled_and_reused(self):
        """Test pinyin cache stores (full, initials) and is reused."""
        proxy = ElaSearchProxyModel()
        proxy.setSourceModel(QStringListModel(["北京"]))

        proxy.setKeyword("bj")
        assert proxy.filterAcceptsRow(0, QModelIndex()) is True
        assert proxy._pinyin_cache["北京"] == ("beijing", "bj")

        proxy.clearPinyinCache()
        assert proxy._pinyin_cache == {}


class TestElaSearchMultiBox:
    """Test cases for ElaSearchMultiBox."""

    def test_initialization(self):
        """Test multi-box initializes with empty selection."""
        box = ElaSearchMultiBox()
        assert box._currentSelection == []
        assert box._isRestoringSelection is False
        assert box._pinyin_cache == {}
        box.deleteLater()

    def test_add_item(self):
        """Test addItem adds item to combo box."""
        box = ElaSearchMultiBox()
        box.addItem("选项1")
        assert box.count() >= 1
        assert box.items == ["选项1"]
        box.deleteLater()

    def test_add_items(self):
        """Test addItems adds multiple items."""
        box = ElaSearchMultiBox()
        box.addItems(["选项1", "选项2", "选项3"])
        assert box.count() >= 3
        assert box.items == ["选项1", "选项2", "选项3"]
        box.deleteLater()

    def test_clear(self):
        """Test clear removes all items and selection."""
        box = ElaSearchMultiBox()
        box.addItems(["选项1", "选项2"])
        box.setCurrentSelection(["选项1"])
        box.clear()
        assert box._currentSelection == []
        assert box.items == []
        assert box._pinyin_cache == {}
        box.deleteLater()

    def test_set_current_selection_accepts_str(self):
        """F10：``str`` 归一为单元素（旧实现 ``list(str)`` 会拆成单字符）。"""
        box = ElaSearchMultiBox()
        box.addItems(["single", "other"])

        box.setCurrentSelection("single")

        assert box._currentSelection == ["single"]
        assert box.currentSelection() == ["single"]
        box.deleteLater()

    def test_set_current_selection_none_clears(self):
        box = ElaSearchMultiBox()
        box.addItems(["a"])
        box.setCurrentSelection(["a"])

        box.setCurrentSelection(None)

        assert box.currentSelection() == []
        box.deleteLater()

    def test_pinyin_cache_cleared_on_clear(self):
        """Test clear clears the pinyin cache."""
        box = ElaSearchMultiBox()
        box.addItems(["选项1", "选项2"])
        box._pinyin_cache["选项1"] = ("xuanxiang1", "xx1")
        box.clear()
        assert box._pinyin_cache == {}
        box.deleteLater()

    def test_pinyin_cache_filled_on_search(self):
        """Test _onSearchTextChanged fills pinyin cache with (full, initials)."""
        box = ElaSearchMultiBox()
        box.addItems(["北京", "上海"])
        box._onSearchTextChanged("bei")
        assert box._pinyin_cache["北京"] == ("beijing", "bj")
        box.deleteLater()

    def test_search_matches_pinyin_initials(self):
        """Test searching by initials (bj -> 北京) hides non-matching rows."""
        box = ElaSearchMultiBox()
        box.addItems(["北京", "上海"])
        box._onSearchTextChanged("bj")
        view = box.view()
        assert view.isRowHidden(0) is False
        assert view.isRowHidden(1) is True
        box.deleteLater()

    def test_search_matches_space_separated_tokens(self):
        """Test space separated tokens are ANDed."""
        box = ElaSearchMultiBox()
        box.addItems(["北京", "上海", "北京上海"])
        box._onSearchTextChanged("bj sh")
        view = box.view()
        assert view.isRowHidden(0) is True
        assert view.isRowHidden(1) is True
        assert view.isRowHidden(2) is False
        box.deleteLater()

    def test_show_popup_resets_row_filter(self):
        """Test showPopup restores hidden rows from the previous search."""
        box = ElaSearchMultiBox()
        box.addItems(["北京", "上海"])
        box._onSearchTextChanged("bj")
        box.showPopup()
        assert box.view().isRowHidden(1) is False
        box.hidePopup()
        box.deleteLater()

    def test_delete_later_cleans_up_search_widget(self):
        """Test deleteLater cleans up search widget."""
        box = ElaSearchMultiBox()
        box.addItem("test")
        box.showPopup()
        box.hidePopup()  # 关闭 Popup：残留的活动弹出窗口会拦截后续测试的鼠标事件
        box.deleteLater()

    def test_set_search_visible_roundtrip(self, make):
        """Test search visibility toggle roundtrip."""
        box = make(ElaSearchMultiBox)
        assert box.searchVisible() is True
        box.setSearchVisible(False)
        assert box.searchVisible() is False


class TestHidePopupWithoutParent:
    """无父控件关弹层不得走上游那条会崩的分支。

    ``ElaComboBox::hidePopup`` / ``ElaMultiSelectComboBox::hidePopup`` 的收起
    动画结束回调无条件 ``QApplication::sendEvent(parentWidget(), ...)`` ——
    本机实测 ``QApplication.sendEvent(None, event)`` 直接访问冲突
    （进程退出码 -1073741819，无 traceback）。所以每个组合框子类的
    ``hidePopup`` 都要先过 ``_internal.hideComboboxPopup``。

    判据钉**可观测契约**而不是「崩不崩」：崩不崩取决于平台 / 动画有没有跑完
    （上游要等弹出动画结束才把 ``_isAllowHidePopup`` 置真），offscreen 下常常
    走不到那条分支 —— 靠「没崩」当断言等于没测。
    """

    def test_helper_takes_over_when_parentless(self, qapp, make):
        box = make(ElaSearchBox)
        box.addItems(["北京", "上海"])
        box.show()
        box.showPopup()
        assert box.parentWidget() is None
        assert hideComboboxPopup(box) is True, "无父控件必须由本库接管"
        assert box.isVisible() is False or box.view().isVisible() is False

    def test_helper_defers_to_upstream_when_parented(self, qapp, make, window_widget):
        box = make(ElaSearchBox, window_widget)
        assert box.parentWidget() is window_widget
        assert hideComboboxPopup(box) is False, "有父控件必须走上游（保留收起动画）"

    @pytest.mark.parametrize(
        "factory",
        [
            lambda: ElaSearchBox(),
            lambda: ElaSearchMultiBox(),
            lambda: ElaTagBox(),
            lambda: ElaTagSearchBox(),
            lambda: ElaTagMultiBox(),
            lambda: ElaTagSearchMultiBox(),
        ],
        ids=[
            "search-box",
            "search-multi-box",
            "tag",
            "tag-search",
            "tag-multi",
            "tag-search-multi",
        ],
    )
    def test_every_combo_subclass_guards_hide_popup(self, qapp, make, factory):
        """六个子类都要在 hidePopup 里接上守卫（漏一个就回到崩溃路径）。"""
        box = make(factory)
        assert box.parentWidget() is None
        box.addItems(["北京", "上海"])
        box.show()
        box.showPopup()
        box.hidePopup()
        _wait_until(qapp, lambda: False, timeout_ms=800)
        qapp.processEvents()


class TestElaSearchBox:
    """Test cases for ElaSearchBox."""

    def test_initialization(self):
        """Test search box initializes with the native combo model."""
        box = ElaSearchBox()
        assert box.items == []
        assert box.count() == 0
        assert box._pinyin_cache == {}
        box.deleteLater()

    def test_add_item(self):
        """Test addItem adds item and user data to the native model."""
        box = ElaSearchBox()
        box.addItem("测试", "u1")
        assert box.count() == 1
        assert box.itemText(0) == "测试"
        assert box.itemData(0, Qt.ItemDataRole.UserRole) == "u1"
        assert box.findData("u1") == 0
        box.deleteLater()

    def test_add_items(self):
        """Test addItems adds multiple items."""
        box = ElaSearchBox()
        box.addItems(["北京", "上海", "广州"])
        assert box.items == ["北京", "上海", "广州"]
        box.deleteLater()

    def test_insert_item_keeps_items_in_sync(self):
        """Test native insertItem is reflected by items property."""
        box = ElaSearchBox()
        box.addItems(["a", "c"])
        box.insertItem(1, "b")
        assert box.items == ["a", "b", "c"]
        box.deleteLater()

    def test_insert_items_keeps_items_in_sync(self):
        """Test native insertItems is reflected by items property."""
        box = ElaSearchBox()
        box.addItems(["c"])
        box.insertItems(0, ["a", "b"])
        assert box.items == ["a", "b", "c"]
        box.deleteLater()

    def test_remove_item_keeps_items_in_sync(self):
        """Test native removeItem is reflected by items property."""
        box = ElaSearchBox()
        box.addItems(["a", "b", "c"])
        box.removeItem(1)
        assert box.items == ["a", "c"]
        box.deleteLater()

    def test_set_item_text_keeps_items_in_sync(self):
        """Test native setItemText is reflected by items property."""
        box = ElaSearchBox()
        box.addItems(["a", "b"])
        box.setItemText(0, "z")
        assert box.items == ["z", "b"]
        box.deleteLater()

    def test_clear(self):
        """Test clear removes all items and resets the pinyin cache."""
        box = ElaSearchBox()
        box.addItems(["北京", "上海"])
        box._onSearchTextChanged("bj")
        box.clear()
        assert box.items == []
        assert box._pinyin_cache == {}
        box.deleteLater()

    def test_search_matches_pinyin_initials(self):
        """Test searching by initials (bj -> 北京) hides non-matching rows."""
        box = ElaSearchBox()
        box.addItems(["北京", "上海"])
        box._onSearchTextChanged("bj")
        view = box.view()
        assert view.isRowHidden(0) is False
        assert view.isRowHidden(1) is True
        box.deleteLater()

    def test_search_matches_full_pinyin(self):
        """Test searching by full pinyin (bei -> 北京)."""
        box = ElaSearchBox()
        box.addItems(["北京", "上海"])
        box._onSearchTextChanged("bei")
        view = box.view()
        assert view.isRowHidden(0) is False
        assert view.isRowHidden(1) is True
        box.deleteLater()

    def test_search_matches_ignoring_punctuation(self, make):
        """Test compact matching ignores punctuation (gpt4o -> gpt-4o)."""
        box = make(ElaSearchBox)
        box.addItems(["gpt-4o", "claude-3"])
        box._onSearchTextChanged("gpt4o")
        view = box.view()
        assert view.isRowHidden(0) is False
        assert view.isRowHidden(1) is True

    def test_search_resets_when_keyword_cleared(self):
        """Test clearing the keyword restores all rows."""
        box = ElaSearchBox()
        box.addItems(["北京", "上海"])
        box._onSearchTextChanged("上海")
        box._onSearchTextChanged("")
        view = box.view()
        assert view.isRowHidden(0) is False
        assert view.isRowHidden(1) is False
        box.deleteLater()

    def test_show_popup_resets_row_filter(self):
        """Test showPopup restores hidden rows from the previous search."""
        box = ElaSearchBox()
        box.addItems(["北京", "上海"])
        box._onSearchTextChanged("bj")
        box.showPopup()
        assert box.view().isRowHidden(1) is False
        box.hidePopup()
        box.deleteLater()

    def test_popup_creates_search_edit_and_filters(self):
        """Test the popup search edit drives the row filter."""
        box = ElaSearchBox()
        box.addItems(["北京", "上海"])
        box.showPopup()
        assert box._searchEdit is not None
        box._searchEdit.setText("bj")
        view = box.view()
        assert view.isRowHidden(0) is False
        assert view.isRowHidden(1) is True
        box.hidePopup()
        box.deleteLater()

    def test_delete_later_cleans_up_search_widget(self):
        """Test deleteLater cleans up search widget."""
        box = ElaSearchBox()
        box.addItem("test")
        box.showPopup()
        box.hidePopup()
        box.deleteLater()

    def test_set_search_visible_roundtrip(self, make):
        """Test search visibility toggle roundtrip."""
        box = make(ElaSearchBox)
        assert box.searchVisible() is True
        box.setSearchVisible(False)
        assert box.searchVisible() is False

    def test_disable_search_skips_widget(self, make, qapp):
        """Test disabled search is not created in the popup."""
        box = make(ElaSearchBox, make(QWidget))
        box.addItem("a")
        box.setSearchVisible(False)
        box.resize(240, 28)
        box.show()
        qapp.processEvents()
        box.showPopup()
        qapp.processEvents()
        assert box._searchWidget is None
        box.hidePopup()
        qapp.processEvents()


class TestComboPopupGeometry:
    """回归：动画期 view 几何必须等于动画结束后的布局终值。

    C++ ``showPopup`` 在 400ms 动画结束才 ``layout->addWidget(view())``；此前
    手工 resize 的宽度若与布局终值不一致，最后一帧滚动条会横跳、底部阴影线会
    抖（2026-10 实测 250→248）。搜索框 / 底栏的高度则通过动态属性提前让出。
    """

    _ROWS = 18

    @staticmethod
    def _make_box(make, parent, cls, title_first: bool):
        box = make(cls, "", parent) if title_first else make(cls, parent)
        box.setFixedWidth(250)
        box.addItems([f"Item {i}" for i in range(TestComboPopupGeometry._ROWS)])
        box.setMaxVisibleItems(5)
        box.show()
        QApplication.processEvents()
        return box

    @staticmethod
    def _container(box):
        container = box.findChild(QWidget, "ElaComboBoxContainer")
        assert container is not None
        return container

    @staticmethod
    def _expected_rect(box, container, top_extra: int):
        layout = container.layout()
        margins = layout.contentsMargins()
        contents = container.contentsRect()
        rows = min(box.count(), box.maxVisibleItems())
        return (
            contents.x() + margins.left(),
            contents.y() + margins.top() + top_extra,
            contents.width() - margins.left() - margins.right(),
            rows * 35,
        )

    @staticmethod
    def _view_rect(box):
        view = box.view()
        return (view.x(), view.y(), view.width(), view.height())

    @pytest.mark.parametrize(
        ("cls", "top_extra", "title_first"),
        [
            (ElaComboBox, 0, False),
            (ElaSearchBox, 40, False),
            (ElaSearchMultiBox, 40, False),
            (ElaTagBox, 0, True),
            (ElaTagMultiBox, 0, True),
            (ElaTagSearchBox, 40, True),
            (ElaTagSearchMultiBox, 40, True),
        ],
        ids=[
            "combo",
            "search",
            "search-multi",
            "tag",
            "tag-multi",
            "tag-search",
            "tag-search-multi",
        ],
    )
    def test_view_geometry_matches_final_layout(
        self, qapp, make, window_widget, cls, top_extra, title_first
    ):
        box = self._make_box(make, window_widget, cls, title_first)
        box.showPopup()
        # 动画起点必须在 processEvents 之前取（之后动画已经往前走了）。
        start_y = box.view().y()
        qapp.processEvents()

        container = self._container(box)
        expected_x, expected_y, expected_w, expected_h = self._expected_rect(
            box, container, top_extra
        )
        view = box.view()
        # 动画起点：C++ 用 listHeight - 8 作为滑动高度，y 从终值上方滑下来。
        assert start_y == expected_y - expected_h, (
            "动画起点应是布局终值上方一个 view 高度"
        )
        assert (view.x(), view.width()) == (expected_x, expected_w), (
            "动画起点宽度 / 横坐标就应是布局终值"
        )
        assert view.height() == max(expected_h, view.minimumHeight())

        final_height = expected_h + 8 + top_extra
        assert _wait_until(
            qapp,
            lambda: container.height() == final_height,
            timeout_ms=2000,
            use_qwait=True,
        ), "容器高度应包含搜索框等附件的高度"
        assert (view.x(), view.y(), view.width()) == (
            expected_x,
            expected_y,
            expected_w,
        ), "动画结束放回布局后不得跳变"
        assert view.height() == max(expected_h, view.minimumHeight())

        box.hidePopup()
        _wait_until(
            qapp,
            lambda: not container.isVisible(),
            timeout_ms=2000,
            use_qwait=True,
        )


class TestComboboxPopupBothSidesTight:
    """F3 回归：上下都放不下时压到**下方**可用空间。

    旧实现 `max_h <= 50` 时什么都不做：容器按默认（下方）位置渲染、超出屏幕
    底部被裁，列表尾部不可达。
    """

    def test_clamps_to_below_space_when_above_is_tight(self, qapp, make, monkeypatch):
        from pyqt6_ela_pro import _internal

        container = make(QWidget)
        container.show()  # isVisible 必须为真才会进入定位逻辑
        combo = MagicMock()
        combo.findChild.return_value = container
        combo.mapToGlobal.return_value = QPoint(100, 40)  # combo_top = 40
        combo.height.return_value = 30  # combo_bottom = 70
        view = MagicMock()
        view.sizeHintForRow.return_value = 35
        combo.view.return_value = view
        combo.count.return_value = 50
        combo.maxVisibleItems.return_value = 10

        screen = MagicMock()
        # QRect(0,0,800,430).bottom() == 429：上方空间 37（≤50，压不了）、
        # 下方 = 429-70-3 = 356（< final 358）→ 压到 356
        screen.availableGeometry.return_value = QRect(0, 0, 800, 430)
        monkeypatch.setattr(
            QApplication, "screenAt", staticmethod(lambda pos: screen)
        )

        _internal._adjust_combobox_popup(combo)

        assert container.minimumHeight() == container.maximumHeight() == 356
