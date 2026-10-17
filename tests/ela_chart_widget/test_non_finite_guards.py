"""charts 的非有限值 / 非数值输入不得冒出到调用方。

AST 守卫（``except`` 是否列了 ``OverflowError``）已迁到
``tests/regression/test_overflow_error_guards.py`` —— 它是**全库**范围的，
判据也收窄到真正会抛 ``OverflowError`` 的五个转换函数（原先把 ``len`` /
``min`` / ``max`` 也算进来，在 charts 之外的模块上误报成片）。本文件只留
charts 侧的行为测试：逐个走真实公开入口，异常不得冒出到调用方。
"""

from __future__ import annotations

import pytest

_NON_FINITE = [float("inf"), float("-inf"), float("nan"), 10**400, -(10**400)]


class TestNonFiniteValuesDoNotEscape:
    """逐个走真实公开入口，异常不得冒出到调用方。"""

    @pytest.mark.parametrize("value", _NON_FINITE)
    def test_opt_float_never_raises(self, value):
        from pyqt6_ela_pro.charts.core import _opt_float

        out = _opt_float(value, 7.0)
        assert isinstance(out, float)

    @pytest.mark.parametrize("value", [float("inf"), 10**400])
    def test_to_buffer_never_raises(self, value):
        from pyqt6_ela_pro.charts.data import toBuffer

        toBuffer([value] + [1.0] * 8)

    def test_split_number_inf_does_not_escape_setoption(self, qapp, make):
        from pyqt6_ela_pro.charts import ElaChartWidget

        chart = make(ElaChartWidget)
        chart.setOption(
            {
                "xAxis": {"type": "category", "data": ["a", "b", "c"]},
                "yAxis": {"type": "value", "splitNumber": float("inf")},
                "series": [{"type": "bar", "name": "A", "data": [1, 2, 3]}],
            }
        )
        chart._layout_all(force=True)
        assert chart.primaryCoord() is not None

    def test_axis_label_infinities_do_not_escape_paint(self, qapp, make):
        from pyqt6_ela_pro.charts import ElaChartWidget

        for key in ("fontWeight", "interval", "fontSize", "rotate"):
            chart = make(ElaChartWidget)
            chart.setOption(
                {
                    "xAxis": {
                        "type": "category",
                        "data": ["a", "b", "c"],
                        "axisLabel": {key: float("inf")},
                    },
                    "yAxis": {"type": "value", "axisLabel": {key: float("inf")}},
                    "series": [{"type": "line", "name": "A", "data": [1, 2, 3]}],
                }
            )
            chart.anim.setProgress(1.0)
            chart._layout_all(force=True)
            chart.grab()  # 不得静默终止

    def test_dispatch_with_infinite_index_does_not_escape(self, qapp, make):
        from pyqt6_ela_pro.charts import ElaChartWidget

        chart = make(ElaChartWidget)
        chart.setOption(
            {
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "A", "data": [1, 2]}],
            }
        )
        assert chart.dispatchAction(
            {"type": "highlight", "dataIndex": float("inf")}
        ) in (
            True,
            False,
        )
        assert chart.dispatchAction(
            {"type": "showTip", "seriesIndex": 0, "x": "abc", "y": 3}
        ) in (True, False)

    def test_series_data_scalar_does_not_escape_setoption(self, qapp, make):
        """``data: 5`` 之类：此前 ``setOption`` 直接抛 TypeError。"""
        from pyqt6_ela_pro.charts import ElaChartWidget

        for bad in (5, 3.5, True):
            chart = make(ElaChartWidget)
            chart.setOption(
                {
                    "xAxis": {"type": "category", "data": ["a", "b"]},
                    "yAxis": {},
                    "series": [{"type": "bar", "name": "A", "data": bad}],
                }
            )
            chart._layout_all(force=True)
