"""
[pyqt6_ela_pro] 持久化与性能页

这一页把「回合记成事件流重放」与「大消息量的三条开关」**变成能跑的演示** ——
此前它们只在 API 指南里有代码，读者看不到实际效果。

三节：

1. **回合日志（``ElaChatTurnJournal``）** —— 把一轮回答记成**追加写事件流**，
   一行一条 JSON。三条设计：① ``_push`` 记事件的同时 ``_apply`` 它（记录与
   重放共用一条路径，``message()`` 随时给「已收到的部分」）；② 浮点在**记录端**
   就洗掉；③ ``loadsLine`` 对截断 / 非法 JSON 返回 ``None``，``fromLines`` 跳过
   未知事件。本页把同一轮回答分别「实时跑一遍」与「从日志重放一遍」并排显示，
   可以直接看出两者是否一致。
2. **会话导出 / 导入** —— ``view.exportSession()`` / ``importSession()`` /
   ``addMessageFromDict()`` / ``restoreMessages(preserveIds=True)``。
   ``preserveIds=True`` 会**先全量校验再写入**，一条不落（撞 id 直接抛
   ``ValueError``，不静默重号）。
3. **大消息量三条开关** —— 交互 resize 延迟重排、历史加载 ``beginBatch``、
   视口外消息挂起重型查看器。

「会话管理」（多话题 UI）在上一节那一页。
"""

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout

from pyqt6_ela_pro import ElaButton
from pyqt6_ela_pro.chat import (
    ElaChatRoleType,
    ElaChatSessionInfo,
    ElaChatStats,
    ElaChatTurnJournal,
)

from .base_page import ExamplePage
from .chat_demo_kit import _ScriptPlayer, note, readonly_chat

#: 这一轮的提问（journal 只记**助手**那条，用户那条由宿主自己存）
_PROMPT = "把这次压缩的判据写清楚"


class ChatPersistPage(ExamplePage):
    """持久化（回合日志 / 会话导入导出）与大消息量性能开关。"""

    PAGE_TITLE = "持久化与性能"

    def __init__(self, parent=None):
        self._chat = None
        self._player = None
        self._journal = None
        self._notes: dict = {}
        self._titles: dict = {}
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        main_layout.addWidget(
            note(
                self,
                "这一页把「回合记成事件流重放」与「大消息量三条开关」做成能跑的演示。"
                "上面是对照区：左边实时跑一轮，右边从日志重放同一轮 —— 两边应该"
                "长得一模一样（重放与实时共用同一条 apply 路径）。",
            )
        )

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addLayout(self._column("实时", "live"))
        row.addLayout(self._column("从日志重放", "replay"))
        main_layout.addLayout(row)

        self._chat = readonly_chat(self, empty_title="还没有消息")
        main_layout.addWidget(self._chat)
        self._sync_chat_height()

        for section in (
            self._section_journal(),
            self._section_session(),
            self._section_perf(),
        ):
            main_layout.addLayout(section)

        self._run_round()

    # -- 对照区 ------------------------------------------------------------

    def _column(self, title, key):
        box = QVBoxLayout()
        box.setSpacing(4)
        self._titles[key] = title
        self._notes[key] = note(self, f"{title}：—")
        box.addWidget(self._notes[key])
        return box

    def _say(self, key, text):
        """更新某一节的说明行。

        前缀取自 ``self._titles``（固定标题），**不能拿当前文本切前缀** ——
        说明文字里没有冒号时切出来还是整段，于是每次追加都把上一条又带一遍。
        """
        label = self._notes.get(key)
        if label is not None:
            label.setText(f"{self._titles.get(key, '')}：{text}")

    def _player_for(self) -> _ScriptPlayer:
        if self._player is None:
            self._player = _ScriptPlayer(self)
        return self._player

    def resizeEvent(self, event):  # noqa: N802 (Qt  name)
        super().resizeEvent(event)
        self._sync_chat_height()

    def _sync_chat_height(self):
        if self._chat is None:
            return
        target = max(320, self.height() - 560)
        if self._chat.height() == target:
            return
        self._chat.setFixedHeight(target)

    # ================================================================ 一轮
    def _run_round(self):
        """跑一轮**带日志**的回答：左边实时显示，右边留待重放。

        走 widget 层入口（``sendUserMessage`` + ``beginAssistantMessage``），
        别直接 ``view.beginMessage`` —— 否则 widget 不知道当前流式消息是哪条，
        底部行 / 贴底 / 生成态都不工作。
        """
        self._chat.sendUserMessage(_PROMPT)
        messageId = self._chat.beginAssistantMessage()
        self._journal = ElaChatTurnJournal()
        self._journal.begin(messageId)
        self._journal.setTitle("deepseek-v4")

        view = self._chat.chatView()
        view.beginStep(messageId)
        self._journal.beginStep()

        view.beginReasoning(messageId)
        view.appendReasoning(messageId, "先确认 historyCount 缺省 0 的含义。")
        view.appendReasoning(messageId, "是「不知道」，不是「压了 0 条」。")
        self._journal.reasoning("先确认 historyCount 缺省 0 的含义。")
        self._journal.reasoning("是「不知道」，不是「压了 0 条」。")
        view.endReasoning(messageId, durationMs=900)
        self._journal.endReasoning(900)

        view.beginText(messageId)
        view.appendText(messageId, "缺省 0 要写「已压缩历史」，不能写「0 条」——")
        view.appendText(messageId, "后者是在说谎。")
        view.endText(messageId)
        self._journal.text("缺省 0 要写「已压缩历史」，不能写「0 条」——")
        self._journal.text("后者是在说谎。")
        self._journal.endText()

        callId = view.addToolCall(
            messageId, "grep", '{"pattern": "historyCount"}', toolCallId="g1"
        )
        view.setToolCallResult(messageId, callId, "3 处命中", ok=True)
        self._journal.toolStart("g1", "grep", '{"pattern": "historyCount"}')
        self._journal.toolEnd("g1", "3 处命中", True)

        view.setStepStats(
            messageId,
            ElaChatStats(
                prompt_tokens=1_200,
                completion_tokens=180,
                total_tokens=1_380,
            ),
        )
        self._journal.stats(
            ElaChatStats(
                prompt_tokens=1_200,
                completion_tokens=180,
                total_tokens=1_380,
            )
        )

        view.setMessageDuration(messageId, 2_600)
        self._journal.setDuration(2_600)
        self._chat.endAssistantMessage()
        self._journal.end()
        self._say("live", f"{len(self._journal.events())} 条事件已记录")

    # ================================================================ 01 日志
    def _section_journal(self):
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addLayout(self._createHeaderRow("01. 回合日志与重放", self._demo_journal))
        label = note(
            self,
            "同一轮回答有两条路径：实时（_push 记事件的同时 _apply 它）与"
            "重放（fromLines 逐条 replay）。因为共用一条 apply 路径，"
            "逐像素应当一致。",
        )
        self._notes["journal"] = label
        box.addWidget(label)

        row = QHBoxLayout()
        row.setSpacing(8)
        for text, callback in (
            ("重放到上面的会话", self._on_replay),
            ("看 dumps() 前 3 行", self._on_dump_head),
            ("塞一行截断的脏数据", self._on_corrupt_line),
            ("统计事件数", self._on_count_events),
        ):
            button = ElaButton(text, variant="outlined", size="small", parent=self)
            button.clicked.connect(self._fire(label, callback))
            row.addWidget(button)
        row.addStretch()
        box.addLayout(row)
        return box

    def _demo_journal(self) -> None:
        """``ElaChatTurnJournal``：把一轮回答记成**追加写事件流**。

        - **记录与重放共用一条路径**：``_push`` 记下事件的同时就 ``_apply`` 它，
          所以 ``message()`` 随时能给出「已收到的部分」，而不是等回合结束；
        - 浮点在**记录端**洗掉（``_float``）—— 事后清洗就来不及，
          ``NaN`` / ``inf`` 会破坏 ``allow_nan=False`` 的 JSON 输出；
        - ``loadsLine`` 对截断 / 非法 JSON 返回 ``None``，``fromLines`` 跳过
          未知事件、``settleOpen=True`` 结算残留（未完成工具 → ``Aborted``，
          出错回合 → ``Error``）。

        失败工具的 ``part.status`` 保持 ``Done``，失败只由
        ``tool_call.status`` 承载 —— journal 必须照抄这条。
        """
        journal = ElaChatTurnJournal(messageId=self._chat.beginAssistantMessage())
        journal.text("增量分片")
        journal.end("done")
        lines = journal.dumps().splitlines()  # 一行一条，可直接落盘
        recovered = ElaChatTurnJournal.fromLines(lines)
        return recovered.message()

    def _on_replay(self):
        if self._journal is None:
            self._say("journal", "还没有记录，先跑一轮")
            return
        view = self._chat.chatView()
        lines = self._journal.dumps().splitlines()  # dumps() 是一个字符串，一行一条
        journal = ElaChatTurnJournal.fromLines(lines)
        # **先清空**：journal 里记的是**当时的 messageId**，直接重放会和
        # 现有的那条撞 id（addMessageFromDict 抛 ValueError）。这正好也是
        # 崩溃恢复的真实场景 —— 进程重启后本来就没有旧消息。
        view.clear()
        self._chat.sendUserMessage(_PROMPT)  # 用户那条不在 journal 里
        journal.replayInto(view)
        self._chat.setGenerating(False)
        self._say(
            "journal",
            f"清空后重放 {len(lines)} 行事件，"
            f"还原 {view.count()} 条消息（id 与实时那轮一致）",
        )

    def _on_dump_head(self):
        if self._journal is None:
            self._say("journal", "还没有记录")
            return
        head = self._journal.dumps().splitlines()[:3]
        self._say(
            "journal", "dumps() 前 3 行：" + " | ".join(line[:46] for line in head)
        )

    def _on_corrupt_line(self):
        """脏数据容错：截断的一行 + 一行未知事件，都不该让整条日志废掉。"""
        if self._journal is None:
            self._say("journal", "还没有记录")
            return
        lines = self._journal.dumps().splitlines()
        lines.append(lines[-1][: len(lines[-1]) // 2])  # 截断
        lines.append('{"t":"完全未知的未来事件"}')  # 未知事件
        journal = ElaChatTurnJournal.fromLines(lines)
        message = journal.message()
        self._say(
            "journal",
            f"塞了 2 行脏数据仍还原出完整消息："
            f"{len(message.tool_calls)} 个工具调用 / status={message.status}"
            f"（loadsLine 对脏行返 None，fromLines 跳过未知事件）",
        )

    def _on_count_events(self):
        if self._journal is None:
            self._say("journal", "还没有记录")
            return
        self._say("journal", f"{len(self._journal.events())} 条事件（dumps 一行一条）")

    # ================================================================ 02 会话
    def _section_session(self):
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addLayout(self._createHeaderRow("02. 会话导出 / 导入", self._demo_session))
        label = note(
            self,
            "消息 / part / tool_call / stats / attachment 都有成对的 "
            "toDict / fromDict，产物是纯 JSON 类型（allow_nan=False 可写）。",
        )
        self._notes["session"] = label
        box.addWidget(label)

        row = QHBoxLayout()
        row.setSpacing(8)
        for text, callback in (
            ("exportSession", self._on_export),
            ("importSession 追加", self._on_import),
            ("restoreMessages 保 id", self._on_restore),
        ):
            button = ElaButton(text, variant="outlined", size="small", parent=self)
            button.clicked.connect(self._fire(label, callback))
            row.addWidget(button)
        row.addStretch()
        box.addLayout(row)
        return box

    def _demo_session(self) -> None:
        """整会话导出 / 导入，以及按条恢复。

        - ``exportSession(session, extra)`` / ``importSession(bundle, clear=)``：
          bundle = 会话元数据 + ``messages`` + ``view`` 外观段（**头像来源与
          主题不导出**）。``clear=True`` 清空后按**原 id** 恢复，
          ``clear=False`` 追加且重新分配 id；
        - ``restoreMessages(items, preserveIds=True)`` —— **先全量校验再写入**，
          一条不落：撞 id 直接抛 ``ValueError``，不静默重号（静默重号会让迟到的
          事件命中另一条消息，是极难查的串号 bug）；
        - ``addMessageFromDict(data, messageId=)`` 单条恢复，沿用存储 id。

        助手消息的派生字段（``text`` / ``reasoning`` / ``tool_calls`` /
        ``stats``）**不信存储值**，一律由 ``withParts()`` 重算 —— 否则版本升级
        改了派生规则，旧数据会显示成旧格式。
        """
        view = self._chat.chatView()
        bundle = view.exportSession(ElaChatSessionInfo(id="s1", title="话题"))
        view.importSession(bundle)  # clear=True：先清空，再按原 id 恢复
        view.restoreMessages(bundle["messages"], preserveIds=True)

    def _on_export(self):
        view = self._chat.chatView()
        bundle = view.exportSession(
            ElaChatSessionInfo(id="s1", title="压缩判据"),
            extra={"note": "示例 extra 段"},
        )
        self._bundle = bundle
        self._say(
            "session",
            f"导出 {len(bundle.get('messages', []))} 条消息 + 会话元数据 + 外观段",
        )

    def _on_import(self):
        if not hasattr(self, "_bundle"):
            self._on_export()
        before = self._chat.chatView().count()
        self._chat.chatView().importSession(self._bundle, clear=False)
        self._say(
            "session",
            f"importSession(clear=False) 追加：{before} → "
            f"{self._chat.chatView().count()} 条（追加时重新分配 id）",
        )

    def _on_restore(self):
        if not hasattr(self, "_bundle"):
            self._on_export()
        items = self._bundle.get("messages", [])
        view = self._chat.chatView()
        ids = [m.get("id") for m in items if m.get("id") is not None]
        view.clear()
        try:
            view.restoreMessages(items, preserveIds=True)
            self._say(
                "session",
                f"clear + restoreMessages(preserveIds=True) 恢复 {len(ids)} 条"
                f"，原 id {ids} 保留",
            )
        except ValueError as exc:
            self._say("session", f"撞 id 了，直接抛错而不是静默重号：{exc}")

    # ================================================================ 03 性能
    def _section_perf(self):
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addLayout(self._createHeaderRow("03. 大消息量的三条开关", self._demo_perf))
        label = note(
            self,
            "30 条消息起步，看延迟重排 / 批量加载 / 视口挂起三个开关的效果。",
        )
        self._notes["perf"] = label
        box.addWidget(label)

        row = QHBoxLayout()
        row.setSpacing(8)
        for text, callback in (
            ("追加 30 条", self._on_load_30),
            ("延迟重排 开/关", self._on_toggle_reflow),
            ("批量加载 begin/endBatch", self._on_batch),
            ("视口挂起 开/关", self._on_toggle_suspend),
        ):
            button = ElaButton(text, variant="outlined", size="small", parent=self)
            button.clicked.connect(self._fire(label, callback))
            row.addWidget(button)
        row.addStretch()
        box.addLayout(row)
        return box

    def _demo_perf(self) -> None:
        """三条开关分别解决什么：

        1. **交互 resize 默认延迟重排**（阈值 50 条 / 延迟 120ms）——
           拖窗口时每来一条消息就重排一次会明显卡；
        2. **历史加载用 ``beginBatch()`` / ``endBatch()``** —— 骨架先建 + 时间片
           渐进渲染，排空发 ``batchRenderFinished``。**延迟期间 ``parts`` 是空的**，
           读内容的代码要能扛住；
        3. **视口外消息默认挂起重型查看器**（``setViewportSuspension``）——
           挂起时 ``bubble.markdownViewer()`` 返回 ``None``，数据要用
           ``message()`` 的快照读。
        """
        view = self._chat.chatView()
        view.setResizeReflowDeferred(True, minMessages=50, delayMs=120)
        view.beginBatch()
        rows = [message.toDict() for message in view.messages()]
        for row in rows:
            view.addMessageFromDict(row)
        view.endBatch()
        view.setViewportSuspension(True)

    def _on_load_30(self):
        view = self._chat.chatView()
        for index in range(30):
            view.addMessage(ElaChatRoleType.User, f"历史消息 {index + 1}")
        view.scrollToBottom()
        self._say("perf", f"已追加 30 条，当前 {view.count()} 条")

    def _on_toggle_reflow(self):
        view = self._chat.chatView()
        target = not view.resizeReflowDeferred()
        view.setResizeReflowDeferred(target)
        self._say(
            "perf",
            f"setResizeReflowDeferred({target}) —— 默认就是开"
            "（交互 resize 延迟重排，阈值 50 条 / 延迟 120ms 可调），"
            "点一下是关掉",
        )

    def _on_batch(self):
        view = self._chat.chatView()
        if view.isBatchActive():
            view.endBatch()
            self._say("perf", "endBatch —— 排空后会发 batchRenderFinished")
            return
        view.beginBatch()
        for index in range(20):
            view.addMessage(ElaChatRoleType.User, f"批量消息 {index + 1}")
        view.endBatch()
        self._say("perf", "beginBatch + 20 条 + endBatch（骨架先建，再渐进渲染）")

    def _on_toggle_suspend(self):
        view = self._chat.chatView()
        target = not view.viewportSuspension()
        view.setViewportSuspension(target)
        self._say(
            "perf",
            f"setViewportSuspension({target}) —— 默认也是开："
            "视口外消息挂起重型查看器，挂起时 bubble.markdownViewer() 返回 None",
        )

    # ---------------------------------------------------------------- 工具
    def _fire(self, label, callback):
        def run():
            self._active_note = label
            try:
                callback()
            except Exception:
                import traceback

                traceback.print_exc()

        return run

    def _button(self, text, callback):
        button = ElaButton(text, variant="outlined", size="small", parent=self)
        button.clicked.connect(callback)
        return button
