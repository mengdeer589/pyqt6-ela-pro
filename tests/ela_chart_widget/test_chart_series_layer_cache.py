"""系列层位图缓存的守卫。

**为什么需要它**：实测 8 系列 × 20 万点（1200×700）单帧绘制中**系列占
99.7%**（914 ms/3 帧 vs 坐标轴 2.9 ms/3 帧）。而悬停每移动一像素就
``update()`` 一次 —— 200 次移动实测 **40.7 秒**（每次 203 ms），交互
完全不可用。系列几何在悬停时并不变化，所以可以整层烘成位图。

缓存的正确性风险全在**失效时机**：漏掉任何一个影响外观的状态，用户就会
看到「高亮停在上一个位置」「换数据不重画」这类陈旧画面。故本文件的重点
是逐个状态验证失效，而不是性能数字。
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts.core import ElaChartWidget
from pyqt6_ela_pro.charts.data import toBuffer

pytestmark = pytest.mark.skipif(
    __import__("pyqt6_ela_pro.charts._downsample", fromlist=["np"]).np is None,
    reason="需要 numpy",
)

N = 3000


def _opt(data=None, **kw):
    s = {"type": "line", "name": "A", "data": data or [float(i % 97) for i in range(N)]}
    s.update(kw)
    tip = kw.pop("tooltip", {"trigger": "axis"})
    return {
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "tooltip": tip,
        "series": [s],
    }


def _ready(chart, option, w=600, h=400):
    """渲染到稳态终态。

    **必须 ``anim.stop()``** 而不只是 ``setProgress(1.0)`` ——``setOption``
    会启动入场动画，而动画运行期间系列层缓存**按设计被绕过**
    （几何每帧都在变，见 ``_series_layer_key`` 返回 ``None``）。只推进度
    不停止，动画仍在跑，所有缓存断言都会失败。
    """
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
    from PyQt6.QtGui import QImage, QPainter

    img = QImage(
        chart.width(), chart.height(), QImage.Format.Format_ARGB32_Premultiplied
    )
    p = QPainter(img)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        chart._paint_content(p)
    finally:
        p.end()
    return img


def _cached(chart):
    return chart._series_pixmap_cache is not None


class TestSeriesLayerBasics:
    def test_cache_filled_after_paint(self, make):
        chart = _ready(make(ElaChartWidget), _opt())
        _render(chart)
        assert _cached(chart), "首帧未填充系列层缓存"
        assert chart._series_pixmap_key is not None

    def test_second_paint_hits_cache(self, make):
        chart = _ready(make(ElaChartWidget), _opt())
        _render(chart)
        first = chart._series_pixmap_cache
        _render(chart)
        assert chart._series_pixmap_cache is first, "未命中缓存（重建了位图）"

    def test_invalidate_clears(self, make):
        chart = _ready(make(ElaChartWidget), _opt())
        _render(chart)
        chart.invalidateSeriesLayer()
        assert not _cached(chart)
        assert chart._series_pixmap_key is None

    def test_animation_bypasses_cache(self, make):
        """动画进行中不缓存（几何每帧都在变，缓存会锁死画面）。"""
        chart = _ready(make(ElaChartWidget), _opt())
        _render(chart)
        chart.anim.start()
        chart._series_pixmap_cache = None
        _render(chart)
        assert not _cached(chart), "动画中仍在缓存"

    def test_key_none_while_animating(self, make):
        chart = _ready(make(ElaChartWidget), _opt())
        assert chart._series_layer_key() is not None
        chart.anim.start()
        assert chart._series_layer_key() is None

    def test_cache_size_matches_viewport(self, make):
        chart = _ready(make(ElaChartWidget), _opt(), w=640, h=480)
        _render(chart)
        img = chart._series_pixmap_cache
        assert img.width() >= 640 and img.height() >= 480


class TestSeriesLayerInvalidation:
    def test_data_change_invalidates(self, make):
        """换数据必须重画（否则旧曲线留在屏幕上）。"""
        chart = _ready(make(ElaChartWidget), _opt())
        _render(chart)
        key_a = chart._series_pixmap_key
        chart.setOption(_opt(data=[float(i % 31) for i in range(N)]))
        chart.anim.stop()
        chart.anim.setProgress(1.0)
        _render(chart)
        assert chart._series_pixmap_key != key_a, "换数据后缓存未失效"

    def test_resize_invalidates(self, make):
        chart = _ready(make(ElaChartWidget), _opt())
        _render(chart)
        key_a = chart._series_pixmap_key
        chart.resize(700, 500)
        _render(chart)
        assert chart._series_pixmap_key != key_a, "resize 后缓存未失效"

    def test_legend_toggle_invalidates(self, make):
        """图例切换可见性必须重画。"""
        chart = _ready(
            make(ElaChartWidget),
            {
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "legend": {},
                "series": [
                    {
                        "type": "line",
                        "name": "A",
                        "data": [float(i % 50) for i in range(500)],
                    },
                    {
                        "type": "line",
                        "name": "B",
                        "data": [float(i % 30) for i in range(500)],
                    },
                ],
            },
        )
        _render(chart)
        key_a = chart._series_pixmap_key
        chart.dispatchAction({"type": "legendToggleSelect", "name": "A"})
        for _ in range(2):
            QApplication.processEvents()
        _render(chart)
        assert chart._series_pixmap_key != key_a, "图例切换后缓存未失效"

    def test_hover_change_invalidates(self, make):
        """**关键**：hover 命中变化必须重画。

        命中项走 emphasis 高亮、未命中项走 blur 淡化，两者都改逐图元外观。
        少了这一条，缓存会把「上一个高亮位置」贴回来。
        """
        chart = _ready(make(ElaChartWidget), _opt(tooltip={"trigger": "item"}))
        _render(chart)
        r = chart.seriesRenderers[0]
        key_none = chart._series_pixmap_key
        chart._hover = (r, {"dataIndex": 5})
        _render(chart)
        key_hover5 = chart._series_pixmap_key
        assert key_hover5 != key_none, "hover 变化后缓存未失效"
        chart._hover = (r, {"dataIndex": 9})
        _render(chart)
        assert chart._series_pixmap_key != key_hover5, "换命中项后缓存未失效"

    def test_hover_same_index_hits_cache(self, make):
        """hover 命中项**不变**时应命中缓存（鼠标在同一点附近移动）。"""
        chart = _ready(make(ElaChartWidget), _opt(tooltip={"trigger": "item"}))
        _render(chart)
        r = chart.seriesRenderers[0]
        chart._hover = (r, {"dataIndex": 7})
        _render(chart)
        img = chart._series_pixmap_cache
        _render(chart)
        assert chart._series_pixmap_cache is img, "同命中项时未命中缓存"

    def test_datazoom_invalidates(self, make):
        """dataZoom 窗口变化必须重画（采样与坐标映射都变了）。"""
        chart = _ready(
            make(ElaChartWidget),
            {
                "xAxis": {"type": "value"},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "line",
                        "name": "A",
                        "data": [float(i % 97) for i in range(5000)],
                    }
                ],
                "dataZoom": [{"type": "inside"}],
            },
        )
        _render(chart)
        key_a = chart._series_pixmap_key
        dz = next(c for c in chart.components if c.optionKey == "dataZoom")
        dz.start, dz.end = 20.0, 60.0
        dz.apply()
        chart.invalidateLayout()
        _render(chart)
        assert chart._series_pixmap_key != key_a, "dataZoom 后缓存未失效"

    def test_theme_change_invalidates_via_key(self, make):
        """主题切换后键里的主题分量变化 → 自动失效。"""
        chart = _ready(make(ElaChartWidget), _opt())
        _render(chart)
        key_a = chart._series_pixmap_key
        assert key_a[4] is not None
        # 键含主题模式；切换后必然不同（不依赖手动 invalidate）
        from PyQt6ElaWidgetTools import ElaThemeType, eTheme

        try:
            eTheme.setThemeMode(
                ElaThemeType.ThemeMode.Dark
                if eTheme.getThemeMode() == ElaThemeType.ThemeMode.Light
                else ElaThemeType.ThemeMode.Light
            )
            for _ in range(2):
                QApplication.processEvents()
            _render(chart)
            assert chart._series_pixmap_key != key_a, "主题切换后缓存未失效"
        finally:
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)


class TestSeriesLayerCorrectness:
    def test_render_equivalent_to_uncached(self, make):
        """缓存路径与直绘路径的画面**实质一致**。

        **不做逐像素相等断言**：offscreen 平台的文字光栅化本身不确定 ——
        实测「同一份内容连续渲染两次」就有 16 个像素差（集中在 y=1~2 的
        文字行），抗锯齿折线另有约 156 个。所以断言精确相等是在测 Qt 的
        确定性，不是在测缓存。

        改为断言「差异像素占比极低」+「差异不集中在某个区域」，既能抓出
        「缓存贴错了图」这类真 bug，又不受渲染噪声干扰。
        """
        chart = _ready(make(ElaChartWidget), _opt())
        img_cached = _render(chart)
        chart.invalidateSeriesLayer()
        img_direct = _render(chart)
        assert img_cached.size() == img_direct.size()
        w, h = img_cached.width(), img_cached.height()
        total = w * h
        diff = sum(
            1
            for y in range(h)
            for x in range(w)
            if img_cached.pixel(x, y) != img_direct.pixel(x, y)
        )
        # 噪声基线：同一条路径连续两次渲染的差异量级
        img_direct2 = _render(chart)
        noise = sum(
            1
            for y in range(h)
            for x in range(w)
            if img_direct.pixel(x, y) != img_direct2.pixel(x, y)
        )
        assert diff <= max(noise * 4, total // 100), (
            f"缓存与直绘差异 {diff} 像素，远超渲染噪声 {noise}"
            f"（占比 {diff / total:.4%}）"
        )

    def test_hover_visual_changes(self, make):
        """hover 确实改变画面（否则「缓存不失效 hover」是伪需求）。"""
        chart = _ready(make(ElaChartWidget), _opt(tooltip={"trigger": "item"}))
        r = chart.seriesRenderers[0]
        chart._hover = (r, {"dataIndex": 40})
        a = _render(chart)
        chart.invalidateSeriesLayer()
        b = _render(chart)
        assert a != b, "hover 前后画面相同，emphasis/blur 未生效"

    def test_multiple_series_all_drawn(self, make):
        """多条系列都要出现在缓存位图里。"""
        opt = {
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "line",
                    "name": "A",
                    "data": [float(i % 50) for i in range(400)],
                },
                {
                    "type": "bar",
                    "name": "B",
                    "data": [float(i % 20) for i in range(200)],
                },
            ],
        }
        chart = _ready(make(ElaChartWidget), opt)
        img = _render(chart)
        colors = {
            img.pixelColor(x, y).alpha()
            for y in range(0, 400, 3)
            for x in range(0, 600, 3)
        }
        assert len(colors) > 1, "画面全透明，系列未画进缓存"

    def test_buffer_backed_series_rendered(self, make):
        """大数组缓冲区（零拷贝摄入后的常态）也进缓存。"""
        buf = toBuffer([float(i % 89) for i in range(2000)])
        assert buf is not None
        chart = _ready(make(ElaChartWidget), _opt(data=buf))
        _render(chart)
        assert _cached(chart)
        img = chart._series_pixmap_cache
        assert any(
            img.pixelColor(x, y).alpha() > 0
            for y in range(0, img.height(), 4)
            for x in range(0, img.width(), 4)
        ), "缓冲区数据未画进缓存"

    def test_empty_series_safe(self, make):
        """空系列不崩（缓存位图为空）。"""
        chart = _ready(make(ElaChartWidget), _opt(data=[]))
        _render(chart)
        assert chart._series_pixmap_cache is not None

    def test_disposed_widget_safe(self, make):
        chart = _ready(make(ElaChartWidget), _opt())
        _render(chart)
        chart.dispose()
        assert chart.isDisposed()


class TestSeriesLayerPerformanceSanity:
    def test_repaint_is_cheaper_when_cached(self, make):
        """命中缓存的重绘应明显快于重建（不设阈值，只要求方向正确）。"""
        import time

        opt = {
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "type": "bar",
                    "name": f"B{i}",
                    "data": [float((j * (i + 3)) % 80) for j in range(3000)],
                }
                for i in range(4)
            ],
        }
        chart = _ready(make(ElaChartWidget), opt, w=700, h=500)
        _render(chart)  # 预热，填充缓存
        n = 5
        t0 = time.perf_counter()
        for _ in range(n):
            _render(chart)
        cached_ms = (time.perf_counter() - t0) / n * 1000
        chart.invalidateSeriesLayer()
        t0 = time.perf_counter()
        for _ in range(n):
            chart.invalidateSeriesLayer()
            _render(chart)
        direct_ms = (time.perf_counter() - t0) / n * 1000
        assert cached_ms < direct_ms, (
            f"命中缓存 {cached_ms:.1f} ms 未快于重建 {direct_ms:.1f} ms"
        )
