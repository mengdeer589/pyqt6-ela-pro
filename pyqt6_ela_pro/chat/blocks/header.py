"""消息头部层：头像、状态点、标题与时间。（``pyqt6_ela_pro.chat`` 内部模块）。"""

from __future__ import annotations


from typing import Optional

from ..._internal import system_cjk_font_family
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconType,
    ElaText,
    ElaThemeType,
    eTheme,
)

from ..._motion import idle_loop_running, start_idle_loop
from ..._styles import ColorText
from ..._theme import ElaStatusRoleType, statusColor
from ...widget_base import ElaThemeWidget
from .._theme import (
    accent_color,
    base_color,
    blend,
    mono_font,
    muted_color,
    text_color,
)
from ..message import (
    ElaChatRoleType,
    ElaChatStatusType,
)
from ._helpers import (
    AVATAR_DEFAULT_SHAPE,
    AVATAR_RADIUS,
    AVATAR_SIZE,
    ElaChatAvatarSource,
    ROLE_ICONS,
    _load_avatar_pixmap,
    avatarPixmap,
    formatDuration,
    normalizeAvatarShape,
)


class _AvatarBadge(QWidget):
    """头像徽标：主题色底 + ElaIcon 字形，可换自定义图片 / SVG（按形状裁切）。"""

    def __init__(self, role: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._role = role
        self._icon_name = ROLE_ICONS.get(role, ElaIconType.IconName.Comment)
        self._bg = QColor()
        self._border = QColor()
        self._icon: Optional[QPixmap] = None
        self._custom: Optional[QPixmap] = None
        #: 自定义头像按 (宽, 高, DPR) 缩放后的缓存：固定尺寸下缩放结果是不变量，
        #: 避免 paintEvent 每帧重做 SmoothTransformation。
        self._scaled_custom: Optional[QPixmap] = None
        self._scaled_custom_key: Optional[tuple] = None
        self._shape = AVATAR_DEFAULT_SHAPE
        self._theme_mode = eTheme.getThemeMode()
        self.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._apply_theme()

    def setIconName(self, iconName: ElaIconType.IconName) -> None:
        """设置头像图标（``ElaIconType`` 成员）。"""
        self._icon_name = iconName
        self._apply_theme()
        self.update()

    def iconName(self):
        """获取当前头像图标。"""
        return self._icon_name

    # -- 形状 --------------------------------------------------------------

    def setShape(self, shape: str) -> None:
        """设置头像形状（``"circle"`` / ``"rounded"`` / ``"square"``；非法值回落默认）。"""
        shape = normalizeAvatarShape(shape)
        if shape == self._shape:
            return
        self._shape = shape
        self.update()

    def shape(self) -> str:
        """获取当前头像形状。"""
        return self._shape

    # -- 自定义头像 --------------------------------------------------------

    def setImage(self, source: ElaChatAvatarSource) -> None:
        """设置自定义头像图（``None`` 清除并回退内置图标）。"""
        self._custom = _load_avatar_pixmap(source, AVATAR_SIZE * 2)
        self._scaled_custom = None
        self._scaled_custom_key = None
        self.update()

    def image(self) -> Optional[QPixmap]:
        """获取自定义头像图（未设置返回 ``None``）。"""
        return None if self._custom is None else QPixmap(self._custom)

    def hasCustomImage(self) -> bool:
        """是否已设置自定义头像图。"""
        return self._custom is not None and not self._custom.isNull()

    def setThemeMode(self, mode) -> None:
        """更新主题模式并重绘。"""
        self._theme_mode = mode
        self._apply_theme()

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        base = base_color(mode)
        text = text_color(mode)
        accent = accent_color(mode)
        if self._role == ElaChatRoleType.User:
            self._bg = blend(base, accent, 0.22)
            self._border = blend(base, accent, 0.38)
        else:
            self._bg = blend(base, text, 0.06)
            self._border = blend(base, text, 0.14)
        self._icon = avatarPixmap(
            self._icon_name, int(AVATAR_SIZE * 0.62), text_color(mode)
        )
        self.update()

    def _shape_path(self) -> QPainterPath:
        """头像外形路径（按当前形状生成圆 / 圆角方形 / 直角方形）。"""
        rect = QRectF(self.rect())
        path = QPainterPath()
        if self._shape == "square":
            path.addRect(rect)
        elif self._shape == "rounded":
            path.addRoundedRect(rect, AVATAR_RADIUS, AVATAR_RADIUS)
        else:
            path.addEllipse(rect)
        return path

    def _stroke_shape(self, painter: QPainter) -> None:
        """按当前形状描边（1px，内缩半像素避免发虚）。"""
        pen = QPen(self._border)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._shape == "square":
            painter.drawRect(rect)
        elif self._shape == "rounded":
            painter.drawRoundedRect(rect, AVATAR_RADIUS, AVATAR_RADIUS)
        else:
            painter.drawEllipse(rect)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        clip = self._shape_path()
        custom = self._custom
        if custom is not None and not custom.isNull():
            painter.setClipPath(clip)
            dpr = self.devicePixelRatioF() or 1.0
            key = (self.width(), self.height(), dpr)
            if self._scaled_custom_key != key or self._scaled_custom is None:
                target = QSize(
                    max(1, int(self.width() * dpr)),
                    max(1, int(self.height() * dpr)),
                )
                scaled = custom.scaled(
                    target,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                scaled.setDevicePixelRatio(dpr)
                self._scaled_custom = scaled
                self._scaled_custom_key = key
            scaled = self._scaled_custom
            offset = self._device_aligned_offset(
                scaled.width() / dpr, scaled.height() / dpr, dpr
            )
            painter.drawPixmap(offset, scaled)
            painter.setClipping(False)
            self._stroke_shape(painter)
            painter.end()
            return

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._bg)
        painter.drawPath(clip)
        self._stroke_shape(painter)
        if self._icon is not None and not self._icon.isNull():
            # 位图本身已按 DPR 渲染，但居中必须按逻辑尺寸算、落点对齐设备像素网格：
            # 用物理尺寸居中会让图标落在半像素上，SmoothPixmapTransform 重采样后发虚。
            dpr = self._icon.devicePixelRatio() or 1.0
            painter.drawPixmap(
                self._device_aligned_offset(
                    self._icon.width() / dpr, self._icon.height() / dpr, dpr
                ),
                self._icon,
            )
        painter.end()

    def _device_aligned_offset(
        self, width: float, height: float, dpr: float
    ) -> QPointF:
        """把位图居中、并把左上角落到**设备像素整数网格**上（高 DPI 防发虚）。"""
        x = (self.width() - width) / 2.0
        y = (self.height() - height) / 2.0
        return QPointF(round(x * dpr) / dpr, round(y * dpr) / dpr)


STATUS_DOT_BREATH_MS = 600


class _StatusDot(QWidget):
    """6px 状态点：生成中呼吸（明暗交替），其余状态静态。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(6, 6)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._color = QColor()
        self._active = False
        self._phase = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def setColor(self, color: QColor) -> None:
        """设置状态色。"""
        self._color = QColor(color)
        self.update()

    def setActive(self, on: bool) -> None:
        """呼吸开关（仅生成中开启；关闭时停止定时器避免空转）。"""
        on = bool(on)
        if on == self._active:
            return
        self._active = on
        if on:
            # 持续动效：Reduced / Disabled 下不启动（停掉而不是放慢）；停掉时画不透明静态点。
            start_idle_loop(
                self._timer, STATUS_DOT_BREATH_MS, on_stop=self._settleStaticDot
            )
        else:
            self._timer.stop()
            self._phase = False
        self.update()

    def isActive(self) -> bool:
        """是否处于呼吸状态。"""
        return self._active

    def _tick(self) -> None:
        self._phase = not self._phase
        self.update()

    def _settleStaticDot(self) -> None:
        """呼吸循环停掉 → 相位归到「亮着」并重画（停在低相位就看不出正在生成）。"""
        self._phase = False
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._color)
        # 判据是「呼吸循环有没有真的在跑」而不是 _active：动效策略可能在运行期停掉
        # 循环，那时必须画满不透明度的静态点，否则看起来像卡住。
        breathing = idle_loop_running(self._timer)
        color.setAlpha(255 if (not breathing or self._phase) else 110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(self.rect()))
        painter.end()


class MessageHeader(ElaThemeWidget):
    """消息头部层：头像 + 名称 + 时间 / 状态（状态点呼吸）。"""

    def __init__(
        self, role: str = ElaChatRoleType.Assistant, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._role = role
        self._title = ""
        self._context = ""
        self._timestamp = ""
        self._status_text = ""
        self._status_kind = ""
        self._avatar = _AvatarBadge(role, self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._texts = QVBoxLayout()
        self._texts.setContentsMargins(0, 1, 0, 1)
        self._texts.setSpacing(1)
        self._title_label = ElaText(self)
        self._title_label.setWordWrap(False)
        # 标题 / 时间 / 状态都可能是外部文本（模型名、自定义名），PlainText 防止
        # AutoText 把 "<b>" / "<img src=...>" 真解析。
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)

        self._subtitle_row = QWidget(self)
        self._subtitle_layout = QHBoxLayout(self._subtitle_row)
        self._subtitle_layout.setContentsMargins(0, 0, 0, 0)
        self._subtitle_layout.setSpacing(4)
        self._context_label = ColorText(self._subtitle_row)
        self._context_label.setWordWrap(False)
        self._context_label.setTextFormat(Qt.TextFormat.PlainText)
        self._context_sep = ColorText("·", self._subtitle_row)
        self._time_label = ColorText(self._subtitle_row)
        self._time_label.setWordWrap(False)
        self._time_label.setTextFormat(Qt.TextFormat.PlainText)
        self._sep_label = ColorText("·", self._subtitle_row)
        self._status_dot = _StatusDot(self._subtitle_row)
        self._status_label = ColorText(self._subtitle_row)
        self._status_label.setWordWrap(False)
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        if role == ElaChatRoleType.User:
            self._subtitle_layout.addStretch(1)
        self._subtitle_layout.addWidget(self._context_label)
        self._subtitle_layout.addWidget(self._context_sep)
        self._subtitle_layout.addWidget(self._time_label)
        self._subtitle_layout.addWidget(self._sep_label)
        self._subtitle_layout.addWidget(self._status_dot)
        self._subtitle_layout.addWidget(self._status_label)
        if role != ElaChatRoleType.User:
            self._subtitle_layout.addStretch(1)

        self._texts.addWidget(self._title_label)
        self._texts.addWidget(self._subtitle_row)

        if role == ElaChatRoleType.User:
            layout.addStretch(1)
            self._texts.setAlignment(Qt.AlignmentFlag.AlignRight)
            self._title_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addLayout(self._texts)
            layout.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignTop)
        else:
            layout.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignTop)
            layout.addLayout(self._texts)
            layout.addStretch(1)

        self._sync_subtitle()
        self._apply_theme()

    # -- 内容 --------------------------------------------------------------

    def role(self) -> str:
        """获取头部所属消息角色。"""
        return self._role

    def setTitle(self, text: str) -> None:
        """设置名称 / 模型名。"""
        self._title = text or ""
        self._title_label.setText(self._title)

    def title(self) -> str:
        """获取名称 / 模型名。"""
        return self._title

    def setContext(self, text: str) -> None:
        """设置上下文文本（agent · 模型 / 变体；空则不显示）。"""
        self._context = text or ""
        self._sync_subtitle()

    def context(self) -> str:
        """获取上下文文本。"""
        return self._context

    def setTimestamp(self, text: str) -> None:
        """设置时间文本。"""
        self._timestamp = text or ""
        self._sync_subtitle()

    def timestamp(self) -> str:
        """获取时间文本。"""
        return self._timestamp

    def setStatusText(self, text: str, kind: str = "") -> None:
        """设置状态文本与状态类型（排队中 / 生成中 / 已停止 / 出错）。"""
        self._status_text = text or ""
        self._status_kind = kind or ""
        self._sync_subtitle()
        self._apply_theme()

    def statusText(self) -> str:
        """获取状态文本。"""
        return self._status_text

    def statusKind(self) -> str:
        """获取状态类型（``ElaChatStatusType`` 取值，空表示无状态）。"""
        return self._status_kind

    def statusDot(self) -> _StatusDot:
        """获取状态点控件（测试 / 高级用法）。"""
        return self._status_dot

    def _sync_subtitle(self) -> None:
        has_context = bool(self._context)
        has_time = bool(self._timestamp)
        has_status = bool(self._status_text)
        self._context_label.setText(self._context)
        self._context_label.setVisible(has_context)
        self._context_sep.setVisible(has_context and (has_time or has_status))
        self._time_label.setText(self._timestamp)
        self._time_label.setVisible(has_time)
        self._sep_label.setVisible(has_time and has_status)
        self._status_label.setText(self._status_text)
        self._status_label.setVisible(has_status)
        self._status_dot.setVisible(has_status)
        self._status_dot.setActive(
            has_status
            and self._status_kind
            in (ElaChatStatusType.Streaming, ElaChatStatusType.Queued)
        )
        self._subtitle_row.setVisible(has_context or has_time or has_status)

    # -- 外观 --------------------------------------------------------------

    def avatar(self) -> _AvatarBadge:
        """获取头像控件。"""
        return self._avatar

    def setAvatarVisible(self, on: bool) -> None:
        """显示 / 隐藏头像。"""
        self._avatar.setVisible(bool(on) and self._role != ElaChatRoleType.System)

    def setAvatarIcon(self, iconName: ElaIconType.IconName) -> None:
        """设置头像图标（``ElaIconType`` 成员）。"""
        self._avatar.setIconName(iconName)

    def setAvatarImage(self, source: ElaChatAvatarSource) -> None:
        """设置自定义头像（SVG 数据 / 文件路径 / ``QPixmap`` 等）。

        ``None`` 清除自定义头像并回退到内置图标。
        """
        self._avatar.setImage(source)

    def avatarImage(self) -> Optional[QPixmap]:
        """获取自定义头像图（未设置返回 ``None``）。"""
        return self._avatar.image()

    def setAvatarShape(self, shape: str) -> None:
        """设置头像形状（``"circle"`` / ``"rounded"`` / ``"square"``）。"""
        self._avatar.setShape(shape)

    def avatarShape(self) -> str:
        """获取头像形状。"""
        return self._avatar.shape()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _status_color(self) -> QColor:
        mode = self._theme_mode
        if self._status_kind == ElaChatStatusType.Error:
            return blend(
                text_color(mode), statusColor(mode, ElaStatusRoleType.Error), 0.55
            )
        if self._status_kind == ElaChatStatusType.Stopped:
            return blend(
                text_color(mode), statusColor(mode, ElaStatusRoleType.Warning), 0.5
            )
        return accent_color(mode)

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        muted = muted_color(mode, 0.5).name()
        # 标题色走主题 BasicText（ElaText 默认），字体走 QFont。名称可能是中文：
        # 中文系统收成单族雅黑（多族列表在 Win7 上是慢 shaping 路径且进程级毒化），
        # 非中文系统保持拉丁优先 + 中文逐字形回退。
        title_font = QFont(self._title_label.font())
        cjk_family = system_cjk_font_family()
        title_font.setFamilies(
            [cjk_family]
            if cjk_family
            else ["Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei"]
        )
        title_font.setPixelSize(13)
        title_font.setWeight(QFont.Weight.DemiBold)
        self._title_label.setFont(title_font)
        self._context_label.setTextColor(muted)
        self._context_label.setTextPixelSize(11)
        self._context_sep.setTextColor(muted)
        self._context_sep.setTextPixelSize(11)
        self._time_label.setTextColor(muted)
        self._time_label.setFont(mono_font(11))
        self._sep_label.setTextColor(muted)
        self._sep_label.setTextPixelSize(11)
        self._status_label.setTextColor(self._status_color())
        self._status_label.setTextPixelSize(11)
        self._status_dot.setColor(self._status_color())
        self._avatar.setThemeMode(mode)


class MessageMeta(ElaThemeWidget):
    """消息底部 meta 标签：``名称 · 耗时``（无内容时自动隐藏）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = ""
        self._context = ""
        self._duration_ms = 0.0
        self._interrupted = False
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._label)
        self.hide()
        self._apply_theme()

    def setTitle(self, text: str) -> None:
        """设置名称 / 模型名。"""
        self._title = text or ""
        self._sync()

    def title(self) -> str:
        """获取名称 / 模型名。"""
        return self._title

    def setContext(self, text: str) -> None:
        """设置上下文文本（agent · 模型 / 变体；空则不显示）。"""
        self._context = text or ""
        self._sync()

    def context(self) -> str:
        """获取上下文文本。"""
        return self._context

    def setInterrupted(self, on: bool) -> None:
        """设置是否显示「已中断」。"""
        self._interrupted = bool(on)
        self._sync()

    def interrupted(self) -> bool:
        """是否标记为已中断。"""
        return self._interrupted

    def setDuration(self, durationMs: float) -> None:
        """设置耗时（毫秒）。"""
        self._duration_ms = float(durationMs or 0.0)
        self._sync()

    def duration(self) -> float:
        """获取耗时（毫秒）。"""
        return self._duration_ms

    def _sync(self) -> None:
        parts = []
        if self._title:
            parts.append(self._title)
        if self._context:
            parts.append(self._context)
        duration = formatDuration(self._duration_ms)
        if duration:
            parts.append(f"耗时 {duration}")
        if self._interrupted:
            parts.append("已中断")
        self._label.setText("  ·  ".join(parts))
        self.setVisible(bool(parts))

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        self._label.setTextColor(muted_color(self._theme_mode, 0.5))
        self._label.setTextPixelSize(11)
