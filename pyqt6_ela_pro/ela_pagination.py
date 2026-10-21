"""
分页组件，风格参考 ElaWidgetTools 的 ElaPagination。

支持页码导航、省略号、跳转输入框。

用法::

    pag = ElaPagination(parent=self)
    pag.setTotalPages(20)
    pag.setJumperVisible(True)
    pag.currentPageChanged.connect(lambda p: print(f"页码: {p}"))
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QEvent, QRect, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import (
    QPainter,
    QPainterPath,
    QFont,
    QPaintEvent,
    QMouseEvent,
    QIntValidator,
)
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import eTheme, ElaThemeType, ElaLineEdit, ElaText

from .widget_base import ElaThemeWidget


class ElaPagination(ElaThemeWidget):
    """分页组件。"""

    currentPageChanged = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._current_page = 1
        self._total_pages = 1
        self._button_size = 28
        self._pager_count = 11
        self._jumper_visible = False
        self._hover_index = -1

        self.setObjectName("ElaPagination")
        self.setMouseTracking(True)
        self.setFixedHeight(self._button_size + 8)
        self._icon_font = QFont("ElaAwesome")

        self._jumper_edit = ElaLineEdit(self)
        self._jumper_edit.setFixedHeight(self._button_size)
        self._jumper_edit.setPlaceholderText("页码")
        self._jumper_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._jumper_edit.setValidator(QIntValidator(1, 9999, self._jumper_edit))
        self._jumper_edit.setVisible(False)
        self._jumper_edit.returnPressed.connect(self._onJumperEntered)

        self._page_label = ElaText(self)
        self._page_label.setText(f"第{self._current_page}/{self._total_pages}页")
        self._page_label.setTextPixelSize(12)
        self._page_label.setVisible(False)

    def _apply_page_change(self, page: int) -> None:
        self._current_page = page
        self.currentPageChanged.emit(page)
        if self._jumper_visible:
            self._page_label.setText(f"第{self._current_page}/{self._total_pages}页")
            self._page_label.adjustSize()
        self.update()

    def setCurrentPage(self, n: int) -> None:
        """仅当 ``1 <= n <= totalPages`` 且与当前页不同时才切页并发信号。"""
        if n != self._current_page and 1 <= n <= self._total_pages:
            self._apply_page_change(n)

    def currentPage(self) -> int:
        return self._current_page

    def setTotalPages(self, n: int) -> None:
        """最小为 1；当前页超出范围时自动夹到末页并发信号。"""
        self._total_pages = max(1, n)
        if self._current_page > self._total_pages:
            self._current_page = self._total_pages
            self.currentPageChanged.emit(self._current_page)
        if self._jumper_visible:
            self._page_label.setText(f"第{self._current_page}/{self._total_pages}页")
            self._page_label.adjustSize()
        self.updateGeometry()
        self.update()

    def totalPages(self) -> int:
        return self._total_pages

    def setButtonSize(self, n: int) -> None:
        self._button_size = n
        self.setFixedHeight(n + 8)
        self.updateGeometry()
        self.update()

    def buttonSize(self) -> int:
        return self._button_size

    def setPagerCount(self, n: int) -> None:
        """设置分页器最多显示的按钮数（**最小 7**——更小无法容纳省略号布局）。"""
        try:
            value = int(n)
        except (TypeError, ValueError, OverflowError):
            # OverflowError 必须显式列出：int(float("inf")) 抛的是它
            value = self._pager_count
        self._pager_count = max(7, value)
        self.update()

    def pagerCount(self) -> int:
        return self._pager_count

    def setJumperVisible(self, v: bool) -> None:
        self._jumper_visible = v
        self._jumper_edit.setVisible(v)
        self._page_label.setVisible(v)
        if v:
            self._page_label.setText(f"第{self._current_page}/{self._total_pages}页")
            self._page_label.adjustSize()
        self.updateGeometry()
        self.update()

    def isJumperVisible(self) -> bool:
        return self._jumper_visible

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    # ── Internal ──────────────────────────────────────────

    def _getVisiblePages(self) -> list[int]:
        total = self._total_pages
        cur = self._current_page
        pc = self._pager_count

        if total <= 0:
            return []
        if total <= pc:
            return list(range(1, total + 1))

        half = (pc - 2) // 2
        left_ellipsis = cur > half + 2
        right_ellipsis = cur < total - half - 1

        pages: list[int] = []
        if not left_ellipsis and right_ellipsis:
            for i in range(1, pc - 1):
                pages.append(i)
            pages.append(-1)  # right ellipsis
            pages.append(total)
        elif left_ellipsis and not right_ellipsis:
            pages.append(1)
            pages.append(-3)  # left ellipsis
            for i in range(total - (pc - 3), total + 1):
                pages.append(i)
        else:
            pages.append(1)
            pages.append(-3)
            side = (pc - 4) // 2
            for i in range(cur - side, cur + side + 1):
                pages.append(i)
            pages.append(-1)
            pages.append(total)
        return pages

    def _getButtonRects(self) -> list[tuple[QRect, int]]:
        rects: list[tuple[QRect, int]] = []
        size = self._button_size
        spacing = 4
        x = 0
        y = 4

        rects.append((QRect(x, y, size, size), 0))  # prev
        x += size + spacing

        for page in self._getVisiblePages():
            rects.append((QRect(x, y, size, size), page))
            x += size + spacing

        rects.append((QRect(x, y, size, size), -2))  # next
        return rects

    def _updateJumperPosition(self) -> None:
        if not self._jumper_edit.isVisible():
            return
        rects = self._getButtonRects()
        if not rects:
            return
        last = rects[-1][0]
        jx = last.x() + last.width() + 12
        jw = 110
        jh = self._button_size
        jy = (self.height() - jh) // 2
        self._jumper_edit.setGeometry(jx, jy, jw, jh)

        lx = jx + jw + 8
        self._page_label.setText(f"第{self._current_page}/{self._total_pages}页")
        self._page_label.adjustSize()
        ly = (self.height() - self._page_label.height()) // 2
        self._page_label.move(lx, ly)

    def _onJumperEntered(self) -> None:
        text = self._jumper_edit.text().strip()
        if not text:
            return
        try:
            page = int(text)
        except ValueError:
            return
        if 1 <= page <= self._total_pages and page != self._current_page:
            self._apply_page_change(page)
        self._jumper_edit.clear()

    # ── Events ───────────────────────────────────────────

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        old = self._hover_index
        self._hover_index = -1
        for i, (r, _) in enumerate(self._getButtonRects()):
            if r.contains(event.position().toPoint()):
                self._hover_index = i
                break
        if old != self._hover_index:
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        # 指针移出后必须清掉 hover 高亮：本控件没有 leaveEvent 时，最后 hover 的
        # 页码会一直保持高亮底色，直到指针再次进入并移动。
        if self._hover_index != -1:
            self._hover_index = -1
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        for r, val in self._getButtonRects():
            if r.contains(event.position().toPoint()):
                new_page = self._current_page
                if val == 0 and self._current_page > 1:
                    new_page = self._current_page - 1
                elif val == -2 and self._current_page < self._total_pages:
                    new_page = self._current_page + 1
                elif val == -1:
                    new_page = min(
                        self._current_page + self._pager_count - 2, self._total_pages
                    )
                elif val == -3:
                    new_page = max(self._current_page - (self._pager_count - 2), 1)
                elif val > 0:
                    new_page = val

                if new_page != self._current_page:
                    self._apply_page_change(new_page)
                break
        super().mousePressEvent(event)

    # ── Paint ─────────────────────────────────────────────

    def paintEvent(self, _event: QPaintEvent) -> None:
        self._updateJumperPosition()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        mode = self._theme_mode
        primary = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.PrimaryNormal)
        base = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicBase)
        hover = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicHover)
        disable_bg = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicDisable)
        text = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText)
        text_dis = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicTextDisable)

        for i, (r, val) in enumerate(self._getButtonRects()):
            is_current = val > 0 and val == self._current_page
            is_disabled = (val == 0 and self._current_page <= 1) or (
                val == -2 and self._current_page >= self._total_pages
            )
            is_hovered = i == self._hover_index

            painter.setPen(Qt.PenStyle.NoPen)
            if is_current:
                painter.setBrush(primary)
            elif is_disabled:
                painter.setBrush(disable_bg)
            elif is_hovered:
                painter.setBrush(hover)
            else:
                painter.setBrush(base)

            path = QPainterPath()
            path.addRoundedRect(QRectF(r), 6, 6)
            painter.drawPath(path)

            if is_current:
                painter.setPen(Qt.GlobalColor.white)
            elif is_disabled:
                painter.setPen(text_dis)
            else:
                painter.setPen(text)

            if val == 0 or val == -2 or val in (-1, -3):
                self._icon_font.setPixelSize(16)
                painter.setFont(self._icon_font)
                icon_char = (
                    chr(0xEA84)
                    if val == 0
                    else chr(0xEA85)
                    if val == -2
                    else chr(0xEC4D)
                )
                painter.drawText(r, Qt.AlignmentFlag.AlignCenter, icon_char)
            else:
                tf = self.font()
                tf.setPixelSize(14)
                painter.setFont(tf)
                painter.drawText(r, Qt.AlignmentFlag.AlignCenter, str(val))

    def sizeHint(self) -> QSize:
        rects = self._getButtonRects()
        tw = rects[-1][0].x() + rects[-1][0].width() if rects else 0
        if self._jumper_visible:
            tw += 12 + 110 + 8 + 80
        return QSize(tw, self._button_size + 8)
