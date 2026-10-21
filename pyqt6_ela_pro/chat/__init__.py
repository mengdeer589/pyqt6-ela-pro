"""
``pyqt6_ela_pro.chat``：ChatGPT 风格聊天组件（自研，交互参考 ChatGPT）。

包级导出：

- 组装与视图：:class:`ElaChatWidget`（消息列表 + 输入区）、
  :class:`ElaChatView`、:class:`ElaChatInput`；
- 分层部件：:class:`ElaChatBubble`（消息气泡）、
  :class:`ElaChatToolBar` / :class:`ElaChatToolButton`（工具栏）、
  :class:`MessageHeader`、:class:`ReasoningBlock`、
  :class:`ToolGroupPanel`（每步工具面板）、:class:`ToolCallCard`、
  :class:`ContextToolGroupCard`、:class:`ThinkingRow`、
  :class:`AttachmentStrip`、:class:`StatsBadge`、:class:`MessageActions`、
  :class:`ErrorCard`；
- 数据模型：:class:`ElaChatMessage`（步骤化 :class:`ElaChatPart` 时间线，
  含 :class:`ElaChatAttachment` / :class:`ElaChatToolCall` /
  :class:`ElaChatStats`）、:class:`ElaChatSessionInfo` /
  :class:`ElaChatSessionStats`；
- 常量：:class:`ElaChatRoleType` / :class:`ElaChatStatusType` /
  :class:`ElaChatToolStatusType` / :class:`ElaChatPartKindType` /
  :class:`ElaChatReasoningStyleType`；

结构设计：

- **输入区** 分三层：附件 chips 行 → ``ElaPlainTextEdit`` →
  工具栏（左：上传 + 清空上下文 + 自定义工具；右：自定义 + 发送 / 停止）；
  工具栏支持 ``addButton`` / ``addWidget`` / ``addSeparator`` 三种扩展入口；
  **大段粘贴自动转附件**（临时文件走同一附件管线，见 ``ElaChatInput`` 的说明）；
- **消息** 分四层：头部（头像 + 名称 + 时间 / 状态）→ 内容分段
  （思考段 → 正文段 → 每步工具面板 → 步骤用量徽标，按加入顺序组成
  时间线；用户纯文本 / 系统提示为单段弱化样式）→ 附件 chips →
  底部（复制 / 撤回 / 重新生成 + 整轮耗时 meta；点击「复制」后弹
  ``ElaMessageBar``「已复制到剪贴板」确认，默认开、``setCopyNotificationEnabled``
  可关）；用量徽标默认只显示
  一个整轮汇总（各步求和，``setStatsMode`` 可切换逐步骤 / 关闭）；
- 助手消息复用 :class:`~pyqt6_ela_pro.ela_markdown_viewer.ElaMarkdownViewer`
  的**嵌入模式**（透明背景 / 隐藏滚动条 / 高度自适应），因此公式、Mermaid、
  代码高亮、流式光标等能力与查看器完全一致；
- **两层的分工（重要）**：:class:`ElaChatWidget` 只负责**输入区 + 回合编排**
  （``beginAssistantMessage`` / ``endAssistantMessage`` / ``stopGeneration`` /
  撤回 / 重生 / 排队 / 头像 / 主题）；**消息内容**（正文 / 思考 / 工具调用 /
  分段 / 用量 / 存储）**只在** :class:`ElaChatView` 上，经 ``chat.chatView()``
  调用。曾经 widget 还转发过 54 个同名方法，只把 ``messageId`` 从首位挪到末位
  —— 两套签名混用时本该是消息 id 的值会落到别的参数上，界面看着正常但数据是
  错的。转发层已删除，``messageId`` 现在只有一套约定。
- 命令式流式 API：``view.beginMessage()`` → ``beginStep`` / ``beginText`` /
  ``appendText`` / ``setStepStats`` → ``endMessage``；思考 / 工具调用分别经
  ``beginReasoning`` / ``addToolCall`` 驱动。需要「跟随当前流式消息」的宿主可用
  :class:`ElaChatWidget` 的 ``beginAssistantMessage`` / ``endAssistantMessage``。
- **回合 token**：后端 ``ask`` / ``regenerate`` 返回回合 token，``turnFinished``
  原样带回；``binder.startTurn`` 把它交给 ``binder.finish`` 认领收尾。后端
  ``cancel()`` 是异步的，旧回合的收尾信号可能晚几十毫秒到达 —— 认不出的迟到
  信号被 ``finish`` 丢弃（返回 ``None``），不会把新回合按「完成」掐掉。
- 数据只读：``view.messages()`` 返回 ``ElaChatMessage`` 快照列表
  （助手消息含 ``parts`` 与派生字段；**流式在途分片不写回 ``part.text``**，
  所以快照在任意时刻都可直接落库，回合结束才是完整正文）；
- **持久化**：``message.toDict()`` → ``jsonDumps(allow_nan=False)`` 落库，
  ``view.addMessageFromDict()`` / ``view.restoreMessages()`` 读回。
  ``fromDict()`` 一律容错（缺字段取默认、多余字段忽略、类型强转、NaN 归零），
  未知 ``part.kind`` 被丢弃；格式版本见 :data:`SCHEMA_VERSION`。
  ``jsonDumps`` / ``jsonLoads`` / ``jsonBackend`` 是库内统一的 JSON 编解码：
  **装了 ``orjson`` 就用 orjson，否则用标准库 json**（两套后端产出同为紧凑
  UTF-8 文本；``allow_nan=False`` 语义一致）；
- **崩溃恢复**：回合**中途**进程死掉时，在途分片会丢（缓冲只在内存里）。
  :class:`ElaChatTurnJournal` 把回合记成**追加写事件流**
  （``journal.dumpsNewLines()`` 一行一条、只给新增的那些；崩了最多丢最后一行），
  ``ElaChatTurnJournal.fromLines()`` 重放出完整消息 —— 可与 binder 并行
  连同一批 worker 信号（``journal.connectWorker(worker)``）；
- **多话题**是**宿主的事务**（一话题一 widget，见 ``example/chat_session_page.py``）：
  会话列表 UI、归档 / 恢复、话题排序都不在库里，本包只提供
  :class:`ElaChatSessionInfo` 与 ``view.exportSession`` / ``importSession``
  这对数据层接口；
- 主题经 ``eTheme`` 语义令牌实时换肤，命名统一 ``camelCase``。

用法::

    from pyqt6_ela_pro.chat import ElaChatWidget

    chat = ElaChatWidget(parent)
    chat.chatView().setSuggestions(["用一句话解释量子纠缠", "写一个快速排序"])
    chat.toolBar().addButton(icon=ElaIconType.IconName.Bolt, tooltip="自定义工具",
                             callback=on_custom_tool)
    chat.messageSubmitted.connect(on_ask)      # 宿主驱动生成

**两层的分工**：:class:`ElaChatWidget` 只管**输入区 + 回合编排**
（``beginAssistantMessage`` / ``appendText`` 的回合入口 / ``stopGeneration`` /
撤回 / 重生 / 排队）；**消息内容**一律经 ``chat.chatView()`` 操作。这样
``messageId`` 只有一套位置约定（view 层首位必填），不存在两套签名混用的风险。

存储接入::

    from pyqt6_ela_pro.chat import ElaChatWidget, jsonDumps

    chat = ElaChatWidget(parent)
    view = chat.chatView()
    view.restoreMessages(load_rows())                     # 读回（重新分配 id）
    for message in view.messages():                       # 落库
        save_row(jsonDumps(message.toDict()))
    # 需要跨重启稳定 id 时逐条恢复（id 冲突会抛 ValueError）
    view.addMessageFromDict(row)

会话 bundle（导出 / 导入整会话；多话题持久化的数据层）::

    from pyqt6_ela_pro.chat import ElaChatSessionInfo

    bundle = view.exportSession(                    # 纯 JSON dict，可直接落库
        session=ElaChatSessionInfo(id="s1", title="快速排序"),
        extra={"model": "deepseek-v4"},             # 宿主自定义元数据（原样带回）
    )
    save_json(bundle)

    view.importSession(load_json())                 # 清空并按原 id 恢复（含外观选项）
    view.importSession(bundle, clear=False)         # 追加：id 重新分配

崩溃恢复（回合中途断电 / 进程被杀）::

    from pyqt6_ela_pro.chat import ElaChatTurnJournal

    journal = ElaChatTurnJournal(messageId=chat.beginAssistantMessage())
    journal.connectWorker(worker)          # 与 binder 并行，不改现有接线
    ...
    journal.end("done")
    fh.write(journal.dumpsNewLines())       # 追加写；崩了最多丢最后一行

    # 重启后：残行与未知事件自动跳过
    recovered = ElaChatTurnJournal.fromLines(read_lines())
    save_row(recovered.message().toDict())             # 补写成一条正常记录
    chat.chatView().addMessageFromDict(recovered.message().toDict())
"""

from ._json import backend as jsonBackend, dumps as jsonDumps, loads as jsonLoads
from .binder import ElaChatStreamBinder, ElaChatTurnSummary
from .blocks import (
    AttachmentStrip,
    ContextToolGroupCard,
    ElaChatAvatarSource,
    ErrorCard,
    MessageActions,
    MessageHeader,
    MessageMeta,
    ReasoningBlock,
    StatsBadge,
    ThinkingRow,
    ToolCallCard,
    ToolGroupPanel,
    toolDefaultOpen,
    toolDefaultOpenCoding,
)
from .bubble import DISCLAIMER_TEXT, ElaChatBubble
from .docks import ElaChatInputDock, ElaChatPermissionDock, ElaChatQueueDock
from .input import ElaChatInput
from .message import (
    SCHEMA_VERSION,
    ElaChatAttachment,
    ElaChatMessage,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatPermission,
    ElaChatOption,
    ElaChatPermissionStatusType,
    ElaChatQuestion,
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolCall,
    ElaChatToolStatusType,
)
from ._pricing import ModelPricing, cost_from_parts, formatCost, stats_cost
from .journal import JOURNAL_VERSION, ElaChatTurnJournal
from .mock import ElaChatMockBackend, ElaChatMockChunk, ElaChatMockUsage
from .renderers import (
    ToolRendererFactory,
    ToolRenderContext,
    ToolSubtitleFn,
    clearToolRenderers,
    registerToolRenderer,
    toolRenderer,
    toolRendererGroupable,
    toolRendererNames,
    unregisterToolRenderer,
)
from .session import SESSION_SCHEMA_VERSION, ElaChatSessionInfo, ElaChatSessionStats
from .status import ElaChatStatusBar
from .suggestions import ElaChatSuggestion, SuggestionPopup
from .toolbar import ElaChatToolBar, ElaChatToolButton
from .view import ElaChatView
from .widget import ElaChatWidget
from .worker import ElaChatAsyncWorker

__all__ = [
    "ElaChatWidget",
    "ElaChatView",
    "ElaChatInput",
    "ElaChatBubble",
    "ElaChatToolBar",
    "ElaChatToolButton",
    "ElaChatMessage",
    "ElaChatPart",
    "ElaChatPartKindType",
    "ElaChatPermission",
    "ElaChatPermissionStatusType",
    "ElaChatOption",
    "ElaChatQuestion",
    "ElaChatAttachment",
    "ElaChatToolCall",
    "ElaChatToolStatusType",
    "ElaChatStats",
    "SCHEMA_VERSION",
    "ElaChatTurnJournal",
    "JOURNAL_VERSION",
    "ElaChatSessionInfo",
    "ElaChatSessionStats",
    "SESSION_SCHEMA_VERSION",
    "ElaChatSuggestion",
    "SuggestionPopup",
    "ElaChatStreamBinder",
    "ElaChatTurnSummary",
    "ElaChatAsyncWorker",
    "ElaChatMockBackend",
    "ElaChatMockChunk",
    "ElaChatMockUsage",
    "ElaChatStatusBar",
    "ElaChatQueueDock",
    "ElaChatInputDock",
    "ElaChatPermissionDock",
    "ElaChatRoleType",
    "ElaChatStatusType",
    "ElaChatReasoningStyleType",
    "ElaChatAvatarSource",
    "MessageHeader",
    "MessageMeta",
    "ReasoningBlock",
    "ThinkingRow",
    "ToolCallCard",
    "ContextToolGroupCard",
    "ToolGroupPanel",
    "AttachmentStrip",
    "StatsBadge",
    "MessageActions",
    "ErrorCard",
    "toolDefaultOpen",
    "toolDefaultOpenCoding",
    "registerToolRenderer",
    "unregisterToolRenderer",
    "toolRenderer",
    "toolRendererNames",
    "toolRendererGroupable",
    "clearToolRenderers",
    "ToolRenderContext",
    "ToolRendererFactory",
    "ToolSubtitleFn",
    "ModelPricing",
    "stats_cost",
    "cost_from_parts",
    "formatCost",
    "DISCLAIMER_TEXT",
    "jsonDumps",
    "jsonLoads",
    "jsonBackend",
]
