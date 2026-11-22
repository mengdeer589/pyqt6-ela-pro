"""关系图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)

from .._symbol import drawSymbol
from .._tokens import T
from .._utils import clamp as _clamp
from .._utils import parse_roam as _parse_roam
from .._utils import to_float as _to_float
from .._utils import with_alpha
from ..core import SeriesRenderer
from ._shared import _dist, _label_font, _series_palette_color, _text_color


class GraphSeriesRenderer(SeriesRenderer):
    """关系图（节点 + 边）。
    选项：``data`` / ``nodes`` / ``categories`` / ``links`` / ``layout`` / ``force`` /
    ``label`` / ``symbolSize`` / ``draggable`` / ``roam`` / ``zoom``。
    """

    labelVisibleByDefault = True

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []  # [dict(name,size,pos=QPointF,color)]
        self._edges = []  # [(i, j)]
        self._edge_styles: dict = {}
        self._categories = []
        self._hidden_items: set[str] = set()
        self._drag_index = None
        self._fixed: dict = {}  # 拖拽后的固定位置 {节点下标: QPointF}
        #: 力导布局记忆化：条目 ``(key, positions)``，positions 为归一化坐标。
        self._force_cache = None
        self._pan = QPointF()
        self._pan_start = None
        self._pan_origin = QPointF()
        self._plot = QRectF()
        self._roam = self._parse_roam()
        try:
            self._zoom = max(0.2, min(5.0, float(opt.get("zoom") or 1.0)))
        except (TypeError, ValueError, OverflowError):
            self._zoom = 1.0

    def _parse_roam(self):
        """``roam`` → ``(可缩放, 可平移)``。"""
        return _parse_roam(self.opt.get("roam", False))

    def _parse(self):
        raw_nodes = self.opt.get("data")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raw_nodes = self.opt.get("nodes")
        categories = self.opt.get("categories") or []
        nodes = []
        name_index = {}
        for i, item in enumerate(raw_nodes or []):
            if isinstance(item, dict):
                name = str(item.get("name") or f"node{i}")
                size = item.get("symbolSize")
                category = item.get("category")
                value = item.get("value")
                item_style = self.itemStyleOf(item)
            else:
                name, size, category, item_style = str(item), None, None, {}
                value = None
            nodes.append(
                {
                    "name": name,
                    "value": value,
                    "size": size,
                    "category": category,
                    "itemStyle": item_style,
                    "symbol": item.get("symbol") if isinstance(item, dict) else None,
                    "symbolRotate": item.get("symbolRotate")
                    if isinstance(item, dict)
                    else None,
                    "item": item if isinstance(item, dict) else None,
                }
            )
            name_index.setdefault(name, i)
        edges = []
        edge_styles = {}
        self._parsed_edge_styles = edge_styles

        def idx(ref):
            if isinstance(ref, bool):
                return None
            if isinstance(ref, (int, float)):
                k = int(ref)
                return k if 0 <= k < len(nodes) else None
            return name_index.get(str(ref))

        for item in self.opt.get("links") or []:
            if not isinstance(item, dict):
                continue
            s, t = idx(item.get("source")), idx(item.get("target"))
            if s is None or t is None or s == t:
                continue
            edges.append((s, t))
            style = item.get("lineStyle")
            if isinstance(style, dict):
                edge_styles[(s, t)] = style
        return nodes, edges, categories

    def _category_color(self, category, categories):
        """分类着色：categories[category].itemStyle.color 优先，否则分类下标取色。"""
        if isinstance(category, bool) or category is None:
            return None
        if isinstance(category, (int, float)):
            index = int(category)
        else:
            index = None
            for i, cat in enumerate(categories):
                name = cat.get("name") if isinstance(cat, dict) else cat
                if str(name) == str(category):
                    index = i
                    break
        if index is None or not (0 <= index < len(categories)):
            return None
        cat = categories[index]
        if isinstance(cat, dict):
            item_style = cat.get("itemStyle") or {}
            raw = item_style.get("color")
            if isinstance(raw, str) and raw:
                color = self.resolveColor(raw)
                if color.isValid():
                    return color
        return _series_palette_color(self.chart, index)

    @staticmethod
    def _category_name(category, categories) -> str:
        if category is None or isinstance(category, bool):
            return ""
        if isinstance(category, (int, float)):
            index = int(category)
            if 0 <= index < len(categories):
                cat = categories[index]
                return str(cat.get("name") if isinstance(cat, dict) else cat)
            return ""
        return str(category)

    def legendItems(self) -> list:
        categories = self._categories or self.opt.get("categories") or []
        items = []
        for index, cat in enumerate(categories):
            name = self._category_name(index, categories)
            if not name:
                continue
            color = self._category_color(index, categories)
            if color is not None:
                items.append((name, color))
        return items or super().legendItems()

    def setHiddenItems(self, names) -> None:
        self._hidden_items = {str(name) for name in (names or [])}

    def _category_hidden(self, node) -> bool:
        if not self._hidden_items:
            return False
        name = self._category_name(node.get("category"), self._categories)
        return name in self._hidden_items

    def layout(self, rect: QRectF) -> None:
        self._nodes = []
        self._edges = []
        nodes, edges, categories = self._parse()
        self._categories = list(categories or [])
        self._edge_styles = dict(getattr(self, "_parsed_edge_styles", {}) or {})
        if not nodes:
            return
        n = len(nodes)
        self._edges = edges
        mode = str(self.opt.get("layout") or "force")
        force_opt = dict(self.opt.get("force") or {})
        pad = 30.0
        plot = QRectF(
            rect.left() + pad,
            rect.top() + pad,
            max(20.0, rect.width() - pad * 2),
            max(20.0, rect.height() - pad * 2),
        )
        self._plot = QRectF(plot)
        if mode == "circular":
            positions = []
            cx, cy = plot.center().x(), plot.center().y()
            r = min(plot.width(), plot.height()) / 2
            for i in range(n):
                theta = -math.pi / 2 + i / n * 2 * math.pi
                positions.append([cx + r * math.cos(theta), cy + r * math.sin(theta)])
        else:
            positions = self._force_positions(nodes, edges, force_opt)
        default_size = _to_float(self.opt.get("symbolSize"), 14.0)
        for i, nd in enumerate(nodes):
            size = _to_float(nd["size"], default_size)
            fixed = self._fixed.get(i)
            if fixed is not None:
                pos = QPointF(fixed)
            else:
                # 力导结果是归一化 [0,1] 坐标；circular 分支已是像素坐标。
                if mode == "circular":
                    pos = QPointF(positions[i][0], positions[i][1])
                else:
                    pos = QPointF(
                        plot.left() + positions[i][0] * plot.width(),
                        plot.top() + positions[i][1] * plot.height(),
                    )
            category_color = self._category_color(nd["category"], categories)
            series_color = self.itemStyle().get("color")
            series_color = (
                self.resolveColor(series_color)
                if isinstance(series_color, str) and series_color
                else None
            )
            self._nodes.append(
                {
                    "name": nd["name"],
                    "value": nd.get("value"),
                    "category": nd["category"],
                    "item": nd.get("item") or nd,
                    "symbol": nd.get("symbol"),
                    "symbolRotate": nd.get("symbolRotate"),
                    "size": _clamp(size, 4.0, 60.0),
                    "pos": pos,
                    "color": (
                        category_color
                        or (
                            series_color
                            if series_color and series_color.isValid()
                            else None
                        )
                        or _series_palette_color(self.chart, i)
                    ),
                    "item_style": nd["itemStyle"],
                }
            )

    def _transform(self, pt: QPointF) -> QPointF:
        """布局坐标 → 屏幕坐标（roam 缩放 / 平移）。"""
        if self._zoom == 1.0 and self._pan.isNull():
            return QPointF(pt)
        c = self._plot.center()
        return QPointF(
            c.x() + (pt.x() - c.x()) * self._zoom + self._pan.x(),
            c.y() + (pt.y() - c.y()) * self._zoom + self._pan.y(),
        )

    def _inverse(self, pos: QPointF) -> QPointF:
        """屏幕坐标 → 布局坐标（拖拽时用）。"""
        if self._zoom == 1.0 and self._pan.isNull():
            return QPointF(pos)
        c = self._plot.center()
        return QPointF(
            c.x() + (pos.x() - c.x() - self._pan.x()) / self._zoom,
            c.y() + (pos.y() - c.y() - self._pan.y()) / self._zoom,
        )

    def onMousePress(self, pos: QPointF) -> bool:
        if bool(self.opt.get("draggable", False)):
            for i, nd in enumerate(self._nodes):
                if _dist(pos, self._transform(nd["pos"])) <= max(
                    nd["size"] / 2 + 2, 8.0
                ):
                    self._drag_index = i
                    return True
        if self._roam[1] and not self._plot.isNull() and self._plot.contains(pos):
            self._pan_start = QPointF(pos)
            self._pan_origin = QPointF(self._pan)
            return True
        return False

    def onMouseMove(self, pos: QPointF) -> bool:
        if self._drag_index is not None:
            layout_pos = self._inverse(pos)
            self._fixed[self._drag_index] = layout_pos
            self._nodes[self._drag_index]["pos"] = layout_pos
            # 拖拽改的是渲染器几何，必须 invalidateLayout 让布局与位图缓存一起失效。
            self.chart.invalidateLayout()
            self.chart.update()
            return True
        if self._pan_start is not None:
            # 以本次按下时的原点为基准累加，否则第二次拖动会丢掉上次的平移量。
            self._pan = self._pan_origin + (QPointF(pos) - self._pan_start)
            self.chart.invalidateLayout()  # 同上：pan 改的是绘制变换
            self.chart.update()
            return True
        return False

    def onMouseRelease(self, pos: QPointF) -> bool:
        if self._drag_index is not None:
            layout_pos = self._inverse(pos)
            self._fixed[self._drag_index] = layout_pos
            self._drag_index = None
            return True
        if self._pan_start is not None:
            self._pan_start = None
            return True
        return False

    def onWheel(self, event) -> bool:
        if not self._roam[0]:
            return False
        try:
            pos = event.position()
        except Exception:
            pos = QPointF()
        if self._plot.isNull() or not self._plot.contains(pos):
            return False
        delta = event.angleDelta().y()
        if delta == 0:
            return False
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._zoom = max(0.2, min(5.0, self._zoom * factor))
        self.chart.invalidateLayout()  # zoom 改的是绘制变换
        self.chart.update()
        return True

    def resetRoam(self) -> None:
        """复位 roam 缩放 / 平移（ECharts restore 语义）。"""
        self._pan = QPointF()
        self._pan_start = None
        self._pan_origin = QPointF()
        self._zoom = 1.0
        self.chart.invalidateLayout()
        self.chart.update()

    def resetPositions(self) -> None:
        """清除拖拽固定位置，恢复自动布局。"""
        if self._fixed:
            self._fixed = {}
            self.chart.invalidateLayout()
            self.chart.update()

    def _force_positions(self, nodes, edges, force_opt):
        """力导布局结果（按全部输入记忆化）。
        ``_force_layout`` 是纯函数，但每次 ``_layout_all`` 都会重跑 O(n² × iterations)
        双层循环（400 节点 / 80 轮约 1.8s）。
        """
        seed = int(_to_float(force_opt.get("seed"), 42))
        iterations = max(10, int(_to_float(force_opt.get("iterations"), 80)))
        repulsion = _clamp(_to_float(force_opt.get("repulsion"), 1.0), 0.1, 10.0)
        key = (
            len(nodes),
            tuple(edges),
            seed,
            iterations,
            repulsion,
        )
        hit = self._force_cache
        if hit is not None and hit[0] == key:
            return hit[1]
        positions = self._force_layout(
            nodes, edges, force_opt, seed, iterations, repulsion
        )
        self._force_cache = (key, positions)
        return positions

    def _force_layout(self, nodes, edges, force_opt, seed, iterations, repulsion):
        """Fruchterman-Reingold 简化力导布局（确定性种子，归一化 [0,1] 空间）。"""
        n = len(nodes)
        rng = random.Random(seed)
        pos = [[rng.random(), rng.random()] for _ in range(n)]
        area = 1.0
        k = math.sqrt(area / max(1, n)) * repulsion
        temp = 0.12
        for it in range(iterations):
            disp = [[0.0, 0.0] for _ in range(n)]
            # 斥力（全对）
            for i in range(n):
                for j in range(i + 1, n):
                    dx = pos[i][0] - pos[j][0]
                    dy = pos[i][1] - pos[j][1]
                    d2 = dx * dx + dy * dy
                    d = math.sqrt(d2) if d2 > 1e-9 else 1e-4
                    if d2 <= 1e-9:
                        dx, dy = rng.random() - 0.5, rng.random() - 0.5
                        d = math.hypot(dx, dy) or 1e-4
                    f = k * k / d
                    disp[i][0] += dx / d * f
                    disp[i][1] += dy / d * f
                    disp[j][0] -= dx / d * f
                    disp[j][1] -= dy / d * f
            # 引力（沿边）
            for s, t in edges:
                dx = pos[s][0] - pos[t][0]
                dy = pos[s][1] - pos[t][1]
                d = math.hypot(dx, dy) or 1e-4
                f = d * d / k
                disp[s][0] -= dx / d * f
                disp[s][1] -= dy / d * f
                disp[t][0] += dx / d * f
                disp[t][1] += dy / d * f
            # 向心重力
            for i in range(n):
                disp[i][0] += (0.5 - pos[i][0]) * 0.02
                disp[i][1] += (0.5 - pos[i][1]) * 0.02
            cool = temp * (1.0 - it / iterations)
            for i in range(n):
                d = math.hypot(disp[i][0], disp[i][1])
                if d <= 1e-9:
                    continue
                step = min(d, cool)
                pos[i][0] = _clamp(pos[i][0] + disp[i][0] / d * step, 0.0, 1.0)
                pos[i][1] = _clamp(pos[i][1] + disp[i][1] / d * step, 0.0, 1.0)
        return pos

    def _node_centroid(self):
        """所有节点的质心（动画收缩的锚点）；空节点集返回原点，避免命中路径零除。"""
        n = len(self._nodes)
        if not n:
            return QPointF()
        return QPointF(
            sum(nd["pos"].x() for nd in self._nodes) / n,
            sum(nd["pos"].y() for nd in self._nodes) / n,
        )

    def _animated_points(self, anim_t):
        """动画进度下的屏幕坐标（``paint`` 与 ``hitTest`` 共用同一份插值）。"""
        center = self._node_centroid()
        out = []
        for nd in self._nodes:
            pt = nd["pos"]
            out.append(
                self._transform(
                    QPointF(
                        center.x() + (pt.x() - center.x()) * anim_t,
                        center.y() + (pt.y() - center.y()) * anim_t,
                    )
                )
            )
        return out

    def _paint_edge_symbols(self, p, p0, p1, fill, stroke) -> None:
        """画边两端的 ``edgeSymbol`` / ``edgeSymbolSize``。"""
        raw = self.opt.get("edgeSymbol")
        if raw is None:
            return
        if isinstance(raw, (list, tuple)):
            kinds = [
                str(raw[0] or "none"),
                str(raw[1] if len(raw) > 1 else raw[0] or "none"),
            ]
        else:
            kinds = [str(raw), str(raw)]
        sizes = self.opt.get("edgeSymbolSize", 4)
        if isinstance(sizes, (list, tuple)):
            values = [
                max(0.0, _to_float(sizes[0], 4.0)),
                max(0.0, _to_float(sizes[1] if len(sizes) > 1 else sizes[0], 4.0)),
            ]
        else:
            size = max(0.0, _to_float(sizes, 4.0))
            values = [size, size]
        if not any(kind not in ("", "none") for kind in kinds):
            return
        dx = p1.x() - p0.x()
        dy = p1.y() - p0.y()
        angle = math.degrees(math.atan2(dy, dx)) + 90.0
        p.save()
        p.setPen(QPen(stroke, 1.0))
        p.setBrush(fill)
        for point, kind, size in ((p0, kinds[0], values[0]), (p1, kinds[1], values[1])):
            if kind in ("", "none") or size <= 0:
                continue
            p.save()
            p.translate(point)
            p.rotate(angle)
            drawSymbol(p, kind, QPointF(0.0, 0.0), size)
            p.restore()
        p.restore()

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
        self._label_rects = []
        pts = self._animated_points(anim_t)
        hidden_indices = {
            index
            for index, node in enumerate(self._nodes)
            if self._category_hidden(node)
        }
        # 边
        p.setBrush(Qt.BrushStyle.NoBrush)
        line_opt = self.opt.get("lineStyle")
        line_opt = line_opt if isinstance(line_opt, dict) else {}
        default_edge = _text_color("color.border.strong", self.chart)
        for s, t in self._edges:
            if s in hidden_indices or t in hidden_indices:
                continue
            if not (0 <= s < len(pts) and 0 <= t < len(pts)):
                continue
            style = dict(line_opt)
            style.update(self._edge_styles.get((s, t), {}))
            raw = style.get("color")
            if raw == "source":
                color = self.resolveColor(self._nodes[s]["color"])
            elif raw == "target":
                color = self.resolveColor(self._nodes[t]["color"])
            else:
                color = self.resolveColor(raw, default_edge)
            width = max(0.5, _to_float(style.get("width"), 1.2))
            opacity = _clamp(_to_float(style.get("opacity"), 160 / 255.0), 0.0, 1.0)
            p.setPen(QPen(with_alpha(color, int(255 * opacity)), width))
            curveness = _to_float(style.get("curveness"), 0.0)
            if abs(curveness) > 1e-6:
                p0, p1 = pts[s], pts[t]
                mx, my = (p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2
                dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
                path = QPainterPath(p0)
                path.quadTo(QPointF(mx - dy * curveness, my + dx * curveness), p1)
                p.drawPath(path)
            else:
                p0, p1 = pts[s], pts[t]
                p.drawLine(p0, p1)
            self._paint_edge_symbols(
                p, p0, p1, color, with_alpha(color, int(255 * opacity))
            )
        # 节点 + 标签
        legend_hover = self.chart._legend_hover
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        c_label = self.labelColor()
        font = _label_font(self, label_opt)
        p.setFont(font)
        fm = QFontMetricsF(font)
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        for i, (nd, pt) in enumerate(zip(self._nodes, pts)):
            if i in hidden_indices:
                continue
            r = nd["size"] / 2
            style = nd.get("item_style") or {}
            raw = style.get("color")
            color = (
                self.resolveColor(raw)
                if isinstance(raw, str) and raw
                else (self.visualColor(i) or self.resolveColor(nd["color"]))
            )
            alpha = self.itemOpacity(i)
            border_color, border_w = self.itemBorder(i)
            if border_color is None or border_w <= 0:
                border_color = QColor(T("color.bg.elevated", self.chart))
                border_w = 1.5
            hover_for_state = i if i == self._drag_index else hovered
            color, alpha, border_color, border_w = self.stateStyle(
                i, hover_for_state, color, alpha, border_color, border_w
            )
            if (
                legend_hover is not None
                and self._category_name(nd.get("category"), self._categories)
                == legend_hover
            ):
                emphasis = self.emphasisColor(i)
                color = emphasis if emphasis is not None else color.lighter(112)
            if alpha < 1.0:
                color.setAlphaF(color.alphaF() * alpha)
            p.setPen(QPen(border_color, border_w))
            p.setBrush(color)
            kind = str(nd.get("symbol") or "circle")
            rotate = _to_float(nd.get("symbolRotate"), 0.0)
            if kind == "none":
                pass
            elif kind == "circle" and not rotate:
                p.drawEllipse(pt, r, r)
            else:
                p.save()
                p.translate(pt)
                if rotate:
                    p.rotate(rotate)
                drawSymbol(p, kind, QPointF(0.0, 0.0), nd["size"])
                p.restore()
            if label_show and nd["name"]:
                text = self.hierarchyLabelText(
                    i, nd["name"], nd.get("value"), nd.get("item")
                )
                p.setPen(c_label)
                tw = fm.horizontalAdvance(text)
                rect = QRectF(pt.x() - tw / 2, pt.y() + r + 2, tw + 4, fm.height())
                p.drawText(
                    rect,
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    text,
                )
                self._label_rects.append((i, rect, text))
        p.restore()

    def hitTest(self, pos: QPointF):
        best = None
        best_d = 1e9
        if not self._nodes:
            return None
        # 命中必须与 ``paint`` 用同一份动画插值，否则动画期会命中还没到位的节点。
        pts = self._animated_points(self._anim_t)
        for i, nd in enumerate(self._nodes):
            if self._category_hidden(nd):
                continue
            d = _dist(pos, pts[i])
            if d <= nd["size"] / 2 + 4 and d < best_d:
                best_d = d
                best = (i, nd)
        if best is None:
            return None
        i, nd = best
        value = nd.get("value")
        style = nd.get("item_style") or {}
        raw = style.get("color")
        color = (
            self.resolveColor(raw)
            if isinstance(raw, str) and raw
            else (self.visualColor(i) or self.resolveColor(nd["color"]))
        )
        return {
            "name": nd["name"],
            "value": i if value is None else value,
            "color": color,
            "series": self.name,
            "dataIndex": i,
        }
