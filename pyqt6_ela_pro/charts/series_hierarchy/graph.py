"""关系图系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPen,
)

from .._tokens import T
from .._utils import clamp as _clamp
from .._utils import parse_roam as _parse_roam
from .._utils import to_float as _to_float
from .._utils import with_alpha
from .._utils import parse_color
from ..core import SeriesRenderer
from ._shared import _dist, _label_font, _series_palette_color, _text_color


class GraphSeriesRenderer(SeriesRenderer):
    """关系图（节点 + 边）。

    option 键：
    - ``data`` / ``nodes``: [{"name","symbolSize","value","category","itemStyle"}]；
    - ``categories``: ["分类"] 或 [{"name","itemStyle":{"color"}}]（节点分类着色）；
    - ``links``: [{"source","target"}]（名称或下标）；
    - ``layout``: "force"（默认，斥力 + 引力迭代 ~80 轮，确定性随机种子
      保证可复现）/ "circular"（均布圆环）；
    - ``force``: {"seed": 42, "iterations": 80, "repulsion": 1.0}；
    - ``label``: {"show": True, "fontSize": px}（节点名称）；
    - ``symbolSize``: 默认节点直径 px（节点级 symbolSize 优先）；
    - ``draggable``: True 时按住节点拖拽调整位置（拖拽后位置固定，布局重算
      不覆盖；ECharts 默认 False）；
    - ``roam``: True / "scale" / "move" 开启滚轮缩放 + 空白处拖拽平移，
      ``zoom`` 为初始缩放倍数，``resetRoam()`` 复位。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._nodes = []  # [dict(name,size,pos=QPointF,color)]
        self._edges = []  # [(i, j)]
        self._drag_index = None
        self._fixed: dict = {}  # 拖拽后的固定位置 {节点下标: QPointF}
        #: 力导布局记忆化（见 ``_force_positions``）。条目 ``(key, positions)``，
        #: ``positions`` 是**归一化 [0,1] 坐标**的 list，调用方只读。
        self._force_cache = None
        self._pan = QPointF()
        self._pan_start = None
        self._plot = QRectF()
        self._roam = self._parse_roam()
        try:
            self._zoom = max(0.2, min(5.0, float(opt.get("zoom") or 1.0)))
        except (TypeError, ValueError, OverflowError):
            self._zoom = 1.0

    def _parse_roam(self):
        """``roam`` → ``(scale 可否缩放, move 可否平移)``。共用 ``parse_roam``。"""
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
                item_style = self.itemStyleOf(item)
            else:
                name, size, category, item_style = str(item), None, None, {}
            nodes.append(
                {
                    "name": name,
                    "size": size,
                    "category": category,
                    "itemStyle": item_style,
                }
            )
            name_index.setdefault(name, i)
        edges = []

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
                color = parse_color(raw)
                if color.isValid():
                    return color
        return _series_palette_color(self.chart, index)

    # -- 布局 --------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._nodes = []
        self._edges = []
        nodes, edges, categories = self._parse()
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
                # 力导结果在归一化 [0,1] 空间里，缩放到绘图区（circular 分支
                # 已经是像素坐标，故按模式区分）
                if mode == "circular":
                    pos = QPointF(positions[i][0], positions[i][1])
                else:
                    pos = QPointF(
                        plot.left() + positions[i][0] * plot.width(),
                        plot.top() + positions[i][1] * plot.height(),
                    )
            category_color = self._category_color(nd["category"], categories)
            self._nodes.append(
                {
                    "name": nd["name"],
                    "size": _clamp(size, 4.0, 60.0),
                    "pos": pos,
                    "color": category_color or _series_palette_color(self.chart, i),
                    "item_style": nd["itemStyle"],
                }
            )

    # -- 交互：节点拖拽 / roam ----------------------------------------------
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
        if self._roam[1]:
            self._pan_start = QPointF(pos)
            return True
        return False

    def onMouseMove(self, pos: QPointF) -> bool:
        if self._drag_index is not None:
            layout_pos = self._inverse(pos)
            self._fixed[self._drag_index] = layout_pos
            self._nodes[self._drag_index]["pos"] = layout_pos
            # 拖节点改的是**渲染器自己的几何**（``_nodes[i]["pos"]``），
            # 必须走 invalidateLayout 让布局缓存与系列层位图一起失效 ——
            # 只 update() 的话两个缓存都留着旧值，拖动看起来完全没反应。
            self.chart.invalidateLayout()
            self.chart.update()
            return True
        if self._pan_start is not None:
            self._pan = QPointF(pos) - self._pan_start
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
        """力导布局结果（带记忆化）。

        ``_force_layout`` 是**纯函数**：随机种子固定，且全程在归一化 [0,1]
        空间里迭代（结果随后才按 ``plot`` 缩放），所以它的输出只取决于
        「节点数 + 边集合 + seed / iterations / repulsion」。

        而 ``layout`` 会被**每一次** ``_layout_all`` 调 —— resize、悬停引起的
        重排、主题切换、图例显隐……每次都把 O(n² × iterations) 的纯 Python
        双层循环重跑一遍。实测 400 节点 / 80 轮 ≈ **1.8 秒**，而这些场景
        根本没改数据。

        记忆化的键覆盖全部输入：节点数、边集合（``edges`` 是 ``(源下标, 目标下标)``
        元组的 list，**顺序敏感**）、三个参数。
        ``_fixed``（拖拽固定位置）在 ``_force_layout`` **之后**才应用，不进
        布局计算，所以拖拽节点不需要让缓存失效。
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
        """Fruchterman-Reingold 简化力导布局（确定性随机种子）。

        在归一化 [0,1] 空间内迭代；输出与 ``plot`` 无关（缩放由调用方做），
        这正是 :meth:`_force_positions` 能记忆化的前提。
        """
        n = len(nodes)
        rng = random.Random(seed)
        # 归一化 [0,1] 空间内迭代
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
        """所有节点的质心（动画收缩的锚点）。

        **必须挡空列表**：``paint`` 侧有 ``if not self._nodes: return`` 兜着，
        而 ``hitTest`` 没有这层 —— 空节点集（data 为空 / layout 还没跑）会
        直接 ``ZeroDivisionError``。而 ``hitTest`` 的异常被
        ``_hitItemWithSeries`` 的 try/except 吞掉，症状是「静默命中不到任何
        节点」，排查时完全看不出是被零除吃掉了。
        """
        n = len(self._nodes)
        if not n:
            return QPointF()
        return QPointF(
            sum(nd["pos"].x() for nd in self._nodes) / n,
            sum(nd["pos"].y() for nd in self._nodes) / n,
        )

    def _animated_points(self, anim_t):
        """动画进度下的屏幕坐标（``paint`` 与 ``hitTest`` 共用）。

        入场动画把每个节点从质心处「张开」到最终位置，所以命中必须用同一
        份插值 —— 否则动画进行中悬停命中的是还没飞到那儿的节点。
        """
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

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._nodes:
            return
        p.save()
        pts = self._animated_points(anim_t)
        # 边
        p.setPen(QPen(with_alpha(_text_color("color.border.strong"), 160), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for s, t in self._edges:
            if 0 <= s < len(pts) and 0 <= t < len(pts):
                p.drawLine(pts[s], pts[t])
        # 节点 + 标签
        label_opt = dict(self.opt.get("label") or {})
        label_show = bool(label_opt.get("show", True))
        c_label = self.labelColor(_text_color("color.text.primary"))
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
            r = nd["size"] / 2
            style = nd.get("item_style") or {}
            raw = style.get("color")
            color = (
                parse_color(raw)
                if isinstance(raw, str) and raw
                else parse_color(nd["color"])
            )
            alpha = self.itemOpacity(i)
            if hovered is not None:
                if i == hovered or i == self._drag_index:
                    if i == hovered:
                        emphasis = self.emphasisColor(i)
                        if emphasis is not None:
                            color = emphasis
                        else:
                            color = color.lighter(112)
                elif i != self._drag_index and self.blursOtherItems():
                    blur = self.blurOpacity()
                    alpha *= blur if blur is not None else 0.4
            if alpha < 1.0:
                color.setAlphaF(color.alphaF() * alpha)
            p.setPen(QPen(QColor(T("color.bg.elevated")), 1.5))
            p.setBrush(color)
            p.drawEllipse(pt, r, r)
            if label_show and nd["name"]:
                p.setPen(c_label)
                tw = fm.horizontalAdvance(nd["name"])
                p.drawText(
                    QRectF(pt.x() - tw / 2, pt.y() + r + 2, tw + 4, fm.height()),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                    nd["name"],
                )
        p.restore()

    def hitTest(self, pos: QPointF):
        best = None
        best_d = 1e9
        if not self._nodes:
            return None
        # 入场动画里节点向质心收缩（``paint`` 的 ``anim_pos``），命中必须用
        # 同一份公式，否则动画期悬停会命中一个「还没到那儿」的节点。
        pts = self._animated_points(self._anim_t)
        for i, nd in enumerate(self._nodes):
            d = _dist(pos, pts[i])
            if d <= nd["size"] / 2 + 4 and d < best_d:
                best_d = d
                best = (i, nd)
        if best is None:
            return None
        i, nd = best
        return {"name": nd["name"], "value": i, "series": self.name, "dataIndex": i}
