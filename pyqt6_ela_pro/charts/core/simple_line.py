"""core 内置的简易折线兜底渲染器。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import (
    QPointF,
    QRectF,
    Qt,
)
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QPolygonF,
)

from .._tokens import (
    T,
)
from ._shared import parseDataPoint
from .renderer import SeriesRenderer


class SimpleLineSeriesRenderer(SeriesRenderer):
    """内置简易 line 渲染器（接口自测 / 兜底实现）。

    刻意保持简单（直线段 + 圆点，无 smooth / areaStyle / step）且**不自动注册**：
    包入口会注册完整版 ``line``，需要最小渲染器自测时才手动注册。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._points = []  # [QPointF]（当前数据）
        self._prev_points = []  # [QPointF]（旧数据，过渡动画用）
        self._entries = []  # [(x, y)] 解析后的数据

    def layout(self, rect: QRectF) -> None:
        coord = self.chart.coordFor(self.opt)
        self._prev_points = list(self._points)
        self._points = []
        self._entries = []
        if coord is None:
            return
        single = getattr(coord, "kind", "") == "singleAxis"
        for i, item in enumerate(self.data()):
            x, y = parseDataPoint(item, i)
            self._entries.append((x, y))
            if y is None:
                self._points.append(None)
                continue
            try:
                if single:
                    # 单轴：数值即轴上位置（y 为解析出的数值）
                    self._points.append(coord.mapPoint(y))
                else:
                    self._points.append(coord.mapPoint(x, y))
            except Exception:
                self._points.append(None)

    def _animated_points(self, anim_t: float):
        """旧→新插值：长度一致时逐点 lerp；否则返回当前点列。"""
        cur = self._points
        prev_src = self._prev_points
        # 过渡动画路径：prev_data 与当前 data 等长时按数据值重映射旧点
        if self.prev_data is not None and len(self.prev_data) == len(self._entries):
            coord = self.chart.coordFor(self.opt)
            prev = []
            for i, item in enumerate(self.prev_data):
                x, y = parseDataPoint(item, i)
                if y is None or coord is None:
                    prev.append(None)
                    continue
                try:
                    prev.append(coord.mapPoint(x, y))
                except Exception:
                    prev.append(None)
            prev_src = prev
        if len(prev_src) != len(cur):
            return cur
        out = []
        for a, b in zip(prev_src, cur):
            if a is None or b is None:
                out.append(b)
            else:
                out.append(
                    QPointF(
                        a.x() + (b.x() - a.x()) * anim_t,
                        a.y() + (b.y() - a.y()) * anim_t,
                    )
                )
        return out

    def paint(self, p: QPainter, anim_t: float) -> None:
        pts = self._animated_points(anim_t)
        valid = [pt for pt in pts if pt is not None]
        if not valid:
            return
        p.save()
        color = self.color()
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # 折线（跳过 None 断点）
        seg = []
        for pt in pts:
            if pt is None:
                if len(seg) >= 2:
                    p.drawPolyline(QPolygonF(seg))
                seg = []
            else:
                seg.append(pt)
        if len(seg) >= 2:
            p.drawPolyline(QPolygonF(seg))
        # 数据点
        p.setBrush(QColor(T("color.bg.elevated")))
        for pt in valid:
            p.drawEllipse(pt, 3.0, 3.0)
        p.restore()

    def hitTest(self, pos: QPointF):
        best = None
        best_d = self.chart.hitRadius()  # 命中半径 px（tooltip.hitRadius）
        for i, pt in enumerate(self._points):
            if pt is None:
                continue
            d = ((pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2) ** 0.5
            if d <= best_d:
                best_d = d
                best = i
        if best is None:
            return None
        x, y = self._entries[best]
        return {
            "name": self.name,
            "value": y,
            "series": self.name,
            "dataIndex": best,
            "x": x,
        }

    def valueAtIndex(self, index: int):
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        if not isinstance(idx, int) or not (0 <= idx < len(self._entries)):
            return None
        x, y = self._entries[idx]
        if y is None:
            return None
        pos = self._points[idx] if idx < len(self._points) else None
        return {"name": self.name, "value": y, "series": self.name, "pos": pos}
