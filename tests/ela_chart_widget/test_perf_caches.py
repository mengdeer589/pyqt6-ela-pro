"""F1 / F3 / F4 回归：性能项的正确性（不写死耗时）。

三条都是「该生效的没生效」类：

* **F1** ``uniformItemStyle`` 用「探前 32 项找dict 项」判断是否存在逐项
  ``itemStyle``。抽样在这里**本质上不可证伪** —— ``data = [1]*500 +
  [{"itemStyle": …}]`` 的探窗里全是数字，于是返回「统一外观」，那根柱子
  用系列色而不是用户明确配的颜色，**无任何报错**。
* **F3** stack 折线每次 ``layout`` 重建整份叠加 data，下游采样缓存键含
  data 身份 → 永不命中。
* **F4** graph 力导布局是纯函数（固定种子 + 归一化空间）却在每次
  ``_layout_all`` 重跑 O(n² × iterations)（400 节点实测 2121 ms → 5.4 ms）。

**判据一律用「同一对象 / 同一结果」而不是耗时** —— 墙钟断言会 flaky
（本批次就有一条既有的 benchmark 墙钟断言 4 跑挂 1 次，见
``test_chart_benchmark.py``）。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication

np = pytest.importorskip("numpy")

from pyqt6_ela_pro.charts import ElaChartWidget  # noqa: E402


def _chart(make, option, w=1200, h=700):
    chart = make(ElaChartWidget)
    chart.resize(w, h)
    chart.setOption(option)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart.show()
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


class TestUniformItemStyleFindsLateItemStyles:
    """F1：任意位置的逐项 itemStyle 都必须被发现。"""

    @pytest.mark.parametrize("late_index", [0, 10, 31, 32, 100, 499])
    def test_detects_item_style_at_any_position(self, make, late_index):
        data = [1.0] * 500
        data[late_index] = {"value": 9.0, "itemStyle": {"color": "#ff0000"}}
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": [str(i) for i in range(500)]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "S", "data": data}],
            },
        )
        r = chart.seriesRenderers[0]
        assert r.uniformItemStyle() is None, (
            f"下标 {late_index} 的逐项 itemStyle 没被发现 —— 那根柱子会用系列色"
        )

    def test_pure_numeric_list_is_uniform(self, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b", "c"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "S", "data": [1.0, 2.0, 3.0]}],
            },
        )
        assert chart.seriesRenderers[0].uniformItemStyle() == {}

    def test_numeric_buffer_stays_uniform(self, make):
        """紧凑容器必是纯数值（包装时已校验），走 O(1) 快路径。"""
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": [str(i) for i in range(1000)]},
                "yAxis": {},
                "series": [
                    {
                        "type": "line",
                        "name": "S",
                        "data": np.arange(1000, dtype=np.float64),
                    }
                ],
            },
        )
        assert chart.seriesRenderers[0].uniformItemStyle() == {}

    def test_result_is_cached(self, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {},
                "series": [{"type": "bar", "name": "S", "data": [1.0, 2.0]}],
            },
        )
        r = chart.seriesRenderers[0]
        first = r.uniformItemStyle()
        assert r.uniformItemStyle() is first or r.uniformItemStyle() == first
        # 缓存条目存在 -> 第二次不再扫描
        assert r._uniform_style_cache is not None


STACK_OPT = {
    "animation": False,
    "xAxis": {"type": "category", "data": ["a", "b", "c", "d"]},
    "yAxis": {},
    "series": [
        # **必须带 id**：更新时也要按 id 匹配。显式给了 id 而旧项没有 id 时，
        # 合并语义是「新增一项」（见 ``_match_option_index``）—— 更新用的
        # 那个 id 得跟初始一致，否则测的就不是「就地更新」这条路径了。
        {"id": "a", "type": "line", "name": "A", "stack": "s", "data": [1, 2, 3, 4]},
        {
            "id": "b",
            "type": "line",
            "name": "B",
            "stack": "s",
            "data": [10, 20, 30, 40],
        },
    ],
}


class TestStackedDataIsMemoized:
    """F3：叠加结果必须复用同一个对象（下游采样缓存靠身份命中）。"""

    def test_same_object_across_calls(self, make):
        chart = _chart(make, STACK_OPT)
        r = chart.seriesRenderers[1]
        first = r._stacked_data()
        second = r._stacked_data()
        assert first is not None
        assert first is second, "每次重建 -> 采样缓存键每帧变 -> 永不命中"

    def test_values_still_correct(self, make):
        chart = _chart(make, STACK_OPT)
        r = chart.seriesRenderers[1]
        stacked = r._stacked_data()
        assert stacked == [11, 22, 33, 44], f"叠加值错了：{stacked}"

    def test_cache_invalidated_when_base_series_changes(self, make):
        """换个基准系列必须重算，不能拿旧的叠加值。"""
        chart = _chart(make, STACK_OPT)
        r = chart.seriesRenderers[1]
        assert r._stacked_data() == [11, 22, 33, 44]
        chart.setOption(
            {"series": [{"id": "a", "name": "A", "data": [100, 200, 300, 400]}]}
        )
        QApplication.processEvents()
        r2 = next(x for x in chart.seriesRenderers if x.name == "B")
        assert len(chart.seriesRenderers) == 2, "就地更新，不该新增系列"
        assert r2._stacked_data() == [110, 220, 330, 440], "换了基准数据却没重算"

    def test_no_stack_returns_none(self, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {},
                "series": [{"type": "line", "name": "A", "data": [1, 2]}],
            },
        )
        assert chart.seriesRenderers[0]._stacked_data() is None


def _graph_opt(n=30):
    return {
        "animation": False,
        "series": [
            {
                "id": "g",  # 同上：更新时要按 id 就地匹配，而不是追加新系列
                "type": "graph",
                "name": "G",
                "layout": "force",
                "data": [{"name": f"n{i}", "symbolSize": 10} for i in range(n)],
                "links": [
                    {"source": f"n{i}", "target": f"n{(i * 7 + 3) % n}"}
                    for i in range(n)
                ],
            }
        ],
    }


class TestForceLayoutIsMemoized:
    """F4：记忆化必须既快又不改结果。"""

    def test_force_layout_runs_once_across_relayouts(self, make):
        chart = _chart(make, _graph_opt(), w=800, h=600)
        r = chart.seriesRenderers[0]
        calls = []
        original = r._force_layout

        def counting(*a, **k):
            calls.append(1)
            return original(*a, **k)

        r._force_layout = counting
        for _ in range(5):
            chart._layout_all(force=True)
        assert len(calls) == 0, f"5 次重排里力导算了 {len(calls)} 次 —— 缓存没生效"

    def test_positions_identical_to_uncached(self, make):
        """缓存不得改变布局结果（力导是固定种子的纯函数）。"""
        chart = _chart(make, _graph_opt(), w=800, h=600)
        r = chart.seriesRenderers[0]
        cached = [(nd["pos"].x(), nd["pos"].y()) for nd in r._nodes]
        r._force_cache = None  # 强制重算
        chart._layout_all(force=True)
        QApplication.processEvents()
        fresh = [(nd["pos"].x(), nd["pos"].y()) for nd in r._nodes]
        assert cached == fresh, "记忆化改变了布局结果"

    def test_dragged_node_does_not_invalidate_other_nodes(self, make):
        """``_fixed`` 在力导之后应用，不该让其它节点重排。"""
        chart = _chart(make, _graph_opt(), w=800, h=600)
        r = chart.seriesRenderers[0]
        before = [(nd["pos"].x(), nd["pos"].y()) for nd in r._nodes]
        r._fixed[3] = QPointF(123.0, 456.0)
        chart._layout_all(force=True)
        QApplication.processEvents()
        assert (r._nodes[3]["pos"].x(), r._nodes[3]["pos"].y()) == (123.0, 456.0)
        for i in (0, 1, 2, 4, 5):
            assert (r._nodes[i]["pos"].x(), r._nodes[i]["pos"].y()) == before[i], (
                f"n{i} 被拖拽连带重排了"
            )

    def test_changing_edges_invalidates(self, make):
        chart = _chart(make, _graph_opt(), w=800, h=600)
        r = chart.seriesRenderers[0]
        before = [(nd["pos"].x(), nd["pos"].y()) for nd in r._nodes]
        chart.setOption(
            {
                "series": [
                    {
                        "id": "g",
                        "type": "graph",
                        "name": "G",
                        "layout": "force",
                        "data": [
                            {"name": f"n{i}", "symbolSize": 10} for i in range(30)
                        ],
                        "links": [{"source": "n0", "target": "n29"}],
                    }
                ]
            }
        )
        QApplication.processEvents()
        r2 = next(x for x in chart.seriesRenderers if x.name == "G")
        assert len(chart.seriesRenderers) == 1, "就地更新，不该新增系列"
        after = [(nd["pos"].x(), nd["pos"].y()) for nd in r2._nodes]
        assert after != before, "边集合变了却复用了旧布局"

    @pytest.mark.parametrize(
        "vary",
        ["edges", "seed", "iterations", "repulsion"],
    )
    def test_cache_key_covers_every_input(self, make, vary):
        """**直接打缓存键**，不经 setOption。

        为什么不能只靠 ``setOption`` 那条：``setOption`` 会 ``_rebuild`` 重建
        渲染器，新实例的 ``_force_cache`` 本来就是 ``None`` —— 于是无论键里
        有没有边集合都会重算，那条测试对键的内容**毫无鉴别力**。
        """
        chart = _chart(make, _graph_opt(), w=800, h=600)
        r = chart.seriesRenderers[0]
        nodes, edges, _cats = r._parse()
        base_force = {"seed": 42, "iterations": 80, "repulsion": 1.0}
        r._force_positions(nodes, edges, base_force)
        first = r._force_cache[0]

        if vary == "edges":
            second = r._force_positions(nodes, [(0, 29)], base_force)
        elif vary == "seed":
            second = r._force_positions(nodes, edges, {**base_force, "seed": 7})
        elif vary == "iterations":
            second = r._force_positions(nodes, edges, {**base_force, "iterations": 40})
        else:
            second = r._force_positions(nodes, edges, {**base_force, "repulsion": 3.0})
        assert r._force_cache[0] != first, f"{vary} 变了而缓存键没变 -> 复用了旧布局"
        assert second is not None

    def test_cache_key_identical_for_same_inputs(self, make):
        """同输入必须命中（否则记忆化等于没做）。"""
        chart = _chart(make, _graph_opt(), w=800, h=600)
        r = chart.seriesRenderers[0]
        nodes, edges, _cats = r._parse()
        force = {"seed": 42, "iterations": 80, "repulsion": 1.0}
        a = r._force_positions(nodes, edges, force)
        b = r._force_positions(nodes, edges, force)
        assert a is b

    def test_empty_node_set_hit_test_is_safe(self, make):
        """空节点集下 hitTest 不得 ZeroDivisionError。

        ``_node_centroid`` 除以节点数，而 ``paint`` 有 ``if not self._nodes``
        挡着、``hitTest`` 原本没有 —— 异常被命中分发吞掉，症状是「静默命中不到
        任何节点」，完全看不出是被零除吃掉的。
        """
        chart = _chart(make, _graph_opt(n=6), w=600, h=400)
        r = chart.seriesRenderers[0]
        r._nodes = []
        assert r.hitTest(QPointF(10.0, 10.0)) is None
        assert r._node_centroid().isNull()
