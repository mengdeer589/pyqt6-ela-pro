"""回归测试（第十一批）：benchmark 交互状态恢复。"""

from __future__ import annotations

from pyqt6_ela_pro.charts import ElaChartWidget


class TestBenchmarkRestoresInteraction:
    def test_datazoom_window_restored(self, qapp):
        chart = ElaChartWidget()
        chart.resize(400, 300)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b", "c"]},
                "yAxis": {"type": "value"},
                "dataZoom": [{"type": "slider", "start": 10, "end": 80}],
                "series": [{"type": "line", "data": [1, 2, 3]}],
            }
        )
        chart.anim.setProgress(1.0)
        chart.dispatchAction({"type": "dataZoom", "start": 30, "end": 50})
        assert chart.getOption()["dataZoom"][0]["start"] == 30
        chart.benchmark(frames=1)
        assert chart.getOption()["dataZoom"][0]["start"] == 30
        assert chart.getOption()["dataZoom"][0]["end"] == 50
        chart.deleteLater()
        qapp.processEvents()

    def test_data_item_visibility_restored(self, qapp):
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
        chart._setDataItemVisible("a", False)
        chart.benchmark(frames=1)
        assert chart._item_state.get("a") is False
        chart.deleteLater()
        qapp.processEvents()
