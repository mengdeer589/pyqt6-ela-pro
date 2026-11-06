"""回归测试（第十二批）：dispose 守卫、焦点与键盘可达性、禁用态。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro.charts import ElaChartWidget
from pyqt6_ela_pro.ela_chip import ElaChip
from pyqt6_ela_pro.ela_pagination import ElaPagination
from pyqt6_ela_pro.ela_rating_control import ElaRatingControl
from pyqt6_ela_pro.ela_split_button import ElaSplitButton
from pyqt6_ela_pro.ela_upload_area import ElaUploadArea


def _key(widget, key):
    QApplication.sendEvent(
        widget, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    )


class TestChartDisposeGuards:
    def test_mutators_raise_after_dispose(self, qapp):
        chart = ElaChartWidget()
        chart.resize(400, 300)
        chart.setOption(
            {
                "animation": False,
                "xAxis": {"type": "category", "data": ["a", "b"]},
                "yAxis": {"type": "value"},
                "dataZoom": [{"type": "slider"}],
                "series": [{"type": "line", "data": [1, 2]}],
            }
        )
        chart.dispose()
        calls = [
            lambda: chart.updateSeries({"data": [3, 4]}),
            lambda: chart.setChartTheme("matlab"),
            lambda: chart.setInteractive(False),
            lambda: chart.setInteractionEnabled("tooltip", False),
            lambda: chart.setWheelZoomEnabled(False),
            lambda: chart.setDragMode("pan"),
            lambda: chart.setDoubleClickReset(False),
            lambda: chart.resetView(),
            lambda: chart.zoomStep(0.5),
            lambda: chart.addComponent(object()),
            lambda: chart.removeComponent(object()),
        ]
        for call in calls:
            with pytest.raises(RuntimeError):
                call()
        qapp.processEvents()


class TestKeyboardReachability:
    def test_focus_policies(self, qapp):
        for widget in (
            ElaChip("x"),
            ElaPagination(),
            ElaRatingControl(),
            ElaUploadArea(),
            ElaSplitButton("x"),
        ):
            assert widget.focusPolicy() != Qt.FocusPolicy.NoFocus
            widget.deleteLater()
        qapp.processEvents()

    def test_chip_space_activates(self, qapp):
        chip = ElaChip("x")
        hits = []
        chip.clicked.connect(lambda: hits.append(1))
        _key(chip, Qt.Key.Key_Space)
        assert hits == [1]
        chip.deleteLater()
        qapp.processEvents()

    def test_pagination_right_moves_page(self, qapp):
        pager = ElaPagination()
        pager.setTotalPages(5)
        pager.setCurrentPage(2)
        _key(pager, Qt.Key.Key_Right)
        assert pager.currentPage() == 3
        pager.deleteLater()
        qapp.processEvents()

    def test_rating_right_increases(self, qapp):
        rating = ElaRatingControl()
        rating.setRating(2)
        _key(rating, Qt.Key.Key_Right)
        assert rating.rating() == 2.5
        rating.deleteLater()
        qapp.processEvents()

    def test_upload_space_opens_dialog(self, qapp, monkeypatch):
        area = ElaUploadArea()
        calls = []
        monkeypatch.setattr(area, "_openFileDialog", lambda: calls.append(1))
        _key(area, Qt.Key.Key_Space)
        assert calls == [1]
        area.deleteLater()
        qapp.processEvents()

    def test_split_space_clicks(self, qapp):
        button = ElaSplitButton("x")
        hits = []
        button.clicked.connect(lambda: hits.append(1))
        _key(button, Qt.Key.Key_Space)
        assert hits == [1]
        button.deleteLater()
        qapp.processEvents()


class TestChipDisabledVisual:
    def test_disabled_is_dimmed(self, qapp):
        chip = ElaChip("x")
        chip.resize(100, 30)
        enabled = chip.grab().toImage()
        chip.setEnabled(False)
        disabled = chip.grab().toImage()
        assert enabled != disabled
        chip.deleteLater()
        qapp.processEvents()
