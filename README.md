# pyqt6-ela-pro

> 基于 [PyQt6-ElaWidgetTools](https://github.com/HIllya51/PyElaWidgetTools) 的 PyQt6 扩展组件库：
> Ela 风格控件全家桶，外加 **AI 对话栈**、**类 ECharts 图表引擎**、Markdown 渲染与 Windows 桌面集成能力。

![Platform](https://img.shields.io/badge/Platform-Windows%20AMD64-0078D4.svg)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Status](https://img.shields.io/badge/Status-Beta-orange.svg)

## 目录

- [这是什么](#这是什么)
- [核心能力](#核心能力)
- [安装](#安装)
- [快速开始](#快速开始)
- [组件一览](#组件一览)
- [示例](#示例)
- [文档](#文档)
- [可选依赖](#可选依赖)
- [设计原则](#设计原则)
- [平台](#平台)
- [组件来源与致谢](#组件来源与致谢)
- [许可证](#许可证)

## 这是什么

`pyqt6-ela-pro` 在 [ElaWidgetTools](https://github.com/Liniyous/ElaWidgetTools) C++ 组件库
与其 Python 绑定 [PyQt6-ElaWidgetTools](https://github.com/HIllya51/PyElaWidgetTools) 之上做了一层
**PyQt6 扩展**：沿用上游 Ela 外观，补齐上游没有的控件（按钮 / 标签纸片 / 抽屉 / 分页 /
时间线 / 分段控件 / 骨架屏 …）、一套可全局切换的**主题令牌与动效策略**，以及三个较大的子系统 ——
**AI 对话栈（`chat/`）**、**类 ECharts 图表引擎（`charts/`）**、**蓝图节点图编辑器（`blueprint/`）**；
另有 Markdown 渲染增强（公式 / Mermaid / 流式）、终端输出视图、划词助手与窗口 / 浏览器嵌入等桌面能力。

组件出处（上游移植 / 第三方参考 / 自研）见文末[组件来源与致谢](#组件来源与致谢)。

仓库顶层结构：

```text
pyqt6_ela_pro/             组件库源码（chat/ charts/ blueprint/ selection_assistant/ 为子系统）
pyqt6_ela_pro/example/     两级侧边栏示例应用（python -m pyqt6_ela_pro.example）
docs/                      README 的深入文档（chat / charts / markdown / 划词助手）
tests/                     回归测试（按组件目录组织）
```

## 核心能力

- **控件全家桶**：输入、按钮、弹窗与提示、导航与布局、数据展示共 100+ 组件；
  所有下拉框支持拼音搜索（`bj` → 北京）。
- **主题与外观**：浅 / 深主题自适应、语义色令牌、全局强调色换肤
  （`setAccentColor` 一并对 hover / press 等派生槽位写入）；**全库零 QSS**，控件全部 `QPainter` 自绘。
- **动效策略**：`motion` 全局三档（`Full` / `Reduced` / `Disabled`），默认跟随系统
  「关闭动画」设置 —— `Reduced` 把状态过渡压到 ≤50ms 并停掉持续动效。
- **AI 对话栈**：命令式回合 API + `ElaChatStreamBinder` 一键接线、分段时间线
  （思考 / 正文 / 工具 / 步骤用量）、工具结果富渲染注册表、审批（批准型 + 问答型逐题向导）、
  排队 / 撤回 / 重新生成 / steer 插话、多话题与崩溃恢复日志、会话导出导入。
  性能基线可复跑：`tools/perf/bench_chat.py`（构造 / 流式 / 历史 / 滚动 / 主题）与
  `tools/perf/bench_markdown_paint.py`（原生浏览器 vs 查看器的滚动绘制分项，Win7 排查字体慢路径）。
  详见 [docs/chat.md](docs/chat.md) 与 [docs/performance.md](docs/performance.md)。
- **图表引擎**：`ElaChartWidget` 对齐 ECharts 的 `setOption`（21 种系列、tooltip / dataZoom /
  日历热力 / 下钻），百万点级数据有系列层位图缓存与降采样 —— 折线 / 散点 100 万点稳态帧
  ~9ms、悬停 <1ms、进入新窗口 ~12ms；显式时间戳数据的**记录中断自动断开**（`addGaps`，
  `connectNulls` 可关）；`tools/perf/bench_charts.py`（含 `zoom新窗口` / `缩回全景` 两列）
  可复跑；**直角坐标图默认
  滚轮缩放**；交互对齐 Plotly：双击复位、`setDragMode`（平移 / 框选缩放 / 框选 / **套索**）、
  可配命中半径、空区坐标事件、图例悬停高亮、联合提示排序、`connectNulls`、**SVG 导出**；
  工具条是真实 `ElaIconButton`。详见 [docs/charts.md](docs/charts.md)。
- **内容渲染**：`ElaMarkdownViewer`（Typora 结构排版、4 套配色主题、GFM / Alert / 脚注 /
  公式 / Mermaid / 流式追加）与 `ElaTerminalView`（ANSI 颜色、跨分片转义、只读）。
  详见 [docs/markdown.md](docs/markdown.md)。
- **桌面集成**：全局划词助手（**默认带取词安全闸门**，避免向终端注入 Ctrl+C）、
  划词结果对话框、Windows 托盘、窗口 / Chromium 嵌入（CDP）、Office 预览、任务栏进度。
- **示例应用**：两级侧边栏，每个组件旁有 `</> 代码` 按钮直接看实现源码；
  聊天五页为「预填 + 可重播」，只在流式中可见的过程可以直接重看。

## 安装

当前仅支持**本地安装**（尚未发布到 PyPI）：

```bash
# 使用 uv（推荐）
uv pip install -e .

# 或 pip
pip install -e .

# 全部可选能力（pywin32 / comtypes / pygments / tsdownsample / mermaidx / orjson / polars）
uv pip install -e ".[all]"

# 按需安装
uv pip install -e ".[parquet]"   # ElaParquetTable（polars）
uv pip install -e ".[dev]"       # 开发依赖（pytest 等）
```

发布到 PyPI 之后应可用 `pip install pyqt6-ela-pro[all]`。

## 快速开始

```python
import sys
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import eApp, ElaWindow

from pyqt6_ela_pro import ElaButton, show_notify

app = QApplication(sys.argv)
eApp.init()          # 必须在创建任何 ElaWindow 之前调用

class MainWindow(ElaWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pyqt6-ela-pro")
        self.resize(1000, 700)

        page = QWidget(self)
        layout = QVBoxLayout(page)
        btn = ElaButton("Hello, pyqt6-ela-pro", variant="solid", color="primary")
        btn.clicked.connect(lambda: show_notify("提示", "按钮被点击了！"))
        layout.addWidget(btn)

        self.addPageNode("首页", page)

window = MainWindow()
window.show()
sys.exit(app.exec())
```

## 组件一览

### 工具函数

| 函数 | 说明 |
|---|---|
| `fade_in(widget, duration)` | 淡入动画 |
| `fade_out(widget, duration)` | 淡出动画 |
| `shake_window(widget)` | 窗口抖动效果 |
| `start_transition(anim, full_ms, ...)` | 按全局动效策略启动一次过渡，返回是否真的播放 |
| `start_transition_timer(timer)` | 同上，给 `QTimer` 手搓插值的过渡；返回 `False` 时调用方要自己落终值 |
| `start_idle_loop(timer, ms, on_stop=)` | 启动持续动效循环；`Reduced` 下停掉，`on_stop` 落到静态基态 |
| `surface(mode)` / `text(mode)` / `accent(mode)` | 语义令牌（`surface`/`surfaceRaised`/`surfacePopup`/`surfaceDialog`/`border`/`text`/`textMuted`/`accent`…） |
| `statusColor(mode, ElaStatusRoleType.X)` | 校验/提示状态色（`Neutral`/`Error`/`Warning`/`Success`） |
| `setAccentColor(color)` | 换强调色，**并一并派生写入 hover/press/开关圆点**（换色后需自行触发重绘） |
| `motion.setMode(ElaMotionModeType.Reduced)` | 全局动效：状态过渡压到 ≤50ms、持续动效停止 |
| `set_tooltip(widget, text, position, theme)` | 设置自定义工具提示 |
| `remove_tooltip(widget)` | 移除自定义工具提示 |
| `setResizeReflowDeferred(widget, on, delayMs)` | 连续 resize（侧栏动画 / 拖窗）期间钉住页面、停手后统一重排（实测单帧 8.6ms → 0.0ms） |
| `svg_to_icon(svg_data, size, color)` | SVG **字符串**转 QIcon（首参是 SVG 源码，不是文件路径）；`color` 替换图里的 `<<<COLOR_CODE>>>` 占位符 |
| `svg_to_pixmap(svg_data, size, color)` | 同上转 QPixmap（每次返回新对象） |
| `svg_to_image(svg_data, size, color)` | 同上转 QImage（值类型，**可跨线程用** —— 前两个的最后一步要 GUI 线程） |
| `svg_icon_loader()` | SVG 图标加载器单例句柄（无参；**不再自动加载任何图标包**，宿主自己 `loadFromFile` / `loadFromPackage`） |
| `btn.setSvgIcon(source, iconSize)` | 给 `ElaButton` 设**第三方 SVG** 图标。`source` 含 `<svg` 走源码、否则走图标名；返回 `False` 表示图标名查不到（已 warn，只画文字）。与 `setElaIcon` 互斥 |
| `btn.clearSvgIcon()` | 清掉 SVG 图标 |
| `loader.setPackageDirectory(path)` | 指定 `loadFromPackage` 找图标包的目录（**默认指向库内置目录，那里现在什么都没有**，宿主应设成自己的资源目录） |
| `create_ela_splitter(widgets, orientation, ...)` | 创建主题感知分割器 |
| `show_notify(title, content, timeout)` | 弹出通知 |

### 组件类

#### 主题 / 动效 / 基础

| 组件 | 说明 |
|---|---|
| **ElaThemeWidget** | 主题感知基础控件 |
| **ElaAnimatedMixin** | 注入 `fade_in()` / `fade_out()` 方法的混入类 |
| **MotionPolicy**（`motion`） | 全局动效策略单例，默认跟随系统 `SPI_GETCLIENTAREAANIMATION` |
| **ElaStatusRoleType**（`statusColor`） | 校验/提示语义状态色（`Neutral`/`Error`/`Warning`/`Success`） |
| **ElaMotionModeType / ElaMotionKindType** | 动效策略三档（`Full`/`Reduced`/`Disabled`）与动效种类（`Transition`/`Continuous`） |
| **ElaWidgetOwnershipType** | 内容所有权三态：`Borrowed`（默认，无父交还）/ `Reparented`（放回原 parent）/ `Owned`（容器 deleteLater） |
| **ContentSlot** | 「宿主持有一个外来内容控件」的记账：挂载 / 换策略 / `takeWidget()`（无父返回、永不删）/ `releaseWidget()`（按策略处置）+ 外部销毁自愈 |

#### 输入

| 组件 | 说明 |
|---|---|
| **ElaSearchBox** | 可搜索单选下拉框 |
| **ElaSearchMultiBox** | 可搜索多选下拉框 |
| **ElaTagBox** | Tag 样式单选下拉框 |
| **ElaTagMultiBox** | Tag 样式多选下拉框 |
| **ElaTagSearchBox** | Tag + 搜索 单选下拉框 |
| **ElaTagSearchMultiBox** | Tag + 搜索 多选下拉框 |
| **ElaTagLineEdit** | Tag 风格输入框（带「上置标题」；构造参数为 `(parent, title="")`） |
| **ElaPasswordEdit** | 密码输入框（可见切换，继承 ElaLineEdit） |
| **ElaRatingControl** | 星级评分（支持半星，可悬停预览） |
| **ElaUploadArea** | 文件上传区域（拖拽+点击，后缀/大小/数量校验） |
| **ElaSearchProxyModel** | 搜索框的过滤代理模型（中文原文 / 全拼 / 首字母匹配，由 `ElaSearchBox` 系列内部使用） |
| **ElaField** | 表单字段外壳：标题 + 必填 `*` + 编辑器槽（走 `ElaWidgetOwnershipType` 三态）+ 辅助文字 + 三态校验行（Error / Warning / Success） |
| **ElaFieldStatusType** | 校验状态：`None_` / `Error` / `Warning` / `Success` |
| **ElaSelectorBar** | 分段控件：三关键帧「压扁-移动-绽开」的动画指示器、溢出时两端箭头滚动或「更多」按钮、键盘可达、RTL 全量镜像 |
| **SelectorBarItem / ElaSelectorBarOverflowType / ElaHitType** | 一个分段的模型 / 溢出交互方式 / 命中区域（内部） |
| **ElaGhostBox** | 幽灵下拉框（透明无边框触发器 / 分组标题行 / 弹层底部固定按钮区；继承搜索与拼音过滤，`setSearchVisible(False)` 可关搜索） |

> 所有下拉框组件都提供 `items` 属性获取选项列表。

#### 按钮

| 组件 | 说明 |
|---|---|
| **ElaButton** | 统一按钮（6 变体 × 16 色，Ant Design 风格；focus ring / loading） |
| **ElaDropDownButton** | 下拉按钮（点击弹出 ElaMenu） |
| **ElaSplitButton** | 拆分按钮（主操作 + 下拉菜单） |
| **ElaLongPressButton** | 长按触发按钮 |
| **ElaProgressButton** | 含进度指示的按钮 |

#### 弹窗与提示

| 组件 | 说明 |
|---|---|
| **ElaMessageDialog** | 消息确认对话框 |
| **ElaConfirmDialog** | 全 QPainter 自绘确认对话框 |
| **ElaDialogBase** | 可定制按钮的对话框基类 |
| **ElaToast** | 通知提示（成功/信息/警告/错误，淡入淡出自动关闭；等级枚举 `ElaToastType`） |
| **ElaNotifyPopup** | 弹出通知控件 |
| **ElaNotifyManager** | 通知队列管理（排队 / 去重 / 逐条弹出；`show_notify()` 是它的自由函数入口） |
| **ElaToolTip** | 自定义工具提示 |
| **ElaStateToolTip** | 状态提示控件 |
| **ElaToolTipPositionType** | 提示位置枚举 |

#### 导航与布局

| 组件 | 说明 |
|---|---|
| **ElaDrawer** | 四方向侧边抽屉 |
| **ElaDrawerPositionType** | 抽屉方向枚举 |
| **ElaSteps** | 步骤条（多步引导，前进/后退；水平/垂直） |
| **ElaPagination** | 分页（页码按钮、省略号、跳转输入框） |
| **ElaSpotlight** | 引导遮罩（单目标/多步骤，淡入淡出） |
| **ElaDivider** | 分割线（水平/垂直/文字/虚线） |
| **ElaSplitter** | 主题感知分割器（定制 Handle，悬停变色） |
| **ElaSplitterHandle** | 分割器手柄（由 `ElaSplitter` 内部创建，宿主一般不直接用） |
| **ElaDrawerPanel / ElaDrawerDim** | 侧边抽屉面板 / 遮罩（内容槽走 `ElaWidgetOwnershipType` 三态） |
| **ElaGroupBox** | 分组框（圆角边框、居中标题、可放置子控件） |

#### 数据与内容展示

| 组件 | 说明 |
|---|---|
| **ElaMermaidRenderer** | Mermaid 渲染器（可选依赖 `mermaidx`，缺浏览器；供 `ElaMarkdownViewer` 调用，也可单独用） |
| **ElaShimmer** | 骨架屏 / 微光加载占位：4 种内置排版模板 + 手工元素、静态绘制入口（可铺在 delegate / 表格单元格里）、相位可手动驱动 |
| **ElaShimmerShapeType / ElaShimmerTemplateType / ShimmerElement / ShimmerPalette** | 骨架的元素形状（矩形 / 圆角矩形 / 圆 / 药丸）、内置模板（文本块 / 头像行 / 图片卡 / 自定义）、单块元素、绘制配色 |
| **ElaAvatar** | 头像：4 档尺寸 × 圆形/圆角方，图片（cover 裁剪）/ 首字母（字素簇感知）/ 人形字形三级回退，5 档在线状态圆点（环画成**周围表面色**） |
| **ElaAvatarSizeType / ElaAvatarShapeType / ElaAvatarPresenceType** | 尺寸档位（24/32/40/56，控件被硬锁）/ 形状 / 在线状态（可用 / 离开 / 忙碌 / 免打扰 / 离线） |
| **ElaDataTable** | 数据表格控件 |
| **ElaRowColorDelegate** | 表格行底色 delegate（跨行分组着色用） |
| **ElaParquetTable** | Parquet 文件分页查看 |
| **ElaInfoBarWidget** | Parquet 查看器的错误 / 统计信息条 |
| **ElaChartWidget** | 类 ECharts 引擎：21 系列 + 交互组件（含日历热力） |
| **ElaNumericBuffer** | charts 的大数组**按引用**包装（百万点不深拷贝）；**传入后不得原地修改** |
| **ElaDashboardGauge** | 仪表盘（全自绘，指针动画，颜色分段） |
| **ElaPlotWidget** | pyqtgraph 绘图控件（主题自适应，可选依赖） |
| **ElaFigureCanvas** | Matplotlib 画布（主题感知，可选依赖） |
| **ElaTimeline** | 时间线（时间戳/标题/内容/图标；垂直/水平） |
| **ElaMarkdownViewer** | Markdown 查看器（主题自适应；主字体缺字形时单族符号字体兜底，不改文本） |
| **ElaChip** | 标签纸片（16 色，可关闭/可选择/胶囊/前置图标） |
| **ElaInfoBadge** | 角标（Dot/Value/Icon 模式，5 种级别） |
| **ElaTerminalView** | 终端输出（ANSI 色彩 / 行号 / 自动滚动 / 搜索过滤 / 选区复制 / 导出；`append` 吃 str 与 bytes；缺字形单族符号字体兜底） |

#### AI 对话

| 组件 | 说明 |
|---|---|
| **ElaChatWidget** | ChatGPT 风格聊天组件（步骤化消息 + 分层输入区 + 流式 / 停止） |
| **ElaChatView** | 聊天消息列表（分段时间线 / 贴底跟随 / 空态建议 / 回到底部） |
| **ElaChatInput** | 分层输入区（补全 / 附件 / 拖放粘贴 / 发送↔停止 / 新建话题与清空上下文） |
| **ElaChatToolBar** | 可复用聊天工具栏（自定义按钮 / 控件 / 分隔线，两段布局） |
| **ElaChatBubble** | 步骤化消息气泡（分段：思考 / 正文 / 每步工具面板 / 步骤统计 / 底部操作） |
| **ElaChatQueueDock** | 排队消息 dock（立即发送 / 编辑 / 移除，宿主驱动发送时机） |
| **ElaChatInputDock** | 通用输入区替换 dock（宿主自定义卡片；审批走 `ElaChatPermissionDock`） |
| **ElaChatStreamBinder** | 流式事件 → 组件映射器（步骤 / 思考 / 工具 / 统计 / 耗时 / 摘要） |
| **ElaChatAsyncWorker** | 异步后端 worker 基类（QThread + asyncio + 命令队列 + 取消收尾） |
| **ElaChatMockBackend** | 模拟后端（QTimer，无模型服务跑通全链路，信号与真实 worker 同构） |
| **ElaChatStatusBar** | 宿主状态栏（信息 + 四档语义状态 + busy 指示） |
| **ElaChatRoleType / ElaChatStatusType / ElaChatPartKindType / ElaChatToolStatusType / ElaChatReasoningStyleType / ElaChatPermissionStatusType** | 消息角色 / 消息状态（`Queued` 只是头部展示态，不进 `_status`）/ 时间线分段种类 / 工具调用状态 / 思考展示形态 / 审批状态；均为 `StrEnum`（与字符串、JSON 兼容） |
| **ElaChatAttachment / ElaChatToolCall** | 附件（路径 / 图片 / 名称）与工具调用记录，成对 `toDict` / `fromDict` |
| **ElaChatPermission / ElaChatQuestion / ElaChatOption** | 审批请求；**`questions` 非空 = 问答型逐题向导**，为空 = 批准型三键。候选项**必须带 description**，自定义答案与候选项互斥 |
| **ElaChatSuggestion** | 空态建议项 |
| **ElaChatAvatarSource** | 头像来源（会话里持久化的是它，不是图片路径） |
| **ElaChatMockChunk / ElaChatMockUsage** | 假后端 `ElaChatMockBackend` 的分片 / 用量构造参数 |
| **ElaChatMessage** | 一条消息的快照（角色 / 分段时间线 / 派生字段；`message.text` 在流式**结束前**为空是设计，用 `bubble(id).text()` 实时读） |
| **ElaChatStats** | 单步或整轮用量 / 耗时（`cost_usd` 由宿主算好填入，或用 `stats_cost()`） |
| **ElaChatTurnSummary** | 一轮回合的收尾摘要（`binder.finish(turn)` 的返回值） |
| **ElaChatSessionInfo** | 会话元信息（多话题由宿主管理，一话题一 widget） |
| **ElaChatToolButton** | 工具栏图标按钮（`ElaIconButton` 子类，可选选中态；带文字的是 `ElaButton`） |
| **ElaChatPermissionDock** | 输入区**上方**的审批 dock（等待回复时的交互卡；时间线上留的是折叠的记录卡，两者不是同一个 widget） |
| **ElaChatTurnJournal** | 回合崩溃恢复日志（追加写事件流：`dumpsNewLines` 落盘、`fromLines` 重放并结算残留） |
| **ElaChatSessionStats** | 会话级用量汇总（`view.sessionStats(limit)`：计数 / 上下文四路词元 / 使用率 / 累计成本 / 工具调用统计（次数 / 轮数 / 按名计数 / 失败与在途）/ 思考耗时合计） |

#### 划词助手

| 组件 | 说明 |
|---|---|
| **ElaSelectionAssistant** | 全局划词监听 + 取词（模拟 Ctrl+C，**带注入闸门：未设过滤器时拖选默认不取词**）+ 动作条，纯信号宿主实现行为 |
| **ElaSelectionPopup** | 动作条浮窗（置顶 / 不抢焦点 / 越界收敛，可独立复用） |
| **ElaSelectionResultDialog** | 结果对话框（上游 ElaWidget 窗口；流式 Markdown / 停止 / 复制（Ctrl+C 默认纯文本；Markdown 源走 Ctrl+Shift+C）/ 重新生成，**只发信号不碰网络**） |
| **ElaMouseMonitor** | 轮询式全局鼠标监视（主线程 QTimer，信号坐标物理像素） |
| **ElaClipboardCapture** | 模拟 Ctrl+C 异步取词（不预先改动剪贴板；恢复有三道校验，含剪贴板序列号与非文本保护） |

#### 系统 / 窗口 / 嵌入

| 组件 | 说明 |
|---|---|
| **ElaTrayIcon** | Windows 托盘图标（三态图标 / 气泡通知 / ElaMenu 右键菜单） |
| **ElaWindowEmbedder** | 嵌入外部应用窗口 |
| **ElaBrowserEmbedder** | 嵌入 Chromium 浏览器，支持 CDP；多实例共享一个浏览器进程（`debug_port` / `browser_args` 以首个实例为准） |
| **ElaSplashScreen** | 应用启动屏（全 QPainter 自绘，淡入淡出） |
| **ElaTaskbarProgress** | Windows 任务栏进度 |
| **ElaSvgIconLoader** | SVG 图标包加载器（`.icons`；宿主自带） |

#### 蓝图节点编辑器

| 组件 | 说明 |
|---|---|
| **ElaBlueprintCanvas** | 蓝图节点图编辑器画布（节点 / 连线 / 框选 / 平移缩放 / 执行高亮；节点体控件可交互、拖动走标题栏与体空白处；重命名 / 属性经 `node_rename_requested` / `node_properties_requested` 信号交给宿主；`from_dict` 整体容错） |
| **ElaNodeRegistry / ElaNodeSpec / ElaPin / ElaPinDirectionType** | 蓝图节点类型注册表与其描述数据（引脚字典、强调色令牌键、自定义节点体构建器）；`register_node_type(...)` 是便捷入口 |

## 示例

```bash
python -m pyqt6_ela_pro.example
```

启动一个 ElaWindow 应用：侧边栏是**两级**结构（可折叠分组 → 页面），
每个组件标题旁有 `</> 代码` 按钮，弹出该演示方法自身的源码 ——
语法高亮**按当前主题取亮 / 暗两套调色板**（均按 WCAG 4.5:1 校验）。

主窗口同时演示 ElaWindow 的**应用外壳**：右侧停靠区（页面导航 / 运行日志 /
说明，可拖拽、可合页）、工具栏、状态栏、AppBar 右键菜单、内容区顶栏的页面
搜索、页脚节点（关于 / 设置）与关闭二次确认 —— 每一处都只是对 `ElaWindow`
公开 API 的调用，可整段照抄。

| 分组 | 页面 |
|---|---|
| 基础组件 | 输入与选择 / 下拉框全变体 / 容器与布局 / 视图与列表 / 按钮与菜单 / 进度与反馈 |
| 数据与图表 | 表格（ElaDataTable / ElaParquetTable）/ 图表（ElaChartWidget / pyqtgraph / matplotlib / 仪表盘） |
| 内容渲染 | Markdown（文本 / 代码 / 公式 / Mermaid / 流式）/ Office 文档预览 |
| AI 对话 | 总览 / 输入区能力 / Agent 能力 / 会话管理 / 持久化与性能（预填 + 可重播） |
| 窗口与应用外壳 | ElaWindow 应用外壳（本页操作主窗口：导航栏模式、窗口按钮、背景绘制、内容堆栈、dock、新窗口打开、关闭链路）/ 弹窗与提示 / 启动与托盘 |
| 系统交互与嵌入 | 窗口嵌入 / 浏览器嵌入 / 终端输出 / 划词助手 |
| 动效与图形 | 动画与图标 / 蓝图节点编辑器 |
| 参考文档 | 聊天组件 API 指南（用 `ElaMarkdownViewer` 渲染 `llm_test` 源码快照） |

> 窗口 / 浏览器嵌入、Office 预览等页面依赖可选依赖（`pywin32` / `comtypes`）；
> 缺失时对应页面会降级为说明文字，不影响其它页面。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/chat.md](docs/chat.md) | AI 对话栈：组件分工、回合 API、流式 / 工具 / 审批 / 压缩、持久化与多话题 |
| [docs/charts.md](docs/charts.md) | `ElaChartWidget`：`setOption` / 控制 / 事件 / 自定义系列扩展 |
| [docs/markdown.md](docs/markdown.md) | `ElaMarkdownViewer` 渲染能力清单（排版 / 公式 / Mermaid / 导出） |
| [docs/selection-assistant.md](docs/selection-assistant.md) | 划词助手与结果对话框（含取词安全闸门与剪贴板恢复策略） |
| [docs/pyside6-migration.md](docs/pyside6-migration.md) | 迁移史（PyQt5 → PySide6 → **当前 PyQt6 维护线**）：致命坑、API 差异速查、测试与环境（轮子 / uv）踩坑 |
| [docs/performance.md](docs/performance.md) | 性能：成本模型（shiboken / Qt6 内核 / 重绘量）+ 宿主配方 + 组件构造成本表 + 聊天 / Markdown 滚动基线脚本 |
| `pyqt6_ela_pro/example/chat_guide_page.py` | 应用内聊天接入指南 + API 速查表 |

## 可选依赖

| 依赖 | 安装方式 | 用途 |
|---|---|---|
| pywin32 | `[all]` | 窗口嵌入 / 浏览器嵌入 / 任务栏进度 |
| comtypes | `[all]` | Office 文档预览（ActiveX） |
| pygments | `[all]` | Markdown 代码语法高亮（缺失自动降级） |
| tsdownsample | `[all]` | `ElaChartWidget` 大数据降采样（缺失自动降级） |
| mermaidx | `[all]` | Markdown Mermaid 图渲染（缺失回退代码卡片） |
| orjson | `[all]` | 聊天 JSON 编解码加速（缺失回退标准库 json） |
| polars | `[all]` / `[parquet]` | `ElaParquetTable` Parquet 查看 |
| pyqtgraph | 手动安装 | `ElaPlotWidget` |
| matplotlib | 手动安装 | `ElaFigureCanvas` |

## 设计原则

- **零 QSS**：控件状态（hover / press / focus / 动效）全部 `QPainter` 自绘，主题经 `eTheme` 语义令牌取色；
- **集中换肤与动效**：强调色（`setAccentColor`）与动效策略（`motion`）都是全局单点，组件不私藏字面量；
- **可拆分复用**：大块子系统（`chat/` / `charts/` / `blueprint/` / `ElaMarkdownViewer`）的每一层
  （气泡、查看器、图表控件、节点画布）都可以脱离整机单独使用；
- **示例即文档**：示例页每个 `_demoXxx` 方法对应一个组件演示节，`</> 代码` 按钮精确展示该方法源码。

## 平台

Windows AMD64（**Windows 7 SP1+**；交付线使用 PyQt6 6.8.1 + 自编译 Qt 6.8.4 运行库，Windows 10/11 同样可用）。Python 3.11–3.13。

## 组件来源与致谢

| 组件 / 模块 | 来源 |
|---|---|
| 输入、容器、展示、对话框等原生组件 | 上游 [ElaWidgetTools](https://github.com/Liniyous/ElaWidgetTools) C++ + [PyQt6-ElaWidgetTools](https://github.com/HIllya51/PyElaWidgetTools) 绑定 |
| `ElaSplitter`、`ElaPagination`、`ElaToast`、`ElaSpotlight`、`ElaSteps`、`ElaTimeline`、`ElaRatingControl`、`ElaInfoBadge`、`ElaChip`、`ElaDropDownButton`、`ElaSplitButton`、`ElaPasswordEdit`、`ElaConfirmDialog`、`ElaMarkdownViewer`、`ElaUploadArea`、`ElaSplashScreen` | [ElaWidgetTools（RainbowCandyX fork）](https://github.com/RainbowCandyX/ElaWidgetTools) C++ 源码移植 |
| `ElaDrawer` | PyQt-SiliconUI `SiLayerDrawer` 设计（内容槽走 `ElaWidgetOwnershipType` 三态） |
| `ElaDrawerArea` | 上游 `ElaDrawerArea` 子类化修复（点击标题栏展开 / 收起） |
| `ElaButton`、`ElaDivider`、`ElaChip` 等 | Ant Design 风格自研（对照 ElaWidgetTools 既有组件） |
| `ElaChartWidget`（`charts/`） | InstructionX_UIKit `charts` 移植（类 ECharts `setOption` 引擎） |
| 蓝图节点图编辑器（`blueprint/`） | InstructionX_UIKit `blueprint` + `anim.painted.SpinnerArc` 移植 |
| `ElaMarkdownViewer` 流式增量渲染 / 公式提取 | InstructionX_UIKit `components.markdown_view` 思路移植；公式渲染为自研 `math_lite.py` |
| 聊天栈（`chat/`） | 自研（助手消息复用 `ElaMarkdownViewer` 嵌入模式；工具卡 / 补全 / 排队 / 审批交互对齐 opencode 会话 UI） |
| `ElaTerminalView`、`ElaTrayIcon`、`ElaMenuItem` | 自研 |
| `ElaTagBox` 族 | PyQt-Fluent-Widgets Tag 组件设计参考 |
| `ElaBrowserEmbedder` / `ElaWindowEmbedder` | 自研（Chromium CDP + win32gui） |

部分组件另参考了 [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
与 [PyQt-SiliconUI](https://github.com/ChinaIceF/PyQt-SiliconUI) 的设计思路。
本项目在 **Minimax** 与 **DeepSeek** 模型的辅助下完成。

## 许可证

MIT

