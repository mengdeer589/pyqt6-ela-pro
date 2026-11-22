"""主题 × 系列能力矩阵（工作台「主题」区）。"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget
from PyQt6ElaWidgetTools import eTheme

from pyqt6_ela_pro.charts import (
    chartFont,
    chartThemeSpec,
    chartThemes,
    chartToken as T,
)
from pyqt6_ela_pro.charts._utils import parse_color

SERIES_ORDER = (
    "bar",
    "line",
    "pie",
    "scatter",
    "effectScatter",
    "candlestick",
    "boxplot",
    "pictorialBar",
    "heatmap",
    "funnel",
    "gauge",
    "radar",
    "graph",
    "tree",
    "treemap",
    "sunburst",
    "sankey",
    "themeRiver",
    "parallel",
    "lines",
    "map",
    "image",
    "gantt",
)

#: 能力顺序：label / visualMap / 选中 / 图例项 / 极坐标
CAPABILITY_KEYS = ("label", "visualMap", "select", "legend", "polar")
_CAP_SHORT = {
    "label": "L",
    "visualMap": "V",
    "select": "S",
    "legend": "G",
    "polar": "P",
}

_CAPS = {
    "bar": (1, 1, 1, 1, 1),
    "line": (1, 1, 1, 1, 1),
    "pie": (1, 1, 1, 1, 0),
    "scatter": (1, 1, 1, 1, 1),
    "effectScatter": (1, 1, 1, 1, 1),
    "candlestick": (1, 0, 0, 1, 0),
    "boxplot": (1, 0, 0, 1, 0),
    "pictorialBar": (1, 1, 1, 1, 0),
    "heatmap": (1, 1, 0, 1, 0),
    "funnel": (1, 0, 1, 1, 0),
    "gauge": (1, 0, 0, 1, 0),
    "radar": (1, 0, 0, 1, 0),
    "graph": (1, 0, 1, 1, 0),
    "tree": (1, 0, 0, 1, 0),
    "treemap": (1, 0, 1, 1, 0),
    "sunburst": (1, 0, 1, 1, 0),
    "sankey": (1, 0, 1, 1, 0),
    "themeRiver": (1, 0, 0, 1, 0),
    "parallel": (0, 0, 0, 1, 0),
    "lines": (0, 0, 0, 1, 0),
    "map": (1, 1, 1, 1, 0),
    "image": (0, 1, 0, 1, 0),
    "gantt": (1, 0, 0, 1, 0),
}


def capabilities(series_type: str) -> dict:
    """该系列的预览能力标记。"""
    flags = _CAPS.get(series_type, (0, 0, 0, 0, 0))
    return dict(zip(CAPABILITY_KEYS, (bool(v) for v in flags)))


def _named(values, names):
    return [{"name": name, "value": value} for name, value in zip(names, values)]


def _is_dark(mode) -> bool:
    return int(getattr(mode, "value", 0) or 0) == 1


def sample_option(series_type: str) -> dict:
    """矩阵单元格点击后的完整示例 option（不含主题）。"""
    kind = str(series_type)
    base = {"animation": False}
    categories = ["华东", "华南", "华北", "西南", "东北"]
    values = [320, 240, 180, 150, 210]

    if kind in ("bar", "line", "scatter", "effectScatter", "pictorialBar"):
        series = {"type": kind, "name": "示例", "data": values}
        if kind == "scatter":
            series["data"] = [[1, 3], [2, 5], [3, 2], [4, 7], [5, 4]]
            series["symbolSize"] = 14
        if kind == "effectScatter":
            series["data"] = [[1, 3], [2, 5], [3, 2], [4, 7], [5, 4]]
            series["symbolSize"] = 12
        if kind == "pictorialBar":
            series["symbol"] = "roundRect"
        return {
            **base,
            "tooltip": {"trigger": "axis"},
            "legend": {"top": 4},
            "xAxis": {"type": "category", "data": categories},
            "yAxis": {"type": "value"},
            "series": [series],
        }
    if kind == "candlestick":
        return {
            **base,
            "xAxis": {"type": "category", "data": categories},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": kind,
                    "name": "K",
                    "data": [
                        [20, 34, 10, 38],
                        [40, 35, 30, 50],
                        [31, 38, 33, 44],
                        [38, 15, 5, 42],
                        [30, 32, 25, 36],
                    ],
                }
            ],
        }
    if kind == "boxplot":
        return {
            **base,
            "xAxis": {"type": "category", "data": categories},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": kind,
                    "name": "分布",
                    "data": [
                        [10, 20, 30, 38, 50],
                        [5, 15, 28, 34, 45],
                        [12, 22, 31, 40, 52],
                        [8, 18, 26, 36, 48],
                        [15, 25, 35, 42, 55],
                    ],
                }
            ],
        }
    if kind == "heatmap":
        return {
            **base,
            "tooltip": {"trigger": "item"},
            "xAxis": {"type": "category", "data": ["周一", "周二", "周三"]},
            "yAxis": {"type": "category", "data": ["上午", "下午"]},
            "visualMap": {"min": 0, "max": 10, "show": False},
            "series": [
                {
                    "type": kind,
                    "name": "活跃度",
                    "data": [
                        [0, 0, 3],
                        [1, 0, 7],
                        [2, 0, 5],
                        [0, 1, 8],
                        [1, 1, 2],
                        [2, 1, 9],
                    ],
                }
            ],
        }
    if kind in ("pie", "funnel"):
        return {
            **base,
            "tooltip": {"trigger": "item"},
            "legend": {"top": 4},
            "series": [
                {
                    "type": kind,
                    "name": "占比",
                    "radius": ["35%", "66%"] if kind == "pie" else None,
                    "data": _named([42, 28, 18, 12], ["A", "B", "C", "D"]),
                }
            ],
        }
    if kind == "gauge":
        return {
            **base,
            "series": [
                {
                    "type": kind,
                    "name": "完成率",
                    "min": 0,
                    "max": 100,
                    "data": [{"name": "完成率", "value": 72}],
                }
            ],
        }
    if kind == "radar":
        return {
            **base,
            "series": [
                {
                    "type": kind,
                    "name": "能力",
                    "indicator": [
                        {"name": "性能", "max": 100},
                        {"name": "体积", "max": 100},
                        {"name": "易用", "max": 100},
                        {"name": "扩展", "max": 100},
                        {"name": "稳定", "max": 100},
                    ],
                    "data": [
                        {"name": "当前", "value": [85, 62, 90, 74, 88]},
                    ],
                }
            ],
        }
    if kind == "graph":
        return {
            **base,
            "series": [
                {
                    "type": kind,
                    "name": "关系",
                    "data": [
                        {"name": "A", "value": 10},
                        {"name": "B", "value": 8},
                        {"name": "C", "value": 6},
                        {"name": "D", "value": 5},
                    ],
                    "links": [
                        {"source": "A", "target": "B", "value": 4},
                        {"source": "A", "target": "C", "value": 3},
                        {"source": "B", "target": "D", "value": 2},
                    ],
                }
            ],
        }
    if kind in ("tree", "treemap", "sunburst"):
        return {
            **base,
            "series": [
                {
                    "type": kind,
                    "name": "层级",
                    "data": [
                        {
                            "name": "根",
                            "children": [
                                {"name": "甲", "value": 30},
                                {"name": "乙", "value": 24},
                                {
                                    "name": "丙",
                                    "children": [
                                        {"name": "丙-1", "value": 14},
                                        {"name": "丙-2", "value": 10},
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    if kind == "sankey":
        return {
            **base,
            "series": [
                {
                    "type": kind,
                    "name": "流向",
                    "data": [
                        {"name": "来源"},
                        {"name": "清洗"},
                        {"name": "分析"},
                        {"name": "报表"},
                    ],
                    "links": [
                        {"source": "来源", "target": "清洗", "value": 12},
                        {"source": "清洗", "target": "分析", "value": 9},
                        {"source": "分析", "target": "报表", "value": 7},
                        {"source": "清洗", "target": "报表", "value": 3},
                    ],
                }
            ],
        }
    if kind == "themeRiver":
        return {
            **base,
            "singleAxis": {
                "type": "category",
                "data": ["一", "二", "三", "四", "五"],
            },
            "series": [
                {
                    "type": kind,
                    "name": "主题河",
                    "data": [
                        ["一", 5, "A"],
                        ["二", 7, "A"],
                        ["三", 6, "A"],
                        ["四", 9, "A"],
                        ["五", 8, "A"],
                        ["一", 4, "B"],
                        ["二", 3, "B"],
                        ["三", 5, "B"],
                        ["四", 4, "B"],
                        ["五", 6, "B"],
                    ],
                }
            ],
        }
    if kind == "parallel":
        return {
            **base,
            "parallelAxis": [
                {"name": "性能"},
                {"name": "体积"},
                {"name": "易用"},
                {"name": "稳定"},
            ],
            "series": [
                {
                    "type": kind,
                    "name": "并行",
                    "data": [
                        [85, 62, 90, 74],
                        [70, 80, 66, 88],
                        [92, 55, 78, 70],
                    ],
                }
            ],
        }
    if kind == "lines":
        return {
            **base,
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": kind,
                    "name": "轨迹",
                    "data": [
                        [[0, 0], [3, 4]],
                        [[1, 4], [4, 1]],
                        [[2, 1], [5, 3]],
                    ],
                }
            ],
        }
    if kind == "map":
        return {
            **base,
            "visualMap": {"min": 0, "max": 100, "show": False},
            "series": [
                {
                    "type": kind,
                    "name": "区域",
                    "map": "demo",
                    "data": _named(
                        [90, 70, 50, 30, 60, 40, 80],
                        ["华北", "东北", "华东", "华南", "华中", "西南", "西北"],
                    ),
                }
            ],
        }
    if kind == "image":
        matrix = [
            [0.0, 0.2, 0.4, 0.6],
            [0.1, 0.3, 0.5, 0.7],
            [0.2, 0.4, 0.6, 0.8],
        ]
        return {
            **base,
            "xAxis": {"type": "value", "min": 0, "max": 4},
            "yAxis": {"type": "value", "min": 0, "max": 3},
            "visualMap": {"min": 0, "max": 1, "show": False},
            "series": [
                {
                    "type": kind,
                    "name": "矩阵",
                    "data": matrix,
                    "extent": [0, 4, 0, 3],
                }
            ],
        }
    if kind == "gantt":
        return {
            **base,
            "xAxis": {"type": "time"},
            "yAxis": {
                "type": "category",
                "data": ["设计", "开发", "测试", "发布"],
            },
            "series": [
                {
                    "type": kind,
                    "name": "计划",
                    "data": [
                        {
                            "name": "设计",
                            "start": "2026-11-02",
                            "end": "2026-11-06",
                            "progress": 1.0,
                        },
                        {
                            "name": "开发",
                            "start": "2026-11-06",
                            "end": "2026-11-15",
                            "progress": 0.8,
                        },
                        {
                            "name": "测试",
                            "start": "2026-11-15",
                            "end": "2026-11-20",
                            "progress": 0.4,
                        },
                        {
                            "name": "发布",
                            "start": "2026-11-21",
                            "end": "2026-11-21",
                            "milestone": True,
                        },
                    ],
                }
            ],
        }
    return {**base, "series": [{"type": kind, "data": values}]}


class ThemeMatrixWidget(QWidget):
    """23 系列 × 当前主题列表的能力矩阵；只绘制视口内的行。"""

    #: (seriesType, themeName)
    cellActivated = pyqtSignal(str, str)

    ROW_H = 54
    HEADER_H = 38
    LABEL_W = 128
    CELL_GAP = 4
    DOT = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._themes = list(chartThemes())
        self._series = list(SERIES_ORDER)
        self._hover = None
        self.setMouseTracking(True)
        self.setMinimumHeight(self.HEADER_H + len(self._series) * self.ROW_H + 8)
        self.setMinimumWidth(760)
        self.setAccessibleName("主题系列能力矩阵")
        self.setAccessibleDescription(
            "每个格子是一种系列在一种主题下的缩略预览；底部五个圆点依次表示 "
            "数据标签、visualMap、选中、图例项、极坐标支持情况。"
        )

    def themes(self) -> list:
        return list(self._themes)

    def seriesTypes(self) -> list:
        return list(self._series)

    def sizeHint(self) -> QSize:
        return QSize(900, self.minimumHeight())

    def minimumSizeHint(self) -> QSize:
        return QSize(760, 320)

    def _columns(self) -> int:
        return max(1, len(self._themes))

    def _cell_rect(self, row: int, col: int) -> QRectF:
        left = self.LABEL_W
        width = max(1.0, self.width() - left - 8.0)
        cell_w = width / self._columns()
        top = self.HEADER_H + row * self.ROW_H
        return QRectF(
            left + col * cell_w + self.CELL_GAP / 2,
            top + 4,
            max(1.0, cell_w - self.CELL_GAP),
            self.ROW_H - 8,
        )

    def _hit(self, pos: QPointF):
        if pos.x() < self.LABEL_W or pos.y() < self.HEADER_H:
            return None
        row = int((pos.y() - self.HEADER_H) // self.ROW_H)
        col = int(
            (pos.x() - self.LABEL_W)
            / max(1.0, (self.width() - self.LABEL_W - 8.0) / self._columns())
        )
        if 0 <= row < len(self._series) and 0 <= col < len(self._themes):
            return row, col
        return None

    def paintEvent(self, event) -> None:
        try:
            self._paint(event)
        except Exception:
            # paintEvent 异常穿过 Qt 边界会终止进程；这里只丢弃本帧。
            pass

    def _paint(self, event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            mode = eTheme.getThemeMode()
            text = parse_color(T("color.text.primary", self))
            muted = parse_color(T("color.text.secondary", self))
            title_font = chartFont(11, 600, self.font().family())
            body_font = chartFont(11, None, self.font().family())
            p.setFont(title_font)
            clip = QRectF(event.rect())
            # 主题列头
            p.setPen(muted)
            for col, theme in enumerate(self._themes):
                rect = self._cell_rect(-1, col)
                rect = QRectF(rect.left(), 4, rect.width(), self.HEADER_H - 8)
                p.setPen(muted)
                p.drawText(
                    rect,
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    theme,
                )
                spec = chartThemeSpec(theme)
                palette = (spec.palette_dark if _is_dark(mode) else spec.palette) or []
                sw = 7.0
                total = sw * min(3, len(palette)) + 2.0 * max(
                    0, min(3, len(palette)) - 1
                )
                x = rect.center().x() - total / 2
                y = rect.top() + 3
                for color in palette[:3]:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(parse_color(color))
                    p.drawRoundedRect(QRectF(x, y, sw, 3), 1.0, 1.0)
                    x += sw + 2.0

            first = max(0, int((clip.top() - self.HEADER_H) // self.ROW_H))
            last = min(
                len(self._series) - 1,
                int((clip.bottom() - self.HEADER_H) // self.ROW_H),
            )
            for row in range(first, last + 1):
                self._paint_row(p, row, text, muted, body_font, mode)
        finally:
            p.end()

    def _paint_row(self, p, row, text, muted, font, mode) -> None:
        y = self.HEADER_H + row * self.ROW_H
        kind = self._series[row]
        if row % 2:
            stripe = parse_color(T("color.bg.muted", self))
            stripe.setAlpha(40)
            p.fillRect(QRectF(0, y, self.width(), self.ROW_H), stripe)
        p.setFont(font)
        p.setPen(text)
        p.drawText(
            QRectF(8, y, self.LABEL_W - 12, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            kind,
        )
        caps = capabilities(kind)
        p.setPen(muted)
        p.drawText(
            QRectF(8, y + 22, self.LABEL_W - 12, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            " · ".join(_CAP_SHORT[name] for name, on in caps.items() if on) or "基础",
        )
        for col, theme in enumerate(self._themes):
            rect = self._cell_rect(row, col)
            self._paint_cell(p, rect, kind, theme, mode, caps)

    def _paint_cell(self, p, rect, kind, theme, mode, caps) -> None:
        spec = chartThemeSpec(theme)
        theme_map = (spec.dark if _is_dark(mode) else spec.light) or {}
        bg = parse_color(
            theme_map.get("color.bg.elevated")
            or theme_map.get("color.bg.base")
            or T("color.bg.elevated", self)
        )
        fg = parse_color(
            theme_map.get("color.text.primary") or T("color.text.primary", self)
        )
        border = parse_color(theme_map.get("color.border") or T("color.border", self))
        p.setPen(QPen(border, 1.0))
        p.setBrush(bg)
        p.drawRoundedRect(rect, 5.0, 5.0)

        palette = [
            parse_color(c)
            for c in (spec.palette_dark if _is_dark(mode) else spec.palette)
        ] or [fg]
        glyph = rect.adjusted(10, 6, -10, -14)
        self._paint_glyph(p, glyph, kind, palette)

        # 能力圆点：label / visualMap / 选中 / 图例项 / 极坐标
        total = len(caps) * self.DOT * 2 - self.DOT
        x = rect.center().x() - total / 2
        y = rect.bottom() - 7
        for name in CAPABILITY_KEYS:
            color = QColor(palette[0])
            if not caps[name]:
                color = QColor(border)
                color.setAlpha(120)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(QPointF(x + self.DOT / 2, y), self.DOT / 2, self.DOT / 2)
            x += self.DOT * 2

    def _paint_glyph(self, p, rect, kind, palette) -> None:
        p.setPen(QPen(palette[0], 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind in ("bar", "pictorialBar", "gantt"):
            w = rect.width() / 4.0
            for i, frac in enumerate((0.55, 0.9, 0.4, 0.75)):
                h = rect.height() * frac
                p.setBrush(palette[i % len(palette)])
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(
                    QRectF(
                        rect.left() + i * w,
                        rect.bottom() - h,
                        max(2.0, w - 3),
                        h,
                    ),
                    1.5,
                    1.5,
                )
        elif kind in ("line", "lines", "themeRiver"):
            path = QPainterPath(
                QPointF(rect.left(), rect.bottom() - rect.height() * 0.3)
            )
            path.lineTo(
                rect.left() + rect.width() * 0.3,
                rect.top() + rect.height() * 0.55,
            )
            path.lineTo(
                rect.left() + rect.width() * 0.6,
                rect.top() + rect.height() * 0.25,
            )
            path.lineTo(rect.right(), rect.top() + rect.height() * 0.6)
            p.drawPath(path)
            if kind == "themeRiver":
                path.lineTo(rect.right(), rect.bottom())
                path.lineTo(rect.left(), rect.bottom())
                fill = QColor(palette[0])
                fill.setAlpha(70)
                p.fillPath(path, fill)
        elif kind in ("scatter", "effectScatter"):
            for i, (fx, fy) in enumerate(
                ((0.15, 0.7), (0.38, 0.3), (0.62, 0.62), (0.85, 0.2))
            ):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(palette[i % len(palette)])
                p.drawEllipse(
                    QPointF(
                        rect.left() + fx * rect.width(),
                        rect.top() + fy * rect.height(),
                    ),
                    2.4,
                    2.4,
                )
        elif kind in ("pie", "funnel", "gauge", "radar", "sunburst"):
            p.setPen(QPen(palette[0], 1.4))
            p.setBrush(QColor(palette[0]))
            p.drawEllipse(rect.center(), 6.0, 6.0)
            if len(palette) > 1:
                p.setBrush(QColor(palette[1]))
                p.drawEllipse(
                    QPointF(rect.center().x() + 7, rect.center().y()),
                    4.0,
                    4.0,
                )
        elif kind in ("candlestick", "boxplot"):
            cx = rect.center().x()
            p.setPen(QPen(palette[0], 1.4))
            p.drawLine(QPointF(cx, rect.top()), QPointF(cx, rect.bottom()))
            p.setBrush(palette[0])
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(
                QRectF(cx - 4, rect.top() + rect.height() * 0.3, 8, 5),
                1.0,
                1.0,
            )
            if len(palette) > 1:
                p.setBrush(palette[1])
                p.drawRoundedRect(
                    QRectF(cx - 4, rect.top() + rect.height() * 0.6, 8, 5),
                    1.0,
                    1.0,
                )
        elif kind == "heatmap":
            for r in range(2):
                for c in range(3):
                    color = QColor(palette[(r + c) % len(palette)])
                    color.setAlpha(150)
                    p.setBrush(color)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawRect(
                        QRectF(
                            rect.left() + c * rect.width() / 3 + 1,
                            rect.top() + r * rect.height() / 2 + 1,
                            max(2.0, rect.width() / 3 - 2),
                            max(2.0, rect.height() / 2 - 2),
                        )
                    )
        elif kind == "map":
            poly = QPainterPath(QPointF(rect.left() + 4, rect.bottom() - 4))
            poly.lineTo(rect.left() + rect.width() * 0.25, rect.top() + 3)
            poly.lineTo(rect.left() + rect.width() * 0.55, rect.top() + 7)
            poly.lineTo(rect.left() + rect.width() * 0.75, rect.top() + 1)
            poly.lineTo(rect.right() - 3, rect.top() + rect.height() * 0.4)
            poly.lineTo(rect.right() - 6, rect.top() + rect.height() * 0.75)
            poly.lineTo(rect.left() + 6, rect.bottom() - 2)
            fill = QColor(palette[0])
            fill.setAlpha(120)
            p.setBrush(fill)
            p.drawPath(poly)
        elif kind == "image":
            for i in range(3):
                color = QColor(palette[i % len(palette)])
                color.setAlpha(180)
                p.fillRect(
                    QRectF(
                        rect.left() + i * rect.width() / 3,
                        rect.top() + i * 2,
                        max(2.0, rect.width() / 3),
                        max(2.0, rect.height() - i * 2),
                    ),
                    color,
                )
        elif kind == "parallel":
            for i in range(4):
                x = rect.left() + i * rect.width() / 3
                p.setPen(QPen(palette[0], 1.0))
                p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            p.setPen(QPen(palette[0], 1.2))
            path = QPainterPath(QPointF(rect.left(), rect.top() + rect.height() * 0.4))
            path.lineTo(
                rect.left() + rect.width() / 3, rect.top() + rect.height() * 0.7
            )
            path.lineTo(
                rect.left() + rect.width() * 0.66, rect.top() + rect.height() * 0.25
            )
            path.lineTo(rect.right(), rect.top() + rect.height() * 0.55)
            p.drawPath(path)
        else:
            p.drawRoundedRect(rect.adjusted(2, 1, -2, -1), 2.0, 2.0)
            p.setBrush(palette[0])
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(rect.center(), 3.0, 3.0)

    def mouseMoveEvent(self, event) -> None:
        try:
            hit = self._hit(QPointF(event.position()))
            self._hover = hit
            if hit is None:
                self.setToolTip("")
            else:
                kind = self._series[hit[0]]
                theme = self._themes[hit[1]]
                caps = capabilities(kind)
                detail = " / ".join(
                    f"{name}={'支持' if on else '不支持'}" for name, on in caps.items()
                )
                self.setToolTip(f"{kind} × {theme}\n{detail}\n点击打开完整示例")
        except Exception:
            pass

    def mousePressEvent(self, event) -> None:
        try:
            if event.button() != Qt.MouseButton.LeftButton:
                return
            hit = self._hit(QPointF(event.position()))
            if hit is not None:
                self.cellActivated.emit(self._series[hit[0]], self._themes[hit[1]])
        except Exception:
            pass
