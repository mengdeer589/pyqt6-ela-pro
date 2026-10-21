"""卡片封面缺图降级（「进度与反馈」页）。

`ElaPromotionCard` 四个文字色写死 `Qt::white`（上游设计：图片上的白字），
封面图一旦缺失，浅色主题下白字落在近白页面上完全不可读（实机截图暴露过）。
所以示例侧自查回退：缺图给深色占位图，且占位图最亮处也必须能承载白字。

`ExamplePage._addInfoText` 建的是 `ElaText`（PlainText），断言按控件文本做。
"""

from __future__ import annotations

import os

from PyQt6ElaWidgetTools import ElaPromotionCard, ElaText

from pyqt6_ela_pro.example.base_page import _res
from pyqt6_ela_pro.example.progress_feedback_page import (
    ProgressFeedbackPage,
    _card_pixmap,
    _placeholder_card_pixmap,
)

#: 占位图底色亮度上限（WCAG 4.5:1 反解，白字相对亮度 = 1.0）
_WHITE_TEXT_MAX_LUMINANCE = 0.1833


def _relative_luminance(color) -> float:
    def channel(value: int) -> float:
        srgb = value / 255.0
        return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def test_missing_asset_falls_back_to_placeholder(qapp):
    pixmap = _card_pixmap("file-that-does-not-exist.png")
    assert not pixmap.isNull()


def test_placeholder_keeps_white_text_readable(qapp):
    image = _placeholder_card_pixmap().toImage()
    worst = 0.0
    for y in range(0, image.height(), 4):
        for x in range(0, image.width(), 4):
            worst = max(worst, _relative_luminance(image.pixelColor(x, y)))
    contrast = 1.05 / (worst + 0.05)
    assert worst <= _WHITE_TEXT_MAX_LUMINANCE, (
        f"占位图最亮处白字对比度仅 {contrast:.2f}:1"
    )


def test_demo_card_always_gets_a_cover(make):
    page = make(ProgressFeedbackPage)
    cards = page.findChildren(ElaPromotionCard)
    assert cards, "06 节应演示 ElaPromotionCard"
    assert not cards[0].getCardPixmap().isNull()
    if not os.path.exists(_res("miku.png")):
        texts = [child.text() for child in page.findChildren(ElaText)]
        assert any("占位图" in text for text in texts), "缺图时应给出降级说明行"
