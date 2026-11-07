"""[pyqt6_ela_pro] 划词助手示例页面。"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaCheckBox,
    ElaComboBox,
    ElaIconType,
    ElaPlainTextEdit,
    ElaText,
    ElaToggleSwitch,
)

from pyqt6_ela_pro import (
    ElaButton,
    ElaMenuItem,
    ElaSelectionAssistant,
    ElaSelectionResultDialog,
)

from .base_page import ExamplePage

_MAX_LOG_LINES = 200

_FAKE_REPLIES = {
    "translate": (
        "## 翻译\n\n",
        "**Hello world** 译作「你好，世界」。\n\n",
        "```text\n你好，世界\n```\n\n",
        "- 语气：中性\n- 场合：正式\n",
    ),
    "explain": (
        "## 这段话在说什么\n\n",
        "它先给结论，再用一个**代码块**举例，",
        "最后用列表补充两个使用场合。\n\n",
        "> 结构是「结论 → 例证 → 补充」\n",
    ),
    "summary": (
        "## 一句话总结\n\n",
        "作者主张**先给结论**，再补论据。\n",
    ),
}


class SelectionAssistantPage(ExamplePage):
    """划词助手：全局划词监听、动作条与事件演示。"""

    PAGE_TITLE = "[ela_ext] 划词助手"

    assistantStateChanged = pyqtSignal(bool)

    def _addDemoContent(self, main_layout):
        self._assistant = None
        self._action_boxes = {}
        self._demo_actions = ()
        self._log = None
        self._updating_switch = False
        self._result_dialog = None
        self._start_action = None

        main_layout.addLayout(
            self._createHeaderRow("01. 启用与参数", self._demoSettings)
        )
        self._demoSettings(main_layout)

        main_layout.addLayout(
            self._createHeaderRow("02. 动作配置（纯信号）", self._demoActions)
        )
        self._demoActions(main_layout)

        main_layout.addLayout(
            self._createHeaderRow("03. 事件日志与宿主实现", self._demoEvents)
        )
        self._demoEvents(main_layout)

        main_layout.addLayout(
            self._createHeaderRow("04. 结果对话框（流式）", self._demoResultDialog)
        )
        self._demoResultDialog(main_layout)

    def _demoSettings(self, main_layout):
        info = ElaText(
            "在任意应用拖选文本（或双击选词），动作条会出现在光标附近；"
            "取词通过模拟 Ctrl+C 完成，默认会恢复原剪贴板。"
            "文字+图片混选只取文字，纯图片选区不弹窗；"
            "助手不拦截键盘，用户自己的 Ctrl+C / Ctrl+V 不受影响。",
            self,
        )
        info.setTextPixelSize(14)
        main_layout.addWidget(info)

        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        enable_label = ElaText("启用", row)
        enable_label.setTextPixelSize(14)
        layout.addWidget(enable_label)
        self._enable_switch = ElaToggleSwitch(row)
        self._enable_switch.toggled.connect(self._on_enable_toggled)
        layout.addWidget(self._enable_switch)
        layout.addSpacing(12)

        compact_label = ElaText("紧凑模式", row)
        compact_label.setTextPixelSize(14)
        layout.addWidget(compact_label)
        self._compact_switch = ElaToggleSwitch(row)
        self._compact_switch.toggled.connect(self._on_compact_toggled)
        layout.addWidget(self._compact_switch)
        layout.addSpacing(12)

        restore_label = ElaText("恢复剪贴板", row)
        restore_label.setTextPixelSize(14)
        layout.addWidget(restore_label)
        self._restore_switch = ElaToggleSwitch(row)
        self._restore_switch.setIsToggled(True)
        self._restore_switch.toggled.connect(self._on_restore_toggled)
        layout.addWidget(self._restore_switch)
        layout.addSpacing(12)

        length_label = ElaText("最小长度", row)
        length_label.setTextPixelSize(14)
        layout.addWidget(length_label)
        self._length_combo = ElaComboBox(row)
        for value in (1, 2, 3, 5):
            self._length_combo.addItem(f"{value} 个字符", value)
        self._length_combo.currentIndexChanged.connect(self._on_length_changed)
        layout.addWidget(self._length_combo)
        layout.addSpacing(12)

        scope_label = ElaText("拖选取词", row)
        scope_label.setTextPixelSize(14)
        layout.addWidget(scope_label)
        self._scope_combo = ElaComboBox(row)
        self._scope_combo.addItem("内置过滤器（推荐）", "builtin")
        self._scope_combo.addItem("仅双击选词", "off")
        self._scope_combo.addItem("不限制（会向任意应用注入）", "all")
        self._scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        layout.addWidget(self._scope_combo)
        layout.addStretch(1)

        self._manual_button = ElaButton(
            "手动弹出动作条", variant="outlined", size="small", parent=row
        )
        self._manual_button.clicked.connect(self._on_manual_show)
        layout.addWidget(self._manual_button)
        main_layout.addWidget(row)

    def _on_enable_toggled(self, checked: bool) -> None:
        if self._updating_switch:
            return
        self._log_line(f"启用划词助手：{checked}")
        assistant = self._ensure_assistant()
        if checked and not assistant.setEnabled(True):
            self._updating_switch = True
            self._enable_switch.setIsToggled(False)
            self._updating_switch = False
            self._log_line("启用失败：请查看错误日志（非 Windows 或钩子安装失败）")
            return
        assistant.setEnabled(checked)

    def isAssistantEnabled(self) -> bool:
        """助手当前是否启用（**不会**顺带创建助手，供外部入口读状态用）。"""
        return bool(self._assistant is not None and self._assistant.isEnabled())

    def toggleAssistantFromTray(self) -> bool:
        """供托盘菜单等外部入口调用的开关入口（与页面内开关双向同步）。

        :returns: 切换后的实际状态；失败为 ``False``，此时页面开关已回滚。
        """
        assistant = self._ensure_assistant()
        target = not assistant.isEnabled()
        # 复用开关那条路径，保证失败回滚与日志只写一处
        self._updating_switch = True
        try:
            self._enable_switch.setIsToggled(target)
        finally:
            self._updating_switch = False
        if self._enable_switch.getIsToggled() == target:
            self._on_enable_toggled(target)
        return self.isAssistantEnabled()

    def _on_compact_toggled(self, checked: bool) -> None:
        if self._assistant is not None:
            self._assistant.popup().setCompactMode(checked)
        self._log_line(f"紧凑模式：{checked}")

    def _on_restore_toggled(self, checked: bool) -> None:
        if self._assistant is not None:
            self._assistant.capture().setRestoreClipboard(checked)
        self._log_line(f"恢复剪贴板：{checked}")

    def _on_length_changed(self, _index: int) -> None:
        length = self._length_combo.currentData() or 1
        if self._assistant is not None:
            self._assistant.setMinSelectionLength(int(length))
        self._log_line(f"最小长度：{length}")

    def _apply_scope(self, assistant: ElaSelectionAssistant) -> None:
        """按「拖选取词」下拉框配置取词闸门。"""
        scope = self._scope_combo.currentData() or "builtin"
        if scope == "all":
            assistant.setCaptureFilter(None)
            assistant.setRequireFilterForDrag(False)
        elif scope == "off":
            assistant.setCaptureFilter(None)
            assistant.setRequireFilterForDrag(True)
        else:
            assistant.setCaptureFilter(ElaSelectionAssistant.builtinDragFilter())
            assistant.setRequireFilterForDrag(True)

    def _on_scope_changed(self, _index: int) -> None:
        scope = self._scope_combo.currentData() or "builtin"
        if self._assistant is not None:
            self._apply_scope(self._assistant)
        hint = {
            "builtin": "拖选仅在同窗口、非边框、短距离时取词",
            "off": "仅双击选词（不注入拖选那条 Ctrl+C）",
            "all": "不限制：任意拖选都会向前台注入 Ctrl+C",
        }[scope]
        self._log_line(f"拖选取词：{hint}")

    def _on_manual_show(self) -> None:
        assistant = self._ensure_assistant()
        assistant.showFor("这是手动弹出的示例文本", QCursor.pos())
        self._log_line("手动弹出动作条（不经全局钩子）")

    def _demoActions(self, main_layout):
        """动作条菜单项由宿主定义（示例：6 个动作；组件本身不内置）。"""
        self._demo_actions = (
            ElaMenuItem(id="copy", label="复制", icon=ElaIconType.IconName.Copy),
            ElaMenuItem(
                id="translate", label="翻译", icon=ElaIconType.IconName.Language
            ),
            ElaMenuItem(
                id="explain", label="解释", icon=ElaIconType.IconName.CommentQuestion
            ),
            ElaMenuItem(
                id="summary", label="总结", icon=ElaIconType.IconName.FileLines
            ),
            ElaMenuItem(
                id="search", label="搜索", icon=ElaIconType.IconName.MagnifyingGlass
            ),
            ElaMenuItem(id="quote", label="引用", icon=ElaIconType.IconName.QuoteLeft),
        )

        info = ElaText(
            "菜单项完全由宿主定义（下面每组「名称 + id + 图标」就是一个菜单项），"
            "动作条只发 actionTriggered(actionId, text, pos) 信号，"
            "复制 / 搜索 / 翻译等行为全部由宿主实现（本页演示 copy）。",
            self,
        )
        info.setTextPixelSize(14)
        main_layout.addWidget(info)

        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        for action in self._demo_actions:
            box = ElaCheckBox(f"{action.label}（{action.id}）", row)
            box.setChecked(action.enabled)
            box.stateChanged.connect(self._on_action_toggled)
            self._action_boxes[action.id] = box
            layout.addWidget(box)
        layout.addStretch(1)
        main_layout.addWidget(row)

    def _on_action_toggled(self, _state: int) -> None:
        if self._assistant is not None:
            self._apply_actions()
        enabled = [key for key, box in self._action_boxes.items() if box.isChecked()]
        self._log_line(f"动作列表更新：{', '.join(enabled) or '（空）'}")

    def _apply_actions(self) -> None:
        actions = [
            ElaMenuItem(
                id=action.id,
                label=action.label,
                icon=action.icon,
                tooltip=action.tooltip,
                enabled=self._action_boxes[action.id].isChecked(),
            )
            for action in self._demo_actions
        ]
        self._assistant.setActions(actions)

    def _demoEvents(self, main_layout):
        info = ElaText(
            "selectionCaptured / actionTriggered / popupShown / popupHidden / "
            "errorOccurred 信号都会记录在下方；宿主实现示例：copy 动作写剪贴板。",
            self,
        )
        info.setTextPixelSize(14)
        main_layout.addWidget(info)

        self._log = ElaPlainTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(180)
        self._log.setPlaceholderText("事件日志…")
        main_layout.addWidget(self._log)

        clear_row = QWidget(self)
        clear_layout = QHBoxLayout(clear_row)
        clear_layout.setContentsMargins(0, 0, 0, 0)
        clear_layout.addStretch(1)
        clear_btn = ElaButton(
            "清空日志", variant="text", size="small", parent=clear_row
        )
        clear_btn.clicked.connect(lambda: self._log.clear())
        clear_layout.addWidget(clear_btn)
        main_layout.addWidget(clear_row)
        self._log_line("就绪：勾选「启用」后可在任意应用划词")

    def _ensure_assistant(self) -> ElaSelectionAssistant:
        if self._assistant is None:
            assistant = ElaSelectionAssistant(self)
            assistant.selectionCaptured.connect(self._on_selection_captured)
            assistant.actionTriggered.connect(self._on_action_triggered)
            assistant.popupShown.connect(self._on_popup_shown)
            assistant.popupHidden.connect(lambda: self._log_line("popupHidden"))
            assistant.errorOccurred.connect(self._on_error)
            assistant.captureBlocked.connect(
                lambda reason: self._log_line(f"captureBlocked：{reason}")
            )
            assistant.popup().setCompactMode(self._compact_switch.getIsToggled())
            assistant.capture().setRestoreClipboard(self._restore_switch.getIsToggled())
            assistant.setMinSelectionLength(int(self._length_combo.currentData() or 1))
            assistant.enabledChanged.connect(self._on_assistant_state_changed)
            self._assistant = assistant
            self._apply_scope(assistant)
            self._apply_actions()
        return self._assistant

    def _on_assistant_state_changed(self, enabled: bool) -> None:
        self.assistantStateChanged.emit(bool(enabled))

    def _on_selection_captured(self, text: str, pos) -> None:
        preview = text.strip().replace("\n", " ")[:40]
        self._log_line(f"selectionCaptured：{preview!r} @ ({pos.x()}, {pos.y()})")

    def _on_popup_shown(self, text: str, pos) -> None:
        self._log_line(f"popupShown：{len(text)} 字 @ ({pos.x()}, {pos.y()})")

    def _on_error(self, message: str) -> None:
        self._log_line(f"errorOccurred：{message}")

    def _on_action_triggered(self, actionId: str, text: str, pos) -> None:
        self._log_line(f"actionTriggered：{actionId} ← {text.strip()[:30]!r}")
        if actionId == "copy":
            QApplication.clipboard().setText(text)
            self._log_line("  宿主实现：已写入剪贴板")
        elif actionId in _FAKE_REPLIES:
            self._start_action(actionId, text)

    def _demoResultDialog(self, main_layout):
        """结果对话框：宿主推进流式内容，取消接 ``stopRequested`` 自己中止。"""
        self._addInfoText(
            "点下面的按钮会在光标附近弹出结果对话框，逐段显示 Markdown。"
            "对话框只负责显示，不发网络请求：内容由本页的假后端用 QTimer 逐段推进，"
            "「停止」与关窗都会发 stopRequested，宿主必须在那里真的中止请求。",
            main_layout,
        )

        dialog = ElaSelectionResultDialog()
        self._result_dialog = dialog
        # 当前在跑的假后端定时器。用闭包盒子装，是为了让 abort 能看到并停掉它
        timer_box = {"timer": None}

        def abort(actionId):
            """``stopRequested`` 的处理：停掉本页的假后端。"""
            timer = timer_box["timer"]
            if timer is not None:
                timer.stop()
                timer.deleteLater()
                timer_box["timer"] = None
            self._log_line(f"stopRequested：{actionId}（本页已中止假后端）")

        def drive(source):
            """假后端：开一个回合，把 ``source`` 逐段推进进去直到落定。"""
            turn = dialog.beginStream()
            index = 0

            def tick():
                nonlocal index
                if index < len(source):
                    dialog.appendMarkdown(source[index], turn)
                    index += 1
                    return
                timer.stop()
                dialog.endStream(turn)

            # 定时器必须是页面的子对象（QTimer.singleShot 是无主的，页面销毁后
            # 照样在 T+ms 触发，去摸已释放的控件 = 0xC0000409 静默终止）
            timer = QTimer(self)
            timer.setInterval(320)
            timer.timeout.connect(tick)
            timer.start()
            timer_box["timer"] = timer

        def start(
            actionId, text="Hello world, this is a sample selection for the demo."
        ):
            """**新划词**：开窗 + 按落点定位 + 跑一个回合。"""
            abort(actionId)
            dialog.openFor(
                actionId,
                {"translate": "翻译", "explain": "解释", "summary": "总结"}[actionId],
                text,
                QCursor.pos(),
                self._action_icon(actionId),
            )
            drive(_FAKE_REPLIES[actionId])

        def regenerate(actionId):
            """重新生成：只重开一个回合，不调 ``openFor``。"""
            abort(actionId)
            drive(_FAKE_REPLIES[actionId])

        def show_one_shot():
            """非流式动作：一次性把完整结果塞进去。"""
            abort("search")
            dialog.openFor(
                "search",
                "搜索",
                "Hello world",
                QCursor.pos(),
                self._action_icon("search"),
            )
            dialog.setResult("## 搜索结果\n\n1. 第一个结果\n2. 第二个结果\n")

        def show_error():
            """出错动作：显示错误行，复制保持禁用（没有可用结果）。"""
            abort("explain")
            dialog.openFor(
                "explain",
                "解释",
                "Hello world",
                QCursor.pos(),
                self._action_icon("explain"),
            )
            dialog.setError("连接模型服务失败：请求超时（演示）")

        # 取消的唯一钩子：关窗 / 停止 / Esc 都会发 stopRequested，宿主在这里真的 abort 后端。
        dialog.stopRequested.connect(abort)

        # 重新生成 = 同一次划词的重跑，重开一个回合即可（regenerate 刻意不走
        #   openFor，否则窗口被按落点重新定位、从用户眼前挪走）
        dialog.regenerateRequested.connect(regenerate)

        # finished 只在**正常落定**时发；被中止的半句话不发（复制按钮保持禁用）。
        dialog.finished.connect(
            lambda actionId, text: self._log_line(
                f"finished：{actionId}（{len(text)} 字）"
            )
        )

        self._start_action = start

        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for actionId, label in (
            ("translate", "演示翻译"),
            ("explain", "演示解释"),
            ("summary", "演示总结"),
        ):
            btn = ElaButton(label, variant="outlined", size="small", parent=row)
            btn.clicked.connect(lambda _checked=False, aid=actionId: start(aid))
            layout.addWidget(btn)
        layout.addSpacing(12)
        once_btn = ElaButton("一次性结果", variant="text", size="small", parent=row)
        once_btn.clicked.connect(show_one_shot)
        layout.addWidget(once_btn)
        err_btn = ElaButton("演示错误", variant="text", size="small", parent=row)
        err_btn.clicked.connect(show_error)
        layout.addWidget(err_btn)
        layout.addStretch(1)
        main_layout.addWidget(row)

    def _action_icon(self, actionId: str):  # noqa: N802 (Qt 命名)
        """从已勾选的动作里取图标（结果对话框标题栏图标用）。"""
        for action in self._demo_actions:
            if action.id == actionId:
                return action.icon
        return None

    def _log_line(self, message: str) -> None:
        if self._log is None:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self._log.appendPlainText(f"[{stamp}] {message}")
        document = self._log.document()
        if document.blockCount() > _MAX_LOG_LINES:
            cursor = self._log.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(
                QTextCursor.MoveOperation.Down,
                QTextCursor.MoveMode.KeepAnchor,
                document.blockCount() - _MAX_LOG_LINES,
            )
            cursor.removeSelectedText()
        self._log.verticalScrollBar().setValue(self._log.verticalScrollBar().maximum())

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._assistant is not None:
            self._assistant.setEnabled(False)
        # 结果对话框是无父顶层窗：必须显式 close + deleteLater，光靠父窗口
        # 析构带不走它，会留在屏幕上（测试 tests/selection_assistant 守着同一条）。
        if self._result_dialog is not None:
            self._result_dialog.close()
            self._result_dialog.deleteLater()
            self._result_dialog = None
        super().closeEvent(event)
