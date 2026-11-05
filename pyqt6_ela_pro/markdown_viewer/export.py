"""PDF / HTML 导出方法组。"""

from __future__ import annotations

import base64
import math
import mimetypes
import os
import re
from typing import Optional

from PyQt6.QtCore import QBuffer, QIODevice, QMarginsF, QRectF, QSizeF, Qt
from PyQt6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QFont,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPalette,
    QPdfWriter,
    QTextCursor,
    QTextDocument,
)
from PyQt6.QtWidgets import QDialog

from .tokens import _CODE_CELL_LEFT_PADDING


class _MarkdownExportMixin:
    def toHtml(self, embedImages: bool = False) -> str:
        """导出当前渲染结果为 HTML；``embedImages=True`` 时把公式 / Mermaid /
        本地图片内嵌成 data URI（单文件分享用，远程图片保持原样），默认关闭。
        """
        self._finish_pending_render()
        html = self._document_for_export().toHtml()
        if not embedImages:
            return html

        def replace(match: re.Match) -> str:
            embedded = self._embed_image_data_uri(match.group(2))
            if not embedded:
                return match.group(0)
            return match.group(1) + embedded + match.group(3)

        return re.sub(r'(<img\b[^>]*?\ssrc=")([^"]*)(")', replace, html)

    def _embed_image_data_uri(self, name: str) -> str:
        """图片名 → data URI（生成图片 / 本地文件；远程或缺失返回空串）。"""
        url = self._resolve_image_url(name, self.document().baseUrl())
        if url.scheme() in ("elamath", "elamermaid"):
            resource = self.document().resource(
                QTextDocument.ResourceType.ImageResource, url
            )
            if not isinstance(resource, QImage):
                # ``data:`` 资源是 QByteArray（见 _load_image_resource 的说明），
                # 这里只处理 elamath / elamermaid，但仍不能假设类型
                converter = getattr(resource, "toImage", None)
                resource = converter() if callable(converter) else None
            if resource is None:
                return ""
            image = resource
            if image.isNull():
                return ""
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            data = bytes(buffer.data())
            return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        if not url.isLocalFile():
            return ""
        path = url.toLocalFile()
        if not os.path.isfile(path):
            return ""
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as handle:
            data = handle.read()
        return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")

    @staticmethod
    def _resolve_pdf_page_size(pageSize) -> QPageSize:
        """纸张解析（大小写不敏感；未知名称回退 A4）。"""
        if isinstance(pageSize, QPageSize):
            return pageSize
        key = str(pageSize).strip().lower()
        for name in dir(QPageSize.PageSizeId):
            if name.startswith("_"):
                continue
            if name.lower() == key:
                return QPageSize(getattr(QPageSize.PageSizeId, name))
        return QPageSize(QPageSize.PageSizeId.A4)

    @staticmethod
    def _normalize_pdf_margins(marginsMm) -> QMarginsF:
        """页边距：数字 / (横, 纵) / (左, 上, 右, 下)，单位毫米。"""
        if isinstance(marginsMm, (int, float)):
            values = [float(marginsMm)] * 4
        else:
            try:
                values = [float(value) for value in marginsMm]
            except (TypeError, ValueError):
                values = [15.0] * 4
            if len(values) == 2:
                values = [values[0], values[1], values[0], values[1]]
            elif len(values) != 4:
                values = [15.0] * 4
        return QMarginsF(*[max(0.0, value) for value in values])

    def _current_body_point_size(self) -> float:
        """当前正文等效字号（pt）。"""
        font = self.document().defaultFont()
        size = font.pointSizeF()
        if size <= 0:
            pixel = font.pixelSize()
            size = pixel * 0.75 if pixel > 0 else 10.0
        return size

    def _pdf_font_scale(self, fontPointSize) -> float:
        """目标正文字号 → painter 缩放系数。"""
        if fontPointSize is None:
            return 1.0
        try:
            target = float(fontPointSize)
        except (TypeError, ValueError, OverflowError):
            return 1.0
        if not math.isfinite(target) or target <= 0:
            return 1.0
        target = max(4.0, min(32.0, target))
        current = self._current_body_point_size()
        if current <= 0:
            return 1.0
        return target / current

    def _strip_code_line_gutter(self, document: QTextDocument) -> None:
        """导出文档去掉代码卡左侧行号槽（行号只属于屏幕绘制层）。"""
        for table in self._iter_tables(document):
            if not self._is_code_table(table) or table.rows() < 1:
                continue
            cell = table.cellAt(0, 0)
            if cell is None:
                continue
            cell_format = cell.format().toTableCellFormat()
            cell_format.setLeftPadding(_CODE_CELL_LEFT_PADDING)
            cell.setFormat(cell_format)

    def _document_for_export(self) -> QTextDocument:
        """导出用副本：保留资源 / 块布局，去掉屏幕专用行号槽。"""
        clone = self.document().clone()
        source = self.document().firstBlock()
        target = clone.firstBlock()
        while source.isValid() and target.isValid():
            source_layout = source.layout()
            target_layout = target.layout()
            if source_layout is not None and target_layout is not None:
                target_layout.setFormats(source_layout.formats())
            source = source.next()
            target = target.next()
        # 阅读列宽度只服务屏幕；PDF / 打印页边距由 QPageLayout 控制。
        frame = clone.rootFrame().frameFormat()
        margin = clone.documentMargin()
        frame.setLeftMargin(margin)
        frame.setRightMargin(margin)
        clone.rootFrame().setFrameFormat(frame)
        self._strip_code_line_gutter(clone)
        return clone

    def _apply_export_line_spacing(self, document: QTextDocument, lineSpacing) -> None:
        """按正文字号基准缩放导出文档的块行高。"""
        if lineSpacing is None:
            return
        try:
            spacing = float(lineSpacing)
        except (TypeError, ValueError, OverflowError):
            return
        if not math.isfinite(spacing):
            return
        spacing = max(0.5, min(3.0, spacing))
        factor = spacing / (self._md_layout["body_line_height"] / 100.0)
        if abs(factor - 1.0) < 1e-6:
            return
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        try:
            block = document.begin()
            while block.isValid():
                block_format = block.blockFormat()
                if block_format.lineHeight() > 0:
                    block_format.setLineHeight(
                        block_format.lineHeight() * factor,
                        block_format.lineHeightType(),
                    )
                    cursor.setPosition(block.position())
                    cursor.setBlockFormat(block_format)
                block = block.next()
        finally:
            cursor.endEditBlock()

    def _paint_pdf_pages(
        self, writer, document: QTextDocument, scale: float, pageNumbers: bool
    ) -> None:
        """按 painter 缩放渲染分页 PDF（页脚页码使用设备坐标）。"""
        width = writer.width()
        height = writer.height()
        if width <= 0 or height <= 0:
            return
        footer = 24.0 if pageNumbers else 0.0
        content_width = width / scale
        content_height = (height - footer) / scale
        if content_width <= 0 or content_height <= 0:
            return
        document.documentLayout().setPaintDevice(writer)
        document.setPageSize(QSizeF(content_width, content_height))
        page_count = max(1, document.pageCount())
        painter = QPainter(writer)
        try:
            painter.scale(scale, scale)
            context = QAbstractTextDocumentLayout.PaintContext()
            context.palette = QPalette()
            context.palette.setColor(QPalette.ColorRole.Text, QColor("#000000"))
            layout = document.documentLayout()
            footer_font = QFont(self.document().defaultFont())
            footer_font.setPixelSize(12)
            for page in range(page_count):
                if page and not writer.newPage():
                    break
                painter.save()
                painter.translate(0, -page * content_height)
                context.clip = QRectF(0, 0, content_width, content_height)
                layout.draw(painter, context)
                painter.restore()
                if pageNumbers:
                    painter.save()
                    painter.resetTransform()
                    painter.setFont(footer_font)
                    painter.setPen(QColor("#666666"))
                    painter.drawText(
                        QRectF(0, height - footer, width - 8, footer - 4),
                        int(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        ),
                        str(page + 1),
                    )
                    painter.restore()
        finally:
            painter.end()

    def exportPdf(
        self,
        path: str,
        *,
        pageSize="A4",
        orientation: str = "portrait",
        marginsMm=15.0,
        fontPointSize: Optional[float] = None,
        lineSpacing: Optional[float] = None,
        pageNumbers: bool = True,
        title: str = "",
        creator: str = "pyqt6_ela_pro",
    ) -> bool:
        """导出 PDF。``fontPointSize`` / ``lineSpacing`` / ``pageNumbers``
        只影响导出，不改屏幕；``marginsMm`` 是真实页边距。
        """
        if not path:
            return False
        self._finish_pending_render()
        size = self._resolve_pdf_page_size(pageSize)
        margins = self._normalize_pdf_margins(marginsMm)
        orientation_value = (
            QPageLayout.Orientation.Landscape
            if str(orientation).strip().lower().startswith("land")
            else QPageLayout.Orientation.Portrait
        )
        scale = self._pdf_font_scale(fontPointSize)
        try:
            writer = QPdfWriter(str(path))
            writer.setResolution(96)
            writer.setPageSize(size)
            writer.setPageOrientation(orientation_value)
            writer.setPageMargins(margins, QPageLayout.Unit.Millimeter)
            if title:
                writer.setTitle(str(title))
            if creator:
                writer.setCreator(str(creator))
            document = self._document_for_export()
            self._apply_export_line_spacing(document, lineSpacing)
            self._paint_pdf_pages(writer, document, scale, bool(pageNumbers))
        except Exception:
            return False
        return os.path.exists(path)

    def printDocument(self, printer=None) -> bool:
        """打印当前渲染内容。
        ``printer`` 为已配置的 :class:`QPrinter`；``None`` 时弹系统打印对话框
        （取消返回 ``False``）。
        """
        try:
            self._finish_pending_render()
            if printer is None:
                from PyQt6.QtPrintSupport import QPrintDialog, QPrinter

                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                dialog = QPrintDialog(printer, self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return False
            self.document().print(printer)
        except Exception:
            return False
        return True
