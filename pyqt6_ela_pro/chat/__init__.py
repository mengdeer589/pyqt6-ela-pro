"""``pyqt6_ela_pro.chat``：ChatGPT 风格聊天组件。

分层、持久化与后端接入见 ``docs/chat.md``。
"""

from __future__ import annotations

from importlib import import_module

from .._diff import ElaDiffFile as ElaChatFileChange
from .._diff import ElaDiffLine as ElaChatFileChangeLine
from .._diff import diffLines as diffChatLines
from .._diff import filesFromMetadata as chatFilesFromMetadata
from .._diff import parseUnifiedDiff as parseChatDiff
from ._json import backend as jsonBackend, dumps as jsonDumps, loads as jsonLoads
from ._changes import ElaChatTurnChanges
from ._pricing import ModelPricing, cost_from_parts, formatCost, stats_cost
from ._trace import ElaChatTraceResult, ElaChatTraceRow, buildTraceRows
from .binder import ElaChatStreamBinder, ElaChatTurnSummary
from .journal import JOURNAL_VERSION, ElaChatTurnJournal
from .message import (
    SCHEMA_VERSION,
    ElaChatAttachment,
    ElaChatMessage,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatPermission,
    ElaChatOption,
    ElaChatPermissionStatusType,
    ElaChatPlan,
    ElaChatPlanItem,
    ElaChatPlanItemStatusType,
    ElaChatQuestion,
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatMention,
    ElaChatNoticeType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolCall,
    ElaChatToolKindType,
    ElaChatToolLocation,
    ElaChatToolStatusType,
)
from .mock import ElaChatMockBackend, ElaChatMockChunk, ElaChatMockUsage
from .prompt_history import ElaChatPromptHistory
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
from .timeline_detail import (
    DEFAULT_TIMELINE_DETAIL,
    ElaChatDetailDepthType,
    ElaChatDetailPlacementType,
    ElaChatDetailSection,
    ElaChatTimelineDetail,
)
from .worker import ElaChatAsyncWorker

#: 纯 UI / 内部块：首次访问属性时再导入，数据模型与后端保持轻量。
_LAZY_MODULES = {
    "widget": ("ElaChatWidget",),
    "view": ("ElaChatView",),
    "input": ("ElaChatInput",),
    "bubble": ("ElaChatBubble", "DISCLAIMER_TEXT"),
    "blocks": (
        "AttachmentStrip",
        "ContextToolGroupCard",
        "ElaChatAvatarSource",
        "ElaChatFileChanges",
        "ElaChatNotice",
        "ElaChatRetryCard",
        "ElaChatWorkingRow",
        "ErrorCard",
        "MessageActions",
        "MessageHeader",
        "MessageMeta",
        "PlanListView",
        "PlanPanel",
        "ReasoningBlock",
        "StatsBadge",
        "SubagentCard",
        "ThinkingRow",
        "TurnChangesRow",
        "ToolCallCard",
        "ToolGroupPanel",
        "toolDefaultOpen",
        "toolDefaultOpenCoding",
    ),
    "docks": ("ElaChatInputDock", "ElaChatPermissionDock", "ElaChatQueueDock"),
    "search": ("ElaChatSearchBar", "ElaChatSearchHit"),
    "selector": ("ElaChatSelector", "ElaChatSelectorItem"),
    "suggestions": ("ElaChatSuggestion", "SuggestionPopup"),
    "status": ("ElaChatStatusBar",),
    "trace": ("ElaChatTracePanel",),
    "toolbar": ("ElaChatToolBar", "ElaChatToolButton"),
    "renderers_builtin": (
        "cleanAnsi",
        "installBuiltinToolRenderers",
        "uninstallBuiltinToolRenderers",
    ),
}
_LAZY_ATTRS = {
    name: module for module, names in _LAZY_MODULES.items() for name in names
}

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
    "ElaChatPlan",
    "ElaChatPlanItem",
    "ElaChatPlanItemStatusType",
    "ElaChatMention",
    "ElaChatNoticeType",
    "ElaChatDetailDepthType",
    "ElaChatDetailPlacementType",
    "ElaChatDetailSection",
    "ElaChatTimelineDetail",
    "DEFAULT_TIMELINE_DETAIL",
    "ElaChatFileChange",
    "ElaChatFileChangeLine",
    "ElaChatFileChanges",
    "PlanListView",
    "PlanPanel",
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
    "ElaChatToolKindType",
    "ElaChatToolLocation",
    "ElaChatToolStatusType",
    "ElaChatStats",
    "ElaChatTurnChanges",
    "ElaChatTracePanel",
    "ElaChatTraceResult",
    "ElaChatTraceRow",
    "buildTraceRows",
    "SCHEMA_VERSION",
    "ElaChatTurnJournal",
    "JOURNAL_VERSION",
    "ElaChatSessionInfo",
    "ElaChatSessionStats",
    "SESSION_SCHEMA_VERSION",
    "ElaChatSuggestion",
    "SuggestionPopup",
    "SubagentCard",
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


def __getattr__(name: str):
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY_ATTRS))
