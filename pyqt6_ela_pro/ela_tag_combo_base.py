"""
具名组合框共享基础设施。

为 ElaTagBox / ElaTagMultiBox / ElaTagSearchBox / ElaTagSearchMultiBox
提供共用的主题色方法、Qt 属性、动画逻辑和 paintEvent 辅助方法。
"""

from __future__ import annotations

from typing import Protocol

from PyQt6.QtCore import (
    Qt,
    QRect,
    QRectF,
    QPropertyAnimation,
    pyqtProperty,  # type: ignore[attr-defined]
)
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QFontMetrics,
    QTextOption,
    QPen,
    QFont,
    QTransform,
)

from PyQt6ElaWidgetTools import eTheme, ElaThemeType, ElaIcon, ElaIconType

from ._internal import connect_theme_signal, disconnect_theme
from ._motion import Duration, Easing, start_transition


class _TagBoxThemeMixin:
    """标签框主题色方法混入类。"""

    _theme_mode: ElaThemeType.ThemeMode

    def _getTitleColor(self) -> QColor:  # type: ignore[attr-defined]
        if not self.isEnabled():
            return eTheme.getThemeColor(
                self._theme_mode, ElaThemeType.ThemeColor.BasicTextDisable
            )
        return eTheme.getThemeColor(self._theme_mode, ElaThemeType.ThemeColor.BasicText)

    def _getBackgroundColor(self) -> QColor:  # type: ignore[attr-defined]
        if not self.isEnabled():
            return eTheme.getThemeColor(
                self._theme_mode, ElaThemeType.ThemeColor.BasicDisable
            )
        if self.hasFocus():
            return eTheme.getThemeColor(
                self._theme_mode, ElaThemeType.ThemeColor.DialogBase
            )
        if self.underMouse():
            return eTheme.getThemeColor(
                self._theme_mode, ElaThemeType.ThemeColor.BasicHover
            )
        return eTheme.getThemeColor(self._theme_mode, ElaThemeType.ThemeColor.BasicBase)

    def _getBorderColor(self) -> QColor:  # type: ignore[attr-defined]
        if self.hasFocus():
            return eTheme.getThemeColor(
                self._theme_mode, ElaThemeType.ThemeColor.PrimaryNormal
            )
        return eTheme.getThemeColor(
            self._theme_mode, ElaThemeType.ThemeColor.BasicBaseLine
        )


class _TagBoxAnimMixin:
    """具名组合框动画与属性共享基类。

    提供 expandMarkWidth / expandIconRotate 属性、
    动画初始化、setTitle / title 方法及主题切换支持。
    子类必须在 __init__ 中调用 self._tag_box_init(title)。
    """

    _title_text: str
    _title_font_size: int
    _expand_mark_width: float
    _expand_icon_rotate: float
    _mark_animation: QPropertyAnimation
    _rotate_animation: QPropertyAnimation
    _theme_mode: ElaThemeType.ThemeMode

    def _tag_box_init(self, title: str = "") -> None:  # type: ignore[attr-defined]
        self._title_text = title
        self._title_font_size = 13
        self._expand_mark_width: float = 0.0
        self._expand_icon_rotate: float = 0.0

        self._mark_animation = QPropertyAnimation(self, b"expandMarkWidth")
        self._mark_animation.setEasingCurve(Easing.type_name(Easing.Standard))

        self._rotate_animation = QPropertyAnimation(self, b"expandIconRotate")
        self._rotate_animation.setEasingCurve(Easing.type_name(Easing.Standard))

        # 与上游 ElaComboBox V3.0（35→30）的触发框同高，整套组合框族统一 30
        self.setFixedHeight(30)  # type: ignore[attr-defined]
        self._theme_mode = eTheme.getThemeMode()

        # 连标准钩子名而不是自定义槽：本 mixin 在 MRO 最前，解析到的就是
        # ``_onThemeChanged``，于是搜索框系列的 ``_ThemeAwareMixin`` 先连的那条
        # 与这里连的是同一个 —— ``connect_theme_signal`` 的幂等守卫才正确。
        # （曾经传的是 ``_on_tag_theme_changed``，那条连接被守卫静默吞掉，
        #   ``_theme_mode`` 永不更新 → 深色主题下底色/边框仍是浅色。）
        connect_theme_signal(self)

    @pyqtProperty(float)
    def expandMarkWidth(self) -> float:
        return self._expand_mark_width

    @expandMarkWidth.setter
    def expandMarkWidth(self, width: float) -> None:
        if self._expand_mark_width != width:
            self._expand_mark_width = width
            self.update()  # type: ignore[attr-defined]

    @pyqtProperty(float)
    def expandIconRotate(self) -> float:
        return self._expand_icon_rotate

    @expandIconRotate.setter
    def expandIconRotate(self, rotate: float) -> None:
        if self._expand_icon_rotate != rotate:
            self._expand_icon_rotate = rotate
            self.update()  # type: ignore[attr-defined]

    def setTitle(self, title: str) -> None:
        self._title_text = title
        self.update()  # type: ignore[attr-defined]

    def title(self) -> str:
        return self._title_text

    def _onThemeChanged(self, _mode=None) -> None:  # type: ignore[attr-defined]
        self._theme_mode = eTheme.getThemeMode()
        self.update()  # type: ignore[attr-defined]
        # 协作式下传：搜索框系列（``ElaTagSearchBox`` 等）的基类链上还有
        # ``_SearchComboMixin._onThemeChanged`` 要给弹层搜索框重新调色。
        # ``ElaTagBox`` 这条链上什么都没有，故用带默认值的 getattr 而非裸 super()。
        parent_hook = getattr(super(), "_onThemeChanged", None)
        if parent_hook is not None:
            parent_hook(_mode)

    def _run_animations(self, mark_end: float, rotate_end: float) -> None:
        # 无收尾路径：目标值同时也被命令式写入（见 ela_tag_multi_box 的
        # showPopup / hidePopup），snap 落终值后画面依旧正确。
        self._mark_animation.setStartValue(self._expand_mark_width)
        self._mark_animation.setEndValue(mark_end)
        start_transition(self._mark_animation, Duration.Normal)

        self._rotate_animation.setStartValue(self._expand_icon_rotate)
        self._rotate_animation.setEndValue(rotate_end)
        start_transition(self._rotate_animation, Duration.Normal)

    def _animate_popup_open(self) -> None:  # type: ignore[attr-defined]
        """运行展开动画（底部主题色条 + 箭头旋转），供子类 showPopup 调用。"""
        if self.count() == 0:
            return
        self._run_animations(self.width() / 2 - 9, -180.0)

    def _animate_popup_close(self) -> None:  # type: ignore[attr-defined]
        """运行收起动画，供子类 hidePopup 调用。"""
        self._run_animations(0.0, 0.0)

    def _theme_cleanup(self) -> None:
        """断开主题单例信号（``connect_theme_signal`` 建立的连接，幂等）。

        原名 ``_tag_box_delete_later`` 是误导 —— 它从不删除任何东西。
        """
        disconnect_theme(self)

    def deleteLater(self) -> None:  # type: ignore[attr-defined]
        self._theme_cleanup()
        super().deleteLater()


# ── 多选组合框共享辅助函数 ───────────────────────────────────────


def _pre_init_popup(widget) -> None:
    """初始化弹出列表的最小高度。"""
    view = widget.view()
    if view:
        view.setMinimumHeight(200)


def _get_target_mark_width(widget) -> float:
    """根据选中比例计算底部主题色条的目标宽度。"""
    selected_count = len(widget.getCurrentSelection())
    total_count = widget.count()
    if total_count <= 0:
        return 0.0
    return (widget.width() / 2 - 9) * selected_count / total_count


# ── paint 辅助函数 ──────────────────────────────────────────────

#: 触发框可见面与控件边缘的内缩（px）。与上游 ``ElaComboBox`` V3.0 的
#: ``comboBoxRect.adjust(1, 1, -1, -1)`` 同值（V3.0 起 combo 从
#: ``_shadowBorderWidth`` 收到 1px，见 ``ElaComboBoxStyle.cpp``）。
_TAG_FACE_INSET = 1


class _TagBoxWidgetProtocol(Protocol):
    """_draw_tag_background 所需的 widget 接口约束"""

    def _getBackgroundColor(self) -> QColor: ...
    def _getTitleColor(self) -> QColor: ...
    def _getBorderColor(self) -> QColor: ...
    def width(self) -> int: ...
    def height(self) -> int: ...


def _draw_tag_background(
    painter: QPainter, widget: _TagBoxWidgetProtocol, face_inset: int = _TAG_FACE_INSET
) -> tuple[QRect, QColor, QColor]:
    """绘制圆角背景和底部分隔线。返回 (content_rect, text_color, border_color)。"""
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    content_rect = QRect(
        face_inset,
        face_inset,
        widget.width() - 2 * face_inset,
        widget.height() - 2 * face_inset,
    )

    bg_color = widget._getBackgroundColor()
    text_color = widget._getTitleColor()
    border_color = widget._getBorderColor()

    path = QPainterPath()
    path.addRoundedRect(QRectF(content_rect), 3, 3)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bg_color)
    painter.drawPath(path)

    pen = QPen(border_color)
    pen.setWidth(2)
    painter.setPen(pen)
    y = content_rect.bottom()
    painter.drawLine(content_rect.left(), y, content_rect.right(), y)

    return content_rect, text_color, border_color


def _draw_tag_title(
    painter: QPainter,
    content_rect: QRect,
    title_text: str,
    title_font_size: int,
    text_color: QColor,
    font,
) -> QRect:
    """绘制标题文本，返回标题区域 QRect。"""
    metrics = QFontMetrics(font)
    title_width = metrics.horizontalAdvance(title_text) + 20

    title_rect = QRect(
        content_rect.left(),
        content_rect.top(),
        title_width,
        content_rect.height(),
    )
    title_option = QTextOption()
    title_option.setWrapMode(QTextOption.WrapMode.NoWrap)
    title_option.setAlignment(
        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
    )
    title_font = QFont(font)
    title_font.setPixelSize(title_font_size)
    painter.setFont(title_font)
    painter.setPen(text_color)
    painter.drawText(
        QRectF(title_rect.adjusted(10, 0, -10, 0)),
        title_text,
        title_option,
    )

    return title_rect


def _draw_tag_arrow(
    painter: QPainter,
    content_rect: QRect,
    text_color: QColor,
    rotate_angle: float,
) -> None:
    """绘制旋转箭头图标。"""
    arrow_rect = QRect(
        content_rect.right() - 25,
        content_rect.top(),
        20,
        content_rect.height(),
    )
    icon = ElaIcon.getInstance().getElaIcon(ElaIconType.IconName.AngleDown, text_color)  # type: ignore[call-arg]
    icon_pixmap = icon.pixmap(17, 17)

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    transform = QTransform()
    transform.translate(
        arrow_rect.left() + arrow_rect.width() / 2,
        arrow_rect.top() + arrow_rect.height() / 2,
    )
    transform.rotate(rotate_angle)
    transform.translate(-icon_pixmap.width() / 2, -icon_pixmap.height() / 2)
    painter.setTransform(transform)
    painter.drawPixmap(0, 0, icon_pixmap)
    painter.restore()


def _draw_tag_mark(
    painter: QPainter,
    widget,
    mark_width: float,
) -> None:
    """绘制底部主题色标记线。"""
    if mark_width > 0:
        mark_color = eTheme.getThemeColor(
            eTheme.getThemeMode(), ElaThemeType.ThemeColor.PrimaryNormal
        )
        painter.setPen(Qt.PenStyle.NoPen)  # type: ignore[attr-defined]
        painter.setBrush(mark_color)
        mark_rect = QRectF(
            widget.width() / 2 - mark_width,
            widget.height() - _TAG_FACE_INSET - 3,
            mark_width * 2,
            3,
        )
        mark_path = QPainterPath()
        mark_path.addRoundedRect(mark_rect, 1.5, 1.5)
        painter.drawPath(mark_path)


def _draw_single_value_text(
    painter: QPainter,
    content_rect: QRect,
    title_rect: QRect,
    current_text: str,
) -> None:
    """绘制单选组合框的值文本。"""
    if not current_text:
        return
    text_left = title_rect.right()
    text_width = content_rect.right() - 30 - text_left
    if text_width <= 0:
        return
    text_rect = QRect(
        text_left,
        content_rect.top(),
        text_width,
        content_rect.height(),
    )
    text_option = QTextOption()
    text_option.setWrapMode(QTextOption.WrapMode.NoWrap)
    text_option.setAlignment(
        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
    )
    painter.drawText(QRectF(text_rect), current_text, text_option)


def _draw_multi_value_text(
    painter: QPainter,
    content_rect: QRect,
    title_rect: QRect,
    selections: list[str],
    max_show: int = 3,
) -> None:
    """绘制多选组合框的值文本（逗号分隔，最多显示 max_show 项）。"""
    if not selections:
        return
    if len(selections) > max_show:
        display_text = ",".join(selections[:max_show]) + "..."
    else:
        display_text = ",".join(selections)
    text_left = title_rect.right()
    text_width = content_rect.right() - 30 - text_left
    if text_width <= 0:
        return
    text_rect = QRect(
        text_left,
        content_rect.top(),
        text_width,
        content_rect.height(),
    )
    text_option = QTextOption()
    text_option.setWrapMode(QTextOption.WrapMode.NoWrap)
    text_option.setAlignment(
        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
    )
    painter.drawText(QRectF(text_rect), display_text, text_option)


def _paint_tag_single(painter: QPainter, widget) -> None:
    """绘制单选标签组合框（ElaTagBox / ElaTagSearchBox 共用）。"""
    content_rect, text_color, _ = _draw_tag_background(painter, widget)
    _draw_tag_mark(painter, widget, widget._expand_mark_width)
    title_rect = _draw_tag_title(
        painter,
        content_rect,
        widget._title_text,
        widget._title_font_size,
        text_color,
        widget.font(),
    )
    _draw_single_value_text(painter, content_rect, title_rect, widget.currentText())
    _draw_tag_arrow(painter, content_rect, text_color, widget._expand_icon_rotate)


def _paint_tag_multi(painter: QPainter, widget) -> None:
    """绘制多选标签组合框（ElaTagMultiBox / ElaTagSearchMultiBox 共用）。"""
    content_rect, text_color, _ = _draw_tag_background(painter, widget)

    view = widget.view()
    is_popup_visible = view.isVisible() if view else False
    mark_width = (
        _get_target_mark_width(widget)
        if is_popup_visible
        else widget._expand_mark_width
    )
    _draw_tag_mark(painter, widget, mark_width)

    title_rect = _draw_tag_title(
        painter,
        content_rect,
        widget._title_text,
        widget._title_font_size,
        text_color,
        widget.font(),
    )
    _draw_multi_value_text(
        painter, content_rect, title_rect, widget.getCurrentSelection()
    )
    _draw_tag_arrow(painter, content_rect, text_color, widget._expand_icon_rotate)
