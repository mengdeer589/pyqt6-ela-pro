"""Splitter 分割器组件。

``ElaSplitter`` 直接采用绑定层实现（V3.0 起由 C++ 绘制主题分割线）；
本模块只保留按控件列表组装分割器的辅助函数。
"""

from __future__ import annotations

import warnings
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QBoxLayout, QSplitter, QWidget

from PyQt6ElaWidgetTools import ElaSplitter

__all__ = ["ElaSplitter", "create_ela_splitter"]


def create_ela_splitter(
    widgets: list,
    orientation: Qt.Orientation = Qt.Orientation.Horizontal,
    handle_thickness: int = 6,
    sizes: Optional[list[int]] = None,
    parent: QWidget = None,
) -> QSplitter:
    """将组件列表（至少 2 个）以 ELA 风格 splitter 分割，返回配置好的 ``ElaSplitter``。"""
    if len(widgets) < 2:
        raise ValueError("组件列表至少需要 2 个组件")
    if sizes is not None and len(sizes) != len(widgets):
        raise ValueError("sizes 列表长度必须与组件列表长度一致")

    if parent is None and widgets:
        parent = widgets[0].parentWidget()

    splitter = ElaSplitter(orientation, parent)
    splitter.setHandleWidth(handle_thickness)

    if parent is not None and parent.layout() is not None:
        layout = parent.layout()
        if isinstance(layout, QBoxLayout):
            idx = layout.indexOf(widgets[0])
            if idx >= 0:
                layout.insertWidget(idx, splitter)
            else:
                layout.addWidget(splitter)
        else:
            layout.addWidget(splitter)
    elif parent is not None:
        # parent 有值但没有布局：splitter 无处安放，而下面的 addWidget 已经把
        # 传入的 widgets reparent 进它 —— 结果返回一个不可见的 splitter、
        # 原控件从界面上消失。显式提示，调用方需自行把返回值挂进布局。
        warnings.warn(
            "create_ela_splitter: parent 没有布局，splitter 不会被挂载"
            "（传入的 widgets 已 reparent 进去，界面上会消失）——"
            "请自行把返回的 splitter 加入布局，或传 parent=None 后手动挂载。",
            RuntimeWarning,
            stacklevel=2,
        )

    for widget in widgets:
        splitter.addWidget(widget)

    if sizes is not None:
        splitter.setSizes(sizes)

    return splitter
