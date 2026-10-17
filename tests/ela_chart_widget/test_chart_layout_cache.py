"""布局路径的**范围缓存**与 **numpy 快速路径**守卫。

两个真问题（均由 ``benchmark`` 的逐系列读数暴露）：

1. ``_grid_value_extent`` 被**每个** bar / candlestick / boxplot 系列的
   ``layout()`` 各调一次，而它要遍历全部 grid 系列的全部数据。实测
   6 折线 + 1 柱：布局 29.7 ms → 597.6 ms（20 倍）。
2. bar 的 ``layout`` 逐项调 ``parseDataPoint``，2 万柱 22 ms/次。

**正确性优先于性能**：缓存必须随数据变化失效；numpy 快路径必须与逐项
路径产出**完全相同**的几何（否则柱子位置会错）。
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import _downsample as _ds
from pyqt6_ela_pro.charts import series_cartesian as sc
from pyqt6_ela_pro.charts.core import ElaChartWidget

np = _ds.np


def _value_x(series):
    return {"xAxis": {"type": "value"}, "yAxis": {"type": "value"}, "series": series}


def _ready(chart, option, w=800, h=500):
    chart.resize(w, h)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart.show()
    for _ in range(3):
        QApplication.processEvents()
    chart._layout_all(force=True)
    return chart


def _bar(chart):
    for r in chart.seriesRenderers:
        if isinstance(r, sc.BarSeriesRenderer):
            return r
    raise AssertionError("未找到 bar 渲染器")


# ---------------------------------------------------------------------------
# _grid_value_extent 缓存
# ---------------------------------------------------------------------------
class TestGridExtentCache:
    @pytest.fixture(autouse=True)
    def _clear(self):
        sc._GRID_EXTENT_CACHE.clear()
        yield
        sc._GRID_EXTENT_CACHE.clear()

    def test_extent_computed(self, make):
        chart = _ready(
            make(ElaChartWidget),
            _value_x(
                [
                    {"type": "line", "name": "A", "data": [1.0, 5.0, 3.0]},
                    {"type": "bar", "name": "B", "data": [-2.0, 8.0, 1.0]},
                ]
            ),
        )
        assert sc._grid_value_extent(chart) == (-2.0, 8.0)

    def test_repeat_hits_cache(self, make, mocker):
        """重复调用命中缓存（不重扫全量数据）。"""
        n = 20_000
        chart = _ready(
            make(ElaChartWidget),
            _value_x(
                [
                    {
                        "type": "line",
                        "name": "A",
                        "data": [float(i % 100) for i in range(n)],
                    },
                    {
                        "type": "bar",
                        "name": "B",
                        "data": [float(i % 50) for i in range(n)],
                    },
                ]
            ),
        )
        # ``_ready`` 内的 ``_layout_all`` 已把缓存填好，故从干净状态起测
        sc._GRID_EXTENT_CACHE.clear()
        spy = mocker.spy(sc, "_grid_value_extent_uncached")
        sc._grid_value_extent(chart)
        first = spy.call_count
        assert first == 1, f"首次应计算一次，实得 {first}"
        for _ in range(5):
            sc._grid_value_extent(chart)
        assert spy.call_count == first, "未命中范围缓存"

    def test_data_change_recomputes(self, make):
        """换数据必须重算，不能返回旧范围。"""
        chart = make(ElaChartWidget)
        _ready(chart, _value_x([{"type": "bar", "name": "B", "data": [1.0, 2.0, 3.0]}]))
        assert sc._grid_value_extent(chart) == (1.0, 3.0)
        chart.setOption(
            _value_x([{"type": "bar", "name": "B", "data": [-50.0, 2.0, 3.0]}])
        )
        assert sc._grid_value_extent(chart) == (-50.0, 3.0), "换数据后未重算"

    def test_same_length_replacement(self, make):
        """**等长**换数据也必须重算（键含长度，靠身份区分）。"""
        chart = make(ElaChartWidget)
        _ready(chart, _value_x([{"type": "bar", "name": "B", "data": [1.0, 2.0, 3.0]}]))
        assert sc._grid_value_extent(chart) == (1.0, 3.0)
        chart.setOption(
            _value_x([{"type": "bar", "name": "B", "data": [10.0, 20.0, 30.0]}])
        )
        assert sc._grid_value_extent(chart) == (10.0, 30.0), "等长换数据未重算"

    def test_stack_extent(self, make):
        """stack 柱按**堆叠和**算范围（缓存不能改变这一语义）。

        A=[1,2] 与 B=[10,20] 同 stack → 逐位相加得 [11,22]，
        故范围是 (11, 22) 而非 (0, 30) —— 基线 0 不参与极值。
        """
        chart = _ready(
            make(ElaChartWidget),
            _value_x(
                [
                    {"type": "bar", "name": "A", "stack": "s", "data": [1.0, 2.0]},
                    {"type": "bar", "name": "B", "stack": "s", "data": [10.0, 20.0]},
                ]
            ),
        )
        assert sc._grid_value_extent(chart) == (11.0, 22.0)

    def test_cache_size_bounded(self, make):
        for i in range(sc._GRID_EXTENT_CACHE_LIMIT + 15):
            _ready(
                make(ElaChartWidget),
                _value_x(
                    [
                        {
                            "type": "bar",
                            "name": "B",
                            "data": [float(i * 1000 + j) for j in range(50)],
                        }
                    ]
                ),
            )
        assert len(sc._GRID_EXTENT_CACHE) <= sc._GRID_EXTENT_CACHE_LIMIT

    def test_holds_strong_reference(self, make):
        """缓存值持有 series option 强引用（key 里只有 id，靠 is 复核）。"""
        chart = _ready(
            make(ElaChartWidget),
            _value_x([{"type": "bar", "name": "B", "data": [1.0, 2.0, 3.0]}]),
        )
        sc._grid_value_extent(chart)
        assert sc._GRID_EXTENT_CACHE, "未写入缓存"
        entry = next(iter(sc._GRID_EXTENT_CACHE.values()))
        assert entry[1], "缓存未持有 series option 引用"


# ---------------------------------------------------------------------------
# numpy 快路径
# ---------------------------------------------------------------------------
@pytest.mark.skipif(np is None, reason="需要 numpy")
class TestNumericXy:
    def test_flat_list(self):
        xs, ys = sc._numeric_xy([1.0, 2.0, 3.0])
        assert xs is not None
        assert xs.tolist() == [0.0, 1.0, 2.0], "纯数值的 x 应取下标"
        assert ys.tolist() == [1.0, 2.0, 3.0]

    def test_xy_pairs(self):
        xs, ys = sc._numeric_xy([[1.0, 10.0], [2.0, 20.0]])
        assert xs.tolist() == [1.0, 2.0]
        assert ys.tolist() == [10.0, 20.0]

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param([{"value": 1.0}] * 300, id="dicts"),
            pytest.param([[1, 2, 3]] * 300, id="xyz-triples"),
            pytest.param([1.0, None] * 300, id="none-gaps"),
            pytest.param([], id="empty"),
        ],
    )
    def test_non_numeric_rejected(self, data):
        """结构型 / 含 None 的数据返回 (None, None)，由 Python 路径处理。"""
        xs, ys = sc._numeric_xy(data)
        assert xs is None and ys is None

    def test_buffer_input(self):
        """大数组缓冲区也走快路径。"""
        from pyqt6_ela_pro.charts.data import toBuffer

        buf = toBuffer([float(i) for i in range(500)])
        assert buf is not None
        xs, ys = sc._numeric_xy(buf)
        assert xs is not None and len(ys) == 500


@pytest.mark.skipif(np is None, reason="需要 numpy")
class TestBarLayoutParity:
    """numpy 快路径与逐项路径必须产出**相同几何**。"""

    def _rects(self, chart):
        return [
            (
                round(b["rect"].x(), 6),
                round(b["rect"].y(), 6),
                round(b["rect"].width(), 6),
                round(b["rect"].height(), 6),
                round(b["center"], 6),
                b["y"],
            )
            for b in _bar(chart)._bars
        ]

    def test_fast_path_matches_python_path(self, make):
        data = [float(i % 37) * 1.5 for i in range(2000)]
        chart = _ready(
            make(ElaChartWidget),
            _value_x([{"type": "bar", "name": "B", "data": list(data)}]),
        )
        fast = self._rects(chart)
        # 强制走逐项路径
        orig = sc._numeric_xy
        sc._numeric_xy = lambda d: (None, None)
        try:
            chart2 = _ready(
                make(ElaChartWidget),
                _value_x([{"type": "bar", "name": "B", "data": list(data)}]),
            )
            slow = self._rects(chart2)
        finally:
            sc._numeric_xy = orig
        assert fast == slow, "numpy 快路径与逐项路径的几何不一致"
        assert len(fast) == 2000

    def test_nan_and_inf_skipped(self, make):
        """NaN / inf 的柱必须跳过（两条路径一致）。"""
        data = [1.0] * 500
        data[10] = float("nan")
        data[20] = float("inf")
        data[30] = float("-inf")
        chart = _ready(
            make(ElaChartWidget),
            _value_x([{"type": "bar", "name": "B", "data": data}]),
        )
        bars = _bar(chart)._bars
        assert len(bars) == 497, f"应跳过 3 根非有限柱，实得 {len(bars)}"
        assert all(b["y"] == b["y"] for b in bars)

    def test_labels_bulk_matches_per_item(self, make):
        """``_cat_labels_bulk`` 与逐项 ``_cat_label`` 结果一致。"""
        cats = [f"c{i}" for i in range(300)]
        chart = _ready(
            make(ElaChartWidget),
            {
                "xAxis": {"type": "category", "data": cats},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "bar",
                        "name": "B",
                        "data": [float(i % 10) for i in range(300)],
                    }
                ],
            },
        )
        r = _bar(chart)
        coord = chart.coords[0]
        bulk = r._cat_labels_bulk(coord.x_axis, list(range(300)))
        one_by_one = [r._cat_label(coord.x_axis, i, i) for i in range(300)]
        assert bulk == one_by_one
        assert bulk[:3] == ["c0", "c1", "c2"]

    def test_value_axis_labels(self, make):
        """数值轴下批量标签退回 ``formatValue``。"""
        chart = _ready(
            make(ElaChartWidget),
            _value_x(
                [{"type": "bar", "name": "B", "data": [float(i) for i in range(200)]}]
            ),
        )
        r = _bar(chart)
        coord = chart.coords[0]
        bulk = r._cat_labels_bulk(coord.x_axis, [0.0, 1.0, 2.0])
        assert bulk == ["0", "1", "2"]

    def test_xy_pair_layout(self, make):
        """``[x, y]`` 对形式的柱也走快路径且几何正确。"""
        chart = _ready(
            make(ElaChartWidget),
            _value_x(
                [
                    {
                        "type": "bar",
                        "name": "B",
                        "data": [[float(i), float(i * 2)] for i in range(500)],
                    }
                ]
            ),
        )
        bars = _bar(chart)._bars
        assert len(bars) == 500
        assert bars[-1]["y"] == 998.0

    def test_buffer_layout(self, make):
        """大数组缓冲区（零拷贝摄入后的常态）布局正常。"""
        from pyqt6_ela_pro.charts.data import toBuffer

        buf = toBuffer([float(i % 60) for i in range(1000)])
        assert buf is not None
        chart = _ready(
            make(ElaChartWidget),
            _value_x([{"type": "bar", "name": "B", "data": buf}]),
        )
        assert len(_bar(chart)._bars) == 1000

    def test_dict_data_still_works(self, make):
        """dict 数据（无法向量化）走逐项路径且正常。"""
        data = [{"value": float(i % 20)} for i in range(400)]
        chart = _ready(
            make(ElaChartWidget),
            _value_x([{"type": "bar", "name": "B", "data": data}]),
        )
        assert len(_bar(chart)._bars) == 400


@pytest.mark.skipif(np is None, reason="需要 numpy")
class TestLineLayoutUnaffected:
    def test_line_layout_stable(self, make):
        """折线布局不受本次改动影响（回归守卫）。"""
        n = 50_000
        chart = _ready(
            make(ElaChartWidget),
            _value_x(
                [
                    {
                        "type": "line",
                        "name": "L",
                        "data": [float(i % 91) for i in range(n)],
                    }
                ]
            ),
        )
        r = chart.seriesRenderers[0]
        assert 0 < len(r._points) <= n
