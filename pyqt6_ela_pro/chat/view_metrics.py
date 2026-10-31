"""聊天视图的布局 / 批量渲染 / 视口度量常量（view 与 virtualizer 共用）。"""

#: 消息间距（Editorial Agent 节奏：turn 之间更松弛）
_MESSAGE_SPACING = 20
#: 虚拟列表每帧最多物化的气泡数（单个约 7ms：建壳 + 查看器 + Markdown 渲染）
_VIRTUAL_MATERIALIZE_BUDGET = 4
#: 虚拟列表每帧物化时间预算（毫秒）；真实会话单条可能远超 7ms。
_VIRTUAL_MATERIALIZE_BUDGET_MS = 8.0
#: 虚拟列表的物化余量（视口高度的倍数，上下各留）
_VIRTUAL_WINDOW_MARGIN_RATIOS = 0.75
#: 懒加载触发距离（距顶部不足该倍数的视口高度时预渲染更早的消息）
_LAZY_TRIGGER_VIEWPORTS = 1.5
#: 懒加载一页渲染多少条更早的消息（逐条物化把单次成本拆开）
_LAZY_PAGE_SIZE = 1
#: 挂起判定的合并间隔（毫秒）
_SUSPEND_INTERVAL_MS = 100
#: 挂起判定余量（视口高度的倍数，上下各留）
_SUSPEND_MARGIN_VIEWPORTS = 2.0

#: 判定「贴底」的容差（像素，对齐 opencode 的 10px）
_BOTTOM_MARGIN = 10
#: 「回到底部」按钮显示阈值下限（离底距离，像素）
_JUMP_MIN_DISTANCE = 400
#: 展开 / 收起工具卡后暂停贴底跟随的时长（毫秒）
_FOLLOW_HOLD_MS = 250
#: 浮动按钮距右下角边距
_FLOAT_MARGIN = 16
