"""桑基图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
)

from .._utils import clamp as _clamp
from .._utils import to_float as _to_float
from .._utils import with_alpha
from .._utils import parse_color
from ..core import SeriesRenderer
from ._shared import _label_font, _series_palette_color, _text_color


class SankeySeriesRenderer(SeriesRenderer):
    """桑基图（节点矩形 + 贝塞尔流带）。

    option 键：
    - ``data`` / ``nodes``: [{"name"}]（节点，二者等价，data 优先）；
    - ``links``: [{"source","target","value"}]（source/target 为名称或下标）；
    - ``nodeWidth``: 节点矩形宽度 px（默认 14）；
    - ``nodeGap``: 同列节点间距 px（默认 10）；
    - ``layoutIterations``: 排序迭代轮数（默认 6，减少流带交叉）；
    - ``label``: {"show": True, "fontSize": px}（节点名称）；
    - 节点着色：调色板按下标循环；流带取源节点色半透明。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []  # [dict(name,color,rect,value,depth)]
        self._bands = []  # [dict(path=QPainterPath,color,source,target,value)]
        self._name_index = {}

    # -- 数据解析 ----------------------------------------------------------
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
            nodes.append({"name": name, "index": i})
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

    # -- 布局 --------------------------------------------------------------
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
        # 环 / 不可达节点兜底：按出边递增深度限幅
        for _ in range(n):
            changed = False
            for lk in links:
                if depth[lk["target"]] <= depth[lk["source"]]:
                    depth[lk["target"]] = depth[lk["source"]] + 1
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
        # 流带偏移（源 / 目标各自的堆叠游标）
        src_off = {i: node_rect[i].top() for i in range(n)}
        tgt_off = {i: node_rect[i].top() for i in range(n)}
        for lk in sorted(links, key=lambda x: -x["value"]):
            s, t = lk["source"], lk["target"]
            rs, rt = node_rect[s], node_rect[t]
            band_scale = (rs.height() / values[s]) if values[s] > 0 else 0.0
            bh = max(1.5, lk["value"] * band_scale)
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
                    "source_color": _series_palette_color(self.chart, s),
                    "target_color": _series_palette_color(self.chart, t),
                    "color": _series_palette_color(self.chart, s),
                }
            )
        for i, nd in enumerate(nodes):
            self._nodes.append(
                {
                    "index": i,
                    "name": nd["name"],
                    "value": values[i],
                    "rect": node_rect[i],
                    "depth": depth[i],
                    "color": self.itemColor(
                        i, default=_series_palette_color(self.chart, i)
                    ),
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
            color = parse_color(mode)
            if color.isValid():
                return with_alpha(color, int(opacity * anim_t))
        return with_alpha(band["source_color"], int(opacity * anim_t))

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
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
        c_text = self.labelColor(_text_color("color.text.primary"))
        max_depth = max((nd["depth"] for nd in self._nodes), default=0)
        for nd in self._nodes:
            r = nd["rect"]
            color = parse_color(nd["color"])
            alpha = self.itemOpacity(nd["index"])
            if hovered is not None:
                if nd["index"] == hovered:
                    emphasis = self.emphasisColor(nd["index"])
                    color = emphasis if emphasis is not None else color.lighter(112)
                elif self.blursOtherItems():
                    blur = self.blurOpacity()
                    alpha *= blur if blur is not None else 0.4
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(with_alpha(color, int(255 * anim_t * alpha)))
            p.drawRect(r)
            if not label_show:
                continue
            p.setPen(c_text)
            tw = fm.horizontalAdvance(nd["name"])
            if nd["depth"] >= max_depth:  # 末列标签放左侧
                p.drawText(
                    QRectF(
                        r.left() - tw - 6,
                        r.center().y() - fm.height() / 2,
                        tw + 4,
                        fm.height(),
                    ),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    nd["name"],
                )
            else:
                p.drawText(
                    QRectF(
                        r.right() + 4,
                        r.center().y() - fm.height() / 2,
                        tw + 4,
                        fm.height(),
                    ),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    nd["name"],
                )
        p.restore()

    def hitTest(self, pos: QPointF):
        for nd in self._nodes:
            if nd["rect"].contains(pos):
                return {
                    "name": nd["name"],
                    "value": nd["value"],
                    "series": self.name,
                    "depth": nd["depth"],
                    "dataIndex": nd.get("index"),
                }
        for band in self._bands:
            if band["path"].contains(pos):
                return {
                    "name": f"{band['source']} → {band['target']}",
                    "value": band["value"],
                    "series": self.name,
                    "source": band["source"],
                    "target": band["target"],
                }
        return None
