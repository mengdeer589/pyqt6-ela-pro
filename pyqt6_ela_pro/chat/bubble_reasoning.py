"""气泡思考段方法组。"""

from __future__ import annotations


from typing import Optional
from uuid import uuid4

from PyQt6.QtWidgets import (
    QWidget,
)

from ..ela_markdown_viewer import ElaMarkdownViewer
from ._theme import base_color
from .blocks import (
    ReasoningBlock,
    ThinkingRow,
    _HeadingScanner,
)
from .message import (
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatStatusType,
)


class _BubbleReasoningMixin:
    """方法组 mixin：状态由 ``ElaChatBubble.__init__`` 建立。"""

    def setReasoningStyle(self, style: str) -> None:
        """设置思考展示形态：``"collapse"``（默认）/ ``"inline"``。

        对已有思考段原位重建（内容 / 耗时 / 流式状态保留）。
        """
        style = (
            style
            if style in ElaChatReasoningStyleType.All
            else ElaChatReasoningStyleType.Collapse
        )
        if style == self._reasoning_style:
            return
        self._reasoning_style = style
        self._rebuild_reasoning_widgets()

    def _rebuild_reasoning_widgets(self) -> None:
        """按当前形态重建全部思考分段控件（分段数据保持不变）。"""
        # 写路径：重建的控件要拿到真实文本
        self._materialize_all()
        layout = self._parts_layout
        streaming_id = None
        for part in list(self._parts):
            if part.kind != ElaChatPartKindType.Reasoning:
                continue
            if part.id in self._suspended_viewers:
                continue  # 挂起中：保留等高占位，恢复时按新形态重建
            old = self._part_widgets.get(part.id)
            index = (
                layout.indexOf(old) if layout is not None and old is not None else -1
            )
            self._discard_part_state(part.id)
            widget = self._create_reasoning_widget()
            self._populate_reasoning_widget(widget, part)
            self._part_widgets[part.id] = widget
            if layout is not None:
                if old is not None:
                    layout.removeWidget(old)
                if index >= 0:
                    layout.insertWidget(index, widget)
                else:
                    layout.addWidget(widget)
            if old is not None:
                old.hide()
                old.setParent(None)
                old.deleteLater()
            if part.status == ElaChatStatusType.Streaming:
                streaming_id = part.id
        self._current_reasoning_id = streaming_id
        if streaming_id is not None:
            widget = self._part_widgets.get(streaming_id)
            if isinstance(widget, ElaMarkdownViewer):
                self._move_thinking_row(widget)
                self._thinking_row.begin()
                scanner = self._heading_scanners.get(streaming_id)
                if scanner is not None:
                    self._thinking_row.setHeading(scanner.result())
            elif self._thinking_row is not None:
                self._thinking_row.end()
        elif self._thinking_row is not None:
            self._thinking_row.end()

    def _populate_reasoning_widget(self, widget: QWidget, part: ElaChatPart) -> None:
        """把思考分段数据灌入重建后的控件（含流式状态）。"""
        streaming = part.status == ElaChatStatusType.Streaming
        if isinstance(widget, ReasoningBlock):
            widget.setText(part.text)
            if streaming:
                widget.setTitle("思考中")
                widget.setBusy(True)
                widget.setOpened(True)
            else:
                widget.end(part.duration_ms)
        elif isinstance(widget, ElaMarkdownViewer):
            if streaming:
                widget.beginStream()
                widget.appendMarkdown(part.text)
                scanner = _HeadingScanner()
                scanner.push(part.text)
                self._heading_scanners[part.id] = scanner
            else:
                self._write_viewer_text(part.id, widget, part.text)

    def reasoningStyle(self) -> str:
        """获取思考展示形态。"""
        return self._reasoning_style

    def _create_reasoning_widget(self) -> QWidget:
        parent = self._parts_container or self._content or self
        if self._reasoning_style == ElaChatReasoningStyleType.Inline:
            viewer = ElaMarkdownViewer(parent)
            viewer.setEmbeddedMode(True)
            viewer.setEmbeddedTrimBottom(True)
            viewer.setBorderRadius(0)
            # 同 _create_text_viewer：嵌入查看器用不透明底色避开 Win7 慢路径
            viewer.setViewportBackground(base_color(self._theme_mode))
            viewer.setStickToBottom(False)
            viewer.setMarkdown("")
            self.viewerCreated.emit(viewer)
            return viewer
        return ReasoningBlock(parent=parent)

    def _ensure_reasoning_part(self, partId: Optional[str] = None) -> str:
        if self._current_reasoning_id is not None and partId is None:
            return self._current_reasoning_id
        partId = partId or uuid4().hex[:12]
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Reasoning,
            status=ElaChatStatusType.Streaming,
            step=self._step_index,
        )
        widget = self._create_reasoning_widget()
        self._append_part(part, widget)
        self._current_reasoning_id = partId
        if isinstance(widget, ElaMarkdownViewer):
            # 内联形态才需要状态行；折叠块标题/进度环已自足，避免内容重复
            self._move_thinking_row(widget)
        return partId

    def _move_thinking_row(self, before: QWidget) -> None:
        """把思考行移动到指定控件之前（跟随当前流式推理段）。"""
        if self._parts_layout is None:
            return
        row = self.thinkingRow()
        # 先摘自身再取目标下标：removeWidget 会让其后的控件整体前移
        self._parts_layout.removeWidget(row)
        index = self._parts_layout.indexOf(before)
        if index < 0:
            index = self._parts_layout.count()
        self._parts_layout.insertWidget(index, row)

    def thinkingRow(self) -> ThinkingRow:
        """获取思考行（按需创建，位于当前推理段之前）。"""
        if self._thinking_row is None:
            self._thinking_row = ThinkingRow(
                self._parts_container or self._content or self
            )
        return self._thinking_row

    def reasoningBlock(self) -> ReasoningBlock:
        """获取当前折叠式思考块（``collapse`` 形态）。

        流式回合内没有段时按需创建；非流式且不存在思考段时抛 ``RuntimeError``
        —— 读取操作不凭空追加分段。
        """
        if self._reasoning_style != ElaChatReasoningStyleType.Collapse:
            raise RuntimeError("inline 形态请使用 inlineReasoningViewer()")
        partId = self._current_reasoning_id
        if partId is None:
            for part in reversed(self._parts):
                widget = self._part_widgets.get(part.id)
                if part.kind == ElaChatPartKindType.Reasoning and isinstance(
                    widget, ReasoningBlock
                ):
                    return widget
            if self._status != ElaChatStatusType.Streaming:
                raise RuntimeError("当前没有思考段（非流式读取不会凭空创建）")
        partId = self._ensure_reasoning_part()
        return self._part_widgets.get(partId)

    def inlineReasoningViewer(self) -> ElaMarkdownViewer:
        """获取当前内联思考查看器（需先 ``setReasoningStyle(Inline)``）。

        与 :meth:`reasoningBlock` 同一契约：读取不建分段，形态不对或非流式且
        没有思考段时抛 ``RuntimeError``。
        """
        if self._reasoning_style != ElaChatReasoningStyleType.Inline:
            raise RuntimeError("当前不是 inline 形态，请先 setReasoningStyle()")
        partId = self._current_reasoning_id
        if partId is None:
            for part in reversed(self._parts):
                widget = self._part_widgets.get(part.id)
                if part.kind == ElaChatPartKindType.Reasoning and isinstance(
                    widget, ElaMarkdownViewer
                ):
                    return widget
            if self._status != ElaChatStatusType.Streaming:
                raise RuntimeError("当前没有思考段（非流式读取不会凭空创建）")
        partId = self._ensure_reasoning_part()
        return self._part_widgets.get(partId)

    def setReasoning(self, text: str, durationMs: Optional[float] = None) -> None:
        """整体设置当前思考段内容（可选耗时，结束后自动收起）。

        先收尾在途思考段再复用当前步骤已有段，重复调用不会留下孤儿段或拼接内容。
        """
        if self._role != ElaChatRoleType.Assistant:
            return
        # 先收尾在途段：不落定缓冲就换段，旧段文本只存在于缓冲里 —— 界面上
        # 看得到、导出 ``parts`` 却是空的（数据丢失），且折叠块永远停在「思考中」。
        self.endReasoning()
        partId = self._current_step_reasoning_id()
        if partId is None:
            partId = self._ensure_reasoning_part()
        text = text or ""
        if text:
            self._mark_generation_started()
        self._discard_part_state(partId)
        widget = self._part_widgets.get(partId)
        if isinstance(widget, ReasoningBlock):
            widget.setText(text)
            if durationMs:
                widget.end(durationMs)
            else:
                widget.setOpened(bool(text))
        elif isinstance(widget, ElaMarkdownViewer):
            self._write_viewer_text(partId, widget, text)
            if self._thinking_row is not None:
                self._thinking_row.setHeading(_HeadingScanner().push(text))
        part = self._find_part(partId)
        if part is not None:
            updated = (
                part.withText(text)
                .withStatus(ElaChatStatusType.Done)
                .withDuration(float(durationMs) if durationMs else 0.0)
            )
            self._replace_part(partId, updated)
        # 「整体设置」不是流式开始：之后 appendReasoning 应新起一段，而不是往
        # 这个已落定段里继续追加。
        self._current_reasoning_id = None

    def reasoning(self) -> str:
        """获取全部思考文本（无思考内容返回空串；纯读取，不写回 ``part.text``）。"""
        return "".join(
            self.partText(part)
            for part in self._parts
            if part.kind == ElaChatPartKindType.Reasoning
        )

    def _current_step_reasoning_id(self) -> Optional[str]:
        """当前步骤已有的思考分段 id（无则返回 ``None``）。"""
        for part in reversed(self._parts):
            if part.step != self._step_index:
                return None
            if part.kind == ElaChatPartKindType.Reasoning:
                return part.id
        return None

    def beginReasoning(self, partId: Optional[str] = None) -> None:
        """开始思考（折叠块展示「思考中」；内联形态附状态行）。

        同一步骤内重复开始会复用已有思考块继续追加；``partId`` 由
        :meth:`setParts` 传入时强制新建分段（恢复时保留原分段 id）。
        """
        if self._role != ElaChatRoleType.Assistant:
            return
        self._ensure_parts_materialized()
        if partId is not None:
            new_id = self._ensure_reasoning_part(partId)
            widget = self._part_widgets.get(new_id)
            if isinstance(widget, ReasoningBlock):
                widget.begin()
            elif isinstance(widget, ElaMarkdownViewer):
                self._move_thinking_row(widget)
                self.thinkingRow().begin()
                widget.setMarkdown("")
            return
        self._current_reasoning_id = None
        existing = self._current_step_reasoning_id()
        if existing is not None:
            self._current_reasoning_id = existing
            part = self._find_part(existing)
            if part is not None and part.status != ElaChatStatusType.Streaming:
                # 复用已落定的思考段继续追加：状态要回到 Streaming
                self._replace_part(
                    existing, part.withStatus(ElaChatStatusType.Streaming)
                )
            widget = self._part_widgets.get(existing)
            if isinstance(widget, ReasoningBlock):
                widget.setTitle("思考中")
                widget.setBusy(True)
                widget.setOpened(True)
            elif isinstance(widget, ElaMarkdownViewer):
                self._move_thinking_row(widget)
                self.thinkingRow().begin()
            return
        partId = self._ensure_reasoning_part()
        widget = self._part_widgets.get(partId)
        if isinstance(widget, ReasoningBlock):
            widget.begin()
        elif isinstance(widget, ElaMarkdownViewer):
            self.thinkingRow().begin()
            widget.setMarkdown("")

    def appendReasoning(self, chunk: str) -> None:
        """追加思考文本（流式）；内联形态的标题由增量扫描器维护。"""
        if not chunk:
            return
        if self._current_reasoning_id is None:
            self.beginReasoning()
        partId = self._current_reasoning_id
        if self._find_part(partId) is None:
            return
        self._mark_generation_started()
        self._write_chunk(partId, chunk)
        widget = self._part_widgets.get(partId)
        if isinstance(widget, ReasoningBlock):
            widget.appendText(chunk)
        elif isinstance(widget, ElaMarkdownViewer):
            scanner = self._heading_scanners.get(partId)
            if scanner is None:
                scanner = _HeadingScanner()
                self._heading_scanners[partId] = scanner
            self.thinkingRow().setHeading(scanner.push(chunk))
            if not self._defer_viewer_append(partId, widget):
                widget.appendMarkdown(chunk)

    def endReasoning(self, durationMs: Optional[float] = None) -> None:
        """结束当前思考段（折叠块收起并显示耗时；内联形态隐藏状态行）。"""
        partId = self._current_reasoning_id
        if partId is None:
            if self._thinking_row is not None:
                self._thinking_row.end()
            return
        self._current_reasoning_id = None
        widget = self._part_widgets.get(partId)
        if isinstance(widget, ReasoningBlock):
            widget.end(durationMs)
        elif isinstance(widget, ElaMarkdownViewer):
            # 内联形态：必须结束查看器自身的流式状态，否则光标定时器会一直保留
            if widget.isStreaming():
                widget.endStream()
            if self._thinking_row is not None:
                self._thinking_row.end()
        # 同 endText：段结束即落定，缓冲并入 part.text
        self._materialize_part(partId)
        part = self._find_part(partId)
        if part is not None:
            updated = part.withStatus(ElaChatStatusType.Done)
            if durationMs:
                # 同一步骤内多次「开始/结束」思考时累计耗时
                updated = updated.withDuration(part.duration_ms + float(durationMs))
            self._replace_part(partId, updated)
