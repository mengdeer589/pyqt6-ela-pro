"""回归：缩放 / 平移后采样必须跟着窗口走（两处真 bug）。

1. **窗口写回顺序**：``dataZoom.apply()`` 原本跑在组件 ``layout()`` 里 = 系列布局
   之后。于是「缩放后再 setOption」会把窗口写回轴、而系列已按全量采样，且帧末布局
   缓存键命中 → 错配永久留下（曲线变稀）。
2. **纯 Python 兜底路径没有窗口裁剪**：dict 项 / 混合类型数据走不到 numpy 快路径，
   那条路径的等距抽稀跑在全量上 → 缩放后绘制只覆盖窗口的一小段（覆盖 195% /
   2000% / 7399%）。
"""

from __future__ import annotations

import numpy as np

from pyqt6_ela_pro import ElaChartWidget
from pyqt6_ela_pro.charts import _downsample as _ds

N = 200_000


def _chart(make, data, axis="value"):
    chart = make(ElaChartWidget)
    chart.resize(1000, 600)
    xaxis = (
        {"type": "category", "data": [str(i) for i in range(len(data))]}
        if axis == "category"
        else {"type": "value"}
    )
    chart.setOption(
        {
            "animation": False,
            "xAxis": xaxis,
            "yAxis": {"type": "value"},
            "series": [{"type": "line", "name": "A", "data": data}],
        }
    )
    chart.anim.setProgress(1.0)
    chart.grab()
    return chart


def _drawn(chart):
    return [i for i in chart.seriesRenderers[0]._point_idx if i is not None]


def _window(chart):
    axis = chart.primaryCoord().x_axis
    if axis.type == "value":
        return float(axis.vmin), float(axis.vmax)
    offset = float(axis.windowOffset())
    return offset, offset + float(len(axis.categories))


def _assert_inside(chart, tol=0.02):
    """x == 下标 的数据：绘制下标必须落在轴窗口内（强判据）。"""
    lo, hi = _window(chart)
    idx = _drawn(chart)
    assert idx, "没有绘制点"
    span = max(1.0, hi - lo)
    assert min(idx) >= lo - span * tol, f"首个点 {min(idx)} 在窗口 {lo:.0f} 之前"
    assert max(idx) <= hi + span * tol, f"末个点 {max(idx)} 在窗口 {hi:.0f} 之后"


def _assert_in_plot(chart, min_cover=0.9):
    """任意数据形态：绘制点必须落在绘图区内，且铺满可见窗口（真实 x 也适用）。"""
    plot = chart.primaryCoord().plot
    pts = [p for p in chart.seriesRenderers[0]._points if p is not None]
    assert pts, "没有绘制点"
    xs = [p.x() for p in pts]
    assert min(xs) >= plot.left() - 2.0, f"绘制点越出绘图区左边界：{min(xs):.1f}"
    assert max(xs) <= plot.right() + 2.0, f"绘制点越出绘图区右边界：{max(xs):.1f}"
    cover = (max(xs) - min(xs)) / max(1.0, plot.width())
    assert cover >= min_cover, f"只覆盖 {cover:.0%} 绘图宽（采样没跟着窗口）"


class TestWindowFollowsZoom:
    def test_zoom_then_setoption_keeps_window(self, qapp, make):
        data = (np.arange(N) % 997).astype(float)
        chart = _chart(make, data)
        chart.dispatchAction({"type": "dataZoom", "start": 40, "end": 45})
        chart.grab()
        _assert_inside(chart)

        # 这条以前会把采样打回全量（窗口写回在系列布局之后 + 布局缓存命中）
        chart.setOption({"title": {"text": "改标题"}})
        chart.grab()
        _assert_inside(chart)
        assert len(_drawn(chart)) <= 1000 * 2.2

        chart.setOption({"series": [{"type": "line", "name": "A", "data": data}]})
        chart.grab()
        _assert_inside(chart)

    def test_pan_moves_window_and_sample(self, qapp, make):
        chart = _chart(make, (np.arange(N) % 997).astype(float))
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 25})
        chart.grab()
        before = _drawn(chart)
        _assert_inside(chart)

        chart.dispatchAction({"type": "dataZoom", "start": 60, "end": 65})
        chart.grab()
        assert _drawn(chart) != before, "平移后点集没跟着变"
        _assert_inside(chart)

    def test_resize_keeps_window(self, qapp, make):
        chart = _chart(make, (np.arange(N) % 997).astype(float))
        chart.dispatchAction({"type": "dataZoom", "start": 30, "end": 40})
        chart.grab()
        chart.resize(1250, 720)
        chart.grab()
        _assert_inside(chart)

    def test_category_window_follows_zoom(self, qapp, make):
        chart = _chart(make, (np.arange(N) % 997).astype(float), axis="category")
        chart.dispatchAction({"type": "dataZoom", "start": 30, "end": 32})
        chart.grab()
        _assert_inside(chart)
        assert len(_drawn(chart)) <= 1000 * 2.2


class TestAxisExtentFollowsData:
    """空数据起步 / 数据增长：轴范围与窗口必须跟着数据更新。

    ``DataZoomComponent._full_range`` 原先只在首次 ``apply()`` 时懒捕一次 ——
    空数据起步的图表（示例第 09 节的「生成数据」就是）会把 ``0~1`` 当全量钉死：
    30 万点到了轴范围仍是 ``0~1``，窗口裁剪把其它点全判在窗外（只画 2 点、
    缩放也没反应）。默认滚轮缩放让每个直角坐标图都带 dataZoom，于是必中。
    """

    def _empty_chart(self, make):
        chart = make(ElaChartWidget)
        chart.resize(900, 500)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [{"type": "line", "name": "A", "data": []}],
            }
        )
        chart.anim.setProgress(1.0)
        chart.grab()
        return chart

    def test_data_arriving_after_empty_start(self, qapp, make):
        chart = self._empty_chart(make)
        axis = chart.primaryCoord().x_axis
        assert axis.vmax <= 1.0, "空数据的初始范围就是 0~1"

        chart.setOption(
            {"series": [{"type": "line", "name": "A", "data": list(range(50_000))}]}
        )
        chart.grab()
        axis = chart.primaryCoord().x_axis
        assert axis.vmax >= 45_000, f"数据到了轴范围还是 {axis.vmin}~{axis.vmax}"
        renderer = chart.seriesRenderers[0]
        drawn = [p for p in renderer._points if p is not None]
        assert len(drawn) > 100, f"只画出 {len(drawn)} 个点"

    def test_zoom_survives_data_arrival(self, qapp, make):
        """空数据 → 数据到达 → 仍能滚轮缩放（而不是被 0~1 钉死）。"""

        chart = self._empty_chart(make)
        chart.setOption(
            {"series": [{"type": "line", "name": "A", "data": list(range(50_000))}]}
        )
        chart.grab()
        comp = chart._component("dataZoom")
        assert comp is not None
        assert chart.zoomStep(0.5) is True
        assert (round(comp.start), round(comp.end)) != (0, 100)
        chart.grab()
        _assert_inside(chart)

    def test_growing_data_keeps_extent_in_sync(self, qapp, make):
        """数据增长（周期 setOption 追加）后，轴范围与采样都跟着长。"""

        chart = self._empty_chart(make)
        for n in (10_000, 40_000, 80_000):
            chart.setOption(
                {
                    "series": [
                        {
                            "type": "line",
                            "name": "A",
                            "data": [float(i % 997) for i in range(n)],
                        }
                    ]
                }
            )
            chart.grab()
            axis = chart.primaryCoord().x_axis
            assert axis.vmax >= n * 0.9, f"{n} 点时轴范围是 {axis.vmin}~{axis.vmax}"
            renderer = chart.seriesRenderers[0]
            assert len([p for p in renderer._points if p is not None]) > 100
            _assert_inside(chart)


class TestPythonFallbackWindow:
    """纯 Python 兜底路径（numpy 化失败的数据）也要按窗口裁剪。"""

    def _dict_data(self):
        return [{"value": float(i % 997)} for i in range(N)]

    def test_dict_data_uses_fallback_path(self, qapp, make):
        chart = _chart(make, self._dict_data())
        assert chart.seriesRenderers[0]._np_y is None, "该数据应走纯 Python 兜底路径"

    def test_dict_data_follows_window(self, qapp, make):
        chart = _chart(make, self._dict_data())
        chart.dispatchAction({"type": "dataZoom", "start": 40, "end": 45})
        chart.grab()
        _assert_inside(chart)
        assert len(_drawn(chart)) <= 1000 * 2.2, "兜底路径的绘制量也要与像素挂钩"

    def test_dict_real_x_follows_window(self, qapp, make):
        """真实 x（非下标）的 dict 数据：按 x 过滤 + 屏幕坐标铺满窗口。"""

        data = [{"value": [i * 3.7, float(i % 997)]} for i in range(N)]
        chart = _chart(make, data)
        chart.dispatchAction({"type": "dataZoom", "start": 40, "end": 45})
        chart.grab()
        _assert_in_plot(chart)

        chart.dispatchAction({"type": "dataZoom", "start": 70, "end": 75})
        chart.grab()
        _assert_in_plot(chart)

    def test_mixed_list_follows_window(self, qapp, make):
        data = [None if i % 5000 else float(i % 997) for i in range(N)]
        chart = _chart(make, data)
        chart.dispatchAction({"type": "dataZoom", "start": 50, "end": 55})
        chart.grab()
        _assert_inside(chart)

    def test_category_dict_data_follows_window(self, qapp, make):
        chart = _chart(make, self._dict_data(), axis="category")
        chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 21})
        chart.grab()
        _assert_inside(chart)

    def test_without_numpy_still_windowed(self, qapp, make, monkeypatch):
        """缺 numpy（``_downsample.np is None``）时同样要窗口裁剪 + 等距抽稀。"""
        monkeypatch.setattr(_ds, "np", None)
        data = [float(i % 997) for i in range(N)]
        chart = _chart(make, data)
        assert chart.seriesRenderers[0]._np_y is None
        chart.dispatchAction({"type": "dataZoom", "start": 40, "end": 45})
        chart.grab()
        _assert_inside(chart)
        assert len(_drawn(chart)) <= 1000 * 2.2
