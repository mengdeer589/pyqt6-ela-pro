"""graphic 组件。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen

from .._tokens import T
from .._utils import parse_color, text_italic
from .._utils import to_float as _to_float, warn_once
from ..axes import chartFont


def lerp_color(c1, c2, t: float) -> QColor:
    """两种颜色按 t ∈ [0,1] 线性插值（RGB 空间）。"""
    t = min(max(float(t), 0.0), 1.0)
    a, b = parse_color(c1), parse_color(c2)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


class GraphicComponent:
    """绝对定位图形元素：circle / rect / text / line。

    option（顶层）::

        "graphic": [
            {"type": "circle", "left": 40, "top": 40,
             "shape": {"cx": 0, "cy": 0, "r": 20},
             "style": {"fill": "#3F5E8C", "stroke": "#..."}},
            {"type": "rect", "left": "center", "top": 20,
             "shape": {"x": -40, "y": 0, "width": 80, "height": 24, "r": 4},
             "style": {"fill": "#..."}},
            {"type": "text", "left": 12, "top": 12,
             "style": {"text": "水印", "fill": "#98A0AC", "fontSize": 14}},
            {"type": "line", "left": 0, "top": 0,
             "shape": {"x1": 0, "y1": 0, "x2": 100, "y2": 40},
             "style": {"stroke": "#...", "lineWidth": 2}},
        ]

    ``left`` / ``top`` 为相对图表内容区的像素偏移，或 ``"center"``
    （水平 / 垂直居中锚点）；shape 内坐标相对该锚点。未知类型静默跳过。
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

    def _anchor(self, el: dict) -> QPointF:
        """元素锚点：``left`` / ``top`` 解析成内容区内的绝对坐标。

        支持三类写法（ECharts 语义）：

        * 数值 —— 相对内容区左上角的**像素**偏移；
        * ``"center"`` —— 该轴居中；
        * ``"middle"`` —— 垂直居中（ECharts 官方拼写；``top: "middle"`` 是
          最常见的一处，原先只认 ``"center"`` 而静默按 0 处理 → 水印类
          纵向居中的文字全贴到顶边）；
        * ``"30%"`` —— 相对内容区宽 / 高的百分比。

        百分比与 ``"middle"`` 原先都落进 ``_to_float`` 的兜底分支（0），
        **不报错也不告警**，只是元素悄悄跑到左上角。
        """
        return QPointF(
            self._anchor_axis(el.get("left", 0), self.rect.left(), self.rect.width()),
            self._anchor_axis(el.get("top", 0), self.rect.top(), self.rect.height()),
        )

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
        for el in self.elements:
            typ = str(el.get("type") or "")
            shape = el.get("shape") or {}
            style = el.get("style") or {}
            base = self._anchor(el)
            try:
                self._paint_element(p, typ, shape, style, base)
            except Exception:
                continue  # 单元素异常不影响其他元素
        p.restore()

    def _paint_element(
        self, p: QPainter, typ: str, shape: dict, style: dict, base: QPointF
    ) -> None:
        if typ == "circle":
            cx = base.x() + _to_float(shape.get("cx"), 0.0)
            cy = base.y() + _to_float(shape.get("cy"), 0.0)
            r = _to_float(shape.get("r"), 20.0)
            self._apply_brush(p, style, default_fill=T("color.primary"))
            p.drawEllipse(QPointF(cx, cy), r, r)
        elif typ == "rect":
            x = base.x() + _to_float(shape.get("x"), 0.0)
            y = base.y() + _to_float(shape.get("y"), 0.0)
            w = _to_float(shape.get("width"), 40.0)
            h = _to_float(shape.get("height"), 24.0)
            radius = _to_float(shape.get("r"), 0.0)
            self._apply_brush(p, style, default_fill=T("color.primary.subtle"))
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
            # ``fill: "none"`` 要跟 circle / rect 一样被认出来：直接喂给
            # ``QColor`` 会得到**无效颜色**，而无效 pen 的文字**根本不画**
            # —— 用户写「不要文字」结果得到空白，且没有任何报错。
            fill = style.get("fill")
            if fill == "none" or fill is False:
                return
            color = parse_color(fill) if isinstance(fill, str) and fill else QColor()
            if not color.isValid():
                warn_once(
                    "graphic-text-fill", f"graphic text 的 fill 非法，已跳过: {fill!r}"
                )
                return
            p.setPen(color or QColor(T("color.text.primary")))
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
            stroke = parse_color(style.get("stroke") or T("color.border.strong"))
            width = _to_float(style.get("lineWidth"), 2.0)
            p.setPen(QPen(stroke, width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    @staticmethod
    def _apply_brush(p: QPainter, style: dict, default_fill) -> None:
        fill = style.get("fill")
        stroke = style.get("stroke")
        if fill == "none" or fill is False:
            p.setBrush(Qt.BrushStyle.NoBrush)
        else:
            p.setBrush(parse_color(fill or default_fill))
        if stroke:
            p.setPen(QPen(parse_color(stroke), _to_float(style.get("lineWidth"), 1.0)))
        else:
            p.setPen(Qt.PenStyle.NoPen)

    def hitTest(self, pos: QPointF):
        """恒返回 None —— graphic 是**装饰元素**，不参与命中。

        ECharts 的 graphic 同为纯覆盖层（要交互得自己接 ``chart.on("click")``
        自己做坐标判定）。保留本方法只为把这个决定写成代码而不是留白：
        ``core`` 的命中分发只问 ``_HOVERABLE_COMPONENTS``，graphic 不在其中。
        """
        return None
