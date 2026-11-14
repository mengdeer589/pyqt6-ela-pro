"""blueprint 包主题令牌适配层（私有）。"""

from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from .._internal import connect_theme_signal
from ..charts._tokens import chart_token

__all__ = ["T", "theme_changed_slot", "shadow_md"]

#: 圆角令牌（源库 radius.lg = 8；其余档位按需补充）
RADIUS = {"sm": 4, "md": 6, "lg": 8}
#: 间距令牌（对齐源库 space.* 值）
SPACE = {"0": 0, "05": 2, "1": 4, "2": 8, "3": 12, "4": 16, "5": 20}

#: 蓝图专有语义色（Ela 主题无对应槽位）：key -> (light, dark)。
#: 引脚圆点铺在节点体 PopupBase 上，Light/Dark 两组都 ≥3:1。
_PIN_COLOR_PAIRS = {
    "color.pin.image": ("#8B4FA8", "#C79AE8"),
    "color.pin.tensor": ("#177A72", "#5FC6BC"),
    "color.pin.warning": ("#A06E1F", "#D2A668"),
}


def T(key):
    """读取令牌：颜色返回 hex 字符串，数值返回 int（对齐源库调用面）。
    **未知键抛 ``KeyError``** —— 这是有意的：静默回退会把「拼错一个令牌名」
    合法性必须在更早的注册期就校验掉（见 ``registry.register_pin_type``），
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
    pair = _PIN_COLOR_PAIRS.get(key)
    if pair is not None:
        dark = eTheme.getThemeMode() == ElaThemeType.ThemeMode.Dark
        return QColor(pair[1] if dark else pair[0]).name()
    v = chart_token(eTheme.getThemeMode(), key)
    if isinstance(v, QColor):
        return v.name()
    return v


def theme_changed_slot(widget, slot) -> None:
    """连接主题切换信号；widget 销毁时 Qt 自动断开（绑定方法语义）。
    **校验 ``slot`` 是 ``widget`` 的绑定方法**：lambda / 普通函数不会被 Qt
    当作「接收方销毁即断连」处理，会在单例信号上静默残留（这里响亮失败，
    """
    if getattr(slot, "__self__", None) is not widget:
        raise TypeError(
            "theme_changed_slot 需要 widget 的绑定方法作为槽"
            "（lambda / 普通函数不会随控件销毁自动断连）"
        )
    connect_theme_signal(widget, slot)


def shadow_md() -> dict:
    """选中发光近似阴影参数（按主题模式）。"""
    if eTheme.getThemeMode() == ElaThemeType.ThemeMode.Dark:
        return {"blur": 16, "offset": (0, 4), "color": (0, 0, 0, 140)}
    return {"blur": 16, "offset": (0, 4), "color": (16, 24, 40, 64)}
