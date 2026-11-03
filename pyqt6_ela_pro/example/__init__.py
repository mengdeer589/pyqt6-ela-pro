"""[pyqt6_ela_pro] 示例页面模块?"""

from .animation_icon_page import AnimationIconPage
from .app_shell_page import AppShellPage
from .base_page import ExamplePage
from .blueprint_page import BlueprintPage
from .buttons_menus_page import ButtonsMenusPage
from .chart_lib_page import ChartLibPage
from .charts_page import ChartsPage
from .chat_agent_page import ChatAgentPage
from .chat_files_page import ChatFilesPage
from .chat_guide_page import ChatGuidePage
from .chat_input_page import ChatInputPage
from .chat_overview_page import ChatOverviewPage
from .chat_persist_page import ChatPersistPage
from .chat_session_page import ChatSessionPage
from .chat_timeline_page import ChatTimelinePage
from .chat_workbench_page import ChatWorkbenchPage
from .combo_box_page import ComboBoxPage
from .container_layout_page import ContainerLayoutPage
from .data_table_page import DataTablePage
from .drawer_tooltip_page import DrawerTooltipPage
from .embed_page import EmbedPage
from .fluent_page import FluentPage
from .input_select_page import InputSelectPage
from .markdown_page import MarkdownPage
from .progress_feedback_page import ProgressFeedbackPage
from .selection_page import SelectionAssistantPage
from .terminal_page import TerminalPage
from .views_list_page import ViewsListPage
from .window_shell_page import WindowShellPage

__all__ = [
    "ExamplePage",
    # 基础组件
    "InputSelectPage",
    "ComboBoxPage",
    "ContainerLayoutPage",
    "ViewsListPage",
    "ButtonsMenusPage",
    "ProgressFeedbackPage",
    "FluentPage",
    # 数据与图表
    "DataTablePage",
    "ChartLibPage",
    "ChartsPage",
    # 内容渲染
    "MarkdownPage",
    # AI 对话（工作台；各工作区类单独导出，供测试与宿主复用）
    "ChatWorkbenchPage",
    "ChatOverviewPage",
    "ChatInputPage",
    "ChatAgentPage",
    "ChatFilesPage",
    "ChatTimelinePage",
    "ChatSessionPage",
    "ChatPersistPage",
    # 窗口与应用外壳
    "WindowShellPage",
    "DrawerTooltipPage",
    "AppShellPage",
    # 系统交互与嵌入
    "EmbedPage",
    "TerminalPage",
    "SelectionAssistantPage",
    # 动效与图形
    "AnimationIconPage",
    "BlueprintPage",
    # 参考文档
    "ChatGuidePage",
]
