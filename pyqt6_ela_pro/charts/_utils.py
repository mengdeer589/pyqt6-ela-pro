"""
charts 包私有共享工具模块。

数值与几何小工具：统一语义为「过滤 NaN/Inf」版：

- ``to_float(v, default=0.0)``：宽松转 float；None / bool / NaN / Inf /
  转换失败一律返回 default（唯一语义，防止 NaN 流入 QPainter 坐标）。
- ``clamp(v, lo, hi)``：区间钳制。
- ``with_alpha(color, a)``：返回设置 alpha（0-255）后的 QColor 副本。
- ``dist_point_segment(p, a, b)``：点 p 到线段 a-b 的距离。
- ``warn_once(key, message)`` / ``warn_key(prefix, *parts)``：异常静默吞噬的
  可见性出口——同一 key 仅向 stderr 记录一次（有界去重）。**key 要带区分信息**
  （类 + 系列名 + 异常类型），只用类名会让第二个系列的不同故障永久不可见。
- ``component_opt(value, show_key)``：ECharts 组件 option 的 ``False`` 简写
  （``legend: false``）→ ``{"show": False}``；非 dict 垃圾值按「关闭」处理。
- ``parse_roam(value)``：ECharts ``roam`` → ``(可缩放, 可平移)``；**数字按
  true 认**（JSON 读进来的 ``roam: 1``），graph / map 共用。
- ``ON_FILL_WHITE``：绘制在彩色填充上的白字常量。

移植自 InstructionX_UIKit.charts._utils（原库为 PyQt6，无逻辑改动；
原库无 LICENSE，保留出处）。
"""

from __future__ import annotations

import math
import sys

from PyQt6.QtGui import QColor

__all__ = [
    "to_float",
    "clamp",
    "with_alpha",
    "dist_point_segment",
    "warn_once",
    "ON_FILL_WHITE",
]

# ---------------------------------------------------------------------------
# 数值 / 几何工具
# ---------------------------------------------------------------------------


def to_float(v, default=0.0):
    """宽松转 float；None / bool / NaN / Inf / 转换失败一律返回 default。"""
    fallback = None if default is None else float(default)
    if isinstance(v, bool) or v is None:
        return fallback
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return fallback
    if math.isnan(f) or math.isinf(f):
        return fallback
    return f


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def with_alpha(color, a):
    """返回设置 alpha（0-255，自动钳制）后的 QColor 副本。"""
    c = QColor(color)
    c.setAlpha(int(clamp(a, 0, 255)))
    return c


def dist_point_segment(p, a, b):
    """点 p 到线段 a-b 的距离（退化线段退化为点距）。"""
    ax, ay = a.x(), a.y()
    bx, by = b.x(), b.y()
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-12:
        return math.hypot(p.x() - ax, p.y() - ay)
    t = clamp(((p.x() - ax) * dx + (p.y() - ay) * dy) / length_sq, 0.0, 1.0)
    return math.hypot(p.x() - (ax + t * dx), p.y() - (ay + t * dy))


# ---------------------------------------------------------------------------
# 异常可见性（「失败不影响主图」契约的配套出口）
# ---------------------------------------------------------------------------

_warned_keys = set()
_WARN_LIMIT = 512  # 去重集合上界，防止长期运行无界增长


def warn_once(key: str, message: str) -> None:
    """同一 key 仅向 stderr 记录一次（有界去重）。

    **key 必须带上足以区分故障的信息。** 去重的目的是「同一故障不要每帧刷屏」，
    不是「同一个类只报一次」：键只用类名时，第二个系列的**另一种**异常会被
    永久吞掉 —— 而这些异常本来就被 ``except Exception`` 静默吞掉了，stderr 是
    唯一的可见性出口，吞掉就没有任何线索了。正确形状是
    ``(类, 系列名, 异常类型)``。
    """
    if key in _warned_keys:
        return
    if len(_warned_keys) >= _WARN_LIMIT:
        _warned_keys.clear()
    _warned_keys.add(key)
    sys.stderr.write(f"[charts] {message}\n")


def warn_key(prefix: str, *parts) -> str:
    """``warn_once`` 的 key 构造：把 ``None`` / 空串去掉后用 ``|`` 连接。

    比在调用点手写 f-string 好在两处：一是 ``None`` 会被 ``|None`` 污染键
    （两个不同的「无名字」撞成同一个键），二是异常类型必须进去。
    """
    return prefix + "".join(f"|{p}" for p in parts if p)


def component_opt(value, show_key: str = "show"):
    """ECharts 组件 option 的 ``False`` 简写 → ``{show_key: False}``。

    ECharts 允许 ``legend: false`` / ``tooltip: false``（等价于
    ``{"show": false}``）。直接 ``opt.get("legend") or {}`` 会把 ``False``
    吞成空 dict → 组件按**默认值**渲染 → 用户写 ``legend: false`` 结果图例
    照样显示，而且没有任何报错。

    非 dict 的真垃圾值（如 ``legend: 5``）也一并按「关闭」处理：那不是合法
    配置，猜一个默认值不如让它显式地不显示。
    """
    if value is False:
        return {show_key: False}
    if isinstance(value, dict):
        return value
    return {}


def parse_roam(value) -> tuple:
    """ECharts ``roam`` → ``(可缩放, 可平移)``。

    支持：``True`` / ``1`` / ``"true"`` / ``"yes"`` / ``"on"``（都按全开）、
    ``"scale"`` / ``"move"``（单方向）、``"scale,move"``（显式组合）。

    **数字必须按 true 认**：从 JSON 读进来的 option 里 ``roam`` 常是数字
    （``{"roam": 1}`` 就是 ``true``）。原先 graph / map 各自解析时都把
    非 bool 落到「方向名」分支，``str(1) == "1"`` 里既没有 ``scale`` 也没有
    ``move`` → **整个 roam 被静默关掉**，用户看到「滚轮没反应、也拖不动」。
    两处共用本函数，免得修一个漏一个。
    """
    if value in (None, False):
        return (False, False)
    if value is True:
        return (True, True)
    if isinstance(value, (int, float)):
        return (bool(value), bool(value))
    text = str(value).strip().lower()
    if text in ("true", "yes", "on", "1"):
        return (True, True)
    if text in ("false", "no", "off", "0", ""):
        return (False, False)
    return ("scale" in text, "move" in text)


# ---------------------------------------------------------------------------
# 硬编码颜色豁免常量
# ---------------------------------------------------------------------------

#: 白字豁免：绘制在彩色填充（系列色块 / 渐变带）之上的标签文字，
#: 与主题无关的「on-fill」前景色，集中于此常量以便审计，不读主题令牌。
ON_FILL_WHITE = "#ffffff"
