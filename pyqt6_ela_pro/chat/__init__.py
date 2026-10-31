"""``pyqt6_ela_pro.chat``：ChatGPT 风格聊天组件（自研）。

分层：``ElaChatWidget`` 只管输入区 + 回合编排；消息内容（正文 / 思考 / 工具 /
分段 / 用量 / 存储）只在 ``ElaChatView`` 上，经 ``chat.chatView()`` 调用，
``messageId`` 首位必填。助手正文复用 ``ElaMarkdownViewer`` 的嵌入模式。

持久化：``message.toDict()`` → ``jsonDumps`` 落库，``addMessageFromDict`` /
``restoreMessages`` 读回；整会话用 ``exportSession`` / ``importSession``。
后端接 ``ElaChatStreamBinder`` + ``ElaChatAsyncWorker``（或 ``ElaChatMockBackend``），
崩溃恢复用 ``ElaChatTurnJournal``。
"""

from ._json import backend as jsonBackend, dumps as jsonDumps, loads as jsonLoads
from .binder import ElaChatStreamBinder, ElaChatTurnSummary
from .._diff import ElaDiffFile as ElaChatFileChange
from .._diff import ElaDiffLine as ElaChatFileChangeLine
from .._diff import diffLines as diffChatLines
from .._diff import filesFromMetadata as chatFilesFromMetadata
from .._diff import parseUnifiedDiff as parseChatDiff
from .blocks import (
    AttachmentStrip,
    ContextToolGroupCard,
    ElaChatAvatarSource,
    ElaChatFileChanges,
    ElaChatNotice,
    ElaChatRetryCard,
    ElaChatWorkingRow,
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
    ElaChatMention,
    ElaChatNoticeType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolCall,
    ElaChatToolStatusType,
)
from .timeline_detail import (
    DEFAULT_TIMELINE_DETAIL,
    ElaChatDetailDepthType,
    ElaChatDetailPlacementType,
    ElaChatDetailSection,
    ElaChatTimelineDetail,
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
from .renderers_builtin import (
    cleanAnsi,
    installBuiltinToolRenderers,
    uninstallBuiltinToolRenderers,
)
from .prompt_history import ElaChatPromptHistory
from .search import ElaChatSearchBar, ElaChatSearchHit
from .selector import ElaChatSelector, ElaChatSelectorItem
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
    "ElaChatMention",
    "ElaChatNoticeType",
    "ElaChatNotice",
    "ElaChatRetryCard",
    "ElaChatWorkingRow",
    "ElaChatDetailDepthType",
    "ElaChatDetailPlacementType",
    "ElaChatDetailSection",
    "ElaChatTimelineDetail",
    "DEFAULT_TIMELINE_DETAIL",
    "ElaChatFileChange",
    "ElaChatFileChangeLine",
    "ElaChatFileChanges",
    "ElaChatPromptHistory",
    "ElaChatSearchBar",
    "ElaChatSearchHit",
    "ElaChatSelector",
    "ElaChatSelectorItem",
    "diffChatLines",
    "parseChatDiff",
    "chatFilesFromMetadata",
    "installBuiltinToolRenderers",
    "uninstallBuiltinToolRenderers",
    "cleanAnsi",
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
