"""
blueprint 包主题令牌适配层（私有）。

源引擎（InstructionX_UIKit.blueprint）大量使用 ``str(T("color.x"))``
（T() 返回 hex 字符串）与 ``ThemeManager.theme_changed``。本模块提供
等价调用面，颜色实时映射到 ``eTheme`` / ``ElaThemeType``：

- ``T(key)``：颜色键返回 hex 字符串，数值键（space./font./radius.lg）
  返回 int；未知键抛 ``KeyError``。
- ``theme_changed_slot(widget, slot)``：连接主题切换信号并随 widget
  销毁自动断开（绑定方法连接，Qt 接收方销毁即断连）。
- ``shadow_md()``：选中发光近似阴影参数（按主题模式）。

颜色映射复用 charts 包主题适配（charts._tokens 无内部依赖，直接引用）。
"""

from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from ..charts._tokens import chart_token

__all__ = ["T", "theme_changed_slot", "shadow_md"]

#: 圆角令牌（源库 radius.lg = 8；其余档位按需补充）
RADIUS = {"sm": 4, "md": 6, "lg": 8}
#: 间距令牌（对齐源库 space.* 值）
SPACE = {"0": 0, "05": 2, "1": 4, "2": 8, "3": 12, "4": 16, "5": 20}


def T(key):
    """读取令牌：颜色返回 hex 字符串，数值返回 int（对齐源库调用面）。

    **未知键抛 ``KeyError``** —— 这是有意的：静默回退会把「拼错一个令牌名」
    变成一片默认色且永不报警。因此凡是在**绘制期**调 ``T()`` 的地方，配色的
    合法性必须在更早的注册期就校验掉（见 ``registry.register_pin_type``），
    或者在读取处显式 ``try``（见 ``registry.pin_color``）。
    """
    if key.startswith("radius."):
        name = key[len("radius.") :]
        if name in RADIUS:
            return RADIUS[name]
        raise KeyError(f"未知圆角令牌: {key!r}")
    if key.startswith("space."):
        name = key[len("space.") :]
        if name in SPACE:
            return SPACE[name]
        raise KeyError(f"未知间距令牌: {key!r}")
    v = chart_token(eTheme.getThemeMode(), key)
    if isinstance(v, QColor):
        return v.name()
    return v


def theme_changed_slot(widget, slot) -> None:
    """连接主题切换信号；widget 销毁时 Qt 自动断开（绑定方法语义）。"""
    eTheme.themeModeChanged.connect(slot)


def shadow_md() -> dict:
    """选中发光近似阴影参数（按主题模式）。"""
    if eTheme.getThemeMode() == ElaThemeType.ThemeMode.Dark:
        return {"blur": 16, "offset": (0, 4), "color": (0, 0, 0, 140)}
    return {"blur": 16, "offset": (0, 4), "color": (16, 24, 40, 64)}
