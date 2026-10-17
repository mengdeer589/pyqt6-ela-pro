"""F 组回归：可观测性与崩溃防护。

三个 bug 的共同点是「**异常被静默吞掉**」，而这恰好是唯一能看到它们的出口：

* **F2** ``warn_once`` 的键只用类名 → 第二个系列的**另一种**异常永久不可见。
  异常本身已被 ``except Exception`` 吞掉，stderr 是唯一线索。
* **F6** ``benchmark()`` 声称「不改变任何状态」，却留下一个指向**已销毁渲染器**
  的 ``_hover``（``notMerge`` 的 ``_rebuild`` 重建了全部渲染器）。
* **F7** 六个鼠标钩子是**裸调**（只有 ``wheelEvent`` 有保护）。钩子跑在 Qt
  回调链上，未捕获异常穿过 C++ 边界 = 0xC0000409 零 traceback 终止。
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts import _utils
from pyqt6_ela_pro.charts._utils import warn_once

OPT = {
    "animation": False,
    "xAxis": {"type": "category", "data": ["a", "b", "c"]},
    "yAxis": {},
    "series": [{"type": "bar", "name": "S", "data": [1, 2, 3]}],
}

_EVENT_FOR = {
    "move": QEvent.Type.MouseMove,
    "press": QEvent.Type.MouseButtonPress,
    "release": QEvent.Type.MouseButtonRelease,
    "dblclick": QEvent.Type.MouseButtonDblClick,
}


@pytest.fixture(autouse=True)
def _fresh_warn_keys():
    """每个用例清空去重集合。

    ``_warned_keys`` 是**模块级**的，跨用例累积 —— 不清的话前一个用例登记过
    的键会把后一个的告警吞掉，而症状是「测试之间互相影响、单跑必过」。
    这与生产里 ``_WARN_LIMIT`` 满了就 ``clear()`` 是同一种有界化。
    """
    _utils._warned_keys.clear()
    yield
    _utils._warned_keys.clear()


def _chart(make, option=None):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setOption(option or OPT)
    chart.anim.stop()
    chart.anim.setProgress(1.0)
    chart.show()
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


def _send(chart, kind, local=QPointF(300.0, 200.0), button=Qt.MouseButton.LeftButton):
    ev = QMouseEvent(
        _EVENT_FOR[kind],
        QPointF(local),
        button,
        button if kind == "release" else Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.instance().sendEvent(chart, ev)
    QApplication.processEvents()


class TestWarnOnceKeysAreDistinguishing:
    """F2：去重键必须能区分故障，而不是「同一个类只报一次」。"""

    def test_same_class_different_exception_types_both_reported(self, capsys):
        from pyqt6_ela_pro.charts._utils import warn_key

        warn_once(warn_key("t", "BarRenderer", "A", "AttributeError"), "第一个故障")
        warn_once(warn_key("t", "BarRenderer", "A", "TypeError"), "第二个故障")
        err = capsys.readouterr().err
        assert "第一个故障" in err
        assert "第二个故障" in err, "同类不同异常被去重键吞掉了"

    def test_different_series_same_exception_both_reported(self, capsys):
        from pyqt6_ela_pro.charts._utils import warn_key

        warn_once(warn_key("t", "BarRenderer", "A", "TypeError"), "A 故障")
        warn_once(warn_key("t", "BarRenderer", "B", "TypeError"), "B 故障")
        err = capsys.readouterr().err
        assert "A 故障" in err and "B 故障" in err

    def test_identical_key_still_deduped(self, capsys):
        """去重的本职（同一故障不刷屏）不能被破坏。"""
        from pyqt6_ela_pro.charts._utils import warn_key

        key = warn_key("t", "BarRenderer", "A", "TypeError")
        warn_once(key, "同一个故障")
        warn_once(key, "同一个故障")
        assert capsys.readouterr().err.count("同一个故障") == 1

    def test_warn_key_drops_empty_parts(self):
        """``None`` / 空串不能进键，否则两个不同的「无名字」撞键。"""
        from pyqt6_ela_pro.charts._utils import warn_key

        assert warn_key("t", "R", None, "E") == warn_key("t", "R", "", "E")
        assert "None" not in warn_key("t", "R", None)

    def test_series_paint_warnings_are_per_series(self, make, capsys):
        """回归到真实路径：同类系列的**两种**异常都要能被看到。

        这正是原 bug 的现场 —— 两个 ``bar`` 系列，第一个抛 ``TypeError``、
        第二个抛 ``ValueError``，键只有类名，于是第二个的故障永不可见。
        """
        chart = _chart(
            make,
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {},
                "series": [
                    {"type": "bar", "name": "dup", "data": [1, 2]},
                    {"type": "bar", "name": "dup", "data": [3, 4]},
                ],
            },
        )
        assert capsys.readouterr().err == "", "基线不该有告警"

        def boom(exc):
            def paint(p, t):
                raise exc

            return paint

        chart.seriesRenderers[0].paint = boom(TypeError("第一个系列类型错"))
        chart.seriesRenderers[1].paint = boom(ValueError("第二个系列值错"))
        # 系列层位图缓存命中时压根不会调 paint，必须先失效
        chart.invalidateSeriesLayer()
        chart.grab()

        err = capsys.readouterr().err
        assert "第一个系列类型错" in err, f"第一个系列告警丢了：{err!r}"
        assert "第二个系列值错" in err, f"第二个系列告警被去重键吞掉了：{err!r}"


class TestBenchmarkLeavesNoStaleState:
    """``benchmark()`` 声称「不改变任何状态」—— 钉住这条契约。

    **注意** ``_hover`` 的清理由 ``setOption(notMerge=True)`` 内部完成
    （core 的 ``notMerge`` 分支会 ``self._hover = None``），不是 benchmark 的
    ``finally``。原先审查时把它记成「benchmark 忘了清 hover」是**误判** ——
    这里把既有行为写成测试，免得下次「修复」时再往 benchmark 里塞一遍。
    """

    def test_hover_is_cleared_after_benchmark(self, make):
        chart = _chart(make)
        r = chart.seriesRenderers[0]
        bar = r._bars[0]
        chart._hover = (r, {"dataIndex": bar["index"], "name": bar["label"]})
        assert chart.hoverInfo() is not None

        chart.benchmark(frames=1, perSeries=False)
        assert chart.hoverInfo() is None, (
            "benchmark 后仍持有 _hover，而它指向的是 notMerge 重建前的渲染器"
        )

    def test_hover_cleared_even_when_benchmark_raises(self, make, monkeypatch):
        chart = _chart(make)
        r = chart.seriesRenderers[0]
        bar = r._bars[0]
        chart._hover = (r, {"dataIndex": bar["index"], "name": bar["label"]})

        def boom(*a, **k):
            raise RuntimeError("layout 炸了")

        monkeypatch.setattr(chart, "_layout_all", boom)
        with pytest.raises(RuntimeError):
            chart.benchmark(frames=1, perSeries=False)
        assert chart.hoverInfo() is None

    def test_legend_state_restored(self, make):
        """benchmark 内部那次 ``notMerge`` 会清空图例选中态，finally 必须复原。"""
        chart = _chart(make)
        chart.setOption({"legend": {"selected": {"S": False}}})
        QApplication.processEvents()
        chart.benchmark(frames=1, perSeries=False)
        assert chart._series_state.get("S") is False


class TestMouseHooksAreExceptionIsolated:
    """F7：所有鼠标钩子都必须异常隔离（Qt 回调链 = 0xC0000409）。"""

    HOOKS = [
        "onMouseMove",
        "onMousePress",
        "onMouseRelease",
        "onMouseDoubleClick",
        "onWheel",
    ]

    @pytest.mark.parametrize("hook", HOOKS)
    @pytest.mark.parametrize(
        "kind", ["move", "press", "release", "dblclick"], ids=["m", "p", "r", "d"]
    )
    def test_broken_hook_does_not_kill_the_process(self, make, hook, kind):
        chart = _chart(make)
        r = chart.seriesRenderers[0]

        def boom(*args):
            raise RuntimeError(f"{hook} 炸了")

        setattr(r, hook, boom)
        _send(chart, kind)  # 不抛到 pytest 即为通过（崩进程会直接 exit）

    def test_broken_component_hook_does_not_kill_the_process(self, make):
        chart = _chart(
            make,
            {
                **OPT,
                "dataZoom": [{"type": "inside", "id": "dz"}],
            },
        )
        for comp in chart._components:
            comp.onMouseMove = lambda *a: (_ for _ in ()).throw(
                RuntimeError("comp 炸了")
            )
        _send(chart, "move")

    def test_wheel_event_already_guarded_still_works(self, make):
        """``wheelEvent`` 原本就有保护，别被重构弄坏。"""
        chart = _chart(make)
        # 没有 onWheel 钩子时不得消费（否则页面滚轮会被图表吞掉）
        assert chart._dispatch_hook("onWheel", None) is False

    def test_exception_is_reported_once_per_distinct_failure(self, make, capsys):
        """告警去重：同一故障只报一次，不刷屏。"""
        chart = _chart(make)
        r = chart.seriesRenderers[0]

        def boom(*args):
            raise RuntimeError("同一个故障")

        r.onMouseMove = boom
        for _ in range(5):
            _send(chart, "move")
        err = capsys.readouterr().err
        assert err.count("同一个故障") == 1, f"刷屏了 {err.count('同一个故障')} 次"
