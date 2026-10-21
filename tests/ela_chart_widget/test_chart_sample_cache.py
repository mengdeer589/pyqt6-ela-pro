"""采样缓存与 numpy 视图缓存的**数据身份**守卫。

背景（两处，都是防御性的 —— ``_rebuild`` 每次都重建渲染器，故公开 API
（``setOption`` / ``updateOption`` / ``appendData``）走不到脏缓存）：

1. ``LineSeriesRenderer`` 的采样缓存键曾经只含
   ``(数据长度, n_out, 算法, 阈值, 窗口 lo, 窗口 hi)``，**不含数据身份**。
   渲染器实例存活期间若数据被换成等长的另一份，会得到完全相同的键而跳过
   重算，用旧数据的采样下标去画新数据（尖峰漏点 / 错位残留）。
2. ``_load_data`` 的 numpy 视图缓存判据：**只比对象身份**会漏判「原地增长」
   （同一个 list 被 extend，新点被静默丢弃）；**只比 ``(id, len)``** 则在
   对象回收后 id 被复用时可能把别的数据的视图当成自己的。

阶段 1（大数组零拷贝摄入）之后数据改为按引用持有，这两条会从「理论隐患」
变成「真实可达」，故在此锁死。

数据一律用 Python ``list``：当前引擎的 option 契约是 list，ndarray 摄入是
阶段 1 引入的能力。
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import _downsample as ds
from pyqt6_ela_pro.charts.core import ElaChartWidget
from pyqt6_ela_pro.charts.data import toBuffer

pytestmark = pytest.mark.skipif(not ds.available(), reason="需要 numpy + tsdownsample")

N = 50_000


def _spiked_at(idx, n=N, height=100.0):
    """全零 + 单点尖峰的序列（尖峰处必被 min/max 采样保留）。"""
    ys = [0.0] * n
    ys[idx] = height
    return ys


def _option(data):
    return {
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "A", "data": data, "sampling": True}],
    }


def _render(chart):
    """推进事件循环使布局生效，返回折线渲染器。"""
    chart.anim.setProgress(1.0)
    chart.show()
    for _ in range(3):
        QApplication.processEvents()
    return chart.seriesRenderers[0]


def _relayout(r):
    """在**同一个渲染器实例**上重跑 layout（不经 setOption，不重建渲染器）。"""
    r.layout(r.chart.coordFor(r.opt).plot)
    return r


class TestSampleCacheDataIdentity:
    def test_sampling_actually_happens(self, make):
        """前提守卫：本组用例依赖「采样确实生效」。"""
        chart = make(ElaChartWidget)
        chart.resize(900, 500)
        chart.setOption(_option(_spiked_at(0)))
        r = _render(chart)
        assert 0 < len(r._point_idx) < N, "采样未生效，用例前提不成立"

    def test_cache_invalidated_on_data_identity_change(self, make):
        """采样缓存按数据身份失效：换等长数据后旧缓存键必须被清掉。"""
        chart = make(ElaChartWidget)
        chart.resize(900, 500)
        chart.setOption(_option(_spiked_at(0)))
        r = _render(chart)
        keys_a = list(r._sample_lru)
        assert keys_a, "首帧未写入采样缓存"

        # 同一渲染器实例，换成等长的另一份数据
        r.opt["data"] = _spiked_at(N - 1)
        _relayout(r)
        keys_b = list(r._sample_lru)
        assert keys_b, "换数据后新窗口未写缓存"
        assert all(k not in keys_b for k in keys_a), (
            "换数据后旧缓存键仍在 —— 缓存未按数据身份失效"
        )

    def test_same_length_replacement_recomputes(self, make):
        """等长换数据后采样点集必须重算。"""
        chart = make(ElaChartWidget)
        chart.resize(900, 500)
        chart.setOption(_option(_spiked_at(0)))
        r = _render(chart)
        first = list(r._point_idx)
        assert first, "首帧未产生采样点"

        r.opt["data"] = _spiked_at(N - 1)
        _relayout(r)
        second = list(r._point_idx)

        assert first != second, (
            "等长换数据后采样点集完全不变 —— 采样缓存未按数据身份失效"
        )
        assert (N - 1) in set(second), "新数据的尖峰下标未被采到"

    def test_repeated_render_hits_cache(self, make):
        """同一份数据 + 同一窗口重复渲染必须命中缓存（不重跑抽稀）。"""
        from types import MethodType

        chart = make(ElaChartWidget)
        chart.resize(900, 500)
        chart.setOption(_option(_spiked_at(0)))
        r = _render(chart)
        idx_first = list(r._point_idx)

        calls = []
        orig = r._decimate

        def counted(_self, *args, **kwargs):
            calls.append(1)
            return orig(*args, **kwargs)

        r._decimate = MethodType(counted, r)
        chart.invalidateLayout()
        r2 = _render(chart)
        assert r2 is r
        assert list(r2._point_idx) == idx_first
        assert not calls, "同数据 + 同窗口重复渲染不应重跑抽稀"

    def test_window_lru_reuses_earlier_zoom(self, make):
        """窗口 A → B → A：第三次必须命中 LRU（旧的单槽实现会重算）。"""
        from types import MethodType

        chart = make(ElaChartWidget)
        chart.resize(900, 500)
        chart.setOption(_option(_spiked_at(0)))
        r = _render(chart)

        calls = []
        orig = r._decimate

        def counted(_self, *args, **kwargs):
            calls.append(1)
            return orig(*args, **kwargs)

        r._decimate = MethodType(counted, r)

        def zoom(a, b):
            chart.dispatchAction({"type": "dataZoom", "start": a, "end": b})
            chart.grab()
            QApplication.processEvents()

        zoom(30, 50)
        n_after_a = len(calls)
        zoom(50, 70)
        n_after_b = len(calls)
        zoom(30, 50)  # 回到窗口 A
        assert (n_after_a, n_after_b) == (1, 2), (
            f"每个新窗口应恰好重算一次，实际 {n_after_a}/{n_after_b}"
        )
        assert len(calls) == 2, "回到窗口 A 应命中 LRU 缓存，不应重算"


@pytest.mark.skipif(not ds.available(), reason="需要 numpy（缓冲区要求 numpy 承载）")
class TestBufferIsImmutable:  # noqa: N801 - 测试类名沿用既有风格
    """缓冲区是**只读**的：原地修改会抛异常，而不是静默改坏图表。

    这是有意的设计取舍：大数组按引用持有，图表与调用方共享同一份内存，
    让 ``append`` / ``del`` 悄悄生效会产生极难排查的错位。改数据的正确
    方式是重新 ``setOption``。
    """

    @pytest.mark.parametrize(
        "op",
        [
            pytest.param(lambda b: b.append(1.0), id="append"),
            pytest.param(lambda b: b.extend([1.0]), id="extend"),
            pytest.param(lambda b: b.__delitem__(0), id="delitem"),
            pytest.param(lambda b: b.__setitem__(0, 1.0), id="setitem"),
        ],
    )
    def test_mutation_rejected(self, make, op):
        """``Sequence`` 未混入可变方法，故一律 ``AttributeError``。"""
        chart = make(ElaChartWidget)
        chart.resize(900, 500)
        chart.setOption(_option(_spiked_at(0)))
        r = _render(chart)
        before = list(r.data())
        with pytest.raises((AttributeError, TypeError)):
            op(r.data())
        assert list(r.data()) == before, "数据被改动了"


class TestDataViewCacheIdentity:
    def test_data_ref_holds_strong_reference(self, make):
        """``_data_ref`` 必须持有数据对象强引用（防 id 复用）。

        断言的是「持有 ``data()`` 返回的那个对象」而非「持有调用方传入的
        list」——``setOption`` 目前会 deepcopy option（阶段 1 消除），
        渲染器看到的是副本；强引用不变量针对的是渲染器实际使用的那份数据。
        """
        chart = make(ElaChartWidget)
        chart.resize(900, 500)
        chart.setOption(_option(_spiked_at(0)))
        r = _render(chart)
        assert r._data_ref is r.data(), "_data_ref 未持有 data() 返回的数据对象"
        # 重复渲染时引用保持稳定（证明缓存是按这份对象判定的）
        chart.invalidateLayout()
        r2 = _render(chart)
        assert r2._data_ref is r.data(), "重复渲染后 _data_ref 变成了另一个对象"

    def test_in_place_growth_is_detected(self, make):
        """**小数组**（未达包装阈值，仍是 list）在 opt 上原地 extend 后必须重建视图。

        只比对象身份的判据会在这里漏判 —— 新点会被静默丢弃。

        注意修改的是 ``r.opt["data"]``（渲染器实际持有的那个 list）：
        调用方传入的原列表在 ``setOption`` 时已被拷贝，改它不影响图表。
        缓冲区（≥256）不可原地修改，见 ``TestBufferIsImmutable``。
        """
        small = [float(i) for i in range(200)]
        assert toBuffer(small) is None, "本用例前提失效：200 点应不包装"
        chart = make(ElaChartWidget)
        chart.resize(900, 500)
        chart.setOption(_option(small))
        r = _render(chart)
        assert r._data_len == 200

        r.opt["data"].extend([999.0, 1000.0])  # 同一对象原地增长
        _relayout(r)
        assert r._data_len == 202, "原地增长后 _data_len 未更新"
        assert r._y_at(201) == 1000.0, "原地增长后的新点未被纳入 numpy 视图"

    def test_in_place_shrink_is_detected(self, make):
        """原地缩短同样必须重建（否则尾部读到越界值）。"""
        small = [float(i) for i in range(200)]
        chart = make(ElaChartWidget)
        chart.resize(900, 500)
        chart.setOption(_option(small))
        r = _render(chart)
        del r.opt["data"][100:]
        _relayout(r)
        assert r._data_len == 100, "原地缩短后 _data_len 未更新"
        assert r._y_at(99) == 99.0
        assert r._y_at(100) is None, "缩短后越界下标应返回 None"
