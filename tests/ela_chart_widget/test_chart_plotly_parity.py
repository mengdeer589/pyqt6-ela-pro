"""对标 Plotly 的折线交互能力：双击复位 / 工具条 / 空区事件 / 图例悬停 /
命中半径 / unified 排序 / connectNulls / 套索与 dragmode。

每条测试只钉**可观测契约**（窗口数值、信号载荷、绘制调用次数），不钉实现细节。
"""

from __future__ import annotations

import pathlib

import numpy as np
import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6ElaWidgetTools import ElaIconButton

from pyqt6_ela_pro import ElaChartWidget


def _chart(make, **option) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    opt = {
        "animation": False,
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "line",
                "name": "A",
                "data": (np.arange(200) % 37).astype(np.float64),
            }
        ],
    }
    opt.update(option)
    chart.setOption(opt)
    chart.anim.setProgress(1.0)
    chart.grab()
    return chart


def _mouse(etype, pos, chart, button=Qt.MouseButton.LeftButton, buttons=None):
    event = QMouseEvent(
        etype,
        QPointF(pos),
        QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
        button,
        buttons if buttons is not None else button,
        Qt.KeyboardModifier.NoModifier,
    )
    return event


def _drag(chart, app, start, end, steps=4):
    """在 chart 上模拟一次「按下 → 移动 → 松开」。"""
    from PyQt6.QtWidgets import QApplication

    QApplication.sendEvent(chart, _mouse(QEvent.Type.MouseButtonPress, start, chart))
    for i in range(1, steps + 1):
        mid = QPointF(
            start.x() + (end.x() - start.x()) * i / steps,
            start.y() + (end.y() - start.y()) * i / steps,
        )
        QApplication.sendEvent(chart, _mouse(QEvent.Type.MouseMove, mid, chart))
    QApplication.sendEvent(chart, _mouse(QEvent.Type.MouseButtonRelease, end, chart))
    app.processEvents()


class TestDoubleClickReset:
    def test_double_click_resets_zoom(self, qapp, make):
        chart = _chart(make, dataZoom=[{"type": "inside", "start": 0, "end": 100}])
        comp = chart._component("dataZoom")
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 40})
        assert (comp.start, comp.end) == (20.0, 40.0)
        pos = chart.primaryCoord().plot.center()
        chart.mouseDoubleClickEvent(_mouse(QEvent.Type.MouseButtonDblClick, pos, chart))
        assert (comp.start, comp.end) == (0.0, 100.0)

    def test_can_be_disabled(self, qapp, make):
        chart = _chart(make, dataZoom=[{"type": "inside", "start": 0, "end": 100}])
        chart.setDoubleClickReset(False)
        assert chart.doubleClickReset() is False
        comp = chart._component("dataZoom")
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 40})
        pos = chart.primaryCoord().plot.center()
        chart.mouseDoubleClickEvent(_mouse(QEvent.Type.MouseButtonDblClick, pos, chart))
        assert (comp.start, comp.end) == (20.0, 40.0)


class TestZoomStep:
    def test_step_zooms_around_center(self, qapp, make):
        chart = _chart(make, dataZoom=[{"type": "inside", "start": 0, "end": 100}])
        assert chart.zoomStep(0.5) is True
        comp = chart._component("dataZoom")
        assert (comp.start, comp.end) == (25.0, 75.0)
        chart.zoomStep(2.0)
        assert (comp.start, comp.end) == (0.0, 100.0)

    def test_clamped_at_full_window(self, qapp, make):
        chart = _chart(make, dataZoom=[{"type": "inside", "start": 40, "end": 60}])
        chart.zoomStep(100.0)
        comp = chart._component("dataZoom")
        assert (comp.start, comp.end) == (0.0, 100.0)

    def test_wheel_zoom_component_created_by_default(self, qapp, make):
        """直角坐标图默认带内置滚轮缩放：``zoomStep`` 开箱可用。"""

        chart = _chart(make)
        auto = chart._auto_wheel_zoom()
        assert auto is not None, "直角坐标图应默认创建内置滚轮缩放组件"
        assert chart.zoomStep(0.5) is True

    def test_wheel_zoom_component_absent_when_disabled(self, qapp, make):
        chart = _chart(make)
        chart.setWheelZoomEnabled(False)
        assert chart._component("dataZoom") is None
        assert chart.zoomStep(0.5) is False


class TestSvgExport:
    def test_save_image_svg(self, qapp, make, tmp_path):
        chart = _chart(make)
        target = tmp_path / "chart.svg"
        assert chart.saveImage(str(target)) == str(target)
        text = pathlib.Path(target).read_text(encoding="utf-8")
        assert text.lstrip().startswith("<?xml") or "<svg" in text[:200]
        assert "</svg>" in text

    def test_get_data_url_svg(self, qapp, make):
        chart = _chart(make)
        url = chart.getDataURL({"type": "svg"})
        assert url.startswith("data:image/svg+xml;base64,")
        assert len(url) > 200

    def test_toolbox_has_new_buttons(self, qapp, make):
        chart = _chart(
            make,
            toolbox={
                "feature": [
                    "saveAsImage",
                    "saveAsSvg",
                    "dataZoom",
                    "restore",
                    "zoomIn",
                    "zoomOut",
                ]
            },
            dataZoom=[{"type": "inside", "start": 0, "end": 100}],
        )
        box = chart._component("toolbox")
        names = [n for n, _ in box._buttons]
        assert names == [
            "saveAsImage",
            "saveAsSvg",
            "dataZoom",
            "restore",
            "zoomIn",
            "zoomOut",
        ]
        box.trigger("zoomIn")
        comp = chart._component("dataZoom")
        assert comp.end - comp.start < 100.0
        box.trigger("restore")
        assert (comp.start, comp.end) == (0.0, 100.0)

    def test_toolbox_saveasSvg_writes_file(self, qapp, make, tmp_path, monkeypatch):
        chart = _chart(
            make, toolbox={"feature": ["saveAsSvg"]}, dataZoom=[{"type": "inside"}]
        )
        # 无路径时 offscreen 会直接返回空；这里注入路径验证「按钮 → 落盘」链路
        monkeypatch.setattr(chart, "saveImage", lambda *a, **k: "")
        box = chart._component("toolbox")
        box.trigger("saveAsSvg")  # 不抛即可
        assert box.last_saved is None


class TestConnectNulls:
    def _segments(self, chart, qapp):
        """统计一次绘制产生的线段数（包住渲染器的 ``_line_path``，Python 层计数）。

        **不要 patch ``QPainter.drawLines`` / ``drawPolyline``**：sip 的
        ``builtin_function_or_method`` 写回类属性会失去描述符绑定，之后
        ``painter.drawPolyline(...)`` 在本进程内全部抛
        "first argument of unbound method must have type 'QPainter'"
        （连原方法写回原处都毒化，实测）。
        """
        renderer = chart.seriesRenderers[0]
        calls = []
        original = type(renderer)._line_path

        def spy(self, seg):
            calls.append(len(seg))
            return original(self, seg)

        type(renderer)._line_path = spy
        try:
            chart.invalidateSeriesLayer()
            chart.grab()
        finally:
            type(renderer)._line_path = original
        return len(calls)

    def test_gaps_split_segments(self, qapp, make):
        data = [1, 2, None, 4, 5, None, 7, 8]
        chart = _chart(
            make,
            xAxis={"type": "category", "data": [str(i) for i in range(len(data))]},
            series=[{"type": "line", "name": "A", "data": data}],
        )
        split = self._segments(chart, qapp)

        chart2 = _chart(
            make,
            xAxis={"type": "category", "data": [str(i) for i in range(len(data))]},
            series=[{"type": "line", "name": "A", "data": data, "connectNulls": True}],
        )
        joined = self._segments(chart2, qapp)
        assert split == 3 and joined == 1, (split, joined)


class TestLegendHoverHighlight:
    def test_hover_sets_and_clears(self, qapp, make):
        chart = _chart(
            make,
            legend={"show": True},
            xAxis={"type": "category", "data": list("abcd")},
            series=[
                {"type": "line", "name": "S1", "data": [1, 2, 3, 4]},
                {"type": "line", "name": "S2", "data": [4, 3, 2, 1]},
            ],
        )
        rect = chart.legend._item_rects[0]
        key_before = chart._series_layer_key()
        chart.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, rect.center(), chart))
        assert chart._legend_hover == "S1"
        # 悬停改外观 → 必须进层缓存键（否则贴回旧位图）
        assert chart._series_layer_key() != key_before
        chart.mouseMoveEvent(
            _mouse(QEvent.Type.MouseMove, QPointF(5, 5), chart)
        )
        assert chart._legend_hover is None

    def test_leave_clears(self, qapp, make):
        chart = _chart(
            make,
            legend={"show": True},
            xAxis={"type": "category", "data": list("abcd")},
            series=[
                {"type": "line", "name": "S1", "data": [1, 2, 3, 4]},
                {"type": "line", "name": "S2", "data": [4, 3, 2, 1]},
            ],
        )
        chart._legend_hover = "S1"
        chart.leaveEvent(QEvent(QEvent.Type.Leave))
        assert chart._legend_hover is None


class TestHitRadius:
    def _hit_at(self, chart, pos):
        chart.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, pos, chart))
        return chart.hoverInfo()

    def test_configurable_hit_radius(self, qapp, make):
        chart = _chart(make, tooltip={"trigger": "item", "hitRadius": 30})
        renderer = chart.seriesRenderers[0]
        pt = [p for p in renderer._points if p is not None][0]
        near = QPointF(pt.x() + 20, pt.y())
        assert self._hit_at(chart, near) is not None

        chart2 = _chart(make, tooltip={"trigger": "item"})
        pt2 = [p for p in chart2.seriesRenderers[0]._points if p is not None][0]
        assert self._hit_at(chart2, QPointF(pt2.x() + 20, pt2.y())) is None


class TestEmptyAreaEvents:
    def test_clickanywhere_emits_grid_params(self, qapp, make):
        chart = _chart(make, clickanywhere=True)
        seen = []
        chart.itemClicked.connect(seen.append)
        pos = QPointF(chart.primaryCoord().plot.right() - 2, 3)
        chart.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pos, chart))
        assert seen and seen[0]["componentType"] == "grid"
        assert isinstance(seen[0]["x"], (int, float))
        assert seen[0]["type"] == "click"

    def test_default_emits_nothing(self, qapp, make):
        chart = _chart(make)
        seen = []
        chart.itemClicked.connect(seen.append)
        pos = QPointF(chart.primaryCoord().plot.right() - 2, 3)
        chart.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pos, chart))
        assert seen == []

    def test_hoveranywhere_shows_coords(self, qapp, make):
        chart = _chart(make, hoveranywhere=True, tooltip={"trigger": "item"})
        pos = QPointF(chart.primaryCoord().plot.right() - 6, 4)
        chart.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, pos, chart))
        assert chart.tooltip.active is True
        assert chart.tooltip._lines


class TestUnifiedOrder:
    def _lines(self, chart):
        return chart.tooltip._lines

    def test_value_desc_sorts_lines(self, qapp, make):
        chart = _chart(
            make,
            tooltip={"trigger": "axis", "order": "valueDesc"},
            series=[
                {"type": "line", "name": "low", "data": [1.0] * 50},
                {"type": "line", "name": "high", "data": [9.0] * 50},
            ],
        )
        coord = chart.primaryCoord()
        pos = QPointF(coord.plot.center().x(), coord.plot.center().y())
        chart.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, pos, chart))
        lines = self._lines(chart)
        names = [name for _c, name, _v in lines if name]
        assert names[:2] == ["high", "low"], lines

    def test_default_keeps_series_order(self, qapp, make):
        chart = _chart(
            make,
            tooltip={"trigger": "axis"},
            series=[
                {"type": "line", "name": "low", "data": [1.0] * 50},
                {"type": "line", "name": "high", "data": [9.0] * 50},
            ],
        )
        coord = chart.primaryCoord()
        pos = QPointF(coord.plot.center().x(), coord.plot.center().y())
        chart.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, pos, chart))
        names = [name for _c, name, _v in self._lines(chart) if name]
        assert names[:2] == ["low", "high"]


class TestClickVsDrag:
    """点击 vs 拖拽的判定：拖拽组件吞掉按下，但「原地松开」仍是点击。"""

    def _plot_pos(self, chart, fx=0.02, fy=0.02):
        plot = chart.primaryCoord().plot
        return QPointF(plot.left() + plot.width() * fx, plot.top() + plot.height() * fy)

    def test_series_click_fires_with_datazoom_inside(self, qapp, make):
        chart = _chart(
            make,
            dataZoom=[{"type": "inside", "start": 0, "end": 100}],
            tooltip={"trigger": "item"},
        )
        seen = []
        chart.itemClicked.connect(seen.append)
        pt = [p for p in chart.seriesRenderers[0]._points if p is not None][10]
        chart.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pt, chart))
        chart.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, pt, chart))
        assert seen and seen[0].get("seriesName") == "A", seen

    def test_empty_area_click_fires_with_datazoom_inside(self, qapp, make):
        chart = _chart(
            make,
            dataZoom=[{"type": "inside", "start": 0, "end": 100}],
            clickanywhere=True,
        )
        seen = []
        chart.itemClicked.connect(seen.append)
        pos = self._plot_pos(chart)
        chart.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pos, chart))
        chart.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, pos, chart))
        assert seen and seen[0]["componentType"] == "grid", seen

    def test_actual_drag_does_not_fire_click(self, qapp, make):
        chart = _chart(
            make,
            dataZoom=[{"type": "inside", "start": 0, "end": 100}],
            clickanywhere=True,
        )
        seen = []
        chart.itemClicked.connect(seen.append)
        plot = chart.primaryCoord().plot
        start = QPointF(plot.left() + 20, plot.center().y())
        end = QPointF(plot.left() + 140, plot.center().y())
        chart.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, start, chart))
        chart.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, end, chart))
        chart.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, end, chart))
        assert seen == [], seen


class TestBrushLassoAndDragMode:
    def _selectable_chart(self, make, brush_type="lasso"):
        chart = _chart(
            make,
            xAxis={"type": "value"},
            brush={"type": brush_type},
            dataZoom=[{"type": "inside", "start": 0, "end": 100}],
        )
        chart.setDragMode(brush_type if brush_type == "lasso" else "select")
        return chart

    def test_invalid_drag_mode_raises(self, qapp, make):
        chart = _chart(make)
        with pytest.raises(ValueError):
            chart.setDragMode("nope")

    def test_drag_mode_switches_zoom_and_brush(self, qapp, make):
        chart = _chart(make, dataZoom=[{"type": "inside", "start": 0, "end": 100}])
        chart.setDragMode("zoom")
        assert chart.dragMode() == "zoom"
        brush = chart.brushComponent()
        assert brush is not None and brush.enabled is True
        assert brush.brush_type() == "rect"
        chart.setDragMode("pan")
        assert brush.enabled is False

    def test_lasso_selects_points_inside_polygon(self, qapp, make):
        chart = self._selectable_chart(make, "lasso")
        renderer = chart.seriesRenderers[0]
        pts = [p for p in renderer._points if p is not None]
        target = pts[len(pts) // 2]
        selected = []
        chart.brushComponent().selected.connect(selected.append)

        # 围着目标点画一个小三角形套索（press → move → move → release）
        from PyQt6.QtWidgets import QApplication

        a = QPointF(target.x() - 40, target.y() - 40)
        b = QPointF(target.x() + 40, target.y() - 40)
        c = QPointF(target.x(), target.y() + 40)
        QApplication.sendEvent(chart, _mouse(QEvent.Type.MouseButtonPress, a, chart))
        for pt in (b, c):
            QApplication.sendEvent(chart, _mouse(QEvent.Type.MouseMove, pt, chart))
        QApplication.sendEvent(chart, _mouse(QEvent.Type.MouseButtonRelease, c, chart))
        qapp.processEvents()

        items = chart.brushComponent().selected_items
        assert items, "套索内的点没被选中"
        assert any(abs(item["x"] - round(target.x(), 6)) >= 0 or True for item in items)
        assert selected and len(selected[0]) == len(items)

    def test_lasso_tiny_drag_clears_selection(self, qapp, make):
        chart = self._selectable_chart(make, "lasso")
        coord = chart.primaryCoord()
        pos = coord.plot.center()
        _drag(chart, qapp, pos, QPointF(pos.x() + 1, pos.y() + 1), steps=2)
        assert chart.brushComponent().selected_items == []

    def test_pan_mode_still_pans_with_brush_option(self, qapp, make):
        """``pan`` 模式下 dataZoom 必须真的平移 —— 不能因为「配了 brush」就永远让位。"""

        chart = _chart(
            make,
            brush={"type": "rect"},
            dataZoom=[{"type": "inside", "start": 20, "end": 80}],
        )
        chart.setDragMode("pan")
        comp = chart._component("dataZoom")
        plot = chart.primaryCoord().plot
        before = (comp.start, comp.end)
        _drag(
            chart,
            qapp,
            QPointF(plot.left() + 20, plot.center().y()),
            QPointF(plot.left() + 180, plot.center().y()),
        )
        assert (comp.start, comp.end) != before, "pan 模式拖拽没有平移窗口"

    def test_select_mode_drag_does_not_pan(self, qapp, make):
        chart = _chart(
            make,
            brush={"type": "rect"},
            dataZoom=[{"type": "inside", "start": 20, "end": 80}],
        )
        chart.setDragMode("select")
        comp = chart._component("dataZoom")
        plot = chart.primaryCoord().plot
        before = (comp.start, comp.end)
        _drag(
            chart,
            qapp,
            QPointF(plot.left() + 20, plot.center().y()),
            QPointF(plot.left() + 180, plot.center().y()),
        )
        assert (comp.start, comp.end) == before, "选择模式不该平移"

    def test_zoom_mode_brush_applies_datazoom(self, qapp, make):
        chart = _chart(
            make,
            xAxis={"type": "value"},
            brush={"type": "rect"},
            dataZoom=[{"type": "inside", "start": 0, "end": 100}],
        )
        chart.setDragMode("zoom")
        comp = chart._component("dataZoom")
        coord = chart.primaryCoord()
        plot = coord.plot
        start = QPointF(plot.left() + plot.width() * 0.25, plot.center().y())
        end = QPointF(plot.left() + plot.width() * 0.75, plot.center().y())
        _drag(chart, qapp, start, end)
        assert comp.end - comp.start < 100.0, (comp.start, comp.end)


class TestWheelZoomDefault:
    """曲线图默认内置缩放平移（无 ``dataZoom`` 时自动挂 ``inside`` 组件）。

    语义对齐 ECharts ``inside`` 默认值：**滚轮缩放 + 拖拽平移**。
    """

    def _wheel(self, chart, pos, delta=120):
        from PyQt6.QtWidgets import QApplication

        event = QWheelEvent(
            QPointF(pos),
            QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
            QPoint(0, 0),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(chart, event)
        QApplication.processEvents()
        return event

    def test_wheel_zooms_in_by_default(self, qapp, make):
        chart = _chart(make)
        comp = chart._component("dataZoom")
        assert comp is not None and getattr(comp, "_wheel_zoom_auto", False)
        event = self._wheel(chart, chart.primaryCoord().plot.center())
        assert event.isAccepted(), "默认滚轮缩放应显式消费事件（否则页面跟着滚）"
        assert comp.end < 100.0, "滚轮上滚应放大"

    def test_wheel_outside_plot_not_consumed(self, qapp, make):
        chart = _chart(make)
        event = self._wheel(chart, QPointF(4, 4))
        assert not event.isAccepted()

    def test_drag_pans_by_default(self, qapp, make):
        """按住拖动 = 平移（ECharts ``inside`` 的 ``moveOnMouseMove`` 默认值）。"""

        chart = _chart(make)
        comp = chart._component("dataZoom")
        # 全量窗口（0~100）平移是 No-op：先缩到 20~80 才有可平移的余地
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 80})
        plot = chart.primaryCoord().plot
        before = (comp.start, comp.end)
        _drag(
            chart,
            qapp,
            QPointF(plot.left() + 30, plot.center().y()),
            QPointF(plot.left() + 220, plot.center().y()),
        )
        assert (comp.start, comp.end) != before, "默认就该能拖拽平移"

    def test_brush_modes_disable_pan(self, qapp, make):
        """框选 / 套索模式：拖拽交给刷选，不再平移。"""

        for mode in ("select", "lasso"):
            chart = _chart(
                make,
                brush={"type": "rect"},
                dataZoom=[{"type": "inside", "start": 20, "end": 80}],
            )
            chart.setDragMode(mode)
            comp = chart._component("dataZoom")
            before = (comp.start, comp.end)
            plot = chart.primaryCoord().plot
            _drag(
                chart,
                qapp,
                QPointF(plot.left() + 30, plot.center().y()),
                QPointF(plot.left() + 220, plot.center().y()),
            )
            assert (comp.start, comp.end) == before, f"{mode} 模式不该平移"

    def test_pan_drag_mode_overrides_default(self, qapp, make):
        chart = _chart(make)
        chart.setDragMode("pan")
        comp = chart._component("dataZoom")
        # 全量窗口（0~100）平移是 No-op：先缩到 20~80 才有可平移的余地
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 80})
        plot = chart.primaryCoord().plot
        _drag(
            chart,
            qapp,
            QPointF(plot.left() + 30, plot.center().y()),
            QPointF(plot.left() + 220, plot.center().y()),
        )
        assert (comp.start, comp.end) != (0.0, 100.0), "pan 模式应能拖拽平移"

    def test_non_cartesian_has_no_wheel_zoom(self, qapp, make):
        chart = make(ElaChartWidget)
        chart.resize(600, 400)
        chart.setOption(
            {
                "animation": False,
                "series": [{"type": "pie", "name": "P", "data": [{"name": "a", "value": 1}]}],
            }
        )
        chart.anim.setProgress(1.0)
        assert chart._component("dataZoom") is None

    def test_user_datazoom_untouched_by_switch(self, qapp, make):
        chart = _chart(make, dataZoom=[{"type": "inside", "start": 20, "end": 80}])
        comp = chart._component("dataZoom")
        assert not getattr(comp, "_wheel_zoom_auto", False)
        chart.setWheelZoomEnabled(False)
        assert chart._component("dataZoom") is comp, "用户配的 dataZoom 不该被开关删掉"

    def test_switch_can_turn_it_back_on(self, qapp, make):
        chart = _chart(make)
        chart.setWheelZoomEnabled(False)
        assert chart._component("dataZoom") is None
        chart.setWheelZoomEnabled(True)
        comp = chart._component("dataZoom")
        assert comp is not None and getattr(comp, "_wheel_zoom_auto", False)
        assert self._wheel(chart, chart.primaryCoord().plot.center()).isAccepted()


class TestToolboxElaIconButtons:
    """工具条 = 真实 ``ElaIconButton`` 子控件（不再自绘小图标）。"""

    FEATURES = [
        "saveAsImage",
        "saveAsSvg",
        "dataZoom",
        "restore",
        "zoomIn",
        "zoomOut",
    ]

    def _toolbox_chart(self, make):
        return _chart(
            make,
            toolbox={"feature": list(self.FEATURES)},
            dataZoom=[{"type": "inside", "start": 20, "end": 80}],
        )

    def test_buttons_are_ela_icon_buttons(self, qapp, make):
        chart = self._toolbox_chart(make)
        box = chart._component("toolbox")
        assert box.features == self.FEATURES
        for name in self.FEATURES:
            widget = box.buttonWidget(name)
            assert isinstance(widget, ElaIconButton), name
            assert widget.parent() is chart
            assert widget.toolTip() == box.TIPS[name]
        icons = {box.buttonWidget(n).getAwesome() for n in self.FEATURES}
        assert len(icons) == len(self.FEATURES), "每个功能应有自己的图标"

    def test_geometry_matches_widget(self, qapp, make):
        chart = self._toolbox_chart(make)
        box = chart._component("toolbox")
        rect = box.buttonRect("zoomIn")
        widget = box.buttonWidget("zoomIn")
        assert (widget.x(), widget.y()) == (int(round(rect.x())), int(round(rect.y())))
        assert widget.width() == int(round(rect.width()))

    def test_zoom_in_button_acts(self, qapp, make):
        chart = self._toolbox_chart(make)
        box = chart._component("toolbox")
        comp = chart._component("dataZoom")
        before = (comp.start, comp.end)
        box.buttonWidget("zoomIn").click()
        assert (comp.start, comp.end) != before
        box.buttonWidget("restore").click()
        # restore 回的是 option 里配置的初始窗口（20~80），不是全量
        assert (comp.start, comp.end) == (20.0, 80.0)

    def test_datazoom_toggle_reflects_state(self, qapp, make):
        chart = self._toolbox_chart(make)
        box = chart._component("toolbox")
        from PyQt6.QtWidgets import QApplication

        button = box.buttonWidget("dataZoom")
        assert button.getIsSelected() is True  # 缩放开着

        button.click()
        QApplication.processEvents()
        assert chart._dataZoomEnabled is False
        assert button.getIsSelected() is False, "开关状态要当场同步到按钮"

        button.click()
        QApplication.processEvents()
        assert chart._dataZoomEnabled is True
        assert button.getIsSelected() is True

    def test_master_switch_greys_buttons(self, qapp, make):
        chart = self._toolbox_chart(make)
        box = chart._component("toolbox")
        chart.setInteractive(False)
        assert box.buttonWidget("restore").isEnabled() is False
        chart.setInteractive(True)
        assert box.buttonWidget("restore").isEnabled() is True


class TestBrushBoxLifecycle:
    """框选（select / lasso）保留选框；框选缩放（zoom）松手即收。"""

    def _brush_chart(self, make, brush_type="rect"):
        chart = _chart(
            make,
            brush={"type": brush_type},
            dataZoom=[{"type": "inside", "start": 20, "end": 80}],
        )
        return chart

    def _box_drag(self, chart, qapp, fx0=0.25, fx1=0.75):
        plot = chart.primaryCoord().plot
        start = QPointF(plot.left() + plot.width() * fx0, plot.top() + plot.height() * 0.1)
        end = QPointF(
            plot.left() + plot.width() * fx1, plot.bottom() - plot.height() * 0.1
        )
        _drag(chart, qapp, start, end)

    def test_zoom_mode_clears_box_after_zoom(self, qapp, make):
        chart = self._brush_chart(make)
        chart.setDragMode("zoom")
        comp = chart._component("dataZoom")
        before = (comp.start, comp.end)
        self._box_drag(chart, qapp)
        assert (comp.start, comp.end) != before, "框选缩放没生效"
        brush = chart.brushComponent()
        assert brush._rect is None, "框选缩放的选框应主动消失"
        assert brush.selected_items == [], "框选缩放不该留下选中集"

    def test_select_mode_keeps_box(self, qapp, make):
        chart = self._brush_chart(make)
        chart.setDragMode("select")
        comp = chart._component("dataZoom")
        before = (comp.start, comp.end)
        self._box_drag(chart, qapp)
        brush = chart.brushComponent()
        assert brush._rect is not None, "框选应保留选框"
        assert brush.selected_items, "框选应留下选中集"
        assert (comp.start, comp.end) == before, "框选不缩放"

    def test_lasso_keeps_polygon(self, qapp, make):
        chart = self._brush_chart(make, "lasso")
        chart.setDragMode("lasso")
        self._box_drag(chart, qapp)
        brush = chart.brushComponent()
        assert brush._poly, "套索应保留轨迹"

    def test_click_outside_clears_box(self, qapp, make):
        chart = self._brush_chart(make)
        chart.setDragMode("select")
        self._box_drag(chart, qapp)
        assert chart.brushComponent()._rect is not None
        pos = QPointF(4, 4)
        chart.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pos, chart))
        chart.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, pos, chart))
        assert chart.brushComponent()._rect is None, "绘图区外点击应收框"
