"""附件层：文件 chip 与图片缩略卡。（``pyqt6_ela_pro.chat`` 内部模块）。"""

from __future__ import annotations


from typing import Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QImage,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QSizePolicy,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaFlowLayout,
    ElaIconButton,
    ElaIconType,
)

from ...ela_chip import ElaChip
from ...tooltips import ElaToolTipPositionType, set_tooltip
from ...widget_base import ElaThemeWidget
from ..message import (
    ElaChatAttachment,
    _as_int,
)
from ._helpers import _IMAGE_THUMB_SIZE


class _ImageAttachmentCard(QWidget):
    """图片附件缩略卡（``ElaIconButton`` 缩略图 + 右上角关闭按钮）。"""

    clicked = pyqtSignal()
    removed = pyqtSignal()

    def __init__(
        self,
        pixmap: QPixmap,
        tooltip: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        width, height = _IMAGE_THUMB_SIZE
        self.setFixedSize(width, height)
        thumb = pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._button = ElaIconButton(thumb, self)
        self._button.setFixedSize(width, height)
        self._button.setBorderRadius(6)
        self._button.setToolTip(tooltip)
        set_tooltip(self._button, tooltip, ElaToolTipPositionType.Top)
        self._button.clicked.connect(self.clicked)
        self._close = ElaIconButton(ElaIconType.IconName.CircleXmark, 11, 16, 16, self)
        self._close.setBorderRadius(8)
        self._close.setToolTip("移除附件")
        set_tooltip(self._close, "移除附件", ElaToolTipPositionType.Top)
        self._close.clicked.connect(self.removed)
        self._close.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._close.move(self.width() - self._close.width() + 4, -4)


class AttachmentStrip(ElaThemeWidget):
    """附件层：``ElaChip``（文件）+ 图片缩略卡，``ElaFlowLayout`` 自动换行。

    - 点击通知宿主，× / 关闭按钮移除；
    - ``setAlignment(AlignRight)`` 时自动收缩宽度并靠右（用户消息）；
    - 粘贴图片的图像挂在附件的 ``image`` 字段上（运行时，**不序列化**），
      以 ``digest`` 去重。
    """

    #: 附件被点击（参数：文件路径，可能为空）
    attachmentClicked = pyqtSignal(str)
    #: 附件被移除（参数：文件路径）
    attachmentRemoved = pyqtSignal(str)
    #: 附件列表变化（参数：``ElaChatAttachment`` 列表）
    changed = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._attachments: list[ElaChatAttachment] = []
        self._cards: list = []
        self._alignment = Qt.AlignmentFlag.AlignLeft
        self._layout = ElaFlowLayout(self, 0, 6, 6)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    # -- 数据 --------------------------------------------------------------

    def attachments(self) -> list:
        """附件快照列表（``ElaChatAttachment``）。"""
        return list(self._attachments)

    def count(self) -> int:
        """附件数量。"""
        return len(self._attachments)

    def isEmpty(self) -> bool:
        """是否没有附件。"""
        return not self._attachments

    def setAttachments(self, attachments) -> None:
        """整体替换附件列表（接受 ``ElaChatAttachment`` 或字典）。"""
        normalized = [self._normalize(item) for item in (attachments or [])]
        self._rebuild(normalized)
        self.changed.emit(self.attachments())

    def addAttachment(
        self, name: str, path: str = "", size: int = 0
    ) -> ElaChatAttachment:
        """追加一个附件并返回快照（同路径自动去重）。"""
        attachment = ElaChatAttachment(name=name, path=path, size=_as_int(size))
        if path and any(item.path == path for item in self._attachments):
            return attachment
        self._append(attachment)
        self.changed.emit(self.attachments())
        return attachment

    def addPastedImage(
        self,
        image: QImage,
        name: str = "粘贴的图片.png",
        digest: str = "",
    ) -> Optional[ElaChatAttachment]:
        """追加剪贴板图片附件（以 digest 去重），返回快照。

        图像挂在附件的 ``image`` 字段上（**不序列化**）：附件对象在输入区与
        消息之间流转，撤回回填 / 消息气泡都据此渲染缩略图。
        """
        if digest and any(item.digest == digest for item in self._attachments):
            return None
        attachment = ElaChatAttachment(
            name=name,
            path="",
            size=0,
            digest=digest,
            mime="image/png",
            image=image,
        )
        self._append(attachment)
        self.changed.emit(self.attachments())
        return attachment

    def addAttachments(self, attachments) -> list:
        """批量追加附件（只发一次 ``changed``），返回新增快照列表。"""
        added = []
        for item in attachments or []:
            attachment = self._normalize(item)
            if attachment.path and any(
                existing.path == attachment.path for existing in self._attachments
            ):
                continue
            self._append(attachment)
            added.append(attachment)
        if added:
            self.changed.emit(self.attachments())
        return added

    def removeAttachment(self, index: int) -> None:
        """按下标移除附件。"""
        if not 0 <= index < len(self._attachments):
            return
        attachment = self._attachments[index]
        self._remove_at(index)
        self.attachmentRemoved.emit(attachment.path or attachment.name)
        self.changed.emit(self.attachments())

    def removePath(self, path: str) -> None:
        """按路径移除附件。"""
        for index, attachment in enumerate(self._attachments):
            if attachment.path == path:
                self.removeAttachment(index)
                return

    def clear(self) -> None:
        """清空附件。"""
        if not self._attachments:
            return
        for card in self._cards:
            self._drop_card(card)
        self._attachments.clear()
        self._cards.clear()
        self.setVisible(False)
        self.changed.emit([])

    # -- 对齐与宽度 --------------------------------------------------------

    def setAlignment(self, alignment: Qt.AlignmentFlag) -> None:
        """设置 chips 行内对齐（用户消息常用 ``AlignRight``）。"""
        self._alignment = alignment
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(
            QSizePolicy.Policy.Fixed
            if alignment & Qt.AlignmentFlag.AlignRight
            else QSizePolicy.Policy.Expanding
        )
        self.setSizePolicy(policy)
        self.syncWidth()

    def alignment(self) -> Qt.AlignmentFlag:
        """获取 chips 行内对齐方式。"""
        return self._alignment

    def syncWidth(self, available: int = -1) -> None:
        """按内容宽度收缩（右对齐场景）或占满可用宽度，并同步高度。"""
        if not (self._alignment & Qt.AlignmentFlag.AlignRight):
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.updateGeometry()
            self._sync_height()
            return
        if available <= 0 and self.parentWidget() is not None:
            available = self.parentWidget().width()
        total = 0
        for index, card in enumerate(self._cards):
            total += card.sizeHint().width()
            if index:
                total += 6
        if available > 0:
            total = min(total, available)
        self.setFixedWidth(max(0, total))
        self.updateGeometry()
        self._sync_height()
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().activate()

    def _sync_height(self) -> None:
        """按当前宽度计算换行后的实际高度（ElaFlowLayout 的 heightForWidth）。"""
        if not self._cards:
            return
        width = self.width()
        if width <= 0:
            return
        height = self._layout.heightForWidth(width)
        if height <= 0:
            height = self._layout.minimumSize().height()
        height = max(1, int(height))
        if self.minimumHeight() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._sync_height()

    # -- 布局 --------------------------------------------------------------

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt 命名)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt 命名)
        return self._layout.heightForWidth(width)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        hint = self._layout.minimumSize()
        if not (self._alignment & Qt.AlignmentFlag.AlignRight):
            hint.setWidth(0)
        return hint

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        return self.sizeHint()

    # -- 内部 --------------------------------------------------------------

    @staticmethod
    def _normalize(item) -> ElaChatAttachment:
        if isinstance(item, ElaChatAttachment):
            return item
        if isinstance(item, dict):
            return ElaChatAttachment(
                name=str(item.get("name") or "文件"),
                path=str(item.get("path") or ""),
                size=_as_int(item.get("size")),
                digest=str(item.get("digest") or ""),
                mime=str(item.get("mime") or ""),
            )
        return ElaChatAttachment(name=str(item))

    def _rebuild(self, attachments: list) -> None:
        for card in self._cards:
            self._drop_card(card)
        self._attachments = []
        self._cards = []
        for attachment in attachments:
            self._append(attachment, notify=False)
        self.setVisible(bool(self._attachments))
        self.syncWidth()

    def _append(self, attachment: ElaChatAttachment, notify: bool = True) -> None:
        card = self._create_card(attachment)
        self._layout.addWidget(card)
        # 显式 show：ElaFlowLayout.heightForWidth 只统计可见项；刚 addWidget 的
        # 子控件在首次事件循环前 isVisible() 仍为 False，量出来是 0 → 1px 条。
        card.show()
        self._attachments.append(attachment)
        self._cards.append(card)
        self.setVisible(True)
        if notify:
            self.syncWidth()

    def _create_card(self, attachment: ElaChatAttachment) -> QWidget:
        tooltip = attachment.path or attachment.name
        if attachment.isImage:
            pixmap = None
            if attachment.image is not None:
                pixmap = QPixmap.fromImage(attachment.image)
            if (pixmap is None or pixmap.isNull()) and attachment.path:
                pixmap = QPixmap(attachment.path)
            if pixmap is not None and not pixmap.isNull():
                card = _ImageAttachmentCard(pixmap, tooltip, self)
                card.clicked.connect(
                    lambda a=attachment: self.attachmentClicked.emit(a.path or a.name)
                )
                card.removed.connect(lambda a=attachment: self._on_card_removed(a))
                card.setToolTip(tooltip)
                return card
        chip = ElaChip(self._chip_text(attachment), self)
        chip.setClosable(True)
        chip.setToolTip(tooltip)
        set_tooltip(chip, tooltip, ElaToolTipPositionType.Top)
        chip.closed.connect(lambda a=attachment: self._on_card_removed(a))
        chip.clicked.connect(
            lambda a=attachment: self.attachmentClicked.emit(a.path or a.name)
        )
        return chip

    def _drop_card(self, card: QWidget) -> None:
        self._layout.removeWidget(card)
        card.setParent(None)
        card.deleteLater()

    def _remove_at(self, index: int) -> None:
        self._attachments.pop(index)
        self._drop_card(self._cards.pop(index))
        self.setVisible(bool(self._attachments))
        self.syncWidth()

    def _on_card_removed(self, attachment: ElaChatAttachment) -> None:
        for index, item in enumerate(self._attachments):
            if item is attachment or item == attachment:
                self._remove_at(index)
                self.attachmentRemoved.emit(attachment.path or attachment.name)
                self.changed.emit(self.attachments())
                return

    @staticmethod
    def _chip_text(attachment: ElaChatAttachment) -> str:
        name = attachment.name
        if len(name) > 28:
            name = name[:27] + "…"
        if attachment.size:
            return f"{name} · {attachment.displaySize}"
        return name
