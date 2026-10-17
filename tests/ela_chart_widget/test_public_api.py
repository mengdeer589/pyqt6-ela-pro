"""Tests for the unified public API (signals / helpers / extension layer)."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro import ElaFigureCanvas
from pyqt6_ela_pro.charts import (
    ElaChartWidget,
    SeriesRenderer,
    chartToken,
    registerSeries,
)


def _make_chart(option):
    chart = ElaChartWidget()
    chart.resize(600, 400)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


def _press(chart, pos: QPointF):
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(chart, event)
    QApplication.processEvents()


def _move(chart, pos: QPointF):
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(chart, event)
    QApplication.processEvents()


def _release(chart, pos: QPointF):
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(chart, event)
    QApplication.processEvents()


def _wheel(chart, pos: QPointF):
    event = QWheelEvent(
        QPointF(pos),
        QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(chart, event)
    QApplication.processEvents()


def _component(chart, key: str):
    return next(c for c in chart.components if getattr(c, "optionKey", "") == key)


class TestSignals:
    def test_legend_toggled(self):
        chart = _make_chart(
            {
                "legend": {"top": "top"},
                "xAxis": {"type": "category", "data": ["一", "二", "三"]},
                "yAxis": {},
                "series": [
                    {"type": "bar", "name": "A", "data": [1, 2, 3]},
                    {"type": "line", "name": "B", "data": [3, 2, 1]},
                ],
            }
        )
        received = []
        chart.legendToggled.connect(
            lambda name, visible: received.append((name, visible))
        )
        rect = chart.legend._item_rects[0]
        _press(chart, rect.center())
        assert received and received[0][0] == "A" and received[0][1] is False
        chart.deleteLater()

    def test_datazoom_changed(self):
        chart = _make_chart(
            {
                "xAxis": {"type": "category", "data": ["一", "二", "三"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "A", "data": [1, 2, 3]}],
                "dataZoom": [{"type": "inside"}],
            }
        )
        received = []
        chart.dataZoomChanged.connect(lambda s, e: received.append((s, e)))
        _wheel(chart, chart.primaryCoord().plot.center())
        assert received and received[-1][1] < 100.0
        chart.deleteLater()

    def test_timeline_changed(self):
        chart = _make_chart(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "A", "data": [1, 2]}],
                "timeline": {"data": ["2024", "2025", "2026"]},
            }
        )
        received = []
        chart.timelineChanged.connect(received.append)
        _component(chart, "timeline").goto(2)
        assert received == [2]
        chart.deleteLater()

    def test_item_clicked(self):
        chart = _make_chart(
            {
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "scatter",
                        "name": "S",
                        "data": [[1.0, 1.0], [2.0, 2.0]],
                    }
                ],
            }
        )
        received = []
        chart.itemClicked.connect(received.append)
        point = chart.primaryCoord().mapPoint(1.0, 1.0)
        assert chart.hitItem(point) is not None
        _press(chart, point)
        assert received and received[0]["seriesName"] == "S"
        assert received[0]["componentType"] == "series"
        assert received[0]["seriesIndex"] == 0
        assert received[0]["dataIndex"] == 0
        assert received[0]["value"] is not None
        assert received[0]["type"] == "click"
        chart.deleteLater()

    def test_toolbox_triggered(self):
        chart = _make_chart(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "A", "data": [1, 2]}],
                "toolbox": {"feature": ["restore"]},
            }
        )
        received = []
        chart.toolboxTriggered.connect(received.append)
        toolbox = _component(chart, "toolbox")
        button = next(rect for name, rect in toolbox._buttons if name == "restore")
        _press(chart, button.center())
        assert received == ["restore"]
        chart.deleteLater()

    def test_brush_changed(self):
        chart = _make_chart(
            {
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "brush": {},
                "series": [
                    {"type": "scatter", "name": "S", "data": [[1.0, 1.0], [9.0, 9.0]]}
                ],
            }
        )
        received = []
        chart.brushChanged.connect(received.append)
        plot = chart.primaryCoord().plot
        _press(chart, plot.topLeft() + QPointF(2, 2))
        _move(chart, plot.bottomRight() - QPointF(2, 2))
        _release(chart, plot.bottomRight() - QPointF(2, 2))
        assert received, "brushChanged 未发射"
        assert any(item.get("series") == "S" for item in received[-1])
        chart.deleteLater()


class TestHelperApis:
    def test_save_image(self, tmp_path):
        chart = _make_chart(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "A", "data": [1, 2]}],
            }
        )
        target = tmp_path / "chart.png"
        assert chart.saveImage(str(target)) == str(target)
        assert target.exists() and target.stat().st_size > 0
        chart.deleteLater()

    def test_animation_option(self):
        chart = _make_chart(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "A", "data": [1, 2]}],
            }
        )
        finished = []
        chart.on("finished", finished.append)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "A", "data": [3, 4]}],
            }
        )
        assert not chart.anim.isRunning()
        assert chart.anim.t == 1.0
        QApplication.processEvents()
        assert finished and finished[-1]["type"] == "finished"
        chart.deleteLater()

    def test_append_data_by_name_and_index(self):
        chart = _make_chart(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "A", "data": [1, 2]}],
            }
        )
        assert chart.appendData({"seriesName": "A", "data": [3, 4]}) is True
        assert chart.appendData({"seriesIndex": 0, "data": 5}) is True
        assert chart.appendData({"seriesName": "missing", "data": 6}) is False
        assert chart.appendData({"data": 7}) is False
        data = chart.getOption()["series"][0]["data"]
        assert data == [1, 2, 3, 4, 5]
        chart.deleteLater()

    def test_clear(self):
        chart = _make_chart(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "A", "data": [1, 2]}],
            }
        )
        chart.clear()
        assert chart.getOption() == {}
        assert chart.seriesRenderers == []
        chart.deleteLater()

    def test_hit_item_without_hit(self):
        chart = _make_chart(
            {
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [{"type": "scatter", "name": "S", "data": [[1.0, 1.0]]}],
            }
        )
        assert chart.hitItem(chart.primaryCoord().plot.bottomRight()) is None
        chart.deleteLater()


class TestExtensionLayer:
    def test_chart_token_types(self):
        color = chartToken("color.primary")
        assert isinstance(color, QColor) and color.isValid()
        assert isinstance(chartToken("font.xs"), int)

    def test_register_series_duplicate_warns(self, capsys):
        class FakeSeries(SeriesRenderer):
            pass

        class FakeSeries2(SeriesRenderer):
            pass

        registerSeries("testDupSeries", FakeSeries)
        capsys.readouterr()
        registerSeries("testDupSeries", FakeSeries2)
        err = capsys.readouterr().err
        assert "testDupSeries" in err

    def test_public_api_has_no_snake_case_leftovers(self):
        chart = ElaChartWidget()
        leftovers = [
            "set_option",
            "update_option",
            "option",
            "updateOption",
            "set_series_visible",
            "is_series_visible",
            "setSeriesVisible",
            "isSeriesVisible",
            "set_interactive",
            "set_interaction_enabled",
            "is_interaction_enabled",
            "register_series",
            "add_component",
            "invalidate_layout",
            "color_for_series",
            "primary_coord",
            "coord_for",
            "series_renderers",
            "set_animation",
            "animationEnabled",
            "save_image",
        ]
        assert all(not hasattr(chart, name) for name in leftovers)
        chart.deleteLater()

    def test_public_api_has_echarts_instance_methods(self):
        chart = ElaChartWidget()
        for name in (
            "setOption",
            "getOption",
            "resize",
            "dispatchAction",
            "on",
            "off",
            "convertToPixel",
            "convertFromPixel",
            "containPixel",
            "showLoading",
            "hideLoading",
            "getDataURL",
            "appendData",
            "clear",
            "dispose",
            "isDisposed",
            "getWidth",
            "getHeight",
            "getDevicePixelRatio",
        ):
            assert callable(getattr(chart, name, None)), f"缺少 ECharts 接口 {name}"
        chart.deleteLater()

    def test_figure_canvas_style_api(self):
        pytest.importorskip("matplotlib")

        assert hasattr(ElaFigureCanvas, "setStyle")


class TestEChartsInstanceApi:
    """ECharts 实例接口：setOption 语义 / dispatchAction / on-off / convert / loading。"""

    _BASE = {
        "xAxis": {"type": "category", "data": ["一", "二", "三"]},
        "yAxis": {},
        "series": [
            {"type": "bar", "name": "A", "data": [1, 2, 3]},
            {"type": "line", "name": "B", "id": "b", "data": [3, 2, 1]},
        ],
    }

    def test_set_option_merges_by_default(self):
        chart = _make_chart(self._BASE)
        chart.setOption({"series": [{"data": [9, 8, 7]}]})
        a, b = chart.seriesRenderers
        assert a.opt["type"] == "bar" and a.name == "A" and a.data() == [9, 8, 7]
        assert b.opt["type"] == "line" and b.name == "B"
        chart.deleteLater()

    def test_set_option_merge_matches_by_id_and_name(self):
        chart = _make_chart(self._BASE)
        chart.setOption(
            {
                "series": [
                    {"id": "b", "data": [7, 7, 7]},
                    {"name": "A", "data": [5, 5, 5]},
                ]
            }
        )
        a, b = chart.seriesRenderers
        assert a.data() == [5, 5, 5]
        assert b.data() == [7, 7, 7]
        chart.deleteLater()

    def test_set_option_not_merge_replaces_and_resets_legend(self):
        chart = _make_chart(self._BASE)
        chart.dispatchAction({"type": "legendUnSelect", "name": "A"})
        assert chart._seriesVisible("A") is False
        chart.setOption(
            {"series": [{"type": "pie", "data": [{"name": "x", "value": 1}]}]},
            notMerge=True,
        )
        assert len(chart.seriesRenderers) == 1
        assert chart.seriesRenderers[0].opt["type"] == "pie"
        assert chart._seriesVisible("A") is True  # notMerge 重置选择状态
        chart.deleteLater()

    def test_set_option_lazy_update_defers_rebuild(self):
        chart = _make_chart(self._BASE)
        chart.setOption({"series": [{"data": [4, 5, 6]}]}, lazyUpdate=True)
        assert chart.seriesRenderers[0].data() == [1, 2, 3]  # 尚未重建
        QApplication.processEvents()
        assert chart.seriesRenderers[0].data() == [4, 5, 6]
        chart.deleteLater()

    def test_legend_selected_initial_state(self):
        option = dict(self._BASE)
        option["legend"] = {"selected": {"B": False}}
        chart = _make_chart(option)
        assert chart.seriesRenderers[1].visible is False
        assert chart.seriesRenderers[0].visible is True
        chart.deleteLater()

    def test_dispatch_action_legend_select_all_and_inverse(self):
        chart = _make_chart(self._BASE)
        chart.dispatchAction({"type": "legendUnSelect", "name": "A"})
        assert chart._seriesVisible("A") is False
        chart.dispatchAction({"type": "legendAllSelect"})
        assert chart._seriesVisible("A") is True
        chart.dispatchAction({"type": "legendInverseSelect"})
        assert chart._seriesVisible("A") is False
        chart.dispatchAction({"type": "legendInverseSelect"})
        assert chart._seriesVisible("A") is True
        chart.deleteLater()

    def test_dispatch_action_datazoom_and_restore(self):
        option = dict(self._BASE)
        option["dataZoom"] = [{"type": "inside", "minSpan": 10}]
        chart = _make_chart(option)
        comp = _component(chart, "dataZoom")
        assert chart.dataZoomChanged.connect(lambda *_: None) is not None
        assert (
            chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 80}) is True
        )
        assert (comp.start, comp.end) == (20, 80)
        assert chart.dispatchAction({"type": "dataZoom", "start": 0, "end": 30}) is True
        assert comp.end - comp.start >= 10 - 1e-6
        assert chart.dispatchAction({"type": "restore"}) is True
        assert (comp.start, comp.end) == (comp.init_start, comp.init_end)
        chart.deleteLater()

    def test_dispatch_action_highlight_and_timeline_unknown(self):
        chart = _make_chart(self._BASE)
        assert (
            chart.dispatchAction(
                {"type": "highlight", "seriesIndex": 0, "dataIndex": 1}
            )
            is True
        )
        assert chart.hoverInfo() is not None
        assert chart.dispatchAction({"type": "downplay"}) is True
        assert chart.hoverInfo() is None
        assert chart.dispatchAction({"type": "nope"}) is False
        chart.deleteLater()

    def test_dispatch_action_timeline(self):
        chart = _make_chart(
            {
                "xAxis": {"type": "category", "data": ["一", "二"]},
                "yAxis": {},
                "timeline": {"data": ["2024", "2025", "2026"], "currentIndex": 0},
                "options": [
                    {"series": [{"type": "bar", "name": "A", "data": [1, 2]}]},
                    {"series": [{"type": "bar", "name": "A", "data": [3, 4]}]},
                    {"series": [{"type": "bar", "name": "A", "data": [5, 6]}]},
                ],
            }
        )
        comp = _component(chart, "timeline")
        assert (
            chart.dispatchAction({"type": "timelineChange", "currentIndex": 2}) is True
        )
        assert comp.current == 2
        assert chart.seriesRenderers[0].data() == [5, 6]
        assert (
            chart.dispatchAction({"type": "timelinePlayChange", "playState": False})
            is True
        )
        assert comp.playing is False
        chart.deleteLater()

    def test_on_off_lifecycle_and_exception_guard(self):
        chart = _make_chart(self._BASE)
        seen = []
        handler = seen.append
        assert chart.on("legendselectchanged", handler) is chart
        chart.dispatchAction({"type": "legendToggleSelect", "name": "A"})
        assert seen and seen[-1]["name"] == "A"
        assert seen[-1]["selected"]["A"] is False
        chart.off("legendselectchanged", handler)
        chart.dispatchAction({"type": "legendToggleSelect", "name": "A"})
        assert len(seen) == 1

        def boom(_params):
            raise RuntimeError("boom")

        chart.on("click", boom)
        chart.dispatchAction({"type": "highlight", "seriesIndex": 0, "dataIndex": 0})
        toggler = []
        chart.on("highlight", toggler.append)
        chart.dispatchAction({"type": "downplay"})  # 异常 handler 不炸进程
        assert chart.off() is chart
        chart.deleteLater()

    def test_convert_pixel_roundtrip_and_contain(self):
        chart = _make_chart(
            {
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [{"type": "scatter", "name": "S", "data": [[1.0, 2.0]]}],
            }
        )
        pixel = chart.convertToPixel({"seriesIndex": 0}, [1.0, 2.0])
        assert isinstance(pixel, list) and len(pixel) == 2
        data = chart.convertFromPixel("grid", pixel)
        assert abs(data[0] - 1.0) < 1e-6 and abs(data[1] - 2.0) < 1e-6
        assert chart.containPixel("grid", pixel) is True
        assert chart.containPixel("grid", [0.0, 0.0]) is False
        assert chart.convertToPixel("nope", [1.0, 2.0]) is None
        chart.deleteLater()

    def test_show_loading_and_get_data_url(self):
        chart = _make_chart(self._BASE)
        chart.showLoading("default", {"text": "加载中"})
        assert chart.isLoading is True
        image = chart.grab().toImage()
        assert image.width() == chart.width()
        chart.hideLoading()
        assert chart.isLoading is False

        url = chart.getDataURL()
        assert url.startswith("data:image/png;base64,")
        jpeg = chart.getDataURL({"type": "jpeg", "backgroundColor": "#ffffff"})
        assert jpeg.startswith("data:image/jpeg;base64,")
        chart.deleteLater()

    def test_resize_and_size_getters(self):
        chart = _make_chart(self._BASE)
        chart.resize({"width": 512, "height": 300})
        assert chart.getWidth() == 512 and chart.getHeight() == 300
        assert chart.getDevicePixelRatio() > 0
        chart.resize(640, 400)
        assert chart.width() == 640 and chart.height() == 400
        chart.deleteLater()

    def test_dispose(self):
        chart = ElaChartWidget()
        assert chart.isDisposed() is False
        chart.dispose()
        assert chart.isDisposed() is True
        chart.dispose()  # 幂等
        QApplication.processEvents()

    def test_finished_event_after_animation(self):
        chart = _make_chart(self._BASE)
        received = []
        chart.on("finished", received.append)
        chart.setOption({"series": [{"data": [4, 5, 6]}]})  # 重新播放过渡动画
        chart.anim.setProgress(1.0)
        assert received and received[-1]["type"] == "finished"
        chart.deleteLater()
