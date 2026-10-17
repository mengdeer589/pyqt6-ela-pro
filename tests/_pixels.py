"""抓图后挑出「不透明像素集合」；平台不渲染文字时返回空集。

**为什么需要它**：`grab()`` 在 ``QT_QPA_PLATFORM=offscreen`` 下**只画控件形状、
不画文字**（像素全空）。仓库里没有任何地方配置 ``QT_QPA_PLATFORM``（
``pyproject.toml`` / ``pytest.ini`` 都没设），所以跑在哪个平台取决于跑测的环境：
本机是 ``windows``（画得出来），无头 CI 常常是 ``offscreen``（画不出来）。

这两个用例断言的是「颜色真的落到像素上」，本身是有价值的（它守的就是
``foregroundRole`` 那个静默失效的 bug），所以不该删；但在画不出文字的平台上
它只能给出**假失败**。这里统一探测一次并 ``skip``，而不是让 CI 变红。
"""

from __future__ import annotations

from PyQt6.QtGui import QColor


def opaque_colors(widget) -> set:
    """抓图，返回所有不透明像素的颜色名集合。

    :returns: 空集 = 这个平台画不出任何东西（offscreen），调用方应 skip
    """
    image = widget.grab().toImage()
    return {
        image.pixelColor(x, y).name()
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 200
    }


def skip_if_no_pixels(colors: set, reason: str = "") -> None:
    """``colors`` 为空就 skip —— 平台不渲染，而不是控件画错了。"""
    import pytest

    if not colors:
        pytest.skip(
            "当前 Qt 平台不渲染文字像素（offscreen），跳过像素级断言"
            + (f"：{reason}" if reason else "")
        )


def contrast_ok(bg: QColor, fg: QColor, minimum: int = 30) -> bool:
    """两个颜色明度差是否够（用于「有底色就该看得见」这类断言）。"""
    return abs(bg.lightness() - fg.lightness()) >= minimum
