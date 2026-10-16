"""
菜单项 / 动作定义（``pyqt6_ela_pro.menu_item``）。

:class:`ElaMenuItem` 是「一条可点击的菜单项」的统一数据模型，被两个消费者共用：
划词动作条（``ElaSelectionAssistant.setActions``）与托盘菜单（``ElaTrayIcon``）。
两个消费者都**只发信号、不执行动作**，行为由宿主监听各自的 ``actionTriggered``
自行实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ElaMenuItem:
    """一条菜单项 / 动作的定义（宿主自定义，组件不内置任何动作）。

    ``tooltip`` 缺省用 ``label``；``icon`` 缺省时消费者回落为纯文字；
    ``enabled=False`` 的语义是**整项不显示**（不是置灰）。
    """

    id: str
    label: str
    icon: Optional[Any] = None
    tooltip: str = ""
    enabled: bool = True


__all__ = ["ElaMenuItem"]
