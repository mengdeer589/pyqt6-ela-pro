"""薄 option 模型 / ChartEvent / 公开查询 API 回归。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import (
    ActionPayload,
    AxisOption,
    ChartEvent,
    ChartOption,
    ChartTheme,
    OptionModel,
    SeriesOption,
    chartThemeSpec,
    registerChartTheme,
    unregisterChartTheme,
)


def _chart(make) -> ElaChartWidget:
    chart = make(ElaChartWidget)
    chart.resize(500, 400)
    chart.setOption(
        ChartOption(
            animation=False,
            x_axis=AxisOption(type="category", data=["A", "B"]),
            y_axis=AxisOption(type="value"),
            tooltip=OptionModel(show=True),
            series=[
                SeriesOption(
                    type="bar",
                    name="S",
                    data=[0, 10],
                    item_style=OptionModel(color="#ff0000"),
                    label=OptionModel(show=True),
                )
            ],
        )
    )
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


def _mouse(etype, pos, chart):
    return QMouseEvent(
        etype,
        QPointF(pos),
        QPointF(chart.mapToGlobal(QPointF(pos).toPoint())),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_option_model_input_and_output(make):
    chart = _chart(make)
    renderer = chart.seriesRenderers[0]
    assert renderer.color().name() == "#ff0000"
    assert isinstance(chart.getOption(), ChartOption)
    assert isinstance(chart.getOption()["series"][0], SeriesOption)
    assert isinstance(chart.getOptionDict(), dict)
    assert chart.getOptionDict()["series"][0]["type"] == "bar"


def test_internal_option_models_are_thin(make):
    chart = _chart(make)
    assert isinstance(chart._option, ChartOption)
    assert isinstance(chart.seriesRenderers[0].opt, SeriesOption)
    assert isinstance(chart.primaryCoord().x_axis.opt, AxisOption)
    assert chart.tooltip.opt.get("show") is True


def test_option_model_attribute_access():
    model = OptionModel(font_size=12, item_style={"color": "#010203"})
    assert model["fontSize"] == 12
    assert model.font_size == 12
    assert model["itemStyle"]["color"] == "#010203"
    model.font_weight = "bold"
    assert model["fontWeight"] == "bold"
    assert model.to_dict()["fontWeight"] == "bold"


def test_validate_option(make):
    chart = _chart(make)
    assert chart.validateOption({"series": [{"type": "bar"}]}) == []
    issues = chart.validateOption({"series": [{"type": "unknown-series"}]})
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert "unknown-series" in issues[0].message


def test_public_query_api(make):
    chart = _chart(make)
    items = chart.seriesItems("S")
    assert [item.name for item in items] == ["A", "B"]
    assert [item.data_index for item in items] == [0, 1]
    item = chart.itemAt("S", 1)
    assert item is not None and item.value == 10
    hits = chart.hitTestAll(item.pos)
    assert hits and hits[0].data_index == 1


def test_on_handler_receives_chart_event(make):
    chart = _chart(make)
    seen = []
    chart.on("highlight", seen.append)
    chart.dispatchAction({"type": "highlight", "seriesName": "S", "dataIndex": 0})
    assert len(seen) == 1
    event = seen[0]
    assert isinstance(event, ChartEvent)
    assert event.data_index == 0
    assert event["dataIndex"] == 0
    assert event.get("seriesName") == "S"
    assert event.as_dict()["dataIndex"] == 0


def test_qt_signal_receives_chart_event(make):
    chart = _chart(make)
    seen = []
    chart.itemClicked.connect(seen.append)
    point = chart.seriesRenderers[0].valueAtIndex(1)["pos"]
    chart.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, point, chart))
    chart.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, point, chart))
    QApplication.processEvents()
    assert seen
    assert isinstance(seen[0], ChartEvent)
    assert seen[0]["dataIndex"] == 1
    assert seen[0].data_index == 1


def test_theme_and_action_models(make):
    registerChartTheme(
        ChartTheme(name="thin-theme", palette=["#010203", "#040506"])
    )
    try:
        spec = chartThemeSpec("thin-theme")
        assert spec["palette"] == ["#010203", "#040506"]
        assert spec.name == "thin-theme"

        chart = _chart(make)
        assert chart.dispatchAction(
            ActionPayload(
                type="select",
                series_name="S",
                data_index=0,
            )
        )
        assert chart.selectedIndices(chart.seriesRenderers[0]) == {0}
    finally:
        unregisterChartTheme("thin-theme")
