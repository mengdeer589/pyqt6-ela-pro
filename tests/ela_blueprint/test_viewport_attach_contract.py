"""GL 视口的「晚挂」契约：给已显示的窗口挂原生子窗口会重建顶层 HWND（窗口闪一下）。

``ElaBlueprintCanvas`` 的 GL 视口是 ``QOpenGLWidget``（**原生子窗口**）。窗口已经
``show()`` 之后再把它挂上去，Windows/Qt 会重建顶层 HWND（实测类名从 ``QWindowIcon``
变成 ``QWindowOwnDCIcon``，视觉上主窗口闪一次 —— 见 ``docs/performance.md``）。

真实重建只会在 win32 桌面 + GL 可用时发生，测试里**不真造** ``QOpenGLWidget``
（offscreen 下 GL 设施不可用，AGENTS 也要求不断言视口类型）：这里只守住「已显示窗口 →
警告一次 / 隐藏窗口 → 不警告」这条契约。
"""

from __future__ import annotations

import logging

import pytest
from PyQt6.QtWidgets import QWidget

from pyqt6_ela_pro.blueprint import viewport as viewport_module
from pyqt6_ela_pro.blueprint.canvas import ElaBlueprintCanvas

_WARNING_MARK = "原生子窗口"


class _DummyGLViewport(QWidget):
    """``_GLViewport`` 的替身（避免在测试里创建真实 GL 上下文）。"""

    def __init__(self, canvas):
        super().__init__(canvas)


@pytest.fixture
def forced_gl(monkeypatch):
    monkeypatch.setattr(viewport_module, "gl_available", lambda: True)
    monkeypatch.setattr(viewport_module, "_GLViewport", _DummyGLViewport)


def _warnings(caplog) -> list[str]:
    return [rec.message for rec in caplog.records if _WARNING_MARK in rec.message]


def test_warns_when_window_already_visible(forced_gl, qapp, caplog, make):
    window = make(QWidget)
    window.show()
    qapp.processEvents()

    with caplog.at_level(logging.WARNING):
        make(ElaBlueprintCanvas, None, window)

    assert len(_warnings(caplog)) == 1


def test_no_warning_when_window_hidden(forced_gl, caplog, make):
    with caplog.at_level(logging.WARNING):
        make(ElaBlueprintCanvas)

    assert _warnings(caplog) == []


def test_no_warning_for_raster_viewport(monkeypatch, qapp, caplog, make):
    """软件视口不是原生子窗口，不提醒。"""
    monkeypatch.setattr(viewport_module, "gl_available", lambda: False)
    window = make(QWidget)
    window.show()
    qapp.processEvents()

    with caplog.at_level(logging.WARNING):
        make(ElaBlueprintCanvas, None, window)

    assert _warnings(caplog) == []


def test_default_is_raster(monkeypatch, make):
    """GL 是**显式选择**：``ELABLUEPRINT_GL`` 未设时用软件视口。

    （默认不用 GL 的原因：原生子窗口挂到已显示的窗口上会重建顶层 HWND，窗口闪一下。
    见 ``docs/performance.md``。）
    """
    monkeypatch.delenv("ELABLUEPRINT_GL", raising=False)
    monkeypatch.delenv("UIKIT_BLUEPRINT_GL", raising=False)
    monkeypatch.setattr(viewport_module, "_GL_STATE", None)

    canvas = make(ElaBlueprintCanvas)

    assert isinstance(canvas._viewport, viewport_module._RasterViewport)
