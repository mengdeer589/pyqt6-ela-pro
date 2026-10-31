"""气泡文本分段 / 流式缓冲 / 查看器挂起方法组（从 ``ElaChatBubble`` 拆出）。"""

from __future__ import annotations

from .bubble_shared import _STREAMING_PLACEHOLDER


from typing import Optional
from uuid import uuid4

from .._internal import is_deleted
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
)

from ..ela_markdown_viewer import ElaMarkdownViewer
from ._theme import base_color
from .blocks import (
    ReasoningBlock,
)
from .message import (
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatStatusType,
)


class _BubbleTextMixin:
    """方法组 mixin：状态由 ``ElaChatBubble.__init__`` 建立。"""

    def hasPendingText(self) -> bool:
        """是否存在尚未落定的流式分片。"""
        return bool(self._text_buffers)

    def _buffer_chunk(self, partId: str, chunk: str) -> None:
        """把流式分片放入该分段的文本缓冲（落定时才并入 ``part.text``）。"""
        self._text_buffers.setdefault(partId, []).append(chunk)

    def _write_chunk(self, partId: str, chunk: str) -> None:
        """写入一个文本分片：流式时入缓冲，非流式时**直接落定**。

        「在途」只存在于流式回合内。往一条**已结束**的消息追加文本时若也走
        缓冲，就再也没有 ``endText()`` 来结算它，``part.text`` 永远是空的 ——
        界面上看得到（查看器自己持有文本），但对序列化 / 存储完全不可见。
        所以按消息状态分流。
        """
        if self._status == ElaChatStatusType.Streaming:
            self._buffer_chunk(partId, chunk)
            return
        part = self._find_part(partId)
        if part is not None:
            self._replace_part(partId, part.withText((part.text or "") + chunk))

    def _materialize_part(self, partId: str) -> None:
        """把指定分段的缓冲分片并入 ``part.text``（**写**操作）。"""
        chunks = self._text_buffers.pop(partId, None)
        if not chunks:
            return
        part = self._find_part(partId)
        if part is not None:
            self._replace_part(partId, part.withText(part.text + "".join(chunks)))

    def _materialize_all(self) -> None:
        """物化全部分段的文本缓冲（**写**操作）。

        只在**写路径**调用 —— 需要把真实文本灌进新建 / 重建的控件，或在分段
        结束时落定。**读路径一律不许调用**：``parts()`` / ``text()`` /
        ``reasoning()`` 必须保持纯读取，否则 ``part.text`` 的值会取决于
        「有没有被读过」，可序列化的落定语义就废了。
        """
        for partId in list(self._text_buffers):
            self._materialize_part(partId)

    def _discard_part_state(self, partId: str) -> None:
        """清理分段的缓冲与扫描器（分段被替换 / 移除时调用）。"""
        self._text_buffers.pop(partId, None)
        self._heading_scanners.pop(partId, None)
        self._pending_renders.pop(partId, None)

    def setRenderDeferred(self, on: bool) -> None:
        """设置是否延迟 Markdown 渲染（批量加载历史时先建骨架）。

        延迟期间正文 / 内联思考只记录待渲染分段，查看器保持空内容；
        由 :meth:`flushRender` 统一渲染（视图批量队列调用）。
        """
        self._render_deferred = bool(on)

    def renderDeferred(self) -> bool:
        """是否处于延迟渲染状态。"""
        return self._render_deferred

    def hasPendingRender(self) -> bool:
        """是否有等待渲染的查看器。"""
        return bool(self._pending_renders)

    def flushRender(self) -> bool:
        """渲染全部待渲染查看器；返回是否执行了渲染。"""
        if not self._pending_renders:
            return False
        pending = dict(self._pending_renders)
        self._pending_renders.clear()
        # 写路径：新建的查看器要拿到真实文本才能填内容
        self._materialize_all()
        for partId in pending:
            part = self._find_part(partId)
            widget = self._part_widgets.get(partId)
            if part is None or not isinstance(widget, ElaMarkdownViewer):
                continue
            if (
                part.kind == ElaChatPartKindType.Reasoning
                and part.status == ElaChatStatusType.Streaming
            ):
                widget.beginStream()
                widget.appendMarkdown(part.text)
            else:
                widget.setMarkdown(part.text)
        return True

    def _write_viewer_text(self, partId: str, widget: QWidget, text: str) -> None:
        """把文本写入查看器；延迟渲染模式下仅登记待渲染。"""
        if not isinstance(widget, ElaMarkdownViewer):
            return
        if self._render_deferred:
            if text:
                self._pending_renders[partId] = True
            return
        widget.setMarkdown(text or "")

    def _defer_viewer_append(self, partId: str, widget: QWidget) -> bool:
        """追加路径的延迟闸门：延迟期间只登记待渲染。

        ``setParts``（存储恢复）是**重放**增量 API 走完的，正文与思考分片最终都
        落在 :meth:`appendText` / ``appendReasoning`` 的 ``appendMarkdown`` 上 ——
        那两处若不看 ``_render_deferred``，批量加载几百条 parts 消息就照样在主线程
        同步渲染全部 Markdown，渐进渲染形同虚设。

        :returns: ``True`` = 已登记待渲染，调用方不要再写查看器。
        """
        if not self._render_deferred or not isinstance(widget, ElaMarkdownViewer):
            return False
        if self._find_part(partId) is None:
            return False
        self._pending_renders[partId] = True
        return True

    def setViewersSuspended(self, on: bool) -> None:
        """挂起 / 恢复全部 Markdown 查看器（视口外消息省内存与 reflow）。

        挂起时用等高透明占位控件替换查看器（布局高度不变，``parts`` 数据
        不变）；恢复时按分段内容重新渲染。流式中的分段不会被挂起。
        """
        on = bool(on)
        if on == self._viewers_suspended:
            return
        if on:
            self._suspend_viewers()
        else:
            self._restore_viewers()

    def viewersSuspended(self) -> bool:
        """查看器是否处于挂起状态。"""
        return self._viewers_suspended

    def hasExpandedSections(self) -> bool:
        """是否有用户展开中的折叠块 / 思考块 / 工具面板。

        壳回收会销毁这些控件（展开态不属 ``parts`` 数据），因此调用方应跳过
        这类消息，避免用户滚回来时发现手动展开的内容又收起了。
        """
        for card in self._tool_cards.values():
            if card is not None and not is_deleted(card) and card.isOpened():
                return True
        for panel in self._panels:
            if panel is not None and not is_deleted(panel) and panel.isOpened():
                return True
        for part in self._parts:
            if part.kind != ElaChatPartKindType.Reasoning:
                continue
            widget = self._part_widgets.get(part.id)
            if isinstance(widget, ReasoningBlock) and widget.isOpened():
                return True
        return False

    def _suspend_viewers(self) -> None:
        layout = self._parts_layout
        for part in self._parts:
            if part.status == ElaChatStatusType.Streaming:
                continue
            widget = self._part_widgets.get(part.id)
            if not isinstance(widget, ElaMarkdownViewer):
                continue
            height = max(1, widget.height())
            self._suspended_viewers[part.id] = height
            placeholder = QWidget(self._parts_container or self._content or self)
            placeholder.setFixedHeight(height)
            placeholder.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            index = layout.indexOf(widget) if layout is not None else -1
            self._part_widgets[part.id] = placeholder
            if layout is not None:
                layout.removeWidget(widget)
                if index >= 0:
                    layout.insertWidget(index, placeholder)
                else:
                    layout.addWidget(placeholder)
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        self._viewers_suspended = bool(self._suspended_viewers)

    def _restore_viewers(self) -> None:
        if not self._suspended_viewers:
            self._viewers_suspended = False
            return
        # 写路径：重建的查看器要拿到真实文本
        self._materialize_all()
        layout = self._parts_layout
        for partId, _height in list(self._suspended_viewers.items()):
            part = self._find_part(partId)
            placeholder = self._part_widgets.get(partId)
            if part is None:
                self._suspended_viewers.pop(partId, None)
                # 占位控件对应的分段已不存在：一并收掉，别留在布局里
                if placeholder is not None and not is_deleted(placeholder):
                    self._part_widgets.pop(partId, None)
                    placeholder.hide()
                    placeholder.setParent(None)
                    placeholder.deleteLater()
                continue
            if part.kind == ElaChatPartKindType.Reasoning:
                widget = self._create_reasoning_widget()
                # 用与「形态切换重建」同一套灌数据逻辑：内联（查看器）与
                # 折叠（ReasoningBlock）两种形态都要恢复文本与耗时
                self._populate_reasoning_widget(widget, part)
            else:
                widget = self._create_text_viewer()
                if part.status == ElaChatStatusType.Streaming:
                    widget.beginStream()
                    widget.appendMarkdown(part.text)
                else:
                    widget.setMarkdown(part.text)
            index = (
                layout.indexOf(placeholder)
                if layout is not None and placeholder is not None
                else -1
            )
            self._part_widgets[partId] = widget
            if layout is not None:
                if placeholder is not None:
                    layout.removeWidget(placeholder)
                if index >= 0:
                    layout.insertWidget(index, widget)
                else:
                    layout.addWidget(widget)
            if placeholder is not None:
                placeholder.hide()
                placeholder.setParent(None)
                placeholder.deleteLater()
            self._suspended_viewers.pop(partId, None)
        self._viewers_suspended = False

    def setText(self, text: str) -> None:
        """设置消息文本（助手消息整体替换当前正文段并走 Markdown 渲染）。"""
        if self._role != ElaChatRoleType.Assistant:
            self._user_text = str(text or "")
            if self._label is not None:
                if self._role == ElaChatRoleType.User:
                    self._render_user_text()
                else:
                    self._label.setText(self._user_text)
                self._update_max_width()
            return
        self._ensure_parts_materialized()
        # 整体替换：还没开段的空白分片属于旧内容，一起丢弃
        self._pending_text_lead.clear()
        if text:
            self._mark_generation_started()
        # 多段正文（多步骤）时 setText 是**整体替换**：先清掉已有正文段，
        # 否则 ``updateMessage(mid, "C")`` 会得到 "A" + "C" 的拼接，而 view 的
        # 文档承诺「整体替换消息文本」。
        if (
            text
            and sum(1 for item in self._parts if item.kind == ElaChatPartKindType.Text)
            > 1
        ):
            self._remove_parts({ElaChatPartKindType.Text})
            self._current_text_id = None
        partId = self._current_text_id or self._last_text_part_id()
        if partId is None:
            if not text:
                return  # 空文本不建空分段（会污染 parts 与导出结果）
            self.beginText()
            partId = self._current_text_id
        self._discard_part_state(partId)
        part = self._find_part(partId)
        if part is not None:
            self._replace_part(partId, part.withText(text or ""))
        widget = self._part_widgets.get(partId)
        self._write_viewer_text(partId, widget, text or "")

    def appendText(self, chunk: str) -> None:
        """追加文本（助手消息追加到当前正文段，用户消息追加到气泡）。

        **纯空白分片不开正文段**：模型常先吐 ``"\\n\\n"`` 再吐正文，直接开段会
        在时间线上留一个空 text part（污染 ``parts`` / 导出），还把「空回答」
        误判成有正文。所以没有打开正文段时先把空白攒进 ``_pending_text_lead``，
        等首个非空白分片一起开段 —— 中段的空白（``"hello" + " " + "world"``）
        不走这条路，照常保留。
        """
        if not chunk:
            return
        if self._role != ElaChatRoleType.Assistant:
            self._user_text += chunk
            if self._label is not None:
                if self._role == ElaChatRoleType.User:
                    self._render_user_text()
                else:
                    self._label.setText(self._user_text)
                self._update_max_width()
            return
        if self._current_text_id is None:
            if not chunk.strip():
                self._pending_text_lead.append(chunk)
                return
            lead = "".join(self._pending_text_lead)
            self._pending_text_lead.clear()
            self.beginText()
            chunk = lead + chunk
        partId = self._current_text_id
        if self._find_part(partId) is None:
            return
        self._mark_generation_started()
        self._write_chunk(partId, chunk)
        widget = self._part_widgets.get(partId)
        if isinstance(widget, ElaMarkdownViewer) and not self._defer_viewer_append(
            partId, widget
        ):
            widget.appendMarkdown(chunk)

    def _create_text_viewer(self) -> ElaMarkdownViewer:
        viewer = ElaMarkdownViewer(self._parts_container or self._content or self)
        viewer.setEmbeddedMode(True)
        # 文末段落下边距不计入高度：正文与后续分段的视觉间距与其它分段一致
        viewer.setEmbeddedTrimBottom(True)
        viewer.setBorderRadius(0)
        # 不透明底色（与消息区同色）：嵌入查看器默认透明，Win7 上会走慢速
        # 重绘路径（见「下游项目反馈bug.md」§4）
        viewer.setViewportBackground(base_color(self._theme_mode))
        viewer.setStickToBottom(False)
        if self._status == ElaChatStatusType.Streaming:
            viewer.setPlaceholderText(_STREAMING_PLACEHOLDER)
        self.viewerCreated.emit(viewer)
        return viewer

    def _restore_text_part(self, partId: str, text: str) -> None:
        """历史恢复正文段：一次性 ``setMarkdown``，不走流式缓冲（bug #17）。"""
        if self._current_text_id is not None:
            self.endText()
        viewer = self._create_text_viewer()
        viewer.setMarkdown(text or "")
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Text,
            status=ElaChatStatusType.Done,
            text=text or "",
            step=self._step_index,
        )
        self._append_part(part, viewer)
        self._current_text_id = None

    def beginText(self, partId: Optional[str] = None) -> Optional[str]:
        """开始一个新的正文段，返回分段 id（非助手消息返回 ``None``）。

        ``partId`` 可由调用方指定（从存储恢复时保留原分段 id，使
        ``messageId`` / ``partId`` 在重启后保持稳定），缺省自动生成。
        """
        if self._role != ElaChatRoleType.Assistant:
            return None
        self._ensure_parts_materialized()
        if self._current_text_id is not None:
            self.endText()
        partId = partId or uuid4().hex[:12]
        status = (
            ElaChatStatusType.Streaming
            if self._status == ElaChatStatusType.Streaming
            else ElaChatStatusType.Done
        )
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Text,
            status=status,
            step=self._step_index,
        )
        self._append_part(part, self._create_text_viewer())
        self._current_text_id = partId
        return partId

    def endText(self) -> None:
        """结束当前正文段（停止流式光标，并把缓冲落成定稿文本）。"""
        # 没开段的空白分片不算内容，收尾时丢弃
        self._pending_text_lead.clear()
        partId = self._current_text_id
        if partId is None:
            return
        self._current_text_id = None
        widget = self._part_widgets.get(partId)
        if isinstance(widget, ElaMarkdownViewer):
            if widget.isStreaming():
                widget.endStream()
            widget.setPlaceholderText("")
        # 段结束即落定：把缓冲并入 part.text，使 part.text 自足、可序列化，
        # 且与读取时机无关（对齐 opencode「`.ended` 携带全量并覆盖」）。
        # 此前只在 parts() 被读时才物化，导致流结束后仍可能残留未落定缓冲。
        self._materialize_part(partId)
        part = self._find_part(partId)
        if part is not None:
            self._replace_part(partId, part.withStatus(ElaChatStatusType.Done))

    def beginStep(self) -> int:
        """开始新步骤：结束当前正文段与工具分组（空步骤不递增）。"""
        if self._role != ElaChatRoleType.Assistant:
            return self._step_index
        if self._step_empty():
            return self._step_index
        self.endText()
        self._finish_tool_group()
        # 思考段也要收尾：此前只把 _current_reasoning_id 置 None 而不
        # endReasoning()，宿主若不显式调用 endReasoning（binder 会调，
        # 手写宿主未必），ReasoningBlock 会永远停在「思考中」转圈，
        # 对应 part 的 status 也冻在 streaming。
        self.endReasoning()
        if self._thinking_row is not None:
            self._thinking_row.end()
        self._step_index += 1
        self._current_text_id = None
        self._current_reasoning_id = None
        self._current_stats_id = None
        self._current_tool_panel = None
        return self._step_index

    def stepIndex(self) -> int:
        """获取当前步骤序号（从 1 开始）。"""
        return self._step_index
