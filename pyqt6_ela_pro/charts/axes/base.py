"""坐标基类与轴模型。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter

from .._tokens import T
from .._utils import merged_text_style, parse_color, text_italic, text_weight
from ._shared import (
    _MAX_DATE_YEAR,
    _MAX_TICKS,
    _clamp_tick_count,
    _dt_to_ms,
    _format_log_tick,
    _log_ticks,
    _ms_to_dt,
    _opt_bound,
    _to_float,
    chartFont,
    formatValue,
    niceTicks,
)

if TYPE_CHECKING:
    from ..core.widget import ElaChartWidget


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
        self, p: QPainter, pos: QPointF, kind: str = "cross", line_style: dict = None
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


class AxisModel:
    """坐标轴模型：category（list[str]）或 value（自动 nice ticks）。

    ECharts 轴键：``type`` / ``data`` / ``name`` / ``min`` / ``max`` /
    ``boundaryGap`` / ``inverse`` / ``scale`` / ``nameLocation`` / ``nameGap`` /
    ``interval`` / ``minInterval`` / ``maxInterval`` / ``splitNumber`` /
    ``axisLabel`` / ``axisTick`` / ``axisLine`` / ``splitLine`` / ``splitArea``。

    :param default_type: opt 未给 ``type`` 时的兜底
    """

    def __init__(
        self,
        opt: dict = None,
        default_type: str = "value",
        chart: "ElaChartWidget" = None,
    ):
        opt = dict(opt or {})
        self.opt = opt
        #: 图表实例（只为读顶层 ``textStyle`` 兜底；单测可直接构造为 None）
        self.chart = chart
        #: 所属网格下标（``gridIndex``，多网格时决定画在哪块网格上）
        try:
            self.grid_index = max(0, int(opt.get("gridIndex", 0) or 0))
        except (TypeError, ValueError, OverflowError):
            self.grid_index = 0
        raw_type = str(opt.get("type") or default_type).strip().lower()
        #: ``type: "time"`` 在内部按 value 轴计算（数值 = 毫秒），只换刻度 /
        #: 标签的生成方式与最小值 / 最大值解析（日期字符串）。
        self.is_time = raw_type == "time"
        self.type = "value" if self.is_time else raw_type
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

    # -- 时间轴 ----------------------------------------------------------
    @staticmethod
    def toNumber(value):
        """日期 / ISO 字符串 / 数字 → 毫秒时间戳（失败 None）。

        数字按毫秒处理（ECharts ``time`` 轴同口径）；``datetime`` / ``date``
        与 ``(y, m, d[, H, M, S])`` 元组转本地时区时间戳。
        """
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            v = float(value)
            return v if math.isfinite(v) else None
        if isinstance(value, datetime):
            return _dt_to_ms(value)
        if isinstance(value, date):
            return _dt_to_ms(datetime(value.year, value.month, value.day))
        if isinstance(value, (list, tuple)):
            try:
                parts = [int(v) for v in value[:6]]
                while len(parts) < 3:
                    parts.append(1)
                return _dt_to_ms(datetime(*parts))
            except (TypeError, ValueError, OverflowError):
                return None
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return _dt_to_ms(datetime.fromisoformat(text.replace("/", "-")))
            except (TypeError, ValueError, OverflowError):
                return None
        return None

    @staticmethod
    def _addMonths(dt: datetime, months: int) -> datetime:
        total = dt.year * 12 + (dt.month - 1) + int(months)
        year, month = divmod(total, 12)
        if year > _MAX_DATE_YEAR:
            return dt
        return dt.replace(year=year, month=month + 1, day=1)

    def _time_floor(self, ms: float, kind: str, step_ms: int) -> datetime:
        dt = _ms_to_dt(ms)
        if kind == "year":
            return datetime(dt.year, 1, 1)
        if kind == "month":
            return datetime(dt.year, dt.month, 1)
        if step_ms >= 86400000:
            return datetime(dt.year, dt.month, dt.day)
        if step_ms >= 3600000:
            return dt.replace(minute=0, second=0, microsecond=0)
        if step_ms >= 60000:
            return dt.replace(second=0, microsecond=0)
        return dt.replace(microsecond=0)

    def _time_ticks(self, lo: float, hi: float, segments: int):
        """时间轴刻度：从秒到年的阶梯，按本地时间边界对齐。"""
        span = max(1.0, float(hi) - float(lo))
        target = max(2, int(segments or 5))
        want = span / target
        ladder = (
            (1000, "sec", 0),
            (2000, "sec", 0),
            (5000, "sec", 0),
            (10000, "sec", 0),
            (15000, "sec", 0),
            (30000, "sec", 0),
            (60000, "sec", 0),
            (120000, "sec", 0),
            (300000, "sec", 0),
            (600000, "sec", 0),
            (900000, "sec", 0),
            (1800000, "sec", 0),
            (3600000, "sec", 0),
            (7200000, "sec", 0),
            (10800000, "sec", 0),
            (21600000, "sec", 0),
            (43200000, "sec", 0),
            (86400000, "day", 0),
            (172800000, "day", 0),
            (604800000, "day", 0),
            (2592000000, "month", 1),
            (7776000000, "month", 3),
            (15552000000, "month", 6),
            (31536000000, "year", 1),
        )
        step_ms, kind, months = ladder[-1]
        for candidate in ladder:
            if candidate[0] >= want:
                step_ms, kind, months = candidate
                break
        else:
            years = max(1, int(math.ceil(want / 31536000000.0)))
            step_ms, kind, months = years * 31536000000, "year", years
        start = self._time_floor(lo, kind, step_ms)
        end = self._time_floor(hi, kind, step_ms)
        if end < _ms_to_dt(hi):
            if kind == "month":
                nxt = self._addMonths(end, months)
                if nxt.year <= _MAX_DATE_YEAR:
                    end = nxt
            elif kind == "year":
                if end.year + months <= _MAX_DATE_YEAR:
                    end = end.replace(year=end.year + months)
            else:
                end = end + timedelta(milliseconds=step_ms)
        ticks = []
        cursor = start
        limit = 2000
        while _dt_to_ms(cursor) <= _dt_to_ms(end) + 1 and len(ticks) < limit:
            ticks.append(_dt_to_ms(cursor))
            if kind == "month":
                if cursor.year >= _MAX_DATE_YEAR and months > 0:
                    break
                cursor = self._addMonths(cursor, months)
            elif kind == "year":
                if cursor.year + months > _MAX_DATE_YEAR:
                    break
                cursor = cursor.replace(year=cursor.year + months)
            else:
                cursor = cursor + timedelta(milliseconds=step_ms)
        if len(ticks) < 2:
            ticks = [_dt_to_ms(start), _dt_to_ms(end)]
        return (
            ticks[0],
            ticks[-1],
            ticks,
            int(step_ms),
            kind,
        )

    def _set_time_extent(self, lo, hi, segments: int) -> None:
        min_value = self._time_bound(self.min)
        max_value = self._time_bound(self.max)
        if min_value is not None:
            lo = min_value
        if max_value is not None:
            hi = max_value
        if lo is None or hi is None or not (math.isfinite(lo) and math.isfinite(hi)):
            lo, hi = 0.0, 86400000.0
        if hi <= lo:
            hi = lo + 86400000.0
        self.vmin, self.vmax, self._ticks, self._time_step_ms, self._time_kind = (
            self._time_ticks(lo, hi, segments)
        )

    def _time_bound(self, raw):
        return self.toNumber(raw) if raw is not None else None

    def _time_tokens(self, value) -> dict:
        dt = _ms_to_dt(value)
        return {
            "yyyy": f"{dt.year:04d}",
            "MM": f"{dt.month:02d}",
            "dd": f"{dt.day:02d}",
            "HH": f"{dt.hour:02d}",
            "mm": f"{dt.minute:02d}",
            "ss": f"{dt.second:02d}",
            "value": formatValue(value),
        }

    def _format_time_tick(self, value, formatter=None) -> str:
        if callable(formatter):
            try:
                out = formatter(value, 0)
            except TypeError:
                try:
                    out = formatter(value)
                except Exception:
                    out = None
            except Exception:
                out = None
            if out is not None:
                return str(out)
        if isinstance(formatter, str) and formatter:
            try:
                return formatter.format_map(self._time_tokens(value))
            except Exception:
                pass
        step = getattr(self, "_time_step_ms", 86400000)
        dt = _ms_to_dt(value)
        if step < 60000:
            return dt.strftime("%H:%M:%S")
        if step < 86400000:
            return dt.strftime("%H:%M")
        if step < 2592000000:
            return dt.strftime("%m-%d")
        if step < 31536000000:
            return dt.strftime("%Y-%m")
        return dt.strftime("%Y")

    def _format_time_value(self, value) -> str:
        dt = _ms_to_dt(value)
        if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%Y-%m-%d %H:%M")

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
        if self.is_time:
            self._set_time_extent(data_min, data_max, segments)
            return
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
        if self.is_time:
            value = self.toNumber(value)
            if value is None:
                return float("nan")
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
        if self.is_time:
            value = self.toNumber(value)
            if value is None:
                return float("nan")
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
        if self.is_time:
            span = hi - lo
            a = lo + span * start / 100.0
            b = lo + span * end / 100.0
            self.vmin, self.vmax, self._ticks, self._time_step_ms, self._time_kind = (
                self._time_ticks(a, max(a, b), 5)
            )
            return
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
        """axisLabel 字体（``axisLabel.fontSize`` / ``fontWeight`` → font.xs / 400）。

        未设置的键回退顶层 ``textStyle``（``fontSize`` / ``fontWeight``）。
        """
        style = merged_text_style(self.chart, self.axisLabelOption())
        try:
            size = float(style.get("fontSize", T("font.xs")))
        except (TypeError, ValueError, OverflowError):
            size = float(T("font.xs"))
        if not math.isfinite(size) or size <= 0:
            size = float(T("font.xs"))
        return chartFont(
            size,
            text_weight(style.get("fontWeight"), 400),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )

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

    def formatTickLabel(self, value, index=None) -> str:
        """``axisLabel.formatter``（字符串模板 ``{value}`` 或 callable）→ 文本。

        value 轴 formatter 收到数值（整数值按 JS 习惯转 int）；
        category 轴收到类别字符串。callable 的第二个参数是**刻度下标**
        （与 ECharts 的 ``formatter(value, index)`` 对齐；旧的一参 callable
        仍兼容）。
        """
        label = self.axisLabelOption()
        formatter = label.get("formatter")
        if self.is_time:
            return self._format_time_tick(value, formatter)
        if self.type != "category":
            raw = (
                int(value) if isinstance(value, float) and value.is_integer() else value
            )
        else:
            raw = str(value)
        text = _format_log_tick(raw) if self.type == "log" else formatValue(raw)
        if callable(formatter):
            tick_index = 0 if index is None else int(index)
            try:
                out = formatter(raw, tick_index)
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

    def formatTooltipValue(self, value) -> str:
        """tooltip 标题用的轴值文案（value / log / time）。"""
        if self.is_time:
            num = self.toNumber(value)
            return self._format_time_value(num) if num is not None else str(value)
        if self.type == "log":
            return _format_log_tick(value)
        return formatValue(value)

    def nameTextStyle(self) -> dict:
        """轴名样式（``nameTextStyle``；未设置的键回退顶层 ``textStyle``）。"""
        return merged_text_style(self.chart, self.opt.get("nameTextStyle"))

    def nameFont(self) -> QFont:
        """轴名字体（``nameTextStyle.fontSize`` / ``fontWeight``）。"""
        style = self.nameTextStyle()
        try:
            size = float(style.get("fontSize", T("font.xs")))
        except (TypeError, ValueError, OverflowError):
            size = float(T("font.xs"))
        if not math.isfinite(size) or size <= 0:
            size = float(T("font.xs"))
        return chartFont(
            size,
            text_weight(style.get("fontWeight")),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )

    def labelColor(self) -> QColor:
        """axisLabel 文本色（``axisLabel.color`` → 顶层 ``textStyle.color`` → 次级文本色）。"""
        raw = merged_text_style(self.chart, self.axisLabelOption()).get("color")
        if isinstance(raw, str) and raw:
            color = parse_color(raw)
            if color.isValid():
                return color
        return QColor(T("color.text.secondary"))
