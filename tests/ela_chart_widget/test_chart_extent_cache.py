"""数值范围缓存（``GridCoord._extent``）的守卫。

范围只取决于数据本身，与 dataZoom 窗口无关，而 ``setSeries`` 在**每次重建**
（缩放 / 平移 / 数据更新 / 图例切换）时都重算。百万点全量扫描是缩放卡顿的
主要来源，故按「数据对象身份 + 长度」缓存。

用例锁死三件事：

1. 同一份数据重复 ``setSeries`` 命中缓存（不重复扫描）；
2. 换成**另一份**数据必须重算，且不能被前者的缓存污染；
3. 缓存值持有数据对象**强引用** —— 只用 ``id`` 做键时，对象回收后 id 会被
   复用，把别的数据的范围当成自己的。
"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro.charts import _downsample as _ds
from pyqt6_ela_pro.charts import axes as _axes
from pyqt6_ela_pro.charts.data import numpyAvailable

np = _ds.np

pytestmark = pytest.mark.skipif(not numpyAvailable(), reason="需要 numpy")


class _Stub:
    """``GridCoord`` 构造所需的最小宿主。"""

    def __init__(self):
        self._option = {}

    def coordFor(self, opt):
        return None


@pytest.fixture
def coord():
    from pyqt6_ela_pro.charts.axes import GridCoord

    _axes._EXTENT_CACHE.clear()
    return GridCoord(_Stub(), {"xAxis": {"type": "value"}, "yAxis": {}})


def _series(data):
    return [{"type": "line", "name": "A", "data": data}]


def _data(n=50_000, scale=1.0, offset=0.0):
    return [offset + float(i % 1000) * scale for i in range(n)]


class TestExtentCache:
    def test_extent_computed(self, coord):
        ext = coord._extent(_data(1000))
        assert ext is not None
        x0, x1, y0, y1 = ext
        assert (x0, x1) == (0.0, 999.0)
        assert y0 == 0.0 and y1 == 999.0

    def test_repeat_hits_cache(self, coord, mocker):
        """同一对象重复查询必须命中缓存（不重复做 numpy 全量扫描）。"""
        data = _data(200_000)
        spy = mocker.spy(np, "asarray")
        coord._extent(data)
        first = spy.call_count
        assert first >= 1
        for _ in range(5):
            coord._extent(data)
        assert spy.call_count == first, "重复查询未命中缓存"

    def test_different_data_recomputed(self, coord):
        """另一份数据必须重算，且不被前者的缓存污染。"""
        a = _data(1000, scale=1.0)
        coord._extent(a)
        ext = coord._extent(_data(1000, scale=2.0, offset=500.0))
        _, _, y0, y1 = ext
        assert y0 == 500.0 and y1 == 500.0 + 2 * 999.0

    def test_same_length_different_data_recomputed(self, coord):
        """**等长**换数据必须重算 —— 键含长度，但还要靠身份区分。"""
        a = _data(1000, scale=1.0)
        b = _data(1000, scale=3.0)
        assert len(a) == len(b)
        coord._extent(a)
        _, _, y0, y1 = coord._extent(b)
        assert y1 == 3 * 999.0, "等长换数据后范围未重算"

    def test_cache_entry_holds_strong_reference(self, coord):
        """缓存值必须持有数据对象强引用（防 id 复用）。"""
        data = _data(1000)
        coord._extent(data)
        key = (id(data), len(data))
        entry = _axes._EXTENT_CACHE.get(key)
        assert entry is not None, "未写入缓存"
        assert entry[0] is data, "缓存未持有数据对象强引用"

    def test_id_reuse_survives_gc(self, coord):
        """数据对象被回收后，新对象不得命中它的缓存条目。

        强引用使数据对象不会被回收，因此旧条目仍在；``is`` 复核保证即使
        id 被复用也只会算错 key 而不会返回错范围。
        """
        import gc

        old = _data(1000, scale=1.0)
        coord._extent(old)
        _, _, y0_old, _ = _axes._EXTENT_CACHE[(id(old), len(old))][1]
        assert y0_old == 0.0
        del old
        gc.collect()
        # 新对象算出自己的范围，且与旧数据不同
        new = _data(1000, scale=5.0)
        _, _, y0_new, y1_new = coord._extent(new)
        assert (y0_new, y1_new) == (0.0, 5 * 999.0)

    def test_setseries_uses_cache(self, coord, mocker):
        """``setSeries`` 走缓存路径（缩放时的真实调用点）。"""
        data = _data(200_000)
        spy = mocker.spy(np, "asarray")
        coord.setSeries(_series(data))
        first = spy.call_count
        assert first >= 1
        for _ in range(5):
            coord.setSeries(_series(data))
        assert spy.call_count == first, "setSeries 未命中范围缓存"

    def test_buffer_input_supported(self, coord):
        """缓冲区（大数组摄入后的常态）也能算范围。"""
        from pyqt6_ela_pro.charts.data import toBuffer

        buf = toBuffer(_data(1000))
        assert buf is not None
        x0, x1, y0, y1 = coord._extent(buf)
        assert (x0, x1) == (0.0, 999.0)
        assert y0 == 0.0 and y1 == 999.0

    def test_nan_gaps_do_not_poison_extent(self, coord):
        """None 间隙（→NaN）不得把轴范围变成 NaN（nanmin/nanmax 口径）。"""
        from pyqt6_ela_pro.charts.data import toBuffer

        data = [1.0] * 600
        data[100] = None
        data[300] = None
        data[500] = 50.0
        buf = toBuffer(data)
        ext = coord._extent(buf)
        assert ext is not None
        _, _, y0, y1 = ext
        assert y0 == y0 and y1 == y1, "范围出现 NaN"
        assert (y0, y1) == (1.0, 50.0)

    def test_all_nan_returns_none(self, coord):
        """全 NaN 无有效范围 → None（调用方回退默认 0~1）。"""
        from pyqt6_ela_pro.charts.data import toBuffer

        buf = toBuffer([None] * 600)
        assert coord._extent(buf) is None

    def test_empty_and_none(self, coord):
        assert coord._extent(None) is None
        assert coord._extent([]) is None

    def test_cache_size_bounded(self, coord):
        """缓存条目数有上限，超限整表清空（不无限增长）。"""
        for i in range(_axes._EXTENT_CACHE_LIMIT + 20):
            coord._extent([float(j + i * 1000) for j in range(300)])
        assert len(_axes._EXTENT_CACHE) <= _axes._EXTENT_CACHE_LIMIT

    def test_xy_pairs(self, coord):
        """``[x, y]`` 对形式的范围。"""
        pairs = [[float(i), float(i * 2)] for i in range(300)]
        x0, x1, y0, y1 = coord._extent(pairs)
        assert (x0, x1) == (0.0, 299.0)
        assert (y0, y1) == (0.0, 598.0)
