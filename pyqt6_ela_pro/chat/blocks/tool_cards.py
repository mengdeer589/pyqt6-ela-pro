"""工具调用卡、上下文分组卡与每步工具面板。（``pyqt6_ela_pro.chat`` 内部模块）。"""

from __future__ import annotations


import html
from typing import Optional

from ..._internal import is_deleted
from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QFont,
    QPainter,
)
from PyQt6.QtWidgets import (
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconButton,
    ElaIconType,
    ElaText,
)

from ..._styles import ColorText
from ..._theme import ElaStatusRoleType, statusColor
from .._theme import (
    blend,
    muted_color,
    text_color,
)
from ..message import (
    ElaChatToolCall,
    ElaChatToolStatusType,
)
from ..renderers import (
    ToolRenderContext,
    toolRenderer,
    toolRendererSubtitle,
)
from ._helpers import (
    _elide_source,
    toolArgumentPairs,
    toolDefaultOpen,
    toolIconName,
    toolSubtitleParts,
)
from .collapsible import _CollapsibleBlock


class ToolCallCard(_CollapsibleBlock):
    """工具层单卡片（对齐 opencode 语义）。

    默认折叠（由 :func:`toolDefaultOpen` 决定，宿主可注入策略）；``Pending`` 状态
    锁定不可展开（shell / 显式放开除外）；运行中不显示参数摘要（分片半截会误导，
    且让整行宽度跳变），完成后出现；内容区首次展开时才构建。
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        tool_call: Optional[ElaChatToolCall] = None,
        name: str = "",
        arguments: str = "",
        toolCallId: str = "",
        allowOpenWhilePending: bool = False,
        defaultOpen: Optional[bool] = None,
    ) -> None:
        call = tool_call or ElaChatToolCall(
            id=toolCallId, name=name, arguments=arguments
        )
        opened = (
            bool(defaultOpen)
            if defaultOpen is not None
            else toolDefaultOpen(call.name, call.arguments)
        )
        super().__init__(title=f"工具调用：{call.name}", opened=opened, parent=parent)
        self._call = call
        self._allow_open_while_pending = bool(allowOpenWhilePending)
        self._body_built = False
        self._args_caption: Optional[ElaText] = None
        self._args_label: Optional[ElaText] = None
        self._result_caption: Optional[ElaText] = None
        self._result_label: Optional[ElaText] = None
        #: 所属消息 id（供渲染器上下文用，0 表示独立使用本卡）
        self._message_id = 0
        #: 宿主注册的渲染器（``None`` = 未注册，走默认纯文本 body）
        self._renderer = toolRenderer(call.name)
        #: 必须持有 Python 引用：布局只转移 C++ 所有权，包装器被 GC 后再调用就是崩溃。
        self._renderer_widget = None
        self._renderer_body_holder: Optional[QWidget] = None

        self._icon = ElaIconButton(toolIconName(call.name), 14, 18, 18, self)
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._icon.setBorderRadius(4)
        # 记下默认图标色：Error -> Done 时 Q_PROPERTY 不会自动还原，得手动写回。
        self._default_icon_light = self._icon.getLightIconColor()
        self._default_icon_dark = self._icon.getDarkIconColor()
        self.insertHeaderWidget(0, self._icon)
        self._subtitle_label = ColorText(self)
        self._subtitle_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._subtitle_label.setWordWrap(False)
        self._subtitle_label.setMinimumWidth(0)
        self._args_label = ColorText(self)
        self._args_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._args_label.setWordWrap(False)
        self._args_label.setMinimumWidth(0)
        # 这几个标签显示模型给的内容：ElaText 默认 AutoText 会解析 HTML，名字里带
        # "<" 或 "&" 会被吃掉（还能注入富文本），必须固定 PlainText。
        for label in (self._title_label, self._subtitle_label, self._args_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.setMinimumWidth(0)
        self._title_text = f"工具调用：{call.name}"
        self._subtitle_text = ""
        self._args_text = ""
        #: ``(cap, len, hash, font)`` → 省略结果；resize / 主题切换会反复问
        self._elide_cache: dict = {}
        #: 上一次的失败态：``_apply_theme`` 只在它变化时跑（每次分片都刷字体在 Win7 上很贵）。
        self._error_state = None
        insert_at = self.headerLayout().count() - 1
        self.insertHeaderWidget(insert_at, self._subtitle_label)
        self.insertHeaderWidget(insert_at + 1, self._args_label)
        # _sync_header() 内部已调 _apply_theme()；再调一次会多一次字体 / 颜色写入。
        self._sync_header()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        # 初始展开的卡：super().__init__ 先 setChecked 后连 toggled，首次显示时补建正文。
        super().showEvent(event)
        if self.isOpened() and not self._body_built:
            self._build_body()

    # -- 数据 --------------------------------------------------------------

    def toolCall(self, callId: Optional[str] = None) -> ElaChatToolCall:
        """获取当前工具调用快照（``callId`` 供容器统一路由，卡内忽略）。"""
        return self._call

    def toolCallId(self) -> str:
        """获取工具调用 id。"""
        return self._call.id

    def toolName(self) -> str:
        """获取工具名称。"""
        return self._call.name

    def setMessageId(self, messageId: int) -> None:
        """设置所属消息 id（供渲染器上下文用，建卡后可补设）。

        初始展开的卡在**拿到消息 id 之后**才建正文：渲染器上下文需要它，
        构造期抢跑的话快照里的 ``messageId`` 永远是 0。
        """
        self._message_id = int(messageId or 0)
        if self.isOpened() and not self._body_built:
            self._build_body()

    def setArguments(self, arguments: str) -> None:
        """设置调用参数文本。"""
        self._call = self._call.withArguments(arguments)
        self._sync_header()
        if self._body_built:
            self._sync_body()

    def arguments(self) -> str:
        """获取调用参数文本。"""
        return self._call.arguments

    def setResult(self, result: str, ok: bool = True) -> None:
        """设置调用结果与状态（``ok=False`` 标记失败）。"""
        status = ElaChatToolStatusType.Done if ok else ElaChatToolStatusType.Error
        self._call = self._call.withResult(result, status)
        self._sync_header()
        if status == ElaChatToolStatusType.Error:
            self.setOpened(True)
        if self._body_built:
            self._sync_body()

    def result(self) -> str:
        """获取调用结果文本。"""
        return self._call.result

    def setStatus(self, status: str) -> None:
        """设置调用状态（见 :class:`ElaChatToolStatusType`）。"""
        self._call = ElaChatToolCall(
            id=self._call.id,
            name=self._call.name,
            arguments=self._call.arguments,
            result=self._call.result,
            status=status,
        )
        self._sync_header()
        # 状态变化也要通知渲染器，否则展开状态下「运行中 -> 完成」会永远停在运行态。
        if self._body_built:
            self._sync_body()

    def status(self) -> str:
        """获取调用状态。"""
        return self._call.status

    def setAllowOpenWhilePending(self, on: bool) -> None:
        """设置 pending 状态下是否允许展开（shell 类工具）。"""
        self._allow_open_while_pending = bool(on)
        self._sync_header()

    def updateResult(self, callId: str, result: str, ok: bool = True) -> None:
        """统一结果更新入口（``callId`` 由容器路由，卡内忽略）。"""
        self.setResult(result, ok=ok)

    # -- 展开与内容 --------------------------------------------------------

    def _on_toggled(self, checked: bool) -> None:
        if not checked or not self._expandable:
            # 不可展开（pending 锁定）：不能建 body，否则渲染器工厂会被提前跑掉并钉住快照。
            super()._on_toggled(checked)
            return
        if not self._body_built:
            self._build_body()
        super()._on_toggled(checked)

    def _build_body(self) -> None:
        """首次展开时才构建内容区（defer）：宿主注册了渲染器就只建它的控件。"""
        self._body_built = True
        if self._build_renderer_body():
            self.updateGeometry()
            if self.layout() is not None:
                self.layout().activate()
            return
        self._args_caption = ColorText("参数", self)
        self._args_value = ColorText(self)
        self._result_caption = ColorText("结果", self)
        self._result_value = ColorText(self)
        for label in (self._args_value, self._result_value):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.bodyLayout().addWidget(self._args_caption)
        self.bodyLayout().addWidget(self._args_value)
        self.bodyLayout().addWidget(self._result_caption)
        self.bodyLayout().addWidget(self._result_value)
        self._sync_body()
        self._apply_theme()
        self.updateGeometry()
        if self.layout() is not None:
            self.layout().activate()

    def _renderer_context(self) -> ToolRenderContext:
        """建渲染器上下文快照（不可变，不持控件引用 → 无悬垂风险）。"""
        call = self._call
        return ToolRenderContext(
            messageId=self._message_id,
            toolCallId=call.id,
            name=call.name,
            arguments=call.arguments or "",
            result=call.result or "",
            status=call.status,
            isError=call.status == ElaChatToolStatusType.Error,
            allowOpenWhilePending=self._allow_open_while_pending,
            metadata=dict(call.metadata or {}),
        )

    def _build_renderer_body(self) -> bool:
        """尝试用宿主注册的渲染器填充内容区；返回是否接管成功。

        任何异常都落回默认纯文本 body：工厂跑在 Qt 回调链里，异常冒出去就是
        0xC0000409 静默终止整个进程。
        """
        factory = self._renderer
        if factory is None:
            return False
        try:
            widget = factory(self._renderer_context())
        except Exception:
            return False
        if widget is None:
            return False
        try:
            self._renderer_widget = widget  # 先持 Python 引用
            holder = QWidget(self)
            layout = QVBoxLayout(holder)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(widget)
            self._renderer_body_holder = holder
            self.bodyLayout().addWidget(holder)
        except Exception:
            self._renderer_widget = None
            self._renderer_body_holder = None
            return False
        return True

    def _notify_renderer(self) -> None:
        """把结果 / 状态推给渲染器（widget 无该方法则跳过）。

        三重守卫缺一不可：``self`` 可能已被 ``removeMessage`` 销毁，widget 也可能
        已被宿主自行 ``deleteLater``。
        """
        widget = self._renderer_widget
        if widget is None:
            return
        if is_deleted(self) or is_deleted(widget):
            return
        update = getattr(widget, "updateToolResult", None)
        if not callable(update):
            return
        try:
            update(self._call.result or "", self._call.status)
        except Exception:
            pass

    def _sync_body(self) -> None:
        self._notify_renderer()
        if self._args_caption is None:
            return
        self._args_value.setText(self._call.arguments or "—")
        self._result_value.setText(self._call.result or "—")
        self._args_caption.setVisible(bool(self._call.arguments))
        self._args_value.setVisible(bool(self._call.arguments))

    def _sync_header(self) -> None:
        call = self._call
        running = call.status in (
            ElaChatToolStatusType.Pending,
            ElaChatToolStatusType.Running,
        )
        self._icon.setAwesome(toolIconName(call.name))
        self._title_text = f"工具调用：{call.name}"
        self.setTitle(self._title_text)
        # 宿主注册了 subtitle 就用它，否则走通用键名启发式；键传给 toolArgumentPairs 去重。
        _subtitle_key, self._subtitle_text = toolRendererSubtitle(
            call.name, call.arguments
        )
        if not self._subtitle_text:
            _subtitle_key, self._subtitle_text = toolSubtitleParts(call.arguments)
        self._subtitle_label.setVisible(bool(self._subtitle_text))
        self._args_text = "  ".join(
            toolArgumentPairs(call.arguments, excludeKey=_subtitle_key)
        )
        # 运行中不显示参数摘要：分片到达时显示半截参数既误导，又会让整行宽度跳变。
        self._args_label.setVisible(bool(self._args_text) and not running)
        # 失败态变化才重刷主题（字号 / 颜色是静态的）；省略必须在主题之后。
        is_error = call.status == ElaChatToolStatusType.Error
        if self._error_state != is_error:
            self._error_state = is_error
            self._apply_theme()
        self._elide_header_texts()

        self.setBusy(running)
        pending = call.status == ElaChatToolStatusType.Pending
        self.setExpandable(not pending or self._allow_open_while_pending)

    def _elide_header_texts(self) -> None:
        """按卡片宽度省略标题 / 副标题 / 参数摘要（三者始终单行且不重叠）。"""
        width = self.width() or self._header.width()
        if width <= 0:
            return
        avail = max(140, width - 96)  # 省略箭头 / 图标 / 进度环与间距
        title_cap = int(avail * 0.52)
        subtitle_cap = int(avail * 0.20)
        args_cap = max(60, avail - title_cap - subtitle_cap)
        for label, text, cap in (
            (self._title_label, self._title_text, title_cap),
            (self._subtitle_label, self._subtitle_text, subtitle_cap),
            (self._args_label, self._args_text, args_cap),
        ):
            if not text:
                label.setText("")
                continue
            # 先按目标像素宽度截源再测量：展示结果由 cap 决定，源串再长也不会多显示字符。
            source = _elide_source(text, cap, label.fontMetrics())
            key = (cap, len(source), hash(source), label.font().toString())
            elided = self._elide_cache.get(key)
            if elided is None:
                elided = label.fontMetrics().elidedText(
                    source, Qt.TextElideMode.ElideRight, max(0, cap)
                )
                if len(self._elide_cache) >= 12:
                    self._elide_cache.clear()
                self._elide_cache[key] = elided
            if label.text() != elided:
                label.setText(elided)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._elide_header_texts()

    def _apply_theme(self) -> None:
        super()._apply_theme()
        if not hasattr(self, "_subtitle_label"):
            return
        mode = self._theme_mode
        is_error = self._call.status == ElaChatToolStatusType.Error
        danger = statusColor(mode, ElaStatusRoleType.Error)
        title_color = (
            blend(text_color(mode), danger, 0.45) if is_error else text_color(mode)
        )
        self._title_label.setTextColor(title_color)
        self._title_label.setTextPixelSize(13)
        self._title_label.setTextWeight(QFont.Weight.DemiBold)
        self._subtitle_label.setTextColor(muted_color(mode, 0.6))
        self._subtitle_label.setTextPixelSize(12)
        self._args_label.setTextColor(muted_color(mode, 0.45))
        self._args_label.setTextPixelSize(11)
        for caption in (
            getattr(self, "_args_caption", None),
            getattr(self, "_result_caption", None),
        ):
            if caption is not None:
                caption.setTextColor(muted_color(mode, 0.5))
                caption.setTextPixelSize(11)
        for value in (
            getattr(self, "_args_value", None),
            getattr(self, "_result_value", None),
        ):
            if value is not None:
                value.setTextColor(muted_color(mode, 0.75))
                value.setTextPixelSize(12)
        if is_error:
            self._icon.setAwesome(ElaIconType.IconName.Ban)
            self._icon.setLightIconColor(danger)
            self._icon.setDarkIconColor(danger)
        else:
            # Error -> Done 的重复上报要把图标字形与颜色一起还原，否则成功后图标还是红的。
            self._icon.setAwesome(toolIconName(self._call.name))
            self._icon.setLightIconColor(self._default_icon_light)
            self._icon.setDarkIconColor(self._default_icon_dark)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().paintEvent(event)
        if self._call.status != ElaChatToolStatusType.Error:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(statusColor(self._theme_mode, ElaStatusRoleType.Error))
        painter.drawRoundedRect(0, 6, 3, max(0, self.height() - 12), 1.5, 1.5)
        painter.end()


class ContextToolGroupCard(_CollapsibleBlock):
    """上下文工具分组卡：连续 read/glob/grep/list 合并为一张卡。"""

    def __init__(
        self, parent: Optional[QWidget] = None, defaultOpen: bool = False
    ) -> None:
        super().__init__(title="正在探索", opened=defaultOpen, parent=parent)
        self._calls: list[ElaChatToolCall] = []
        self._call_rows: dict = {}
        self._counts = {"read": 0, "glob": 0, "grep": 0, "list": 0}
        self._rows_container = QWidget(self)
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        self.bodyLayout().addWidget(self._rows_container)
        self._summary_label = ColorText(self)
        self._summary_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._summary_label.setWordWrap(False)
        self.insertHeaderWidget(self.headerLayout().count() - 1, self._summary_label)
        self._sync_header()
        self._apply_theme()

    # -- 数据 --------------------------------------------------------------

    def addToolCall(self, call: ElaChatToolCall) -> None:
        """追加上下文工具调用。"""
        self._calls.append(call)
        key = (call.name or "").lower()
        if key in self._counts:
            self._counts[key] += 1
        row = ColorText(self._rows_container)
        row.setTextFormat(Qt.TextFormat.PlainText)
        self._rows_layout.addWidget(row)
        self._call_rows[call.id] = row
        self._sync_row(call)
        self._sync_header()
        self._apply_theme(row)

    def toolCall(self, callId: str) -> Optional[ElaChatToolCall]:
        """按 id 获取包含的工具调用快照。"""
        for call in self._calls:
            if call.id == callId:
                return call
        return None

    def updateResult(self, callId: str, result: str, ok: bool = True) -> None:
        """按 id 更新某个工具调用的结果与状态。"""
        status = ElaChatToolStatusType.Done if ok else ElaChatToolStatusType.Error
        for index, call in enumerate(self._calls):
            if call.id == callId:
                updated = call.withResult(result, status)
                self._calls[index] = updated
                self._sync_row(updated)
                self._sync_header()
                return

    def updateArguments(self, callId: str, arguments: str) -> None:
        """按 id 更新某个工具调用的参数（重复上报时幂等更新）。"""
        for index, call in enumerate(self._calls):
            if call.id == callId:
                updated = call.withArguments(arguments)
                self._calls[index] = updated
                self._sync_row(updated)
                self._sync_header()
                return

    def _sync_row(self, call: ElaChatToolCall) -> None:
        row = self._call_rows.get(call.id)
        if row is None:
            return
        # 与 ToolCallCard._sync_header 同一套：先算副标题键，再据此排除参数。
        subtitle_key, subtitle = toolRendererSubtitle(call.name, call.arguments)
        if not subtitle:
            subtitle_key, subtitle = toolSubtitleParts(call.arguments)
        pairs = "  ".join(
            toolArgumentPairs(call.arguments, limit=2, excludeKey=subtitle_key)
        )
        text = f"{call.name}  {subtitle}"
        if pairs:
            text += f"  {pairs}"
        if call.status == ElaChatToolStatusType.Error:
            text += "  · 失败"
        elif call.status == ElaChatToolStatusType.Aborted:
            text += "  · 已中止"
        if len(text) > 72:
            text = text[:71] + "…"
        row.setText(text)

    def finish(self) -> None:
        """全部完成（标题切「已探索」，隐藏忙碌环）。"""
        self.setTitle("已探索")
        self.setBusy(False)

    def toolCalls(self) -> list:
        """获取包含的工具调用快照。"""
        return list(self._calls)

    def count(self) -> int:
        """工具调用条数。"""
        return len(self._calls)

    def summary(self) -> str:
        """计数摘要文本（如 ``2 个文件 · 1 次搜索``）。"""
        parts = []
        if self._counts["read"]:
            parts.append(f"{self._counts['read']} 个文件")
        if self._counts["glob"]:
            parts.append(f"{self._counts['glob']} 次查找")
        if self._counts["grep"]:
            parts.append(f"{self._counts['grep']} 次搜索")
        if self._counts["list"]:
            parts.append(f"{self._counts['list']} 次列目录")
        return " · ".join(parts)

    def _sync_header(self) -> None:
        self._summary_label.setText(self.summary())
        self._summary_label.setVisible(bool(self.summary()))
        running = any(
            call.status
            in (ElaChatToolStatusType.Pending, ElaChatToolStatusType.Running)
            for call in self._calls
        )
        self.setBusy(running)
        if running:
            self.setTitle("正在探索")

    def _apply_theme(self, row: Optional[ColorText] = None) -> None:
        super()._apply_theme()
        if not hasattr(self, "_summary_label"):
            return
        self._summary_label.setTextColor(muted_color(self._theme_mode, 0.5))
        self._summary_label.setTextPixelSize(12)
        # 追加一行时只给新行上色；主题切换（row=None）才遍历全部行。
        rows = (row,) if row is not None else self._call_rows.values()
        for item in rows:
            item.setTextColor(muted_color(self._theme_mode, 0.7))
            item.setTextPixelSize(12)


class ToolGroupPanel(_CollapsibleBlock):
    """工具调用外层折叠面板（对齐 agent_chat 的「工具调用 (N)」层级）。

    与思考折叠块完全一致的内联样式：无卡片底色、标题为纯文本色（不叠强调色），
    两者只靠「>」箭头与文案区分。内容区承载 :class:`ToolCallCard` /
    :class:`ContextToolGroupCard`。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            title="工具调用 (0)", opened=False, parent=parent, surface=False
        )
        self.setCardMargins(0, 0, 0, 0)
        self._counts = (0, 0)
        self._running = False
        self._summary = ""
        self._summary_key = None
        self._title_key = None
        self._body_container = QWidget(self)
        self._tool_layout = QVBoxLayout(self._body_container)
        self._tool_layout.setContentsMargins(0, 0, 0, 0)
        self._tool_layout.setSpacing(2)
        self.bodyLayout().addWidget(self._body_container)
        # 标题 + 浅灰摘要共用一个 label：富文本片段只用于颜色，外部文本全部转义。
        self._title_label.setTextFormat(Qt.TextFormat.RichText)
        self.hide()

    # -- 内容 --------------------------------------------------------------

    def toolLayout(self) -> QVBoxLayout:
        """获取工具卡片布局（向其添加卡片）。"""
        return self._tool_layout

    def toolContainer(self) -> QWidget:
        """获取工具卡片容器。"""
        return self._body_container

    def setCounts(
        self,
        done: int,
        total: int,
        running: Optional[bool] = None,
        summary: Optional[str] = None,
    ) -> None:
        """更新标题计数与折叠摘要（``running`` 为空时按 ``done < total`` 推断）。"""
        done = max(0, int(done))
        total = max(0, int(total))
        if running is None:
            running = done < total
        self._counts = (done, total)
        self._running = bool(running)
        if summary is not None:
            self._summary = str(summary or "")
        self._sync_title()

    def setSummary(self, summary: str) -> None:
        """设置折叠态的一行工具摘要（``shell · git status``）。"""
        self._summary = str(summary or "")
        self._sync_title()

    def counts(self) -> tuple:
        """获取 ``(已完成, 总数)``。"""
        return self._counts

    def isRunning(self) -> bool:
        """是否有工具仍在运行。"""
        return self._running

    def summary(self) -> str:
        """获取折叠态摘要文本（不含标题前缀）。"""
        return self._summary

    def _sync_title(self) -> None:
        done, total = getattr(self, "_counts", (0, 0))
        summary = " ".join(str(getattr(self, "_summary", "") or "").split())
        running = getattr(self, "_running", False)
        if running:
            base = f"工具调用 ({done}/{total})"
        else:
            base = f"工具调用 ({total})"
        self._title = base
        key = (self.width(), base, summary, self._theme_mode)
        if key == getattr(self, "_title_key", None):
            self.setBusy(running)
            return
        self._title_key = key
        if not summary:
            text = html.escape(base)
            tip = ""
        else:
            title_width = self._title_label.fontMetrics().horizontalAdvance(base)
            available = max(60, self.width() - title_width - 70)
            elided = self._title_label.fontMetrics().elidedText(
                summary, Qt.TextElideMode.ElideRight, available
            )
            color = muted_color(self._theme_mode, 0.6).name()
            text = (
                f"{html.escape(base)} "
                f'<span style="color:{color}">{html.escape(elided)}</span>'
            )
            tip = summary if elided != summary else ""
        if self._title_label.text() != text:
            self._title_label.setText(text)
        if self._title_label.toolTip() != tip:
            self._title_label.setToolTip(tip)
        self.setBusy(running)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._sync_title()

    def _apply_theme(self) -> None:
        super()._apply_theme()
        mode = self._theme_mode
        # 与思考块同为纯文本色：两者靠「>」箭头与文案区分，不靠颜色（叠强调色会含混）。
        self._title_label.setTextColor(text_color(mode))
        self._title_label.setTextPixelSize(13)
        self._title_label.setTextWeight(QFont.Weight.DemiBold)
        self._sync_title()
