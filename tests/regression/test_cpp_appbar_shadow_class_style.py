"""``ElaAppBar`` 不得把 ``CS_DROPSHADOW`` 写到共享窗口类。

``SetClassLong(..., GCL_STYLE, ... | CS_DROPSHADOW)`` 是类级写入：任一
``Qt::Tool`` appbar 窗口 show 后会污染同类的 tooltip / 浮层。正确做法是
逐 HWND 的 ``ElaWinShadowHelper::setWindowShadow``（``DwmExtendFrameIntoClientArea``）。
"""

from __future__ import annotations

import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_APPBAR = (
    _ROOT / "PyElaWidgetTools" / "ElaWidgetTools" / "ElaWidgetTools" / "ElaAppBar.cpp"
)


def test_appbar_never_writes_class_drop_shadow():
    if not _APPBAR.is_file():  # pragma: no cover - 子模块未检出
        pytest.skip("PyElaWidgetTools 子模块未检出")
    text = _APPBAR.read_text(encoding="utf-8")
    assert "CS_DROPSHADOW" not in text, (
        "ElaAppBar 又把 CS_DROPSHADOW 写到共享窗口类了；应改用逐 HWND 的 "
        "setWindowShadow()"
    )
    assert "setWindowShadow" in text
