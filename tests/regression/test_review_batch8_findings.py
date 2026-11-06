"""回归测试（第八批）：图表缓存 / dataZoom / SVG、时间线 hfw、蓝图焦点。

对应全库审查中已实测确认的功能问题。
"""

from __future__ import annotations

import pathlib

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QFocusEvent, QKeyEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.blueprint import ElaBlueprintCanvas
from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.ela_timeline import ElaTimeline


def _chart(qapp) -> ElaChartWidget:
    chart = ElaChartWidget()
    chart.resize(400, 300)
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "category", "data": ["a", "b", "c"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "line", "data": [1, 2, 3]}],
        }
    )
    chart.anim.setProgress(1.0)
    chart.grab()
    return chart


class TestChartCacheInvalidation:
    def test_data_item_toggle_changes_series_layer_key(self, qapp):
        chart = ElaChartWidget()
        chart.resize(400, 300)
        chart.setOption(
            {
                "animation": False,
                "legend": {"data": ["a", "b"]},
                "series": [
                    {
                        "type": "pie",
                        "data": [
                            {"name": "a", "value": 1},
                            {"name": "b", "value": 2},
                        ],
                    }
                ],
            }
        )
        chart.anim.setProgress(1.0)
        chart.grab()
        before = chart._series_layer_key()
        chart._setDataItemVisible("a", False)
        assert chart._series_layer_key() != before

    def test_user_datazoom_replaces_auto_wheel_component(self, qapp):
        chart = _chart(qapp)
        auto = chart._auto_wheel_zoom()
        assert auto is not None
        option = {
            "animation": False,
            "xAxis": {"type": "category", "data": ["a", "b", "c"]},
            "yAxis": {"type": "value"},
            "dataZoom": [{"type": "slider", "start": 10, "end": 80}],
            "series": [{"type": "line", "data": [1, 2, 3]}],
        }
        chart.setOption(option)
        zooms = [
            comp
            for comp in chart._components
            if getattr(comp, "optionKey", "") == "dataZoom"
        ]
        assert len(zooms) == 1
        assert not getattr(zooms[0], "_wheel_zoom_auto", False)

    def test_svg_export_does_not_embed_series_layer_bitmap(self, qapp, tmp_path):
        chart = _chart(qapp)
        target = pathlib.Path(tmp_path) / "chart.svg"
        assert chart.saveImage(str(target), format="svg") == str(target)
        text = target.read_text(encoding="utf-8")
        assert "<image" not in text


class TestTimelineHeightForWidth:
    def test_narrow_width_returns_taller_height(self, qapp):
        timeline = ElaTimeline()
        timeline.addItem(ElaTimeline.TimelineItem("title", "line " * 120, "2026-01-01"))
        assert timeline.hasHeightForWidth()
        assert timeline.heightForWidth(200) > timeline.sizeHint().height()


class TestBlueprintViewportFocus:
    def test_focus_out_cancels_space_pan(self, qapp):
        canvas = ElaBlueprintCanvas()
        canvas.resize(600, 400)
        viewport = canvas._viewport
        viewport.setFocus(Qt.FocusReason.OtherFocusReason)
        QApplication.sendEvent(
            viewport,
            QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier
            ),
        )
        assert canvas._space_down
        viewport.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
        assert canvas._space_down is False
