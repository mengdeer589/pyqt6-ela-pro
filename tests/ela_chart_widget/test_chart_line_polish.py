"""折线专项：smoothMonotone / step 数组 / areaStyle.origin / endLabel / 符号。"""

from __future__ import annotations

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QPainterPath

from _pixels import skip_if_no_pixels
from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts.series_cartesian import (
    _monotone_path,
    _reversed_path,
    _smooth_path,
)


def _chart(make, series, **patch):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    option = {
        "animation": False,
        "xAxis": {
            "type": "category",
            "data": [str(i) for i in range(len(series[0]["data"]))],
        },
        "yAxis": {"type": "value"},
        "series": series,
    }
    option.update(patch)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    chart.grab()
    return chart


class TestSmoothMonotone:
    def test_monotone_path_does_not_overshoot(self):
        points = [QPointF(0, 0), QPointF(1, 10), QPointF(2, 10), QPointF(3, 10)]
        path = _monotone_path(points)
        bounds = path.boundingRect()
        assert bounds.top() >= -0.01
        assert bounds.bottom() <= 10.01

    def test_series_uses_monotone_path(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [0, 10, 10, 10],
                    "smooth": True,
                    "smoothMonotone": True,
                }
            ],
        )
        path, _pts = chart.seriesRenderers[0]._line_path(
            [QPointF(0, 100), QPointF(10, 50), QPointF(20, 50)]
        )
        assert path is not None
        assert path.boundingRect().top() >= 49.9


class TestStepAndOrigin:
    def test_step_array_start(self, qapp, make):
        chart = _chart(
            make,
            [{"type": "line", "name": "A", "data": [1, 2], "step": [True, False]}],
        )
        _path, pts = chart.seriesRenderers[0]._line_path(
            [QPointF(0, 100), QPointF(10, 50)]
        )
        assert len(pts) == 3
        assert pts[1] == QPointF(0, 50)

    def test_area_origin_start_uses_axis_min(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [100, 200, 150],
                    "areaStyle": {"origin": "start"},
                }
            ],
        )
        renderer = chart.seriesRenderers[0]
        coord = chart.primaryCoord()
        baseline = renderer._baseline_y(coord, {"origin": "start"})
        assert abs(baseline - coord.plot.bottom()) < 1.0

    def test_area_origin_number(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [100, 200, 150],
                    "areaStyle": {"origin": 150},
                }
            ],
        )
        renderer = chart.seriesRenderers[0]
        coord = chart.primaryCoord()
        baseline = renderer._baseline_y(coord, {"origin": 150})
        expected = coord.y_axis.map(150, coord.plot.bottom(), coord.plot.top())
        assert abs(baseline - expected) < 1.0


class TestLineSymbolsAndEndLabel:
    def test_show_all_symbol(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "mode": "lines+markers",
                    "showAllSymbol": True,
                    "data": list(range(100)),
                }
            ],
        )
        assert len(chart.seriesRenderers[0]._symbol_items) == 100

    def test_symbol_rotate_renders(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "mode": "lines+markers",
                    "symbol": "triangle",
                    "symbolRotate": 90,
                    "data": [1, 2, 3],
                }
            ],
        )
        assert chart.seriesRenderers[0]._symbol_items
        assert chart.grab().width() == chart.width()

    def test_end_label(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [1, 5, 9],
                    "endLabel": {"show": True, "formatter": "末值 {c}"},
                }
            ],
        )
        end = chart.seriesRenderers[0]._end_label
        assert end is not None
        assert end[0] == "末值 9"

    def test_line_style_opacity_and_cap(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [1, 2, 3],
                    "lineStyle": {"opacity": 0.5, "cap": "butt", "join": "bevel"},
                }
            ],
        )
        assert chart.grab().width() == chart.width()


def _first_cubic_mid(path):
    """路径首段三次贝塞尔在 t=0.5 的点（曲线的真实中点）。"""
    e = [path.elementAt(i) for i in range(4)]
    return QPointF(
        (e[0].x + 3 * e[1].x + 3 * e[2].x + e[3].x) / 8.0,
        (e[0].y + 3 * e[1].y + 3 * e[2].y + e[3].y) / 8.0,
    )


def _channel_delta(a, b):
    return max(
        abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue())
    )


def _skip_if_blank(image):
    """平台画不出图形时跳过像素断言（10px 网格采样，避免全图扫描）。"""
    colors = {
        image.pixelColor(x, y).name()
        for y in range(0, image.height(), 10)
        for x in range(0, image.width(), 10)
        if image.pixelColor(x, y).alpha() > 200
    }
    skip_if_no_pixels(colors if len(colors) > 1 else set(), "面积像素")


class TestAreaFillHugsCurve:
    """面积填充的上下边界必须与描边共用同一条几何。"""

    def test_smooth_area_fill_follows_curve(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [10, 90, 10, 90],
                    "smooth": True,
                    "areaStyle": {"opacity": 0.3},
                }
            ],
        )
        renderer = chart.seriesRenderers[0]
        coord = chart.primaryCoord()
        pts = [p for p in renderer._points if p is not None]
        curve, geom = renderer._line_path(pts)
        assert curve is not None
        base_y = renderer._baseline_y(coord, renderer.opt.get("areaStyle"))
        fill = renderer._area_fill_path([None] * len(pts), base_y, curve, geom, coord)
        mid = _first_cubic_mid(curve)
        # 曲线中点上方是空白、下方必须被填充；旧的「直线弦」填充恰好相反
        assert not fill.contains(QPointF(mid.x(), mid.y() - 4))
        assert fill.contains(QPointF(mid.x(), mid.y() + 4))

    def test_empty_area_style_renders(self, qapp, make):
        """``areaStyle: {}`` 与 ECharts 一致 = 显示，不能当成关闭。"""
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [10, 90, 10, 90],
                    "smooth": True,
                    "areaStyle": {},
                }
            ],
        )
        image = chart.grab().toImage()
        renderer = chart.seriesRenderers[0]
        pts = [p for p in renderer._points if p is not None]
        curve, _geom = renderer._line_path(pts)
        mid = _first_cubic_mid(curve)
        _skip_if_blank(image)
        inside = image.pixelColor(round(mid.x()), round(mid.y()) + 6)
        assert _channel_delta(inside, image.pixelColor(5, 5)) >= 8

    def test_smooth_area_renders_below_curve(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [10, 90, 10, 90],
                    "smooth": True,
                    "areaStyle": {"opacity": 0.35},
                }
            ],
        )
        image = chart.grab().toImage()
        renderer = chart.seriesRenderers[0]
        pts = [p for p in renderer._points if p is not None]
        mid = _first_cubic_mid(renderer._line_path(pts)[0])
        _skip_if_blank(image)
        bg = image.pixelColor(5, 5)
        below = image.pixelColor(round(mid.x()), round(mid.y()) + 6)
        above = image.pixelColor(round(mid.x()), round(mid.y()) - 6)
        assert _channel_delta(below, bg) >= 8
        assert _channel_delta(above, bg) <= 3

    def test_straight_area_fill_stays_polyline(self, qapp, make):
        chart = _chart(
            make,
            [{"type": "line", "name": "A", "data": [10, 90, 10], "areaStyle": {}}],
        )
        renderer = chart.seriesRenderers[0]
        coord = chart.primaryCoord()
        pts = [p for p in renderer._points if p is not None]
        curve, geom = renderer._line_path(pts)
        assert curve is None
        fill = renderer._area_fill_path(
            [None] * len(pts), renderer._baseline_y(coord, {}), None, geom, coord
        )
        kinds = {fill.elementAt(i).type for i in range(fill.elementCount())}
        assert QPainterPath.ElementType.CurveToElement not in kinds

    def test_stacked_smooth_area_follows_base_curve(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [10, 60, 20, 60],
                    "stack": "t",
                    "smooth": True,
                    "areaStyle": {"opacity": 0.3},
                },
                {
                    "type": "line",
                    "name": "B",
                    "data": [10, 30, 50, 30],
                    "stack": "t",
                    "smooth": True,
                    "areaStyle": {"opacity": 0.3},
                },
            ],
        )
        renderer = chart.seriesRenderers[1]
        coord = chart.primaryCoord()
        base_pts = [
            coord.mapPoint(renderer._x_at(o), renderer._stack_base.get(o, 0.0))
            for o in renderer._point_idx
        ]
        curve, geom = renderer._line_path(
            [p for p in renderer._points if p is not None]
        )
        fill = renderer._area_fill_path(base_pts, None, curve, geom, coord)
        base_mid = _first_cubic_mid(_smooth_path(base_pts, 0.5))
        # 上带在基线上方（y 更小），直线弦会把这块漏掉
        assert fill.contains(QPointF(base_mid.x(), base_mid.y() - 4))
        assert not fill.contains(QPointF(base_mid.x(), base_mid.y() + 4))

    def test_stacked_step_area_follows_base_steps(self, qapp, make):
        chart = _chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [10, 60, 20, 60],
                    "stack": "t",
                    "step": "start",
                    "areaStyle": {"opacity": 0.3},
                },
                {
                    "type": "line",
                    "name": "B",
                    "data": [10, 30, 50, 30],
                    "stack": "t",
                    "step": "start",
                    "areaStyle": {"opacity": 0.3},
                },
            ],
        )
        renderer = chart.seriesRenderers[1]
        coord = chart.primaryCoord()
        base_pts = [
            coord.mapPoint(renderer._x_at(o), renderer._stack_base.get(o, 0.0))
            for o in renderer._point_idx
        ]
        rev = renderer._line_path_reversed(base_pts)
        first, second = rev.elementAt(0), rev.elementAt(1)
        assert (first.x, first.y) == (base_pts[-1].x(), base_pts[-1].y())
        # step=start 的末段反向：先回到 (前一列, 末点值) 的拐角
        assert (second.x, second.y) == (base_pts[-2].x(), base_pts[-1].y())


class TestReversedPath:
    def test_reversed_curve_matches_forward(self):
        pts = [QPointF(0, 100), QPointF(50, 0), QPointF(100, 100), QPointF(150, 40)]
        fwd = _smooth_path(pts, 0.5)
        rev = _reversed_path(fwd)
        for t in (0.1, 0.3, 0.5, 0.7, 0.9):
            a, b = fwd.pointAtPercent(t), rev.pointAtPercent(1 - t)
            assert abs(a.x() - b.x()) < 0.5
            assert abs(a.y() - b.y()) < 0.5

    def test_reversed_polyline(self):
        pts = [QPointF(0, 0), QPointF(10, 20), QPointF(20, 5)]
        path = QPainterPath()
        path.moveTo(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        rev = _reversed_path(path)
        elems = [rev.elementAt(i) for i in range(rev.elementCount())]
        assert (elems[0].x, elems[0].y) == (20.0, 5.0)
        assert (elems[1].x, elems[1].y) == (10.0, 20.0)
        assert (elems[2].x, elems[2].y) == (0.0, 0.0)
