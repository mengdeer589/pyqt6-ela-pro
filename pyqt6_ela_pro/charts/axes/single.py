"""单轴坐标系。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen

from .._tokens import T
from .._utils import single_option
from ._shared import (
    _iter_data_values,
    _line_pen,
    _margin_px,
    _parse_margin,
    formatValue,
)
from .base import AxisModel, Coord


class SingleAxisCoord(Coord):
    """横向单轴坐标系（一行数值轴，系列在其上排布）。

    ``singleAxis`` 收 left/right/top/bottom/type/min/max/name；left/right 默认
    40，top/bottom 不给时垂直居中。``mapPoint(value)`` 单参返回轴线上像素点。
    """

    kind = "singleAxis"

    def __init__(self, chart=None, option: dict = None):
        super().__init__(chart, option)
        sopt = dict(single_option(self.option.get("singleAxis"), "singleAxis") or {})
        self.axis = AxisModel(sopt, "value", self.chart)
        # 边距支持 px / 百分比；top/bottom 非法输入降级为 None（垂直居中）
        self._m_left = _parse_margin(sopt.get("left"), 40)
        self._m_right = _parse_margin(sopt.get("right"), 40)
        self._m_top = _parse_margin(sopt.get("top"), None)
        self._m_bottom = _parse_margin(sopt.get("bottom"), None)
        self.m_left = self.m_right = self.m_top = self.m_bottom = 0.0
        self.line_y = 0.0
        self.plot = QRectF()

    def setSeries(self, series_opts: list) -> None:
        vs = []
        for s in series_opts or []:
            if not isinstance(s, dict) or s.get("coordinateSystem") != "singleAxis":
                continue
            vs.extend(_iter_data_values(s.get("data")))
        if vs:
            self.axis.setExtent(min(vs), max(vs))
        else:
            self.axis.setExtent(0.0, 1.0)

    def layout(self, rect: QRectF) -> None:
        super().layout(rect)
        self.m_left = _margin_px(self._m_left, rect.width())
        self.m_right = _margin_px(self._m_right, rect.width())
        self.m_top = _margin_px(self._m_top, rect.height())
        self.m_bottom = _margin_px(self._m_bottom, rect.height())
        left = rect.left() + self.m_left
        right = rect.right() - self.m_right
        if self.m_top is not None:
            y = rect.top() + self.m_top
        elif self.m_bottom is not None:
            y = rect.bottom() - self.m_bottom
        else:
            y = rect.center().y()
        self.line_y = y
        self.plot = QRectF(left, y, max(10.0, right - left), 0.0)

    def mapPoint(self, x, y=None) -> QPointF:
        px = self.axis.map(x, self.plot.left(), self.plot.right())
        return QPointF(px, self.line_y)

    def invertX(self, pos: QPointF):
        return self.axis.invert(pos.x(), self.plot.left(), self.plot.right())

    def invertPoint(self, pos: QPointF):
        """像素 → 轴数值（单轴返回标量）。"""
        return self.axis.invert(pos.x(), self.plot.left(), self.plot.right())

    def containPoint(self, pos: QPointF) -> bool:
        rect = QRectF(
            self.plot.left(),
            self.line_y - 12.0,
            max(1.0, self.plot.width()),
            24.0,
        )
        return rect.contains(QPointF(pos))

    def paintAxes(self, p: QPainter) -> None:
        p.save()
        c_axis = QColor(T("color.border.strong"))
        c_grid = QColor(T("color.border"))
        c_text = QColor(T("color.text.secondary"))
        font = self.axis.labelFont()
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(QPen(c_axis, 1))
        p.drawLine(
            QPointF(self.plot.left(), self.line_y),
            QPointF(self.plot.right(), self.line_y),
        )
        for tv in self.axis.ticks():
            px = self.axis.map(tv, self.plot.left(), self.plot.right())
            p.setPen(QPen(c_grid, 1))
            p.drawLine(QPointF(px, self.line_y - 4), QPointF(px, self.line_y + 4))
            p.setPen(c_text)
            p.drawText(
                QRectF(px - 40, self.line_y + 6, 80, fm.height()),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                formatValue(tv),
            )
        if self.axis.name:
            p.setPen(QColor(T("color.text.tertiary")))
            p.drawText(
                QRectF(
                    self.plot.right() + 6,
                    self.line_y - fm.height() / 2,
                    80,
                    fm.height(),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.axis.name,
            )
        p.restore()

    def paintTooltipMarker(
        self, p: QPainter, pos: QPointF, kind: str = "cross", line_style: dict = None
    ) -> None:
        if kind == "none":
            return
        p.save()
        style = line_style if isinstance(line_style, dict) else {}
        pen = _line_pen({"lineStyle": style}, T("color.border.strong"))
        if not isinstance(style.get("type"), str):
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        x = min(max(pos.x(), self.plot.left()), self.plot.right())
        p.drawLine(QPointF(x, self.rect.top() + 8), QPointF(x, self.rect.bottom() - 8))
        p.restore()
