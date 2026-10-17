"""``ChartTimeline`` 生命周期回归。

时间轴的帧切换路径比较特别：``goto()`` 会调 ``chart._refresh()`` → ``_rebuild()``，
而 ``_rebuild`` 现在会先 ``dispose()`` 旧组件 —— 也就是**从旧组件自己的定时器
回调里把自己 dispose 掉**（``_advance`` → ``goto`` → 刷新）。这条路径以前没有
任何测试，``ChartTimeline`` 是全库零覆盖组件之一。
"""

from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, QEvent, QTimer
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import ElaChartWidget

FRAMES = [
    {"series": [{"type": "line", "name": "A", "data": [1, 2, 3]}]},
    {"series": [{"type": "line", "name": "A", "data": [9, 8, 7]}]},
    {"series": [{"type": "line", "name": "A", "data": [4, 4, 4]}]},
]


def _option(**timeline):
    opt = {
        "xAxis": {"type": "category", "data": ["a", "b", "c"]},
        "yAxis": {},
        "series": [{"type": "line", "name": "A", "data": [1, 2, 3]}],
        "baseOption": {"title": {"text": "T"}},
        "options": [dict(f) for f in FRAMES],
    }
    opt["timeline"] = {"data": ["2024", "2025", "2026"], **timeline}
    return opt


def _chart(make, **timeline):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setOption(_option(**timeline))
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


def _timeline(chart):
    return next(
        (c for c in chart.components if getattr(c, "optionKey", "") == "timeline"), None
    )


def _flush_deferred_deletes():
    """显式冲刷 DeferredDelete（``processEvents()`` 不派发，见 AGENTS.md）。"""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


def _timers(chart):
    return [c for c in chart.children() if isinstance(c, QTimer)]


class TestFrameSwitching:
    def test_goto_switches_frame_and_emits_once(self, make):
        chart = _chart(make)
        tl = _timeline(chart)
        seen = []
        chart.timelineChanged.connect(seen.append)

        tl.goto(2)
        QApplication.processEvents()

        assert seen == [2], f"goto 应发一次 timelineChanged，实际 {seen}"
        assert _timeline(chart).current == 2, "重建后的新组件应继承帧号"

    def test_goto_rewinds(self, make):
        chart = _chart(make)
        _timeline(chart).goto(2)
        QApplication.processEvents()
        seen = []
        chart.timelineChanged.connect(seen.append)

        _timeline(chart).goto(5)  # 越界应回绕到 5 % 3 == 2
        assert seen == [2]

        _timeline(chart).goto(-1)  # 负数回绕到 2
        assert seen == [2, 2]

    def test_goto_from_timer_callback_survives_rebuild(self, make):
        """``_advance`` 里会 dispose 掉自己所在的旧组件，不能崩也不能断播。

        **直接驱动 ``_advance()`` 而不等墙钟**：要验的是「从定时器回调里
        ``goto`` → ``_rebuild`` → dispose 自己」这条重入路径，与真实计时器
        触发的是同一个函数。等 400ms 数 tick 在合跑时会偶发 0 次（事件循环被
        前面的用例占住）—— 那是测试的脆弱性，不是产品的行为。
        """
        chart = _chart(make, autoPlay=True, playInterval=60)
        tl = _timeline(chart)
        assert tl.playing and tl._timer.isActive()

        seen = []
        chart.timelineChanged.connect(seen.append)

        stale = []
        for _ in range(3):
            stale.append(tl._timer)
            tl._advance()  # 定时器回调的入口
            QApplication.processEvents()
            tl = _timeline(chart)

        assert len(seen) == 3, f"每次 _advance 应推进一帧，实际 {seen}"
        assert tl.playing, "重建后应仍在播放"
        assert all(not t.isActive() for t in stale), "旧定时器必须已停"
        assert tl._timer is not stale[0], "组件确实被重建过（否则本用例没意义）"

    def test_autoplay_state_survives_rebuild(self, make):
        chart = _chart(make, autoPlay=True, playInterval=60)
        _timeline(chart).goto(1)
        QApplication.processEvents()
        assert _timeline(chart).playing
        assert getattr(chart, "_timeline_playing", None) is True


class TestTimerHygiene:
    def test_timers_do_not_accumulate_across_rebuilds(self, make):
        """``dispose()`` 必须连 ``deleteLater()`` 一起做，否则每次刷新泄一个 QTimer。

        计数前必须**显式冲刷 DeferredDelete**（AGENTS.md）：``processEvents()``
        不派发它，所以「跑一会儿事件循环」这种写法在合跑时不一定落地。
        """
        chart = _chart(make, autoPlay=True, playInterval=60)
        tl = _timeline(chart)
        baseline = len(_timers(chart))
        assert baseline >= 1

        stale = []
        for _ in range(6):
            stale.append(tl._timer)
            tl.goto(tl.current + 1)
            QApplication.processEvents()
            tl = _timeline(chart)

        assert all(not t.isActive() for t in stale), "每次切帧都要停掉旧定时器"

        _flush_deferred_deletes()
        after = len(_timers(chart))
        assert after <= baseline + 1, (
            f"6 次切帧后 QTimer 从 {baseline} 涨到 {after}，dispose 没清干净"
        )

    def test_timeline_owns_exactly_one_timer(self, make):
        chart = _chart(make, autoPlay=True, playInterval=60)
        tl = _timeline(chart)
        assert getattr(chart, "_timeline_timer", None) is tl._timer

        tl.dispose()
        assert not tl._timer.isActive()
        assert getattr(chart, "_timeline_timer", None) is None

    def test_dispose_is_idempotent(self, make):
        chart = _chart(make, autoPlay=True)
        tl = _timeline(chart)
        tl.dispose()
        tl.dispose()
        assert getattr(chart, "_timeline_timer", None) is None


class TestOptionBookkeeping:
    def test_goto_syncs_current_index_in_option(self, make):
        """帧号要写回 ``_option["timeline"]["currentIndex"]``，否则重建会回退。"""
        chart = _chart(make)
        _timeline(chart).goto(1)
        QApplication.processEvents()

        assert chart._option["timeline"]["currentIndex"] == 1

        # 之后随便改一次 option 再重建，帧号不该丢
        chart.setOption({"title": {"text": "T2"}})
        QApplication.processEvents()
        assert _timeline(chart).current == 1

    def test_toggle_play_round_trip(self, make):
        chart = _chart(make, autoPlay=False)
        tl = _timeline(chart)
        assert not tl.playing and not tl._timer.isActive()

        tl.togglePlay()
        assert tl.playing and tl._timer.isActive()
        assert getattr(chart, "_timeline_playing", None) is True

        tl.togglePlay()
        assert not tl.playing and not tl._timer.isActive()

    def test_reserve_bottom_zero_without_labels(self, make):
        chart = _chart(make)
        _timeline(chart).opt["data"] = []
        _timeline(chart).labels = []
        assert _timeline(chart).reserveBottom() == 0.0
