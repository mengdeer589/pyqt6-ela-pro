"""graphic 组件。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen

from .._tokens import T
from .._utils import resolve_color_option, text_italic
from .._utils import to_float as _to_float, warn_once
from ..axes import chartFont


class GraphicComponent:
    """绝对定位图形元素：circle / rect / text / line。
    ``left`` / ``top`` 为相对图表内容区的像素偏移、``"center"`` / ``"middle"``
    或 ``"N%"``；``shape`` 内坐标相对该锚点。未知类型静默跳过。
    """

    optionKey = "graphic"

    def __init__(self, chart, opt):
        self.chart = chart
        if isinstance(opt, dict):
            opt = [opt]
        self.elements = [e for e in (opt or []) if isinstance(e, dict)]
        self.rect = QRectF()

    def layout(self, rect: QRectF) -> None:
        self.rect = QRectF(rect)

    def _anchor_axis(self, value, origin: float, extent: float) -> float:
        text = str(value).strip().lower()
        if text in ("center", "middle"):
            return origin + extent / 2.0
        if text.endswith("%"):
            try:
                return origin + extent * float(text[:-1]) / 100.0
            except ValueError:
                return origin
        if text in ("left", "top"):
            return origin
        if text in ("right", "bottom"):
            return origin + extent
        return origin + _to_float(value, 0.0)

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self.elements:
            return
        p.save()
        for el in self._sorted(self.elements):
            try:
                self._paint_node(p, el, self.rect)
            except Exception:
                continue  # 单元素异常不影响其他元素
        p.restore()

    @staticmethod
    def _sorted(elements):
        return sorted(
            elements,
            key=lambda item: _to_float(item.get("z"), 0.0),
        )

    def _paint_node(self, p: QPainter, el: dict, rect: QRectF) -> None:
        typ = str(el.get("type") or "")
        if typ == "group":
            base = self._anchor(el, rect)
            p.save()
            p.translate(base)
            origin = el.get("origin") or [0, 0]
            if isinstance(origin, (list, tuple)) and len(origin) >= 2:
                ox, oy = _to_float(origin[0], 0.0), _to_float(origin[1], 0.0)
            else:
                ox = oy = 0.0
            p.translate(ox, oy)
            p.rotate(_to_float(el.get("rotation"), 0.0))
            sx = _to_float(el.get("scaleX", el.get("scale", 1.0)), 1.0)
            sy = _to_float(el.get("scaleY", el.get("scale", 1.0)), 1.0)
            p.scale(sx, sy)
            p.translate(-ox, -oy)
            children = el.get("children")
            if isinstance(children, (list, tuple)):
                # 子元素坐标相对 group；百分比沿用内容区尺寸。
                child_rect = QRectF(0, 0, self.rect.width(), self.rect.height())
                for child in self._sorted(
                    [item for item in children if isinstance(item, dict)]
                ):
                    self._paint_node(p, child, child_rect)
            p.restore()
            return
        shape = el.get("shape") or {}
        style = el.get("style") or {}
        base = self._anchor(el, rect)
        self._paint_element(p, typ, shape, style, base)

    def _anchor(self, el: dict, rect: QRectF = None) -> QPointF:
        """元素锚点：``left`` / ``top``（或 ``right`` / ``bottom``）解析成内容区内的绝对坐标。
        数值 = 像素偏移，``"center"`` / ``"middle"`` = 该轴居中，``"30%"`` =
        相对内容区宽 / 高；无法解析的值按 0 处理。
        """
        rect = rect if rect is not None else self.rect
        left = el.get("left")
        top = el.get("top")
        if left is None and el.get("right") is not None:
            x = rect.right() - self._anchor_axis(el.get("right"), 0.0, rect.width())
        else:
            x = self._anchor_axis(left, rect.left(), rect.width())
        if top is None and el.get("bottom") is not None:
            y = rect.bottom() - self._anchor_axis(el.get("bottom"), 0.0, rect.height())
        else:
            y = self._anchor_axis(top, rect.top(), rect.height())
        return QPointF(x, y)

    def _paint_element(
        self, p: QPainter, typ: str, shape: dict, style: dict, base: QPointF
    ) -> None:
        if typ == "circle":
            cx = base.x() + _to_float(shape.get("cx"), 0.0)
            cy = base.y() + _to_float(shape.get("cy"), 0.0)
            r = _to_float(shape.get("r"), 20.0)
            self._apply_brush(p, style, default_fill=T("color.primary", self.chart))
            p.drawEllipse(QPointF(cx, cy), r, r)
        elif typ == "rect":
            x = base.x() + _to_float(shape.get("x"), 0.0)
            y = base.y() + _to_float(shape.get("y"), 0.0)
            w = _to_float(shape.get("width"), 40.0)
            h = _to_float(shape.get("height"), 24.0)
            radius = _to_float(shape.get("r"), 0.0)
            self._apply_brush(
                p, style, default_fill=T("color.primary.subtle", self.chart)
            )
            if radius > 0:
                p.drawRoundedRect(QRectF(x, y, w, h), radius, radius)
            else:
                p.drawRect(QRectF(x, y, w, h))
        elif typ == "text":
            text = str(style.get("text") or "")
            if not text:
                return
            size = int(_to_float(style.get("fontSize"), T("font.xs")))
            p.setFont(
                chartFont(
                    size,
                    None,
                    style.get("fontFamily") or self.chart.fontFamily(),
                    text_italic(style.get("fontStyle")),
                )
            )
            # ``fill: "none"`` 必须显式识别：喂给 QColor 会得到无效色，而无效
            # pen 的文字根本不画（用户写「不要文字」得到空白且无报错）。
            fill = style.get("fill")
            if fill == "none" or fill is False:
                return
            color = (
                resolve_color_option(fill, self.chart)
                if isinstance(fill, str) and fill
                else QColor()
            )
            if not color.isValid():
                # 未写 fill = 用主题文本色；非法值告警后回退，不能整段文字消失。
                if fill:
                    warn_once(
                        "graphic-text-fill",
                        f"graphic text 的 fill 非法，已回退主题文本色: {fill!r}",
                    )
                color = QColor(T("color.text.primary", self.chart))
            p.setPen(color)
            p.setBrush(Qt.BrushStyle.NoBrush)
            fm = QFontMetricsF(p.font())
            x = base.x() + _to_float(shape.get("x"), 0.0)
            y = base.y() + _to_float(shape.get("y"), 0.0)
            p.drawText(
                QRectF(x, y, fm.horizontalAdvance(text) + 4, fm.height() + 2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                text,
            )
        elif typ == "line":
            x1 = base.x() + _to_float(shape.get("x1"), 0.0)
            y1 = base.y() + _to_float(shape.get("y1"), 0.0)
            x2 = base.x() + _to_float(shape.get("x2"), 40.0)
            y2 = base.y() + _to_float(shape.get("y2"), 0.0)
            stroke = resolve_color_option(
                style.get("stroke"), self.chart, T("color.border.strong", self.chart)
            )
            width = _to_float(style.get("lineWidth"), 2.0)
            p.setPen(QPen(stroke, width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _apply_brush(self, p: QPainter, style: dict, default_fill) -> None:
        fill = style.get("fill")
        stroke = style.get("stroke")
        if fill == "none" or fill is False:
            p.setBrush(Qt.BrushStyle.NoBrush)
        else:
            p.setBrush(resolve_color_option(fill, self.chart, default_fill))
        if stroke:
            p.setPen(
                QPen(
                    resolve_color_option(stroke, self.chart),
                    _to_float(style.get("lineWidth"), 1.0),
                )
            )
        else:
            p.setPen(Qt.PenStyle.NoPen)

    def hitTest(self, pos: QPointF):
        """恒返回 None —— graphic 是装饰元素，不参与命中（``_HOVERABLE_COMPONENTS`` 不含它）。"""
        return None
