"""持续动效（飞线亮点 / 涟漪）必须**自己动**，不靠鼠标。

回归 bug：``LinesSeriesRenderer`` / ``EffectScatterSeriesRenderer`` 的定时回调
推进了相位后只 ``chart.update()``，而相位不在 ``_series_layer_key`` 里 ——
系列层位图被原样贴回，用户看到的航迹是静止的；鼠标一放上去（hover 进缓存键）
就重画一帧，于是一路看过去成了「只有鼠标放上去时航迹才会动」。

修复是在每帧走 ``SeriesRenderer.requestSeriesRepaint()``（失效系列层 + 重绘）。
本文件**不依赖 numpy**（与 ``test_chart_series_layer_cache`` 的 skip 条件分开，
否则纯 Python 环境的用户会失去这条守卫）。
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts.core import ElaChartWidget


def _ready(chart, option, w=600, h=400):
    """渲染到稳态终态（必须 ``anim.stop()``，动画期缓存按设计被绕过）。"""
    chart.resize(w, h)
    chart.setOption(option)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart.show()
    for _ in range(3):
        QApplication.processEvents()
    chart.anim.stop()
    chart._layout_all(force=True)
    return chart


def _render(chart):
    """走与 ``paintEvent`` 相同的绘制路径（会填充 / 命中系列层缓存）。"""
    img = QImage(
        max(1, chart.width()),
        max(1, chart.height()),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    p = QPainter(img)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart._paint_content(p)
    finally:
        p.end()
    return img


def _lines_option():
    return {
        "xAxis": {"type": "value", "min": 0, "max": 10},
        "yAxis": {"type": "value", "min": 0, "max": 10},
        "series": [
            {
                "type": "lines",
                "name": "航路",
                "lineStyle": {"width": 1.6, "curveness": 0.25},
                "effect": {"show": True, "period": 4, "symbolSize": 5},
                "data": [
                    {"coords": [[1, 1], [4, 7]]},
                    {"coords": [[1, 3], [7, 8]]},
                    {"coords": [[3, 1], [8, 5]]},
                    {"coords": [[5, 2], [9, 9]]},
                    {"coords": [[2, 8], [8, 2]]},
                ],
            }
        ],
    }


def _ripple_option():
    return {
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [
            {
                "type": "effectScatter",
                "name": "涟漪",
                "data": [[1, 2], [5, 6]],
                "rippleEffect": {"period": 2},
            }
        ],
    }


class TestContinuousEffectRepaint:
    def test_lines_effect_tick_repaints_without_mouse(self, make):
        chart = _ready(make(ElaChartWidget), _lines_option())
        _render(chart)
        first = chart._series_pixmap_cache
        assert first is not None
        _render(chart)
        assert chart._series_pixmap_cache is first, "稳态下应命中缓存"

        renderer = chart.seriesRenderers[0]
        epoch = chart._geometry_epoch
        before = renderer._phase
        renderer._on_tick()
        assert renderer._phase != before, "定时回调未推进相位"
        assert chart._series_pixmap_cache is None, "相位推进后系列层未失效"
        assert chart._geometry_epoch == epoch, "持续动效不应触发全量重排"

        # 再推进几十步让亮点明显移位，确认画出来的位图真的变了
        for _ in range(20):
            renderer._on_tick()
        after = _render(chart)
        assert chart._series_pixmap_cache is not first, "系列层未重建"
        assert after != first, "亮点位置没有变化"

    def test_effect_scatter_tick_repaints_without_mouse(self, make):
        chart = _ready(make(ElaChartWidget), _ripple_option())
        _render(chart)
        first = chart._series_pixmap_cache
        assert first is not None
        _render(chart)
        assert chart._series_pixmap_cache is first, "稳态下应命中缓存"

        renderer = chart.seriesRenderers[0]
        before = renderer._phase
        renderer._tick()
        assert renderer._phase != before, "定时回调未推进相位"
        assert chart._series_pixmap_cache is None, "相位推进后系列层未失效"

        for _ in range(20):
            renderer._tick()
        after = _render(chart)
        assert chart._series_pixmap_cache is not first, "系列层未重建"
        assert after != first, "涟漪半径没有变化"

    @pytest.mark.parametrize("option", [_lines_option(), _ripple_option()])
    def test_request_series_repaint_keeps_geometry(self, make, option):
        """``requestSeriesRepaint`` 只失效位图，不动布局纪元（否则每帧全量重排）。"""
        chart = _ready(make(ElaChartWidget), option)
        renderer = chart.seriesRenderers[0]
        _render(chart)
        epoch = chart._geometry_epoch
        layout_key = chart._layout_key
        renderer.requestSeriesRepaint()
        assert chart._series_pixmap_cache is None
        assert chart._geometry_epoch == epoch
        assert chart._layout_key is layout_key
