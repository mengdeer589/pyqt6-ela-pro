"""拖选超出可见带时的自动滚动：独立查看器与嵌入（宿主滚动区）两条路径。"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QFocusEvent, QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QScrollArea, QVBoxLayout, QWidget
from _qthelpers import wait_until

from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer

_LONG_MD = "\n\n".join(
    f"## Section {i}\n\n" + "lorem ipsum dolor sit amet " * 12 for i in range(120)
)


def _send(viewport, event_type, local, button, buttons):
    QApplication.sendEvent(
        viewport,
        QMouseEvent(
            event_type,
            QPointF(local),
            QPointF(viewport.mapToGlobal(local)),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def _press(viewport, local):
    _send(
        viewport,
        QEvent.Type.MouseButtonPress,
        local,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
    )


def _move(viewport, local):
    _send(
        viewport,
        QEvent.Type.MouseMove,
        local,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
    )


def _release(viewport, local):
    _send(
        viewport,
        QEvent.Type.MouseButtonRelease,
        local,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
    )


def _standalone(qapp, make):
    viewer = make(ElaMarkdownViewer)
    viewer.resize(600, 400)
    viewer.setStickToBottom(False)
    viewer.setMarkdown(_LONG_MD)
    viewer.show()
    bar = viewer.textBrowser().verticalScrollBar()
    assert wait_until(qapp, lambda: bar.maximum() > 0)
    return viewer, bar


class TestSelectionAutoScroll:
    def test_drag_below_scrolls_and_extends_selection(self, qapp, make):
        viewer, bar = _standalone(qapp, make)
        viewport = viewer.textBrowser().viewport()
        _press(viewport, QPoint(100, 100))
        _move(viewport, QPoint(100, viewport.height() + 60))

        assert wait_until(qapp, lambda: bar.value() > 0, timeout_ms=1500)
        before = len(viewer.textBrowser().textCursor().selectedText())
        assert wait_until(
            qapp,
            lambda: len(viewer.textBrowser().textCursor().selectedText()) > before,
            timeout_ms=1000,
        )

        _release(viewport, QPoint(100, viewport.height() + 60))
        assert not viewer._drag_scroll_timer.isActive()
        value = bar.value()
        QTest.qWait(120)
        assert bar.value() == value

    def test_drag_above_scrolls_up(self, qapp, make):
        viewer, bar = _standalone(qapp, make)
        bar.setValue(bar.maximum() // 2)
        start = bar.value()
        viewport = viewer.textBrowser().viewport()
        _press(viewport, QPoint(100, 100))
        _move(viewport, QPoint(100, -80))
        assert wait_until(qapp, lambda: bar.value() < start, timeout_ms=1500)
        _release(viewport, QPoint(100, -80))

    def test_drag_inside_viewport_does_not_scroll(self, qapp, make):
        viewer, bar = _standalone(qapp, make)
        start = bar.value()
        viewport = viewer.textBrowser().viewport()
        _press(viewport, QPoint(100, 100))
        _move(viewport, QPoint(100, 220))
        assert not viewer._drag_scroll_timer.isActive()
        QTest.qWait(120)
        assert bar.value() == start
        _release(viewport, QPoint(100, 220))

    def test_focus_out_stops_autoscroll(self, qapp, make):
        viewer, bar = _standalone(qapp, make)
        viewport = viewer.textBrowser().viewport()
        _press(viewport, QPoint(100, 100))
        _move(viewport, QPoint(100, viewport.height() + 60))
        assert wait_until(qapp, lambda: viewer._drag_scroll_timer.isActive())
        QApplication.sendEvent(viewer.textBrowser(), QFocusEvent(QEvent.Type.FocusOut))
        assert not viewer._drag_scroll_timer.isActive()
        _release(viewport, QPoint(100, viewport.height() + 60))

    def test_embedded_drag_scrolls_host_area(self, qapp, make):
        outer = make(QScrollArea)
        outer.setWidgetResizable(True)
        holder = make(QWidget)
        layout = QVBoxLayout(holder)
        viewer = make(ElaMarkdownViewer, holder)
        viewer.setEmbeddedMode(True)
        viewer.setStickToBottom(False)
        layout.addWidget(viewer)
        layout.addStretch(1)
        outer.setWidget(holder)
        outer.resize(620, 420)
        outer.show()
        viewer.setMarkdown(_LONG_MD)

        bar = outer.verticalScrollBar()
        assert wait_until(qapp, lambda: bar.maximum() > 0)
        viewport = viewer.textBrowser().viewport()
        _press(viewport, QPoint(100, 60))
        outside = outer.viewport().mapToGlobal(
            QPoint(100, outer.viewport().height() + 80)
        )
        _move(viewport, viewport.mapFromGlobal(outside))

        assert wait_until(qapp, lambda: bar.value() > 0, timeout_ms=1500)
        selected = len(viewer.textBrowser().textCursor().selectedText())
        assert wait_until(
            qapp,
            lambda: len(viewer.textBrowser().textCursor().selectedText()) > selected,
            timeout_ms=1000,
        )
        _release(viewport, viewport.mapFromGlobal(outside))
        assert not viewer._drag_scroll_timer.isActive()
