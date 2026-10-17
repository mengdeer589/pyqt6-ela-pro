"""Tests for ECharts-fidelity batch: palette / itemStyle / labels / stack /
ripple / drill-down / drag / roam and layout keys."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import ECHARTS_PALETTE, ElaChartWidget


def _make(option, size=(600, 400)):
    chart = ElaChartWidget()
    chart.resize(*size)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


def _component(chart, key):
    return next(c for c in chart.components if getattr(c, "optionKey", "") == key)


def _press(chart, pos):
    QApplication.sendEvent(
        chart,
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    QApplication.processEvents()


def _move(chart, pos):
    QApplication.sendEvent(
        chart,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    QApplication.processEvents()


def _release(chart, pos):
    QApplication.sendEvent(
        chart,
        QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    QApplication.processEvents()


class TestPalette:
    def test_default_palette_is_echarts(self):
        chart = ElaChartWidget()
        names = [c.name() for c in chart.palette()[: len(ECHARTS_PALETTE)]]
        assert names == ECHARTS_PALETTE
        chart.deleteLater()

    def test_first_two_series_colors_distinct(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [
                    {"type": "line", "name": "A", "data": [1, 2]},
                    {"type": "line", "name": "B", "data": [2, 1]},
                ],
            }
        )
        colors = [r.color().name() for r in chart.seriesRenderers]
        assert colors[0] != colors[1]
        chart.deleteLater()


class TestItemStyle:
    def test_series_item_style_color(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [
                    {
                        "type": "bar",
                        "name": "A",
                        "data": [1, 2],
                        "itemStyle": {"color": "#123456"},
                    }
                ],
            }
        )
        assert chart.seriesRenderers[0].color().name() == "#123456"
        chart.deleteLater()

    def test_per_item_color_and_border_radius(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一", "二", "三"]},
                "yAxis": {},
                "series": [
                    {
                        "type": "bar",
                        "name": "A",
                        "data": [
                            {"value": 1, "itemStyle": {"color": "#ff0000"}},
                            {"value": 2},
                            {"value": 3, "itemStyle": {"color": "#00ff00"}},
                        ],
                        "itemStyle": {"borderRadius": 6},
                    }
                ],
            }
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.itemColor(0).name() == "#ff0000"
        assert renderer.itemColor(2).name() == "#00ff00"
        assert renderer.itemColor(1).name() != "#ff0000"
        radius = renderer._bar_radius(0, renderer._bars[0]["rect"])
        assert radius > 0
        chart.deleteLater()

    def test_item_opacity(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一"]},
                "yAxis": {},
                "series": [
                    {
                        "type": "bar",
                        "name": "A",
                        "data": [{"value": 1, "itemStyle": {"opacity": 0.3}}],
                    }
                ],
            }
        )
        assert abs(chart.seriesRenderers[0].itemOpacity(0) - 0.3) < 1e-6
        chart.deleteLater()


class TestLabels:
    def test_label_text_formatter(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一"]},
                "yAxis": {},
                "series": [
                    {
                        "type": "bar",
                        "name": "A",
                        "data": [5],
                        "label": {"show": True, "formatter": "{b}: {c} 件"},
                    }
                ],
            }
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.labelShown() is True
        assert renderer.labelText(0, 5, "一") == "一: 5 件"
        chart.deleteLater()

    def test_label_callable_formatter(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一"]},
                "yAxis": {},
                "series": [
                    {
                        "type": "line",
                        "name": "A",
                        "data": [7],
                        "label": {"show": True, "formatter": lambda p: f"<{p['c']}>"},
                    }
                ],
            }
        )
        assert chart.seriesRenderers[0].labelText(0, 7, "一") == "<7>"
        chart.deleteLater()

    def test_labels_render_without_error(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [
                    {
                        "type": "bar",
                        "name": "A",
                        "data": [1, 2],
                        "label": {"show": True},
                    },
                    {
                        "type": "scatter",
                        "name": "S",
                        "data": [[1, 1], [2, 2]],
                        "label": {"show": True},
                    },
                ],
            }
        )
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        chart.deleteLater()


class TestHeatmapHover:
    """热力图 hover：只高亮悬浮格，不淡化其余格（避免快速移动时整图闪烁）。"""

    @staticmethod
    def _chart():
        return _make(
            {
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {"type": "category", "data": ["a", "b"]},
                "visualMap": {"min": 0, "max": 10},
                "series": [
                    {
                        "type": "heatmap",
                        "name": "H",
                        "data": [[0, 0, 1], [1, 1, 9]],
                    }
                ],
            }
        )

    def test_others_not_dimmed_and_hovered_lighter(self):
        chart = self._chart()
        renderer = chart.seriesRenderers[0]
        other_baseline = renderer._cell_fill_color(renderer._cells[0], None, 1.0)
        other_under_hover = renderer._cell_fill_color(renderer._cells[0], 1, 1.0)
        assert other_under_hover == other_baseline  # 其余格不淡化

        hovered_base = renderer._cell_fill_color(renderer._cells[1], None, 1.0)
        hovered_fill = renderer._cell_fill_color(renderer._cells[1], 1, 1.0)
        assert hovered_fill != hovered_base
        assert hovered_fill.lightness() > hovered_base.lightness()

        chart._hover = (renderer, {"dataIndex": 1})
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        chart.deleteLater()


class TestLineStack:
    def test_stack_accumulates_and_raw_value_kept(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [
                    {"type": "line", "name": "A", "data": [3, 4], "stack": "t"},
                    {"type": "line", "name": "B", "data": [1, 2], "stack": "t"},
                ],
            }
        )
        a, b = chart.seriesRenderers
        assert a._y_at(0) == 3
        assert b._y_at(0) == 4
        assert b._raw_value(0) == 1
        assert b.hitTest(b._points[0]).get("value") == 1
        chart.deleteLater()

    def test_stacked_area_renders(self):
        chart = _make(
            {
                "xAxis": {"type": "category", "data": ["一", "二", "三"]},
                "yAxis": {},
                "series": [
                    {
                        "type": "line",
                        "name": "A",
                        "data": [3, 4, 2],
                        "stack": "t",
                        "areaStyle": {"color": "#5470c6", "opacity": 0.3},
                    },
                    {
                        "type": "line",
                        "name": "B",
                        "data": [1, 2, 3],
                        "stack": "t",
                        "areaStyle": {},
                    },
                ],
            }
        )
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        chart.deleteLater()


class TestEffectScatterRipple:
    def test_ripple_number_and_first_frame(self):
        chart = _make(
            {
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "effectScatter",
                        "name": "R",
                        "rippleEffect": {"number": 4},
                        "data": [[1, 1]],
                    }
                ],
            }
        )
        renderer = chart.seriesRenderers[0]
        assert renderer._number == 4
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        chart.deleteLater()


class TestDrillDown:
    _SUN = {
        "series": [
            {
                "type": "sunburst",
                "name": "S",
                "data": [
                    {
                        "name": "A",
                        "children": [
                            {"name": "A1", "value": 30},
                            {"name": "A2", "value": 20},
                        ],
                    },
                    {"name": "B", "value": 40},
                ],
            }
        ]
    }

    def test_sunburst_drill_and_back(self):
        chart = _make(self._SUN)
        renderer = chart.seriesRenderers[0]
        top_count = len(renderer._nodes)
        node_a = next(n for n in renderer._nodes if n.name == "A")
        r0, r1 = renderer._ring(node_a.level)
        center = renderer._pt(node_a.a0 + (node_a.a1 - node_a.a0) / 2, (r0 + r1) / 2)
        assert renderer.onMousePress(center) is True
        chart._layout_all(force=True)
        assert renderer._focus_path == [0]
        assert len(renderer._nodes) < top_count
        # 点击中心孔返回
        renderer.onMousePress(QPointF(renderer._center))
        chart._layout_all(force=True)
        assert renderer._focus_path == []
        chart.deleteLater()

    def test_treemap_drill_and_reset(self):
        chart = _make(
            {
                "series": [
                    {
                        "type": "treemap",
                        "name": "T",
                        "data": [
                            {
                                "name": "A",
                                "children": [
                                    {"name": "A1", "value": 3},
                                    {"name": "A2", "value": 2},
                                ],
                            },
                            {"name": "B", "value": 2},
                        ],
                    }
                ]
            }
        )
        renderer = chart.seriesRenderers[0]
        assert renderer._crumb_show is True  # ECharts 默认显示面包屑
        node_a = next(n for n in renderer._nodes if n.name == "A")
        # 点击父块 header 条带（子块覆盖不到的区域）下钻
        header = QPointF(node_a.rect.center().x(), node_a.rect.top() + 6)
        assert renderer.onMousePress(header) is True
        chart._layout_all(force=True)
        assert renderer._focus_path == [0]
        renderer.resetDrill()
        chart._layout_all(force=True)
        assert renderer._focus_path == []
        chart.deleteLater()


class TestGraphDrag:
    def test_drag_moves_and_fixes_node(self):
        chart = _make(
            {
                "series": [
                    {
                        "type": "graph",
                        "name": "G",
                        "draggable": True,
                        "data": [
                            {"name": "A", "symbolSize": 30},
                            {"name": "B", "symbolSize": 24},
                        ],
                        "links": [{"source": "A", "target": "B"}],
                    }
                ]
            }
        )
        renderer = chart.seriesRenderers[0]
        start = QPointF(renderer._nodes[0]["pos"])
        _press(chart, start)
        target = QPointF(start.x() + 40, start.y() + 20)
        _move(chart, target)
        _release(chart, target)
        moved = renderer._nodes[0]["pos"]
        assert abs(moved.x() - target.x()) < 1 and abs(moved.y() - target.y()) < 1
        chart.invalidateLayout()
        chart._layout_all(force=True)
        assert abs(renderer._nodes[0]["pos"].x() - target.x()) < 1
        renderer.resetPositions()
        chart.deleteLater()

    def test_drag_disabled_by_default(self):
        """ECharts ``draggable`` 默认 False：不消费按下事件。"""
        chart = _make(
            {
                "series": [
                    {
                        "type": "graph",
                        "name": "G",
                        "data": [
                            {"name": "A", "symbolSize": 30},
                            {"name": "B", "symbolSize": 24},
                        ],
                        "links": [{"source": "A", "target": "B"}],
                    }
                ]
            }
        )
        renderer = chart.seriesRenderers[0]
        start = QPointF(renderer._nodes[0]["pos"])
        assert renderer.onMousePress(start) is False
        assert renderer._drag_index is None
        chart.deleteLater()

    def test_roam_zoom_and_pan(self):
        chart = _make(
            {
                "series": [
                    {
                        "type": "graph",
                        "name": "G",
                        "roam": True,
                        "data": [{"name": "A", "symbolSize": 30}],
                    }
                ]
            }
        )
        renderer = chart.seriesRenderers[0]
        assert renderer.onWheel(_wheel_event(QPointF(300, 200))) is True
        assert renderer._zoom > 1.0
        renderer.onMousePress(QPointF(300, 200))
        renderer.onMouseMove(QPointF(340, 210))
        renderer.onMouseRelease(QPointF(340, 210))
        assert renderer._pan.x() > 0
        renderer.resetRoam()
        assert renderer._zoom == 1.0 and renderer._pan == QPointF()
        chart.deleteLater()


def _wheel_event(pos: QPointF):
    return QWheelEvent(
        QPointF(pos),
        QPointF(pos.toPoint()),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


class TestMapRoam:
    _MAP = {
        "visualMap": {"min": 0, "max": 150},
        "series": [
            {
                "type": "map",
                "name": "M",
                "roam": True,
                "data": [{"name": "华北", "value": 120}],
            }
        ],
    }

    def test_wheel_zoom_and_pan(self):
        chart = _make(self._MAP)
        renderer = chart.seriesRenderers[0]
        rect = renderer._rect
        wheel = QWheelEvent(
            QPointF(rect.center()),
            QPointF(chart.mapToGlobal(rect.center().toPoint())),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(chart, wheel)
        QApplication.processEvents()
        assert renderer._zoom > 1.0
        _press(chart, rect.center())
        _move(chart, QPointF(rect.center().x() + 30, rect.center().y() + 10))
        _release(chart, QPointF(rect.center().x() + 30, rect.center().y() + 10))
        assert renderer._pan.x() > 0
        renderer.resetRoam()
        assert renderer._zoom == 1.0 and renderer._pan == QPointF()
        chart.deleteLater()

    def test_roam_disabled_by_default(self):
        """ECharts ``roam`` 默认 False：滚轮 / 拖拽不生效。"""
        chart = _make(
            {
                "series": [
                    {"type": "map", "name": "M", "data": [{"name": "华北", "value": 1}]}
                ]
            }
        )
        renderer = chart.seriesRenderers[0]
        rect = renderer._rect
        wheel = QWheelEvent(
            QPointF(rect.center()),
            QPointF(chart.mapToGlobal(rect.center().toPoint())),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(chart, wheel)
        QApplication.processEvents()
        assert renderer._zoom == 1.0
        assert renderer.onMousePress(rect.center()) is False
        assert renderer._pan_start is None
        chart.deleteLater()


class TestLayoutKeys:
    def test_bar_gap_shrinks_bars(self):
        base = {
            "xAxis": {"type": "category", "data": ["一", "二"]},
            "yAxis": {},
            "legend": {"show": False},
        }
        narrow = _make(
            {
                **base,
                "series": [
                    {"type": "bar", "name": "A", "data": [1, 2]},
                    {"type": "bar", "name": "B", "data": [2, 1]},
                ],
            }
        )
        gapped = _make(
            {
                **base,
                "series": [
                    {"type": "bar", "name": "A", "data": [1, 2], "barGap": "80%"},
                    {"type": "bar", "name": "B", "data": [2, 1], "barGap": "80%"},
                ],
            }
        )
        w1 = narrow.seriesRenderers[0]._bars[0]["w"]
        w2 = gapped.seriesRenderers[0]._bars[0]["w"]
        assert w2 < w1
        narrow.deleteLater()
        gapped.deleteLater()

    def test_funnel_align_and_formatter(self):
        chart = _make(
            {
                "series": [
                    {
                        "type": "funnel",
                        "name": "F",
                        "funnelAlign": "left",
                        "label": {"show": True, "formatter": "{b} = {c} ({d})"},
                        "data": [
                            {"name": "展现", "value": 100},
                            {"name": "点击", "value": 60},
                        ],
                    }
                ]
            }
        )
        renderer = chart.seriesRenderers[0]
        lefts = [layer["left"] for layer in renderer._layers]
        assert abs(lefts[0] - lefts[1]) < 1.0  # 左对齐
        assert renderer._funnel_label(renderer._layers[0], "60%") == "展现 = 100 (60%)"
        chart.deleteLater()

    def test_radar_axis_name_toggle(self):
        chart = _make(
            {
                "series": [
                    {
                        "type": "radar",
                        "name": "R",
                        "indicator": [
                            {"name": "A", "max": 10},
                            {"name": "B", "max": 10},
                        ],
                        "axisName": {"show": False},
                        "splitLine": {"lineStyle": {"color": "#ff0000"}},
                        "data": [{"name": "S", "value": [5, 6]}],
                    }
                ]
            }
        )
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        chart.deleteLater()

    def test_sankey_line_style_gradient(self):
        chart = _make(
            {
                "series": [
                    {
                        "type": "sankey",
                        "name": "S",
                        "lineStyle": {"color": "gradient", "opacity": 0.5},
                        "data": [{"name": "A"}, {"name": "B"}],
                        "links": [{"source": "A", "target": "B", "value": 5}],
                    }
                ]
            }
        )
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        chart.deleteLater()
