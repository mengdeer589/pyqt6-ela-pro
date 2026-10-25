"""日历坐标系。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


from datetime import date, timedelta

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QFontMetricsF, QPainter

from .._tokens import T
from .._utils import merged_text_style, single_option, text_italic, text_weight
from .._utils import parse_color
from ._shared import _MAX_DATE_YEAR, _MONTH_LABELS, _line_pen, _to_float, chartFont
from .base import Coord


class CalendarCoord(Coord):
    """日历坐标系：GitHub 式 周×星期 网格（ECharts ``calendar``）。

    option 键：``calendar``：``range``（``2026`` / ``"2026"`` /
    ``["2026-01-01", "2026-12-31"]``，缺省当前年）、``orient``
    （``"horizontal"`` 默认 / ``"vertical"``）、``cellSize``（px 或 ``"auto"``）、
    ``dayLabel`` {show, firstDay（0=周日 … 6=周六，或 "sunday"/"monday"）}、
    ``monthLabel`` {show}、``yearLabel`` {show}、``splitLine``
    {show, lineStyle}、``itemStyle`` {color, borderColor, borderWidth}。

    行 / 列 = 星期与周序（orient 决定转置）；``mapPoint(date)`` 单参 →
    单元格中心；``cellRect(date)``；``dateAt(pos)`` 反查。
    """

    kind = "calendar"

    def __init__(self, chart=None, option: dict = None):
        super().__init__(chart, option)
        cal = dict(single_option(self.option.get("calendar"), "calendar") or {})
        self.start, self.end = self._resolve_range(cal.get("range"))
        self.year = self.start.year
        self._vertical = str(cal.get("orient") or "horizontal") == "vertical"
        day_label = cal.get("dayLabel")
        self._day_label = day_label if isinstance(day_label, dict) else {}
        month_label = cal.get("monthLabel")
        self._month_label = month_label if isinstance(month_label, dict) else {}
        year_label = cal.get("yearLabel")
        self._year_label = year_label if isinstance(year_label, dict) else {}
        split = cal.get("splitLine")
        self._split_line = split if isinstance(split, dict) else {}
        item_style = cal.get("itemStyle")
        self._item_style = item_style if isinstance(item_style, dict) else {}
        self.cell_size_opt = cal.get("cellSize", 14)
        self._row_offset = self._parse_first_day(self._day_label.get("firstDay"))
        self.show_week_labels = bool(self._day_label.get("show", True))
        self.show_month_labels = bool(self._month_label.get("show", True))
        self.show_year_label = bool(self._year_label.get("show", True))
        self._cell = 14.0
        self._origin = QPointF()  # 网格左上角（orient 转置后）
        self._weeks = 1

    # -- 选项 -------------------------------------------------------------
    @staticmethod
    def _parse_first_day(value) -> int:
        """``dayLabel.firstDay`` → 行号偏移（周日=6，周一=0）。默认周日在上。"""
        text = str(value).strip().lower() if value is not None else ""
        if text in ("monday", "mon", "1"):
            return 0
        if text in ("", "0", "sunday", "sun"):
            return 6  # 0 = 周日（默认）
        try:
            first = int(value) % 7
        except (TypeError, ValueError, OverflowError):
            return 6
        return (first - 1) % 7

    @classmethod
    def _clamp_year(cls, year):
        """年份夹到 ``date`` 支持的区间（1..9999），越界回退当前年。

        ``{"calendar": {"range": 10000}}`` 原先让 ``date(10000, 1, 1)`` 抛
        ``ValueError``，而 ``_make_coord`` 的兜底只是 ``coord = None`` →
        **整张日历热力图静默空白**，看不出是年份越界。
        """
        try:
            y = int(year)
        except (TypeError, ValueError, OverflowError):
            return date.today().year
        if y < 1 or y > _MAX_DATE_YEAR:
            return date.today().year
        return y

    @classmethod
    def _resolve_range(cls, rng):
        """``calendar.range`` → ``(start, end)``。

        支持年份（``2026`` / ``"2026"``）、单日期、``[start, end]`` 或
        ``["2026"]``；非法 / 缺省回退当前年。
        """
        today = date.today()
        year = today.year
        if rng is None:
            return date(year, 1, 1), date(year, 12, 31)
        if isinstance(rng, (int, float)) and not isinstance(rng, bool):
            year = cls._clamp_year(rng)
            return date(year, 1, 1), date(year, 12, 31)
        if isinstance(rng, str):
            text = rng.strip()
            if len(text) == 4 and text.isdigit():
                year = cls._clamp_year(text)
                return date(year, 1, 1), date(year, 12, 31)
            parsed = cls._parse_date(text)
            if parsed is not None:
                return parsed, parsed
            return date(year, 1, 1), date(year, 12, 31)
        if isinstance(rng, (list, tuple)):
            items = list(rng)
            if len(items) == 1:
                items.append(None)
            start = cls._parse_date(items[0])
            end = cls._parse_date(items[1]) if len(items) > 1 else None
            if start is None and isinstance(items[0], (int, float)):
                year = cls._clamp_year(items[0])
                return date(year, 1, 1), date(year, 12, 31)
            if start is None:
                start = date(year, 1, 1)
            if end is None:
                end = date(start.year, 12, 31)
            if end < start:
                start, end = end, start
            return start, end
        return date(year, 1, 1), date(year, 12, 31)

    # -- 日期工具 ---------------------------------------------------------
    @staticmethod
    def _parse_date(v):
        """ "YYYY-MM-DD" / date / (y, m, d) → datetime.date（失败 None）。"""
        if isinstance(v, date):
            return v
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            try:
                return date(int(v[0]), int(v[1]), int(v[2]))
            except (TypeError, ValueError, OverflowError):
                return None
        if isinstance(v, str):
            try:
                parts = v.strip().split("-")
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
            except (TypeError, ValueError, OverflowError, IndexError):
                return None
        return None

    def _first_column_start(self) -> date:
        """首格对应的日期（按 ``dayLabel.firstDay`` 对齐）。"""
        return self.start - timedelta(
            days=(self.start.weekday() - self._row_offset) % 7
        )

    def _row_of(self, day: date) -> int:
        """日期 → 星期行号（0 = 首行，按 firstDay）。"""
        return (day.weekday() - self._row_offset) % 7

    def _month_dates(self) -> list:
        """start→end 逐月 1 日列表（跨年 range 正确）。"""
        out = []
        d = date(self.start.year, self.start.month, 1)
        while d <= self.end:
            out.append(d)
            # ``date`` 的 year 上限是 9999：range 落在 9999 年时
            # ``date(d.year + 1, 1, 1)`` 抛 ValueError，而这里跑在
            # ``paintAxes`` 的调用链上 → 整张日历热力图静默空白。
            if d.year >= _MAX_DATE_YEAR:
                break
            if d.month == 12:
                d = date(d.year + 1, 1, 1)
            else:
                d = date(d.year, d.month + 1, 1)
        return out

    def _grid_xy(self, week_index: int, weekday_row: int):
        """(周序, 星期行) → 网格 (列, 行)（``orient`` 转置）。"""
        if self._vertical:
            return weekday_row, week_index
        return week_index, weekday_row

    # -- 协议 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        super().layout(rect)
        label_top = 16.0  # 月份 / 星期标签带
        label_left = 28.0  # 星期 / 月份标签带
        if self._vertical:
            label_top = 18.0
            label_left = 36.0
        first = self._first_column_start()
        self._weeks = max(1, (self.end - first).days // 7 + 1)
        cols = 7 if self._vertical else self._weeks
        rows = self._weeks if self._vertical else 7
        avail_w = max(20.0, rect.width() - label_left - 4)
        avail_h = max(20.0, rect.height() - label_top - 4)
        if str(self.cell_size_opt).lower() == "auto":
            self._cell = max(3.0, min(avail_w / cols, avail_h / rows))
        else:
            self._cell = max(3.0, _to_float(self.cell_size_opt, 14.0))
        grid_w = self._cell * cols
        ox = rect.left() + label_left + max(0.0, (avail_w - grid_w) / 2)
        self._origin = QPointF(ox, rect.top() + label_top)

    def cellRect(self, day) -> QRectF:
        """日期 → 单元格矩形（无法解析 / 范围外返回空矩形）。"""
        d = self._parse_date(day)
        if d is None or d < self.start or d > self.end:
            return QRectF()
        first = self._first_column_start()
        week_index = (d - first).days // 7
        col, row = self._grid_xy(week_index, self._row_of(d))
        return QRectF(
            self._origin.x() + col * self._cell,
            self._origin.y() + row * self._cell,
            self._cell,
            self._cell,
        )

    def mapPoint(self, x, y=None) -> QPointF:
        """日期 → 单元格中心。"""
        r = self.cellRect(x)
        if r.isNull():
            return QPointF(self._origin)
        return r.center()

    def invertPoint(self, pos: QPointF):
        """像素 → ``[ISO 日期]``（网格外返回 None）。"""
        d = self.dateAt(pos)
        if d is None:
            return None
        return [d.isoformat()]

    def containPoint(self, pos: QPointF) -> bool:
        return self.dateAt(pos) is not None

    def cellSize(self) -> float:
        """当前单元格边长（px）。"""
        return self._cell

    def weeks(self) -> int:
        """总列数 / 行数（周数）。"""
        return self._weeks

    def iterDates(self):
        """遍历范围内全部日期（含无数据日）。"""
        d = self.start
        while d <= self.end:
            yield d
            # ``date`` 上限是 9999-12-31，再加一天抛 OverflowError —— 跑在
            # heatmap 的 layout 里 → 整张日历热力图静默空白。
            if d.year >= _MAX_DATE_YEAR:
                break
            d += timedelta(days=1)

    def _weekday_label_rows(self) -> dict:
        """星期标签序号 → 标签（GitHub 只标 周一/周三/周五）。

        ``dayLabel.nameMap`` 可覆盖：数组按 ECharts 约定 **0 = 周日** … 6 = 周六；
        也接受 ``{0: "SUN", ...}`` 形式的 dict（键同样是 0 = 周日）。
        """
        base = {row: label for row, label in ((0, "周一"), (2, "周三"), (4, "周五"))}
        raw = self._day_label.get("nameMap")
        if isinstance(raw, (list, tuple)) and len(raw) >= 7:
            return {
                row: str(raw[(row + 1) % 7]) for row in base
            }
        if isinstance(raw, dict):
            return {row: str(raw.get((row + 1) % 7, label)) for row, label in base.items()}
        return base

    def _month_name(self, month: int) -> str:
        """月份标签（``monthLabel.nameMap`` 数组按 1 月起始，或 dict）。"""
        raw = self._month_label.get("nameMap")
        if isinstance(raw, (list, tuple)) and len(raw) >= 12:
            return str(raw[month - 1])
        if isinstance(raw, dict):
            if month in raw:
                return str(raw[month])
            # 0 基 dict（{0: "Jan", ...}）——只有存在键 0 时才按 0 基解释，
            # 否则 ``{2: "Feb"}`` 在 3 月会命中 2 而错显示成 2 月
            if 0 in raw and (month - 1) in raw:
                return str(raw[month - 1])
        return _MONTH_LABELS[month - 1]

    def itemStyle(self) -> dict:
        """``calendar.itemStyle``（空日底色 / 边框由 heatmap 系列读取）。"""
        return self._item_style

    def _label_style(self, which: str) -> dict:
        """``dayLabel`` / ``monthLabel`` / ``yearLabel`` 的文字样式。"""
        raw = {
            "day": self._day_label,
            "month": self._month_label,
            "year": self._year_label,
        }.get(which, {})
        return merged_text_style(self.chart, raw)

    def _label_font(self, style: dict):
        return chartFont(
            style.get("fontSize", T("font.xs")),
            text_weight(style.get("fontWeight")),
            style.get("fontFamily"),
            text_italic(style.get("fontStyle")),
        )

    def paintAxes(self, p: QPainter) -> None:
        p.save()
        day_style = self._label_style("day")
        day_font = self._label_font(day_style)
        p.setFont(day_font)
        p.setPen(parse_color(day_style.get("color") or T("color.text.tertiary")))
        # 星期标签（周一/周三/周五；行号按 firstDay 换算）
        if self.show_week_labels:
            for local_row, label in self._weekday_label_rows().items():
                row = (local_row - self._row_offset) % 7
                if self._vertical:
                    x = self._origin.x() + row * self._cell
                    p.drawText(
                        QRectF(x, self.rect.top(), self._cell, 14),
                        Qt.AlignmentFlag.AlignCenter,
                        label,
                    )
                else:
                    y = self._origin.y() + row * self._cell
                    p.drawText(
                        QRectF(
                            self.rect.left(),
                            y,
                            max(8.0, self._origin.x() - self.rect.left() - 4),
                            self._cell,
                        ),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        label,
                    )
        # 月份标签：每月 1 日所在格（去重；跨年逐月遍历）
        month_style = self._label_style("month")
        month_font = self._label_font(month_style)
        month_fm = QFontMetricsF(month_font)
        if self.show_month_labels:
            p.setFont(month_font)
            p.setPen(parse_color(month_style.get("color") or T("color.text.tertiary")))
            first = self._first_column_start()
            last_idx = -1
            for d in self._month_dates():
                anchor = d if d >= self.start else self.start
                week_index = (anchor - first).days // 7
                if week_index == last_idx:
                    continue
                last_idx = week_index
                if self._vertical:
                    y = self._origin.y() + week_index * self._cell
                    p.drawText(
                        QRectF(
                            self.rect.left(),
                            y,
                            max(8.0, self._origin.x() - self.rect.left() - 4),
                            self._cell,
                        ),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        self._month_name(d.month),
                    )
                else:
                    x = self._origin.x() + week_index * self._cell
                    p.drawText(
                        QRectF(x, self.rect.top(), 40, month_fm.height()),
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        self._month_name(d.month),
                    )
        # 年份标签
        year_style = self._label_style("year")
        year_font = self._label_font(year_style)
        year_fm = QFontMetricsF(year_font)
        if self.show_year_label and str(self.start.year) == str(self.end.year):
            p.setFont(year_font)
            p.setPen(parse_color(year_style.get("color") or T("color.text.tertiary")))
            p.drawText(
                QRectF(self.rect.left(), self.rect.top(), 60, year_fm.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                str(self.start.year),
            )
        # splitLine：单元格网格线
        if bool(self._split_line.get("show", False)):
            p.setPen(_line_pen(self._split_line, T("color.border")))
            grid_w = self._cell * (7 if self._vertical else self._weeks)
            grid_h = self._cell * (self._weeks if self._vertical else 7)
            cols = 7 if self._vertical else self._weeks
            rows = self._weeks if self._vertical else 7
            for c in range(cols + 1):
                x = self._origin.x() + c * self._cell
                p.drawLine(
                    QPointF(x, self._origin.y()), QPointF(x, self._origin.y() + grid_h)
                )
            for r in range(rows + 1):
                y = self._origin.y() + r * self._cell
                p.drawLine(
                    QPointF(self._origin.x(), y), QPointF(self._origin.x() + grid_w, y)
                )
        p.restore()

    def paintTooltipMarker(
        self, p: QPainter, pos: QPointF, kind: str = "cross", line_style: dict = None
    ) -> None:
        if kind == "none":
            return
        p.save()
        d = self.dateAt(pos)
        if d is not None:
            r = self.cellRect(d)
            style = line_style if isinstance(line_style, dict) else {}
            pen = _line_pen({"lineStyle": style}, T("color.primary"), 1.4)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
        p.restore()

    def dateAt(self, pos: QPointF):
        """像素 → 日期（网格外返回 None）。"""
        if self._cell <= 0:
            return None
        col = int((pos.x() - self._origin.x()) // self._cell)
        row = int((pos.y() - self._origin.y()) // self._cell)
        cols = 7 if self._vertical else self._weeks
        rows = self._weeks if self._vertical else 7
        if col < 0 or col >= cols or row < 0 or row >= rows:
            return None
        if self._vertical:
            weekday, week_index = col, row
        else:
            week_index, weekday = col, row
        try:
            d = self._first_column_start() + timedelta(days=week_index * 7 + weekday)
        except OverflowError:
            # range 落在 9999 年末尾时，最后几列会越出 ``date`` 上限
            return None
        if d < self.start or d > self.end:
            return None
        return d
