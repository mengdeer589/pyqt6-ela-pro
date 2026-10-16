from PyQt6.QtCore import Qt, QModelIndex, QSize
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem
from PyQt6.QtGui import QPainter, QFont
from PyQt6ElaWidgetTools import eTheme, ElaThemeColor, ElaThemeType


class T_IconDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._themeMode = eTheme.getThemeMode()
        eTheme.themeModeChanged.connect(self._onThemeModeChanged)

    def _onThemeModeChanged(self, themeMode: ElaThemeType.ThemeMode):
        self._themeMode = themeMode

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ):
        viewOption = QStyleOptionViewItem(option)
        self.initStyleOption(viewOption, index)

        if option.state & QStyle.StateFlag.State_HasFocus:
            viewOption.state &= ~QStyle.StateFlag.State_HasFocus

        super().paint(painter, viewOption, index)

        iconList = index.data(Qt.ItemDataRole.UserRole)
        if not iconList or len(iconList) != 2:
            return

        iconName = iconList[0]
        iconValue = iconList[1]

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        iconFont = QFont("ElaAwesome")
        iconFont.setPixelSize(22)
        painter.setFont(iconFont)
        painter.setPen(ElaThemeColor(self._themeMode, ElaThemeType.ThemeColor.BasicText))
        painter.drawText(
            option.rect.x() + option.rect.width() // 2 - 11,
            option.rect.y() + option.rect.height() // 2 - 11,
            iconValue,
        )

        painter.setPen(ElaThemeColor(self._themeMode, ElaThemeType.ThemeColor.BasicText))
        titleFont = painter.font()
        titleFont.setPixelSize(13)
        painter.setFont(titleFont)

        rowTextWidth = option.rect.width() * 0.8
        fontMetrics = painter.fontMetrics()
        subTitleRow = fontMetrics.horizontalAdvance(iconName) / rowTextWidth
        if subTitleRow > 0:
            subTitleText = iconName
            for i in range(int(subTitleRow) + 1):
                text = fontMetrics.elidedText(
                    subTitleText, Qt.TextElideMode.ElideRight, int(rowTextWidth)
                )
                if text[-3:] == "…" or "…" in text:
                    text = text.replace("…", subTitleText[len(text) - 1 : len(text)])
                subTitleText = subTitleText[len(text) :]
                painter.drawText(
                    option.rect.x()
                    + option.rect.width() // 2
                    - fontMetrics.horizontalAdvance(text) // 2,
                    option.rect.y()
                    + option.rect.height()
                    - 10 * (int(subTitleRow) + 1 - i),
                    text,
                )
        else:
            painter.drawText(
                option.rect.x()
                + option.rect.width() // 2
                - fontMetrics.horizontalAdvance(iconName) // 2,
                option.rect.y() + option.rect.height() - 20,
                iconName,
            )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(100, 100)
