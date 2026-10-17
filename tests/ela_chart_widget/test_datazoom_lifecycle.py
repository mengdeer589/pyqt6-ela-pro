"""dataZoom 组件的生命周期与事件去重回归。

两条都是「陈旧实例仍在 chart 上起作用」这一族问题：

* **事件过滤器泄漏** —— ``DataZoomComponent`` 把滚轮缩放装成 chart 的事件
  过滤器，但解挂旧实例的代码原先写在 ``if self.has_inside:`` 里面。于是
  ``inside -> slider`` 的切换（以及 ``dataZoom`` 被整块删掉）会留下一个孤儿
  过滤器：它已不在 ``chart.components`` 里，UI 的滑块不知道它存在，但它继续
  拦截滚轮并用陈旧的 ``_full_cats`` / ``_full_range`` 改坐标轴 —— 滑块显示
  0-100% 而实际窗口已缩到 10-90%，此后两者每帧互相覆盖。
* **事件发两遍** —— ``dispatchAction({"type": "dataZoom"})`` 路径上，
  ``applyAction`` 内部已经 ``_emit_changed()``，``core._dispatch_data_zoom``
  又补发一次 ``dataZoomChanged``；滚轮 / 拖拽路径只发一遍，两条路径不一致。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import ElaChartWidget

CATS = ["a", "b", "c", "d", "e", "f", "g", "h"]
VALUES = [1, 3, 2, 5, 4, 7, 6, 8]


def _option(zoom):
    opt = {
        "xAxis": {"type": "category", "data": list(CATS)},
        "yAxis": {},
        "series": [{"type": "line", "name": "A", "data": list(VALUES)}],
    }
    if zoom is not None:
        opt["dataZoom"] = zoom
    return opt


def _chart(make, zoom, **set_kwargs):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setOption(_option(zoom), **set_kwargs)
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


def _comp(chart, key="dataZoom"):
    return next(
        (c for c in chart.components if getattr(c, "optionKey", "") == key), None
    )


def _window(comp):
    if comp is None:
        return None
    return (round(float(comp.start), 3), round(float(comp.end), 3))


def _wheel(chart, pos: QPointF | None = None, dy: int = 120):
    if pos is None:
        plot = chart.primaryCoord().plot
        pos = QPointF(plot.center())
    ev = QWheelEvent(
        QPointF(pos),
        QPointF(pos),
        QPoint(0, 0),
        QPoint(0, dy),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(chart, ev)
    QApplication.processEvents()


def _zoom_events(chart):
    """收集对外可见的缩放事件。

    两条出口都要看：``dataZoomChanged`` 是公开信号，``chart.on("datazoom")``
    是 ECharts 事件出口（内部 ``_forward_data_zoom`` → ``_emit_event``）。
    两条由同一次 emit 驱动，**数量必须一致** —— 不一致就是重复发射或漏发。
    """
    got = []
    chart.dataZoomChanged.connect(lambda s, e: got.append(("signal", s, e)))
    chart.on("datazoom", lambda params: got.append(("echarts", params)))
    return got


def _count(got, kind):
    return sum(1 for item in got if item[0] == kind)


class TestNoOrphanWheelFilter:
    """``inside -> slider`` 不得留下仍拦截滚轮的孤儿过滤器。"""

    def test_switching_to_slider_unhooks_old_filter(self, make):
        chart = _chart(make, [{"type": "inside"}])
        old = getattr(chart, "_datazoom_filter", None)
        assert old is not None, "inside 组件应把自己装成 chart 的事件过滤器"

        chart.setOption(_option([{"type": "slider"}]))
        QApplication.processEvents()

        live = _comp(chart)
        assert live is not None and live.has_slider and not live.has_inside
        assert getattr(chart, "_datazoom_filter", None) is None, (
            "has_inside=False 的新组件不该留下过滤器登记"
        )

    def test_orphan_does_not_steal_the_wheel(self, make):
        """回归：孤儿曾把窗口改成 (10, 90)，而活组件仍停在 (0, 100)。"""
        chart = _chart(make, [{"type": "inside"}])
        old = getattr(chart, "_datazoom_filter", None)
        before = _window(old)

        chart.setOption(_option([{"type": "slider"}]))
        QApplication.processEvents()
        live = _comp(chart)

        events = _zoom_events(chart)
        _wheel(chart)

        assert _window(old) == before, "孤儿过滤器不该再响应滚轮"
        assert _window(live) == before, "滚轮落在 slider-only 配置上应无人缩放"
        assert events == [], f"无 inside 缩放时不该有 datazoom 事件，实际 {events}"

    def test_repeated_switches_do_not_accumulate(self, make):
        """反复 inside/slider 切换后仍只有一个有效缩放者。"""
        chart = _chart(make, [{"type": "inside"}])
        for _ in range(3):
            chart.setOption(_option([{"type": "slider"}]))
            chart.setOption(_option([{"type": "inside"}]))
        QApplication.processEvents()

        live = _comp(chart)
        assert getattr(chart, "_datazoom_filter", None) is live

        events = _zoom_events(chart)
        _wheel(chart)
        assert _count(events, "signal") == 1, f"滚轮应只触发一次缩放：{events}"
        assert _window(live) != (0.0, 100.0), "活组件应真的缩放了"


class TestDroppingDataZoomUnhooks:
    def test_not_merge_removal_unhooks_filter(self, make):
        """``notMerge=True`` 把 dataZoom 整块删掉时也要解挂。"""
        chart = _chart(make, [{"type": "inside"}])
        assert getattr(chart, "_datazoom_filter", None) is not None

        chart.setOption(
            {
                "xAxis": {"type": "category", "data": list(CATS)},
                "yAxis": {},
                "series": [{"type": "line", "name": "A", "data": list(VALUES)}],
            },
            notMerge=True,
        )
        QApplication.processEvents()

        assert _comp(chart) is None, "notMerge 后不该还有 dataZoom 组件"
        assert getattr(chart, "_datazoom_filter", None) is None, (
            "组件被删后过滤器登记必须清掉，否则滚轮会驱动一个不存在的组件"
        )

        events = _zoom_events(chart)
        _wheel(chart)
        assert events == [], f"dataZoom 已删除却仍发出 {events}"


class TestZoomEmittedOnce:
    def test_dispatch_action_emits_once(self, make):
        chart = _chart(make, [{"type": "inside"}])
        events = _zoom_events(chart)

        assert chart.dispatchAction({"type": "dataZoom", "start": 20, "end": 60})

        assert _count(events, "signal") == 1, f"dispatchAction 应发一次：{events}"
        assert _count(events, "echarts") == 1, f"ECharts 事件应发一次：{events}"
        echarts = next(p for kind, p in events if kind == "echarts")
        assert echarts["type"] == "datazoom"
        assert (echarts["start"], echarts["end"]) == (20.0, 60.0)

    def test_dispatch_action_emits_once_with_zoom_lock(self, make):
        chart = _chart(make, [{"type": "inside"}])
        events = _zoom_events(chart)

        assert chart.dispatchAction({"type": "dataZoom", "start": 30, "zoomLock": True})

        assert _count(events, "signal") == 1, f"zoomLock 路径同样只发一次：{events}"
        assert _count(events, "echarts") == 1, f"zoomLock 路径同样只发一次：{events}"

    def test_wheel_path_emits_once(self, make):
        chart = _chart(make, [{"type": "inside"}])
        events = _zoom_events(chart)
        _wheel(chart)
        assert _count(events, "signal") == 1, f"滚轮应发一次：{events}"
        assert _count(events, "echarts") == 1, f"滚轮应发一次：{events}"

    def test_rejected_dispatch_emits_nothing(self, make):
        chart = _chart(make, [{"type": "inside"}])
        events = _zoom_events(chart)

        assert chart.dispatchAction({"type": "dataZoom", "dataZoomIndex": 3}) is False
        assert chart.dispatchAction({"type": "dataZoom"}) is False
        assert events == []


class TestComponentDisposeHook:
    def test_dispose_is_idempotent(self, make):
        chart = _chart(make, [{"type": "inside"}])
        comp = _comp(chart)
        comp.dispose()
        comp.dispose()  # 重复调用不得抛
        assert getattr(chart, "_datazoom_filter", None) is None

    def test_timeline_dispose_stops_timer(self, make):
        chart = _chart(make, None)
        chart.setOption(
            {
                **_option(None),
                "timeline": {"data": ["2024", "2025"], "autoPlay": True},
            }
        )
        QApplication.processEvents()
        timeline = _comp(chart, "timeline")
        assert timeline is not None
        assert timeline._timer.isActive()

        timeline.dispose()
        assert not timeline._timer.isActive()
        assert getattr(chart, "_timeline_timer", None) is None


class TestSpanLimitsAcrossEntries:
    """``minSpan`` / ``maxSpan`` 要取**所有** dataZoom 条目的交集。

    引擎只有一个共享窗口（``start`` / ``end``，inside 与 slider 共用），而
    ECharts 是每个 ``dataZoom[i]`` 各带各的约束 —— 只读 ``entries[0]`` 会让
    挂在 slider 上的约束整条丢失（实测窗口能被拖到 10%）。
    """

    def _drag_end_to(self, chart, pct):
        z = _comp(chart)
        handle = z._h_end.center()
        assert z.onMousePress(QPointF(handle)), "end 把手未命中"
        x = z._track.left() + z._track.width() * pct / 100.0
        z.onMouseMove(QPointF(x, z._track.center().y()))
        z.onMouseRelease(QPointF(x, z._track.center().y()))
        return z.end - z.start

    def test_min_span_on_later_entry_is_honoured(self, make):
        chart = _chart(make, [{"type": "inside"}, {"type": "slider", "minSpan": 40}])
        z = _comp(chart)
        assert z._span_limits() == (40.0, None)

        span = self._drag_end_to(chart, 20.0)
        assert span >= 39.9, f"minSpan=40 应封底，实际 {span}"

    def test_min_span_on_first_entry_still_honoured(self, make):
        chart = _chart(make, [{"type": "slider", "minSpan": 40}, {"type": "inside"}])
        span = self._drag_end_to(chart, 20.0)
        assert span >= 39.9, f"minSpan=40 应封底，实际 {span}"

    def test_max_span_takes_the_tightest(self, make):
        """两个条目各带 maxSpan 时取最小者（交集），而不是 entries[0] 的那个。"""
        chart = _chart(
            make, [{"type": "inside", "maxSpan": 90}, {"type": "slider", "maxSpan": 40}]
        )
        z = _comp(chart)
        assert z._span_limits() == (None, 40.0)

        assert chart.dispatchAction({"type": "dataZoom", "start": 0, "end": 100})
        assert (z.end - z.start) <= 40.1, f"maxSpan 交集是 40，实际 {z.end - z.start}"

    def test_min_and_max_both_intersected(self, make):
        chart = _chart(
            make,
            [
                {"type": "inside", "minSpan": 10, "maxSpan": 90},
                {"type": "slider", "minSpan": 30, "maxSpan": 60},
            ],
        )
        assert _comp(chart)._span_limits() == (30.0, 60.0)

    def test_single_entry_unchanged(self, make):
        chart = _chart(make, [{"type": "inside", "minSpan": 25, "maxSpan": 75}])
        assert _comp(chart)._span_limits() == (25.0, 75.0)

    def test_no_limits_still_unconstrained(self, make):
        chart = _chart(make, [{"type": "inside"}, {"type": "slider"}])
        assert _comp(chart)._span_limits() == (None, None)


@pytest.mark.parametrize("zoom", [[{"type": "inside"}], [{"type": "slider"}]])
def test_drag_handle_does_not_emit_without_change(make, zoom):
    """在把手位置按下再原地松开：窗口没变就不该发事件。"""
    chart = _chart(make, zoom)
    events = _zoom_events(chart)
    comp = _comp(chart)
    if not comp.has_slider:
        pytest.skip("该配置没有滑块把手")
    handle = comp._h_start.center()
    assert comp.onMousePress(QPointF(handle)) is True
    comp.onMouseRelease(QPointF(handle))
    assert events == []
