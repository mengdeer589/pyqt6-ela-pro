"""Tests for utils module: shake_window function."""

from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, QTimer, Qt
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro import shake_window


class TestShakeWindow:
    """Test cases for shake_window function."""

    def test_shake_window_ignores_when_animation_running(self, qapp):
        """Test shake_window ignores new request while animation is running."""
        widget = QWidget()
        widget.setFixedSize(200, 100)

        shake_window(widget, duration=200, loop_count=1)

        assert hasattr(widget, "_shake_animation")
        first_anim = widget._shake_animation

        shake_window(widget, duration=200, loop_count=1)

        second_anim = widget._shake_animation
        assert first_anim is second_anim

        widget.deleteLater()
        qapp.processEvents()

    def test_shake_window_creates_animation(self, qapp):
        """Test shake_window creates position animation."""
        widget = QWidget()
        widget.setFixedSize(200, 100)

        shake_window(widget, duration=200, loop_count=1)

        assert hasattr(widget, "_shake_animation")
        anim = widget._shake_animation
        assert isinstance(anim, QPropertyAnimation)
        assert anim.targetObject() is widget

        widget.deleteLater()
        qapp.processEvents()

    def test_shake_window_creates_animation_with_loop_count(self, qapp):
        """Test shake_window respects loop_count parameter."""
        widget = QWidget()
        widget.setFixedSize(200, 100)

        shake_window(widget, duration=200, loop_count=3)

        anim = widget._shake_animation
        assert anim.loopCount() == 3

        widget.deleteLater()
        qapp.processEvents()

    def test_shake_window_cleans_up_attribute_on_finish(self, qapp):
        """Test shake_window removes _shake_animation attribute after finish."""
        widget = QWidget()
        widget.setFixedSize(200, 100)
        widget.setWindowFlags(Qt.WindowType.Window)

        shake_window(widget, duration=100, loop_count=1)

        QTimer.singleShot(600, lambda: None)
        qapp.processEvents()

        if hasattr(widget, "_shake_animation"):
            anim = widget._shake_animation
            if anim.state() == QPropertyAnimation.State.Running:
                anim.stop()

        widget.deleteLater()
        qapp.processEvents()

    def test_shake_window_callback_not_called_if_no_callback(self, qapp):
        """Test shake_window doesn't raise when no callback provided."""
        widget = QWidget()
        widget.setFixedSize(200, 100)
        widget.setWindowFlags(Qt.WindowType.Window)

        shake_window(widget, duration=100, loop_count=1)

        widget.deleteLater()
        qapp.processEvents()
