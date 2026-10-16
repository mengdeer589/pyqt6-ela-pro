"""头像：图片 / 首字母 / 图标三级回退 + 在线状态圆点。

搬运自 ``Fluent-Qt/src/components/status_info/Avatar.*``。

改道三处
--------
1. **状态圆点自己画，不用 ``ElaInfoBadge``。** Fluent 那边圆环是 Avatar 画的、圆点是
   子控件画的，因为环的**颜色取决于头像周围那层表面**（父链上的
   ``fluentSurfaceColor``）。本库用 ``ElaInfoBadge`` 做不到「环 = 周围表面色」，
   而没有环的状态点在深色头像上会跟背景糊在一起。所以整体自绘，属性名改成本库的
   ``pyqt5SurfaceColor``。
2. **名字→底色的哈希必须自己算。** Fluent 用 ``qHash(name, 0u)``（固定种子，跨进程稳定）。
   Python 内置 ``hash(str)`` **按进程随机化**（``PYTHONHASHSEED``），直接用会让同一个
   名字每次启动换一个颜色 —— 这里改用 ``zlib.crc32``（确定性、跨进程一致）。
3. **``Square`` 是 4px 圆角方**，不是硬矩形（与 Fluent 一致）。1px 描边环复用同一个
   clip path，一次成形。
"""

from __future__ import annotations

import zlib
from enum import IntEnum
from typing import Optional

from PyQt6.QtCore import QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import ElaIconType

from ._styles import drawCoverPixmap, drawElaIcon
from ._theme import (
    ElaStatusRoleType,
    accent,
    border,
    chartPalette,
    currentMode,
    relativeLuminance,
    surface,
    surfaceRaised,
    statusColor,
    textDisabled,
)
from .widget_base import ElaThemeWidget

__all__ = ["ElaAvatar", "ElaAvatarPresenceType", "ElaAvatarShapeType", "ElaAvatarSizeType"]


#: 「圆角方」的圆角（对齐 Fluent ``CornerRadius::Control``）。
_SQUARE_RADIUS = 4.0

#: 内缩半像素，让 1px 描边落在设备像素上不糊。
_STROKE_INSET = 0.5

#: 前景文字对比度阈值：Rec.709 亮度超过它就用深色字。
_CONTRAST_THRESHOLD = 0.56

#: 深色前景不是纯黑而是 ``#141414``（纯黑在深色底上会显脏）。
_DARK_TEXT = QColor(20, 20, 20)
_LIGHT_TEXT = QColor(255, 255, 255)

#: 描边 1px 的相对透明度（对齐 Fluent ``strokeCard``）。
_RING_ALPHA_LIGHT = 13
_RING_ALPHA_DARK = 26

#: 禁用态背景强制降到这个 alpha（**不看尺寸档位**，与 Fluent 一致）。
_DISABLED_BG_ALPHA = 120
#: 禁用态图片额外降到 55% 不透明度（文字不用这个 —— 走 ``textDisabled`` 色即可）。
_DISABLED_IMAGE_ALPHA = 0.55

#: 父链上用来声明「我这一层是什么表面」的动态属性名。
#:
#: **为什么需要**：状态圆点的 2px 环必须画成「圆点周围那层表面」的颜色，而不是画布色。
#: 一个浮在深色卡片上的头像，若环取画布色（浅色模式是浅灰）就会出现一圈亮边。
#: 宿主在自己的容器控件上 ``setProperty("pyqt5SurfaceColor", <QColor>)`` 即可纠正。
SURFACE_PROPERTY = "pyqt5SurfaceColor"


class ElaAvatarSizeType(IntEnum):
    """尺寸档位。控件被**硬锁**在该档位，不会被布局拉伸。"""

    Small = 24
    Medium = 32
    Large = 40
    ExtraLarge = 56


class ElaAvatarShapeType(IntEnum):
    Circular = 0
    """圆形（默认）。"""

    Square = 1
    """4px 圆角方。"""


class ElaAvatarPresenceType(IntEnum):
    """在线状态。"""

    None_ = 0
    """不显示圆点。"""

    Available = 1
    Away = 2
    Busy = 3
    DoNotDisturb = 4
    Offline = 5


#: 状态 → ``ElaStatusRoleType``。``Offline`` 刻意不走角色：它的语义是「不可用」而不是
#: 「危险」，用 ``textDisabled``（灰）比用红/黄更准确。
_PRESENCE_ROLE = {
    ElaAvatarPresenceType.Available: ElaStatusRoleType.Success,
    ElaAvatarPresenceType.Away: ElaStatusRoleType.Warning,
    ElaAvatarPresenceType.Busy: ElaStatusRoleType.Error,
    ElaAvatarPresenceType.DoNotDisturb: ElaStatusRoleType.Error,
    ElaAvatarPresenceType.Offline: None,
}

#: 状态圆点直径按档位：24→6 / 32→8 / 40→8 / 56→10。
_PRESENCE_DOT = {24: 6, 32: 8, 40: 8, 56: 10}
#: 环宽 = 2px/边，故宿主盒子 = 直径 + 4。
_PRESENCE_RING = 2

#: 无图片、无首字母时的兜底字形（人形）。
_FALLBACK_ICON = ElaIconType.IconName.CircleUser


def _graphemes(text: str, limit: int) -> list:
    """取前 ``limit`` 个**字素簇**（不是 UTF-16 码元）。

    必须按字素簇切：一个 emoji 是多个码元、组合音标会与前字母合成一个可视图元，
    按码元切会把它们劈成两半（首字母位置出现半个 emoji）。

    **段是 ``text[prev:next]`` 而不是 ``text[:next]``** —— 后者取的是不断变长的前缀，
    拼出来是「J」+「JO」= ``JJO``（实测踩过：``john`` 出三个字母、``XYZABC`` 出
    ``XXY``，而首字母位只放得下两个）。
    """
    from PyQt6.QtCore import QTextBoundaryFinder

    if not text or limit <= 0:
        return []
    finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
    out = []
    start = 0
    while len(out) < limit:
        end = finder.toNextBoundary()
        if end < 0:
            end = len(text)
        out.append(text[start:end])
        start = end
        if start >= len(text):
            break
    return out


def deriveInitials(name: str, rtl: bool = False) -> str:  # noqa: N802
    """从名字派生首字母。

    - **1 个词** → 前 2 个字素簇转大写（``"john smith doe"`` → ``"JO"``）
    - **≥2 个词** → 首词首字素 + 末词首字素（``"John Smith"`` → ``"JS"``）
    - RTL 下首末顺序翻转
    """
    words = str(name).split()
    if not words:
        return ""
    if len(words) == 1:
        return "".join(_graphemes(words[0], 2)).upper()
    first = _graphemes(words[0], 1)
    last = _graphemes(words[-1], 1)
    pair = last + first if rtl else first + last
    return "".join(pair).upper()


def stableHash(text: str) -> int:  # noqa: N802
    """**跨进程稳定**的字符串哈希。

    **不要用内置 ``hash(str)``**：CPython 对 str 的哈希按进程随机化（PYTHONHASHSEED），
    同一个名字两次启动会落到调色板的不同位置 —— 头像颜色会「每次启动都变」。
    ``zlib.crc32`` 是纯函数、无种子、跨版本一致。
    """
    return zlib.crc32(str(text).encode("utf-8"))


def contrastingText(background: QColor) -> QColor:  # noqa: N802
    """按 Rec.709 亮度选深/浅前景。"""
    return (
        _DARK_TEXT
        if relativeLuminance(background) > _CONTRAST_THRESHOLD
        else _LIGHT_TEXT
    )


class ElaAvatar(ElaThemeWidget):
    """头像。

    ::

        av = ElaAvatar(parent)
        av.setName("John Smith")     # 自动出 "JS"
        av.setImage(pixmap)          # 有图就用图（cover 裁剪，不是拉伸）
        av.setPresence(ElaAvatarPresenceType.Available)
    """

    nameChanged = pyqtSignal(str)
    initialsChanged = pyqtSignal(str)
    imageChanged = pyqtSignal(object)
    shapeChanged = pyqtSignal(object)
    avatarSizeChanged = pyqtSignal(object)
    presenceChanged = pyqtSignal(object)
    backgroundColorChanged = pyqtSignal(object)
    foregroundColorChanged = pyqtSignal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._name = ""
        self._initials = ""
        self._image: Optional[QPixmap] = None
        self._shape = ElaAvatarShapeType.Circular
        self._size = ElaAvatarSizeType.Medium
        self._presence = ElaAvatarPresenceType.None_
        self._background_color = QColor()
        self._foreground_color = QColor()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._applyExtent()

    # -- 内容 ---------------------------------------------------------------

    def name(self) -> str:
        return self._name

    def setName(self, name: str) -> None:  # noqa: N802
        """设名字。**只在没有显式 ``initials`` 时**影响首字母。"""
        value = "" if name is None else str(name)
        if value == self._name:
            return
        self._name = value
        self.nameChanged.emit(value)
        self.update()

    def initials(self) -> str:
        """显式设置的首字母（未设置时为 ``""``）。"""
        return self._initials

    def setInitials(self, initials: str) -> None:  # noqa: N802
        """显式设首字母，**截到 2 个字素簇**并转大写。

        截断在这里做（而不是只在绘制时）—— 宿主读回 ``initials()`` 拿到的就该是
        最终值，否则会出现「设了 4 个字母、界面只显示 2 个、但 ``initials()``
        仍返回 4 个」这种对不上的状态。
        """
        value = "".join(
            _graphemes("" if initials is None else str(initials), 2)
        ).upper()
        if value == self._initials:
            return
        self._initials = value
        self.initialsChanged.emit(value)
        self.update()

    def effectiveInitials(self) -> str:  # noqa: N802
        """实际用于绘制的首字母：显式值优先，否则从 ``name`` 派生。"""
        if self._initials:
            return self._initials
        if not self._name:
            return ""
        return deriveInitials(
            self._name, self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        )

    def image(self) -> Optional[QPixmap]:
        return self._image

    def setImage(self, pixmap: Optional[QPixmap]) -> None:  # noqa: N802
        """设图片（**cover 等比填满裁剪**，不是拉伸 —— 16:9 塞进方形会被压扁）。

        去重按 ``cacheKey()`` + 设备像素比，**不按 ``==``**：``QPixmap.__eq__`` 不是值
        比较（同 AGENTS.md 里 ``QColor`` 那条）。
        """
        new = None if pixmap is None or QPixmap(pixmap).isNull() else QPixmap(pixmap)
        old = self._image
        if old is not None and new is not None:
            if (
                old.cacheKey() == new.cacheKey()
                and old.devicePixelRatio() == new.devicePixelRatio()
            ):
                return
        elif old is None and new is None:
            return
        self._image = new
        self.imageChanged.emit(new)
        self.update()

    # -- 外观 ---------------------------------------------------------------

    def shape(self) -> ElaAvatarShapeType:
        return self._shape

    def setShape(self, shape) -> None:  # noqa: N802
        value = ElaAvatarShapeType(shape)
        if value == self._shape:
            return
        self._shape = value
        self.shapeChanged.emit(value)
        self.update()

    def avatarSize(self) -> ElaAvatarSizeType:
        return self._size

    def setAvatarSize(self, size) -> None:  # noqa: N802
        value = ElaAvatarSizeType(size)
        if value == self._size:
            return
        self._size = value
        self._applyExtent()
        self.avatarSizeChanged.emit(value)
        self.update()

    def extent(self) -> int:
        """当前档位的边长（px）。"""
        return int(self._size)

    def presence(self) -> ElaAvatarPresenceType:
        return self._presence

    def setPresence(self, presence) -> None:  # noqa: N802
        value = ElaAvatarPresenceType(presence)
        if value == self._presence:
            return
        self._presence = value
        self.presenceChanged.emit(value)
        self.update()

    def backgroundColor(self) -> QColor:  # noqa: N802
        """显式设置的底色（未设置时为无效 ``QColor``）。"""
        return QColor(self._background_color)

    def setBackgroundColor(self, color) -> None:  # noqa: N802
        value = QColor(color)
        if value.rgba() == self._background_color.rgba():
            return
        self._background_color = value
        self.backgroundColorChanged.emit(value)
        self.update()

    def foregroundColor(self) -> QColor:  # noqa: N802
        return QColor(self._foreground_color)

    def setForegroundColor(self, color) -> None:  # noqa: N802
        value = QColor(color)
        if value.rgba() == self._foreground_color.rgba():
            return
        self._foreground_color = value
        self.foregroundColorChanged.emit(value)
        self.update()

    def effectiveBackgroundColor(self) -> QColor:  # noqa: N802
        """实际绘制的底色，回退链：显式 → 名字哈希调色板 → 强调色 → 抬起表面。

        有名字时**先走哈希调色板**：一排头像全是同一个强调色会像一排色块，看不出是
        不同的人。哈希是确定性的（见 :func:`stableHash`），同一个人每次启动同色。
        """
        if self._background_color.isValid():
            color = QColor(self._background_color)
        elif self._name:
            palette = chartPalette(currentMode())
            if palette:
                color = QColor(palette[stableHash(self._name) % len(palette)])
            else:
                color = accent(currentMode())
        else:
            color = surfaceRaised(currentMode())
        if not self.isEnabled():
            color.setAlpha(_DISABLED_BG_ALPHA)
        return color

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.extent(), self.extent())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    # -- 绘制 ---------------------------------------------------------------

    def _clipPath(self) -> QPainterPath:  # noqa: N802
        path = QPainterPath()
        rect = QRectF(self.rect()).adjusted(
            _STROKE_INSET, _STROKE_INSET, -_STROKE_INSET, -_STROKE_INSET
        )
        if rect.isEmpty():
            return path
        if self._shape == ElaAvatarShapeType.Circular:
            path.addEllipse(rect)
        else:
            path.addRoundedRect(rect, _SQUARE_RADIUS, _SQUARE_RADIUS)
        return path

    def _initialsFont(self) -> QFont:  # noqa: N802
        """字号随档位走：≥48 用 18/半粗，≥32 用 14/半粗，更小用 12/常规。

        小头像塞 14px 半粗会糊成一团（笔画挤在一起），而大头像用 12px 又显得空。
        """
        extent = self.extent()
        font = self.font()
        if extent >= 48:
            font.setPixelSize(18)
            font.setWeight(QFont.Weight.DemiBold)
        elif extent >= 32:
            font.setPixelSize(14)
            font.setWeight(QFont.Weight.DemiBold)
        else:
            font.setPixelSize(12)
            font.setWeight(QFont.Weight.Normal)
        return font

    def _surroundingSurface(self) -> QColor:
        """环要画的颜色 = **圆点周围那层表面**。

        沿父链找 ``pyqt5SurfaceColor`` 动态属性；找不到就退回画布色。这是个**已知
        会出错的默认**：浮在任意表面上的头像若宿主没声明属性，环会取画布色而显出一圈
        亮边（Fluent 侧同样的问题，属性名是 ``fluentSurfaceColor``）。
        """
        node = self.parentWidget()
        while node is not None:
            value = node.property(SURFACE_PROPERTY)
            if isinstance(value, QColor) and value.isValid():
                return QColor(value)
            node = node.parentWidget()
        return surface(currentMode())

    def _presenceGeometry(self) -> QRect:  # noqa: N802
        extent = self.extent()
        dot = _PRESENCE_DOT.get(extent, 8)
        host = dot + _PRESENCE_RING * 2
        return QRect(
            max(0, self.width() - host), max(0, self.height() - host), host, host
        )

    def _applyExtent(self) -> None:
        """**硬锁**尺寸档位：头像不是可拉伸控件，让布局去拉只会得到椭圆。"""
        extent = self.extent()
        self.setFixedSize(extent, extent)

    def _onThemeChanged(self, mode) -> None:  # noqa: N802 (基类钩子)
        super()._onThemeChanged(mode)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        clip = self._clipPath()
        if clip.isEmpty():
            return
        inner = QRectF(self.rect()).adjusted(
            _STROKE_INSET, _STROKE_INSET, -_STROKE_INSET, -_STROKE_INSET
        )

        # 1. 底色永远先画 —— 后面三级内容都画在它上面。
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.effectiveBackgroundColor())
        painter.drawPath(clip)

        foreground = (
            QColor(self._foreground_color) if self._foreground_color.isValid() else None
        )

        # 2/3/4. 图片 → 首字母 → 人形字形（三级回退）。
        if self._image is not None and not self._image.isNull():
            painter.save()
            painter.setClipPath(clip)
            if not self.isEnabled():
                painter.setOpacity(_DISABLED_IMAGE_ALPHA)
            drawCoverPixmap(painter, inner, self._image)
            painter.restore()
        else:
            initials = self.effectiveInitials()
            if initials:
                if foreground is None:
                    foreground = contrastingText(self.effectiveBackgroundColor())
                painter.setPen(QPen(foreground))
                painter.setFont(self._initialsFont())
                painter.drawText(inner, Qt.AlignmentFlag.AlignCenter, initials)
            else:
                icon_px = max(12, self.extent() // 2)
                color = (
                    foreground
                    if foreground is not None
                    else contrastingText(self.effectiveBackgroundColor())
                )
                drawElaIcon(
                    painter,
                    QRectF(
                        (self.width() - icon_px) / 2.0,
                        (self.height() - icon_px) / 2.0,
                        icon_px,
                        icon_px,
                    ),
                    _FALLBACK_ICON,
                    color,
                    ratio=self.devicePixelRatioF(),
                )

        # 5. 1px 描边压在**所有**内容之上（含图片）—— 否则图片会盖掉描边，头像就
        #    在深色底上「化开」了。
        ring = QColor(border(currentMode()))
        ring.setAlpha(_RING_ALPHA_DARK if ring.lightness() < 128 else _RING_ALPHA_LIGHT)
        if ring.alpha() > 0:
            painter.setPen(QPen(ring, 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(clip)

        # 6. 状态圆点：先把「环」画成周围表面的颜色（这是 Avatar 画的，不是徽标画的），
        #    再把圆点画在正中。环的存在是为了在深色头像上把点分离出来。
        if self._presence is not ElaAvatarPresenceType.None_:
            geometry = self._presenceGeometry()
            host_px = geometry.width()
            dot = host_px - _PRESENCE_RING * 2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._surroundingSurface())
            # 走 QRectF 而不是 QRect：``QRect.adjusted`` 的四个参数是 **int**，
            # 传 0.5 这种半像素内缩直接 TypeError —— 而这行在 paintEvent 里，
            # TypeError = 整个进程 0xC0000409 静默崩（无 traceback）。实测踩过。
            painter.drawEllipse(
                QRectF(geometry).adjusted(
                    _STROKE_INSET, _STROKE_INSET, -_STROKE_INSET, -_STROKE_INSET
                )
            )
            painter.setBrush(self._presenceColor())
            painter.drawEllipse(
                QRectF(
                    geometry.x() + _PRESENCE_RING,
                    geometry.y() + _PRESENCE_RING,
                    dot,
                    dot,
                )
            )

    def _presenceColor(self) -> QColor:  # noqa: N802
        """状态圆点填充色。

        ``None_`` 返回**无效 ``QColor``**：那一档本来就不画点，色值没有意义。返回
        无效色而不是 KeyError / 随便挑一个，是为了让「读色」在任何状态下都安全
        （探针、测试、宿主自绘扩展都会读它）。

        ``Offline`` 走 ``textDisabled``（灰）而不是任何角色色：它的语义是「不可用」而
        不是「危险」。用红或黄会让一排灰色离线用户看起来像一片告警。
        """
        if self._presence is ElaAvatarPresenceType.None_:
            return QColor()
        role = _PRESENCE_ROLE[self._presence]
        if role is None:
            return textDisabled(currentMode())
        return statusColor(currentMode(), role)
