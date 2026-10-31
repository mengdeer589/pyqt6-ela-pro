"""飞线系列。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import QApplication

from ..._motion import start_idle_loop
from .._tokens import EFFECT_TICK_MS
from .._utils import ON_FILL_WHITE
from .._utils import dist_point_segment
from .._utils import to_float as _to_float
from .._utils import with_alpha
from .._utils import parse_color
from ..core import SeriesRenderer


class LinesSeriesRenderer(SeriesRenderer):
    """飞线（起终点坐标对，Grid 直角坐标系下绘制）。

    支持 ``coordinateSystem`` / ``data``（``coords`` 起终点）/ ``lineStyle`` /
    ``effect``（QTimer 驱动的移动亮点）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._segments = []  # [dict(p0,p1,value)]
        self._phase = 0.0  # 亮点进度 [0,1)
        self._timer = None
        effect = self._effect_opt()
        if bool(effect.get("show", False)) and QApplication.instance() is not None:
            timer = QTimer(chart)  # 生命周期挂 ChartWidget
            timer.timeout.connect(self._on_tick)
            # 间隔只在这里设置一次：``start_idle_loop`` 无论启不启动都会写 ``setInterval``。
            start_idle_loop(timer, EFFECT_TICK_MS)
            self._timer = timer

    def _effect_opt(self):
        eff = self.opt.get("effect")
        return dict(eff or {})

    def _on_tick(self):
        """亮点推进。整个回调包裹：Qt 定时器回调抛异常会终止进程。"""
        timer = self._timer
        if timer is None:
            return
        try:
            alive = self in self.chart.seriesRenderers
        except RuntimeError:
            alive = False  # chart 已销毁
        if not alive:
            timer.stop()
            timer.deleteLater()
            self._timer = None
            return
        if not self.visible:
            if timer.isActive():
                timer.stop()
            return
        if not timer.isActive():
            timer.start()
        try:
            effect = self._effect_opt()
            period = max(0.5, _to_float(effect.get("period"), 4.0))
            # 步长按实际 tick 间隔算，``period`` 才是用户可见的周期。
            step = max(1, int(timer.interval())) / 1000.0 / period
            self._phase = (self._phase + step) % 1.0
            self.requestSeriesRepaint()
        except RuntimeError:
            timer.stop()
            timer.deleteLater()
            self._timer = None
        except Exception:
            timer.stop()
            timer.deleteLater()
            self._timer = None

    def _on_visible_changed(self):
        """显隐变化钩子：显示恢复时重启定时器（必须走 ``start_idle_loop`` 以守动效策略）。"""
        if self.visible and self._timer is not None and not self._timer.isActive():
            start_idle_loop(self._timer, EFFECT_TICK_MS)

    def layout(self, rect: QRectF) -> None:
        self._segments = []
        coord = self.chart.coordFor(self.opt)
        if coord is None or not hasattr(coord, "mapPoint"):
            return
        for item in self.data():
            if not isinstance(item, dict):
                continue
            coords = item.get("coords")
            if not isinstance(coords, (list, tuple)) or len(coords) < 2:
                continue
            c0, c1 = coords[0], coords[1]
            if (
                not isinstance(c0, (list, tuple))
                or len(c0) < 2
                or not isinstance(c1, (list, tuple))
                or len(c1) < 2
            ):
                continue
            try:
                p0 = coord.mapPoint(c0[0], c0[1])
                p1 = coord.mapPoint(c1[0], c1[1])
            except Exception:
                continue
            self._segments.append(
                {
                    "p0": p0,
                    "p1": p1,
                    "name": str(item.get("name") or ""),
                    "value": item.get("value"),
                }
            )

    def _curve_path(self, p0, p1, curveness):
        """直线 / 二次贝塞尔曲线路径。"""
        path = QPainterPath(p0)
        if abs(curveness) > 1e-6:
            mx, my = (p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2
            dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
            # 法向偏移控制点
            cx, cy = mx - dy * curveness, my + dx * curveness
            path.quadTo(QPointF(cx, cy), p1)
        else:
            path.lineTo(p1)
        return path

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._segments:
            return
        p.save()
        ls = dict(self.opt.get("lineStyle") or {})
        width = _to_float(ls.get("width"), 2.0)
        color = parse_color(str(ls.get("color"))) if ls.get("color") else self.color()
        curveness = _to_float(ls.get("curveness"), 0.0)
        pen = QPen(with_alpha(color, int(220 * anim_t)), width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for seg in self._segments:
            p.drawPath(self._curve_path(seg["p0"], seg["p1"], curveness))
        # 端点
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(with_alpha(color, int(200 * anim_t)))
        for seg in self._segments:
            p.drawEllipse(seg["p0"], 2.5, 2.5)
            p.drawEllipse(seg["p1"], 2.5, 2.5)
        # effect 移动亮点
        effect = self._effect_opt()
        if bool(effect.get("show", False)) and anim_t > 0.5:
            dot_size = _to_float(effect.get("symbolSize"), 6.0)
            dot_color = (
                parse_color(str(effect.get("color")))
                if effect.get("color")
                else QColor(ON_FILL_WHITE)
            )
            n = len(self._segments)
            for i, seg in enumerate(self._segments):
                phase = (self._phase + i / max(1, n)) % 1.0
                path = self._curve_path(seg["p0"], seg["p1"], curveness)
                pt = path.pointAtPercent(phase)
                # 光晕 + 亮点
                p.setBrush(with_alpha(dot_color, 60))
                p.drawEllipse(pt, dot_size, dot_size)
                p.setBrush(dot_color)
                p.drawEllipse(pt, dot_size / 2, dot_size / 2)
        p.restore()

    def hitTest(self, pos: QPointF):
        best = None
        best_d = 8.0
        curveness = _to_float((self.opt.get("lineStyle") or {}).get("curveness"), 0.0)
        for i, seg in enumerate(self._segments):
            if abs(curveness) > 1e-6:
                # 命中必须贴着实际绘制的贝塞尔曲线（曲线中点与弦中点可差 90px）。
                path = self._curve_path(seg["p0"], seg["p1"], curveness)
                pts = [path.pointAtPercent(k / 8.0) for k in range(9)]
                d = min(dist_point_segment(pos, a, b) for a, b in zip(pts, pts[1:]))
            else:
                d = dist_point_segment(pos, seg["p0"], seg["p1"])
            if d <= best_d:
                best_d = d
                best = (i, seg)
        if best is None:
            return None
        i, seg = best
        return {
            "name": seg["name"] or self.name,
            "value": seg["value"],
            "series": self.name,
            "dataIndex": i,
        }
