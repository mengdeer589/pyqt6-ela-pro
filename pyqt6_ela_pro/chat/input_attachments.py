"""聊天输入区附件 / 粘贴 / 拖放方法组。"""

from __future__ import annotations

import hashlib
import os
import tempfile
import warnings
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QFileDialog

from ._mime import localFiles, mimeImage
from .blocks import AttachmentStrip


class _InputAttachmentsMixin:
    def setFilePicker(self, picker: Optional[Callable[[], list]]) -> None:
        """自定义文件选择器（返回本地路径列表；``None`` 恢复默认对话框）。"""
        self._file_picker = picker

    def _on_add_file_clicked(self) -> None:
        picker = self._file_picker or self._default_file_picker
        paths = picker() or []
        if paths:
            self.addAttachments(paths)
        self.addFileRequested.emit()

    def _default_file_picker(self) -> list:
        files, _ = QFileDialog.getOpenFileNames(self, "选择文件")
        return [path for path in files if path]

    def attachmentStrip(self) -> AttachmentStrip:
        """获取附件条控件。"""
        return self._attachments

    def attachments(self) -> list:
        """待发附件快照列表（``ElaChatAttachment``）。"""
        return self._attachments.attachments()

    def attachmentPaths(self) -> list:
        """待发附件的本地路径列表（按添加顺序，便于直接读文件）。
        仅含带路径的文件附件；剪贴板图片等无路径项被排除，其内容仍在
        :meth:`attachments` 快照中。
        """
        return [item.path for item in self._attachments.attachments() if item.path]

    def attachmentCount(self) -> int:
        """待发附件数量。"""
        return self._attachments.count()

    def addAttachments(self, paths) -> list:
        """按本地路径批量添加附件，返回新增的快照列表。"""
        items = []
        for path in paths or []:
            if not isinstance(path, str) or not path:
                continue
            name = os.path.basename(path) or path
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            items.append({"name": name, "path": path, "size": size})
        return self._attachments.addAttachments(items)

    def addAttachment(self, name: str, path: str = "", size: int = 0):
        """添加一个附件（可直接给展示名 / 路径 / 大小）。"""
        return self._attachments.addAttachment(name, path, size)

    def setAttachments(self, attachments) -> None:
        """整体替换附件列表（接受 ``ElaChatAttachment`` 或字典）。"""
        self._attachments.setAttachments(attachments)

    def removeAttachment(self, index: int) -> None:
        """按下标移除附件。"""
        self._attachments.removeAttachment(index)

    def clearAttachments(self) -> None:
        """清空附件。"""
        self._attachments.clear()

    def _on_attachments_changed(self, attachments: list) -> None:
        self._draft_timer.start()
        self.attachmentsChanged.emit(attachments)

    def _on_image_pasted(self, image: QImage) -> bool:
        digest = self._image_digest(image)
        name = f"粘贴的图片-{datetime.now().strftime('%H%M%S')}.png"
        if self._attachments.addPastedImage(image, name, digest) is None:
            return False
        self.imagePasted.emit(image)
        return True

    def _on_files_added(self, paths: list) -> None:
        self._add_files(paths)

    def _on_large_text_pasted(self, text: str) -> None:
        """大段粘贴转附件：写临时文件并进附件条（失败回退为直接插入）。
        与 ``_add_files`` 同一管线 → ``filesAdded`` 照常发出；同内容同 digest
        恒同路径，附件条按路径自然去重。
        """
        path = self._write_paste_file(text)
        if path is None:
            # 写盘失败（权限 / 磁盘满）：不能静默丢内容，回退为直接插入并告警一次
            self._edit.insertPlainText(text)
            warnings.warn(
                "大段粘贴转附件失败（临时文件不可写），已回退为直接插入文本",
                RuntimeWarning,
                stacklevel=2,
            )
            return
        self._add_files([path])

    @staticmethod
    def _write_paste_file(text: str) -> Optional[str]:
        """把粘贴文本写成临时文件，返回路径；失败返回 ``None``。

        文件名带内容摘要（同内容同路径 → 天然幂等）。
        """
        try:
            digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
            directory = Path(tempfile.gettempdir()) / "pyqt6_ela_pro_paste"
            directory.mkdir(exist_ok=True)
            path = directory / f"粘贴文本-{digest}.txt"
            path.write_text(text, encoding="utf-8")
            return str(path)
        except OSError:
            return None

    def _add_files(self, paths: list) -> bool:
        """本地文件进附件条 + 发 ``filesAdded``（拖放与粘贴共用一条路径）。

        信号只带实际新增的路径：重复项被去重后不再发出。
        """
        added = self.addAttachments(paths)
        if not added:
            return False
        self.filesAdded.emit([item.path for item in added if item.path])
        return True

    @staticmethod
    def _image_digest(image: QImage) -> str:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        return hashlib.sha1(bytes(data)).hexdigest()

    def acceptsMime(self, mime) -> bool:
        """mime 里是否有本组件能收下的内容（本地文件 / 图片）。"""
        return bool(localFiles(mime) or mimeImage(mime) is not None)

    def attachMime(self, mime) -> bool:
        """把 mime 里的文件 / 图片收进附件（与粘贴图片同一处去重）；实际收下了才返回 ``True``。"""
        files = localFiles(mime)
        if files:
            return self._add_files(files)
        image = mimeImage(mime)
        if image is not None:
            return self._on_image_pasted(image)
        return False

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self.acceptsMime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self.acceptsMime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if not self.attachMime(event.mimeData()):
            super().dropEvent(event)
            return
        event.acceptProposedAction()
