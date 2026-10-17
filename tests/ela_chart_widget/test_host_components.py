"""``addComponent`` / ``removeComponent`` 契约：宿主注入的组件跨 ``setOption`` 存活。

``_rebuild`` 每次 ``setOption`` 都把 ``_components`` 清空重建（option 驱动的组件
就该这样）。但宿主经 ``addComponent`` 挂上来的组件原先也被一起丢掉 —— 公开 API
没有任何「重新挂上」的路径，等于挂一次就只在第一次 ``setOption`` 之前有效。

分界：option 驱动的组件走 :func:`registerComponent` + option 同名键（每次重建）；
纯运行时挂件走 ``addComponent``（宿主自管刷新，``_rebuild`` 原样挂回）。
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.charts.core import registerComponent

BASE = {
    "xAxis": {"type": "category", "data": ["a", "b", "c"]},
    "yAxis": {},
    "series": [{"type": "line", "name": "A", "data": [1, 2, 3]}],
}


class HostProbe:
    """宿主自定义组件：鸭子类型，不注册到 COMPONENT_REGISTRY。"""

    optionKey = "hostProbe"

    def __init__(self, chart, opt=None):
        self.chart = chart
        self.opt = dict(opt or {})
        self.paint_calls = 0
        self.layout_calls = 0
        self.disposed = 0
        self.rect = QRectF()

    def layout(self, rect: QRectF) -> None:
        self.layout_calls += 1
        self.rect = QRectF(rect)

    def paint(self, p, anim_t: float = 1.0) -> None:
        self.paint_calls += 1

    def hitTest(self, pos: QPointF):
        return None

    def dispose(self) -> None:
        self.disposed += 1


def _chart(make, **extra):
    chart = make(ElaChartWidget)
    chart.resize(600, 400)
    chart.setOption({**BASE, **extra})
    chart.anim.setProgress(1.0)
    chart._layout_all(force=True)
    QApplication.processEvents()
    return chart


def _keys(chart):
    return [getattr(c, "optionKey", "?") for c in chart.components]


class TestHostComponentSurvivesSetOption:
    def test_survives_rebuild(self, make):
        chart = _chart(make)
        probe = HostProbe(chart)
        chart.addComponent(probe)
        assert probe in chart.components

        for title in ("t1", "t2", "t3"):
            chart.setOption({"title": {"text": title}})
            QApplication.processEvents()

        assert probe in chart.components, "宿主组件被 setOption 静默丢弃了"
        assert probe.disposed == 0, "宿主组件不该被 _rebuild dispose（它没被丢弃）"

    def test_not_duplicated_across_rebuilds(self, make):
        chart = _chart(make)
        probe = HostProbe(chart)
        chart.addComponent(probe)
        for _ in range(4):
            chart.setOption({"title": {"text": "x"}})
            QApplication.processEvents()
        assert _keys(chart).count("hostProbe") == 1, f"组件被重复挂载：{_keys(chart)}"

    def test_add_twice_is_idempotent(self, make):
        chart = _chart(make)
        probe = HostProbe(chart)
        chart.addComponent(probe)
        chart.addComponent(probe)
        assert _keys(chart).count("hostProbe") == 1

    def test_none_is_ignored(self, make):
        chart = _chart(make)
        chart.addComponent(None)
        assert "hostProbe" not in _keys(chart)

    def test_layout_and_paint_still_invoked(self, make):
        """挂上去就得真的参与布局与绘制，否则等于没挂。"""
        chart = _chart(make)
        probe = HostProbe(chart)
        chart.addComponent(probe)
        chart._layout_all(force=True)
        QApplication.processEvents()
        assert probe.layout_calls >= 1

        chart.show()  # 隐藏控件 repaint() 不走 paintEvent
        QApplication.processEvents()
        chart.repaint()
        QApplication.processEvents()
        assert probe.paint_calls >= 1

    def test_coexists_with_option_components(self, make):
        chart = _chart(make, toolbox={"feature": ["restore"]})
        probe = HostProbe(chart)
        chart.addComponent(probe)
        chart.setOption({"title": {"text": "z"}})
        QApplication.processEvents()

        keys = _keys(chart)
        assert "hostProbe" in keys
        assert "toolbox" in keys, f"option 组件应照常重建：{keys}"


class TestRemoveComponent:
    def test_remove_returns_true_and_detaches(self, make):
        chart = _chart(make)
        probe = HostProbe(chart)
        chart.addComponent(probe)

        assert chart.removeComponent(probe) is True
        assert probe not in chart.components
        assert probe.disposed == 1, "摘除时应调用组件的 dispose"

    def test_remove_unknown_returns_false(self, make):
        chart = _chart(make)
        assert chart.removeComponent(HostProbe(chart)) is False
        assert chart.removeComponent(None) is False

    def test_removed_component_does_not_come_back(self, make):
        chart = _chart(make)
        probe = HostProbe(chart)
        chart.addComponent(probe)
        chart.removeComponent(probe)
        chart.setOption({"title": {"text": "q"}})
        QApplication.processEvents()
        assert "hostProbe" not in _keys(chart)

    def test_remove_tolerates_component_without_dispose(self, make):
        class Bare:
            optionKey = "bareHost"

            def layout(self, rect):
                pass

            def hitTest(self, pos):
                return None

        chart = _chart(make)
        bare = Bare()
        chart.addComponent(bare)
        assert chart.removeComponent(bare) is True


class TestDisposeTearsDownComponents:
    def test_chart_dispose_disposes_components(self, make):
        chart = _chart(make, dataZoom=[{"type": "inside"}])
        probe = HostProbe(chart)
        chart.addComponent(probe)

        chart.dispose()

        assert chart.isDisposed()
        assert probe.disposed >= 1, "chart.dispose() 应一并解挂宿主挂件"
        assert getattr(chart, "_datazoom_filter", None) is None
        assert chart.components == []

    def test_option_component_dispose_does_not_remove_host(self, make):
        """option 组件被 dispose，宿主组件必须留下。"""
        chart = _chart(make, dataZoom=[{"type": "inside"}])
        probe = HostProbe(chart)
        chart.addComponent(probe)

        chart.setOption({**BASE, "title": {"text": "n"}})
        QApplication.processEvents()

        assert probe.disposed == 0
        assert probe in chart.components


class TestRegisterComponentRemainsTheOptionPath:
    def test_registered_component_rebuilt_from_option(self, make):
        """对照组：``registerComponent`` 那条路仍按 option 每次重建。

        注意 ``_rebuild`` 用的是**类自己的** ``optionKey``（缺省才回落到注册键），
        所以这里让类的 ``optionKey`` 与注册键一致。
        """

        class RegProbe(HostProbe):
            optionKey = "regProbe"

        registerComponent("regProbe", RegProbe)
        chart = _chart(make, regProbe={"tag": 1})
        first = next(
            c for c in chart.components if getattr(c, "optionKey", "") == "regProbe"
        )

        chart.setOption({**BASE, "regProbe": {"tag": 2}})
        QApplication.processEvents()
        second = next(
            c for c in chart.components if getattr(c, "optionKey", "") == "regProbe"
        )

        assert first is not second, "option 组件应被重建出新实例"
        assert second.opt == {"tag": 2}
        assert first.disposed >= 1, "被替换的 option 组件应走 dispose"
