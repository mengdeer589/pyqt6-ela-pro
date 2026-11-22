"""甘特图系列（``type="gantt"``）：任务条 / 进度 / 里程碑 / 依赖箭头 / 拖动改期。"""

from __future__ import annotations


import math
from datetime import date, datetime, timedelta

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF

from .._tokens import T
from .._utils import parse_color, to_float as _to_float, warn_once, with_alpha
from ..models import event_from_dict
from ..axes import (
    GridCoord,
    _dt_to_ms,
    _gantt_baseline,
    _gantt_bounds,
    _gantt_deadline,
    _gantt_display_rows,
    _gantt_progress,
    _ms_to_dt,
    _to_timestamp,
    chartFont,
    formatValue,
)
from ..core import SeriesRenderer
from ._shared import (
    _fix_value_axis,
    label_rotate,
    paint_label_at,
    paint_label_in,
)


class GanttSeriesRenderer(SeriesRenderer):
    """甘特图：``xAxis.type`` 为 ``time`` / ``value``，``yAxis.type`` 为 ``category``。

    数据项支持 ``{"name","start","end","progress","milestone","dependencies"}``
    与 ``[start, end, progress]`` 简写；``editable`` 开启后可拖动改期。
    """

    #: 按下时优先于 dataZoom / brush（标注组件仍在它之前）
    pressPriority = True

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._items = []
        self._by_name = {}
        self._bar_h = 12.0
        self._radius = 4.0
        self._progress_cfg = {}
        self._milestone_cfg = {}
        self._deps_cfg = {}
        self._today_cfg = {}
        self._weekend_cfg = {}
        self._baseline_cfg = {}
        self._deadline_cfg = {}
        self._critical_cfg = {}
        self._row_stripe = False
        self._today_ms = None
        self._snap = None
        self._editable = bool(self.opt.get("editable", False))
        self._drag = None
        self._drag_axis = None
        #: 拖动过（哪怕 <4px）就不再补发点击
        self.consumesClick = False

    def layout(self, rect: QRectF) -> None:
        self._items = []
        self._by_name = {}
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        x_axis, y_axis = coord.x_axis, coord.y_axis
        if y_axis.type != "category":
            warn_once(
                "gantt-y-category",
                "甘特图需要 yAxis.type='category'（当前不是，已跳过绘制）",
            )
            return
        if x_axis.type != "value":
            warn_once(
                "gantt-x-value",
                "甘特图需要 xAxis.type='time' 或 'value'（当前不是，已跳过绘制）",
            )
            return
        _fix_value_axis(x_axis, self.chart, self.opt, "x")
        self._parse_config(x_axis)
        plot = coord.plot
        band = y_axis.bandWidth(plot.top(), plot.bottom())
        if band <= 0:
            band = plot.height() / max(1, len(self.data()))
        self._bar_h = self._resolve_bar_height(band)
        self._radius = self._resolve_radius()
        data = self.data()
        for row in _gantt_display_rows(self.opt):
            index = row.get("index")
            if not isinstance(index, int) or not (0 <= index < len(data)):
                continue
            item = data[index]
            bounds = _gantt_bounds(item)
            if bounds is None:
                continue
            start, end = bounds
            raw_name = row.get("name") if row.get("named") else None
            name = str(raw_name) if raw_name else None
            row_local, row_full = self._row_index(name, index, y_axis)
            if row_local < 0 or row_full < 0:
                continue
            # 与 ECharts 类目轴一致：0 在底部；工作计划通常配 yAxis.inverse=true 让首行在顶部。
            y = y_axis.map(row_full, plot.bottom(), plot.top())
            if not _finite(y):
                continue
            milestone = self._is_milestone(item, start, end)
            progress = None if milestone else _gantt_progress(item)
            color = parse_color(self.itemColor(index))
            progress_rect = None
            progress_handle = None
            milestone_pt = None
            row_top = y - band / 2.0
            row_bottom = y + band / 2.0
            x0 = x_axis.map(start, plot.left(), plot.right())
            x1 = x_axis.map(end, plot.left(), plot.right())
            if not (_finite(x0) and _finite(x1)):
                continue
            if milestone:
                size = self._milestone_size()
                milestone_pt = QPointF(x0, y)
                bar_rect = QRectF(x0 - size / 2, y - size / 2, size, size)
            else:
                bar_rect = QRectF(
                    min(x0, x1),
                    y - self._bar_h / 2,
                    max(1.0, abs(x1 - x0)),
                    self._bar_h,
                )
                if progress is not None and self._progress_cfg.get("show", True):
                    progress_rect = QRectF(
                        bar_rect.left(),
                        bar_rect.top(),
                        bar_rect.width() * progress,
                        bar_rect.height(),
                    )
                    progress_handle = self._progress_handle_rect(
                        bar_rect, progress, row_top
                    )
            baseline_rect, baseline_overrun = self._baseline_rects(
                item, end, bar_rect, row_top, row_bottom, x_axis, plot
            )
            baseline = (
                _gantt_baseline(item) if self._baseline_cfg.get("show", True) else None
            )
            deadline = (
                _gantt_deadline(item) if self._deadline_cfg.get("show", True) else None
            )
            deadline_x = (
                x_axis.map(deadline, plot.left(), plot.right())
                if deadline is not None
                else None
            )
            if deadline_x is not None and not _finite(deadline_x):
                deadline_x = None
            entry = {
                "index": index,
                "name": name,
                "status": item.get("status") if isinstance(item, dict) else None,
                "start": start,
                "end": end,
                "x0": x0,
                "x1": x1,
                "start_fmt": self._raw_start(item),
                "end_fmt": self._raw_end(item),
                "progress": progress,
                "milestone": milestone,
                "deps": self._deps_of(item),
                "row_local": row_local,
                "row_full": row_full,
                "row_top": row_top,
                "row_bottom": row_bottom,
                "y": y,
                "rect": bar_rect,
                "progress_rect": progress_rect,
                "progress_handle": progress_handle,
                "baseline": baseline,
                "baseline_rect": baseline_rect,
                "baseline_overrun": baseline_overrun,
                "deadline": deadline,
                "deadline_x": deadline_x,
                "overdue": False,
                "overdue_days": 0.0,
                "milestone_pt": milestone_pt,
                "color": color,
                "critical": False,
                "slack": None,
            }
            self._refresh_overdue(entry)
            self._items.append(entry)
            if name:
                self._by_name.setdefault(name, entry)
        self._mark_critical_path()

    def itemColor(self, index=None, default=None) -> QColor:
        """项 ``itemStyle.color`` → ``statusColors[status]`` → 系列色 → 默认。"""
        item_color = self._itemStyleFor(index).get("color")
        if isinstance(item_color, str) and item_color:
            color = self.resolveColor(item_color)
            if color.isValid():
                return color
        if isinstance(index, int):
            data = self.data()
            if 0 <= index < len(data):
                item = data[index]
                status = item.get("status") if isinstance(item, dict) else None
                mapping = self.opt.get("statusColors")
                if status is not None and isinstance(mapping, dict):
                    raw = mapping.get(str(status))
                    if isinstance(raw, str) and raw:
                        color = self.resolveColor(raw)
                        if color.isValid():
                            return color
        series_color = self.itemStyle().get("color")
        if isinstance(series_color, str) and series_color:
            color = self.resolveColor(series_color)
            if color.isValid():
                return color
        if default is not None:
            return self.resolveColor(default)
        return self.color()

    def preferredHeight(self, rowHeight: float = 26.0, padding: float = 88.0) -> int:
        """按有效任务行数建议的图表高度。"""
        rows = len(_gantt_display_rows(self.opt))
        rh = max(8.0, _to_float(rowHeight, 26.0))
        pad = max(0.0, _to_float(padding, 88.0))
        return int(round(max(1, rows) * rh + pad))

    def _option_color(self, raw, fallback):
        """progress / baseline 子配置颜色：支持主题令牌，非法值回退。"""
        color = self.resolveColor(raw)
        if color.isValid():
            return color
        return self.resolveColor(fallback)

    def _parse_config(self, x_axis) -> None:
        raw_progress = self.opt.get("progress")
        if isinstance(raw_progress, dict):
            self._progress_cfg = dict(raw_progress)
        else:
            self._progress_cfg = {
                "show": bool(raw_progress) if raw_progress is not None else True
            }
        raw_baseline = self.opt.get("baseline")
        self._baseline_cfg = (
            dict(raw_baseline)
            if isinstance(raw_baseline, dict)
            else {"show": raw_baseline is not False}
        )
        raw_deadline = self.opt.get("deadline")
        self._deadline_cfg = (
            dict(raw_deadline)
            if isinstance(raw_deadline, dict)
            else {"show": raw_deadline is not False}
        )
        raw_critical = self.opt.get("criticalPath")
        self._critical_cfg = (
            dict(raw_critical)
            if isinstance(raw_critical, dict)
            else {"show": raw_critical is True}
        )
        raw_ms = self.opt.get("milestone")
        self._milestone_cfg = dict(raw_ms) if isinstance(raw_ms, dict) else {}
        raw_deps = self.opt.get("dependencies")
        if isinstance(raw_deps, dict):
            self._deps_cfg = dict(raw_deps)
        else:
            self._deps_cfg = {"show": raw_deps is not False}
        raw_today = self.opt.get("todayLine")
        self._today_cfg = dict(raw_today) if isinstance(raw_today, dict) else {}
        raw_weekend = self.opt.get("weekend")
        self._weekend_cfg = (
            dict(raw_weekend)
            if isinstance(raw_weekend, dict)
            else {"show": raw_weekend is True}
        )
        self._row_stripe = self.opt.get("rowStripe", False) is not False
        self._today_ms = None
        if self._today_cfg.get("show", False):
            raw_date = self._today_cfg.get("date")
            when = (
                _to_timestamp(raw_date)
                if raw_date is not None
                else _dt_to_ms(datetime.now())
            )
            if when is not None:
                self._today_ms = when
        self._snap = self._resolve_snap(x_axis)

    def _resolve_snap(self, x_axis):
        raw = self.opt.get("snap")
        if raw is False:
            return None
        if raw is None:
            return "day" if x_axis.is_time else None
        if isinstance(raw, str):
            text = raw.strip().lower()
            return text if text in ("day", "hour") else None
        step = _to_float(raw, None)
        return step if step and step > 0 else None

    def _resolve_bar_height(self, band: float) -> float:
        raw = _to_float(self.opt.get("barHeight"), None)
        if raw is None:
            raw = _to_float(self.opt.get("barWidth"), None)
        if raw is None:
            return max(1.0, min(band * 0.6, band * 0.9))
        if 0 < raw <= 1:
            return max(1.0, min(band * raw, band * 0.9))
        return max(1.0, min(raw, band * 0.9))

    def _resolve_radius(self) -> float:
        raw = self.itemStyle().get("borderRadius")
        if isinstance(raw, (list, tuple)):
            raw = max((_to_float(v, 0.0) for v in raw), default=0.0)
        return max(0.0, _to_float(raw, 4.0))

    def _progress_handle_rect(self, bar_rect: QRectF, progress: float, row_top: float):
        """进度手柄（任务条上方小圆点）；``progress.editable`` 关闭时返回 None。"""
        if not self._progress_cfg.get("editable") or not self._progress_cfg.get(
            "show", True
        ):
            return None
        radius = 4.0
        x = bar_rect.left() + bar_rect.width() * max(0.0, min(1.0, progress))
        y = max(row_top + radius + 1.0, bar_rect.top() - 5.0)
        return QRectF(x - radius, y - radius, radius * 2.0, radius * 2.0)

    def _baseline_rects(
        self,
        item,
        end: float,
        bar_rect: QRectF,
        row_top: float,
        row_bottom: float,
        x_axis,
        plot: QRectF,
    ):
        """基线细条 + 实际超出基线的红色尾段；未配置返回 ``(None, None)``。"""
        if not self._baseline_cfg.get("show", True):
            return None, None
        baseline = _gantt_baseline(item)
        if baseline is None:
            return None, None
        base_start, base_end = baseline
        bx0 = x_axis.map(base_start, plot.left(), plot.right())
        bx1 = x_axis.map(base_end, plot.left(), plot.right())
        if not (_finite(bx0) and _finite(bx1)):
            return None, None
        band = max(1.0, row_bottom - row_top)
        height = max(
            1.0,
            min(
                _to_float(self._baseline_cfg.get("height"), 3.0),
                max(1.0, band * 0.25),
            ),
        )
        top = min(bar_rect.bottom() + 1.0, row_bottom - height - 1.0)
        top = max(row_top + 1.0, top)
        rect = QRectF(min(bx0, bx1), top, max(1.0, abs(bx1 - bx0)), height)
        overrun = None
        if end > base_end:
            ox0 = x_axis.map(base_end, plot.left(), plot.right())
            ox1 = x_axis.map(end, plot.left(), plot.right())
            if _finite(ox0) and _finite(ox1):
                overrun = QRectF(min(ox0, ox1), top, max(1.0, abs(ox1 - ox0)), height)
        return rect, overrun

    def _refresh_overdue(self, item) -> None:
        """按当前 end / progress 重算截止状态（拖动 / 进度改动后必须调用）。"""
        deadline = item.get("deadline")
        if deadline is None:
            item["overdue"] = False
            item["overdue_days"] = 0.0
            return
        progress = item["progress"]
        overdue = item["end"] > deadline and (progress is None or progress < 1.0)
        item["overdue"] = bool(overdue)
        if not overdue:
            item["overdue_days"] = 0.0
            return
        coord = self.chart.coordFor(self.opt)
        delta = item["end"] - deadline
        item["overdue_days"] = (
            delta / 86400000.0
            if isinstance(coord, GridCoord) and coord.x_axis.is_time
            else delta
        )

    def _mark_critical_path(self) -> None:
        """按 FS 依赖找最长依赖链；只标记当前系列内的一条关键链。

        工期按 ``end - start`` 累加，日期之间的空隙不算浮动 —— 甘特的日期
        往往是手排的，严格的日期 slack 会把整条依赖链都判成非关键。
        """
        if not self._critical_cfg.get("show", False) or not self._items:
            return
        items = self._items
        if not any(item["deps"] for item in items):
            return
        ids = {id(item) for item in items}
        succs = {id(item): [] for item in items}
        indegree = {id(item): 0 for item in items}
        has_pred = set()
        for item in items:
            for dep in item["deps"]:
                pred = self._find_dep(dep)
                if pred is None or pred is item:
                    continue
                if id(pred) not in ids:
                    warn_once(
                        "gantt-critical-cross-series",
                        "关键路径只计算单个甘特系列；跨系列依赖已忽略",
                    )
                    continue
                succs[id(pred)].append(item)
                indegree[id(item)] += 1
                has_pred.add(id(item))
        queue = [item for item in items if indegree[id(item)] == 0]
        order = []
        while queue:
            current = queue.pop()
            order.append(current)
            for nxt in succs[id(current)]:
                key = id(nxt)
                indegree[key] -= 1
                if indegree[key] == 0:
                    queue.append(nxt)
        if len(order) != len(items):
            warn_once("gantt-critical-cycle", "甘特依赖存在环，已跳过关键路径计算")
            return
        depth = {}
        for item in reversed(order):
            children = succs[id(item)]
            best = max((depth[id(child)] for child in children), default=0.0)
            depth[id(item)] = max(0.0, item["end"] - item["start"]) + best
        if not depth:
            return
        max_depth = max(depth.values())
        for item in items:
            item["slack"] = max(0.0, max_depth - depth[id(item)])
            item["critical"] = False
        roots = [item for item in items if id(item) not in has_pred]
        if not roots:
            return
        current = max(roots, key=lambda item: depth[id(item)])
        while current is not None:
            current["critical"] = True
            children = succs[id(current)]
            if not children:
                break
            current = max(children, key=lambda item: depth[id(item)])

    def _milestone_size(self) -> float:
        size = _to_float(self._milestone_cfg.get("symbolSize"), 12.0)
        return max(6.0, min(size, 32.0))

    @staticmethod
    def _row_index(name, index: int, y_axis):
        """任务名 → ``(窗口内行下标, 全量行下标)``；无名任务按数据下标。"""
        cats = y_axis.categories
        all_cats = getattr(y_axis, "_all_categories", None) or cats
        if not name:
            if 0 <= index < len(all_cats):
                return index, index
            return -1, -1
        if name in cats:
            local = cats.index(name)
            return local, local + y_axis.windowOffset()
        if name in all_cats:
            full = all_cats.index(name)
            return full - y_axis.windowOffset(), full
        # 显式 yAxis.data 不含该任务：跳过，不能拿数据下标冒充类目下标
        # （否则任务会画到别人的行上）。
        return -1, -1

    @staticmethod
    def _is_milestone(item, start: float, end: float) -> bool:
        if isinstance(item, dict) and item.get("milestone"):
            return True
        if isinstance(item, dict) and item.get("milestone") is False:
            return False
        missing_end = True
        if isinstance(item, dict):
            if "end" in item:
                missing_end = item.get("end") is None
            elif "finish" in item:
                missing_end = item.get("finish") is None
            else:
                value = item.get("value")
                missing_end = not (isinstance(value, (list, tuple)) and len(value) >= 2)
        elif isinstance(item, (list, tuple)):
            missing_end = len(item) < 2
        return missing_end or end <= start

    @staticmethod
    def _deps_of(item) -> list:
        if not isinstance(item, dict):
            return []
        raw = item.get("dependencies")
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, (list, tuple)):
            return [v for v in raw if isinstance(v, (str, int))]
        return []

    @staticmethod
    def _raw_start(item):
        if isinstance(item, dict):
            if "start" in item:
                return item.get("start")
            if "begin" in item:
                return item.get("begin")
            value = item.get("value")
            if isinstance(value, (list, tuple)) and value:
                return value[0]
            return value
        if isinstance(item, (list, tuple)) and item:
            return item[0]
        return None

    @staticmethod
    def _raw_end(item):
        if isinstance(item, dict):
            if "end" in item:
                return item.get("end")
            if "finish" in item:
                return item.get("finish")
            value = item.get("value")
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                return value[1]
            return None
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            return item[1]
        return None

    def _animated_rect(self, item, anim_t: float) -> QRectF:
        if anim_t >= 1.0:
            return QRectF(item["rect"])
        x0, x1 = item["x0"], item["x1"]
        if item["milestone"]:
            size = self._milestone_size() * (0.35 + 0.65 * anim_t)
            return QRectF(
                item["milestone_pt"].x() - size / 2,
                item["milestone_pt"].y() - size / 2,
                size,
                size,
            )
        cur = x0 + (x1 - x0) * anim_t
        return QRectF(
            min(x0, cur),
            item["y"] - self._bar_h / 2,
            max(1.0, abs(cur - x0)),
            self._bar_h,
        )

    def paint(self, p: QPainter, anim_t: float) -> None:
        self._label_rects = []
        if not self._items:
            return
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        plot = coord.plot
        p.save()
        p.setClipRect(plot)
        self._paint_background(p, coord)
        if self._deps_cfg.get("show", True):
            self._paint_dependencies(p, coord)
        emphasized = self.chart.emphasizedIndices(self)
        show_label = self.labelShown()
        font = self.labelFont() if show_label else None
        fm = QFontMetricsF(font) if font is not None else None
        if font is not None:
            p.setFont(font)
        hovered = next(iter(emphasized), None) if emphasized else None
        for item in self._items:
            rect = self._animated_rect(item, anim_t)
            if not plot.intersects(rect):
                continue
            color = parse_color(item["color"])
            alpha = self.itemOpacity(item["index"])
            border_color, border_w = self.itemBorder(item["index"])
            color, alpha, border_color, border_w = self.stateStyle(
                item["index"], hovered, color, alpha, border_color, border_w
            )
            if item["baseline_rect"] is not None:
                self._paint_baseline(p, item, alpha)
            if item["milestone"]:
                self._paint_milestone(
                    p, item, rect, color, alpha, border_color, border_w
                )
            else:
                self._paint_bar(p, item, rect, color, alpha, border_color, border_w)
            self._paint_critical(p, item, rect)
            self._paint_deadline(p, item, rect)
            if show_label:
                self._paint_label(p, item, rect, color, alpha, fm)
            self._paint_progress_handle(p, item, rect, alpha)
        # 今天线画在任务条之上，避免被长条盖住。
        self._paint_today(p, coord)
        p.restore()

    def _paint_background(self, p: QPainter, coord: GridCoord) -> None:
        """周末底纹 + 交替行底纹（都在系列图元之下）。"""
        plot = coord.plot
        x_axis = coord.x_axis
        if self._weekend_cfg.get("show", False) and x_axis.is_time:
            day = 86400000.0
            span = float(x_axis.vmax) - float(x_axis.vmin)
            if 0 < span <= day * 800 and span / day >= 2.0:
                color = self.resolveColor(
                    self._weekend_cfg.get("color") or T("color.bg.muted", self.chart)
                )
                color.setAlpha(
                    int(
                        max(
                            10,
                            min(
                                80,
                                _to_float(self._weekend_cfg.get("opacity"), 0.55) * 80,
                            ),
                        )
                    )
                )
                cursor = _ms_to_dt(x_axis.vmin)
                cursor = datetime(cursor.year, cursor.month, cursor.day)
                limit_ms = float(x_axis.vmax)
                while _dt_to_ms(cursor) <= limit_ms:
                    if cursor.weekday() >= 5:
                        x0 = x_axis.map(_dt_to_ms(cursor), plot.left(), plot.right())
                        x1 = x_axis.map(
                            _dt_to_ms(cursor + timedelta(days=1)),
                            plot.left(),
                            plot.right(),
                        )
                        p.fillRect(
                            QRectF(x0, plot.top(), max(1.0, x1 - x0), plot.height()),
                            color,
                        )
                    cursor += timedelta(days=1)
        if not self._row_stripe:
            return
        band = coord.y_axis.bandWidth(plot.top(), plot.bottom())
        if band <= 0:
            return
        stripe = parse_color(T("color.bg.muted", self.chart))
        stripe.setAlpha(16)
        for item in self._items:
            if item["row_full"] % 2:
                p.fillRect(
                    QRectF(
                        plot.left(),
                        item["y"] - band / 2.0,
                        plot.width(),
                        band,
                    ),
                    stripe,
                )

    def _paint_bar(self, p, item, rect, color, alpha, border_color, border_w):
        progress = item["progress"]
        show_progress = progress is not None and self._progress_cfg.get("show", True)
        radius = min(self._radius, rect.height() / 2, rect.width() / 2)
        if border_color is None or border_w <= 0:
            border_color = with_alpha(color.darker(112), 80)
            border_w = 0.8
        p.setPen(Qt.PenStyle.NoPen)
        if show_progress:
            base = self._option_color(self._progress_cfg.get("baseColor"), color)
            base.setAlphaF(
                max(
                    0.0,
                    min(
                        1.0,
                        base.alphaF()
                        * alpha
                        * _to_float(self._progress_cfg.get("baseOpacity"), 0.35),
                    ),
                )
            )
            self._draw_rounded(p, rect, radius, base)
            # 用 hover / 选中后的 color，进度段和轨道保持同一强调色。
            fill = self._option_color(self._progress_cfg.get("color"), color)
            fill.setAlphaF(max(0.0, min(1.0, fill.alphaF() * alpha)))
            prog_rect = QRectF(
                rect.left(), rect.top(), rect.width() * progress, rect.height()
            )
            if prog_rect.width() > 0.5:
                self._draw_rounded(p, prog_rect, radius, fill)
        else:
            fill = parse_color(color)
            fill.setAlphaF(max(0.0, min(1.0, fill.alphaF() * alpha)))
            self._draw_rounded(p, rect, radius, fill)
        if border_color is not None and border_w > 0:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(border_color, border_w))
            p.drawRoundedRect(rect, radius, radius)

    @staticmethod
    def _draw_rounded(p: QPainter, rect: QRectF, radius: float, color: QColor) -> None:
        p.setBrush(color)
        if radius > 0.5:
            p.drawRoundedRect(rect, radius, radius)
        else:
            p.drawRect(rect)

    def _paint_baseline(self, p: QPainter, item, alpha: float) -> None:
        rect = item["baseline_rect"]
        if rect is None:
            return
        opacity = max(
            0.0,
            min(1.0, alpha * _to_float(self._baseline_cfg.get("opacity"), 0.55)),
        )
        color = self._option_color(
            self._baseline_cfg.get("color"), T("color.text.tertiary", self.chart)
        )
        color.setAlphaF(max(0.0, min(1.0, color.alphaF() * opacity)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        radius = rect.height() / 2.0
        p.drawRoundedRect(rect, radius, radius)
        overrun = item["baseline_overrun"]
        if overrun is not None:
            over = self._option_color(
                self._baseline_cfg.get("overdueColor"), T("color.danger", self.chart)
            )
            over.setAlphaF(max(0.0, min(1.0, over.alphaF() * opacity)))
            p.setBrush(over)
            p.drawRoundedRect(overrun, radius, radius)

    def _paint_deadline(self, p: QPainter, item, rect: QRectF) -> None:
        if not self._deadline_cfg.get("show", True):
            return
        x = item["deadline_x"]
        if x is None or not _finite(x):
            return
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        plot = coord.plot
        if x < plot.left() or x > plot.right():
            return
        overdue = bool(item["overdue"])
        color = self.resolveColor(
            (self._deadline_cfg.get("overdueColor") if overdue else None)
            or self._deadline_cfg.get("color")
            or (
                T("color.danger", self.chart)
                if overdue
                else T("color.text.tertiary", self.chart)
            )
        )
        top = max(plot.top() + 1.0, rect.top() - 1.0)
        p.setPen(QPen(color, 1.0))
        p.setBrush(color)
        p.drawLine(QPointF(x, top), QPointF(x, top + 7.0))
        p.drawLine(
            QPointF(x, top + 7.0), QPointF(x, max(top + 7.0, rect.bottom() + 1.0))
        )
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(x, top),
                    QPointF(x + 6.0, top + 2.5),
                    QPointF(x, top + 5.0),
                ]
            )
        )

    def _paint_critical(self, p: QPainter, item, rect: QRectF) -> None:
        if not item["critical"]:
            return
        cfg = self._critical_cfg
        color = self.resolveColor(cfg.get("color") or T("color.danger", self.chart))
        width = max(1.0, _to_float(cfg.get("width"), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, width))
        if item["milestone"]:
            half = min(rect.width(), rect.height()) / 2.0
            center = rect.center()
            p.drawPolygon(
                QPolygonF(
                    [
                        QPointF(center.x(), center.y() - half),
                        QPointF(center.x() + half, center.y()),
                        QPointF(center.x(), center.y() + half),
                        QPointF(center.x() - half, center.y()),
                    ]
                )
            )
            return
        radius = min(self._radius, rect.height() / 2.0, rect.width() / 2.0)
        p.drawRoundedRect(rect, radius, radius)

    def _paint_progress_handle(self, p: QPainter, item, rect: QRectF, alpha: float):
        if item["progress"] is None or item["milestone"]:
            return
        handle = self._progress_handle_rect(rect, item["progress"], item["row_top"])
        if handle is None:
            return
        p.save()
        p.setOpacity(max(0.2, min(1.0, alpha)))
        p.setPen(QPen(QColor(T("color.primary", self.chart)), 1.2))
        p.setBrush(QColor(T("color.bg.elevated", self.chart)))
        p.drawEllipse(handle)
        p.restore()

    def _paint_milestone(self, p, item, rect, color, alpha, border_color, border_w):
        pt = item["milestone_pt"]
        if pt is None:
            return
        half = rect.width() / 2
        poly = QPolygonF(
            [
                QPointF(pt.x(), pt.y() - half),
                QPointF(pt.x() + half, pt.y()),
                QPointF(pt.x(), pt.y() + half),
                QPointF(pt.x() - half, pt.y()),
            ]
        )
        fill = parse_color(color)
        fill.setAlphaF(max(0.0, min(1.0, fill.alphaF() * alpha)))
        if border_color is None or border_w <= 0:
            border_color = parse_color(T("color.bg.base", self.chart))
            border_w = 1.2
        p.setBrush(fill)
        p.setPen(QPen(border_color, border_w))
        p.drawPolygon(poly)

    def _paint_label(self, p, item, rect, color, alpha, fm):
        text = self._label_text(item)
        if not text:
            return
        label_opt = self.labelOption()
        position = str(label_opt.get("position") or "inside").lower()
        rotate = label_rotate(label_opt)
        if (
            position == "inside"
            and not item["milestone"]
            and rect.height() < fm.height() - 1
        ):
            # 行高不足时 inside 文字会压到相邻行；轴标签仍能标识任务。
            return
        text_w = fm.horizontalAdvance(text)
        if position == "inside" and rect.width() > text_w + 8:
            fill, dx = self._label_background(item, rect, color, alpha, text_w)
            p.setPen(self.contrastLabelColor(fill, item["index"]))
            hit = paint_label_in(
                p,
                rect.adjusted(4, 0, -4, 0).translated(dx, 0),
                text,
                rotate,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                series=self,
                index=item["index"],
                color=self.contrastLabelColor(fill, item["index"]),
            )
            if hit.isNull():
                return
            self._label_rects.append((item["index"], hit.adjusted(-2, -2, 2, 2), text))
            return
        if item["milestone"]:
            anchor_x = item["milestone_pt"].x() + self._milestone_size() / 2 + 4
        elif position == "left":
            anchor_x = rect.left() - 4 - text_w
        else:
            anchor_x = rect.right() + 4
        anchor = QPointF(anchor_x, rect.center().y() + fm.ascent() / 3.0)
        p.setPen(self.labelColorFor(item["index"]))
        hit = paint_label_at(
            p,
            anchor,
            text,
            fm,
            rotate,
            series=self,
            index=item["index"],
            color=self.labelColorFor(item["index"]),
        )
        if hit.isNull():
            return
        self._label_rects.append((item["index"], hit.adjusted(-2, -2, 2, 2), text))

    def _label_background(self, item, rect, color, alpha, text_w):
        """进度标签实际压住的底色，以及让它完整落在该区域的水平微调。

        标签默认居中；进度不足一半时文字中心其实落在低透明度底轨上，不能拿
        进度填充色选黑 / 白。返回 ``(背景色, dx)``，``dx`` 把标签收进填充段或
        底轨内，避免文字骑在两种颜色交界处。
        """
        center = rect.center().x()
        half = text_w / 2.0 + 4.0
        progress = item["progress"]
        if progress is None or not self._progress_cfg.get("show", True):
            fill = parse_color(color)
            fill.setAlphaF(max(0.0, min(1.0, fill.alphaF() * alpha)))
            return fill, 0.0

        ratio = max(0.0, min(1.0, _to_float(progress, 0.0)))
        prog_right = rect.left() + rect.width() * ratio
        fill = self._option_color(self._progress_cfg.get("color"), item["color"])
        fill.setAlphaF(max(0.0, min(1.0, fill.alphaF() * alpha)))
        base = self._option_color(self._progress_cfg.get("baseColor"), color)
        base.setAlphaF(
            max(
                0.0,
                min(
                    1.0,
                    base.alphaF()
                    * alpha
                    * _to_float(self._progress_cfg.get("baseOpacity"), 0.35),
                ),
            )
        )
        # 满进度时底轨被完全盖住；零进度时填充不可见。这两种情况不能按
        # 「文字放不放得下」回退，否则会拿看不见的那层颜色选黑 / 白。
        if ratio >= 1.0:
            return fill, 0.0
        if ratio <= 0.0:
            return base, 0.0
        if prog_right - rect.left() >= 2.0 * half:
            target = min(max(center, rect.left() + half), prog_right - half)
            return fill, target - center
        if rect.right() - prog_right >= 2.0 * half:
            target = min(max(center, prog_right + half), rect.right() - half)
            return base, target - center
        # 两段都放不下（窄条）：按可见面积更大的一段取色，避免拿几乎看不见
        # 的那层颜色选黑 / 白。
        if prog_right - rect.left() >= rect.right() - prog_right:
            return fill, 0.0
        return base, 0.0

    def _label_text(self, item) -> str:
        overrides = self._source_opt.get("labelTexts")
        if isinstance(overrides, dict) and str(item["index"]) in overrides:
            return str(overrides[str(item["index"])])
        name = item["name"]
        progress = item["progress"]
        params = {
            "a": self.name,
            "b": name,
            "c": name,
            "value": [item["start"], item["end"], progress],
            "name": name,
            "series": self.name,
            "dataIndex": item["index"],
            "start": item["start"],
            "end": item["end"],
            "progress": progress,
        }
        data = self.data()
        index = item["index"]
        source = data[index] if 0 <= index < len(data) else None
        item_label = source.get("label") if isinstance(source, dict) else None
        if isinstance(item_label, dict):
            if "text" in item_label:
                return str(item_label.get("text") or "")
            if item_label.get("formatter") is not None:
                return self._apply_label_formatter(
                    item_label.get("formatter"), params, name
                )
        return self._apply_label_formatter(
            self.labelOption().get("formatter"), params, name
        )

    def _paint_dependencies(self, p: QPainter, coord: GridCoord) -> None:
        cfg = self._deps_cfg
        color = self.resolveColor(
            cfg.get("color") or T("color.text.tertiary", self.chart)
        )
        color.setAlpha(165)
        critical_color = self.resolveColor(
            self._critical_cfg.get("color") or T("color.danger", self.chart)
        )
        critical_color.setAlpha(210)
        width = _to_float(cfg.get("width"), 1.0)
        show_critical = bool(
            self._critical_cfg.get("show", False)
            and self._critical_cfg.get("arrows", True)
        )
        plot = coord.plot
        for item in self._items:
            for dep in item["deps"]:
                pred = self._find_dep(dep)
                if pred is None or pred is item:
                    continue
                critical_link = bool(
                    show_critical and item["critical"] and pred.get("critical", False)
                )
                link_color = critical_color if critical_link else color
                link_width = width + 0.4 if critical_link else width
                self._paint_dependency(p, pred, item, plot, link_color, link_width)

    def _paint_dependency(self, p, pred, succ, plot, color, width) -> None:
        if pred["milestone"]:
            pred_pt = pred["milestone_pt"]
            if pred_pt is None:
                return
            x1 = pred_pt.x() + self._milestone_size() / 2
            y1 = pred_pt.y()
        else:
            x1 = pred["rect"].right()
            y1 = pred["rect"].center().y()
        if succ["milestone"]:
            succ_pt = succ["milestone_pt"]
            if succ_pt is None:
                return
            x2 = succ_pt.x() - self._milestone_size() / 2
            y2 = succ_pt.y()
        else:
            x2 = succ["rect"].left()
            y2 = succ["rect"].center().y()
        if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
            return
        gap = 8.0
        if x2 - x1 >= gap * 2:
            mid = x1 + gap
        else:
            mid = (x1 + x2) / 2.0
        mid = max(plot.left() + 2.0, min(plot.right() - 2.0, mid))
        sign_y = 1.0 if y2 >= y1 else -1.0
        sign_x1 = 1.0 if mid >= x1 else -1.0
        sign_x2 = 1.0 if x2 >= mid else -1.0
        radius = min(4.0, abs(y2 - y1) / 2.0, abs(mid - x1), abs(x2 - mid))
        path = QPainterPath(QPointF(x1, y1))
        if radius > 0.5:
            path.lineTo(mid - sign_x1 * radius, y1)
            path.quadTo(mid, y1, mid, y1 + sign_y * radius)
            path.lineTo(mid, y2 - sign_y * radius)
            path.quadTo(mid, y2, mid + sign_x2 * radius, y2)
        else:
            path.lineTo(mid, y1)
            path.lineTo(mid, y2)
        path.lineTo(x2, y2)
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        direction = 1.0 if x2 >= x1 else -1.0
        head = QPolygonF(
            [
                QPointF(x2, y2),
                QPointF(x2 - 4.2 * direction, y2 - 3.4),
                QPointF(x2 - 4.2 * direction, y2 + 3.4),
            ]
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPolygon(head)

    def _find_dep(self, dep):
        if isinstance(dep, int):
            for item in self._items:
                if item["index"] == dep:
                    return item
            return None
        name = str(dep)
        found = self._by_name.get(name)
        if found is not None:
            return found
        for renderer in self.chart.seriesRenderers:
            if renderer is self:
                continue
            table = getattr(renderer, "_by_name", None)
            if isinstance(table, dict) and name in table:
                return table[name]
        return None

    def _paint_today(self, p: QPainter, coord: GridCoord) -> None:
        if self._today_ms is None:
            return
        plot = coord.plot
        x = coord.x_axis.map(self._today_ms, plot.left(), plot.right())
        if not _finite(x) or x < plot.left() or x > plot.right():
            return
        color = self.resolveColor(
            self._today_cfg.get("color") or T("color.danger", self.chart)
        )
        pen = QPen(color, 1.0)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        text = self._today_cfg.get("label", "今天")
        if text is False or text is None or not str(text):
            return
        font = chartFont(T("font.xs"), 600)
        fm = QFontMetricsF(font)
        text = str(text)
        tw = fm.horizontalAdvance(text)
        box = QRectF(x + 4, plot.top() + 2, tw + 8, fm.height() + 2)
        p.setPen(Qt.PenStyle.NoPen)
        bg = parse_color(T("color.bg.elevated", self.chart))
        bg.setAlphaF(0.92)
        p.setBrush(bg)
        p.drawRoundedRect(box, 3, 3)
        p.setPen(color)
        p.setFont(font)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def hitTest(self, pos: QPointF):
        if self._anim_t < 1.0:
            return None
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return None
        if not coord.plot.adjusted(-1, -1, 1, 1).contains(pos):
            return None
        for item in reversed(self._items):
            if item["milestone"]:
                pt = item["milestone_pt"]
                if pt is None:
                    continue
                if (
                    math.hypot(pos.x() - pt.x(), pos.y() - pt.y())
                    <= self._milestone_size() / 2 + 3
                ):
                    return self._hit_info(item)
            elif item["rect"].adjusted(-2, -2, 2, 2).contains(pos):
                return self._hit_info(item)
        return None

    def _hit_info(self, item) -> dict:
        start_text = self._fmt_value(item["start"])
        end_text = self._fmt_value(item["end"])
        rows = [("开始", start_text)]
        if item["milestone"]:
            rows.append(("类型", "里程碑"))
        else:
            rows.extend(
                [
                    ("结束", end_text),
                    ("工期", self._duration_text(item["start"], item["end"])),
                ]
            )
            if item["progress"] is not None:
                rows.append(("进度", f"{round(item['progress'] * 100)}%"))
        baseline = item.get("baseline")
        if baseline is not None:
            base_start, base_end = baseline
            rows.append(
                ("基线", f"{self._fmt_value(base_start)} → {self._fmt_value(base_end)}")
            )
            delta = item["end"] - base_end
            rows.append(("偏差", self._deviation_text(delta)))
        if item.get("deadline") is not None:
            rows.append(("截止", self._fmt_value(item["deadline"])))
            if item.get("overdue"):
                rows.append(("逾期", self._overdue_text(item)))
        if item.get("critical"):
            rows.append(("关键路径", "是"))
            if item.get("slack") is not None:
                rows.append(("浮动", self._duration_text(0, max(0.0, item["slack"]))))
        center = (
            item["milestone_pt"]
            if item["milestone"] and item["milestone_pt"] is not None
            else item["rect"].center()
        )
        value = [item["start"], item["end"]]
        if item["progress"] is not None:
            value.append(item["progress"])
        return {
            "name": item["name"],
            "value": value,
            "color": parse_color(item["color"]),
            "series": self.name,
            "dataIndex": item["index"],
            "title": item["name"],
            "rows": rows,
            "pos": QPointF(center),
        }

    def valueAtPosition(self, pos: QPointF):
        """axis tooltip 按像素取任务（``yAxis.inverse`` / 行序与全局 invert 不一致）。"""
        item = self._hit_item(pos)
        return self._axis_info(item) if item is not None else None

    def valueAtIndex(self, index: int):
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return None
        for item in self._items:
            if item["index"] == index:
                return self._axis_info(item)
        return None

    def _axis_info(self, item) -> dict:
        start_text = self._fmt_value(item["start"])
        end_text = self._fmt_value(item["end"])
        text = start_text if item["milestone"] else f"{start_text} → {end_text}"
        center = (
            item["milestone_pt"]
            if item["milestone"] and item["milestone_pt"] is not None
            else item["rect"].center()
        )
        return {
            "name": item["name"],
            "value": item["end"],
            "color": parse_color(item["color"]),
            "series": self.name,
            "dataIndex": item["index"],
            "rowIndex": item["row_local"],
            "pos": QPointF(center),
            "axisTitle": item["name"],
            "axisText": text,
        }

    def _fmt_value(self, value) -> str:
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, GridCoord) and coord.x_axis.is_time:
            return coord.x_axis.formatTooltipValue(value)
        return formatValue(value)

    def _duration_text(self, start, end) -> str:
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, GridCoord) and coord.x_axis.is_time:
            days = (end - start) / 86400000.0
            if days >= 1.0:
                return f"{formatValue(round(days, 1))} 天"
            return f"{formatValue(round(days * 24, 1))} 小时"
        return formatValue(end - start)

    def _deviation_text(self, delta: float) -> str:
        """实际结束相对基线的偏差（正值 = 延迟）。"""
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, GridCoord) and coord.x_axis.is_time:
            days = delta / 86400000.0
            if abs(days) < 1.0 / 24.0:
                return "0 天"
            if days > 0:
                return f"延迟 {formatValue(round(days, 1))} 天"
            return f"提前 {formatValue(round(-days, 1))} 天"
        return formatValue(delta)

    def _overdue_text(self, item) -> str:
        """截止逾期文案：时间轴按天，数值轴按原数值单位。"""
        coord = self.chart.coordFor(self.opt)
        if isinstance(coord, GridCoord) and coord.x_axis.is_time:
            return f"{formatValue(round(item['overdue_days'], 1))} 天"
        return formatValue(item["overdue_days"])

    def cursorShapeAt(self, pos: QPointF):
        progress_editable = bool(self._progress_cfg.get("editable"))
        if not (self._editable or progress_editable) or self.silent:
            return None
        if not self.chart.isInteractionEnabled("gantt"):
            return None
        if self._drag is not None:
            mode = self._drag.get("mode", "move")
            return (
                Qt.CursorShape.SizeHorCursor
                if mode.startswith("resize") or mode == "progress"
                else Qt.CursorShape.ClosedHandCursor
            )
        item = self._hit_item(pos)
        if item is None:
            return None
        mode = self._drag_mode(item, pos)
        if mode == "progress":
            return Qt.CursorShape.SizeHorCursor
        if not self._editable:
            return None
        return (
            Qt.CursorShape.SizeHorCursor
            if mode.startswith("resize")
            else Qt.CursorShape.OpenHandCursor
        )

    def _hit_item(self, pos: QPointF):
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return None
        if not coord.plot.adjusted(-1, -1, 1, 1).contains(pos):
            return None
        for item in reversed(self._items):
            handle = item.get("progress_handle")
            if handle is not None and handle.adjusted(-2, -2, 2, 2).contains(pos):
                return item
            if item["milestone"]:
                pt = item["milestone_pt"]
                if (
                    pt is not None
                    and math.hypot(pos.x() - pt.x(), pos.y() - pt.y())
                    <= self._milestone_size() / 2 + 3
                ):
                    return item
            elif item["rect"].adjusted(-2, -2, 2, 2).contains(pos):
                return item
        return None

    def _task_payload(self, item) -> dict:
        """任务级信号 / 右键菜单用的载荷。"""
        progress = item["progress"]
        payload = {
            "componentType": "series",
            "series": self.name,
            "seriesIndex": getattr(self, "_series_index", 0),
            "dataIndex": item["index"],
            "name": item["name"],
            "status": item["status"],
            "start": item["start"],
            "end": item["end"],
            "progress": progress,
            "startText": self._fmt_value(item["start"]),
            "endText": self._fmt_value(item["end"]),
            "progressText": (
                f"{round(progress * 100)}%" if progress is not None else ""
            ),
            "overdue": bool(item["overdue"]),
            "overdueDays": float(item["overdue_days"]),
            "critical": bool(item["critical"]),
            "slack": item["slack"],
        }
        baseline = item.get("baseline")
        if baseline is not None:
            payload["baselineStart"] = baseline[0]
            payload["baselineEnd"] = baseline[1]
            payload["baselineStartText"] = self._fmt_value(baseline[0])
            payload["baselineEndText"] = self._fmt_value(baseline[1])
        if item.get("deadline") is not None:
            payload["deadline"] = item["deadline"]
            payload["deadlineText"] = self._fmt_value(item["deadline"])
        return payload

    def emitTaskClicked(self, hit: dict) -> None:
        """由通用点击分发调用；只对命中的甘特任务补发专用信号。"""
        index = hit.get("dataIndex") if isinstance(hit, dict) else None
        for item in self._items:
            if item["index"] == index:
                self.chart.ganttTaskClicked.emit(
                    event_from_dict("ganttTaskClicked", self._task_payload(item))
                )
                return

    def onMouseDoubleClick(self, pos: QPointF) -> bool:
        item = self._hit_item(pos)
        if item is None:
            return False
        self.chart.ganttTaskDoubleClicked.emit(
            event_from_dict("ganttTaskDoubleClicked", self._task_payload(item))
        )
        return True

    def onContextMenu(self, pos: QPointF, event=None) -> bool:
        item = self._hit_item(pos)
        if item is None:
            return False
        payload = self._task_payload(item)
        payload["pos"] = QPointF(pos)
        if event is not None:
            try:
                payload["globalPos"] = QPointF(event.globalPos())
            except Exception:
                pass
        self.chart.ganttTaskContextMenuRequested.emit(
            event_from_dict("ganttTaskContextMenuRequested", payload)
        )
        return True

    def _drag_mode(self, item, pos: QPointF) -> str:
        if item["milestone"]:
            return "move"
        handle = item.get("progress_handle")
        if handle is not None and handle.adjusted(-2, -2, 2, 2).contains(pos):
            return "progress"
        rect = item["rect"]
        if rect.width() >= 18.0:
            if abs(pos.x() - rect.left()) <= 6.0:
                return "resize-start"
            if abs(pos.x() - rect.right()) <= 6.0:
                return "resize-end"
        return "move"

    def onMousePress(self, pos: QPointF) -> bool:
        progress_editable = bool(self._progress_cfg.get("editable"))
        if not (self._editable or progress_editable) or self.silent:
            return False
        if (
            getattr(self.chart, "_press_button", Qt.MouseButton.LeftButton)
            != Qt.MouseButton.LeftButton
        ):
            return False
        if not self.chart.isInteractionEnabled("gantt"):
            return False
        item = self._hit_item(pos)
        if item is None:
            return False
        mode = self._drag_mode(item, pos)
        if mode != "progress" and not self._editable:
            return False
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return False
        x_axis = coord.x_axis
        try:
            self.chart.anim.stop()
            self.chart.anim.setProgress(1.0)
        except Exception:
            pass
        self.chart.tooltip.hide()
        clear_axis = getattr(self.chart, "_tooltip_axis_clear", None)
        if callable(clear_axis):
            try:
                clear_axis()
            except Exception:
                pass
        clear_hover = getattr(self.chart, "_clear_hover", None)
        if callable(clear_hover):
            try:
                clear_hover()
            except Exception:
                pass
        self._drag_axis = (float(x_axis.vmin), float(x_axis.vmax))
        if (
            not (
                math.isfinite(self._drag_axis[0]) and math.isfinite(self._drag_axis[1])
            )
            or self._drag_axis[1] <= self._drag_axis[0]
        ):
            self._drag_axis = None
            if mode != "progress":
                return False
        self.consumesClick = False
        self._drag = {
            "item": item,
            "index": item["index"],
            "mode": mode,
            "press_x": float(pos.x()),
            "orig_start": item["start"],
            "orig_end": item["end"],
            "orig_progress": item["progress"],
            "moved": False,
        }
        self.chart.setCursor(self.cursorShapeAt(pos) or Qt.CursorShape.ClosedHandCursor)
        self.chart.update()
        return True

    def onMouseMove(self, pos: QPointF) -> bool:
        drag = self._drag
        if drag is None:
            return False
        item = drag["item"]
        if not any(item is current for current in self._items):
            self._drag = None
            return False
        if drag["mode"] == "progress":
            return self._move_progress(item, pos, drag)
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord) or self._drag_axis is None:
            return True
        plot = coord.plot
        x_axis = coord.x_axis
        press_value = x_axis.invert(drag["press_x"], plot.left(), plot.right())
        now_value = x_axis.invert(pos.x(), plot.left(), plot.right())
        if not (_finite(press_value) and _finite(now_value)):
            return True
        delta = float(now_value) - float(press_value)
        axis_min, axis_max = self._drag_axis
        span = axis_max - axis_min
        min_dur = self._min_duration(span)
        start, end = drag["orig_start"], drag["orig_end"]
        mode = drag["mode"]
        if mode == "move":
            new_start, new_end = start + delta, end + delta
            duration = new_end - new_start
            if duration >= span:
                # 任务比当前视窗还长：只钳制起点，尾部可以伸出视窗（数据不能被截短）。
                new_start = self._snap_value(new_start)
                new_start = max(axis_min, min(new_start, axis_max - min_dur))
                new_end = new_start + duration
            else:
                if new_start < axis_min:
                    shift = axis_min - new_start
                    new_start += shift
                    new_end += shift
                if new_end > axis_max:
                    shift = new_end - axis_max
                    new_start -= shift
                    new_end -= shift
                new_start = self._snap_value(new_start)
                new_end = self._snap_value(new_end)
                if new_end - new_start < min_dur:
                    new_end = new_start + min_dur
                duration = new_end - new_start
                if new_start < axis_min:
                    new_start = axis_min
                    new_end = min(axis_max, new_start + duration)
                if new_end > axis_max:
                    new_end = axis_max
                    new_start = max(axis_min, new_end - duration)
        elif mode == "resize-start":
            new_start = self._snap_value(start + delta)
            new_end = end
            new_start = max(axis_min, min(new_start, new_end - min_dur))
        else:
            new_start = start
            new_end = self._snap_value(end + delta)
            new_end = min(axis_max, max(new_end, new_start + min_dur))
        if abs(new_start - item["start"]) < 1e-6 and abs(new_end - item["end"]) < 1e-6:
            return True
        self._apply_geometry(item, new_start, new_end)
        self._write_range(item, new_start, new_end)
        if (
            abs(new_start - drag["orig_start"]) > 1e-6
            or abs(new_end - drag["orig_end"]) > 1e-6
        ):
            drag["moved"] = True
            self.consumesClick = True
        self.chart.invalidateSeriesLayer()
        self.chart.update()
        return True

    def onMouseRelease(self, pos: QPointF) -> bool:
        drag = self._drag
        if drag is None:
            return False
        self._drag = None
        item = drag["item"]
        moved = bool(drag["moved"])
        if drag["mode"] == "progress":
            if abs(item["progress"] - drag["orig_progress"]) < 1e-9:
                moved = False
            if moved:
                try:
                    self.chart.ganttProgressChanged.emit(
                        event_from_dict(
                            "ganttProgressChanged",
                            {
                                "componentType": "series",
                                "series": self.name,
                                "seriesIndex": getattr(self, "_series_index", 0),
                                "dataIndex": item["index"],
                                "name": item["name"],
                                "progress": item["progress"],
                                "prevProgress": drag["orig_progress"],
                                "progressText": f"{round(item['progress'] * 100)}%",
                            },
                        )
                    )
                except Exception:
                    pass
                self.chart.update()
            return True
        payload = None
        if moved:
            payload = {
                "componentType": "series",
                "series": self.name,
                "seriesIndex": getattr(self, "_series_index", 0),
                "dataIndex": item["index"],
                "name": item["name"],
                "mode": drag["mode"],
                "start": item["start"],
                "end": item["end"],
                "prevStart": drag["orig_start"],
                "prevEnd": drag["orig_end"],
                "startText": self._fmt_value(item["start"]),
                "endText": self._fmt_value(item["end"]),
            }
        if moved:
            # 只更新已算好的几何：不重排全图，轴窗口保持拖动前的位置，
            # 避免松手时轴范围跳动或百万点系列被重新采样。
            if self._critical_cfg.get("show", False):
                coord = self.chart.coordFor(self.opt)
                if isinstance(coord, GridCoord):
                    self._mark_critical_path()
            self.chart.update()
        if payload is not None:
            try:
                self.chart.ganttTaskChanged.emit(
                    event_from_dict("ganttTaskChanged", payload)
                )
            except Exception:
                pass
        return True

    def _move_progress(self, item, pos: QPointF, drag: dict) -> bool:
        rect = item["rect"]
        if rect.width() <= 0:
            return True
        ratio = (pos.x() - rect.left()) / rect.width()
        step = _to_float(self._progress_cfg.get("step"), 0.01)
        if step > 0:
            ratio = round(ratio / step) * step
        ratio = max(0.0, min(1.0, ratio))
        if abs(ratio - item["progress"]) < 1e-9:
            return True
        item["progress"] = ratio
        item["progress_rect"] = QRectF(
            rect.left(), rect.top(), rect.width() * ratio, rect.height()
        )
        item["progress_handle"] = self._progress_handle_rect(
            rect, ratio, item["row_top"]
        )
        self._refresh_overdue(item)
        self._write_progress(item, ratio)
        drag["moved"] = True
        self.consumesClick = True
        self.chart.invalidateSeriesLayer()
        self.chart.update()
        return True

    def _write_progress(self, item, progress: float) -> None:
        data = self.data()
        index = item["index"]
        if not (0 <= index < len(data)):
            return
        source = data[index]
        if isinstance(source, dict):
            source["progress"] = progress
            return
        if isinstance(source, list):
            if len(source) >= 3:
                source[2] = progress
            else:
                while len(source) < 2:
                    source.append(None)
                source.append(progress)
            return
        if isinstance(source, tuple):
            values = list(source)
            if len(values) >= 3:
                values[2] = progress
            else:
                values.append(progress)
            try:
                data[index] = values
            except TypeError:
                pass

    def _min_duration(self, span: float) -> float:
        if self._snap == "day":
            return 86400000.0
        if self._snap == "hour":
            return 3600000.0
        if isinstance(self._snap, (int, float)) and self._snap > 0:
            return float(self._snap)
        return max(1e-6, span * 0.005)

    def _snap_value(self, value: float) -> float:
        snap = self._snap
        if snap is None:
            return value
        if snap == "day":
            dt = _ms_to_dt(value)
            day = datetime(dt.year, dt.month, dt.day)
            if dt.hour >= 12:
                day += timedelta(days=1)
            return _dt_to_ms(day)
        if snap == "hour":
            dt = _ms_to_dt(value)
            hour = dt.replace(minute=0, second=0, microsecond=0)
            if dt.minute >= 30:
                hour += timedelta(hours=1)
            return _dt_to_ms(hour)
        if isinstance(snap, (int, float)) and snap > 0:
            return round(value / float(snap)) * float(snap)
        return value

    def _apply_geometry(self, item, start: float, end: float) -> None:
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return
        plot = coord.plot
        item["start"] = start
        item["end"] = end
        x0 = coord.x_axis.map(start, plot.left(), plot.right())
        x1 = coord.x_axis.map(end, plot.left(), plot.right())
        if not (_finite(x0) and _finite(x1)):
            return
        item["x0"] = x0
        item["x1"] = x1
        if item["milestone"]:
            size = self._milestone_size()
            item["milestone_pt"] = QPointF(x0, item["y"])
            item["rect"] = QRectF(x0 - size / 2, item["y"] - size / 2, size, size)
            item["progress_handle"] = None
            return
        rect = QRectF(
            min(x0, x1),
            item["y"] - self._bar_h / 2,
            max(1.0, abs(x1 - x0)),
            self._bar_h,
        )
        item["rect"] = rect
        if item["progress"] is not None and self._progress_cfg.get("show", True):
            item["progress_rect"] = QRectF(
                rect.left(),
                rect.top(),
                rect.width() * item["progress"],
                rect.height(),
            )
            item["progress_handle"] = self._progress_handle_rect(
                rect, item["progress"], item["row_top"]
            )
        else:
            item["progress_rect"] = None
            item["progress_handle"] = None
        baseline = item.get("baseline")
        if baseline is not None:
            _base_start, base_end = baseline
            overrun = None
            if end > base_end and item["baseline_rect"] is not None:
                ox0 = coord.x_axis.map(base_end, plot.left(), plot.right())
                ox1 = coord.x_axis.map(end, plot.left(), plot.right())
                if _finite(ox0) and _finite(ox1):
                    base_rect = item["baseline_rect"]
                    overrun = QRectF(
                        min(ox0, ox1),
                        base_rect.top(),
                        max(1.0, abs(ox1 - ox0)),
                        base_rect.height(),
                    )
            item["baseline_overrun"] = overrun
        self._refresh_overdue(item)

    def _write_range(self, item, start: float, end: float) -> None:
        data = self.data()
        index = item["index"]
        if not (0 <= index < len(data)):
            return
        source = data[index]
        start_fmt = self._format_like(item.get("start_fmt"), start)
        end_fmt = self._format_like(item.get("end_fmt"), end)
        milestone = item["milestone"]
        if isinstance(source, dict):
            if any(key in source for key in ("start", "begin", "end", "finish")):
                if "start" in source:
                    source["start"] = start_fmt
                elif "begin" in source:
                    source["begin"] = start_fmt
                if "end" in source:
                    if not (milestone and source.get("end") is None):
                        source["end"] = end_fmt
                elif "finish" in source:
                    if not (milestone and source.get("finish") is None):
                        source["finish"] = end_fmt
                elif not milestone:
                    source["end"] = end_fmt
            else:
                value = source.get("value")
                if isinstance(value, list):
                    if value:
                        value[0] = start_fmt
                    else:
                        value.append(start_fmt)
                    if len(value) >= 2:
                        value[1] = end_fmt
                    elif not milestone:
                        value.append(end_fmt)
                elif isinstance(value, tuple):
                    if milestone:
                        source["value"] = (start_fmt, *value[1:])
                    else:
                        source["value"] = [start_fmt, end_fmt, *value[2:]]
                else:
                    source["value"] = start_fmt if milestone else [start_fmt, end_fmt]
        elif isinstance(source, list):
            if source:
                source[0] = start_fmt
            else:
                source.append(start_fmt)
            if len(source) >= 2:
                source[1] = end_fmt
            elif not milestone:
                source.append(end_fmt)
        elif isinstance(source, tuple):
            new = list(source)
            if new:
                new[0] = start_fmt
            else:
                new.append(start_fmt)
            if len(new) >= 2:
                new[1] = end_fmt
            elif not milestone:
                new.append(end_fmt)
            data[index] = new
        else:
            data[index] = start_fmt
        item["start_fmt"] = start_fmt
        item["end_fmt"] = end_fmt

    @staticmethod
    def _format_like(raw, value: float):
        if isinstance(raw, datetime):
            return _ms_to_dt(value)
        if isinstance(raw, date):
            return _ms_to_dt(value).date()
        if isinstance(raw, str):
            text = raw.strip()
            dt = _ms_to_dt(value)
            has_time = bool(dt.hour or dt.minute or dt.second or dt.microsecond)
            if "T" in text:
                return (
                    dt.strftime("%Y-%m-%dT%H:%M:%S")
                    if has_time
                    else dt.strftime("%Y-%m-%dT%H:%M")
                )
            if ":" in text:
                return (
                    dt.strftime("%Y-%m-%d %H:%M:%S")
                    if has_time
                    else dt.strftime("%Y-%m-%d %H:%M")
                )
            # 日期型源数据被拖出时间：必须把时间写回，否则数据没变而
            # ganttTaskChanged 载荷带了新时间，宿主会存下不一致的值。
            return (
                dt.strftime("%Y-%m-%dT%H:%M:%S")
                if has_time
                else dt.strftime("%Y-%m-%d")
            )
        dt = _ms_to_dt(value)
        if isinstance(raw, int) and not isinstance(raw, bool):
            return int(round(value))
        if isinstance(raw, float):
            return float(value)
        if isinstance(raw, (list, tuple)):
            return dt.isoformat(sep=" ")
        return dt.strftime("%Y-%m-%d")


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False
