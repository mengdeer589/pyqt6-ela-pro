"""直角坐标系列的共享数值 / 几何工具与网格范围缓存。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QTransform
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
)

from .._tokens import T
from .. import _downsample as _ds
from .._symbol import drawSymbol
from .._utils import parse_color, to_float as _to_float
from ..axes import formatValue
from ..core import parseDataPoint


def _lerp(a, b, t):
    return a + (b - a) * t


# -- 数据点标签的 rotate / align -------------------------------------------

_LABEL_ALIGNS = ("left", "center", "right")


def label_rotate(label: dict) -> float:
    """``series.label.rotate``（度；非法值 0）。"""
    return _to_float(label.get("rotate"), 0.0)


def label_align(label: dict) -> str:
    """``series.label.align``（``left`` / ``center`` / ``right``；空 = 跟随位置）。"""
    raw = str(label.get("align") or "").strip().lower()
    return raw if raw in _LABEL_ALIGNS else ""


def label_anchor_offset(align: str, width: float) -> float:
    """``align`` 相对默认居中的水平锚点偏移（top / bottom / inside 语义）。"""
    if align == "left":
        return width / 2.0
    if align == "right":
        return -width / 2.0
    return 0.0


def label_rotated_bounds(rect: QRectF, angle: float) -> QRectF:
    """标签矩形旋转后的外接矩形（命中 / 重叠判定用）。"""
    if abs(angle) < 1e-6:
        return QRectF(rect)
    transform = QTransform()
    transform.translate(rect.center().x(), rect.center().y())
    transform.rotate(angle)
    local = QRectF(
        -rect.width() / 2.0,
        -rect.height() / 2.0,
        rect.width(),
        rect.height(),
    )
    return transform.mapRect(local)


def paint_label_at(
    p: QPainter, anchor: QPointF, text: str, fm, angle: float = 0.0
) -> QRectF:
    """在 ``anchor``（文字基线起点）画标签，绕文字中心旋转；返回外接矩形。"""
    width = fm.horizontalAdvance(text)
    center = QPointF(anchor.x() + width / 2.0, anchor.y() - fm.ascent() / 2.0)
    if abs(angle) < 1e-6:
        p.drawText(anchor, text)
    else:
        p.save()
        p.translate(center)
        p.rotate(angle)
        p.drawText(QPointF(-width / 2.0, fm.ascent() / 2.0), text)
        p.restore()
    rect = QRectF(
        center.x() - width / 2.0,
        center.y() - fm.height() / 2.0,
        width,
        fm.height(),
    )
    return label_rotated_bounds(rect, angle)


def paint_label_in(
    p: QPainter, rect: QRectF, text: str, angle: float = 0.0, align=None
) -> QRectF:
    """在 ``rect`` 内画标签（默认居中）；``angle`` 非 0 时绕矩形中心旋转。"""
    align = align or (Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
    if abs(angle) < 1e-6:
        p.drawText(rect, align, text)
        return QRectF(rect)
    p.save()
    p.translate(rect.center())
    p.rotate(angle)
    local = QRectF(
        -rect.width() / 2.0,
        -rect.height() / 2.0,
        rect.width(),
        rect.height(),
    )
    p.drawText(local, align, text)
    p.restore()
    return label_rotated_bounds(rect, angle)


_SAMPLE_CACHE_MAX = 6
_GAP_MIN_PIXELS = 4.0


def _win_span(win, data_len: int):
    """窗口 ``(first, last, size)``。

    ``win`` 为 ``None``（全量）/ ``(start, stop)`` 连续段 / 下标 ``ndarray``。
    """
    if win is None:
        return 0, data_len - 1, data_len
    if isinstance(win, tuple):
        start, stop = win
        return start, stop - 1, max(0, stop - start)
    size = int(win.size)
    if size == 0:
        return -1, -1, 0
    return int(win[0]), int(win[-1]), size


def _ramp_color(colors, t):
    """多色带插值：colors 为颜色列表，t∈[0,1] → QColor。"""
    cols = [parse_color(c) for c in (colors or []) if c]
    if not cols:
        return QColor(T("color.primary"))
    if len(cols) == 1:
        return cols[0]
    t = max(0.0, min(1.0, float(t)))
    pos = t * (len(cols) - 1)
    i = min(int(pos), len(cols) - 2)
    f = pos - i
    a, b = cols[i], cols[i + 1]
    return QColor(
        int(_lerp(a.red(), b.red(), f)),
        int(_lerp(a.green(), b.green(), f)),
        int(_lerp(a.blue(), b.blue(), f)),
        int(_lerp(a.alpha(), b.alpha(), f)),
    )


def _smooth_path(points, smooth=0.5):
    """Catmull-Rom → 三次贝塞尔平滑路径。points: [QPointF]（≥2）。"""
    path = QPainterPath()
    n = len(points)
    if n == 0:
        return path
    path.moveTo(points[0])
    if n == 1:
        return path
    k = max(0.0, min(1.0, float(smooth)))
    for i in range(n - 1):
        p0 = points[max(i - 1, 0)]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[min(i + 2, n - 1)]
        c1 = QPointF(
            p1.x() + (p2.x() - p0.x()) * k / 6.0,
            p1.y() + (p2.y() - p0.y()) * k / 6.0,
        )
        c2 = QPointF(
            p2.x() - (p3.x() - p1.x()) * k / 6.0,
            p2.y() - (p3.y() - p1.y()) * k / 6.0,
        )
        path.cubicTo(c1, c2, p2)
    return path


def _monotone_path(points):
    """单调三次样条（Steffen）：折线平滑但不过冲（``smoothMonotone``）。"""
    path = QPainterPath()
    n = len(points)
    if n < 2:
        if n == 1:
            path.moveTo(points[0])
        return path
    xs = [p.x() for p in points]
    ys = [p.y() for p in points]
    for i in range(n - 1):
        if xs[i + 1] <= xs[i]:
            return _smooth_path(points, 0.5)
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    m = [0.0] * n
    m[0] = d[0]
    m[-1] = d[-1]
    for i in range(1, n - 1):
        m[i] = (d[i - 1] + d[i]) / 2.0
    for i in range(n - 1):
        if d[i] == 0.0:
            m[i] = m[i + 1] = 0.0
            continue
        a = m[i] / d[i]
        b = m[i + 1] / d[i]
        if a < 0:
            m[i] = 0.0
        if b < 0:
            m[i + 1] = 0.0
        if a * a + b * b > 9.0:
            tau = 3.0 / math.sqrt(a * a + b * b)
            m[i] = tau * a * d[i]
            m[i + 1] = tau * b * d[i]
    path.moveTo(points[0])
    for i in range(n - 1):
        dx = xs[i + 1] - xs[i]
        c1 = QPointF(xs[i] + dx / 3.0, ys[i] + m[i] * dx / 3.0)
        c2 = QPointF(xs[i + 1] - dx / 3.0, ys[i + 1] - m[i + 1] * dx / 3.0)
        path.cubicTo(c1, c2, points[i + 1])
    return path


def _draw_symbol(p: QPainter, kind: str, pt: QPointF, size: float, rotate: float = 0.0):
    """画数据点符号（支持 ``symbolRotate``；0 度走原路径）。"""
    if not rotate:
        drawSymbol(p, kind, pt, size)
        return
    p.save()
    p.translate(pt)
    p.rotate(float(rotate))
    drawSymbol(p, kind, QPointF(0.0, 0.0), size)
    p.restore()


def _has_explicit_x(item) -> bool:
    """数据项是否显式带 x（``[x, y]`` / ``{"value": [x, y]}``）。"""
    value = item.get("value") if isinstance(item, dict) else item
    return isinstance(value, (list, tuple)) and len(value) >= 2


def _label_placement(point, text, fm, position="top", distance=4.0, marker_r=0.0):
    """数据点标签的落点（ECharts ``label.position``）。

    返回 ``(baseline_anchor, hit_rect)``：``baseline_anchor`` 给
    ``QPainter.drawText(QPointF, text)``，``hit_rect`` 与画出来的文字一致
    （双击编辑命中用）。
    """
    tw = fm.horizontalAdvance(text)
    ascent, descent = fm.ascent(), fm.descent()
    px, py = point.x(), point.y()
    pos = str(position or "top").lower()
    if pos == "bottom":
        baseline = py + marker_r + distance + ascent
        anchor = QPointF(px - tw / 2.0, baseline)
    elif pos == "left":
        baseline = py + (ascent - descent) / 2.0
        anchor = QPointF(px - marker_r - distance - tw, baseline)
    elif pos == "right":
        baseline = py + (ascent - descent) / 2.0
        anchor = QPointF(px + marker_r + distance, baseline)
    elif pos == "inside":
        baseline = py + (ascent - descent) / 2.0
        anchor = QPointF(px - tw / 2.0, baseline)
    else:  # top（默认）
        baseline = py - marker_r - distance
        anchor = QPointF(px - tw / 2.0, baseline)
    rect = QRectF(
        anchor.x() - 2.0,
        baseline - ascent,
        tw + 4.0,
        fm.height() + 2.0,
    )
    return anchor, rect


def _datum_list(item):
    """取数据项的数值列表：[...] 或 {"value": [...]} → list[float]|None。"""
    v = item.get("value") if isinstance(item, dict) else item
    if not isinstance(v, (list, tuple)):
        return None
    out = []
    for x in v:
        f = _to_float(x, None)
        if f is None:
            return None
        out.append(f)
    return out


def _grid_series_opts(
    chart, axis_kind: str = None, axis_index: int = 0, grid_index: int = None
):
    """当前 option 中落在 grid 坐标系的系列 option 列表（内部引用，零拷贝）。

    ``axis_kind`` 为 ``"x"`` / ``"y"`` 时只保留绑定到该轴索引的系列
    （缺省索引 = 0）；``None`` 表示不过滤。
    """
    out = []
    for s in chart._option_ref().get("series") or []:
        if not isinstance(s, dict):
            continue
        if s.get("coordinateSystem") not in (None, "cartesian2d", "grid"):
            continue
        if grid_index is not None:
            try:
                own_grid = int(s.get("gridIndex", 0) or 0)
            except (TypeError, ValueError, OverflowError):
                own_grid = 0
            if own_grid != grid_index:
                continue
        if axis_kind in ("x", "y"):
            key = "xAxisIndex" if axis_kind == "x" else "yAxisIndex"
            try:
                idx = int(s.get(key, 0) or 0)
            except (TypeError, ValueError, OverflowError):
                idx = 0
            if idx != axis_index:
                continue
        out.append(s)
    return out


def _finite(v) -> bool:
    """是否为有限数值（None / NaN / inf 一律 False）。"""
    try:
        return math.isfinite(v)
    except TypeError:
        return False


def _numeric_xy(data):
    """数值化 ``[(x, y), ...]`` → numpy 数组；不可数值化返回 ``(None, None)``。

    折线已有这套快路径（``LineSeriesRenderer._to_arrays``），但 bar /
    candlestick / boxplot 的 ``layout`` 仍在逐项调 ``parseDataPoint``
    ——本优化的先冲来自「逐项调
    ``parseDataPoint``」（cProfile 下 tottime 前三），而不是柱的绝对数量。

    纯数值序列（x 取下标）与 ``[x, y]`` 对序列走 numpy；含 dict / None /
    混合形态返回 ``(None, None)``，调用方回退 Python 循环（数据量通常较小）。
    """
    if _ds.np is None:
        return None, None
    n = len(data) if hasattr(data, "__len__") else 0
    if not n:
        return None, None
    np_ = _ds.np
    # **必须先抽样确认元素类型**：``asarray`` 对 ``[1.0, None]`` 会把 None
    # 变成 NaN 并成功返回（ndim==1），对 ``[[1,2,3]]`` 也会成功返回
    # （ndim==2, shape[1]==3）。若直接信任返回值，这两种结构型数据会被
    # 误当数值序列 —— ``[x, y, z]`` 的第三列被静默丢弃、None 间隙被
    # 当成 NaN 跳过（后者恰好正确，但前者是错误）。
    step = max(1, n // 64)
    probes = set(range(0, n, step))
    probes.update(range(min(24, n)))
    probes.update(range(max(0, n - 24), n))
    for i in probes:
        item = data[i]
        if isinstance(item, bool):
            return None, None
        if isinstance(item, (int, float)):
            continue
        if isinstance(item, (list, tuple)):
            # 只接受长度恰为 2 的 [x, y]
            if len(item) == 2 and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in item
            ):
                continue
            return None, None
        return None, None
    try:
        arr = np_.asarray(data, dtype=np_.float64)
    except (TypeError, ValueError, OverflowError):
        return None, None
    if arr.ndim == 1:
        return np_.arange(n, dtype=np_.float64), arr
    if arr.ndim == 2 and arr.shape[1] == 2:
        return arr[:, 0], arr[:, 1]
    return None, None


_GRID_EXTENT_CACHE: dict = {}
_GRID_EXTENT_CACHE_LIMIT = 32


def _seq_len(value) -> int:
    """序列长度，非序列 / 无长度返回 0。

    **别写 ``len(v or ())``**：``v`` 是裸 ndarray 时 ``or`` 会对它求真值，
    numpy 抛 ``ValueError: The truth value of an array with more than one
    element is ambiguous``。这条路径的后果特别隐蔽 —— 异常被 ``_paint_series``
    的 ``warn_once`` 吞掉（且去重后只报一次），表现为 **bar / candlestick /
    boxplot 一根都不画、没有任何报错**。而「可直接传 numpy 数组」是本模块
    明文承诺的用法（``data`` 模块 docstring），短数组（< 256）不包装成
    ``ElaNumericBuffer``，所以裸 ndarray 确实会走到这里。
    """
    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return 0


def _grid_value_extent(
    chart, axis_kind: str = "y", axis_index: int = 0, grid_index: int = None
):
    """grid 数值轴真实范围（类型感知）：stack 柱按堆叠和。返回 (dmin, dmax) 或 None。

    带缓存（见 ``_GRID_EXTENT_CACHE``）：逐系列 ``layout`` 都会调它，
    百万点下每次全量遍历会让布局时间放大一个数量级。``axis_kind`` /
    ``axis_index`` 只筛选**哪些系列**参与（多 y 轴时副轴不能污染主轴范围）。
    """
    opts = _grid_series_opts(chart, axis_kind, axis_index, grid_index)
    key = (
        axis_kind,
        axis_index,
        grid_index,
        tuple((id(s), id(s.get("data")), _seq_len(s.get("data"))) for s in opts),
    )
    hit = _GRID_EXTENT_CACHE.get(key)
    # 命中时复核 series 对象仍是同一批（key 里只有 id，靠强引用 + is 兜底）
    if hit is not None:
        cached_ext, cached_opts = hit
        if len(cached_opts) == len(opts) and all(
            a is b for a, b in zip(cached_opts, opts)
        ):
            return cached_ext
    ext = _grid_value_extent_uncached(chart, opts)
    if len(_GRID_EXTENT_CACHE) >= _GRID_EXTENT_CACHE_LIMIT:
        _GRID_EXTENT_CACHE.clear()
    _GRID_EXTENT_CACHE[key] = (ext, tuple(opts))
    return ext


def _grid_value_extent_uncached(chart, opts) -> tuple:
    """``_grid_value_extent`` 的实际计算（无缓存）。"""
    dmin = None
    dmax = None

    def feed(v):
        """喂一个候选极值；**非有限值必须拒收**（后果见 AGENTS.md「charts」）。"""
        nonlocal dmin, dmax
        if v is None or not math.isfinite(v):
            return
        dmin = v if dmin is None else min(dmin, v)
        dmax = v if dmax is None else max(dmax, v)

    stack_pos = {}
    stack_neg = {}
    for s in opts:
        stype = str(s.get("type") or "line")
        data = s.get("data")
        if data is None:
            data = []
        if stype == "bar" and s.get("stack"):
            key = str(s.get("stack"))
            for i, item in enumerate(data):
                _, y = parseDataPoint(item, i)
                if y is None:
                    continue
                if y >= 0:
                    stack_pos[(key, i)] = stack_pos.get((key, i), 0.0) + y
                else:
                    stack_neg[(key, i)] = stack_neg.get((key, i), 0.0) + y
        elif stype == "candlestick":
            for item in data:
                nums = _datum_list(item)
                if nums and len(nums) >= 4:
                    feed(min(nums[2], nums[0], nums[1]))
                    feed(max(nums[3], nums[0], nums[1]))
        elif stype == "boxplot":
            for item in data:
                nums = _datum_list(item)
                if nums and len(nums) >= 5:
                    feed(nums[0])
                    feed(nums[4])
        else:
            for i, item in enumerate(data):
                _, y = parseDataPoint(item, i)
                feed(y)
    for v in stack_pos.values():
        feed(v)
    for v in stack_neg.values():
        feed(v)
    if dmin is None:
        return None
    return dmin, dmax


def _axis_label(axis, x):
    """类别轴标签（x 为类别名或下标）；数值轴退回 formatValue。"""
    if axis is not None and axis.type == "category" and axis.categories:
        idx = axis.categoryIndex(x)
        if 0 <= idx < len(axis.categories):
            return axis.categories[idx]
        all_cats = getattr(axis, "_all_categories", None) or []
        if 0 <= idx < len(all_cats):
            return all_cats[idx]
    return formatValue(x)


def _fix_value_axis(axis, chart, series_opt=None, axis_kind: str = "y"):
    """按 ``_grid_value_extent`` 重设数值轴范围（category 轴自动跳过）。"""
    if axis is None or axis.type not in ("value", "log"):
        return
    s = series_opt if isinstance(series_opt, dict) else {}
    key = "xAxisIndex" if axis_kind == "x" else "yAxisIndex"
    try:
        axis_index = int(s.get(key, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        axis_index = 0
    ext = _grid_value_extent(
        chart, axis_kind, axis_index, getattr(axis, "grid_index", None)
    )
    if ext is not None:
        lo, hi = ext
        if axis.type == "log":
            # log 轴只接受正值；全非正时保持 setSeries 给的默认范围。
            if lo <= 0.0 or hi <= 0.0:
                return
        axis.setExtent(lo, hi)
