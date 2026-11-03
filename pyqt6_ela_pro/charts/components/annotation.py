"""annotations 组件：Plotly 风格可拖动标注（文本框 + 指向数据点的箭头）。"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen

from .._tokens import T
from .._utils import (
    clamp,
    merged_text_style,
    parse_color,
    text_italic,
    text_weight,
)
from .._utils import to_float as _to_float
from ..axes import GridCoord, chartFont


def _is_paper(ref) -> bool:
    """``xref`` / ``yref`` 是否是绘图区比例坐标（``"paper"``）。"""
    return isinstance(ref, str) and ref.strip().lower() == "paper"


def _is_no_color(value) -> bool:
    """``bgcolor: "none"`` / ``"transparent"`` / ``False`` 表示不填充。"""
    if value is False:
        return True
    if not isinstance(value, str):
        return False
    return value.strip().lower() in ("none", "transparent")


def _finite_point(point: QPointF) -> bool:
    return math.isfinite(point.x()) and math.isfinite(point.y())


def _rect_edge_point(box: QRectF, target: QPointF) -> QPointF:
    """矩形中心 → ``target`` 的射线与矩形边界的交点。"""
    center = box.center()
    dx = target.x() - center.x()
    dy = target.y() - center.y()
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return QPointF(center)
    half_w = box.width() / 2.0
    half_h = box.height() / 2.0
    tx = half_w / abs(dx) if abs(dx) > 1e-9 else float("inf")
    ty = half_h / abs(dy) if abs(dy) > 1e-9 else float("inf")
    t = min(tx, ty)
    return QPointF(center.x() + dx * t, center.y() + dy * t)


class AnnotationComponent:
    """一条 Plotly 风格标注：箭头尾部 = 数据锚点 + 像素偏移 ``ax`` / ``ay``。

    ``x`` / ``y`` 是箭头指向的数据坐标（category 轴可传类目名或下标）；
    ``ax`` / ``ay`` 是箭头尾部相对锚点的像素偏移，文本框再按 ``xanchor`` /
    ``yanchor`` 摆在尾部周围。拖动只改这两个偏移，箭头终点始终停在 ``x`` /
    ``y`` 对应的数据点上。

    ``xref`` / ``yref`` 支持 ``"x"`` / ``"x2"`` / ``"paper"``（paper = 绘图区
    比例坐标，0 在左 / 下、1 在右 / 上）。``text`` 按纯文本绘制，支持
    ``\\n`` 与 ``<br>`` 换行。
    """

    optionKey = "annotations"
    spawnPerItem = True
    #: 按下文本框算组件消费；原地松开也不能再落成数据点击
    consumesClick = True

    def __init__(self, chart, opt):
        self.chart = chart
        self._source = opt if isinstance(opt, dict) else {}
        self.opt = dict(self._source)
        #: 所属系列 option（core 注入；顶层实例化为 None）
        self.series_opt = None
        self._anchor = QPointF()
        self._box = QRectF()
        self._rect = QRectF()
        self._arrow_start = None
        self._arrow_end = None
        self._lines = []
        self._font = None
        self._text_color = QColor()
        self._bg = QColor()
        self._border = QColor()
        self._border_width = 0.0
        self._radius = 4.0
        self._align = Qt.AlignmentFlag.AlignHCenter
        self._xanchor = "center"
        self._yanchor = "middle"
        self._pad_x = 4.0
        self._pad_y = 4.0
        self._opacity = 1.0
        self._arrow_color = QColor()
        self._arrow_width = 1.5
        self._arrow_size = 8.0
        self._arrow_head = 2
        self._show_arrow = True
        self._standoff = 2.0
        self._ax = 0.0
        self._ay = 0.0
        self._visible = False
        self._dragging = False
        self._drag_moved = False
        self._hovered = False
        self._grab_delta = QPointF()

    def isDragging(self) -> bool:
        return bool(self._dragging)

    def box(self) -> QRectF:
        """文本框矩形（副本；未布局 / 隐藏时为空矩形）。"""
        return QRectF(self._box)

    def anchor(self) -> QPointF:
        """箭头终点（数据锚点）的像素坐标副本。"""
        return QPointF(self._anchor)

    def annotationIndex(self) -> int:
        """本标注在同层 ``annotations`` 数组里的下标（找不到返回 -1）。"""
        return self._scope_index()

    def labelEditHit(self, pos: QPointF):
        """双击命中：返回 ``(数组下标, 文本框矩形)``，未命中 None。"""
        if not self._contains(pos):
            return None
        return self._scope_index(), QRectF(self._box)

    def labelEditText(self, index: int) -> str:
        """行内编辑器初始文本（单行化：``QLineEdit`` 不显示换行）。"""
        return self._text().replace("\n", " ")

    def labelEditRawText(self, index: int) -> str:
        """原始文本（保留换行；编辑器未改动时提交这一份）。"""
        return self._text()

    def setLabelText(self, index: int, text: str) -> bool:
        """修改 ``annotations[index].text``（共享 option 数据）。"""
        try:
            idx = int(index)
        except (TypeError, ValueError, OverflowError):
            return False
        if idx != self._scope_index():
            return False
        value = str(text or "")
        self.opt["text"] = value
        try:
            self._source["text"] = value
        except Exception:
            pass
        self._rebuild_geometry()
        if self.opt.get("show") is False or self.opt.get("visible") is False:
            self._visible = False
        else:
            self._visible = bool(value) and not self._box.isNull()
        return True

    def hitTest(self, pos: QPointF):
        """标注不参与数据命中 / tooltip（拖拽走 ``boxHitTest``）。"""
        return None

    def boxHitTest(self, pos: QPointF) -> bool:
        """光标是否落在可拖动的文本框上。"""
        return self._draggable() and self._contains(pos)

    def _contains(self, pos: QPointF) -> bool:
        """光标是否落在文本框上（不要求可拖动）。"""
        if not self._visible or self._opacity <= 0.0:
            return False
        return self._box.adjusted(-2.0, -2.0, 2.0, 2.0).contains(QPointF(pos))

    def layout(self, rect: QRectF) -> None:
        self._visible = False
        self._box = QRectF()
        self._rect = QRectF(rect)
        self._anchor = QPointF()
        self._arrow_start = None
        self._arrow_end = None
        if self.opt.get("show") is False or self.opt.get("visible") is False:
            return
        text = self._text()
        if not text:
            return
        coord = self._resolve_coord()
        anchor = self._resolve_anchor(coord)
        if anchor is None or not _finite_point(anchor):
            return
        self._anchor = anchor
        self._ax, self._ay = self._read_offsets()
        self._read_style()
        self._rebuild_geometry(text)
        self._visible = True

    def _resolve_coord(self):
        chart = self.chart
        if self.series_opt is not None:
            return chart.coordFor(self.series_opt)
        grid_index = self.opt.get("gridIndex")
        if grid_index is not None:
            try:
                want = int(grid_index)
            except (TypeError, ValueError, OverflowError):
                want = None
            if want is not None:
                for coord in getattr(chart, "_coords", []):
                    if isinstance(coord, GridCoord) and coord.grid_index == want:
                        x_ref = self.opt.get("xref")
                        y_ref = self.opt.get("yref")
                        if isinstance(x_ref, str):
                            xi = self._axis_index(x_ref, "x")
                        else:
                            xi = next(
                                (
                                    i
                                    for i, axis in enumerate(coord.x_axes)
                                    if int(getattr(axis, "grid_index", 0) or 0) == want
                                ),
                                0,
                            )
                        if isinstance(y_ref, str):
                            yi = self._axis_index(y_ref, "y")
                        else:
                            yi = next(
                                (
                                    i
                                    for i, axis in enumerate(coord.y_axes)
                                    if int(getattr(axis, "grid_index", 0) or 0) == want
                                ),
                                0,
                            )
                        return coord.axis_view_for_indices(xi, yi)
        x_ref = self.opt.get("xref")
        y_ref = self.opt.get("yref")
        if isinstance(x_ref, str) or isinstance(y_ref, str):
            # 轴归属决定网格（ECharts xAxis[i].gridIndex）；副轴在第二块网格时
            # 不能拿第一块网格的 plot 去映射。
            xi = self._axis_index(x_ref, "x")
            yi = self._axis_index(y_ref, "y")
            grids = [
                coord
                for coord in getattr(chart, "_coords", [])
                if isinstance(coord, GridCoord)
            ]
            if grids:
                axes = grids[0].x_axes
                axis = axes[xi] if 0 <= xi < len(axes) else None
                want = int(getattr(axis, "grid_index", 0) or 0)
                for coord in grids:
                    if coord.grid_index == want:
                        return coord.axis_view_for_indices(xi, yi)
        return chart.coordFor(self.series_opt)

    def _axis_index(self, ref, prefix: str) -> int:
        """``"x"`` / ``"x2"`` → 轴下标（无法解析回 0）。"""
        if not isinstance(ref, str):
            return 0
        text = ref.strip().lower()
        if text == prefix:
            return 0
        if text.startswith(prefix):
            suffix = text[len(prefix) :]
            if suffix.isdigit():
                return max(0, int(suffix) - 1)
        return 0

    def _resolve_anchor(self, coord) -> QPointF:
        x_ref = self.opt.get("xref")
        y_ref = self.opt.get("yref")
        x_paper = _is_paper(x_ref)
        y_paper = _is_paper(y_ref)
        x = self.opt.get("x", 0)
        y = self.opt.get("y", 0)

        paper = self._paper_rect(coord) if (x_paper or y_paper) else None
        paper_x = paper.left() + _to_float(x, 0.0) * paper.width() if x_paper else None
        paper_y = (
            paper.bottom() - _to_float(y, 0.0) * paper.height() if y_paper else None
        )
        if x_paper and y_paper:
            return QPointF(paper_x, paper_y)
        if coord is None:
            return None
        mapped = None
        try:
            kwargs = {}
            if isinstance(x_ref, str):
                kwargs["x_axis_index"] = self._axis_index(x_ref, "x")
            if isinstance(y_ref, str):
                kwargs["y_axis_index"] = self._axis_index(y_ref, "y")
            if isinstance(coord, GridCoord):
                mapped = coord.mapPoint(x, y, **kwargs)
            else:
                mapped = coord.mapPoint(x, y)
        except Exception:
            mapped = None
        px = paper_x if x_paper else (mapped.x() if mapped is not None else None)
        py = paper_y if y_paper else (mapped.y() if mapped is not None else None)
        if px is None or py is None:
            return None
        return QPointF(px, py)

    def _paper_rect(self, coord) -> QRectF:
        """``paper`` 参照系：优先绘图区，其次坐标系矩形，最后内容区。"""
        if coord is not None:
            plot = getattr(coord, "plot", None)
            if isinstance(plot, QRectF) and not plot.isNull():
                return QRectF(plot)
            rect = getattr(coord, "rect", None)
            if isinstance(rect, QRectF) and not rect.isNull():
                return QRectF(rect)
        if not self._rect.isNull():
            return QRectF(self._rect)
        return QRectF(self.chart.rect())

    def _read_offsets(self) -> tuple:
        show_arrow = bool(self.opt.get("showarrow", True))
        ax = _to_float(self.opt.get("ax"), None)
        ay = _to_float(self.opt.get("ay"), None)
        if ax is None:
            ax = 0.0
        if ay is None:
            ay = -40.0 if show_arrow else 0.0
        return ax, ay

    def _read_style(self) -> None:
        font_opt = self.opt.get("font")
        if isinstance(font_opt, dict):
            # Plotly 的 font 用 size / family；ECharts 用 fontSize / fontFamily。
            font_opt = dict(font_opt)
            if "fontSize" not in font_opt and "size" in font_opt:
                font_opt["fontSize"] = font_opt.get("size")
            if "fontFamily" not in font_opt and "family" in font_opt:
                font_opt["fontFamily"] = font_opt.get("family")
        style = merged_text_style(self.chart, font_opt)
        size = style.get("fontSize", T("font.sm"))
        self._font = chartFont(
            size,
            text_weight(style.get("fontWeight")),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )
        color = (
            parse_color(style.get("color") or self.opt.get("color"))
            if (style.get("color") or self.opt.get("color"))
            else QColor()
        )
        if not color.isValid():
            color = QColor(T("color.text.primary", self.chart))
        self._text_color = color

        bg_value = self.opt.get("bgcolor", self.opt.get("backgroundColor"))
        if bg_value is None:
            bg = QColor(T("color.bg.elevated", self.chart))
            bg.setAlpha(235)
        elif _is_no_color(bg_value):
            bg = QColor(0, 0, 0, 0)
        else:
            bg = parse_color(bg_value)
            if not bg.isValid():
                bg = QColor(T("color.bg.elevated", self.chart))
                bg.setAlpha(235)
        self._bg = bg

        border_value = self.opt.get("bordercolor", self.opt.get("borderColor"))
        if border_value is None:
            border = QColor(T("color.border.strong", self.chart))
            border.setAlpha(140)
        elif _is_no_color(border_value):
            border = QColor()
        else:
            border = parse_color(border_value)
        self._border = border
        border_width = _to_float(
            self.opt.get("borderwidth", self.opt.get("borderWidth")), 1.0
        )
        self._border_width = max(0.0, border_width) if border.isValid() else 0.0

        pad_value = self.opt.get("borderpad", self.opt.get("padding", 4.0))
        if isinstance(pad_value, (list, tuple)):
            pads = [_to_float(item, 0.0) for item in pad_value]
            if len(pads) >= 2:
                self._pad_y, self._pad_x = pads[0], pads[1]
            elif pads:
                self._pad_x = self._pad_y = pads[0]
        else:
            self._pad_x = self._pad_y = _to_float(pad_value, 4.0)
        self._pad_x = clamp(self._pad_x, 0.0, 40.0)
        self._pad_y = clamp(self._pad_y, 0.0, 40.0)

        self._radius = clamp(_to_float(self.opt.get("borderRadius"), 4.0), 0.0, 40.0)
        self._opacity = clamp(_to_float(self.opt.get("opacity"), 1.0), 0.0, 1.0)
        align = str(self.opt.get("align") or "center").strip().lower()
        self._align = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "right": Qt.AlignmentFlag.AlignRight,
        }.get(align, Qt.AlignmentFlag.AlignHCenter)
        xanchor = str(self.opt.get("xanchor") or "center").strip().lower()
        self._xanchor = xanchor if xanchor in ("left", "center", "right") else "center"
        yanchor = str(self.opt.get("yanchor") or "middle").strip().lower()
        self._yanchor = yanchor if yanchor in ("top", "middle", "bottom") else "middle"

        self._show_arrow = bool(self.opt.get("showarrow", True))
        arrow_color = (
            parse_color(self.opt.get("arrowcolor"))
            if self.opt.get("arrowcolor")
            else QColor()
        )
        self._arrow_color = (
            arrow_color if arrow_color.isValid() else parse_color(self._text_color)
        )
        self._arrow_width = max(0.5, _to_float(self.opt.get("arrowwidth"), 1.5))
        self._arrow_size = clamp(_to_float(self.opt.get("arrowsize"), 8.0), 2.0, 30.0)
        try:
            self._arrow_head = int(_to_float(self.opt.get("arrowhead"), 2.0))
        except (TypeError, ValueError, OverflowError):
            self._arrow_head = 2
        self._standoff = clamp(_to_float(self.opt.get("standoff"), 2.0), 0.0, 20.0)

    def _rebuild_geometry(self, text: str = None) -> None:
        if text is None:
            text = self._text()
        self._lines = text.split("\n") if text else []
        if not self._lines or self._font is None:
            self._box = QRectF()
            self._arrow_start = None
            self._arrow_end = None
            return
        fm = QFontMetricsF(self._font)
        text_w = max((fm.horizontalAdvance(line) for line in self._lines), default=0.0)
        line_h = fm.height()
        width = max(8.0, text_w + self._pad_x * 2.0)
        height = max(8.0, line_h * len(self._lines) + self._pad_y * 2.0)
        center = QPointF(self._anchor.x() + self._ax, self._anchor.y() + self._ay)
        left = center.x() - width / 2.0
        if self._xanchor == "left":
            left = center.x()
        elif self._xanchor == "right":
            left = center.x() - width
        top = center.y() - height / 2.0
        if self._yanchor == "top":
            top = center.y()
        elif self._yanchor == "bottom":
            top = center.y() - height
        self._box = QRectF(left, top, width, height)
        self._radius = min(self._radius, min(width, height) / 2.0)
        self._arrow_end = QPointF(self._anchor)
        self._arrow_start = None
        if self._show_arrow and not self._box.contains(self._anchor):
            edge = _rect_edge_point(self._box, self._anchor)
            dx = self._anchor.x() - edge.x()
            dy = self._anchor.y() - edge.y()
            distance = math.hypot(dx, dy)
            if distance > 1e-6:
                offset = min(self._standoff, max(0.0, distance - 1.0))
                self._arrow_start = QPointF(
                    edge.x() + dx / distance * offset,
                    edge.y() + dy / distance * offset,
                )
            else:
                self._arrow_start = edge

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._visible or self._box.isNull():
            return
        p.save()
        try:
            if self._opacity < 1.0:
                p.setOpacity(self._opacity)
            if (
                self._show_arrow
                and self._arrow_start is not None
                and self._arrow_end is not None
            ):
                self._paint_arrow(p)
            self._paint_box(p)
            self._paint_text(p)
        finally:
            p.restore()

    def _paint_arrow(self, p: QPainter) -> None:
        start = self._arrow_start
        end = self._arrow_end
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return
        ux, uy = dx / length, dy / length
        head = min(self._arrow_size, length * 0.8)
        line_end = QPointF(end.x() - ux * head * 0.85, end.y() - uy * head * 0.85)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(
            QPen(
                self._arrow_color,
                self._arrow_width,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
        )
        p.drawLine(start, line_end)
        if self._arrow_head <= 0 or head <= 0.5:
            return
        px, py = -uy, ux
        base = QPointF(end.x() - ux * head, end.y() - uy * head)
        half = head * 0.45
        if self._arrow_head == 1:
            # 开放式箭头：只画两条边
            p.drawLine(end, QPointF(base.x() + px * half, base.y() + py * half))
            p.drawLine(end, QPointF(base.x() - px * half, base.y() - py * half))
            return
        if self._arrow_head == 3:
            p.setPen(QPen(Qt.PenStyle.NoPen))
            p.setBrush(self._arrow_color)
            p.drawEllipse(end, head * 0.35, head * 0.35)
            return
        # 实心三角（默认）
        path = QPainterPath(end)
        path.lineTo(base.x() + px * half, base.y() + py * half)
        path.lineTo(base.x() - px * half, base.y() - py * half)
        path.closeSubpath()
        p.setPen(QPen(Qt.PenStyle.NoPen))
        p.setBrush(self._arrow_color)
        p.drawPath(path)

    def _paint_box(self, p: QPainter) -> None:
        if self._bg.alpha() > 0:
            p.setPen(QPen(Qt.PenStyle.NoPen))
            p.setBrush(self._bg)
            p.drawRoundedRect(self._box, self._radius, self._radius)
        if self._border_width > 0.0 and self._border.isValid():
            half = self._border_width / 2.0
            rect = self._box.adjusted(half, half, -half, -half)
            radius = max(0.0, self._radius - half)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(self._border, self._border_width))
            p.drawRoundedRect(rect, radius, radius)

    def _paint_text(self, p: QPainter) -> None:
        if self._font is None:
            return
        p.setFont(self._font)
        p.setPen(self._text_color)
        p.setBrush(Qt.BrushStyle.NoBrush)
        fm = QFontMetricsF(self._font)
        line_h = fm.height()
        flags = int(self._align | Qt.AlignmentFlag.AlignVCenter) | int(
            Qt.TextFlag.TextSingleLine
        )
        for index, line in enumerate(self._lines):
            rect = QRectF(
                self._box.left() + self._pad_x,
                self._box.top() + self._pad_y + index * line_h,
                max(1.0, self._box.width() - self._pad_x * 2.0),
                line_h,
            )
            p.drawText(rect, flags, line)

    def onMousePress(self, pos: QPointF) -> bool:
        if (
            getattr(self.chart, "_press_button", Qt.MouseButton.LeftButton)
            != Qt.MouseButton.LeftButton
        ):
            return False
        if not self.boxHitTest(pos):
            return False
        self._dragging = True
        self._drag_moved = False
        self._grab_delta = QPointF(pos) - self._box.center()
        chart = self.chart
        chart.tooltip.hide()
        clear_axis = getattr(chart, "_tooltip_axis_clear", None)
        if callable(clear_axis):
            try:
                clear_axis()
            except Exception:
                pass
        try:
            chart._clear_hover()
        except Exception:
            pass
        chart.setCursor(Qt.CursorShape.ClosedHandCursor)
        chart.update()
        return True

    def onMouseMove(self, pos: QPointF) -> bool:
        if self._dragging:
            self._move_to(pos)
            return True
        hovered = self.boxHitTest(pos)
        if hovered and not self._hovered:
            self._hovered = True
            self.chart.tooltip.hide()
            clear_axis = getattr(self.chart, "_tooltip_axis_clear", None)
            if callable(clear_axis):
                try:
                    clear_axis()
                except Exception:
                    pass
            try:
                self.chart._clear_hover()
            except Exception:
                pass
            self.chart.update()
        elif not hovered:
            self._hovered = False
        return hovered

    def onMouseRelease(self, pos: QPointF) -> bool:
        if not self._dragging:
            return False
        self._dragging = False
        self._hovered = self.boxHitTest(pos)
        self._write_offsets()
        self._rebuild_geometry()
        self.chart.update()
        if self._drag_moved:
            self._drag_moved = False
            try:
                self.chart.annotationDragged.emit(self._drag_payload())
            except Exception:
                pass
        return True

    def _move_to(self, pos: QPointF) -> None:
        box_center = QPointF(pos) - self._grab_delta
        chart = self.chart
        half_w = self._box.width() / 2.0
        half_h = self._box.height() / 2.0
        margin = 2.0
        if self._box.width() + margin * 2.0 <= chart.width():
            box_center.setX(
                clamp(box_center.x(), margin + half_w, chart.width() - margin - half_w)
            )
        else:
            box_center.setX(chart.width() / 2.0)
        if self._box.height() + margin * 2.0 <= chart.height():
            box_center.setY(
                clamp(box_center.y(), margin + half_h, chart.height() - margin - half_h)
            )
        else:
            box_center.setY(chart.height() / 2.0)
        # ax / ay 是「箭头尾部」相对锚点的偏移，不是文本框中心（xanchor /
        # yanchor 会把框摆到尾部的一侧）。
        tail = QPointF(self._anchor.x() + self._ax, self._anchor.y() + self._ay)
        center_offset = self._box.center() - tail
        new_tail = box_center - center_offset
        ax = new_tail.x() - self._anchor.x()
        ay = new_tail.y() - self._anchor.y()
        if abs(ax - self._ax) > 0.01 or abs(ay - self._ay) > 0.01:
            self._drag_moved = True
        self._ax = ax
        self._ay = ay
        self._write_offsets()
        self._rebuild_geometry()
        chart.update()

    def _write_offsets(self) -> None:
        ax = round(float(self._ax), 3)
        ay = round(float(self._ay), 3)
        self.opt["ax"] = ax
        self.opt["ay"] = ay
        try:
            self._source["ax"] = ax
            self._source["ay"] = ay
        except Exception:
            pass

    def _drag_payload(self) -> dict:
        return {
            "index": self._scope_index(),
            "id": str(self.opt.get("id") or ""),
            "name": str(self.opt.get("name") or ""),
            "componentType": self.optionKey,
            "seriesName": str((self.series_opt or {}).get("name") or ""),
            "text": self._text(),
            "x": self.opt.get("x", 0),
            "y": self.opt.get("y", 0),
            "ax": round(float(self._ax), 3),
            "ay": round(float(self._ay), 3),
        }

    def _scope_index(self) -> int:
        comps = [
            comp
            for comp in getattr(self.chart, "_components", [])
            if str(getattr(comp, "optionKey", "")) == self.optionKey
            and getattr(comp, "series_opt", None) is self.series_opt
        ]
        try:
            return comps.index(self)
        except ValueError:
            return -1

    def _text(self) -> str:
        text = self.opt.get("text")
        if isinstance(text, (list, tuple)):
            text = "\n".join(str(part) for part in text)
        text = str(text or "")
        for token in ("<br />", "<br/>", "<br>"):
            text = text.replace(token, "\n")
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def _draggable(self) -> bool:
        return bool(self.opt.get("draggable", True))

    def dispose(self) -> None:
        self._dragging = False
        self._hovered = False
