"""坐标系共享的数值 / 刻度 / 文本工具。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math
import time
from datetime import date, datetime, timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPen

from ..._internal import system_cjk_font_family
from .._tokens import FONT_FAMILIES, T
from .._utils import single_font_family
from .._utils import to_float as _utils_to_float
from .._utils import resolve_color_option

_EXTENT_CACHE: dict = {}
_EXTENT_CACHE_LIMIT = 16


def clearExtentCache() -> None:
    """丢弃全局数值范围缓存（销毁图表 / 大规模 clear 后释放数据引用）。"""
    _EXTENT_CACHE.clear()
_MAX_TICKS = 2000
_MAX_SEGMENTS = 200
_MAX_DATE_YEAR = 9999
_TIME_EPOCH = datetime(1970, 1, 1)
_TIME_LOCAL_OFFSET_MS = time.timezone * 1000.0
#: ``datetime`` 可表示范围（毫秒时间戳）：越界（如误用纳秒）直接丢弃，
#: 否则 ``timedelta`` 会 OverflowError 并从 setOption 穿出。
_MIN_TIMESTAMP_MS = -62135596800000.0
_MAX_TIMESTAMP_MS = 253402300799999.0


def _dt_to_ms(dt: datetime) -> float:
    """本地朴素 datetime → 毫秒时间戳（不受平台 timestamp 范围限制）。"""
    return (dt - _TIME_EPOCH).total_seconds() * 1000.0 + _TIME_LOCAL_OFFSET_MS


def _ms_to_dt(ms) -> datetime:
    """毫秒时间戳 → 本地朴素 datetime（越界夹到 datetime 支持范围）。"""
    try:
        return _TIME_EPOCH + timedelta(milliseconds=float(ms) - _TIME_LOCAL_OFFSET_MS)
    except (OverflowError, ValueError):
        return datetime.max if float(ms) > 0 else datetime.min


def _to_timestamp(value):
    """日期 / ISO 字符串 / 数字 → 毫秒时间戳（失败 None）；数字按毫秒处理。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if not math.isfinite(v) or v < _MIN_TIMESTAMP_MS or v > _MAX_TIMESTAMP_MS:
            return None
        return v
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone().replace(tzinfo=None)
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
            parsed = datetime.fromisoformat(text.replace("/", "-"))
        except (TypeError, ValueError, OverflowError):
            return None
        return _to_timestamp(parsed)
    return None


def chartFont(
    px: int = None,
    weight: int = None,
    family: str = None,
    italic: bool = False,
) -> QFont:
    """构造图表用字体（默认 ``FONT_FAMILIES``；中文系统单族雅黑）。

    ``family`` 只取单个族名；``italic`` 对应 ``fontStyle: "italic" | "oblique"``。
    """
    font = QFont()
    single = single_font_family(family)
    if single:
        font.setFamilies([single])
    else:
        cjk_family = system_cjk_font_family()
        font.setFamilies([cjk_family] if cjk_family else list(FONT_FAMILIES))
    font.setStyleHint(QFont.StyleHint.SansSerif)
    # 外部 JSON 的 fontSize 可能是 "12.5" / "12px"，裸 int() 会抛 ValueError。
    px_value = _to_float(px, T("font.xs"))
    if px_value is None or not math.isfinite(px_value) or px_value <= 0:
        px_value = float(T("font.xs"))
    # 上限保护：QFont.setPixelSize 超过 int32 会抛 OverflowError，从 resize /
    # paint 回调穿出就是 0xC0000409；4096 已远超任何可读字号。
    px_value = min(px_value, 4096.0)
    font.setPixelSize(max(1, int(round(px_value))))
    if weight:
        try:
            font.setWeight(QFont.Weight(int(weight)))
        except (TypeError, ValueError, OverflowError):
            pass
    if italic:
        font.setItalic(True)
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
        # 小数位按量级自适应、封顶 8 位（再多是浮点尾数）：固定两位会把 1e-3
        # 量级的刻度标签全变成 "0"，负小数还会给出 "-0"。
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
    # 端点有限不代表差值有限：±1e308 的差溢出成 inf，随后 math.floor(inf) 抛 OverflowError。
    if not math.isfinite(span) or span <= 0.0:
        vmin, vmax = 0.0, 1.0
        span = 1.0
    step0 = span / segments
    if not math.isfinite(step0) or step0 <= 0.0:
        vmin, vmax = 0.0, 1.0
        span = 1.0
        step0 = 1.0 / segments
    mag = 10 ** math.floor(math.log10(step0))
    if not math.isfinite(mag) or mag <= 0.0:
        # 次正规数下 ``10 ** -324`` 下溢成 0，随后除法 ZeroDivisionError；
        # 极端量级退回等分刻度（有刻度可读总比崩掉 setOption 好）。
        ticks = [vmin + i * span / segments for i in range(segments + 1)]
        return vmin, vmax, ticks
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
    # 刻度数硬上限：step 极小时 n 会膨胀到百万级，逐个 append + 每根刻度画线
    # 画标签时单帧可达 35 秒，宁可少几根网格线也不能毁掉整帧。
    if n > _MAX_TICKS:
        return _clamp_tick_count(nice_min, nice_max, step, _MAX_TICKS)
    ticks = []
    for i in range(n + 1):
        t = nice_min + i * step
        ticks.append(0.0 if abs(t) < step * 1e-9 else t)
    return nice_min, nice_max, ticks


def _clamp_tick_count(nice_min, nice_max, step, limit):
    """刻度过多时改用放大 step 的等分刻度（端点保持不变，刻度数 ≤ ``limit + 1``）。"""
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
    scale = 10.0**exp
    if not math.isfinite(scale) or scale == 0.0:
        return f"{v:g}"
    mant = v / scale
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
    # 先按数量级上限判断，别先物化上千万个幂值再截断。
    if e1 - e0 > _MAX_TICKS:
        return [vmin, vmax]
    ticks = [base**e for e in range(e0, e1 + 1)]
    # 不足三个数量级时只有 2~3 个幂次标签太稀，补 2/5 子刻度。
    if e1 - e0 <= 2 and abs(base - 10.0) < 1e-9:
        ticks = [m * (10.0**e) for e in range(e0, e1 + 1) for m in (1, 2, 5)]
    ticks = [t for t in ticks if vmin * (1.0 - 1e-9) <= t <= vmax * (1.0 + 1e-9)]
    if len(ticks) < 2:
        ticks = [vmin, vmax]
    limit = max(2, min(int(segments) + 1, _MAX_TICKS))
    if len(ticks) > limit:
        # 1/2/5 混合刻度按步长抽样会得到 1,5,20,100 这种不等距序列；
        # 超限时退回纯数量级刻度，标签少但间隔均匀。
        powers = [
            base**e
            for e in range(e0, e1 + 1)
            if vmin * (1.0 - 1e-9) <= base**e <= vmax * (1.0 + 1e-9)
        ]
        if len(powers) >= 2:
            ticks = powers
        else:
            step = max(1, int(math.ceil(len(ticks) / float(limit))))
            ticks = ticks[::step]
        if ticks[-1] != vmax:
            ticks.append(vmax)
    return ticks


def _iter_data_values(data):
    """从系列 data 中迭代全部**有限**数值（number / [x, y] / {"value": v}）。
    滤 NaN / inf 的原因：调用方用 ``min()`` / ``max()`` 归约，而 ``min()`` 遇
    NaN 的结果是顺序相关的（``[1, 2, nan, 5]`` 会得 0..1 或 0..5）。
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


def _to_float(v, default=0.0) -> float:
    """数值轴映射用宽松转换（NaN/Inf 过滤，防止污染 QPainter 坐标）。"""
    return _utils_to_float(v, default)


def _opt_bound(v):
    """解析轴 min/max 选项：合法数值返回 float，非法返回 None（视为未设置）。"""
    try:
        return _utils_to_float(v, None)
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_margin(v, default):
    """解析 grid / singleAxis 边距：数值 px 或百分比字符串（"10%"）→ ``(is_pct, value)``。

    非法输入（含非有限值）降级为 default；``default=None`` 表示「未设置」。
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


_PEN_STYLES = {
    "solid": Qt.PenStyle.SolidLine,
    "dashed": Qt.PenStyle.DashLine,
    "dash": Qt.PenStyle.DashLine,
    "dotted": Qt.PenStyle.DotLine,
    "dot": Qt.PenStyle.DotLine,
}


def _matrix_shape(data):
    """2D 矩阵 / 3D RGB(A) 数据的 ``(rows, cols)``；非法 / 锯齿形状返回 ``None``。"""
    try:
        rows = len(data)
    except TypeError:
        return None
    if rows <= 0:
        return None
    try:
        first = data[0]
        cols = len(first)
    except (TypeError, IndexError, KeyError):
        return None
    if cols <= 0:
        return None
    for index in range(1, rows):
        try:
            if len(data[index]) != cols:
                return None
        except (TypeError, IndexError, KeyError):
            return None
    return rows, cols


def _series_image_extent(series_opt: dict):
    """``type="image"`` 系列的数据范围 ``(x0, x1, y0, y1)``；非法数据返回 ``None``。

    默认按像素中心取 ``[-0.5, N-0.5, -0.5, M-0.5]``（matplotlib imshow 口径）。
    """
    shape = _matrix_shape(series_opt.get("data"))
    if shape is None:
        return None
    rows, cols = shape
    raw = series_opt.get("extent")
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        values = []
        for item in raw:
            try:
                value = float(item)
            except (TypeError, ValueError, OverflowError):
                values = None
                break
            if not math.isfinite(value):
                values = None
                break
            values.append(value)
        if values and values[0] != values[1] and values[2] != values[3]:
            return tuple(values)
    return (-0.5, cols - 0.5, -0.5, rows - 0.5)


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


def _line_pen(opt: dict, default_color, default_width=1.0, chart=None) -> QPen:
    """解析 ``{lineStyle: {color, width, type}}`` → QPen。"""
    style = opt.get("lineStyle")
    style = style if isinstance(style, dict) else {}
    color = resolve_color_option(style.get("color"), chart, default_color)
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


def _datum_y(item):
    """取数据项的 y 值（number / [x, y] / {"value": ...}）；**非有限值返回 None**。"""
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


def _gantt_bounds(item):
    """甘特条目 → ``(start, end)`` 毫秒时间戳 / 数值；非法返回 ``None``。

    支持 ``{"name","start","end"}``、``{"value":[start,end,...]}``、
    ``[start, end, ...]``；缺 ``end`` 时按里程碑处理（``end = start``）。
    """
    if isinstance(item, dict):
        if any(key in item for key in ("start", "begin", "end", "finish")):
            start_raw = item.get("start", item.get("begin"))
            end_raw = item.get("end", item.get("finish"))
        else:
            value = item.get("value")
            if isinstance(value, (list, tuple)):
                start_raw = value[0] if value else None
                end_raw = value[1] if len(value) >= 2 else None
            else:
                start_raw = value
                end_raw = None
    elif isinstance(item, (list, tuple)):
        start_raw = item[0] if item else None
        end_raw = item[1] if len(item) >= 2 else None
    else:
        return None
    start = _to_timestamp(start_raw)
    end = _to_timestamp(end_raw) if end_raw is not None else start
    if start is None or end is None:
        return None
    if end < start:
        start, end = end, start
    return start, end


def _gantt_progress(item):
    """甘特条目进度 0~1（缺省 ``None``；大于 1 且 ≤100 按百分比）。"""
    raw = None
    if isinstance(item, dict):
        raw = item.get("progress")
        value = item.get("value")
        if raw is None and isinstance(value, (list, tuple)) and len(value) >= 3:
            raw = value[2]
    elif isinstance(item, (list, tuple)) and len(item) >= 3:
        raw = item[2]
    progress = _to_float(raw, None)
    if progress is None:
        return None
    if 1.0 < progress <= 100.0:
        progress /= 100.0
    return max(0.0, min(1.0, progress))


def _gantt_baseline(item):
    """甘特条目基线 → ``(start, end)``；支持 ``{start,end}`` / ``[start,end]``。"""
    if not isinstance(item, dict):
        return None
    raw = item.get("baseline")
    if isinstance(raw, dict):
        start_raw = raw.get("start", raw.get("begin"))
        end_raw = raw.get("end", raw.get("finish"))
    elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
        start_raw, end_raw = raw[0], raw[1]
    else:
        return None
    start = _to_timestamp(start_raw)
    end = _to_timestamp(end_raw) if end_raw is not None else start
    if start is None or end is None:
        return None
    if end < start:
        start, end = end, start
    return start, end


def _gantt_deadline(item):
    """甘特条目截止日期 → 毫秒时间戳 / 数值；缺省返回 ``None``。"""
    if not isinstance(item, dict):
        return None
    raw = item.get("deadline")
    return None if raw is None else _to_timestamp(raw)


def _gantt_span_bounds(item, series_opt=None):
    """甘特条目在 x 轴上的完整跨度：任务、基线、截止日期三者并集。"""
    values = []
    bounds = _gantt_bounds(item)
    if bounds is not None:
        values.extend(bounds)
    include_baseline = True
    include_deadline = True
    if isinstance(series_opt, dict):
        raw = series_opt.get("baseline")
        if raw is False or (isinstance(raw, dict) and raw.get("show") is False):
            include_baseline = False
        raw = series_opt.get("deadline")
        if raw is False or (isinstance(raw, dict) and raw.get("show") is False):
            include_deadline = False
    if include_baseline:
        baseline = _gantt_baseline(item)
        if baseline is not None:
            values.extend(baseline)
    if include_deadline:
        deadline = _gantt_deadline(item)
        if deadline is not None:
            values.append(deadline)
    if not values:
        return None
    return min(values), max(values)


def _gantt_item_name(item, index: int):
    """甘特条目名 → ``(name, 是否显式给了 name)``。"""
    if isinstance(item, dict):
        name = item.get("name", item.get("title"))
        if name is not None and str(name).strip():
            return str(name), True
    return str(index), False


def _gantt_display_rows(series_opt: dict) -> list:
    """甘特有效任务行（跳过非法 start / end）；``named`` 表示是否显式给 name。"""
    if not isinstance(series_opt, dict):
        return []
    data = series_opt.get("data")
    if not isinstance(data, (list, tuple)) or not data:
        return []
    rows = []
    for index, item in enumerate(data):
        if _gantt_bounds(item) is None:
            continue
        name, named = _gantt_item_name(item, index)
        rows.append({"index": index, "name": name, "named": named})
    return rows


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
