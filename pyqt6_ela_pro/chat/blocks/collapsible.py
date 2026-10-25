"""可折叠区块基类、思考块与思考行。（``pyqt6_ela_pro.chat`` 内部模块）。"""

from __future__ import annotations


from typing import Optional

from ..._internal import is_deleted
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QFont,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconButton,
    ElaIconType,
    ElaProgressRing,
    ElaScrollPageArea,
    ElaText,
    ElaThemeType,
    eTheme,
)

from ..._internal import _ThemeAwareMixin
from ..._styles import BareButton, ColorText
from ...widget_base import ElaThemeWidget
from .._theme import (
    muted_color,
    text_color,
)
from ._helpers import REASONING_FLUSH_INTERVAL_MS


class _CollapsibleBlock(_ThemeAwareMixin, ElaScrollPageArea):
    """可折叠区块（``ElaScrollPageArea`` 圆角卡面 + ``ElaIconButton`` 箭头）。

    ``setSurfaceVisible(False)`` 可关闭卡面绘制（思考块等内联场景）。
    """

    #: 展开状态变化（参数：是否展开）
    toggled = pyqtSignal(bool)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        title: str = "",
        opened: bool = True,
        surface: bool = True,
    ) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        # ElaScrollPageArea 构造时 setFixedHeight(75)，卡片需按内容自适应
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setBorderRadius(8)
        self._title = title or ""
        self._surface = bool(surface)
        self._expandable = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(4)

        self._header = BareButton(self)
        self._header.setFlat(True)
        self._header.setCheckable(True)
        self._header.setChecked(bool(opened))
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_layout = QHBoxLayout(self._header)
        self._header_layout.setContentsMargins(0, 0, 0, 0)
        self._header_layout.setSpacing(6)
        self._chevron = ElaIconButton(
            ElaIconType.IconName.ChevronRight, 12, 16, 16, self
        )
        self._chevron.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chevron.setBorderRadius(4)
        self._title_label = ColorText(self)
        self._title_label.setWordWrap(False)
        # 折叠块标题含外部数据（工具名 / 审批 action）—— 一律纯文本渲染
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        #: 运行指示按需创建：历史消息里 99% 的折叠块从没运行过，构造期就建
        #: ``ElaProgressRing``（含两套 QPropertyAnimation）是纯浪费。
        self._busy: Optional[ElaProgressRing] = None
        self._busy_on = False
        self._header_layout.addWidget(self._chevron)
        self._header_layout.addWidget(self._title_label)
        self._header_layout.addStretch(1)

        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(22, 0, 0, 0)
        self._body_layout.setSpacing(4)
        self._body.setVisible(bool(opened))

        layout.addWidget(self._header)
        layout.addWidget(self._body)

        self._header.toggled.connect(self._on_toggled)
        self._sync_chevron()
        self._apply_theme()

    # -- 内容 --------------------------------------------------------------

    def setTitle(self, text: str) -> None:
        """设置标题文本。"""
        self._title = text or ""
        self._title_label.setText(self._title)

    def title(self) -> str:
        """获取标题文本。"""
        return self._title

    def setOpened(self, opened: bool) -> None:
        """展开 / 收起内容区（不可展开时忽略）。"""
        if not self._expandable and opened:
            return
        self._header.setChecked(bool(opened))

    def setOpenedSilently(self, opened: bool) -> None:
        """设置展开态但**不触发** toggled / 祖先布局链（恢复历史用）。

        恢复时每块都 ``setOpened(True)`` → ``setOpened(False)`` 会触发
        ``_relayoutAncestors``（最多 32 层）与 ``toggled`` 信号；几千个块累计
        上万次布局激活，纯属浪费。最终态由 ``setParts`` 收尾统一激活一次。
        """
        self._header.blockSignals(True)
        try:
            self._header.setChecked(bool(opened))
        finally:
            self._header.blockSignals(False)
        self._body.setVisible(bool(opened))
        self._sync_chevron()

    def isOpened(self) -> bool:
        """内容区是否展开。"""
        return self._header.isChecked()

    def setExpandable(self, on: bool) -> None:
        """设置是否允许展开（pending 工具锁定）。"""
        self._expandable = bool(on)
        self._chevron.setVisible(self._expandable)
        if not self._expandable:
            self._header.setChecked(False)
        self._header.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self._expandable
            else Qt.CursorShape.ArrowCursor
        )

    def isExpandable(self) -> bool:
        """是否允许展开。"""
        return self._expandable

    def setBusy(self, on: bool) -> None:
        """显示 / 隐藏运行中指示（``ElaProgressRing``）。

        关闭时必须 ``setIsBusying(False)``：``ElaProgressRing`` 的动画由
        ``IsBusying`` 驱动，仅隐藏控件会留下两个 QPropertyAnimation 永久
        空转（每个已完成的工具卡都会泄漏）。控件本身按需创建。
        """
        on = bool(on)
        self._busy_on = on
        if on:
            if self._busy is None:
                ring = ElaProgressRing(self)
                ring.setFixedSize(14, 14)
                ring.setIsTransparent(True)
                ring.setBusyingWidth(2)
                ring.hide()
                self._busy = ring
                self._header_layout.insertWidget(1, ring)
            self._busy.setIsBusying(True)
            self._busy.show()
            return
        if self._busy is not None:
            self._busy.setIsBusying(False)
            self._busy.hide()

    def isBusy(self) -> bool:
        """是否处于运行中状态（与父链可见性无关）。"""
        return self._busy_on

    def bodyLayout(self) -> QVBoxLayout:
        """获取内容区布局（向其添加自定义内容）。"""
        return self._body_layout

    def bodyWidget(self) -> QWidget:
        """获取内容区容器。"""
        return self._body

    def headerButton(self) -> QPushButton:
        """获取标题按钮句柄。"""
        return self._header

    def headerLayout(self) -> QHBoxLayout:
        """获取标题行布局（供子类插入图标 / 副标题 / 参数）。"""
        return self._header_layout

    def insertHeaderWidget(self, index: int, widget: QWidget) -> None:
        """在标题行指定位置插入控件。"""
        self._header_layout.insertWidget(index, widget)

    def setSurfaceVisible(self, on: bool) -> None:
        """显示 / 隐藏卡面背景。"""
        self._surface = bool(on)
        self.update()

    def surfaceVisible(self) -> bool:
        """卡面背景是否显示。"""
        return self._surface

    def setCardMargins(self, left: int, top: int, right: int, bottom: int) -> None:
        """调整卡片内边距（内联场景可收紧）。"""
        self.layout().setContentsMargins(left, top, right, bottom)

    def _on_toggled(self, checked: bool) -> None:
        if not self._expandable and checked:
            self._header.setChecked(False)
            return
        self._body.setVisible(bool(checked))
        self._sync_chevron()
        if self.layout() is not None:
            self.layout().activate()
        self.updateGeometry()
        self._relayoutAncestors()
        self.toggled.emit(bool(checked))

    def _relayoutAncestors(self) -> None:
        """同步刷新祖先布局链。

        Qt 的布局失效（``updateGeometry``）会逐级投递 ``LayoutRequest``，
        每层在独立的事件循环轮次里重排：展开 / 收起工具卡时表现为内容分
        2-3 帧逐级收缩，肉眼可见「抖动」。这里从自身向上依次激活布局，
        让整条链（卡片 → 工具面板 → 气泡 → 消息容器）在同一帧内完成重排。
        """
        widget = self
        for _ in range(32):  # 防御：避免异常父链导致死循环
            parent = widget.parentWidget()
            if parent is None:
                break
            layout = parent.layout()
            if layout is not None:
                layout.activate()
            widget = parent

    def _sync_chevron(self) -> None:
        icon = (
            ElaIconType.IconName.ChevronDown
            if self._header.isChecked()
            else ElaIconType.IconName.ChevronRight
        )
        self._chevron.setAwesome(icon)

    # -- 外观 --------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._surface:
            super().paintEvent(event)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()

    def _apply_theme(self) -> None:
        self._title_label.setTextColor(text_color(self._theme_mode))
        self._title_label.setTextPixelSize(13)
        self._title_label.setTextWeight(QFont.Weight.DemiBold)


class ReasoningBlock(_CollapsibleBlock):
    """思考层：可折叠的推理文本，支持流式追加与耗时统计。"""

    def __init__(self, title: str = "思考中", parent: Optional[QWidget] = None) -> None:
        super().__init__(title=title, opened=False, parent=parent, surface=False)
        self.setCardMargins(0, 0, 0, 0)
        self._text = ""
        self._chunks: list = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_chunks)
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.bodyLayout().addWidget(self._label)
        self._apply_theme()

    # -- 流式 --------------------------------------------------------------

    def begin(self) -> None:
        """进入思考状态（展开并显示「思考中」与运行指示）。"""
        self.setText("")
        self.setTitle("思考中")
        self.setBusy(True)
        self.setOpened(True)

    def end(self, durationMs: Optional[float] = None) -> None:
        """结束思考，标题显示耗时并自动收起。"""
        self._flush_chunks()
        self.setBusy(False)
        # 宿主可能传非数值（恢复历史时从 JSON 读到 "1.2s" 之类），
        # 直接做算术会抛 TypeError/ValueError；而本方法常在信号槽里被调用，
        # 异常穿出 Qt 回调就是 0xC0000409 静默 abort。
        try:
            millis = float(durationMs) if durationMs else 0.0
        except (TypeError, ValueError, OverflowError):
            millis = 0.0
        if millis > 0:
            self.setTitle(f"思考完成 ({millis / 1000:.1f}s)")
        else:
            self.setTitle("思考完成")
        self.setOpened(False)

    def finishSilently(self, durationMs: Optional[float] = None) -> None:
        """恢复历史时的收尾：直接落成「已完成 + 收起」，不触发 toggled / 布局链。"""
        self._flush_chunks()
        self.setBusy(False)
        try:
            millis = float(durationMs) if durationMs else 0.0
        except (TypeError, ValueError, OverflowError):
            millis = 0.0
        if millis > 0:
            self.setTitle(f"思考完成 ({millis / 1000:.1f}s)")
        else:
            self.setTitle("思考完成")
        self.setOpenedSilently(False)

    # -- 文本 --------------------------------------------------------------

    def text(self) -> str:
        """获取思考文本（含尚未刷新的分片）。"""
        self._flush_chunks()
        return self._text

    def setText(self, text: str) -> None:
        """整体替换思考文本。"""
        self._flush_timer.stop()
        self._chunks.clear()
        self._text = text or ""
        # 折叠态不把全文塞进 word-wrap 标签：QLabel 的首次 sizeHint /
        # heightForWidth 要整段折行（51KB 实测 12~45ms/次），958 个历史思考块
        # 全量物化就是秒级纯浪费（bug #17）。展开时再灌。
        if self.isOpened():
            self._sync_label_text()

    def appendText(self, chunk: str) -> None:
        """追加思考文本（流式；标签刷新按事件循环轮次合并）。"""
        if not chunk:
            return
        self._chunks.append(chunk)
        if not self._flush_timer.isActive():
            self._flush_timer.start(REASONING_FLUSH_INTERVAL_MS)

    def _flush_chunks(self) -> None:
        """把缓冲分片并入文本并刷新标签（定时器 / 读取前调用）。"""
        if not self._chunks or is_deleted(self):
            return
        self._text += "".join(self._chunks)
        self._chunks.clear()
        if self.isOpened():
            self._sync_label_text()

    def _sync_label_text(self) -> None:
        """把当前文本灌进标签（文本没变时不动，保住 ColorText 尺寸缓存）。"""
        text = self._displayText()
        if self._label.text() != text:
            self._label.setText(text)

    def _on_toggled(self, checked: bool) -> None:
        # 先把全文灌进标签再交给基类：基类会触发祖先布局激活，空标签先量一遍
        # 会把同一 (类别, 宽度) 算两次（ColorText 缓存按文本分键）。
        if checked and getattr(self, "_label", None) is not None:
            self._flush_chunks()
            self._sync_label_text()
        super()._on_toggled(checked)

    def setOpenedSilently(self, opened: bool) -> None:
        if opened and getattr(self, "_label", None) is not None:
            self._flush_chunks()
            self._sync_label_text()
        super().setOpenedSilently(opened)

    def _displayText(self) -> str:
        """喂给标签的文本：裁掉尾部空白（``self._text`` 保持原样）。

        模型常以若干换行收尾一段思考，而这是 PlainText 标签 —— 不像内联形态走
        Markdown 导入器（导入器本来就丢尾部空行），每个换行都真的画一行。
        只裁显示不裁数据：``text()`` / ``part.text`` / journal / 导出全部保真。
        """
        return self._text.rstrip()

    def label(self) -> ElaText:
        """获取内部文本标签（高级用法）。"""
        return self._label

    def _apply_theme(self) -> None:
        super()._apply_theme()
        label = getattr(self, "_label", None)
        if label is not None:
            label.setTextColor(muted_color(self._theme_mode, 0.55))
            label.setTextPixelSize(12)


class ThinkingRow(ElaThemeWidget):
    """思考行：``ElaProgressRing`` + 「思考中」+ 从推理抽取的标题。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._heading = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._ring = ElaProgressRing(self)
        self._ring.setFixedSize(14, 14)
        self._ring.setIsTransparent(True)
        self._ring.setBusyingWidth(2)
        self._ring.setIsBusying(True)
        self._label = ColorText("思考中", self)
        self._label.setWordWrap(False)
        self._heading_label = ColorText(self)
        self._heading_label.setWordWrap(False)
        # 标题来自 extractReasoningHeading（模型推理文本），必须按纯文本渲染
        self._heading_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._ring)
        layout.addWidget(self._label)
        layout.addWidget(self._heading_label, 1)
        self.hide()
        self._apply_theme()

    def begin(self) -> None:
        """进入思考状态（显示并清空标题）。"""
        self.setHeading("")
        self._ring.setIsBusying(True)
        self.show()

    def end(self) -> None:
        """结束思考（隐藏）。"""
        self._ring.setIsBusying(False)
        self.hide()

    def setHeading(self, text: str) -> None:
        """设置标题（长文本截断）。"""
        self._heading = text or ""
        display = self._heading
        if len(display) > 60:
            display = display[:59] + "…"
        self._heading_label.setText(display)

    def heading(self) -> str:
        """获取标题。"""
        return self._heading

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        self._label.setTextColor(muted_color(mode, 0.65))
        self._label.setTextPixelSize(12)
        self._heading_label.setTextColor(muted_color(mode, 0.45))
        self._heading_label.setTextPixelSize(12)
