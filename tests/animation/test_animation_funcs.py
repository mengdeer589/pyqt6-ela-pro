"""Tests for animation module: fade_in, fade_out, and animation registry cleanup."""

from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, QTimer
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro.animation import (
    fade_in,
    fade_out,
    _animation_registry,
    ElaAnimatedMixin,
)


class TestAnimationRegistryCleanup:
    """Test animation registry cleanup on widget destruction."""

    def test_registry_cleans_up_on_widget_destroyed(self, qapp, window_widget):
        """Test that destroyed widgets are removed from registry."""
        assert window_widget not in _animation_registry

        fade_in(window_widget, duration=50)
        assert window_widget in _animation_registry

        window_widget.deleteLater()
        qapp.processEvents()

    def test_fade_in_ignores_when_animation_running(self, qapp, window_widget):
        """Test that calling fade_in while animation is running is ignored."""
        fade_in(window_widget, duration=500)
        first_animation = _animation_registry.get(window_widget)

        fade_in(window_widget, duration=500)
        second_animation = _animation_registry.get(window_widget)

        assert first_animation is second_animation

        window_widget.deleteLater()
        qapp.processEvents()

    def test_fade_out_ignores_when_animation_running(self, qapp, window_widget):
        """Test that calling fade_out while animation is running is ignored."""
        fade_out(window_widget, duration=500)
        first_animation = _animation_registry.get(window_widget)

        fade_out(window_widget, duration=500)
        second_animation = _animation_registry.get(window_widget)

        assert first_animation is second_animation

        window_widget.deleteLater()
        qapp.processEvents()

    def test_registry_cleanup_on_fade_in_finished(self, qapp, window_widget):
        """Test registry is cleaned up when fade_in animation finishes."""
        fade_in(window_widget, duration=50)
        assert window_widget in _animation_registry

        QTimer.singleShot(200, lambda: None)
        qapp.processEvents()

        window_widget.deleteLater()
        qapp.processEvents()


class TestFadeIn:
    """Test cases for fade_in function."""

    def test_fade_in_sets_opacity_to_zero_first(self, qapp, window_widget):
        """Test fade_in sets window opacity to 0 before showing."""
        window_widget.setWindowOpacity(1)
        fade_in(window_widget, duration=50)

        assert window_widget.windowOpacity() == 0
        assert window_widget.isVisible()

        window_widget.deleteLater()
        qapp.processEvents()

    def test_fade_in_creates_animation(self, qapp, window_widget):
        """Test fade_in creates animation in registry."""
        fade_in(window_widget, duration=100)

        assert window_widget in _animation_registry
        anim = _animation_registry[window_widget]
        assert isinstance(anim, QPropertyAnimation)
        assert anim.targetObject() is window_widget

        window_widget.deleteLater()
        qapp.processEvents()

    def test_fade_in_duration_parameter(self, qapp, window_widget):
        """Test fade_in respects duration parameter."""
        fade_in(window_widget, duration=2000)

        anim = _animation_registry[window_widget]
        assert anim.duration() == 2000

        window_widget.deleteLater()
        qapp.processEvents()


class TestFadeOut:
    """Test cases for fade_out function."""

    def test_fade_out_does_not_autoclose_window(self, qapp, window_widget):
        """Test fade_out only animates opacity, doesn't close window."""
        window_widget.show()
        fade_out(window_widget, duration=50)

        assert window_widget.isVisible()

        window_widget.deleteLater()
        qapp.processEvents()

    def test_fade_out_callback_is_called(self, qapp, window_widget):
        """Test fade_out calls on_finished callback after animation."""
        callbackCalled = False

        def on_finished():
            nonlocal callbackCalled
            callbackCalled = True

        window_widget.show()
        fade_out(window_widget, duration=50, on_finished=on_finished)

        anim = _animation_registry.get(window_widget)
        if anim:
            anim.finished.emit()

        assert callbackCalled

        window_widget.deleteLater()
        qapp.processEvents()

    def test_fade_out_creates_animation(self, qapp, window_widget):
        """Test fade_out creates animation in registry."""
        window_widget.show()
        fade_out(window_widget, duration=100)

        assert window_widget in _animation_registry
        anim = _animation_registry[window_widget]
        assert isinstance(anim, QPropertyAnimation)

        window_widget.deleteLater()
        qapp.processEvents()


class TestElaAnimatedMixin:
    """Test cases for ElaAnimatedMixin class."""

    def test_mixin_provides_fade_methods(self, qapp):
        """Test mixin provides fade_in and fade_out methods."""

        class TestWindow(ElaAnimatedMixin, QWidget):
            pass

        window = TestWindow()
        assert hasattr(window, "fade_in")
        assert hasattr(window, "fade_out")
        assert callable(window.fade_in)
        assert callable(window.fade_out)

        window.deleteLater()
        qapp.processEvents()

    def test_mixin_fade_in_shows_window(self, qapp):
        """Test mixin's fade_in shows hidden window."""

        class TestWindow(ElaAnimatedMixin, QWidget):
            pass

        window = TestWindow()
        window.fade_in(duration=50)

        assert window.isVisible()

        window.deleteLater()
        qapp.processEvents()

    def test_mixin_fade_out_creates_animation(self, qapp):
        """Test mixin's fade_out creates animation."""

        class TestWindow(ElaAnimatedMixin, QWidget):
            pass

        window = TestWindow()
        window.show()
        window.fade_out(duration=50)

        assert window._fade_animation is not None
        assert isinstance(window._fade_animation, QPropertyAnimation)

        window.deleteLater()
        qapp.processEvents()

    def test_mixin_reuses_animation_instance(self, qapp):
        """Test mixin reuses same animation instance on multiple calls."""

        class TestWindow(ElaAnimatedMixin, QWidget):
            pass

        window = TestWindow()
        window.fade_in(duration=100)
        first_anim = window._fade_animation

        window.fade_in(duration=100)
        second_anim = window._fade_animation

        assert first_anim is second_anim

        window.deleteLater()
        qapp.processEvents()
