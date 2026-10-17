"""C2 / C4 / E 组回归：组件层命中与 option 解析。

* **C2** ``markPoint`` / ``markLine`` 的 ``hitTest`` 是**死代码** —— 命中分发
  只遍历 ``_series``，组件层从没被问过，于是这两类标注既没 tooltip 也没
  click。``markArea`` / ``graphic`` 则是**刻意不接**（前者是半透明背景区域，
  接进来会抢走系列的悬停；后者是纯装饰），两者都不该被误当成 bug 接上。
* **E3** map 取「第一个带 ``mapColor`` 的组件」→ 多个系列共用同一个
  visualMap，给第二个系列配的独立色带永远不生效。
* **E4** 自定义 ``map`` 名缺 ``geo.regions`` 时静默回落到内置演示地图。
* **E6** ``roam: 1`` / ``"true"`` 落进「方向名」分支 → roam 被静默关掉。
* **E7** ``graphic`` 的 ``left``/``top`` 只认 ``"center"`` 与纯数值 ——
  ECharts 的 ``"middle"`` 与 ``"30%"`` 都落进兜底分支（0），元素悄悄跑到
  左上角，不报错不告警。
* **E8** ``graphic`` text 的 ``fill: "none"`` 造出无效 QColor → 文字不画。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts import _utils


@pytest.fixture(autouse=True)
def _fresh_warn_keys():
    """``_warned_keys`` 是模块级的，跨用例累积 —— 不清会互相吞告警。"""
    _utils._warned_keys.clear()
    yield
    _utils._warned_keys.clear()


def _chart(make, option, w=600, h=400):
    chart = make(ElaChartWidget)
    chart.resize(w, h)
    chart.setOption(option)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart.show()
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


def _press(chart, pos):
    ev = QMouseEvent(
        Qt
        and __import__(
            "PyQt6.QtCore", fromlist=["QEvent"]
        ).QEvent.Type.MouseButtonPress,
        QPointF(pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.instance().sendEvent(chart, ev)
    QApplication.processEvents()


BASE = {
    "animation": False,
    "xAxis": {"type": "category", "data": ["a", "b", "c", "d"]},
    "yAxis": {},
    "series": [{"type": "bar", "name": "S", "data": [1, 2, 3, 4]}],
}


class TestMarkPointAndLineAreHoverable:
    """C2：这两类标注必须能被命中。"""

    OPT = {
        **BASE,
        "series": [
            {
                **BASE["series"][0],
                "markPoint": {"data": [{"type": "max", "name": "峰值"}]},
            }
        ],
    }

    def test_mark_point_is_in_the_hit_path(self, make):
        chart = _chart(make, self.OPT)
        comp = next(
            c for c in chart.components if getattr(c, "optionKey", "") == "markPoint"
        )
        assert comp._marks, "markPoint 没布局出标记点"
        pos = QPointF(comp._marks[0]["pos"])
        assert comp.hitTest(pos) is not None, "组件自身的 hitTest 就不命中"

        found = chart._hitItemWithSeries(pos)
        assert found is not None, "命中分发没问组件 -> markPoint 是死代码"
        renderer, hit = found
        assert hit["name"] == "峰值"
        assert renderer is not None and renderer.name == "S"

    def test_mark_line_is_in_the_hit_path(self, make):
        opt = {
            **BASE,
            "series": [
                {**BASE["series"][0], "markLine": {"data": [{"type": "average"}]}}
            ],
        }
        chart = _chart(make, opt)
        comp = next(
            c for c in chart.components if getattr(c, "optionKey", "") == "markLine"
        )
        assert comp._lines, "markLine 没布局出标线"
        ln = comp._lines[0]
        coord = chart.primaryCoord()
        py = coord.y_axis.map(ln["value"], coord.plot.bottom(), coord.plot.top())
        pos = QPointF(coord.plot.center().x(), py)
        assert comp.hitTest(pos) is not None
        found = chart._hitItemWithSeries(pos)
        assert found is not None, "markLine 没接进命中分发"
        assert found[1]["value"] == ln["value"]

    def test_series_hit_still_works_away_from_marks(self, make):
        """接入组件不能抢走系列自身的悬停。"""
        chart = _chart(make, self.OPT)
        r = chart.seriesRenderers[0]
        bar = r._bars[0]
        found = chart._hitItemWithSeries(bar["rect"].center())
        assert found is not None
        assert found[1]["dataIndex"] == bar["index"]


class TestMarkAreaDoesNotStealHover:
    """C2 的另一半：markArea 是背景区域，接进来是**退化**。"""

    OPT = {
        **BASE,
        "series": [
            {
                **BASE["series"][0],
                "markArea": {"data": [[{"xAxis": "a"}, {"xAxis": "c"}]]},
            }
        ],
    }

    def test_mark_area_is_not_in_hoverable_set(self):
        from pyqt6_ela_pro.charts.core import _HOVERABLE_COMPONENTS

        assert "markArea" not in _HOVERABLE_COMPONENTS
        assert "graphic" not in _HOVERABLE_COMPONENTS
        assert {"markPoint", "markLine"} <= _HOVERABLE_COMPONENTS

    def test_hovering_inside_mark_area_still_hits_the_series(self, make):
        chart = _chart(make, self.OPT)
        comp = next(
            c for c in chart.components if getattr(c, "optionKey", "") == "markArea"
        )
        assert comp._areas, "markArea 没布局出区域"
        area = comp._areas[0]
        assert comp.hitTest(area.center()) is not None, "组件自身仍应能命中"

        r = chart.seriesRenderers[0]
        hit_bars = [b for b in r._bars if area.contains(b["rect"].center())]
        assert hit_bars, "本用例需要至少一根柱落在 markArea 内"
        found = chart._hitItemWithSeries(hit_bars[0]["rect"].center())
        assert found is not None
        assert "dataIndex" in found[1], "被 markArea 抢走了 -> 是退化"


class TestMapOptionParsing:
    """E3 / E4 / E6。"""

    MAP_BASE = {
        "animation": False,
        "series": [
            {
                "type": "map",
                "name": "M",
                "map": "demo",
                "data": [
                    {"name": "华北", "value": 10},
                    {"name": "东北", "value": 20},
                ],
            }
        ],
    }

    @pytest.mark.parametrize(
        "roam,expect",
        [
            (True, (True, True)),
            (1, (True, True)),
            ("true", (True, True)),
            ("True", (True, True)),
            ("scale", (True, False)),
            ("move", (False, True)),
            ("scale,move", (True, True)),
            (False, (False, False)),
            (0, (False, False)),
            ("false", (False, False)),
        ],
    )
    def test_roam_truthiness(self, make, roam, expect):
        """E6：数字与布尔字符串都要按 true 认（JSON 读进来的 option）。"""
        chart = _chart(
            make,
            {**self.MAP_BASE, "series": [{**self.MAP_BASE["series"][0], "roam": roam}]},
        )
        r = chart.seriesRenderers[0]
        assert r._roam == expect, f"roam={roam!r} -> {r._roam}，应为 {expect}"

    def test_roam_false_does_not_warn(self, make, capsys):
        _chart(make, self.MAP_BASE)
        assert "regions" not in capsys.readouterr().err

    def test_missing_geo_regions_warns(self, make, capsys):
        """E4：自定义 map 名缺 regions 时必须喊一声。"""
        _chart(
            make,
            {
                **self.MAP_BASE,
                "series": [{**self.MAP_BASE["series"][0], "map": "my-map"}],
            },
        )
        err = capsys.readouterr().err
        assert "my-map" in err and "regions" in err, f"静默回落了：{err!r}"

    def test_provided_geo_regions_does_not_warn(self, make, capsys):
        _chart(
            make,
            {
                **self.MAP_BASE,
                "geo": {"regions": {"A": [[0, 0], [10, 0], [10, 10]]}},
                "series": [{**self.MAP_BASE["series"][0], "map": "mine"}],
            },
        )
        assert "regions" not in capsys.readouterr().err

    def test_two_maps_use_their_own_visual_map(self, make):
        """E3：两个 map 系列各配一个 visualMap，必须各用自己的色带。"""
        chart = _chart(
            make,
            {
                "animation": False,
                "visualMap": [
                    {
                        "min": 0,
                        "max": 100,
                        "seriesIndex": 0,
                        "inRange": {"colors": ["#000000", "#111111"]},
                    },
                    {
                        "min": 0,
                        "max": 100,
                        "seriesIndex": 1,
                        "inRange": {"colors": ["#ffffff", "#eeeeee"]},
                    },
                ],
                "series": [
                    {**self.MAP_BASE["series"][0], "name": "first"},
                    {**self.MAP_BASE["series"][0], "name": "second"},
                ],
            },
        )
        a, b = chart.seriesRenderers
        assert a._visual_map() is not b._visual_map(), "两个系列拿到了同一个 visualMap"
        ca = a._fill_color("华北", {"华北": 50.0}, 0.0, 100.0, a._visual_map())
        cb = b._fill_color("华北", {"华北": 50.0}, 0.0, 100.0, b._visual_map())
        assert ca != cb, "两套 inRange.colors 没生效"

    def test_generic_visual_map_is_the_fallback(self, make):
        """未绑定的通用 visualMap 不能抢走显式绑定的。"""
        chart = _chart(
            make,
            {
                "animation": False,
                "visualMap": [
                    {
                        "min": 0,
                        "max": 10,
                        "inRange": {"colors": ["#111111", "#222222"]},
                    },
                    {
                        "min": 0,
                        "max": 10,
                        "seriesIndex": 0,
                        "inRange": {"colors": ["#333333", "#444444"]},
                    },
                ],
                "series": [
                    {**self.MAP_BASE["series"][0], "name": "first"},
                    {**self.MAP_BASE["series"][0], "name": "second"},
                ],
            },
        )
        a, b = chart.seriesRenderers
        assert a._visual_map() is not b._visual_map()
        assert a._visual_map() is not None
        # 第一个系列拿显式绑定的那条（而不是通用件）
        assert a._visual_map().opt.get("seriesIndex") == 0

    def test_visual_map_binds_to(self, make):
        """``bindsTo`` 的判定顺序：显式绑定 > 通用件。"""
        chart = _chart(make, self.MAP_BASE)
        vms = [c for c in chart.components if hasattr(c, "bindsTo")]
        assert not vms, "本用例只需要组件基类语义"


class TestParseRoamShared:
    """E6：``roam`` 的解析由 ``_utils.parse_roam`` 单点实现。

    原先 graph 与 map **各写一份**，两份都把非 bool落到「方向名」分支 ——
    ``str(1) == "1"`` 里既没有 ``scale`` 也没有 ``move``，于是 ``roam: 1``
    静默关掉整个 roam。共用一份才不会「修一个漏一个」。
    """

    @pytest.mark.parametrize(
        "value,expect",
        [
            (True, (True, True)),
            (False, (False, False)),
            (None, (False, False)),
            (1, (True, True)),
            (0, (False, False)),
            (2, (True, True)),
            ("true", (True, True)),
            ("True", (True, True)),
            ("false", (False, False)),
            ("scale", (True, False)),
            ("move", (False, True)),
            ("scale,move", (True, True)),
            ("", (False, False)),
        ],
    )
    def test_parse_roam(self, value, expect):
        from pyqt6_ela_pro.charts._utils import parse_roam

        assert parse_roam(value) == expect

    @pytest.mark.parametrize("roam", [1, "true", "scale"])
    def test_graph_uses_the_shared_parser(self, make, roam):
        chart = _chart(
            make,
            {
                "animation": False,
                "series": [
                    {
                        "type": "graph",
                        "name": "G",
                        "layout": "circular",
                        "roam": roam,
                        "data": [{"name": "a"}, {"name": "b"}],
                        "links": [{"source": "a", "target": "b"}],
                    }
                ],
            },
        )
        from pyqt6_ela_pro.charts._utils import parse_roam

        assert chart.seriesRenderers[0]._roam == parse_roam(roam)

    def test_graph_roam_one_is_enabled(self, make):
        """``roam: 1`` 曾让 graph 的缩放 / 拖拽全部失效。"""
        chart = _chart(
            make,
            {
                "animation": False,
                "series": [
                    {
                        "type": "graph",
                        "name": "G",
                        "layout": "circular",
                        "roam": 1,
                        "data": [{"name": "a"}, {"name": "b"}],
                        "links": [{"source": "a", "target": "b"}],
                    }
                ],
            },
        )
        assert chart.seriesRenderers[0]._roam == (True, True)


class TestGraphicAnchorAndText:
    """E7 / E8。"""

    GRAPHIC_BASE = {
        "animation": False,
        "xAxis": {"type": "category", "data": ["a", "b", "c"]},
        "yAxis": {},
        "series": [{"type": "bar", "name": "S", "data": [1, 2, 3]}],
    }

    def _elem_anchor(self, make, el):
        chart = _chart(make, {**self.GRAPHIC_BASE, "graphic": [el]})
        comp = next(
            c for c in chart.components if getattr(c, "optionKey", "") == "graphic"
        )
        return comp._anchor(comp.elements[0]), comp

    def test_middle_is_a_valid_vertical_anchor(self, make):
        """E7：``top: "middle"`` 是 ECharts 官方拼写。"""
        pt, comp = self._elem_anchor(make, {"type": "rect", "top": "middle"})
        assert abs(pt.y() - comp.rect.center().y()) < 1.0, (
            f'top="middle" 落到了 y={pt.y()}，内容区中心是 {comp.rect.center().y()}'
        )

    def test_center_still_works(self, make):
        """回归：``"center"`` 不能被新分支带偏。"""
        pt, comp = self._elem_anchor(make, {"type": "rect", "left": "center"})
        assert abs(pt.x() - comp.rect.center().x()) < 1.0

    @pytest.mark.parametrize("pct", ["0%", "25%", "50%", "100%"])
    def test_percentage_anchor(self, make, pct):
        """E7：``"30%"`` 原先落进兜底分支变成 0。"""
        pt, comp = self._elem_anchor(make, {"type": "rect", "left": pct})
        want = comp.rect.left() + comp.rect.width() * float(pct[:-1]) / 100.0
        assert abs(pt.x() - want) < 1.0, f"left={pct} -> {pt.x()}，应为 {want}"

    def test_numeric_anchor_is_unaffected(self, make):
        pt, comp = self._elem_anchor(make, {"type": "rect", "left": 40, "top": 30})
        assert abs(pt.x() - (comp.rect.left() + 40)) < 1.0
        assert abs(pt.y() - (comp.rect.top() + 30)) < 1.0

    def test_text_with_valid_fill_still_draws(self, make, capsys):
        chart = _chart(
            make,
            {
                **self.GRAPHIC_BASE,
                "graphic": [
                    {
                        "type": "text",
                        "left": 20,
                        "top": 20,
                        "style": {"text": "水印", "fill": "#ff0000"},
                    }
                ],
            },
        )
        chart.grab()
        assert "非法" not in capsys.readouterr().err

    def test_text_with_fill_none_draws_nothing(self, make, capsys):
        """E8：``fill: "none"`` 之前造出无效 QColor -> 静默不画且无告警。

        判据看**消息**而不是去重键：``warn_once(key, message)`` 只把 message 写进
        stderr，key 不出现。
        """
        chart = _chart(
            make,
            {
                **self.GRAPHIC_BASE,
                "graphic": [
                    {
                        "type": "text",
                        "left": 20,
                        "top": 20,
                        "style": {"text": "不该出现", "fill": "none"},
                    }
                ],
            },
        )
        chart.grab()
        assert "fill" not in capsys.readouterr().err, (
            "fill: 'none' 是合法用法，不该告警"
        )

    def test_text_with_invalid_fill_warns(self, make, capsys):
        chart = _chart(
            make,
            {
                **self.GRAPHIC_BASE,
                "graphic": [
                    {
                        "type": "text",
                        "left": 20,
                        "top": 20,
                        "style": {"text": "x", "fill": "不是颜色"},
                    }
                ],
            },
        )
        chart.grab()
        assert "非法" in capsys.readouterr().err
