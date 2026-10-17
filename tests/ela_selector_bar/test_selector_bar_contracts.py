"""``ElaSelectorBar`` 的三条状态一致性契约。

1. ``insertItem`` 存的是**传入的活对象** —— 宿主改一下就绕过了全部校验与信号
   （``items()`` / ``itemAt()`` 都给副本，唯独入口这一路是漏的）；
2. ``focusInEvent`` 直接改 ``_selected_index`` —— 不发信号、不同步
   ``items()`` 的 ``selected`` 镜像、指示器也不动，于是 ``selectedIndex()``
   说选了第 0 项、``items()`` 说一项都没选、指示器几何是空的，三者互相矛盾；
3. ``_animateIndicator`` 每次都 ``valueChanged.connect`` —— 切 N 次就有 N 个
   接收者，每帧的槽调用次数线性增长（源码第 708 行的注释只提醒了 ``finished``）。

**注意 ``_repairSelection`` 不在范围内**：它是刻意的静默修复（「把选中挪到
最近的仍可选项」，不是用户意图），实测 ``setItemEnabled(0, False)`` 不发
信号是设计而非缺陷。
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QFocusEvent

from pyqt6_ela_pro.ela_selector_bar import ElaSelectorBar, SelectorBarItem


@pytest.fixture
def bar(make):
    widget = make(ElaSelectorBar)
    for text in ("A", "B", "C", "D"):
        widget.addItem(text)
    return widget


class TestInsertItemStoresACopy:
    def test_caller_object_is_not_retained(self, bar):
        item = SelectorBarItem(text="原始")
        bar.insertItem(0, item)
        item.text = "宿主偷偷改的"
        assert bar.itemAt(0).text == "原始"

    def test_caller_cannot_bypass_enabled(self, bar):
        item = SelectorBarItem(text="X", enabled=True)
        bar.insertItem(0, item)
        item.enabled = False
        assert bar.itemAt(0).enabled is True

    def test_caller_cannot_bypass_visible(self, bar):
        item = SelectorBarItem(text="X", visible=True)
        bar.insertItem(0, item)
        item.visible = False
        assert bar.itemAt(0).visible is True

    def test_internal_selection_does_not_write_back(self, bar):
        """内部把 ``selected`` 镜像置True 不该回写宿主手上的对象。"""
        item = SelectorBarItem(text="X")
        bar.insertItem(0, item)
        bar.setSelectedIndex(0)
        assert item.selected is False

    def test_copy_carries_every_field(self, bar):
        item = SelectorBarItem(
            text="X", icon=7, enabled=False, visible=False, data={"k": 1},
            accessibleName="名字",
        )
        bar.insertItem(0, item)
        got = bar.itemAt(0)
        assert (got.text, got.icon, got.enabled, got.visible) == ("X", 7, False, False)
        assert got.data == {"k": 1}
        assert got.accessibleName == "名字"

    def test_stored_copy_is_independent_of_later_additions(self, bar):
        item = SelectorBarItem(text="X")
        bar.insertItem(0, item)
        bar.addItem("Y")
        assert bar.itemAt(0).text == "X"


class TestFocusInKeepsStateConsistent:
    """focus 落到一个「无选中」的 bar 上时会自动选一项 —— 三处状态必须同步。"""

    def test_emits_selected_index_changed(self, bar):
        bar.setSelectedIndex(0)
        bar.clearSelection()
        seen: list = []
        bar.selectedIndexChanged.connect(seen.append)
        bar.focusInEvent(QFocusEvent(QFocusEvent.Type.FocusIn))
        assert seen == [0], f"宿主没收到选中变化，实际 {seen}"

    def test_items_mirror_matches_selected_index(self, bar):
        bar.clearSelection()
        bar.focusInEvent(QFocusEvent(QFocusEvent.Type.FocusIn))
        selected = bar.selectedIndex()
        mirror = [i.selected for i in bar.items()]
        assert selected >= 0
        assert mirror[selected] is True, f"selectedIndex={selected} 但镜像 {mirror}"
        assert sum(mirror) == 1, f"镜像应恰有一项为真，实际 {mirror}"

    def test_indicator_moves_to_the_new_selection(self, bar):
        bar.clearSelection()
        bar.focusInEvent(QFocusEvent(QFocusEvent.Type.FocusIn))
        assert not bar.indicatorGeometry().isEmpty(), "指示器没落到选中项上"

    def test_skips_unselectable_items(self, bar):
        bar.setItemEnabled(0, False)
        bar.setItemVisible(1, False)
        bar.clearSelection()
        seen: list = []
        bar.selectedIndexChanged.connect(seen.append)
        bar.focusInEvent(QFocusEvent(QFocusEvent.Type.FocusIn))
        assert seen == [2], f"应跳过 0/1 选到 2，实际 {seen}"

    def test_all_unselectable_leaves_no_selection(self, bar):
        for i in range(bar.itemCount()):
            bar.setItemEnabled(i, False)
        bar.focusInEvent(QFocusEvent(QFocusEvent.Type.FocusIn))
        assert bar.selectedIndex() == -1
        assert not any(i.selected for i in bar.items())

    def test_selectable_selection_is_left_alone(self, bar):
        bar.setSelectedIndex(1)
        seen: list = []
        bar.selectedIndexChanged.connect(seen.append)
        bar.focusInEvent(QFocusEvent(QFocusEvent.Type.FocusIn))
        assert bar.selectedIndex() == 1
        assert seen == [], "已有合法选中时不该再发一次"

    def test_runs_without_items(self, make):
        empty = make(ElaSelectorBar)
        empty.focusInEvent(QFocusEvent(QFocusEvent.Type.FocusIn))
        assert empty.selectedIndex() == -1


class TestRepairSelectionKeepsMirrorConsistent:
    """``setItemEnabled`` / ``setItemVisible`` 触发 ``_repairSelection`` 时镜像必须同步。

    原先两个 setter 都先把 ``_selected_index`` 置 -1 再调 ``_repairSelection``，
    而后者末段有 ``if target == self._selected_index: return`` —— 「一个可选
    项都不剩」时 target 也是 -1，于是直接 return，**镜像永远留着上一项的
    True**，与 ``selectedIndex() == -1`` 互相矛盾（实测：逐项禁用到最后一项）。
    """

    def test_disabling_every_item_clears_mirror(self, bar):
        for index in range(bar.itemCount()):
            bar.setItemEnabled(index, False)
        assert bar.selectedIndex() == -1
        assert not any(i.selected for i in bar.items()), (
            f"selectedIndex() 已是 -1，但 items() 镜像 {bar.items()}"
        )

    def test_disabling_last_item_clears_mirror(self, make):
        """只剩一项时禁掉它 -> 应落到「无选中」且镜像清空。"""
        bar = make(ElaSelectorBar)
        bar.addItem("only")
        assert bar.selectedIndex() == 0
        bar.setItemEnabled(0, False)
        assert bar.selectedIndex() == -1
        assert not any(i.selected for i in bar.items())

    def test_disabling_last_of_many_falls_back(self, bar):
        """还有别的可选项时应回落到最近的一项（不是 -1）。"""
        last = bar.itemCount() - 1
        bar.setSelectedIndex(last)
        bar.setItemEnabled(last, False)
        assert bar.selectedIndex() == last - 1
        mirror = [i.selected for i in bar.items()]
        assert mirror[last - 1] and sum(mirror) == 1

    def test_hiding_every_item_clears_mirror(self, bar):
        for index in range(bar.itemCount()):
            bar.setItemVisible(index, False)
        assert bar.selectedIndex() == -1
        assert not any(i.selected for i in bar.items())

    def test_falling_back_still_sets_the_new_mirror(self, bar):
        bar.setSelectedIndex(0)
        bar.setItemEnabled(0, False)
        assert bar.selectedIndex() == 1
        mirror = [i.selected for i in bar.items()]
        assert mirror == [False, True, False, False]

    def test_mirror_and_index_agree_through_a_sweep(self, bar):
        for index in range(bar.itemCount()):
            bar.setSelectedIndex(index)
            bar.setItemEnabled(index, False)
            selected = bar.selectedIndex()
            mirror = [i.selected for i in bar.items()]
            if selected < 0:
                assert not any(mirror), f"index=-1 但镜像 {mirror}"
            else:
                assert mirror[selected] and sum(mirror) == 1, (
                    f"index={selected} 但镜像 {mirror}"
                )


class TestIndicatorValueChangedConnectedOnce:
    def test_receiver_count_stays_at_one(self, bar, monkeypatch):
        """每切一次不得叠一个 ``valueChanged`` 接收者。

        ``QObject.receivers()`` 在 PyQt6 下对所有信号都不可用（见 MIGRATION），
        改为**数处理函数实际被调用的次数** —— 槽虽幂等，但叠连接会让次数线性增长。
        """
        bar.show()
        anim = bar._indicator_anim
        calls: list = []
        monkeypatch.setattr(bar, "_setIndicatorRect", lambda *a, **k: calls.append(1))

        per_frame = []
        for index in range(1, bar.itemCount()):  # 0 号已是选中项，不会起动画
            bar.setSelectedIndex(index)
            before = len(calls)
            anim.setCurrentTime(anim.duration())
            per_frame.append(len(calls) - before)

        assert per_frame == [1] * (bar.itemCount() - 1), (
            f"每帧处理次数应恒为 1，实为 {per_frame}"
        )

    def test_connect_is_not_in_the_animate_helper(self):
        import inspect

        src = inspect.getsource(ElaSelectorBar._animateIndicator)
        assert "valueChanged.connect" not in src, (
            "连接必须放在 __init__，不能放在每次动画都跑的 _animateIndicator 里"
        )

    def test_indicator_still_animates(self, bar):
        """连接搬走不等于动画不响应（回归：槽没接上会静默不动）。"""
        bar.show()
        bar.setSelectedIndex(0)
        anim = bar._indicator_anim
        for _ in range(40):
            anim.setCurrentTime(anim.duration())
        bar.setSelectedIndex(3)
        for _ in range(40):
            anim.setCurrentTime(anim.duration())
        expected = bar.selectedIndicatorGeometry(3)
        assert not expected.isEmpty()
        assert bar.indicatorGeometry() == expected