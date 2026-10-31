"""审批 / 提问交互卡（逐题向导）。（``pyqt6_ela_pro.chat`` 内部模块）。"""

from __future__ import annotations


from typing import Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QFont,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconButton,
    ElaIconType,
    ElaPlainTextEdit,
    ElaScrollPageArea,
    ElaThemeType,
    eTheme,
)

from ..._internal import _ThemeAwareMixin
from ..._styles import ColorText
from ...ela_button import ElaButton
from ...ela_long_press_button import ElaLongPressButton
from ...tooltips import ElaToolTipPositionType, set_tooltip
from .. import _json
from .._question import (
    OPTION_GAP,
    SEGMENT_HIT,
    QuestionOptionCard,
    QuestionSegment,
    globalKeyAction,
    question_colors,
)
from .._theme import (
    base_color,
    blend,
    mono_font,
    muted_color,
    text_color,
)
from ..message import (
    ElaChatPermission,
    ElaChatPermissionStatusType,
)
from ._helpers import CARD_V_PADDING, LAYOUT_SPACING, _collapsed_detail


class PermissionCard(_ThemeAwareMixin, ElaScrollPageArea):
    """工具审批卡（``kind == Permission``）。

    **库不阻塞**：卡片只收集点击并发信号，挂起后端是宿主的事（Qt 里真的等按钮
    会卡死事件循环）。两种形态由 ``permission.questions`` 是否为空决定：空 = 批准型
    （允许一次 / 长按始终允许 / 拒绝），非空 = 逐题向导。

    「始终允许」只发信号，规则存哪、怎么匹配由宿主决定；库不持有权限状态。
    """

    #: 用户做出选择（reply / answer / feedback）；``reply`` 取 ElaChatPermissionStatusType。
    replied = pyqtSignal(str, str, str)

    #: 「始终允许」的长按时长（毫秒）。持久授权误触代价高，点一下不够。
    ALWAYS_HOLD_MS = 700

    _REJECT_ICON = ElaIconType.IconName.Ban
    _OK_ICON = ElaIconType.IconName.CircleCheck
    _QUESTION_ICON = ElaIconType.IconName.Question

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        # 圆角 0 + paintEvent 不画 = 透明：dock 本身就是那张卡，再画一层成「卡中卡」。
        self.setBorderRadius(0)
        self._permission: Optional[ElaChatPermission] = None
        self._responding = False

        # 逐题向导的状态（key 全部来自 ElaChatQuestion.key）
        self._tab = 0
        self._answers: dict = {}  # key -> [已选 label]
        self._custom: dict = {}  # key -> 自定义答案文本
        self._custom_on: dict = {}  # key -> 自定义行是否处于「选中」
        self._drafts: dict = {}  # key -> 未提交的自定义草稿（刷新重建后恢复）
        self._editing = ""  # 正在编辑自定义答案的 key
        self._focus_row = 0  # 键盘焦点所在行号
        self._segments: list = []  # QuestionSegment
        self._rows: dict = {}  # key -> [QuestionOptionCard]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, CARD_V_PADDING, 12, CARD_V_PADDING)
        layout.setSpacing(LAYOUT_SPACING)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self._icon = ElaIconButton(ElaIconType.IconName.ShieldHalved, 14, 18, 18, self)
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        head.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self._title = ColorText(self)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        title_row.addWidget(self._title)
        # 题目短标签放在标题行里：单独占行看起来像题面莫名换行，还白吃一行高度。
        self._tag = ColorText(self)
        self._tag.setTextFormat(Qt.TextFormat.PlainText)
        self._tag.hide()
        title_row.addWidget(self._tag)
        title_row.addStretch(1)
        # 右边是一组进度：「2 / 2」紧挨段条；左边说「在答什么」，右边说「答到第几」。
        self._progress = ColorText(self)
        self._progress.setTextFormat(Qt.TextFormat.PlainText)
        self._progress.hide()
        title_row.addWidget(self._progress, 0, Qt.AlignmentFlag.AlignVCenter)
        # 进度段：只在**多题**时出现（单题时进度条是纯噪音）
        self._segment_box = QWidget(self)
        self._segment_box.setFixedHeight(SEGMENT_HIT)
        self._segment_layout = QHBoxLayout(self._segment_box)
        self._segment_layout.setContentsMargins(0, 0, 0, 0)
        self._segment_layout.setSpacing(4)
        self._segment_box.hide()
        title_row.addWidget(self._segment_box, 0, Qt.AlignmentFlag.AlignVCenter)
        titles.addLayout(title_row)
        self._resources = ColorText(self)
        self._resources.setTextFormat(Qt.TextFormat.PlainText)
        self._resources.setWordWrap(True)
        titles.addWidget(self._resources)
        head.addLayout(titles, 1)
        layout.addLayout(head)

        # 详情（diff / 命令行 / 问题描述 / 已落定的答案摘要）
        self._detail = ColorText(self)
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setWordWrap(True)
        self._detail.setFont(mono_font(11))
        self._detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._detail.hide()
        layout.addWidget(self._detail)
        # 大量 diff 必须能折叠：一次 git diff 上千行，全量摊开会把消息撑到几千像素。
        self._detail_expanded = False
        #: 详情折叠态归属的请求 id（换请求才复位折叠）
        self._detail_request = ""
        self._detail_toggle = ElaButton(
            "展开全部", variant="link", size="small", parent=self
        )
        self._detail_toggle.clicked.connect(self._toggle_detail)
        self._detail_toggle.hide()
        layout.addWidget(self._detail_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        # ── 问答型：题面 + 提示 + 选项区 ─────────────────────────────────
        self._question_box = QWidget(self)
        question_layout = QVBoxLayout(self._question_box)
        # 顶部 4px + 段间距 10px ≈ opencode 的 gap:16px 减一点；标题行与题面挨太近会糊成一段。
        question_layout.setContentsMargins(0, 4, 0, 0)
        question_layout.setSpacing(10)
        self._question_text = ColorText(self._question_box)
        self._question_text.setTextFormat(Qt.TextFormat.PlainText)
        self._question_text.setWordWrap(True)
        question_layout.addWidget(self._question_text)
        # 选项区是普通容器不是滚动区：QScrollArea 的 sizeHint 是无意义小值，会压扁
        # 内容；「自测内容再 setFixedHeight」又会与布局互相喂误差。候选行行高固定，
        # 容器 sizeHint 就是内容高度，不设上限（内容被裁到够不着更糟）。
        self._options_host = QWidget(self._question_box)
        self._options_box = QVBoxLayout(self._options_host)
        self._options_box.setContentsMargins(0, 0, 0, 0)
        self._options_box.setSpacing(OPTION_GAP)
        question_layout.addWidget(self._options_host)
        self._question_box.hide()
        layout.addWidget(self._question_box)
        self._option_buttons: list = []  # 当前题的全部候选卡
        self._custom_edit = None

        # ── 批准型的动作区（问答型不用） ───────────────────────────────
        # 三个动作按重要性分档：允许一次 = 实心强调色，始终允许 = 描边，拒绝 = 文字 + 危险色。
        self._actions = QWidget(self)
        actions_layout = QHBoxLayout(self._actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        self._allow_button = ElaButton(
            "允许一次",
            variant="solid",
            color="primary",
            size="small",
            parent=self._actions,
        )
        self._allow_button.clicked.connect(
            lambda: self._emit_reply(ElaChatPermissionStatusType.Allowed, "", "")
        )
        actions_layout.addWidget(self._allow_button)
        # 「始终允许」是持久授权，误触代价高 —— 按住 700ms 才生效；短按不发 longPressed。
        self._always_button = ElaLongPressButton(
            "始终允许",
            variant="outlined",
            size="small",
            duration=self.ALWAYS_HOLD_MS,
            parent=self._actions,
        )
        self._always_button.longPressed.connect(
            lambda: self._emit_reply(ElaChatPermissionStatusType.Always, "", "")
        )
        set_tooltip(
            self._always_button,
            f"长按 {self.ALWAYS_HOLD_MS / 1000:g} 秒始终允许",
            ElaToolTipPositionType.Top,
        )
        actions_layout.addWidget(self._always_button)
        self._reject_button = ElaButton(
            "拒绝…", variant="text", danger=True, size="small", parent=self._actions
        )
        self._reject_button.clicked.connect(self._open_feedback)
        actions_layout.addWidget(self._reject_button)
        actions_layout.addStretch(1)
        self._actions.hide()
        layout.addWidget(self._actions)
        self._feedback_row = QWidget(self)
        feedback_layout = QHBoxLayout(self._feedback_row)
        feedback_layout.setContentsMargins(0, 0, 0, 0)
        feedback_layout.setSpacing(6)
        self._feedback_edit = ElaPlainTextEdit(self._feedback_row)
        self._feedback_edit.setPlaceholderText("为什么拒绝？（可留空，会回传给模型）")
        self._feedback_edit.setFixedHeight(30)
        feedback_layout.addWidget(self._feedback_edit, 1)
        self._feedback_send = ElaButton(
            "回车提交", size="small", parent=self._feedback_row
        )
        self._feedback_send.clicked.connect(self._submit_feedback)
        feedback_layout.addWidget(self._feedback_send, 0)
        self._feedback_row.hide()
        layout.addWidget(self._feedback_row)

        # ── 问答型的页脚托盘 ────────────────────────────────────────────
        self._footer = QWidget(self)
        footer_layout = QHBoxLayout(self._footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(6)
        self._dismiss_button = ElaButton(
            "忽略", variant="text", size="small", parent=self._footer
        )
        self._dismiss_button.clicked.connect(
            lambda: self._emit_reply(ElaChatPermissionStatusType.Cancelled, "", "")
        )
        footer_layout.addWidget(self._dismiss_button)
        footer_layout.addStretch(1)
        self._back_button = ElaButton(
            "上一步", variant="outlined", size="small", parent=self._footer
        )
        self._back_button.clicked.connect(self._go_back)
        footer_layout.addWidget(self._back_button)
        # 主动作 = 实心强调色；快捷键只在键盘上生效、不写在按钮上（内联提示比按钮抢眼）。
        self._next_button = ElaButton(
            "下一步",
            variant="solid",
            color="primary",
            size="small",
            parent=self._footer,
        )
        self._next_button.clicked.connect(self._go_next)
        footer_layout.addWidget(self._next_button)
        self._footer.hide()
        layout.addWidget(self._footer)

        self.hide()
        self._apply_theme()

    # -- 尺寸契约 ----------------------------------------------------------

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        """按内容布局报高度；宽度交给父布局（0 = 别替我决定）。

        不能继承 ``QAbstractScrollArea`` 的 ``sizeHint()``（它按视口 + 框架估算，
        不是内容高度契约）；高度取布局的 ``minimumSize``，否则可换行文本会算小。
        """
        return QSize(0, self.layout().minimumSize().height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        return self.sizeHint()

    # -- 数据 --------------------------------------------------------------

    def setPermission(self, permission: Optional[ElaChatPermission]) -> None:
        """设置审批请求（``None`` 隐藏整张卡）。

        新 request（``request_id`` 变了）重置向导状态；同一 request 的状态推进保留
        草稿，否则宿主「先 setResponding(True) 再回填」的两段式会抹掉用户已选。

        这里不调 ``show()``：卡片由 dock 在收下它的那一刻显示；无父控件在这里 show
        会被 Qt 当成顶层窗口弹出来。
        """
        previous = self._permission
        self._permission = permission
        # 只在「新请求进入等待」时清 responding：落定那次 setPermission 是
        # replied.emit() 的同步回环，无条件清会抹掉刚置上的 responding。
        is_new = previous is None or (
            permission is not None
            and previous is not None
            and previous.request_id != permission.request_id
        )
        if permission is not None and permission.isPending:
            self._responding = False
            if is_new:
                self._reset_wizard()
        if permission is None:
            self.hide()
            return
        self._sync_all()

    def permission(self) -> Optional[ElaChatPermission]:
        """获取当前审批快照。"""
        return self._permission

    def setResponding(self, on: bool) -> None:
        """设置「回复已在途」——期间禁用全部可交互部件，防双击重复提交。"""
        self._responding = bool(on)
        self._sync_actions()
        self._sync_options_enabled()

    def responding(self) -> bool:
        """是否处于「回复在途」状态。"""
        return self._responding

    def answers(self) -> dict:
        """当前向导的答案（``{key: [label, ...]}``，未答的 key 不在字典里）。"""
        result = {}
        for question in self._questions():
            values = self._current_values(question)
            if values:
                result[question.key] = list(values)
        return result

    def tabIndex(self) -> int:  # noqa: N802
        """当前题号（从 0 起）。"""
        return self._tab

    def questionCount(self) -> int:  # noqa: N802
        """题目总数。"""
        return len(self._questions())

    # -- 内部：向导 --------------------------------------------------------

    def _questions(self) -> tuple:
        permission = self._permission
        if permission is None:
            return ()
        return permission.questions

    def _current_question(self):
        questions = self._questions()
        if not questions:
            return None
        return questions[min(self._tab, len(questions) - 1)]

    def _reset_wizard(self) -> None:
        self._tab = 0
        self._answers.clear()
        self._custom.clear()
        self._custom_on.clear()
        self._drafts.clear()
        self._editing = ""

    def _current_values(self, question) -> list:
        """该题当前的答案列表（自定义优先且与候选项互斥）。"""
        if self._custom_on.get(question.key) and self._custom.get(question.key):
            return [self._custom[question.key]]
        return list(self._answers.get(question.key) or ())

    def _build_answer(self) -> str:
        """把向导状态编码成 ``permissionReplied`` 的 ``answer``。

        单选塌缩成标量，多选发数组，未答题整条不进 payload（空数组会被误读成
        「一个都不选」），自定义答案与候选项互斥。
        """
        payload = {}
        for question in self._questions():
            values = self._current_values(question)
            if not values:
                continue
            payload[question.key] = values if question.isMultiple else values[0]
        return _json.dumps(payload)

    def _sync_all(self) -> None:
        """刷新整张交互卡。

        本控件只负责「正在等用户操作」：落定后它立刻被销毁，时间线上留下的是
        :class:`PermissionRecord`，所以这里没有 settled 分支。
        """
        permission = self._permission
        if permission is None:
            return
        is_question = permission.isQuestion
        self._question_box.setVisible(is_question)
        self._footer.setVisible(is_question)
        # 动作区显隐只有 _sync_actions 一处说了算；question 分支也要调它，否则
        # 从批准型切到问答型时批准三键与拒绝理由行会留在卡上。
        if is_question:
            self._sync_header(permission)
            self._sync_detail(permission)
            self._sync_question()
            self._sync_segments()
            self._sync_footer()
            self._sync_actions()
        else:
            self._segment_box.hide()
            self._progress.hide()
            self._tag.hide()
            self._sync_header(permission)
            self._sync_detail(permission)
            self._sync_actions()
        self._apply_theme()

    def _sync_header(self, permission: ElaChatPermission) -> None:
        title = permission.title or self._default_title(permission)
        self._title.setText(title)
        if permission.isQuestion:
            total = len(permission.questions)
            self._progress.setText(f"{self._tab + 1} / {total}")
            self._progress.setVisible(total > 1)
        else:
            self._progress.setText("")
            self._progress.hide()
        if permission.isQuestion:
            # 资源列表与「始终允许」规则对问答型无意义
            self._resources.setText("")
            self._resources.hide()
            return
        self._tag.setText("")
        self._tag.hide()
        resources = [item for item in permission.resources if item]
        if resources:
            shown = resources[:4]
            text = "\n".join(shown)
            if len(resources) > len(shown):
                text += f"\n… 另有 {len(resources) - len(shown)} 项"
            self._resources.setText(text)
            self._resources.show()
        else:
            self._resources.setText("")
            self._resources.hide()

    @staticmethod
    def _default_title(permission: ElaChatPermission) -> str:
        if permission.isQuestion:
            return "需要你回答"
        return f"需要确认：{permission.action or '工具执行'}"

    def _sync_detail(self, permission: ElaChatPermission) -> None:
        """交互期间只显示宿主给的 detail（diff / 命令行）。

        答案摘要归 :class:`PermissionRecord`：交互卡落定即销毁，没必要再写一套。
        """
        if permission.request_id != self._detail_request:
            # 只在新请求时复位折叠；同一 request 的状态刷新（``setResponding``
            # 两段式的回填）不能把用户刚展开的长 diff 折回去。
            self._detail_expanded = False
            self._detail_request = permission.request_id
        self._sync_detail_text(permission.detail or "")

    def _sync_detail_text(self, detail: str) -> None:
        """写入详情，并按「行数 + 单行长度」双上限决定是否折叠。

        两个上限缺一不可：``git diff`` 行多但每行短，minified / base64 行少但单行巨长。
        """
        if not detail:
            self._detail.setText("")
            self._detail.hide()
            self._detail_toggle.hide()
            return
        shown, overflow, total = _collapsed_detail(detail, self._detail_expanded)
        self._detail.setText(shown)
        self._detail.show()
        self._detail_toggle.setVisible(overflow)
        self._detail_toggle.setText(
            f"收起（共 {total} 行）"
            if self._detail_expanded
            else f"展开全部（共 {total} 行）"
        )

    def _toggle_detail(self) -> None:
        permission = self._permission
        if permission is None:
            return
        self._detail_expanded = not self._detail_expanded
        self._sync_detail_text(permission.detail or "")

    def _sync_question(self) -> None:
        """重建选项区并显示当前题（切题时草稿从 ``_custom`` 恢复）。"""
        question = self._current_question()
        self._clear_options()
        if question is None:
            self._question_text.setText("")
            self._option_buttons = []
            self._editing = ""
            return
        # 短标签进标题行（不单独占一行）；前缀分隔符免得和标题糊成一片
        self._tag.setText(f"\u00b7 {question.header}" if question.header else "")
        self._tag.setVisible(bool(question.header))
        self._question_text.setText(question.question or question.header)
        rows = []
        for index, option in enumerate(question.options):
            rows.append(
                self._make_row(
                    question,
                    option.label,
                    option.description,
                    index,
                    custom=False,
                )
            )
        if question.custom:
            rows.append(self._make_row(question, "", "", len(rows), custom=True))
        for row in rows:
            self._options_box.addWidget(row)
        self._rows[question.key] = rows
        self._option_buttons = rows
        self._refresh_rows()
        if self._editing == question.key:
            # 同一题刷新（setPermission 两段式回填）：编辑器原地恢复，草稿由 _refresh_rows 回填。
            self._enter_editing(question.key)
        else:
            # 切题 / 换请求：旧编辑态作废（草稿已在 ``_clear_options`` 暂存）
            self._editing = ""

    def _on_row_focused(self, index: int) -> None:
        """记住键盘焦点行号（不轮询 ``hasFocus()``：它要求窗口已激活，会静默失灵）。"""
        self._focus_row = int(index)

    def _make_row(
        self, question, label: str, description: str, index: int, *, custom: bool
    ):
        row = QuestionOptionCard(
            self._options_host,
            value=label,
            description=description,
            multi=question.isMultiple,
            isCustom=custom,
        )
        row.setRowIndex(index)
        row.activate.connect(lambda value, q=question: self._on_activate(q, value))
        row.markClicked.connect(lambda v, q=question: self._on_mark_clicked(q, v))
        row.editCommitted.connect(lambda text, q=question: self._on_commit(q, text))
        row.moveFocus.connect(self._move_focus)
        row.rowFocused.connect(self._on_row_focused)
        # 数字键 / Ctrl+⏎ / Alt+← / Esc 由持有全部行的这一层派发：焦点常驻在行上，
        # 键盘事件发给行、不冒泡回卡片。
        row.globalKey.connect(self._on_global_key)
        return row

    def _clear_options(self) -> None:
        # 编辑中的草稿先存下来：刷新会销毁行控件，重建后只能从 _drafts 找回。
        # 不在这里清 _editing：_sync_question 还要按它决定原地恢复还是丢弃。
        if self._editing:
            row = self._custom_row(self._editing)
            if row is not None and row.editorText():
                self._drafts[self._editing] = row.editorText()
        for rows in self._rows.values():
            for row in rows:
                self._options_box.removeWidget(row)
                row.setParent(None)
                row.deleteLater()
        self._rows.clear()
        self._option_buttons = []

    def _refresh_rows(self) -> None:
        """把 ``_answers`` / ``_custom`` 同步到当前题的每一张卡，并刷新进度段。

        自定义行的勾选态只认 ``_custom_on``：它的 ``value()`` 是空串，用
        ``row.value() in picked`` 会让自定义答案永远不高亮、再点还取消答案。
        """
        question = self._current_question()
        if question is not None:
            picked = set(self._current_values(question))
            custom_on = bool(self._custom_on.get(question.key))
            for row in self._rows.get(question.key, ()):
                if row.isCustom():
                    row.setPicked(custom_on)
                else:
                    row.setPicked(row.value() in picked)
                # 正在编辑的行不要覆盖：用户没提交的字比已提交值新（草稿优先）
                if row.isCustom() and not row.isEditing():
                    row.setEditorText(
                        self._drafts.get(question.key)
                        or self._custom.get(question.key, "")
                    )
        self._sync_segments()

    def _on_activate(self, question, value: str) -> None:
        """整行被激活：普通候选项 = 切换勾选；自定义行 = 展开编辑器。"""
        if not value:
            self._enter_editing(question.key)
            return
        already = value in (self._answers.get(question.key) or ())
        self._select_value(question, value, not already)

    def _on_mark_clicked(self, question, value: str) -> None:
        """点标记 / 按 Space。

        普通候选行切换勾选；自定义行（``value`` 空串）选中并展开编辑器。单选下
        标记不提供「再点取消」（radio），取消语义只挂多选。
        """
        if value:
            already = value in (self._answers.get(question.key) or ())
            self._select_value(question, value, not already)
            return
        key = question.key
        if not question.options:
            # 没有候选项时标记没有意义，整行 = 展开编辑器
            self._enter_editing(key)
            return
        if question.isMultiple and self._custom_on.get(key, False):
            self._custom_on[key] = False
            self._close_custom_editor(key)
            self._refresh_rows()
            return
        self._enter_editing(key)

    def _on_commit(self, question, text: str) -> None:
        key = question.key
        self._custom[key] = text
        self._custom_on[key] = True
        self._answers.pop(key, None)
        self._drafts.pop(key, None)
        self._editing = ""
        row = self._custom_row(key)
        if row is not None:
            row.setEditing(False)
        self._refresh_rows()

    def _select_value(self, question, value: str, checked: bool) -> None:
        key = question.key
        if question.isMultiple:
            picked = list(self._answers.get(key) or ())
            if checked and value not in picked:
                picked.append(value)
            elif not checked and value in picked:
                picked.remove(value)
            self._answers[key] = picked
        else:
            self._answers[key] = [value] if checked else []
        # 选了候选项 -> 取消「自定义选中」（两者互斥，见 _build_answer）；输入框一起收起。
        self._custom_on[key] = False
        self._close_custom_editor(key)
        self._refresh_rows()

    def _custom_row(self, key: str):
        for row in self._rows.get(key, ()):
            if row.isCustom():
                return row
        return None

    def _close_custom_editor(self, key: str) -> None:
        """收起自定义答案的输入框（``_editing`` 与行上的 ``setEditing(False)`` 要一起动）。"""
        if self._editing != key:
            return
        self._editing = ""
        row = self._custom_row(key)
        if row is not None:
            row.setEditing(False)

    def _commit_editing(self) -> None:
        """落定正在编辑的自定义答案（空文本等于没写，``commitEdit`` 自会跳过）。

        用户敲完字习惯直接点「下一步 / 提交」，不在这里补一次提交那段文字会丢。
        """
        if not self._editing:
            return
        row = self._custom_row(self._editing)
        if row is not None:
            row.commitEdit()

    def _enter_editing(self, key: str) -> None:
        self._editing = key
        # 展开编辑器 = 选中自定义：单选下候选项随之取消，否则两根圆点同时亮着。
        self._custom_on[key] = True
        self._answers.pop(key, None)
        row = self._custom_row(key)
        if row is not None:
            # 编辑器里已有内容（未提交草稿）就不要用已提交值覆盖。
            if not row.editorText():
                row.setEditorText(self._drafts.get(key) or self._custom.get(key, ""))
            row.setEditing(True)
        self._refresh_rows()

    def _move_focus(self, delta: int) -> None:
        """方向键 / Home / End 在当前题的候选卡之间移动焦点。"""
        rows = self._option_buttons
        if not rows:
            return
        if delta == 0:
            target = 0
        elif delta == 2:
            target = len(rows) - 1
        else:
            target = max(0, min(len(rows) - 1, self._focus_row + delta))
        self._focus_row = target
        rows[target].setFocus()

    def focusedRowIndex(self) -> int:  # noqa: N802
        """当前键盘焦点所在行号（从 0 起）。"""
        return self._focus_row

    def _sync_segments(self) -> None:
        """进度段：只在**多题**时出现。"""
        questions = self._questions()
        while len(self._segments) > len(questions):
            segment = self._segments.pop()
            self._segment_layout.removeWidget(segment)
            segment.setParent(None)
            segment.deleteLater()
        while len(self._segments) < len(questions):
            index = len(self._segments)
            segment = QuestionSegment(index, self._segment_box)
            segment.jumped.connect(self._goto)
            self._segment_layout.addWidget(segment)
            self._segments.append(segment)
        for index, segment in enumerate(self._segments):
            question = questions[index]
            # 与 answers() 同一口径（_current_values）：只看 _custom 有文本会把已取消勾选的答案判成已答。
            answered = bool(self._current_values(question))
            segment.setState(index == self._tab, answered)
        self._segment_box.setVisible(len(questions) > 1)

    def _sync_footer(self) -> None:
        """页脚：按钮文案随题号变，「上一步」只在有得退时出现。

        配色不用手工注入 —— 三个都是 ElaButton，自己跟随主题取色。
        """
        questions = self._questions()
        last = self._tab >= len(questions) - 1
        self._back_button.setVisible(self._tab > 0)
        self._next_button.setText("提交" if last else "下一步")

    def _sync_options_enabled(self) -> None:
        permission = self._permission
        pending = permission is not None and permission.isPending
        enabled = pending and not self._responding
        for rows in self._rows.values():
            for row in rows:
                row.setEnabled(enabled)

    def _go_next(self) -> None:
        """「下一步」：还有题就前进，最后一题就是提交。"""
        questions = self._questions()
        if not questions:
            return
        # 编辑框里的文字先落定：用户很少会先按 Enter 再点按钮
        self._commit_editing()
        if self._tab < len(questions) - 1:
            self._set_tab(self._tab + 1)
            return
        self._submit_answers()

    def _go_back(self) -> None:
        if self._tab <= 0:
            return
        self._set_tab(self._tab - 1)

    def _goto(self, index: int) -> None:
        if not 0 <= index < len(self._questions()):
            return
        self._set_tab(index)

    def _set_tab(self, index: int) -> None:
        """切题的唯一入口（前进 / 后退 / 点进度段都走这里）。"""
        questions = self._questions()
        if not 0 <= index < len(questions) or index == self._tab:
            return
        # 走之前把这一题编辑框里的文字落定（草稿只在「行还在」时才是答案）。
        self._commit_editing()
        self._tab = index
        self._focus_row = 0
        self._sync_question()
        self._sync_header(self._permission)
        self._sync_segments()
        self._sync_footer()
        if self._option_buttons:
            self._option_buttons[0].setFocus()

    def _submit_answers(self) -> None:
        self._emit_reply(ElaChatPermissionStatusType.Allowed, self._build_answer(), "")

    def _sync_actions(self) -> None:
        permission = self._permission
        if permission is None or permission.isQuestion:
            self._actions.hide()
            # 问答型不该看到批准型的拒绝理由行（同一张卡换请求类型时尤其明显）
            self._feedback_row.hide()
        else:
            pending = permission.isPending and not self._responding
            self._actions.setVisible(pending)
            for button in self._action_buttons():
                button.setEnabled(pending)
            if permission.isPending:
                # 用 isHidden 判据（isVisible 要求整条父链已显示，未 show 时恒 False）。
                self._feedback_row.setVisible(
                    not self._feedback_row.isHidden() and pending
                )
            else:
                self._feedback_row.hide()
        # 问答型的页脚在 responding 期间一起置灰
        enabled = (
            permission is not None and permission.isPending and not self._responding
        )
        for button in (self._dismiss_button, self._back_button, self._next_button):
            button.setEnabled(enabled)
        self._sync_options_enabled()

    def _action_buttons(self) -> tuple:
        """批准型的三个动作按钮（**给宿主与测试用的稳定顺序**）。"""
        return (self._allow_button, self._always_button, self._reject_button)

    def _open_feedback(self) -> None:
        self._feedback_row.show()
        self._feedback_edit.setFocus()

    def _submit_feedback(self) -> None:
        text = self._feedback_edit.toPlainText().strip()
        self._feedback_row.hide()
        self._emit_reply(ElaChatPermissionStatusType.Rejected, "", text)

    def _emit_reply(self, reply: str, answer: str, feedback: str) -> None:
        # 两道闸：responding（回复在途）与已落定（双击的第二下）。
        if self._responding or self._permission is None:
            return
        if not self._permission.isPending:
            return
        self._responding = True
        self._sync_actions()
        self.replied.emit(str(reply), str(answer), str(feedback))

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        permission = self._permission
        text = text_color(mode)
        # 标题用主文本色、与题面同级（弱化会读不出「现在需要你做什么」）。
        self._title.setTextColor(text)
        self._title.setTextPixelSize(14)
        self._title.setTextWeight(QFont.Weight.Medium)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        # 进度与短标签退到 11px 弱化：它们是注记，不该和标题抢同一层级
        self._progress.setTextColor(muted_color(mode, 0.62))
        self._progress.setTextPixelSize(11)
        self._resources.setTextColor(muted_color(mode, 0.7))
        self._resources.setTextPixelSize(11)
        self._resources.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setTextColor(muted_color(mode, 0.8))
        self._detail.setTextPixelSize(11)
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail_toggle.setColor("primary")
        # 问答型各处的色（题面 / 说明 / 提示 / 选项卡）
        colors = question_colors(mode)
        self._tag.setTextColor(colors["hint"])
        self._tag.setTextPixelSize(11)
        self._tag.setTextFormat(Qt.TextFormat.PlainText)
        self._question_text.setTextColor(colors["ink"])
        self._question_text.setTextPixelSize(14)
        self._question_text.setTextWeight(QFont.Weight.DemiBold)
        for rows in self._rows.values():
            for row in rows:
                row.applyTheme(mode)
        # 交互卡只处理等待态：图标只有「提问」/「工具确认」两种，绿 / 红是记录卡的语义。
        icon = (
            self._QUESTION_ICON
            if permission is not None and permission.isQuestion
            else ElaIconType.IconName.ShieldHalved
        )
        self._icon.setAwesome(icon)
        self._icon.setLightIconColor(blend(base_color(mode), text, 0.5))
        self._icon.setDarkIconColor(blend(base_color(mode), text, 0.5))
        if permission is not None and permission.isQuestion:
            self._sync_footer()

    def paintEvent(self, _event) -> None:  # noqa: N802
        """不画卡面：dock 本身就是那张卡（圆角 + 边框），再画一层成「卡中卡」。"""

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """卡片级快捷键（焦点在卡片本体上时的兜底路径）。

        主路径是候选行的 :attr:`QuestionOptionCard.globalKey` 信号：焦点常驻在行上，
        键盘事件发给行、不冒泡回卡片。
        """
        if not self._handle_shortcut(event):
            super().keyPressEvent(event)

    def _on_global_key(self, action: str) -> None:
        """候选行转上来的卡片级快捷键。

        ``digit:<n>`` 只能在这一层派发：单行只知道自己的序号，而 1–9 的语义是
        「选中整组候选卡的第 n 个」。
        """
        if not self._live():
            return
        if action == "next":
            self._go_next()
        elif action == "back":
            self._go_back()
        elif action == "dismiss":
            self._emit_reply(ElaChatPermissionStatusType.Cancelled, "", "")
        elif action.startswith("digit:"):
            try:
                index = int(action.split(":", 1)[1])
            except ValueError:
                return
            rows = self._option_buttons
            if 0 <= index < len(rows):
                rows[index].activate.emit(rows[index].value())

    def _live(self) -> bool:
        """卡片是否还能接受交互（待答复 + 不在途）。"""
        permission = self._permission
        return permission is not None and permission.isPending and not self._responding

    def _handle_shortcut(self, event) -> bool:
        """在卡片本体上复现同一套快捷键；返回是否已消费。"""
        if not self._live():
            return False
        action = globalKeyAction(event.key(), event.modifiers())
        if action is None:
            return False
        if action == "next":
            self._go_next()
        elif action == "back":
            self._go_back()
        elif action == "dismiss":
            self._emit_reply(ElaChatPermissionStatusType.Cancelled, "", "")
        else:
            self._on_global_key(action)
        return True
