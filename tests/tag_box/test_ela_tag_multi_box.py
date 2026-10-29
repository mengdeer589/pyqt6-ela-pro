"""``ElaTagMultiBox`` 测试：构造接线 / 展开属性 / 标题 / 弹层辅助函数。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPropertyAnimation

from pyqt6_ela_pro._motion import Duration
from pyqt6_ela_pro.ela_tag_combo_base import _get_target_mark_width, _pre_init_popup
from pyqt6_ela_pro.ela_tag_multi_box import ElaTagMultiBox


@pytest.fixture
def box(make):
    """默认构造的 tag multi box（空标题）。"""
    return make(ElaTagMultiBox)


class TestElaTagMultiBoxInit:
    def test_ctor_wiring(self, box, motion_full):
        """一次钉住构造期接线：标题 / 字号 / 展开起点 / 高度 / 动画 / 多选上限。"""
        assert box._title_text == ""
        assert box._title_font_size == 13
        assert box._expand_mark_width == 0.0
        # 与上游 ElaComboBox V3.0（35→30）的触发框同高。
        assert box.height() == 30
        assert isinstance(box._mark_animation, QPropertyAnimation)
        assert box._mark_animation.duration() == Duration.Normal
        assert box.maxVisibleItems() == 10

    def test_initialization_with_title(self, make):
        assert make(ElaTagMultiBox, title="语言")._title_text == "语言"


class TestElaTagMultiBoxExpandProperties:
    @pytest.mark.parametrize(
        ("prop", "value"),
        [("expandMarkWidth", 50.0), ("expandIconRotate", -180.0)],
        ids=["mark-width", "icon-rotate"],
    )
    def test_expand_property_roundtrip(self, box, prop, value):
        setattr(box, prop, value)
        assert getattr(box, prop) == value


class TestElaTagMultiBoxTitle:
    def test_title_roundtrip(self, box):
        box.setTitle("新标题")
        assert box.title() == "新标题"
        assert box._title_text == "新标题"


class TestElaTagMultiBoxHelpers:
    def test_get_target_mark_width_empty(self, box):
        """没有选项时标记宽度应为 0。"""
        assert _get_target_mark_width(box) == 0.0

    def test_pre_init_popup_runs_safely(self, box):
        """_pre_init_popup 必须在未创建弹层时也不报错。"""
        _pre_init_popup(box)


class TestElaTagMultiBoxSelection:
    def test_set_none_clears(self, box):
        box.addItems(["A", "B"])
        box.setCurrentSelection(["A"])
        box.setCurrentSelection(None)
        assert box.currentSelection() == []

    def test_current_selection_reads_cpp_state(self, box):
        box.addItems(["A", "B"])
        box.setCurrentSelection("B")
        assert box.currentSelection() == ["B"]

    def test_mark_width_uses_new_selection(self, box):
        """先写 C++ 选中再算标记宽度（旧实现拿旧选中算，标记宽度停在旧值）。"""
        box.addItems(["A", "B", "C", "D"])
        box.resize(240, 30)
        box.setCurrentSelection(["A", "B"])
        assert box._expand_mark_width == pytest.approx(_get_target_mark_width(box))
