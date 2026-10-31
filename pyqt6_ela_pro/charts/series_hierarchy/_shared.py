"""层级 / 关系系列的共享解析与几何工具。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import (
    QColor,
)

from .._tokens import T
from .._utils import dist_point_segment
from .._utils import merged_text_style, text_italic, text_weight
from .._utils import to_float as _to_float
from .._utils import parse_color
from ..axes import chartFont


def _parse_pct(v, base, default=0.0):
    """解析像素值 / 百分比字符串（"40%" → base*0.4）。"""
    if isinstance(v, str) and v.strip().endswith("%"):
        try:
            return base * float(v.strip()[:-1]) / 100.0
        except (TypeError, ValueError, OverflowError):
            return float(default)
    if v is None:
        return float(default)
    return _to_float(v, default)


def _text_color(key="color.text.primary"):
    return QColor(T(key))


def _label_font(series, style=None):
    """层级 / 关系类系列的标签字体（``fontSize`` / ``fontWeight`` + 顶层兜底）。

    这些系列的标签样式不以 ``label`` 为唯一来源（树图 / 雷达 / 仪表各有自己的
    ``label`` / ``title`` / ``axisName`` 子 option），所以把**实际使用的样式
    dict** 传进来统一解析。
    """
    merged = merged_text_style(
        getattr(series, "chart", None), style if isinstance(style, dict) else {}
    )
    px = merged.get("fontSize")
    return chartFont(
        px if px else T("font.xs"),
        text_weight(merged.get("fontWeight")),
        merged.get("fontFamily"),
        text_italic(merged.get("fontStyle")),
    )


def _series_palette_color(chart, index):
    """按序号取全局调色板颜色（越界循环）。"""
    pal = chart.palette()
    if not pal:
        return QColor(T("color.primary"))
    return parse_color(pal[index % len(pal)])


def _parse_named_values(data):
    """解析 [{"name","value"}] / 数值 → ``[(原下标, name, value)]``。

    **保留负值与原始下标**：饼图 / 漏斗里负值只应得到 0 角度，不能整条删掉
    （删掉会让后续项的 ``itemStyle`` / ``dataIndex`` 整体前移，红色画到别的
    数据上）；仪表盘量程含负值时负值更是正常业务数据。
    """
    out = []
    for index, item in enumerate(data or []):
        if isinstance(item, dict):
            name = str(item.get("name") or "")
            v = item.get("value")
        else:
            name, v = "", item
        fv = _to_float(v, None) if not isinstance(v, bool) else None
        if fv is None:
            continue
        out.append((index, name, fv))
    return out


def _dist(a, b):
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def _dist_to_polygon_edge(p, pts) -> float:
    """点到闭合折线（多边形边界）的最近距离（雷达命中判定用）。"""
    n = len(pts)
    if n == 0:
        return float("inf")
    if n == 1:
        return _dist(p, pts[0])
    return min(dist_point_segment(p, pts[i], pts[(i + 1) % n]) for i in range(n))


class _HNode:
    """层级数据节点：name / value（含子级合计）/ children / depth / 颜色。"""

    __slots__ = (
        "name",
        "value",
        "children",
        "depth",
        "color",
        "a0",
        "a1",
        "level",
        "rect",
        "x",
        "y",
        "style_index",
        "path",
    )

    def __init__(self, name, value=0.0, depth=0):
        self.name = name
        self.value = value
        self.children = []
        self.depth = depth
        self.color = None
        self.a0 = 0.0  # sunburst 角区间
        self.a1 = 0.0
        self.level = 0  # sunburst 环层
        self.rect = QRectF()  # treemap 矩形
        self.x = 0.0  # tree 布局坐标（逻辑）
        self.y = 0.0


def _build_hierarchy(data):
    """[{"name","value","children"}] → [_HNode] 根列表；value 自动累计子级。"""
    roots = []

    def build(item, depth):
        if not isinstance(item, dict):
            return None
        node = _HNode(str(item.get("name") or ""), 0.0, depth)
        raw = item.get("value")
        own = _to_float(raw, 0.0) if raw is not None else 0.0
        for child in item.get("children") or []:
            c = build(child, depth + 1)
            if c is not None:
                node.children.append(c)
        node.value = (
            max(0.0, own) if raw is not None else sum(c.value for c in node.children)
        )
        if raw is not None and node.children:
            node.value = max(0.0, own)
        if node.value <= 0 and node.children:
            node.value = sum(c.value for c in node.children)
        return node

    for item in data or []:
        node = build(item, 0)
        if node is not None:
            roots.append(node)
    return roots


def _assign_branch_colors(chart, roots):
    """顶层分支取调色板色；子级同色相逐级递减明度。"""
    for i, root in enumerate(roots):
        base = _series_palette_color(chart, i)

        def rec(node, color):
            node.color = color
            lighter = color.lighter(115)
            for c in node.children:
                rec(c, lighter)

        rec(root, base)


def _squarify(items, rect):
    """squarified 布局：items [(key, value)] 按面积填充 rect。

    返回 {key: QRectF}。经典 Bruls 算法：按值降序沿短边分行，
    行内保持长宽比尽量接近 1。
    """
    result = {}
    if not items or rect.width() <= 0 or rect.height() <= 0:
        return result
    total = sum(v for _, v in items)
    if total <= 0:
        return result
    scale = rect.width() * rect.height() / total
    remaining = [
        (k, v * scale)
        for k, v in sorted(items, key=lambda kv: kv[1], reverse=True)
        if v > 0
    ]
    x, y = rect.left(), rect.top()
    w, h = rect.width(), rect.height()

    def worst(row, side):
        areas = [a for _, a in row]
        s = sum(areas)
        if s <= 0 or side <= 0:
            return float("inf")
        mx, mn = max(areas), min(areas)
        return max(side * side * mx / (s * s), s * s / (side * side * mn))

    while remaining:
        side = min(w, h)
        row = [remaining.pop(0)]
        while remaining:
            cand = row + [remaining[0]]
            if worst(cand, side) <= worst(row, side):
                row.append(remaining.pop(0))
            else:
                break
        row_area = sum(a for _, a in row)
        if w >= h:
            col_w = row_area / h if h > 0 else 0.0
            cy = y
            for key, area in row:
                rh = area / col_w if col_w > 0 else 0.0
                result[key] = QRectF(x, cy, col_w, rh)
                cy += rh
            x += col_w
            w -= col_w
        else:
            row_h = row_area / w if w > 0 else 0.0
            cx = x
            for key, area in row:
                rw = area / row_h if row_h > 0 else 0.0
                result[key] = QRectF(cx, y, rw, row_h)
                cx += rw
            y += row_h
            h -= row_h
    return result
