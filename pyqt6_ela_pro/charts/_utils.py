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
  （``legend: false``）→ ``{"show": False}``；数组写法取第一个 dict；
  非 dict 垃圾值按「关闭」处理。
- ``single_option(value, name)``：单实例组件的 option（dict / 数组取首个 dict）。
- ``parse_roam(value)``：ECharts ``roam`` → ``(可缩放, 可平移)``；**数字按
  true 认**（JSON 读进来的 ``roam: 1``），graph / map 共用。
- ``merged_text_style(chart, local)``：组件级文字样式叠加顶层 ``textStyle``
  兜底（只合 fontSize / fontWeight / fontFamily / fontStyle / color）。
- ``text_weight(value, default)``：ECharts ``fontWeight``（数字 / ``"bold"`` 等）
  → Qt 数值，非法值回退 default。
- ``text_italic(value)``：ECharts ``fontStyle`` → 是否斜体。
- ``ON_FILL_WHITE``：绘制在彩色填充上的白字常量。

移植自 InstructionX_UIKit.charts._utils（原库为 PyQt6，无逻辑改动；
原库无 LICENSE，保留出处）。
"""

from __future__ import annotations

import math
import sys

from PyQt6.QtGui import QColor

from .._colors import parse_color

__all__ = [
    "to_float",
    "clamp",
    "with_alpha",
    "dist_point_segment",
    "warn_once",
    "ON_FILL_WHITE",
    "merged_text_style",
    "parse_color",
    "text_weight",
    "text_italic",
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
    c = QColor(parse_color(color))
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
# 文字样式（顶层 ``textStyle`` 兜底 + ECharts fontWeight 解析）
# ---------------------------------------------------------------------------

#: 顶层 ``textStyle`` 参与兜底的键。**只合外观、不合行为** —— 把整个 dict
#: 合进 ``series.label`` 会让 ``{"textStyle": {"show": True}}`` 顺手打开所有
#: 数据点标签（ECharts 的 textStyle 本来也不描述 show / formatter）。
TEXT_STYLE_KEYS = ("fontSize", "fontWeight", "fontFamily", "fontStyle", "color")

#: ECharts ``fontWeight`` 的关键字（Canvas 字体串语义）→ Qt 数值
_FONT_WEIGHTS = {"normal": 400, "bold": 700, "bolder": 700, "lighter": 300}


def merged_text_style(chart, local=None) -> dict:
    """组件级文字样式叠加顶层 ``textStyle`` 兜底（组件级优先）。

    顶层 ``textStyle`` 在 ECharts 里是**全图文字外观的默认值**；本库原先虽然有
    ``ElaChartWidget.textStyle()`` 读取入口，却没有任何组件消费它 —— 用户写
    ``{"textStyle": {"fontSize": 14}}`` 一点效果都没有，且零报错。

    :param chart: 图表实例（可为 None；取 ``chart.textStyle()``）
    :param local: 组件级样式 dict（如 ``legend.textStyle`` / ``series.label``）
    :returns: 只含 :data:`TEXT_STYLE_KEYS` 的合并结果
    """
    merged = {}
    if chart is not None:
        getter = getattr(chart, "textStyle", None)
        if callable(getter):
            try:
                global_style = getter() or {}
            except Exception:  # 宿主自定义图表 / 已销毁包装器
                global_style = {}
            if isinstance(global_style, dict):
                for key in TEXT_STYLE_KEYS:
                    value = global_style.get(key)
                    if value is None:
                        continue
                    if key == "fontFamily" and not str(value).strip():
                        continue  # 空串 = 未设置，继续走图表级字体
                    merged[key] = value
    if "fontFamily" not in merged and chart is not None:
        # 图表级 ``setFontFamily``（不写进 option，``notMerge`` 也不会丢）
        getter = getattr(chart, "fontFamily", None)
        if callable(getter):
            try:
                family = getter()
            except Exception:
                family = ""
            if family:
                merged["fontFamily"] = family
    if isinstance(local, dict):
        for key in TEXT_STYLE_KEYS:
            value = local.get(key)
            if value is None:
                continue
            if key == "fontFamily" and not str(value).strip():
                continue
            merged[key] = value
    return merged


#: ECharts ``fontStyle`` 中按斜体渲染的取值
_ITALIC_STYLES = frozenset({"italic", "oblique"})


def text_italic(value) -> bool:
    """ECharts ``fontStyle`` → 是否斜体（``normal`` / 其它一律 False）。"""
    return isinstance(value, str) and value.strip().lower() in _ITALIC_STYLES


def text_weight(value, default=None):
    """ECharts ``fontWeight`` → Qt 数值；无法解析返回 ``default``。

    支持数字 / 数字字符串 / ``"normal"`` / ``"bold"`` / ``"bolder"`` /
    ``"lighter"``。**非法值必须回退**：``QFont.Weight(650)`` 本身能接受任意
    int，但 ``int("bold")`` 会抛异常，而这条链跑在 ``paintAxes`` 里。
    """
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, str):
        mapped = _FONT_WEIGHTS.get(value.strip().lower())
        if mapped is not None:
            return mapped
    try:
        weight = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default
    return weight if 1 <= weight <= 1000 else default


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


def single_option(value, name: str = ""):
    """单实例组件 option：dict 原样，**数组取第一个 dict**。

    ECharts 的 ``title`` / ``legend`` / ``grid`` / ``polar`` / ``calendar`` /
    ``singleAxis`` / ``brush`` / ``toolbox`` 都允许数组（多实例）。本库只实现
    单实例，但**不能因此让组件静默消失** —— 数组是官方示例最常见的写法：

    * ``grid: [{...}]`` 原先走 ``dict(list)`` 抛 ``ValueError``，坐标系兜底成
      ``None`` → **整张图空白**；
    * ``title: [{...}]`` 原先被 ``component_opt`` 当成非 dict → ``{}`` →
      标题文本为空。

    多元素时只取第一个并用 ``warn_once`` 留一条可见记录（stderr），
    不假装支持多实例。
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        items = [item for item in value if isinstance(item, dict)]
        if len(items) > 1:
            warn_once(
                f"single-option:{name or '?'}",
                f"只支持单个 {name or '组件'}，已忽略其余 {len(items) - 1} 项",
            )
        return items[0] if items else None
    return None


def grid_options(value) -> list:
    """``grid`` option → 网格列表（单 dict / 数组；空或非法 → 一个默认 ``{}``）。"""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        items = [item for item in value if isinstance(item, dict)]
        return items or [{}]
    return [{}]


def component_options(value, show_key: str = "show") -> list:
    """组件 option → **实例列表**（多实例组件用）。

    ``False`` → ``[{show: False}]``；dict → 单元素；数组 → 逐项 dict。
    空数组 / 非法值 → 一个默认 ``{}``（组件照常按默认值渲染）。
    """
    if value is False:
        return [{show_key: False}]
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        items = [item for item in value if isinstance(item, dict)]
        return items or [{}]
    return [{}]


def component_opt(value, show_key: str = "show", name: str = ""):
    """ECharts 组件 option 的 ``False`` 简写 → ``{show_key: False}``。

    ECharts 允许 ``legend: false`` / ``tooltip: false``（等价于
    ``{"show": false}``）。直接 ``opt.get("legend") or {}`` 会把 ``False``
    吞成空 dict → 组件按**默认值**渲染 → 用户写 ``legend: false`` 结果图例
    照样显示，而且没有任何报错。

    **数组写法取第一个 dict**（见 :func:`single_option`）：``legend: [{...}]``
    是 ECharts 标准写法，不能整块丢掉。非 dict 的真垃圾值（如 ``legend: 5``）
    按「关闭」处理：那不是合法配置，猜一个默认值不如让它显式地不显示。
    """
    if value is False:
        return {show_key: False}
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        first = single_option(value, name)
        return first if isinstance(first, dict) else {}
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
