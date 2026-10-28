"""
[pyqt6_ela_pro] 聊天组件的 Agent 能力演示页。

``chat_input_page.py`` 演示的是「怎么把一个聊天组件接起来」；本页演示的是**典型
智能体软件**比普通聊天多出来的那几件事，每节都能单独点「</> 代码」看接法：

1. **工具结果富渲染**（``registerToolRenderer``）—— 宿主按工具名接管工具卡的
   **内容区**，头部 / 折叠 / 错误竖线 / 忙碌环 / 展开策略仍由 ``ToolCallCard``
   负责（所以库内既有工具卡行为一条不变）。本节注册 ``patch`` / ``edit`` 渲染
   成带增删统计的假 diff，并让 ``subtitle`` 声明来源键以避免「2 个文件
   files=[...]」重复。
2. **工具审批**（``beginPermission``）—— 卡片只负责**画 + 收集 + 发信号**，
   **绝不阻塞**（在 Qt 里挂起等用户点按钮会卡死事件循环）。本节演示批准型
   （允许一次 / 始终允许 / 拒绝…带反馈）与问答型（候选项单选）。
3. **steer 插话**（``steerMessage``）—— 生成中把新指令送进**正在跑的这一轮**
   （对齐 opencode 的 ``Delivery = "steer" | "queue"``），投递点是
   ``beginStep`` 之后的安全边界。回执走「``↳`` 旁注」而不是插一条用户气泡。
4. **上下文压缩**（``beginCompaction``）—— 库**不实现压缩算法**，只在时间线
   上如实表达「这里发生过一次压缩」并接住摘要（压不压、压哪段由宿主决定）。
5. **成本与上下文占用** —— ``cost_usd``（定价表归宿主，库只给换算纯函数）
   + 输入区工具栏里的占用圆环（三档配色）。
6. **手动重试** —— 错误类型单独存字段，错误卡据此决定是否点亮「重试」
   （限流 / 超时可重试，参数错误 / 鉴权失败不给）。

本节代码全部写在各 ``_demo_*`` 方法体内 —— 「</> 代码」按钮展示的就是那个
方法自己的源码。
"""

import traceback

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from PyQt6ElaWidgetTools import eTheme

from pyqt6_ela_pro import ElaButton
from pyqt6_ela_pro._styles import ColorText
from pyqt6_ela_pro.chat import (
    ElaChatOption,
    ElaChatPermission,
    ElaChatQuestion,
    ElaChatStats,
    ElaChatWidget,
    ModelPricing,
    registerToolRenderer,
    stats_cost,
    unregisterToolRenderer,
)
from pyqt6_ela_pro.chat._theme import mono_font, muted_color
from .base_page import ExamplePage
from .chat_demo_kit import note

#: 示例定价表（每百万词元美元）—— 真实宿主从自己的模型配置里取
_DEMO_PRICING = ModelPricing(
    input_per_m=3.0,
    output_per_m=15.0,
    cache_read_per_m=0.3,
    # 上下文超 200k 的部分按贵档计（对齐 opencode 的 tier 语义）
    tiers=((200_000, ModelPricing(input_per_m=6.0, output_per_m=22.5)),),
)

#: 演示用的上下文窗口（词元）
_DEMO_WINDOW = 200_000


class _DiffView(QWidget):
    """假的 diff 视图（真宿主会换成自己的 unified-diff 控件）。

    实现了**可选**的 ``updateToolResult(result, status)`` —— 卡片有它就把
    结果推送过来，没有就只在首次展开时建一次。这个方法名与签名是约定，
    库不做鸭子类型之外的检查。

    **每个 ``ColorText`` 都必须显式 ``setTextPixelSize``。** ``ColorText`` 走
    ``ElaText``，不设就是 ``ElaText`` 的默认字号（约 18px），比工具卡头部
    （13/12/11px）大一大截 —— 渲染器内容区突然冒出巨大字号，整张卡的比例就
    崩了（实测截图里最刺眼的问题）。库内每一处 ``ColorText`` 都显式设了字号，
    宿主写渲染器时同理。
    """

    #: 文件路径字号（与卡片头部的副标题同级）
    PATH_PX = 12
    #: 增删行数字号（与参数摘要同级）
    COUNT_PX = 11
    #: 工具返回原文（等宽，与审批卡的 diff 详情同级）
    BODY_PX = 11

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self._entries = list(entries or [])
        self.setObjectName("diffView")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        mode = eTheme.getThemeMode()
        for entry in self._entries:
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            path = ColorText(str(entry.get("path", "?")), row)
            path.setTextFormat(Qt.TextFormat.PlainText)
            path.setTextPixelSize(self.PATH_PX)
            row_layout.addWidget(path, 1)
            count = ColorText(f"+{entry.get('add', 0)} / -{entry.get('del', 0)}", row)
            count.setTextFormat(Qt.TextFormat.PlainText)
            count.setTextPixelSize(self.COUNT_PX)
            count.setTextColor(muted_color(mode, 0.6))
            row_layout.addWidget(count, 0, Qt.AlignmentFlag.AlignRight)
            layout.addWidget(row)
        self._body = ColorText(self)
        self._body.setTextFormat(Qt.TextFormat.PlainText)
        self._body.setTextPixelSize(self.BODY_PX)
        self._body.setFont(mono_font(self.BODY_PX))
        self._body.setTextColor(muted_color(mode, 0.75))
        self._body.setWordWrap(True)
        layout.addWidget(self._body)

    def updateToolResult(self, result: str, status: str) -> None:
        """结果推送（工具跑完后调用）。"""
        self._body.setText(f"// 工具返回（status={status}）\n{result or ''}")


class ChatAgentPage(ExamplePage):
    """聊天组件的 Agent 能力演示（渲染器 / 审批 / steer / 压缩 / 成本 / 重试）。"""

    PAGE_TITLE = "Agent 能力"

    def __init__(self, parent=None):
        self._chat = None
        self._active_note = None
        self._renderers_registered = False
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        main_layout.addWidget(
            note(
                self,
                "上面是共用的一条会话（输入区已隐藏），下面每一节都是「说明 + 按钮」，"
                "点按钮就把那一节的效果追加进上面那条会话 —— 控件与效果不用隔着"
                "整页去找。每节落定后的反馈都写在该节自己的说明行里。",
            )
        )

        self._chat = ElaChatWidget(self)
        self._chat.setUserName("我")
        self._chat.setAssistantName("deepseek-v4")
        self._chat.chatView().setEmptyTitle("Agent 能力")
        self._chat.chatView().setEmptySubtitle(
            "点下面任意一节的按钮，往这里追加对应能力的效果。"
        )
        self._chat.setPlaceholderText("（本页由下方按钮驱动，无需输入）")
        self._chat.setGenerating(False)
        self._chat.chatInput().setVisible(False)

        # 接线：审批 / 重试 / steer 三个宿主行为信号
        self._chat.permissionRequested.connect(self._on_permission_requested)
        self._chat.permissionReplied.connect(self._on_permission_replied)
        self._chat.retryRequested.connect(self._on_retry_requested)
        self._chat.steerReady.connect(self._on_steer_ready)

        main_layout.addWidget(self._chat)
        self._sync_chat_height()

        for index, title, method, buttons, hint in self._sections():
            main_layout.addLayout(self._section(index, title, method, buttons, hint))

    def _sections(self):
        """本页的能力域清单：``(序号, 标题, 「</> 代码」对应的方法, 按钮, 说明)``。"""
        return (
            (
                1,
                "工具结果富渲染",
                self._demo_renderer,
                (("注册渲染器", self._demo_renderer), ("注销", self._demo_unregister)),
                "registerToolRenderer：渲染器只接管工具卡的内容区，头部 / 折叠 / "
                "错误竖线 / 忙碌环 / 展开策略仍由卡片负责（所以库内既有工具卡行为"
                "一条不变）。注册后往上面会话里发一张 patch 卡，展开看 diff。",
            ),
            (
                2,
                "工具审批 · 批准型",
                self._demo_permission,
                (("插入批准型审批卡", self._demo_permission),),
                "卡片只画卡 + 发信号，绝不阻塞（Qt 里挂起等点击会卡死事件循环）。"
                "三个动作按重要性分档：允许一次（实心）/ 始终允许（描边）/ "
                "拒绝（文字 + 危险色）。",
            ),
            (
                3,
                "工具审批 · 问答型（逐题向导）",
                self._demo_question,
                (("插入 3 题向导", self._demo_question),),
                "questions 非空时渲染成逐题向导：候选项带说明（两行）、多题逐题答、"
                "头部「N / M」+ 可点的进度段，「输入自己的答案」是列表最后一项。",
            ),
            (
                4,
                "steer 插话",
                self._demo_steer,
                (("插入一条插话", self._demo_steer),),
                "生成中把新指令送进正在跑的这一轮（区别于排队：排队等整轮跑完）。"
                "投递点是 beginStep 之后的安全边界，回执走「↳」旁注而不是插用户气泡。",
            ),
            (
                5,
                "上下文压缩",
                self._demo_compaction,
                (("插入压缩分隔卡", self._demo_compaction),),
                "库不实现压缩算法，只在时间线上如实表达「这里发生过一次压缩」"
                "并接住摘要；压不压、压哪段全由宿主决定。",
            ),
            (
                6,
                "成本与上下文占用",
                self._demo_cost,
                (("累计一轮用量", self._demo_cost),),
                "cost_usd 跟着 ElaChatStats 走，定价表不烤进库；会话级汇总走 "
                "view.sessionStats(limit)（计数 / 当前上下文四路词元 / 使用率 / "
                "累计成本，口径对齐 opencode），把 total_tokens / total_cost_usd "
                "喂给输入区工具栏的圆环（本页输入区隐藏，看效果去「输入区能力」页）。",
            ),
            (
                7,
                "手动重试",
                self._demo_retry,
                (("插入错误卡", self._demo_retry),),
                "错误类型单独存字段，错误卡据此决定是否点亮「重试」"
                "（限流 / 超时可重试，参数错误 / 鉴权失败 / 内容过滤不给）。",
            ),
        )

    def _section(self, index, title, method, buttons, hint):
        """一节 = 标题行（含「</> 代码」+ 按钮）+ 一行说明。"""
        box = QVBoxLayout()
        box.setSpacing(6)
        label = note(self, hint)
        row = self._createHeaderRow(f"{index:02d}. {title}", method)
        for text, callback in buttons:
            row.addWidget(self._button(text, self._fire(label, callback)))
        box.addLayout(row)
        box.addWidget(label)
        return box

    def _fire(self, label, callback):
        """把按钮回调绑到「它属于哪一节」，这样 ``_note()`` 知道写哪一行。

        顺带 catch：这些都跑在 Qt 回调链上，未捕获异常会 0xC0000409 静默终止。
        """

        def run():
            self._active_note = label
            try:
                callback()
            except Exception:
                traceback.print_exc()

        return run

    def _sync_chat_height(self):
        if self._chat is not None:
            self._chat.setFixedHeight(max(360, self.height() - 500))

    def resizeEvent(self, event):  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._sync_chat_height()

    def _button(self, text, callback):
        btn = ElaButton(text, variant="outlined", size="small", parent=self)
        # 标题行后面有 stretch，不限宽的话按钮会被拉成一整条
        btn.setFixedWidth(max(96, 13 * len(text) + 26))
        btn.clicked.connect(callback)
        return btn

    def _note(self, text):
        """写到**当前节**的说明行 —— 节内演示方法的反馈出口。"""
        if self._active_note is not None:
            self._active_note.setText(text)

    # ================================================================ 演示 1
    def _demo_renderer(self) -> None:
        """工具结果富渲染：把 ``patch`` / ``edit`` 的内容区换成自己的 diff 视图。

        关键点（``chat/renderers.py`` 的 docstring 有完整版）：

        - 渲染器**只接管内容区**，卡片 chrome 不动 —— 所以库里既有的
          「副标题去重 / 运行中不显示参数 / 展开策略」三条回归行为全保留；
        - ``subtitle`` 返回 ``(键, 值)`` 而不是裸字符串：那个键会被自动从
          参数摘要里排除，否则折叠态会出现「2 个文件 files=[{...}]」；
        - 给上下文工具注册渲染器时**默认退出分组**（``groupable=None`` →
          上下文工具为 ``False``），否则会被 ``ContextToolGroupCard``
          整张卡绕过；
        - 返回的 widget 会被卡片持有 Python 引用，宿主**不用**自己 ``del``。
        """
        if self._renderers_registered:
            return

        def build(ctx):
            """上下文是**建卡那一刻的不可变快照**，不持控件引用。"""
            entries = [
                item
                for item in (ctx.parsedArguments().get("files") or [])
                if isinstance(item, dict)
            ]
            return _DiffView(entries)

        def subtitle(arguments: str):
            """折叠态副标题：告诉用户「几个文件」而不是甩一串 JSON。"""
            data = _parse(arguments)
            files = data.get("files")
            count = len(files) if isinstance(files, list) else 0
            return ("files", f"{count} 个文件" if count else "")

        registerToolRenderer("patch", build, subtitle=subtitle)
        registerToolRenderer("edit", build, subtitle=subtitle)
        self._renderers_registered = True

        view = self._chat.chatView()
        # 走 **widget 层**的回合入口（`sendUserMessage` + `beginAssistantMessage`），
        # 别直接 `view.beginMessage` —— 那样 widget 不知道当前流式消息是哪条，
        # steer 回执就找不到落点（`drainSteer` 靠 `streamingMessageId()`）。
        self._chat.sendUserMessage("给 patch 加 diff 渲染")
        messageId = self._chat.beginAssistantMessage()
        view.beginStep(messageId)
        callId = view.addToolCall(
            messageId,
            "patch",
            '{"files": [{"path": "src/chat/blocks.py", "add": 18, "del": 4},'
            ' {"path": "src/chat/view.py", "add": 6, "del": 1}], "root": "src/chat"}',
        )
        view.setToolCallResult(
            messageId,
            callId,
            "2 files changed, 24 insertions(+), 5 deletions(-)",
            ok=True,
        )
        self._chat.endAssistantMessage()
        self._note("已注册 patch/edit 渲染器 —— 展开上面那张工具卡看 diff")

    def _demo_unregister(self) -> None:
        """注销渲染器：卡片回落默认的「参数 / 结果」纯文本。"""
        for name in ("patch", "edit"):
            unregisterToolRenderer(name)
        self._renderers_registered = False
        self._note("已注销渲染器（已有卡片不受影响，新建卡片回落纯文本）")

    # ================================================================ 演示 2
    def _demo_permission(self) -> None:
        """工具审批（批准型）：组件画卡 + 发信号，**不阻塞**。

        真实宿主的完整链路是：

        1. 后端要执行 ``edit``，规则评估结果是「需要确认」；
        2. 宿主调 ``view.beginPermission(...)`` 插卡；
        3. 组件发 ``permissionRequested(messageId, requestId)``；
        4. **宿主自己**把后端挂起（可以真等，也可以先记下继续跑别的）；
        5. 用户点按钮 → 组件更新卡片并发 ``permissionReplied(...)``；
        6. **宿主按回复恢复 / 中止后端**。

        「始终允许」的规则持久化也归宿主：``resources`` 里的模式串原样交出，
        怎么匹配、存哪、作用域多大都是产品决策。库不持有任何权限状态。
        """
        view = self._chat.chatView()
        messageId = view.beginMessage("assistant")
        view.beginStep(messageId)
        view.beginPermission(
            messageId,
            ElaChatPermission(
                request_id=f"perm-{messageId}",
                action="edit",
                resources=("src/chat/blocks.py", "src/chat/view.py"),
                detail="@@ -112,7 +112,7 @@\n-    return self._content\n"
                "+    return self._column",
            ),
        )
        self._note("已插入审批卡（不阻塞：组件不会等你的点击）")

    def _demo_question(self) -> None:
        """工具审批（问答型）：**逐题向导**，对齐 opencode 的 question dock。

        问答型与批准型共用同一套信号（``permissionRequested`` /
        ``permissionReplied``），区别只在卡片形态：``questions`` 非空时渲染成
        逐题向导，回复走 ``answer``（``json.dumps({key: str | [str, ...]})``）。

        三点值得注意：

        1. **候选项带 description**。截图级 UI 里每个选项都是两行 —— 只给标题
           逼着用户靠猜，而模型给的选项之间往往差别很微妙。
        2. **多题逐题答**而不是一张长列表（长列表在窄列里很高、要上下扫），
           头部有「N / M 个问题」+ 可点的进度段，每题独立草稿。
        3. **「输入自己的答案」是列表最后一项**（不是独立控件）：点它的标记、点
           整行、按 ``Space`` 是同一件事 —— **选中它 + 展开输入框**，一步就能开始
           输入。单选下它是圆点（radio，再点标记不会取消，要换答案点其它选项）；
           多选下再点标记 = 取消勾选并收起输入框。敲完字直接点「下一步 / 提交」
           或按 ``Ctrl+↵`` 都会**先把这段文字落定**，不会丢。

        键盘：``1``–``9`` 选中对应行、``Space`` 切换（多选）、``↑↓`` 移动焦点、
        ``Ctrl+↵`` 下一步 / 提交、``Alt+←`` 上一步、``Esc`` 忽略。
        """
        view = self._chat.chatView()
        self._chat.sendUserMessage("这批未提交的改动你想怎么处理？")
        messageId = self._chat.beginAssistantMessage()
        view.beginStep(messageId)
        view.beginPermission(
            messageId,
            ElaChatPermission(
                request_id=f"q-{messageId}",
                action="question",
                questions=(
                    ElaChatQuestion(
                        key="q0",
                        header="下一步",
                        question="这次想在 elawidgettools 上做什么？",
                        options=(
                            ElaChatOption(
                                "规划这批未提交改动的收尾",
                                "梳理新增组件、补齐文档与回归测试",
                            ),
                            ElaChatOption(
                                "新增/修改某个具体组件",
                                "你指定组件，我先读代码再给方案",
                            ),
                            ElaChatOption(
                                "修 bug 或做性能优化",
                                "我来定位问题、给最小改动 + 补丁",
                            ),
                        ),
                    ),
                    ElaChatQuestion(
                        key="q1",
                        header="范围",
                        question="哪些目录需要一起看？（可多选）",
                        multiple=True,
                        options=(
                            ElaChatOption("pyqt6_ela_pro/", "组件库本体"),
                            ElaChatOption("tests/", "回归测试（改 API 必须同步）"),
                            ElaChatOption("example/", "示例页（改公开 API 要跟着改）"),
                        ),
                    ),
                    ElaChatQuestion(
                        key="q2",
                        header="补充",
                        question="还有什么要我注意的吗？（没有就跳过）",
                        options=(),
                    ),
                ),
            ),
        )
        self._note(
            "已插入 3 题向导（←→ 切题 / Ctrl+↵ 前进 / Esc 忽略；"
            "「提交」后 answer 是 json）"
        )

    def _on_permission_requested(self, messageId: int, requestId: str) -> None:
        """宿主侧：收到请求 —— **这里才是挂起后端的地方**。"""
        self._note(
            f"宿主收到审批请求 #{requestId}（消息 #{messageId}）"
            f" —— 真实宿主在此挂起后端"
        )

    def _on_permission_replied(
        self, messageId: int, requestId: str, reply: str, answer: str, feedback: str
    ) -> None:
        """宿主侧：收到回复 —— 恢复 / 中止后端，并把 feedback 喂回模型。

        问答型的 ``answer`` 是 ``json.dumps({key: str | [str, ...]})``：单选塌缩成
        标量、多选发整个数组、**未答题整条不进 payload**（不是空串）。宿主按
        ``key`` 对回自己的问题列表即可，不需要理解组件内部怎么组织选项。
        """
        detail = answer or feedback
        self._note(
            f"宿主收到审批回复 #{requestId}：{reply}"
            + (f"（{detail}）" if detail else "")
        )

    # ================================================================ 演示 3
    def _demo_steer(self) -> None:
        """steer 插话：生成中把新指令送进**正在跑的这一轮**。

        与「排队」的区别是时序：排队要等整轮跑完，steer 在**下一个 step 安全
        边界**（``binder.beginRound()`` 里 ``beginStep()`` 之后）就投递 ——
        agent 场景下模型可能连跑十几次工具调用，用户想纠偏却只能干等。

        组件只负责「在同一条助手消息里留一行 ``↳`` 回执 + 发 ``steerReady``」；
        把文本送进后端是宿主的事。回执刻意**不插用户气泡**：助手消息正在流式
        输出，中途冒出一条用户消息视觉上很怪。
        """
        view = self._chat.chatView()
        # 必须是**真正流式中**的一条助手消息：回执行靠
        # ``drainSteer()`` 里的 ``streamingMessageId()`` 找落点
        self._chat.sendUserMessage("看看 blocks.py 的布局")
        messageId = self._chat.beginAssistantMessage()
        view.beginStep(messageId)
        view.beginText(messageId)
        view.appendText(messageId, "我先看看 `blocks.py` 的布局……")
        view.endText(messageId)

        # 入队一条插话，然后手动走一次 step 边界（真实链路里这一步由
        # ElaChatStreamBinder 在 beginRound 之后自动触发）
        steerId = self._chat.steerMessage("等等，先别动 _column")
        self._chat.setSteerEnabled(False)  # 本页手动驱动，关掉自动投递
        view.beginStep(messageId)
        payload = self._chat.drainSteer()
        self._chat.setSteerEnabled(True)
        if payload is not None:
            self._chat.endAssistantMessage()
            self._note(
                f"steer 已投递（{steerId}）—— 宿主收到 steerReady 后"
                f"把 {payload['text']!r} 送进后端"
            )

    def _on_steer_ready(self, payload: dict) -> None:
        """宿主侧：把插话文本送进**正在跑的**那一轮。"""
        self._note(f"steerReady：{payload['text']}")

    # ================================================================ 演示 4
    def _demo_compaction(self) -> None:
        """上下文压缩：**库只做「表达」，不做压缩算法**。

        摘要模板、``SHRINK_STEPS`` 收缩循环、词元估算、transcript 边界全都依赖
        provider 侧能力，不在 UI 库范围。库负责的是「能表达 + 能持久化」——
        时间线上如实出现一条分隔卡，接住流式摘要，随消息一起落库 / 恢复。
        压不压、压哪段、什么时候压，全由宿主决定。
        """
        view = self._chat.chatView()
        messageId = view.beginMessage("assistant")
        partId = view.beginCompaction(messageId, "auto")
        for chunk in (
            "## 目标\n",
            "- 给 patch 加 diff 渲染\n",
            "\n## 下一步\n",
            "- 等审批链路接上\n",
        ):
            view.appendCompactionSummary(messageId, partId, chunk)
        view.endCompaction(messageId, partId, "done", 24)
        self._note("已插入压缩分隔卡（展开看摘要；它不并入正文 text）")

    # ================================================================ 演示 5
    def _demo_cost(self) -> None:
        """成本与上下文占用：数据全由宿主提供，库只给换算规则。

        - ``cost_usd`` 跟着 :class:`ElaChatStats` 走（各步求和 = 整轮汇总），
          tooltip 里显示「花费 $x」；
        - 定价表**不烤进库**（价格会变、还分上下文长度阶梯），换算口径对齐
          opencode：``output`` 与 ``reasoning`` 同价、按输入侧总量选最大的
          满足档、最后除以 1e6；
        - 会话级汇总走 ``view.sessionStats(limit)``（``ElaChatSessionStats``）：
          计数 / 当前上下文四路词元 / 使用率 / 累计成本 / **工具调用统计**
          （``tool_calls`` 次数、``tool_rounds`` 轮数、``tool_counts`` 按名计数、
          失败 / 中止 / 在途分档）/ ``reasoning_ms`` 思考耗时合计，口径对齐
          opencode ``getSessionContext``（取**最后一条有 tokens 的助手消息的
          最后一步**）；把它的 ``total_tokens`` / ``total_cost_usd`` 直接喂
          输入区圆环即可。
        """
        view = self._chat.chatView()
        roundStats = ElaChatStats(
            prompt_tokens=3_000,
            completion_tokens=3_000,
            total_tokens=18_000,
            reasoning_tokens=600,
            cache_read_tokens=12_000,
        )
        roundCost = stats_cost(roundStats, _DEMO_PRICING)

        self._chat.sendUserMessage("这一轮花了多少钱")
        messageId = self._chat.beginAssistantMessage()
        view.beginStep(messageId)
        view.beginText(messageId)
        view.appendText(messageId, "这一轮的用量与花费如下。")
        view.endText(messageId)
        # 一次工具调用：会话统计里会数出「次数 / 轮数 / 按名计数」
        readId = view.addToolCall(messageId, "read", '{"path": "src/app.py"}')
        view.setToolCallResult(messageId, readId, "…文件内容…", ok=True)
        view.setStepStats(
            messageId,
            ElaChatStats(
                prompt_tokens=roundStats.prompt_tokens,
                completion_tokens=roundStats.completion_tokens,
                total_tokens=roundStats.total_tokens,
                reasoning_tokens=roundStats.reasoning_tokens,
                cache_read_tokens=roundStats.cache_read_tokens,
                cost_usd=roundCost,
            ),
        )
        self._chat.endAssistantMessage()

        # 会话级汇总（opencode context 面板同口径）→ 直接喂底部工具栏的圆环
        session = view.sessionStats(_DEMO_WINDOW)
        self._chat.chatInput().setContextUsage(
            session.total_tokens, _DEMO_WINDOW, session.total_cost_usd
        )
        self._note(
            f"本轮 {roundCost} · 当前上下文 {session.total_tokens:,} 词元"
            f"（{session.usage_percent}%）· 会话累计花费 ${session.total_cost_usd:.4f}"
            f" · 工具调用 {session.tool_calls} 次 / {session.tool_rounds} 轮"
            f"（{session.tool_counts}）"
        )

    # ================================================================ 演示 6
    def _demo_retry(self) -> None:
        """手动重试：错误类型单独存字段，错误卡据此决定是否点亮「重试」。

        ``binder.error(errorType, message)`` 原样把类型传给 view（早期实现
        格式化成 ``"[Type] msg"`` 拼进文案，类型就此丢失）。判据是「换次机会
        大概率会成功」：限流 / 超时 / 网络 / 5xx 给按钮；参数错误 / 鉴权失败 /
        内容过滤不给（重试只会再失败一次），但仍给「重新生成」。

        ``retryMessage()`` 与 ``regenerateFrom()`` 的区别是**不删消息** ——
        保留 id 与时间线位置，同参数重发。
        """
        view = self._chat.chatView()
        # 前面必须有一条**用户消息**：`retryMessage()` 找不到前置提问就返回
        # None 且不做任何改动（宁可不重试，也不猜要重发什么）
        self._chat.sendUserMessage("跑一下测试")
        messageId = self._chat.beginAssistantMessage()
        view.beginStep(messageId)
        view.beginText(messageId)
        view.appendText(messageId, "写到一半上游报错了……")
        view.endText(messageId)
        view.setMessageError(messageId, "上游返回 502 Bad Gateway", "ServerError")
        self._chat.setGenerating(False)
        self._note("已插入错误卡（ServerError 可重试 → 展开错误卡点「重试」）")

    def _on_retry_requested(self, messageId: int) -> None:
        """宿主侧：同参数重发。**保留消息位置**，清错误并把状态落成 stopped。"""
        prompt = self._chat.retryMessage(messageId)
        self._note(
            f"重试消息 #{messageId}"
            + (f"（提问：{prompt.text[:16]}…）" if prompt else "")
        )


def _parse(arguments: str) -> dict:
    """容错解析工具参数。

    示例里够用；真宿主直接用 ``chat.renderers.parseToolArguments``（同一份
    实现：非 JSON 纯文本会落成 ``{"": 原文}``，流式半截参数不会整段消失）。
    """
    import json

    try:
        data = json.loads(arguments or "{}")
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}
