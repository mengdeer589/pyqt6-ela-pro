"""流式追加 / 分块渲染方法组。"""

from __future__ import annotations

import re

from PyQt6.QtCore import QElapsedTimer, QRectF
from PyQt6.QtGui import (
    QPainter,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
)

from .._internal import is_deleted
from .._motion import start_idle_loop
from ..math_lite import MATH_ENVS
from .syntax import (
    _DETAILS_CLOSE_RE,
    _DETAILS_OPEN_RE,
    _fence_close,
    _fence_open,
    _stable_cut,
)

_SCROLL_MARGIN = 4

_STREAM_INTERVAL = 24

_STREAM_INTERVAL_MID = 150

_STREAM_INTERVAL_LONG = 400

_STREAM_MID_CHARS = 16000

_STREAM_LONG_CHARS = 64000

STREAM_CARET_BLINK_MS = 500

_LARGE_RENDER_CHARS = 65536

_LARGE_RENDER_CHUNK = 16384

_LARGE_RENDER_BUDGET_MS = 16


class _MarkdownStreamMixin:
    def beginStream(self) -> None:
        """开始流式模式：清空内容，等待 ``appendMarkdown`` 追加。"""
        self._stop_stream()
        self._cancel_large_render()
        self._expanded_code_blocks.clear()
        self._expanded_folds.clear()
        self._block_source_map = None
        self._stream_active = True
        self._stream_source = ""
        self._stream_committed = 0
        self._stream_tail_pos = 0
        self._stream_cut_from = 0
        self._stream_first_flush = True
        self._stream_capture_at_bottom = True
        self._source = ""
        # 清空文档会销毁旧代码表对象；按钮 / 表格引用必须同步失效，
        # 否则重绘或布局刷新会访问已删除的 C++ 对象（PyQt 静默 abort）
        self._rebuild_code_buttons([])
        self._reset_image_scan()
        adapter = getattr(self, "_document_tooltip_adapter", None)
        if adapter is not None:
            adapter.hide()
        self._text_browser.document().clear()
        self._caret_visible = True
        # 持续动效：Reduced/Disabled 下不闪，但**光标必须留在可见态** ——
        # 闪烁的静态基态是「亮着」，停在 phase 0 等于把光标删掉，用户会以为
        # 流式卡住了。on_stop 负责摆静态基态（启动时和运行期切策略都会调）。
        start_idle_loop(
            self._caret_timer, STREAM_CARET_BLINK_MS, on_stop=self._stop_stream_caret
        )

    def appendMarkdown(self, chunk: str) -> None:
        """流式追加 Markdown 片段（AI 逐 token 输出场景）。

        稳定段只增量提交一次；未稳定的尾部按节流整体重渲染替换。
        贴底时自动跟随滚动，用户上翻后保持阅读位置。最终内容以
        ``endStream`` 的全量渲染为准。

        :param chunk: Markdown 片段
        """
        if not isinstance(chunk, str):
            raise TypeError(f"chunk 应为 str，收到 {type(chunk).__name__}")
        if not self._stream_active:
            self._cancel_large_render()
            bar = self._text_browser.verticalScrollBar()
            captured_at_bottom = bar.value() >= bar.maximum() - _SCROLL_MARGIN
            prefix = self._source
            self.beginStream()
            self._stream_capture_at_bottom = captured_at_bottom
            self._stream_source = prefix
        self._stream_source += chunk
        self._source = self._stream_source

        # 首个分片不走节流：此刻文档还是空的，等一个 24ms 节拍会在屏幕上留下
        # 「空查看器」窗口（慢机器上更久）；越早渲染，布局越早拿到真实内容与
        # 高度。只在文档为空且定时器空闲时走这条快路径，不会变成逐片全量渲染。
        if not self._stream_timer.isActive() and (
            self._text_browser.document().characterCount() <= 1
        ):
            self._stream_flush()
            return
        if self._stream_timer.isActive():
            return
        tail_len = len(self._stream_source) - self._stream_committed
        if tail_len > _STREAM_LONG_CHARS:
            interval = _STREAM_INTERVAL_LONG
        elif tail_len > _STREAM_MID_CHARS:
            interval = _STREAM_INTERVAL_MID
        else:
            interval = _STREAM_INTERVAL
        self._stream_timer.start(interval)

    def endStream(self) -> None:
        """结束流式模式：全量重渲染，保证与一次性设置内容一致。

        大文档且查看器**不在屏幕上**（后台标签页）时改走分块渲染：收尾是每轮
        生成的最后一步，不该让宿主在后台页面上卡 100~300ms。分块期间
        ``isRendering()`` 为真、结束后发 ``renderingFinished``；``streamFinished``
        仍然立即发出。读取内容 / 导出的入口会先把在途渲染补完（``_finish_pending_render``），
        所以「endStream 之后立刻读全文」的结果与同步渲染一致。
        """
        if not self._stream_active:
            return
        self._stop_stream()
        self._source = self._stream_source
        if self._should_chunk_final_render():
            self._begin_large_render()
            self._needs_render = False
        else:
            self._render()
        self.streamFinished.emit()

    def _should_chunk_final_render(self) -> bool:
        """收尾的全量重渲染是否分帧。
        只对**不可见的后台查看器**分帧：可见内容分帧重渲染会先清空文档、
        再逐块长回来（闪烁）；未显示过的独立控件也不分帧，免得调用方拿到
        """
        if len(self._source) <= _LARGE_RENDER_CHARS:
            return False
        if self.isVisible():
            return False
        window = self.window()
        return window is not self and window.isVisible()

    def _finish_pending_render(self) -> None:
        """把在途分块渲染 / 流式刷新 / 懒渲染一口气做完（读取与导出前调用）。"""
        if self._large_render_chunks:
            # 分块期间文档已被清空，_render() 读到的旧值是 0：先存下分块
            # 路径捕获的状态，渲染完再按同一策略落点（同内容重渲保留位置）。
            old_value, old_max = self._large_render_scroll
            reset_position = self._large_render_reset
            self._cancel_large_render()
            self._render()
            self._apply_render_scroll(old_value, old_max, reset_position)
            return
        if self._needs_render and self._source:
            self._needs_render = False
            self._render()
            return
        # 流式定时器还压着最新分片：不补这一步，导出 / 读取只会拿到上次
        # flush 的内容（流式长回答导出表现为大段空白）。
        if (
            self._stream_active
            and self._stream_source
            and not is_deleted(self._stream_timer)
            and self._stream_timer.isActive()
        ):
            self._stream_timer.stop()
            try:
                self._flush_stream()
            except Exception:
                self._render()

    def isStreaming(self) -> bool:
        """当前是否处于流式模式。"""
        return self._stream_active

    def setStickToBottom(self, on: bool) -> None:
        """贴底时是否自动跟随滚动，并决定 ``setMarkdown`` 换内容后的落点。
        ``True``（默认，聊天 / 流式语义）：内容在底部时追加后自动滚到底；
        ``False``（阅读语义）：``setMarkdown`` 换新内容后回到顶部，同内容重渲
        """
        self._stick_to_bottom = bool(on)
        if not self._stick_to_bottom:
            # 兜住宿主「先 setMarkdown 再关贴底」的顺序：那次渲染按贴底跳过
            # 了光标复位，否则首次布局照样跳到文末。
            self._reset_cursor_for_first_layout()

    def stickToBottom(self) -> bool:
        """是否贴底自动跟随。"""
        return self._stick_to_bottom

    def _stop_stream(self) -> None:
        if not is_deleted(self._stream_timer):
            self._stream_timer.stop()
        if not is_deleted(self._caret_timer):
            self._caret_timer.stop()
        if self._caret_visible:
            self._caret_visible = False
            if not is_deleted(self):
                self.update()
        self._stream_active = False

    def _stop_stream_caret(self) -> None:
        """停掉闪烁但**把光标留在可见态**。
        闪烁的静态基态是「亮着」。直接 ``_caret_timer.stop()`` 的话光标会停在
        「停掉」不等于「不画」：必须显式摆好静态态。
        """
        if is_deleted(self._caret_timer):
            return
        self._caret_timer.stop()
        if not self._caret_visible:
            self._caret_visible = True
            if not is_deleted(self):
                self.update()

    def _toggle_stream_caret(self) -> None:
        """流式末尾打字光标闪烁。"""
        if is_deleted(self):
            return
        self._caret_visible = not self._caret_visible
        self.update()

    def _split_large_chunks(self, text: str) -> list:
        """按安全空行切分大文档：围栏 / 公式 / details / 推理块内不切。

        空行是 Markdown 的块边界；只在这里切，表格（无空行）与缩进代码
        （空行后仍是缩进行）不会被拆开。找不到安全空行时整段并入下一块，
        宁可单块大一点，也不能把一个代码块 / 表格切成两半。
        """
        lines = text.splitlines(keepends=True)
        chunks: list[str] = []
        start = 0
        size = 0
        fence = None
        math_closer = None
        details_depth = 0
        reasoning_open = False
        tag = (self._reasoning_tag or "").strip().lower()
        open_tag = f"<{tag}>" if tag else ""
        close_tag = f"</{tag}>" if tag else ""
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            stripped = line.strip()
            if fence is not None:
                if _fence_close(line, fence):
                    fence = None
            elif math_closer is not None:
                if stripped == math_closer:
                    math_closer = None
            else:
                opened, _lang = _fence_open(line)
                if opened:
                    fence = opened
                elif stripped in ("$$", "\\["):
                    math_closer = "$$" if stripped == "$$" else "\\]"
                else:
                    env = re.match(r"\\begin\{(\w+\*?)\}\s*$", stripped)
                    if env and env.group(1).rstrip("*") in MATH_ENVS:
                        math_closer = "\\end{" + env.group(1) + "}"
                    elif _DETAILS_OPEN_RE.match(stripped):
                        details_depth += 1
                    elif _DETAILS_CLOSE_RE.match(stripped):
                        details_depth = max(0, details_depth - 1)
                    elif open_tag and stripped.lower() == open_tag:
                        reasoning_open = True
                    elif close_tag and stripped.lower() == close_tag:
                        reasoning_open = False
            size += len(line)
            safe = (
                fence is None
                and math_closer is None
                and details_depth == 0
                and not reasoning_open
                and not stripped
            )
            if safe and i + 1 < n and lines[i + 1].startswith(("    ", "\t")):
                # 空行后的缩进行仍是同一个缩进代码块
                safe = False
            if safe and size >= _LARGE_RENDER_CHUNK:
                # 空行本身丢掉：块间由 _render_large_step 的 insertBlock 分隔
                chunks.append("".join(lines[start:i]))
                start = i + 1
                size = 0
            i += 1
        tail = "".join(lines[start:])
        if tail:
            chunks.append(tail)
        chunks = [chunk for chunk in chunks if chunk]
        # 全空白文档（> 阈值）没有安全空行可切：整篇作为一个块，保证收尾能结束
        return chunks or [text]

    def _begin_large_render(self, reset_position: bool = False) -> None:
        """启动分块渲染：清空文档后按时间片逐块提交。"""
        bar = self._text_browser.verticalScrollBar()
        self._large_render_reset = reset_position
        # 必须在 document.clear() 前捕获：清空会把 bar 夹到 0，
        # 之后无从判断「同内容重渲保留位置」的旧位置。
        self._large_render_scroll = (bar.value(), bar.maximum())
        self._large_render_chunks = self._split_large_chunks(self._source)
        self._large_render_index = 0
        self._render_issues = []
        # 同 beginStream：清空文档前先让旧代码表引用失效（分块渲染期间
        # 事件循环仍会重绘，访问已删除表格会 PyQt abort）
        self._rebuild_code_buttons([])
        # **同 beginStream：必须作废源行映射**。懒建后只置 ``None``（下次
        # ``markdownSelection()`` 重建）；旧映射若留着，行号区间会被套到新
        # 文档上，``markdownSelection()`` 会返回**别的段落**的内容。
        self._block_source_map = None
        self._reset_image_scan()
        adapter = getattr(self, "_document_tooltip_adapter", None)
        if adapter is not None:
            adapter.hide()
        self._text_browser.document().clear()
        self._large_render_timer.start(0)

    def _render_large_step(self) -> None:
        """渲染一个时间片内的若干块，随后让出事件循环。"""
        if is_deleted(self) or is_deleted(self._text_browser):
            return
        if not self._large_render_chunks:
            return
        timer = QElapsedTimer()
        timer.start()
        document = self._text_browser.document()
        total = len(self._large_render_chunks)
        while (
            self._large_render_index < total
            and timer.elapsed() < _LARGE_RENDER_BUDGET_MS
        ):
            chunk = self._large_render_chunks[self._large_render_index]
            fragment, block_format = self._render_fragment(chunk, document)
            cursor = QTextCursor(document)
            cursor.movePosition(QTextCursor.MoveOperation.End)
            if document.characterCount() > 1:
                cursor.insertBlock(block_format, QTextCharFormat())
            cursor.insertFragment(fragment)
            self._large_render_index += 1
        self.renderingProgress.emit(int(self._large_render_index * 100 / total))
        if self._large_render_index >= total:
            self._finish_large_render()
        else:
            self._large_render_timer.start(0)

    def _finish_large_render(self) -> None:
        self._large_render_chunks = []
        self._large_render_index = 0
        # 源行映射懒建（markdownSelection 首次使用时构建）：分块路径全程不调
        # _render()，这里同样只作废，绝不提前付出逐块匹配的代价。
        self._block_source_map = None
        self.renderingProgress.emit(100)
        self._sync_code_buttons()
        self._schedule_layout_refresh()
        old_value, old_max = self._large_render_scroll
        self._apply_render_scroll(old_value, old_max, self._large_render_reset)
        self._refresh_search_after_render()
        self.renderingFinished.emit()

    def _cancel_large_render(self) -> None:
        self._large_render_timer.stop()
        self._large_render_chunks = []
        self._large_render_index = 0
        self._large_render_reset = False
        self._large_render_scroll = (0, 0)

    def _stream_flush(self) -> None:
        """流式刷新：提交新稳定段并替换未稳定尾部。
        迟到的定时器回调可能落在控件已销毁之后（窗口关闭 / 消息重建），
        此时直接忽略，避免访问已删除的 C++ 对象（PyQt 会 abort）。
        """
        if is_deleted(self) or is_deleted(self._text_browser):
            return
        try:
            self._flush_stream()
        except Exception:
            if is_deleted(self) or is_deleted(self._text_browser):
                return
            # 增量状态异常：退回全量渲染，保证内容正确
            self._stop_stream()
            self._render()

    def _flush_stream(self) -> None:
        browser = self._text_browser
        document = browser.document()
        bar = browser.verticalScrollBar()
        old_value, old_max = bar.value(), bar.maximum()
        at_bottom = old_value >= old_max - _SCROLL_MARGIN
        if self._stream_first_flush:
            # 从静态模式续写时 beginStream 会清空文档，首个 flush 的
            # max==0 不能作为贴底依据；使用清空前捕获的滚动状态
            at_bottom = self._stream_capture_at_bottom
            self._stream_first_flush = False

        browser.setUpdatesEnabled(False)
        try:
            cut, next_scan = _stable_cut(
                self._stream_source,
                self._stream_committed,
                allow_sentence=True,
                safe_from=self._stream_cut_from,
            )
            self._stream_cut_from = next_scan
            cut = max(cut, self._stream_committed)

            # 删除旧尾部
            if document.characterCount() > 1:
                # 尾段代码卡 QTextTable 随内容析构，但不全量清空：稳定段的表按身份
                # 增量复用，失效表由 is_deleted 过滤（见 _sync_code_buttons）。
                cursor = QTextCursor(document)
                position = max(
                    0, min(self._stream_tail_pos, document.characterCount() - 1)
                )
                cursor.setPosition(position)
                cursor.movePosition(
                    QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor
                )
                cursor.removeSelectedText()
            else:
                self._stream_tail_pos = 0

            # 提交新稳定段（只渲染一次）
            if cut > self._stream_committed:
                segment = self._stream_source[self._stream_committed : cut]
                fragment, block_format = self._render_fragment(segment, document)
                cursor = QTextCursor(document)
                cursor.movePosition(QTextCursor.MoveOperation.End)
                if document.characterCount() > 1:
                    cursor.insertBlock(block_format, QTextCharFormat())
                cursor.insertFragment(fragment)
                self._stream_committed = cut

            self._stream_tail_pos = document.characterCount() - 1

            # 渲染未稳定尾部
            tail = self._stream_source[self._stream_committed :]
            if tail:
                cursor = QTextCursor(document)
                cursor.movePosition(QTextCursor.MoveOperation.End)
                tail_fragment, tail_block_format = self._render_fragment(tail, document)
                if document.characterCount() > 1:
                    cursor.insertBlock(tail_block_format, QTextCharFormat())
                cursor.insertFragment(tail_fragment)
        finally:
            browser.setUpdatesEnabled(True)

        if self._stick_to_bottom and at_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(min(old_value, bar.maximum()))
        browser.viewport().update()
        self._sync_embedded_height()
        # 立刻重建代码按钮（不要等 80ms 后的 _schedule_layout_refresh）
        self._sync_code_buttons()
        self._schedule_layout_refresh()

    def _render_fragment(self, text: str, resource_doc: QTextDocument) -> tuple:
        """把一段 Markdown 渲染为可插入主文档的片段。

        使用临时文档走与全量渲染完全相同的管线（代码/表格/公式/主题色），
        因此片段插入后与一次性渲染结果一致；公式图片资源注册在主文档上，
        片段插入后仍可解析。

        :returns: ``(片段, 片段首块的 QTextBlockFormat)``。``insertFragment`` 把片段
            首块并入光标所在块**并沿用该块自己的格式**，所以造分块必须用首块格式，
            否则这一段的段距 / 行高 / 标题属性全丢。
        """
        scratch = QTextDocument()
        scratch.setDefaultStyleSheet(self._document_css())
        scratch.setDefaultFont(self.document().defaultFont())
        scratch.setBaseUrl(self._text_browser.document().baseUrl())
        self._render_into(scratch, text, resource_doc=resource_doc)
        cursor = QTextCursor(scratch)
        cursor.select(QTextCursor.SelectionType.Document)
        fragment = QTextDocumentFragment(cursor)
        first = scratch.firstBlock()
        block_format = first.blockFormat() if first.isValid() else QTextBlockFormat()
        return fragment, block_format

    def _apply_render_scroll(
        self, old_value: int, old_max: int, reset_position: bool
    ) -> None:
        """按滚动语义落点：贴底跟随 / 换内容回顶部 / 其余保留旧位置。"""
        bar = self._text_browser.verticalScrollBar()
        if self._stick_to_bottom and old_value >= old_max - _SCROLL_MARGIN:
            bar.setValue(bar.maximum())
        elif reset_position and not self._stick_to_bottom:
            bar.setValue(0)
        else:
            bar.setValue(min(old_value, bar.maximum()))
        self._reset_cursor_for_first_layout()

    def _reset_cursor_for_first_layout(self) -> None:
        """首次布局前把 widget 光标放回文首，避免 Qt 布局滚到文末光标。

        整体替换文档（``document.setMarkdown`` / 外部 ``QTextCursor`` 插入）会把
        浏览器自己的光标推到文末；控件还没布局过时，首次布局会
        ``ensureCursorVisible`` 到该光标并覆盖 ``bar.setValue(0)``。

        只在阅读语义且**尚无滚动范围**（= 内容还没被真实布局过）时动：
        ``setTextCursor`` 会把已布局控件直接滚到光标；聊天贴底也依赖光标在文末。
        """
        if self._stick_to_bottom:
            return
        browser = self._text_browser
        if browser.verticalScrollBar().maximum() > 0:
            return
        browser.setTextCursor(QTextCursor(browser.document()))

    def _paint_stream_caret(self, painter: QPainter) -> None:
        """流式期间在文档末尾绘制闪烁打字光标。"""
        if not (self._stream_active and self._caret_visible and self._source):
            return
        document = self.document()
        if document.characterCount() <= 1:
            return
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        rect = self._text_browser.cursorRect(cursor)
        if not rect.isValid():
            return
        top_left = self._text_browser.viewport().mapTo(self, rect.topLeft())
        painter.fillRect(
            QRectF(float(top_left.x()), float(top_left.y()), 2.0, float(rect.height())),
            self._text_color,
        )
