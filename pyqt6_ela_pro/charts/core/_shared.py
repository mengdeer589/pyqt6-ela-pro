"""注册表、数据解析与图表共享小工具。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math
import time
import weakref
from collections import defaultdict
from typing import Optional

from ..._internal import is_deleted
from PyQt6.QtCore import (
    QEasingCurve,
)
from PyQt6ElaWidgetTools import eTheme

from .._tokens import (
    palette_for_mode,
)
from .._utils import warn_once
from ..axes import (
    formatValue,
)

SERIES_REGISTRY: dict = {}
COMPONENT_REGISTRY: dict = {}
_CHART_GROUPS: dict = {}


def _group_members(group: str) -> list:
    """取出组内存活实例（顺手剪掉已销毁的 weakref）。"""
    refs = _CHART_GROUPS.get(str(group)) or []
    alive = []
    for ref in refs:
        chart = ref()
        if chart is not None and not is_deleted(chart):
            alive.append(chart)
    if alive:
        _CHART_GROUPS[str(group)] = [weakref.ref(c) for c in alive]
    else:
        _CHART_GROUPS.pop(str(group), None)
    return alive


def connectCharts(group: str) -> None:
    """连接同组图表（ECharts ``connect``）：联动 dataZoom / legend / axis tooltip。"""
    key = str(group or "").strip()
    if not key:
        return
    for chart in _group_members(key):
        chart._joinGroupHandlers(key)


def disconnectCharts(group: str = None) -> None:
    """断开图表组；``group=None`` 断开全部。"""
    if group is None:
        for key in list(_CHART_GROUPS):
            for chart in _group_members(key):
                chart._leaveGroupHandlers()
        _CHART_GROUPS.clear()
        return
    key = str(group).strip()
    for chart in _group_members(key):
        chart._leaveGroupHandlers()
    _CHART_GROUPS.pop(key, None)


def registerSeries(type_name: str, cls) -> None:
    """注册系列渲染器：``type_name``（如 "bar"）→ SeriesRenderer 子类。

    同名重复注册（换类）会覆盖并记录一次 stderr 告警，便于排查冲突。
    """
    if not type_name:
        raise ValueError("registerSeries: type_name 不能为空")
    key = str(type_name)
    previous = SERIES_REGISTRY.get(key)
    if previous is not None and previous is not cls:
        warn_once(
            f"series-replace:{key}",
            f"系列 {key!r} 已注册（{getattr(previous, '__name__', previous)}），"
            f"现被覆盖为 {getattr(cls, '__name__', cls)}",
        )
    SERIES_REGISTRY[key] = cls


def registerComponent(name: str, cls) -> None:
    """注册图表组件：``name``（如 "markLine"）→ 组件类。

    同名重复注册（换类）会覆盖并记录一次 stderr 告警，便于排查冲突。
    """
    if not name:
        raise ValueError("registerComponent: name 不能为空")
    key = str(name)
    previous = COMPONENT_REGISTRY.get(key)
    if previous is not None and previous is not cls:
        warn_once(
            f"component-replace:{key}",
            f"组件 {key!r} 已注册（{getattr(previous, '__name__', previous)}），"
            f"现被覆盖为 {getattr(cls, '__name__', cls)}",
        )
    COMPONENT_REGISTRY[key] = cls


def defaultPalette() -> list:
    """默认调色板（主题感知：随 eTheme 模式取色，重绘即生效）。"""
    return palette_for_mode(eTheme.getThemeMode())


def parseDataPoint(item, index: int = 0):
    """解析系列数据项 → ``(x, y)``。

    支持：``number``（x=index）、``[x, y]``、``{"value": ...}``；
    无法解析返回 ``(index, None)``。
    """
    if item is None:
        return index, None
    v = item.get("value") if isinstance(item, dict) else item
    if isinstance(v, (list, tuple)):
        if not v:
            return index, None
        x = v[0]
        y = v[1] if len(v) >= 2 else None
        if isinstance(y, (int, float)) and not isinstance(y, bool):
            return x, float(y)
        return x, None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return index, float(v)
    return index, None


GRID_SERIES_TYPES = frozenset(
    {
        "bar",
        "pictorialBar",
        "line",
        "scatter",
        "effectScatter",
        "candlestick",
        "boxplot",
        "heatmap",
        "lines",
    }
)


def _needs_grid_coord(series_opts) -> bool:
    """是否存在 coordinateSystem 缺省且落在 grid 的系列（决定是否创建 GridCoord）。"""
    for s in series_opts or []:
        if not isinstance(s, dict):
            continue
        if s.get("coordinateSystem") not in (None, "cartesian2d", "grid"):
            continue
        if str(s.get("type") or "line") in GRID_SERIES_TYPES:
            return True
    return False


def _opt_float(value, default):
    """把 option 里的取值安全转成 float，失败回退 ``default``。

    ``default`` 传 ``None`` 时表示「转换失败就返回 None」而不是回退数值 ——
    宿主的 ``dispatchAction({"type": "showTip", "x": "abc"})`` 这类要靠它
    区分「没给坐标」与「坐标是 0」。

    ``fontSize`` 之类由调用方提供的值可能是 ``None``、``"14px"``、``"large"`` 等；
    裸 ``float()`` 会在 ``Title.height()`` / ``Legend._font()`` 里抛
    ``TypeError`` / ``ValueError``，而这两处由 ``resizeEvent`` / ``paintEvent``
    无保护地调用 —— 异常穿透 Qt 回调边界会让进程 0xC0000409 静默终止。
    与 ``axes.AxisModel.labelFont`` 的既有防御保持一致。

    **``OverflowError`` 必须列进来**：它继承 ``ArithmeticError`` 而不是
    ``ValueError``，而 ``int(float("inf"))`` / ``float(10**400)`` 抛的正是它
    （option 里写 ``{"splitNumber": Infinity}`` 就可达）。漏掉它 = 一个
    ``except (TypeError, ValueError)`` 看起来齐全、实则漏一个子类。
    本包所有「把 option 外部值转数值」的容错点都按这条统一。
    """
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result


_HOVERABLE_COMPONENTS = frozenset({"markPoint", "markLine"})
_ANIM_EASINGS = {
    "linear": QEasingCurve.Type.Linear,
    "quadraticin": QEasingCurve.Type.InQuad,
    "quadraticout": QEasingCurve.Type.OutQuad,
    "quadraticinout": QEasingCurve.Type.InOutQuad,
    "cubicin": QEasingCurve.Type.InCubic,
    "cubicout": QEasingCurve.Type.OutCubic,
    "cubicinout": QEasingCurve.Type.InOutCubic,
    "quarticin": QEasingCurve.Type.InQuart,
    "quarticout": QEasingCurve.Type.OutQuart,
    "quarticinout": QEasingCurve.Type.InOutQuart,
    "sinusoidalin": QEasingCurve.Type.InSine,
    "sinusoidalout": QEasingCurve.Type.OutSine,
    "sinusoidalinout": QEasingCurve.Type.InOutSine,
    "exponentialin": QEasingCurve.Type.InExpo,
    "exponentialout": QEasingCurve.Type.OutExpo,
    "exponentialinout": QEasingCurve.Type.InOutExpo,
    "circularin": QEasingCurve.Type.InCirc,
    "circularout": QEasingCurve.Type.OutCirc,
    "circularinout": QEasingCurve.Type.InOutCirc,
    "elasticin": QEasingCurve.Type.InElastic,
    "elasticout": QEasingCurve.Type.OutElastic,
    "elasticinout": QEasingCurve.Type.InOutElastic,
    "backin": QEasingCurve.Type.InBack,
    "backout": QEasingCurve.Type.OutBack,
    "backinout": QEasingCurve.Type.InOutBack,
    "bouncein": QEasingCurve.Type.InBounce,
    "bounceout": QEasingCurve.Type.OutBounce,
    "bounceinout": QEasingCurve.Type.InOutBounce,
}


def _easing_from_name(name, default=QEasingCurve.Type.OutCubic):
    """解析 ECharts ``animationEasing`` 名称 → QEasingCurve.Type。"""
    if name is None:
        return default
    return _ANIM_EASINGS.get(str(name).strip().lower(), default)


def _anchor_px(value, total: float, default: float) -> float:
    """解析 left/top/right/bottom 锚点：数值 px 或 ``"N%"``（非法 → default）。"""
    if value is None:
        return default
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("%"):
            try:
                return float(s[:-1]) * float(total) / 100.0
            except ValueError:
                return default
        if not s or s.lower() in (
            "auto",
            "left",
            "top",
            "right",
            "bottom",
            "center",
            "middle",
        ):
            return default
        try:
            return float(s)
        except ValueError:
            return default
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _now() -> float:
    """单调秒（``benchmark`` 计时用）。

    用 ``time.monotonic`` 而非 ``time.time``：后者受系统时钟调整影响，
    一次基准测试跨越 NTP 校正就会算出负耗时。
    """
    return time.monotonic()


def _elapsed_ms(t0: float) -> float:
    return (time.monotonic() - t0) * 1000.0


def formatLabelTemplate(template: str, params: dict) -> Optional[str]:
    """ECharts 风格 ``{a}/{b}/{c}/{d}`` 标签模板（缺失键 → 空串；失败 None）。

    浮点值按 ``formatValue`` 规则渲染（``100.0`` → ``"100"``），与数值标签一致。
    """
    try:
        safe = {
            key: formatValue(value) if isinstance(value, float) else value
            for key, value in params.items()
        }
        return template.format_map(defaultdict(str, safe))
    except Exception:
        return None


def _sort_value(value) -> float:
    """unified 排序键：数值原样，非数值一律 +inf（正序落尾、倒序落头）。"""
    if isinstance(value, bool) or value is None:
        return math.inf
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return math.inf
    return number if math.isfinite(number) else math.inf
