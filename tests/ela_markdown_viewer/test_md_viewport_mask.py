"""圆角视口底色与 mask（bug 报告 §4）。

圆角形态不再切透明视口：保持与自绘圆角背景同色的不透明 ``BasicPress``
（走快重绘路径），四角由 ``QRegion`` mask 裁掉后透出外层自绘背景；
嵌入模式保持透明，由宿主传自己的背景色作不透明底色。
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QPalette
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro import ElaMarkdownViewer


def _base(viewer: ElaMarkdownViewer) -> QColor:
    palette = viewer.textBrowser().palette()
    return palette.color(palette.ColorRole.Base)


def _basic_press(mode) -> QColor:
    return eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicPress)


class TestViewportBase:
    def test_plain_is_opaque_basic_press(self, make):
        v = make(ElaMarkdownViewer)
        color = _base(v)
        assert color.alpha() == 255
        assert color.name() == _basic_press(v._theme_mode).name()
        assert v.textBrowser().mask().isEmpty()

    def test_radius_keeps_opaque_base_with_mask(self, make):
        v = make(ElaMarkdownViewer)
        v.setBorderRadius(6)
        color = _base(v)
        assert color.alpha() == 255
        assert color.name() == _basic_press(v._theme_mode).name()
        assert not v.textBrowser().mask().isEmpty()

    def test_radius_zero_clears_mask(self, make):
        v = make(ElaMarkdownViewer)
        v.setBorderRadius(6)
        assert not v.textBrowser().mask().isEmpty()
        v.setBorderRadius(0)
        assert v.textBrowser().mask().isEmpty()
        assert v._mask_key is None

    def test_embedded_stays_transparent(self, make):
        v = make(ElaMarkdownViewer)
        v.setEmbeddedMode(True)
        assert _base(v).alpha() == 0
        assert v.textBrowser().mask().isEmpty()

    def test_embedding_after_radius_clears_mask(self, make):
        v = make(ElaMarkdownViewer)
        v.setBorderRadius(6)
        v.setEmbeddedMode(True)
        assert v.textBrowser().mask().isEmpty()
        assert _base(v).alpha() == 0

    def test_embedded_with_explicit_color_is_opaque(self, make):
        v = make(ElaMarkdownViewer)
        v.setEmbeddedMode(True)
        v.setViewportBackground(QColor("#123456"))
        color = _base(v)
        assert color.alpha() == 255
        assert color.name() == "#123456"

    def test_explicit_color_with_radius_keeps_mask(self, make):
        v = make(ElaMarkdownViewer)
        v.setViewportBackground(QColor("#123456"))
        v.setBorderRadius(6)
        assert _base(v).name() == "#123456"
        assert not v.textBrowser().mask().isEmpty()

    def test_theme_switch_keeps_base_in_sync(self, make):
        v = make(ElaMarkdownViewer)
        v.setBorderRadius(6)
        v._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        color = _base(v)
        assert color.alpha() == 255
        assert color.name() == _basic_press(ElaThemeType.ThemeMode.Dark).name()
        assert not v.textBrowser().mask().isEmpty()
        # 视口自己的 palette 也要跟上（它带 WA_SetPalette、不跟随控件 setPalette）
        viewport = v.textBrowser().viewport()
        assert viewport.palette().color(QPalette.ColorRole.Base).name() == color.name()


class TestMaskGeometry:
    def test_corners_cut_center_kept(self, make, qapp):
        v = make(ElaMarkdownViewer)
        v.resize(320, 200)
        v.show()
        qapp.processEvents()
        v.setBorderRadius(6)
        browser = v.textBrowser()
        mask = browser.mask()
        assert not mask.isEmpty()
        assert not mask.contains(QPoint(0, 0))
        assert mask.contains(browser.rect().center())

    def test_mask_rebuilds_on_browser_resize(self, make, qapp):
        v = make(ElaMarkdownViewer)
        v.resize(320, 200)
        v.show()
        qapp.processEvents()
        v.setBorderRadius(6)
        browser = v.textBrowser()
        browser.resize(200, 150)
        assert v._mask_key == (200, 150, 6)
        assert not browser.mask().contains(QPoint(0, 0))
        assert browser.mask().contains(QPoint(100, 75))

    def test_rounded_corner_reveals_host_background(self, make, qapp):
        """抓图验证四角透出宿主背景（红），而非被方角补成视口底色。"""
        from _pixels import opaque_colors, skip_if_no_pixels
        from PyQt6.QtGui import QPalette
        from PyQt6.QtWidgets import QWidget

        host = make(QWidget)
        host.resize(300, 200)
        palette = host.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#ff0000"))
        host.setAutoFillBackground(True)
        host.setPalette(palette)
        viewer = ElaMarkdownViewer(host)
        make.track(viewer)
        viewer.setGeometry(20, 20, 240, 160)
        viewer.setBorderRadius(6)
        host.show()
        qapp.processEvents()

        colors = opaque_colors(host)
        skip_if_no_pixels(colors, "圆角角落透出宿主背景")
        image = host.grab().toImage()
        red = 0
        for x in range(20, 30):
            for y in range(20, 30):
                pixel = image.pixelColor(x, y)
                if pixel.red() > 200 and pixel.green() < 60 and pixel.blue() < 60:
                    red += 1
        assert red > 0, "圆角四角应透出宿主背景（mask 未生效？）"
        center = image.pixelColor(140, 100)
        assert center.name() != "#ff0000", "视口中心不应是宿主背景色"
