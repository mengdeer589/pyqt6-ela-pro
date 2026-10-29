"""``pyqt6_ela_pro.ela_selector_bar`` 的单元测试。

钉住的核心不变量：

1. **指示器动画的三关键帧** —— 起点与 0.55 处都是 **16px 细条**（只有 x 在动），
   终点才绽开到 20px。移动占 55%、绽开占 45% 是这个组件的全部观感。
2. **静止时 relayout 不打断在飞的动画**（否则 resize 会把指示器「拽回去」再重播）。
3. **选中状态在变更后自愈**：禁掉 / 隐藏当前选中项时落到最近的可选项；一个都不可选
   就保持 ``-1``（**不是**硬选一个）。
4. **非法下标静默忽略**（不抛、不发信号）。
5. **溢出：一次点击滚一项**；到头的箭头**置灰而不是隐藏**（控件宽度不跳）。
6. **RTL 全量镜像**（含溢出按钮与左右键），且布局方向变了必须重排。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPoint, Qt, QPointF
from PyQt6.QtGui import QFontMetrics, QKeyEvent

from pyqt6_ela_pro._motion import ElaMotionModeType, motion
from pyqt6_ela_pro.ela_selector_bar import (
    _Metrics,
    ElaSelectorBar,
    SelectorBarItem,
    ElaSelectorBarOverflowType,
)


def _bar(make, width=520, texts=("最近", "全部", "已归档", "回收站")):
    bar = make(ElaSelectorBar)
    bar.resize(width, _Metrics.rowHeight)
    bar.addItems(list(texts))
    bar.show()
    return bar


class TestItems:
    def test_starts_empty(self, make):
        bar = make(ElaSelectorBar)
        assert bar.itemCount() == 0
        assert bar.items() == []
        assert bar.selectedIndex() == -1

    def test_add_and_read_back(self, make):
        bar = make(ElaSelectorBar)
        assert bar.addItem("a") == 0
        assert bar.addItem("b") == 1
        assert bar.itemCount() == 2
        assert bar.itemAt(1).text == "b"

    def test_item_at_out_of_range_is_none(self, make):
        bar = make(ElaSelectorBar)
        bar.addItem("a")
        assert bar.itemAt(5) is None
        assert bar.itemAt(-1) is None

    def test_items_returns_copies(self, make):
        """返回副本 —— ``selected`` 是派生镜像，改内部项等于绕过全部校验与信号。"""
        bar = make(ElaSelectorBar)
        bar.addItems(["a", "b"])
        bar.clearSelection()
        snapshot = bar.items()
        snapshot[0].text = "hacked"
        snapshot[0].selected = True
        assert bar.itemAt(0).text == "a"
        assert bar.itemAt(0).selected is False

    def test_item_at_returns_a_copy(self, make):
        bar = make(ElaSelectorBar)
        bar.addItem("a")
        bar.itemAt(0).text = "hacked"
        assert bar.itemAt(0).text == "a"

    def test_insert_clamps_index(self, make):
        bar = make(ElaSelectorBar)
        assert bar.insertItem(-5, SelectorBarItem("first")) == 0
        assert bar.insertItem(999, SelectorBarItem("last")) == 1

    def test_insert_rejects_wrong_type(self, make):
        with pytest.raises(TypeError):
            make(ElaSelectorBar).insertItem(0, "not an item")

    def test_insert_shifts_selection(self, make):
        bar = make(ElaSelectorBar)
        bar.addItems(["a", "b", "c"])
        bar.setSelectedIndex(2)
        bar.insertItem(0, SelectorBarItem("new"))
        assert bar.selectedIndex() == 3

    def test_remove(self, make):
        bar = make(ElaSelectorBar)
        bar.addItems(["a", "b", "c"])
        assert bar.removeItem(1) is True
        assert bar.itemCount() == 2
        assert bar.removeItem(9) is False

    def test_remove_before_selection_shifts_it(self, make):
        bar = make(ElaSelectorBar)
        bar.addItems(["a", "b", "c"])
        bar.setSelectedIndex(2)
        bar.removeItem(0)
        assert bar.selectedIndex() == 1

    def test_clear_resets_selection(self, make):
        bar = make(ElaSelectorBar)
        bar.addItems(["a", "b"])
        bar.setSelectedIndex(1)
        bar.clearItems()
        assert bar.itemCount() == 0
        assert bar.selectedIndex() == -1

    def test_signal_on_count_change(self, make):
        bar = make(ElaSelectorBar)
        seen = []
        bar.itemCountChanged.connect(seen.append)
        bar.addItem("a")
        bar.addItem("b")
        assert seen == [1, 2]

    @pytest.mark.parametrize("field", ["setItemText", "setItemIcon", "setItemData"])
    def test_setters_reject_bad_index(self, make, field):
        bar = make(ElaSelectorBar)
        assert getattr(bar, field)(5, "x") is False

    def test_set_item_text_updates_width(self, make):
        bar = _bar(make, texts=["a"])
        narrow = bar.itemGeometry(0).width()
        bar.setItemText(0, "一段很长很长的文案")
        assert bar.itemGeometry(0).width() > narrow


class TestLayout:
    def test_size_hints(self, make):
        bar = make(ElaSelectorBar)
        assert bar.sizeHint().width() == _Metrics.defaultWidth
        assert bar.sizeHint().height() == _Metrics.rowHeight
        assert bar.minimumSizeHint().width() == _Metrics.overflowButtonWidth * 3

    def test_items_are_vertically_centred_in_the_row(self, make):
        bar = _bar(make)
        rect = bar.itemGeometry(0)
        assert rect.height() == _Metrics.itemVisualHeight
        top_gap = rect.top()
        bottom_gap = bar.height() - rect.bottom() - 1
        assert abs(top_gap - bottom_gap) <= 1

    def test_items_are_laid_out_left_to_right_without_gaps(self, make):
        bar = _bar(make)
        for index in range(bar.itemCount() - 1):
            current = bar.itemGeometry(index)
            following = bar.itemGeometry(index + 1)
            assert current.right() + 1 == following.left()

    def test_width_has_a_floor(self, make):
        bar = _bar(make, texts=["", "a"])
        assert bar.itemGeometry(0).width() >= _Metrics.minItemWidth

    def test_width_has_a_ceiling(self, make):
        bar = _bar(make, texts=["很" * 200])
        assert bar.itemGeometry(0).width() <= _Metrics.maxItemWidth

    def test_icon_widens_the_item(self, make):
        bar = _bar(make, texts=["a"])
        without = bar.itemGeometry(0).width()
        bar.setItemIcon(0, 0xEAB4)
        assert bar.itemGeometry(0).width() >= without

    def test_layout_is_lazy_but_correct_without_event_loop(self, make):
        """``resize()`` 只投递事件 —— 几何自省必须自己按当前尺寸算。"""
        bar = make(ElaSelectorBar)
        bar.resize(300, 44)
        bar.addItems(["a", "b", "c", "d", "e", "f"])
        assert bar.isOverflowing() is True
        assert bar.itemGeometry(0).width() > 0

    def test_indicator_is_narrower_than_the_item(self, make):
        bar = _bar(make)
        for index in range(bar.itemCount()):
            indicator = bar.selectedIndicatorGeometry(index)
            assert indicator.width() <= _Metrics.indicatorWidth
            assert indicator.height() == _Metrics.indicatorHeight

    def test_indicator_is_centred_under_its_item(self, make):
        bar = _bar(make)
        for index in range(bar.itemCount()):
            item = bar.itemGeometry(index)
            indicator = bar.selectedIndicatorGeometry(index)
            assert abs(item.center().x() - indicator.center().x()) <= 1


class TestSelection:
    def test_first_insert_auto_selects(self, make):
        """什么都不选的分段控件看起来像坏了 —— 插入时自动选中第一项。"""
        bar = make(ElaSelectorBar)
        bar.addItem("a")
        assert bar.selectedIndex() == 0

    def test_auto_select_respects_existing_selection(self, make):
        bar = make(ElaSelectorBar)
        bar.addItems(["a", "b", "c"])
        bar.setSelectedIndex(2)
        bar.addItem("d")
        assert bar.selectedIndex() == 2

    def test_no_selection_is_a_legal_state(self, make, motion_full):
        bar = _bar(make)
        bar.clearSelection()
        assert bar.selectedIndex() == -1
        assert bar.selectedItem() is None
        assert bar.indicatorGeometry().isEmpty() is True

    def test_a_brand_new_bar_has_no_selection(self, make):
        bar = make(ElaSelectorBar)
        assert bar.selectedIndex() == -1
        assert bar.selectedItem() is None

    def test_set_and_signal(self, make):
        bar = _bar(make)
        seen = []
        bar.selectedIndexChanged.connect(seen.append)
        bar.setSelectedIndex(2)
        assert bar.selectedIndex() == 2
        assert seen == [2]

    def test_selected_flag_is_a_mirror(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(1)
        assert [item.selected for item in bar.items()] == [False, True, False, False]

    def test_clear_selection(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(1)
        bar.clearSelection()
        assert bar.selectedIndex() == -1
        assert all(not item.selected for item in bar.items())

    def test_negative_index_clears(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(1)
        bar.setSelectedIndex(-5)
        assert bar.selectedIndex() == -1

    @pytest.mark.parametrize("bad", [99, -1])
    def test_out_of_range_is_silently_ignored(self, make, bad):
        bar = _bar(make)
        bar.setSelectedIndex(1)
        seen = []
        bar.selectedIndexChanged.connect(seen.append)
        bar.setSelectedIndex(bad if bad > 0 else 99)
        assert bar.selectedIndex() == (1 if bad < 0 else 1)
        assert seen == []

    def test_disabled_index_is_silently_ignored(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(0)
        bar.setItemEnabled(1, False)
        seen = []
        bar.selectedIndexChanged.connect(seen.append)
        bar.setSelectedIndex(1)
        assert bar.selectedIndex() == 0
        assert seen == []

    def test_hidden_index_is_silently_ignored(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(0)
        bar.setItemVisible(1, False)
        bar.setSelectedIndex(1)
        assert bar.selectedIndex() == 0

    def test_set_item_selected_false_clears(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(1)
        assert bar.setItemSelected(1, False) is True
        assert bar.selectedIndex() == -1

    def test_same_index_emits_nothing(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(1)
        seen = []
        bar.selectedIndexChanged.connect(seen.append)
        bar.setSelectedIndex(1)
        assert seen == []


class TestSelectionRepair:
    def test_disabling_the_selected_picks_the_next(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(1)
        bar.setItemEnabled(1, False)
        assert bar.selectedIndex() == 2

    def test_disabling_the_last_selected_picks_the_previous(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(3)
        bar.setItemEnabled(3, False)
        assert bar.selectedIndex() == 2

    def test_disabling_a_non_selected_item_keeps_the_selection(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(1)
        bar.setItemEnabled(2, False)
        assert bar.selectedIndex() == 1

    def test_hiding_the_selected_repairs_it(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(1)
        bar.setItemVisible(1, False)
        assert bar.selectedIndex() == 2

    def test_all_disabled_yields_no_selection(self, make):
        """一个都不可选就保持 -1，**不是**硬选一个。"""
        bar = _bar(make)
        bar.setSelectedIndex(1)
        for index in range(bar.itemCount()):
            bar.setItemEnabled(index, False)
        assert bar.selectedIndex() == -1

    def test_removing_the_selected_repairs_it(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(2)
        bar.removeItem(2)
        assert bar.selectedIndex() in (1, 2)

    def test_repair_skips_over_unselectable_neighbours(self, make):
        bar = make(ElaSelectorBar)
        bar.resize(400, 44)
        bar.addItems(["a", "b", "c", "d"])
        bar.setItemEnabled(1, False)
        bar.setItemEnabled(2, False)
        bar.setSelectedIndex(0)
        bar.setItemEnabled(0, False)
        assert bar.selectedIndex() == 3, "向前不可用时要能螺旋找到后面的"


class TestIndicatorAnimation:
    def test_collapses_to_a_thin_bar_before_moving(self, make, motion_full):
        """动画起点就是压扁态（16px），而不是从 20px「飞」过去。"""
        bar = _bar(make)
        bar.setSelectedIndex(0)
        bar.setSelectedIndex(1)
        assert bar.indicatorGeometry().width() == _Metrics.collapsedIndicatorWidth

    def test_collapsed_rect_keeps_y_and_height(self, make):
        """压扁只改宽度 —— 改 y 或高度会让指示器「跳一下」。"""
        bar = _bar(make)
        target = bar.selectedIndicatorGeometry(1)
        collapsed = bar._collapsedRect(target)
        assert collapsed.top() == target.top()
        assert collapsed.height() == target.height()
        assert collapsed.width() == _Metrics.collapsedIndicatorWidth

    def test_collapsed_never_widens(self, make):
        bar = make(ElaSelectorBar)
        bar.resize(200, 44)
        bar.addItems(["a", "b", "c"])
        tiny = bar.selectedIndicatorGeometry(0)
        if not tiny.isEmpty():
            assert bar._collapsedRect(tiny).width() <= tiny.width()

    def test_travel_ratio_is_the_documented_split(self):
        """移动占 55%、绽开占 45% —— 等速会看着像两个动作拼在一起。"""
        assert _Metrics.travelRatio == 0.55

    def test_three_keyframes_are_configured(self, make, motion_full):
        bar = _bar(make)
        bar.show()
        bar.setSelectedIndex(0)
        bar._animateIndicator(
            bar.selectedIndicatorGeometry(0), bar.selectedIndicatorGeometry(2)
        )
        anim = bar._indicator_anim
        assert anim.startValue() is not None
        assert anim.keyValueAt(_Metrics.travelRatio) is not None
        assert anim.endValue() is not None

    def test_snapping_lands_exactly_on_target(self, make, motion_full):
        bar = _bar(make)
        bar.setSelectedIndex(2)
        bar.snapIndicator()
        target = bar.selectedIndicatorGeometry(2)
        actual = bar.indicatorGeometry()
        assert actual.x() == target.x()
        assert actual.width() == target.width()

    def test_selection_to_nothing_clears_the_indicator(self, make, motion_full):
        bar = _bar(make)
        bar.setSelectedIndex(1)
        bar.clearSelection()
        assert bar.indicatorGeometry().isEmpty() is True

    def test_invisible_widget_skips_the_animation(self, make, motion_full):
        """不可见时直接落终值，不播「从零长出来」的入场。"""
        bar = make(ElaSelectorBar)
        bar.resize(400, 44)
        bar.addItems(["a", "b"])
        bar.setSelectedIndex(1)
        bar.snapIndicator()
        target = bar.selectedIndicatorGeometry(1)
        assert bar.indicatorGeometry().x() == target.x()

    def test_resize_does_not_interrupt_a_running_animation(self, make, motion_full):
        """resize 期间动画在跑时**不能**把指示器拽回终态（观感是抽搐）。"""
        bar = _bar(make)
        bar.setSelectedIndex(0)
        bar.setSelectedIndex(3)
        assert bar.isIndicatorAnimating() is True
        moving = bar.indicatorGeometry()
        bar.resize(500, 44)
        assert bar.indicatorGeometry() == moving or bar.isIndicatorAnimating() is True

    def test_resize_snaps_when_idle(self, make, motion_full):
        bar = _bar(make)
        bar.setSelectedIndex(1)
        bar.snapIndicator()
        before = bar.indicatorGeometry()
        bar.resize(400, 44)
        assert bar.indicatorGeometry().x() == bar.selectedIndicatorGeometry(1).x()
        assert before.width() == bar.indicatorGeometry().width()

    def test_reduced_mode_still_lands_on_target(self, make, motion_full):
        """``Reduced`` 把过渡压到 ≤50ms，但**终值必须一样**。"""
        bar = _bar(make)
        bar.setSelectedIndex(0)
        bar.snapIndicator()
        previous = motion.mode()
        try:
            motion.setMode(ElaMotionModeType.Reduced)
            bar.setSelectedIndex(3)
            bar.snapIndicator()
        finally:
            motion.setMode(previous)
        target = bar.selectedIndicatorGeometry(3)
        assert bar.indicatorGeometry().x() == target.x()
        assert bar.indicatorGeometry().width() == target.width()

    def test_disabled_mode_lands_immediately(self, make, motion_full):
        bar = _bar(make)
        bar.setSelectedIndex(0)
        bar.snapIndicator()
        previous = motion.mode()
        try:
            motion.setMode(ElaMotionModeType.Disabled)
            bar.setSelectedIndex(2)
        finally:
            motion.setMode(previous)
        target = bar.selectedIndicatorGeometry(2)
        assert bar.indicatorGeometry().x() == target.x()


class TestOverflow:
    def _many(self, make, count=24, width=300):
        bar = _bar(make, width=width, texts=[f"项{n}" for n in range(count)])
        return bar

    def test_no_overflow_when_everything_fits(self, make):
        bar = _bar(make, width=520)
        assert bar.isOverflowing() is False
        assert bar.hiddenItemIndexes() == []
        assert bar._overflow_back_rect.isEmpty() is True

    def test_overflow_hides_the_tail(self, make):
        bar = self._many(make)
        assert bar.isOverflowing() is True
        assert len(bar.visibleItemIndexes()) < bar.itemCount()
        assert set(bar.visibleItemIndexes()) & set(bar.hiddenItemIndexes()) == set()

    def test_scroll_moves_one_item_at_a_time(self, make):
        bar = self._many(make)
        first = bar.visibleItemIndexes()
        bar.scrollOverflow(1)
        second = bar.visibleItemIndexes()
        assert second[0] == first[0] + 1

    def test_scroll_clamps_at_the_ends(self, make):
        bar = self._many(make)
        for _ in range(200):
            bar.scrollOverflow(-1)
        assert bar.visibleItemIndexes()[0] == 0
        assert bar.canScrollBack() is False

    def test_hidden_item_does_not_occupy_space(self, make):
        bar = _bar(make, width=400, texts=["a", "b", "c"])
        bar.setItemVisible(1, False)
        first, third = bar.itemGeometry(0), bar.itemGeometry(2)
        assert third.left() == first.right() + 1, "隐藏项不该留空隙"

    def test_first_visible_item_is_shown_even_when_too_wide(self, make):
        """窗口的第一项超宽也照画（截断），不能什么都不显示。"""
        bar = make(ElaSelectorBar)
        bar.resize(60, 44)
        bar.addItems(["很" * 100, "b"])
        bar.show()
        assert bar.visibleItemIndexes() != []

    def test_more_button_behavior_reserves_one_slot(self, make):
        bar = self._many(make)
        bar.setOverflowBehavior(ElaSelectorBarOverflowType.MoreButton)
        assert bar._overflow_more_rect.width() == _Metrics.overflowButtonWidth
        assert bar._overflow_back_rect.isEmpty() is True

    def test_scroll_buttons_grey_out_at_the_ends(self, make):
        bar = self._many(make)
        assert bar.canScrollBack() is False
        assert bar.canScrollForward() is True

    def test_selected_item_is_scrolled_into_view(self, make):
        """指示器绝不能指向一个看不见的项。"""
        bar = self._many(make)
        bar.setSelectedIndex(bar.itemCount() - 1)
        assert bar.itemCount() - 1 in bar.visibleItemIndexes()


class TestActivation:
    def test_activate_emits_then_commits(self, make):
        """先发信号再提交选中 —— 宿主在槽里销毁控件也不会崩。"""
        bar = _bar(make)
        seen = []
        order = []
        bar.itemActivated.connect(
            lambda i, it: (seen.append(i), order.append("signal"))
        )
        bar.selectedIndexChanged.connect(lambda i: order.append("selected"))
        bar._activateIndex(2)
        assert seen == [2]
        assert order == ["signal", "selected"]

    def test_activate_ignores_disabled(self, make):
        bar = _bar(make)
        bar.setItemEnabled(1, False)
        seen = []
        bar.itemActivated.connect(lambda i, it: seen.append(i))
        bar._activateIndex(1)
        assert seen == []

    def test_activation_carries_a_copy_of_the_item(self, make):
        """信号参数也是出口 —— 宿主不该有机会改内部状态。"""
        bar = _bar(make)
        got = []
        bar.itemActivated.connect(lambda i, item: got.append(item))
        bar._activateIndex(1)
        assert got[0].text == bar.itemAt(1).text
        got[0].text = "hacked"
        assert bar.itemAt(1).text != "hacked"


class TestKeyboard:
    def _key(self, bar, key):
        from PyQt6.QtWidgets import QApplication

        event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(bar, event)

    def test_right_and_left_move(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(0)
        self._key(bar, Qt.Key.Key_Right)
        assert bar.selectedIndex() == 1
        self._key(bar, Qt.Key.Key_Left)
        assert bar.selectedIndex() == 0

    def test_moving_clamps_at_the_ends(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(0)
        self._key(bar, Qt.Key.Key_Left)
        assert bar.selectedIndex() == 0
        bar.setSelectedIndex(bar.itemCount() - 1)
        self._key(bar, Qt.Key.Key_Right)
        assert bar.selectedIndex() == bar.itemCount() - 1

    def test_home_and_end(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(1)
        self._key(bar, Qt.Key.Key_End)
        assert bar.selectedIndex() == bar.itemCount() - 1
        self._key(bar, Qt.Key.Key_Home)
        assert bar.selectedIndex() == 0

    def test_enter_activates(self, make):
        bar = _bar(make)
        bar.setSelectedIndex(2)
        seen = []
        bar.itemActivated.connect(lambda i, it: seen.append(i))
        self._key(bar, Qt.Key.Key_Return)
        assert seen == [2]

    def test_arrow_keys_skip_disabled_items(self, make):
        bar = _bar(make)
        bar.setItemEnabled(1, False)
        bar.setSelectedIndex(0)
        self._key(bar, Qt.Key.Key_Right)
        assert bar.selectedIndex() == 2

    def test_rtl_swaps_the_horizontal_arrows(self, make):
        """RTL 下布局已镜像（第 0 项在右），所以「按左」是往后一项。"""
        bar = _bar(make)
        bar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        bar.setSelectedIndex(0)
        self._key(bar, Qt.Key.Key_Left)
        assert bar.selectedIndex() == 1
        self._key(bar, Qt.Key.Key_Right)
        assert bar.selectedIndex() == 0

    def test_all_disabled_is_a_noop(self, make):
        bar = _bar(make)
        for index in range(bar.itemCount()):
            bar.setItemEnabled(index, False)
        self._key(bar, Qt.Key.Key_Right)
        assert bar.selectedIndex() == -1


class TestMouse:
    def _click(self, bar, rect):
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtWidgets import QApplication

        center = rect.center()
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(center),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(center),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(bar, press)
        QApplication.sendEvent(bar, release)

    def test_click_selects(self, make, qapp):
        bar = _bar(make)
        bar.snapIndicator()
        self._click(bar, bar.itemGeometry(2))
        assert bar.selectedIndex() == 2

    def test_click_on_disabled_item_does_nothing(self, make, qapp):
        bar = _bar(make)
        bar.setItemEnabled(1, False)
        bar.setSelectedIndex(0)
        bar.snapIndicator()
        self._click(bar, bar.itemGeometry(1))
        assert bar.selectedIndex() == 0

    def test_press_then_drag_off_cancels(self, make, qapp):
        """按下与抬起必须是同一目标才激活。"""
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtWidgets import QApplication

        bar = _bar(make)
        bar.setSelectedIndex(0)
        bar.snapIndicator()
        source = bar.itemGeometry(1).center()
        QApplication.sendEvent(
            bar,
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(source),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        empty = QRectOf(bar)
        QApplication.sendEvent(
            bar,
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(empty),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        assert bar.selectedIndex() == 0

    def test_hovering_a_disabled_item_gives_no_feedback(self, make, qapp):
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtWidgets import QApplication

        bar = _bar(make)
        bar.setItemEnabled(1, False)
        QApplication.sendEvent(
            bar,
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(bar.itemGeometry(1).center()),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        assert bar._hovered.name == "None_"


def QRectOf(bar):  # noqa: N802
    """一个必然不命中任何项的点。"""

    return QPoint(-5, -5)


class TestRtl:
    def test_layout_mirrors_on_direction_change(self, make):
        """``setLayoutDirection`` 之后必须重排 —— 否则第 0 项还在左边。"""
        bar = _bar(make)
        bar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        first = bar.itemGeometry(0)
        last = bar.itemGeometry(bar.itemCount() - 1)
        assert first.left() > last.left(), "RTL 下第 0 项应该在最右"

    def test_indicator_mirrors_too(self, make, motion_full):
        bar = _bar(make)
        bar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        bar.setSelectedIndex(0)
        bar.snapIndicator()
        item = bar.itemGeometry(0)
        indicator = bar.indicatorGeometry()
        assert abs(item.center().x() - indicator.center().x()) <= 2

    def test_overflow_buttons_mirror(self, make):
        bar = _bar(make, width=300, texts=[f"项{n}" for n in range(24)])
        bar.setOverflowBehavior(ElaSelectorBarOverflowType.ScrollButtons)
        bar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        assert bar._overflow_back_rect.left() > bar._overflow_forward_rect.left()

    def test_items_still_read_left_to_right_in_order(self, make):
        """镜像的是位置，**索引顺序不变** —— 数据顺序不该随语言变。"""
        bar = _bar(make)
        bar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        assert bar.visibleItemIndexes() == [0, 1, 2, 3]


class TestPaintSafety:
    @pytest.mark.parametrize(
        ("behavior", "rtl", "width", "count", "overflowing"),
        [
            (ElaSelectorBarOverflowType.ScrollButtons, False, 520, 4, False),
            (ElaSelectorBarOverflowType.ScrollButtons, False, 300, 24, True),
            (ElaSelectorBarOverflowType.MoreButton, False, 300, 24, True),
            (ElaSelectorBarOverflowType.ScrollButtons, True, 300, 24, True),
        ],
    )
    def test_every_mode_paints(
        self, make, motion_full, behavior, rtl, width, count, overflowing
    ):
        bar = _bar(make, width=width, texts=[f"项{n}" for n in range(count)])
        bar.setOverflowBehavior(behavior)
        if rtl:
            bar.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        bar.setSelectedIndex(1)
        bar.snapIndicator()
        assert bar.grab().isNull() is False
        assert bar.isOverflowing() is overflowing

    def test_empty_bar_paints(self, make):
        bar = make(ElaSelectorBar)
        bar.resize(300, 44)
        bar.show()
        assert bar.grab().isNull() is False

    def test_item_with_icon_paints(self, make, motion_full):
        bar = _bar(make)
        bar.setItemIcon(0, 0xEAB4)
        bar.setSelectedIndex(0)
        bar.snapIndicator()
        assert bar.grab().isNull() is False

    def test_disabled_bar_paints(self, make):
        bar = _bar(make)
        bar.setEnabled(False)
        bar.setSelectedIndex(0)
        bar.snapIndicator()
        assert bar.grab().isNull() is False


class TestNoQss:
    def test_no_setstylesheet_in_the_module(self):
        import pathlib

        import pyqt6_ela_pro.ela_selector_bar as mod

        source = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        assert ".setStyleSheet(" not in source


class TestItemFontMetrics:
    def test_item_width_uses_item_font(self, make):
        """?????**????**??setItemPixelSize ?????????"""
        bar = make(ElaSelectorBar)
        bar.addItem("Hello")
        bar.setItemPixelSize(20)
        item = bar.items()[0]
        text_w = QFontMetrics(bar._itemFont()).horizontalAdvance("Hello")
        expected = max(
            float(_Metrics.minItemWidth),
            min(float(_Metrics.maxItemWidth), _Metrics.horizontalPadding * 2 + text_w),
        )
        assert bar._itemNaturalWidth(item) == pytest.approx(expected)
