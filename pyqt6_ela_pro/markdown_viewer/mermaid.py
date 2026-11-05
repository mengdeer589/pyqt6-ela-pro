"""Mermaid 异步渲染 / 占位替换方法组。"""

from __future__ import annotations

import hashlib
from typing import Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import (
    QImage,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextImageFormat,
)
from PyQt6.QtWidgets import QApplication

from .._internal import is_deleted
from .. import mermaid_support
from ..mermaid_support import ElaMermaidRenderer
from .syntax import _clamp_pos
from .tokens import (
    _CODE_TOKEN_SUFFIX,
    _MERMAID_IMAGE_PREFIX,
    _MERMAID_PENDING_PREFIX,
    _MERMAID_TIP_PREFIX,
    _MERMAID_TOKEN_PREFIX,
)


_MERMAID_PRIORITY_INTERVAL_MS = 80

_MERMAID_IMAGE_MARGIN = 24


class _MarkdownMermaidMixin:
    def setMermaidRenderer(self, renderer=None) -> None:
        """设置 Mermaid 渲染器（``None`` 关闭，回退为代码卡片）。

        :param renderer: ``callable(code, theme) -> QImage | None``、
            :class:`~pyqt6_ela_pro.mermaid_support.ElaMermaidRenderer`
            或 ``None``（关闭）
        """
        if isinstance(renderer, ElaMermaidRenderer):
            if self._mermaid_renderer is not renderer:
                self._disconnect_mermaid_renderer()
                self._mermaid_renderer = renderer
                self._mermaidSlot = self._on_mermaid_rendered  # 断连要同一对象
                renderer.rendered.connect(self._mermaidSlot)
            self._mermaid_override = None
            self._mermaid_disabled = False
        elif renderer is None:
            self._disconnect_mermaid_renderer()
            self._mermaid_override = None
            self._mermaid_disabled = True
        else:
            self._disconnect_mermaid_renderer()
            self._mermaid_override = renderer
            self._mermaid_disabled = False
        if self._source:
            self._render()

    def setMermaidEnabled(self, on: bool) -> None:
        """启用/禁用 Mermaid 渲染（启用时自动探测 mermaidx）。"""
        on = bool(on)
        if on == (not self._mermaid_disabled):
            return
        self._disconnect_mermaid_renderer()
        self._mermaid_disabled = not on
        if on:
            self._mermaid_override = None
        if self._source:
            self._render()

    def mermaidAvailable(self) -> bool:
        """当前是否有可用的 Mermaid 渲染后端。"""
        return self._mermaid_enabled()

    def mermaidEnabled(self) -> bool:
        """是否启用 Mermaid 渲染（``setMermaidEnabled`` 的开关状态）。"""
        return not self._mermaid_disabled

    def setMermaidPrewarm(self, on: bool) -> None:
        """设置是否后台预热 Mermaid 引擎（默认关闭）。
        开启后立即创建渲染器并在后台启动 mermaid.js 引擎（约 0.4s），
        首次出图不再叠加冷启动耗时；仅在未设置自定义渲染函数时生效。
        """
        self._mermaid_prewarm = bool(on)
        if not self._mermaid_prewarm:
            return
        had_renderer = self._mermaid_renderer is not None
        renderer = self._ensure_mermaid_renderer()
        # 新建渲染器时 _ensure_mermaid_renderer 已触发预热，这里只补已有渲染器
        if renderer is not None and had_renderer:
            renderer.prewarm()

    def mermaidPrewarm(self) -> bool:
        """获取 Mermaid 引擎预热开关状态。"""
        return self._mermaid_prewarm

    def mermaidRenderer(self) -> Optional[ElaMermaidRenderer]:
        """获取（惰性创建的）Mermaid 渲染器。"""
        return self._ensure_mermaid_renderer()

    def _disconnect_mermaid_renderer(self) -> None:
        if self._mermaid_renderer is not None:
            try:
                self._mermaid_renderer.rendered.disconnect(self._mermaidSlot)
            except TypeError:
                pass
            self._mermaid_renderer = None
        # 旧渲染器的在途结果不再回调（信号已断开），计数一并复位
        self._mermaid_active = 0
        self._mermaid_jobs.clear()
        self._mermaid_job_keys.clear()

    def _mermaid_enabled(self) -> bool:
        if self._mermaid_disabled:
            return False
        if self._mermaid_override is not None:
            return True
        return mermaid_support.mermaidx_available()

    def _ensure_mermaid_renderer(self) -> Optional[ElaMermaidRenderer]:
        if self._mermaid_disabled:
            return None
        if self._mermaid_renderer is None:
            renderer = ElaMermaidRenderer(parent=self)
            if self._mermaid_override is not None:
                renderer.setRenderer(self._mermaid_override)
            if not renderer.available():
                return None
            self._mermaidSlot = self._on_mermaid_rendered  # 断连要同一对象
            renderer.rendered.connect(self._mermaidSlot)
            self._mermaid_renderer = renderer
            if self._mermaid_prewarm:
                renderer.prewarm()
        return self._mermaid_renderer

    def _theme_key(self) -> str:
        return "dark" if self._is_dark_theme else "light"

    def _embed_mermaid(
        self, document: QTextDocument, resource_doc, reset: bool = False
    ) -> None:
        """把 Mermaid 占位符替换为渲染图片（异步；失败/未装回退代码卡片）。

        未命中缓存的图进入待渲染队列（:attr:`_mermaid_jobs`），由
        :meth:`_pump_mermaid` 按**距视口距离**逐个提交（引擎串行，逐个提交
        不损失吞吐，但能保证当前可见的图最先出图）。

        :param reset: 全量渲染（主文档）时重置任务队列；流式片段渲染
            （临时文档）只追加，避免丢弃前面片段尚未完成的占位任务
        """
        if reset:
            self._mermaid_jobs.clear()
            self._mermaid_job_keys.clear()
        if not self._mermaid_blocks:
            return
        theme = self._theme_key()
        renderer = self._ensure_mermaid_renderer()
        resource_document = resource_doc or document
        for index, code in enumerate(self._mermaid_blocks):
            token = f"{_MERMAID_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}"
            found = document.find(token)
            if found.isNull():
                continue
            if renderer is None:
                self._insert_code_card(found, "mermaid", code)
                continue
            known, image = renderer.lookup(code, theme)
            if known:
                if image is None:
                    self._insert_code_card(found, "mermaid", code)
                else:
                    self._insert_mermaid_image(
                        found, code, image, resource_document, theme
                    )
                continue
            # 其它主题已有同源码图片时先顶上（避免主题切换时长期空白），
            # 挂上 pending 锚点，当前主题渲染完成后再替换。
            anchor = f"{_MERMAID_PENDING_PREFIX}{self._mermaid_digest(code)}-{index}"
            known_other, other_theme, other_image = renderer.lookupAnyTheme(code, theme)
            if known_other and other_image is not None:
                self._insert_mermaid_image(
                    found,
                    code,
                    other_image,
                    resource_document,
                    other_theme,
                    pending_anchor=anchor,
                )
            else:
                self._insert_mermaid_placeholder(found, index, code, anchor)
            key = (self._mermaid_digest(code), theme)
            if key in self._mermaid_job_keys:
                continue
            self._mermaid_job_keys.add(key)
            self._mermaid_jobs.append(
                {
                    "index": index,
                    "code": code,
                    "digest": key[0],
                    "anchor": anchor,
                    "theme": theme,
                    "distance": float("inf"),
                }
            )
        self._refresh_mermaid_priorities()
        self._schedule_mermaid_pump()

    def _mermaid_view_max_width(self) -> float:
        """当前阅读列可用的图片最大宽度（像素）。"""
        return max(self._content_text_width() - _MERMAID_IMAGE_MARGIN, 120)

    def _mermaid_anchor_positions(self) -> dict:
        """一次遍历收集 ``mermaid-pending-`` 锚点的视口 y 坐标。"""
        positions: dict = {}
        if not self._mermaid_jobs:
            return positions
        browser = self._text_browser
        document = self.document()
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    for name in fragment.charFormat().anchorNames():
                        if name.startswith(_MERMAID_PENDING_PREFIX):
                            cursor = QTextCursor(document)
                            cursor.setPosition(fragment.position())
                            positions[name] = browser.cursorRect(cursor).center().y()
                iterator += 1
            block = block.next()
        return positions

    def _refresh_mermaid_priorities(self) -> None:
        """重算待渲染任务与视口中心的距离（滚动/文档变化后调用）。"""
        if is_deleted(self) or not self._mermaid_jobs:
            return
        center = max(1, self._text_browser.viewport().height()) / 2.0
        positions = self._mermaid_anchor_positions()
        for job in self._mermaid_jobs:
            y = positions.get(job.get("anchor"))
            job["distance"] = float("inf") if y is None else abs(y - center)

    def _schedule_mermaid_pump(self, delay: int = 0) -> None:
        """延后提交下一个任务（让贴底/滚动逻辑先更新视口位置）。"""
        if not self._mermaid_pump_timer.isActive():
            self._mermaid_pump_timer.start(delay)

    def _pump_mermaid(self) -> None:
        """提交下一个待渲染任务（引擎串行，同一时刻只保留一个在途请求）。"""
        if is_deleted(self):
            return
        if self._mermaid_disabled or not self._mermaid_jobs or self._mermaid_active:
            return
        renderer = self._ensure_mermaid_renderer()
        if renderer is None:
            return
        theme = self._theme_key()
        self._refresh_mermaid_priorities()
        renderer.setMaxImageWidth(self._mermaid_view_max_width())
        while self._mermaid_jobs:
            job = min(self._mermaid_jobs, key=lambda item: item["distance"])
            self._mermaid_jobs.remove(job)
            job_theme = job.get("theme", theme)
            if job_theme != theme:
                continue  # 旧主题任务：主题已切换，丢弃
            known, image = renderer.lookup(job["code"], theme)
            if known:
                self._replace_mermaid_pending(job["code"], theme, image)
                continue
            self._mermaid_active += 1
            renderer.request(job["code"], theme)
            return

    def _replace_mermaid_pending(self, code: str, theme: str, image) -> None:
        """把文档中该源码的 pending 锚点（占位文本/旧主题图）替换为最终结果。"""
        prefix = f"mermaid-pending-{self._mermaid_digest(code)}-"
        ranges = self._find_anchor_ranges(self.document(), prefix)
        if not ranges:
            return
        document = self.document()
        for start, end in reversed(ranges):
            cursor = QTextCursor(document)
            cursor.setPosition(_clamp_pos(document, start))
            cursor.setPosition(
                _clamp_pos(document, end), QTextCursor.MoveMode.KeepAnchor
            )
            if image is None:
                self._record_issue("mermaid", code)
                self._insert_code_card(cursor, "mermaid", code)
            else:
                self._insert_mermaid_image(cursor, code, image, document, theme)

    @staticmethod
    def _mermaid_digest(code: str) -> str:
        return hashlib.md5(code.encode("utf-8")).hexdigest()[:12]

    def _insert_mermaid_placeholder(
        self, cursor: QTextCursor, index: int, code: str, anchor: Optional[str] = None
    ) -> None:
        """渲染进行中占位（带唯一锚点名，供异步结果定位替换）。"""
        name = anchor or f"mermaid-pending-{self._mermaid_digest(code)}-{index}"
        fmt = QTextCharFormat()
        fmt.setForeground(self._muted_color)
        fmt.setFontItalic(True)
        fmt.setAnchorNames([name])
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        cursor.insertText("Mermaid 渲染中…", fmt)
        cursor.endEditBlock()

    def _insert_mermaid_image(
        self,
        cursor: QTextCursor,
        code: str,
        image: QImage,
        resource_doc: QTextDocument,
        theme: str,
        pending_anchor: Optional[str] = None,
    ) -> None:
        """把占位符替换为 Mermaid 渲染图片（居中、限宽、tooltip 存源码）。

        :param pending_anchor: 非空时给图片挂上 pending 锚点（旧主题降级图），
            当前主题渲染完成后可再次定位替换
        """
        digest = hashlib.md5(f"{code}|{theme}".encode("utf-8")).hexdigest()
        url = f"{_MERMAID_IMAGE_PREFIX}{digest}"
        resource_doc.addResource(
            QTextDocument.ResourceType.ImageResource, QUrl(url), image
        )
        width = image.width() / 2.0
        height = image.height() / 2.0
        max_width = self._mermaid_view_max_width()
        if width > max_width > 0:
            height = height * max_width / width
            width = max_width
        image_format = QTextImageFormat()
        image_format.setName(url)
        image_format.setWidth(width)
        image_format.setHeight(height)
        image_format.setToolTip(f"{_MERMAID_TIP_PREFIX}{code}")
        image_format.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignMiddle)
        if pending_anchor:
            image_format.setAnchorNames([pending_anchor])
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        cursor.insertImage(image_format)
        block_format = cursor.blockFormat()
        block_format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        block_format.setTopMargin(6)
        block_format.setBottomMargin(6)
        cursor.setBlockFormat(block_format)
        cursor.endEditBlock()

    def _find_anchor_ranges(self, document: QTextDocument, prefix: str) -> list:
        """扫描文档中锚点名以 ``prefix`` 开头的片段范围 ``[(start, end)]``。"""
        ranges: list = []
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    names = fragment.charFormat().anchorNames()
                    if any(name.startswith(prefix) for name in names):
                        ranges.append(
                            (
                                fragment.position(),
                                fragment.position() + fragment.length(),
                            )
                        )
                iterator += 1
            block = block.next()
        return ranges

    def _on_mermaid_rendered(self, code: str, theme: str, image) -> None:
        """渲染完成（GUI 线程）：替换对应占位符/降级图，并提交下一个任务。"""
        self._mermaid_active = max(0, self._mermaid_active - 1)
        if self._mermaid_disabled:
            return
        try:
            if theme == self._theme_key():
                self._replace_mermaid_pending(code, theme, image)
        finally:
            # 延后一拍：替换图片可能引起滚动/贴底，下一个任务按最新视口选择
            self._schedule_mermaid_pump()

    def _mermaid_source_at_cursor(self) -> str:
        return self._image_source_at_cursor(_MERMAID_IMAGE_PREFIX, _MERMAID_TIP_PREFIX)

    def _copy_mermaid_at_cursor(self) -> None:
        code = self._mermaid_source_at_cursor()
        if not code:
            return
        QApplication.clipboard().setText(code)
        self.mermaidCopied.emit(code)
