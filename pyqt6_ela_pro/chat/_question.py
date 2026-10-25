"""问答型工具审批的自绘控件（``pyqt6_ela_pro.chat`` 内部模块）。

对应 opencode ``packages/app/src/session/requests/session-question-dock.tsx``
的视觉与交互：**逐题向导** + 「N / M 个问题」进度段 + 候选卡（两行：标题 +
说明）+ 选中态 + 「输入自己的答案」作为列表最后一项。

与 opencode 的一处**有意分歧**：它把强调色硬编码成 ``#034cff``（那是他们
的品牌色，两套主题同值）。本库是**可换肤的组件库**，硬编码外来品牌色既违反
``AGENTS.md`` 的「主题经 eTheme 语义令牌实时换肤」，也会在用户换主题时显得
突兀。所以 opencode 的色板在这里被**映射到主题令牌**：

===========================  ==========================================
opencode                     本库
===========================  ==========================================
``bg-layer-01`` 未选中卡底     ``surface_color()``
``bg-base``      悬浮卡底     ``card_color()``
``state-bg-info`` 选中卡底    ``blend(base, accent, 0.10)``
``#034cff``      选中标记      **不用**：交给 ``ElaCheckBox`` /
                             ``ElaRadioButton``（它们自己从 ``eTheme`` 取色）
``--shadow-xs-border-hover`` 外发光 ``paintRoundedCard(glow=…)``
``text-muted``   说明 / 提示   ``muted_color()``
``border-base``  0.5px 描边   ``border_color()``（本库画 1px：Qt 下 0.5px 会糊）
===========================  ==========================================

**勾选标记一律用 Ela 现有控件，不自绘。** 早期版本手画了 16px 的圆角方块 +
强调色填充，结果「未选中」时**单选和多选画得一模一样**（都是圆角方块），用户
根本分不出这是单选还是多选 —— 而这恰恰是这个控件唯一要传达的信息。
:class:`ElaCheckBox`（走 ``ElaCheckBoxStyle``，21×22）与
:class:`ElaRadioButton`（自绘 ``paintEvent``，20×21）都是正牌 Ela 外观，
21px 也比手画的 16px 更符合 Ela 的控件密度。

三个已踩过的坑，这里是修好的版本：

1. **自定义答案必须真的进答案** —— 早期实现在「自己写一个」那行挂了个
   ``ElaPlainTextEdit``，但 ``toPlainText()`` 一次都没被调用，是个**纯装饰
   品**。现在 :meth:`QuestionOptionCard.commitEdit` 会读它。
2. **自增高要靠 ``sizeHint``，不能在 ``textChanged`` 里改几何**（否则 0xC0000409）。
   见 :class:`_AutoGrowEditor`。
3. **编辑器上色只能走 palette** —— ``ElaPlainTextEdit`` 没有 ``setTextColor``。
   见 :meth:`QuestionOptionCard._apply_editor_theme`。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaCheckBox,
    ElaPlainTextEdit,
    ElaRadioButton,
    ElaThemeType,
    eTheme,
)

from .._internal import _ThemeAwareMixin, is_deleted, single_shot_on
from .._styles import ColorText, paintRoundedCard
from ._theme import (
    accent_color,
    base_color,
    blend,
    border_color,
    card_color,
    muted_color,
    surface_color,
    text_color,
)

#: 标记与文字的间距
MARK_GAP = 8
#: 卡片内边距（左, 上, 右, 下）
#:
#: 纵向刻意压到 4px：候选行是**列表**不是卡片，一行占 46px 时 5 个选项就吃掉
#: 250px，整张问题卡半屏都是框，看着「每项都太高」（实测截图）。
CARD_PADDING = (8, 4, 8, 4)
#: 候选卡圆角
CARD_RADIUS = 6.0
#: 候选卡之间的间距（对齐 ``gap: 6px``）
OPTION_GAP = 6
#: 进度段的条形尺寸与命中盒（对齐 opencode ``question-progress-segment``）。
#:
#: CSS 是 ``width:16px; height:2px; border-radius:999px`` + ``gap:8px`` ——
#: **2px 细条 + 全圆角胶囊**。之前「细条像划痕」的观感其实来自圆角：画成 1px
#: 圆角就成了方头短横。圆角取高度一半（1px）才是胶囊，命中盒另给 16px 保证好点。
SEGMENT_BAR = (16, 2)
SEGMENT_HIT = 16
#: 外发光透明度（对齐 opencode ``rgba(3,76,255,.24)``）
GLOW_ALPHA = 61
#: 「输入自己的答案」的固定文案（对齐 ``ui.messagePart.option.typeOwnAnswer``）
CUSTOM_ANSWER_LABEL = "输入自己的答案"
#: 自定义答案输入框的占位符（对齐 ``ui.question.custom.placeholder``）
CUSTOM_ANSWER_PLACEHOLDER = "输入你的答案…"


def question_colors(mode) -> dict:
    """一次性算出问答型用到的全部颜色（避免各处重复拼 ``blend``）。

    **注意这里没有「标记色」**：勾选标记是真正的
    :class:`~PyQt6ElaWidgetTools.ElaCheckBox` /
    :class:`~PyQt6ElaWidgetTools.ElaRadioButton` 子控件，它自己从 ``eTheme``
    取色（``ElaCheckBoxStyle`` 用 ``PrimaryNormal`` / ``BasicBorderDeep``）。
    自绘一份标记只会和它打架 —— 而且自绘版本在「未选中」时两种模式都画圆角方块，
    单选看着像多选（这正是被指出来的那个问题）。
    """
    ink = text_color(mode)
    accent = accent_color(mode)
    glow = QColor(accent)
    glow.setAlpha(GLOW_ALPHA)
    return {
        "card": surface_color(mode),
        "card_hover": card_color(mode),
        "picked": blend(base_color(mode), accent, 0.10),
        "border": border_color(mode, 0.16),
        "neutral_border": border_color(mode, 0.18),
        "glow": glow,
        "accent": accent,
        "ink": ink,
        "muted": muted_color(mode, 0.7),
        "hint": muted_color(mode, 0.62),
        "surface": card_color(mode),
        "overlay": blend(base_color(mode), ink, 0.06),
        "overlay_press": blend(base_color(mode), ink, 0.12),
        "focus": blend(accent, ink, 0.35),
    }


def globalKeyAction(key, mods) -> Optional[str]:
    """把卡片级快捷键 ``(key, mods)`` 映射成动作串；不匹配返回 ``None``。

    动作串：``"next"``（Ctrl+Enter）/ ``"back"``（Alt+←）/ ``"dismiss"``（Esc）/
    ``"digit:N"``（1–9，按**整组候选卡**下标）。

    行内分发（:class:`QuestionOptionCard` 的 ``globalKey``）与卡片本体
    （``PermissionCard._handle_shortcut``）共用这一份 —— 两处各写一套必然漂移。
    """
    ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
    alt = bool(mods & Qt.KeyboardModifier.AltModifier)
    plain = not (
        ctrl
        or alt
        or mods & (Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.ShiftModifier)
    )
    if ctrl and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        return "next"
    if alt and key == Qt.Key.Key_Left:
        return "back"
    if plain and key == Qt.Key.Key_Escape:
        return "dismiss"
    if plain and Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
        return f"digit:{key - Qt.Key.Key_1}"
    return None


class _AutoGrowEditor(ElaPlainTextEdit):
    """按文档高度自增高的编辑器。

    **为什么必须子类化**：``ElaPlainTextEdit.sizeHint()`` 在 C++ 侧硬编码返回
    ``(256, 192)``（它本来是给输入卡片用的固定高度），所以
    ``setSizePolicy(..., Minimum)`` 完全没用 —— 布局取的 ``sizeHint()`` 就是
    192，单行输入会撑出一个巨大的框。

    在这里覆盖 ``sizeHint``，让**布局**去要正确的高度，而不是反过来在
    ``textChanged`` 里改控件几何。后者才是之前崩的原因：在 textChanged 槽里
    ``setFixedHeight(0)`` 再按文档高度设回去 = 重入布局失效，Qt 直接
    0xC0000409 静默终止（无 traceback）。改 ``sizeHint`` + ``updateGeometry()``
    是单向的（只发 LayoutRequest，不动几何），不会重入。

    编辑器自己的按键语义（Enter / Esc / Ctrl+Enter）通过**信号**上报，
    刻意**不装** Python 事件过滤器：这是会被随行销毁的子控件，
    ``child.installEventFilter(parent)`` 在父窗口树整体析构时踩 0xC0000409
    （候选行的键盘分发就是为此改成信号的，同一形状不该两套做法）。
    """

    #: 按 Enter（非 Shift / Ctrl）：提交这一题
    submitRequested = pyqtSignal()
    #: 按 Esc：退出编辑（**保留文本**）
    dismissRequested = pyqtSignal()
    #: 按 Ctrl+Enter：整卡「下一步 / 提交」
    advanceRequested = pyqtSignal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.dismissRequested.emit()
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            mods = event.modifiers()
            if mods & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)  # 换行
                return
            if mods & Qt.KeyboardModifier.ControlModifier:
                self.advanceRequested.emit()
            else:
                self.submitRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(hint.width(), self._document_height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(60, 24)

    def _document_height(self) -> int:
        """排版后的像素高度（**含折行**）。

        **别用** ``document().size().height()`` / ``documentLayout().documentSize()``
        —— 它们返回逻辑单位（块数），不是像素。按块数算则长单段（折行）永远只
        报一行；``blockBoundingRect`` 是布局后的真实高度（含折行）。
        """
        document = self.document()
        # 文档宽度必须跟视口同步，否则 blockBoundingRect 按旧宽（或不定宽）
        # 排版，折行高度会被低估（长单段只报一两行）。
        width = self.viewport().width()
        if width > 0 and document.textWidth() != width:
            document.setTextWidth(width)
        layout = document.documentLayout()
        total = 0.0
        block = document.begin()
        while block.isValid():
            total += layout.blockBoundingRect(block).height()
            block = block.next()
        if total <= 0:
            total = max(1, document.blockCount()) * self.fontMetrics().lineSpacing()
        return int(total + 0.5) + 2 * self.frameWidth() + 4


class QuestionSegment(_ThemeAwareMixin, QWidget):
    """进度段（opencode 的 ``question-progress-segment``）。

    16×2px 圆角条 + 16px 命中盒，三态：**未答**（弱化）/ **已答**（强调）/
    **当前**（主文本色，最强 —— 对齐 opencode 的 CSS 覆盖顺序）。可点击跳题。
    """

    #: 用户点了第 ``index`` 道题
    jumped = pyqtSignal(int)

    def __init__(self, index: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self._index = int(index)
        self._active = False
        self._answered = False
        self.setFixedSize(SEGMENT_HIT, SEGMENT_HIT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"第 {index + 1} 个问题")

    def setState(self, active: bool, answered: bool) -> None:  # noqa: N802
        """设置三态。"""
        self._active = bool(active)
        self._answered = bool(answered)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.jumped.emit(self._index)
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._active:
            color = text_color(self._theme_mode)
        elif self._answered:
            color = accent_color(self._theme_mode)
        else:
            color = muted_color(self._theme_mode, 0.45)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        # 圆角 = 高度的一半 = 全圆角胶囊（``border-radius: 999px`` 的直译）
        radius = SEGMENT_BAR[1] / 2.0
        painter.drawRoundedRect(
            QRectF(
                0,
                (self.height() - SEGMENT_BAR[1]) / 2.0,
                SEGMENT_BAR[0],
                SEGMENT_BAR[1],
            ),
            radius,
            radius,
        )
        painter.end()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:  # noqa: N802
        self._theme_mode = mode
        self.update()


class QuestionOptionCard(QAbstractButton):
    """候选卡（opencode 的 ``question-option``）。

    整卡是一个点击目标：左侧 16px 自绘标记，右侧两行文字（**标题 14/500 +
    说明 14/400 弱化**）。选中态 = 底变色 + 描边透明 + 一圈强调色外发光
    （``paintRoundedCard(glow=...)``，QSS 表达不了外发光）。

    ``isCustom`` 时是「输入自己的答案」那一行 —— opencode 把它放在**列表最后
    一项**（不是独立控件）：折叠态显示占位符，点标记 / 点整行 / 按 ``Space``
    三者同义，都是**选中它 + 展开编辑器**（保持选中卡样式），编辑态里露出一个
    无边框自增高的输入框。标记在编辑态下仍可点（多选要能「再点一次 = 取消 +
    收起」）。

    **本控件是「纯输入面」**：它不认识单选/多选的状态机，只把「谁被激活了、
    从哪儿激活的」发出去，勾选状态由外层 :class:`~pyqt6_ela_pro.chat.blocks.
    PermissionCard` 的状态机算完再用 :meth:`setPicked` 灌回来。所以这里既没有
    ``setCheckable`` 也没有 ``autoExclusive``，``QAbstractButton`` 自带的
    ``clicked`` / ``toggled`` 一概不用。
    """

    #: 整行被激活（鼠标点行、Space；参数为选项 label，自定义行为空串）
    activate = pyqtSignal(str)
    #: 只点了左侧标记（自定义行用它「选中但不展开」；普通行与整行等价）
    markClicked = pyqtSignal(str)
    #: 自定义答案提交（参数：文本）
    editCommitted = pyqtSignal(str)
    #: 该行获得键盘焦点（参数：行号）
    rowFocused = pyqtSignal(int)
    #: 请求把焦点移到相邻行（``-1`` 上一行 / ``+1`` 下一行 / ``0`` 首行 / ``2`` 末行）
    moveFocus = pyqtSignal(int)
    #: 卡片级快捷键（参数：``"next"`` / ``"back"`` / ``"dismiss"`` /
    #: ``"digit:<n>"``）—— 由持有全部行的 :class:`~pyqt6_ela_pro.chat.blocks.
    #: PermissionCard` 统一处理
    #:
    #: **刻意用信号而不是 ``installEventFilter``**：焦点常驻在行上，键盘事件发给
    #: 行、不冒泡回卡片，所以卡片那一层确实拦不到；但给行装 Python 事件过滤器在
    #: 销毁期会踩 0xC0000409（实测：整个 chat 析构时静默终止，单独建控件正常、
    #: 把过滤器摘掉就正常）。信号没这个问题。
    globalKey = pyqtSignal(str)
    #: 本行**内容高度**变了（自定义答案输入框展开 / 收起）—— 外层据此重算选项区
    #: 高度。用信号而不是让外层轮询，是因为行高取决于文档行数，只有行自己知道。
    contentChanged = pyqtSignal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        value: str = "",
        description: str = "",
        multi: bool = False,
        isCustom: bool = False,
    ) -> None:
        super().__init__(parent)
        self._value = value or ""
        self._description = description or ""
        self._multi = bool(multi)
        self._is_custom = bool(isCustom)
        self._picked = False
        self._editing = False
        #: 本次按下是否落在勾选标记区（决定 release 是否再发 activate）
        self._press_on_mark = False
        self._row_index = 0
        self._theme_mode = eTheme.getThemeMode()
        self._colors = question_colors(self._theme_mode)

        # **刻意不开 checkable**：勾选状态的唯一真相是 :attr:`_picked`，由外层
        # ``PermissionCard`` 的状态机通过 :meth:`setPicked` 灌进来。开了
        # ``setCheckable(True)`` 就会多出 Qt 自己那份 ``checked`` 状态，而它永远
        # 是 False（本控件从不调 ``setChecked``）—— 于是每次点击都发
        # ``toggled(True)``，多选的「再点一下取消」直接失效，外发光也会与
        # Qt 的 checked 状态脱节。两套状态并存是这个控件最初的设计错误。
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 高度锁死成「内容高」：``Minimum`` 会让父布局把剩余空间全灌进来
        # （一行答案的输入框实测被撑到 91px），``Fixed`` 才是「你要多高给多高」。
        # sizeHint 随内容变，``updateGeometry`` 负责通知布局重新问。
        #
        # 说明文案可换行：``QAbstractButton`` 不把 ``heightForWidth`` 转发给
        # 自己的布局，所以 ``sizeHint`` 里按 ``fontMetrics().boundingRect``
        # 自己折行算高度，``resizeEvent`` 里 ``updateGeometry()`` 让布局在
        # 宽度确定后重新问一次（否则首次按「一行」定死，第二行被裁）。
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(*CARD_PADDING)
        row.setSpacing(MARK_GAP)
        # **勾选标记用 Ela 现有控件**（多选 -> ElaCheckBox，单选 -> ElaRadioButton）。
        # 不放文案（文案由右侧的 ColorText 负责，要两行且能换行）；不抢焦点
        # （NoFocus，焦点归整张卡）；不吃鼠标（点击由卡片的 mousePress 统一
        # 判断「点的是标记区还是整行」）。它自己从 eTheme 取色，21px 的密度也比
        # 手画的 16px 更贴近 Ela 其它控件。
        self._mark = ElaCheckBox(self) if self._multi else ElaRadioButton(self)
        self._mark.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._mark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._mark.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._mark.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row.addWidget(self._mark, 0, Qt.AlignmentFlag.AlignVCenter)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(1)
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(True)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        texts.addWidget(self._label)
        self._desc = ColorText(self)
        self._desc.setTextFormat(Qt.TextFormat.PlainText)
        self._desc.setWordWrap(True)
        self._desc.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        texts.addWidget(self._desc)
        row.addLayout(texts, 1)
        self._editor = None
        #: 编辑器尚未创建时的待回填文本（草稿 / 已提交的自定义答案）。
        #: ``setEditorText`` 在编辑器懒创建（首次 ``setEditing(True)``）之前
        #: 只能把文本存这里，否则每次重建都会静默丢掉草稿。
        self._pending_editor_text = ""
        self._texts_layout = texts
        self._apply_content()
        self._apply_theme()

    # -- 数据 --------------------------------------------------------------

    def value(self) -> str:
        """选项 label（自定义行为空串）。"""
        return self._value

    def description(self) -> str:
        """选项说明。"""
        return self._description

    def isCustom(self) -> bool:  # noqa: N802
        """是否是「输入自己的答案」那一行。"""
        return self._is_custom

    def isMulti(self) -> bool:  # noqa: N802
        """是否多选（决定 radio / checkbox）。"""
        return self._multi

    def isPicked(self) -> bool:  # noqa: N802
        """是否选中。"""
        return self._picked

    def isEditing(self) -> bool:  # noqa: N802
        """是否处于自定义答案编辑态。"""
        return self._editing

    def rowIndex(self) -> int:  # noqa: N802
        """行号（供方向键导航）。"""
        return self._row_index

    def setRowIndex(self, index: int) -> None:  # noqa: N802
        """设置行号。"""
        self._row_index = int(index)

    def setPicked(self, picked: bool) -> None:  # noqa: N802
        """设置选中态（**不发** ``activate``，避开自检回环）。

        标记子控件的 ``checkState`` 是被**灌**进去的（``setChecked``），不是它
        自己算出来的 —— 它连 ``toggled`` 都没接，勾选真相仍然只有
        :attr:`_picked` 一份。
        """
        if self._picked == bool(picked):
            return
        self._picked = bool(picked)
        self._mark.setChecked(self._picked)
        self.update()
        self._apply_theme()

    def setEditing(self, editing: bool) -> None:  # noqa: N802
        """进入 / 退出自定义答案编辑态（编辑中**保持选中卡样式**）。"""
        if not self._is_custom:
            return
        editing = bool(editing)
        if editing and self._editor is None:
            self._editor = _AutoGrowEditor(self)
            self._editor.setFrameShape(QFrame.Shape.NoFrame)
            self._editor.setPlaceholderText(CUSTOM_ANSWER_PLACEHOLDER)
            self._editor.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._editor.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._editor.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
            )
            self._editor.textChanged.connect(self._on_editor_changed)
            # 文档排版完成（折行高度变化）后再同步一次：``textChanged`` 触发时
            # 布局往往还没更新，只靠那一次会把行高压在旧值上。
            self._editor.document().documentLayout().documentSizeChanged.connect(
                lambda *_: self._schedule_height_sync()
            )
            # 按键语义走编辑器自己的信号（见 _AutoGrowEditor 的说明），
            # 不给这个会被随行销毁的子控件装 Python 事件过滤器。
            self._editor.submitRequested.connect(self.commitEdit)
            self._editor.dismissRequested.connect(self._on_editor_dismissed)
            self._editor.advanceRequested.connect(self._on_editor_advance)
            self._texts_layout.addWidget(self._editor)
            if self._pending_editor_text:
                self._editor.setPlainText(self._pending_editor_text)
        self._editing = editing
        if self._editor is not None:
            self._editor.setVisible(editing)
        if editing:
            self._editor.setFocus()
        self._apply_content()
        self.updateGeometry()
        self._schedule_height_sync()
        self.contentChanged.emit()

    def editorText(self) -> str:  # noqa: N802
        """自定义答案当前文本（编辑器未创建时返回待回填文本）。"""
        if self._editor is not None:
            return self._editor.toPlainText()
        return self._pending_editor_text

    def setEditorText(self, text: str) -> None:  # noqa: N802
        """回填自定义答案（切题回来时恢复草稿；编辑器懒创建前先暂存）。"""
        text = text or ""
        self._pending_editor_text = text
        if self._editor is None:
            return
        if self._editor.toPlainText() != text:
            self._editor.setPlainText(text)

    def commitEdit(self) -> None:  # noqa: N802
        """提交自定义答案（Enter；卡片在「下一步 / 提交 / 切题」前也会先调它）。

        **空文本什么都不做**；非空文本**不要求行处于编辑态** —— Esc 退出编辑
        但保留了文本，此时点「下一步 / 提交」也必须把它算成答案（早期实现要求
        ``self._editing``，Esc 后那段字会被静默丢弃，payload 里没有这一题）。
        """
        if self._editor is None:
            return
        text = self.editorText().strip()
        if not text:
            return
        self.editCommitted.emit(text)

    def _on_editor_dismissed(self) -> None:
        """编辑器按 Esc：退出编辑但保留文本（不能冒泡成「忽略整个问题」）。"""
        self.setEditing(False)
        self.setFocus()

    def _on_editor_advance(self) -> None:
        """编辑器按 Ctrl+Enter：转成整卡的「下一步 / 提交」。"""
        self.globalKey.emit("next")

    # -- 交互 --------------------------------------------------------------

    def _mark_rect(self) -> QRectF:
        """标记的命中区（直接取子控件几何，标记尺寸变了也不用改这里）。"""
        return QRectF(self._mark.geometry())

    def markWidget(self) -> QWidget:  # noqa: N802
        """勾选标记控件（``ElaRadioButton`` / ``ElaCheckBox``）。"""
        return self._mark

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """点左侧标记 = 只切勾选；点其余 = 整行激活（自定义行即展开编辑器）。

        **编辑态下标记仍然可点**：多选要能「再点一次标记 = 取消自定义勾选并收起
        输入框」（对齐 opencode —— 标记在那个 ``<form>`` 里，编辑时照样点得到）。
        行内其它位置（标签 / 说明）则把焦点**还给编辑器**：走 ``super()`` 会让
        ``QAbstractButton`` 抢走焦点，随后按 Enter 落到行上等于什么都没发生。
        """
        if self._mark_rect().contains(event.position()):
            self._press_on_mark = True
            self.markClicked.emit(self._value)
            event.accept()
            return
        if self._editing:
            if self._editor is not None:
                self._editor.setFocus()
            event.accept()
            return
        self._press_on_mark = False
        QAbstractButton.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        # 不用 super：``QAbstractButton`` 在这里只会发 ``clicked``（我们不用），
        # 而且它要求 press 走过 ``super``，我们上面是**故意**不走的（标记区要
        # 截断），走 ``super().mouseReleaseEvent`` 会在没 press 过的情况下也算
        # 一次点击，白白多发一轮 activate。
        if self._press_on_mark:
            # 标记区的按下已经在 press 里发过 ``markClicked``，同一手势的 release
            # 绝不能再发 ``activate``（否则普通行两次切换互相抵消、自定义行会
            # 被连带展开编辑器）。Qt 的隐式 grab 保证 release 一定回到本控件。
            self._press_on_mark = False
            return
        if not self._editing and self.rect().contains(event.position().toPoint()):
            self.activate.emit(self._value)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self.rowFocused.emit(self._row_index)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """键盘操作（编辑态一律让给编辑器）。

        - ``Ctrl+⏎`` / ``Alt+←`` / ``Esc`` / ``1``–``9`` —— 转成
          :attr:`globalKey` 交给外层（它们是**整张卡**的语义，单行无权决定）；
        - ``↑ ↓ ← →`` / ``Home`` / ``End`` —— 在行之间移动焦点（左右键与上下键
          等价，因为这是纵向列表）；
        - ``Space`` —— 切换勾选（对齐 opencode 的 "Toggle answer"）。
        """
        key = event.key()
        if self._editing:
            return QAbstractButton.keyPressEvent(self, event)
        mods = event.modifiers()
        if self._emit_global_key(key, mods):
            event.accept()
            return
        if mods & (
            Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.MetaModifier
        ):
            return QAbstractButton.keyPressEvent(self, event)
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Right):
            self.moveFocus.emit(1)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Left):
            self.moveFocus.emit(-1)
        elif key == Qt.Key.Key_Home:
            self.moveFocus.emit(0)
        elif key == Qt.Key.Key_End:
            self.moveFocus.emit(2)
        elif key == Qt.Key.Key_Space:
            # 自定义行：Space 走「切勾选」而不是「展开编辑器」，Enter 才展开
            self.markClicked.emit(self._value)
        else:
            return QAbstractButton.keyPressEvent(self, event)
        event.accept()

    def _emit_global_key(self, key, mods) -> bool:
        """把卡片级快捷键转成 :attr:`globalKey`；返回是否消费。"""
        action = globalKeyAction(key, mods)
        if action is None:
            return False
        self.globalKey.emit(action)
        return True

    def _on_editor_changed(self) -> None:
        """编辑器内容变化：收起占位文案 + 请布局重新问一次高度。

        **绝不能在这里直接改控件几何**（``setFixedHeight`` 之类）—— 那是在
        ``textChanged`` 槽里重入布局失效，Qt 直接 0xC0000409 静默终止。自增高
        由 :class:`_AutoGrowEditor` 的 ``sizeHint`` 负责，这里只发
        ``updateGeometry``（单向的 LayoutRequest，不动几何）。
        """
        if self._editor is None:
            return
        self._apply_content()
        self.updateGeometry()
        # 行高由内容决定，但布局不会自己重新问 sizeHint（实测 updateGeometry
        # 在嵌套布局里不生效）。延到下一轮事件循环再定高，避免在 textChanged
        # 槽里同步改几何（重入布局 = 0xC0000409）。
        self._schedule_height_sync()
        self.contentChanged.emit()

    # -- 外观 --------------------------------------------------------------

    def _apply_content(self) -> None:
        if self._is_custom:
            self._label.setText(CUSTOM_ANSWER_LABEL)
            # 编辑态下让位给输入框（它自带 placeholder），不再重复显示一遍
            if self._editing:
                self._desc.setText("")
            else:
                self._desc.setText(
                    CUSTOM_ANSWER_PLACEHOLDER
                    if not self.editorText()
                    else self.editorText()
                )
        else:
            self._label.setText(self._value)
            self._desc.setText(self._description)
        self._desc.setVisible(bool(self._desc.text()))

    def applyTheme(self, mode) -> None:  # noqa: N802
        """换主题（由 :class:`~pyqt6_ela_pro.chat.blocks.PermissionCard` 派发）。

        **只改颜色，不碰内容**。文案与主题无关，而 ``_apply_content()`` 会连带
        ``setEditorText()`` —— 那是一次无谓的文本写入，在「行已销毁但 Python 包装
        器还在」的时机下会直接踩进已释放的编辑器（0xC0000409 静默终止）。内容
        只在 :meth:`setEditing` / :meth:`_on_editor_changed` 里更新。
        """
        self._theme_mode = mode
        self._colors = question_colors(mode)
        self._apply_theme()
        self.update()

    def _apply_theme(self) -> None:
        colors = self._colors
        self._label.setTextColor(colors["ink"])
        self._label.setTextPixelSize(13)
        # 常规字重：题面（14/DemiBold）才是该被强调的那一行，候选标题再加粗
        # 就会和它抢层级、整片糊在一起
        self._label.setTextWeight(QFont.Weight.Normal)
        self._desc.setTextColor(colors["muted"])
        self._desc.setTextPixelSize(12)
        self._apply_editor_theme(colors)

    def _apply_editor_theme(self, colors: dict) -> None:
        """给自定义答案输入框上色（**只能走 palette**）。

        ``ElaPlainTextEdit`` **没有** ``setTextColor``（实测 ``AttributeError``）。
        而这行原本就写在 ``_apply_theme`` 里 —— 也就是**主题切换的信号链上**，
        于是切一次主题就 Qt 回调内抛异常 = 0xC0000409 静默终止（无 traceback）。

        ``QPlainTextEdit`` 不像 ``ElaText`` 那样在 ``paintEvent`` 里重置 palette，
        所以这里设的色**能留住**（实测 ``setPlainText`` 之后仍是同一个值），
        不需要 ``ColorText`` 那套绘制前自愈。
        """
        if self._editor is None:
            return
        palette = self._editor.palette()
        role = self._editor.foregroundRole()
        palette.setColor(role, colors["muted"])
        self._editor.setPalette(palette)

    def paintEvent(self, _event) -> None:  # noqa: N802
        """自绘卡片底 / 描边 / 外发光。

        **标记不在这里画** —— 那是 :class:`ElaCheckBox` / :class:`ElaRadioButton`
        子控件自己的事（自绘一份只会和它的 ``ElaCheckBoxStyle`` 打架，而且
        「未选中」时两种模式画得一模一样，分不出单选/多选）。
        文字同样走子控件（``ColorText``）：换行、主题、字体回退都交给它，我们只
        负责卡片的「壳」。
        """
        colors = self._colors
        enabled = self.isEnabled()
        if self._picked:
            background = colors["picked"]
            border = QColor(0, 0, 0, 0)
            glow = colors["glow"]
        elif self.underMouse():
            # opencode：``:hover:not([data-picked]) { background-color: bg-base }``
            background = colors["card_hover"]
            border = colors["border"]
            glow = None
        else:
            # 默认态**保留一圈极淡描边**（opencode 的
            # ``border: .5px solid border-base``）。全去掉的话几行底色会连成一片
            # 灰带，行与行之间没有任何分隔 —— 那才是「又高又乱」的真正来源；
            # 「太高」要靠压 padding 解决，不是靠删描边。
            background = colors["card"]
            border = colors["border"]
            glow = None
        if not enabled:
            background = QColor(background)
            background.setAlphaF(background.alphaF() * 0.5)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paintRoundedCard(
            painter,
            QRectF(self.rect()),
            background=background,
            border=border,
            radius=CARD_RADIUS,
            glow=glow,
        )
        painter.end()

    def _comfortable_minimum(self) -> int:
        """**单行**候选行的舒适高度下限（从字体度量算，不写死像素）。

        两行（标题 + 说明）时不需要下限 —— 内容自己就够高。只有标题时
        自然高只有「一行 + 上下 padding」，实测约 26px，点选目标偏小，
        才需要一个下限。

        **别写死 44**：字体度量是平台相关的。实测 windows 上「标题 13px +
        说明 12px + 1px 间距 + 上下 4px」的自然高已经是 43px，下限 44 会
        比布局需要高 1px；每行多 1px 累积起来让整张问题卡比自己的
        ``sizeHint`` 矮 19px（``TestLayoutContract::test_card_gets_its_size_hint``：
        卡片 249px vs sizeHint 268px、dock 265px vs 284px）。而在 offscreen 上
        字体度量小得多（行高 16→12），写死的 44 又是凭空多出 8px。
        """
        if self._desc.isVisible() or self._description:
            return 0
        fm = self._label.fontMetrics()
        return round(fm.height() * 2.0) + CARD_PADDING[1] + CARD_PADDING[3]

    def sizeHint(self) -> QSize:  # noqa: N802
        """行高 = 折行后的自然高（有下限保底）+ （编辑态）编辑器高度。

        ``QAbstractButton`` 不把 ``heightForWidth`` 转发给自己的布局，光靠 Qt
        只会在首次（行宽还是 0）按「一行」定死，说明折两行时第二行被裁 ——
        所以 ``resizeEvent`` 里发 ``updateGeometry()``，行宽一确定就让布局
        重新问一次（``sizeHint`` 里的自然高取自布局/子标签，此时宽度已知）。
        高度变化不会反过来改宽度，不会震荡。

        **必须显式把编辑器算进来**：``QAbstractButton.sizeHint()`` 只认 Qt 自己
        的 ``text + icon`` 尺寸，完全看不见布局里那个 ``_AutoGrowEditor``，
        于是父布局不会为它让位，用户用 Shift+Enter 敲的第二行被裁掉。
        """
        hint = super().sizeHint()
        base = max(hint.height(), self._comfortable_minimum())
        if self._editor is not None and self._editing:
            base += self._editor.sizeHint().height()
        return QSize(hint.width(), base)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # 宽度变了 → 折行行数可能变 → 下一轮按新宽度重算行高。
        self.updateGeometry()
        self._schedule_height_sync()

    def _schedule_height_sync(self) -> None:
        """下一轮事件循环把行高钉到 ``sizeHint``（布局不会自己重问）。"""
        single_shot_on(self, 0, self._sync_height)

    def _sync_height(self) -> None:
        if is_deleted(self):
            return
        if self._editor is not None:
            if self._editing:
                # 外层布局不会把编辑器撑到它的 sizeHint（Minimum 策略只保证
                # 下限），必须显式钉住；否则多行 / 折行答案只露出一部分。
                editor_height = max(24, self._editor.sizeHint().height())
                if self._editor.height() != editor_height or (
                    self._editor.minimumHeight() != editor_height
                ):
                    self._editor.setFixedHeight(editor_height)
            else:
                self._editor.setMinimumHeight(0)
                self._editor.setMaximumHeight(16777215)
        target = max(1, self.sizeHint().height())
        if target == self.height() and self.minimumHeight() == target:
            return
        self.setFixedHeight(target)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        # 宽度给 0：候选行要能换行（说明文案长度不定），横向上不许比 sizeHint 更宽
        return QSize(0, self.sizeHint().height())
