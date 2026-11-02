"""
连线绘制。

本模块不创建 QWidget——边与临时线由画布在 ``paintEvent`` 中统一绘制，
这里提供「边部件」对象封装几何与视觉状态，便于命中检测与测试断言：

- ``bezier_path(p1, p2)``：蓝图风格贝塞尔曲线（曲率随水平距离变化）；
- ``ElaEdgeWidget``：一条已建立连线的几何 / 绘制 / 命中（hover 加粗、
  点击选中、running 路径 flowing 虚线动画）；
- ``ElaTempWire``：引脚拖拽中的临时线（磁吸到兼容引脚时高亮）。

移植自 InstructionX_UIKit.blueprint.edge_widget（原库为 PyQt6，
类名 Ela* 前缀；主题令牌经 blueprint._tokens 适配 eTheme；原库无 LICENSE，
保留出处）。
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen

from ._tokens import T
from .model import ElaPinDirectionType
from .registry import pin_color

__all__ = ["bezier_path", "ElaEdgeWidget", "ElaTempWire"]

#: 连线标签的最大宽度（场景单位；超出按省略号截断）
LABEL_MAX_W = 220.0
LABEL_PAD_X = 6.0
LABEL_PAD_Y = 3.0
LABEL_RADIUS = 4.0


def bezier_path(p1: QPointF, p2: QPointF) -> QPainterPath:
    """生成两点间的蓝图风格三次贝塞尔曲线路径。

    控制点沿水平方向外推，外推距离随水平间距增大
    （``clamp(abs(dx) * 0.5, 40, 240)``），垂直堆叠时也有自然弧度。
    """
    dx = abs(p2.x() - p1.x())
    off = min(max(dx * 0.5, 40.0), 240.0)
    path = QPainterPath(p1)
    path.cubicTo(QPointF(p1.x() + off, p1.y()), QPointF(p2.x() - off, p2.y()), p2)
    return path


def _path_points(path: QPainterPath, count: int = 24) -> list:
    """按参数均匀采样曲线上的点（命中检测用）。"""
    return [path.pointAtPercent(i / count) for i in range(count + 1)]


#: 边颜色解析缓存：键为 T() 解析后的色值字符串（主题切换后解析值变化，
#: 缓存自然失效）；容量封顶时整体清空。
_COLOR_CACHE = {}
_COLOR_CACHE_MAX = 64
#: 边画笔缓存：键为 (颜色 RGBA, 宽度, 线型, dash 模式)。同上。
_PEN_CACHE = {}
_PEN_CACHE_MAX = 96


def _cached_color(token_value) -> QColor:
    """按 T() 解析值缓存 QColor 并返回**副本**（避免每帧 hex 解析）。"""
    key = str(token_value)
    color = _COLOR_CACHE.get(key)
    if color is None:
        color = QColor(key)
        if len(_COLOR_CACHE) >= _COLOR_CACHE_MAX:
            _COLOR_CACHE.clear()
        _COLOR_CACHE[key] = color
    return QColor(color)


def _cached_pen(
    color: QColor,
    width: float,
    style=Qt.PenStyle.SolidLine,
    dash=None,
    mutable: bool = False,
) -> QPen:
    """按 (颜色, 宽度, 线型, dash) 缓存 QPen。

    ``mutable=True`` 时返回**副本**。缓存里存的是共享实例，直接改它（例如
    ``setDashOffset``）会让所有共用该键的边互相污染 —— 最后绘制的边留下的
    偏移会传给下一个 painter。
    """
    style_v = getattr(style, "value", style)
    key = (color.rgba(), width, style_v, tuple(dash) if dash is not None else None)
    pen = _PEN_CACHE.get(key)
    if pen is None:
        pen = QPen(QColor.fromRgba(color.rgba()), width)
        pen.setStyle(style)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if dash is not None:
            pen.setDashPattern(dash)
        if len(_PEN_CACHE) >= _PEN_CACHE_MAX:
            _PEN_CACHE.clear()
        _PEN_CACHE[key] = pen
    return QPen(pen) if mutable else pen


class ElaEdgeWidget(QObject):
    """一条已建立连线的部件（几何 + 视觉状态，画布负责绘制）。

    :param canvas: 所属 ``ElaBlueprintCanvas``（用于查询引脚场景坐标）
    :param edge: ``model.ElaEdge`` 数据对象

    状态属性：``hovered`` / ``selected`` / ``flowing``（running 路径流动虚线）。
    贝塞尔路径 / 包围盒 / 命中采样点 / 基础颜色按端点坐标缓存。
    """

    def __init__(self, canvas, edge, parent=None):
        super().__init__(parent or canvas)
        self.canvas = canvas
        self.edge = edge
        self.hovered = False
        self.selected = False
        self.flowing = False
        self._dash_offset = 0.0
        # 几何缓存（端点几何键未变时零重建）
        self._geo_key = None
        self._path = None
        self._p1 = None
        self._p2 = None
        self._bounds = None
        self._samples = None
        self._label_layout = None
        # 标签锚点（曲线中点）；标签被挪开时用细引线连回连线
        self._label_anchor = None
        # 基础颜色（边的引脚类型创建后不变，惰性取一次）
        self._base_color = None

    # -- 几何 ------------------------------------------------------------
    def source_pos(self) -> QPointF:
        """输出端引脚的场景坐标（取不到时回退节点左上角）。"""
        return self.canvas.pin_scene_pos(
            self.edge.from_node, self.edge.from_pin, ElaPinDirectionType.Output
        )

    def target_pos(self) -> QPointF:
        """输入端引脚的场景坐标。"""
        return self.canvas.pin_scene_pos(
            self.edge.to_node, self.edge.to_pin, ElaPinDirectionType.Input
        )

    def _ensure_path(self) -> None:
        """端点几何变化时重建路径并级联失效派生缓存。"""
        canvas = self.canvas
        src = canvas.graph.node(self.edge.from_node)
        tgt = canvas.graph.node(self.edge.to_node)
        sw = canvas._node_widgets.get(self.edge.from_node)
        tw = canvas._node_widgets.get(self.edge.to_node)
        key = (
            None
            if src is None
            else (src.pos.x(), src.pos.y(), sw._layout_rev if sw is not None else -1),
            None
            if tgt is None
            else (tgt.pos.x(), tgt.pos.y(), tw._layout_rev if tw is not None else -1),
        )
        if self._path is not None and key == self._geo_key:
            return
        self._geo_key = key
        self._p1, self._p2 = self.source_pos(), self.target_pos()
        self._path = bezier_path(self._p1, self._p2)
        self._bounds = None
        self._samples = None
        self._label_layout = None
        self._label_anchor = None

    def path(self) -> QPainterPath:
        """当前贝塞尔曲线路径（场景坐标，缓存）。"""
        self._ensure_path()
        return self._path

    def bounding_rect(self) -> QRectF:
        """路径外接矩形 + 标签卡片（含描边余量，场景坐标，缓存）。"""
        self._ensure_path()
        if self._bounds is None:
            bounds = self._path.boundingRect().adjusted(-8, -8, 8, 8)
            label = self._ensure_label()[0]
            if not label.isNull():
                bounds = bounds.united(label.adjusted(-4, -4, 4, 4))
            self._bounds = bounds
        return self._bounds

    def _ensure_label(self):
        """惰性计算标签布局：``(rect, lines, font, line_height)``。"""
        if self._label_layout is not None:
            return self._label_layout
        text = str(self.edge.label or "")
        if not text.strip():
            self._label_layout = (QRectF(), [], None, 0.0)
            self._label_anchor = None
            return self._label_layout
        font = QFont(self.canvas.font())
        font.setPixelSize(int(T("font.sm")))
        metrics = QFontMetrics(font)
        line_h = float(metrics.height())
        lines = [
            metrics.elidedText(raw, Qt.TextElideMode.ElideRight, int(LABEL_MAX_W))
            for raw in text.splitlines() or [text]
        ]
        width = max(metrics.horizontalAdvance(line) for line in lines) + 2 * LABEL_PAD_X
        height = line_h * len(lines) + 2 * LABEL_PAD_Y
        center = self.path().pointAtPercent(0.5)
        rect = QRectF(
            center.x() - width / 2.0,
            center.y() - height / 2.0,
            width,
            height,
        )
        self._label_anchor = center
        chosen, anchor = self._place_label(rect, center, height)
        self._label_anchor = anchor
        self._label_layout = (chosen, lines, font, line_h)
        return self._label_layout

    def _place_label(self, rect: QRectF, center: QPointF, height: float):
        """为标签找位置：沿曲线换锚点 + 法线上下偏移，避开节点矩形。

        返回 ``(label_rect, anchor)``；``anchor`` 是标签对应的曲线点（引线终点）。
        """
        node_rects = [
            QRectF(node.pos, node.size).adjusted(-2.0, -2.0, 2.0, 2.0)
            for node in self.canvas.graph.nodes()
        ]
        canvas_rect = QRectF(self.canvas.rect()).adjusted(2.0, 2.0, -2.0, -2.0)

        def clear(candidate: QRectF) -> bool:
            if any(candidate.intersects(node) for node in node_rects):
                return False
            tl = self.canvas.scene_to_view(candidate.topLeft())
            br = self.canvas.scene_to_view(candidate.bottomRight())
            return canvas_rect.contains(QRectF(tl, br).normalized())

        for percent in (0.5, 0.35, 0.65, 0.2, 0.8):
            spot = self.path().pointAtPercent(percent)
            base = rect.translated(spot - center)
            if clear(base):
                return base, spot
            p1 = self.path().pointAtPercent(percent - 0.01)
            p2 = self.path().pointAtPercent(percent + 0.01)
            dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
            length = (dx * dx + dy * dy) ** 0.5
            normal = (
                QPointF(dy / length, -dx / length)
                if length > 1e-6
                else QPointF(0.0, -1.0)
            )
            for sign in (1.0, -1.0):
                for extra in (8.0, 20.0, 36.0, 56.0, 80.0):
                    candidate = base.translated(normal * (height / 2.0 + extra) * sign)
                    if clear(candidate):
                        return candidate, spot
        return rect, center

    def label_rect(self) -> QRectF:
        """标签卡片矩形（场景坐标；无标签时为空矩形）。"""
        return QRectF(self._ensure_label()[0])

    def invalidate_label(self) -> None:
        """失效标签布局与包围盒（``edge_changed`` 后由画布调用）。"""
        self._label_layout = None
        self._label_anchor = None
        self._bounds = None

    def contains(self, scene_pt: QPointF, tol: float = 7.0) -> bool:
        """命中检测：标签卡片或曲线采样点距场景点小于 ``tol`` 即命中。"""
        coarse = self.bounding_rect().adjusted(-tol, -tol, tol, tol)
        if not coarse.contains(scene_pt):
            return False
        label = self._ensure_label()[0]
        if not label.isNull() and label.adjusted(-2, -2, 2, 2).contains(scene_pt):
            return True
        self._ensure_path()
        if self._samples is None:
            self._samples = _path_points(self._path)
        for pt in self._samples:
            if math.hypot(pt.x() - scene_pt.x(), pt.y() - scene_pt.y()) <= tol:
                return True
        return False

    def _color(self) -> QColor:
        """边的基础颜色（按源引脚类型，惰性缓存；主题切换时画布调用
        ``invalidate_color()`` 失效重建）。"""
        if self._base_color is None:
            node = self.canvas.graph.node(self.edge.from_node)
            pin = (
                node.pin(self.edge.from_pin, ElaPinDirectionType.Output)
                if node is not None
                else None
            )
            self._base_color = (
                _cached_color(pin_color(pin.data_type))
                if pin is not None
                else _cached_color(str(T("color.text.tertiary")))
            )
        return QColor(self._base_color)

    def invalidate_color(self) -> None:
        """失效缓存的边基础色（主题切换后由画布调用，下次绘制实时取色）。"""
        self._base_color = None

    # -- 状态 ------------------------------------------------------------
    def set_flowing(self, on: bool) -> None:
        """设置 / 取消流动虚线动画（由 ExecutionController.set_path 驱动）。"""
        on = bool(on)
        if on == self.flowing:
            return
        self.flowing = on
        update = getattr(self.canvas, "_update_scene_rects", None)
        if update is not None:
            update([self.bounding_rect()])
        else:
            self.canvas.update()

    def advance_dash(self, step: float = 1.6) -> None:
        """推进流动虚线相位（画布定时器调用）。"""
        self._dash_offset -= step

    # -- 绘制 ------------------------------------------------------------
    def draw(self, p: QPainter, label: bool = True) -> None:
        """在已做场景变换的画笔上绘制本条边（``label=False`` 时只画线）。"""
        path = self.path()
        if self.flowing:
            pen = _cached_pen(
                _cached_color(str(T("color.primary"))),
                2.4,
                Qt.PenStyle.DashLine,
                [3.0, 3.0],
                mutable=True,  # 下面要 setDashOffset，必须用副本
            )
            pen.setDashOffset(self._dash_offset)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        else:
            width = 2.0
            color = self._color()
            if self.selected:
                color = _cached_color(str(T("color.primary")))
                width = 2.8
            elif self.hovered:
                width = 3.2
            pen = _cached_pen(color, width)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        if label:
            self.draw_label(p)

    def draw_label(self, p: QPainter) -> None:
        """在曲线中点绘制标签卡片（多行居中；标签覆盖线段，保证可读）。"""
        rect, lines, font, line_h = self._ensure_label()
        if not lines or rect.isNull():
            return
        anchor = self._label_anchor
        if anchor is not None and not rect.contains(anchor):
            x = min(max(anchor.x(), rect.left()), rect.right())
            y = min(max(anchor.y(), rect.top()), rect.bottom())
            p.setPen(QPen(_cached_color(str(T("color.border"))), 1.0))
            p.drawLine(anchor, QPointF(x, y))
        p.setPen(QPen(_cached_color(str(T("color.border"))), 1.0))
        p.setBrush(_cached_color(str(T("color.bg.elevated"))))
        p.drawRoundedRect(rect, LABEL_RADIUS, LABEL_RADIUS)
        p.setPen(_cached_color(str(T("color.text.primary"))))
        p.setFont(font)
        inner_w = rect.width() - 2 * LABEL_PAD_X
        for index, line in enumerate(lines):
            line_rect = QRectF(
                rect.x() + LABEL_PAD_X,
                rect.y() + LABEL_PAD_Y + index * line_h,
                inner_w,
                line_h,
            )
            p.drawText(line_rect, Qt.AlignmentFlag.AlignCenter, line)


class ElaTempWire(QObject):
    """引脚拖拽中的临时连线；``magnet`` 置真 = 磁吸到兼容引脚的反馈（加粗实线）。"""

    def __init__(self, start: QPointF, data_type: str = "any", parent=None):
        super().__init__(parent)
        self.start = QPointF(start)
        self.end = QPointF(start)
        self.data_type = data_type or "any"
        self.magnet = False

    def set_end(self, scene_pt: QPointF) -> None:
        """更新临时线末端（场景坐标）。"""
        self.end = QPointF(scene_pt)

    def draw(self, p: QPainter) -> None:
        """绘制临时线（拖拽中虚线，磁吸时实线加粗）。"""
        path = bezier_path(self.start, self.end)
        color = QColor(pin_color(self.data_type))
        if self.magnet:
            pen = QPen(color, 3.0)
        else:
            pen = QPen(color, 2.0)
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setDashPattern([4.0, 3.0])
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # 末端小圆点
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(self.end, 3.5, 3.5)
