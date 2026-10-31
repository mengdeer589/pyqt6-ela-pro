"""
聊天 dock 组件（``pyqt6_ela_pro.chat``）。

- :class:`ElaChatQueueDock`：排队消息 dock（输入区上方，可折叠），``N 条排队消息``
  + 首条预览，展开后每条支持「立即发送 / 编辑 / 移除」；
- :class:`ElaChatInputDock`：可替换输入区的通用 dock 容器，``replace=True`` 时输入区
  不可用；
- :class:`ElaChatPermissionDock`：审批 / 提问的交互 dock。

三者都是 ``ElaScrollPageArea`` 卡面。
"""

from __future__ import annotations

from typing import Optional
from uuid import uuid4

from .._internal import is_deleted
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import (
    ElaIconButton,
    ElaIconType,
    ElaScrollPageArea,
    eTheme,
)

from .._internal import _ThemeAwareMixin
from .._ownership import ContentSlot, ElaWidgetOwnershipType
from .._styles import BareButton, ColorText
from ..ela_button import ElaButton
from ._theme import muted_color, text_color
from .message import _as_int


class ElaChatQueueDock(_ThemeAwareMixin, ElaScrollPageArea):
    """排队消息 dock（输入区上方，可折叠）。"""

    #: 点击「立即发送」（参数：消息 id）
    sendRequested = pyqtSignal(str)
    #: 点击「编辑」（参数：消息 id）
    editRequested = pyqtSignal(str)
    #: 点击「移除」（参数：消息 id）
    removeRequested = pyqtSignal(str)
    #: 请求把某条排队消息移到指定下标（参数：消息 id、目标下标）
    reorderRequested = pyqtSignal(str, int)
    #: 点击「插话」（参数：消息 id）
    steerRequested = pyqtSignal(str)
    #: 点击「撤销」上一次队列操作
    undoRequested = pyqtSignal()
    #: 展开状态变化（参数：是否展开）
    toggled = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        # ElaScrollPageArea 构造时 setFixedHeight(75)，dock 需按内容自适应
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setBorderRadius(10)
        self._messages: list = []
        self._expanded = False
        self._working = False
        self._undo_available = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(4)

        self._header = BareButton(self)
        self._header.setFlat(True)
        self._header.setCheckable(True)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        self._chevron = ElaIconButton(
            ElaIconType.IconName.ChevronRight, 12, 16, 16, self
        )
        self._chevron.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chevron.setBorderRadius(4)
        self._title = ColorText(self)
        self._preview = ColorText(self)
        # 排队文本来自用户输入，按纯文本渲染（AutoText 会真解析 HTML）
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._preview.setTextFormat(Qt.TextFormat.PlainText)
        header_layout.addWidget(self._chevron)
        header_layout.addWidget(self._title)
        header_layout.addWidget(self._preview, 1)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(4)
        self._undo_button = ElaIconButton(
            ElaIconType.IconName.ArrowRotateLeft, 12, 18, 18, self
        )
        self._undo_button.setBorderRadius(4)
        self._undo_button.setToolTip("撤销上一次队列操作")
        self._undo_button.hide()
        self._undo_button.clicked.connect(self.undoRequested)
        header_row.addWidget(self._header, 1)
        header_row.addWidget(self._undo_button)
        layout.addLayout(header_row)

        self._rows = QWidget(self)
        self._rows_layout = QVBoxLayout(self._rows)
        self._rows_layout.setContentsMargins(22, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        self._rows.hide()
        layout.addWidget(self._rows)

        self._header.toggled.connect(self._on_toggled)
        self.hide()
        self._apply_theme()

    # -- 数据 --------------------------------------------------------------

    def setMessages(self, messages: list) -> None:
        """整体替换排队消息（``dict``：``id`` / ``text`` / ``attachments``）。"""
        self._messages = [
            {
                "id": str(item.get("id") or uuid4().hex),
                "text": str(item.get("text") or ""),
                "attachments": list(item.get("attachments") or []),
            }
            for item in (messages or [])
            if isinstance(item, dict)
        ]
        self._rebuild_rows()
        self._sync_header()
        self.setVisible(bool(self._messages))

    def messages(self) -> list:
        """排队消息快照列表（``attachments`` 也是副本，改它不会影响内部状态）。"""
        return [
            {
                "id": item["id"],
                "text": item["text"],
                "attachments": [
                    dict(a) if isinstance(a, dict) else a for a in item["attachments"]
                ],
            }
            for item in self._messages
        ]

    def count(self) -> int:
        """排队消息条数。"""
        return len(self._messages)

    def setWorking(self, on: bool) -> None:
        """设置是否正在生成（生成中行按钮显示「插话」）。"""
        on = bool(on)
        if on == self._working:
            return
        self._working = on
        self._rebuild_rows()

    def working(self) -> bool:
        """是否正在生成。"""
        return self._working

    def setUndoAvailable(self, on: bool) -> None:
        """设置撤销按钮是否可用。"""
        self._undo_available = bool(on)
        self._undo_button.setVisible(self._undo_available)

    def undoAvailable(self) -> bool:
        """撤销是否可用。"""
        return self._undo_available

    def setExpanded(self, on: bool) -> None:
        """展开 / 收起明细。"""
        self._header.setChecked(bool(on))

    def isExpanded(self) -> bool:
        """是否展开明细。"""
        return self._header.isChecked()

    # -- 内部 --------------------------------------------------------------

    def _on_toggled(self, checked: bool) -> None:
        self._rows.setVisible(bool(checked))
        self._chevron.setAwesome(
            ElaIconType.IconName.ChevronDown
            if checked
            else ElaIconType.IconName.ChevronRight
        )
        self.toggled.emit(bool(checked))

    def _sync_header(self) -> None:
        self._title.setText(f"{len(self._messages)} 条排队消息")
        first = self._messages[0]["text"] if self._messages else ""
        if not first and self._messages:
            first = "[附件]"
        preview = first.replace("\n", " ")
        if len(preview) > 40:
            preview = preview[:39] + "…"
        self._preview.setText(preview)

    def _rebuild_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for message in self._messages:
            self._rows_layout.addWidget(self._build_row(message))
        # 行文本样式统一交给 _apply_theme：新行必须重新应用 12px 字号
        self._apply_theme()

    def _build_row(self, message: dict) -> QWidget:
        row = QWidget(self._rows)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = ColorText(self._row_text(message), row)
        label.setToolTip(message["text"])
        row._queue_label = label
        layout.addWidget(label, 1)
        send = ElaButton(
            "插话" if self._working else "立即发送",
            variant="text",
            size="small",
            parent=row,
        )
        send.setToolTip("送进当前回合，不打断生成" if self._working else "立即发送这一条")
        send.clicked.connect(
            lambda _checked=False, mid=message["id"]: self._activate_row(mid)
        )
        row._send_button = send
        edit = ElaButton("编辑", variant="text", size="small", parent=row)
        edit.clicked.connect(
            lambda _checked=False, mid=message["id"]: self.editRequested.emit(mid)
        )
        remove = ElaIconButton(ElaIconType.IconName.Xmark, 12, 18, 18, row)
        remove.setBorderRadius(4)
        remove.setToolTip("移除")
        remove.clicked.connect(
            lambda _checked=False, mid=message["id"]: self.removeRequested.emit(mid)
        )
        layout.addWidget(send)
        layout.addWidget(edit)
        layout.addWidget(remove)
        return row

    def _activate_row(self, queueId: str) -> None:
        if self._working:
            self.steerRequested.emit(queueId)
        else:
            self.sendRequested.emit(queueId)

    @staticmethod
    def _row_text(message: dict) -> str:
        text = message["text"].replace("\n", " ")
        if len(text) > 60:
            text = text[:59] + "…"
        attachments = len(message["attachments"])
        if attachments:
            text += f"  （{attachments} 个附件）"
        return text or "[附件]"

    def _apply_theme(self) -> None:
        self._title.setTextColor(text_color(self._theme_mode))
        self._title.setTextPixelSize(12)
        self._title.setTextWeight(QFont.Weight.DemiBold)
        self._preview.setTextColor(muted_color(self._theme_mode, 0.55))
        self._preview.setTextPixelSize(12)
        self._undo_button.setLightIconColor(muted_color(self._theme_mode, 0.6))
        self._undo_button.setDarkIconColor(muted_color(self._theme_mode, 0.6))
        for index in range(self._rows_layout.count()):
            item = self._rows_layout.itemAt(index)
            row = item.widget() if item is not None else None
            if row is None:
                continue
            label = getattr(row, "_queue_label", None)
            if label is not None:
                label.setTextColor(muted_color(self._theme_mode, 0.8))
                label.setTextPixelSize(12)

    def _onThemeChanged(self, mode) -> None:
        self._theme_mode = mode
        self._apply_theme()


class ElaChatInputDock(_ThemeAwareMixin, ElaScrollPageArea):
    """可替换输入区的通用 dock 容器（权限 / 提问卡片等）。

    内容槽走 :class:`~pyqt6_ela_pro._ownership.ContentSlot`（AGENTS.md 要求带内容槽
    的容器一律用它），**释放策略由调用方选**：默认 ``Borrowed`` 只是
    ``setParent(None)`` 交还，``Owned`` 才由本 dock ``deleteLater()``。
    """

    #: dock 内容变化（参数：是否有内容）
    changed = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setBorderRadius(10)
        self._title = ""
        self._replace = False
        self._updating = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 8, 10, 8)
        self._layout.setSpacing(6)
        self._title_label = ColorText(self)
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.hide()
        self._layout.addWidget(self._title_label)
        self._slot = ContentSlot(self, "inputDock")
        # 只在**外部**销毁内容时收尾；显式 setWidget / clear 走各自的路径
        self._slot.widgetChanged.connect(self._on_slot_changed)
        self.hide()
        self._apply_theme()

    # -- 内容 --------------------------------------------------------------

    def setTitle(self, text: str) -> None:
        """设置 dock 标题（空则不显示）。"""
        self._title = text or ""
        self._title_label.setText(self._title)
        self._title_label.setVisible(bool(self._title))

    def title(self) -> str:
        """获取 dock 标题。"""
        return self._title

    def setWidget(  # noqa: N802
        self,
        widget: Optional[QWidget],
        replace: bool = True,
        *,
        ownership: ElaWidgetOwnershipType = ElaWidgetOwnershipType.Borrowed,
    ) -> bool:
        """设置 dock 内容；``replace=True`` 表示替换输入区（输入区不可用）。

        ``ownership`` 默认 ``Borrowed``（交还调用方），选 ``Owned`` 时由本 dock 负责
        ``deleteLater()``。返回是否挂载成功 —— 自挂 / 挂祖先 / 非 QWidget / 宿主已死
        都会被拒。
        """
        self._updating = True
        try:
            self._replace = bool(replace)
            if not self._slot.setWidget(widget, ownership=ownership):
                self._replace = False
                return False
            if widget is None:
                self.hide()
                self.changed.emit(False)
                return True
            self._layout.addWidget(widget)
            self.show()
            self.changed.emit(True)
            return True
        finally:
            self._updating = False

    def widget(self) -> Optional[QWidget]:
        """获取当前 dock 内容。"""
        return self._slot.widget()

    def ownership(self) -> ElaWidgetOwnershipType:
        """当前内容槽的释放策略。"""
        return self._slot.ownership()

    def replacesInput(self) -> bool:
        """当前是否处于替换输入区模式。"""
        return self._replace and self._slot.hasWidget()

    def clear(self) -> None:
        """按当前策略处置内容并收起 dock。"""
        widget = self._slot.widget()
        self._replace = False
        if widget is None:
            self.hide()
            return
        self._updating = True
        try:
            # 先摘出布局；releaseWidget 随后 setParent(None)（Borrowed）或删除（Owned）
            self._layout.removeWidget(widget)
            self._slot.releaseWidget()
        finally:
            self._updating = False
        self.hide()
        self.changed.emit(False)

    def _on_slot_changed(self, widget) -> None:
        """内容被**外部**销毁时收起 dock。

        显式 ``setWidget`` / ``clear`` 自己发 ``changed``（``_updating`` 期间跳过），
        避免一次替换发两遍。此处**不动布局** —— ``widgetChanged(None)`` 也可能来自
        ``destroyed``，此刻 Qt 自己的布局清理可能还没跑完。
        """
        if self._updating or widget is not None:
            return
        self._replace = False
        self.hide()
        self.changed.emit(False)

    def _apply_theme(self) -> None:
        self._title_label.setTextColor(muted_color(self._theme_mode, 0.6))
        self._title_label.setTextPixelSize(12)
        self._title_label.setTextWeight(QFont.Weight.DemiBold)

    def _onThemeChanged(self, mode) -> None:
        self._theme_mode = mode
        self._apply_theme()


class ElaChatPermissionDock(_ThemeAwareMixin, ElaScrollPageArea):
    """审批 / 提问的交互 dock（输入区**上方**，不占用输入区）。

    **不复用** :class:`ElaChatInputDock`：那个的语义是「**替换**输入区」
    （``replace=True`` 时输入区被禁用），审批卡不是输入 —— 塞进去等于 hijack 输入框，
    用户等待期间连字都打不了，而审批往往并不要求「此刻不许说话」。

    一次只显示一张卡；其余请求用一行「还有 N 个待答复」提示。
    """

    #: dock 是否有内容（参数：是否有卡片）
    changed = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setBorderRadius(10)
        self._card: Optional[QWidget] = None
        self._queued = 0

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 8, 10, 8)
        self._layout.setSpacing(4)
        self._queued_label = ColorText(self)
        self._queued_label.setTextFormat(Qt.TextFormat.PlainText)
        self._queued_label.hide()
        self._layout.addWidget(self._queued_label)
        self.hide()
        self._apply_theme()

    def setCard(self, card: Optional[QWidget]) -> None:  # noqa: N802
        """设置当前交互卡（``None`` 收起整个 dock）。

        **显示时机在这里，不在卡片自己身上。** ``bubble.beginPermission`` 建卡时不给
        parent，卡片若自己 ``show()``，Qt 会把这个无父控件当**顶层窗口**弹出来 ——
        用户看到「小窗一闪 -> 变成输入区上那张卡」，连点几次就同时弹出好几个窗口。
        """
        self._detach()
        if card is None:
            self.hide()
            self.changed.emit(False)
            return
        card.setParent(self)
        self._card = card
        # 卡片插到索引 0 = 「排队提示」**下面**（提示是补充信息，卡片是主内容）
        self._layout.insertWidget(0, card)
        self._layout.setAlignment(card, Qt.AlignmentFlag.AlignTop)
        card.show()
        self.show()
        self.changed.emit(True)

    def card(self) -> Optional[QWidget]:
        """当前交互卡。"""
        return self._card

    def setQueued(self, count: int) -> None:  # noqa: N802
        """设置「后面还排着几个」（``<= 0`` 不显示）。"""
        self._queued = max(0, _as_int(count))
        self._queued_label.setText(f"还有 {self._queued} 个待答复")
        self._queued_label.setVisible(self._queued > 0)

    def queued(self) -> int:
        """排队中的待答复数量。"""
        return self._queued

    def clear(self) -> None:
        """收起 dock（卡片交还气泡，**不销毁**）。"""
        had = self._card is not None
        self._detach()
        self._queued = 0
        self._queued_label.hide()
        self.hide()
        if had:
            self.changed.emit(False)

    def _detach(self) -> None:
        if self._card is None:
            return
        # **dock 只是借用卡片，所有权在气泡**（``bubble._interactive_cards``）：
        # 落定时由气泡 deleteLater，气泡销毁时由 ``_reset_part_state`` 收。
        # 这里绝不能 deleteLater —— 撤下后 part 仍是 pending，气泡会把它重新
        # 顶回 dock：冲刷过就是 setParent 到已释放对象（0xC0000409），没冲刷
        # 则卡稍后被 DeferredDelete 删掉、从 dock 里凭空消失。
        if not is_deleted(self._card):
            self._layout.removeWidget(self._card)
            self._card.setParent(None)
        self._card = None

    def _apply_theme(self) -> None:
        self._queued_label.setTextColor(muted_color(self._theme_mode, 0.62))
        self._queued_label.setTextPixelSize(11)

    def _onThemeChanged(self, mode) -> None:
        self._theme_mode = mode
        self._apply_theme()


__all__ = ["ElaChatQueueDock", "ElaChatInputDock", "ElaChatPermissionDock"]
