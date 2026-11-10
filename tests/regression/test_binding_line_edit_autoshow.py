"""本地重编轮守卫：``ElaLineEdit`` 构造时不得自行显示。

上游构造函数末尾有 ``QWidget::setVisible(true)``：无父控件时 ``ElaLineEdit`` 本身就是
顶层窗口，宿主按 Qt 常规「先构造、再 addWidget」的写法会在屏幕上闪一个小窗（示例
蓝图页的 ``optim_body`` 必中）。修复在 C++ 侧（``ElaLineEdit.cpp`` 删除该调用）→
重编 ``pyqt6-elawidgettools`` 轮子。**装到重编前的旧轮子时本用例会红。**
"""

from __future__ import annotations

from PyQt6ElaWidgetTools import ElaLineEdit


def test_parentless_line_edit_stays_hidden(make):
    edit = make(ElaLineEdit)
    assert not edit.isVisible(), (
        "无父构造的 ElaLineEdit 自行显示了顶层窗口；当前装的多半是重编前的旧轮子"
    )
