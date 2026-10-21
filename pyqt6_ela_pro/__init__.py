"""
pyqt6_ela_pro - PyQt6 Extension Widgets Module

Extension components based on PyQt6ElaWidgetTools with custom styling.
"""

from ._version import __version__

# ── Functions ────────────────────────────────────────────────────────────────

from .tooltips import (
    set_tooltip,
    remove_tooltip,
)

from .resize_reflow import setResizeReflowDeferred

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
    ElaStatusRoleType,
    accent,
    border,
    borderStrong,
    chartPalette,
    resetAccentColor,
    setAccentColor,
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
from .ela_avatar import ElaAvatarPresenceType, ElaAvatarShapeType, ElaAvatarSizeType, ElaAvatar
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

from .ela_markdown_viewer import (
    ElaMarkdownViewer,
    defaultMarkdownTheme,
    markdownThemes,
    registerMarkdownTheme,
    setDefaultMarkdownTheme,
    unregisterMarkdownTheme,
)

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

from .charts import ElaChartWidget

from .chat import (
    AttachmentStrip,
    ContextToolGroupCard,
    ElaChatAsyncWorker,
    ElaChatAttachment,
    ElaChatAvatarSource,
    ElaChatBubble,
    ElaChatInput,
    ElaChatInputDock,
    ElaChatMessage,
    ElaChatMockBackend,
    ElaChatMockChunk,
    ElaChatMockUsage,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatQueueDock,
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatSessionInfo,
    ElaChatSessionStats,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatStatusBar,
    ElaChatStreamBinder,
    ElaChatSuggestion,
    ElaChatToolBar,
    ElaChatToolButton,
    ElaChatToolCall,
    ElaChatToolStatusType,
    ElaChatTurnSummary,
    ElaChatView,
    ElaChatWidget,
    ErrorCard,
    MessageActions,
    MessageHeader,
    MessageMeta,
    ReasoningBlock,
    StatsBadge,
    SuggestionPopup,
    ThinkingRow,
    ToolCallCard,
    ToolGroupPanel,
)

from .menu_item import ElaMenuItem

from .ela_tray_icon import ElaTrayIcon

from .selection_assistant import (
    ElaClipboardCapture,
    ElaMouseMonitor,
    ElaSelectionAssistant,
    ElaSelectionPopup,
    ElaSelectionResultDialog,
)

from .ela_tag_box import ElaTagBox

from .ela_tag_multi_box import ElaTagMultiBox

from .ela_tag_search_box import ElaTagSearchBox

from .ela_tag_search_multi_box import ElaTagSearchMultiBox

from .notify_popup import ElaNotifyPopup

from .svg_icon import (
    ElaSvgIconLoader,
)

from .window_embedder import ElaWindowEmbedder

from .browser_embedder import ElaBrowserEmbedder

from .splitter import ElaSplitter

from .blueprint import (
    ElaBlueprintCanvas,
    ElaBlueprintGraph,
    ElaBlueprintNode,
    ElaEdge,
    ElaEdgeWidget,
    ElaExecutionController,
    ElaNodeContextMenu,
    ElaNodeCreationMenu,
    ElaNodeRegistry,
    ElaNodeSpec,
    ElaNodeWidget,
    ElaPin,
    ElaPinDirectionType,
    ElaPinHandle,
    ElaTempWire,
    PIN_COLORS,
    bezier_path,
    format_elapsed,
    gl_available,
    pin_color,
    register_node_type,
    register_pin_type,
    types_compatible,
)


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
    "ElaButton",
    "ElaChartWidget",
    "ElaChatAsyncWorker",
    "ElaChatAttachment",
    "ElaChatAvatarSource",
    "ElaChatBubble",
    "ElaChatInput",
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
    "ElaChip",
    "ElaClipboardCapture",
    "ElaConfirmDialog",
    "ElaDashboardGauge",
    "ElaDataTable",
    "ElaDialogBase",
    "ElaDivider",
    "ElaDrawer",
    "ElaDrawerArea",
    "ElaDrawerPositionType",
    "ElaDropDownButton",
    "ElaEdge",
    "ElaEdgeWidget",
    "ElaExecutionController",
    "ElaFigureCanvas",
    "ElaGhostBox",
    "ElaGroupBox",
    "ElaInfoBadge",
    "ElaLongPressButton",
    "ElaMarkdownViewer",
    "ElaMenuItem",
    "markdownThemes",
    "defaultMarkdownTheme",
    "setDefaultMarkdownTheme",
    "registerMarkdownTheme",
    "unregisterMarkdownTheme",
    "ElaMessageDialog",
    "ElaMouseMonitor",
    "ElaNodeContextMenu",
    "ElaNodeCreationMenu",
    "ElaNodeRegistry",
    "ElaNodeSpec",
    "ElaNodeWidget",
    "ElaNotifyPopup",
    "ElaParquetTable",
    "ElaPasswordEdit",
    "ElaPin",
    "ElaPinDirectionType",
    "ElaPinHandle",
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
    "ElaTempWire",
    "ElaTerminalView",
    "ElaThemeWidget",
    "ElaTrayIcon",
    "ElaTimeline",
    "ElaToast",
    "ElaToolTip",
    "ElaToolTipPositionType",
    "ElaUploadArea",
    "ElaWindowEmbedder",
    "ContextToolGroupCard",
    "ToolGroupPanel",
    "ToolCallCard",
    "MessageHeader",
    "MessageActions",
    "MessageMeta",
    "ReasoningBlock",
    "ThinkingRow",
    "StatsBadge",
    "SuggestionPopup",
    "AttachmentStrip",
    "ErrorCard",
    "PIN_COLORS",
    "bezier_path",
    "format_elapsed",
    "gl_available",
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
