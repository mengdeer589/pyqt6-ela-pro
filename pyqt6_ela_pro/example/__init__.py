"""[pyqt6_ela_pro] 示例页面模块

**侧边栏的两级结构**（见 ``__main__.py``）：一级是可折叠的 expander（按主题
分组），展开后是页面 / 分类。分组依据是「这组页面回答的是同一个问题」。

页面清单（``__all__`` 与侧边栏注册顺序一致）：

======================  ====================================================
一级分组                页面
======================  ====================================================
基础组件                输入与选择 / 下拉框组件 / 容器与布局 / 视图与列表 /
                        按钮与菜单 / 进度与反馈
数据与图表              表格 / 图表（第三方库）/ ElaChartWidget 图表工作台
内容渲染                Markdown 渲染 / Office 文档预览
AI 对话                  聊天组件总览 / 输入区能力 / Agent 能力 / 会话管理 /
                        持久化与性能
窗口与应用外壳          ElaWindow 应用外壳 / 弹窗与提示 / 启动与托盘
系统交互与嵌入          外部内容嵌入 / 终端输出 / 划词助手
动效与图形              动画与图标 / 节点图编辑器
参考文档                聊天组件 API 指南
======================  ====================================================

**AI 对话那五页是按能力域切的**，不是按使用场景：「长什么样」（总览，预填 +
可重播）/「怎么接」（输入区）/「agent 多了什么」/「多话题怎么管」/
「落库与大消息量」。聊天组件有些能力**只在流式过程中可见**（推理逐步浮现、
工具卡忙碌环、统计徽标落定），所以聊天示例页统一是「预填 + 可重播」，
共用零件见 ``chat_demo_kit.py``。
"""

from .animation_icon_page import AnimationIconPage
from .app_shell_page import AppShellPage
from .base_page import ExamplePage
from .blueprint_page import BlueprintPage
from .buttons_menus_page import ButtonsMenusPage
from .chart_lib_page import ChartLibPage
from .charts_page import ChartsPage
from .chat_agent_page import ChatAgentPage
from .chat_guide_page import ChatGuidePage
from .chat_input_page import ChatInputPage
from .chat_overview_page import ChatOverviewPage
from .chat_persist_page import ChatPersistPage
from .chat_session_page import ChatSessionPage
from .combo_box_page import ComboBoxPage
from .container_layout_page import ContainerLayoutPage
from .data_table_page import DataTablePage
from .drawer_tooltip_page import DrawerTooltipPage
from .embed_page import EmbedPage
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
    # 数据与图表
    "DataTablePage",
    "ChartLibPage",
    "ChartsPage",
    # 内容渲染
    "MarkdownPage",
    # AI 对话（按能力域切，不是按使用场景）
    "ChatOverviewPage",
    "ChatInputPage",
    "ChatAgentPage",
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
