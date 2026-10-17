"""bar / scatter 绘制路径的**外观快路径**守卫。

背景：这两个系列的绘制循环逐图元调 ``itemColor`` / ``itemOpacity`` /
``itemBorder`` / ``_bar_radius``，而每个方法都要 ``self.data()`` 取长度 +
下标 + ``itemStyleOf``。2 万柱单帧实测 ``data()`` 被调 30 万次（3 帧 ×
5 处 × 2 万），加上 ``palette()`` 每次新建 9 个 QColor，绘制慢到 463 ms。

两条快路径：

1. ``uniformItemStyle()`` —— 抽样判别「有没有 per-item itemStyle」，
   没有则一律按系列级取值（O(1)，不碰 data）；
2. ``palette()`` 缓存 —— 调色板只取决于「自定义色板 + 主题」。

**快路径必须与逐项路径结果完全一致**，否则会画出错的颜色。故这些用例的
重点是「两条路径等价」，而不是性能数字。
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts.core import ElaChartWidget
from pyqt6_ela_pro.charts.series_cartesian import (
    BarSeriesRenderer,
    ScatterSeriesRenderer,
)

pytestmark = pytest.mark.skipif(
    __import__("pyqt6_ela_pro.charts._downsample", fromlist=["np"]).np is None,
    reason="需要 numpy",
)


def _value_x(data, stype="line", **kw):
    s = {"type": stype, "name": "S", "data": data}
    s.update(kw)
    return {"xAxis": {"type": "value"}, "yAxis": {"type": "value"}, "series": [s]}


def _ready(chart, option, w=600, h=400):
    chart.resize(w, h)
    chart.setOption(option)
    chart.anim.setProgress(1.0)
    chart.show()
    for _ in range(3):
        QApplication.processEvents()
    chart._layout_all(force=True)
    return chart


def _r(chart, cls):
    for x in chart.seriesRenderers:
        if isinstance(x, cls):
            return x
    raise AssertionError(f"未找到 {cls.__name__}")


class TestUniformItemStyle:
    def test_uniform_detected_without_item_style(self, make):
        r = _r(
            _ready(
                make(ElaChartWidget),
                _value_x([float(i) for i in range(500)], "bar"),
            ),
            BarSeriesRenderer,
        )
        assert r.uniformItemStyle() == {}, "纯数值数据应判定为均匀"

    def test_per_item_detected(self, make):
        data = [{"value": float(i)} for i in range(500)]
        data[10]["itemStyle"] = {"color": "#ff0000"}
        r = _r(
            _ready(make(ElaChartWidget), _value_x(data, "bar")),
            BarSeriesRenderer,
        )
        assert r.uniformItemStyle() is None, "存在 per-item itemStyle 却判为均匀"

    def test_fast_and_slow_path_agree(self, make):
        """快路径与逐项路径必须给出一致的颜色 / 透明度 / 描边。"""
        data = [float(i % 40) for i in range(500)]
        # 纯数值数据走 bar 渲染器（bar 需要 rect 几何才有意义）
        opt = _value_x(data, "bar", itemStyle={"opacity": 0.7})
        r = _r(_ready(make(ElaChartWidget), opt), BarSeriesRenderer)
        assert r.uniformItemStyle() is not None, "本用例前提：应走快路径"
        resolved = r.uniformItemStyleResolved()
        assert resolved is not None
        for idx in (0, 7, 250, 499):
            assert r.itemOpacity(idx) == pytest.approx(resolved["opacity"])
            assert r.itemBorder(idx)[1] == pytest.approx(resolved["borderWidth"])
            assert r.itemColor(idx) == r.itemColor(0)

    def test_resolved_none_when_per_item(self, make):
        data = [{"value": float(i)} for i in range(300)]
        data[0]["itemStyle"] = {"color": "#00ff00"}
        r = _r(
            _ready(make(ElaChartWidget), _value_x(data, "bar")),
            BarSeriesRenderer,
        )
        assert r.uniformItemStyleResolved() is None, "有 per-item 时不应给统一外观"

    def test_cache_invalidated_on_data_change(self, make):
        """换数据后均匀性判定必须重算（否则新增的 per-item 样式被忽略）。"""
        chart = make(ElaChartWidget)
        _ready(chart, _value_x([float(i) for i in range(300)], "bar"))
        r = _r(chart, BarSeriesRenderer)
        assert r.uniformItemStyle() is not None
        mixed = [{"value": float(i)} for i in range(300)]
        mixed[5]["itemStyle"] = {"color": "#123456"}
        chart.setOption(_value_x(mixed, "bar"))
        r2 = _r(_ready(chart, _value_x(mixed, "bar")), BarSeriesRenderer)
        assert r2.uniformItemStyle() is None, "换数据后未重判均匀性"

    def test_resolved_parses_list_radius(self, make):
        r = _r(
            _ready(
                make(ElaChartWidget),
                _value_x(
                    [float(i) for i in range(300)],
                    "bar",
                    itemStyle={"borderRadius": [4, 8]},
                ),
            ),
            BarSeriesRenderer,
        )
        assert r.uniformItemStyleResolved()["borderRadius"] == 8.0

    def test_resolved_handles_bad_opacity(self, make):
        """非法 opacity 不得抛异常，回退 1.0。"""
        r = _r(
            _ready(
                make(ElaChartWidget),
                _value_x(
                    [float(i) for i in range(300)], "bar", itemStyle={"opacity": "坏值"}
                ),
            ),
            BarSeriesRenderer,
        )
        assert r.uniformItemStyleResolved()["opacity"] == 1.0


class TestPaletteCache:
    def test_palette_stable_across_calls(self, make):
        chart = _ready(make(ElaChartWidget), _value_x([1.0, 2.0, 3.0]))
        p1 = chart.palette()
        p2 = chart.palette()
        assert [c.name() for c in p1] == [c.name() for c in p2]
        assert len(p1) > 0

    def test_palette_returns_fresh_list(self, make):
        """返回**新 list** —— 调用方 setAlphaF 不得污染缓存。"""
        chart = _ready(make(ElaChartWidget), _value_x([1.0, 2.0, 3.0]))
        p1 = chart.palette()
        p1[0].setAlphaF(0.1)
        p2 = chart.palette()
        assert p2[0].alpha() == 255, "调色板被上一次调用的 setAlphaF 污染"

    def test_custom_palette_respected(self, make):
        chart = make(ElaChartWidget)
        opt = _value_x([1.0, 2.0, 3.0])
        opt["color"] = ["#112233", "#445566"]
        _ready(chart, opt)
        pal = chart.palette()
        assert [c.name() for c in pal] == ["#112233", "#445566"]

    def test_custom_palette_switch_invalidates(self, make):
        """换自定义色板后必须重算，不能命中旧缓存。"""
        chart = make(ElaChartWidget)
        _ready(chart, _value_x([1.0, 2.0, 3.0]))
        first = [c.name() for c in chart.palette()]
        opt = _value_x([1.0, 2.0, 3.0])
        opt["color"] = ["#aabbcc"]
        _ready(chart, opt)
        assert [c.name() for c in chart.palette()] == ["#aabbcc"] != first

    def test_color_for_series_uses_index(self, make):
        """``colorForSeries`` 走 ``_series_index``，颜色仍按序号取。"""
        chart = make(ElaChartWidget)
        opt = _value_x([1.0, 2.0, 3.0])
        opt["series"] = [
            {"type": "line", "name": "A", "data": [1.0, 2.0]},
            {"type": "line", "name": "B", "data": [2.0, 3.0]},
            {"type": "line", "name": "C", "data": [3.0, 4.0]},
        ]
        _ready(chart, opt)
        pal = chart.palette()
        rs = chart.seriesRenderers
        for i, r in enumerate(rs):
            assert r._series_index == i
            assert chart.colorForSeries(r).name() == pal[i % len(pal)].name()


class TestBarPaintFastPath:
    def test_renders_without_per_item_style(self, make):
        chart = _ready(
            make(ElaChartWidget), _value_x([float(i % 30) for i in range(2000)], "bar")
        )
        img = chart.grab().toImage()
        assert img.width() == 600 and img.height() == 400

    def test_renders_with_per_item_style(self, make):
        """per-item itemStyle 存在时走慢路径，也必须能画（快路径没吞掉它）。"""
        data = [{"value": float(i % 30)} for i in range(500)]
        for i in range(0, 500, 50):
            data[i]["itemStyle"] = {"color": "#ff0000", "borderRadius": 3}
        chart = _ready(make(ElaChartWidget), _value_x(data, "bar"))
        r = _r(chart, BarSeriesRenderer)
        assert r.uniformItemStyle() is None
        assert chart.grab().toImage().width() == 600

    def test_hover_still_works_with_fast_path(self, make):
        """快路径下 hover 高亮 / blur 淡化仍生效（不能被优化掉）。"""
        data = [float(i % 30) for i in range(300)]
        chart = _ready(make(ElaChartWidget), _value_x(data, "bar"))
        r = _r(chart, BarSeriesRenderer)
        assert r.uniformItemStyle() is not None
        assert r._bars
        # 直接调 paint 不应抛异常（hover 态由 chart.hoverInfo 驱动）
        from PyQt6.QtGui import QImage, QPainter

        img = QImage(600, 400, QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        try:
            r.paint(p, 1.0)
        finally:
            p.end()

    def test_border_and_radius_applied(self, make):
        """描边 + 圆角在快路径下仍被应用。"""
        opt = _value_x([float(i % 30) for i in range(300)], "bar")
        opt["series"][0]["itemStyle"] = {
            "borderColor": "#ff0000",
            "borderWidth": 2,
            "borderRadius": 4,
        }
        chart = _ready(make(ElaChartWidget), opt)
        r = _r(chart, BarSeriesRenderer)
        resolved = r.uniformItemStyleResolved()
        assert resolved["borderColor"] is not None
        assert resolved["borderColor"].name() == "#ff0000"
        assert resolved["borderWidth"] == 2.0
        assert resolved["borderRadius"] == 4.0


class TestScatterPaintFastPath:
    def test_renders_and_reports_style(self, make):
        pts = [[float(i), float(i % 40)] for i in range(2000)]
        chart = _ready(make(ElaChartWidget), _value_x(pts, "scatter"))
        r = _r(chart, ScatterSeriesRenderer)
        assert r.uniformItemStyle() == {}
        assert r.uniformItemStyleResolved() is not None
        assert chart.grab().toImage().width() == 600

    def test_per_item_style_path(self, make):
        pts = [
            {"value": [float(i), float(i % 20)], "itemStyle": {"color": "#00ff00"}}
            if i % 40 == 0
            else [float(i), float(i % 20)]
            for i in range(1000)
        ]
        chart = _ready(make(ElaChartWidget), _value_x(pts, "scatter"))
        r = _r(chart, ScatterSeriesRenderer)
        assert r.uniformItemStyle() is None
        assert chart.grab().toImage().width() == 600


class TestLineSymbolFastPath:
    def test_symbols_render(self, make):
        """折线的 ``showSymbol`` 路径也走同一快路径，须能画。"""
        opt = _value_x([float(i % 30) for i in range(500)])
        opt["series"][0]["showSymbol"] = True
        chart = _ready(make(ElaChartWidget), opt)
        assert chart.grab().toImage().width() == 600

    def test_symbols_per_item_style(self, make):
        data = [{"value": float(i % 30)} for i in range(500)]
        for i in range(0, 500, 60):
            data[i]["itemStyle"] = {"color": "#ff00ff"}
        opt = _value_x(data)
        opt["series"][0]["showSymbol"] = True
        chart = _ready(make(ElaChartWidget), opt)
        assert chart.grab().toImage().width() == 600


class TestColorIsolation:
    def test_hover_does_not_mutate_palette(self, make):
        """悬浮 / 淡化不得改坏全局调色板（历史上共享 QColor 实例）。"""
        chart = _ready(
            make(ElaChartWidget), _value_x([float(i % 30) for i in range(500)], "bar")
        )
        before = [c.alpha() for c in chart.palette()]
        r = _r(chart, BarSeriesRenderer)
        r._bars and chart.hoverInfo()
        # 模拟一次淡化绘制
        from PyQt6.QtGui import QImage, QPainter

        img = QImage(600, 400, QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        try:
            r.paint(p, 1.0)
        finally:
            p.end()
        assert [c.alpha() for c in chart.palette()] == before, "调色板被绘制污染"
        assert all(QColor(c).isValid() for c in chart.palette())
