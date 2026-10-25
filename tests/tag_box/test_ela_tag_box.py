"""``ElaTagBox`` 测试：构造接线 / 展开属性 / 标题 / 析构。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPropertyAnimation

from pyqt6_ela_pro._motion import Duration
from pyqt6_ela_pro.ela_tag_box import ElaTagBox


@pytest.fixture
def box(make):
    """默认构造的 tag box（空标题）。"""
    return make(ElaTagBox)


class TestElaTagBoxInit:
    def test_ctor_wiring(self, box, motion_full):
        """一次钉住构造期全部接线：标题初值 / 字号 / 展开起点 / 高度 / 动画。"""
        assert box._title_text == ""
        assert box._title_font_size == 13
        assert box._expand_mark_width == 0.0
        assert box._expand_icon_rotate == 0.0
        # 与上游 ElaComboBox V3.0（35→30）的触发框同高。
        assert box.height() == 30
        for attr in ("_mark_animation", "_rotate_animation"):
            anim = getattr(box, attr)
            assert isinstance(anim, QPropertyAnimation)
            assert anim.duration() == Duration.Normal

    def test_initialization_with_title(self, make):
        assert make(ElaTagBox, title="语言")._title_text == "语言"


class TestElaTagBoxExpandProperties:
    @pytest.mark.parametrize(
        ("prop", "value"),
        [
            ("expandMarkWidth", 50.0),
            ("expandMarkWidth", 0.0),
            ("expandIconRotate", -180.0),
            ("expandIconRotate", 0.0),
        ],
        ids=["mark-width-50", "mark-width-0", "icon-rotate-minus180", "icon-rotate-0"],
    )
    def test_expand_property_roundtrip(self, box, prop, value):
        setattr(box, prop, value)
        assert getattr(box, prop) == value


class TestElaTagBoxTitle:
    def test_title_roundtrip(self, box):
        box.setTitle("新标题")
        assert box.title() == "新标题"
        assert box._title_text == "新标题"


class TestElaTagBoxDeleteLater:
    """析构路径本身就是被测行为：动画的 ``finished`` 信号与
    ``currentIndexChanged`` 在析构时要被解绑，漏解绑会抛 ``TypeError``。"""

    def test_delete_later_cleans_up(self, box):
        box.deleteLater()

    def test_delete_later_disconnects_index_changed(self, make):
        make(ElaTagBox, title="test").deleteLater()
