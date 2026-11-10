"""
pyqt6_ela_pro - PyQt6 Extension Widgets Module

Extension components based on PyQt6ElaWidgetTools with custom styling.
"""

from importlib import import_module

from ._version import __version__

# ── Functions ────────────────────────────────────────────────────────────────

from .tooltips import (
    set_tooltip,
    remove_tooltip,
)

from .resize_reflow import setResizeReflowDeferred

from ._webengine import prepareWebEngine

from .animation import fade_in, fade_out, shake_window

from ._motion import (
    Duration,
    Easing,
    ElaMotionKindType,
    ElaMotionModeType,
    MotionPolicy,
    idle_loop_running,
    motion,
    start_idle_loop,
    start_transition,
    start_transition_timer,
)

from ._theme import (
    ElaSeverity,
    ElaStatusRoleType,
    accent,
    border,
    borderStrong,
    chartPalette,
    resetAccentColor,
    setAccentColor,
    severityColor,
    statusColor,
    surface,
    surfaceDialog,
    surfacePopup,
    surfaceRaised,
    text,
    textDisabled,
    textMuted,
    textOnAccent,
)

from ._ownership import ContentSlot, ElaWidgetOwnershipType

# ── Fluent 风格新增组件 ──
from .ela_shimmer import (
    ElaShimmer,
    ShimmerElement,
    ShimmerPalette,
    ElaShimmerShapeType,
    ElaShimmerTemplateType,
)
from .ela_field import ElaField, ElaFieldStatusType
from .ela_avatar import (
    ElaAvatarPresenceType,
    ElaAvatarShapeType,
    ElaAvatarSizeType,
    ElaAvatar,
)
from .ela_selector_bar import (
    ElaSelectorBar,
    SelectorBarItem,
    ElaSelectorBarOverflowType,
)

from .svg_icon import (
    svg_to_icon,
    svg_to_image,
    svg_to_pixmap,
    svg_icon_loader,
)

from .splitter import create_ela_splitter

from .notify_popup import show_notify

# ── Components ───────────────────────────────────────────────────────────────

from .widget_base import ElaThemeWidget

from .table_view import ElaDataTable

from .combo_box import (
    ElaSearchBox,
    ElaSearchMultiBox,
)

from .tooltips import (
    ElaToolTipPositionType,
    ElaToolTip,
    ElaStateToolTip,
)

from .tooltip_targets import (
    ACTION_TOOLTIP_PROPERTY,
    DOCUMENT_TOOLTIP_PROPERTY,
    ElaToolTipAdapter,
    action_tooltip_text,
    document_format_tooltip,
    install_document_tooltips,
    install_item_view_tooltips,
    install_menu_tooltips,
    set_action_tooltip,
)

from .dialog_base import ElaDialogBase

from .message_dialog import ElaMessageDialog

from .parquet_table import ElaParquetTable

from .splash_screen import ElaSplashScreen

from .terminal_view import (
    AnsiColor,
    AnsiParser,
    ElaTerminalView,
    TerminalLine,
    TerminalSpan,
    TerminalStyle,
    defaultTerminalTheme,
    registerTerminalTheme,
    setDefaultTerminalTheme,
    terminalThemes,
    unregisterTerminalTheme,
)

from .animation import ElaAnimatedMixin

from .taskbar_progress import ElaTaskbarProgress

from .ela_long_press_button import ElaLongPressButton


from .ela_tag_line_edit import ElaTagLineEdit

from .ela_confirm_dialog import ElaConfirmDialog

from .ela_dashboard_gauge import ElaDashboardGauge

from .ela_divider import ElaDivider

from .ela_drawer_area import ElaDrawerArea

from .ela_button import ElaButton

from .ela_chip import ElaChip

from .ela_dropdown_button import ElaDropDownButton

from .ela_figure_canvas import ElaFigureCanvas

from .ela_ghost_box import ElaGhostBox

from .ela_group_box import ElaGroupBox

from .ela_info_badge import ElaInfoBadge

from .ela_pagination import ElaPagination

from .ela_password_edit import ElaPasswordEdit

from .ela_pyqtgraph_canvas import ElaPlotWidget

from .ela_progress_button import ElaProgressButton

from .ela_rating_control import ElaRatingControl

from .ela_side_drawer import ElaDrawer, ElaDrawerPositionType

from .ela_split_button import ElaSplitButton

from .ela_spotlight import ElaSpotlight

from .ela_steps import ElaSteps

from .ela_timeline import ElaTimeline

from .ela_toast import ElaToast

from .ela_upload_area import ElaUploadArea


from .ela_diff_view import ElaDiffView


from .menu_item import ElaMenuItem

from .ela_tray_icon import ElaTrayIcon


from .ela_tag_box import ElaTagBox

from .ela_tag_multi_box import ElaTagMultiBox

from .ela_tag_search_box import ElaTagSearchBox

from .ela_tag_search_multi_box import ElaTagSearchMultiBox

from .notify_popup import ElaNotifyManager, ElaNotifyPopup

from .svg_icon import (
    ElaSvgIconLoader,
)

from .window_embedder import ElaWindowEmbedder


from .splitter import ElaSplitter


#: 重型子系统：首次访问属性时再导入，避免 ``import pyqt6_ela_pro`` 拉起全部 UI。
_LAZY_MODULES = {
    "ela_markdown_viewer": (
        "ElaMarkdownViewer",
        "defaultMarkdownBodyFontFamily",
        "defaultMarkdownTheme",
        "isFontFamilyAvailable",
        "markdownThemes",
        "registerMarkdownTheme",
        "setDefaultMarkdownBodyFontFamily",
        "setDefaultMarkdownTheme",
        "unregisterMarkdownTheme",
    ),
    "charts": (
        "ElaChartWidget",
        "chartThemeSpec",
        "chartThemes",
        "defaultChartTheme",
        "registerChartTheme",
        "setDefaultChartTheme",
        "unregisterChartTheme",
    ),
    "chat": (
        "AttachmentStrip",
        "ContextToolGroupCard",
        "DEFAULT_TIMELINE_DETAIL",
        "ElaChatAsyncWorker",
        "ElaChatAttachment",
        "ElaChatAvatarSource",
        "ElaChatBubble",
        "ElaChatDetailDepthType",
        "ElaChatDetailPlacementType",
        "ElaChatDetailSection",
        "ElaChatFileChange",
        "ElaChatFileChangeLine",
        "ElaChatFileChanges",
        "ElaChatInput",
        "ElaChatMention",
        "ElaChatNotice",
        "ElaChatNoticeType",
        "ElaChatPromptHistory",
        "ElaChatRetryCard",
        "ElaChatSelector",
        "ElaChatSelectorItem",
        "ElaChatSearchBar",
        "ElaChatSearchHit",
        "ElaChatTimelineDetail",
        "ElaChatWorkingRow",
        "ElaChatInputDock",
        "ElaChatMessage",
        "ElaChatMockBackend",
        "ElaChatMockChunk",
        "ElaChatMockUsage",
        "ElaChatPart",
        "ElaChatPartKindType",
        "ElaChatQueueDock",
        "ElaChatReasoningStyleType",
        "ElaChatRoleType",
        "ElaChatSessionInfo",
        "ElaChatSessionStats",
        "ElaChatStats",
        "ElaChatStatusType",
        "ElaChatStatusBar",
        "ElaChatStreamBinder",
        "ElaChatSuggestion",
        "ElaChatToolBar",
        "ElaChatToolButton",
        "ElaChatToolCall",
        "ElaChatToolStatusType",
        "ElaChatTurnSummary",
        "ElaChatView",
        "ElaChatWidget",
        "ErrorCard",
        "MessageActions",
        "MessageHeader",
        "MessageMeta",
        "ReasoningBlock",
        "StatsBadge",
        "SuggestionPopup",
        "ThinkingRow",
        "ToolCallCard",
        "ToolGroupPanel",
    ),
    "browser_embedder": ("ElaBrowserEmbedder",),
    "selection_assistant": (
        "ElaClipboardCapture",
        "ElaMouseMonitor",
        "ElaSelectionAssistant",
        "ElaSelectionPopup",
        "ElaSelectionResultDialog",
    ),
    "blueprint": (
        "ElaBlueprintCanvas",
        "ElaBlueprintGraph",
        "ElaBlueprintNode",
        "ElaEdge",
        "ElaEdgeContextMenu",
        "ElaExecutionController",
        "ElaNodeContextMenu",
        "ElaNodeCreationMenu",
        "ElaNodeRegistry",
        "ElaNodeSpec",
        "ElaPin",
        "ElaPinDirectionType",
        "PIN_COLORS",
        "gl_available",
        "pin",
        "pin_color",
        "register_node_type",
        "register_pin_type",
        "types_compatible",
    ),
}
_LAZY_ATTRS = {
    name: module for module, names in _LAZY_MODULES.items() for name in names
}


def __getattr__(name: str):
    if name in _LAZY_MODULES:
        value = import_module(f"{__name__}.{name}")
        globals()[name] = value
        return value
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY_ATTRS) | set(_LAZY_MODULES))


__all__ = [
    # ── 动效策略 ──
    "motion",
    "ElaMotionModeType",
    "ElaMotionKindType",
    "MotionPolicy",
    "Duration",
    "Easing",
    "start_transition",
    "start_transition_timer",
    "start_idle_loop",
    "idle_loop_running",
    # ── 语义令牌 ──
    "ElaSeverity",
    "ElaStatusRoleType",
    "surface",
    "surfaceRaised",
    "surfacePopup",
    "surfaceDialog",
    "border",
    "borderStrong",
    "text",
    "textMuted",
    "textDisabled",
    "textOnAccent",
    "accent",
    "severityColor",
    "statusColor",
    "chartPalette",
    "setAccentColor",
    "resetAccentColor",
    # ── 内容所有权 ──
    "ElaWidgetOwnershipType",
    "ContentSlot",
    # ── 骨架屏 ──
    "ElaShimmer",
    "ElaShimmerShapeType",
    "ElaShimmerTemplateType",
    "ShimmerElement",
    "ShimmerPalette",
    # ── 表单字段 ──
    "ElaField",
    "ElaFieldStatusType",
    # ── 头像 ──
    "ElaAvatar",
    "ElaAvatarSizeType",
    "ElaAvatarShapeType",
    "ElaAvatarPresenceType",
    # ── 分段控件 ──
    "ElaSelectorBar",
    "SelectorBarItem",
    "ElaSelectorBarOverflowType",
    # ── Functions ──
    "fade_in",
    "fade_out",
    "shake_window",
    "set_tooltip",
    "remove_tooltip",
    "setResizeReflowDeferred",
    "prepareWebEngine",
    "svg_to_icon",
    "svg_to_image",
    "svg_to_pixmap",
    "svg_icon_loader",
    "create_ela_splitter",
    "show_notify",
    # ── Components ──
    "ElaAnimatedMixin",
    "ElaBlueprintCanvas",
    "ElaBlueprintGraph",
    "ElaBlueprintNode",
    "ElaBrowserEmbedder",
    "DEFAULT_TIMELINE_DETAIL",
    "ElaButton",
    "ElaChartWidget",
    "ElaChatAsyncWorker",
    "ElaChatAttachment",
    "ElaChatBubble",
    "ElaChatDetailDepthType",
    "ElaChatDetailPlacementType",
    "ElaChatDetailSection",
    "ElaChatFileChange",
    "ElaChatFileChangeLine",
    "ElaChatFileChanges",
    "ElaChatInput",
    "ElaChatInputDock",
    "ElaChatMention",
    "ElaChatMessage",
    "ElaChatNoticeType",
    "ElaChatPromptHistory",
    "ElaChatSearchBar",
    "ElaChatSearchHit",
    "ElaChatSelector",
    "ElaChatSelectorItem",
    "ElaChatTimelineDetail",
    "ElaChatMockBackend",
    "ElaChatMockChunk",
    "ElaChatMockUsage",
    "ElaChatPart",
    "ElaChatPartKindType",
    "ElaChatQueueDock",
    "ElaChatReasoningStyleType",
    "ElaChatRoleType",
    "ElaChatSessionInfo",
    "ElaChatSessionStats",
    "ElaChatStats",
    "ElaChatStatusType",
    "ElaChatStatusBar",
    "ElaChatStreamBinder",
    "ElaChatSuggestion",
    "ElaChatToolBar",
    "ElaChatToolButton",
    "ElaChatToolCall",
    "ElaChatToolStatusType",
    "ElaChatTurnSummary",
    "ElaChatView",
    "ElaChatWidget",
    "ElaChip",
    "ElaClipboardCapture",
    "ElaConfirmDialog",
    "ElaDashboardGauge",
    "ElaDataTable",
    "ElaDialogBase",
    "ElaDiffView",
    "ElaDivider",
    "ElaDrawer",
    "ElaDrawerArea",
    "ElaDrawerPositionType",
    "ElaDropDownButton",
    "ElaEdge",
    "ElaEdgeContextMenu",
    "ElaExecutionController",
    "ElaFigureCanvas",
    "ElaGhostBox",
    "ElaGroupBox",
    "ElaInfoBadge",
    "ElaLongPressButton",
    "ElaMarkdownViewer",
    "ElaMenuItem",
    "defaultMarkdownBodyFontFamily",
    "isFontFamilyAvailable",
    "markdownThemes",
    "defaultMarkdownTheme",
    "setDefaultMarkdownBodyFontFamily",
    "setDefaultMarkdownTheme",
    "registerMarkdownTheme",
    "unregisterMarkdownTheme",
    "chartThemes",
    "defaultChartTheme",
    "setDefaultChartTheme",
    "registerChartTheme",
    "unregisterChartTheme",
    "chartThemeSpec",
    "ElaMessageDialog",
    "ElaMouseMonitor",
    "ElaNodeContextMenu",
    "ElaNodeCreationMenu",
    "ElaNodeRegistry",
    "ElaNodeSpec",
    "ElaNotifyManager",
    "ElaNotifyPopup",
    "ElaParquetTable",
    "ElaPasswordEdit",
    "ElaPin",
    "ElaPinDirectionType",
    "ElaPlotWidget",
    "ElaPagination",
    "ElaProgressButton",
    "ElaRatingControl",
    "ElaSearchBox",
    "ElaSearchMultiBox",
    "ElaSelectionAssistant",
    "ElaSelectionPopup",
    "ElaSelectionResultDialog",
    "ElaSplashScreen",
    "ElaSplitButton",
    "ElaSplitter",
    "ElaSpotlight",
    "ElaStateToolTip",
    "ElaSteps",
    "ElaSvgIconLoader",
    "ElaTagBox",
    "ElaTagLineEdit",
    "ElaTagMultiBox",
    "ElaTagSearchBox",
    "ElaTagSearchMultiBox",
    "ElaTaskbarProgress",
    "ElaTerminalView",
    "ElaThemeWidget",
    "ElaTrayIcon",
    "ElaTimeline",
    "ElaToast",
    "ElaToolTip",
    "ElaToolTipAdapter",
    "ElaToolTipPositionType",
    "ACTION_TOOLTIP_PROPERTY",
    "DOCUMENT_TOOLTIP_PROPERTY",
    "action_tooltip_text",
    "document_format_tooltip",
    "install_document_tooltips",
    "install_item_view_tooltips",
    "install_menu_tooltips",
    "set_action_tooltip",
    "ElaUploadArea",
    "ElaWindowEmbedder",
    "SuggestionPopup",
    "PIN_COLORS",
    "gl_available",
    "pin",
    "pin_color",
    "register_node_type",
    "register_pin_type",
    "types_compatible",
    # ── 终端组件 ──
    "AnsiColor",
    "AnsiParser",
    "TerminalLine",
    "TerminalSpan",
    "TerminalStyle",
    "defaultTerminalTheme",
    "registerTerminalTheme",
    "setDefaultTerminalTheme",
    "terminalThemes",
    "unregisterTerminalTheme",
    "__version__",
]
