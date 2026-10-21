"""
图表引擎核心：``ElaChartWidget`` 与系列 / 组件协议。

对外契约（ECharts 实例 API 对齐）见 :class:`ElaChartWidget` 的类docstring，
此处不重复。模块层面的三件事：

- **注册表** ``SERIES_REGISTRY`` / ``COMPONENT_REGISTRY`` + ``registerSeries`` /
  ``registerComponent``：同名键**后注册覆盖先注册**（内置类型在包import 时
  注册，宿主可在自己的模块里替换某个内置类型的实现）。
- **协议基类** ``SeriesRenderer``（系列，``layout`` / ``paint(p, anim_t)`` /
  ``hitTest``）与 ``Coord``（坐标，见 ``axes.py``）。注册进来的类只需满足
  构造签名 ``(chart, opt)``。
- **组件数组的实例化规则**：顶层 ``visualMap`` 是数组语义（多个 visualMap
  各自绑定不同系列，声明 ``spawnPerItem = True`` 逐元素建实例），而
  ``dataZoom`` / ``graphic`` 自己处理数组、整包传入。见 ``_component_inputs``。

出处：ECharts 风格 ``setOption`` API 移植自 InstructionX_UIKit.charts.core
（原库为 PyQt6；主题令牌经 ``charts._tokens`` 适配到 eTheme /
ElaThemeType，原库无 LICENSE，保留出处）。
"""

from __future__ import annotations

import copy
import math
import pathlib
import time
from collections import defaultdict
from typing import Optional

from .._internal import is_deleted
from PyQt6.QtCore import (
    QAbstractAnimation,
    QBuffer,
    QEasingCurve,
    QIODevice,
    QObject,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import QFileDialog, QWidget
from PyQt6ElaWidgetTools import eTheme

from .._internal import connect_theme_signal, disconnect_theme
from .._motion import ElaMotionKindType, motion, start_idle_loop
from . import data as _cdata
from .data import ElaNumericBuffer
from ._tokens import (
    ANIM_DURATION,
    ANIM_EASING,
    SPINNER_TICK_MS,
    T,
    palette_for_mode,
)
from ._utils import to_float as _to_float
from ._utils import component_opt as _component_opt
from ._utils import warn_key, warn_once
from .axes import (
    CalendarCoord,
    Coord,
    GridCoord,
    PolarCoord,
    SingleAxisCoord,
    chartFont,
    formatValue,
    niceTicks,
)

__all__ = [
    "SERIES_REGISTRY",
    "COMPONENT_REGISTRY",
    "registerSeries",
    "registerComponent",
    "defaultPalette",
    "niceTicks",
    "formatValue",
    "parseDataPoint",
    "SeriesRenderer",
    "Coord",
    "ChartAnimation",
    "Title",
    "Legend",
    "Tooltip",
    "ElaChartWidget",
    "SimpleLineSeriesRenderer",
]

# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

#: "bar" -> BarSeriesRenderer 等；同名后注册覆盖先注册
SERIES_REGISTRY: dict = {}

#: "markLine" -> MarkLineComponent 等（组件注册）
COMPONENT_REGISTRY: dict = {}


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


#: coordinateSystem 缺省（None / "cartesian2d" / "grid"）时落在 grid 直角
#: 坐标系的系列类型名单（决定是否兜底创建 GridCoord）。
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


def _hold_value(v):
    """合并 / 存入 option 时的取值策略：**大数组按引用，其余深拷贝**。

    ``copy.deepcopy`` 对百万级 float list 是纯浪费（本机 100 万点约
    60~95 ms），而这些数组图表从不在内部修改它们。``ElaNumericBuffer`` /
    ndarray 一律按引用持有，其余走原有深拷贝路径。

    注意：按引用持有意味着**调用方在 setOption 之后不得原地修改该数组**
    （与 InstructionX 的口径一致，见 ``charts.data`` 模块 docstring）。
    """
    if _cdata.isBufferLike(v):
        return v
    return copy.deepcopy(v)


def _deep_merge(dst: dict, src: dict) -> dict:
    """递归合并 src 到 dst（dict 深合并，list / 标量整体替换），返回 dst。"""
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = _hold_value(v)
    return dst


#: setOption 合并时按 ECharts 组件数组「逐项合并」的顶层键
_MERGE_ARRAY_KEYS = frozenset({"series", "dataZoom", "graphic"})

#: 参与 item 命中的组件（顶层优先于系列，因为它们画在系列之上）。
#: **markArea / graphic 刻意不在内**：前者是半透明背景区域（接进来会让区域
#: 内任何位置都抢走系列的悬停），后者是纯装饰（ECharts 侧也不交互）。
_HOVERABLE_COMPONENTS = frozenset({"markPoint", "markLine"})

#: animationEasing 名称 → QEasingCurve.Type（不认识的名称回退 OutCubic）
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


def _match_option_index(new_item, old_list: list, index: int) -> int:
    """组件 / 系列数组项匹配（ECharts 语义）：``id`` → ``name`` → 序号。

    返回旧列表下标；未匹配返回 -1（调用方按「新增一项」处理）。

    **显式给了 ``id`` 且没匹配上时必须返回 -1，不能回退到序号。** ECharts 的
    ``mappingByIndex`` 写得很明确（``echarts/src/util/model.ts``）：

        (2) If new option has id, it can only set to a hole or append to the
            last. It should not be merged to the existings with different id.
            Because id should not be overwritten.

    回退到序号的后果是**静默毁掉一个系列**：``[a, b]`` + ``[{"id": "zzz"}]``
    会把 ``b`` 位置上的系列替换成 ``zzz``，``a`` 整个消失且无任何告警；而
    ECharts 期望 3 个系列。若新项只带 ``id`` 不带 ``name`` / ``type``，更糟 ——
    幸存者保留旧系列的 ``name`` / ``type`` 却拿到新数据，图上出现一个用户
    根本没要求过的系列。
    """
    if isinstance(new_item, dict):
        new_id = new_item.get("id")
        if new_id is not None:
            for i, old in enumerate(old_list):
                if isinstance(old, dict) and old.get("id") == new_id:
                    return i
            # 显式 id 未命中 -> 只能新增，绝不按序号覆盖别人
            return -1
        new_name = new_item.get("name")
        if new_name:
            for i, old in enumerate(old_list):
                if isinstance(old, dict) and old.get("name") == new_name:
                    return i
    return index if 0 <= index < len(old_list) else -1


def _merge_option_array(old_list: list, new_list: list) -> list:
    """ECharts 风格组件数组合并（``series`` / ``dataZoom`` / ``graphic``）。

    新项按 ``id`` → ``name`` → 序号匹配旧项并深合并；未匹配的新项追加；
    旧列表中未被匹配的项保留（ECharts ``setOption`` 合并语义：合并模式下
    传空数组不会删除旧项，需 ``notMerge=True`` 或 ``clear()``）。
    标量数组无法逐项合并时整体替换。
    """
    old_list = list(old_list or [])
    new_list = list(new_list or [])
    if any(not isinstance(item, dict) for item in new_list):
        # 标量数组无法逐项合并 → 整体替换（逐项按引用持有，见 ``_hold_value``）。
        return [_hold_value(i) for i in new_list]
    result = [_hold_value(i) for i in old_list]
    used = set()
    for i, new_item in enumerate(new_list):
        idx = _match_option_index(new_item, old_list, i)
        if idx >= 0 and idx not in used:
            merged = _hold_value(old_list[idx])
            _deep_merge(merged, new_item)
            result[idx] = _normalize_series_entry(merged)
            used.add(idx)
        else:
            result.append(_copy_series_entry(new_item))
    return result


def _now() -> float:
    """单调秒（``benchmark`` 计时用）。

    用 ``time.monotonic`` 而非 ``time.time``：后者受系统时钟调整影响，
    一次基准测试跨越 NTP 校正就会算出负耗时。
    """
    return time.monotonic()


def _elapsed_ms(t0: float) -> float:
    return (time.monotonic() - t0) * 1000.0


def _int_attr(obj, name: str) -> int:
    """安全取整型属性；缺失 / 非法一律 0（诊断接口不因缺字段而抛异常）。"""
    try:
        return int(getattr(obj, name, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


#: 各系列渲染器存放「几何图元」的属性名（取最大长度者）。
#: 折线存 ``_points``、bar 存 ``_bars``、scatter 存 ``_dots``、pie 存
#: ``_sectors`` …… 早期实现只读折线的属性名，导致 bar / scatter 的规模恒为
#: 0（实测 8 系列里两条读数为 0）。这里列出各渲染器实际使用的名字。
_SERIES_GEOM_ATTRS = (
    "_points",
    "_bars",
    "_dots",
    "_sectors",
    "_nodes",
    "_items",
    "_rows",
    "_wedges",
    "_rings",
)


def _series_type_name(r) -> str:
    """系列类型名（取 option 的 ``type``，回退到类名去后缀）。"""
    t = (
        getattr(r, "opt", {}).get("type")
        if isinstance(getattr(r, "opt", None), dict)
        else None
    )
    if t:
        return str(t)
    return type(r).__name__.replace("SeriesRenderer", "")


def _series_data_len(r) -> int:
    """系列数据量。

    优先用折线的 ``_data_len``（它已是最终生效的数据长度，stack 叠加后也
    正确）；其余系列回退到 ``data()`` 的长度 —— 几何属性只反映**绘制**
    规模（采样后），不能当数据量用。
    """
    n = _int_attr(r, "_data_len")
    if n:
        return n
    data = r.data() if hasattr(r, "data") else []
    try:
        return len(data)
    except TypeError:
        return 0


def _series_geom_len(r) -> int:
    """系列实际绘制的几何元素数（折线点 / 柱 / 散点…… 各不相同）。"""
    best = 0
    for name in _SERIES_GEOM_ATTRS:
        try:
            v = getattr(r, name, None)
            best = max(best, len(v) if v is not None else 0)
        except TypeError:
            continue
    return best


def _animation_enabled(cur_option: dict, new_option: dict) -> bool:
    """本次 setOption 是否可能用到过渡动画数据（旧数据快照）。

    与 ``_start_animation`` 的判定保持一致：任一侧的 ``animation`` 不是
    显式 ``False`` 就认为可能要用。宁可多算一次快照，也不能出现「该播动画
    却拿不到旧数据」的空插值。
    """
    for opt in (cur_option, new_option):
        if isinstance(opt, dict) and opt.get("animation", True) is False:
            return False
    return True


def _snapshot_series_data(r):
    """取系列旧数据用于插值：大数组按引用，其余物化成 list。

    快照的用途只是「上一帧画过什么」，插值时按下标读；缓冲区按引用持有
    不会读到错位数据（``_rebuild`` 之后 ``prev_data`` 即被弃用）。
    """
    d = r.data()
    if _cdata.isBufferLike(d):
        return d
    return list(d)


def _normalize_series_entry(entry):
    """把 series 项**直接**的 ``data`` 大数值数组包成紧凑存储（就地）。

    只认 series 项自己的 ``data``，不碰 ``xAxis.data`` 等其它按 list 语义
    读取的键（包装会破坏它们）；也不递归 —— ``markPoint.data`` /
    ``graphic[].data`` 等嵌套数据形态各异，交给既有渲染路径。

    ``toBuffer`` 只接受「扁平数值序列」，遇到 dict / ``[x, y]`` 对 /
    heatmap 的 ``[x, y, v]`` 一律返回 ``None``，故本函数对结构型数据是
    无操作，语义零变化。
    """
    if not isinstance(entry, dict):
        return entry
    buf = _cdata.toBuffer(entry.get("data"))
    if buf is not None:
        entry["data"] = buf
    return entry


def _copy_option_shallow_arrays(option: dict) -> dict:
    """``notMerge`` 全量替换用的拷贝：**大数组按引用，其余深拷贝**。

    与 ``copy.deepcopy`` 的唯一区别就是数组不再逐元素复制，语义上仍然保证
    ``self._option`` 与调用方传入的 dict 不共享可变结构（只有只读的大数组
    共享 —— 见 ``_hold_value`` 的说明）。
    """
    if not isinstance(option, dict):
        return {}
    out = {}
    for k, v in option.items():
        if k == "series" and isinstance(v, list):
            out[k] = [_copy_series_entry(s) for s in v]
        else:
            out[k] = _hold_value(v)
    return out


def _copy_series_entry(s):
    """单个 series 项的拷贝：大 ``data`` 按引用，其余深拷贝。"""
    if not isinstance(s, dict):
        return _hold_value(s)
    return _normalize_series_entry({k: _hold_value(v) for k, v in s.items()})


def _copy_any(v):
    """递归拷贝：大数组按引用，其余深拷贝（供 getOption 使用）。"""
    if _cdata.isBufferLike(v):
        return v
    if isinstance(v, dict):
        return {k: _copy_any(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_copy_any(x) for x in v]
    return copy.deepcopy(v)


def _unwrap_option(option):
    """把 option 树中的紧凑存储还原为普通 list（``getOption`` 对外出口）。"""
    if isinstance(option, dict):
        return {k: _unwrap_option(v) for k, v in option.items()}
    if isinstance(option, list):
        return [_unwrap_option(v) for v in option]
    return _cdata.unwrapData(option)


def _merge_option(dst: dict, src: dict) -> dict:
    """ECharts 风格 option 合并：dict 深合并 / 组件数组逐项合并 / 其余整体替换。"""
    for k, v in (src or {}).items():
        if (
            k in _MERGE_ARRAY_KEYS
            and isinstance(v, list)
            and isinstance(dst.get(k), list)
        ):
            dst[k] = _merge_option_array(dst[k], v)
        elif k == "series" and isinstance(v, list):
            # series 首次出现（dst 侧还不是 list）：逐项拷贝并包装大数组。
            # 少了这一支，默认的合并模式会把整个 series 深拷贝一遍 ——
            # 而首次注入的那份数据正是最该零拷贝的。
            dst[k] = [_copy_series_entry(s) for s in v]
        elif isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge_option(dst[k], v)
        else:
            dst[k] = _hold_value(v)
    return dst


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


# ---------------------------------------------------------------------------
# 系列渲染器协议
# ---------------------------------------------------------------------------


class SeriesRenderer:
    """系列渲染器协议基类。

    子类实现 ``layout(rect)`` / ``paint(p, anim_t)`` / ``hitTest(pos)``。
    坐标映射经 ``self.chart.coordFor(self.opt)`` 取得 Coord 后
    ``coord.mapPoint(x, y)``。

    可选扩展：
    - ``valueAtIndex(index)`` → dict（{"name","value","series","color"}），
      供 tooltip axis 触发取数；
    - ``self.prev_data``：上次 option 前的旧 data 列表（core 自动注入），
      用于旧→新插值动画。
    """

    def __init__(self, chart: "ElaChartWidget", opt: dict):
        self.chart = chart
        self.opt = dict(opt or {})
        self.name = str(self.opt.get("name") or "")
        #: ECharts ``series.id``（setOption 合并时的身份匹配键）
        self.id = str(self.opt.get("id") or "")
        #: 系列显隐（legend 点击切换；初始状态由 widget 按 legend.selected 注入）
        self.visible = True
        #: **最近一次绘制所用的动画进度**（core 在 paint / 命中分发前写入）。
        #: ``hitTest`` 靠它判断「现在是否处于动画中」，见该方法 docstring。
        self._anim_t = 1.0
        #: 上次 option 的旧数据（core 注入，用于动画插值）
        self.prev_data = None
        #: itemStyle 均匀性缓存 (key, {} | None)，见 ``uniformItemStyle``
        self._uniform_style_cache = None

    # -- 协议 ------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        """计算几何（坐标映射经 coord）。"""

    def paint(self, p: QPainter, anim_t: float) -> None:
        """绘制。anim_t ∈ [0,1]，入场 / 更新动画进度。"""
        raise NotImplementedError

    def hitTest(self, pos: QPointF):
        """命中检测 → ``{"name","value","series",...}`` 或 None。

        **默认实现在动画期一律返回 None**：``anim_t`` 是绘制期变量，而子类的
        几何来自 ``layout()``（终态），用终态几何命中会指到「动画结束后才会到
        的位置」—— 用户看到的是高亮 / tooltip 落在错误的图元上。想支持动画期
        命中的子类在自己的 ``hitTest`` 里用 ``self._anim_t`` 复算几何即可。
        完整规则与已实现清单见 AGENTS.md「charts」。
        """
        if self._anim_t < 1.0:
            return None
        return None

    # -- 辅助 ------------------------------------------------------------
    @property
    def silent(self) -> bool:
        """ECharts ``series.silent``：True 时不响应鼠标命中（tooltip / click）。"""
        return bool(self.opt.get("silent", False))

    def animProgress(self, t: float) -> float:
        """系列动画进度：``series.animation=false`` 时直接呈现终态。"""
        if self.opt.get("animation", True) is False:
            return 1.0
        return t

    def data(self) -> list:
        """系列原始 data 列表（None 容灾）。

        接受两种承载：``list``（默认）与 ``ElaNumericBuffer``（大数组零拷贝
        摄入的产物，见 ``charts.data``）。**不能只认 list** ——``setOption``
        会把大数值数组包成缓冲区，只认 list 会让整条曲线静默消失。

        返回值对外语义与 list 一致（``Sequence``：可 ``len`` / 下标 / 迭代 /
        与 list 比较），既有的 40 余处只读调用点无需改动。内部热路径
        （``layout`` / 采样 / 范围统计）请用 :meth:`dataView`，它不做任何
        list 化。

        **裸 ndarray 会就地包成 ``ElaNumericBuffer`` 再返回**，因为 ndarray 的
        ``__eq__`` 不返回 bool：``if renderer.data() == other:`` 会在它上面抛
        ``ValueError: The truth value of an array ... is ambiguous``，而这行
        常出现在 Qt 回调里 = 0xC0000409。``ElaNumericBuffer`` 的 ``__eq__``
        走 list 比较，契约与返回值宣称的一致。短数组（< ``_BUFFER_MIN_LEN``）
        不包装，所以裸 ndarray 确实会到这里。
        """
        d = self.opt.get("data")
        if isinstance(d, list):
            return d
        if isinstance(d, _cdata.ElaNumericBuffer):
            return d
        if _cdata.isBufferLike(d):
            # 包一次并**写回 opt**：`_data_ref` 等调用方要求同一 data 对象
            # 反复拿到的是同一实例（采样缓存键含 id(data)，每次新建包装件会让
            # 键每帧变化 → 降采样缓存永不命中，布局耗时 22 倍）。
            wrapped = _cdata.ElaNumericBuffer(d)
            self.opt["data"] = wrapped
            return wrapped
        return []

    def dataView(self):
        """系列数据的**只读视图**（内部热路径专用，不做任何拷贝）。

        与 :meth:`data` 判据相同但语义更明确：返回的就是 ``opt["data]``
        本身，不做任何 list 化。内部热路径（``layout`` / 采样 / 范围统计）
        统一走这里。
        """
        d = self.opt.get("data")
        if isinstance(d, list) or _cdata.isBufferLike(d):
            return d
        return []

    def color(self) -> QColor:
        """系列主色（``itemStyle.color`` 覆盖 → option color → 全局调色板）。"""
        raw = self.itemStyle().get("color")
        if isinstance(raw, str) and raw:
            color = QColor(raw)
            if color.isValid():
                return color
        return self.chart.colorForSeries(self)

    # -- itemStyle / label / emphasis（ECharts 通用键） --------------------
    def itemStyle(self) -> dict:
        """系列级 ``itemStyle``（非 dict 时返回空 dict）。"""
        style = self.opt.get("itemStyle")
        return style if isinstance(style, dict) else {}

    @staticmethod
    def itemStyleOf(item) -> dict:
        """数据项级 ``itemStyle``（``{"value": ..., "itemStyle": {...}}``）。"""
        if isinstance(item, dict):
            style = item.get("itemStyle")
            if isinstance(style, dict):
                return style
        return {}

    def uniformItemStyle(self):
        """系列级统一 ``itemStyle``；``None`` = 存在逐项 itemStyle。

        **O(1) 判据是「容器类型」而非抽样** —— 紧凑数值容器必是纯数值序列，
        ``list`` 必须全量扫（带 dict 项的列表本就不是百万级场景）。原先的
        32 项探窗会静默漏掉 ``[1]*500 + [{"itemStyle": …}]``，见 AGENTS.md
        「charts」。
        """
        data = self.opt.get("data")
        try:
            n = len(data)
        except TypeError:
            n = 0
        key = (id(self.opt), id(data), n)
        hit = self._uniform_style_cache
        if hit is not None and hit[0] == key:
            return hit[1]
        # 紧凑数值容器：元素类型在包装时已校验，必定没有逐项 itemStyle
        if n and _cdata.isBufferLike(data):
            self._uniform_style_cache = (key, {})
            return {}
        result = {}
        if n:
            for i in range(n):
                item = data[i]
                if isinstance(item, dict) and isinstance(item.get("itemStyle"), dict):
                    result = None
                    break
        self._uniform_style_cache = (key, result)
        return result

    def _itemStyleFor(self, index):
        """取某下标的项级 ``itemStyle``（走 ``uniformItemStyle`` 快路径）。"""
        uniform = self.uniformItemStyle()
        if uniform is not None:
            return uniform
        item = None
        data = self.data()
        if isinstance(index, int) and 0 <= index < len(data):
            item = data[index]
        return self.itemStyleOf(item)

    def uniformItemStyleResolved(self) -> dict:
        """一次性解析「全系列统一」的外观，供绘制循环**循环外**取用。

        返回 ``{"color": QColor|None, "opacity": float, "borderColor": ...,
        "borderWidth": float, "borderRadius": float|None}``。仅当
        ``uniformItemStyle()`` 判定为均匀时可用（否则返回 ``None``）。

        用途：bar / scatter 逐图元绘制时，若每根柱子都调
        ``itemColor`` / ``itemOpacity`` / ``itemBorder`` / ``_bar_radius``，
        素材多时就是每图元 4 次方法调用。绘制循环外解析一次，
        循环内只做数组取值即可。
        """
        if self.uniformItemStyle() is None:
            return None
        style = self.itemStyle()
        raw_color = style.get("color")
        color = None
        if isinstance(raw_color, str) and raw_color:
            c = QColor(raw_color)
            if c.isValid():
                color = c
        raw_border = style.get("borderColor")
        border = None
        if isinstance(raw_border, str) and raw_border:
            c = QColor(raw_border)
            if c.isValid():
                border = c
        try:
            opacity = max(0.0, min(1.0, float(style.get("opacity", 1.0))))
        except (TypeError, ValueError, OverflowError):
            opacity = 1.0
        try:
            border_width = max(0.0, float(style.get("borderWidth", 0)))
        except (TypeError, ValueError, OverflowError):
            border_width = 0.0
        raw_radius = style.get("borderRadius")
        radius = None
        if raw_radius is not None:
            if isinstance(raw_radius, (list, tuple)):
                raw_radius = max((_to_float(v, 0.0) for v in raw_radius), default=0.0)
            radius = max(0.0, _to_float(raw_radius, 0.0))
        return {
            "color": color,
            "opacity": opacity,
            "borderColor": border,
            "borderWidth": border_width,
            "borderRadius": radius,
        }

    def itemColor(self, index=None, default=None) -> QColor:
        """数据项颜色：项 ``itemStyle.color`` → 系列 ``itemStyle.color``
        → ``default`` → 全局调色板。"""
        raw = self._itemStyleFor(index).get("color") or self.itemStyle().get("color")
        if isinstance(raw, str) and raw:
            color = QColor(raw)
            if color.isValid():
                return color
        if default is not None:
            return QColor(default)
        return self.color()

    def itemOpacity(self, index=None) -> float:
        """数据项透明度：项 ``itemStyle.opacity`` → 系列 ``itemStyle.opacity``（默认 1）。"""
        raw = self._itemStyleFor(index).get("opacity")
        if raw is None:
            raw = self.itemStyle().get("opacity")
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError, OverflowError):
            return 1.0

    def itemBorder(self, index=None):
        """数据项描边 → ``(QColor | None, width)``（未配置颜色返回 None）。"""
        style = self._itemStyleFor(index)
        series_style = self.itemStyle()
        raw = style.get("borderColor") or series_style.get("borderColor")
        width = style.get("borderWidth", series_style.get("borderWidth", 0))
        color = None
        if isinstance(raw, str) and raw:
            candidate = QColor(raw)
            if candidate.isValid():
                color = candidate
        try:
            width = max(0.0, float(width))
        except (TypeError, ValueError, OverflowError):
            width = 0.0
        return color, width

    # -- emphasis / blur 状态（ECharts 通用键） ---------------------------
    def emphasisOption(self) -> dict:
        """系列级 ``emphasis``（非 dict 时返回空 dict）。"""
        opt = self.opt.get("emphasis")
        return opt if isinstance(opt, dict) else {}

    def emphasisItemStyle(self, index=None) -> dict:
        """hover 高亮样式：系列 ``emphasis.itemStyle`` → 项 ``emphasis.itemStyle``。"""
        style = dict(self.emphasisOption().get("itemStyle") or {})
        item = None
        data = self.data()
        if isinstance(index, int) and 0 <= index < len(data):
            item = data[index]
        if isinstance(item, dict):
            item_emphasis = item.get("emphasis")
            if isinstance(item_emphasis, dict) and isinstance(
                item_emphasis.get("itemStyle"), dict
            ):
                style.update(item_emphasis["itemStyle"])
        return style

    def blurOption(self) -> dict:
        """系列级 ``blur``（非 dict 时返回空 dict）。"""
        opt = self.opt.get("blur")
        return opt if isinstance(opt, dict) else {}

    def blurItemStyle(self) -> dict:
        """非高亮项的淡化样式（``blur.itemStyle``）。"""
        style = self.blurOption().get("itemStyle")
        return style if isinstance(style, dict) else {}

    def emphasisColor(self, index=None):
        """hover 高亮色（``emphasis.itemStyle.color``）；未配置返回 None。"""
        raw = self.emphasisItemStyle(index).get("color")
        if isinstance(raw, str) and raw:
            color = QColor(raw)
            if color.isValid():
                return color
        return None

    def emphasisOpacity(self, index=None):
        """hover 高亮透明度（``emphasis.itemStyle.opacity``）；未配置 None。"""
        raw = self.emphasisItemStyle(index).get("opacity")
        if raw is None:
            return None
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError, OverflowError):
            return None

    def blurOpacity(self):
        """非高亮项透明度（``blur.itemStyle.opacity``）；未配置 None。"""
        raw = self.blurItemStyle().get("opacity")
        if raw is None:
            return None
        try:
            return max(0.0, min(1.0, float(raw)))
        except (TypeError, ValueError, OverflowError):
            return None

    def labelOption(self) -> dict:
        """系列级 ``label``（非 dict 时返回空 dict）。"""
        label = self.opt.get("label")
        return label if isinstance(label, dict) else {}

    def labelShown(self) -> bool:
        """是否显示数据标签（``label.show``）。"""
        return bool(self.labelOption().get("show", False))

    def labelColor(self) -> QColor:
        """标签颜色（``label.color`` → 次级文本色）。"""
        raw = self.labelOption().get("color")
        if isinstance(raw, str) and raw:
            color = QColor(raw)
            if color.isValid():
                return color
        return QColor(T("color.text.secondary"))

    def labelFontSize(self) -> float:
        """标签字号（``label.fontSize`` → font.xs）。"""
        try:
            return max(6.0, float(self.labelOption().get("fontSize", T("font.xs"))))
        except (TypeError, ValueError, OverflowError):
            return float(T("font.xs"))

    def labelText(self, index, value, name=None) -> str:
        """按 ``label.formatter`` 生成标签文本（缺省显示数值）。

        formatter 支持 callable(params) 或 ``{a}/{b}/{c}/{d}/{value}/{name}``
        模板（``{d}`` 需调用方在 params 中提供）。
        """
        formatter = self.labelOption().get("formatter")
        params = {
            "a": self.name,
            "b": name if name is not None else self.name,
            "c": value,
            "value": value,
            "name": name if name is not None else self.name,
            "series": self.name,
            "dataIndex": index,
        }
        if callable(formatter):
            try:
                text = formatter(params)
                return str(text) if text is not None else formatValue(value)
            except Exception:
                return formatValue(value)
        if isinstance(formatter, str):
            text = formatLabelTemplate(formatter, params)
            if text is not None:
                return text
        return formatValue(value)

    def valueAtIndex(self, index: int):
        """tooltip axis 触发：返回 {"name","value","series","color"} 或 None。"""
        return None

    def _sampling_params(self):
        """``sampling`` option 解析（折线 / 散点等大系列共用）。

        ECharts 语义：``sampling`` 可为 False / 字符串（``minmax`` / ``m4`` /
        ``lttb`` / ``minmaxLTTB``）/ dict
        {``algorithm``, ``threshold``, ``pointsPerPixel``}；返回
        ``(enabled, threshold, pointsPerPixel, algorithm)``。

        **这里只表达用户意图**（是否抽稀）——能不能抽由调用方的三层兜底决定
        （tsdownsample → numpy 按桶 min/max → 纯 Python 等距）。
        """
        sopt = self.opt.get("sampling", True)
        enabled = bool(sopt)
        threshold = 2000.0
        ppb = 2.0
        algo = "minmax"
        if isinstance(sopt, str):
            name = sopt.strip().lower()
            if name in ("false", "none", "off"):
                enabled = False
            elif name:
                algo = name
        elif isinstance(sopt, dict):
            threshold = _to_float(sopt.get("threshold"), threshold)
            ppb = _to_float(sopt.get("pointsPerPixel"), ppb)
            algo = str(sopt.get("algorithm") or algo)
        return enabled, max(2.0, threshold), max(0.5, ppb), algo

    def _full_index(self, index):
        """tooltip 局部下标 → 全量数据下标（dataZoom category 窗口偏移换算）。"""
        if not isinstance(index, int):
            return index
        coord = self.chart.coordFor(self.opt)
        axis = getattr(coord, "x_axis", None)
        if axis is not None and getattr(axis, "type", "") == "category":
            return index + axis.windowOffset()
        return index


# ---------------------------------------------------------------------------
# 动画驱动
# ---------------------------------------------------------------------------


class ChartAnimation(QObject):
    """0→1 进度动画（QVariantAnimation，缓出）。

    渲染器在 ``paint(p, anim_t)`` 中经 ``anim_t`` 插值。
    ``setProgress(v)`` 支持无事件循环环境（测试）手动推进。
    ``finished`` 在进度到达 1.0（动画播完或手动置满）后发射一次。
    """

    #: 一次入场 / 过渡动画播放完毕（ECharts ``finished`` 事件源）
    finished = pyqtSignal()

    def __init__(self, on_update=None, parent: QObject = None):
        super().__init__(parent)
        self._t = 0.0
        self._on_update = on_update
        self._finished_pending = False
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(ANIM_DURATION)
        self._anim.setEasingCurve(ANIM_EASING)
        self._anim.valueChanged.connect(self._on_value)

    @property
    def t(self) -> float:
        """当前进度 ∈ [0,1]。"""
        return self._t

    def start(self) -> None:
        """从头播放（setOption / 过渡动画时调用）。"""
        self._anim.stop()
        self._finished_pending = True
        self._anim.start()

    def stop(self) -> None:
        self._anim.stop()

    def complete(self) -> None:
        """直接置满进度并发射 ``finished``（``animation=false`` 路径）。"""
        self._anim.stop()
        self._finished_pending = True
        self._apply(1.0)

    def startResolved(self, full_ms: int, easing=None) -> bool:
        """按全局动效策略启动过渡，返回是否真的播放。

        本类**不用** :func:`pyqt6_ela_pro._motion.start_transition`：它没有 Qt 属性
        目标，收尾是在 ``_apply`` 里用 ``valueChanged`` 阈值判断的（``v >= 1.0``），
        不挂 ``QAbstractAnimation.finished`` —— 那个 helper 挂的正是后者。所以这里
        只借它的策略解析，落到本类自己的 ``complete()``（它本来就是正确的 snap）。
        """
        duration_ms, snap = motion.plan(full_ms, ElaMotionKindType.Transition)
        self.setDuration(duration_ms)
        self.setEasing(easing)
        if snap:
            self.complete()
            return False
        self.start()
        return True

    def setDuration(self, duration: int) -> None:
        """设置动画时长（ms，ECharts ``animationDuration``）。"""
        try:
            self._anim.setDuration(max(0, int(duration)))
        except (TypeError, ValueError, OverflowError):
            pass

    def setEasing(self, easing) -> None:
        """设置缓动曲线（QEasingCurve.Type）。"""
        if easing is not None:
            self._anim.setEasingCurve(easing)

    def isRunning(self) -> bool:
        return self._anim.state() == QAbstractAnimation.State.Running

    def setProgress(self, v: float) -> None:
        """手动设置进度并触发重绘回调（测试 / 无动画路径用）。"""
        self._apply(max(0.0, min(1.0, float(v))))

    def _on_value(self, v) -> None:
        self._apply(float(v))

    def _apply(self, v: float) -> None:
        self._t = v
        if callable(self._on_update):
            self._on_update()
        if v >= 1.0 and self._finished_pending:
            self._finished_pending = False
            self.finished.emit()


# ---------------------------------------------------------------------------
# 标题组件
# ---------------------------------------------------------------------------


class Title:
    """标题组件（ECharts ``title``）。

    option：``text`` / ``subtext`` / ``left`` / ``top`` / ``right`` / ``bottom`` /
    ``itemGap`` / ``textStyle``（color/fontSize/fontWeight）/
    ``subtextStyle``（color/fontSize）。

    默认占画布顶部条带；指定 ``bottom``（且未指定 ``top``）时改占底部条带，
    ``top`` / ``bottom`` / ``left`` / ``right`` 支持数值 px 或 ``"N%"``。
    """

    def __init__(self, opt: dict = None):
        self.opt = dict(opt or {})

    def setOption(self, opt: dict) -> None:
        self.opt = dict(opt or {})

    @property
    def text(self) -> str:
        return str(self.opt.get("text") or "")

    @property
    def subtext(self) -> str:
        return str(self.opt.get("subtext") or "")

    def textStyle(self) -> dict:
        style = self.opt.get("textStyle")
        return style if isinstance(style, dict) else {}

    def subtextStyle(self) -> dict:
        style = self.opt.get("subtextStyle")
        return style if isinstance(style, dict) else {}

    def itemGap(self) -> float:
        try:
            return max(0.0, float(self.opt.get("itemGap", 2)))
        except (TypeError, ValueError, OverflowError):
            return 2.0

    @property
    def atBottom(self) -> bool:
        """是否使用底部条带（指定 bottom 且未指定 top）。"""
        return "bottom" in self.opt and "top" not in self.opt

    def height(self) -> float:
        """标题区总高（无 text 时为 0）。"""
        if not self.text:
            return 0.0
        h = _opt_float(self.textStyle().get("fontSize"), T("font.title.md")) * 1.3 + 6
        if self.subtext:
            h += _opt_float(self.subtextStyle().get("fontSize"), T("font.sm")) * 1.5 + 2
        return h + 4

    def bandRect(self, width: float, height: float) -> QRectF:
        """标题条带（画布坐标）；无标题返回空矩形。"""
        h = self.height()
        if h <= 0:
            return QRectF()
        w = max(0.0, float(width))
        if self.atBottom:
            offset = _anchor_px(self.opt.get("bottom"), float(height), 0.0)
            return QRectF(0, float(height) - offset - h, w, h)
        offset = _anchor_px(self.opt.get("top"), float(height), 0.0)
        return QRectF(0, offset, w, h)

    def paint(self, p: QPainter, rect: QRectF) -> None:
        """在标题条带 rect 内绘制。"""
        if not self.text or rect.height() <= 0:
            return
        p.save()
        style = self.textStyle()
        sub_style = self.subtextStyle()
        title_font = chartFont(
            _opt_float(style.get("fontSize"), T("font.title.md")),
            style.get("fontWeight", T("font.weight.semibold")),
        )
        sub_font = chartFont(
            _opt_float(sub_style.get("fontSize"), T("font.sm")),
            sub_style.get("fontWeight", 400),
        )
        fm_t = QFontMetricsF(title_font)
        fm_s = QFontMetricsF(sub_font)
        text_w = fm_t.horizontalAdvance(self.text)
        sub_w = fm_s.horizontalAdvance(self.subtext) if self.subtext else 0.0
        w = max(text_w, sub_w)
        x = self._anchor_x(rect, w)
        gap = self.itemGap()
        y = rect.top() + 2
        p.setFont(title_font)
        p.setPen(QColor(style.get("color") or T("color.text.primary")))
        p.drawText(
            QRectF(x, y, text_w + 4, fm_t.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.text,
        )
        if self.subtext:
            y += fm_t.height() + gap
            p.setFont(sub_font)
            p.setPen(QColor(sub_style.get("color") or T("color.text.secondary")))
            p.drawText(
                QRectF(x, y, sub_w + 4, fm_s.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.subtext,
            )
        p.restore()

    def _anchor_x(self, rect: QRectF, text_w: float) -> float:
        """水平锚点：``left`` / ``right``（数值 px、"N%" 或 center/right 对齐）。"""
        left = self.opt.get("left")
        right = self.opt.get("right")
        if left is not None:
            if str(left).strip().lower() == "center":
                return rect.center().x() - text_w / 2
            if str(left).strip().lower() == "right":
                return rect.right() - text_w - 8
            return rect.left() + _anchor_px(left, rect.width(), 8.0)
        if right is not None:
            if str(right).strip().lower() == "center":
                return rect.center().x() - text_w / 2
            return rect.right() - _anchor_px(right, rect.width(), 8.0) - text_w
        return rect.left() + 8.0


# ---------------------------------------------------------------------------
# 图例组件
# ---------------------------------------------------------------------------


class Legend:
    """图例组件（ECharts ``legend``）。

    option：``show`` / ``orient`` / ``top|bottom|left|right`` / ``data``
    （条目白名单与排序）/ ``selected``（{name: bool} 初始显隐）/ ``itemWidth`` /
    ``itemHeight`` / ``itemGap`` / ``textStyle`` / ``selectedMode``
    （``"multiple"`` 默认 / ``"single"``）。条目由 ElaChartWidget 按系列名
    注入（``setItems([(name, color), ...])``，color 仅为兜底值）——绘制时
    色块经 chart 实时取系列当前色，主题切换后无需重建即生效。
    ``type: "scroll"`` 未实现滚动分页，按 plain 降级（首次告警）。
    """

    #: 条目点击回调：chart 注入 ``legend.on_toggle = chart._legendSelectToggle``
    on_toggle = None

    def __init__(self, chart: "ElaChartWidget", opt: dict = None):
        self.chart = chart
        self.opt = {"show": True, "orient": "horizontal"}
        self.setOption(opt)
        self._items = []  # [(name, QColor)]（已按 legend.data 过滤排序）
        self._all_items = []  # [(name, QColor)]（未过滤）
        self._item_rects = []  # [QRectF] 与 _items 对齐
        self.rect = QRectF()

    def setOption(self, opt: dict) -> None:
        if isinstance(opt, dict):
            merged = {"show": True, "orient": "horizontal"}
            merged.update(opt)
            self.opt = merged
        else:
            self.opt = {"show": True, "orient": "horizontal"}

    def setItems(self, items: list) -> None:
        self._all_items = [(str(n), c) for n, c in (items or []) if str(n)]
        data = self.opt.get("data")
        if isinstance(data, list) and data:
            wanted = [str(n) for n in data]
            by_name = dict(self._all_items)
            self._items = [(n, by_name[n]) for n in wanted if n in by_name]
        else:
            self._items = list(self._all_items)

    # -- option 取值 -------------------------------------------------------
    def itemWidth(self) -> float:
        try:
            return max(2.0, float(self.opt.get("itemWidth", 9)))
        except (TypeError, ValueError, OverflowError):
            return 9.0

    def itemHeight(self) -> float:
        try:
            return max(2.0, float(self.opt.get("itemHeight", 9)))
        except (TypeError, ValueError, OverflowError):
            return 9.0

    def itemGap(self) -> float:
        try:
            return max(2.0, float(self.opt.get("itemGap", 10)))
        except (TypeError, ValueError, OverflowError):
            return 10.0

    def textStyle(self) -> dict:
        style = self.opt.get("textStyle")
        return style if isinstance(style, dict) else {}

    def _font(self):
        size = _opt_float(self.textStyle().get("fontSize"), T("font.xs"))
        return chartFont(size)

    def selectedMode(self) -> str:
        mode = str(self.opt.get("selectedMode") or "multiple")
        return "single" if mode == "single" else "multiple"

    def _item_color(self, name: str):
        """条目实时色：按系列名从 chart 当前渲染器取色（主题感知），
        找不到渲染器时返回 None（调用方退回 setItems 的兜底色）。"""
        for r in self.chart.seriesRenderers:
            if r.name == name:
                return r.color()
        return None

    @property
    def shown(self) -> bool:
        return bool(self.opt.get("show", True)) and bool(self._items)

    @property
    def orient(self) -> str:
        return "vertical" if str(self.opt.get("orient")) == "vertical" else "horizontal"

    # -- 布局 -------------------------------------------------------------
    def _entry(self, name: str):
        """单条目的 (宽, 高) 与字体。"""
        font = self._font()
        fm = QFontMetricsF(font)
        iw, ih = self.itemWidth(), self.itemHeight()
        h = max(18.0, fm.height() + 6, ih + 6)
        w = iw + 6 + fm.horizontalAdvance(name) + self.itemGap()
        return w, h

    def preferredSize(self, avail_w: float, avail_h: float):
        """按可用空间返回 (w, h)：横向为整行高度，纵向为列宽。"""
        if not self.shown:
            return 0.0, 0.0
        if self.orient == "horizontal":
            h = max((self._entry(n)[1] for n, _ in self._items), default=0.0)
            return avail_w, h + 4
        w = max((self._entry(n)[0] for n, _ in self._items), default=0.0)
        return w, avail_h

    def layout(self, rect: QRectF) -> None:
        """在已分配条带 rect 内排布条目（横向居中 / 纵向顶对齐）。"""
        self.rect = QRectF(rect)
        self._item_rects = []
        if not self.shown or rect.isNull():
            return
        font = self._font()
        fm = QFontMetricsF(font)
        entry_h = max(18.0, fm.height() + 6)
        if self.orient == "horizontal":
            gap = self.itemGap()
            total = sum(self._entry(n)[0] for n, _ in self._items) - gap
            x = rect.left() + max(0.0, (rect.width() - total) / 2)
            y = rect.top() + (rect.height() - entry_h) / 2
            for name, _ in self._items:
                w, _ = self._entry(name)
                self._item_rects.append(QRectF(x, y, w - gap, entry_h))
                x += w
        else:
            x = rect.left() + 4
            y = rect.top() + 4
            for name, _ in self._items:
                w, _ = self._entry(name)
                self._item_rects.append(QRectF(x, y, w - self.itemGap(), entry_h))
                y += entry_h + 2

    # -- 交互 -------------------------------------------------------------
    def hitTest(self, pos: QPointF):
        """命中条目名或 None。"""
        for (name, _), r in zip(self._items, self._item_rects):
            if r.contains(pos):
                return name
        return None

    def toggle(self, name: str) -> None:
        if callable(self.on_toggle):
            self.on_toggle(name)

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter) -> None:
        if not self.shown or not self._item_rects:
            return
        p.save()
        font = self._font()
        p.setFont(font)
        style = self.textStyle()
        iw, ih = self.itemWidth(), self.itemHeight()
        for (name, fallback), r in zip(self._items, self._item_rects):
            enabled = self.chart._seriesVisible(name)
            live = self._item_color(name) if enabled else None
            swatch = QColor(live) if live is not None else QColor(fallback)
            if not enabled:
                swatch = QColor(T("color.text.disabled"))
            text_c = QColor(
                style.get("color") or T("color.text.primary")
                if enabled
                else T("color.text.disabled")
            )
            # 悬停高亮：该条目文字转强调色（对齐 Plotly 图例 hover）
            if enabled and self.chart._legend_hover == name:
                text_c = QColor(T("color.primary"))
            # 色块（圆角小方块）
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(swatch)
            box = QRectF(r.left(), r.center().y() - ih / 2, iw, ih)
            p.drawRoundedRect(box, 2, 2)
            p.setPen(text_c)
            p.drawText(
                QRectF(box.right() + 6, r.top(), r.width() - iw - 6, r.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name,
            )
        p.restore()


# ---------------------------------------------------------------------------
# 提示框组件
# ---------------------------------------------------------------------------


def _default_tooltip_title(raw) -> str:
    """ISO 日期 → 中文日期（``"2026-09-02"`` → ``"2026年9月2日"``）。"""
    text = str(raw or "")
    parts = text.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{int(parts[0])}年{int(parts[1])}月{int(parts[2])}日"
    return text


class Tooltip:
    """提示框组件（ECharts ``tooltip``）。

    - ``show`` / ``trigger``（``"item"`` 默认 / ``"axis"`` / ``"none"``）；
    - ``formatter``：callable(params) 或 ``{a}/{b}/{c}`` 模板；callable 返回
      字符串，或 ``[标题, 内容]``（标题行无圆点，扩展约定）；
    - ``valueFormatter``：callable(value) 或含 ``{value}`` 的模板，作用于
      默认内容中的数值；
    - ``axisPointer.type``：``"line"`` / ``"shadow"`` / ``"cross"`` / ``"none"``；
    - 样式：``backgroundColor`` / ``borderColor`` / ``borderWidth`` /
      ``textStyle``（color/fontSize）。
    """

    def __init__(self, chart: "ElaChartWidget", opt: dict = None):
        self.chart = chart
        self.opt = {"show": True, "trigger": "item"}
        self.setOption(opt)
        self._active = False
        self._pos = QPointF()  # 鼠标位置（跟随）
        self._marker_pos = None  # 十字线锚点（None 用 _pos）
        self._lines = []  # [(QColor, name, value_str)]

    def setOption(self, opt: dict) -> None:
        if isinstance(opt, dict):
            merged = {"show": True, "trigger": "item"}
            merged.update(opt)
            self.opt = merged
        else:
            self.opt = {"show": True, "trigger": "item"}

    # -- option 取值 -------------------------------------------------------
    def textStyle(self) -> dict:
        style = self.opt.get("textStyle")
        return style if isinstance(style, dict) else {}

    def axisPointerType(self) -> str:
        ap = self.opt.get("axisPointer")
        kind = (
            str((ap or {}).get("type") or "cross") if isinstance(ap, dict) else "cross"
        )
        return kind if kind in ("line", "shadow", "cross", "none") else "cross"

    def formatValueText(self, value) -> str:
        """按 ``valueFormatter`` 渲染数值（缺省走 ``formatValue``）。"""
        formatter = self.opt.get("valueFormatter")
        if callable(formatter):
            try:
                out = formatter(value)
                if out is not None:
                    return str(out)
            except Exception:
                pass
        elif isinstance(formatter, str):
            try:
                return formatter.format_map(defaultdict(str, {"value": value}))
            except Exception:
                pass
        return formatValue(value)

    @staticmethod
    def _safe_format(template: str, params: dict) -> Optional[str]:
        """``{}`` 模板安全替换（缺失键 → 空串；失败返回 None）。"""
        try:
            return template.format_map(defaultdict(str, params))
        except Exception:
            return None

    def buildLines(self, hit: dict, color, fallback_name: str = "") -> list:
        """命中结果 → 浮层行 ``[(color, name, value_str), ...]``。

        标题行走 ``(None, "", 标题)``（无圆点），内容行走 ``(color, "", 文本)``
        （带系列色圆点）。命中方可给 ``hit["rows"]``（``[(名称, 值), ...]``）
        让默认排版渲染**多行**（雷达的逐维度行）；``formatter`` 输出仍然优先。
        """
        name = str(hit.get("name") or hit.get("series") or fallback_name)
        series = str(hit.get("series") or fallback_name)
        value = hit.get("value")
        title_raw = hit.get("title")
        text_raw = hit.get("text")
        params = {
            "name": name,
            "series": series,
            "seriesName": series,
            "value": value,
            "dataIndex": hit.get("dataIndex"),
            "title": title_raw,
            "text": text_raw,
            "b": name,
            "a": series,
            "c": value,
        }
        title: Optional[str] = None
        if title_raw is not None:
            title = _default_tooltip_title(title_raw)
        text: Optional[str] = None
        # 数据项 tooltip.formatter 优先于系列 tooltip.formatter（ECharts 语义）
        formatter = hit.get("tooltipFormatter")
        if formatter is None:
            formatter = self.opt.get("formatter")
        formatted = None
        if callable(formatter):
            try:
                formatted = formatter(params)
            except Exception:
                formatted = None
        elif isinstance(formatter, str):
            formatted = self._safe_format(formatter, params)
        if formatted is not None:
            parts = [
                str(part)
                for part in (
                    formatted if isinstance(formatted, (list, tuple)) else [formatted]
                )
            ]
            if len(parts) >= 2:
                if title is None:
                    title = parts[0]
                text = parts[1]
            elif parts:
                text = parts[0]
        lines = []
        if title:
            lines.append((None, "", title))
        rows = hit.get("rows")
        if text:
            lines.append((color, "", text))
        elif formatted is None and isinstance(rows, (list, tuple)) and rows:
            # 命中方提供的结构化多行（雷达的「指标: 值」逐维度行）。
            # 有 formatter 输出时 formatter 优先（ECharts：formatter 覆盖默认排版）。
            for row in rows:
                if not isinstance(row, (list, tuple)) or len(row) != 2:
                    continue
                lines.append((color, str(row[0]), self.formatValueText(row[1])))
        elif value is not None:
            lines.append((color, name, self.formatValueText(value)))
        return lines

    @property
    def shown(self) -> bool:
        return bool(self.opt.get("show", True))

    @property
    def trigger(self) -> str:
        raw = str(self.opt.get("trigger") or "item")
        return raw if raw in ("item", "axis", "none") else "item"

    @property
    def active(self) -> bool:
        return self._active and bool(self._lines)

    # -- 状态 -------------------------------------------------------------
    def showAt(self, pos: QPointF, lines: list, marker_pos: QPointF = None) -> None:
        """显示浮层。lines: [(color, name, value_str), ...]。"""
        self._active = True
        self._pos = QPointF(pos)
        self._marker_pos = QPointF(marker_pos) if marker_pos is not None else None
        self._lines = list(lines or [])

    def hide(self) -> None:
        self._active = False
        self._lines = []

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter) -> None:
        if not self.shown or not self.active:
            return
        # 十字线 / 指示线（axisPointer.type）
        marker = self._marker_pos if self._marker_pos is not None else self._pos
        coord = self.chart.primaryCoord()
        if coord is not None and self.axisPointerType() != "none":
            coord.paintTooltipMarker(p, marker, self.axisPointerType())

        p.save()
        style = self.textStyle()
        font = chartFont(float(style.get("fontSize", T("font.xs"))))
        p.setFont(font)
        fm = QFontMetricsF(font)
        pad_x, pad_y, line_gap, dot = 10.0, 8.0, 3.0, 8.0
        line_h = fm.height()
        rows = []
        for color, name, value in self._lines:
            label = f"{name}: {value}" if name else str(value)
            rows.append((color, label))
        text_w = max((fm.horizontalAdvance(t) for _, t in rows), default=0.0)
        w = pad_x * 2 + (dot + 5 if any(c is not None for c, _ in rows) else 0) + text_w
        h = pad_y * 2 + len(rows) * line_h + max(0, len(rows) - 1) * line_gap
        # 跟随鼠标：右侧偏移，越界翻转 / 收敛
        area = QRectF(0, 0, self.chart.width(), self.chart.height())
        x = self._pos.x() + 14
        y = self._pos.y() + 14
        if x + w > area.right() - 4:
            x = self._pos.x() - w - 14
        if y + h > area.bottom() - 4:
            y = self._pos.y() - h - 14
        x = min(max(x, 4.0), max(4.0, area.right() - w - 4))
        y = min(max(y, 4.0), max(4.0, area.bottom() - h - 4))
        box = QRectF(x, y, w, h)
        radius = float(T("radius.md"))
        # 近似阴影：三层外扩低透明度圆角矩形
        shadow_c = QColor(T("color.text.primary"))
        for i, alpha in ((6, 16), (4, 22), (2, 30)):
            sc = QColor(shadow_c)
            sc.setAlpha(alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(sc)
            p.drawRoundedRect(
                box.translated(0, 2).adjusted(-i / 2, -i / 2, i / 2, i / 2),
                radius + i / 2,
                radius + i / 2,
            )
        # 浮层本体（ECharts 样式键 → 主题兜底）
        bg = self.opt.get("backgroundColor")
        border = self.opt.get("borderColor")
        try:
            border_w = max(0.0, float(self.opt.get("borderWidth", 1)))
        except (TypeError, ValueError, OverflowError):
            border_w = 1.0
        if border_w > 0:
            p.setPen(QPen(QColor(border or T("color.border")), border_w))
        else:
            p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(bg) if bg else QColor(T("color.bg.elevated")))
        p.drawRoundedRect(box, radius, radius)
        # 文本行（缩进仅对带圆点的行生效；标题行 color 为 None 不缩进）
        text_color = QColor(style.get("color") or T("color.text.primary"))
        ty = box.top() + pad_y
        for color, label in rows:
            tx = box.left() + pad_x
            if color is not None:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(color))
                p.drawEllipse(QRectF(tx, ty + line_h / 2 - dot / 2, dot, dot))
                tx += dot + 5
            p.setPen(text_color)
            p.drawText(
                QRectF(tx, ty, box.right() - pad_x - tx, line_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            ty += line_h + line_gap
        p.restore()


# ---------------------------------------------------------------------------
# 图表主控件
# ---------------------------------------------------------------------------


class ElaChartWidget(QWidget):
    """类 ECharts 图表控件（Ela 主题感知，纯 QPainter 自绘）。

    用法::

        chart = ElaChartWidget(parent)
        chart.setOption({"title": {"text": "销量"},
                          "xAxis": {"type": "category", "data": ["一", "二"]},
                          "series": [{"type": "line", "name": "A", "data": [3, 5]}]})
        chart.setOption({"series": [{"data": [4, 6]}]})  # ECharts 合并语义
        chart.on("click", lambda p: print(p["seriesName"]))

    ECharts 实例 API：``setOption``（默认合并）/ ``getOption`` / ``resize`` /
    ``dispatchAction`` / ``on``&``off`` / ``convertToPixel`` /
    ``convertFromPixel`` / ``containPixel`` / ``showLoading``&``hideLoading`` /
    ``getDataURL`` / ``appendData`` / ``clear`` / ``dispose``&``isDisposed``。

    resizeEvent 自动重排；构造时连接 ``eTheme.themeModeChanged``，
    主题切换后实时换肤重绘（配色经 ``_tokens.T`` 逐帧取色）。

    性能：``_layout_all`` 带布局缓存 + 脏标记，悬停 / 无动画重绘不再
    全量重排；动画进行中按历史行为每帧重算。
    """

    #: 图例切换系列显隐：(系列名, 是否可见)
    legendToggled = pyqtSignal(str, bool)
    #: dataZoom 窗口变化：(start, end)，0-100 百分比
    dataZoomChanged = pyqtSignal(float, float)
    #: timeline 帧切换：帧下标
    timelineChanged = pyqtSignal(int)
    #: 数据项点击（ECharts click params）：见 ``_make_item_params``
    itemClicked = pyqtSignal(dict)
    #: toolbox 动作触发：动作名（saveAsImage / restore / dataZoom）
    toolboxTriggered = pyqtSignal(str)
    #: brush 选区变化：选中数据点列表（空列表 = 清除选区）
    brushChanged = pyqtSignal(list)
    #: 动画播放完毕（ECharts ``finished`` 事件）
    finished = pyqtSignal()

    #: ECharts 事件名 → 内部转发（``on``/``off`` 用）
    _ECHARTS_EVENTS = (
        "click",
        "legendselectchanged",
        "datazoom",
        "timelinechanged",
        "brushselected",
        "restore",
        "highlight",
        "downplay",
        "finished",
    )

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 150)
        self._option = {}
        self._series = []  # [SeriesRenderer]
        self._coords = []  # [Coord]
        self._components = []  # [组件实例]
        self._series_state = {}  # name -> bool（legend selected 状态）
        #: 调色板缓存 (key, list[QColor])，key = (主题模式, 自定义色板 id, 长度)
        self._palette_cache = None
        #: itemStyle 均匀性缓存 (key, {} | None)，见 ``uniformItemStyle``
        self._uniform_style_cache = None
        #: 系列层位图缓存 (key, QImage)，见 ``_paint_series_cached``
        self._series_pixmap_cache = None
        self._series_pixmap_key = None
        #: 交互开关：总开关 + 逐功能开关（缺失 = 启用）
        self._interactive = True
        self._feature_flags: dict = {}
        #: 当前悬停命中 (renderer, hit)：emphasis 高亮用
        self._hover = None
        self._opt_version = 0  # option 版本号（setOption 递增）
        self._layout_key = None  # 布局缓存键（脏标记）
        #: 渲染器内部几何状态的版本号（``invalidateLayout()`` 递增）。
        #: 进 ``_series_layer_key`` —— 少了它，下钻 / roam 之后系列层位图
        #: 会被原样贴回（见该方法 docstring）。
        self._geometry_epoch = 0
        #: 生命周期 / ECharts 事件
        self._disposed = False
        self._event_handlers: dict = {}
        #: 双击复位视图（Plotly ``doubleClick: 'reset'`` 语义，默认开）
        self._double_click_reset = True
        #: 图例悬停高亮的系列名（None = 无）
        self._legend_hover = None
        #: 本次按下的 (位置, 是否被拖拽组件吞掉)——松开时判「点击 vs 拖拽」
        self._press_ctx = None
        #: 直角坐标图默认内置缩放平移（无 dataZoom 时自动挂 inside 组件）
        self._wheel_zoom_enabled = bool(self.WHEEL_ZOOM_DEFAULT)
        #: lazyUpdate 延迟重建标记
        self._lazy_pending = False
        #: 宿主经 ``addComponent`` 注入的组件（跨 ``setOption`` 存活，见该方法）
        self._host_components: list = []
        #: timeline 基线快照（``options`` 帧切换用；core 内部维护）
        self._timeline_base = None
        #: loading 遮罩（showLoading / hideLoading）
        self._loading = False
        self._loading_opts: dict = {}
        self._spinner_angle = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self.title = Title()
        self.legend = Legend(self)
        self.tooltip = Tooltip(self)
        self.legend.on_toggle = self._legendSelectToggle
        self.anim = ChartAnimation(self.update, self)
        self.anim.finished.connect(self._on_animation_finished)
        self._chartEvent.connect(self._dispatch_chart_event)
        # 信号 → ECharts 事件转发
        self.legendToggled.connect(self._forward_legend_toggled)
        self.dataZoomChanged.connect(self._forward_data_zoom)
        self.timelineChanged.connect(self._forward_timeline_changed)
        self.itemClicked.connect(self._forward_click)
        self.brushChanged.connect(self._forward_brush_selected)
        self.toolboxTriggered.connect(self._forward_toolbox)
        # 主题连接走 _internal 的统一机制（两条防线：destroyed 上的模块级函数 +
        # 槽自身 ``is_deleted`` 自愈）。别在这里手写 eTheme.themeModeChanged.connect
        connect_theme_signal(self, self._on_theme_changed)

    def _disconnect_theme(self, *_args) -> None:
        """销毁路径显式断开主题单例信号连接。"""
        disconnect_theme(self)

    def deleteLater(self) -> None:
        self._disconnect_theme()
        super().deleteLater()

    # ---------------------------------------------------------------- API
    #: ECharts 事件名 → Qt 信号（``on``/``off`` 的转发源）
    _chartEvent = pyqtSignal(str, dict)

    def setOption(
        self, option: dict, notMerge: bool = False, lazyUpdate: bool = False
    ) -> "ElaChartWidget":
        """设置 option（ECharts ``setOption(option, notMerge, lazyUpdate)``）。

        - 默认 ``notMerge=False``：**合并**——dict 深合并；``series`` /
          ``dataZoom`` / ``graphic`` 数组按 ``id`` → ``name`` → 下标逐项合并
          （未匹配的旧项保留、新项追加）；其余 list 整体替换。
        - ``notMerge=True``：全量替换，并重置图例选择 / 悬浮态 / 提示框。
        - ``lazyUpdate=True``：合并立即生效，重建 / 重绘延迟到下一事件循环
          （合并多次调用，避免频繁重排）。
        - 旧系列数据注入新渲染器的 ``prev_data`` 供插值（name 优先、下标回退）；
          ``animation`` 关闭时跳过该快照（百万级物化纯浪费）。
        - **大数值数组按引用摄入**（``series[].data`` 会被包成
          ``ElaNumericBuffer``，见 ``charts.data``）：调用方在本次调用之后
          不得再原地修改该数组，否则图表会跟着变。改数据请重新 ``setOption``。

        :returns: self（支持链式调用）
        """
        if not isinstance(option, dict):
            option = {}
        prev_list, prev_by_name = self._capture_prev_data(option)
        if notMerge:
            # 先把大数值数组包成紧凑存储再存入：否则下面的深拷贝会把百万级
            # list 逐元素复制一遍（本机 100 万点约 60~95 ms）。
            self._option = _copy_option_shallow_arrays(option)
            self._series_state = {}
            self._timeline_base = None
            self.tooltip.hide()
            self._hover = None
        else:
            _merge_option(self._option, option)
        self._opt_version += 1
        if lazyUpdate:
            self._lazy_pending = True
            self._schedule_lazy_option()
        else:
            self._apply_option(prev_list, prev_by_name)
        return self

    def _capture_prev_data(self, new_option: dict):
        """捕获旧系列数据供过渡动画插值；动画关闭时**完全跳过**。

        ``list(r.data())`` 对百万级数据是一次完整物化（新建 N 个 Python
        float 对象），而它的唯一用途是 ``_start_animation`` 的插值 ——
        ``animation: False`` 时根本不读。故先判一次动画开关，省掉这次拷贝。

        :returns: ``(prev_list, prev_by_name)``；跳过时两者均为 ``None``
        """
        if not _animation_enabled(self._option, new_option):
            return None, None
        prev_list = [_snapshot_series_data(r) for r in self._series]
        prev_by_name = {
            r.name: prev_list[i] for i, r in enumerate(self._series) if r.name
        }
        return prev_list, prev_by_name

    def _schedule_lazy_option(self) -> None:
        """排一次延迟重建 —— **常驻子定时器**，不用无主 ``singleShot``。

        无主的 ``QTimer.singleShot(0, self._apply_lazy_option)`` 不随本对象
        销毁；而 ``lazyUpdate=True`` 的 ``setOption`` 可以连着调很多次，
        每次 new 一个子定时器会堆积，所以用同一个常驻的。
        """
        timer = self.__dict__.get("_lazy_timer")
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._apply_lazy_option)
            self._lazy_timer = timer
        timer.start(0)

    def _apply_lazy_option(self) -> None:
        """延迟重建（lazyUpdate）；对象已销毁时安全跳过。"""
        if self._disposed or is_deleted(self) or not self._lazy_pending:
            return
        self._lazy_pending = False
        prev_list, prev_by_name = self._capture_prev_data({})
        self._apply_option(prev_list, prev_by_name)

    def _capture_timeline_base(self) -> None:
        """捕获 timeline 基线：``baseOption``（优先）或除 ``options`` 外的顶层键。

        **整条 timeline 路径一律走 ``_copy_any``，不用 ``copy.deepcopy``。**
        后者会把 ``series[].data`` 里的百万点数组逐元素复制一遍，把「按引用
        摄入」的契约彻底绕过 —— 而 timeline 的基线捕获 + 每帧 apply 各来一次，
        于是**每切一帧就深拷贝整份数据**。``_copy_any`` 是深层拷贝但**在任意
        深度保留缓冲区**，语义相同、代价不同。
        """
        frames = self._option.get("options")
        if not isinstance(frames, list) or not frames:
            self._timeline_base = None
            return
        if self._timeline_base is None:
            base = self._option.get("baseOption")
            if isinstance(base, dict):
                merged = _copy_any(base)
                extra = {
                    k: v
                    for k, v in self._option.items()
                    if k not in ("baseOption", "options")
                }
                _deep_merge(merged, extra)
            else:
                merged = {
                    k: _copy_any(v) for k, v in self._option.items() if k != "options"
                }
            self._timeline_base = merged
        # 合并语义下 baseOption 可能被增量修改：同步回基线快照
        for key, value in self._option.items():
            if key in ("options", "baseOption"):
                continue
            if key in ("series", "dataZoom", "graphic") and isinstance(value, list):
                self._timeline_base[key] = _copy_any(value)
                continue
            if isinstance(value, dict) and isinstance(
                self._timeline_base.get(key), dict
            ):
                _deep_merge(self._timeline_base[key], value)
            else:
                self._timeline_base[key] = _copy_any(value)

    def _apply_timeline_frame(self) -> None:
        """把当前帧（``_timeline_index``）合并到 timeline 基线上。

        无 ``options`` 帧时为空操作；合并结果写回 ``_option``（保留
        ``options`` / ``baseOption`` 结构键，供 getOption 与后续帧切换）。
        """
        frames = self._option.get("options")
        if not isinstance(frames, list) or not frames or self._timeline_base is None:
            return
        timeline_opt = self._option.get("timeline")
        idx = getattr(self, "_timeline_index", 0)
        if isinstance(timeline_opt, dict):
            if "currentIndex" in timeline_opt:
                idx = timeline_opt.get("currentIndex")
            else:
                timeline_opt["currentIndex"] = idx
        try:
            idx = int(idx or 0)
        except (TypeError, ValueError, OverflowError):
            idx = 0
        idx = max(0, min(idx, len(frames) - 1))
        self._timeline_index = idx
        frame = frames[idx]
        if not isinstance(frame, dict):
            return
        effective = _copy_any(self._timeline_base)
        _deep_merge(effective, frame)
        effective["options"] = _copy_any(frames)
        if isinstance(self._option.get("baseOption"), dict):
            effective["baseOption"] = _copy_any(self._option["baseOption"])
        self._option = effective

    def _refresh(self) -> None:
        """按当前 option 重建并播放过渡动画（timeline 帧切换用）。"""
        prev_list = [list(r.data()) for r in self._series]
        prev_by_name = {
            r.name: prev_list[i] for i, r in enumerate(self._series) if r.name
        }
        self._capture_timeline_base()
        self._apply_timeline_frame()
        self._opt_version += 1
        self._apply_option(prev_list, prev_by_name)

    def _apply_option(self, prev_list: list, prev_by_name: dict) -> None:
        """重建渲染器并注入旧数据（动画插值），随后播放入场 / 过渡动画。

        ``prev_list`` / ``prev_by_name`` 允许为 ``None`` ——``setOption``
        在动画关闭时会跳过旧数据快照（百万级物化纯浪费），此时不注入
        ``prev_data``，渲染器走无插值路径。
        """
        self._capture_timeline_base()
        self._apply_timeline_frame()
        self._rebuild()
        if prev_list is not None or prev_by_name:
            for i, r in enumerate(self._series):
                prev = (prev_by_name or {}).get(r.name) if r.name else None
                if prev is None and prev_list is not None and i < len(prev_list):
                    prev = prev_list[i]
                r.prev_data = prev
        self._start_animation()
        self.update()

    def _start_animation(self) -> None:
        """按 option 动画键启动入场 / 过渡动画；关闭时直接呈现终态。

        ``animation`` / ``animationDuration`` / ``animationEasing``
        （更新过渡用 ``animationDurationUpdate`` / ``animationEasingUpdate``）。
        """
        opt = self._option
        enabled = opt.get("animation", True) is not False
        has_prev = any(r.prev_data is not None for r in self._series)
        if has_prev:
            duration = opt.get(
                "animationDurationUpdate", opt.get("animationDuration", ANIM_DURATION)
            )
            easing_name = opt.get("animationEasingUpdate", opt.get("animationEasing"))
        else:
            duration = opt.get("animationDuration", ANIM_DURATION)
            easing_name = opt.get("animationEasing")
        if enabled:
            # 走策略解析：Reduced 压时长、Disabled 同步落终值（都仍会发 finished）。
            self.anim.startResolved(duration, _easing_from_name(easing_name))
        else:
            self.anim.setDuration(duration)
            self.anim.setEasing(_easing_from_name(easing_name))
            self.anim.complete()

    def getOption(self) -> dict:
        """当前 option 深拷贝（ECharts ``getOption``）。

        大数值数组被还原为普通 ``list``（``_unwrap_option``）—— 缓冲区是
        内部紧凑存储，调用方观察不到它，也无需知道它存在。拷贝过程对缓冲区
        **按引用**、最后一步才物化成新 list，因此「深拷贝」的语义仍然成立
        （调用方改动返回值不会影响图表），但不会逐元素复制两遍百万级数据。
        """
        return _unwrap_option(_copy_any(self._option))

    def resize(self, width=None, height=None) -> None:
        """ECharts ``resize``：无参强制重排；兼容 QWidget ``resize(w, h)``。

        ``width`` 传 dict 时按 ECharts opts 解析（``{"width":..., "height":...}``）。
        """
        opts = width if isinstance(width, dict) else None
        if opts is not None:
            width = opts.get("width")
            height = opts.get("height")
        if width is not None or height is not None:
            w = int(width) if width is not None else self.width()
            h = int(height) if height is not None else self.height()
            super().resize(w, h)
        self.invalidateLayout()
        self._layout_all(force=True)
        self.update()

    def appendData(self, params: dict) -> bool:
        """向指定系列追加数据（ECharts ``appendData({seriesIndex|seriesName, data})``）。

        ``params`` 是 ``{"seriesIndex": int}`` / ``{"seriesName": str}`` /
        ``{"seriesId": str}``（三者其一）+ ``"data"``（单点或点列表）；
        返回是否找到目标系列并追加。
        """
        if not isinstance(params, dict):
            return False
        data = params.get("data")
        if data is None:
            return False
        series_opts = [
            s for s in (self._option.get("series") or []) if isinstance(s, dict)
        ]
        if not series_opts:
            return False
        index = None
        if params.get("seriesIndex") is not None:
            try:
                idx = int(params["seriesIndex"])
            except (TypeError, ValueError, OverflowError):
                return False
            if 0 <= idx < len(series_opts):
                index = idx
        elif params.get("seriesName"):
            name = str(params["seriesName"])
            for i, s in enumerate(series_opts):
                if str(s.get("name") or "") == name:
                    index = i
                    break
        elif params.get("seriesId"):
            sid = str(params["seriesId"])
            for i, s in enumerate(series_opts):
                if str(s.get("id") or "") == sid:
                    index = i
                    break
        if index is None:
            return False
        target = _copy_series_entry(series_opts[index])
        # 缓冲区不可原地 extend（只读，见 charts.data），故先物化成 list；
        # 追加完成后 ``setOption`` 会重新包成缓冲区。
        data_list = target.get("data")
        if isinstance(data_list, ElaNumericBuffer):
            data_list = data_list.toList()
        elif not isinstance(data_list, list):
            data_list = []
        if isinstance(data, list):
            data_list.extend(
                _hold_value(data) if _cdata.isBufferLike(data) else copy.deepcopy(data)
            )
        else:
            data_list.append(copy.deepcopy(data))
        target["data"] = data_list
        # 必须按**下标对齐**传整份 series：合并时新项按 id → name → **下标**
        # 匹配旧项，只传 ``[target]`` 会让它落到下标 0（除非恰好有 id/name）。
        patch = [{} for _ in range(index)] + [target]
        self.setOption({"series": patch})
        return True

    def clear(self) -> None:
        """清空图表（ECharts ``clear``；等价 ``setOption({}, notMerge=True)``）。"""
        self.setOption({}, notMerge=True)

    def dispatchAction(self, payload: dict) -> bool:
        """触发 ECharts 动作（``dispatchAction``）。

        支持：``legendToggleSelect`` / ``legendSelect`` / ``legendUnSelect`` /
        ``legendAllSelect`` / ``legendInverseSelect`` / ``dataZoom`` /
        ``restore`` / ``showTip`` / ``hideTip`` / ``highlight`` /
        ``downplay`` / ``timelineChange`` / ``timelinePlayChange``。

        :returns: 动作是否被识别并执行
        """
        if not isinstance(payload, dict):
            return False
        action = str(payload.get("type") or "")
        if action in (
            "legendToggleSelect",
            "legendSelect",
            "legendUnSelect",
            "legendAllSelect",
            "legendInverseSelect",
        ):
            return self._dispatch_legend(action, payload)
        if action == "dataZoom":
            return self._dispatch_data_zoom(payload)
        if action == "restore":
            self._restore_state()
            return True
        if action == "showTip":
            return self._dispatch_show_tip(payload)
        if action == "hideTip":
            self.tooltip.hide()
            self.update()
            return True
        if action in ("highlight", "downplay"):
            return self._dispatch_emphasis(action, payload)
        if action == "timelineChange":
            comp = self._component("timeline")
            if comp is None:
                return False
            try:
                comp.goto(int(payload.get("currentIndex", 0)))
            except (TypeError, ValueError, OverflowError):
                return False
            return True
        if action == "timelinePlayChange":
            comp = self._component("timeline")
            if comp is None:
                return False
            want = bool(payload.get("playState", not comp.playing))
            if want != bool(comp.playing):
                comp.togglePlay()
            return True
        return False

    # -- 事件（on / off）：ECharts 事件名与载荷 ---------------------------
    def on(self, eventName: str, handler) -> "ElaChartWidget":
        """注册 ECharts 事件处理器（``chart.on('click', fn)``）。

        handler 接收一个 dict（ECharts params，含 ``type``）。异常被捕获并
        仅告警一次，不会穿透 Qt 事件循环导致进程 abort。
        """
        if not callable(handler):
            raise TypeError("on(eventName, handler): handler 必须可调用")
        self._event_handlers.setdefault(str(eventName), []).append(handler)
        return self

    def off(self, eventName: str = None, handler=None) -> "ElaChartWidget":
        """移除事件处理器（``off()`` 清空 / ``off(name)`` 按事件 / ``off(name, fn)`` 按函数）。"""
        if eventName is None:
            self._event_handlers.clear()
            return self
        key = str(eventName)
        if handler is None:
            self._event_handlers.pop(key, None)
            return self
        handlers = self._event_handlers.get(key)
        if handlers:
            try:
                handlers.remove(handler)
            except ValueError:
                pass
            if not handlers:
                self._event_handlers.pop(key, None)
        return self

    def _emit_event(self, name: str, params: dict) -> None:
        """发射 ECharts 事件（唯一出口；载荷异常不扩散）。"""
        try:
            self._chartEvent.emit(str(name), dict(params or {}))
        except Exception as exc:
            warn_once(f"event-emit:{name}", f"事件参数异常（{name}）：{exc!r}")

    def _dispatch_chart_event(self, name: str, params: dict) -> None:
        for handler in list(self._event_handlers.get(name, ())):
            try:
                handler(dict(params))
            except Exception as exc:
                warn_once(
                    f"event-handler:{name}",
                    f"事件处理器异常（{name}）：{exc!r}",
                )

    def _forward_click(self, params: dict) -> None:
        self._emit_event("click", params)

    def _forward_legend_toggled(self, name: str, visible: bool) -> None:
        self._emit_event(
            "legendselectchanged",
            {
                "type": "legendselectchanged",
                "name": str(name),
                "selected": dict(self._series_state),
            },
        )

    def _forward_data_zoom(self, start: float, end: float) -> None:
        self._emit_event(
            "datazoom",
            {
                "type": "datazoom",
                "start": float(start),
                "end": float(end),
                "batch": [{"start": float(start), "end": float(end)}],
            },
        )

    def _forward_timeline_changed(self, index: int) -> None:
        self._emit_event(
            "timelinechanged",
            {"type": "timelinechanged", "currentIndex": int(index)},
        )

    def _forward_brush_selected(self, items: list) -> None:
        batch = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            batch.append(
                {
                    "seriesIndex": self._series_index(item.get("series")),
                    "seriesName": str(item.get("series") or ""),
                    "dataIndex": item.get("dataIndex"),
                    "value": item.get("value"),
                    "name": item.get("name", ""),
                }
            )
        self._emit_event(
            "brushselected",
            {"type": "brushselected", "batch": batch, "selected": list(items or [])},
        )

    def _forward_toolbox(self, action: str) -> None:
        if str(action) == "restore":
            self._emit_restore_event()

    def _emit_restore_event(self) -> None:
        self._emit_event("restore", {"type": "restore"})

    def _on_animation_finished(self) -> None:
        if self._disposed:
            return
        try:
            self.finished.emit()
        except Exception:
            pass
        self._emit_event("finished", {"type": "finished"})

    # -- dispatchAction 分派实现 ------------------------------------------
    def _dispatch_legend(self, action: str, payload: dict) -> bool:
        names = payload.get("name")
        if isinstance(names, (list, tuple, set)):
            names = [str(n) for n in names]
        elif names is not None:
            names = [str(names)]
        else:
            names = [r.name for r in self._series]
        if not names:
            return False
        for name in names:
            if action == "legendSelect":
                self._setSeriesVisible(name, True)
            elif action == "legendUnSelect":
                self._setSeriesVisible(name, False)
            elif action == "legendAllSelect":
                self._setSeriesVisible(name, True)
            elif action == "legendInverseSelect":
                self._setSeriesVisible(name, not self._seriesVisible(name))
            else:  # legendToggleSelect
                self._legendSelectToggle(name)
        if action != "legendToggleSelect":
            # **每个名字都要发**。原先只发 ``names[0]``：动作明明应用到了
            # 全部系列（上面的循环），宿主挂在 ``legendToggled`` 上同步自己
            # 的状态时却只收到第一个 —— 剩下那些静默不同步，表现为「批量
            # 取消选中后宿主 UI 只更新了一项」。
            # ``legendToggleSelect`` 走 ``_legendSelectToggle``，它自己发。
            for name in names:
                self.legendToggled.emit(name, self._seriesVisible(name))
        self.update()
        return True

    def _component(self, optionKey: str):
        """按 optionKey 取首个组件实例。"""
        for comp in self._components:
            if str(getattr(comp, "optionKey", "")) == optionKey:
                return comp
        return None

    def _dispatch_data_zoom(self, payload: dict) -> bool:
        comp = self._component("dataZoom")
        if comp is None:
            return False
        apply_action = getattr(comp, "applyAction", None)
        if not callable(apply_action):
            return False
        if not apply_action(payload):
            return False
        # **不要在这里再 emit 一次** ``dataZoomChanged`` —— ``applyAction`` 内部
        # 末尾已经 ``_emit_changed()``，而那条信号经 ``_forward_data_zoom`` 转成
        # ECharts ``datazoom`` 事件。在此处补发会让 dispatchAction 路径把事件发两遍
        # （滚轮 / 拖拽路径只发一遍，两条路径行为不一致）。
        return True

    def _dispatch_show_tip(self, payload: dict) -> bool:
        renderer = self._renderer_for(payload)
        if renderer is None:
            return False
        data_index = payload.get("dataIndex")
        hit = None
        if data_index is not None:
            try:
                idx = int(data_index)
            except (TypeError, ValueError, OverflowError):
                idx = None
            if idx is not None:
                value = renderer.valueAtIndex(idx)
                if value is not None:
                    hit = dict(value)
                    hit.setdefault("dataIndex", idx)
        x, y = _opt_float(payload.get("x"), None), _opt_float(payload.get("y"), None)
        if x is not None and y is not None:
            pos = QPointF(x, y)
        elif hit is not None and hit.get("pos") is not None:
            pos = QPointF(hit["pos"])
        else:
            pos = QPointF(self.width() / 2, self.height() / 2)
            coord = self.coordFor(renderer.opt)
            if coord is not None and hit is not None:
                try:
                    px, py = parseDataPoint((renderer.data() or [None])[0], 0)
                    pt = coord.mapPoint(px, py)
                    pos = QPointF(pt)
                except Exception:
                    pass
        if hit is None:
            hit = {"name": renderer.name, "value": None}
        self._hover = (renderer, hit)
        self.tooltip.showAt(
            pos, self.tooltip.buildLines(hit, renderer.color(), renderer.name)
        )
        self.update()
        return True

    def _dispatch_emphasis(self, action: str, payload: dict) -> bool:
        renderer = self._renderer_for(payload)
        if renderer is None:
            return False
        if action == "downplay":
            if self._hover is not None and self._hover[0] is renderer:
                self._hover = None
            params = {
                "type": "downplay",
                "seriesIndex": self._series.index(renderer),
                "seriesName": renderer.name,
                "dataIndex": payload.get("dataIndex"),
                "name": payload.get("name"),
            }
            self._emit_event("downplay", params)
            self.update()
            return True
        data_index = payload.get("dataIndex")
        name = payload.get("name")
        hit = {"name": str(name or ""), "dataIndex": data_index}
        if data_index is not None:
            try:
                idx = int(data_index)
                hit["dataIndex"] = idx
                value = renderer.valueAtIndex(idx)
                if value:
                    hit["value"] = value.get("value")
                    hit.setdefault("name", str(value.get("name") or ""))
            except (TypeError, ValueError, OverflowError):
                pass
        self._hover = (renderer, hit)
        params = {
            "type": "highlight",
            "seriesIndex": self._series.index(renderer),
            "seriesName": renderer.name,
            "dataIndex": hit.get("dataIndex"),
            "name": hit.get("name"),
        }
        self._emit_event("highlight", params)
        self.update()
        return True

    def _restore_state(self) -> None:
        """恢复初始状态（ECharts restore）：dataZoom / 图例选择 / 下钻 / roam。"""
        for comp in self._components:
            restore = getattr(comp, "restore", None)
            if callable(restore):
                try:
                    restore()
                except Exception:
                    pass
        for name in list(self._series_state.keys()):
            self._setSeriesVisible(name, True)
        for r in self._series:
            for method in ("resetDrill", "resetPositions", "resetRoam"):
                fn = getattr(r, method, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
        self.invalidateLayout()
        self.update()
        self._emit_restore_event()

    def _renderer_for(self, payload: dict):
        """按 seriesIndex / seriesName / seriesId 找可见渲染器（缺省首个）。"""
        series_id = payload.get("seriesId")
        if series_id is not None:
            for r in self._series:
                if r.id == str(series_id):
                    return r
        name = payload.get("seriesName")
        if (
            name is None
            and payload.get("name") is not None
            and payload.get("seriesIndex") is None
            and payload.get("dataIndex") is None
        ):
            name = payload.get("name")
        if name is not None:
            for r in self._series:
                if r.name == str(name):
                    return r
        index = payload.get("seriesIndex")
        if index is not None:
            try:
                idx = int(index)
            except (TypeError, ValueError, OverflowError):
                idx = -1
            if 0 <= idx < len(self._series):
                return self._series[idx]
            return None
        return self._series[0] if self._series else None

    def _series_index(self, name) -> int:
        for i, r in enumerate(self._series):
            if r.name == str(name):
                return i
        return -1

    # -- convertToPixel / convertFromPixel / containPixel -----------------
    def _resolve_finder(self, finder):
        """解析 finder（字符串或 dict）→ Coord；无法解析返回 None。"""
        alias = {
            "cartesian2d": "grid",
            "grid": "grid",
            "polar": "polar",
            "singleaxis": "singleAxis",
            "singleAxis": "singleAxis",
            "calendar": "calendar",
        }
        if isinstance(finder, str):
            kind = alias.get(finder, alias.get(finder.lower(), finder))
            for c in self._coords:
                if c.kind == kind:
                    return c
            return None
        if isinstance(finder, dict):
            for key in ("seriesIndex", "seriesName", "seriesId"):
                if finder.get(key) is not None:
                    renderer = self._renderer_for(finder)
                    return self.coordFor(renderer.opt) if renderer else None
            for key, kind in (
                ("gridIndex", "grid"),
                ("xAxisIndex", "grid"),
                ("yAxisIndex", "grid"),
                ("polarIndex", "polar"),
                ("angleAxisIndex", "polar"),
                ("radiusAxisIndex", "polar"),
                ("singleAxisIndex", "singleAxis"),
                ("calendarIndex", "calendar"),
            ):
                if finder.get(key) is not None:
                    try:
                        if int(finder[key]) != 0:
                            return None  # 多坐标系未实现
                    except (TypeError, ValueError, OverflowError):
                        return None
                    for c in self._coords:
                        if c.kind == kind:
                            return c
            return None
        return None

    def convertToPixel(self, finder, value):
        """数据值 → 像素（ECharts ``convertToPixel``）。

        grid / polar / calendar 返回 ``[x, y]``；singleAxis 返回标量；
        无法解析时返回 ``None``。
        """
        coord = self._resolve_finder(finder)
        if coord is None:
            return None
        if isinstance(value, dict):
            if "coord" in value:
                value = value["coord"]
            else:
                value = [value.get("x"), value.get("y")]
        if not isinstance(value, (list, tuple)):
            value = [value]
        try:
            if coord.kind == "singleAxis":
                pt = coord.mapPoint(value[0])
                return float(pt.y())
            if coord.kind == "calendar":
                pt = coord.mapPoint(value[0])
            else:
                pt = coord.mapPoint(value[0], value[1] if len(value) > 1 else None)
            if pt is None:
                return None
            return [float(pt.x()), float(pt.y())]
        except Exception:
            return None

    def convertFromPixel(self, finder, value):
        """像素 → 数据值（ECharts ``convertFromPixel``）。

        grid 返回 ``[x, y]``；polar 返回 ``[angle, radius]``；singleAxis
        返回标量；calendar 返回 ``[ISO 日期]``。
        """
        coord = self._resolve_finder(finder)
        if coord is None:
            return None
        if isinstance(value, QPointF):
            pos = QPointF(value)
        elif isinstance(value, dict):
            pos = QPointF(float(value.get("x", 0)), float(value.get("y", 0)))
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            pos = QPointF(float(value[0]), float(value[1]))
        else:
            return None
        invert = getattr(coord, "invertPoint", None)
        if not callable(invert):
            return None
        try:
            result = invert(pos)
        except Exception:
            return None
        if result is None:
            return None
        if isinstance(result, (list, tuple)):
            return list(result)
        return result

    def containPixel(self, finder, value) -> bool:
        """像素是否落在坐标系内（ECharts ``containPixel``）。"""
        coord = self._resolve_finder(finder)
        if coord is None:
            return False
        if isinstance(value, QPointF):
            pos = QPointF(value)
        elif isinstance(value, dict):
            pos = QPointF(float(value.get("x", 0)), float(value.get("y", 0)))
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            pos = QPointF(float(value[0]), float(value[1]))
        else:
            return False
        contain = getattr(coord, "containPoint", None)
        if not callable(contain):
            return False
        try:
            return bool(contain(pos))
        except Exception:
            return False

    # -- showLoading / hideLoading ----------------------------------------
    def showLoading(self, type: str = "default", opts: dict = None) -> None:
        """显示加载遮罩（ECharts ``showLoading``）。

        opts：``text`` / ``color`` / ``textColor`` / ``maskColor`` /
        ``fontSize`` / ``showSpinner`` / ``spinnerRadius`` / ``lineWidth``。
        """
        self._loading = True
        self._loading_type = str(type or "default")
        self._loading_opts = dict(opts or {})
        if self._loading_opts.get("showSpinner", True):
            # 持续动效：Reduced/Disabled 下不转。角度冻结在当前值 —— 遮罩与文字
            # 都照常画，只是不再转，所以看起来是「有遮罩但静止」。
            start_idle_loop(self._spinner_timer, SPINNER_TICK_MS)
        self.update()

    def hideLoading(self) -> None:
        """隐藏加载遮罩（ECharts ``hideLoading``）。"""
        self._spinner_timer.stop()
        self._loading = False
        self._loading_opts = {}
        self.update()

    @property
    def isLoading(self) -> bool:
        """当前是否显示加载遮罩（扩展查询）。"""
        return bool(self._loading)

    def _tick_spinner(self) -> None:
        if self._disposed or is_deleted(self):
            return
        self._spinner_angle = (self._spinner_angle + 12) % 360
        self.update()

    def _paint_loading(self, p: QPainter) -> None:
        opts = self._loading_opts
        mask = QColor(opts.get("maskColor") or QColor(T("color.bg.base")))
        if not opts.get("maskColor"):
            mask.setAlpha(204)
        p.fillRect(self.rect(), mask)
        font_size = float(opts.get("fontSize", T("font.sm")))
        font = chartFont(font_size)
        p.setFont(font)
        text = str(opts.get("text", "加载中"))
        fm = QFontMetricsF(font)
        text_w = fm.horizontalAdvance(text) if text else 0.0
        if opts.get("showSpinner", True) and self._loading_type != "none":
            radius = max(6.0, float(opts.get("spinnerRadius", 14)))
            line_w = max(1.0, float(opts.get("lineWidth", 3)))
            color = QColor(opts.get("color") or T("color.primary"))
            pen = QPen(color, line_w)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            cx = self.width() / 2
            cy = self.height() / 2 - (fm.height() / 2 if text else 0.0)
            p.drawArc(
                QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                int(90 - self._spinner_angle) * 16,
                270 * 16,
            )
        if text:
            p.setPen(QColor(opts.get("textColor") or T("color.text.secondary")))
            p.drawText(
                QRectF(
                    self.width() / 2 - max(120.0, text_w) / 2 - 10,
                    self.height() / 2 + fm.height() / 2 + 2,
                    max(120.0, text_w) + 20,
                    fm.height() + 2,
                ),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                text,
            )

    # -- 导出 / 图片 -------------------------------------------------------
    def getDataURL(self, opts: dict = None) -> str:
        """导出为 data URL（ECharts ``getDataURL``）。

        opts：``type``（``"png"`` / ``"jpeg"``）/ ``pixelRatio`` /
        ``backgroundColor``；``excludeComponents`` 暂不支持（忽略）。
        """
        opts = dict(opts or {})
        fmt = str(opts.get("type") or "png").lower()
        if fmt == "svg":
            return self._svg_data_url()
        fmt = "jpeg" if fmt in ("jpeg", "jpg") else "png"
        try:
            image = self._grab_without_toolbox().toImage()
        except Exception:
            return ""
        if image.isNull():
            return ""
        try:
            ratio = float(opts.get("pixelRatio") or 1.0)
        except (TypeError, ValueError, OverflowError):
            ratio = 1.0
        if ratio > 0 and abs(ratio - 1.0) > 1e-6:
            image = image.scaled(
                max(1, int(image.width() * ratio)),
                max(1, int(image.height() * ratio)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        bg = opts.get("backgroundColor")
        if bg or fmt == "jpeg":
            canvas = QImage(image.size(), QImage.Format.Format_RGB32)
            canvas.fill(QColor(bg) if bg else QColor(T("color.bg.base")))
            painter = QPainter(canvas)
            painter.drawImage(0, 0, image)
            painter.end()
            image = canvas
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        ok = image.save(buf, fmt.upper())
        buf.close()
        if not ok:
            return ""
        payload = bytes(buf.data().toBase64()).decode("ascii")
        mime = "image/jpeg" if fmt == "jpeg" else "image/png"
        return f"data:{mime};base64,{payload}"

    def zoomStep(self, factor: float) -> bool:
        """按倍数步进缩放（``<1`` 放大 / ``>1`` 缩小），围绕当前窗口中心。

        工具条 ``zoomIn`` / ``zoomOut`` 与宿主快捷键都用它；无 dataZoom 组件时
        返回 ``False``（没有可缩放的窗口）。窗口最小 0.5%、最大 100%（全量）。
        """
        comp = self._component("dataZoom")
        if comp is None:
            return False
        try:
            start = float(getattr(comp, "start", 0.0))
            end = float(getattr(comp, "end", 100.0))
            factor = float(factor)
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(factor) or factor <= 0:
            return False
        span = max(0.5, end - start)
        new_span = min(100.0, max(0.5, span * factor))
        center = (start + end) / 2.0
        new_start = center - new_span / 2.0
        new_end = center + new_span / 2.0
        if new_start < 0.0:
            new_end -= new_start
            new_start = 0.0
        if new_end > 100.0:
            new_start -= new_end - 100.0
            new_end = 100.0
        return bool(
            self.dispatchAction(
                {"type": "dataZoom", "start": max(0.0, new_start), "end": new_end}
            )
        )

    def saveImage(self, path: str = None, *, format: str = None) -> str:
        """保存当前图表（``path=None`` 弹保存对话框）。

        格式按 ``format`` 或扩展名判定：``svg`` → 矢量导出（``QSvgGenerator``，
        矢量图元 + 位图符号内嵌）；其余走 PNG。返回实际保存路径，未保存返回 ``""``。
        """
        target = path
        want_svg = str(format or "").lower() == "svg" or (
            bool(target) and str(target).lower().endswith(".svg")
        )
        if not target:
            try:
                if QGuiApplication.platformName() == "offscreen":
                    return ""
                filt = (
                    "SVG 矢量图 (*.svg)" if want_svg else "PNG 图片 (*.png)"
                )
                default = "chart.svg" if want_svg else "chart.png"
                target, _ = QFileDialog.getSaveFileName(self, "保存图表", default, filt)
            except Exception:
                target = None
        if not target:
            return ""
        if want_svg:
            return self._save_svg(str(target))
        try:
            if self._grab_without_toolbox().save(target, "PNG"):
                return str(target)
        except Exception:
            pass
        return ""

    def _save_svg(self, target: str) -> str:
        """用 ``QSvgGenerator`` 走同一条绘制链导出矢量图。"""
        try:
            from PyQt6.QtSvg import QSvgGenerator
        except ImportError:  # 可选依赖（QtSvg）
            return ""
        try:
            width, height = max(1, self.width()), max(1, self.height())
            generator = QSvgGenerator()
            generator.setFileName(target)
            generator.setSize(QSize(width, height))
            generator.setViewBox(QRect(0, 0, width, height))
            generator.setTitle("ElaChartWidget")
            painter = QPainter(generator)
            try:
                painter.fillRect(
                    QRect(0, 0, width, height), QColor(T("color.bg.base"))
                )
                self._paint_content(painter)
            finally:
                painter.end()
            return target
        except Exception:
            return ""

    # -- 生命周期 ----------------------------------------------------------
    def _toolbox_widgets(self) -> list:
        """工具条按钮子控件（导出时临时隐藏用）。"""
        result = []
        for comp in self._components:
            if str(getattr(comp, "optionKey", "")) != "toolbox":
                continue
            widgets = getattr(comp, "_widgets", None)
            if isinstance(widgets, dict):
                result.extend(
                    w for w in list(widgets.values()) if not is_deleted(w)
                )
        return result

    def _grab_without_toolbox(self):
        """``grab()`` 前隐藏工具条按钮：导出 / 截图要的是**图**，不是 UI。

        工具条按钮是真实子控件（``ElaIconButton``），``grab()`` 会把它们一起
        画进去，而 SVG 导出走 ``_paint_content``（不含子控件）—— 不统一的话
        同一个图表导 PNG 带一排按钮、导 SVG 不带。
        """
        buttons = self._toolbox_widgets()
        hidden = [b for b in buttons if b.isVisible()]
        for button in hidden:
            button.setVisible(False)
        try:
            return self.grab()
        finally:
            for button in hidden:
                button.setVisible(True)

    def _svg_data_url(self) -> str:
        """矢量图 → ``data:image/svg+xml;base64,...``（``getDataURL({"type": "svg"})``）。"""
        import base64
        import tempfile

        try:
            with tempfile.TemporaryDirectory() as tmp:
                target = str(pathlib.Path(tmp) / "chart.svg")
                if not self._save_svg(target):
                    return ""
                data = pathlib.Path(target).read_bytes()
        except Exception:
            return ""
        if not data:
            return ""
        return "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii")

    def dispose(self) -> None:
        """销毁实例（ECharts ``dispose``；停定时器 / 断主题 / deleteLater）。"""
        if self._disposed:
            return
        self._disposed = True
        try:
            self._spinner_timer.stop()
        except Exception:
            pass
        try:
            self.anim.stop()
        except Exception:
            pass
        self.tooltip.hide()
        self._hover = None
        self._event_handlers.clear()
        # 组件一并解挂：事件过滤器 / 定时器虽然 parent 在 chart 上会跟着销毁，
        # 但组件可能持有 chart 之外的东西（宿主句柄、注册的全局回调）。
        self._dispose_components(include_host=True)
        self._host_components.clear()
        self._components = []
        self._disconnect_theme()
        self.deleteLater()

    def isDisposed(self) -> bool:
        """实例是否已 dispose。"""
        return bool(self._disposed)

    def getWidth(self) -> int:
        """图表宽度（ECharts ``getWidth``）。"""
        return int(self.width())

    def getHeight(self) -> int:
        """图表高度（ECharts ``getHeight``）。"""
        return int(self.height())

    def getDevicePixelRatio(self) -> float:
        """设备像素比（ECharts ``getDevicePixelRatio``）。"""
        try:
            return float(self.devicePixelRatioF())
        except Exception:
            return 1.0

    def benchmark(
        self,
        frames: int = 8,
        forceLayout: bool = True,
        perSeries: bool = True,
    ) -> dict:
        """性能剖析：分项测量各阶段耗时（诊断用，不改变任何状态）。

        **为什么需要它**：大数据量下「慢」的归因必须靠实测，不能猜。本机
        100 万点 / 单系列实测（offscreen，1200x700）::

            ingestMs  15.0    摄入（setOption 全程）
            layoutMs  19.6    布局（坐标 + 系列几何，含采样与坐标映射）
            paintMs  107.4    绘制（纯光栅化，画到离屏 QImage）
            frameMs  127.0    → 远超 60 Hz 预算 16.7 ms

        **关键结论：瓶颈在绘制，不在点数也不在摄入。** 采样后只画 2256 个
        点却仍要 107 ms —— 说明成本来自「每段抗锯齿折线的光栅化」而非点数
        规模。因此优化方向是绘制阶段（分层位图缓存 / GPU 直绘），而不是
        继续优化采样或数据摄入。

        :param frames: 重复帧数（取平均，降低单帧噪声）。默认 8。
        :param forceLayout: 每次都强制重排（``_layout_all(force=True)``），
            绕过布局缓存。传 ``False`` 测的是「命中缓存的稳态」——那才是
            悬停 / 动画期的真实成本。
        :param perSeries: 是否额外测**每条系列**的布局 / 绘制耗时。多系列
            场景下总耗时只说明「慢」，逐系列读数才能定位到具体哪条曲线。
        :returns: 各项耗时（毫秒）与规模信息。**所有时间单位为毫秒（ms）**。
            ``seriesTimings`` 为逐系列读数（``perSeries=False`` 时为 ``[]``），
            每项含 ``name`` / ``type`` / ``dataPoints`` / ``drawnPoints`` /
            ``layoutMs`` / ``paintMs``。键集合由测试钉住。
        """
        frames = max(1, int(frames))
        # 记录需复原的状态。``setOption(notMerge=True)`` 内部会重置图例
        # 选中态（``_series_state``）并重新起动画，所以二者都要在测量
        # **之后**按调用前的值覆盖，否则 benchmark 会顺手改掉用户的图例。
        was_anim = self.anim.isRunning()
        saved_state = dict(self._series_state)
        # 悬浮提示：``notMerge`` 会 ``tooltip.hide()``。tooltip 自身持有
        # 全部状态，直接留一个对象引用即可复原。
        saved_tip = (
            self.tooltip,
            self.tooltip.active,
            self.tooltip._pos,
            self.tooltip._lines,
            self.tooltip._marker_pos,
        )
        try:
            # 固定到终态：动画每帧都在变，会让布局缓存永久失效，测出来的
            # 是「动画中」而非「稳态」的成本。
            self.anim.stop()
            self.anim.setProgress(1.0)
            # -- 摄入：setOption 全程（含合并 / 快照 / 重建） --
            t0 = _now()
            self.setOption(self._option, notMerge=True)
            ingest_ms = _elapsed_ms(t0)
            self.anim.stop()
            self.anim.setProgress(1.0)
            # ``notMerge`` 清空了图例选中态，测量前先复原 —— 否则被隐藏的
            # 系列也会被计入布局 / 绘制耗时。
            self._series_state = dict(saved_state)
            for r in self._series:
                r.visible = self._seriesVisible(r.name)
            # -- 布局：坐标系 + 系列几何（含采样与坐标映射） --
            t0 = _now()
            for _ in range(frames):
                self._layout_all(force=forceLayout)
            layout_ms = _elapsed_ms(t0) / frames
            # -- 绘制：坐标轴 + 系列 + 组件（不含布局） --
            t0 = _now()
            for _ in range(frames):
                self._render_to_painter()
            paint_ms = _elapsed_ms(t0) / frames
            # -- 逐系列：定位到具体哪条曲线慢（多系列时的关键读数） --
            series_timings = self._benchmark_series() if perSeries else []
        finally:
            # 复原图例选中态与悬浮提示（``notMerge`` 会清空两者）
            self._series_state = dict(saved_state)
            tip, was_active, pos, lines, marker = saved_tip
            if was_active:
                tip.showAt(pos, list(lines), marker)
            else:
                tip.hide()
            # 复原动画状态：调用前在跑 → 重新起；否则保持停止。
            if was_anim:
                self.anim.start()
            else:
                self.anim.stop()
                self.anim.setProgress(1.0)
        return self._benchmark_reduce(ingest_ms, layout_ms, paint_ms, series_timings)

    def _benchmark_series(self) -> list:
        """逐系列测量布局 / 绘制耗时（每项跑一轮，不取平均）。

        多系列场景下总耗时只回答「慢不慢」，答不出「哪条慢」。本方法把每条
        可见系列**单独**跑一遍布局与绘制，代价是总耗时约翻倍（仅诊断时用）。

        每条系列独测：关掉其余系列的可见性，避免把邻居的成本算到它头上
        （先画的系列会受益于「后画的还没覆盖这块区域」，同测才有可比性）。

        **只跑一轮**，不按 ``frames`` 取平均：逐系列读数用于横向比较「谁更
        慢」，量级差异远大于单轮噪声；而重复取平均在 8 系列 × 20 万点下会
        把一次 benchmark 拖到分钟级（实测 ``_render`` 单轮 122 ms）。

        **``layoutMs`` 读数含「其余系列被隐藏」的重排成本**：折线系列的
        布局会扫描全量 ``series_opts`` 重建槽位，故单测一条线时该值仍与
        总系列数相关（实测各折线均为 ~660 ms，而总布局 635 ms）。故该值
        只宜**横向比较同一批读数**（同轮、同条件），不可当作「这条线的
        布局绝对成本」。``paintMs`` 无此问题（绘制确实只画可见系列）。
        """
        out = []
        saved_state = dict(self._series_state)
        # 在进入循环前**快照**目标列表：循环内会把 ``r.visible`` 置为
        # False，而那正是循环的跳过条件 —— 直接遍历 ``self._series`` 会
        # 在第一轮之后全部被跳过（实测 3 条系列只返回 1 条）。
        targets = [r for r in self._series if getattr(r, "visible", True)]
        try:
            for target in targets:
                # 只留目标系列可见
                for r in self._series:
                    r.visible = r is target
                # 布局跑一次即可拿到几何 —— 逐系列读数要的是「这条线自身
                # 多贵」，重复 frames 轮取平均在多系列大数据下会拖到分钟级
                # （8 系列 × 6 帧实测 16 s），而布局幂等、单轮噪声远小于
                # 系列间的量级差异。
                self.invalidateLayout()
                t0 = _now()
                self._layout_all(force=True)
                s_layout = _elapsed_ms(t0)
                # 绘制同理跑一次。
                t0 = _now()
                self._render_to_painter()
                s_paint = _elapsed_ms(t0)
                out.append(
                    {
                        "name": str(target.name),
                        "type": _series_type_name(target),
                        "dataPoints": _series_data_len(target),
                        "drawnPoints": _series_geom_len(target),
                        "layoutMs": round(s_layout, 3),
                        "paintMs": round(s_paint, 3),
                    }
                )
        finally:
            self._series_state = dict(saved_state)
            for r in self._series:
                r.visible = self._seriesVisible(r.name)
            self.invalidateLayout()
        # 按「每单位几何的绘制成本」降序：多系列下真正可比的指标是密度，
        # 绝对 paintMs 会被图元数直接带偏（bar 20k 图元 515 ms vs 折线
        # 2256 点 32 ms，看着差 16 倍，实际每图元只差 3 倍）。
        out.sort(key=lambda d: -(d["paintMs"] / max(1, d["drawnPoints"])))
        return out

    def _render_to_painter(self) -> None:
        """把当前内容画到离屏 QImage（走与 ``paintEvent`` 相同的绘制路径）。

        不直接用 ``paintEvent``：那需要真实可见的控件，且 Qt 的合成 /
        窗口交换等待会计入读数，把「算法成本」和「系统等待」混在一起。
        """
        img = QImage(
            max(1, self.width()),
            max(1, self.height()),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            self._paint_content(p)
        finally:
            p.end()

    def _benchmark_reduce(self, ingest_ms, layout_ms, paint_ms, series_timings) -> dict:
        """汇总 benchmark 结果。

        返回键集合**固定**（由 ``tests/ela_chart_widget/test_chart_benchmark.py``
        钉住）—— 诊断接口靠 key 取值，键悄悄变动会让调用方静默拿到 ``None``，
        比没有这个接口更糟。

        规模字段的口径：

        - ``dataPoints``：**单个可见系列**的最大数据量（多系列时不是总和；
          ``totalDataPoints`` 才是总和）；
        - ``drawnPoints``：所有可见系列**实际绘制**的点数之和（已被采样
          压缩到视口像素量级，故远小于数据量）；
        - ``seriesTimings``：逐系列读数，按 ``paintMs`` 降序（最慢的在前），
          用于定位具体是哪条曲线吃掉了帧时间。
        """
        largest = 0
        total_data = 0
        drawn = 0
        visible = 0
        series_kinds = {}
        for r in self._series:
            if not getattr(r, "visible", True):
                continue
            visible += 1
            kind = _series_type_name(r)
            series_kinds[kind] = series_kinds.get(kind, 0) + 1
            n = _series_data_len(r)
            largest = max(largest, n)
            total_data += n
            drawn += _series_geom_len(r)
        return {
            # -- 耗时（毫秒） --
            "ingestMs": round(ingest_ms, 3),
            "layoutMs": round(layout_ms, 3),
            "paintMs": round(paint_ms, 3),
            "frameMs": round(layout_ms + paint_ms, 3),
            # -- 规模 --
            "dataPoints": largest,
            "totalDataPoints": total_data,
            "drawnPoints": drawn,
            "seriesCount": visible,
            "seriesKinds": series_kinds,
            "width": int(self.width()),
            "height": int(self.height()),
            "dpr": self.getDevicePixelRatio(),
            "frameBudget60HzMs": round(1000.0 / 60.0, 3),
            # -- 逐系列（按每图元绘制成本降序） --
            "seriesTimings": series_timings,
        }

    def _option_ref(self) -> dict:
        """当前 option 的内部引用（无拷贝；仅包内部热路径使用）。"""
        return self._option

    @property
    def seriesRenderers(self) -> list:
        """系列渲染器列表（含隐藏系列，``r.visible`` 标记）。"""
        return list(self._series)

    @property
    def coords(self) -> list:
        """坐标系列表。"""
        return list(self._coords)

    @property
    def components(self) -> list:
        """组件实例列表。"""
        return list(self._components)

    def palette(self) -> list:
        """当前生效调色板：option["color"] 覆盖，否则默认调色板（主题实时取）。

        **带缓存**：调色板只取决于「option 里的自定义色板」与「当前主题」，
        而 bar / scatter 的绘制路径会**逐图元**取色，而调色板本身不会逐图元变。
        未缓存时每次都新建 9 个 QColor，实测占绘制 tottime 的 16%。

        **返回的 QColor 是深拷贝**：调用方（``colorForSeries`` →
        ``itemColor`` → bar 绘制循环）会逐图元 ``setAlphaF`` 改 alpha，
        共享实例会让第一次绘制把整个调色板改成半透明（实测：一次 hover
        之后所有系列颜色都变淡，且新 list 也救不回来 —— 元素本身是共享的）。
        深拷贝 9 个 QColor 仍远快于每次重建调色板。
        """
        custom = self._option.get("color")
        has_custom = isinstance(custom, list) and bool(custom)
        key = (
            eTheme.getThemeMode(),
            id(custom) if has_custom else 0,
            len(custom) if has_custom else 0,
        )
        hit = self._palette_cache
        # ``hit[1] is custom`` 这道复核不能省：``setOption`` 换色板时旧 list
        # 会被释放，新 list **可能拿到同一个 id**，而长度也一样 —— 只比 key
        # 就会把上一个色板当成当前的，整张图配色错掉且零报错。持强引用
        # （存进 cache）同时杜绝 id 复用。
        if hit is not None and hit[0] == key and hit[1] is custom:
            return [QColor(c) for c in hit[2]]
        if has_custom:
            pal = [QColor(c) for c in custom]
        else:
            pal = defaultPalette()
        self._palette_cache = (key, custom, pal)
        return [QColor(c) for c in pal]

    def colorForSeries(self, series) -> QColor:
        """系列主色：series opt 的 "color" → 全局调色板按序号取色。

        序号取 ``_rebuild`` 时写好的 ``_series_index``，不用
        ``list.index()`` —— 后者是 O(系列数) 扫描，而本函数在 bar /
        scatter 的绘制路径上逐图元调用，而 ``list.index()`` 是 O(系列数)扫描
        —— 系列数与图元数相乘，顺序遍历时效果可惊人。
        """
        if isinstance(series, SeriesRenderer):
            idx = getattr(series, "_series_index", 0)
            if not isinstance(idx, int):
                idx = 0
            own = series.opt.get("color")
        else:
            idx = int(series)
            own = None
        if isinstance(own, str) and own:
            return QColor(own)
        pal = self.palette()
        return QColor(pal[idx % len(pal)])

    def primaryCoord(self):
        """主坐标系（coords[0]，无则 None）。"""
        return self._coords[0] if self._coords else None

    def coordFor(self, series_opt: dict = None):
        """按 series 的 coordinateSystem 匹配坐标系（默认首个）。"""
        want = None
        if isinstance(series_opt, dict):
            want = series_opt.get("coordinateSystem")
        alias = {
            "cartesian2d": "grid",
            "grid": "grid",
            "polar": "polar",
            "singleAxis": "singleAxis",
            "calendar": "calendar",
            None: None,
        }
        want = alias.get(want, want)
        if want:
            for c in self._coords:
                if c.kind == want:
                    return c
        return self.primaryCoord()

    # -- 图例 / 系列显隐（内部；对外走 dispatchAction / legend.selected） --
    def _setSeriesVisible(self, name, visible: bool) -> None:
        name = str(name)
        self._series_state[name] = bool(visible)
        # 回写 option：_rebuild 每次都会重放 legend.selected，若不同步，用户点了
        # 图例之后一次常规的数据刷新（setOption({"series": ...}) 合并）就会把
        # 显隐状态悄悄还原成旧值。
        legend_opt = self._option.get("legend")
        if isinstance(legend_opt, dict) and isinstance(
            legend_opt.get("selected"), dict
        ):
            legend_opt["selected"][name] = bool(visible)
        for r in self._series:
            if r.name == name:
                r.visible = bool(visible)
                hook = getattr(r, "_on_visible_changed", None)
                if callable(hook):
                    try:
                        hook()
                    except Exception:
                        pass
        self._layout_key = None
        self.update()

    def _seriesVisible(self, name) -> bool:
        return bool(self._series_state.get(str(name), True))

    def _legendSelectToggle(self, name: str) -> None:
        """图例点击：切换单个系列（selectedMode=single 时互斥）。"""
        name = str(name)
        new_visible = not self._seriesVisible(name)
        if new_visible and self.legend.selectedMode() == "single":
            for r in self._series:
                if r.name != name and self._seriesVisible(r.name):
                    self._setSeriesVisible(r.name, False)
        self._setSeriesVisible(name, new_visible)
        self.legendToggled.emit(name, new_visible)
        self.update()

    # ------------------------------------------------------------ 交互开关
    #: 可开关的交互功能（与组件 optionKey 对齐；tooltip / legend 由核心实现）
    INTERACTION_FEATURES = (
        "tooltip",
        "legend",
        "dataZoom",
        "brush",
        "timeline",
        "toolbox",
    )

    def setInteractive(self, enabled: bool) -> None:
        """交互总开关：关闭后所有鼠标交互失效（提示框 / 图例 / 缩放 / 刷选 /
        时间轴 / 工具箱），绘制与数据不变。

        **打开 = 全开**：置 ``True`` 时会**清空逐功能开关**（``setInteractionEnabled``
        设过的覆盖）—— 语义是「把交互恢复成完整状态」。宿主用总开关做「交互: 开/关」
        按钮时，用户期望点开就是全开，而不是保留上轮单独关掉的那几项。

        :param enabled: ``False`` 变为静态图（动画与程序化 API 不受影响）
        """
        self._interactive = bool(enabled)
        if not self._interactive:
            self.tooltip.hide()
            self._hover = None
        else:
            self._feature_flags.clear()
        # 总开关也影响工具条按钮的启用态（子控件不会跟 chart 重绘走）
        self._notify_interaction_changed()
        self.invalidateLayout()
        self.update()

    def interactiveEnabled(self) -> bool:
        """交互总开关是否开启。"""
        return self._interactive

    def setInteractionEnabled(self, feature: str, enabled: bool) -> None:
        """逐功能开关（与总开关取与）；``feature`` 取 ``"tooltip"`` / ``"legend"``
        / ``"dataZoom"`` / ``"brush"`` / ``"timeline"`` / ``"toolbox"``。
        """
        key = str(feature)
        if key not in self.INTERACTION_FEATURES:
            raise ValueError(
                f"未知交互功能：{feature!r}"
                f"（可选：{', '.join(self.INTERACTION_FEATURES)}）"
            )
        self._feature_flags[key] = bool(enabled)
        if not enabled and key == "tooltip":
            self.tooltip.hide()
            self._hover = None
        # 工具条按钮是真实子控件（启用态在 ``layout()`` 里同步）：
        # 这里既要让它当场变灰 / 恢复，也要让下一次布局重算位置与状态
        self._notify_interaction_changed()
        self.invalidateLayout()
        self.update()

    def _notify_interaction_changed(self) -> None:
        """交互开关变化 → 让组件立刻刷新「子控件级」的状态（工具条按钮启用态）。"""
        for comp in self._components:
            hook = getattr(comp, "onInteractionChanged", None)
            if not callable(hook):
                continue
            try:
                hook()
            except Exception:
                continue

    def hitRadius(self) -> float:
        """命中半径（px）：``tooltip.hitRadius`` / Plotly 风格的 ``hoverdistance``。

        默认 10px（库内原值）。曲线 / 散点的 ``hitTest`` 都走它，宿主可按
        数据密度调小（避免密集点「抢命中」）或调大（触摸场景）。
        """
        tooltip_opt = self._option.get("tooltip")
        raw = None
        if isinstance(tooltip_opt, dict):
            raw = tooltip_opt.get("hitRadius", tooltip_opt.get("hoverdistance"))
        radius = 10.0
        if raw is not None:
            try:
                radius = float(raw)
            except (TypeError, ValueError, OverflowError):
                radius = 10.0
        if not math.isfinite(radius) or radius <= 0:
            return 10.0
        return min(200.0, radius)

    #: 拖拽模式（对齐 Plotly ``dragmode``）：平移 / 框选缩放 / 框选 / 套索
    DRAG_MODES = ("pan", "zoom", "select", "lasso")

    #: 直角坐标图是否默认内置滚轮缩放（``setWheelZoomEnabled`` 可改）
    WHEEL_ZOOM_DEFAULT = True

    def setWheelZoomEnabled(self, enabled: bool) -> None:
        """内置滚轮缩放开关（**默认开**：曲线 / 柱状等直角坐标图开箱即用）。

        与 ``dataZoom`` 选项的关系：

        * option 里自己配了 ``dataZoom`` → 完全听用户的，本开关不再插手
          （``setWheelZoomEnabled(False)`` 也不会删掉用户配置的组件）；
        * 没配 → 打开时自动挂一个 ``inside`` 组件（``zoomOnMouseWheel`` /
          ``moveOnMouseMove`` 均为 True，对齐 ECharts 默认值）：**滚轮缩放 +
          按住拖动平移**；``setDragMode("zoom"/"select"/"lasso")`` 会把拖拽让给
          刷选，``setWheelZoomEnabled(False)`` 直接移除它。
        """
        enabled = bool(enabled)
        self._wheel_zoom_enabled = enabled
        if not enabled:
            auto = self._auto_wheel_zoom()
            if auto is not None:
                self._drop_component(auto)
            return
        self._ensure_wheel_zoom()

    def wheelZoomEnabled(self) -> bool:
        """内置滚轮缩放开关状态。"""
        return bool(self._wheel_zoom_enabled)

    def _auto_wheel_zoom(self):
        """取出自动创建的滚轮缩放组件（宿主自己配的不算）。"""
        for comp in self._host_components:
            if getattr(comp, "_wheel_zoom_auto", False):
                return comp
        return None

    def _drop_component(self, comp) -> None:
        """把一个组件从 chart 上摘干净（解挂事件过滤器 + 移出两个列表）。"""
        dispose = getattr(comp, "dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:
                pass
        for bucket in (self._components, self._host_components):
            while comp in bucket:
                bucket.remove(comp)
        self.invalidateLayout()
        self.update()

    def _ensure_wheel_zoom(self) -> None:
        """无 ``dataZoom`` 的直角坐标图自动挂 ``inside`` 组件（滚轮缩放 + 拖拽平移）。

        语义对齐 ECharts ``inside`` 的默认值：``zoomOnMouseWheel`` 与
        ``moveOnMouseMove`` 都是 True —— 滚轮缩放、按住拖动平移。
        框选 / 套索模式（``setDragMode``）会把平移关掉、把拖拽让给刷选；
        点击（按下→原地松开 ≤4px）仍走 ``_press_ctx`` 补发的 ``itemClicked``。
        """
        if not self._wheel_zoom_enabled or self._auto_wheel_zoom() is not None:
            return
        if self._component("dataZoom") is not None:
            return
        if not any(isinstance(coord, GridCoord) for coord in self._coords):
            return
        cls = COMPONENT_REGISTRY.get("dataZoom")
        if cls is None:  # pragma: no cover - 注册表恒有 dataZoom
            return
        try:
            comp = cls(
                self,
                [
                    {
                        "type": "inside",
                        "zoomOnMouseWheel": True,
                        "moveOnMouseMove": True,
                    }
                ],
            )
        except Exception as exc:
            warn_once(
                warn_key("wheel-zoom-ctor", type(exc).__name__),
                f"默认滚轮缩放组件构造失败: {exc!r}",
            )
            return
        comp._wheel_zoom_auto = True
        # 走 ``_host_components``：跨 setOption 存活，且不会被 _rebuild 重复创建
        self._host_components.append(comp)
        self._components.append(comp)

    def setDragMode(self, mode: str) -> None:
        """切换拖拽模式（Plotly ``dragmode`` 语义）。

        * ``"pan"`` —— 拖拽平移 + 滚轮缩放（ECharts ``inside`` 默认行为）；
        * ``"zoom"`` —— 拖拽**框选即缩放**（松手把 x 范围缩到选框）；
        * ``"select"`` —— 矩形框选（结果走 ``brushChanged``，不缩放）；
        * ``"lasso"`` —— 套索选择（同上，任意多边形）。

        实现方式：dataZoom ``inside`` 的拖拽平移与 brush 的拖拽接管互斥，
        按模式开关两者；``zoom`` 复用 brush 的选框几何。
        """
        key = str(mode or "").strip().lower()
        if key not in self.DRAG_MODES:
            raise ValueError(
                f"未知拖拽模式：{mode!r}（可选：{', '.join(self.DRAG_MODES)}）"
            )
        self._drag_mode = key
        data_zoom = self._component("dataZoom")
        if data_zoom is not None:
            # 缩放 / 选择模式：拖拽交给 brush（否则两者抢同一个拖拽手势）
            data_zoom.moveOnMouseMove = key == "pan"
            if hasattr(data_zoom, "zoomOnMouseWheel"):
                data_zoom.zoomOnMouseWheel = True
        brush = self._ensure_brush_component()
        if brush is not None:
            brush.enabled = key in ("zoom", "select", "lasso")
            brush.opt["type"] = "lasso" if key == "lasso" else "rect"
        self.update()

    def _ensure_brush_component(self):
        """取 brush 组件；option 里没配就按需建一个（``setDragMode`` 用）。

        宿主没写 ``brush`` 选项时也要能用 ``dragmode``（Plotly 模式条的框选 /
        套索按钮就是这么工作的）。建出来的实例挂进 ``_host_components``，
        跨 ``setOption`` 存活。
        """
        brush = self._component("brush")
        if brush is not None:
            return brush
        cls = COMPONENT_REGISTRY.get("brush")
        if cls is None:
            return None
        try:
            brush = cls(self, {"type": "rect"})
        except Exception as exc:
            warn_once("brush-ctor", f"brush 组件构造失败: {exc!r}")
            return None
        self._host_components.append(brush)
        self._components.append(brush)
        return brush

    def dragMode(self) -> str:
        """当前拖拽模式（未设置过时按 dataZoom ``inside`` 的默认行为报 ``"pan"``）。"""
        return str(getattr(self, "_drag_mode", "") or "pan")

    def brushComponent(self):
        """brush 组件句柄（宿主可读 ``selected_items`` / 接 ``selected`` 信号）。"""
        return self._component("brush")

    def setDoubleClickReset(self, enabled: bool) -> None:
        """双击是否复位视图（默认 **开**，对齐 Plotly ``doubleClick: 'reset'``）。"""
        self._double_click_reset = bool(enabled)

    def doubleClickReset(self) -> bool:
        """双击复位是否开启。"""
        return bool(self._double_click_reset)

    def resetView(self) -> None:
        """把视图还原到初始状态：全部 dataZoom 窗口回到 ``0..100`` +
        各协调器的漫游 / 缩放复位 + 提示框与悬停态清空。

        等价于 Plotly 模式条的「reset axes」；双击默认走这里
        （``setDoubleClickReset(False)`` 可关）。只影响视图，不动数据 / 图例显隐
        （图例请用 ``toolbox`` 的 restore 或 ``dispatchAction(legendAllSelect)``）。
        """
        comp = self._component("dataZoom")
        if comp is not None and hasattr(comp, "reset_window"):
            comp.reset_window()
        for coord in list(self.coords):
            hook = getattr(coord, "resetView", None)
            if callable(hook):
                try:
                    hook()
                except Exception:
                    continue
        for renderer in self._series:
            hook = getattr(renderer, "resetView", None)
            if callable(hook):
                try:
                    hook()
                except Exception:
                    continue
        self.tooltip.hide()
        self._hover = None
        self._legend_hover = None
        self.invalidateLayout()
        self.update()

    def isInteractionEnabled(self, feature: str) -> bool:
        """功能是否生效（总开关关闭时恒为 ``False``；未设置默认启用）。"""
        if not self._interactive:
            return False
        return bool(self._feature_flags.get(str(feature), True))

    def _interactive_components(self) -> list:
        """过滤后的组件列表（交互被关闭的组件不接收鼠标 / 滚轮事件）。"""
        result = []
        for comp in self._components:
            key = str(getattr(comp, "optionKey", ""))
            if key and not self.isInteractionEnabled(key):
                continue
            result.append(comp)
        return result

    def addComponent(self, comp) -> None:
        """挂接宿主自定义组件，**跨 ``setOption`` 存活**。

        两条路，别混：

        * **要跟着 option 走**（每次 ``setOption`` 按新 option 重建实例）就用
          :func:`registerComponent` —— 把类按 ``optionKey`` 注册，再在 option 里
          写同名键。
        * **纯运行时挂件**（宿主自己管刷新）用这里。它进 ``_host_components``，
          ``_rebuild`` 只重建 option 里的那些，不会丢它、也不会 ``dispose`` 它。

        组件只需鸭子类型实现 ``optionKey``（可选）/ ``layout(rect)`` /
        ``paint(painter, anim_t)`` / ``hitTest(pos)``；``onMousePress`` 等鼠标钩子
        有则调用。摘除用 :meth:`removeComponent`。
        """
        if comp is None:
            return
        if any(comp is existing for existing in self._host_components):
            return
        self._host_components.append(comp)
        if not any(comp is c for c in self._components):
            self._components.append(comp)
        self.invalidateLayout()
        self.update()

    def removeComponent(self, comp) -> bool:
        """摘掉宿主注入的组件（并在它实现了 ``dispose`` 时调用它）。"""
        found = None
        for existing in self._host_components:
            if existing is comp:
                found = existing
                break
        if found is None:
            return False
        self._host_components.remove(found)
        self._components = [c for c in self._components if c is not found]
        dispose = getattr(found, "dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:
                pass
        self.invalidateLayout()
        self.update()
        return True

    def _dispose_components(self, include_host: bool = False) -> None:
        """丢弃旧组件前调用其 ``dispose()``（没实现就跳过）。

        组件通过 duck typing 自愿解挂：``DataZoomComponent`` 摘事件过滤器、
        ``ChartTimeline`` 停定时器。``dispose`` 跑在 ``_rebuild`` 里，而
        ``_rebuild`` 可能由 ``ChartTimeline.goto()`` 从定时器回调触发 ——
        所以实现里只做「停止投递」与清 chart 上的登记，不去碰已析构的 C++ 对象。

        ``include_host=False``（``_rebuild`` 路径）**跳过**宿主经 ``addComponent``
        注入的组件 —— 它们不是被丢弃，而是被原样挂回去，由宿主自己负责刷新。

        ``include_host=True``（``dispose()`` 路径）全收：图表都没了，宿主挂件
        留着只会继续持有已失效的 chart。
        """
        hosts = set() if include_host else {id(c) for c in self._host_components}
        for comp in self._components:
            if id(comp) in hosts:
                continue
            dispose = getattr(comp, "dispose", None)
            if not callable(dispose):
                continue
            try:
                dispose()
            except Exception:
                pass

    # ------------------------------------------------------------- 内部构建
    def _rebuild(self) -> None:
        """按当前 option 重建组件 / 坐标系 / 系列渲染器（并使布局缓存失效）。"""
        opt = self._option
        self._layout_key = None
        self.title.setOption(_component_opt(opt.get("title"), "show"))
        self.legend.setOption(_component_opt(opt.get("legend"), "show"))
        self.tooltip.setOption(_component_opt(opt.get("tooltip"), "show"))
        series_opts = [s for s in (opt.get("series") or []) if isinstance(s, dict)]

        # 图例 selected：初始显隐状态（ECharts ``legend.selected``）
        legend_opt = opt.get("legend")
        if isinstance(legend_opt, dict):
            selected = legend_opt.get("selected")
            if isinstance(selected, dict):
                for name, visible in selected.items():
                    self._series_state[str(name)] = bool(visible)

        # 坐标系：calendar > polar > singleAxis > grid。grid 仅在
        # ①option 显式给出 xAxis/yAxis/grid，或 ②存在 coordinateSystem
        # 缺省且落在 grid 的系列时创建；纯无坐标 option（pie 等）不创建。
        self._coords = []
        if "calendar" in opt:
            c = self._make_coord(CalendarCoord, "calendar")
            if c is not None:
                self._coords.append(c)
        if "polar" in opt or "radiusAxis" in opt or "angleAxis" in opt:
            c = self._make_coord(PolarCoord, "polar")
            if c is not None:
                self._coords.append(c)
        if "singleAxis" in opt:
            c = self._make_coord(SingleAxisCoord, "singleAxis")
            if c is not None:
                self._coords.append(c)
        need_grid = (
            "xAxis" in opt
            or "yAxis" in opt
            or "grid" in opt
            or _needs_grid_coord(series_opts)
        )
        if need_grid:
            grid = self._make_coord(GridCoord, "grid")
            if grid is not None:
                self._coords.insert(0, grid)
        for c in self._coords:
            c.setSeries(series_opts)
        # 坐标轴的自然范围刚由 setSeries 重算：**跨 setOption 存活的 dataZoom**
        # （默认滚轮缩放是 host 组件）必须在这里重捕全量范围，否则它一直拿旧数据的
        # 范围当全量（空数据起步 → 钉在 0~1，30 万点到了也只画得出 2 个点）。
        for comp in self._components:
            capture = getattr(comp, "captureExtent", None)
            if not callable(capture):
                continue
            try:
                capture()
            except Exception as exc:
                warn_once(
                    warn_key(
                        "capture-extent",
                        comp.__class__.__name__,
                        type(exc).__name__,
                    ),
                    f"重捕轴范围失败（{comp.__class__.__name__}）: {exc!r}",
                )

        # 系列渲染器
        self._series = []
        for i, s in enumerate(series_opts):
            type_name = str(s.get("type") or "line")
            cls = SERIES_REGISTRY.get(type_name)
            if cls is None:
                continue  # 未注册类型安全跳过
            try:
                r = cls(self, s)
            except Exception as exc:
                warn_once(
                    warn_key("series-ctor", type_name, type(exc).__name__),
                    f"系列构造失败（type={type_name}）: {exc!r}",
                )
                continue
            # 注入 option 内序号：bar 槽位等按序号定位自身
            r._series_index = i
            if not r.name:
                r.name = f"series{i}"
                r.opt.setdefault("name", r.name)
            r.visible = self._seriesVisible(r.name)
            self._series.append(r)

        # 组件（类属性 optionKey + 构造 (chart, opt)）
        # **丢弃旧组件前先让它解挂在 chart 上的资源**（事件过滤器 / 定时器）。
        # 组件可能往 chart 上装事件过滤器（``DataZoomComponent`` 的滚轮缩放）或
        # 建定时器（``ChartTimeline``）；``_components = []`` 只丢 Python 引用，
        # Qt 侧的挂载还在 —— 旧实例会继续拦截输入并用陈旧状态改坐标轴，而它已经
        # 不在 ``chart.components`` 里，新组件对此一无所知。
        self._dispose_components()
        # option 组件全部重建；宿主注入的（``addComponent``）原样挂回去。
        self._components = list(self._host_components)
        for key, cls in list(COMPONENT_REGISTRY.items()):
            optionKey = getattr(cls, "optionKey", key)
            for value, series_opt in self._component_inputs(
                cls, opt, optionKey, series_opts
            ):
                self._spawn_component(cls, value, series_opt)
        # 直角坐标图默认滚轮缩放（用户配了 dataZoom 就完全听用户的）
        self._ensure_wheel_zoom()

        # 图例条目
        items = []
        for i, r in enumerate(self._series):
            items.append((r.name, self.colorForSeries(r)))
        self.legend.setItems(items)
        self._layout_all(force=True)

    def _make_coord(self, cls, kind: str):
        """构造单个坐标系：失败降级为 None 并记录一次（不拖垮整图）。"""
        try:
            return cls(self, self._option)
        except Exception as exc:
            warn_once(f"coord-ctor:{kind}", f"坐标构造失败（{kind}）: {exc!r}")
            return None

    def _component_inputs(self, cls, opt: dict, optionKey: str, series_opts: list):
        """列出该组件键下所有该建的实例：``(构造参数, 所属 series 或 None)``。

        **数组形式的顶层键要为每个元素各建一个实例**（组件声明
        ``spawnPerItem = True`` 时）。ECharts 的 ``visualMap`` 就是数组语义
        —— ``visualMap: [{...}, {...}]`` 是「多个 visualMap 各自绑定不同
        系列」的唯一写法 —— 而组件构造普遍是 ``dict(opt or {})``，收到 list
        直接 ``ValueError``，被 ``_spawn_component`` 的 except 吞掉，结果是
        **一个 visualMap 组件都建不起来**：色带不画、地图全部退回内置配色，
        只有一行告警。

        自己会处理数组的组件（``dataZoom`` 把 list 当多条、``graphic`` 把单个
        dict 包成 list）保持整包传入。
        """
        per_item = bool(getattr(cls, "spawnPerItem", False))

        def expand(value):
            """→ 构造参数列表（空 = 不建实例）。

            注意**不能**把「原样返回的 list」在下游当成多实例：那会把
            ``dataZoom: [...]`` 拆成每个条目一个组件，整套 dataZoom 行为全废
            （滑块不再联动、span 约束失效）。只有 ``spawnPerItem`` 为真时
            才逐元素拆。
            """
            if not isinstance(value, (dict, list)):
                return []
            if isinstance(value, list):
                if per_item:
                    return [v for v in value if isinstance(v, dict)]
                return [value]
            return [value]

        for value in expand(opt.get(optionKey)):
            yield value, None
        for s in series_opts:
            for value in expand(s.get(optionKey)):
                yield value, s

    def _spawn_component(self, cls, comp_opt, series_opt) -> None:
        try:
            comp = cls(self, comp_opt)
        except Exception as exc:
            warn_once(
                f"component-ctor:{getattr(cls, '__name__', cls)!r}",
                f"组件构造失败（{getattr(cls, 'optionKey', '')}）: {exc!r}",
            )
            return
        if series_opt is not None:
            comp.series_opt = series_opt
        # 组件事件 → 图表级信号（brush 选区 / toolbox 动作）
        selected = getattr(comp, "selected", None)
        if selected is not None and hasattr(selected, "connect"):
            try:
                selected.connect(self._onBrushSelected)
            except Exception:
                pass
        if getattr(comp, "optionKey", "") == "toolbox":
            comp.on_action = self.toolboxTriggered.emit
        self._components.append(comp)

    def _onBrushSelected(self, items) -> None:
        """brush 组件选区变化 → ``brushChanged`` 信号。"""
        self.brushChanged.emit(list(items or []))

    def _content_rect(self) -> QRectF:
        """扣除标题 / 图例后的坐标系可用区。"""
        rect = QRectF(0, 0, max(1, self.width()), max(1, self.height()))
        content = QRectF(rect)
        band = self.title.bandRect(rect.width(), rect.height())
        if not band.isNull():
            if self.title.atBottom:
                content.setBottom(max(content.top() + 1.0, band.top()))
            else:
                content.setTop(min(content.bottom() - 1.0, band.bottom()))
        if self.legend.shown:
            lw, lh = self.legend.preferredSize(content.width(), content.height())
            lo = self.legend.opt
            if self.legend.orient == "horizontal":
                if "top" in lo:
                    band = QRectF(content.left(), content.top(), content.width(), lh)
                    content.setTop(content.top() + lh)
                else:  # 默认 bottom
                    band = QRectF(
                        content.left(), content.bottom() - lh, content.width(), lh
                    )
                    content.setBottom(content.bottom() - lh)
            else:
                if "left" in lo:
                    band = QRectF(content.left(), content.top(), lw, content.height())
                    content.setLeft(content.left() + lw)
                else:  # 默认 right
                    band = QRectF(
                        content.right() - lw, content.top(), lw, content.height()
                    )
                    content.setRight(content.right() - lw)
            self.legend.layout(band)
        return content

    def invalidateLayout(self) -> None:
        """使布局缓存失效（下次绘制 / 布局时全量重排）。

        同时递增 ``_geometry_epoch``（进 ``_series_layer_key``）—— 渲染器除了
        图表级状态还有自己那份几何（下钻焦点、roam 平移缩放、treemap / sankey
        布局），那些变更一律经本方法通知，否则系列层位图会被原样贴回
        （实测旭日图下钻后位图逐字节不变，表现为「点了没反应」）。
        「哪些状态必须走这里」的清单见 AGENTS.md「charts」。
        """
        self._layout_key = None
        self._geometry_epoch += 1

    def _layout_cache_key(self):
        """布局缓存键：option 版本 / 视口尺寸 / 主题 / dataZoom 窗口状态。"""
        theme = eTheme.getThemeMode()
        dz = tuple(
            (getattr(c, "start", 0.0), getattr(c, "end", 100.0))
            for c in self._components
            if getattr(c, "optionKey", "") == "dataZoom"
        )
        return (self._opt_version, self.width(), self.height(), theme, dz)

    #: 底部组件条带顺序（从外到内，最外层贴近画布底边）
    _BOTTOM_BAND_ORDER = ("timeline", "dataZoom", "visualMap")

    def _layout_all(self, force: bool = False) -> None:
        """全量布局：组件条带 / 坐标系 / 系列 / 组件几何。

        组件条带：竖直 visualMap 占右侧，timeline 占最底部、dataZoom 在其上；
        坐标系与系列避开全部条带，组件各自落在专属条带内（互不遮挡）。

        布局缓存：键命中直接返回；动画进行中不缓存（每帧重算）。
        """
        if force:
            self._layout_key = None
        elif not self.anim.isRunning():
            key = self._layout_cache_key()
            if key == self._layout_key:
                return
            self._layout_key = key
        content = self._content_rect()
        right_reserves = []  # [(component, size)]
        bottom_reserves = []  # [(component, size)]
        for comp in self._components:
            right_fn = getattr(comp, "reserveRight", None)
            if callable(right_fn):
                try:
                    size = float(right_fn())
                except Exception:
                    size = 0.0
                if size > 0:
                    right_reserves.append((comp, size))
            bottom_fn = getattr(comp, "reserveBottom", None)
            if callable(bottom_fn):
                try:
                    size = float(bottom_fn())
                except Exception:
                    size = 0.0
                if size > 0:
                    bottom_reserves.append((comp, size))
        band_order = {key: index for index, key in enumerate(self._BOTTOM_BAND_ORDER)}
        bottom_reserves.sort(
            key=lambda item: band_order.get(getattr(item[0], "optionKey", ""), 99)
        )
        bottom_total = sum(size for _, size in bottom_reserves)
        right_total = sum(size for _, size in right_reserves)

        coord_content = QRectF(content)
        if right_total > 0:
            coord_content.setRight(
                max(coord_content.left() + 20.0, coord_content.right() - right_total)
            )
        if bottom_total > 0:
            coord_content.setBottom(
                max(coord_content.top() + 20.0, coord_content.bottom() - bottom_total)
            )

        # 组件专属条带（bottom 自底向上；right 自右向左）
        band_rects = {}
        cursor = content.bottom()
        for comp, size in bottom_reserves:
            band_rects[id(comp)] = QRectF(
                content.left(), cursor - size, content.width(), size
            )
            cursor -= size
        cursor = content.right()
        for comp, size in right_reserves:
            band_rects[id(comp)] = QRectF(
                cursor - size,
                content.top(),
                size,
                max(20.0, content.height() - bottom_total),
            )
            cursor -= size

        # dataZoom 窗口必须先写回坐标轴，再排系列：系列按**当前轴窗口**做
        # 「窗口裁剪 + 采样」，顺序反了就是「新轴 + 旧采样」的错配，且帧末布局
        # 缓存键（含窗口值）已命中 → 下一次布局 early-return，错配永久留下
        # （症状：缩放 / 平移后曲线变稀）。``apply()`` 本身幂等。
        for comp in self._components:
            apply_window = getattr(comp, "applyWindow", None)
            if not callable(apply_window):
                continue
            try:
                apply_window()
            except Exception as exc:
                warn_once(
                    warn_key(
                        "apply-window",
                        comp.__class__.__name__,
                        type(exc).__name__,
                    ),
                    f"窗口写回坐标轴失败（{comp.__class__.__name__}）: {exc!r}",
                )
        for c in self._coords:
            c.layout(coord_content)
        for r in self._series:
            try:
                r.layout(coord_content)
            except Exception as exc:
                warn_once(
                    warn_key(
                        "series-layout",
                        r.__class__.__name__,
                        r.name,
                        type(exc).__name__,
                    ),
                    f"系列布局异常（{r.name}）: {exc!r}",
                )
        for comp in self._components:
            layout = getattr(comp, "layout", None)
            if callable(layout):
                try:
                    layout(band_rects.get(id(comp), content))
                except Exception as exc:
                    warn_once(
                        f"component-layout:{comp.__class__.__name__}",
                        f"组件布局异常（{comp.__class__.__name__}）: {exc!r}",
                    )

    # ------------------------------------------------------------- Qt 事件
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_all()
        self.update()

    def _on_theme_changed(self, _mode) -> None:
        # 配色全部经 T() 实时取，重绘即生效；主题可能影响字体度量等布局
        # 输入，保守失效布局缓存（下一次绘制全量重排一次）
        self._layout_key = None
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            p.fillRect(self.rect(), self._background_color())
            self._layout_all()
            self._paint_content(p)
        except Exception as exc:  # noqa: BLE001
            # **这里原来只有 try/finally 没有 except** —— 任何漏网的异常都会
            # 穿过 Qt 回调边界 = 0xC0000409 静默终止（零 traceback）。
            # 已知入口：``backgroundColor`` 传 list / dict 时 ``QColor(bg)`` 抛
            # TypeError，而它在 ``_paint_content`` 的逐块守卫之外。
            # 绘制失败退化成「这一帧画得不全」，不能拖垮整个进程。
            warn_once("paint-event", f"绘制异常（已跳过本帧剩余内容）: {exc!r}")
        finally:
            # 无论任何绘制路径抛异常，QPainter 都必须收尾，
            # 否则后续绘制状态被污染会导致 Qt 崩溃
            p.end()

    def _background_color(self) -> QColor:
        """``backgroundColor`` → QColor，非法值回退主题底色。

        宿主可能传 list / dict / 任何非 str 值（``QColor(list)`` 是 TypeError），
        所以这里不能直接构造。
        """
        bg = self._option.get("backgroundColor")
        if isinstance(bg, QColor):
            return QColor(bg)
        if isinstance(bg, str) and bg.strip():
            color = QColor(bg)
            if color.isValid():
                return color
            warn_once(
                "background-color", f"backgroundColor 非法，已回退主题底色: {bg!r}"
            )
        return QColor(T("color.bg.base"))

    def _series_layer_key(self):
        """系列层位图缓存键（``None`` 表示本帧不缓存）。

        **只包含影响系列外观的状态**：option 版本 / ``_geometry_epoch`` /
        视口尺寸 / 主题 / dataZoom 窗口 / 逐系列可见性 / hover 命中 / 动画进度。
        后两项（hover、几何纪元）少一个就会「贴回旧外观」，逐项理由与踩坑见
        AGENTS.md「charts」。
        """
        if self.anim.isRunning():
            return None  # 动画每帧几何都在变，缓存无意义
        hover = None
        if self._hover is not None:
            r, hit = self._hover
            hover = (
                id(r),
                str(r.name),
                hit.get("dataIndex") if isinstance(hit, dict) else None,
            )
        return (
            self._opt_version,
            self._geometry_epoch,
            self.width(),
            self.height(),
            round(self.getDevicePixelRatio(), 4),
            eTheme.getThemeMode(),
            self._series_layer_key_zoom(),
            tuple((id(r), r.visible) for r in self._series),
            hover,
            # 图例悬停高亮会改系列不透明度 → 必须进键，否则贴回旧外观
            self._legend_hover,
        )

    def _series_layer_key_zoom(self):
        """dataZoom 窗口（影响采样与坐标映射）。"""
        return tuple(
            (getattr(c, "start", 0.0), getattr(c, "end", 100.0))
            for c in self._components
            if getattr(c, "optionKey", "") == "dataZoom"
        )

    def _paint_series_cached(self, p: QPainter, t: float) -> None:
        """绘制系列层（命中缓存则整幅位图贴回）。

        为什么值得：实测 8 系列 × 20 万点（1200×700）单帧绘制中
        **系列占 99.7%**（914 ms/3 帧 vs 坐标轴 2.9 ms/3 帧）。而悬停
        每移动一像素就 ``update()`` 一次 —— 200 次移动实测 40.7 秒
        （每次 203 ms），交互完全不可用。

        缓存命中时只做一次 ``drawImage``，悬停 / 动画期的重绘成本从
        「重建全部折线路径」降到「贴一张位图」。

        失效条件全部在 ``_series_layer_key`` 里；坐标轴、组件、图例、
        标题、tooltip **不缓存**（它们要么本来就便宜，要么逐帧变化）。
        """
        key = self._series_layer_key()
        if key is None:
            self._paint_series(p, t)
            return
        if self._series_pixmap_cache is not None and self._series_pixmap_key == key:
            p.drawImage(0, 0, self._series_pixmap_cache)
            return
        w, h = max(1, self.width()), max(1, self.height())
        dpr = self.getDevicePixelRatio()
        # 每维都要 ``max(1, ...)``：DPR < 1 时 ``int(round(1 * 0.5))`` 走银行家
        # 舍入得 **0**，QImage(0, h) 是空图，QPainter 画上去什么都不出 ——
        # 而外面那层 ``max(1, self.width())`` 让人以为已经防住了。
        img = QImage(
            max(1, int(round(w * dpr))),
            max(1, int(round(h * dpr))),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p2 = QPainter(img)
        try:
            p2.setRenderHint(QPainter.RenderHint.Antialiasing)
            p2.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            self._paint_series(p2, t)
        finally:
            p2.end()
        self._series_pixmap_cache = img
        self._series_pixmap_key = key
        p.drawImage(0, 0, img)

    def _paint_series(self, p: QPainter, t: float) -> None:
        """逐系列绘制（单系列异常不影响整图，且至少可见一次）。

        图例悬停高亮（``_legend_hover``）：命中系列正常绘制，其余降到 35%
        不透明度 —— 对齐 Plotly「悬停图例条目高亮对应 trace」的行为。
        """
        highlight = self._legend_hover
        for r in self._series:
            if not r.visible:
                continue
            try:
                # 记下本次进度：命中分发可能发生在下一帧 paint 之前
                r._anim_t = r.animProgress(t)
                if highlight is not None:
                    p.setOpacity(1.0 if r.name == highlight else 0.35)
                r.paint(p, r._anim_t)
            except Exception as exc:
                warn_once(
                    warn_key(
                        "series-paint", r.__class__.__name__, r.name, type(exc).__name__
                    ),
                    f"系列绘制异常（{r.name}）: {exc!r}",
                )
            finally:
                if highlight is not None:
                    p.setOpacity(1.0)

    def invalidateSeriesLayer(self) -> None:
        """使系列层位图缓存失效（数据 / 主题 / 尺寸变化时调用）。"""
        self._series_pixmap_cache = None
        self._series_pixmap_key = None

    def _paint_content(self, p: QPainter) -> None:
        """内容绘制体（坐标轴 → 系列 → 组件 → 图例/标题/提示框/遮罩）。

        从 ``paintEvent`` 抽出，使 ``benchmark`` 能画到离屏 QImage 上测
        **纯绘制成本**（不掺入窗口合成 / 交换等待）。**绘制顺序不可调换**
        （画家算法）。
        """
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        t = self.anim.t
        for c in self._coords:
            try:
                c.paintAxes(p)
            except Exception as exc:
                # 坐标绘制异常不能中断整帧：记录并跳过（否则 QPainter
                # 未收尾会污染绘制状态导致 Qt 崩溃）
                warn_once(
                    f"coord-paint:{c.__class__.__name__}",
                    f"坐标绘制异常（{c.__class__.__name__}）: {exc!r}",
                )
        self._paint_series_cached(p, t)
        for comp in self._components:
            paint = getattr(comp, "paint", None)
            if callable(paint):
                try:
                    paint(p, t)
                except TypeError:
                    try:
                        paint(p)
                    except Exception as exc:
                        warn_once(
                            f"component-paint:{comp.__class__.__name__}",
                            f"组件绘制异常（{comp.__class__.__name__}）: {exc!r}",
                        )
                except Exception as exc:
                    warn_once(
                        f"component-paint:{comp.__class__.__name__}",
                        f"组件绘制异常（{comp.__class__.__name__}）: {exc!r}",
                    )
        try:
            self.legend.paint(p)
        except Exception as exc:
            warn_once("legend-paint", f"图例绘制异常: {exc!r}")
        try:
            self.title.paint(p, self.title.bandRect(self.width(), self.height()))
        except Exception as exc:
            warn_once("title-paint", f"标题绘制异常: {exc!r}")
        try:
            self.tooltip.paint(p)
        except Exception as exc:
            warn_once("tooltip-paint", f"提示框绘制异常: {exc!r}")
        if self._loading:
            try:
                self._paint_loading(p)
            except Exception as exc:
                warn_once("loading-paint", f"加载遮罩绘制异常: {exc!r}")

    # -- 鼠标：legend 点击 / tooltip 跟随 / 组件钩子 ------------------------
    def _interactive_renderers(self) -> list:
        """可见系列（渲染器可覆写 onMousePress/Move/Release/onWheel 获得交互）。"""
        return [r for r in self._series if r.visible]

    def mousePressEvent(self, event) -> None:
        if self._loading:
            return
        pos = event.position()
        consumed = self._dispatch_hook("onMousePress", pos)
        # 记下这次按下：拖拽类组件（dataZoom ``inside`` / brush）会「吞掉」按下事件
        # （它们只能在这一刻起手），但**按下 → 原地松开**是一次点击，不该被吞 ——
        # 否则配了 dataZoom inside 的图表点数据点 / 点空区全都不发 ``itemClicked``
        # （ECharts 的 click 也是在松开时判定的）。
        self._press_ctx = (QPointF(pos), bool(consumed))
        if consumed:
            super().mousePressEvent(event)
            return
        if self.legend.shown and self.isInteractionEnabled("legend"):
            name = self.legend.hitTest(pos)
            if name is not None:
                self.legend.toggle(name)
                super().mousePressEvent(event)
                return
        self._emit_click_at(pos, event)
        super().mousePressEvent(event)

    def _emit_click_at(self, pos: QPointF, event=None) -> None:
        """命中数据点 → ``itemClicked``；空区且开 ``clickanywhere`` → 数据坐标载荷。"""
        if not self._interactive:
            return
        found = self._hitItemWithSeries(pos)
        if found is not None:
            renderer, hit = found
            self.itemClicked.emit(
                self._make_item_params(renderer, hit, "click", event, pos)
            )
            return
        if self._emptyAreaEnabled("clickanywhere"):
            # Plotly ``clickanywhere``：空区点击也发事件，载荷带光标的数据坐标
            empty = self._emptyAreaHit(pos)
            if empty is not None:
                empty["type"] = "click"
                empty["event"] = event
                self.itemClicked.emit(empty)

    def _make_item_params(
        self, renderer, hit: dict, event_type: str, event=None, pos=None
    ) -> dict:
        """命中 → ECharts 事件 params（click / highlight 等共用）。"""
        data_index = hit.get("dataIndex")
        data = None
        raw_data = renderer.data()
        if isinstance(data_index, int) and 0 <= data_index < len(raw_data):
            data = raw_data[data_index]
        # ECharts 的 params.color 是**数据项**颜色（雷达 colorBy='data'、饼图逐扇区），
        # 命中方给了就用它，别再回落到系列色 —— 否则事件里两个数据源同色。
        raw_color = hit.get("color")
        item_color = QColor(raw_color) if raw_color is not None else renderer.color()
        if not item_color.isValid():
            item_color = renderer.color()
        params = {
            "type": event_type,
            "componentType": "series",
            "seriesType": str(renderer.opt.get("type") or ""),
            "seriesIndex": self._series.index(renderer)
            if renderer in self._series
            else -1,
            "seriesId": renderer.id,
            "seriesName": renderer.name,
            "name": str(hit.get("name") or ""),
            "dataIndex": data_index,
            "data": data,
            "value": hit.get("value"),
            "color": item_color.name(),
        }
        for extra in ("title", "text"):
            if hit.get(extra) is not None:
                params[extra] = hit[extra]
        if hit.get("pos") is not None:
            params["pos"] = hit["pos"]
        if pos is not None:
            params["offsetX"] = float(pos.x())
            params["offsetY"] = float(pos.y())
        if event is not None:
            params["event"] = event
        return params

    def _call_hook(self, owner, hook_name: str, *args) -> bool:
        """调组件 / 渲染器的鼠标钩子，异常隔离并去重上报。

        **所有钩子都必须走这里。** 这些钩子跑在 Qt 的事件回调链上，未捕获的
        Python 异常会穿过 C++ 边界 → 进程直接 0xC0000409 终止、**零
        traceback**。而钩子实现里全是坐标换算与 option 取值，宿主传进来的
        option 一个畸形值就能让某个系列崩掉整个应用。原先只有 ``wheelEvent``
        有这层保护，move / press / release / double-click 六处都是裸调。
        """
        hook = getattr(owner, hook_name, None)
        if not callable(hook):
            return False
        label = getattr(owner, "name", "") or owner.__class__.__name__
        try:
            return bool(hook(*args))
        except Exception as exc:
            warn_once(
                warn_key(
                    f"{hook_name}",
                    owner.__class__.__name__,
                    label,
                    type(exc).__name__,
                ),
                f"{owner.__class__.__name__}.{hook_name} 异常（{label}）: {exc!r}",
            )
            return False

    def _dispatch_hook(self, hook_name: str, *args) -> bool:
        """按「组件优先、系列其次」的顺序分发钩子，任一消费则返回 True。"""
        for comp in self._interactive_components():
            if self._call_hook(comp, hook_name, *args):
                return True
        if not self._interactive:
            return False
        for renderer in self._interactive_renderers():
            if self._call_hook(renderer, hook_name, *args):
                return True
        return False

    def mouseMoveEvent(self, event) -> None:
        if self._loading:
            return
        pos = event.position()
        consumed = self._dispatch_hook("onMouseMove", pos)
        if not consumed:
            # 图例悬停高亮优先于提示框：指针在图例上时不出 tooltip，只高亮系列
            legend_hover = (
                self.legend.hitTest(pos)
                if self.legend.shown and self.isInteractionEnabled("legend")
                else None
            )
            if legend_hover != self._legend_hover:
                self._legend_hover = legend_hover
                self.update()
            if legend_hover is not None:
                if self.tooltip.active:
                    self.tooltip.hide()
                if self._hover is not None:
                    self._hover = None
                    self.update()
            elif self.isInteractionEnabled("tooltip"):
                self._update_tooltip(pos)
            elif self.tooltip.active:
                self.tooltip.hide()
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._loading:
            return
        pos = event.position()
        self._dispatch_hook("onMouseRelease", pos)
        ctx = getattr(self, "_press_ctx", None)
        self._press_ctx = None
        if ctx is not None:
            start, consumed = ctx
            # 位移 ≤ 4px 视作点击：把被拖拽组件吞掉的这次按下还给「点击」语义
            dragged = math.hypot(pos.x() - start.x(), pos.y() - start.y()) > 4.0
            if consumed and not dragged:
                over_legend = False
                if self.legend.shown:
                    over_legend = self.legend.hitTest(start) is not None
                if not over_legend:
                    self._emit_click_at(pos, event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._loading:
            return
        # 交互组件（如 roam / dataZoom）先接：被消费就不做默认复位。
        if self._dispatch_hook("onMouseDoubleClick", event.position()):
            super().mouseDoubleClickEvent(event)
            return
        # 双击复位（Plotly ``doubleClick: 'reset'`` 语义）：把缩放 / 平移 / 缩放窗口
        # 还原到初始状态。可用 ``setDoubleClickReset(False)`` 关掉。
        if self._double_click_reset:
            self.resetView()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:
        """滚轮：优先交给交互组件（如 dataZoom inside）消费。

        组件经 ``onWheel(event)`` 钩子返回 True 时显式 ``event.accept()``，
        事件状态为「已消费」—— 祖先滚动区（ElaScrollArea / 页面）不会再
        同时滚动，解决「图表缩放与页面滚动同时触发」的问题；未被消费的
        滚轮按默认路径向上冒泡（图表外区域页面正常滚动）。
        交互关闭（``setInteractive`` / ``setInteractionEnabled``）时不消费。
        """
        if self._loading:
            return
        if self._dispatch_hook("onWheel", event):
            event.accept()
            return
        super().wheelEvent(event)

    def leaveEvent(self, event) -> None:
        self.tooltip.hide()
        if self._hover is not None:
            self._hover = None
        if self._legend_hover is not None:
            self._legend_hover = None
        self.update()
        super().leaveEvent(event)

    # -- tooltip 聚合 ------------------------------------------------------
    def textStyle(self) -> dict:
        """全局 ``textStyle``（扩展查询；作为标签 / 轴文字的兜底样式）。"""
        style = self._option.get("textStyle")
        return style if isinstance(style, dict) else {}

    def hitItem(self, pos: QPointF):
        """坐标命中数据项 → ECharts click params（无命中 None）。"""
        found = self._hitItemWithSeries(pos)
        if not found:
            return None
        renderer, hit = found
        return self._make_item_params(renderer, hit, "click", None, pos)

    def hoverInfo(self):
        """当前悬停命中 ``(渲染器, hit)``；无悬停返回 ``None``（emphasis 高亮用）。"""
        return self._hover

    def _hitItemWithSeries(self, pos: QPointF):
        """命中查询：返回 ``(渲染器, 命中 info)``；无命中 None（silent 系列跳过）。

        **markPoint / markLine 优先**：它们画在系列之上，先判才符合「上层元素
        拿走悬停」的直觉（原先它们的 ``hitTest`` 是死代码 —— 只遍历
        ``_series``，组件层从没被问过，于是这两类标注既没 tooltip 也没
        click）。

        **markArea / graphic 不参与**：前者是半透明**背景区域**，接进来会让
        「悬停区域内任何位置」都抢走系列的悬停（明确的退化）；后者是纯装饰，
        ECharts 侧默认也不参与交互。两条都不实现 ``hitTest``，免得留下
        「看着能用其实从不调」的死代码。
        """
        # 动画进度可能在最后一次 paint 之后又推进了（鼠标事件先到），这里
        # 按当前进度刷新一遍，保证 hitTest 看到的动画阶段是「现在」。
        t = self.anim.t
        for comp in self._components:
            if str(getattr(comp, "optionKey", "")) not in _HOVERABLE_COMPONENTS:
                continue
            hit = None
            try:
                hit = comp.hitTest(pos)
            except Exception as exc:
                warn_once(
                    warn_key(
                        "component-hit",
                        comp.__class__.__name__,
                        type(exc).__name__,
                    ),
                    f"{comp.__class__.__name__}.hitTest 异常: {exc!r}",
                )
                hit = None
            if hit:
                renderer = comp._renderer() if hasattr(comp, "_renderer") else None
                return renderer, hit
        for r in reversed(self._series):
            if not r.visible or r.silent:
                continue
            hit = None
            try:
                r._anim_t = r.animProgress(t)
                hit = r.hitTest(pos)
            except Exception:
                hit = None
            if hit:
                return r, hit
        return None

    def _update_tooltip(self, pos: QPointF) -> None:
        if not self.tooltip.shown or not self._series or self.tooltip.trigger == "none":
            if self.tooltip.active:
                self.tooltip.hide()
            if self._hover is not None:
                self._hover = None
                self.update()
            return
        if self.tooltip.trigger == "axis":
            if self._hover is not None:
                self._hover = None
            self._tooltip_axis(pos)
        else:
            self._tooltip_item(pos)
        self.update()

    def _emptyAreaHit(self, pos: QPointF) -> Optional[dict]:
        """空区命中：把像素反查成数据坐标（``hoveranywhere`` / ``clickanywhere``）。

        Plotly 语义：光标不在任何 trace 上时，事件 / 提示仍带**光标的数据坐标**。
        坐标系不支持反查（polar / calendar 等）时返回 ``None``。
        """
        coord = self.primaryCoord()
        if coord is None:
            return None
        try:
            x, y = coord.invertPoint(pos)
        except Exception:
            return None
        if x is None or y is None:
            return None
        if isinstance(x, (int, float)) and not math.isfinite(x):
            return None
        if isinstance(y, (int, float)) and not math.isfinite(y):
            return None
        return {
            "componentType": "grid",
            "series": "",
            "name": "",
            "value": [x, y],
            "x": x,
            "y": y,
        }

    def _emptyAreaEnabled(self, key: str) -> bool:
        """读取 ``hoveranywhere`` / ``clickanywhere``（默认关，对齐 Plotly）。"""
        opt = self._option.get(key)
        if isinstance(opt, bool):
            return opt
        tooltip_opt = self._option.get("tooltip")
        if key == "hoveranywhere" and isinstance(tooltip_opt, dict):
            return bool(tooltip_opt.get("hoverAnywhere", False))
        return False

    def _tooltip_item(self, pos: QPointF) -> None:
        found = self._hitItemWithSeries(pos)
        if found is not None:
            renderer, hit = found
            if (
                self._hover is None
                or self._hover[0] is not renderer
                or (self._hover[1].get("dataIndex") != hit.get("dataIndex"))
            ):
                self._hover = (renderer, hit)
            raw_color = hit.get("color")
            color = QColor(raw_color) if raw_color is not None else renderer.color()
            if not color.isValid():
                color = renderer.color()
            self.tooltip.showAt(pos, self.tooltip.buildLines(hit, color, renderer.name))
            return
        if self._hover is not None:
            self._hover = None
        if self._emptyAreaEnabled("hoveranywhere"):
            empty = self._emptyAreaHit(pos)
            if empty is not None:
                color = QColor(T("color.text.secondary"))
                self.tooltip.showAt(
                    pos, self.tooltip.buildLines(empty, color, "")
                )
                self.update()
                return
        self.tooltip.hide()

    def _tooltip_axis(self, pos: QPointF) -> None:
        coord = self.primaryCoord()
        lines = []
        marker = None
        anchor = None
        if coord is not None:
            try:
                anchor = coord.invertX(pos)
            except Exception:
                anchor = None
        if anchor is not None:
            # **必须先判有限**。``AxisModel.invert`` 返回
            # ``vmin + frac * (vmax - vmin)``，而 ±1e308 的轴跨度相减会溢出成
            # inf → 结果是 inf → ``int(inf)`` 抛 ``OverflowError``。这行跑在
            # ``mouseMoveEvent`` 里，抛出去就是 0xC0000409 静默终止。
            # 非有限时退回 None（走 item 命中），别让一次悬停干掉进程。
            if isinstance(anchor, (int, float)) and not math.isfinite(anchor):
                anchor = None
        if anchor is not None:
            idx = int(anchor) if isinstance(anchor, (int, float)) else anchor
            for r in self._series:
                if not r.visible:
                    continue
                info = None
                try:
                    info = r.valueAtIndex(idx)
                except Exception:
                    info = None
                if info:
                    lines.append(
                        (
                            r.color(),
                            str(info.get("series") or r.name),
                            formatValue(info.get("value")),
                            info.get("value"),
                        )
                    )
                    if marker is None and info.get("pos") is not None:
                        marker = info["pos"]
        else:
            # 坐标系不支持反查：退化为 item 模式
            self._tooltip_item(pos)
            return
        if not lines:
            # 退化：尝试 item 命中
            self._tooltip_item(pos)
            return
        # unified 排序：ECharts ``tooltip.order``（``valueAsc`` / ``valueDesc``）
        # 或 Plotly 风格的 ``hoversort``（``value ascending`` / ``value descending``）
        order = ""
        tooltip_opt = self._option.get("tooltip")
        if isinstance(tooltip_opt, dict):
            order = (
                str(tooltip_opt.get("order") or tooltip_opt.get("hoversort") or "")
                .strip()
                .lower()
            )
        if order in ("valueasc", "value ascending", "ascending"):
            lines.sort(key=lambda row: _sort_value(row[3]))
        elif order in ("valuedesc", "value descending", "descending"):
            lines.sort(key=lambda row: _sort_value(row[3]), reverse=True)
        title = None
        if isinstance(coord, GridCoord) and coord.x_axis.type == "category":
            cats = coord.x_axis.categories
            if isinstance(idx, int) and 0 <= idx < len(cats):
                title = cats[idx]
        # 交给 tooltip 的行统一为 (color, name, value_str)（第 4 项仅供排序）
        lines = [(color, name, value) for color, name, value, *_rest in lines]
        if title:
            lines.insert(0, (None, "", title))
        self.tooltip.showAt(pos, lines, marker_pos=marker or pos)


# ---------------------------------------------------------------------------
# 内置自检用简易 line 系列
def _sort_value(value) -> float:
    """unified 排序键：数值原样，非数值一律 +inf（正序落尾、倒序落头）。"""
    if isinstance(value, bool) or value is None:
        return math.inf
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return math.inf
    return number if math.isfinite(number) else math.inf


# ---------------------------------------------------------------------------


class SimpleLineSeriesRenderer(SeriesRenderer):
    """内置简易 line 渲染器（接口自测 / 兜底实现）。

    注意：本实现刻意保持简单（直线段 + 圆点，无 smooth/areaStyle/step），
    **不自动注册**；包入口导入 ``series_cartesian`` 时会注册完整版 ``line``，
    仅当需要无依赖的最小渲染器做自测时才手动
    ``registerSeries("line", SimpleLineSeriesRenderer)``。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._points = []  # [QPointF]（当前数据）
        self._prev_points = []  # [QPointF]（旧数据，过渡动画用）
        self._entries = []  # [(x, y)] 解析后的数据

    def layout(self, rect: QRectF) -> None:
        coord = self.chart.coordFor(self.opt)
        self._prev_points = list(self._points)
        self._points = []
        self._entries = []
        if coord is None:
            return
        single = getattr(coord, "kind", "") == "singleAxis"
        for i, item in enumerate(self.data()):
            x, y = parseDataPoint(item, i)
            self._entries.append((x, y))
            if y is None:
                self._points.append(None)
                continue
            try:
                if single:
                    # 单轴：数值即轴上位置（y 为解析出的数值）
                    self._points.append(coord.mapPoint(y))
                else:
                    self._points.append(coord.mapPoint(x, y))
            except Exception:
                self._points.append(None)

    def _animated_points(self, anim_t: float):
        """旧→新插值：长度一致时逐点 lerp；否则返回当前点列。"""
        cur = self._points
        prev_src = self._prev_points
        # 过渡动画路径：prev_data 与当前 data 等长时按数据值重映射旧点
        if self.prev_data is not None and len(self.prev_data) == len(self._entries):
            coord = self.chart.coordFor(self.opt)
            prev = []
            for i, item in enumerate(self.prev_data):
                x, y = parseDataPoint(item, i)
                if y is None or coord is None:
                    prev.append(None)
                    continue
                try:
                    prev.append(coord.mapPoint(x, y))
                except Exception:
                    prev.append(None)
            prev_src = prev
        if len(prev_src) != len(cur):
            return cur
        out = []
        for a, b in zip(prev_src, cur):
            if a is None or b is None:
                out.append(b)
            else:
                out.append(
                    QPointF(
                        a.x() + (b.x() - a.x()) * anim_t,
                        a.y() + (b.y() - a.y()) * anim_t,
                    )
                )
        return out

    def paint(self, p: QPainter, anim_t: float) -> None:
        pts = self._animated_points(anim_t)
        valid = [pt for pt in pts if pt is not None]
        if not valid:
            return
        p.save()
        color = self.color()
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # 折线（跳过 None 断点）
        seg = []
        for pt in pts:
            if pt is None:
                if len(seg) >= 2:
                    p.drawPolyline(QPolygonF(seg))
                seg = []
            else:
                seg.append(pt)
        if len(seg) >= 2:
            p.drawPolyline(QPolygonF(seg))
        # 数据点
        p.setBrush(QColor(T("color.bg.elevated")))
        for pt in valid:
            p.drawEllipse(pt, 3.0, 3.0)
        p.restore()

    def hitTest(self, pos: QPointF):
        best = None
        best_d = self.chart.hitRadius()  # 命中半径 px（tooltip.hitRadius）
        for i, pt in enumerate(self._points):
            if pt is None:
                continue
            d = ((pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2) ** 0.5
            if d <= best_d:
                best_d = d
                best = i
        if best is None:
            return None
        x, y = self._entries[best]
        return {
            "name": self.name,
            "value": y,
            "series": self.name,
            "dataIndex": best,
            "x": x,
        }

    def valueAtIndex(self, index: int):
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        if not isinstance(idx, int) or not (0 <= idx < len(self._entries)):
            return None
        x, y = self._entries[idx]
        if y is None:
            return None
        pos = self._points[idx] if idx < len(self._points) else None
        return {"name": self.name, "value": y, "series": self.name, "pos": pos}
