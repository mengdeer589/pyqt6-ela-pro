"""
统一按钮组件，风格参考 Ant Design Button。

支持 6 种变体 (outlined/dashed/solid/filled/text/link)、
16 种色彩主题以及深色/浅色主题自适应。

用法::

    from pyqt6_ela_pro import ElaButton
    from PyQt6ElaWidgetTools import ElaIconType

    btn = ElaButton("提交", variant="solid", color="primary", parent=self)
    btn = ElaButton("编辑", variant="outlined", icon=ElaIconType.IconName.Pencil, parent=self)
    btn = ElaButton("删除", variant="solid", danger=True, parent=self)
"""

from __future__ import annotations

import warnings
from typing import Literal, Optional

from PyQt6.QtCore import Qt, QRect, QRectF, QSize, QTimer, QVariantAnimation
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPaintEvent,
    QEnterEvent,
)
from PyQt6.QtWidgets import QPushButton, QWidget

from PyQt6ElaWidgetTools import eApp, eTheme, ElaThemeType, ElaIcon, ElaIconType

from ._internal import _ThemeAwareMixin
from ._colors import get_color_scheme, state_tint
from ._motion import Duration, start_idle_loop, start_transition
from ._styles import coerceElaIcon
from ._theme import accent as theme_accent, blend
from .svg_icon import svg_icon_loader, svg_to_pixmap


# ── Type aliases ─────────────────────────────────────────────

ElaButtonVariant = Literal["outlined", "dashed", "solid", "filled", "text", "link"]
ElaButtonColor = Literal[
    "default",
    "primary",
    "danger",
    "blue",
    "purple",
    "cyan",
    "green",
    "magenta",
    "pink",
    "red",
    "orange",
    "yellow",
    "volcano",
    "geekblue",
    "lime",
    "gold",
]
ElaButtonSize = Literal["small", "middle", "large"]


# ── Size presets ─────────────────────────────────────────────

#: 可见按钮面与控件边缘的内缩（px）。与上游 ``ElaPushButton`` V3.0 的
#: ``rect().adjusted(1, 1, -1, -1)`` 同值：控件高 30 → 可见面 28。
_FACE_INSET = 1

#: ``fontDelta`` 是相对 ``eApp.getFontPixelSize()`` 的偏移；middle 与上游
#: ``ElaPushButton``（``eApp + 2``）一致。
#: 高度 22/30/38 → 可见面 20/28/36（档距保持 8；middle 与上游 V3.0 逐值一致）。
_SIZE_MAP: dict[str, dict[str, int]] = {
    "small": {
        "height": 22,
        "fontDelta": 0,
        "paddingH": 12,
        "iconSize": 14,
        "radius": 4,
    },
    "middle": {
        "height": 30,
        "fontDelta": 2,
        "paddingH": 16,
        "iconSize": 16,
        "radius": 6,
    },
    "large": {
        "height": 38,
        "fontDelta": 4,
        "paddingH": 20,
        "iconSize": 18,
        "radius": 8,
    },
}


# ── ElaButton ────────────────────────────────────────────────


class ElaButton(_ThemeAwareMixin, QPushButton):
    """统一风格按钮组件。

    支持 6 种变体、16 种色彩主题、3 种尺寸，自动适配深浅色主题。取值范围见
    :data:`ElaButtonVariant` / :data:`ElaButtonColor` / :data:`ElaButtonSize`；
    尺寸与上游 ``ElaPushButton`` 对齐（见 :data:`_SIZE_MAP`）。
    """

    def __init__(
        self,
        text: Optional[str] = None,
        icon: Optional[ElaIconType.IconName] = None,
        iconSize: int = 16,
        variant: ElaButtonVariant = "outlined",
        color: ElaButtonColor = "default",
        danger: bool = False,
        size: ElaButtonSize = "middle",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._variant = variant
        self._color_name = color
        self._danger = danger
        self._border_radius = 6
        self._padding_h = 16
        self._size_height = 30
        #: ElaAwesome 图标（``ElaIconType.IconName`` 或其整数值，入口即归一）。
        #: 绘制路径上的 ``getElaIcon`` 只接受枚举成员 —— 传 int 会在
        #: ``paintEvent`` 里抛 TypeError，穿出 Qt 回调 = 0xC0000409 崩溃，
        #: 所以归一必须在 setter / 构造期完成（见 ``_styles.coerceElaIcon``）。
        self._icon_name: Optional[ElaIconType.IconName] = (
            None if icon is None else coerceElaIcon(icon)
        )
        self._icon_size = iconSize
        #: SVG 图标源：SVG 源码字符串，或 :class:`ElaSvgIconLoader` 里的图标名
        #: （二选一，见 :meth:`setSvgIcon`）。非 ``None`` 时**压过** ``_icon_name``。
        self._svg_source: Optional[str] = None
        self._svg_is_name: bool = False
        self._hovered = False
        self._focus_ring = False
        self._loading = False
        self._spin_angle = 0
        self._hover_t = 0.0

        if text:
            self.setText(text)

        self._theme_mode = eTheme.getThemeMode()
        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.valueChanged.connect(self._onHoverValue)
        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._onSpinTick)
        self._apply_size(size)

    # ── Public API ────────────────────────────────────────

    def setVariant(self, variant: ElaButtonVariant) -> None:
        self._variant = variant
        self.update()

    def variant(self) -> str:
        return self._variant

    def setColor(self, color: ElaButtonColor) -> None:
        self._color_name = color
        self.update()

    def color(self) -> str:
        return self._color_name

    def setDanger(self, danger: bool) -> None:
        """启用危险色（覆盖 :meth:`setColor`）。"""
        self._danger = danger
        self.update()

    def isDanger(self) -> bool:
        return self._danger

    def setButtonSize(self, size: ElaButtonSize) -> None:
        self._apply_size(size)
        self.update()

    def buttonSize(self) -> str:
        h = self.height()
        for name, cfg in _SIZE_MAP.items():
            if cfg["height"] == h:
                return name
        return "middle"

    def setElaIcon(self, iconName, iconSize: int = 16) -> None:
        """设置 ElaAwesome 图标（``ElaIconType.IconName`` 或其整数值；``None`` 清除）。"""
        self._icon_name = None if iconName is None else coerceElaIcon(iconName)
        self._icon_size = iconSize
        self._svg_source = None
        self.setIconSize(QSize(iconSize, iconSize))
        self.updateGeometry()
        self.update()

    def setSvgIcon(self, source: str, iconSize: Optional[int] = None) -> bool:
        """设置 **第三方 SVG** 图标，颜色跟随当前主题文字色 / 禁用色。

        ``source`` 按是否含 ``<svg`` 自动分「SVG 源码」与「图标名」两种形态，
        名字形态需宿主自己 ``svg_icon_loader().loadFromFile(...)`` 加载图标包。
        SVG 里的 ``<<<COLOR_CODE>>>`` 占位符替换成当前文字色。与
        :meth:`setElaIcon` 互斥（两套图标语义并存说不清谁生效）。

        :returns: 图标名形态且图标包里找不到该名字时返回 ``False``（只画文字，
            并已 ``warnings.warn`` 一次）
        """
        self._svg_source = source or None
        self._svg_is_name = bool(source) and "<svg" not in source
        if iconSize is not None:
            self._icon_size = iconSize
        self._icon_name = None
        found = True
        if self._svg_is_name:
            found = svg_icon_loader().hasIcon(source)
            if not found:
                warnings.warn(
                    f"图标名 {source!r} 在已加载的图标包里不存在"
                    "（svg_icon_loader().loadFromFile(...) 加载过吗？）—— 只画文字。",
                    RuntimeWarning,
                    stacklevel=2,
                )
        self.setIconSize(QSize(self._icon_size, self._icon_size))
        self.updateGeometry()
        self.update()
        return found

    def clearSvgIcon(self) -> None:
        self._svg_source = None
        self._svg_is_name = False
        self.updateGeometry()
        self.update()

    def svgIcon(self) -> Optional[str]:
        return self._svg_source

    def setIcon(self, icon) -> None:  # noqa: N802 (Qt 命名)
        """**恒抛** ``RuntimeError``：本控件自绘，只读 ``_icon_name`` /
        ``_svg_source``，``QPushButton.setIcon`` 设了不会画。"""
        del icon
        raise RuntimeError(
            "ElaButton 自绘，不支持 QPushButton.setIcon（会静默不画）。"
            "请用 setElaIcon(ElaIconType.IconName) 放 ElaAwesome 图标，"
            "或 setSvgIcon(svg源码或图标名) 放第三方 SVG。"
        )

    def setBorderRadius(self, radius: int) -> None:
        self._border_radius = radius
        self.update()

    def borderRadius(self) -> int:
        return self._border_radius

    # ── Internal ──────────────────────────────────────────

    def _apply_size(self, size: ElaButtonSize) -> None:
        cfg = _SIZE_MAP[size]
        self._padding_h = cfg["paddingH"]
        self._size_height = cfg["height"]
        self._border_radius = cfg["radius"]
        self.setFixedHeight(cfg["height"])
        font = self.font()
        # 字号跟随 eApp（与上游 ElaPushButton 的 eApp + 2 同源），不再写死 12/14/16
        font.setPixelSize(eApp.getFontPixelSize() + cfg["fontDelta"])
        self.setFont(font)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        """按文字 / 图标与内边距计算合适宽度（不再依赖样式默认值）。

        宽度是**控件**宽度：可见按钮面还要内缩 ``_FACE_INSET``（与上游
        ``ElaPushButton`` V3.0 的面内缩一致），所以面宽 = 控件宽 − 2×inset。
        """
        fm = self.fontMetrics()
        face_width = fm.horizontalAdvance(self.text())
        if self._icon_name is not None or self._svg_source or self._loading:
            face_width += self._icon_size + (8 if self.text() else 0)
        face_width += 2 * self._padding_h
        return QSize(max(64, face_width) + 2 * _FACE_INSET, self._size_height)

    def minimumSizeHint(self) -> QSize:
        return QSize(max(48, 2 * self._padding_h) + 2 * _FACE_INSET, self._size_height)

    def _svg_pixmap_for_paint(self, color: QColor):
        """按当前文字色渲染 SVG 图标；取不到时返回 ``None``（只画文字）。

        绘制路径上**绝不能**让异常穿出去（``paintEvent`` 在 Qt 回调链里，
        未捕获异常 = 0xC0000409 静默终止）。所以三道全兜住：图标名找不到
        （``getSvgData`` 会抛 ``KeyError``）、SVG 语法错、渲染出空图。
        """
        source = self._svg_source
        if not source:
            return None
        size = self._icon_size
        try:
            if self._svg_is_name:
                data = svg_icon_loader().getSvgData(source, color.name())
            else:
                data = source
            pixmap = svg_to_pixmap(data, size, color.name())
        except Exception:  # noqa: BLE001 —— paintEvent 里必须全兜
            return None
        return None if pixmap.isNull() else pixmap

    def _effective_color(self) -> str:
        return "danger" if self._danger else self._color_name

    def _is_dark(self) -> bool:
        return self._theme_mode == ElaThemeType.ThemeMode.Dark

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self.update()

    # ── ElaChipColorType helpers ─────────────────────────────────────

    def _neutral_text(self) -> QColor:
        return QColor(0xE0, 0xE0, 0xE0) if self._is_dark() else QColor(0x1F, 0x1F, 0x1F)

    def _neutral_border(self) -> QColor:
        """default 变体的描边色，与上游 ``ElaPushButton`` 同款。"""
        return eTheme.getThemeColor(self._theme_mode, ElaThemeType.ThemeColor.BasicBorder)

    def _disabled_bg(self) -> QColor:
        return eTheme.getThemeColor(
            self._theme_mode, ElaThemeType.ThemeColor.BasicDisable
        )

    def _disabled_text(self) -> QColor:
        return eTheme.getThemeColor(
            self._theme_mode, ElaThemeType.ThemeColor.BasicTextDisable
        )

    def _disabled_border(self) -> QColor:
        return self._neutral_border()

    def _hover_tint(self) -> QColor:
        """状态层：hover ≈ 8%（暗色叠白 / 亮色叠黑）。"""
        return state_tint(self._theme_mode)

    def _pressed_tint(self) -> QColor:
        """状态层：press ≈ 12%。"""
        return state_tint(self._theme_mode, pressed=True)

    def _scheme(self) -> dict[str, QColor]:
        return get_color_scheme(self._effective_color(), self._theme_mode)

    def _state_colors(
        self, scheme: dict[str, QColor], hovered: bool, pressed: bool
    ) -> tuple:
        """某状态下的 ``(底, 描边, 文字)``；描边为 ``None`` 表示不画。

        彩色变体的文字一律走 ``accentText``（浅底上的可读档，对比度 ≥ 4.5），
        ``accent`` 只用于填充 / 描边。
        """
        variant = self._variant
        is_default = self._effective_color() == "default"
        transparent = QColor(0, 0, 0, 0)
        if variant == "solid":
            bg = (
                scheme["solidActive"]
                if pressed
                else (scheme["solidHover"] if hovered else scheme["solid"])
            )
            return bg, None, scheme["solidText"]
        if variant in ("outlined", "dashed"):
            if is_default:
                bg = self._hover_tint() if (hovered or pressed) else transparent
                return bg, self._neutral_border(), self._neutral_text()
            bg = scheme["accentBgHover"] if (hovered or pressed) else scheme["accentBg"]
            border = QColor(scheme["accent"])
            border.setAlpha(110 if not self._is_dark() else 150)
            return bg, border, scheme["accentText"]
        if variant == "filled":
            bg = scheme["accentBgHover"] if (hovered or pressed) else scheme["accentBg"]
            return bg, None, scheme["accentText"]
        if variant == "text":
            bg = (
                self._pressed_tint()
                if pressed
                else (self._hover_tint() if hovered else transparent)
            )
            return (
                bg,
                None,
                scheme["accentText"] if not is_default else self._neutral_text(),
            )
        if variant == "link":
            return (
                transparent,
                None,
                scheme["accentText"] if not is_default else self._neutral_text(),
            )
        return transparent, None, self._neutral_text()

    # ── Events ────────────────────────────────────────────

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hovered = True
        self._fade_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._fade_hover(0.0)
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        """键盘聚焦（Tab / Shift+Tab / 快捷键）才显示 focus ring。"""
        self._focus_ring = event.reason() in (
            Qt.FocusReason.TabFocusReason,
            Qt.FocusReason.BacktabFocusReason,
            Qt.FocusReason.ShortcutFocusReason,
        )
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self._focus_ring = False
        self.update()
        super().focusOutEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._loading:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._loading:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ── Motion / loading ──────────────────────────────────

    def _onHoverValue(self, value) -> None:  # noqa: ANN001
        self._hover_t = float(value)
        self.update()

    def _fade_hover(self, target: float) -> None:
        anim = self._hover_anim
        anim.stop()
        anim.setStartValue(self._hover_t)
        anim.setEndValue(float(target))
        start_transition(anim, Duration.Fast)

    def _onSpinTick(self) -> None:
        self._spin_angle = (self._spin_angle + 30) % 360
        self.update()

    def setLoading(self, loading: bool = True) -> None:  # noqa: N802 (Qt 命名)
        """加载态：左侧显示旋转指示器，期间不响应点击。"""
        if loading == self._loading:
            return
        self._loading = loading
        if loading:
            start_idle_loop(self._spin_timer, 33)
        else:
            self._spin_timer.stop()
        self.updateGeometry()
        self.update()

    def isLoading(self) -> bool:  # noqa: N802 (Qt 命名)
        return self._loading

    # ── Paint ─────────────────────────────────────────────

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

            w = self.width()
            h = self.height()
            # 可见按钮面：与上游 ElaPushButton V3.0 一样内缩 1px（控件高 30 → 面 28）
            fw = w - 2 * _FACE_INSET
            fh = h - 2 * _FACE_INSET
            br = self._border_radius

            disabled = not self.isEnabled()
            pressed = self.isDown()
            hovered = self._hovered
            variant = self._variant
            cname = self._effective_color()
            is_default = cname == "default"
            scheme = self._scheme()

            path = QPainterPath()
            path.addRoundedRect(
                QRectF(
                    _FACE_INSET + 0.5,
                    _FACE_INSET + 0.5,
                    fw - 1.0,
                    fh - 1.0,
                ),
                br,
                br,
            )

            # -- Resolve background / border / text color --
            # 彩色文字一律走 accentText（可读档）；hover 用 _hover_t 在两套状态
            # 色之间插值（150ms 淡入淡出，Reduced/Disabled 下同步落终值）。
            if disabled:
                bg = (
                    Qt.GlobalColor.transparent
                    if variant in ("text", "link")
                    else self._disabled_bg()
                )
                text_color = self._disabled_text()
                border_color = (
                    self._disabled_border()
                    if variant in ("outlined", "dashed")
                    else None
                )
            else:
                bg0, border0, text_color = self._state_colors(scheme, False, False)
                if pressed:
                    bg, border_color = self._state_colors(scheme, True, True)[:2]
                else:
                    bg1, border1, _ = self._state_colors(scheme, True, False)
                    t = self._hover_t
                    bg = blend(bg0, bg1, t)
                    if border0 is not None and border1 is not None:
                        border_color = blend(border0, border1, t)
                    else:
                        border_color = border0 if border0 is not None else border1

            border_pen = None
            if border_color is not None:
                border_pen = QPen(border_color, 1)
                if variant == "dashed":
                    border_pen.setStyle(Qt.PenStyle.DashLine)

            painter.setBrush(bg)
            painter.setPen(border_pen if border_pen is not None else Qt.PenStyle.NoPen)
            painter.drawPath(path)

            # -- Focus ring（键盘可见性）--
            if self._focus_ring:
                ring_color = (
                    theme_accent(self._theme_mode)
                    if is_default
                    else QColor(scheme["accent"])
                )
                ring_pen = QPen(ring_color, 2)
                ring_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(ring_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(
                    QRectF(
                        _FACE_INSET - 1.0,
                        _FACE_INSET - 1.0,
                        fw + 2.0,
                        fh + 2.0,
                    ),
                    br + 2.0,
                    br + 2.0,
                )

            # -- Draw icon / spinner + text --
            painter.setPen(text_color)
            icon_name = self._icon_name
            loading = self._loading
            btn_text = self.text()
            svg_pixmap = None if loading else self._svg_pixmap_for_paint(text_color)
            if icon_name is not None or loading or svg_pixmap is not None:
                spacing = 8
                icon_sz = QSize(self._icon_size, self._icon_size)
                fm = painter.fontMetrics()
                tw = fm.horizontalAdvance(btn_text) if btn_text else 0
                if tw:
                    total_w = icon_sz.width() + spacing + tw
                    sx = _FACE_INSET + (fw - total_w) // 2
                else:
                    # 纯图标按钮：只居中图标本身（含 spacing 会向左偏）
                    sx = _FACE_INSET + (fw - icon_sz.width()) // 2
                iy = _FACE_INSET + (fh - icon_sz.height()) // 2
                ir = QRect(sx, iy, icon_sz.width(), icon_sz.height())
                if loading:
                    spin_pen = QPen(text_color, 2)
                    spin_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    painter.setPen(spin_pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawArc(QRectF(ir), self._spin_angle * 16, 270 * 16)
                    painter.setPen(text_color)
                elif svg_pixmap is not None:
                    painter.drawPixmap(ir, svg_pixmap)
                else:
                    # 绘制链兜底：取图标失败（归一后仍非法 / 图标字体未就绪）
                    # 只丢这一枚图标，绝不让异常穿出 paintEvent
                    try:
                        icon = ElaIcon.getInstance().getElaIcon(
                            coerceElaIcon(icon_name), text_color
                        )
                    except Exception:
                        icon = None
                    if icon is not None:
                        painter.drawPixmap(ir, icon.pixmap(icon_sz))
                if tw:
                    tr = QRect(ir.right() + spacing, _FACE_INSET, tw, fh)
                    painter.drawText(
                        tr,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        btn_text,
                    )
                    if variant == "link" and hovered and not disabled:
                        underline_y = ir.center().y() + fm.ascent() // 2 + 2
                        painter.setPen(QPen(text_color, 1))
                        painter.drawLine(
                            tr.left(), underline_y, tr.left() + tw, underline_y
                        )
            else:
                painter.drawText(
                    QRect(_FACE_INSET, _FACE_INSET, fw, fh),
                    Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                    btn_text,
                )
                if variant == "link" and hovered and not disabled:
                    fm = painter.fontMetrics()
                    tw = fm.horizontalAdvance(btn_text)
                    tx = _FACE_INSET + (fw - tw) // 2
                    ty = _FACE_INSET + fh // 2 + fm.ascent() // 2 + 2
                    painter.setPen(QPen(text_color, 1))
                    painter.drawLine(tx, ty, tx + tw, ty)
        finally:
            painter.end()
