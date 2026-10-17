"""A 组回归：缓存失效、option 合并的 id 语义、numpy 数组承载。

三个 bug 同属「静默失效」——都不抛异常、不报错，只是**该生效的没生效**：

* **A5** 渲染器内部几何状态（下钻 / roam）变更后，系列层位图被原样贴回。
  症状是「点了完全没反应」：实测旭日图下钻后真实渲染差 5067 px，而贴回的
  位图与下钻前逐字节相同。
* **A6** ``_match_option_index`` 在「显式给了 id 但没匹配上」时回退到序号
  匹配，于是新 id **覆盖掉**同位置的别的系列。ECharts 明令禁止（id 不该被
  覆写），本库原先一个系列被静默吃掉。
* **A7/A8** 短 ndarray（< 256，不包装成缓冲区）踩到 ``len(v or ())`` ——
  numpy 对 ``or`` 求真值抛 ``ValueError``，被 ``warn_once`` 吞掉后表现为
  **bar / candlestick / boxplot 一根都不画、零报错**。而「可直接传 numpy
  数组」是本模块明文承诺的用法。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication

np = pytest.importorskip("numpy")

from pyqt6_ela_pro.charts import ElaChartWidget  # noqa: E402


def _chart(make, option, w=600, h=400, show=True):
    """把图表摆到**稳态终态**。

    **必须 ``anim.stop()`` 在 ``setProgress(1.0)`` 之前** ——``setOption`` 会
    启动入场动画，只推进度不停止的话动画仍在跑，于是：

    * 系列层位图缓存被**按设计绕过**（几何每帧都变，见 ``_series_layer_key``
      返回 ``None``），本文件的多条用例直接失去意义；
    * 抓图时进度是「墙钟推进到多少算多少」，柱高随之抖动 —— 实测同一份数据
      两次渲染的柱面积能差 9 倍（3724 vs 404 个采样点），而且哪一次偏小是
      随机的。

    同一条约定见 ``test_chart_series_layer_cache.py::_ready``。
    """
    chart = make(ElaChartWidget)
    chart.resize(w, h)
    chart.setOption(option)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    if show:
        chart.show()
    chart._layout_all(force=True)
    QApplication.processEvents()
    chart.anim.stop()
    return chart


#: 像素取样步长。判据一律用「差异占**总取样数**的比例」，所以稀疏取样
#: 不影响结论，却能把内存与耗时降一个数量级。
_PIXEL_SAMPLE_STEP = 4


def _pixels(chart, step=_PIXEL_SAMPLE_STEP):
    img = chart.grab().toImage()
    return [
        img.pixel(x, y)
        for y in range(0, img.height(), step)
        for x in range(0, img.width(), step)
    ]


def _diff(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


#: 允许的渲染差异占**总像素**的比例上限。
#:
#: AGENTS.md 记着「离屏渲染不确定，逐像素相等断言不可用」：同一份内容连续渲染
#: 两次有 16 个像素差（文字行）、抗锯齿折线约 156 个。而「整幅图被静默丢弃」
#: 时差异是**非背景像素的全体**（实测 bar 有 15976 个）。两者差三个数量级，
#: 所以按「占总像素比例」判定就足够干净 —— 而且**不必现场测噪声底噪**
#: （那要额外渲染 3 轮，本文件曾因此跑到 14 分钟）。
def _assert_similar(a, b, what, cap=0.02):
    """两幅渲染结果的差异必须在总像素的 ``cap`` 比例内。"""
    assert len(a) == len(b), "取样规模不同，无法比较"
    d = _diff(a, b)
    assert d <= len(a) * cap, (
        "{}: 差异 {}/{} 像素（{:.1%} > 上限 {:.0%}）—— 内容真的不一样了".format(
            what, d, len(a), d / len(a), cap
        )
    )


def _nonblank(chart):
    """非背景像素数（图元确实画出来了）。"""
    from collections import Counter

    pix = _pixels(chart)
    bg = Counter(pix).most_common(1)[0][0]
    return sum(1 for p in pix if p != bg)


SUNBURST = {
    "animation": False,
    "series": [
        {
            "type": "sunburst",
            "data": [
                {
                    "name": "A",
                    "value": 10,
                    "children": [
                        {"name": "A1", "value": 6},
                        {"name": "A2", "value": 4},
                    ],
                },
                {
                    "name": "B",
                    "value": 20,
                    "children": [
                        {"name": "B1", "value": 12},
                        {"name": "B2", "value": 8},
                    ],
                },
            ],
        }
    ],
}


class TestSeriesLayerCacheFollowsGeometry:
    """A5：几何状态变更必须让系列层位图失效。"""

    def test_epoch_advances_on_invalidate_layout(self, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {},
                "series": [{"type": "line", "name": "A", "data": [1, 2]}],
            },
        )
        before = chart._geometry_epoch
        chart.invalidateLayout()
        assert chart._geometry_epoch == before + 1

    def test_epoch_is_part_of_the_layer_key(self, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {},
                "series": [{"type": "line", "name": "A", "data": [1, 2]}],
            },
        )
        k1 = chart._series_layer_key()
        chart.invalidateLayout()
        k2 = chart._series_layer_key()
        assert k1 != k2, "几何状态变了而位图键没变 -> 旧位图会被贴回"

    def test_layer_key_stable_on_pure_repaint(self, make):
        """不能反过来：纯重绘也变键的话缓存就形同虚设（这是它存在的理由）。"""
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {},
                "series": [{"type": "line", "name": "A", "data": [1, 2]}],
            },
        )
        chart.grab()
        k1 = chart._series_layer_key()
        chart.repaint()
        QApplication.processEvents()
        assert chart._series_layer_key() == k1

    def test_sunburst_drilldown_repaints(self, make):
        """回归：下钻后位图必须真的刷新。"""
        chart = _chart(make, SUNBURST, w=500, h=400)
        r = chart.seriesRenderers[0]

        # 扫描出一个真能命中有 children 的节点的点（不猜角度约定）
        point = None
        for gx in range(20, 480, 7):
            for gy in range(20, 380, 7):
                p = QPointF(float(gx), float(gy))
                hit = r.hitTest(p)
                if not isinstance(hit, dict):
                    continue
                idx = hit.get("dataIndex")
                if isinstance(idx, int) and 0 <= idx < len(r._nodes):
                    if r._nodes[idx].children:
                        point = p
                        break
            if point is not None:
                break

        if point is None:
            pytest.skip("没找到可下钻的扇区（布局尺寸变化）")

        before = _pixels(chart)  # 先建立位图缓存
        assert r.onMousePress(point) is True
        QApplication.processEvents()
        after = _pixels(chart)

        assert r._focus_path, "应已进入下钻态"
        # 缓存把旧位图贴回时差异是 **0**；离屏噪声只有几十个像素。判据取
        # 「差异超过总像素的 1%」，两种情形差几个数量级，不会混淆。
        assert _diff(before, after) > len(before) * 0.01, (
            f"下钻后差异仅 {_diff(before, after)}/{len(before)} 像素 -> 缓存把旧位图贴回来了"
        )

    def test_reset_drill_also_repaints(self, make):
        chart = _chart(make, SUNBURST, w=500, h=400)
        r = chart.seriesRenderers[0]
        r._focus_path = [0]
        chart.invalidateLayout()
        QApplication.processEvents()
        before = _pixels(chart)
        r.resetDrill()
        QApplication.processEvents()
        assert _diff(before, _pixels(chart)) > len(before) * 0.01


class TestExplicitIdIsNeverOverwritten:
    """A6：显式 id 未匹配时必须新增，不得按序号覆盖。"""

    BASE = {
        "xAxis": {"type": "category", "data": ["a", "b", "c"]},
        "yAxis": {},
    }

    def test_new_id_does_not_destroy_existing_series(self, make):
        chart = _chart(
            make,
            {
                **self.BASE,
                "series": [
                    {"id": "a", "name": "A", "data": [1, 2]},
                    {"id": "b", "name": "B", "data": [3, 4]},
                ],
            },
        )
        assert len(chart.seriesRenderers) == 2

        chart.setOption(
            {"series": [{"id": "zzz", "type": "bar", "name": "NEW", "data": [9, 9]}]}
        )
        QApplication.processEvents()

        names = sorted(r.name for r in chart.seriesRenderers)
        assert names == ["A", "B", "NEW"], f"系列被吃掉了：{names}"

    def test_new_id_keeps_old_series_type_and_name(self, make):
        """只给 id 不给 name/type 时，幸存者不能被换成用户没要求过的组合。"""
        chart = _chart(
            make,
            {
                **self.BASE,
                "series": [
                    {"id": "a", "name": "A", "type": "line", "data": [1, 2]},
                    {"id": "b", "name": "B", "type": "bar", "data": [3, 4]},
                ],
            },
        )
        chart.setOption({"series": [{"id": "zzz", "data": [7, 7]}]})
        QApplication.processEvents()

        by_name = {r.name: r for r in chart.seriesRenderers}
        assert set(by_name) == {"A", "B", "series2"}
        assert by_name["B"].opt.get("type") == "bar", "B 的 type 不该被新项改掉"

    def test_matching_id_still_updates_in_place(self, make):
        """正常路径不能被这次修改带坏：id 命中就该就地更新。"""
        chart = _chart(
            make,
            {**self.BASE, "series": [{"id": "a", "name": "A", "data": [1, 2]}]},
        )
        chart.setOption({"series": [{"id": "a", "name": "A", "data": [5, 6, 7]}]})
        QApplication.processEvents()
        assert len(chart.seriesRenderers) == 1
        assert list(chart.seriesRenderers[0].data()) == [5, 6, 7]

    def test_name_fallback_still_works(self, make):
        """无 id 时仍按 name 匹配（ECharts 语义不变）。"""
        chart = _chart(
            make,
            {**self.BASE, "series": [{"name": "A", "data": [1, 2]}]},
        )
        chart.setOption({"series": [{"name": "A", "data": [8, 9]}]})
        QApplication.processEvents()
        assert len(chart.seriesRenderers) == 1
        assert list(chart.seriesRenderers[0].data()) == [8, 9]

    def test_index_fallback_without_id_still_works(self, make):
        """无 id 无 name 时仍按序号 —— 那是 ECharts 允许的默认行为。"""
        chart = _chart(
            make,
            {**self.BASE, "series": [{"name": "A", "data": [1, 2]}]},
        )
        chart.setOption({"series": [{"data": [3, 4]}]})
        QApplication.processEvents()
        assert len(chart.seriesRenderers) == 1
        assert list(chart.seriesRenderers[0].data()) == [3, 4]


CARTESIAN_BASE = {
    "xAxis": {"type": "category", "data": ["a", "b", "c", "d"]},
    "yAxis": {},
}


def _render(make, stype, data, w=600, h=400):
    chart = _chart(
        make,
        {**CARTESIAN_BASE, "series": [{"type": stype, "name": "S", "data": data}]},
        w,
        h,
    )
    pix = _pixels(chart)
    chart.hide()
    return pix


class TestShortNumpyArraysAreNotDropped:
    """A7/A8：短 ndarray（< 256）必须与 list 渲染一致。"""

    @pytest.mark.parametrize(
        "stype", ["bar", "line", "scatter", "candlestick", "boxplot"]
    )
    def test_ndarray_matches_list_pixel_for_pixel(self, make, stype):
        arr = np.array([1.0, 2.0, 3.0, 4.0])
        assert len(arr) < 256, "本用例针对「不包装成缓冲区」的短数组"
        lst = [1.0, 2.0, 3.0, 4.0]

        # 曾经是「一根都不画」：整幅图与空白无异，差异是全图量级
        _assert_similar(_render(make, stype, arr), _render(make, stype, lst), stype)

    @pytest.mark.parametrize("stype", ["bar", "line", "candlestick", "boxplot"])
    def test_ndarray_actually_draws_something(self, make, stype):
        """正向判据：非背景像素数与 list 相当（不是「恰好都是空白」）。"""
        arr = np.array([1.0, 2.0, 3.0, 4.0])
        c_arr = _chart(
            make,
            {**CARTESIAN_BASE, "series": [{"type": stype, "name": "S", "data": arr}]},
        )
        from_arr = _nonblank(c_arr)
        c_arr.hide()
        c_list = _chart(
            make,
            {
                **CARTESIAN_BASE,
                "series": [{"type": stype, "name": "S", "data": [1.0, 2.0, 3.0, 4.0]}],
            },
        )
        from_list = _nonblank(c_list)
        c_list.hide()

        assert from_arr > 50, f"{stype}: ndarray 只画出 {from_arr} 个非背景像素"
        assert abs(from_arr - from_list) <= max(from_list * 0.1, 30), (
            f"{stype}: ndarray={from_arr} 与 list={from_list} 相差过大"
        )

    def test_2d_ndarray_pairs_do_not_raise(self, make):
        """``[x, y]`` 点对的 2-D ndarray 曾抛 'only 0-dimensional arrays'。"""
        pts = np.array([[0.0, 1.0], [1.0, 3.0], [2.0, 2.0], [3.0, 5.0]])
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "value"},
                "yAxis": {},
                "series": [{"type": "line", "name": "P", "data": pts}],
            },
        )
        chart.grab()

    def test_get_option_returns_detached_list(self, make):
        arr = np.array([1.0, 2.0, 3.0, 4.0])
        chart = _chart(
            make,
            {
                **CARTESIAN_BASE,
                "series": [{"type": "line", "name": "S", "data": arr}],
            },
        )
        out = chart.getOption()["series"][0]["data"]
        assert isinstance(out, list), f"getOption 泄漏了 {type(out).__name__}"
        assert out is not arr

        out[0] = 999.0
        assert arr[0] == 1.0, "改 getOption 的结果改到了调用方的数组"
        assert list(chart.seriesRenderers[0].data())[0] != 999.0

    def test_renderer_data_supports_equality(self, make):
        """裸 ndarray 没有 ``__eq__ -> bool``；``data() == [...]`` 不得抛。"""
        chart = _chart(
            make,
            {
                **CARTESIAN_BASE,
                "series": [
                    {
                        "type": "line",
                        "name": "S",
                        "data": np.array([1.0, 2.0, 3.0, 4.0]),
                    }
                ],
            },
        )
        d = chart.seriesRenderers[0].data()
        assert bool(d == [1.0, 2.0, 3.0, 4.0]) is True

    def test_renderer_data_identity_is_stable(self, make):
        """``_data_ref`` 依赖同一 data 对象：每次新建包装件会让采样缓存永不命中。"""
        chart = _chart(
            make,
            {
                **CARTESIAN_BASE,
                "series": [
                    {
                        "type": "line",
                        "name": "S",
                        "data": np.array([1.0, 2.0, 3.0, 4.0]),
                    }
                ],
            },
        )
        r = chart.seriesRenderers[0]
        assert r.data() is r.data()

    @pytest.mark.parametrize("width", [2, 8, 30])
    def test_narrow_plot_does_not_crash(self, make, width):
        """绘图区极窄时 ``n_out`` 落到算法下界，曾触发 tsdownsample 的 Rust panic。"""
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": [str(i) for i in range(50)]},
                "yAxis": {},
                "series": [{"type": "line", "name": "S", "data": list(range(50))}],
            },
            w=max(width, 80),
            h=200,
        )
        chart.grab()

    def test_duplicate_x_does_not_crash(self, make):
        """重复 x + value 轴曾让 Rust searchsorted 越界 panic（0xC0000409）。"""
        xs = np.repeat(np.arange(1000, dtype=np.float64), 3)
        ys = np.sin(xs / 20.0)
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "value"},
                "yAxis": {},
                "series": [
                    {
                        "type": "line",
                        "name": "dup",
                        "data": np.column_stack([xs, ys]),
                        "sampling": "minmax",
                    }
                ],
            },
        )
        chart.grab()
