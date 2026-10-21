"""空多选下拉框绘制不许泄漏 ``QPainter`` 状态（回归 + 上游修复守卫）。

上游 ``ElaMultiSelectComboBox::paintEvent`` 曾把 ``painter.save()`` 写在函数级、
``painter.restore()`` 塞进 ``if (count() > 0)`` —— **空框**绘制时漏 restore，
``QPainter`` 析构即打印 ``QPainter::end: Painter ended with 1 saved states``
（示例「下拉框组件」页滚到底部那几行）。

修复落在 **C++ 侧**（``ElaMultiSelectComboBox.cpp``：``restore()`` 移出 ``if``，
子模块提交 ``c0386b7``）→ 重编 ``pyqt6-elawidgettools`` 轮子。所以本文件同时守住：

* 本库的多选子类（``ElaSearchMultiBox`` / ``ElaTagSearchMultiBox`` / ``ElaTagMultiBox``）；
* **裸用的上游 ``ElaMultiSelectComboBox``** —— 它一旦又告警，说明装到的是**旧轮子**
  （重编前的产物），而不是代码回归。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, qInstallMessageHandler
from PyQt6.QtGui import QPixmap, QRegion
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import ElaMultiSelectComboBox

from pyqt6_ela_pro.combo_box import ElaSearchMultiBox
from pyqt6_ela_pro.ela_tag_multi_box import ElaTagMultiBox
from pyqt6_ela_pro.ela_tag_search_multi_box import ElaTagSearchMultiBox

#: 只画控件自身（不带子控件），把告警归因到具体控件的绘制
_SELF_ONLY = QWidget.RenderFlag.DrawWindowBackground

_FACTORIES = [ElaSearchMultiBox, ElaTagSearchMultiBox, ElaTagMultiBox, ElaMultiSelectComboBox]
_IDS = [factory.__name__ for factory in _FACTORIES]


def _render_self(widget) -> tuple[list[str], QPixmap]:
    """自绘一次，返回（期间的 Qt 消息, 渲染结果）。"""
    messages: list[str] = []

    def handler(_mode, _context, message):  # noqa: ANN001
        messages.append(str(message))

    previous = qInstallMessageHandler(handler)
    target = QPixmap(max(1, widget.width()), max(1, widget.height()))
    target.fill()
    try:
        widget.render(target, QPoint(), QRegion(), _SELF_ONLY)
    finally:
        qInstallMessageHandler(previous)
    return messages, target


class TestEmptyMultiSelectPaint:
    @pytest.mark.parametrize("factory", _FACTORIES, ids=_IDS)
    def test_empty_box_does_not_leak_painter_state(self, qapp, make, factory):
        widget = make(factory)
        widget.resize(240, 32)
        assert widget.count() == 0, "本用例针对空框"

        messages, _target = _render_self(widget)
        leaks = [m for m in messages if "saved states" in m]
        assert not leaks, (
            f"{factory.__name__} 空框绘制泄漏 QPainter 状态：{leaks}"
            "（若只有上游类失败，多半是装到了重编前的旧轮子）"
        )

    @pytest.mark.parametrize("factory", _FACTORIES, ids=_IDS)
    def test_non_empty_box_does_not_leak_painter_state(self, qapp, make, factory):
        widget = make(factory)
        widget.resize(240, 32)
        widget.addItems(["一", "二", "三"])
        assert widget.count() == 3

        messages, _target = _render_self(widget)
        leaks = [m for m in messages if "saved states" in m]
        assert not leaks, f"{factory.__name__} 非空框绘制泄漏 QPainter 状态：{leaks}"

    def test_empty_box_still_paints_box(self, qapp, make):
        """空框要真画出「底 + 边框 + 底线」，不能退化成纯透明。"""
        widget = make(ElaSearchMultiBox)
        widget.resize(240, 32)

        _messages, target = _render_self(widget)
        image = target.toImage()
        colors = {
            image.pixel(x, y)
            for x in range(0, image.width(), 3)
            for y in range(0, image.height(), 3)
        }
        assert len(colors) > 1, "空框应画出边框 / 底线，而不是单一底色"
