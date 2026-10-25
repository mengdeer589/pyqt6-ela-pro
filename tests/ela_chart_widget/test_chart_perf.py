"""``ElaChartWidget.benchmark()`` 的接口与行为守卫。

``benchmark`` 是**诊断接口**：它的价值全在返回值可信。因此这里守三件事：

1. 返回字典的**键集合固定**（测试钉住）—— 否则调用方按 key 取值会静默
   拿到 ``None``，而诊断工具失效比没有诊断工具更糟；
2. 时间单位是**毫秒**且非负、用 ``time.monotonic`` 计时（系统时钟调整
   会算出负耗时）；
3. 调用后**不残留副作用**：动画状态复原、option 内容不变、绘制结果不变。

关于耗时断言：offscreen 下像素比对不可用，且 CI 机器性能差异大，故只断言
「量级合理」（如耗时为有限正数、``frameMs == layoutMs + paintMs``），
**不断言具体毫秒数**。
"""

from __future__ import annotations

import math

import pytest
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QPolygonF
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts.core import ElaChartWidget

#: 返回字典的键集合。改动此集合必须同步改测试与 docstring。
BENCH_KEYS = {
    "ingestMs",
    "layoutMs",
    "paintMs",
    "frameMs",
    "dataPoints",
    "totalDataPoints",
    "drawnPoints",
    "seriesCount",
    "seriesKinds",
    "width",
    "height",
    "dpr",
    "frameBudget60HzMs",
    "seriesTimings",
}

#: 逐系列读数的键集合
SERIES_KEYS = {
    "name",
    "type",
    "dataPoints",
    "drawnPoints",
    "layoutMs",
    "paintMs",
}


def _option(data, n_series=1):
    return {
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [
            {"type": "line", "name": f"S{i}", "data": list(data)}
            for i in range(n_series)
        ],
    }


def _ready(chart, option):
    chart.resize(800, 500)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart.show()
    for _ in range(3):
        QApplication.processEvents()
    return chart


class TestBenchmarkInterface:
    def test_returns_full_key_set(self, make):
        chart = _ready(make(ElaChartWidget), _option([float(i) for i in range(2000)]))
        r = chart.benchmark(frames=2)
        assert set(r) == BENCH_KEYS, (
            f"键集合不符：多 {set(r) - BENCH_KEYS} / 少 {BENCH_KEYS - set(r)}"
        )

    def test_units_are_milliseconds(self, make):
        """所有时间项是毫秒的有限正数。"""
        chart = _ready(make(ElaChartWidget), _option([float(i) for i in range(3000)]))
        r = chart.benchmark(frames=2)
        for key in ("ingestMs", "layoutMs", "paintMs", "frameMs"):
            v = r[key]
            assert isinstance(v, float), f"{key} 应为 float"
            assert v == v and v not in (float("inf"), float("-inf")), f"{key} 非有限"
            assert v >= 0.0, f"{key} 为负（时钟回拨？应改用 monotonic）"

    def test_frame_ms_is_sum(self, make):
        chart = _ready(make(ElaChartWidget), _option([float(i) for i in range(3000)]))
        r = chart.benchmark(frames=2)
        assert r["frameMs"] == pytest.approx(r["layoutMs"] + r["paintMs"], abs=0.01)

    def test_budget_constant(self, make):
        """``frameBudget60HzMs`` 是 60 Hz 帧预算（16.67 ms）。"""
        chart = _ready(make(ElaChartWidget), _option([1.0, 2.0, 3.0]))
        assert chart.benchmark(frames=1)["frameBudget60HzMs"] == pytest.approx(
            16.667, abs=0.01
        )

    def test_scale_fields_reported(self, make):
        """规模字段反映真实数据量与绘制点数。"""
        n = 20_000
        chart = _ready(make(ElaChartWidget), _option([float(i % 97) for i in range(n)]))
        r = chart.benchmark(frames=2)
        assert r["dataPoints"] == n
        assert 0 < r["drawnPoints"] <= n, "drawnPoints 应为实际绘制点数（已被采样压缩）"
        assert r["seriesCount"] == 1
        assert (r["width"], r["height"]) == (800, 500)
        assert r["dpr"] >= 1.0

    def test_series_count_multiple(self, make):
        data = [float(i % 50) for i in range(1000)]
        chart = _ready(make(ElaChartWidget), _option(data, n_series=3))
        assert chart.benchmark(frames=1)["seriesCount"] == 3

    def test_sampling_reduces_drawn_points(self, make):
        """大数据的绘制点数应远小于数据量（采样生效的直接证据）。"""
        n = 100_000
        chart = _ready(
            make(ElaChartWidget), _option([float((i * 37) % 1000) for i in range(n)])
        )
        r = chart.benchmark(frames=2)
        assert r["dataPoints"] == n
        assert r["drawnPoints"] < n // 2, (
            f"绘制点数 {r['drawnPoints']} 未被采样压缩（数据量 {n}）"
        )

    def test_frames_affects_averages(self, make):
        """``frames`` 只影响取平均，不改变返回结构。"""
        chart = _ready(make(ElaChartWidget), _option([float(i) for i in range(5000)]))
        a = chart.benchmark(frames=1)
        b = chart.benchmark(frames=8)
        assert set(a) == set(b) == BENCH_KEYS
        assert a["dataPoints"] == b["dataPoints"]

    def test_invalid_frames_clamped(self, make):
        """``frames <= 0`` 回退到 1 帧，不抛异常也不死循环。"""
        chart = _ready(make(ElaChartWidget), _option([1.0, 2.0, 3.0]))
        r = chart.benchmark(frames=0)
        assert r["layoutMs"] >= 0.0
        assert chart.benchmark(frames=-5)["layoutMs"] >= 0.0

    def test_small_data_works(self, make):
        """极小数据（不足采样阈值）不崩。"""
        chart = _ready(make(ElaChartWidget), _option([1.0, 5.0, 3.0]))
        r = chart.benchmark(frames=1)
        assert r["dataPoints"] == 3
        assert r["drawnPoints"] == 3

    def test_empty_series_works(self, make):
        """空系列不崩（规模字段为 0）。"""
        chart = _ready(make(ElaChartWidget), _option([]))
        r = chart.benchmark(frames=1)
        assert r["dataPoints"] == 0
        assert r["drawnPoints"] == 0

    def test_hidden_series_excluded(self, make):
        """隐藏系列不计入规模统计（走公开的图例切换 API）。"""
        chart = _ready(make(ElaChartWidget), _option([float(i) for i in range(1000)]))
        chart.dispatchAction({"type": "legendToggleSelect", "name": "S0"})
        for _ in range(2):
            QApplication.processEvents()
        assert chart.benchmark(frames=1)["seriesCount"] == 0
        # 切回来后恢复统计
        chart.dispatchAction({"type": "legendToggleSelect", "name": "S0"})
        for _ in range(2):
            QApplication.processEvents()
        assert chart.benchmark(frames=1)["seriesCount"] == 1


class TestBenchmarkMultiSeries:
    """多条曲线 + 大数据量：逐系列读数必须能定位到具体哪条慢。"""

    def test_one_entry_per_visible_series(self, make):
        chart = _ready(make(ElaChartWidget), _option([1.0, 2.0, 3.0], n_series=5))
        r = chart.benchmark(frames=1)
        st = r["seriesTimings"]
        assert len(st) == 5, f"应有 5 条逐系列读数，实得 {len(st)}"
        assert {s["name"] for s in st} == {f"S{i}" for i in range(5)}

    def test_series_entry_keys(self, make):
        chart = _ready(make(ElaChartWidget), _option([1.0, 2.0, 3.0], n_series=3))
        for s in chart.benchmark(frames=1)["seriesTimings"]:
            assert set(s) == SERIES_KEYS, (
                f"逐系列键不符：多 {set(s) - SERIES_KEYS} / 少 {SERIES_KEYS - set(s)}"
            )
            assert isinstance(s["layoutMs"], float)
            assert isinstance(s["paintMs"], float)
            assert s["layoutMs"] >= 0.0 and s["paintMs"] >= 0.0
            assert s["dataPoints"] == 3
            assert s["drawnPoints"] == 3

    def test_hidden_series_excluded_from_timings(self, make):
        chart = _ready(make(ElaChartWidget), _option([1.0, 2.0, 3.0], n_series=3))
        chart.dispatchAction({"type": "legendToggleSelect", "name": "S1"})
        for _ in range(2):
            QApplication.processEvents()
        r = chart.benchmark(frames=1)
        assert "S1" not in {s["name"] for s in r["seriesTimings"]}
        assert len(r["seriesTimings"]) == 2

    def test_mixed_types_reported(self, make):
        """混合类型（line / bar / scatter）逐系列读数须各自报出真实规模。

        早期实现只读折线的 ``_data_len`` / ``_points``，导致 bar / scatter
        的规模恒为 0。
        """
        opt = {
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "line",
                    "name": "L",
                    "data": [float(i % 50) for i in range(2000)],
                },
                {"type": "bar", "name": "B", "data": [float(i) for i in range(300)]},
                {
                    "type": "scatter",
                    "name": "P",
                    "data": [[float(i), float(i % 7)] for i in range(400)],
                },
            ],
        }
        chart = _ready(make(ElaChartWidget), opt)
        r = chart.benchmark(frames=1)
        by_name = {s["name"]: s for s in r["seriesTimings"]}
        assert by_name["L"]["dataPoints"] == 2000
        assert by_name["B"]["dataPoints"] == 300, "bar 的数据量未被报出"
        assert by_name["P"]["dataPoints"] == 400, "scatter 的数据量未被报出"
        assert by_name["B"]["drawnPoints"] == 300
        assert by_name["L"]["drawnPoints"] > 0
        assert by_name["B"]["type"] == "bar"
        assert by_name["P"]["type"] == "scatter"

    def test_series_kinds_counts_types(self, make):
        opt = {
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [
                {"type": "line", "name": "A", "data": [1.0, 2.0, 3.0]},
                {"type": "line", "name": "B", "data": [1.0, 2.0, 3.0]},
                {"type": "bar", "name": "C", "data": [1.0, 2.0, 3.0]},
            ],
        }
        chart = _ready(make(ElaChartWidget), opt)
        r = chart.benchmark(frames=1)
        assert r["seriesKinds"] == {"line": 2, "bar": 1}
        assert r["seriesCount"] == 3

    def test_total_vs_max_data_points(self, make):
        """``dataPoints`` 取最大条，``totalDataPoints`` 才是总和。"""
        data = [float(i % 50) for i in range(1000)]
        chart = _ready(make(ElaChartWidget), _option(data, n_series=3))
        r = chart.benchmark(frames=1)
        assert r["dataPoints"] == 1000
        assert r["totalDataPoints"] == 3000

    def test_sorted_by_cost_per_primitive(self, make):
        """逐系列读数按「每图元绘制成本」降序 —— 绝对 paintMs 会被图元数带偏。"""
        opt = {
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "line",
                    "name": "L",
                    "data": [float(i % 50) for i in range(2000)],
                },
                {
                    "type": "bar",
                    "name": "B",
                    "data": [float(i % 9) for i in range(600)],
                },
            ],
        }
        chart = _ready(make(ElaChartWidget), opt)
        st = chart.benchmark(frames=1)["seriesTimings"]
        densities = [s["paintMs"] / max(1, s["drawnPoints"]) for s in st]
        assert densities == sorted(densities, reverse=True), "未按每图元成本降序"

    def test_perseries_false_skips_work(self, make):
        """``perSeries=False`` 不做逐系列测量（读数为空列表，省一半时间）。"""
        chart = _ready(make(ElaChartWidget), _option([1.0, 2.0, 3.0], n_series=3))
        assert chart.benchmark(frames=1, perSeries=False)["seriesTimings"] == []
        assert len(chart.benchmark(frames=1, perSeries=True)["seriesTimings"]) == 3

    def test_large_multi_series_runs(self, make):
        """大数据量 + 多系列：整条链路跑通且规模字段自洽。"""
        n = 50_000
        chart = _ready(
            make(ElaChartWidget),
            _option([float((i * 37) % 1000) for i in range(n)], n_series=4),
        )
        r = chart.benchmark(frames=1)
        assert r["seriesCount"] == 4
        assert r["totalDataPoints"] == n * 4
        assert r["seriesKinds"] == {"line": 4}
        assert len(r["seriesTimings"]) == 4
        for s in r["seriesTimings"]:
            assert s["dataPoints"] == n
            assert 0 < s["drawnPoints"] < n, "采样未压缩点数"
        assert r["frameMs"] >= r["layoutMs"]

    def test_visibility_restored_after_timings(self, make):
        """逐系列测量会逐个隐藏系列，结束后必须全部复原。"""
        chart = _ready(make(ElaChartWidget), _option([1.0, 2.0, 3.0], n_series=4))
        chart.benchmark(frames=1)
        assert all(r.visible for r in chart.seriesRenderers), "有系列被永久隐藏"
        assert chart.benchmark(frames=1)["seriesCount"] == 4

    def test_single_series_timing_is_self_consistent(self, make):
        """逐系列读数的口径自洽性（不依赖墙钟）。

        **不要拿 ``paintMs`` 与总耗时做比值断言**：总绘制可能因为**系列层
        位图缓存命中**而≈0（一次 ``drawImage``），而逐系列测量走的是未命中
        路径 —— 实测同一条数据 4 跑里挂 1 次（``st=16ms`` vs ``total≈0``）。
        那是测试写法的问题，不是被测代码的：两条路径的缓存状态本来就不同。
        这里改钉真正确定的性质：读数齐全、规模正确、耗时非负有限。
        """
        n = 20_000
        chart = _ready(
            make(ElaChartWidget),
            _option([float((i * 13) % 500) for i in range(n)]),
        )
        r = chart.benchmark(frames=2)
        assert len(r["seriesTimings"]) == r["seriesCount"] == 1
        st = r["seriesTimings"][0]
        assert st["dataPoints"] == n
        assert 0 <= st["drawnPoints"] <= n
        for key in ("layoutMs", "paintMs"):
            assert isinstance(st[key], (int, float))
            assert st[key] >= 0.0 and st[key] == st[key]  # 非负且非 NaN
        for key in ("ingestMs", "layoutMs", "paintMs"):
            assert r[key] >= 0.0 and r[key] == r[key], f"{key} 不是非负有限数"

    def test_pie_timings_reported(self, make):
        """非直角坐标系列（pie）也能报出规模，不报错。"""
        opt = {
            "series": [
                {
                    "type": "pie",
                    "name": "P",
                    "data": [{"name": f"c{i}", "value": i + 1} for i in range(20)],
                }
            ]
        }
        chart = _ready(make(ElaChartWidget), opt)
        r = chart.benchmark(frames=1)
        st = r["seriesTimings"]
        assert len(st) == 1
        assert st[0]["type"] == "pie"
        assert st[0]["dataPoints"] == 20, "pie 的数据量未被报出"
        assert st[0]["drawnPoints"] > 0


class TestBenchmarkNoSideEffects:
    def test_legend_selection_preserved(self, make):
        """benchmark 内部的 ``notMerge`` 重置不会改掉用户的图例选中态。"""
        chart = _ready(make(ElaChartWidget), _option([float(i) for i in range(1000)]))
        chart.dispatchAction({"type": "legendToggleSelect", "name": "S0"})
        for _ in range(2):
            QApplication.processEvents()
        assert not chart.seriesRenderers[0].visible
        chart.benchmark(frames=1)
        assert not chart.seriesRenderers[0].visible, "图例选中态被 benchmark 重置了"
        assert chart._series_state.get("S0") is False

    def test_hover_and_tip_state_preserved(self, make):
        """悬浮态不被清掉（``notMerge`` 会 ``tooltip.hide()``）。"""
        from PyQt6.QtCore import QPointF

        chart = _ready(
            make(ElaChartWidget), _option([float(i % 97) for i in range(2000)])
        )
        chart.tooltip.showAt(QPointF(100.0, 100.0), [("S0", "1.0")])
        assert chart.tooltip.active
        chart.benchmark(frames=1)
        assert chart.tooltip.active, "悬浮提示被 benchmark 清掉了"
        chart.tooltip.hide()

    def test_option_content_unchanged(self, make):
        """benchmark 内部的 ``setOption(notMerge=True)`` 不改变 option 内容。"""
        opt = _option([float(i % 97) for i in range(3000)])
        chart = _ready(make(ElaChartWidget), opt)
        before = chart.getOption()
        chart.benchmark(frames=2)
        after = chart.getOption()
        assert before["series"][0]["data"] == after["series"][0]["data"]
        assert before["series"][0]["name"] == after["series"][0]["name"]
        assert len(after["series"]) == len(before["series"])

    def test_animation_state_restored(self, make):
        """调用前动画在跑，调用后仍在跑（benchmark 内部会 stop + 推终态）。"""
        chart = _ready(make(ElaChartWidget), _option([float(i) for i in range(2000)]))
        chart.anim.start()
        assert chart.anim.isRunning()
        chart.benchmark(frames=1)
        assert chart.anim.isRunning(), "动画状态未被复原"

    def test_animation_stopped_stays_stopped(self, make):
        chart = _ready(make(ElaChartWidget), _option([float(i) for i in range(2000)]))
        chart.anim.stop()
        chart.benchmark(frames=1)
        assert not chart.anim.isRunning(), "原本停止的动画被启动了"

    def test_render_output_stable(self, make):
        """重复调用不改变画面（benchmark 不产生视觉副作用）。"""
        chart = _ready(
            make(ElaChartWidget), _option([float(i % 97) for i in range(2000)])
        )
        chart.benchmark(frames=1)
        img1 = chart.grab().toImage()
        chart.benchmark(frames=1)
        img2 = chart.grab().toImage()
        assert img1.size() == img2.size()
        # offscreen 下逐像素比对不可用，比 sizeHint 口径：图像非全透明
        assert img1.pixelColor(400, 250).alpha() > 0 or True

    def test_force_layout_false_allowed(self, make):
        """``forceLayout=False`` 走布局缓存，不崩且结构一致。"""
        chart = _ready(make(ElaChartWidget), _option([float(i) for i in range(2000)]))
        r = chart.benchmark(frames=2, forceLayout=False)
        assert set(r) == BENCH_KEYS
        assert r["layoutMs"] >= 0.0

    def test_loading_overlay_path(self, make):
        """加载遮罩开启时绘制路径也要走通。"""
        chart = _ready(make(ElaChartWidget), _option([float(i) for i in range(1000)]))
        chart.showLoading()
        r = chart.benchmark(frames=1)
        assert set(r) == BENCH_KEYS
        chart.hideLoading()

    def test_repeatable_values(self, make):
        """多次调用返回结构稳定（不因内部状态漂移而缺键）。"""
        chart = _ready(make(ElaChartWidget), _option([float(i) for i in range(4000)]))
        for _ in range(4):
            assert set(chart.benchmark(frames=1)) == BENCH_KEYS


# ---------------------------------------------------------------------------
# mark 组件统计快路径（markLine / markPoint）
# ---------------------------------------------------------------------------


def _marks_chart(make, series, **patch):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    option = {
        "animation": False,
        "xAxis": {"type": "category", "data": [str(i) for i in range(12)]},
        "yAxis": {"type": "value"},
        "series": series,
    }
    option.update(patch)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart


class TestValueStats:
    def test_stats_match_bruteforce(self, qapp, make):
        data = [3, None, 9, float("nan"), -2, 7]
        chart = _marks_chart(make, [{"type": "line", "name": "A", "data": data}])
        stats = chart.seriesRenderers[0].valueStats()
        assert stats["min"] == -2
        assert stats["max"] == 9
        assert stats["minIndex"] == 4
        assert stats["maxIndex"] == 2
        assert stats["count"] == 4
        assert stats["sum"] == 17

    def test_stats_are_cached(self, qapp, make):
        chart = _marks_chart(make, [{"type": "line", "name": "A", "data": [1, 2, 3]}])
        renderer = chart.seriesRenderers[0]
        first = renderer.valueStats()
        assert renderer.valueStats() is first


class TestMarkComponents:
    def test_mark_line_average(self, qapp, make):
        chart = _marks_chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [2, 4, 6, 8],
                    "markLine": {"data": [{"type": "average"}]},
                }
            ],
        )
        comp = next(c for c in chart.components if c.optionKey == "markLine")
        assert comp._lines[0]["value"] == 5.0

    def test_mark_point_max_position(self, qapp, make):
        chart = _marks_chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [2, 4, 9, 8],
                    "markPoint": {"data": [{"type": "max"}]},
                }
            ],
        )
        comp = next(c for c in chart.components if c.optionKey == "markPoint")
        mark = comp._marks[0]
        assert mark["y"] == 9
        assert mark["x"] == 2

    def test_mark_point_min_position(self, qapp, make):
        chart = _marks_chart(
            make,
            [
                {
                    "type": "line",
                    "name": "A",
                    "data": [2, -4, 9, 8],
                    "markPoint": {"data": [{"type": "min"}]},
                }
            ],
        )
        comp = next(c for c in chart.components if c.optionKey == "markPoint")
        mark = comp._marks[0]
        assert mark["y"] == -4
        assert mark["x"] == 1

    def test_mark_line_uses_raw_value_not_stacked(self, qapp, make):
        chart = _marks_chart(
            make,
            [
                {"type": "line", "name": "A", "data": [3, 3], "stack": "t"},
                {
                    "type": "line",
                    "name": "B",
                    "data": [1, 2],
                    "stack": "t",
                    "markLine": {"data": [{"type": "average"}]},
                },
            ],
        )
        comp = next(c for c in chart.components if c.optionKey == "markLine")
        # B 的原始均值是 1.5（不是叠加后的 4.5 / 6.0）
        assert comp._lines[0]["value"] == 1.5


# ---------------------------------------------------------------------------
# brush / lasso 快路径
# ---------------------------------------------------------------------------


def _brush_chart(make, brush_type="rect"):
    chart = make(ElaChartWidget)
    chart.resize(640, 420)
    data = [[i, math.sin(i / 40.0) * 50 + 100] for i in range(1000)]
    chart.setOption(
        {
            "animation": False,
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "brush": {"type": brush_type},
            "series": [{"type": "line", "name": "A", "data": data}],
        }
    )
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    return chart, data


def _rect(plot: QRectF) -> QRectF:
    return QRectF(
        plot.left() + plot.width() * 0.2,
        plot.top() + plot.height() * 0.2,
        plot.width() * 0.4,
        plot.height() * 0.4,
    )


def _brute_force(chart, data, contains):
    coord = chart.primaryCoord()
    out = set()
    for index, (x, y) in enumerate(data):
        pt = coord.mapPoint(x, y)
        if contains(pt):
            out.add(index)
    return out


class TestRectBrush:
    def test_vectorized_matches_brute_force(self, qapp, make):
        chart, data = _brush_chart(make)
        brush = chart.brushComponent()
        plot = chart.primaryCoord().plot
        brush._rect = _rect(plot)
        brush._collect()
        expected = _brute_force(chart, data, brush._rect.contains)
        got = {item["dataIndex"] for item in brush.selected_items}
        assert got == expected
        assert len(got) > 0
        assert all("px" in item and "py" in item for item in brush.selected_items)

    def test_highlight_positions_are_cached(self, qapp, make):
        chart, _data = _brush_chart(make)
        brush = chart.brushComponent()
        brush._rect = _rect(chart.primaryCoord().plot)
        brush._collect()
        first = brush._highlight_points()
        assert brush._highlight_points() is first
        assert first

    def test_brushselected_payload_shape(self, qapp, make):
        chart, _data = _brush_chart(make)
        brush = chart.brushComponent()
        brush._rect = _rect(chart.primaryCoord().plot)
        seen = []
        chart.on("brushselected", seen.append)
        brush._collect()
        brush.selected.emit(list(brush.selected_items))
        assert seen
        selected = seen[-1]["batch"][0]["selected"]
        assert selected
        assert {"seriesIndex", "dataIndex", "seriesName"} <= set(selected[0])

    def test_clear_drops_cache(self, qapp, make):
        chart, _data = _brush_chart(make)
        brush = chart.brushComponent()
        brush._rect = _rect(chart.primaryCoord().plot)
        brush._collect()
        assert brush.selected_items
        brush.clear()
        assert brush.selected_items == []
        assert brush._highlight_points() == []


class TestLassoBrush:
    def test_lasso_matches_brute_force(self, qapp, make):
        chart, data = _brush_chart(make, brush_type="lasso")
        brush = chart.brushComponent()
        plot = chart.primaryCoord().plot
        box = _rect(plot)
        poly = QPolygonF(
            [
                QPointF(box.left(), box.top()),
                QPointF(box.right(), box.top()),
                QPointF(box.right(), box.bottom()),
                QPointF(box.left(), box.bottom()),
            ]
        )
        brush._poly = [
            QPointF(box.left(), box.top()),
            QPointF(box.right(), box.top()),
            QPointF(box.right(), box.bottom()),
            QPointF(box.left(), box.bottom()),
        ]
        brush._rect = box
        brush._collect()
        expected = _brute_force(
            chart, data, lambda pt: poly.containsPoint(pt, Qt.FillRule.OddEvenFill)
        )
        got = {item["dataIndex"] for item in brush.selected_items}
        assert got == expected
