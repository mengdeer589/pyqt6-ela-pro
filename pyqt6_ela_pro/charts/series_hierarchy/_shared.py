"""层级 / 关系系列的共享解析与几何工具。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import (
    QColor,
)

from .._tokens import T
from .._utils import _series_palette_color, dist_point_segment
from .._utils import merged_text_style, text_italic, text_weight
from .._utils import to_float as _to_float
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


def _text_color(key, chart):
    return QColor(T(key, chart))


def _label_font(series, style=None):
    """层级 / 关系类系列的标签字体（样式 dict 统一解析 + 顶层兜底）。"""
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


def _parse_named_values(data):
    """解析 [{"name","value"}] / 数值 → ``[(原下标, name, value)]``。

    保留负值与原始下标：删负值会让后续项的 itemStyle / dataIndex 整体前移。
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
        "style",
        "path",
        "item",
    )

    def __init__(self, name, value=0.0, depth=0):
        self.name = name
        self.value = value
        self.children = []
        self.depth = depth
        self.color = None
        self.style = {}
        self.item = None
        self.a0 = 0.0  # sunburst 角区间
        self.a1 = 0.0
        self.level = 0  # sunburst 环层
        self.rect = QRectF()  # treemap 矩形
        self.x = 0.0  # tree 布局坐标（逻辑）
        self.y = 0.0


def _build_hierarchy(data):
    """[{"name","value","children"}] → [_HNode] 根列表；value 自动累计子级。"""
    roots = []
    visiting = set()

    def build(item, depth):
        if not isinstance(item, dict) or depth > 1000 or id(item) in visiting:
            return None
        visiting.add(id(item))
        node = _HNode(str(item.get("name") or ""), 0.0, depth)
        node.item = item
        style = item.get("itemStyle")
        if isinstance(style, dict):
            node.style = style
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
        visiting.discard(id(item))
        return node

    for item in data or []:
        node = build(item, 0)
        if node is not None:
            roots.append(node)
    return roots


def _assign_branch_colors(chart, roots):
    """分支取调色板色；子级同色相逐级提亮。

    单根数据常写成「包装根 → 多个分支」，只按根取色会让整图只有一种颜色，
    因此先下潜到第一个能分出支的层级（多根时就是根本身）。
    """
    branches = roots
    while len(branches) == 1 and branches[0].children:
        branches = branches[0].children

    def paint_branch(node, color):
        node.color = color
        lighter = color.lighter(115)
        for child in node.children:
            paint_branch(child, lighter)

    for i, node in enumerate(branches):
        paint_branch(node, _series_palette_color(chart, i))

    base = branches[0].color if branches else None
    branch_ids = {id(node) for node in branches}

    def paint_wrapper(node):
        if id(node) in branch_ids:
            return
        node.color = base
        for child in node.children:
            paint_wrapper(child)

    for root in roots:
        paint_wrapper(root)


def _node_style(node):
    return node.style if isinstance(node.style, dict) else {}


def _node_color(series, node):
    """节点色：数据项 ``itemStyle.color`` → 系列 ``itemStyle.color`` → 分支色。"""
    raw = _node_style(node).get("color")
    if isinstance(raw, str) and raw:
        color = series.resolveColor(raw)
        if color.isValid():
            return color
    visual = series.visualColorForValue(node.value)
    if visual is not None:
        return visual
    return series.itemColor(default=node.color)


def _node_label_color(series, node, fill):
    """节点标签色：数据项 ``label.color`` → 系列显式色 → 按填充选黑白。"""
    item = getattr(node, "item", None)
    label = item.get("label") if isinstance(item, dict) else None
    if isinstance(label, dict):
        raw = label.get("color")
        if isinstance(raw, str) and raw:
            color = series.resolveColor(raw)
            if color.isValid():
                return color
    return series.contrastLabelColor(fill, None)


def _node_emphasis_color(series, node):
    """节点 hover 强调色：数据项 ``emphasis.itemStyle.color`` → 系列级。"""
    item = getattr(node, "item", None)
    emphasis = item.get("emphasis") if isinstance(item, dict) else None
    style = emphasis.get("itemStyle") if isinstance(emphasis, dict) else None
    if isinstance(style, dict):
        raw = style.get("color")
        if isinstance(raw, str) and raw:
            color = series.resolveColor(raw)
            if color.isValid():
                return color
    return series.emphasisColor()


def _node_opacity(series, node):
    raw = _node_style(node).get("opacity")
    if raw is None:
        return series.itemOpacity()
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError, OverflowError):
        return series.itemOpacity()


def _node_border(series, node):
    """节点描边 ``(QColor | None, width)``：数据项覆盖系列 ``itemStyle``。"""
    color, width = series.itemBorder()
    style = _node_style(node)
    raw = style.get("borderColor")
    if isinstance(raw, str) and raw:
        candidate = series.resolveColor(raw)
        if candidate.isValid():
            color = candidate
    if "borderWidth" in style:
        width = max(0.0, _to_float(style.get("borderWidth"), width))
    return color, width


def _flatten_hierarchy(roots) -> list:
    """层级根 → 先序扁平节点列表（与 tree / sunburst 的 style_index 对齐）。"""
    out = []

    def walk(node):
        out.append(node)
        for child in node.children:
            walk(child)

    for root in roots or []:
        walk(root)
    return out


def _hierarchy_nodes(renderer) -> list:
    """当前渲染节点（已布局用 ``style_index``；未布局回退原始先序）。"""
    nodes = getattr(renderer, "_nodes", None) or []
    out = []
    for entry in nodes:
        node = entry[0] if isinstance(entry, tuple) else entry
        if getattr(node, "style_index", None) is not None:
            out.append(node)
    if out:
        return out
    return _flatten_hierarchy(_build_hierarchy(renderer.data()))


def _hierarchy_node_at(renderer, index: int):
    if not isinstance(index, int) or isinstance(index, bool):
        return None
    for node in _hierarchy_nodes(renderer):
        if getattr(node, "style_index", None) == index:
            return node
    nodes = _hierarchy_nodes(renderer)
    return nodes[index] if 0 <= index < len(nodes) else None


def _hierarchy_value(renderer, index: int):
    node = _hierarchy_node_at(renderer, index)
    if node is None:
        return None
    return {
        "name": node.name,
        "value": node.value,
        "color": _node_color(renderer, node),
        "series": renderer.name,
        "dataIndex": index,
    }


def _hierarchy_name_at(renderer, index: int) -> str:
    node = _hierarchy_node_at(renderer, index)
    return node.name if node is not None else ""


def _hierarchy_item_count(renderer) -> int:
    return len(_hierarchy_nodes(renderer))


def _hierarchy_selected_seeds(renderer) -> set:
    seeds = set()
    for index, node in enumerate(_hierarchy_nodes(renderer)):
        item = getattr(node, "item", None)
        if isinstance(item, dict) and item.get("selected") is True:
            seeds.add(index)
    return seeds


def _squarify(items, rect):
    """squarified 布局：items [(key, value)] 按面积填充 rect，返回 {key: QRectF}。"""
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
