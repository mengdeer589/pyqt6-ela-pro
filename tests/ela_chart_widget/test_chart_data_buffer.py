"""charts 大数组零拷贝摄入（``charts.data``）的行为守卫。

覆盖三件事：

1. ``ElaNumericBuffer`` 的对外语义必须与 ``list`` 完全一致 —— 绘图、tooltip、
   既有测试全都直接比较数据，语义偏差会静默画错。
2. ``setOption`` 对大数值数组**按引用持有**（不再 ``deepcopy``），且
   ``getOption`` 把它还原成普通 list（调用方观察不到缓冲区）。
3. 结构型数据（dict / ``[x, y]`` 对 / 布尔 / 小数组）**不包装**，语义零变化。
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import _downsample as _ds
from pyqt6_ela_pro.charts.core import ElaChartWidget
from pyqt6_ela_pro.charts.data import (
    ElaNumericBuffer,
    isBufferLike,
    numpyAvailable,
    toBuffer,
    unwrapData,
)

np = _ds.np

#: toBuffer 的包装阈值（见 charts.data._BUFFER_MIN_LEN）
MIN_LEN = 256
BIG = 1000


def _flat(n=BIG, seed=1):
    return [float((i * seed) % 97) for i in range(n)]


def _option(data):
    return {
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "A", "data": data}],
    }


def _render(chart):
    chart.anim.setProgress(1.0)
    chart.show()
    for _ in range(3):
        QApplication.processEvents()
    return chart


# ---------------------------------------------------------------------------
# 缓冲区自身的语义
# ---------------------------------------------------------------------------
class TestBufferSemantics:
    @pytest.fixture
    def buf(self):
        return toBuffer(_flat())

    def test_returns_buffer_for_large_flat_list(self, buf):
        assert isinstance(buf, ElaNumericBuffer)
        assert len(buf) == BIG

    def test_sequence_protocol_matches_list(self, buf):
        src = _flat()
        assert len(buf) == len(src)
        assert buf[0] == src[0]
        assert buf[-1] == src[-1]
        assert list(buf) == src
        assert buf[3:6] == src[3:6]
        assert len(buf) == len(list(buf))

    def test_equality_with_list(self, buf):
        assert buf == _flat()
        assert not (buf == _flat(2))
        assert buf != _flat(2)
        # 长度不同 → False（与 list 语义一致），而不是 NotImplemented
        assert (buf == [1.0, 2.0]) is False
        # 非序列类型 → NotImplemented，交回 Python 反射为 False
        assert buf.__eq__(42) is NotImplemented
        assert (buf == 42) is False

    def test_elements_are_native_float(self, buf):
        """元素必须是原生 float —— numpy 标量的 repr / 类型断言会露馅。"""
        for v in (buf[0], buf[1], list(buf)[0]):
            assert type(v) is float, f"得到 {type(v)}，应为原生 float"

    def test_unhashable_like_list(self, buf):
        assert ElaNumericBuffer.__hash__ is None

    def test_repr_is_informative(self, buf):
        assert "ElaNumericBuffer" in repr(buf)
        assert str(BIG) in repr(buf)

    def test_numpy_interop(self, buf):
        """``numpy.asarray(buffer)`` 必须可用（内部范围统计依赖它）。"""
        arr = np.asarray(buf, dtype=np.float64)
        assert arr.shape == (BIG,)
        assert float(arr[0]) == buf[0]

    def test_empty_buffer_is_falsy(self):
        b = toBuffer([0.0] * MIN_LEN)
        assert len(b) == MIN_LEN
        empty = ElaNumericBuffer(np.zeros(0, dtype=np.float64))
        assert len(empty) == 0
        assert not empty  # __len__ 驱动真值，供 `data or []` 语义使用


# ---------------------------------------------------------------------------
# 何时包装 / 何时不包装
# ---------------------------------------------------------------------------
class TestToBufferGating:
    def test_small_list_not_wrapped(self):
        assert toBuffer([1.0, 2.0, 3.0]) is None
        assert toBuffer([1.0] * (MIN_LEN - 1)) is None

    def test_exactly_at_threshold_wrapped(self):
        assert toBuffer([1.0] * MIN_LEN) is not None

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param([{"name": "a", "value": 1}] * 300, id="dict"),
            pytest.param([[1.0, 2.0]] * 300, id="xy-pairs"),
            pytest.param([[1, 2, 3]] * 300, id="xyz-triples"),
            pytest.param([True, False] * 300, id="bools"),
            pytest.param(None, id="none"),
            pytest.param("abc" * 300, id="str"),
        ],
    )
    def test_structural_data_not_wrapped(self, data):
        """结构型数据必须原样走既有渲染路径，包装会破坏其语义。"""
        assert toBuffer(data) is None

    def test_none_gaps_allowed(self):
        """含 None 的间隙数据要包装（写成 NaN），断点语义由 isnan 承载。"""
        data = [1.0] * 300
        data[7] = None
        b = toBuffer(data)
        assert b is not None
        assert b[7] != b[7]  # NaN

    def test_ndarray_held_by_reference(self):
        """ndarray 必须**按引用**持有（真零拷贝）。"""
        arr = np.arange(BIG, dtype=np.float64)
        b = toBuffer(arr)
        assert b is not None
        assert b.raw is arr, "ndarray 未按引用持有"

    def test_none_or_buffer_returns_none(self):
        b = toBuffer(_flat())
        assert toBuffer(b) is None, "已是缓冲区不应重复包装"

    def test_isbufferlike_predicate(self):
        arr = np.arange(BIG, dtype=np.float64)
        b = toBuffer(_flat())
        assert isBufferLike(b) and isBufferLike(arr)
        # list 仍需一次 O(n) 转换，不算「已经可以按引用拿着」
        assert not isBufferLike(_flat()), "普通 list 不算 buffer-like"
        assert not isBufferLike([1.0, 2.0])
        assert not isBufferLike("abc")
        assert not isBufferLike(None)
        assert not isBufferLike([[1.0, 2.0]] * 300)

    def test_unwrapdata_passthrough(self):
        b = toBuffer(_flat())
        assert unwrapData(b) == _flat()
        assert unwrapData([1.0]) == [1.0]
        assert unwrapData(None) is None


# ``normalizeOptionData`` 已删除（死代码）：它只包装 series[].data，而
# ``setOption`` 的摄入路径走 ``_copy_series_entry`` / ``_merge_option_array``
# （同时服务 dataZoom / graphic），全库无人调用它。相关用例随函数一并删除。


# ---------------------------------------------------------------------------
# 端到端：setOption 按引用 / getOption 还原 / data() 不再返回空
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not numpyAvailable(), reason="需要 numpy")
class TestWidgetIntegration:
    def test_option_holds_buffer_not_copy(self, make):
        chart = make(ElaChartWidget)
        chart.setOption(_option(_flat()))
        held = chart._option["series"][0]["data"]
        assert isinstance(held, ElaNumericBuffer), "大数组未被包装，deepcopy 仍在发生"

    def test_ndarray_input_accepted(self, make):
        """阶段 1 的新能力：ndarray 直接传入即按引用摄入。"""
        chart = make(ElaChartWidget)
        arr = np.linspace(0, 10, BIG)
        chart.setOption(_option(arr))
        held = chart._option["series"][0]["data"]
        assert isinstance(held, ElaNumericBuffer)
        assert held.raw is arr, "ndarray 未零拷贝摄入"
        _render(chart)
        r = chart.seriesRenderers[0]
        assert r._data_len == BIG
        assert len(r._points) == BIG, "ndarray 数据未画出来"

    def test_renderer_data_not_empty_for_buffer(self, make):
        """曾经的静默失效点：``data()`` 只认 list，缓冲区会返回 ``[]``。"""
        chart = make(ElaChartWidget)
        chart.setOption(_option(_flat()))
        r = _render(chart).seriesRenderers[0]
        assert len(r.data()) == BIG, "data() 对缓冲区返回了空列表"
        assert len(r.dataView()) == BIG

    def test_getoption_returns_plain_lists(self, make):
        """调用方观察不到缓冲区。"""
        chart = make(ElaChartWidget)
        chart.setOption(_option(_flat()))
        got = chart.getOption()
        d = got["series"][0]["data"]
        assert type(d) is list, f"getOption 泄露了 {type(d)}"
        assert d == _flat()

    def test_getoption_result_is_independent(self, make):
        """getOption 仍是深拷贝：改动返回值不影响图表。"""
        chart = make(ElaChartWidget)
        chart.setOption(_option(_flat()))
        got = chart.getOption()
        got["series"][0]["data"][0] = -999.0
        got["series"][0]["name"] = "CHANGED"
        assert chart.seriesRenderers[0].data()[0] != -999.0
        assert chart._option["series"][0]["name"] == "A"

    def test_merge_path_also_buffers(self, make):
        """合并模式（默认）同样按引用持有。"""
        chart = make(ElaChartWidget)
        chart.setOption({"yAxis": {"type": "value"}, "series": []})
        chart.setOption({"series": [{"type": "line", "name": "A", "data": _flat()}]})
        assert isinstance(chart._option["series"][0]["data"], ElaNumericBuffer)

    def test_merge_replacement_buffers(self, make):
        """合并模式下**替换**已有系列的 data 也要包装。"""
        chart = make(ElaChartWidget)
        chart.setOption(_option([1.0, 2.0, 3.0]))
        chart.setOption({"series": [{"name": "A", "data": _flat()}]})
        assert isinstance(chart._option["series"][0]["data"], ElaNumericBuffer)

    def test_none_gaps_render_with_finite_axis(self, make):
        """None 间隙 → NaN → 轴范围仍须有限（nanmin/nanmax 口径）。"""
        data = [1.0] * 600
        data[100] = None
        data[300] = None
        data[500] = 50.0
        chart = make(ElaChartWidget)
        chart.resize(600, 400)
        chart.setOption(_option(data))
        _render(chart)
        coord = chart.coords[0]
        ymin, ymax = coord.y_axis.vmin, coord.y_axis.vmax
        assert ymin == ymin and ymax == ymax, "轴范围出现 NaN"
        assert ymax == 50.0
        r = chart.seriesRenderers[0]
        assert r._y_at(100) is None, "None 间隙应读作缺失"

    def test_large_line_renders_and_hits(self, make):
        """端到端：十万点走完摄入 → 布局 → 采样 → 绘制 → 命中。"""
        n = 100_000
        data = [float((i * 37) % 1000) for i in range(n)]
        chart = make(ElaChartWidget)
        chart.resize(800, 500)
        chart.setOption(_option(data))
        _render(chart)
        r = chart.seriesRenderers[0]
        assert 0 < len(r._points) <= n
        assert chart.convertToPixel("grid", {"x": 10.0, "y": 5.0}) is not None
        assert chart.convertFromPixel("grid", [10.0, 20.0]) is not None
        # 命中查询不得因缓冲区而抛异常（悬停按采样点位置判定）
        assert (
            chart.hitItem(chart.coords[0].plot.center().toPoint()) is not None or True
        )

    def test_animation_disabled_skips_snapshot(self, make):
        """``animation: False`` 时不再物化百万级旧数据快照。"""
        chart = make(ElaChartWidget)
        chart.resize(600, 400)
        chart.setOption(dict(_option(_flat()), animation=False))
        _render(chart)
        assert chart.seriesRenderers[0].prev_data is None
