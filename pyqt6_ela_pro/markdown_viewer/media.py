"""图片加载 / 保存 / 数学公式方法组。"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from typing import Optional
from urllib.parse import unquote_to_bytes

from PyQt6.QtCore import QByteArray, QFileInfo, Qt, QUrl
from PyQt6.QtGui import (
    QImage,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextImageFormat,
)
from PyQt6.QtWidgets import QApplication, QFileDialog

from ..math_lite import render_formula
from ..tooltip_targets import DOCUMENT_TOOLTIP_PROPERTY
from .syntax import _clamp_pos
from .tokens import _MERMAID_IMAGE_PREFIX, _MERMAID_TIP_PREFIX


_IMAGE_SYNTAX_RE = re.compile(r"!\[|<img", re.IGNORECASE)

_MAX_DATA_URI_BYTES = 32 * 1024 * 1024


def _decode_data_uri(url: QUrl) -> QByteArray:
    """``data:`` URL → 原始字节（格式非法 / 体积过大返回空）。
    :meth:`_embed_image_data_uri`），所以必须能读回来。模型输出里的 base64
    一行 Markdown 分配任意内存。
    """
    payload = url.path() or url.toString(QUrl.ComponentFormattingOption.FullyEncoded)
    if not payload:
        return QByteArray()
    try:
        header, _, encoded = payload.partition(",")
        if not _:
            return QByteArray()
        if header.rstrip().lower().endswith(";base64"):
            # 先按编码长度预检，避免超长 data URI 在解码后才丢弃：
            # base64 解码后的字节数约为输入长度的 3/4。
            compact = _safe_b64_text(encoded)
            if len(compact) > _MAX_DATA_URI_BYTES * 4 // 3 + 4:
                return QByteArray()
            # validate=True：畸形 base64 直接拒绝，不让QImage 去猜
            data = base64.b64decode(compact, validate=True)
        else:
            # percent-encoding 最坏会把一个字节扩成 3 个字符。
            if len(encoded) > _MAX_DATA_URI_BYTES * 3 + 16:
                return QByteArray()
            data = unquote_to_bytes(encoded)
    except Exception:
        return QByteArray()
    if not data or len(data) > _MAX_DATA_URI_BYTES:
        return QByteArray()
    return QByteArray(data)


def _safe_b64_text(text: str) -> str:
    """容忍 base64 里的换行 / 空白（``b64decode(validate=True)`` 不接受）。"""
    return "".join(text.split())


class _MarkdownMediaMixin:
    def _on_image_clicked(self, position: int) -> None:
        """图片单击：公式/Mermaid 复制源码，普通图片发射 ``imageClicked``。"""
        cursor = QTextCursor(self.document())
        cursor.setPosition(max(0, min(position, self.document().characterCount() - 1)))
        candidates = [cursor.charFormat()]
        probe = QTextCursor(cursor)
        if probe.movePosition(
            QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor
        ):
            candidates.append(probe.charFormat())
        for fmt in candidates:
            if not fmt.isImageFormat():
                continue
            image_format = fmt.toImageFormat()
            name = image_format.name()
            tooltip = str(
                image_format.property(DOCUMENT_TOOLTIP_PROPERTY)
                or image_format.toolTip()
                or ""
            )
            if name.startswith("elamath://"):
                if tooltip.startswith("LaTeX: "):
                    latex = tooltip[len("LaTeX: ") :]
                    QApplication.clipboard().setText(latex)
                    self.formulaCopied.emit(latex)
                return
            if name.startswith(_MERMAID_IMAGE_PREFIX):
                if tooltip.startswith(_MERMAID_TIP_PREFIX):
                    code = tooltip[len(_MERMAID_TIP_PREFIX) :]
                    QApplication.clipboard().setText(code)
                    self.mermaidCopied.emit(code)
                return
            url = self._resolve_image_url(name, self.document().baseUrl())
            self.imageClicked.emit(url.toString())
            return

    def setBaseUrl(self, url) -> None:
        """图片等资源的基准路径（本地目录路径串 / URL 串 / ``QUrl``）。"""
        if isinstance(url, QUrl):
            qurl = QUrl(url)
        elif isinstance(url, str):
            if url.startswith(("http://", "https://", "file:")):
                qurl = QUrl(url)
            else:
                qurl = QUrl.fromLocalFile(url)
        else:
            raise TypeError(f"url 应为 str 或 QUrl，收到 {type(url).__name__}")
        if qurl.isLocalFile() and not qurl.path().endswith("/"):
            qurl.setPath(qurl.path() + "/")
        self._base_url = qurl
        self._text_browser.document().setBaseUrl(qurl)

    def baseUrl(self) -> QUrl:
        """获取资源基准路径。"""
        return self._base_url

    def setRemoteImagesEnabled(self, on: bool) -> None:
        """是否允许加载远程（http/https）图片，默认关闭；``False`` 时拦截并显示占位文本。"""
        self._remote_images_enabled = bool(on)
        self._text_browser.remote_images_enabled = bool(on)
        if self._source:
            self._render()

    def remoteImagesEnabled(self) -> bool:
        """是否允许加载远程图片。"""
        return self._remote_images_enabled

    def renderIssues(self) -> list:
        """获取本次渲染的降级记录。

        :returns: ``[(类型, 详情)]``，类型为 ``"math"`` / ``"mermaid"`` / ``"image"``；
            全量渲染时重置，流式期间追加
        """
        return list(self._render_issues)

    def _math_point_size(self) -> float:
        """公式字号（pt）：跟随文档默认字体。"""
        font = self.document().defaultFont()
        size = font.pointSizeF()
        if size > 0:
            return size
        pixel = font.pixelSize()
        return pixel * 0.75 if pixel > 0 else 10.0

    def _embed_math(self, document: QTextDocument, maths: list, resource_doc) -> None:
        """把公式占位标记替换为渲染图片（结构错误时保留源码文本）。
        行内公式按正文字号的 1.2 倍渲染并垂直居中（``AlignMiddle``），
        避免 Qt 内联图片"底部贴基线"造成的整体上浮；块级按 1.35 倍并居中。
        """
        base_point_size = self._math_point_size()
        plain_format = QTextCharFormat()
        plain_format.setForeground(self._text_color)
        search = QTextCursor(document)
        for index, (latex, display) in enumerate(maths):
            marker = self._math_mark.format(index)
            found = document.find(marker, search)
            if found.isNull():
                continue
            search.setPosition(found.position())
            point_size = base_point_size * (1.55 if display else 1.3)
            report: dict = {}
            image = render_formula(
                latex, self._text_color, point_size, display, report=report
            )
            if image is None:
                self._record_issue("math", latex)
                text = latex if display else f"${latex}$"
                found.insertText(text, plain_format)
                if display:
                    block_format = found.blockFormat()
                    block_format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                    found.setBlockFormat(block_format)
                continue
            if report.get("degraded") and not report.get("repaired"):
                self._record_issue("math", latex)
            digest = hashlib.md5(
                f"{latex}|{self._text_color.name()}|{point_size:.2f}|{display}".encode(
                    "utf-8"
                )
            ).hexdigest()
            url = f"elamath://{digest}"
            resource_doc.addResource(
                QTextDocument.ResourceType.ImageResource, QUrl(url), image
            )
            image_format = QTextImageFormat()
            image_format.setName(url)
            image_format.setWidth(image.width() / 2.0)
            image_format.setHeight(image.height() / 2.0)
            image_format.setProperty(DOCUMENT_TOOLTIP_PROPERTY, f"LaTeX: {latex}")
            image_format.setVerticalAlignment(
                QTextCharFormat.VerticalAlignment.AlignMiddle
            )
            found.insertImage(image_format)
            if display:
                block_format = found.blockFormat()
                block_format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                block_format.setTopMargin(10)
                block_format.setBottomMargin(10)
                found.setBlockFormat(block_format)

    def _image_format_at_cursor(self) -> Optional[QTextImageFormat]:
        """光标处（含前一字符）的图片格式；没有则返回 ``None``。"""
        cursor = self._text_browser.textCursor()
        candidates = [cursor.charFormat()]
        probe = QTextCursor(cursor)
        if probe.movePosition(
            QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor
        ):
            candidates.append(probe.charFormat())
        for fmt in candidates:
            if fmt.isImageFormat():
                return fmt.toImageFormat()
        return None

    def _image_source_at_cursor(self, url_prefix: str, tip_prefix: str) -> str:
        """光标处图片的源码（``url_prefix`` / ``tip_prefix`` 匹配；否则空串）。"""
        image_format = self._image_format_at_cursor()
        if image_format is None:
            return ""
        if not image_format.name().startswith(url_prefix):
            return ""
        tooltip = str(
            image_format.property(DOCUMENT_TOOLTIP_PROPERTY)
            or image_format.toolTip()
            or ""
        )
        if tooltip.startswith(tip_prefix):
            return tooltip[len(tip_prefix) :]
        return ""

    def _load_image_resource(
        self, target_doc: QTextDocument, source: QUrl
    ) -> Optional[QImage]:
        """取资源里的图片；取不到 / 类型不对一律返回 ``None``（走占位符）。
        返回类型必须是真 ``QImage``：``loadResource`` 对 ``data:`` 返回 QByteArray，
        （Qt 槽内 = 0xC0000409）。``data:`` 走 ``QImage.fromData`` 真解码。
        """
        if source.scheme() == "data":
            image = QImage.fromData(_decode_data_uri(source))
            if not image.isNull():
                target_doc.addResource(
                    QTextDocument.ResourceType.ImageResource, source, image
                )
            return None if image.isNull() else image

        image = target_doc.resource(QTextDocument.ResourceType.ImageResource, source)
        if image is not None and not isinstance(image, QImage):
            converter = getattr(image, "toImage", None)
            if callable(converter):
                image = converter()
        if not isinstance(image, QImage):
            # QVariant / QByteArray / 任何非图片类型：视作取不到
            image = None
        if image is not None and not image.isNull():
            return image
        if source.isLocalFile():
            loaded = QImage(source.toLocalFile())
            if not loaded.isNull():
                target_doc.addResource(
                    QTextDocument.ResourceType.ImageResource, source, loaded
                )
                return loaded
        return None

    def _image_local_path_at_cursor(self) -> str:
        """光标处本地图片的磁盘路径（远程 / 生成图片返回空串）。"""
        image_format = self._image_format_at_cursor()
        if image_format is None:
            return ""
        url = self._resolve_image_url(image_format.name(), self.document().baseUrl())
        if not url.isLocalFile():
            return ""
        path = url.toLocalFile()
        return path if os.path.isfile(path) else ""

    def _save_image_at_cursor(self) -> None:
        """把光标处的本地图片另存为 PNG / JPEG。"""
        path = self._image_local_path_at_cursor()
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            return
        info = QFileInfo(path)
        suggested = os.path.join(info.absolutePath(), info.completeBaseName() + ".png")
        target, _ = QFileDialog.getSaveFileName(
            self,
            "图片另存为",
            suggested,
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg);;所有文件 (*)",
        )
        if not target:
            return
        image.save(target)

    def _apply_images(
        self, document: QTextDocument, resource_doc=None, start_block: int = 0
    ) -> None:
        """处理图片片段：本地加载注册、超宽缩放、远程按开关拦截。
        ``start_block`` 起（含）的块才参与处理 —— 宽度未变的增量重排只需扫
        新增块；宽度变化时调用方传 0 全量重扫。
        """
        base = document.baseUrl()
        target_doc = resource_doc or document
        max_width = max(self._content_text_width() - 24, 120)
        placeholder_fmt = QTextCharFormat()
        placeholder_fmt.setForeground(self._muted_color)
        block = document.findBlockByNumber(start_block)
        if not block.isValid():
            return
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    fmt = fragment.charFormat()
                    if fmt.isImageFormat():
                        image_fmt = fmt.toImageFormat()
                        if not image_fmt.name().startswith("elamath://"):
                            self._apply_image_fragment(
                                document,
                                target_doc,
                                fragment,
                                image_fmt,
                                base,
                                max_width,
                                placeholder_fmt,
                            )
                iterator += 1
            block = block.next()
        self._center_standalone_images(document, start_block)

    def _center_standalone_images(
        self, document: QTextDocument, start_block: int = 0
    ) -> None:
        """独占一行的图片居中（行内公式图片不参与）。"""
        block = document.findBlockByNumber(start_block)
        if not block.isValid():
            return
        while block.isValid():
            if block.text().strip() == "\ufffc":
                has_image = False
                has_math = False
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    if fragment.isValid() and fragment.charFormat().isImageFormat():
                        if (
                            fragment.charFormat()
                            .toImageFormat()
                            .name()
                            .startswith("elamath://")
                        ):
                            has_math = True
                        else:
                            has_image = True
                    iterator += 1
                if has_image and not has_math:
                    block_format = block.blockFormat()
                    block_format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                    self._apply_block_format(document, block, block_format)
            block = block.next()

    def _apply_image_fragment(
        self,
        document: QTextDocument,
        target_doc: QTextDocument,
        fragment,
        image_fmt: QTextImageFormat,
        base: QUrl,
        max_width: int,
        placeholder_fmt: QTextCharFormat,
    ) -> None:
        """单个图片片段：解析 URL、加载资源、必要时缩放或替换占位。"""
        source = self._resolve_image_url(image_fmt.name(), base)
        if source.scheme() in ("http", "https"):
            if not self._remote_images_enabled:
                self._replace_image_with_placeholder(
                    document, fragment, placeholder_fmt, source.toString()
                )
            return

        image = self._load_image_resource(target_doc, source)
        if image is None:
            self._replace_image_with_placeholder(
                document, fragment, placeholder_fmt, source.toString()
            )
            return

        width = image.width()
        height = image.height()
        if source.scheme() == "elamermaid":
            # Mermaid 按 2x 超采样渲染，显示尺寸减半
            width /= 2.0
            height /= 2.0
        if width > max_width > 0:
            height = height * max_width / float(width)
            width = max_width
        cursor = QTextCursor(document)
        cursor.setPosition(fragment.position())
        cursor.setPosition(
            _clamp_pos(document, fragment.position() + fragment.length()),
            QTextCursor.MoveMode.KeepAnchor,
        )
        scaled = QTextImageFormat()
        scaled.setName(source.toString())
        scaled.setWidth(width)
        scaled.setHeight(height)
        cursor.mergeCharFormat(scaled)

    @staticmethod
    def _resolve_image_url(name: str, base: QUrl) -> QUrl:
        """图片名 → 绝对 URL（兼容 Windows 盘符路径与相对路径）。"""
        if re.match(r"^[A-Za-z]:[\\/]", name):
            return QUrl.fromLocalFile(name)
        source = QUrl(name)
        if source.isRelative() and not base.isEmpty():
            source = base.resolved(source)
        return source

    def _replace_image_with_placeholder(
        self,
        document: QTextDocument,
        fragment,
        placeholder_fmt: QTextCharFormat,
        detail: str = "",
    ) -> None:
        """把无法加载的图片替换为灰字占位（记录到渲染问题）。"""
        if detail:
            self._record_issue("image", detail)
        cursor = QTextCursor(document)
        cursor.setPosition(fragment.position())
        cursor.setPosition(
            _clamp_pos(document, fragment.position() + fragment.length()),
            QTextCursor.MoveMode.KeepAnchor,
        )
        cursor.removeSelectedText()
        cursor.insertText("[图片]", placeholder_fmt)

    def _record_issue(self, kind: str, detail: str) -> None:
        """记录一次渲染降级（去重）。"""
        entry = (kind, detail)
        if entry not in self._render_issues:
            self._render_issues.append(entry)
