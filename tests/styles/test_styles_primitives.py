"""``pyqt6_ela_pro._styles`` 的禁 QSS 原语（内部模块，直接测行为）。"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPainter, QPalette
from PyQt6.QtWidgets import QFrame, QTextBrowser, QWidget

from pyqt6_ela_pro._styles import (
    BareButton,
    ColorText,
    FlatIconButton,
    paintRoundedCard,
    setPlainFrame,
    setSolidBackground,
    setTextBaseColor,
)

from _pixels import opaque_colors, skip_if_no_pixels


def _px(widget, x, y):
    """控件抓图某点颜色（按抓图 DPR 换算，避免高 DPI 下采样错位）。"""
    grab = widget.grab()
    dpr = grab.devicePixelRatio()
    return grab.toImage().pixelColor(round(x * dpr), round(y * dpr)).name()


class TestColorText:
    def test_sets_palette_and_keeps_it_after_paint(self, qapp, make):
        label = make(ColorText, "abc")
        label.setTextColor("#0000ff")
        label.grab()
        assert label.textColor().name() == "#0000ff"
        assert label.palette().color(QPalette.ColorRole.WindowText).name() == "#0000ff"

    def test_heals_palette_reset_on_paint(self, qapp, make):
        """ElaText 的主题信号会把 palette 刷回 BasicText，绘制前必须自愈。"""
        label = make(ColorText, "abc")
        label.setTextColor("#0000ff")
        palette = label.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#123456"))
        label.setPalette(palette)
        label.grab()
        assert label.palette().color(QPalette.ColorRole.WindowText).name() == "#0000ff"

    def test_none_restores_theme_behaviour(self, qapp, make):
        label = make(ColorText, "abc")
        label.setTextColor("#0000ff")
        label.setTextColor(None)
        assert label.textColor() is None
        label.grab()  # 回落到 ElaText 绘制，不应抛异常

    def test_parent_only_constructor_overload(self, qapp, make):
        """``ColorText(parent)`` / ``ColorText(text, parent)`` 两个重载都要能用。"""
        parent = make(QWidget)
        assert make(ColorText, parent).text() == ""
        assert make(ColorText, "标题", parent).text() == "标题"

    def test_constructor_accepts_color_and_pixel_size(self, qapp, make):
        label = make(ColorText, "abc", color="#0000ff", pixelSize=18)
        assert label.textColor().name() == "#0000ff"
        assert label.font().pixelSize() == 18

    def test_rendered_pixels_use_color(self, qapp, make):
        label = make(ColorText, "MMMM")
        label.setTextPixelSize(24)
        label.setTextColor("#0000ff")
        label.resize(160, 40)
        colors = opaque_colors(label)
        skip_if_no_pixels(colors)
        assert "#0000ff" in colors

    def test_paints_when_foreground_role_is_not_window_text(self, qapp, make):
        """``foregroundRole`` 不是 ``WindowText`` 时也必须真的画上色。

        踩过的坑：``ColorText`` 原先只往 palette 的 ``WindowText`` 写色。Ela 的控件
        树里同一个 ``ColorText`` 可能拿到别的前景色角色（实测
        ``_CollapsibleBlock`` 的标题标签是 ``8 = ButtonText``），于是
        ``textColor()`` 读回来是对的、``palette().color(WindowText)`` 也是对的，
        唯独**绘制走的那个角色**仍是主题的 BasicText —— 设了颜色却画成黑字，
        而且完全没有任何报错。是靠审批记录卡渲染出来「应该是绿色却是黑色」才定位到的。
        """
        label = make(ColorText, "MMMM")
        label.setTextPixelSize(24)
        label.setForegroundRole(QPalette.ColorRole.ButtonText)
        assert label.foregroundRole() != QPalette.ColorRole.WindowText
        label.setTextColor("#0000ff")
        assert label.palette().color(label.foregroundRole()).name() == "#0000ff"
        label.resize(160, 40)
        colors = opaque_colors(label)
        skip_if_no_pixels(colors)
        assert "#0000ff" in colors, sorted(colors)[:6]

    def test_heals_the_actual_role_after_theme_reset(self, qapp, make):
        """ElaText 的主题信号会刷回 BasicText —— 自愈也要刷**前景色角色**。"""
        label = make(ColorText, "abc")
        label.setForegroundRole(QPalette.ColorRole.ButtonText)
        label.setTextColor("#0000ff")
        palette = label.palette()
        role = label.foregroundRole()
        palette.setColor(role, QColor("#123456"))
        label.setPalette(palette)
        label.grab()
        assert label.palette().color(role).name() == "#0000ff"


class TestSolidBackground:
    def test_fills_with_color(self, qapp, make):
        container = make(QWidget)
        container.resize(60, 30)
        setSolidBackground(container, "#00ff00")
        container.show()
        qapp.processEvents()
        assert _px(container, 30, 15) == "#00ff00"


class TestTransparentTextBase:
    def test_browser_shows_parent_background(self, qapp, make):
        container = make(QWidget)
        container.resize(220, 120)
        setSolidBackground(container, "#ff0000")
        browser = make(QTextBrowser, container)
        browser.setPlainText("x")
        browser.setGeometry(10, 10, 200, 100)
        setTextBaseColor(browser, None)
        container.show()
        qapp.processEvents()
        assert browser.palette().color(QPalette.ColorRole.Base).alpha() == 0
        assert _px(container, 110, 100) == "#ff0000"


class TestTextBaseViewportPropagation:
    """``setTextBaseColor`` 必须把 ``Base`` 同时写到 **viewport** 上。

    ``QAbstractScrollArea`` 的视口带自己的显式 palette（``WA_SetPalette``），
    **不跟随**控件的 ``setPalette`` —— 只设控件时，视口自动填充用的还是首次
    解析出的旧色（换主题后聊天里的查看器留浅色横条就是这个：控件 palette 已
    是新色、视口没跟上）。
    """

    def test_viewport_palette_follows_updates(self, qapp, make):
        browser = make(QTextBrowser)
        setTextBaseColor(browser, "#ff0000")
        assert browser.palette().color(QPalette.ColorRole.Base).name() == "#ff0000"
        assert (
            browser.viewport().palette().color(QPalette.ColorRole.Base).name()
            == "#ff0000"
        )
        setTextBaseColor(browser, "#0000ff")
        assert browser.palette().color(QPalette.ColorRole.Base).name() == "#0000ff"
        assert (
            browser.viewport().palette().color(QPalette.ColorRole.Base).name()
            == "#0000ff"
        )

    def test_viewport_fill_follows_color_change(self, qapp, make):
        container = make(QWidget)
        container.resize(220, 120)
        browser = make(QTextBrowser, container)
        browser.setGeometry(10, 10, 200, 100)
        setTextBaseColor(browser, "#ff0000")
        container.show()
        qapp.processEvents()
        assert _px(container, 110, 100) == "#ff0000"
        setTextBaseColor(browser, "#0000ff")
        qapp.processEvents()
        assert _px(container, 110, 100) == "#0000ff"

    def test_transparent_resets_viewport_base(self, qapp, make):
        browser = make(QTextBrowser)
        setTextBaseColor(browser, "#ff0000")
        setTextBaseColor(browser, None)
        assert (
            browser.viewport().palette().color(QPalette.ColorRole.Base).alpha() == 0
        )


class TestBareButton:
    def test_paints_nothing(self, qapp, make):
        container = make(QWidget)
        container.resize(220, 120)
        setSolidBackground(container, "#ff0000")
        button = make(BareButton, container)
        button.setText("不画我")
        button.setGeometry(10, 10, 200, 40)
        container.show()
        qapp.processEvents()
        assert _px(container, 110, 30) == "#ff0000"


class TestFlatIconButton:
    def test_press_color_rounds_and_fills(self, qapp, make):
        button = make(FlatIconButton)
        button.setFixedSize(24, 24)
        button.setPressColor("#00ff00")
        button.setCornerRadius(6)
        assert button.pressColor().name() == "#00ff00"
        button.setDown(True)
        assert _px(button, 12, 4) == "#00ff00"

    def test_transparent_when_idle(self, qapp, make):
        container = make(QWidget)
        container.resize(60, 60)
        setSolidBackground(container, "#ff0000")
        button = make(FlatIconButton, container)
        button.setFixedSize(24, 24)
        button.setGeometry(10, 10, 24, 24)
        button.setHoverColor("#0000ff")
        container.show()
        qapp.processEvents()
        assert _px(container, 22, 22) == "#ff0000"  # 未悬浮 / 未按下：不画底


class TestRoundedCardPainter:
    def test_fill_and_border(self, qapp, make):
        class _Card(QWidget):
            def paintEvent(self, _event):
                painter = QPainter(self)
                paintRoundedCard(
                    painter,
                    self.rect(),
                    background=QColor("#00ffff"),
                    border=QColor("#000080"),
                    radius=8,
                )

        card = make(_Card)
        card.resize(120, 60)
        card.show()
        qapp.processEvents()
        assert _px(card, 60, 30) == "#00ffff"
        assert _px(card, 0, 30) == "#000080"

    def test_background_only(self, qapp, make):
        class _Card(QWidget):
            def paintEvent(self, _event):
                painter = QPainter(self)
                paintRoundedCard(
                    painter, self.rect(), background=QColor("#00ffff"), radius=8
                )

        card = make(_Card)
        card.resize(120, 60)
        card.show()
        qapp.processEvents()
        assert _px(card, 60, 30) == "#00ffff"
        assert _px(card, 0, 30) == "#00ffff"


class TestPlainFrame:
    def test_border_and_fill(self, qapp, make):
        frame = make(QFrame)
        frame.resize(100, 50)
        setPlainFrame(frame, "#2b2b2b", "#444444")
        frame.show()
        qapp.processEvents()
        assert _px(frame, 50, 25) == "#2b2b2b"
        assert _px(frame, 0, 25) == "#444444"
