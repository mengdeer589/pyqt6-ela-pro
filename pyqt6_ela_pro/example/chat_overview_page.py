"""
[pyqt6_ela_pro] 聊天组件总览页

**一屏看完聊天消息能长什么样**：一条**预填**的完整回合，滚动即读完全貌；
想看动态（推理逐步浮现、工具忙碌环、统计徽标落定）就点「重播流式」。

内容按 opencode 会话 UI 的结构铺：

- 用户消息 + 附件（文件 + 图片）；
- 助手消息：思考块 → 正文（Markdown / 代码 / 公式）→ 每步工具面板
  （``工具调用 (N)``，含一张失败卡）→ 步骤用量徽标 → 脚注「内容由 AI 生成」；
- 底部行：复制 / 重新生成（流式期间整条隐藏，这里已落定所以可见）；
- 第二节是**外观开关**：推理形态、工具分组、统计模式、免责声明、头像形状、
  正文宽度、贴底跟随 —— 全是 ``view`` 上的 setter，改完立刻作用于已有消息。
"""

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout

from pyqt6_ela_pro import ElaButton, ElaDropDownButton
from pyqt6_ela_pro.chat import (
    ElaChatReasoningStyleType,
    ElaChatRoleType,
    ElaChatStats,
)
from PyQt6ElaWidgetTools import ElaCheckBox, ElaIconType, ElaMenu

from .base_page import ExamplePage
from .chat_demo_kit import _ScriptPlayer, note, readonly_chat, replay_section, set_note


#: 下拉的初始选中项（用来给菜单项打勾）
_INITIAL = {
    "推理形态：折叠": ElaChatReasoningStyleType.Collapse,
    "工具：分组": "group",
    "统计：整轮": "footer",
    "头像：圆形": "rounded",
}


class ChatOverviewPage(ExamplePage):
    """聊天消息的完整形态（预填 + 可重播）+ 外观开关。"""

    PAGE_TITLE = "聊天组件总览"

    def __init__(self, parent=None):
        self._chat = None
        self._note = None
        self._player = None
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        main_layout.addWidget(
            note(
                self,
                "本页把一整轮回答预先填好，不用自己造对话就能看全貌；"
                "每节都能「重播流式」，看推理逐步浮现、工具卡忙碌环、"
                "统计徽标落定这些只在过程中可见的效果。",
            )
        )

        box, self._note = replay_section(
            self,
            "01. 一条完整回合（预填 + 可重播）",
            self._script_full_turn,
            self._player_for(),
            self._script_full_turn,
            interval=42,
            hint="点「重播流式」从零走一遍；每一步都是 view 上的公开 API 调用。",
        )
        main_layout.addLayout(box)

        self._chat = readonly_chat(
            self, empty_title="还没有消息", empty_subtitle="点上面「重播流式」看效果"
        )
        main_layout.addWidget(self._chat)
        self._sync_chat_height()

        main_layout.addLayout(self._section_appearance())

        # 页面构造完就有内容（零延迟跑完同一份脚本）
        self._player.play_now(self._script_full_turn())

    # -- 播放与高度 --------------------------------------------------------

    def _player_for(self) -> _ScriptPlayer:
        if self._player is None:
            self._player = _ScriptPlayer(self)
        return self._player

    def resizeEvent(self, event):  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._sync_chat_height()

    def _sync_chat_height(self):
        """总览页要让**底部行与统计徽标**也落在首屏里，所以给足高度。

        头部两行说明 + 外观开关那排控件是固定开销，聊天的份额按剩下的算。
        """
        if self._chat is None:
            return
        target = max(460, self.height() - 300)
        if self._chat.height() == target:
            return
        self._chat.setFixedHeight(target)

    # ================================================================ 01 完整回合
    def _script_full_turn(self):
        """一整轮回答的脚本 —— 每一步都是 ``chatView()`` 上的公开 API。

        这条链路就是 ``ElaChatStreamBinder`` 内部做的事（把后端事件映射到这些
        调用），所以读懂它就等于读懂了 binder。真实接入时不需要自己写这一串，
        但**要知道自己调了哪些东西**。
        """
        view = self._chat.chatView()
        steps = []
        userId = {}

        def add_user():
            userId["id"] = view.addMessage(
                ElaChatRoleType.User,
                "帮我把 `chat/blocks.py` 的工具卡高度收一收，再补一条回归测试。",
            )
            view.addMessageAttachment(
                userId["id"], "blocks.py", "src/chat/blocks.py", 48_120
            )
            view.addMessageAttachment(
                userId["id"], "tool_card.png", "screenshot/tool_card.png", 96_540
            )
            view.setMessageTimestamp(userId["id"], "14:02")
            set_note(
                self._note, "① 用户消息 + 两个附件（点附件名会发 attachmentClicked）"
            )

        def begin_assistant():
            userId["mid"] = view.beginMessage(ElaChatRoleType.Assistant)
            view.setMessageTitle(userId["mid"], "deepseek-v4")
            view.setMessageTimestamp(userId["mid"], "14:02")
            view.beginStep(userId["mid"])
            set_note(self._note, "② beginMessage(Assistant) + beginStep → 第 1 步开始")

        def reason_a():
            view.beginReasoning(userId["mid"])
            view.appendReasoning(userId["mid"], "先量一下现在一张工具卡有多高：")

        def reason_b():
            view.appendReasoning(
                userId["mid"],
                "选项区用 QHBoxLayout(标记 + 两行文字)，"
                "上下各 4px padding，标题 13px + 说明 12px。",
            )

        def reason_end():
            view.endReasoning(userId["mid"], durationMs=1_800)
            set_note(self._note, "③ 思考块落定（折叠形态；可在下面切「内联」）")

        def text_a():
            view.beginText(userId["mid"])
            view.appendText(userId["mid"], "量完了，当前高度是 **43px**。")

        def text_b():
            view.appendText(
                userId["mid"],
                "\n\n压缩方案：把上下 padding 从 4px 收到 3px，"
                "并去掉 `sizeHint` 里写死的下限（那个下限比布局需要高 1px，"
                "累积起来会把整张卡压到比自己的 sizeHint 矮 19px）。\n\n",
            )
            view.appendText(
                userId["mid"],
                "预期降到 **41px**，5 个选项时整张卡少占约 10px。",
            )

        def text_end():
            view.endText(userId["mid"])
            set_note(self._note, "④ 正文段落（Markdown；代码 / 公式 / Mermaid 同理）")

        def step2():
            view.beginStep(userId["mid"])
            set_note(self._note, "⑤ beginStep → 第 2 步（工具面板按步分组）")

        def tool_ok():
            userId["call1"] = view.addToolCall(
                userId["mid"],
                "read_file",
                '{"path": "src/chat/blocks.py"}',
                toolCallId="c1",
            )
            set_note(self._note, "⑥ addToolCall —— 展开看参数与结果")

        def tool_ok_done():
            view.setToolCallResult(
                userId["mid"],
                userId["call1"],
                "1-220 行，共 220 行",
                ok=True,
            )

        def tool_fail():
            userId["call2"] = view.addToolCall(
                userId["mid"],
                "run_tests",
                '{"target": "tests/ela_chat", "filter": "tool_card"}',
                toolCallId="c2",
            )

        def tool_fail_done():
            view.setToolCallResult(
                userId["mid"],
                userId["call2"],
                "收集到 3 条：test_高度锁定 通过；test_组内顺序 通过；"
                "test_错误态 失败（期望 height<=41，实际 43）",
                ok=False,
            )
            set_note(self._note, "⑦ 失败工具卡：展开带错误竖线与结果全文")

        def text3():
            view.beginText(userId["mid"])
            view.appendText(
                userId["mid"],
                "\n\n还差一个用例没写，补上就完。",
            )
            view.endText(userId["mid"])

        def stats():
            view.setStepStats(
                userId["mid"],
                ElaChatStats(
                    prompt_tokens=15_020,
                    completion_tokens=2_940,
                    total_tokens=17_960,
                    ttft_ms=620,
                    tps=35.0,
                    duration_ms=8_400,
                ),
            )
            set_note(
                self._note, "⑧ setStepStats —— 徽标落定（流式期间不摆，结束后才出现）"
            )

        def finish():
            view.setMessageDuration(userId["mid"], 8_400)
            view.endMessage(userId["mid"])
            set_note(self._note, "⑨ endMessage —— 底部行（复制 / 重新生成）此刻才出现")

        steps += [
            (0, add_user),
            (140, begin_assistant),
            (120, reason_a),
            (150, reason_b),
            (200, reason_end),
            (140, text_a),
            (110, text_b),
            (160, text_end),
            (120, step2),
            (110, tool_ok),
            (170, tool_ok_done),
            (140, tool_fail),
            (260, tool_fail_done),
            (150, text3),
            (170, stats),
            (240, finish),
        ]
        return steps

    # ================================================================ 02 外观
    def _section_appearance(self):
        box = QVBoxLayout()
        box.setSpacing(8)
        box.addLayout(self._createHeaderRow("02. 外观开关", self._demo_appearance))
        box.addWidget(
            note(
                self,
                "全部是 chatView() 上的 setter，改完立刻作用于已有消息，"
                "不需要重新生成。注意设置项的值不导出（exportSession 只导出"
                "数据与头像来源），跨话题要靠宿主自己传播。",
            )
        )

        row = QHBoxLayout()
        row.setSpacing(8)

        self._reasoning_button, self._reasoning_actions, self._reasoning_labels = (
            self._dropdown(
                "推理形态：折叠",
                "思考形态",
                (
                    (ElaChatReasoningStyleType.Collapse, "折叠块", "折叠"),
                    (ElaChatReasoningStyleType.Inline, "内联（opencode 风格）", "内联"),
                ),
                self._on_reasoning_style,
            )
        )
        self._grouping_button, self._grouping_actions, self._grouping_labels = (
            self._dropdown(
                "工具：分组",
                "工具面板",
                (
                    ("group", "按步分组", "分组"),
                    ("raw", "逐个平铺", "平铺"),
                ),
                self._on_tool_grouping,
            )
        )
        self._stats_button, self._stats_actions, self._stats_labels = self._dropdown(
            "统计：整轮",
            "用量徽标",
            (
                ("footer", "整轮汇总停靠底部", "整轮"),
                ("steps", "逐步显示", "逐步"),
                ("none", "不显示", "不显示"),
            ),
            self._on_stats_mode,
        )
        self._avatar_button, self._avatar_actions, self._avatar_labels = self._dropdown(
            "头像：圆形",
            "头像",
            (
                ("rounded", "圆形", "圆形"),
                ("square", "方形", "方形"),
            ),
            self._on_avatar_shape,
        )
        for widget in (
            self._reasoning_button,
            self._grouping_button,
            self._stats_button,
            self._avatar_button,
        ):
            row.addWidget(widget)

        row.addWidget(self._toggle("免责声明", True, self._on_disclaimer))
        row.addWidget(self._toggle("复制提示", True, self._on_copy_notification))
        row.addWidget(self._toggle("贴底跟随", True, self._on_stick))
        row.addWidget(self._button("正文限宽 720", self._on_content_width))
        row.addStretch()
        box.addLayout(row)
        return box

    def _demo_appearance(self) -> None:
        """外观：推理形态 / 工具分组 / 统计模式 / 免责声明 / 复制提示 / 头像形状 / 正文限宽。

        对应 API：``setReasoningStyle`` / ``setToolGrouping`` / ``setStatsMode`` /
        ``setDisclaimer`` + ``setDisclaimerVisible`` / ``setCopyNotificationEnabled`` /
        ``setAvatarShape`` / ``setContentMaxWidth`` / ``setStickToBottom``。

        两条约定：

        - 这几个 setter 都**立即重建**已有消息的对应区块，不丢内容；
        - 「思考行」与「工具面板标题」用**同一个**纯文本色，不叠强调色 ——
          叠出来的差异在浅色下明显、在深色下几乎读不出，两头不讨好。
        """
        view = self._chat.chatView()
        view.setReasoningStyle(ElaChatReasoningStyleType.Inline)
        view.setToolGrouping(True)
        view.setStatsMode("footer")
        view.setCopyNotificationEnabled(True)
        view.setAvatarShape("rounded")
        view.setContentMaxWidth(720)
        view.setStickToBottom(True)

    # -- 外观回调 ----------------------------------------------------------

    def _dropdown(self, label, tip, choices, callback):
        """下拉：选中即调 ``callback(value)``。

        ``choices`` 是 ``(值, 菜单文案, 按钮短文案)``；返回
        ``(按钮, {值: action}, {值: 短文案})``。返回 actions 是必需的：
        **checkable 项自己没有互斥** —— 点已选项会取消勾选，点另一项两项同时
        勾上。回调必须拿它做全量 ``setChecked`` 同步（见 :func:`_select`），
        只改 view 与按钮文案的话菜单勾选态会一直错。
        """
        button = ElaDropDownButton(label, ElaIconType.IconName.Sliders, parent=self)
        button.setFixedHeight(28)
        button.setToolTip(tip)
        menu = ElaMenu(self)
        menu.setMenuItemHeight(28)
        actions = {}
        labels = {}
        for value, text, short in choices:
            action = menu.addElaIconAction(ElaIconType.IconName.Sliders, text)
            action.setCheckable(True)
            action.setChecked(value == _INITIAL[label])
            action.triggered.connect(lambda _checked=False, v=value, c=callback: c(v))
            actions[value] = action
            labels[value] = short
        button.setMenu(menu)
        return button, actions, labels

    def _toggle(self, text, checked, callback):
        """ElaCheckBox 走 Qt 标准 ``setChecked``（**没有** ``setIsToggled``）。"""
        box = ElaCheckBox(text, self)
        box.setChecked(bool(checked))
        box.toggled.connect(callback)
        return box

    def _button(self, text, callback):
        button = ElaButton(text, variant="outlined", size="small", parent=self)
        button.clicked.connect(callback)
        return button

    def _on_reasoning_style(self, value: str):
        self._chat.chatView().setReasoningStyle(value)
        _select(
            self._reasoning_button,
            "推理形态",
            self._reasoning_actions,
            self._reasoning_labels,
            value,
        )

    def _on_tool_grouping(self, value: str):
        self._chat.chatView().setToolGrouping(value == "group")
        _select(
            self._grouping_button,
            "工具",
            self._grouping_actions,
            self._grouping_labels,
            value,
        )

    def _on_stats_mode(self, value: str):
        self._chat.chatView().setStatsMode(value)
        _select(
            self._stats_button,
            "统计",
            self._stats_actions,
            self._stats_labels,
            value,
        )

    def _on_avatar_shape(self, value: str):
        self._chat.chatView().setAvatarShape(value)
        _select(
            self._avatar_button,
            "头像",
            self._avatar_actions,
            self._avatar_labels,
            value,
        )

    def _on_disclaimer(self, checked: bool):
        self._chat.chatView().setDisclaimerVisible(bool(checked))

    def _on_copy_notification(self, checked: bool):
        self._chat.chatView().setCopyNotificationEnabled(bool(checked))

    def _on_stick(self, checked: bool):
        self._chat.chatView().setStickToBottom(bool(checked))

    def _on_content_width(self):
        view = self._chat.chatView()
        current = view.contentMaxWidth()
        target = 0 if current else 720
        view.setContentMaxWidth(target)
        self._note.setText(
            f"setContentMaxWidth({target}) —— 限的是整列（正文 + 附件条 + 底部行），"
            "不限时行为完全不变；0 = 不限。"
        )


def _select(button, prefix, actions, labels, value) -> None:
    """全量同步勾选态 + 按钮文案。

    checkable 项没有互斥（再点已选项会取消勾选、点另一项会两项同时勾上），
    每次选择都必须把所有项重刷一遍。
    """
    for item, action in actions.items():
        action.setChecked(item == value)
    text = f"{prefix}：{labels.get(value, value)}"
    button.setText(text)
    button.setToolTip(text)
