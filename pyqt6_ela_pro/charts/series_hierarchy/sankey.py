"""桑基图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

from .._utils import clamp as _clamp
from .._utils import to_float as _to_float
from .._utils import with_alpha
from ..core import SeriesRenderer
from ._shared import _label_font


class SankeySeriesRenderer(SeriesRenderer):
    """桑基图（节点矩形 + 贝塞尔流带）。
    支持 ``data`` / ``nodes`` / ``links`` / ``nodeWidth`` / ``nodeGap`` /
    ``layoutIterations`` / ``label`` / ``lineStyle``。
    """

    labelVisibleByDefault = True

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []  # [dict(name,color,rect,value,depth)]
        self._bands = []  # [dict(path=QPainterPath,color,source,target,value)]
        self._name_index = {}

        self._fixed_y: dict[int, float] = {}
        self._drag_index = None
        self._drag_offset = 0.0

    def _parse(self):
        raw_nodes = self.opt.get("data")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raw_nodes = self.opt.get("nodes")
        nodes = []
        for i, item in enumerate(raw_nodes or []):
            if isinstance(item, dict):
                name = str(item.get("name") or f"node{i}")
            else:
                name = str(item)
            nodes.append(
                {
                    "name": name,
                    "index": i,
                    "item": item if isinstance(item, dict) else None,
                }
            )
        self._name_index = {}
        for nd in nodes:
            self._name_index.setdefault(nd["name"], nd["index"])
        links = []
        for item in self.opt.get("links") or []:
            if not isinstance(item, dict):
                continue
            s = self._node_index(item.get("source"))
            t = self._node_index(item.get("target"))
            v = _to_float(item.get("value"), 0.0)
            if s is None or t is None or s == t or v <= 0:
                continue
            links.append({"source": s, "target": t, "value": v})
        return nodes, links

    def _node_index(self, ref):
        if isinstance(ref, bool):
            return None
        if isinstance(ref, (int, float)):
            i = int(ref)
            return i if 0 <= i < len(self._name_index) else None
        return self._name_index.get(str(ref))

    def layout(self, rect: QRectF) -> None:
        self._nodes = []
        self._bands = []
        nodes, links = self._parse()
        if not nodes:
            return
        n = len(nodes)
        # 邻接表
        out_adj = [[] for _ in range(n)]
        in_adj = [[] for _ in range(n)]
        for lk in links:
            out_adj[lk["source"]].append(lk)
            in_adj[lk["target"]].append(lk)
        # 节点值 = max(入流, 出流)
        values = [0.0] * n
        for i in range(n):
            values[i] = max(
                sum(link["value"] for link in out_adj[i]),
                sum(link["value"] for link in in_adj[i]),
            )
        # BFS 分层（最长路径：深度 = 最远前置层 + 1）
        depth = [0] * n
        indeg = [len(in_adj[i]) for i in range(n)]
        queue = [i for i in range(n) if indeg[i] == 0]
        order = list(queue)
        head = 0
        while head < len(order):
            u = order[head]
            head += 1
            for lk in out_adj[u]:
                v = lk["target"]
                depth[v] = max(depth[v], depth[u] + 1)
                indeg[v] -= 1
                if indeg[v] == 0:
                    order.append(v)
                    queue.append(v)
        # 环 / 不可达节点兜底：按出边递增深度，但必须限幅。整环每轮都会
        # 继续加深度，60 节点环能涨到 3500+ 列，节点全挤在右侧。
        max_layers = max(1, n)
        for _ in range(n):
            changed = False
            for lk in links:
                if depth[lk["target"]] <= depth[lk["source"]]:
                    depth[lk["target"]] = min(depth[lk["source"]] + 1, max_layers - 1)
                    changed = True
            if not changed:
                break
        max_depth = max(depth) if depth else 0
        columns = [[] for _ in range(max_depth + 1)]
        for i in range(n):
            columns[depth[i]].append(i)
        # 迭代排序减交叉：按对侧邻居重心排序（正反向各扫）
        iterations = max(0, int(_to_float(self.opt.get("layoutIterations"), 6)))
        pos_in_col = {i: k for col in columns for k, i in enumerate(col)}

        def barycenter(col, neighbors_fn, other_pos):
            def key(i):
                neigh = neighbors_fn(i)
                if not neigh:
                    return pos_in_col.get(i, 0)
                return sum(other_pos.get(j, 0) for j in neigh) / len(neigh)

            return key

        for _ in range(iterations):
            for d in range(1, max_depth + 1):  # 正向：按入边源排序
                col = columns[d]
                other = {i: pos_in_col[i] for i in columns[d - 1]}
                col.sort(
                    key=barycenter(
                        col, lambda i: [lk["source"] for lk in in_adj[i]], other
                    )
                )
                for k, i in enumerate(col):
                    pos_in_col[i] = k
            for d in range(max_depth - 1, -1, -1):  # 反向：按出边目标排序
                col = columns[d]
                other = {i: pos_in_col[i] for i in columns[d + 1]}
                col.sort(
                    key=barycenter(
                        col, lambda i: [lk["target"] for lk in out_adj[i]], other
                    )
                )
                for k, i in enumerate(col):
                    pos_in_col[i] = k
        # 几何：列 x 均布，列内按值纵向堆叠
        node_w = _clamp(_to_float(self.opt.get("nodeWidth"), 14.0), 4.0, 60.0)
        node_gap = _clamp(_to_float(self.opt.get("nodeGap"), 10.0), 0.0, 60.0)
        pad_x, pad_y = 56.0, 12.0
        plot = QRectF(
            rect.left() + pad_x,
            rect.top() + pad_y,
            max(20.0, rect.width() - pad_x * 2),
            max(20.0, rect.height() - pad_y * 2),
        )
        col_x = []
        for d in range(max_depth + 1):
            if max_depth == 0:
                col_x.append(plot.center().x() - node_w / 2)
            else:
                col_x.append(plot.left() + (plot.width() - node_w) * d / max_depth)
        align = str(self.opt.get("nodeAlign") or "justify").strip().lower()
        if align == "left":
            col_x = [plot.left() for _ in col_x]
        elif align == "right":
            col_x = [plot.right() - node_w for _ in col_x]
        node_rect = {}
        for d, col in enumerate(columns):
            total_v = sum(values[i] for i in col)
            avail_h = plot.height() - node_gap * max(0, len(col) - 1)
            scale = avail_h / total_v if total_v > 0 else 0.0
            y = plot.top()
            for i in col:
                h_i = max(3.0, values[i] * scale) if total_v > 0 else 6.0
                node_rect[i] = QRectF(col_x[d], y, node_w, h_i)
                y += h_i + node_gap
        for i, fixed in self._fixed_y.items():
            rect_i = node_rect.get(i)
            if rect_i is None:
                continue
            rect_i.moveTop(
                _clamp(
                    fixed, plot.top(), max(plot.top(), plot.bottom() - rect_i.height())
                )
            )
        # 节点实际渲染色：流带 source/target 与节点共用，避免两套取色。
        node_colors = [
            self.visualColorForValue(values[i]) or self.dataColor(i) for i in range(n)
        ]
        # 流带偏移（源 / 目标各自的堆叠游标）
        src_off = {i: node_rect[i].top() for i in range(n)}
        tgt_off = {i: node_rect[i].top() for i in range(n)}
        for lk in sorted(links, key=lambda x: -x["value"]):
            s, t = lk["source"], lk["target"]
            rs, rt = node_rect[s], node_rect[t]
            scale_s = (rs.height() / values[s]) if values[s] > 0 else 0.0
            scale_t = (rt.height() / values[t]) if values[t] > 0 else 0.0
            # 两端都要装得下：只按源节点缩放会让目标端流带越界重叠。
            bh = max(1.5, lk["value"] * min(scale_s, scale_t))
            y1 = src_off[s]
            y2 = tgt_off[t]
            src_off[s] += bh
            tgt_off[t] += bh
            x1 = rs.right()
            x2 = rt.left()
            path = QPainterPath()
            path.moveTo(x1, y1)
            mx = (x1 + x2) / 2
            path.cubicTo(mx, y1, mx, y2, x2, y2)
            path.lineTo(x2, y2 + bh)
            path.cubicTo(mx, y2 + bh, mx, y1 + bh, x1, y1 + bh)
            path.closeSubpath()
            self._bands.append(
                {
                    "path": path,
                    "source": nodes[s]["name"],
                    "target": nodes[t]["name"],
                    "value": lk["value"],
                    "source_color": node_colors[s],
                    "target_color": node_colors[t],
                    "color": node_colors[s],
                }
            )
        for i, nd in enumerate(nodes):
            self._nodes.append(
                {
                    "index": i,
                    "name": nd["name"],
                    "item": nd.get("item") or nd,
                    "value": values[i],
                    "rect": node_rect[i],
                    "depth": depth[i],
                    "color": node_colors[i],
                }
            )

    def _band_brush(self, band, anim_t):
        """流带画刷：``lineStyle.color`` 支持 source（默认）/ target / gradient / 色值。"""
        line_style = self.opt.get("lineStyle") or {}
        mode = line_style.get("color")
        opacity = 70.0
        if isinstance(line_style.get("opacity"), (int, float)):
            opacity = 255.0 * _clamp(float(line_style["opacity"]), 0.0, 1.0)
        if mode == "target":
            return with_alpha(band["target_color"], int(opacity * anim_t))
        if mode == "gradient":
            rect = band["path"].boundingRect()
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            grad.setColorAt(
                0.0, with_alpha(band["source_color"], int(opacity * anim_t))
            )
            grad.setColorAt(
                1.0, with_alpha(band["target_color"], int(opacity * anim_t))
            )
            return grad
        if isinstance(mode, str) and mode not in ("source",):
            color = self.resolveColor(mode)
            if color.isValid():
                return with_alpha(color, int(opacity * anim_t))
        return with_alpha(band["source_color"], int(opacity * anim_t))

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
        self._label_rects = []
        hover = self.chart.hoverInfo()
        hovered = (
            hover[1].get("dataIndex")
            if hover is not None and hover[0] is self
            else None
        )
        # 流带（默认源色半透明；anim_t 渐入）
        for band in self._bands:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._band_brush(band, anim_t))
            p.drawPath(band["path"])
        # 节点 + 标签
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        font = _label_font(self, label_opt)
        p.setFont(font)
        fm = QFontMetricsF(font)
        c_text = self.labelColor()
        max_depth = max((nd["depth"] for nd in self._nodes), default=0)
        for nd in self._nodes:
            r = nd["rect"]
            color = self.visualColorForValue(nd["value"]) or self.dataColor(nd["index"])
            alpha = self.itemOpacity(nd["index"])
            border_color, border_w = self.itemBorder(nd["index"])
            color, alpha, border_color, border_w = self.stateStyle(
                nd["index"], hovered, color, alpha, border_color, border_w
            )
            if border_color is not None and border_w > 0:
                p.setPen(QPen(border_color, border_w))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(with_alpha(color, int(255 * anim_t * alpha)))
            p.drawRect(r)
            if not label_show:
                continue
            text = self.hierarchyLabelText(
                nd.get("index"),
                nd["name"],
                nd.get("value"),
                nd.get("item"),
            )
            p.setPen(c_text)
            tw = fm.horizontalAdvance(text)
            if nd["depth"] >= max_depth:  # 末列标签放左侧
                rect = QRectF(
                    r.left() - tw - 6,
                    r.center().y() - fm.height() / 2,
                    tw + 4,
                    fm.height(),
                )
                p.drawText(
                    rect,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    text,
                )
            else:
                rect = QRectF(
                    r.right() + 4,
                    r.center().y() - fm.height() / 2,
                    tw + 4,
                    fm.height(),
                )
                p.drawText(
                    rect,
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    text,
                )
            self._label_rects.append((nd.get("index"), rect, text))
        p.restore()

    def onMousePress(self, pos: QPointF) -> bool:
        if not self.opt.get("draggable", False):
            return False
        for nd in reversed(self._nodes):
            if nd["rect"].adjusted(-2, -2, 2, 2).contains(pos):
                self._drag_index = nd["index"]
                self._drag_offset = pos.y() - nd["rect"].top()
                return True
        return False

    def onMouseMove(self, pos: QPointF) -> bool:
        if self._drag_index is None:
            return False
        self._fixed_y[self._drag_index] = pos.y() - self._drag_offset
        self.chart.invalidateLayout()
        self.chart.update()
        return True

    def onMouseRelease(self, pos: QPointF) -> bool:
        if self._drag_index is None:
            return False
        self._drag_index = None
        return True

    def resetPositions(self) -> None:
        """清除拖拽固定位置。"""
        if self._fixed_y:
            self._fixed_y.clear()
            self.chart.invalidateLayout()
            self.chart.update()

    def hitTest(self, pos: QPointF):
        for nd in self._nodes:
            if nd["rect"].contains(pos):
                return {
                    "name": nd["name"],
                    "value": nd["value"],
                    "color": self.visualColorForValue(nd["value"])
                    or self.dataColor(nd["index"]),
                    "series": self.name,
                    "depth": nd["depth"],
                    "dataIndex": nd.get("index"),
                }
        for band in self._bands:
            if band["path"].contains(pos):
                return {
                    "name": f"{band['source']} → {band['target']}",
                    "value": band["value"],
                    "color": band.get("color"),
                    "series": self.name,
                    "source": band["source"],
                    "target": band["target"],
                }
        return None
