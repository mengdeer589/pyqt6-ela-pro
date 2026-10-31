"""提示框组件（item / axis 两种触发）。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from collections import defaultdict
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import (
    QPointF,
    QRectF,
    Qt,
)
from PyQt6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPen,
)

from .._tokens import (
    T,
)
from .._utils import merged_text_style, parse_color, text_italic, text_weight
from ..axes import (
    GridCoord,
    chartFont,
    formatValue,
)

if TYPE_CHECKING:
    from .widget import ElaChartWidget


def _default_tooltip_title(raw) -> str:
    """ISO 日期 → 中文日期（``"2026-09-02"`` → ``"2026年9月2日"``）。"""
    text = str(raw or "")
    parts = text.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{int(parts[0])}年{int(parts[1])}月{int(parts[2])}日"
    return text


class Tooltip:
    """提示框组件（ECharts ``tooltip``）。

    ``trigger`` 取 ``"item"``（默认）/ ``"axis"`` / ``"none"``；``formatter`` 是
    callable(params) 或 ``{a}/{b}/{c}`` 模板，可返回 ``[标题, 内容]``；
    ``valueFormatter`` 作用于默认内容里的数值。``axisPointer.type`` 取
    ``line`` / ``shadow`` / ``cross`` / ``none``，外观键回退顶层 ``textStyle``。
    """

    def __init__(self, chart: "ElaChartWidget", opt: dict = None):
        self.chart = chart
        self.opt = {"show": True, "trigger": "item"}
        self.setOption(opt)
        self._active = False
        self._pos = QPointF()  # 鼠标位置（跟随）
        self._marker_pos = None  # 十字线锚点（None 用 _pos）
        self._lines = []  # [(QColor, name, value_str)]
        self._markers = []  # axis 模式：每条系列命中点的 [(QPointF, QColor)]
        self._axis_pointer = False  # 只有 axis 触发才画指示线（ECharts 语义）
        self._axis_label = None  # 轴上数值气泡文案（axisPointer.label）
        self._coord = None  # 本帧 axis 提示所属坐标系（多网格）
        self._x_axis_index = 0

    def setOption(self, opt: dict) -> None:
        if isinstance(opt, dict):
            merged = {"show": True, "trigger": "item"}
            merged.update(opt)
            self.opt = merged
        else:
            self.opt = {"show": True, "trigger": "item"}

    # -- option 取值 -------------------------------------------------------
    def textStyle(self) -> dict:
        """浮层文字样式（组件级优先，未设置的键回退顶层 ``textStyle``）。"""
        return merged_text_style(self.chart, self.opt.get("textStyle"))

    def _font(self, size_delta: float = 0.0):
        """浮层字体（字号回退 font.xs，含 fontWeight）。"""
        style = self.textStyle()
        try:
            size = float(style.get("fontSize", T("font.xs"))) - float(size_delta)
        except (TypeError, ValueError, OverflowError):
            size = float(T("font.xs")) - float(size_delta)
        return chartFont(
            size,
            text_weight(style.get("fontWeight")),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )

    def axisPointerType(self) -> str:
        ap = self.opt.get("axisPointer")
        kind = str((ap or {}).get("type") or "line") if isinstance(ap, dict) else "line"
        return kind if kind in ("line", "shadow", "cross", "none") else "line"

    def axisPointerLabelOption(self) -> dict:
        """``axisPointer.label``（show / 颜色 / 字号 / formatter）。"""
        ap = self.opt.get("axisPointer")
        label = ap.get("label") if isinstance(ap, dict) else None
        return label if isinstance(label, dict) else {}

    def axisPointerLineStyle(self) -> dict:
        """``axisPointer.lineStyle``（颜色 / 线宽 / 线型）。"""
        ap = self.opt.get("axisPointer")
        style = ap.get("lineStyle") if isinstance(ap, dict) else None
        return style if isinstance(style, dict) else {}

    def axisPointerSnap(self, category: bool) -> bool:
        """``axisPointer.snap``：auto = category 吸附、value 跟随光标。"""
        ap = self.opt.get("axisPointer")
        raw = (ap or {}).get("snap", "auto") if isinstance(ap, dict) else "auto"
        if isinstance(raw, str) and raw.strip().lower() == "auto":
            return bool(category)
        return bool(raw)

    def formatValueText(self, value) -> str:
        """按 ``valueFormatter`` 渲染数值（缺省走 ``formatValue``）。"""
        formatter = self.opt.get("valueFormatter")
        if callable(formatter):
            try:
                out = formatter(value)
                if out is not None:
                    return str(out)
            except Exception:
                pass
        elif isinstance(formatter, str):
            try:
                return formatter.format_map(defaultdict(str, {"value": value}))
            except Exception:
                pass
        return formatValue(value)

    @staticmethod
    def _safe_format(template: str, params: dict) -> Optional[str]:
        """``{}`` 模板安全替换（缺失键 → 空串；失败返回 None）。"""
        try:
            return template.format_map(defaultdict(str, params))
        except Exception:
            return None

    def buildLines(self, hit: dict, color, fallback_name: str = "") -> list:
        """命中结果 → 浮层行 ``[(color, name, value_str), ...]``。

        标题行走 ``(None, "", 标题)``（无圆点）；``hit["rows"]`` 提供多行内容
        （雷达逐维度行），``formatter`` 输出仍然优先。
        """
        name = str(hit.get("name") or hit.get("series") or fallback_name)
        series = str(hit.get("series") or fallback_name)
        value = hit.get("value")
        title_raw = hit.get("title")
        text_raw = hit.get("text")
        params = {
            "name": name,
            "series": series,
            "seriesName": series,
            "value": value,
            "dataIndex": hit.get("dataIndex"),
            "title": title_raw,
            "text": text_raw,
            "b": name,
            "a": series,
            "c": value,
        }
        title: Optional[str] = None
        if title_raw is not None:
            title = _default_tooltip_title(title_raw)
        text: Optional[str] = None
        # 数据项 tooltip.formatter 优先于系列 tooltip.formatter（ECharts 语义）
        formatter = hit.get("tooltipFormatter")
        if formatter is None:
            formatter = self.opt.get("formatter")
        formatted = None
        if callable(formatter):
            try:
                formatted = formatter(params)
            except Exception:
                formatted = None
        elif isinstance(formatter, str):
            formatted = self._safe_format(formatter, params)
        if formatted is not None:
            parts = [
                str(part)
                for part in (
                    formatted if isinstance(formatted, (list, tuple)) else [formatted]
                )
            ]
            if len(parts) >= 2:
                if title is None:
                    title = parts[0]
                text = parts[1]
            elif parts:
                text = parts[0]
        lines = []
        if title:
            lines.append((None, "", title))
        rows = hit.get("rows")
        if text:
            lines.append((color, "", text))
        elif formatted is None and isinstance(rows, (list, tuple)) and rows:
            # 命中方提供的结构化多行（雷达的「指标: 值」逐维度行）。
            # 有 formatter 输出时 formatter 优先（ECharts：formatter 覆盖默认排版）。
            for row in rows:
                if not isinstance(row, (list, tuple)) or len(row) != 2:
                    continue
                lines.append((color, str(row[0]), self.formatValueText(row[1])))
        elif value is not None:
            lines.append((color, name, self.formatValueText(value)))
        return lines

    @property
    def shown(self) -> bool:
        return bool(self.opt.get("show", True))

    @property
    def trigger(self) -> str:
        raw = str(self.opt.get("trigger") or "item")
        return raw if raw in ("item", "axis", "none") else "item"

    @property
    def active(self) -> bool:
        return self._active and bool(self._lines)

    # -- 状态 -------------------------------------------------------------
    def showAt(
        self,
        pos: QPointF,
        lines: list,
        marker_pos: QPointF = None,
        *,
        markers: list = None,
        axis_pointer: bool = False,
        axis_label: str = None,
        coord=None,
        x_axis_index: int = 0,
    ) -> None:
        """显示浮层。

        ``lines``: ``[(color, name, value_str), ...]``；``markers``: axis 模式下
        每条系列命中点；``axis_pointer``: 是否画指示线（item 触发不画）。
        """
        self._active = True
        self._pos = QPointF(pos)
        self._marker_pos = QPointF(marker_pos) if marker_pos is not None else None
        self._lines = list(lines or [])
        self._markers = list(markers or [])
        self._axis_pointer = bool(axis_pointer)
        self._axis_label = str(axis_label) if axis_label else None
        self._coord = coord
        self._x_axis_index = int(x_axis_index)

    def hide(self) -> None:
        self._active = False
        self._lines = []
        self._markers = []
        self._axis_pointer = False
        self._axis_label = None
        self._coord = None

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter) -> None:
        if not self.shown or not self.active:
            return
        # 十字线 / 指示线（axisPointer.type）：只有 axis 触发才画
        marker = self._marker_pos if self._marker_pos is not None else self._pos
        coord = self._coord or self.chart.primaryCoord()
        if (
            self._axis_pointer
            and coord is not None
            and self.axisPointerType() != "none"
        ):
            coord.paintTooltipMarker(
                p,
                marker,
                self.axisPointerType(),
                self._x_axis_index,
                self.axisPointerLineStyle(),
            )
        # axis 模式：每条系列在命中点画一个强调圆点（ECharts 同款）
        if self._axis_pointer and self._markers:
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            for point, color in self._markers:
                dot_color = parse_color(color)
                ring = QColor(T("color.bg.elevated"))
                p.setPen(QPen(ring, 1.6))
                p.setBrush(dot_color)
                p.drawEllipse(QPointF(point), 4.2, 4.2)
            p.restore()
        # 轴上数值气泡（axisPointer.label）
        if (
            self._axis_pointer
            and self._axis_label
            and self.axisPointerType() != "none"
            and isinstance(coord, GridCoord)
        ):
            try:
                self._paint_axis_label(p, coord, marker)
            except Exception:
                pass

        p.save()
        style = self.textStyle()
        font = self._font()
        p.setFont(font)
        fm = QFontMetricsF(font)
        pad_x, pad_y, line_gap, dot = 10.0, 8.0, 3.0, 8.0
        line_h = fm.height()
        rows = []
        for color, name, value in self._lines:
            label = f"{name}: {value}" if name else str(value)
            rows.append((color, label))
        text_w = max((fm.horizontalAdvance(t) for _, t in rows), default=0.0)
        w = pad_x * 2 + (dot + 5 if any(c is not None for c, _ in rows) else 0) + text_w
        h = pad_y * 2 + len(rows) * line_h + max(0, len(rows) - 1) * line_gap
        # 跟随鼠标：右侧偏移，越界翻转 / 收敛
        area = QRectF(0, 0, self.chart.width(), self.chart.height())
        x = self._pos.x() + 14
        y = self._pos.y() + 14
        if x + w > area.right() - 4:
            x = self._pos.x() - w - 14
        if y + h > area.bottom() - 4:
            y = self._pos.y() - h - 14
        x = min(max(x, 4.0), max(4.0, area.right() - w - 4))
        y = min(max(y, 4.0), max(4.0, area.bottom() - h - 4))
        box = QRectF(x, y, w, h)
        radius = float(T("radius.md"))
        # 近似阴影：三层外扩低透明度圆角矩形
        shadow_c = QColor(T("color.text.primary"))
        for i, alpha in ((6, 16), (4, 22), (2, 30)):
            sc = parse_color(shadow_c)
            sc.setAlpha(alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(sc)
            p.drawRoundedRect(
                box.translated(0, 2).adjusted(-i / 2, -i / 2, i / 2, i / 2),
                radius + i / 2,
                radius + i / 2,
            )
        # 浮层本体（ECharts 样式键 → 主题兜底）
        bg = self.opt.get("backgroundColor")
        border = self.opt.get("borderColor")
        try:
            border_w = max(0.0, float(self.opt.get("borderWidth", 1)))
        except (TypeError, ValueError, OverflowError):
            border_w = 1.0
        if border_w > 0:
            p.setPen(QPen(parse_color(border or T("color.border")), border_w))
        else:
            p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(parse_color(bg) if bg else QColor(T("color.bg.elevated")))
        p.drawRoundedRect(box, radius, radius)
        # 文本行（缩进仅对带圆点的行生效；标题行 color 为 None 不缩进）
        text_color = parse_color(style.get("color") or T("color.text.primary"))
        ty = box.top() + pad_y
        for color, label in rows:
            tx = box.left() + pad_x
            if color is not None:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(parse_color(color))
                p.drawEllipse(QRectF(tx, ty + line_h / 2 - dot / 2, dot, dot))
                tx += dot + 5
            p.setPen(text_color)
            p.drawText(
                QRectF(tx, ty, box.right() - pad_x - tx, line_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            ty += line_h + line_gap
        p.restore()

    def axisLabelText(self) -> str:
        """轴气泡文案（``axisPointer.label.formatter`` 应用后；空 = 不画）。"""
        text = self._axis_label
        if not text:
            return ""
        opt = self.axisPointerLabelOption()
        if opt.get("show", True) is False:
            return ""
        formatter = opt.get("formatter")
        if callable(formatter):
            try:
                out = formatter(text)
            except Exception:
                out = None
            if out is not None:
                return str(out)
        elif isinstance(formatter, str):
            return formatter.replace("{value}", text)
        return text

    def _paint_axis_label(self, p: QPainter, coord, anchor: QPointF) -> None:
        """在 x 轴线上画数值气泡（``axisPointer.label``）。"""
        opt = self.axisPointerLabelOption()
        text = self.axisLabelText()
        if not text:
            return
        style = merged_text_style(self.chart, opt)
        font = self._font(1.0)
        if style.get("fontSize") is not None or style.get("fontWeight") is not None:
            font = chartFont(
                style.get("fontSize") or font.pixelSize(),
                text_weight(style.get("fontWeight")),
                style.get("fontFamily"),
                text_italic(style.get("fontStyle")),
            )
        p.save()
        p.setFont(font)
        fm = QFontMetricsF(font)
        w = fm.horizontalAdvance(text) + 12
        h = fm.height() + 5
        plot = coord.plot
        x = min(max(anchor.x() - w / 2, plot.left()), plot.right() - w)
        y = plot.bottom() - h / 2
        box = QRectF(x, y, w, h)
        p.setPen(
            QPen(parse_color(opt.get("borderColor") or T("color.border.strong")), 1)
        )
        p.setBrush(parse_color(opt.get("backgroundColor") or T("color.bg.elevated")))
        p.drawRoundedRect(box, 3, 3)
        p.setPen(parse_color(style.get("color") or T("color.text.primary")))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()
