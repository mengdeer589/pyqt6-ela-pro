"""框选 / 套索组件。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QPolygonF,
)

from .._tokens import T
from .. import _downsample as _ds
from .._utils import clamp as _clamp
from .._utils import to_float as _to_float
from .._utils import parse_color
from ..axes import GridCoord
from ..core import parseDataPoint


class BrushComponent(QObject):
    """矩形 / 套索刷选：Grid 上拖出选框，命中数据点集合并高亮。

    option: ``"brush": {"toolbox": ["rect", "clear"], "outOfBrush": {"opacity": 0.4}}``。
    落定后 ``selected_items`` 为命中点列表并发出 ``selected(list)``；
    配置后 plot 内左键拖拽归刷选，dataZoom inside 仅保留滚轮缩放。
    """

    optionKey = "brush"
    #: 只支持单实例：数组写法取第一个 dict（见 ``_utils.single_option``）
    singleOption = True

    #: 刷选完成信号：list[{"series","dataIndex","value","x"}]
    selected = pyqtSignal(list)

    #: 选中点高亮环半径（px）
    HIGHLIGHT_R = 7.0
    #: 单次绘制最多画多少个高亮环（超出按步长抽样，避免选中 10 万点时每帧卡死）
    HIGHLIGHT_MAX = 4000
    #: 超过该数量改用批量 ``drawPoints``（逐个画环太慢）
    HIGHLIGHT_BULK = 300
    #: lasso 向量化候选点上限（超出按步长抽样；矩形框选不设上限）
    LASSO_MAX_CANDIDATES = 200_000

    def __init__(self, chart, opt):
        super().__init__()
        self.chart = chart
        self.opt = dict(opt or {})
        self._rect = None  # 当前选框 QRectF（None 表示无选区）
        self._anchor = None  # 拖拽起点
        #: lasso（套索）轨迹点；``brush.type == "lasso"`` 时使用
        self._poly = []
        #: 是否接管拖拽（``setDragMode`` 用；``False`` 时 onMouse* 一律放行）
        self.enabled = True
        self.selected_items = []
        #: 选中集版本 + 屏幕坐标缓存键（``_highlight_points`` 用）
        self._selection_epoch = 0
        self._highlight_key = None
        self._highlight_cache = []
        #: 本次框选所属网格（多网格；None = 主坐标系）
        self._coord = None

    def _plot(self) -> QRectF:
        coord = self._coord or self.chart.primaryCoord()
        if isinstance(coord, GridCoord):
            return coord.plot
        return QRectF()

    def brush_type(self) -> str:
        """刷选形态：``rect``（默认，框选）/ ``lasso``（套索，Plotly 同款）。"""
        raw = self.opt.get("type", self.opt.get("brushType", "rect"))
        name = str(raw or "rect").strip().lower()
        return "lasso" if name in ("lasso", "free", "polygon") else "rect"

    def onMousePress(self, pos: QPointF) -> bool:
        if not self.enabled:
            return False
        coord = self.chart.coordAt(pos)
        if not isinstance(coord, GridCoord) or not coord.plot.contains(pos):
            # 绘图区外按下：收掉已有选框，但不消费事件。
            if self._rect is not None or self._poly:
                self.clear()
            return False
        self._coord = coord
        self._anchor = QPointF(pos)
        self._poly = [QPointF(pos)]
        self._rect = QRectF(pos, pos)
        self.selected_items = []
        self.chart.update()
        return True

    def onMouseMove(self, pos: QPointF) -> bool:
        if not self.enabled or self._anchor is None:
            return False
        if self.brush_type() == "lasso":
            # 采样点距 <2px 不记，套索轨迹不必要地密集会拖慢 containsPoint
            if not self._poly or (
                math.hypot(self._poly[-1].x() - pos.x(), self._poly[-1].y() - pos.y())
                >= 2.0
            ):
                self._poly.append(QPointF(pos))
            self._rect = QRectF(self._anchor, pos).normalized()
        else:
            self._rect = QRectF(self._anchor, pos).normalized()
        self.chart.update()
        return True

    def onMouseRelease(self, pos: QPointF) -> bool:
        if not self.enabled or self._anchor is None:
            return False
        self._rect = QRectF(self._anchor, pos).normalized()
        if self.brush_type() == "lasso":
            self._poly.append(QPointF(pos))
        self._anchor = None
        too_small = (
            self._rect is not None
            and self._rect.width() < 3
            and self._rect.height() < 3
        ) or (self.brush_type() == "lasso" and len(self._poly) < 4)
        if too_small:
            self.clear()  # 视为单击：清除选区
        elif str(getattr(self.chart, "_drag_mode", "")) == "zoom":
            # 框选缩放是一次性手势：缩放落地后选框主动消失。
            self._zoom_to_rect()
            self.clear()
        else:
            self._collect()
        self.chart.update()
        if self._rect is not None:
            self.selected.emit(list(self.selected_items))
        return True

    def clear(self) -> None:
        """清除选框与选中集（框选缩放完成后 / 宿主 ``brush clear`` 动作）。"""
        self._coord = None
        self._rect = None
        self._poly = []
        self.selected_items = []
        self._selection_epoch += 1
        self._highlight_key = None
        self._highlight_cache = []
        self.chart.update()

    def _zoom_to_rect(self) -> None:
        """把当前选框映射成 dataZoom 窗口（``dragmode="zoom"``）。

        比例按当前 dataZoom 窗口换算，叠加而不是跳回全量。
        """
        coord = self._coord or self.chart.primaryCoord()
        rect = self._rect
        if rect is None or not isinstance(coord, GridCoord) or rect.width() <= 0:
            return
        comp = self.chart._component("dataZoom")
        if comp is None:
            comp = self.chart._ensure_zoom_component()
        if comp is None:
            return
        plot = coord.plot
        if plot.width() <= 0:
            return
        span = float(comp.end) - float(comp.start)
        if span <= 0:
            return
        frac0 = _clamp((rect.left() - plot.left()) / plot.width(), 0.0, 1.0)
        frac1 = _clamp((rect.right() - plot.left()) / plot.width(), 0.0, 1.0)
        start = float(comp.start) + min(frac0, frac1) * span
        end = float(comp.start) + max(frac0, frac1) * span
        if end - start < 0.5:
            return
        payload = {
            "type": "dataZoom",
            "start": start,
            "end": end,
            "fromBrush": True,
        }
        enable_y = getattr(comp, "enableYAxisZoom", None)
        if callable(enable_y):
            enable_y()
        if (
            getattr(comp, "_y_zoom_enabled", False)
            and plot.height() > 0
            and rect.height() >= 3
        ):
            y_span = float(comp.y_end) - float(comp.y_start)
            if y_span > 0:
                fy0 = _clamp((plot.bottom() - rect.bottom()) / plot.height(), 0.0, 1.0)
                fy1 = _clamp((plot.bottom() - rect.top()) / plot.height(), 0.0, 1.0)
                payload["yStart"] = float(comp.y_start) + min(fy0, fy1) * y_span
                payload["yEnd"] = float(comp.y_start) + max(fy0, fy1) * y_span
        self.chart.dispatchAction(payload)

    def _collect(self) -> None:
        """统计选框内的数据点（经 parseDataPoint + coord 映射，通用各系列）。"""
        self.selected_items = []
        coord = self._coord or self.chart.primaryCoord()
        polygon = None
        if self.brush_type() == "lasso":
            if len(self._poly) < 3:
                return
            polygon = QPolygonF([QPointF(pt) for pt in self._poly])
        elif self._rect is None:
            return
        if not isinstance(coord, GridCoord):
            return
        for r in self.chart.seriesRenderers:
            if not r.visible:
                continue
            series_coord = self.chart.coordFor(r.opt)
            if not isinstance(series_coord, GridCoord):
                continue
            fast = self._collect_vectorized(r, series_coord, self._rect, polygon)
            if fast is not None:
                self.selected_items.extend(fast)
                continue
            for i, item in enumerate(r.data()):
                x, y = parseDataPoint(item, i)
                if y is None:
                    continue
                if series_coord.x_axis.type == "category":
                    idx = series_coord.x_axis.localIndex(x)
                    n = len(series_coord.x_axis.categories)
                    if not (0 <= idx < n):
                        continue  # 窗口外数据点跳过（不映射，防坍缩误选）
                try:
                    pt = series_coord.mapPoint(x, y)
                except Exception:
                    continue
                inside = (
                    polygon.containsPoint(pt, Qt.FillRule.OddEvenFill)
                    if polygon is not None
                    else self._rect.contains(pt)
                )
                if inside:
                    self.selected_items.append(
                        {
                            "series": r.name,
                            "dataIndex": i,
                            "value": y,
                            "x": x,
                            "px": pt.x(),
                            "py": pt.y(),
                        }
                    )
        self._selection_epoch += 1
        self._highlight_key = None
        self._highlight_cache = []
        self._cache_highlight_from_items()

    def _collect_vectorized(self, r, series_coord, rect, polygon):
        """numpy 快路径：矩形 / 套索命中（``None`` = 回退逐点实现）。

        逐点 ``mapPoint`` 在 10 万点上要 238ms，这里一次向量化映射；
        套索先按 bbox 预筛再逐点判多边形（候选上限见 ``LASSO_MAX_CANDIDATES``）。
        """
        np_ = _ds.np
        if np_ is None or rect is None:
            return None
        data = r.data()
        if not data:
            return []
        try:
            arr = np_.asarray(data, dtype=np_.float64)
        except (TypeError, ValueError, OverflowError):
            return None
        if arr.ndim == 1:
            xs = np_.arange(arr.size, dtype=np_.float64)
            ys = arr
        elif arr.ndim == 2 and arr.shape[1] >= 2:
            xs = arr[:, 0]
            ys = arr[:, 1]
        else:
            return None
        mapped = series_coord.mapArrays(xs, ys)
        if mapped is None:
            return None
        px, py = mapped
        ok = np_.isfinite(px) & np_.isfinite(py) & np_.isfinite(ys)
        x0, x1 = rect.left(), rect.right()
        y0, y1 = rect.top(), rect.bottom()
        inside = ok & (px >= x0) & (px <= x1) & (py >= y0) & (py <= y1)
        candidates = np_.flatnonzero(inside)
        if polygon is not None:
            if candidates.size == 0:
                return []
            if candidates.size > self.LASSO_MAX_CANDIDATES:
                step = int(math.ceil(candidates.size / self.LASSO_MAX_CANDIDATES))
                candidates = candidates[::step]
            px_list = px.tolist()
            py_list = py.tolist()
            candidates = [
                int(i)
                for i in candidates.tolist()
                if polygon.containsPoint(
                    QPointF(px_list[i], py_list[i]), Qt.FillRule.OddEvenFill
                )
            ]
        else:
            candidates = candidates.tolist()
        xs_list = xs.tolist()
        ys_list = ys.tolist()
        px_list = px.tolist()
        py_list = py.tolist()
        return [
            {
                "series": r.name,
                "dataIndex": int(i),
                "value": float(ys_list[i]),
                "x": xs_list[i],
                "px": px_list[i],
                "py": py_list[i],
            }
            for i in candidates
        ]

    def _highlight_key_value(self):
        """高亮缓存的键（选中集版本 + option 版本 + 尺寸 + dataZoom 窗口）。"""
        return (
            self._selection_epoch,
            getattr(self.chart, "_opt_version", 0),
            self.chart.width(),
            self.chart.height(),
            self.chart._series_layer_key_zoom(),
        )

    def _cache_highlight_from_items(self) -> bool:
        """用 brush 落定时的屏幕坐标直接建缓存（避免首帧重新逐点映射）。"""
        renderers = {r.name: r for r in self.chart.seriesRenderers}
        coord = self._coord or self.chart.primaryCoord()
        if not isinstance(coord, GridCoord):
            return False
        plot = coord.plot.adjusted(-2, -2, 2, 2)
        out = []
        for item in self.selected_items:
            px, py = item.get("px"), item.get("py")
            if px is None or py is None:
                return False
            r = renderers.get(item.get("series"))
            if r is None or not r.visible:
                continue
            point = QPointF(float(px), float(py))
            if not plot.contains(point):
                continue
            out.append((point, r.color()))
        self._highlight_key = self._highlight_key_value()
        self._highlight_cache = out
        return True

    def _highlight_points(self) -> list:
        """选中点像素位置列表 [(QPointF, QColor)]（带缓存）。

        选中集只在落定 / clear 时变化，而 ``paint`` 每帧都会调用；
        10 万点逐帧重映射约 121ms，故按选中集版本 + 视图状态缓存。
        """
        key = self._highlight_key_value()
        if self._highlight_key == key:
            return self._highlight_cache
        out = []
        coord = self._coord or self.chart.primaryCoord()
        if not isinstance(coord, GridCoord):
            self._highlight_key = key
            self._highlight_cache = out
            return out
        renderers = {r.name: r for r in self.chart.seriesRenderers}
        for item in self.selected_items:
            r = renderers.get(item.get("series"))
            if r is None or not r.visible:
                continue
            y = item.get("value")
            if y is None:
                continue
            series_coord = self.chart.coordFor(r.opt)
            if not isinstance(series_coord, GridCoord):
                continue
            try:
                pt = series_coord.mapPoint(item.get("x"), y)
            except Exception:
                continue
            if not series_coord.plot.adjusted(-2, -2, 2, 2).contains(pt):
                continue
            out.append((pt, r.color()))
        self._highlight_key = key
        self._highlight_cache = out
        return out

    def _paint_lasso(self, p: QPainter) -> None:
        """套索轨迹：半透明填充 + 描边（矩形刷选的同一套强调色语义）。"""
        accent = QColor(T("color.primary"))
        fill = parse_color(accent)
        fill.setAlpha(30)
        stroke = parse_color(accent)
        stroke.setAlpha(140)
        polygon = QPolygonF([QPointF(pt) for pt in self._poly])
        p.save()
        p.setBrush(fill)
        pen = QPen(stroke, 1.2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolygon(polygon)
        p.restore()

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        # 选中点高亮（无论选框是否仍在，选中集持续可见）
        if self.selected_items:
            self._paint_highlight(p)
        if self.brush_type() == "lasso" and len(self._poly) >= 2:
            self._paint_lasso(p)
            return
        if self._rect is None or self._rect.isNull():
            return
        plot = self._plot()
        rect = self._rect.intersected(plot) if not plot.isNull() else self._rect
        p.save()
        # outOfBrush：框外降透明遮罩
        if self.opt.get("outOfBrush") and not plot.isNull():
            mask = QColor(T("color.bg.base"))
            op = _to_float((self.opt.get("outOfBrush") or {}).get("opacity"), 0.45)
            mask.setAlpha(int(255 * _clamp(op if op is not None else 0.45, 0.0, 1.0)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(mask)
            p.drawRect(
                QRectF(
                    plot.left(),
                    plot.top(),
                    max(0.0, rect.left() - plot.left()),
                    plot.height(),
                )
            )
            p.drawRect(
                QRectF(
                    rect.right(),
                    plot.top(),
                    max(0.0, plot.right() - rect.right()),
                    plot.height(),
                )
            )
            p.drawRect(
                QRectF(
                    rect.left(),
                    plot.top(),
                    rect.width(),
                    max(0.0, rect.top() - plot.top()),
                )
            )
            p.drawRect(
                QRectF(
                    rect.left(),
                    rect.bottom(),
                    rect.width(),
                    max(0.0, plot.bottom() - rect.bottom()),
                )
            )
        fill = QColor(T("color.primary"))
        fill.setAlpha(36)
        p.setBrush(fill)
        pen = QPen(QColor(T("color.primary")), 1.2)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(rect)
        p.restore()

    def _paint_highlight(self, p: QPainter) -> None:
        """绘制选中点高亮：系列色描边环 + 亮色内芯（超量按步长抽样）。"""
        p.save()
        r = self.HIGHLIGHT_R
        points = self._highlight_points()
        if len(points) > self.HIGHLIGHT_MAX:
            step = int(math.ceil(len(points) / self.HIGHLIGHT_MAX))
            points = points[::step]
        if len(points) > self.HIGHLIGHT_BULK:
            # 大量选中：按颜色分组一次 drawPoints（5px 圆头笔 = 实心点）。
            groups = {}
            for pt, color in points:
                groups.setdefault(parse_color(color).name(), []).append(pt)
            for name, pts in groups.items():
                pen = QPen(parse_color(name), 5.0)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawPoints(QPolygonF(pts))
            p.restore()
            return
        for pt, color in points:
            ring = parse_color(color)
            ring.setAlpha(200)
            pen = QPen(ring, 1.8)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(pt, r, r)
            core = parse_color(color).lighter(140)
            core.setAlpha(120)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(core)
            p.drawEllipse(pt, r * 0.45, r * 0.45)
        p.restore()

    def layout(self, rect: QRectF) -> None:
        pass

    def hitTest(self, pos: QPointF):
        return None
