"""插话回执、压缩分隔卡与错误卡。（``pyqt6_ela_pro.chat`` 内部模块）。"""

from __future__ import annotations


from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
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
    ElaScrollPageArea,
    ElaText,
    ElaThemeType,
    eTheme,
)

from ..._internal import _ThemeAwareMixin
from ..._styles import ColorText, setSolidBackground
from ..._theme import ElaStatusRoleType, statusColor
from .._theme import (
    base_color,
    blend,
    muted_color,
    text_color,
)
from ..message import (
    ElaChatStatusType,
)
from ..toolbar import ElaChatToolBar
from ._helpers import PREVIEW_MAX_CHARS, RETRYABLE_ERROR_TYPES


class SteerNotice(_ThemeAwareMixin, QWidget):
    """插话回执行（``kind == Synthetic``）。

    渲染成一条极简的左竖线 + ``↳ <文本>``。**刻意不插一条用户气泡** ——
    助手消息正在流式输出，中途插一条用户消息视觉上很怪（opencode 就是那么
    做的，产物是时间线上「助手话说到一半、下面冒出一条用户消息」）。改成在
    同一条助手消息内追加一行旁注，语义是「插话已送达」，视觉连续，且随消息
    一起持久化。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self._text = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        self._rail = QWidget(self)
        self._rail.setFixedWidth(2)
        layout.addWidget(self._rail, 0, Qt.AlignmentFlag.AlignVCenter)
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._label, 1)
        self._apply_theme()

    def setText(self, text: str) -> None:
        """设置回执文本。"""
        self._text = text or ""
        self._label.setText(f"↳ {self._text}" if self._text else "")

    def text(self) -> str:
        """获取回执文本（不含 ``↳`` 前缀）。"""
        return self._text

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        setSolidBackground(self._rail, muted_color(mode, 0.4))
        self._label.setTextColor(muted_color(mode, 0.7))
        self._label.setTextPixelSize(12)
        self._label.setTextFormat(Qt.TextFormat.PlainText)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()


class CompactionSeparator(_ThemeAwareMixin, ElaScrollPageArea):
    """上下文压缩分隔卡（``kind == Compaction``）。

    「历史已被摘要替代」这件事**必须在时间线上如实表达**，否则用户看到的是
    一条断层：模型突然「忘了」前面说过什么。渲染成一条虚线 + 说明 + 可折叠
    的摘要正文（对齐 opencode ``SessionCompactionMessage``）。

    **库不实现压缩算法**：``SHRINK_STEPS`` 收缩循环 / 摘要模板 / 词元估算
    / transcript 边界全在 provider 抽象那一侧，超出 UI 库范围。本卡片只负责
    「能表达 + 能持久化」—— 压不压、压哪段、摘要怎么来由宿主决定。
    """

    #: 展开 / 收起摘要
    toggled = pyqtSignal(bool)

    #: 分隔文案模板（``{count}`` 会被替换成被压缩的历史条数）
    LABEL_TEMPLATE = "已压缩 {count} 条历史"
    #: **调用方没给条数时**用的文案。
    #:
    #: 绝不能写「已压缩 0 条历史」—— ``historyCount`` 默认 0 是「不知道」的意思，
    #: 不是「真的压了 0 条」。照实说，模型才不会被一条自相矛盾的时间线带偏
    #: （实测截图里就是一行「已压缩 0 条历史」）。
    LABEL_NO_COUNT = "已压缩历史"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setBorderRadius(8)
        self._summary = ""
        self._count = 0
        self._status = ElaChatStatusType.Done
        self._body_built = False
        # **显式记展开态**，不要从 ``self._body.isVisible()`` 反推：控件还没被
        # show 过时 ``isVisible()`` 恒为 False（跟父链可见性走），反推出来的
        # 「展开了吗」在离屏测试与真实挂载前都是错的。
        self._opened = False
        self._summary_label: Optional[ElaText] = None
        self._preview: Optional[ColorText] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        self._header = QHBoxLayout()
        self._header.setContentsMargins(0, 0, 0, 0)
        self._header.setSpacing(6)
        self._icon = ElaIconButton(ElaIconType.IconName.BoxArchive, 12, 16, 16, self)
        self._icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._header.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._header.addWidget(self._label, 1)
        self._chevron = ElaIconButton(
            ElaIconType.IconName.ChevronRight, 12, 16, 16, self
        )
        self._chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._header.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(self._header)
        # 折叠态的摘要首行。整张卡折叠着也要能回答「到底压掉了什么」——
        # 只留一行「已压缩 N 条历史」+ 箭头等于什么都没说（对齐 opencode 的
        # ``SessionCompactionMessage``：分隔条下面就是摘要正文）。
        self._preview = ColorText(self)
        self._preview.setTextFormat(Qt.TextFormat.PlainText)
        self._preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._preview.hide()
        layout.addWidget(self._preview)
        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        layout.addWidget(self._body)
        self._body.hide()
        # 整卡可点开关摘要（点标题行 / 图标 / 箭头都行）
        self._header_label = self._label
        for widget in (self._label, self._icon, self._chevron):
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label.mousePressEvent = self._toggle_from_header  # type: ignore[method-assign]
        self._icon.mousePressEvent = self._toggle_from_header  # type: ignore[method-assign]
        self._chevron.mousePressEvent = self._toggle_from_header  # type: ignore[method-assign]
        self._apply_theme()

    # -- 数据 --------------------------------------------------------------

    def setSummary(self, summary: str) -> None:
        """设置摘要文本。"""
        self._summary = summary or ""
        if self._body_built and self._summary_label is not None:
            self._summary_label.setText(self._summary)
        self._sync_preview()

    @staticmethod
    def _preview_text(summary: str) -> str:
        """折叠态那一行：摘要的首行，超长截断。

        ``ColorText`` 不按宽度省略（``ElaText.sizeHint`` 无视 ``wordWrap``），
        所以只能自己按字符数截，省略号自己加。
        """
        for line in (summary or "").splitlines():
            line = line.strip()
            if line:
                return (
                    line
                    if len(line) <= PREVIEW_MAX_CHARS
                    else (line[: PREVIEW_MAX_CHARS - 1] + "…")
                )
        return ""

    def _sync_preview(self) -> None:
        if self._preview is None:
            return
        text = self._preview_text(self._summary)
        self._preview.setText(text)
        # 展开后正文已经全露出来了，预览行就没必要重复
        self._preview.setVisible(bool(text) and not self._opened)

    def summary(self) -> str:
        """获取摘要文本。"""
        return self._summary

    def setHistoryCount(self, count: int) -> None:
        """设置被压缩的历史条数（只影响文案）。"""
        try:
            self._count = max(0, int(count))
        except (TypeError, ValueError, OverflowError):
            self._count = 0
        self._sync_label()

    def historyCount(self) -> int:
        """获取被压缩的历史条数。"""
        return self._count

    def setCompactionStatus(self, status: str) -> None:
        """设置压缩状态（``streaming`` 时标题追加「进行中」）。"""
        self._status = status or ElaChatStatusType.Done
        self._sync_label()

    def setOpened(self, opened: bool) -> None:
        """展开 / 收起摘要。"""
        if opened:
            self._build_body()
        self._opened = bool(opened)
        self._body.setVisible(self._opened)
        self._sync_preview()
        self._chevron.setAwesome(
            ElaIconType.IconName.ChevronDown
            if opened
            else ElaIconType.IconName.ChevronRight
        )
        if self.layout() is not None:
            self.layout().activate()
        self.updateGeometry()
        self.toggled.emit(bool(opened))

    def opened(self) -> bool:
        """摘要是否展开（读的是显式状态，与是否已 show 无关）。"""
        return self._opened

    def _toggle_from_header(self, _event=None) -> None:
        self.setOpened(not self._opened)

    def _build_body(self) -> None:
        if self._body_built:
            return
        self._body_built = True
        self._summary_label = ColorText(self._body)
        self._summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._body_layout.addWidget(self._summary_label)
        self._summary_label.setText(self._summary)
        self._apply_theme()

    def _sync_label(self) -> None:
        text = (
            self.LABEL_TEMPLATE.format(count=self._count)
            if self._count > 0
            else self.LABEL_NO_COUNT
        )
        if self._status == ElaChatStatusType.Streaming:
            text = f"{text} · 压缩中…"
        elif self._status == ElaChatStatusType.Error:
            text = f"{text} · 压缩失败"
        self._label.setText(text)

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        self._label.setTextColor(muted_color(mode, 0.7))
        self._label.setTextPixelSize(12)
        self._icon.setLightIconColor(muted_color(mode, 0.5))
        self._icon.setDarkIconColor(muted_color(mode, 0.5))
        self._chevron.setLightIconColor(muted_color(mode, 0.5))
        self._chevron.setDarkIconColor(muted_color(mode, 0.5))
        if self._preview is not None:
            self._preview.setTextColor(muted_color(mode, 0.62))
            self._preview.setTextPixelSize(12)
        if self._summary_label is not None:
            self._summary_label.setTextColor(muted_color(mode, 0.8))
            self._summary_label.setTextPixelSize(12)
            self._summary_label.setTextFormat(Qt.TextFormat.PlainText)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()


class ErrorCard(_ThemeAwareMixin, ElaScrollPageArea):
    """错误卡片（左 danger 竖线 + 图标 + 标题 + 详情 + 动作区）。

    动作区（**手动重试**，对齐 opencode 的 ``session-retry.tsx``）按错误类型
    点亮：

    - 「重试」—— 同参数重发。仅 :data:`RETRYABLE_ERROR_TYPES` 里的类型
      有意义（限流 / 超时 / 网络 / 5xx 这类**换次机会大概率会成功**的错误）；
      参数错误、鉴权失败、内容过滤这类重试只会再失败一次，不给按钮；
    - 「重新生成」—— 换采样重来，对任何错误都有意义，恒显示（复用气泡
      底部已有的 ``regenerateRequested`` 通道，不另开一条）。

    两个动作都只发信号，**不自己发请求** —— 后端怎么重试是宿主的事。
    """

    #: 点击「重试」（由气泡转发成 view / widget 的 ``retryRequested``）
    retryRequested = pyqtSignal()
    #: 点击「重新生成」（与气泡底部同一个语义）
    regenerateRequested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setBorderRadius(8)
        self._message = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 8, 10, 8)
        layout.setSpacing(8)
        self._rail = QWidget(self)
        self._rail.setFixedWidth(2)
        layout.addWidget(self._rail)
        self._icon = ElaIconButton(
            ElaIconType.IconName.TriangleExclamation, 14, 18, 18, self
        )
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        self._title = ColorText("出错了", self)
        self._label = ColorText(self)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        texts.addWidget(self._title)
        texts.addWidget(self._label)
        layout.addLayout(texts, 1)
        #: 错误类型（决定哪些动作可用；见 :meth:`setMessage`）
        self._error_type = ""
        #: 动作区（默认隐藏，无可用动作时不占位）
        self._actions = ElaChatToolBar(self)
        self._actions.setCompact(True)
        self._actions.setVisible(False)
        layout.addWidget(self._actions, 0, Qt.AlignmentFlag.AlignBottom)
        self.hide()
        self._apply_theme()

    def setMessage(self, message: str, errorType: str = "") -> None:
        """设置错误文本与类型（空文本则隐藏整张卡）。

        :param message: 面向用户的错误文本
        :param errorType: 错误类型（``"RateLimit"`` / ``"Timeout"`` / ...）。
            **只用于决定动作可用性，不拼进文案** —— 早期实现把它格式化成
            ``"[TypeError] ..."`` 塞进 message，类型就此丢失，宿主无法据此
            点亮「重试」还是「换个模型重试」。

        动作区按类型给（:data:`RETRYABLE_ERROR_TYPES` 命中 -> 点亮「重试」，
        任何类型都点亮「重新生成」）；两个都不可用时动作区隐藏。
        """
        self._message = message or ""
        self._error_type = str(errorType or "")
        if not self._message:
            self.hide()
            return
        self._label.setText(self._message)
        self._sync_actions()
        self.show()

    def message(self) -> str:
        """获取错误文本。"""
        return self._message

    def errorType(self) -> str:
        """获取错误类型。"""
        return self._error_type

    def canRetry(self) -> bool:
        """该错误是否可原地重试（同参数重发）。"""
        return self._error_type.lower() in RETRYABLE_ERROR_TYPES

    def _sync_actions(self) -> None:
        """按错误类型刷新动作区（无动作则隐藏，不留空占位）。"""
        self._actions.clear()
        if self.canRetry():
            self._actions.addButton(
                icon=ElaIconType.IconName.RotateRight,
                tooltip="重试",
                key="retry",
                callback=self.retryRequested.emit,
            )
        # 「重新生成」对任何错误都有意义（换采样重来），所以恒有
        if self._message:
            self._actions.addButton(
                icon=ElaIconType.IconName.RotateLeft,
                tooltip="重新生成",
                key="regenerate",
                callback=self.regenerateRequested.emit,
            )
        self._actions.setVisible(self._actions.count() > 0)

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        danger = statusColor(mode, ElaStatusRoleType.Error)
        base = base_color(mode)
        text = text_color(mode)
        setSolidBackground(self._rail, danger)
        self._title.setTextColor(blend(text, danger, 0.35))
        self._title.setTextPixelSize(12)
        self._title.setTextWeight(QFont.Weight.DemiBold)
        self._label.setTextColor(muted_color(mode, 0.75))
        self._label.setTextPixelSize(12)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._icon.setLightIconColor(blend(base, danger, 0.4))
        self._icon.setDarkIconColor(blend(base, danger, 0.4))

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()
