"""回归测试（第六批）：全库审查确认的崩溃面修复。

覆盖：单次定时器异常/回收、主题槽异常、ContentSlot 死 parent、tooltip 死缓存、
Spotlight 目标销毁、图标 None、emit 后销毁 sender、binder 迟到收尾、仪表盘坏数值、
异步表格坏单元格、图表超大字号。
"""

from __future__ import annotations

import warnings

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QPointF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QResizeEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro._internal import _ThemeAwareMixin, single_shot_on
from pyqt6_ela_pro._ownership import ContentSlot, ElaWidgetOwnershipType
from pyqt6_ela_pro.ela_chip import ElaChip
from pyqt6_ela_pro.ela_dashboard_gauge import ElaDashboardGauge
from pyqt6_ela_pro.ela_dropdown_button import ElaDropDownButton
from pyqt6_ela_pro.ela_info_badge import ElaInfoBadge
from pyqt6_ela_pro.ela_pagination import ElaPagination
from pyqt6_ela_pro.ela_rating_control import ElaRatingControl
from pyqt6_ela_pro.ela_selector_bar import ElaSelectorBar
from pyqt6_ela_pro.ela_split_button import ElaSplitButton
from pyqt6_ela_pro.ela_spotlight import ElaSpotlight
from pyqt6_ela_pro.ela_steps import ElaSteps
from pyqt6_ela_pro.ela_timeline import ElaTimeline
from pyqt6_ela_pro.table_view import ElaDataTable


def _mouse(kind: QEvent.Type, x: float, y: float) -> QMouseEvent:
    pos = QPointF(x, y)
    return QMouseEvent(
        kind,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


class TestSingleShotOn:
    def test_slot_exception_is_swallowed(self, qapp):
        w = QWidget()
        hits = []

        def boom():
            hits.append(1)
            raise ValueError("slot boom")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            single_shot_on(w, 0, boom)
            QTest.qWait(30)
            qapp.processEvents()
        assert hits == [1], "槽未被调用"

    def test_timer_and_closure_are_recycled(self, qapp):
        w = QWidget()
        for _ in range(5):
            single_shot_on(w, 0, lambda: None)
        QTest.qWait(30)
        qapp.processEvents()
        assert w.findChildren(QTimer) == [], "单次定时器未随触发回收"


class TestThemeSlot:
    def test_theme_slot_exception_does_not_abort(self, qapp):
        class Bad(_ThemeAwareMixin, QWidget):
            def _onThemeChanged(self, mode):
                raise ValueError("theme boom")

        old = eTheme.getThemeMode()
        w = Bad()
        try:
            eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
        finally:
            eTheme.setThemeMode(old)
            w.deleteLater()
            qapp.processEvents()


class TestOwnershipSafety:
    def test_release_with_dead_original_parent(self, qapp):
        host = QWidget()
        parent = QWidget()
        content = QWidget(parent)
        slot = ContentSlot(host)
        assert slot.setWidget(content, ElaWidgetOwnershipType.Reparented)
        sip.delete(parent)
        slot.releaseWidget()  # 不得抛
        assert not sip.isdeleted(content)

    def test_set_widget_rejects_dead_wrapper(self, qapp):
        host = QWidget()
        content = QWidget(host)
        sip.delete(content)
        slot = ContentSlot(host)
        assert slot.setWidget(content) is False


class TestTooltipSafety:
    def test_dead_cached_tooltip_is_replaced(self, qapp):
        from pyqt6_ela_pro import tooltips

        w = QWidget()
        tooltips.set_tooltip(w, "a")
        tip = tooltips._tooltip_dict[w]
        sip.delete(tip)
        tooltips.set_tooltip(w, "b")  # 不得抛
        tooltips.remove_tooltip(w)
        w.deleteLater()
        qapp.processEvents()


class TestSpotlightDeadTarget:
    def test_resize_after_target_destroyed(self, qapp):
        host = QWidget()
        host.resize(400, 300)
        target = QWidget(host)
        spot = ElaSpotlight(host)
        spot.setSteps([ElaSpotlight.SpotlightStep(target, "t", "c")])
        spot.start()
        sip.delete(target)
        QApplication.sendEvent(host, QResizeEvent(host.size(), host.size()))
        spot.finish()
        host.deleteLater()
        qapp.processEvents()


class TestIconNone:
    def test_split_button(self, qapp):
        w = ElaSplitButton("x")
        w.setElaIcon(None)
        w.grab()

    def test_dropdown_button(self, qapp):
        w = ElaDropDownButton("x")
        w.setElaIcon(None)
        w.grab()

    def test_info_badge(self, qapp):
        w = ElaInfoBadge()
        w.setBadgeMode(ElaInfoBadge.ElaBadgeModeType.Icon)
        w.setElaIcon(None)
        w.grab()

    def test_timeline(self, qapp):
        w = ElaTimeline()
        w.addItem(ElaTimeline.TimelineItem("t", "c", "ts", icon=None))
        w.grab()


class TestEmitThenDeleteSender:
    def test_selector_bar(self, qapp):
        bar = ElaSelectorBar()
        bar.addItems(["a", "b"])
        bar.setSelectedIndex(0)
        bar.itemActivated.connect(lambda *_: sip.delete(bar))
        bar._activateIndex(1)

    def test_chip_closed(self, qapp):
        chip = ElaChip("x")
        chip.closed.connect(lambda: sip.delete(chip))
        chip._finish_close()

    def test_split_button(self, qapp):
        button = ElaSplitButton("x")
        button.resize(100, 30)
        button.clicked.connect(lambda: sip.delete(button))
        button.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 5, 5))
        button.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 5, 5))

    def test_pagination(self, qapp):
        w = ElaPagination()
        w.setTotalPages(5)
        w.currentPageChanged.connect(lambda _p: sip.delete(w))
        w.setCurrentPage(2)

    def test_steps(self, qapp):
        w = ElaSteps()
        w.step_titles = ["a", "b"]
        w.currentStepChanged.connect(lambda _n: sip.delete(w))
        w.setCurrentStep(1)

    def test_rating(self, qapp):
        w = ElaRatingControl()
        w.ratingChanged.connect(lambda _n: sip.delete(w))
        w.setRating(2)


class TestBinderLateFinish:
    def test_chat_deleted_before_turn_finished(self, qapp):
        from pyqt6_ela_pro.chat import ElaChatStreamBinder, ElaChatWidget

        class Worker(QObject):
            turnFinished = pyqtSignal(object)

        chat = ElaChatWidget()
        binder = ElaChatStreamBinder(chat)
        worker = Worker()
        worker.turnFinished.connect(binder.finish)
        sip.delete(chat)
        binder._turn_token = 1
        binder._flow.begin_turn()
        worker.turnFinished.emit(1)  # 不得 abort


class TestGaugeBadNumbers:
    @pytest.mark.parametrize(
        "call",
        [
            lambda w: w.setMinimum(float("nan")),
            lambda w: w.setMaximum(float("inf")),
            lambda w: w.setValue(float("nan")),
            lambda w: w.setMajorTickCount(10.5),
            lambda w: w.setMinorTickCount(2.5),
            lambda w: w.setStartAngle(float("nan")),
            lambda w: w.setSpanAngle(float("nan")),
            lambda w: w.setArcWidth(float("nan")),
            lambda w: w.setValuePixelSize(2**31),
            lambda w: w.setDecimals(2.5),
            lambda w: w.setDangerPercent(float("nan")),
        ],
    )
    def test_bad_value_does_not_crash_paint(self, qapp, call):
        w = ElaDashboardGauge()
        call(w)
        w.grab()
        w.deleteLater()
        qapp.processEvents()


class TestAsyncTableBadCell:
    def test_bad_str_is_guarded(self, qapp):
        class Bad:
            def __str__(self):
                raise ValueError("bad cell")

        w = ElaDataTable()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            w.setTableDataAsync([["h"], [Bad()]])
            QTest.qWait(200)
            qapp.processEvents()
        w.deleteLater()
        qapp.processEvents()


class TestChartHugeFont:
    def test_huge_font_size_is_rejected(self, qapp):
        from pyqt6_ela_pro.charts import ElaChartWidget

        chart = ElaChartWidget()
        chart.resize(400, 300)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {"type": "value"},
                "series": [{"type": "line", "data": [1, 2]}],
            }
        )
        assert chart.setAxisLabelStyle("x", fontSize=1e10) is False
        chart.resize(420, 300)
        chart.grab()
        chart.deleteLater()
        qapp.processEvents()
