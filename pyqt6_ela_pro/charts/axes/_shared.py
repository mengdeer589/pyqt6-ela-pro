"""坐标系共享的数值 / 刻度 / 文本工具。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math
import time
from datetime import datetime, timedelta

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPen

from ..._internal import system_cjk_font_family
from .._tokens import FONT_FAMILIES, T
from .._utils import to_float as _utils_to_float, warn_once
from .._utils import parse_color

_EXTENT_CACHE: dict = {}
_EXTENT_CACHE_LIMIT = 64
_MAX_TICKS = 2000
_MAX_SEGMENTS = 200
_MAX_DATE_YEAR = 9999
_TIME_EPOCH = datetime(1970, 1, 1)
_TIME_LOCAL_OFFSET_MS = time.timezone * 1000.0


def _dt_to_ms(dt: datetime) -> float:
    """本地朴素 datetime → 毫秒时间戳（不受平台 timestamp 范围限制）。"""
    return (dt - _TIME_EPOCH).total_seconds() * 1000.0 + _TIME_LOCAL_OFFSET_MS


def _ms_to_dt(ms) -> datetime:
    """毫秒时间戳 → 本地朴素 datetime（跨 1970 前后 / 9999 年都可用）。"""
    return _TIME_EPOCH + timedelta(milliseconds=float(ms) - _TIME_LOCAL_OFFSET_MS)


def single_font_family(value) -> str:
    """用户给的字体族 → **单个**族名（本库硬约束，见 ``chartFont``）。

    ECharts 的 ``fontFamily`` 允许逗号分隔的回退列表；本库在 Win7 上只能单族
    （多族 = 逐字形族匹配的慢 shaping，且进程级毒化后续文本），所以取第一个，
    其余留一条 ``warn_once``。
    """
    if not isinstance(value, str):
        return ""
    text = value.strip().strip("\'\"").strip()
    if not text:
        return ""
    parts = [p.strip().strip("\'\"") for p in text.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) > 1:
        warn_once(
            "font-family:multiple",
            f"图表只支持单个字体族，已取 {parts[0]!r}（忽略 {len(parts) - 1} 个回退族）",
        )
    return parts[0]


def chartFont(
    px: int = None,
    weight: int = None,
    family: str = None,
    italic: bool = False,
) -> QFont:
    """构造图表用字体（默认 ``FONT_FAMILIES`` / 中文系统单族雅黑）。

    ``family`` 是**单个族名**（逗号列表取第一个）；``italic`` 对应 ECharts
    ``fontStyle: "italic" | "oblique"``。

    中文系统默认收成单族 ``Microsoft YaHei``：多族列表在 Win7 上是慢 shaping
    路径（图表文本逐重绘放大，见「下游项目反馈bug.md」§3），而列表其余族全是
    mac / linux 字体、Windows 上本就轮不到。
    """
    font = QFont()
    single = single_font_family(family)
    if single:
        font.setFamilies([single])
    else:
        cjk_family = system_cjk_font_family()
        font.setFamilies([cjk_family] if cjk_family else list(FONT_FAMILIES))
    font.setStyleHint(QFont.StyleHint.SansSerif)
    # 数值容错：外部 JSON 里 ``fontSize`` 可能是 ``"12.5"`` / ``"12px"``，
    # 直接 ``int(px)`` 会抛 ValueError（层级系列整条 paint 中断 → 静默消失）。
    px_value = _to_float(px, T("font.xs"))
    if px_value is None or not math.isfinite(px_value) or px_value <= 0:
        px_value = float(T("font.xs"))
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
    if not math.isfinite(step0) or step0 <= 0.0:
        vmin, vmax = 0.0, 1.0
        span = 1.0
        step0 = 1.0 / segments
    mag = 10 ** math.floor(math.log10(step0))
    if not math.isfinite(mag) or mag <= 0.0:
        # 次正规数（如 span=2.5e-323）下 ``10 ** -324`` 下溢成 0，随后
        # ``vmin / step`` 直接 ZeroDivisionError。极端量级退回等分刻度，
        # 不做 nice 取整 —— 有刻度可读总比崩掉 setOption 好。
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
    color = parse_color(style.get("color") or default_color)
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
