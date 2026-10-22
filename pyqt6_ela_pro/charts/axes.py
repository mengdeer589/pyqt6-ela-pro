"""
坐标系与轴模型。

- ``Coord``：坐标系协议基类，子类实现
  ``layout(rect)`` / ``mapPoint(x, y)`` / ``paintAxes(p)`` /
  ``paintTooltipMarker(p, pos)``；可选 ``setSeries(series_opts)``、
  ``invertX(pos)``（tooltip axis 触发用）。
- ``AxisModel``：category / value 轴模型，支持 name、min/max、nice ticks。
- ``GridCoord``：直角坐标（grid 边距 + x/y 轴 + 刻度网格线）。
- ``PolarCoord``：极坐标（radiusAxis/angleAxis，多边形/圆形网格）。
- ``SingleAxisCoord``：横向单轴。
- ``CalendarCoord``：GitHub 式 周(列)×星期(行) 年历网格。
- ``niceTicks(vmin, vmax, segments=5)``：数值轴 nice ticks 工具函数。

构造约定：``Coord`` 子类签名为 ``(chart, option)``，``option`` 为完整
图表 option 字典，各坐标系自取所需键（如 ``grid`` / ``xAxis`` …）。
所有配色经 ``T()`` 实时读取，主题切换后重绘即生效。

移植自 InstructionX_UIKit.charts.axes（原库为 PyQt6；主题令牌经
charts._tokens 适配到 eTheme / ElaThemeType，原库无 LICENSE，保留出处）。
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from .._internal import system_cjk_font_family
from ._tokens import FONT_FAMILIES, T
from ._utils import to_float as _utils_to_float
from . import _downsample as _ds
from . import data as _cdata

#: 数据对象身份 → 数值范围的缓存（见 ``GridCoord._extent``）。
#:
#: **必须同时持有数据对象的强引用**（缓存值是 ``(数据对象, 范围)``）：只用
#: ``id`` 做键时，对象被回收后 id 会被下一个对象复用，于是把别的数据的范围
#: 当成自己的 —— 表现为换数据后轴范围莫名其妙。命中时额外用 ``is`` 复核，
#: 强引用使这一复核恒成立，代价只是一次指针比较。
_EXTENT_CACHE: dict = {}

#: 缓存条目上限。超限整表清空（不做 LRU）：范围计算是纯函数，重建代价小，
#: 而 LRU 的 bookkeeping 在每次缩放的热路径上不划算。
_EXTENT_CACHE_LIMIT = 64

__all__ = [
    "niceTicks",
    "formatValue",
    "chartFont",
    "Coord",
    "AxisModel",
    "GridCoord",
    "PolarCoord",
    "SingleAxisCoord",
    "CalendarCoord",
]


# ---------------------------------------------------------------------------
# 工具：字体 / 数值格式化 / nice ticks
# ---------------------------------------------------------------------------

#: 单根轴的刻度数硬上限。超过就把 step 放大到等分（见 ``_clamp_tick_count``）。
#: 取 2000 量级：正常图表的段数是 5，最多几百根；2000 根网格线 + 标签在
#: 1200x700 下仍可接受，而它是「step 细到毫无意义」时的兜底。
_MAX_TICKS = 2000

#: ``niceTicks`` 的段数上限（``splitNumber`` 走同一条路）。
_MAX_SEGMENTS = 200

#: ``datetime.date`` 的 year 上限（``date(10000, ...)`` 抛 ValueError）。
_MAX_DATE_YEAR = 9999


def chartFont(px: int = None, weight: int = None) -> QFont:
    """构造图表用字体（``FONT_FAMILIES`` 字族；px 默认 font.xs）。

    中文系统收成单族 ``Microsoft YaHei``（即 ``FONT_FAMILIES`` 首族）：多族列表
    在 Win7 上是慢 shaping 路径（图表文本逐重绘放大，见「下游项目反馈bug.md」
    §3），而列表其余族全是 mac / linux 字体、Windows 上本就轮不到。
    """
    font = QFont()
    cjk_family = system_cjk_font_family()
    font.setFamilies([cjk_family] if cjk_family else list(FONT_FAMILIES))
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPixelSize(int(px if px else T("font.xs")))
    if weight:
        font.setWeight(QFont.Weight(int(weight)))
    return font


def formatValue(v) -> str:
    """数值标签格式化：整数不带小数点，其余保留至多两位小数。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return ""
        if float(v).is_integer() and abs(v) < 1e15:
            return str(int(v))
        # **两位小数对小于 0.005 的量级完全不够**，而 ``rstrip("0")`` 再把
        # "0.00" 清成 "0" —— 于是同一根轴上所有刻度标签变成同一个字符串。
        # 实测数据在 1e-3 量级（niceTicks(0, 0.001) 的 step = 0.0002）时，
        # 6 个刻度的标签全是 "0"，负小数还会给出 "-0"。
        # 小数位按量级自适应，封顶 8 位（再多是浮点尾数，如 0.6000000000000001）。
        av = abs(float(v))
        if av == 0.0:
            return "0"
        decimals = min(8, max(2, -math.floor(math.log10(av)) + 2))
        text = f"{v:.{decimals}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"
    return str(v)


def niceTicks(vmin: float, vmax: float, segments: int = 5):
    """数值轴 nice ticks，返回 ``(nice_min, nice_max, ticks)``；``segments`` 是目标
    段数（约 5 段），``ticks`` 为含端点的刻度值列表。
    """
    vmin = float(vmin)
    vmax = float(vmax)
    if vmin > vmax:
        vmin, vmax = vmax, vmin
    if not math.isfinite(vmin) or not math.isfinite(vmax):
        vmin, vmax = 0.0, 1.0
    if vmin == vmax:
        if vmin == 0:
            vmax = 1.0
        else:
            pad = abs(vmin) * 0.5
            vmin -= pad
            vmax += pad
    segments = max(1, min(int(segments), _MAX_SEGMENTS))
    span = vmax - vmin
    # 端点有限不代表差值有限：±1e308 的差会溢出成 inf，随后 log10(inf)=inf、
    # math.floor(inf) 抛 OverflowError（曾使 data:[1e308,-1e308] 直接崩掉 setOption）。
    if not math.isfinite(span) or span <= 0.0:
        vmin, vmax = 0.0, 1.0
        span = 1.0
    step0 = span / segments
    mag = 10 ** math.floor(math.log10(step0)) if step0 > 0 else 1.0
    step = mag
    for m in (1.0, 2.0, 5.0, 10.0):
        if m * mag >= step0 - 1e-12:
            step = m * mag
            break
    # 端点 / step 仍可能溢出（step 极小时），先夹到有限范围再取整
    lo_q = vmin / step
    hi_q = vmax / step
    if not math.isfinite(lo_q):
        lo_q = -1e15
    if not math.isfinite(hi_q):
        hi_q = 1e15
    nice_min = math.floor(lo_q) * step
    nice_max = math.ceil(hi_q) * step
    if nice_min == nice_max:
        nice_max = nice_min + step
    # 用整数计数避免浮点累积误差
    n = int(round((nice_max - nice_min) / step))
    # **刻度数硬上限**。step 极小时（``maxInterval: 1e-9``、或 step 恰好比
    # 浮点分辨率还细）n 会膨胀到百万 / 千万级，而下面这个循环逐个 append 到
    # Python list、随后每根刻度都要画一条网格线 + 一个标签。实测跨度 1 的
    # 数据配 ``maxInterval=1e-6`` → 约 200 万刻度、单帧 35 秒；1e-9 直接
    # 挂死（一分钟无返回）。宁可少几根网格线，也不能毁掉整帧。
    if n > _MAX_TICKS:
        return _clamp_tick_count(nice_min, nice_max, step, _MAX_TICKS)
    ticks = []
    for i in range(n + 1):
        t = nice_min + i * step
        ticks.append(0.0 if abs(t) < step * 1e-9 else t)
    return nice_min, nice_max, ticks


def _clamp_tick_count(nice_min, nice_max, step, limit):
    """刻度过多时改用放大 step 的等分刻度，并保持端点不变。

    返回的刻度数 ≤ ``limit + 1``。``step`` 放大到能整除跨度为止 —— 不整除
    时最后一根刻度会越过 ``nice_max``，宁可让 ``nice_max`` 与最后刻度略有
    出入，也不要让坐标范围与数据脱节。
    """
    span = nice_max - nice_min
    if span <= 0.0 or step <= 0.0:
        return nice_min, nice_max, [nice_min]
    grown = step
    while True:
        count = int(math.ceil(span / grown))
        if count <= limit:
            break
        grown *= 10.0
    ticks = [nice_min + i * grown for i in range(count + 1)]
    # 末刻度与 nice_max 差得太多时，把末刻度直接钉到 nice_max
    if ticks and abs(ticks[-1] - nice_max) > grown * 0.5:
        ticks[-1] = nice_max
    return nice_min, nice_max, ticks


def _format_log_tick(value) -> str:
    """log 轴刻度文案：普通量级走 ``formatValue``，极端量级用 ``1e-5`` / ``1e6``。"""
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        return formatValue(value)
    if v == 0.0 or not math.isfinite(v):
        return formatValue(value)
    a = abs(v)
    if 1e-4 <= a < 1e6:
        return formatValue(v)
    exp = int(math.floor(math.log10(a)))
    mant = v / (10.0**exp)
    if abs(mant - round(mant)) < 1e-9:
        mant = float(round(mant))
    text = f"{mant:g}e{exp}"
    return text.replace("e+", "e")


def _log_ticks(vmin: float, vmax: float, base: float, segments: int = 5) -> list:
    """对数轴刻度：按数量级取幂；跨度不足两个数量级时补 1/2/5 子刻度。"""
    if vmin <= 0.0 or vmax <= 0.0 or vmax <= vmin:
        return [1.0, 10.0]
    log_base = math.log(base)
    e0 = int(math.floor(math.log(vmin) / log_base))
    e1 = int(math.ceil(math.log(vmax) / log_base))
    if e1 <= e0:
        e1 = e0 + 1
    ticks = [base**e for e in range(e0, e1 + 1)]
    # 十年内（例如 1..100）只有 3 个幂次标签太稀，补 2/5 子刻度。
    if e1 - e0 <= 2 and abs(base - 10.0) < 1e-9:
        ticks = [m * (10.0**e) for e in range(e0, e1 + 1) for m in (1, 2, 5)]
    ticks = [t for t in ticks if vmin * (1.0 - 1e-9) <= t <= vmax * (1.0 + 1e-9)]
    if len(ticks) < 2:
        ticks = [vmin, vmax]
    limit = max(2, min(int(segments) + 1, _MAX_TICKS))
    if len(ticks) > limit:
        step = max(1, int(math.ceil(len(ticks) / float(limit))))
        ticks = ticks[::step]
        if ticks[-1] != vmax:
            ticks.append(vmax)
    return ticks


# ---------------------------------------------------------------------------
# 坐标协议基类
# ---------------------------------------------------------------------------


class Coord:
    """坐标系协议基类。

    子类必须实现 ``layout`` / ``mapPoint`` / ``paintAxes`` /
    ``paintTooltipMarker``。可选：
    ``setSeries(series_opts)`` 接收原始系列 option 列表用于范围统计；
    ``invertX(pos)`` 由像素反推主轴数据值（tooltip axis 触发用）；
    ``invertPoint(pos)`` 像素 → 数据（``convertFromPixel``）；
    ``containPoint(pos)`` 像素是否落在坐标系内（``containPixel``）。
    """

    #: 坐标系种类名（"grid" / "polar" / "singleAxis" / "calendar"），
    #: 供 ElaChartWidget.coordFor 按 series.coordinateSystem 匹配。
    kind = ""

    def __init__(self, chart=None, option: dict = None):
        self.chart = chart
        self.option = dict(option or {})
        self.rect = QRectF()

    # -- 协议 ------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        """按可用矩形完成几何布局。"""
        self.rect = QRectF(rect)

    def mapPoint(self, x, y=None) -> QPointF:
        """数据 → 像素。polar 为 (angle, radius)；calendar/single 单参。"""
        raise NotImplementedError

    def paintAxes(self, p: QPainter) -> None:
        """绘制轴线 / 刻度 / 网格 / 标签（主题感知，T() 实时取色）。"""
        raise NotImplementedError

    def paintTooltipMarker(
        self, p: QPainter, pos: QPointF, kind: str = "cross"
    ) -> None:
        """绘制指示线（``kind``：line / shadow / cross / none）。"""
        raise NotImplementedError

    # -- 可选 ------------------------------------------------------------
    def setSeries(self, series_opts: list) -> None:
        """接收原始系列 option 列表（布局前调用，用于数值范围统计）。"""

    def invertX(self, pos: QPointF):
        """像素 → 主轴数据值（默认不支持，返回 None）。"""
        return None

    def invertPoint(self, pos: QPointF):
        """像素 → 数据值（``convertFromPixel``；默认不支持，返回 None）。"""
        return None

    def containPoint(self, pos: QPointF) -> bool:
        """像素是否落在坐标系内（``containPixel``；默认按可用矩形判定）。"""
        return bool(self.rect.contains(QPointF(pos)))


# ---------------------------------------------------------------------------
# 轴模型
# ---------------------------------------------------------------------------


def _iter_data_values(data):
    """从系列 data 中迭代全部**有限**数值（支持 number / [x, y] / {"value": v}）。

    滤 NaN / inf 的原因与清单见 AGENTS.md「charts」。此处除极值污染外还多一层：
    调用方（``SingleAxisCoord.setSeries``）用 ``min()`` / ``max()`` 归约，而
    ``min()`` 遇 NaN 的结果是**顺序相关**的 —— 实测同一份数据 ``[1, 2, nan, 5]``，
    NaN 在首位得 0..1、在末位得 0..5。
    """
    if data is None:
        return
    for item in data:
        if item is None:
            continue
        v = item
        if isinstance(item, dict):
            v = item.get("value")
        if isinstance(v, (list, tuple)):
            for sub in v:
                if (
                    isinstance(sub, (int, float))
                    and not isinstance(sub, bool)
                    and math.isfinite(sub)
                ):
                    yield float(sub)
        elif (
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
        ):
            yield float(v)


class AxisModel:
    """坐标轴模型：category（list[str]）或 value（自动 nice ticks）。

    ECharts 轴键：``type`` / ``data`` / ``name`` / ``min`` / ``max`` /
    ``boundaryGap`` / ``inverse`` / ``scale`` / ``nameLocation`` / ``nameGap`` /
    ``interval`` / ``minInterval`` / ``maxInterval`` / ``splitNumber`` /
    ``axisLabel`` / ``axisTick`` / ``axisLine`` / ``splitLine`` / ``splitArea``。

    :param default_type: opt 未给 ``type`` 时的兜底
    """

    def __init__(self, opt: dict = None, default_type: str = "value"):
        opt = dict(opt or {})
        self.opt = opt
        self.type = str(opt.get("type") or default_type).strip().lower()
        self.name = str(opt.get("name") or "")
        #: ``xAxis`` / ``yAxis`` 的 ``position``（bottom/top 或 left/right）。
        #: 空串表示由 :class:`GridCoord` 按索引给默认值。
        self.position = str(opt.get("position") or "").strip().lower()
        #: 同侧多轴的外扩偏移（px）；0 表示贴绘图区边缘。
        try:
            self.offset = max(0.0, float(opt.get("offset", 0) or 0))
        except (TypeError, ValueError, OverflowError):
            self.offset = 0.0
        #: log 轴底数（``type="log"`` 时生效）
        try:
            self.log_base = float(opt.get("logBase", 10) or 10)
        except (TypeError, ValueError, OverflowError):
            self.log_base = 10.0
        if not math.isfinite(self.log_base) or self.log_base <= 1.0:
            self.log_base = 10.0
        #: ``windowOffset()`` 的记忆化缓存（类别一变就作废，见 property setter）
        self._window_offset_cache = None
        self.categories = [str(c) for c in (opt.get("data") or [])]
        #: dataZoom 全量类别缓存：``categories`` 可能被窗口替换，
        #: 本属性始终保留完整列表，供窗外类别映射与窗口偏移换算
        self._all_categories = list(self.categories)
        self.min = opt.get("min")
        self.max = opt.get("max")
        self.inverse = bool(opt.get("inverse", False))
        #: category 轴点位：True（默认）落在 band 中心，False 落在边界
        self.boundary_gap = self._parse_boundary_gap(opt.get("boundaryGap"))
        #: value 轴是否允许不包含 0 基线（ECharts ``scale``）
        self.scale = bool(opt.get("scale", False))
        self.name_location = str(opt.get("nameLocation") or "end")
        try:
            self.name_gap = float(opt.get("nameGap", 8))
        except (TypeError, ValueError, OverflowError):
            self.name_gap = 8.0
        # value 轴：布局前由 setExtent 填充
        self.vmin = 0.0
        self.vmax = 1.0
        self._ticks = [0.0, 1.0]

    @staticmethod
    def _parse_boundary_gap(raw) -> bool:
        """``boundaryGap`` 解析：bool / ``[lo, hi]``（数组视为开启）。"""
        if raw is None:
            return True
        if isinstance(raw, (list, tuple)):
            return True
        return bool(raw)

    # -- 范围 ------------------------------------------------------------
    def setExtent(
        self,
        data_min: float = None,
        data_max: float = None,
        segments: int = 5,
    ) -> None:
        """按数据范围计算 value / log 轴 nice ticks（min/max/scale 可覆盖端点）。

        非法 min/max（空字符串 / 非数值 / NaN 等输入）降级为未设置；
        ``minInterval`` / ``maxInterval`` 约束刻度步长。
        """
        if self.type == "log":
            self._set_log_extent(data_min, data_max, segments)
            return
        if self.type != "value":
            return
        lo = 0.0 if data_min is None else float(data_min)
        hi = 1.0 if data_max is None else float(data_max)
        lo = _to_float(lo, 0.0)
        hi = _to_float(hi, 1.0)
        user_lo = _opt_bound(self.min)
        user_hi = _opt_bound(self.max)
        # 数据全为正时基线取 0、全为负时顶取 0（``scale`` 可关闭该行为）
        if user_lo is None and lo > 0 and not self.scale:
            lo = 0.0
        if user_hi is None and hi < 0 and not self.scale:
            hi = 0.0
        if user_lo is not None:
            lo = user_lo
        if user_hi is not None:
            hi = user_hi
        try:
            segments = max(1, int(self.opt.get("splitNumber", segments)))
        except (TypeError, ValueError, OverflowError):
            pass
        self.vmin, self.vmax, self._ticks = niceTicks(lo, hi, segments)
        self._apply_interval_constraints()
        # **用户边界必须自洽**，否则轴会塌掉。
        #
        # ``min`` 大于数据最大值时（``{"min": 100}`` 配 ``data: [1, 2]``），
        # niceTicks 拿到的区间是退化的，覆盖后 ``vmin == vmax`` → span 为 0 →
        # **所有刻度映射到同一像素**、标签叠成一团、数据也画在同一行。
        # ``min > max`` 更糟：span 为负，点被画到坐标区之外。
        # 下面两个守卫把退化区间撑开；不合法的那一侧直接忽略。
        if user_lo is not None and user_hi is not None and user_hi <= user_lo:
            user_hi = None  # min >= max：忽略 hi，交给下面按 lo 撑开
        if user_lo is not None:
            self.vmin = user_lo
        if user_hi is not None:
            self.vmax = user_hi
        if self.vmax <= self.vmin:
            pad = max(1.0, abs(self.vmin) * 0.5)
            self.vmax = self.vmin + pad
            self.vmin, self.vmax, self._ticks = niceTicks(
                self.vmin, self.vmax, segments
            )

    def _apply_interval_constraints(self) -> None:
        """``minInterval`` / ``maxInterval`` 约束 value 轴刻度步长。"""
        min_iv = _opt_bound(self.opt.get("minInterval"))
        max_iv = _opt_bound(self.opt.get("maxInterval"))
        if min_iv is None and max_iv is None:
            return
        ticks = self._ticks
        step = ticks[1] - ticks[0] if len(ticks) > 1 else None
        if not step or step <= 0:
            return
        new_step = step
        if min_iv is not None and min_iv > 0 and step < min_iv:
            new_step = min_iv
        elif max_iv is not None and max_iv > 0 and step > max_iv:
            new_step = max_iv
        if abs(new_step - step) < 1e-12:
            return
        start = math.floor(self.vmin / new_step) * new_step
        end = math.ceil(self.vmax / new_step) * new_step
        count = int(round((end - start) / new_step))
        if count > _MAX_TICKS:
            # **maxInterval 只把 step 变小、不限制刻度总数**，所以 count 直接
            # 等于「跨度 / maxInterval」。实测数据跨 1 配 ``maxInterval=1e-6``
            # → 约 200 万刻度、单帧 3.5 秒；1e-9 直接挂死。宁可少一根网格线
            # 也不能毁掉整帧，所以这里放大 step 重新等分（端点保持不变）。
            self.vmin, self.vmax, self._ticks = _clamp_tick_count(
                start, end, new_step, _MAX_TICKS
            )
            return
        self.vmin, self.vmax = start, end
        self._ticks = [
            0.0 if abs(start + i * new_step) < new_step * 1e-9 else start + i * new_step
            for i in range(count + 1)
        ]

    def _set_log_extent(self, data_min, data_max, segments: int = 5) -> None:
        """log 轴范围：正值过滤 + 按数量级生成刻度。

        非正值在 :meth:`GridCoord.setSeries` 收数据时已经跳过；这里再兜一层，
        避免宿主直接调用 ``setExtent(-1, 0)`` 把轴打塌。
        """
        lo = _to_float(data_min, None)
        hi = _to_float(data_max, None)
        if lo is None or lo <= 0.0 or hi is None or hi <= 0.0 or hi <= lo:
            lo, hi = 1.0, 10.0
        user_lo = _opt_bound(self.min)
        user_hi = _opt_bound(self.max)
        if user_lo is not None and user_lo > 0.0:
            lo = user_lo
        if user_hi is not None and user_hi > 0.0:
            hi = user_hi
        if hi <= lo:
            hi = lo * self.log_base
        try:
            segments = max(1, int(self.opt.get("splitNumber", segments)))
        except (TypeError, ValueError, OverflowError):
            pass
        e0 = int(math.floor(math.log(lo) / math.log(self.log_base)))
        e1 = int(math.ceil(math.log(hi) / math.log(self.log_base)))
        if e1 <= e0:
            e1 = e0 + 1
        # 主轴范围扩到整数量级；用户显式 min/max 时保留用户边界。
        nice_lo = self.log_base**e0
        nice_hi = self.log_base**e1
        if user_lo is not None and user_lo > 0.0:
            nice_lo = lo
        if user_hi is not None and user_hi > 0.0:
            nice_hi = hi
        if nice_hi <= nice_lo:
            nice_hi = nice_lo * self.log_base
        self.vmin, self.vmax = nice_lo, nice_hi
        self._ticks = _log_ticks(nice_lo, nice_hi, self.log_base, segments)

    def ticks(self) -> list:
        """刻度列表：category 返回类别字符串，value 返回数值列表。"""
        if self.type == "category":
            return list(self.categories)
        return list(self._ticks)

    # -- 映射（一维：start→end 像素区间） ----------------------------------
    def localIndex(self, value) -> int:
        """category 轴数据值 → 窗口内下标（dataZoom 窗口外返回越界下标）。"""
        if self.type != "category":
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value) - self.windowOffset()
        return self.categoryIndex(value)

    def map(self, value, start: float, end: float, *, local: bool = False) -> float:
        """数据值 → [start, end] 区间内的像素坐标。

        category 轴不 clamp：窗口外类别返回越界坐标，由各系列的
        clipRect 裁剪。``local=True`` 表示 value 已是窗口内下标。
        ``boundaryGap=false`` 时类别落在边界而非 band 中心；
        ``inverse`` 反转方向。
        """
        if self.type == "category":
            if (
                local
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                idx = int(value)
            else:
                idx = self.localIndex(value)
            n = max(1, len(self.categories))
            if self.boundary_gap or n <= 1:
                frac = (idx + 0.5) / n
            else:
                frac = idx / (n - 1)
            if self.inverse:
                frac = 1.0 - frac
            return start + (end - start) * frac
        if self.type == "log":
            v = _to_float(value, None)
            if v is None or v <= 0.0 or self.vmin <= 0.0 or self.vmax <= 0.0:
                return float("nan")
            lo, hi = math.log(self.vmin), math.log(self.vmax)
            if hi == lo:
                frac = 0.0
            else:
                frac = (math.log(v) - lo) / (hi - lo)
            if self.inverse:
                frac = 1.0 - frac
            return start + (end - start) * frac
        v = _to_float(value, self.vmin)
        span = self.vmax - self.vmin
        frac = 0.0 if span == 0 else (v - self.vmin) / span
        if self.inverse:
            frac = 1.0 - frac
        return start + (end - start) * frac

    def fraction(self, value) -> float:
        """数据值 → 0..1 归一化位置（log 轴走对数空间；无效值返回 NaN）。"""
        v = _to_float(value, None)
        if v is None:
            return float("nan")
        if self.type == "log":
            if v <= 0.0 or self.vmin <= 0.0 or self.vmax <= 0.0:
                return float("nan")
            lo, hi = math.log(self.vmin), math.log(self.vmax)
            if hi == lo:
                return 0.0
            return (math.log(v) - lo) / (hi - lo)
        span = self.vmax - self.vmin
        if span == 0:
            return 0.0
        return (v - self.vmin) / span

    def setWindow(
        self, full_min: float, full_max: float, start: float, end: float
    ) -> None:
        """按 dataZoom 的 0-100 窗口重设轴范围与刻度（log 轴在对数空间插值）。"""
        if self.type == "category":
            return
        lo = _to_float(full_min, self.vmin)
        hi = _to_float(full_max, self.vmax)
        if lo is None or hi is None or hi <= lo:
            return
        start = max(0.0, min(100.0, float(start)))
        end = max(start, min(100.0, float(end)))
        if self.type == "log":
            if lo <= 0.0 or hi <= 0.0:
                return
            l0, l1 = math.log(lo), math.log(hi)
            a = l0 if start <= 0.0 else l0 + (l1 - l0) * start / 100.0
            b = l1 if end >= 100.0 else l0 + (l1 - l0) * end / 100.0
            self.vmin, self.vmax = math.exp(a), math.exp(b)
            if start <= 0.0:
                self.vmin = lo
            if end >= 100.0:
                self.vmax = hi
            if self.vmax <= self.vmin:
                self.vmax = self.vmin * self.log_base
            self._ticks = _log_ticks(self.vmin, self.vmax, self.log_base)
            return
        span = hi - lo
        self.vmin = lo + span * start / 100.0
        self.vmax = lo + span * end / 100.0
        if self.vmax <= self.vmin:
            self.vmax = self.vmin + max(1e-6, span * 0.01)
        _, _, self._ticks = niceTicks(self.vmin, self.vmax)

    def bandWidth(self, start: float, end: float) -> float:
        """category 轴单个 band 的像素宽度（value 轴返回 0）。"""
        if self.type != "category" or not self.categories:
            return 0.0
        n = len(self.categories)
        if not self.boundary_gap and n > 1:
            return abs(end - start) / (n - 1)
        return abs(end - start) / n

    def categoryIndex(self, value) -> int:
        """类别值（名字或序号）→ 下标（不 clamp）。"""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
        s = str(value)
        if s in self.categories:
            return self.categories.index(s)
        all_cats = getattr(self, "_all_categories", None) or []
        if s in all_cats:
            return all_cats.index(s)  # 窗外类别：全量下标（越界）
        return 0

    @property
    def categories(self) -> list:
        """可见类别列表（dataZoom 生效时是窗口内的子集）。"""
        return self._categories

    @categories.setter
    def categories(self, value) -> None:
        self._categories = value
        # 可见类别换了，窗口偏移的线性扫描结果作废
        self._window_offset_cache = None

    def windowOffset(self) -> int:
        """dataZoom 类别窗口在全量类别中的起始下标（无窗口时 0）。

        **必须记忆化**：实现是 ``_all_categories.index(categories[0])`` —— 线性
        扫描，1M 个类别单次 ~2.4ms；而它会被 ``localIndex`` → ``mapPoint``
        **逐点**调用（符号清单 133 个点就 320ms，实测「category 1M 缩放一步」
        339ms 里 320ms 是这 135 次 ``list.index``）。缓存随 ``categories``
        赋值作废（property setter）。
        """
        cached = self._window_offset_cache
        if cached is not None:
            return cached
        all_cats = getattr(self, "_all_categories", None) or []
        offset = 0
        if self.categories and all_cats:
            try:
                offset = all_cats.index(self.categories[0])
            except ValueError:
                offset = 0
        self._window_offset_cache = offset
        return offset

    def invert(self, px: float, start: float, end: float):
        """像素 → 数据值（category 返回窗口内下标，越界收敛到窗口边缘）。"""
        if end == start:
            return 0
        frac = (px - start) / (end - start)
        if self.inverse:
            frac = 1.0 - frac
        if self.type == "category":
            n = max(1, len(self.categories))
            if not self.boundary_gap and n > 1:
                idx = int(round(frac * (n - 1)))
            else:
                idx = int(frac * n)
            return min(max(idx, 0), n - 1)
        if self.type == "log":
            if self.vmin <= 0.0 or self.vmax <= 0.0:
                return None
            return self.vmin * (self.vmax / self.vmin) ** frac
        return self.vmin + frac * (self.vmax - self.vmin)

    # -- 外观 ------------------------------------------------------------
    def axisLabelOption(self) -> dict:
        opt = self.opt.get("axisLabel")
        return opt if isinstance(opt, dict) else {}

    def axisTickOption(self) -> dict:
        opt = self.opt.get("axisTick")
        return opt if isinstance(opt, dict) else {}

    def axisLineOption(self) -> dict:
        opt = self.opt.get("axisLine")
        return opt if isinstance(opt, dict) else {}

    def splitLineOption(self) -> dict:
        opt = self.opt.get("splitLine")
        return opt if isinstance(opt, dict) else {}

    def splitAreaOption(self) -> dict:
        opt = self.opt.get("splitArea")
        return opt if isinstance(opt, dict) else {}

    def labelFont(self) -> QFont:
        """axisLabel 字体（``axisLabel.fontSize`` → font.xs）。"""
        label = self.axisLabelOption()
        try:
            size = float(label.get("fontSize", T("font.xs")))
        except (TypeError, ValueError, OverflowError):
            size = float(T("font.xs"))
        if not math.isfinite(size) or size <= 0:
            size = float(T("font.xs"))
        try:
            weight = int(label.get("fontWeight", 400))
        except (TypeError, ValueError, OverflowError):
            weight = 400
        return chartFont(size, weight)

    def labelShownAt(self, index: int, value=None) -> bool:
        """``axisLabel.interval``：0 全部显示；N 每 N+1 显示一个；callable 判定。"""
        label = self.axisLabelOption()
        if label.get("show", True) is False:
            return False
        interval = label.get("interval", "auto")
        if callable(interval):
            try:
                return bool(interval(index, value))
            except Exception:
                return True
        if isinstance(interval, bool):
            return True
        if isinstance(interval, (int, float)):
            step = int(interval) + 1
            return step <= 1 or index % step == 0
        return True

    def formatTickLabel(self, value) -> str:
        """``axisLabel.formatter``（字符串模板 ``{value}`` 或 callable）→ 文本。

        value 轴 formatter 收到数值（整数值按 JS 习惯转 int）；
        category 轴收到类别字符串。
        """
        label = self.axisLabelOption()
        formatter = label.get("formatter")
        if self.type != "category":
            raw = (
                int(value) if isinstance(value, float) and value.is_integer() else value
            )
        else:
            raw = str(value)
        text = _format_log_tick(raw) if self.type == "log" else formatValue(raw)
        if callable(formatter):
            try:
                out = formatter(raw, 0)
            except TypeError:
                try:
                    out = formatter(raw)
                except Exception:
                    return text
            except Exception:
                return text
            return str(out) if out is not None else text
        if isinstance(formatter, str):
            try:
                return formatter.format_map({"value": text})
            except Exception:
                return text
        return text

    def labelColor(self) -> QColor:
        """axisLabel 文本色（``axisLabel.color`` → 次级文本色）。"""
        raw = self.axisLabelOption().get("color")
        if isinstance(raw, str) and raw:
            color = QColor(raw)
            if color.isValid():
                return color
        return QColor(T("color.text.secondary"))


def _to_float(v, default=0.0) -> float:
    """数值轴映射用宽松转换（NaN/Inf 过滤，防止污染 QPainter 坐标）。"""
    return _utils_to_float(v, default)


def _opt_bound(v):
    """解析轴 min/max 选项：合法数值返回 float，非法返回 None（视为未设置）。"""
    try:
        return _utils_to_float(v, None)
    except (TypeError, ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# 直角坐标系
# ---------------------------------------------------------------------------


def _parse_margin(v, default):
    """解析 grid / singleAxis 边距：数值 px 或百分比字符串（"10%"）。

    返回 ``(is_pct, value)``：百分比在 layout 时按 rect 宽 / 高换算；
    非法输入降级为 default（default 可为 None 表示「未设置」）。

    **非有限值（inf / nan）与其它非法输入同等处理。** 原先 ``float(v)`` 直接
    放行，导致 ``{"grid": {"left": "inf"}}`` 得到 ``plot = QRectF(inf, 40, 10,
    202)``、``mapPoint`` 返回 NaN 坐标 —— 不抛异常、不告警，整图坐标系变成
    NaN（Qt 画不出东西，宿主任何算术都拿到 NaN）。
    """
    fallback = float(default) if default is not None else None
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("%"):
            try:
                pct = float(s[:-1])
            except ValueError:
                return False, fallback
            return (True, pct) if math.isfinite(pct) else (False, fallback)
        if not s:
            return False, fallback
    if v is None:
        return False, fallback
    try:
        val = float(v)
    except (TypeError, ValueError, OverflowError):
        return False, fallback
    return (False, val) if math.isfinite(val) else (False, fallback)


def _margin_px(spec, total):
    """把 ``_parse_margin`` 的 ``(is_pct, v)`` 换算为像素（v 为 None 时原样返回）。"""
    is_pct, v = spec
    if v is None:
        return None
    return total * v / 100.0 if is_pct else v


#: lineStyle.type → Qt 画笔样式
_PEN_STYLES = {
    "solid": Qt.PenStyle.SolidLine,
    "dashed": Qt.PenStyle.DashLine,
    "dash": Qt.PenStyle.DashLine,
    "dotted": Qt.PenStyle.DotLine,
    "dot": Qt.PenStyle.DotLine,
}


def _axis_options(value) -> list:
    """``xAxis`` / ``yAxis`` → option dict 列表（单 dict 与数组两种写法）。"""
    if isinstance(value, dict):
        return [dict(value)]
    if isinstance(value, (list, tuple)):
        return [dict(v) for v in value if isinstance(v, dict)]
    return []


def _axis_index(value, count: int) -> int:
    """轴索引归一化：非整数 / 越界一律收敛到合法范围（默认 0）。"""
    if count <= 0:
        return 0
    try:
        idx = int(value)
    except (TypeError, ValueError, OverflowError):
        idx = 0
    return min(max(idx, 0), count - 1)


def _line_pen(opt: dict, default_color, default_width=1.0) -> QPen:
    """解析 ``{lineStyle: {color, width, type}}`` → QPen。"""
    style = opt.get("lineStyle")
    style = style if isinstance(style, dict) else {}
    color = QColor(style.get("color") or default_color)
    try:
        width = max(0.5, float(style.get("width", default_width)))
    except (TypeError, ValueError, OverflowError):
        width = float(default_width)
    pen = QPen(color, width)
    pen.setStyle(
        _PEN_STYLES.get(
            str(style.get("type") or "solid").lower(), Qt.PenStyle.SolidLine
        )
    )
    return pen


class GridCoord(Coord):
    """直角坐标系：grid 边距 + 多 x/y 轴 + 网格 / 区域 / 刻度 / 标签。

    option 键：``grid``（left/right/top/bottom 默认 48/24/40/36、``show``、
    ``containLabel``、``borderColor`` / ``borderWidth`` / ``backgroundColor``）、
    ``xAxis`` / ``yAxis``（单个 dict 或数组，见 AxisModel）。边距支持数值 px
    或 ``"N%"``。``mapPoint(x, y)``：x 为类别名/下标或数值，y 为数值；
    可选 ``x_axis_index`` / ``y_axis_index`` 指定轴。

    多轴通过 :meth:`axis_view` 返回绑定到某对轴的轻量视图；系列渲染器继续
    读 ``coord.x_axis`` / ``coord.y_axis``，无需逐个改。
    """

    kind = "grid"

    def __init__(self, chart=None, option: dict = None):
        super().__init__(chart, option)
        xopts = _axis_options(self.option.get("xAxis"))
        yopts = _axis_options(self.option.get("yAxis"))
        if not xopts:
            xopts = [{}]
        if not yopts:
            yopts = [{}]
        self.x_axes = [
            AxisModel(o, "category" if o.get("data") else "value") for o in xopts
        ]
        self.y_axes = [AxisModel(o, "value") for o in yopts]
        for i, axis in enumerate(self.x_axes):
            if axis.position not in ("top", "bottom"):
                axis.position = "bottom" if i == 0 else "top"
        for i, axis in enumerate(self.y_axes):
            if axis.position not in ("left", "right"):
                axis.position = "left" if i == 0 else "right"
        #: ``(x_axis_index, y_axis_index)`` → 轴对视图缓存
        self._axis_views: dict = {}
        grid = dict(self.option.get("grid") or {})
        self._m_left = _parse_margin(grid.get("left"), 48)
        self._m_right = _parse_margin(grid.get("right"), 24)
        self._m_top = _parse_margin(grid.get("top"), 40)
        self._m_bottom = _parse_margin(grid.get("bottom"), 36)
        self.m_left = self.m_right = self.m_top = self.m_bottom = 0.0
        self.plot = QRectF()  # 绘图区（扣除边距）
        self.grid_show = bool(grid.get("show", False))
        self.grid_border_color = grid.get("borderColor")
        self.grid_bg = grid.get("backgroundColor")
        try:
            self.grid_border_width = max(0.0, float(grid.get("borderWidth", 0)))
        except (TypeError, ValueError, OverflowError):
            self.grid_border_width = 0.0
        self.contain_label = bool(grid.get("containLabel", False))

    @property
    def x_axis(self) -> AxisModel:
        """主轴（索引 0）；多轴请用 :meth:`axis_view` 或直接读 ``x_axes``。"""
        return self.x_axes[0]

    @property
    def y_axis(self) -> AxisModel:
        """主轴（索引 0）。"""
        return self.y_axes[0]

    def _series_axes(self, series_opt: dict):
        """系列 → ``(x_axis_index, y_axis_index)``（越界静默收敛）。"""
        s = series_opt if isinstance(series_opt, dict) else {}
        return (
            _axis_index(s.get("xAxisIndex"), len(self.x_axes)),
            _axis_index(s.get("yAxisIndex"), len(self.y_axes)),
        )

    def axis_view_for_indices(self, x_axis_index=0, y_axis_index=0):
        """取绑定到某对轴的视图（同一个 GridCoord 共享绘图区）。"""
        xi = _axis_index(x_axis_index, len(self.x_axes))
        yi = _axis_index(y_axis_index, len(self.y_axes))
        key = (xi, yi)
        view = self._axis_views.get(key)
        if view is None:
            view = _GridAxisView(self, xi, yi)
            self._axis_views[key] = view
        return view

    def axis_view(self, series_opt: dict = None):
        """按系列 ``xAxisIndex`` / ``yAxisIndex`` 取轴对视图。"""
        xi, yi = self._series_axes(series_opt)
        return self.axis_view_for_indices(xi, yi)

    # -- 数据范围 ---------------------------------------------------------
    def _extent(self, data, positive_x: bool = False, positive_y: bool = False):
        """带缓存的数值范围 ``(x0, x1, y0, y1)``（缺失维度为 ``None``）。

        缓存是**缩放 / 平移流畅度的关键**：``setSeries`` 在每次重建
        （缩放、平移、数据更新、图例切换都会触发）时都重算全量范围，
        百万点逐点扫描要 400 ms 以上。范围只取决于数据本身，与窗口无关，
        因此按「数据对象身份 + 长度 + 正值过滤」缓存后，缩放时这一步接近零成本。

        缓存值同时**持有数据对象的强引用**（见 ``_EXTENT_CACHE`` 的说明），
        否则对象被回收后 ``id`` 会被复用，把别的数据的范围当成自己的。
        """
        if data is None:
            return None
        if _cdata.isBufferLike(data) or _ds.np is not None:
            try:
                n = len(data)
                key = (
                    (id(data), n)
                    if not positive_x and not positive_y
                    else (id(data), n, int(bool(positive_x)), int(bool(positive_y)))
                )
            except TypeError:
                return self._numpy_extent(data, positive_x, positive_y)
            hit = _EXTENT_CACHE.get(key)
            if hit is not None and hit[0] is data:
                return hit[1]
            ext = self._numpy_extent(data, positive_x, positive_y)
            if len(_EXTENT_CACHE) >= _EXTENT_CACHE_LIMIT:
                _EXTENT_CACHE.clear()
            _EXTENT_CACHE[key] = (data, ext)
            return ext
        return self._numpy_extent(data, positive_x, positive_y)

    def _numpy_extent(self, data, positive_x: bool = False, positive_y: bool = False):
        """numpy 快速路径：返回 ``(x0, x1, y0, y1)``（缺失维度为 ``None``）或 None。

        纯数值列表：x 按下标语义（0 .. n-1）；[x, y] 列表：取两列；
        含字典 / None / 混合形式返回 None（调用方回退 Python 循环）。

        走 ``nanmin`` / ``nanmax``：``None`` 间隙在缓冲里是 NaN，用 ``min``/``max``
        会让整个轴范围变成 NaN。但**它们只跳 NaN 不跳 inf**，所以先把非有限值
        掩成 NaN —— 完整清单与后果见 AGENTS.md「charts」。
        """
        if data is None or _ds.np is None:
            return None
        try:
            n = len(data)
        except TypeError:
            return None
        if n == 0:
            return None
        try:
            arr = _ds.np.asarray(data, dtype=_ds.np.float64)
        except (TypeError, ValueError, OverflowError):
            return None
        np_ = _ds.np
        if arr.ndim == 1:
            if not arr.size:
                return None
            arr = np_.where(np_.isfinite(arr), arr, np_.nan)
            if positive_y:
                arr = np_.where(arr > 0.0, arr, np_.nan)
            if not np_.isfinite(arr).any():
                return None
            ymin, ymax = float(np_.nanmin(arr)), float(np_.nanmax(arr))
            x0 = 1.0 if positive_x and arr.size > 1 else 0.0
            if positive_x and arr.size <= 1:
                return None
            return x0, float(arr.size - 1), ymin, ymax
        if arr.ndim == 2 and arr.shape[1] >= 2 and arr.shape[0]:
            xcol = np_.where(np_.isfinite(arr[:, 0]), arr[:, 0], np_.nan)
            ycol = np_.where(np_.isfinite(arr[:, 1]), arr[:, 1], np_.nan)
            if positive_x:
                xcol = np_.where(xcol > 0.0, xcol, np_.nan)
            if positive_y:
                ycol = np_.where(ycol > 0.0, ycol, np_.nan)
            xpair = (
                (float(np_.nanmin(xcol)), float(np_.nanmax(xcol)))
                if np_.isfinite(xcol).any()
                else None
            )
            ypair = (
                (float(np_.nanmin(ycol)), float(np_.nanmax(ycol)))
                if np_.isfinite(ycol).any()
                else None
            )
            if ypair is None and not (positive_x or positive_y):
                return None
            if xpair is None and ypair is None:
                return None
            return (
                xpair[0] if xpair else None,
                xpair[1] if xpair else None,
                ypair[0] if ypair else None,
                ypair[1] if ypair else None,
            )
        return None

    def setSeries(self, series_opts: list) -> None:
        xs = [[] for _ in self.x_axes]
        ys = [[] for _ in self.y_axes]
        for s in series_opts or []:
            if not isinstance(s, dict):
                continue
            if s.get("coordinateSystem") not in (None, "cartesian2d", "grid"):
                continue
            xi, yi = self._series_axes(s)
            xaxis = self.x_axes[xi]
            yaxis = self.y_axes[yi]
            need_x = xaxis.type in ("value", "log")
            need_y = yaxis.type in ("value", "log")
            if not need_x and not need_y:
                continue
            positive_x = xaxis.type == "log"
            positive_y = yaxis.type == "log"
            data = s.get("data")
            # ``data: 5`` / ``3.5`` / ``True`` 这类**标量**不是合法序列（ECharts
            # 也不接受），但它此前一路走到下面的 ``enumerate(data)`` 抛 TypeError，
            # 而 ``_rebuild`` 调 ``setSeries`` 没有 try —— 异常直接冒给
            # ``setOption`` 的调用方。降级成空数据，与「数据为空」同路径。
            #
            # 注意判据不能用 ``isBufferLike``：它**故意不认** list / tuple
            # （逐元素拷贝对百万级列表是性能灾难，见 data.isBufferLike 的
            # docstring），那样会把正常数据全清空。
            if data is None:
                data = []
            elif not _cdata.isBufferLike(data) and not isinstance(data, (list, tuple)):
                data = []
            ext = self._extent(data, positive_x, positive_y)
            if ext is not None:
                x0, x1, y0, y1 = ext
                have_x = x0 is not None and x1 is not None
                have_y = y0 is not None and y1 is not None
                if need_x and have_x:
                    xs[xi].extend((x0, x1))
                if need_y and have_y:
                    ys[yi].extend((y0, y1))
                if (not need_x or have_x) and (not need_y or have_y):
                    continue
            for i, item in enumerate(data):
                # ``_datum_y`` / ``_datum_x`` 在入口已滤掉 NaN / inf
                y = _datum_y(item)
                if need_y and y is not None and (not positive_y or y > 0.0):
                    ys[yi].append(y)
                if need_x:
                    x = _datum_x(item)
                    if x is None:
                        if y is not None:
                            x = float(i)  # 纯数值数据：x 取下标（index 语义）
                        else:
                            continue
                    if positive_x and x <= 0.0:
                        continue
                    xs[xi].append(float(x))
        for i, axis in enumerate(self.y_axes):
            if axis.type in ("value", "log"):
                vals = ys[i]
                axis.setExtent(min(vals), max(vals)) if vals else axis.setExtent(
                    0.0, 1.0
                )
        for i, axis in enumerate(self.x_axes):
            if axis.type in ("value", "log"):
                vals = xs[i]
                axis.setExtent(min(vals), max(vals)) if vals else axis.setExtent(
                    0.0, 1.0
                )

    # -- 协议 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        super().layout(rect)
        # 百分比边距在此换算（左右相对宽、上下相对高）
        self.m_left = _margin_px(self._m_left, rect.width())
        self.m_right = _margin_px(self._m_right, rect.width())
        self.m_top = _margin_px(self._m_top, rect.height())
        self.m_bottom = _margin_px(self._m_bottom, rect.height())
        self._apply_axis_margins(rect)
        self.plot = QRectF(
            rect.left() + self.m_left,
            rect.top() + self.m_top,
            max(10.0, rect.width() - self.m_left - self.m_right),
            max(10.0, rect.height() - self.m_top - self.m_bottom),
        )

    def _axis_label_extent(self, axis: AxisModel, horizontal: bool) -> float:
        """轴标签在垂直轴方向（y 轴宽度 / x 轴高度）需要的像素。"""
        if axis.axisLabelOption().get("show", True) is False:
            return 0.0
        font = axis.labelFont()
        fm = QFontMetricsF(font)
        if horizontal:
            if axis.type == "category":
                values = axis.categories
            else:
                values = axis._ticks
            if not values:
                return 0.0
            step = max(1, len(values) // 64)
            width = 0.0
            for i in range(0, len(values), step):
                label = (
                    str(values[i])
                    if axis.type == "category"
                    else axis.formatTickLabel(values[i])
                )
                width = max(width, float(fm.horizontalAdvance(label)))
            extra = float(fm.height()) + 6.0 if axis.name else 0.0
            return width + 12.0 + axis.offset + extra
        height = float(fm.height()) + 12.0 + axis.offset
        if axis.name:
            height += float(fm.height()) + 4.0
        return height

    def _apply_axis_margins(self, rect: QRectF) -> None:
        """按轴位置预留标签空间（右侧 Y / 顶部 X 是新功能，必须自动留白）。"""
        left = [a for a in self.y_axes if a.position == "left"]
        right = [a for a in self.y_axes if a.position == "right"]
        bottom = [a for a in self.x_axes if a.position == "bottom"]
        top = [a for a in self.x_axes if a.position == "top"]
        left_need = sum(self._axis_label_extent(a, True) for a in left)
        right_need = sum(self._axis_label_extent(a, True) for a in right)
        bottom_need = sum(self._axis_label_extent(a, False) for a in bottom)
        top_need = sum(self._axis_label_extent(a, False) for a in top)
        if self.contain_label:
            self.m_left = max(self.m_left, left_need)
            self.m_right = max(self.m_right, right_need)
            self.m_bottom = max(self.m_bottom, bottom_need)
            self.m_top = max(self.m_top, top_need)
            return
        # 非 containLabel：主轴保持既有边距（向后兼容），副轴 / 右 / 上必须留白。
        if any(a is not self.y_axes[0] for a in left):
            self.m_left = max(self.m_left, left_need)
        if right:
            self.m_right = max(self.m_right, right_need)
        if any(a is not self.x_axes[0] for a in bottom):
            self.m_bottom = max(self.m_bottom, bottom_need)
        if top:
            self.m_top = max(self.m_top, top_need)

    def mapPoint(
        self,
        x,
        y=None,
        x_axis_index: int = 0,
        y_axis_index: int = 0,
    ) -> QPointF:
        xa = self.x_axes[_axis_index(x_axis_index, len(self.x_axes))]
        ya = self.y_axes[_axis_index(y_axis_index, len(self.y_axes))]
        px = xa.map(x, self.plot.left(), self.plot.right())
        py = ya.map(_to_float(y), self.plot.bottom(), self.plot.top())
        return QPointF(px, py)

    def mapArrays(
        self,
        xs,
        ys,
        x_axis_index: int = 0,
        y_axis_index: int = 0,
    ):
        """批量映射（numpy 数组进 → ``(px, py)`` 两个数组）；不支持时返回 ``None``。

        与 :meth:`mapPoint` 逐点**同语义**，只是把「每点 ~6µs 的 Python 调用链」
        换成一次向量化运算（实测 1M 点 2.4s → 数十 ms；采样后 2.6k 点也从
        16ms 降到 <1ms）。以下情形返回 ``None`` 让调用方退回逐点：

        * 缺 numpy；
        * 轴类型不在 ``value`` / ``category`` / ``log`` 内；
        * category 轴的 x 不是数值（类别名无法向量化）。

        非有限坐标不做过滤：由调用方按 ``isfinite`` 决定是否断开（保持
        ``mapPoint`` 把 NaN 交给调用方处理的既有约定）。log 轴的非正值
        产出 NaN。
        """
        np_ = _ds.np
        if np_ is None or xs is None or ys is None:
            return None
        xa = self.x_axes[_axis_index(x_axis_index, len(self.x_axes))]
        ya = self.y_axes[_axis_index(y_axis_index, len(self.y_axes))]
        left, right = self.plot.left(), self.plot.right()
        bottom, top = self.plot.bottom(), self.plot.top()

        if xa.type == "category":
            count = len(xa.categories)
            if count <= 0:
                return None
            try:
                idx = np_.asarray(xs, dtype=np_.float64) - float(xa.windowOffset())
            except (TypeError, ValueError, OverflowError):
                return None
            if xa.boundary_gap or count <= 1:
                frac = (idx + 0.5) / count
            else:
                frac = idx / (count - 1)
        elif xa.type == "value":
            values = np_.asarray(xs, dtype=np_.float64)
            span = xa.vmax - xa.vmin
            frac = np_.zeros_like(values) if span == 0 else (values - xa.vmin) / span
        elif xa.type == "log":
            values = np_.asarray(xs, dtype=np_.float64)
            frac = np_.full(values.shape, np_.nan, dtype=np_.float64)
            valid = values > 0.0
            if xa.vmin > 0.0 and xa.vmax > 0.0:
                lo, hi = math.log(xa.vmin), math.log(xa.vmax)
                if hi != lo:
                    frac[valid] = (np_.log(values[valid]) - lo) / (hi - lo)
                else:
                    frac[valid] = 0.0
        else:
            return None
        if xa.inverse:
            frac = 1.0 - frac
        px = left + (right - left) * frac

        if ya.type == "value":
            y_values = np_.asarray(ys, dtype=np_.float64)
            y_span = ya.vmax - ya.vmin
            y_frac = (
                np_.zeros_like(y_values)
                if y_span == 0
                else (y_values - ya.vmin) / y_span
            )
        elif ya.type == "log":
            y_values = np_.asarray(ys, dtype=np_.float64)
            y_frac = np_.full(y_values.shape, np_.nan, dtype=np_.float64)
            valid = y_values > 0.0
            if ya.vmin > 0.0 and ya.vmax > 0.0:
                lo, hi = math.log(ya.vmin), math.log(ya.vmax)
                if hi != lo:
                    y_frac[valid] = (np_.log(y_values[valid]) - lo) / (hi - lo)
                else:
                    y_frac[valid] = 0.0
        else:
            return None
        if ya.inverse:
            y_frac = 1.0 - y_frac
        py = bottom + (top - bottom) * y_frac
        return px, py

    def invertX(self, pos: QPointF, x_axis_index: int = 0):
        xa = self.x_axes[_axis_index(x_axis_index, len(self.x_axes))]
        return xa.invert(pos.x(), self.plot.left(), self.plot.right())

    def invertPoint(self, pos: QPointF, x_axis_index: int = 0, y_axis_index: int = 0):
        """像素 → ``[x, y]``（category 轴返回窗口内下标）。"""
        xa = self.x_axes[_axis_index(x_axis_index, len(self.x_axes))]
        ya = self.y_axes[_axis_index(y_axis_index, len(self.y_axes))]
        return [
            xa.invert(pos.x(), self.plot.left(), self.plot.right()),
            ya.invert(pos.y(), self.plot.bottom(), self.plot.top()),
        ]

    def containPoint(self, pos: QPointF) -> bool:
        return self.plot.contains(QPointF(pos))

    # -- 绘制 -------------------------------------------------------------
    def _interval_step(self, axis: AxisModel, horizontal: bool, option_key: str) -> int:
        """标签 / 刻度 / 网格线的抽稀步长（``interval: 'auto'`` 语义）。

        **为什么必须有**：坐标轴现在是「有多少刻度画多少」——1M 个类别的 x 轴
        会画 1M 个标签 + 1M 条刻度（实测单帧 11.8s + 3.5s，比系列绘制贵两个
        数量级）。抽稀后绘制量与像素宽度挂钩，与数据量解耦。

        判据：沿轴方向「一个标签占的像素」不够放时按倍数跳。显式 ``interval``
        （数字 / callable）优先，用户说了算。
        """
        opt = axis.axisLabelOption() if option_key == "axisLabel" else None
        if opt is None:
            if option_key == "axisTick":
                opt = axis.axisTickOption()
            elif option_key == "splitLine":
                opt = axis.splitLineOption()
            elif option_key == "splitArea":
                opt = axis.splitAreaOption()
            else:
                opt = {}
        interval = opt.get("interval")
        if isinstance(interval, bool):
            return 1
        if isinstance(interval, (int, float)):
            return max(1, int(interval) + 1)
        if callable(interval):
            return 1
        # 每次绘制只算一次：同一次 paintAxes 里标签 / 刻度 / 网格 / 分隔区
        # 会各问一次，样本量文本不能重复付（记忆化按轴 + 方向 + 画布尺寸）。
        memo = getattr(self, "_step_memo", None)
        if memo is None:
            memo = self._step_memo = {}
        memo_key = (id(axis), horizontal, option_key)
        if memo_key in memo:
            return memo[memo_key]
        step = self._compute_interval_step(axis, horizontal)
        memo[memo_key] = step
        return step

    def _compute_interval_step(self, axis: AxisModel, horizontal: bool) -> int:
        count = len(axis.categories) if axis.type == "category" else len(axis.ticks())
        if count <= 1:
            return 1
        span = self.plot.height() if horizontal else self.plot.width()
        if span <= 0:
            return 1
        spacing = span / float(count)
        font = axis.labelFont()
        fm = QFontMetricsF(font)
        if horizontal:
            # y 轴：沿轴方向是标签**高度**（一行）
            extent = float(fm.height())
        else:
            # x 轴：沿轴方向是标签**宽度**；量最多 32 个样本取最宽
            # （全量量文本会把「画不出来」换成「量不完」）
            extent = 0.0
            step_sample = max(1, count // 32)
            ticks = axis.ticks() if axis.type != "category" else None
            for i in range(0, count, step_sample):
                text = (
                    str(axis.categories[i])
                    if axis.type == "category"
                    else axis.formatTickLabel(ticks[i])
                )
                extent = max(extent, float(fm.horizontalAdvance(text)))
            if extent <= 0.0:
                extent = float(fm.height())
        need = extent + 6.0
        if need <= spacing:
            return 1
        return int(math.ceil(need / spacing))

    def _axis_positions(self, axis: AxisModel, horizontal: bool, step: int = 1):
        """轴刻度位置列表 ``[(px, py, label, index)]``（category 用本地下标映射）。

        ``step`` 是抽稀步长（``_interval_step``）：**category 轴按它跳着枚举**，
        1M 个类别的轴才不会在这里先造出 1M 个元组（光这一步就要 ~0.3s）。
        """
        out = []
        step = max(1, int(step))
        if axis.type == "category":
            categories = axis.categories
            for i in range(0, len(categories), step):
                label = str(categories[i])
                if horizontal:
                    py = axis.map(i, self.plot.bottom(), self.plot.top(), local=True)
                    out.append((self.plot.left(), py, label, i))
                else:
                    px = axis.map(i, self.plot.left(), self.plot.right(), local=True)
                    out.append((px, self.plot.bottom(), label, i))
        else:
            ticks = axis.ticks()
            for i in range(0, len(ticks), step):
                tv = ticks[i]
                if horizontal:
                    py = axis.map(tv, self.plot.bottom(), self.plot.top())
                    out.append((self.plot.left(), py, axis.formatTickLabel(tv), tv))
                else:
                    px = axis.map(tv, self.plot.left(), self.plot.right())
                    out.append((px, self.plot.bottom(), axis.formatTickLabel(tv), tv))
        return out

    def _axis_sides(self):
        """``(axis, horizontal, primary)``：y 轴 horizontal=True，x 轴 False。"""
        out = []
        for i, axis in enumerate(self.y_axes):
            out.append((axis, True, i == 0))
        for i, axis in enumerate(self.x_axes):
            out.append((axis, False, i == 0))
        return out

    def _axis_line_pos(self, axis: AxisModel, horizontal: bool) -> float:
        """轴线所在像素（y 轴返回 x，x 轴返回 y）。"""
        if horizontal:
            if axis.position == "right":
                return self.plot.right() + axis.offset
            return self.plot.left() - axis.offset
        if axis.position == "top":
            return self.plot.top() - axis.offset
        return self.plot.bottom() + axis.offset

    def _paint_split_area(self, p: QPainter) -> None:
        for axis, horizontal, _primary in self._axis_sides():
            opt = axis.splitAreaOption()
            if not bool(opt.get("show", False)):
                continue
            area = opt.get("areaStyle")
            colors = (area or {}).get("color") if isinstance(area, dict) else None
            if not isinstance(colors, list) or not colors:
                colors = [T("color.bg.muted")]
            positions = self._axis_positions(
                axis, horizontal, self._interval_step(axis, horizontal, "splitArea")
            )
            spans = []
            for px, py, _label, _idx in positions:
                spans.append(py if horizontal else px)
            for i in range(len(spans) - 1):
                lo, hi = sorted((spans[i], spans[i + 1]))
                color = QColor(colors[i % len(colors)])
                if not color.isValid():
                    continue
                if horizontal:
                    rect = QRectF(self.plot.left(), lo, self.plot.width(), hi - lo)
                else:
                    rect = QRectF(lo, self.plot.top(), hi - lo, self.plot.height())
                p.fillRect(rect, color)

    def _paint_split_lines(self, p: QPainter) -> None:
        for axis, horizontal, primary in self._axis_sides():
            opt = axis.splitLineOption()
            # ECharts 默认：value / log 轴显示网格线，category 轴不显示。
            # 副轴默认不画（否则两套网格叠在一起），显式 show 可开。
            default_show = axis.type in ("value", "log") and primary
            if not bool(opt.get("show", default_show)):
                continue
            p.setPen(_line_pen(opt, T("color.border")))
            for px, py, _label, _idx in self._axis_positions(
                axis, horizontal, self._interval_step(axis, horizontal, "splitLine")
            ):
                if horizontal:
                    p.drawLine(
                        QPointF(self.plot.left(), py), QPointF(self.plot.right(), py)
                    )
                else:
                    p.drawLine(
                        QPointF(px, self.plot.top()), QPointF(px, self.plot.bottom())
                    )

    def _paint_axis_lines(self, p: QPainter) -> None:
        for axis, horizontal, _primary in self._axis_sides():
            opt = axis.axisLineOption()
            if not bool(opt.get("show", True)):
                continue
            p.setPen(_line_pen(opt, T("color.border.strong")))
            if horizontal:
                x = self._axis_line_pos(axis, True)
                p.drawLine(QPointF(x, self.plot.bottom()), QPointF(x, self.plot.top()))
            else:
                y = self._axis_line_pos(axis, False)
                p.drawLine(QPointF(self.plot.left(), y), QPointF(self.plot.right(), y))

    def _paint_ticks(self, p: QPainter) -> None:
        for axis, horizontal, _primary in self._axis_sides():
            opt = axis.axisTickOption()
            if not bool(opt.get("show", True)):
                continue
            inside = bool(opt.get("inside", False))
            try:
                length = max(1.0, float(opt.get("length", 5)))
            except (TypeError, ValueError, OverflowError):
                length = 5.0
            p.setPen(_line_pen(opt, T("color.border.strong")))
            line = self._axis_line_pos(axis, horizontal)
            # 向外方向的符号：left=-1 / right=+1 / bottom=+1 / top=-1
            if horizontal:
                outward = 1.0 if axis.position == "right" else -1.0
            else:
                outward = 1.0 if axis.position == "bottom" else -1.0
            direction = -outward if inside else outward
            for px, py, _label, _idx in self._axis_positions(
                axis, horizontal, self._interval_step(axis, horizontal, "axisTick")
            ):
                if horizontal:
                    p.drawLine(
                        QPointF(line, py), QPointF(line + direction * length, py)
                    )
                else:
                    p.drawLine(
                        QPointF(px, line), QPointF(px, line + direction * length)
                    )

    def _paint_axis_labels(self, p: QPainter) -> None:
        # y 轴标签：left 右对齐到轴线左侧，right 左对齐到轴线右侧
        for axis in self.y_axes:
            font = axis.labelFont()
            p.setFont(font)
            fm = QFontMetricsF(font)
            color = axis.labelColor()
            line = self._axis_line_pos(axis, True)
            if axis.position == "right":
                left = line + 6
                right = max(left + 8, self.rect.right())
                align = Qt.AlignmentFlag.AlignLeft
            else:
                left = self.rect.left()
                right = max(left + 8, line - 6)
                align = Qt.AlignmentFlag.AlignRight
            for px, py, label, idx in self._axis_positions(
                axis, True, self._interval_step(axis, True, "axisLabel")
            ):
                if not axis.labelShownAt(idx, label):
                    continue
                p.setPen(color)
                p.drawText(
                    QRectF(
                        left, py - fm.height() / 2, max(8.0, right - left), fm.height()
                    ),
                    align | Qt.AlignmentFlag.AlignVCenter,
                    label,
                )
        # x 轴标签：bottom 在轴线下，top 在轴线上；可按 axisLabel.rotate 旋转
        for axis in self.x_axes:
            font = axis.labelFont()
            p.setFont(font)
            fm = QFontMetricsF(font)
            color = axis.labelColor()
            try:
                rotate = float(axis.axisLabelOption().get("rotate", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                rotate = 0.0
            line = self._axis_line_pos(axis, False)
            top_side = axis.position == "top"
            for px, py, label, idx in self._axis_positions(
                axis, False, self._interval_step(axis, False, "axisLabel")
            ):
                if not axis.labelShownAt(idx, label):
                    continue
                p.setPen(color)
                if abs(rotate) < 1e-6:
                    rect = (
                        QRectF(px - 40, line - 5 - fm.height(), 80, fm.height())
                        if top_side
                        else QRectF(px - 40, line + 5, 80, fm.height())
                    )
                    p.drawText(
                        rect,
                        Qt.AlignmentFlag.AlignHCenter
                        | (
                            Qt.AlignmentFlag.AlignBottom
                            if top_side
                            else Qt.AlignmentFlag.AlignTop
                        ),
                        label,
                    )
                else:
                    center_y = (
                        line - 5 - fm.height() / 2
                        if top_side
                        else line + 5 + fm.height() / 2
                    )
                    p.save()
                    p.translate(px, center_y)
                    p.rotate(rotate)
                    p.drawText(
                        QRectF(-60, -fm.height() / 2, 120, fm.height()),
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                        label,
                    )
                    p.restore()

    def _paint_axis_names(self, p: QPainter) -> None:
        c_name = QColor(T("color.text.tertiary"))
        for axis in self.x_axes:
            if not axis.name:
                continue
            p.setPen(c_name)
            fm = QFontMetricsF(axis.labelFont())
            line = self._axis_line_pos(axis, False)
            if axis.position == "top":
                base_y = line - 5 - fm.height() - fm.height() - 2
                align_v = Qt.AlignmentFlag.AlignBottom
            else:
                base_y = line + 5 + fm.height() + 2
                align_v = Qt.AlignmentFlag.AlignTop
            if axis.name_location == "start":
                rect = QRectF(self.plot.left() - 40, base_y, 80, fm.height())
                align_h = Qt.AlignmentFlag.AlignLeft
            elif axis.name_location == "middle":
                rect = QRectF(self.plot.center().x() - 60, base_y, 120, fm.height())
                align_h = Qt.AlignmentFlag.AlignHCenter
            else:
                rect = QRectF(self.plot.right() - 80, base_y, 80, fm.height())
                align_h = Qt.AlignmentFlag.AlignRight
            p.drawText(rect, align_h | align_v, axis.name)
        for axis in self.y_axes:
            if not axis.name:
                continue
            p.setPen(c_name)
            fm = QFontMetricsF(axis.labelFont())
            line = self._axis_line_pos(axis, True)
            if axis.position == "right":
                left = line + 4
                width = max(20.0, self.rect.right() - left)
                align_h = Qt.AlignmentFlag.AlignLeft
            else:
                left = self.rect.left()
                width = max(20.0, line - 4 - left)
                align_h = Qt.AlignmentFlag.AlignRight
            if axis.name_location == "start":
                y = self.plot.bottom() - fm.height()
                align_v = Qt.AlignmentFlag.AlignBottom
            elif axis.name_location == "middle":
                y = self.plot.center().y() - fm.height() / 2
                align_v = Qt.AlignmentFlag.AlignVCenter
            else:
                y = self.plot.top() - fm.height() - 4
                align_v = Qt.AlignmentFlag.AlignBottom
            p.drawText(
                QRectF(left, y, width, fm.height()), align_h | align_v, axis.name
            )

    def paintAxes(self, p: QPainter) -> None:
        p.save()
        # 抽稀步长的记忆化按「一次绘制」为界：轴范围 / 画布尺寸变了要重算
        self._step_memo = {}
        # grid 背景 / 边框
        if self.grid_bg:
            p.fillRect(self.plot, QColor(self.grid_bg))
        if self.grid_show and self.grid_border_width > 0:
            p.setPen(
                QPen(
                    QColor(self.grid_border_color or T("color.border")),
                    self.grid_border_width,
                )
            )
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.plot)
        self._paint_split_area(p)
        self._paint_split_lines(p)
        self._paint_axis_lines(p)
        self._paint_ticks(p)
        self._paint_axis_labels(p)
        self._paint_axis_names(p)
        p.restore()

    def paintTooltipMarker(
        self,
        p: QPainter,
        pos: QPointF,
        kind: str = "cross",
        x_axis_index: int = 0,
    ) -> None:
        if kind == "none":
            return
        p.save()
        pen = QPen(QColor(T("color.border.strong")), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        x = min(max(pos.x(), self.plot.left()), self.plot.right())
        y = min(max(pos.y(), self.plot.top()), self.plot.bottom())
        if kind == "shadow":
            xa = self.x_axes[_axis_index(x_axis_index, len(self.x_axes))]
            band = xa.bandWidth(self.plot.left(), self.plot.right())
            width = band if band > 1.0 else 8.0
            shadow = QColor(T("color.bg.muted"))
            shadow.setAlpha(90)
            p.fillRect(
                QRectF(x - width / 2, self.plot.top(), width, self.plot.height()),
                shadow,
            )
        elif kind == "line":
            p.drawLine(QPointF(x, self.plot.top()), QPointF(x, self.plot.bottom()))
        else:  # cross（默认）
            p.drawLine(QPointF(x, self.plot.top()), QPointF(x, self.plot.bottom()))
            p.drawLine(QPointF(self.plot.left(), y), QPointF(self.plot.right(), y))
        p.restore()


class _GridAxisView(GridCoord):
    """绑定到一对 ``(xAxisIndex, yAxisIndex)`` 的 GridCoord 视图。

    共享 ``plot`` / ``rect``，只把 ``x_axis`` / ``y_axis`` 换成所选轴。
    继承 ``GridCoord`` 是为了让系列 / 组件里既有的
    ``isinstance(coord, GridCoord)`` 判断继续成立。
    """

    def __init__(self, owner: GridCoord, x_axis_index: int, y_axis_index: int):
        self._owner = owner
        self.chart = owner.chart
        self.option = owner.option
        self.x_axis_index = x_axis_index
        self.y_axis_index = y_axis_index
        self.x_axis = owner.x_axes[x_axis_index]
        self.y_axis = owner.y_axes[y_axis_index]

    #: 覆盖基类的只读 property，让实例可以指向所选轴
    x_axis = None
    y_axis = None

    @property
    def plot(self) -> QRectF:  # type: ignore[override]
        return self._owner.plot

    @property
    def rect(self) -> QRectF:  # type: ignore[override]
        return self._owner.rect

    def mapPoint(self, x, y=None, x_axis_index=None, y_axis_index=None) -> QPointF:
        return self._owner.mapPoint(
            x,
            y,
            self.x_axis_index if x_axis_index is None else x_axis_index,
            self.y_axis_index if y_axis_index is None else y_axis_index,
        )

    def mapArrays(self, xs, ys, x_axis_index=None, y_axis_index=None):
        return self._owner.mapArrays(
            xs,
            ys,
            self.x_axis_index if x_axis_index is None else x_axis_index,
            self.y_axis_index if y_axis_index is None else y_axis_index,
        )

    def invertX(self, pos: QPointF, x_axis_index=None):
        return self._owner.invertX(
            pos, self.x_axis_index if x_axis_index is None else x_axis_index
        )

    def invertPoint(self, pos: QPointF, x_axis_index=None, y_axis_index=None):
        return self._owner.invertPoint(
            pos,
            self.x_axis_index if x_axis_index is None else x_axis_index,
            self.y_axis_index if y_axis_index is None else y_axis_index,
        )

    def containPoint(self, pos: QPointF) -> bool:
        return self._owner.containPoint(pos)

    def paintTooltipMarker(
        self, p: QPainter, pos: QPointF, kind: str = "cross", x_axis_index=None
    ) -> None:
        return self._owner.paintTooltipMarker(
            p,
            pos,
            kind,
            self.x_axis_index if x_axis_index is None else x_axis_index,
        )


def _datum_y(item):
    """取数据项的 y 值：number / [x, y] / {"value": ...}；**非有限值返回 None**。

    所有数据取 y 的入口，所以 NaN / inf 在这里滤最彻底（后果见 AGENTS.md
    「charts」的极值一条）。
    """
    if item is None:
        return None
    v = item.get("value") if isinstance(item, dict) else item
    if isinstance(v, (list, tuple)):
        if len(v) >= 2 and isinstance(v[1], (int, float)):
            return _finite_or_none(v[1])
        if len(v) == 1 and isinstance(v[0], (int, float)):
            return _finite_or_none(v[0])
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return _finite_or_none(v)
    return None


def _finite_or_none(v):
    """float(v)，非有限则 None。"""
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _datum_x(item):
    """取数据项的 x 值（无则 None，调用方用下标代替）；非有限值返回 None。"""
    if item is None:
        return None
    v = item.get("value") if isinstance(item, dict) else item
    if isinstance(v, (list, tuple)) and v:
        return _finite_or_none(v[0])
    return None


# ---------------------------------------------------------------------------
# 极坐标系
# ---------------------------------------------------------------------------


class PolarCoord(Coord):
    """极坐标系：radiusAxis（value）+ angleAxis（category/value）。

    option 键：``polar`` {``radius``（数值 / ``"N%"`` / ``[inner, outer]``，
    默认 ``"80%"``）、``center``（``["50%", "50%"]``）、``radiusAxis``、
    ``angleAxis``。``mapPoint(angle, radius)``：angle 为类别名/下标或数值，
    radius 为数值；角度自正上方起顺时针。
    """

    kind = "polar"

    def __init__(self, chart=None, option: dict = None):
        super().__init__(chart, option)
        polar = dict(self.option.get("polar") or {})
        aopt = dict(self.option.get("angleAxis") or {})
        a_default = "category" if aopt.get("data") else "value"
        self.angle_axis = AxisModel(aopt, a_default)
        self.radius_axis = AxisModel(dict(self.option.get("radiusAxis") or {}), "value")
        self._radius_opt = polar.get("radius", "80%")
        center = polar.get("center")
        self._center_opt = (
            list(center)
            if isinstance(center, (list, tuple)) and len(center) >= 2
            else ["50%", "50%"]
        )
        self.center = QPointF()
        self.radius = 1.0

    def setSeries(self, series_opts: list) -> None:
        rs = []
        for s in series_opts or []:
            if not isinstance(s, dict) or s.get("coordinateSystem") != "polar":
                continue
            for item in s.get("data") or []:
                r = _datum_y(item)
                if r is not None:
                    rs.append(r)
        if rs:
            self.radius_axis.setExtent(0.0, max(rs))
        else:
            self.radius_axis.setExtent(0.0, 1.0)
        if self.angle_axis.type == "value":
            self.angle_axis.setExtent(0.0, 360.0, segments=4)

    @staticmethod
    def _extent_px(value, avail: float, default_frac: float) -> float:
        """极坐标 radius / center 分量：数值 px、``"N%"`` 或非法 → 默认比例。"""
        if value is None:
            return avail * default_frac
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        text = str(value).strip()
        if text.endswith("%"):
            try:
                return avail * float(text[:-1]) / 100.0
            except ValueError:
                return avail * default_frac
        try:
            return float(text)
        except ValueError:
            return avail * default_frac

    def layout(self, rect: QRectF) -> None:
        super().layout(rect)
        cx = self._extent_px(self._center_opt[0], rect.width(), 0.5)
        cy = self._extent_px(self._center_opt[1], rect.height(), 0.5)
        self.center = QPointF(rect.left() + cx, rect.top() + cy)
        radius_opt = self._radius_opt
        if isinstance(radius_opt, (list, tuple)):
            radius_opt = radius_opt[-1] if radius_opt else "80%"
        self.radius = max(
            10.0,
            self._extent_px(radius_opt, min(rect.width(), rect.height()) / 2, 0.8),
        )

    def _angle_frac(self, angle) -> float:
        ax = self.angle_axis
        if ax.type == "category":
            n = max(1, len(ax.categories))
            return (ax.categoryIndex(angle) % n) / n
        span = ax.vmax - ax.vmin
        return 0.0 if span == 0 else (_to_float(angle) - ax.vmin) / span

    def mapPoint(self, x, y=None) -> QPointF:
        """(angle, radius) → 像素。angle 类别/数值；radius 数值。"""
        frac = self._angle_frac(x)
        theta = -math.pi / 2 + frac * 2 * math.pi  # 正上方起顺时针
        r_span = self.radius_axis.vmax - self.radius_axis.vmin
        r_frac = 0.0 if r_span == 0 else (_to_float(y) - self.radius_axis.vmin) / r_span
        r_frac = min(max(r_frac, 0.0), 1.0)
        r = self.radius * r_frac
        return QPointF(
            self.center.x() + r * math.cos(theta), self.center.y() + r * math.sin(theta)
        )

    def invertPoint(self, pos: QPointF):
        """像素 → ``[angle, radius]``（category 角轴返回下标）。"""
        dx = pos.x() - self.center.x()
        dy = pos.y() - self.center.y()
        r = math.hypot(dx, dy)
        r_span = self.radius_axis.vmax - self.radius_axis.vmin
        r_frac = (r / self.radius) if self.radius else 0.0
        radius_val = self.radius_axis.vmin + min(max(r_frac, 0.0), 1.0) * r_span
        frac = ((math.atan2(dy, dx) + math.pi / 2) % (2 * math.pi)) / (2 * math.pi)
        if self.angle_axis.type == "category":
            n = max(1, len(self.angle_axis.categories))
            angle = min(int(frac * n), n - 1)
        else:
            span = self.angle_axis.vmax - self.angle_axis.vmin
            angle = self.angle_axis.vmin + frac * span
        return [angle, radius_val]

    def containPoint(self, pos: QPointF) -> bool:
        return (
            math.hypot(pos.x() - self.center.x(), pos.y() - self.center.y())
            <= self.radius + 1e-6
        )

    def _ring_path(self, frac: float) -> QPainterPath:
        r = self.radius * frac
        path = QPainterPath()
        path.addEllipse(self.center, r, r)
        return path

    def paintAxes(self, p: QPainter) -> None:
        p.save()
        c_grid = QColor(T("color.border"))
        c_text = QColor(T("color.text.secondary"))
        font = self.radius_axis.labelFont()
        p.setFont(font)
        fm = QFontMetricsF(font)
        ticks = self.radius_axis.ticks()
        span = self.radius_axis.vmax - self.radius_axis.vmin
        # 环形网格（多边形 / 圆形）
        for tv in ticks[1:]:
            frac = 1.0 if span == 0 else (tv - self.radius_axis.vmin) / span
            p.setPen(QPen(c_grid, 1))
            p.drawPath(self._ring_path(frac))
        # 角轴辐条 + 外圈类别标签
        if self.angle_axis.type == "category" and self.angle_axis.categories:
            n = len(self.angle_axis.categories)
            for i, cat in enumerate(self.angle_axis.categories):
                theta = -math.pi / 2 + i / n * 2 * math.pi
                outer = QPointF(
                    self.center.x() + self.radius * math.cos(theta),
                    self.center.y() + self.radius * math.sin(theta),
                )
                p.setPen(QPen(c_grid, 1))
                p.drawLine(self.center, outer)
                lx = self.center.x() + (self.radius + 14) * math.cos(theta)
                ly = self.center.y() + (self.radius + 14) * math.sin(theta)
                p.setPen(c_text)
                p.drawText(
                    QRectF(lx - 40, ly - fm.height() / 2, 80, fm.height()),
                    Qt.AlignmentFlag.AlignCenter,
                    str(cat),
                )
        # 半径刻度标签（沿正上方辐条）
        for tv in ticks[1:]:
            frac = 1.0 if span == 0 else (tv - self.radius_axis.vmin) / span
            p.setPen(c_text)
            p.drawText(
                QRectF(
                    self.center.x() + 2,
                    self.center.y() - self.radius * frac - fm.height() / 2,
                    48,
                    fm.height(),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                formatValue(tv),
            )
        p.restore()

    def paintTooltipMarker(
        self, p: QPainter, pos: QPointF, kind: str = "cross"
    ) -> None:
        if kind == "none":
            return
        p.save()
        pen = QPen(QColor(T("color.border.strong")), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(self.center, pos)
        if kind == "cross":
            r = math.hypot(pos.x() - self.center.x(), pos.y() - self.center.y())
            if r > 1:
                p.drawEllipse(self.center, r, r)
        p.restore()


# ---------------------------------------------------------------------------
# 单轴坐标系
# ---------------------------------------------------------------------------


class SingleAxisCoord(Coord):
    """横向单轴坐标系（一行数值轴，系列在其上排布）。

    option 键：``singleAxis`` {left,right,top,bottom,type,min,max,name}
    （left/right 默认 40；top/bottom 不给时取可用区垂直居中）。
    ``mapPoint(value)`` 单参调用，返回轴线上像素点。
    """

    kind = "singleAxis"

    def __init__(self, chart=None, option: dict = None):
        super().__init__(chart, option)
        sopt = dict(self.option.get("singleAxis") or {})
        self.axis = AxisModel(sopt, "value")
        # 边距支持 px / 百分比（"10%"）；top/bottom 非法输入降级为 None（垂直居中）
        self._m_left = _parse_margin(sopt.get("left"), 40)
        self._m_right = _parse_margin(sopt.get("right"), 40)
        self._m_top = _parse_margin(sopt.get("top"), None)
        self._m_bottom = _parse_margin(sopt.get("bottom"), None)
        self.m_left = self.m_right = self.m_top = self.m_bottom = 0.0
        self.line_y = 0.0
        self.plot = QRectF()

    def setSeries(self, series_opts: list) -> None:
        vs = []
        for s in series_opts or []:
            if not isinstance(s, dict) or s.get("coordinateSystem") != "singleAxis":
                continue
            vs.extend(_iter_data_values(s.get("data")))
        if vs:
            self.axis.setExtent(min(vs), max(vs))
        else:
            self.axis.setExtent(0.0, 1.0)

    def layout(self, rect: QRectF) -> None:
        super().layout(rect)
        self.m_left = _margin_px(self._m_left, rect.width())
        self.m_right = _margin_px(self._m_right, rect.width())
        self.m_top = _margin_px(self._m_top, rect.height())
        self.m_bottom = _margin_px(self._m_bottom, rect.height())
        left = rect.left() + self.m_left
        right = rect.right() - self.m_right
        if self.m_top is not None:
            y = rect.top() + self.m_top
        elif self.m_bottom is not None:
            y = rect.bottom() - self.m_bottom
        else:
            y = rect.center().y()
        self.line_y = y
        self.plot = QRectF(left, y, max(10.0, right - left), 0.0)

    def mapPoint(self, x, y=None) -> QPointF:
        px = self.axis.map(x, self.plot.left(), self.plot.right())
        return QPointF(px, self.line_y)

    def invertX(self, pos: QPointF):
        return self.axis.invert(pos.x(), self.plot.left(), self.plot.right())

    def invertPoint(self, pos: QPointF):
        """像素 → 轴数值（单轴返回标量）。"""
        return self.axis.invert(pos.x(), self.plot.left(), self.plot.right())

    def containPoint(self, pos: QPointF) -> bool:
        rect = QRectF(
            self.plot.left(),
            self.line_y - 12.0,
            max(1.0, self.plot.width()),
            24.0,
        )
        return rect.contains(QPointF(pos))

    def paintAxes(self, p: QPainter) -> None:
        p.save()
        c_axis = QColor(T("color.border.strong"))
        c_grid = QColor(T("color.border"))
        c_text = QColor(T("color.text.secondary"))
        font = self.axis.labelFont()
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(QPen(c_axis, 1))
        p.drawLine(
            QPointF(self.plot.left(), self.line_y),
            QPointF(self.plot.right(), self.line_y),
        )
        for tv in self.axis.ticks():
            px = self.axis.map(tv, self.plot.left(), self.plot.right())
            p.setPen(QPen(c_grid, 1))
            p.drawLine(QPointF(px, self.line_y - 4), QPointF(px, self.line_y + 4))
            p.setPen(c_text)
            p.drawText(
                QRectF(px - 40, self.line_y + 6, 80, fm.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                formatValue(tv),
            )
        if self.axis.name:
            p.setPen(QColor(T("color.text.tertiary")))
            p.drawText(
                QRectF(
                    self.plot.right() + 6,
                    self.line_y - fm.height() / 2,
                    80,
                    fm.height(),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.axis.name,
            )
        p.restore()

    def paintTooltipMarker(
        self, p: QPainter, pos: QPointF, kind: str = "cross"
    ) -> None:
        if kind == "none":
            return
        p.save()
        pen = QPen(QColor(T("color.border.strong")), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        x = min(max(pos.x(), self.plot.left()), self.plot.right())
        p.drawLine(QPointF(x, self.rect.top() + 8), QPointF(x, self.rect.bottom() - 8))
        p.restore()


# ---------------------------------------------------------------------------
# 日历坐标系
# ---------------------------------------------------------------------------

_MONTH_LABELS = [
    "1月",
    "2月",
    "3月",
    "4月",
    "5月",
    "6月",
    "7月",
    "8月",
    "9月",
    "10月",
    "11月",
    "12月",
]


class CalendarCoord(Coord):
    """日历坐标系：GitHub 式 周×星期 网格（ECharts ``calendar``）。

    option 键：``calendar``：``range``（``2026`` / ``"2026"`` /
    ``["2026-01-01", "2026-12-31"]``，缺省当前年）、``orient``
    （``"horizontal"`` 默认 / ``"vertical"``）、``cellSize``（px 或 ``"auto"``）、
    ``dayLabel`` {show, firstDay（0=周日 … 6=周六，或 "sunday"/"monday"）}、
    ``monthLabel`` {show}、``yearLabel`` {show}、``splitLine``
    {show, lineStyle}、``itemStyle`` {color, borderColor, borderWidth}。

    行 / 列 = 星期与周序（orient 决定转置）；``mapPoint(date)`` 单参 →
    单元格中心；``cellRect(date)``；``dateAt(pos)`` 反查。
    """

    kind = "calendar"

    def __init__(self, chart=None, option: dict = None):
        super().__init__(chart, option)
        cal = dict(self.option.get("calendar") or {})
        self.cal_opt = cal
        self.start, self.end = self._resolve_range(cal.get("range"))
        self.year = self.start.year
        self._vertical = str(cal.get("orient") or "horizontal") == "vertical"
        day_label = cal.get("dayLabel")
        self._day_label = day_label if isinstance(day_label, dict) else {}
        month_label = cal.get("monthLabel")
        self._month_label = month_label if isinstance(month_label, dict) else {}
        year_label = cal.get("yearLabel")
        self._year_label = year_label if isinstance(year_label, dict) else {}
        split = cal.get("splitLine")
        self._split_line = split if isinstance(split, dict) else {}
        item_style = cal.get("itemStyle")
        self._item_style = item_style if isinstance(item_style, dict) else {}
        self.cell_size_opt = cal.get("cellSize", 14)
        self._row_offset = self._parse_first_day(self._day_label.get("firstDay"))
        self.show_week_labels = bool(self._day_label.get("show", True))
        self.show_month_labels = bool(self._month_label.get("show", True))
        self.show_year_label = bool(self._year_label.get("show", True))
        self._cell = 14.0
        self._origin = QPointF()  # 网格左上角（orient 转置后）
        self._weeks = 1

    # -- 选项 -------------------------------------------------------------
    @staticmethod
    def _parse_first_day(value) -> int:
        """``dayLabel.firstDay`` → 行号偏移（周日=6，周一=0）。默认周日在上。"""
        text = str(value).strip().lower() if value is not None else ""
        if text in ("monday", "mon", "1"):
            return 0
        if text in ("", "0", "sunday", "sun"):
            return 6  # 0 = 周日（默认）
        try:
            first = int(value) % 7
        except (TypeError, ValueError, OverflowError):
            return 6
        return (first - 1) % 7

    @classmethod
    def _clamp_year(cls, year):
        """年份夹到 ``date`` 支持的区间（1..9999），越界回退当前年。

        ``{"calendar": {"range": 10000}}`` 原先让 ``date(10000, 1, 1)`` 抛
        ``ValueError``，而 ``_make_coord`` 的兜底只是 ``coord = None`` →
        **整张日历热力图静默空白**，看不出是年份越界。
        """
        try:
            y = int(year)
        except (TypeError, ValueError, OverflowError):
            return date.today().year
        if y < 1 or y > _MAX_DATE_YEAR:
            return date.today().year
        return y

    @classmethod
    def _resolve_range(cls, rng):
        """``calendar.range`` → ``(start, end)``。

        支持年份（``2026`` / ``"2026"``）、单日期、``[start, end]`` 或
        ``["2026"]``；非法 / 缺省回退当前年。
        """
        today = date.today()
        year = today.year
        if rng is None:
            return date(year, 1, 1), date(year, 12, 31)
        if isinstance(rng, (int, float)) and not isinstance(rng, bool):
            year = cls._clamp_year(rng)
            return date(year, 1, 1), date(year, 12, 31)
        if isinstance(rng, str):
            text = rng.strip()
            if len(text) == 4 and text.isdigit():
                year = cls._clamp_year(text)
                return date(year, 1, 1), date(year, 12, 31)
            parsed = cls._parse_date(text)
            if parsed is not None:
                return parsed, parsed
            return date(year, 1, 1), date(year, 12, 31)
        if isinstance(rng, (list, tuple)):
            items = list(rng)
            if len(items) == 1:
                items.append(None)
            start = cls._parse_date(items[0])
            end = cls._parse_date(items[1]) if len(items) > 1 else None
            if start is None and isinstance(items[0], (int, float)):
                year = cls._clamp_year(items[0])
                return date(year, 1, 1), date(year, 12, 31)
            if start is None:
                start = date(year, 1, 1)
            if end is None:
                end = date(start.year, 12, 31)
            if end < start:
                start, end = end, start
            return start, end
        return date(year, 1, 1), date(year, 12, 31)

    # -- 日期工具 ---------------------------------------------------------
    @staticmethod
    def _parse_date(v):
        """ "YYYY-MM-DD" / date / (y, m, d) → datetime.date（失败 None）。"""
        if isinstance(v, date):
            return v
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            try:
                return date(int(v[0]), int(v[1]), int(v[2]))
            except (TypeError, ValueError, OverflowError):
                return None
        if isinstance(v, str):
            try:
                parts = v.strip().split("-")
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
            except (TypeError, ValueError, OverflowError, IndexError):
                return None
        return None

    def _first_column_start(self) -> date:
        """首格对应的日期（按 ``dayLabel.firstDay`` 对齐）。"""
        return self.start - timedelta(
            days=(self.start.weekday() - self._row_offset) % 7
        )

    def _row_of(self, day: date) -> int:
        """日期 → 星期行号（0 = 首行，按 firstDay）。"""
        return (day.weekday() - self._row_offset) % 7

    def _month_dates(self) -> list:
        """start→end 逐月 1 日列表（跨年 range 正确）。"""
        out = []
        d = date(self.start.year, self.start.month, 1)
        while d <= self.end:
            out.append(d)
            # ``date`` 的 year 上限是 9999：range 落在 9999 年时
            # ``date(d.year + 1, 1, 1)`` 抛 ValueError，而这里跑在
            # ``paintAxes`` 的调用链上 → 整张日历热力图静默空白。
            if d.year >= _MAX_DATE_YEAR:
                break
            if d.month == 12:
                d = date(d.year + 1, 1, 1)
            else:
                d = date(d.year, d.month + 1, 1)
        return out

    def _grid_xy(self, week_index: int, weekday_row: int):
        """(周序, 星期行) → 网格 (列, 行)（``orient`` 转置）。"""
        if self._vertical:
            return weekday_row, week_index
        return week_index, weekday_row

    # -- 协议 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        super().layout(rect)
        label_top = 16.0  # 月份 / 星期标签带
        label_left = 28.0  # 星期 / 月份标签带
        if self._vertical:
            label_top = 18.0
            label_left = 36.0
        first = self._first_column_start()
        self._weeks = max(1, (self.end - first).days // 7 + 1)
        cols = 7 if self._vertical else self._weeks
        rows = self._weeks if self._vertical else 7
        avail_w = max(20.0, rect.width() - label_left - 4)
        avail_h = max(20.0, rect.height() - label_top - 4)
        if str(self.cell_size_opt).lower() == "auto":
            self._cell = max(3.0, min(avail_w / cols, avail_h / rows))
        else:
            self._cell = max(3.0, _to_float(self.cell_size_opt, 14.0))
        grid_w = self._cell * cols
        ox = rect.left() + label_left + max(0.0, (avail_w - grid_w) / 2)
        self._origin = QPointF(ox, rect.top() + label_top)

    def cellRect(self, day) -> QRectF:
        """日期 → 单元格矩形（无法解析 / 范围外返回空矩形）。"""
        d = self._parse_date(day)
        if d is None or d < self.start or d > self.end:
            return QRectF()
        first = self._first_column_start()
        week_index = (d - first).days // 7
        col, row = self._grid_xy(week_index, self._row_of(d))
        return QRectF(
            self._origin.x() + col * self._cell,
            self._origin.y() + row * self._cell,
            self._cell,
            self._cell,
        )

    def mapPoint(self, x, y=None) -> QPointF:
        """日期 → 单元格中心。"""
        r = self.cellRect(x)
        if r.isNull():
            return QPointF(self._origin)
        return r.center()

    def invertPoint(self, pos: QPointF):
        """像素 → ``[ISO 日期]``（网格外返回 None）。"""
        d = self.dateAt(pos)
        if d is None:
            return None
        return [d.isoformat()]

    def containPoint(self, pos: QPointF) -> bool:
        return self.dateAt(pos) is not None

    def cellSize(self) -> float:
        """当前单元格边长（px）。"""
        return self._cell

    def weeks(self) -> int:
        """总列数 / 行数（周数）。"""
        return self._weeks

    def iterDates(self):
        """遍历范围内全部日期（含无数据日）。"""
        d = self.start
        while d <= self.end:
            yield d
            # ``date`` 上限是 9999-12-31，再加一天抛 OverflowError —— 跑在
            # heatmap 的 layout 里 → 整张日历热力图静默空白。
            if d.year >= _MAX_DATE_YEAR:
                break
            d += timedelta(days=1)

    def _weekday_label_rows(self) -> dict:
        """星期标签序号 → 标签（GitHub 只标 周一/周三/周五）。"""
        return {row: label for row, label in ((0, "周一"), (2, "周三"), (4, "周五"))}

    def itemStyle(self) -> dict:
        """``calendar.itemStyle``（空日底色 / 边框由 heatmap 系列读取）。"""
        return self._item_style

    def paintAxes(self, p: QPainter) -> None:
        p.save()
        c_text = QColor(T("color.text.tertiary"))
        font = chartFont(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(c_text)
        # 星期标签（周一/周三/周五；行号按 firstDay 换算）
        if self.show_week_labels:
            for local_row, label in self._weekday_label_rows().items():
                row = (local_row - self._row_offset) % 7
                if self._vertical:
                    x = self._origin.x() + row * self._cell
                    p.drawText(
                        QRectF(x, self.rect.top(), self._cell, 14),
                        Qt.AlignmentFlag.AlignCenter,
                        label,
                    )
                else:
                    y = self._origin.y() + row * self._cell
                    p.drawText(
                        QRectF(
                            self.rect.left(),
                            y,
                            max(8.0, self._origin.x() - self.rect.left() - 4),
                            self._cell,
                        ),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        label,
                    )
        # 月份标签：每月 1 日所在格（去重；跨年逐月遍历）
        if self.show_month_labels:
            first = self._first_column_start()
            last_idx = -1
            for d in self._month_dates():
                anchor = d if d >= self.start else self.start
                week_index = (anchor - first).days // 7
                if week_index == last_idx:
                    continue
                last_idx = week_index
                if self._vertical:
                    y = self._origin.y() + week_index * self._cell
                    p.drawText(
                        QRectF(
                            self.rect.left(),
                            y,
                            max(8.0, self._origin.x() - self.rect.left() - 4),
                            self._cell,
                        ),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        _MONTH_LABELS[d.month - 1],
                    )
                else:
                    x = self._origin.x() + week_index * self._cell
                    p.drawText(
                        QRectF(x, self.rect.top(), 40, fm.height()),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        _MONTH_LABELS[d.month - 1],
                    )
        # 年份标签
        if self.show_year_label and str(self.start.year) == str(self.end.year):
            p.drawText(
                QRectF(self.rect.left(), self.rect.top(), 60, fm.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                str(self.start.year),
            )
        # splitLine：单元格网格线
        if bool(self._split_line.get("show", False)):
            p.setPen(_line_pen(self._split_line, T("color.border")))
            grid_w = self._cell * (7 if self._vertical else self._weeks)
            grid_h = self._cell * (self._weeks if self._vertical else 7)
            cols = 7 if self._vertical else self._weeks
            rows = self._weeks if self._vertical else 7
            for c in range(cols + 1):
                x = self._origin.x() + c * self._cell
                p.drawLine(
                    QPointF(x, self._origin.y()), QPointF(x, self._origin.y() + grid_h)
                )
            for r in range(rows + 1):
                y = self._origin.y() + r * self._cell
                p.drawLine(
                    QPointF(self._origin.x(), y), QPointF(self._origin.x() + grid_w, y)
                )
        p.restore()

    def paintTooltipMarker(
        self, p: QPainter, pos: QPointF, kind: str = "cross"
    ) -> None:
        if kind == "none":
            return
        p.save()
        d = self.dateAt(pos)
        if d is not None:
            r = self.cellRect(d)
            pen = QPen(QColor(T("color.primary")), 1.4)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
        p.restore()

    def dateAt(self, pos: QPointF):
        """像素 → 日期（网格外返回 None）。"""
        if self._cell <= 0:
            return None
        col = int((pos.x() - self._origin.x()) // self._cell)
        row = int((pos.y() - self._origin.y()) // self._cell)
        cols = 7 if self._vertical else self._weeks
        rows = self._weeks if self._vertical else 7
        if col < 0 or col >= cols or row < 0 or row >= rows:
            return None
        if self._vertical:
            weekday, week_index = col, row
        else:
            week_index, weekday = col, row
        try:
            d = self._first_column_start() + timedelta(days=week_index * 7 + weekday)
        except OverflowError:
            # range 落在 9999 年末尾时，最后几列会越出 ``date`` 上限
            return None
        if d < self.start or d > self.end:
            return None
        return d
