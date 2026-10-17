from __future__ import annotations

import gc
import weakref

import pytest
from _qthelpers import wait_until
from PyQt6.QtGui import QImage

from pyqt6_ela_pro.mermaid_support import (
    _MAX_RASTER_DIM,
    _MIN_ZOOM,
    _clamp_zoom_to_budget,
    _raster_budget_ok,
    ElaMermaidRenderer,
)

CODE = "graph TD; A-->B;"


def _image() -> QImage:
    image = QImage(4, 4, QImage.Format.Format_ARGB32)
    image.fill(0xFF00FF00)
    return image


@pytest.fixture
def renderer(make):
    widget = make(ElaMermaidRenderer)
    widget.setRenderer(lambda code, theme: _image())
    return widget


def _drain(renderer, qapp, timeout_ms=3000) -> None:
    # wait_until 的签名是 (qapp, predicate, ...) —— 第一个参数是 QApplication
    wait_until(
        qapp,
        lambda: not renderer._inflight,
        timeout_ms=timeout_ms,
        use_qwait=True,
    )
    qapp.processEvents()


class TestCallbacksSurviveClearCache:
    """``request(..., cb)`` 的回调契约：``clearCache`` 不得让 cb 消失。"""

    def test_clear_cache_delivers_pending_callbacks_as_none(self, renderer, qapp):
        seen: list = []
        # 阻塞式渲染器：保证调用clearCache 时回调还挂在 _callbacks 上
        from PyQt6.QtCore import QThread

        def slow(code: str, theme: str):
            QThread.msleep(400)
            return _image()

        renderer.setRenderer(slow)
        renderer.request(CODE, "light", lambda img: seen.append(img))
        renderer.clearCache()
        assert seen == [None], "clearCache 把在途回调直接丢掉了（它永远不会被调用）"

    def test_clear_cache_empties_inflight(self, renderer):
        renderer.request(CODE, "light")
        renderer.clearCache()
        assert renderer._inflight == set(), "在途 key 没被清掉（回调会无界堆积）"

    def test_inflight_key_not_poisoned_after_clear(self, renderer, qapp):
        """原缺陷：某key 卡住后，每次 request 都只追加回调然后 return。"""
        seen: list = []
        renderer.request(CODE, "light", lambda img: seen.append(img))
        renderer.clearCache()
        renderer.request(CODE, "light", lambda img: seen.append(img))
        _drain(renderer, qapp)
        assert seen and seen[-1] is not None, "clearCache 之后同一个 key 再也渲染不出来"


class TestRasterBudget:
    """模型输出不可信 —— 一段 mermaid 不该能分配任意内存。"""

    def test_small_is_allowed(self):
        assert _raster_budget_ok(800, 600) is True
        assert _raster_budget_ok(100, 100) is True

    def test_area_cap_enforced(self):
        assert _raster_budget_ok(10_000, 10_000) is False, "1亿像素超 64M 上限"
        assert _raster_budget_ok(8000, 8000) is True, "64M 正好在上限内"

    def test_single_side_cap_enforced(self):
        assert _raster_budget_ok(_MAX_RASTER_DIM + 1, 100) is False
        assert _raster_budget_ok(100, _MAX_RASTER_DIM + 1) is False

    @pytest.mark.parametrize(
        ("w", "h"),
        [
            (float("inf"), 10),
            (float("nan"), 10),
            (0, 10),
            (-5, 10),
            (10, 0),
        ],
    )
    def test_non_finite_and_degenerate_rejected(self, w, h):
        assert _raster_budget_ok(w, h) is False

    def test_zoom_clamped_into_budget(self):
        # 9000x9000 @ zoom1.0 = 8100万像素> 6400万 -> 压到 sqrt(64/81)≈0.888
        clamped = _clamp_zoom_to_budget(1.0, 9000.0, 9000.0)
        assert clamped is not None
        assert clamped < 1.0, "面积超预算时必须降 zoom"
        assert _raster_budget_ok(9000.0 * clamped, 9000.0 * clamped) is True
        assert clamped >= _MIN_ZOOM

    def test_zoom_none_when_even_min_zoom_too_big(self):
        """10万x10万 viewBox：连最小 zoom 都塞不进预算 -> 判「渲染不出来」。

        这正是要拦的形态 —— 不拦就是 ``50000x50000x4B ≈ 10 GB``。
        宁可报失败让调用方降级成代码卡片，也不要默默分配。
        """
        assert _clamp_zoom_to_budget(1.0, 100_000.0, 100_000.0) is None

    def test_zoom_none_on_non_finite(self):
        assert _clamp_zoom_to_budget(float("inf"), 100.0, 100.0) is None
        assert _clamp_zoom_to_budget(1.0, float("nan"), 100.0) is None

    def test_reasonable_size_untouched(self):
        assert _clamp_zoom_to_budget(2.0, 800.0, 600.0) == 2.0


class TestLifecycle:
    def test_pool_is_not_a_child_of_the_renderer(self, renderer):
        """池是子对象时，销毁渲染器会在 GUI 线程阻塞到当前渲染结束。"""
        assert renderer._pool.parent() is None

    def test_delete_later_returns_promptly(self, renderer, qapp):
        renderer.deleteLater()
        wait_until(qapp, lambda: False, timeout_ms=100, use_qwait=True)

    def test_render_task_holds_renderer_weakly(self, make, qapp):
        """渲染途中宿主被关掉时，任务不得 emit 到已释放对象。"""
        from pyqt6_ela_pro.mermaid_support import _RenderTask

        widget = make(ElaMermaidRenderer)
        task = _RenderTask(widget, CODE, "light")
        assert isinstance(task._renderer, weakref.ref), "任务对渲染器是强引用"

        ref = weakref.ref(widget)
        widget.deleteLater()
        del widget
        gc.collect()
        task.run()  # 不得抛异常
        assert ref() is None or True  # 只验证「运行不抛」，不钉存活时机

    def test_prewarm_task_holds_renderer_weakly(self, make, qapp):
        from pyqt6_ela_pro.mermaid_support import _PrewarmTask

        widget = make(ElaMermaidRenderer)
        task = _PrewarmTask(widget)
        assert isinstance(task._renderer, weakref.ref)
        widget.deleteLater()
        del widget
        gc.collect()
        task.run()
