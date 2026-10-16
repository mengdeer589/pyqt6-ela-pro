"""
SVG 图标渲染代理。
"""

from PyQt6.QtCore import QModelIndex, QSize, Qt
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle
from PyQt6.QtGui import QPainter, QFont
from PyQt6ElaWidgetTools import eTheme, ElaThemeType

from pyqt6_ela_pro.svg_icon import svg_to_pixmap


class EsIconDelegate(QStyledItemDelegate):
    """SVG 图标渲染代理，用于图标浏览器。"""

    LIGHT_ICON_COLOR = "#000000"
    DARK_ICON_COLOR = "#FFFFFF"

    def __init__(self, icon_loader, parent=None):
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self._icon_loader = icon_loader
        self._icon_size = 24
        self._icon_color = self._get_icon_color()
        eTheme.themeModeChanged.connect(self._onThemeModeChanged)

    def _onThemeModeChanged(self, mode: ElaThemeType.ThemeMode):
        self._theme_mode = mode
        self._icon_color = self._get_icon_color()
        self.parent().update() if self.parent() else None

    def _get_icon_color(self) -> str:
        return (
            self.LIGHT_ICON_COLOR
            if self._theme_mode == ElaThemeType.ThemeMode.Light
            else self.DARK_ICON_COLOR
        )

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ):
        view_option = QStyleOptionViewItem(option)
        self.initStyleOption(view_option, index)

        if option.state & QStyle.StateFlag.State_HasFocus:
            view_option.state &= ~QStyle.StateFlag.State_HasFocus

        super().paint(painter, view_option, index)

        icon_name = index.data()
        if not icon_name:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        pixmap = svg_to_pixmap(
            self._icon_loader.getSvgData(icon_name, self._icon_color),
            size=self._icon_size,
            color=self._icon_color,
        )
        icon_rect_x = option.rect.x() + (option.rect.width() - self._icon_size) // 2
        icon_rect_y = option.rect.y() + option.rect.height() // 2 - self._icon_size - 10
        painter.drawPixmap(icon_rect_x, icon_rect_y, pixmap)

        title_font = QFont()
        title_font.setPixelSize(12)
        painter.setFont(title_font)
        color = eTheme.getThemeColor(
            self._theme_mode, ElaThemeType.ThemeColor.BasicText
        )
        painter.setPen(color)

        display_name = icon_name.replace("ic_fluent_", "").replace("_regular", "")
        font_metrics = painter.fontMetrics()
        text_width = option.rect.width() * 0.9
        elided_text = font_metrics.elidedText(
            display_name, Qt.TextElideMode.ElideRight, int(text_width)
        )

        text_x = (
            option.rect.x()
            + option.rect.width() // 2
            - font_metrics.horizontalAdvance(elided_text) // 2
        )
        text_y = option.rect.y() + option.rect.height() - 15
        painter.drawText(text_x, text_y, elided_text)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(90, 90)
