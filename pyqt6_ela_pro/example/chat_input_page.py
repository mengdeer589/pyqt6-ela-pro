"""
[pyqt6_ela_pro] 聊天输入区能力页

**一个真正能用的 chat**（``ElaChatMockBackend`` + ``ElaChatStreamBinder``），
按能力域分小节。每节都有一个按钮直接触发那个能力，并注明**正常使用时你会在
哪里点它** —— 输入区上有些入口（比如「清空上下文」）本来就在组件内部，
示例页如果不额外给一个按钮，读者只能靠猜。

小节：

1. **工具栏自定义** —— ``toolBar()`` 的 ``addButton`` / ``addWidget`` /
   ``addSeparator``，以及 checkable 开关怎么表达状态；
2. **附件** —— 文件 / 图片 / 粘贴 / 拖放四个来源统一走一条通道；
3. **@ 引用补全** —— ``setMentionProvider`` 提供候选；
4. **清空上下文** —— 组件自带 ``ElaConfirmDialog`` 二次确认；
5. **新建话题** —— 组件**只发信号**，界面与会话归宿主；
6. **排队 / 撤回 / 重新生成 / 停止** —— 一轮对话的四种干预。

这一页是「怎么把聊天接起来」的完整答案；组件**能力面**在「聊天组件总览」，
agent 专属能力在「Agent 能力」。
"""

from datetime import datetime

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout
from PyQt6ElaWidgetTools import ElaIconType, ElaMenu

from pyqt6_ela_pro import ElaButton, ElaDropDownButton
from pyqt6_ela_pro.chat import (
    ElaChatMockBackend,
    ElaChatRoleType,
    ElaChatStatusType,
    ElaChatReasoningStyleType,
    ElaChatStatusBar,
    ElaChatStreamBinder,
    ElaChatSuggestion,
    ElaChatWidget,
)

from .base_page import ExamplePage
from .chat_demo_kit import note

#: 默认回答（覆盖标题 / 列表 / 表格 / 代码 / 公式 / Mermaid / 引用）
_ANSWER_DEFAULT = r"""### 快速排序（Quick Sort）

快速排序是一种分治排序算法，平均时间复杂度 $O(n \log n)$。

**核心步骤**

1. 选取基准值 `pivot`；
2. 把小于基准的元素放到左边，大于的放到右边；
3. 对左右子区间递归执行。

```python
def quick_sort(items):
    if len(items) <= 1:
        return items
    pivot = items[len(items) // 2]
    left = [x for x in items if x < pivot]
    mid = [x for x in items if x == pivot]
    right = [x for x in items if x > pivot]
    return quick_sort(left) + mid + quick_sort(right)
```

| 场景 | 时间复杂度 | 空间复杂度 |
| --- | --- | --- |
| 最好 | $O(n \log n)$ | $O(\log n)$ |
| 最坏 | $O(n^2)$ | $O(n)$ |

```mermaid
graph TD
  A[选择基准] --> B{分区}
  B -->|小于| C[左子区间]
  B -->|大于| D[右子区间]
  C --> E[递归]
  D --> E
```

> [!TIP]
> 工程实现中通常随机选择基准，避免有序输入退化为 $O(n^2)$。
"""

#: 关键词匹配的回答
_ANSWERS = [
    (
        ("公式", "数学", "latex"),
        r"""行内公式 $E = mc^2$，块级公式：

$$
\int_{-\infty}^{+\infty} e^{-x^2}\,\mathrm{d}x = \sqrt{\pi}
$$

矩阵与分段函数：

$$
A = \begin{pmatrix} a & b \\ c & d \end{pmatrix},\quad
f(x) = \begin{cases} x^2, & x \ge 0 \\ -x, & x < 0 \end{cases}
$$
""",
    ),
    (
        ("表格", "对比"),
        r"""| 组件 | 用途 | 依赖 |
| --- | --- | --- |
| `ElaMarkdownViewer` | Markdown 渲染 | 无（公式自研 / Mermaid 可选） |
| `ElaChatWidget` | 聊天会话 | 无 |
| `ElaChartWidget` | 图表引擎 | 无 |
""",
    ),
]

#: 输入模板
_TEMPLATE = "请从以下三个方面分析这段代码：\n1. 时间复杂度\n2. 潜在缺陷\n3. 改进建议\n"


def _pick_answer(text: str) -> str:
    for keywords, answer in _ANSWERS:
        if any(keyword in text for keyword in keywords):
            return answer
    return _ANSWER_DEFAULT


def _long_answer() -> str:
    parts = ["## 长回答演示\n"]
    for index in range(40):
        parts.append(
            f"### 第 {index + 1} 节\n\n"
            f"这是第 {index + 1} 段内容，用于演示长回答的流式追加与滚动跟随。"
            f"行内公式 $a_{index} = {index}$，列表：\n\n"
            f"- 要点 A{index}\n- 要点 B{index}\n\n"
        )
    return "".join(parts)


class ChatInputPage(ExamplePage):
    """聊天输入区能力（工具栏 / 附件 / @ 引用 / 清空 / 新建话题 / 排队干预 / 上下文占用圆环）。"""

    PAGE_TITLE = "输入区能力"

    def __init__(self, parent=None):
        self._pending_answer = None
        self._question = ""
        self._question_attachments: list = []
        self._chat = None
        self._status = None
        self._mock = None
        self._binder = None
        self._think_level = "normal"
        self._agent_mode = "build"
        self._model_name = "deepseek-v4"
        self._section_notes: dict = {}
        self._usage_step = 0
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        main_layout.addWidget(
            note(
                self,
                "这一页是「怎么把聊天接起来」的完整答案：上面那个 chat 是真的能用的"
                "（mock 后端 + 流绑定器），下面的按钮直接触发各个能力。",
            )
        )

        self._chat = ElaChatWidget(self)
        self._chat.setUserName("我")
        self._chat.setAssistantName("deepseek-v4")
        self._chat.setPlaceholderText("输入消息，Enter 发送（支持 @ 引用、拖入文件）")
        self._chat.chatView().setEmptyTitle("有什么可以帮你？")
        self._chat.chatView().setEmptySubtitle("输入问题，或点击下面的建议开始。")
        self._chat.chatView().setSuggestions(
            ["用 Python 写一个快速排序", "展示一下数学公式", "Markdown 表格对比"]
        )
        self._chat.setMentionProvider(self._mention_suggestions)
        self._build_toolbar()
        main_layout.addWidget(self._chat)
        self._sync_chat_height()

        self._status = ElaChatStatusBar(self)
        self._status.setInfo("mock 后端 · 无真实模型调用")
        self._status.setStatus("最近操作：—")
        main_layout.addWidget(self._status)

        for section in (
            self._section_toolbar(),
            self._section_attachment(),
            self._section_mention(),
            self._section_clear(),
            self._section_new_topic(),
            self._section_turn_control(),
            self._section_usage(),
        ):
            main_layout.addLayout(section)

        self._mock = ElaChatMockBackend(self, tickMs=28, thinkLevel=self._think_level)
        self._binder = ElaChatStreamBinder(self._chat, worker=self._mock)
        self._mock.setReplyProvider(self._reply_for)
        self._mock.turnFinished.connect(self._on_turn_finished)

        self._chat.messageSubmittedFull.connect(self._on_submitted)
        self._chat.stopRequested.connect(self._on_stop_requested)
        self._chat.generationFinished.connect(self._on_generation_finished)
        self._chat.suggestionClicked.connect(self._on_suggestion)
        self._chat.undoRequested.connect(self._on_undo)
        self._chat.regenerateRequested.connect(self._on_regenerate)
        self._chat.retryRequested.connect(self._on_retry)
        self._chat.attachmentClicked.connect(self._on_attachment_clicked)
        self._chat.clearRequested.connect(self._on_clear_requested)
        self._chat.cleared.connect(self._on_context_cleared)
        self._chat.newTopicRequested.connect(self._on_new_topic_requested)
        self._chat.contextUsageClicked.connect(self._on_context_usage_clicked)

    # -- 页面高度 ----------------------------------------------------------

    def resizeEvent(self, event):  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._sync_chat_height()

    def _sync_chat_height(self):
        if self._chat is None:
            return
        target = max(420, self.height() - 420)
        if self._chat.height() == target:
            return
        self._chat.setFixedHeight(target)

    def _section(self, index, title, method, hint):
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addLayout(self._createHeaderRow(f"{index}. {title}", method))
        label = note(self, hint)
        box.addWidget(label)
        self._section_notes[index] = label
        return box

    def _say(self, index, text):
        label = self._section_notes.get(index)
        if label is not None:
            label.setText(text)

    # ================================================================ 01 工具栏
    def _section_toolbar(self):
        box = self._section(
            1,
            "工具栏自定义",
            self._demo_toolbar,
            "控件就在上面输入区的工具栏上（分两组，中间一条分隔线）："
            "左边是图标按钮（加号 / 回形针 / 对话气泡），"
            "右边是下拉与 checkable 开关。",
        )
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._button("再插一个按钮", self._on_add_toolbar_button))
        row.addWidget(self._button("推理形态：切换", self._on_toggle_reasoning))
        row.addStretch()
        box.addLayout(row)
        return box

    def _demo_toolbar(self) -> None:
        """``chat.toolBar()`` 的三个入口：``addButton`` / ``addWidget`` /
        ``addSeparator``。

        - ``addButton(icon, tooltip, key, callback, checkable=)`` —— 图标按钮，
          ``key`` 用于后续 ``toolToggled`` 回调里分辨是哪个（**别用闭包捕获
          文案**，用户改文案就认不出来了）；
        - ``addWidget(widget, key=)`` —— 任意控件（下拉 / 开关）；
        - ``addSeparator()`` 分组。

        组件只管摆放与状态回传，**点了干什么归宿主**。checkable 项会发
        ``toolToggled(key, checked)``。
        """
        toolbar = self._chat.toolBar()
        toolbar.addButton(
            icon=ElaIconType.IconName.Bolt,
            tooltip="插入分析模板",
            key="template",
            callback=self._on_template,
        )
        toolbar.addWidget(self._agent_button, key="agent")
        toolbar.toolToggled.connect(self._on_tool_toggled)

    def _on_add_toolbar_button(self) -> None:
        key = f"extra{len(getattr(self, '_extra_keys', ())) + 1}"
        self._extra_keys = tuple(getattr(self, "_extra_keys", ())) + (key,)
        self._chat.toolBar().addButton(
            icon=ElaIconType.IconName.Bolt,
            tooltip=f"动态追加的按钮 {key}",
            key=key,
            callback=lambda: self._status.setStatus(f"点了动态按钮 {key}"),
        )
        self._say(1, f"addButton(key={key!r}) —— 工具栏按钮是随时可加的")

    def _on_toggle_reasoning(self) -> None:
        self._reasoning_style = getattr(
            self, "_reasoning_style", ElaChatReasoningStyleType.Collapse
        )
        self._reasoning_style = (
            ElaChatReasoningStyleType.Inline
            if self._reasoning_style == ElaChatReasoningStyleType.Collapse
            else ElaChatReasoningStyleType.Collapse
        )
        self._chat.chatView().setReasoningStyle(self._reasoning_style)
        self._say(
            1, f"推理形态切到 {self._reasoning_style}（checkable 项发 toolToggled）"
        )

    def _build_toolbar(self):
        toolbar = self._chat.toolBar()
        toolbar.addSeparator()
        toolbar.addButton(
            icon=ElaIconType.IconName.PenToSquare,
            tooltip="插入分析模板",
            key="template",
            callback=self._on_template,
        )
        toolbar.addButton(
            icon=ElaIconType.IconName.Paperclip,
            tooltip="添加示例附件",
            key="demo_file",
            callback=self._on_demo_attachment,
        )
        toolbar.addButton(
            icon=ElaIconType.IconName.Comment,
            tooltip="上下文引用（@）",
            key="context",
            callback=self._on_context,
        )
        toolbar.addSeparator()
        self._agent_button = self._build_agent_button()
        toolbar.addWidget(self._agent_button, key="agent")
        self._model_button = self._build_model_button()
        toolbar.addWidget(self._model_button, key="model")
        self._think_button = self._build_think_button()
        toolbar.addWidget(self._think_button, key="think_level")
        toolbar.toolToggled.connect(self._on_tool_toggled)

    def _build_agent_button(self) -> ElaDropDownButton:
        """Agent 选择（构建 / 规划）—— 宿主自己的概念，组件只提供摆放位。"""
        label = {"build": "构建", "plan": "规划"}.get(self._agent_mode, "构建")
        button = ElaDropDownButton(label, ElaIconType.IconName.Robot, parent=self)
        button.setFixedHeight(28)
        button.setToolTip(f"Agent：{label}（点击切换）")
        menu = ElaMenu(self)
        menu.setMenuItemHeight(30)
        self._agent_actions = {}
        for mode, text in (("build", "构建"), ("plan", "规划")):
            action = menu.addElaIconAction(ElaIconType.IconName.Robot, text)
            action.setCheckable(True)
            action.setChecked(mode == self._agent_mode)
            action.triggered.connect(
                lambda _checked=False, value=mode: self._set_agent_mode(value)
            )
            self._agent_actions[mode] = action
        button.setMenu(menu)
        return button

    def _build_model_button(self) -> ElaDropDownButton:
        """模型选择 —— 组件自带一个「助手名」位，切模型时同步过去。"""
        button = ElaDropDownButton(
            self._model_name, ElaIconType.IconName.Microchip, parent=self
        )
        button.setFixedHeight(28)
        button.setToolTip(f"模型：{self._model_name}（点击切换）")
        menu = ElaMenu(self)
        menu.setMenuItemHeight(30)
        self._model_actions = {}
        for model in ("deepseek-v4", "gpt-5-mini", "Spark-X2.5-4B-FP8"):
            action = menu.addElaIconAction(ElaIconType.IconName.Microchip, model)
            action.setCheckable(True)
            action.setChecked(model == self._model_name)
            action.triggered.connect(
                lambda _checked=False, value=model: self._set_model(value)
            )
            self._model_actions[model] = action
        button.setMenu(menu)
        return button

    def _build_think_button(self) -> ElaDropDownButton:
        """思考强度（关闭 / 标准 / 深度）—— 只改 mock 后端的产出，组件无感。"""
        button = ElaDropDownButton("", ElaIconType.IconName.Lightbulb, parent=self)
        button.setFixedHeight(28)
        button.setToolTip("思考强度")
        menu = ElaMenu(self)
        menu.setMenuItemHeight(30)
        self._think_actions = {}
        for level, label in (
            ("off", "关闭思考"),
            ("normal", "标准思考"),
            ("deep", "深度思考"),
        ):
            action = menu.addElaIconAction(ElaIconType.IconName.Lightbulb, label)
            action.setCheckable(True)
            action.setChecked(level == self._think_level)
            action.triggered.connect(
                lambda _checked=False, value=level: self._set_think_level(value)
            )
            self._think_actions[level] = action
        button.setMenu(menu)
        return button

    def _on_tool_toggled(self, key: str, checked: bool):
        if key == "reasoning_style":
            self._chat.chatView().setReasoningStyle(
                ElaChatReasoningStyleType.Inline
                if checked
                else ElaChatReasoningStyleType.Collapse
            )

    # ================================================================ 02 附件
    def _section_attachment(self):
        box = self._section(
            2,
            "附件（文件 / 图片 / 粘贴 / 拖放）",
            self._demo_attachment,
            "四个来源走同一条通道：文件 → 附件条 → 消息；图片 → 图片预览。"
            "现在把一个文件塞进输入框，或直接把文件拖到上面任意位置。",
        )
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._button("加一个示例附件", self._on_demo_attachment))
        row.addWidget(self._button("带附件直接发送", self._on_send_with_attachment))
        row.addStretch()
        box.addLayout(row)
        return box

    def _demo_attachment(self) -> None:
        """附件：``chatInput().addAttachment(name, path, size)``。

        **拖放与粘贴不需要你写**：组件把整块（卡片 / 工具栏空白 / 编辑框）
        都设成放置点，判定逻辑集中在库内一份 ``chat/_mime.py``。真宿主要做的
        只有「点击附件名」的反应 —— 连 ``attachmentClicked(messageId, path)``。

        容易漏的一处：**复制的文件**（Explorer 里 Ctrl+C）拖进来，mime 是
        ``file://`` URL 而不是路径，各写一份判定就会漏掉这一种。

        **大段粘贴（≥8000 字符或 ≥120 行）自动转附件**：写成临时文件后走
        同一条附件通道（``filesAdded`` 照常发），不把几兆文本塞进编辑框。
        """
        self._chat.chatInput().addAttachment("blocks.py", "src/chat/blocks.py", 48_120)
        self._chat.sendUserMessage(
            "这两个文件一起看", attachments=[{"name": "notes.md", "size": 1_204}]
        )
        self._chat.attachmentClicked.connect(self._on_attachment_clicked)

    def _on_demo_attachment(self) -> None:
        name = datetime.now().strftime("示例文件_%H%M%S.txt")
        self._chat.chatInput().addAttachment(name, f"C:/demo/{name}", 2048)
        self._say(2, f"已加附件 {name} —— 回车发送后它会出现在消息下方")

    def _on_send_with_attachment(self) -> None:
        self._chat.sendUserMessage(
            "这两个文件一起看",
            attachments=(
                {"name": "blocks.py", "path": "src/chat/blocks.py", "size": 48_120},
                {"name": "notes.md", "path": "notes.md", "size": 1_204},
            ),
        )
        self._say(2, "sendUserMessage(text, attachments=[...]) —— 附件随消息落库")

    def _on_attachment_clicked(self, messageId: int, path: str):
        self._status.setStatus(f"附件被点击：消息 #{messageId} → {path}")

    # ================================================================ 03 引用
    def _section_mention(self):
        box = self._section(
            3,
            "@ 上下文引用",
            self._demo_mention,
            "输入区里打 @ 会弹候选浮层。候选由 setMentionProvider 提供 —— "
            "组件只做过滤与高亮，候选从哪来（文件 / 分支 / 历史提问）归宿主。",
        )
        row = QHBoxLayout()
        row.addWidget(self._button("打开 @ 补全", self._on_context))
        row.addStretch()
        box.addLayout(row)
        return box

    def _demo_mention(self) -> None:
        """``setMentionProvider(callable)``：给关键词，返回候选列表。

        provider 收到的是「用户已经敲的那段关键词」，返回
        ``[ElaChatSuggestion(id, label), ...]``。**返回空列表就关闭浮层** ——
        不要用「返回上一次结果」来保活，用户会觉得幽灵条目在乱跳。
        """
        self._chat.setMentionProvider(self._mention_suggestions)
        self._chat.chatInput().openMentionPopup()
        self._chat.mentionSelected.connect(
            lambda ref_id, label: self._status.setStatus(f"引用 {label}")
        )

    def _on_context(self) -> None:
        self._chat.chatInput().openMentionPopup()
        self._say(3, "在输入框里打字筛选；↑↓ 移动、Enter 选中")

    def _mention_suggestions(self, query: str):
        items = [
            ElaChatSuggestion(id="src/main.py", label="src/main.py"),
            ElaChatSuggestion(id="src/utils.py", label="src/utils.py"),
            ElaChatSuggestion(id="README.md", label="README.md"),
        ]
        query = (query or "").lower()
        return [item for item in items if query in item.id.lower()]

    # ================================================================ 04 清空
    def _section_clear(self):
        box = self._section(
            4,
            "清空上下文",
            self._demo_clear,
            "输入区工具栏右端的垃圾桶图标。组件先发 clearRequested（给宿主埋点），"
            "再弹 ElaConfirmDialog 二次确认；确认后组件清界面并发 cleared。",
        )
        row = QHBoxLayout()
        row.addWidget(self._button("请求清空", self._chat.requestClear))
        row.addStretch()
        box.addLayout(row)
        return box

    def _demo_clear(self) -> None:
        """清空上下文：``requestClear()`` → 确认 → ``cleared``。

        - **空会话直接 return**，不弹框也不发信号 —— 否则宿主埋点里的
          「等待确认…」提示会一直挂着；
        - **别接 ``clearRequested`` 当清空入口**，它是确认**之前**的钩子，
          用户点「取消」也会先响一次；
        - **清空分两半**：组件清界面，后端会话历史归宿主 —— 在 ``cleared``
          里调 ``worker.reset()``，少这一步模型还记得上文。
        """
        self._chat.clearRequested.connect(self._on_clear_requested)  # 确认之前
        self._chat.cleared.connect(self._on_context_cleared)  # 确认之后
        self._chat.requestClear()

    def _on_clear_requested(self):
        """确认**之前**的钩子：只埋点。"""
        self._say(4, "clearRequested —— 用户点了垃圾桶，等确认…")

    def _on_context_cleared(self):
        """确认之后：组件清界面，**宿主清后端上下文**。"""
        self._mock.reset()
        self._say(4, "cleared —— 组件已清界面，这里补上 worker.reset()")

    # ================================================================ 05 话题
    def _section_new_topic(self):
        box = self._section(
            5,
            "新建话题",
            self._demo_new_topic,
            "输入区工具栏上的加号。组件**什么都不做**，只发 newTopicRequested ——"
            "界面、话题 id、会话历史全归宿主。",
        )
        row = QHBoxLayout()
        row.addWidget(self._button("请求新建话题", self._on_new_topic_clicked))
        row.addStretch()
        box.addLayout(row)
        return box

    def _demo_new_topic(self) -> None:
        """新建话题：组件只发信号，宿主做四件事。

        1. ``view.clear()`` 清界面；
        2. ``worker.reset()`` 清后端会话；
        3. 新建一条 ``ElaChatSessionInfo``；
        4. ``setCurrentSessionId(id)``（纯标记，库不据此做任何事）。

        组件**故意不清草稿 / 附件** —— 用户正在打的那半句话不该被系统动作吃掉。
        """
        self._chat.newTopicRequested.connect(self._on_new_topic_requested)
        self._chat.chatView().clear()
        self._mock.reset()
        self._chat.setCurrentSessionId("s2")

    def _on_new_topic_clicked(self):
        self._on_new_topic_requested()

    def _on_new_topic_requested(self):
        self._say(5, "newTopicRequested —— 宿主在这里建话题（本页只有一个话题）")

    # ================================================================ 06 干预
    def _section_turn_control(self):
        box = self._section(
            6,
            "排队 / 撤回 / 重新生成 / 停止",
            self._demo_turn_control,
            "一轮对话的四种干预。生成中发第二条消息会自动排队续发"
            "（autoSendQueue 默认开）；撤回 / 重新生成 / 重试在每条消息的"
            "悬停操作条上。",
        )
        row = QHBoxLayout()
        for text, callback in (
            ("排一条消息（不立即发）", self._on_enqueue),
            ("撤回最后一条", self._on_undo_last),
            ("重新生成最后一条", self._on_regenerate_last),
            ("停止生成", self._on_stop_clicked),
            ("30 条消息压测", self._on_stress),
            ("长回答", self._on_long_answer),
        ):
            row.addWidget(self._button(text, callback))
        row.addStretch()
        box.addLayout(row)
        return box

    def _demo_turn_control(self) -> None:
        """一轮对话的四种干预，四个 API 各自的语义差别要记住：

        - ``stopGeneration()`` —— 停当前轮，**保留已输出内容**，收尾状态
          ``Stopped``；
        - ``undoLastUserMessage()`` —— 撤回**最后一条用户消息**：删该条及其后
          所有消息，原文 / 附件回填输入框；按显式 id 撤回用 ``undoMessage(id)``，
          它**只对用户消息生效**（传助手消息返回 ``None``）；
        - ``regenerateFrom(id)`` —— **删掉**那条回答重发（回答侧）；
        - ``retryMessage(id)`` —— 同参数重发但**不删消息**，保留 id 与时间线
          位置（错误卡上的「重试」走这条）；
        - ``enqueueMessage()`` —— 排队，等整轮跑完自动续发。

        生成中再发一条消息，默认就是排队（``setAutoSendQueue(True)``）。
        """
        self._chat.enqueueMessage("排队中的一条", messageId=42)  # 生成中提交 → 排队
        self._chat.stopGeneration()  # 停当前轮（保留已输出内容）

        # 「撤回最后一条」= 撤回最后一条用户消息（不是最后一条消息）
        self._chat.undoLastUserMessage()

        # 显式 id 的两种方向：
        # self._chat.undoMessage(userMessageId)         # 只对用户消息生效
        # self._chat.regenerateFrom(assistantMessageId) # 删掉这条回答重发
        # self._chat.retryMessage(assistantMessageId)   # 原地重试（不删消息）

    def _on_enqueue(self) -> None:
        self._chat.enqueueMessage("（排队中）这一条等上一轮跑完再发")
        self._say(
            6, f"enqueueMessage —— 队列 {self._chat.queueCount()} 条，跑完自动续发"
        )

    def _on_undo_last(self) -> None:
        # 「撤回最后一条」= 撤回最后一条**用户消息**（不是最后一条消息 ——
        # 最后一条通常是助手回答，拿它的 id 去撤会被 undoMessage 拒绝）
        target = self._chat.undoLastUserMessage()
        if target is None:
            self._say(6, "还没有用户消息可撤回")
            return
        self._mock.cancel()
        self._pending_answer = None
        self._say(6, f"已撤回最后一条用户消息（#{target.id}），原文已回填输入框")

    def _on_regenerate_last(self) -> None:
        view = self._chat.chatView()
        messages = view.messages()
        if not messages:
            self._say(6, "还没有消息可重新生成")
            return
        self._on_regenerate(messages[-1].id)

    def _on_stop_clicked(self) -> None:
        self._on_stop_requested()

    def _on_long_answer(self) -> None:
        self._pending_answer = _long_answer()
        self._chat.sendUserMessage("给我一个很长的回答")

    def _on_stress(self) -> None:
        for index in range(30):
            self._chat.addMessage(
                ElaChatRoleType.User,
                f"压测消息 {index + 1}：" + "这是一段用于撑开滚动区域的内容。" * 3,
            )
        self._chat.chatView().scrollToBottom()
        self._say(6, "已追加 30 条消息（验证贴底与滚动）")

    # ================================================================ mock 后端
    def _reply_for(self, question: str) -> str:
        answer = self._pending_answer or _pick_answer(question)
        self._pending_answer = None
        return answer

    def _on_suggestion(self, text: str) -> None:
        self._chat.sendUserMessage(text)

    def _on_submitted(self, text: str, attachments: list) -> None:
        note_text = f"（附件 {len(attachments)} 个）" if attachments else ""
        self._question = text
        self._question_attachments = list(attachments or ())
        self._status.setStatus(f"已发送：{text[:20]}{note_text}")
        self._start_answer()

    def _start_answer(self) -> None:
        """开始一轮 mock 生成（binder 负责建消息 / 步骤 / 思考 / 工具 / 统计）。"""
        # 附件必须走 startTurn(attachments=...) 送进后端；mock 后端只收不留用，
        # 真实后端在这里就能拿到用户上传的文件
        self._binder.startTurn(self._question, attachments=self._question_attachments)
        self._question_attachments = []
        self._status.setStatus("生成中…", level="busy")

    def _on_turn_finished(self, turn) -> None:
        summary = self._binder.finish(turn)
        if summary is None:
            return  # 迟到的旧回合收尾（已开新回合），不动状态栏
        if summary.status == ElaChatStatusType.Stopped:
            self._status.setStatus("已停止（保留已输出内容）")
        elif summary.isEmptyReply():
            self._status.setStatus(
                f"模型未返回正文（finish_reason={summary.finishReason or 'unknown'}）",
                level="error",
            )
        else:
            self._status.setStatus(
                f"完成 · {summary.durationMs / 1000:.1f}s · "
                f"{self._chat.chatView().count()} 条消息",
                level="success",
            )

    def _on_stop_requested(self) -> None:
        self._binder.cancel()  # 记录停止，finish 自动按 Stopped 收尾
        self._mock.cancel()
        self._status.setStatus("已停止生成（保留已输出内容）")

    def _on_generation_finished(self, messageId: int, status: str) -> None:
        queued = self._chat.queuedMessages()
        self._status.setStatus(
            f"消息 #{messageId}（状态 {status}），"
            f"当前会话 {self._chat.chatView().count()} 条消息"
            + (f"，排队 {len(queued)} 条（将自动续发）" if queued else "")
        )

    def _on_undo(self, messageId: int) -> None:
        self._mock.cancel()
        target = self._chat.undoMessage(messageId)
        if target is None:
            return
        self._pending_answer = None
        self._say(6, f"已撤回消息 #{messageId}，原文已回填输入框")

    def _on_regenerate(self, messageId: int) -> None:
        self._mock.cancel()
        userMessage = self._chat.regenerateFrom(messageId)
        if userMessage is None:
            self._status.setStatus("找不到可重新生成的用户消息", level="error")
            return
        self._question = userMessage.text
        # 快照里带着附件，重新生成必须原样送回后端（否则模型看不见文件）
        self._question_attachments = list(userMessage.attachments)
        self._pending_answer = None
        self._start_answer()

    def _on_retry(self, messageId: int) -> None:
        self._mock.cancel()
        userMessage = self._chat.retryMessage(messageId)
        if userMessage is None:
            self._status.setStatus("找不到可重试的用户消息", level="error")
            return
        self._question = userMessage.text
        self._question_attachments = list(userMessage.attachments)
        self._pending_answer = None
        self._start_answer()

    # ================================================================ 杂项
    def _on_template(self) -> None:
        self._chat.chatInput().setText(_TEMPLATE)
        self._chat.chatInput().textEdit().setFocus()
        self._say(1, "已插入分析模板（工具栏第一个按钮）")

    def _set_think_level(self, level: str):
        self._think_level = level
        if self._mock is not None:
            self._mock.setThinkLevel(level)
        for key, action in self._think_actions.items():
            action.setChecked(key == level)
        self._status.setStatus(f"思考强度：{level}")

    def _set_agent_mode(self, mode: str):
        self._agent_mode = mode if mode in ("build", "plan") else "build"
        for value, action in self._agent_actions.items():
            action.setChecked(value == self._agent_mode)
        label = {"build": "构建", "plan": "规划"}.get(self._agent_mode, "构建")
        self._agent_button.setText(label)
        self._agent_button.setToolTip(f"Agent：{label}（点击切换）")
        self._status.setInfo(f"mock 后端 · {self._model_name} · Agent {label}")

    def _set_model(self, model: str):
        self._model_name = model or self._model_name
        for value, action in self._model_actions.items():
            action.setChecked(value == self._model_name)
        self._model_button.setText(self._model_name)
        self._model_button.setToolTip(f"模型：{self._model_name}（点击切换）")
        self._chat.setAssistantName(self._model_name)
        label = {"build": "构建", "plan": "规划"}.get(self._agent_mode, "构建")
        self._status.setInfo(f"mock 后端 · {self._model_name} · Agent {label}")

    # ================================================ 07 上下文占用圆环
    def _section_usage(self):
        box = self._section(
            7,
            "上下文占用圆环",
            self._demo_usage,
            "圆环就在上面输入区工具栏里（与「清空上下文」同排的**默认组件**，"
            "无数据时画空底环）。点「喂一档占用」循环 9% → 72% → 92% → 归零"
            "看三档配色，再**直接点一下圆环**看点击回执。",
        )
        row = QHBoxLayout()
        row.addWidget(self._button("喂一档占用", self._demo_usage))
        row.addStretch()
        box.addLayout(row)
        return box

    def _demo_usage(self) -> None:
        """上下文占用圆环：数据全由宿主提供（库不推断），按百分比三档配色。

        - ``chat.chatInput().setContextUsage(used, window, costUsd)`` —— 圆环挂在
          **输入区工具栏**（经 ``chatInput()`` 访问），是**默认常驻**组件
          （与新建话题 / 上传 / 清空同排，无数据时画空底环）；``window <= 0``
          按 0% 显示（换话题 / 清空后宿主可这样重置）；显隐走
          ``setContextUsageVisible``；
        - 三档配色：``<60%`` 弱化 / ``60~85%`` 警示 / ``>=85%`` 危险（红色 +
          tooltip 追加「建议压缩上下文」）；hover 显示花费 / 百分比 / 词元数；
        - **圆环可点击**：``chat.contextUsageClicked``（或
          ``chatInput().contextUsageClicked``）—— 组件不做任何行为，
          弹什么详情面板归宿主（本页写在说明行里）。
        """
        states = (
            (18_000, 200_000, 0.0900),  # 9%  弱化
            (144_000, 200_000, 0.3500),  # 72% 警示
            (184_000, 200_000, 0.6200),  # 92% 危险（tooltip 追加建议）
            (0, 0, 0.0),  # 归零：空底环（0%，圆环默认常驻）
        )
        used, window, cost = states[self._usage_step % len(states)]
        self._usage_step += 1
        chat_input = self._chat.chatInput()
        chat_input.setContextUsage(used, window, cost)
        if window <= 0:
            self._say(
                7,
                "已归零：window=0 → 空底环 0%（换话题 / 清空后宿主可这样重置）",
            )
            return
        self._say(
            7,
            f"已喂 {used:,} / {window:,} 词元（{chat_input.contextUsagePercent()}%）"
            f" · 花费 ${cost:.4f} —— 点一下工具栏里的圆环看点击回执",
        )

    def _on_context_usage_clicked(self) -> None:
        """圆环点击回执：真宿主在这里弹自己的上下文详情面板。"""
        chat_input = self._chat.chatInput()
        used, window, cost = chat_input.contextUsage()
        self._say(
            7,
            f"点击回执：已用 {used:,} / {window:,}（{chat_input.contextUsagePercent()}%）"
            f" · 花费 ${cost:.4f} —— 弹什么面板归宿主（组件只发信号）",
        )

    def _button(self, text, callback):
        button = ElaButton(text, variant="outlined", size="small", parent=self)
        button.clicked.connect(callback)
        return button
