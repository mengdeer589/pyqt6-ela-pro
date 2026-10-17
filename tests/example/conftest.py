"""示例页守卫的公共夹具。

示例页内容是**惰性构建**的（`ExamplePage.buildDemoContent()`，首次显示时建；
启动后由 `__main__` 的后台链逐页预热）。测试里没有真实显示，所以在 `make(SomePage)`
之后显式补一次构建，让既有守卫（它们假设「构造完内容就在」）保持原语义。

不经 `make` 直接 `SomePage()` 且不 `show()` 的用例，需要自己调 `buildDemoContent()`
（`show()` 的用例由 `showEvent` 自动构建，与真实路径一致）。
"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro.example.base_page import ExamplePage


class _PageBuildingFactory:
    """``make`` 的薄包装：造出示例页时顺手构建演示内容。"""

    def __init__(self, factory) -> None:
        self._factory = factory

    def __call__(self, cls, *args, **kwargs):
        obj = self._factory(cls, *args, **kwargs)
        if isinstance(obj, ExamplePage):
            obj.buildDemoContent()
        return obj

    def __getattr__(self, name):
        return getattr(self._factory, name)


@pytest.fixture
def make(qt_cleanup):
    """示例守卫版 ``make``：示例页造出来即构建内容（见模块 docstring）。"""
    return _PageBuildingFactory(qt_cleanup)
