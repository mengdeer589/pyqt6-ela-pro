"""C 组回归：命中测试。

两个 bug 都属「静默指错」——不抛异常、没告警，只是**指错对象**：

* **C1** 饼图 / 旭日图里占满 360° 的扇区（单个数据点、单扇区饼）**恒不命中**。
  根因是角度判据两端都取了 ``% 360``：``360 % 360 == 0``，于是 ``a0 == a1``
  → 判据退化成 ``0 <= a < 0``。用户看到的是「点不动的饼」。
* **C3** ``anim_t`` 是在**绘制期**施加的（柱高生长、折线插值、扇区扫掠、
  图节点向质心收缩），而 ``hitTest`` 拿的是 ``layout()`` 给的**终态**几何。
  于是动画进行中悬停 / 点击会命中「动画结束后才会到的位置」上的图元。
  修法是 base 类默认「动画期不命中」（绝不会指错），bar / line / scatter /
  pie / graph 复用各自 ``paint`` 的插值公式做到动画期也能命中。
"""

from __future__ import annotations

import math

import pytest
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QPolygonF
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts.series_hierarchy import _dist_to_polygon_edge


def _chart(make, option, w=600, h=400):
    """摆到稳态终态。

    **必须 ``anim.stop()`` 在 ``setProgress(1.0)`` 之前**：``setOption`` 会启动
    入场动画，只推进度不停止的话动画仍在跑 —— 几何每帧都变，本文件一半的用例
    直接失去意义。同一条约定见 ``test_chart_series_layer_cache.py::_ready``。
    """
    chart = make(ElaChartWidget)
    chart.resize(w, h)
    chart.setOption(option)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart.show()
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


def _at_progress(make, option, t, w=600, h=400):
    """停在动画进度 ``t``（0<t<1）的图表。"""
    chart = make(ElaChartWidget)
    chart.resize(w, h)
    chart.setOption(option)
    chart.anim.stop()
    chart.anim.setProgress(t)
    chart.show()
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


def _transitioning(make, first, second, t, w=600, h=400):
    """先渲染 ``first`` 再 ``setOption(second)``，停在进度 ``t``。

    **必须有 first 这一版**：``_animated_points`` 的旧→新插值依赖
    ``prev_data``，而它只在**第二次** setOption 时才被注入。首帧渲染时
    ``prev_data is None`` → 插值函数直接返回终态点，于是「动画期命中」
    与「终态命中」结果完全相同 —— 那种用例对本次修复毫无鉴别力。
    """
    chart = make(ElaChartWidget)
    chart.resize(w, h)
    chart.setOption(first)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart.show()
    chart._layout_all(force=True)
    QApplication.processEvents()

    chart.setOption(second)
    chart.anim.stop()
    chart.anim.setProgress(t)
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


def _scan(renderer, w=600, h=400, step=6):
    """扫描出若干个真能命中的点（不猜几何约定，命中才算数）。"""
    hits = []
    for gx in range(4, w, step):
        for gy in range(4, h, step):
            p = QPointF(float(gx), float(gy))
            if renderer.hitTest(p):
                hits.append(p)
    return hits


def _toward(a, b, f):
    """从 ``a`` 向 ``b`` 走 ``f``（0..1）得到的点。"""
    return QPointF(a.x() + (b.x() - a.x()) * f, a.y() + (b.y() - a.y()) * f)


class TestFullCircleSectorIsHittable:
    """C1：整圆扇区不能因为 ``% 360`` 而恒不命中。"""

    SINGLE = {
        "animation": False,
        "series": [
            {"type": "pie", "name": "P", "data": [{"name": "only", "value": 42}]}
        ],
    }

    def test_single_slice_pie_hits_everywhere(self, make):
        chart = _chart(make, self.SINGLE)
        r = chart.seriesRenderers[0]
        center = r._center
        rmid = (r._r_in + r._r_out) / 2.0
        # 8 个方向都必须命中
        for deg in range(0, 360, 45):
            rad = math.radians(deg)
            pt = QPointF(
                center.x() + rmid * math.cos(rad), center.y() + rmid * math.sin(rad)
            )
            hit = r.hitTest(pt)
            assert hit is not None, f"{deg}° 未命中 —— 整圆扇区被判成空区间"
            assert hit["name"] == "only"
            assert hit["value"] == 42

    def test_single_node_sunburst_hits_everywhere(self, make):
        chart = _chart(
            make,
            {
                "animation": False,
                "series": [
                    {"type": "sunburst", "data": [{"name": "only", "value": 42}]}
                ],
            },
        )
        r = chart.seriesRenderers[0]
        found = _scan(r)
        assert len(found) > 50, f"整圆旭日图扇区只命中 {len(found)} 个采样点"

    def test_normal_pie_still_hits(self, make):
        """回归：多扇区饼图的正常命中不能被整圆特判带坏。"""
        chart = _chart(
            make,
            {
                "animation": False,
                "series": [
                    {
                        "type": "pie",
                        "name": "P",
                        "data": [
                            {"name": "a", "value": 1},
                            {"name": "b", "value": 2},
                            {"name": "c", "value": 3},
                        ],
                    }
                ],
            },
        )
        r = chart.seriesRenderers[0]
        names = {r.hitTest(p)["name"] for p in _scan(r)}
        assert names == {"a", "b", "c"}, f"只命中了 {names}"

    def test_pie_does_not_hit_outside_the_ring(self, make):
        """整圆特判不能放宽半径判据。"""
        chart = _chart(make, self.SINGLE)
        r = chart.seriesRenderers[0]
        assert r.hitTest(QPointF(r._center.x() + r._r_out + 40, r._center.y())) is None


class TestHitTestFollowsAnimationProgress:
    """C3：命中几何必须跟着 ``anim_t`` 走。"""

    BAR = {
        "animation": True,
        "xAxis": {"type": "category", "data": ["a", "b", "c", "d"]},
        "yAxis": {},
        "series": [{"type": "bar", "name": "S", "data": [4, 3, 2, 1]}],
    }

    def test_bar_hit_is_empty_before_first_paint(self, make):
        """没 paint 过时 ``_anim_t`` 是终态，不能据此误判。"""
        chart = make(ElaChartWidget)
        chart.resize(600, 400)
        chart.setOption(self.BAR)
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        chart._layout_all(force=True)
        QApplication.processEvents()
        assert chart.seriesRenderers[0]._anim_t == 1.0

    def test_bar_hit_matches_painted_rect_at_progress(self, make):
        """动画中途：命中框必须等于同一进度下 ``paint`` 用的矩形。"""
        chart = _at_progress(make, self.BAR, 0.25)
        r = chart.seriesRenderers[0]
        coord = chart.primaryCoord()
        bar = r._bars[-1]
        painted = r._animated_rect(bar, r._anim_t, coord)
        hit = r.hitTest(painted.center())
        assert hit is not None, "动画中画出来的那根柱命中不到"
        assert hit["dataIndex"] == bar["index"]

    def test_bar_hit_is_consistent_with_painted_rects(self, make):
        """不变式：动画期命中的那根柱，其**画出时的矩形**必须含命中点。

        这比「某个高度必须不命中」更本质 —— 不依赖对柱高方向的猜测，且能
        直接抓住「用终态矩形命中」这个 bug：终态矩形更大，会在柱还没长到
        的地方命中，而那里的动画矩形不含该点。
        """
        chart = _at_progress(make, self.BAR, 0.25)
        r = chart.seriesRenderers[0]
        coord = chart.primaryCoord()
        painted = [r._animated_rect(b, r._anim_t, coord) for b in r._bars]
        final = [b["rect"] for b in r._bars]
        assert any(f.height() - p.height() > 1.0 for p, f in zip(painted, final)), (
            "本用例需要动画确实缩短了柱高"
        )

        checked = 0
        for bx in range(10, 590, 11):
            for by in range(10, 390, 11):
                pt = QPointF(float(bx), float(by))
                hit = r.hitTest(pt)
                if hit is None:
                    continue
                idx = hit["dataIndex"]
                rect = next(p for p, b in zip(painted, r._bars) if b["index"] == idx)
                assert rect.adjusted(-2, -2, 2, 2).contains(pt), (
                    f"命中 dataIndex={idx}，但该柱在进度 {r._anim_t} 下画出的"
                    f"矩形 {rect} 不含命中点 {pt} —— 用的是终态几何"
                )
                checked += 1
        assert checked > 0, "动画期一个都没命中，用例失去意义"

    def test_line_hit_uses_animated_points(self, make):
        """折线：动画期命中用**插值后**的点，而不是终态点。"""
        first = {
            "animation": True,
            "xAxis": {"type": "category", "data": ["a", "b", "c"]},
            "yAxis": {},
            "series": [{"type": "line", "name": "L", "data": [1, 1, 1]}],
        }
        second = {
            "series": [{"type": "line", "name": "L", "data": [1, 9, 1]}],
        }
        chart = _transitioning(make, first, second, 0.25)
        r = chart.seriesRenderers[0]
        assert r._anim_t < 1.0

        moved = r._animated_points(r._anim_t)[1]
        final = r._points[1]
        assert moved is not None and moved.y() != final.y(), (
            "插值前后重合，本用例对修复没有鉴别力"
        )
        # 插值位置命中
        hit = r.hitTest(moved)
        assert hit is not None, "动画中画出来的折线点命中不到"
        assert hit["dataIndex"] == 1
        # 终态位置此刻还没飞到，不该命中（命中半径 10px，位移远大于它）
        assert r.hitTest(final) is None, "命中用的是终态点"

    def test_scatter_hit_radius_follows_scale(self, make):
        """散点：动画只缩半径，命中半径要跟着缩。"""
        opt = {
            "animation": True,
            "xAxis": {"type": "value"},
            "yAxis": {},
            "series": [
                {
                    "type": "scatter",
                    "name": "S",
                    "symbolSize": 30,
                    "data": [[1, 1], [2, 2], [3, 3]],
                }
            ],
        }
        chart = _at_progress(make, opt, 0.1)
        r = chart.seriesRenderers[0]
        dot = r._dots[0]
        # 动画中点半径 = r * 0.1 = 1.5px；命中判据下界是 max(1.5, 4)+3 = 7
        assert r.hitTest(QPointF(dot["pt"].x() + 6, dot["pt"].y())) is not None
        # 远在半径之外必须不命中
        assert r.hitTest(QPointF(dot["pt"].x() + 40, dot["pt"].y())) is None

    def test_pie_hit_uses_swept_span(self, make):
        """饼图：入场扫掠到一半时，尚未扫到的角度不该命中。"""
        opt = {
            "animation": True,
            "series": [
                {"type": "pie", "name": "P", "data": [{"name": "x", "value": 1}]}
            ],
        }
        chart = _at_progress(make, opt, 0.3, w=400, h=400)
        r = chart.seriesRenderers[0]
        sector = r._sectors[0]
        # 起始角处（在已扫到的区间内）应命中
        rad = math.radians(float(sector["a0"]) + 1.0)
        rmid = (sector["r0"] + sector["r1"]) / 2.0
        assert (
            r.hitTest(
                QPointF(
                    r._center.x() + rmid * math.cos(rad),
                    r._center.y() + rmid * math.sin(rad),
                )
            )
            is not None
        )

    def test_graph_hit_is_disabled_while_animating_without_math(self, make):
        """graph 已有动画期命中公式；这里钉住「命中的是画出来的点」。"""
        opt = {
            "animation": True,
            "series": [
                {
                    "type": "graph",
                    "name": "G",
                    "layout": "force",
                    "data": [
                        {"name": "a", "x": 0.2, "y": 0.2},
                        {"name": "b", "x": 0.8, "y": 0.8},
                    ],
                    "links": [{"source": "a", "target": "b"}],
                }
            ],
        }
        chart = _at_progress(make, opt, 0.3)
        r = chart.seriesRenderers[0]
        pts = r._animated_points(r._anim_t)
        assert r.hitTest(pts[0]) is not None


class TestBaseRendererRefusesHitDuringAnimation:
    """C3 的兜底：没实现动画期命中的渲染器宁可「不命中」，也不指错。"""

    RADAR = {
        "animation": True,
        "radar": {
            "indicator": [
                {"name": "a", "max": 10},
                {"name": "b", "max": 10},
                {"name": "c", "max": 10},
            ]
        },
        "series": [{"type": "radar", "name": "R", "data": [{"value": [8, 8, 8]}]}],
    }

    def test_radar_hit_uses_animated_polygon(self, make):
        """radar 也是「从中心张开」，命中须用插值后的多边形。

        判据点取「圆心 → 顶点」的 0.85 处：它在**终态**多边形内、在
        ``anim_t=0.3`` 收缩后的多边形外 —— 正好落在两者之间，用它就能区分
        「命中用了哪份几何」。
        """
        chart = _at_progress(make, self.RADAR, 0.3)
        r = chart.seriesRenderers[0]
        assert r._anim_t < 1.0
        vertex = r._polys[0]["points"][0]
        center = r._center
        probe = _toward(center, vertex, 0.85)
        # 该点只在终态几何里，动画中还没张开到 -> 不该命中
        assert r.hitTest(probe) is None
        # 同一方向 0.15 处（动画多边形内）-> 命中
        assert r.hitTest(_toward(center, vertex, 0.15)) is not None

    def test_radar_still_hits_after_animation(self, make):
        """不能把「动画后也不命中」一起带坏。"""
        chart = _at_progress(make, self.RADAR, 1.0)
        r = chart.seriesRenderers[0]
        assert r._anim_t == 1.0
        vertex = r._polys[0]["points"][0]
        assert r.hitTest(_toward(r._center, vertex, 0.85)) is not None


class TestRadarTooltipDistinguishesSources:
    """雷达图 tooltip 必须能区分不同数据源。

    两条回归：

    ① **命中**：多个多边形重叠时按「边界离光标最近」选，不再让后画的那条通吃。
       实测贴着「预算」的顶点（离它 0.3px、离「实际」18.5px）旧实现报「实际」；
    ② **展示**：标题 = 数据项名、逐维度一行、圆点用**数据项色**（旧实现用系列色，
       两条多边形同一个颜色，等于没区分）。
    """

    OPT = {
        "animation": False,
        "series": [
            {
                "type": "radar",
                "name": "能力",
                "indicator": [
                    {"name": "销售", "max": 6500},
                    {"name": "管理", "max": 16000},
                    {"name": "技术", "max": 30000},
                    {"name": "客服", "max": 38000},
                    {"name": "研发", "max": 52000},
                    {"name": "市场", "max": 25000},
                ],
                "data": [
                    {
                        "name": "预算",
                        "value": [4200, 3000, 20000, 35000, 50000, 18000],
                    },
                    {
                        "name": "实际",
                        "value": [5000, 14000, 28000, 26000, 42000, 21000],
                    },
                ],
            }
        ],
    }

    def _renderer(self, make):
        return _chart(make, self.OPT).seriesRenderers[0]

    def test_overlap_picks_nearest_boundary(self, make):
        """回归：贴着哪条多边形的边线，就命中哪条数据。"""
        r = self._renderer(make)
        budget, actual = r._polys[0], r._polys[1]
        vertex = budget["points"][0]
        probe = QPointF(vertex.x(), vertex.y() + 1.0)
        # 前提（用例的鉴别力）：该点同时在两条多边形内，且离「预算」边界更近。
        # 旧实现按 z 序取最上层（「实际」后画）→ 必然报「实际」。
        assert QPolygonF(actual["points"]).containsPoint(
            probe, Qt.FillRule.OddEvenFill
        ), "该点不在「实际」内 —— 旧实现也会命中「预算」，用例没有鉴别力"
        assert _dist_to_polygon_edge(probe, budget["points"]) < _dist_to_polygon_edge(
            probe, actual["points"]
        )
        hit = r.hitTest(probe)
        assert hit is not None
        assert hit["name"] == "预算"

    def test_scan_reaches_both_sources(self, make):
        """两个数据源都要能被鼠标单独命中（旧实现里后画的那条通吃重叠区）。"""
        r = self._renderer(make)
        seen = set()
        for gx in range(4, 600, 8):
            for gy in range(4, 400, 8):
                hit = r.hitTest(QPointF(float(gx), float(gy)))
                if hit:
                    seen.add(hit["name"])
        assert seen == {"预算", "实际"}

    def test_hit_carries_item_color_and_indicator_rows(self, make):
        r = self._renderer(make)
        first = r._hit_info(0, r._polys[0])
        second = r._hit_info(1, r._polys[1])
        assert first["color"].name() == r._polys[0]["color"].name()
        assert second["color"].name() == r._polys[1]["color"].name()
        assert first["color"].name() != second["color"].name()
        assert first["title"] == "预算"
        assert first["rows"][0] == ("销售", 4200.0)

    def test_tooltip_shows_header_and_rows(self, make):
        chart = _chart(make, self.OPT)
        r = chart.seriesRenderers[0]
        vertex = r._polys[0]["points"][0]
        chart._update_tooltip(QPointF(vertex.x(), vertex.y() + 1.0))
        lines = chart.tooltip._lines
        assert lines[0] == (None, "", "预算")
        assert lines[1][0].name() == r._polys[0]["color"].name()
        assert lines[1][1:] == ("销售", "4200")
        assert len(lines) == 1 + len(r._indicators)
        # 多行浮层的绘制路径也要真跑一遍（标题 + 逐维度行 + 圆点）
        chart.grab()
        assert chart.tooltip.active is True

    def test_formatter_still_wins_over_rows(self, make):
        """``tooltip.formatter`` 的输出优先于逐维度默认行。"""
        option = dict(self.OPT)
        option["tooltip"] = {"formatter": "自定义文案"}
        chart = _chart(make, option)
        r = chart.seriesRenderers[0]
        hit = r._hit_info(0, r._polys[0])
        lines = chart.tooltip.buildLines(hit, hit["color"], r.name)
        assert any("自定义文案" in line[2] for line in lines)
        assert all("销售" not in line[2] for line in lines)

    def test_event_params_use_item_color(self, make):
        chart = _chart(make, self.OPT)
        r = chart.seriesRenderers[0]
        hit = r._hit_info(1, r._polys[1])
        params = chart._make_item_params(r, hit, "click")
        assert params["color"] == hit["color"].name()


class TestPieOptionParsing:
    """E1 / E2：饼图 option 的两处静默失效。"""

    BASE = {
        "animation": False,
        "series": [
            {
                "type": "pie",
                "name": "P",
                "data": [
                    {"name": "a", "value": 5},
                    {"name": "b", "value": 3},
                    {"name": "c", "value": 2},
                ],
            }
        ],
    }

    @pytest.mark.parametrize(
        "center",
        [["50%", "50%"], "50%"],
        ids=["pair", "percent-string"],
    )
    def test_center_accepts_percent_string(self, make, center):
        """E1：``center`` 传字符串不能按字符下标取值（``"50%"[0] == "5"``）。

        原症状：圆心跑到绘图区左上角 5px 处，用户看到「饼心不见了」。
        """
        chart = _chart(
            make,
            {**self.BASE, "series": [{**self.BASE["series"][0], "center": center}]},
        )
        r = chart.seriesRenderers[0]
        cx, cy = r._center.x(), r._center.y()
        # 判据只用控件尺寸：饼图没有 cartesian 坐标系，``primaryCoord()``
        # 是 None，不该让用例依赖内部绘图区变量
        assert 0 < cx < chart.width(), f"圆心 x={cx} 不在控件内"
        assert 0 < cy < chart.height(), f"圆心 y={cy} 不在控件内"
        assert not (cx < 10 and cy < 10), (
            f"圆心贴在左上角 {cx},{cy} —— 字符串被按字符下标取值了"
        )

    def test_center_accepts_bare_number(self, make):
        """裸数字此前让 ``len(0.5)`` 抛 ``TypeError``，**整张饼图消失**
        （异常被 ``warn_once`` 吞掉，只剩一行控制台告警）。

        数值语义与 ECharts 一致（按**像素**解释，``0.5`` 就是 0.5px 而不是
        50%），所以这里只钉「不崩且仍出图」。
        """
        chart = _chart(
            make,
            {**self.BASE, "series": [{**self.BASE["series"][0], "center": 0.5}]},
        )
        r = chart.seriesRenderers[0]
        assert len(r._sectors) == 3, "饼图整个没画出来"

    def test_center_offset_pair_still_works(self, make):
        """回归：二元组的语义不能被字符串分支带偏（x 靠左、y 靠下）。"""
        chart = _chart(
            make,
            {
                **self.BASE,
                "series": [{**self.BASE["series"][0], "center": ["30%", "70%"]}],
            },
        )
        r = chart.seriesRenderers[0]
        cx, cy = r._center.x(), r._center.y()
        assert cx < chart.width() * 0.45, f"x={cx} 不该落在 30% 附近（偏右了）"
        assert cy > chart.height() * 0.55, f"y={cy} 不该落在 70% 附近（偏上了）"

    def test_pad_angle_survives_transition_animation(self, make):
        """E2：``padAngle`` / ``minAngle`` 在过渡动画里同样生效。

        原症状：动画播完的那一帧扇区突然贴合、小值扇区缩回 0 角 ——
        视觉上是「饼图在动画结束时跳了一下」。

        **必须 ``animation: True``**：动画关闭时 core 会**跳过旧数据快照**
        （百万级物化纯浪费），``prev_data`` 恒为 None，插值路径压根不会走。
        """
        first = {
            "animation": True,
            "series": [{**self.BASE["series"][0], "padAngle": 8, "minAngle": 10}],
        }
        second = {
            "animation": True,
            "series": [
                {
                    "type": "pie",
                    "name": "P",
                    "padAngle": 8,
                    "minAngle": 10,
                    "data": [
                        {"name": "a", "value": 9},
                        {"name": "b", "value": 4},
                        {"name": "c", "value": 1},
                    ],
                }
            ],
        }
        chart = _transitioning(make, first, second, 1.0)
        r = chart.seriesRenderers[0]
        # **判据必须打在过渡动画重建出来的那份扇区上**（``paint`` 实际用的），
        # 而不是 ``_sectors`` —— 后者是 ``layout()`` 的终态几何，它一直带着
        # minAngle / padAngle，断言它永远通过，抓不到这个 bug。
        drawn = r._animated_sectors(1.0)
        assert drawn is not r._sectors, "过渡动画没走重建路径，用例失去意义"
        gaps = [drawn[i + 1]["a0"] - drawn[i]["a1"] for i in range(len(drawn) - 1)]
        assert all(g > 1.0 for g in gaps), f"padAngle 丢了：扇区间隙 {gaps}"
        assert min(s["a1"] - s["a0"] for s in drawn) > 1.0, (
            "minAngle 丢了：存在 0 度扇区"
        )


class TestAlphaOnlyAnimationKeepsHitWorking:
    """``anim_t`` 只改 alpha、不动几何的系列：动画期命中本就正确，不该被拦。"""

    @pytest.mark.parametrize(
        "option",
        [
            {
                "animation": True,
                "series": [
                    {
                        "type": "treemap",
                        "name": "M",
                        "data": [
                            {
                                "name": "r",
                                "value": 10,
                                "children": [{"name": "c", "value": 5}],
                            }
                        ],
                    }
                ],
            },
            {
                "animation": True,
                "series": [
                    {
                        "type": "sankey",
                        "name": "S",
                        "data": [{"name": "a"}, {"name": "b"}],
                        "links": [{"source": "a", "target": "b", "value": 5}],
                    }
                ],
            },
        ],
        ids=["treemap", "sankey"],
    )
    def test_hit_works_mid_animation(self, make, option):
        """treemap / sankey 的 ``paint`` 只用 ``anim_t`` 调 alpha
        （``60 + 195 * anim_t`` / ``255 * anim_t``），图元位置是静态的 ——
        动画期用终态几何命中完全正确，不该被「动画期不命中」误伤。

        这条是**反向**约束：base 默认的保守策略不能变成「所有系列动画期
        都不可交互」，否则实时刷新的图表（每次 setOption 都重起动画）会
        永远悬停不到东西。
        """
        chart = _at_progress(make, option, 0.4)
        r = chart.seriesRenderers[0]
        assert r._anim_t < 1.0
        assert _scan(r, step=10), f"{type(r).__name__} 动画期完全不可命中"
