"""非 QWidget 目标的悬浮提示适配器（item view / 菜单 / QTextDocument）。

``set_tooltip`` 依赖 QWidget 的 Enter / Leave / ToolTip；这里把同样的行为装到
真正接收事件的 viewport / 菜单上，并用 ``ElaToolTip.showAtPoint`` 显示。
"""

from __future__ import annotations

from typing import Callable, Optional
import weakref

from PyQt6.QtCore import QEvent, QModelIndex, QObject, QPoint, Qt, QTimer
from PyQt6.QtGui import QAction, QCursor, QTextCharFormat, QTextCursor, QTextFormat
from PyQt6.QtWidgets import QAbstractItemView, QMenu, QTextEdit, QWidget

from ._internal import is_deleted, safe_connect
from .tooltips import TOOLTIP_WATCH_INTERVAL, ElaToolTip

__all__ = [
    "ACTION_TOOLTIP_PROPERTY",
    "DOCUMENT_TOOLTIP_PROPERTY",
    "ElaToolTipAdapter",
    "action_tooltip_text",
    "document_format_tooltip",
    "install_document_tooltips",
    "install_item_view_tooltips",
    "install_menu_tooltips",
    "set_action_tooltip",
]

#: QAction 的自定义提示属性（不依赖原生 toolTip 的默认回退到 text）
ACTION_TOOLTIP_PROPERTY = "_ela_tooltip"
#: QTextFormat 的自定义提示属性（链接 / 公式 / Mermaid 图片等）
DOCUMENT_TOOLTIP_PROPERTY = int(QTextFormat.Property.UserProperty) + 200

_adapters: weakref.WeakKeyDictionary[QWidget, "ElaToolTipAdapter"] = (
    weakref.WeakKeyDictionary()
)


def set_action_tooltip(action: QAction, text: str) -> None:
    """给菜单项设置库内提示文本（不写原生 ``QAction.setToolTip``）。"""
    action.setProperty(ACTION_TOOLTIP_PROPERTY, str(text or ""))


def action_tooltip_text(action: QAction) -> str:
    """读取菜单项提示：自定义属性优先，兼容显式设置过的原生 toolTip。"""
    value = action.property(ACTION_TOOLTIP_PROPERTY)
    if isinstance(value, str) and value:
        return value
    tip = action.toolTip()
    # QAction.toolTip() 未设置时返回 text()，不能把它当成提示文案。
    return tip if tip and tip != action.text() else ""


def document_format_tooltip(fmt: QTextCharFormat) -> str:
    """读取 QTextFormat 的提示：自定义属性优先，兼容旧的原生 toolTip。"""
    value = fmt.property(DOCUMENT_TOOLTIP_PROPERTY)
    if isinstance(value, str) and value:
        return value
    text = fmt.toolTip()
    if text:
        return text
    image = fmt.toImageFormat()
    if image.isValid():
        value = image.property(DOCUMENT_TOOLTIP_PROPERTY)
        if isinstance(value, str) and value:
            return value
        text = image.toolTip()
    return text or ""


class ElaToolTipAdapter(QObject):
    """给 item view / 菜单 / 文档视图安装库内提示。

    一个目标只建一个 ``ElaToolTip``；提示文本由 ``text_at(QPoint)`` 按光标位置
    解析。目标销毁时适配器与提示框一并回收。
    """

    def __init__(
        self,
        target: QWidget,
        text_at: Callable[[QPoint], str],
        *,
        max_width: int = 520,
        word_wrap: bool = True,
    ) -> None:
        super().__init__(target)
        self._target = target
        self._text_at = text_at
        self._max_width = int(max_width or 0)
        self._word_wrap = bool(word_wrap)
        self._tooltip = ElaToolTip("", target.window())
        self._shown_text = ""
        self._disposed = False
        self._watch = QTimer(self)
        self._watch.setInterval(TOOLTIP_WATCH_INTERVAL)
        safe_connect(self._watch, "timeout", self._check_still_hovered, "tooltip_watch")
        self._mouse_tracking_before = target.hasMouseTracking()
        self._restore_mouse_tracking = False
        if not self._mouse_tracking_before:
            target.setMouseTracking(True)
            self._restore_mouse_tracking = True
        target.installEventFilter(self)
        target.destroyed.connect(self._on_target_destroyed)

    def configure(
        self,
        text_at: Callable[[QPoint], str],
        *,
        max_width: int = 520,
        word_wrap: bool = True,
    ) -> None:
        """复用适配器时更新取词函数与折行配置。"""
        self._text_at = text_at
        self._max_width = int(max_width or 0)
        self._word_wrap = bool(word_wrap)

    def tooltip(self) -> ElaToolTip:
        """当前提示框（测试 / 宿主调试用；不要跨目标复用）。"""
        return self._tooltip

    def hide(self) -> None:
        """隐藏提示框。"""
        self._stop_watch()
        self._shown_text = ""
        if self._tooltip is not None and not is_deleted(self._tooltip):
            self._tooltip.hide()

    def _stop_watch(self) -> None:
        if not is_deleted(self._watch):
            self._watch.stop()

    def _check_still_hovered(self) -> None:
        """看门狗：光标下的提示文本变了 / 目标不可见或禁用时收起。"""
        if self._disposed:
            self._stop_watch()
            return
        tooltip = self._tooltip
        if tooltip is None or is_deleted(tooltip):
            self._stop_watch()
            return
        if not tooltip.isVisible():
            self._stop_watch()
            return
        target = self._target
        try:
            if not target.isVisible() or not target.isEnabled():
                self.hide()
                return
            pos = target.mapFromGlobal(QCursor.pos())
            if not target.rect().contains(pos):
                self.hide()
                return
            text = str(self._text_at(pos) or "")
        except Exception:
            self.hide()
            return
        if not text or text != self._shown_text:
            self.hide()

    def eventFilter(self, a0, a1) -> bool:  # noqa: N802 (Qt 命名)
        """截获 ToolTip 显示库内提示；移动 / 离开 / 点击时收起。"""
        if self._disposed or a0 is not self._target or a1 is None:
            return False
        event_type = a1.type()
        if event_type == QEvent.Type.ToolTip:
            try:
                text = self._text_at(a1.pos()) or ""
            except Exception:
                text = ""
            if text:
                self._tooltip.setWordWrap(self._word_wrap)
                self._tooltip.setMaxWidth(self._max_width)
                self._shown_text = str(text)
                self._tooltip.setText(self._shown_text)
                self._tooltip.showAtPoint(a1.globalPos())
                self._watch.start()
            else:
                self.hide()
            # 必须吞掉：否则 QTextBrowser / item view / QMenu 还会弹原生 QToolTip。
            return True
        if event_type in (
            QEvent.Type.MouseMove,
            QEvent.Type.Leave,
            QEvent.Type.Hide,
            QEvent.Type.Wheel,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.WindowDeactivate,
        ):
            self.hide()
        return False

    def dispose(self) -> None:
        """主动解除绑定并销毁提示框（目标仍存活时调用）。"""
        if self._disposed:
            return
        self._disposed = True
        target = self._target
        _adapters.pop(target, None)
        if not is_deleted(target):
            try:
                target.removeEventFilter(self)
                if self._restore_mouse_tracking:
                    target.setMouseTracking(self._mouse_tracking_before)
            except RuntimeError:
                pass
        self._drop_tooltip()
        self.setParent(None)
        self.deleteLater()

    def _on_target_destroyed(self, _obj=None) -> None:
        self._disposed = True
        _adapters.pop(self._target, None)
        self._drop_tooltip()

    def _drop_tooltip(self) -> None:
        self._stop_watch()
        tooltip = self._tooltip
        self._tooltip = None
        if tooltip is not None and not is_deleted(tooltip):
            tooltip.hide()
            tooltip.deleteLater()


def _install(
    target: QWidget,
    text_at: Callable[[QPoint], str],
    *,
    max_width: int,
    word_wrap: bool,
) -> ElaToolTipAdapter:
    existing = _adapters.get(target)
    if existing is not None and not is_deleted(existing):
        existing.configure(text_at, max_width=max_width, word_wrap=word_wrap)
        return existing
    adapter = ElaToolTipAdapter(
        target, text_at, max_width=max_width, word_wrap=word_wrap
    )
    _adapters[target] = adapter
    return adapter


def install_item_view_tooltips(
    view: QAbstractItemView,
    *,
    role: int = Qt.ItemDataRole.ToolTipRole,
    text_getter: Optional[Callable[[QModelIndex], str]] = None,
    max_width: int = 520,
    word_wrap: bool = True,
) -> ElaToolTipAdapter:
    """给 ``QAbstractItemView`` 的 item 安装库内提示。

    ``text_getter`` 缺省读 ``index.data(role)``；需要从宿主数据解析时传入。
    """

    def text_at(pos: QPoint) -> str:
        index = view.indexAt(pos)
        if not index.isValid():
            return ""
        if text_getter is not None:
            return str(text_getter(index) or "")
        value = index.data(role)
        return value if isinstance(value, str) else ""

    return _install(
        view.viewport(),
        text_at,
        max_width=max_width,
        word_wrap=word_wrap,
    )


def install_menu_tooltips(
    menu: QMenu,
    *,
    text_getter: Optional[Callable[[QAction], str]] = None,
    max_width: int = 520,
    word_wrap: bool = True,
) -> ElaToolTipAdapter:
    """给 ``QMenu`` 的菜单项安装库内提示。"""

    def text_at(pos: QPoint) -> str:
        action = menu.actionAt(pos)
        if action is None or action.isSeparator() or not action.isEnabled():
            return ""
        if text_getter is not None:
            return str(text_getter(action) or "")
        return action_tooltip_text(action)

    return _install(menu, text_at, max_width=max_width, word_wrap=word_wrap)


def install_document_tooltips(
    view: QTextEdit,
    *,
    text_getter: Optional[Callable[[QPoint], str]] = None,
    max_width: int = 520,
    word_wrap: bool = True,
) -> ElaToolTipAdapter:
    """给 ``QTextEdit`` / ``QTextBrowser`` 安装文档级库内提示。

    默认读取 ``QTextFormat`` 的自定义属性 / 原生 toolTip；Markdown 的链接、
    LaTeX、Mermaid 都走这条。
    """

    def text_at(pos: QPoint) -> str:
        if text_getter is not None:
            return str(text_getter(pos) or "")
        cursor = view.cursorForPosition(pos)
        text = document_format_tooltip(cursor.charFormat())
        if not text:
            # cursorForPosition 在字符边界可能返回「前一个位置」，往后/往前
            # 探一个字符，才能命中链接首尾。
            document = cursor.document()
            for next_pos in (cursor.position() + 1, cursor.position() - 1):
                if 0 <= next_pos <= document.characterCount():
                    probe = QTextCursor(cursor)
                    probe.setPosition(next_pos)
                    text = document_format_tooltip(probe.charFormat())
                    if text:
                        break
        if not text:
            anchor_at = getattr(view, "anchorAt", None)
            if callable(anchor_at):
                href = anchor_at(pos)
                # 内部锚点（折叠 / 任务 / 代码块控制）不是用户可读的链接。
                if href and not href.startswith("#"):
                    text = href
        return text

    return _install(
        view.viewport(),
        text_at,
        max_width=max_width,
        word_wrap=word_wrap,
    )
