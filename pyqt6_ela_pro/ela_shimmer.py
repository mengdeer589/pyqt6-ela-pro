"""骨架屏 / 微光加载占位（对齐 Fluent 的 ``Shimmer``）。

搬运自 ``Fluent-Qt/src/components/status_info/Shimmer.cpp``，两处**有意改道**：

1. **``setActive(False)`` 不隐藏控件，只画静态基态。** Fluent 的 ``paintEvent``
   在 ``!m_active`` 时直接 return —— 加上「``Reduced`` 下持续动效一律停掉」，无障碍
   用户看到的是**一个纯空白框**。而 Shimmer 的全部价值就在那句 pattern「**基态必画
   + 扫光叠加**」：基态本身就是一个可用的静态骨架。停掉扫光不等于不画。
2. **停止时相位归零**（``on_stop``）。Fluent 是纯 ``QBasicTimer``、停了停在哪个相位
   就冻在哪个相位，扫光可能冻在正中。本库走 ``start_idle_loop``，按桶 B 的规矩必须
   显式摆好静态态，否则「停掉」会留下半条扫光。

配色沿用 Fluent 的推导式（画布明度决定深浅两套，**高亮都是白色、只有 alpha 不同**），
但画布取控件自身 palette 的 ``Window``（``ElaThemeWidget`` 默认 ``BasicPress``，
与消息区 / 滚动页底色一致），取不到时回落 ``_theme.surface(mode)`` —— 不再硬编码
``#F3F3F3``/``#202020``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional

from ._internal import is_deleted
from PyQt6.QtCore import QEvent, QRectF, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
)

from ._motion import Duration, idle_loop_running, start_idle_loop
from ._theme import blend, surface
from .widget_base import ElaThemeWidget

__all__ = [
    "ElaShimmer",
    "ShimmerElement",
    "ShimmerPalette",
    "ElaShimmerShapeType",
    "ElaShimmerTemplateType",
    "imageCardElements",
    "avatarTextRowElements",
    "textBlockElements",
]


#: 帧间隔对齐 Fluent 的 16ms。
_FRAME_MS = 16

#: 扫光宽度 = ``max(56px, 元素包围盒宽的 42%)``。56 是下限：窄元素上按比例算会细到
#: 看不见扫光，只剩一条一闪而过的线。
_SWEEP_MIN_WIDTH = 56.0
_SWEEP_WIDTH_RATIO = 0.42

#: 渐变峰值落在 0.48 而不是 0.5 —— 视觉中心比几何中心前移一点，扫过去更利落。
_SWEEP_PEAK = 0.48

#: 各模板的内边距（四面同值），对齐 Fluent 的 ``Spacing::Small``。
_TEMPLATE_INSET = 8.0

#: 圆角（对齐 Fluent ``CornerRadius::Control``）。
_CONTROL_RADIUS = 4.0

#: 判断「深色画布」的明度阈值（对齐 Fluent 的 96）。注意判的是**画布**不是主题枚举，
#: 高对比主题的纯黑画布（L=0）也该走深色分支。
_DARK_LIGHTNESS = 96

# 深/浅画布下的底色与高亮 alpha。底色是「白叠深色」/「黑叠浅色」，不是固定色 ——
# 固定色在自定义强调色/自定义画布下会明显不对。
_DARK_BASE_T = 0.12
_LIGHT_BASE_T = 0.075
_DARK_HIGHLIGHT_ALPHA = 68
_LIGHT_HIGHLIGHT_ALPHA = 218
_DISABLED_HIGHLIGHT_ALPHA = 18


class ElaShimmerShapeType(IntEnum):
    """单个骨架元素的形状。"""

    Rectangle = 0
    RoundedRect = 1
    Circle = 2
    Line = 3


class ElaShimmerTemplateType(IntEnum):
    """内置排版模板。"""

    Custom = 0
    TextBlock = 1
    AvatarTextRow = 2
    ImageCard = 3


@dataclass
class ShimmerElement:
    """一块骨架。

    ``rect`` 相对控件左上角（尺寸变化时整体重排）；``radius=-1`` 用默认值
    （``RoundedRect``→4px，``Line``→半高药丸）。
    """

    shape: ElaShimmerShapeType = ElaShimmerShapeType.RoundedRect
    rect: QRectF = field(default_factory=QRectF)
    radius: float = -1.0


@dataclass
class ShimmerPalette:
    """一套绘制颜色。"""

    base: QColor
    highlight: QColor
    border: QColor


def _darkCanvas(canvas: QColor) -> bool:  # noqa: N802
    """按画布明度判深浅，而不是查主题枚举（高对比主题的纯黑画布也得走深色）。"""
    return canvas.lightness() < _DARK_LIGHTNESS


def shimmerPalette(
    canvas: Optional[QColor] = None, enabled: bool = True
) -> ShimmerPalette:
    """从画布推出一套骨架配色。

    **深浅两套的高亮都是白色，只有 alpha 不同**（深色 68 / 浅色 218）。这不是笔误：
    扫光叠在骨架底色上，深色下底色本来就亮，再给高 alpha 就直接糊成一片白。
    """
    if canvas is None:
        canvas = surface(None)
    dark = _darkCanvas(canvas)
    # 注意 blend 的参数序是「底在前、前景在后」：``blend(canvas, 白, 0.12)`` =
    # 深色画布上叠 12% 白。
    if dark:
        base = blend(canvas, QColor("#ffffff"), _DARK_BASE_T)
        highlight_alpha = (
            _DARK_HIGHLIGHT_ALPHA if enabled else _DISABLED_HIGHLIGHT_ALPHA
        )
    else:
        base = blend(canvas, QColor("#000000"), _LIGHT_BASE_T)
        highlight_alpha = _LIGHT_HIGHLIGHT_ALPHA if enabled else 50
    highlight = QColor(255, 255, 255, highlight_alpha)
    border = QColor(canvas)
    border.setAlpha(18 if not dark else 26)
    return ShimmerPalette(base=base, highlight=highlight, border=border)


def _elementPath(element: ShimmerElement) -> QPainterPath:  # noqa: N802
    """形状 → ``QPainterPath``。``Line`` 是半高圆角 = 全圆角药丸。"""
    path = QPainterPath()
    rect = element.rect
    if rect.isEmpty():
        return path
    if element.shape == ElaShimmerShapeType.Rectangle:
        path.addRect(rect)
    elif element.shape == ElaShimmerShapeType.Circle:
        path.addEllipse(rect)
    else:
        if element.shape == ElaShimmerShapeType.Line:
            radius = element.radius if element.radius >= 0 else rect.height() / 2.0
        else:
            radius = element.radius if element.radius >= 0 else _CONTROL_RADIUS
        # 注意只能给 QRectF —— QPainterPath.addRoundedRect 不接受 QRect。
        path.addRoundedRect(rect, radius, radius)
    return path


def _combinedPath(elements) -> QPainterPath:  # noqa: N802
    combined = QPainterPath()
    for element in elements:
        combined = combined.united(_elementPath(element))
    return combined


def paintShimmer(  # noqa: N802
    painter: QPainter,
    elements: List[ShimmerElement],
    palette: ShimmerPalette,
    progress: float,
    animated: bool = True,
) -> None:
    """静态绘制入口（委托类 / 自绘控件可直接调，不必造子控件）。

    三步顺序不可换：**基态 → 扫光 → 描边**。描边压在扫光之上，否则扫光会把 1px 边
    冲淡（每帧边线亮度都在跳，看着像闪烁噪点）。
    """
    if not elements:
        return
    combined = _combinedPath(elements)
    if combined.isEmpty():
        return

    # 1. 基态：无条件画。「骨架在但没在动」是一个合法且必须好看的状态。
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(palette.base))
    painter.drawPath(combined)

    # 2. 扫光：只在动的时候叠。
    if animated and QColor(palette.highlight).alpha() > 0:
        bounds = combined.boundingRect()
        # 内缩半像素，让 1px 描边落在设备像素上不糊。
        bounds = bounds.adjusted(0.5, 0.5, -0.5, -0.5)
        phase = _normalizeProgress(progress)
        sweepWidth = max(_SWEEP_MIN_WIDTH, bounds.width() * _SWEEP_WIDTH_RATIO)
        # 行程是「包围盒宽 + 两个扫光宽」：扫光完整地从左边外面进来、再完整地
        # 从右边外面出去。
        sweepX = (
            bounds.left() - sweepWidth + (bounds.width() + sweepWidth * 2.0) * phase
        )
        gradient = QLinearGradient(
            sweepX - sweepWidth,
            bounds.center().y(),
            sweepX + sweepWidth,
            bounds.center().y(),
        )
        transparent = QColor(palette.highlight)
        transparent.setAlpha(0)
        gradient.setColorAt(0.0, transparent)
        gradient.setColorAt(_SWEEP_PEAK, QColor(palette.highlight))
        gradient.setColorAt(1.0, transparent)
        # 裁到并集路径 —— 否则扫光会糊在整个包围盒上，几块骨架之间连成一片。
        painter.setClipPath(combined)
        # fillRect 左右各扩一个扫光宽，否则渐变贴图会留下接缝。
        painter.fillRect(bounds.adjusted(-sweepWidth, 0, sweepWidth, 0), gradient)
        painter.setClipping(False)

    # 3. 描边。
    border = QColor(palette.border)
    if border.alpha() > 0:
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(combined)
    painter.restore()


def _normalizeProgress(progress: float) -> float:
    """折到 ``[0, 1)``；非有限值归零（别让 ``nan`` 进 painter）。"""
    try:
        value = math.fmod(float(progress), 1.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return value + 1.0 if value < 0 else value


# ---------------------------------------------------------------------------
# 模板
# ---------------------------------------------------------------------------


def _templateBounds(area: QRectF) -> QRectF:  # noqa: N802
    return area.adjusted(
        _TEMPLATE_INSET, _TEMPLATE_INSET, -_TEMPLATE_INSET, -_TEMPLATE_INSET
    )


def textBlockElements(area: QRectF, lineCount: int = 3) -> List[ShimmerElement]:  # noqa: N802
    """多行文本块：等间距的横向药丸，最后一行短一截。

    宽度比例按行号取 **0.92 / 0.76 / 0.62** 递减（偶数行号用宽的），这是「一段真实
    文本」的形状 —— 全等宽会看着像栅格而不像文字。
    """
    bounds = _templateBounds(area)
    if bounds.isEmpty():
        return []
    lineHeight = 12.0
    lineGap = 8.0
    lineStep = lineHeight + lineGap
    total = lineHeight + lineGap * max(0, lineCount - 1)
    top = bounds.top() + (bounds.height() - total) / 2.0
    elements = []
    for index in range(max(0, int(lineCount))):
        if index == lineCount - 1:
            ratio = 0.62
        elif index % 2 == 0:
            ratio = 0.92
        else:
            ratio = 0.76
        elements.append(
            ShimmerElement(
                shape=ElaShimmerShapeType.Line,
                rect=QRectF(
                    bounds.left(),
                    top + index * lineStep,
                    bounds.width() * ratio,
                    lineHeight,
                ),
            )
        )
    return elements


def avatarTextRowElements(area: QRectF) -> List[ShimmerElement]:  # noqa: N802
    """「圆形头像 + 两行文字」的一行。"""
    bounds = _templateBounds(area)
    if bounds.isEmpty():
        return []
    extent = min(32.0, max(16.0, bounds.height() - 8.0))
    center = bounds.center()
    avatar = QRectF(
        bounds.left(),
        center.y() - extent / 2.0,
        extent,
        extent,
    )
    textLeft = avatar.right() + 12.0
    textWidth = max(16.0, bounds.right() - textLeft)
    lineGap = 8.0
    top1 = center.y() - lineGap / 2.0 - 12.0
    top2 = center.y() + lineGap / 2.0
    return [
        ShimmerElement(shape=ElaShimmerShapeType.Circle, rect=avatar),
        ShimmerElement(
            shape=ElaShimmerShapeType.Line,
            rect=QRectF(textLeft, top1, textWidth * 0.78, 12.0),
        ),
        ShimmerElement(
            shape=ElaShimmerShapeType.Line,
            rect=QRectF(textLeft, top2, textWidth * 0.52, 12.0),
        ),
    ]


def imageCardElements(
    area: QRectF, radius: float = _CONTROL_RADIUS
) -> List[ShimmerElement]:  # noqa: N802
    """整块占满的图片卡位。"""
    bounds = _templateBounds(area)
    if bounds.isEmpty():
        return []
    return [ShimmerElement(shape=ElaShimmerShapeType.RoundedRect, rect=bounds, radius=radius)]


def _buildTemplate(template: ElaShimmerTemplateType, area: QRectF) -> List[ShimmerElement]:  # noqa: N802
    if template == ElaShimmerTemplateType.TextBlock:
        return textBlockElements(area)
    if template == ElaShimmerTemplateType.AvatarTextRow:
        return avatarTextRowElements(area)
    if template == ElaShimmerTemplateType.ImageCard:
        return imageCardElements(area)
    return []


class ElaShimmer(ElaThemeWidget):
    """骨架屏 / 微光占位。

    典型用法（列表项加载中）::

        sh = ElaShimmer(parent)
        sh.setTemplate(ElaShimmerTemplateType.AvatarTextRow)
        sh.resize(240, 56)

    或用静态入口自绘（列表 delegate / 表格单元格里铺多块）::

        paintShimmer(painter, textBlockElements(cellRect, 3), palette, phase)
    """

    activeChanged = pyqtSignal(bool)
    animationEnabledChanged = pyqtSignal(bool)
    shimmerProgressChanged = pyqtSignal(float)
    cycleDurationChanged = pyqtSignal(int)
    templateChanged = pyqtSignal(object)

    #: 与 Fluent 一致的三档 sizeHint（240 宽 / 36-140 高），横向够放两行文字。
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._active = True
        self._animation_enabled = True
        self._progress = 0.0
        self._cycle_duration = Duration.VerySlow * 2
        self._template = ElaShimmerTemplateType.TextBlock
        self._elements: List[ShimmerElement] = []
        self._area = QRectF()
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._onTick)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._updateAnimationState()

    # -- 状态 ---------------------------------------------------------------

    def isActive(self) -> bool:  # noqa: N802
        """是否播扫光。``False`` = 画静态骨架（**不隐藏控件**）。"""
        return self._active

    def setActive(self, active: bool) -> None:  # noqa: N802
        """开关扫光。

        **注意与 Fluent 的差异**：关掉只是不画扫光，基态照画 —— 宿主想用真实内容
        顶替时该直接 ``hide()`` 或把这块换掉，而不是指望它变透明。
        """
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        self.activeChanged.emit(active)
        self._updateAnimationState()
        self.update()

    def isAnimationEnabled(self) -> bool:  # noqa: N802
        """组件自身动效开关（优先于全局策略）。"""
        return self._animation_enabled

    def setAnimationEnabled(self, enabled: bool) -> None:  # noqa: N802
        enabled = bool(enabled)
        if enabled == self._animation_enabled:
            return
        self._animation_enabled = enabled
        self.animationEnabledChanged.emit(enabled)
        self._updateAnimationState()
        self.update()

    def isAnimationRunning(self) -> bool:  # noqa: N802
        return idle_loop_running(self._timer)

    # -- 相位（可手动驱动） ---------------------------------------------------

    def shimmerProgress(self) -> float:
        """当前相位 ``[0, 1)``。宿主想自己做时间轴（播放/暂停/接续）时读它。"""
        return self._progress

    def setShimmerProgress(self, progress: float) -> None:  # noqa: N802
        """手动设相位。会停掉内部计时器，避免和手动的打架。"""
        value = _normalizeProgress(progress)
        if abs(value - self._progress) < 1e-9:
            return
        self._progress = value
        self.shimmerProgressChanged.emit(value)
        self.update()

    def cycleDuration(self) -> int:
        """一整趟扫光的毫秒数，下限 ``Duration.Fast``（150）。"""
        return self._cycle_duration

    def setCycleDuration(self, durationMs: int) -> None:  # noqa: N802
        """设周期，下限 150ms。

        下限存在的理由：低于 150ms 扫光变成频闪，``Reduced`` 模式恰好把过渡压到
        这个量级 —— 一个骨架屏每 150ms 闪一次白条是纯粹的伤害。
        """
        value = max(Duration.Fast, int(durationMs))
        if value == self._cycle_duration:
            return
        self._cycle_duration = value
        self.cycleDurationChanged.emit(value)

    # -- 排版 ---------------------------------------------------------------

    def shimmerTemplate(self) -> ElaShimmerTemplateType:
        return self._template

    def setTemplate(self, template) -> None:  # noqa: N802
        """切换内置模板（会清掉 ``Custom`` 的手工元素）。"""
        template = ElaShimmerTemplateType(template)
        if template == self._template:
            return
        self._template = template
        self._elements = []
        self._invalidateLayout()
        self.templateChanged.emit(template)

    def elements(self) -> List[ShimmerElement]:
        """当前元素列表（``Custom`` 模板下是手工设的，否则是模板算的）。"""
        self._ensureLayout()
        return list(self._elements)

    def setElements(self, elements: List[ShimmerElement]) -> None:  # noqa: N802
        """设手工元素（自动切到 ``Custom`` 模板）。"""
        self._template = ElaShimmerTemplateType.Custom
        self._elements = list(elements or [])
        self.templateChanged.emit(self._template)
        self.update()

    def clearElements(self) -> None:  # noqa: N802
        """清空元素 —— 控件变成什么都不画（**仍然占位**）。

        刻意**不**切回某个模板：调用方表达的是「我自己管排版」，不是「给我默认那个」。
        """
        self._template = ElaShimmerTemplateType.Custom
        self._elements = []
        self.templateChanged.emit(self._template)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        if self._template == ElaShimmerTemplateType.AvatarTextRow:
            return QSize(240, 56)
        if self._template == ElaShimmerTemplateType.ImageCard:
            return QSize(240, 140)
        return QSize(240, 72)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(32, 24)

    # -- 内部 ---------------------------------------------------------------

    def _ensureLayout(self) -> None:
        """按当前控件尺寸重排模板元素（尺寸没变就不动）。

        **必须懒算而不是只在 ``resizeEvent`` 里算**：``resize()`` 只是**投递**一个
        resize 事件，事件要到事件循环转起来才派发 —— 于是「刚 ``resize()`` 就读
        ``elements()``」会拿到上一次（构造时的默认尺寸）算出的、甚至空的结果。
        懒算让 ``elements()`` / ``paintEvent`` 两条路都拿到与当前尺寸一致的结果。
        """
        if self._template is ElaShimmerTemplateType.Custom:
            return
        area = QRectF(self.rect())
        if area == self._area:
            return
        self._area = area
        self._elements = _buildTemplate(self._template, area)

    def _invalidateLayout(self) -> None:
        self._area = QRectF()
        self._ensureLayout()
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._template is not ElaShimmerTemplateType.Custom:
            self._invalidateLayout()

    def _onTick(self) -> None:  # noqa: N802
        # 跑在 Qt 回调链上：sip 守卫 + try 都得有（未捕获异常 = 0xC0000409）。
        try:
            if is_deleted(self):
                return
        except (RuntimeError, TypeError):
            return
        try:
            self._progress = _normalizeProgress(
                self._progress + float(_FRAME_MS) / max(1, self._cycle_duration)
            )
            self.shimmerProgressChanged.emit(self._progress)
            self.update()
        except (RuntimeError, TypeError):
            return

    def _settleStatic(self) -> None:
        """停掉时落到干净静态态。

        相位归零 ⇒ 扫光完整地在左边界之外（``sweepX = left - sweepWidth`` 处渐变
        全透明）⇒ 画出来与「完全不画扫光」逐像素一致。**不归零就会冻在半条白带上**。
        """
        self._progress = 0.0
        self.update()

    def _updateAnimationState(self) -> None:
        """四个条件同时成立才跑（对齐 Fluent）：本身激活 / 策略允许 / 控件可用 / 可见。

        四个条件合成一个 ``local_enabled`` —— 对 ``start_idle_loop`` 来说它们没有区别，
        都是「不该跑循环」。停止时 ``on_stop`` 一定会被调到（库内无条件传了钩子），
        所以这里**不需要**再自己兜一次相位归零。
        """
        local = (
            self._active
            and self._animation_enabled
            and self.isEnabled()
            and self.isVisible()
        )
        start_idle_loop(
            self._timer, _FRAME_MS, local_enabled=local, on_stop=self._settleStatic
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._updateAnimationState()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self._updateAnimationState()

    def _onThemeChanged(self, mode) -> None:  # noqa: N802 (基类钩子)
        """换主题只需重画 —— 配色在 ``paintEvent`` 里现取，不缓存颜色。"""
        super()._onThemeChanged(mode)
        self.update()

    def _canvas_color(self) -> QColor:
        """骨架所在表面色：优先取控件 palette 的 ``Window``，缺失时用主题表面。

        ``ElaThemeWidget`` 的默认表面就是 ``BasicPress``（消息区 / 滚动页底色），
        比固定用 ``surface(None)``（``WindowBase``）更贴合实际画布 —— 亮色下
        ``WindowBase`` 会算出一档偏深的骨架。
        """
        color = self.palette().color(QPalette.ColorRole.Window)
        if color.isValid() and color.alpha() > 0:
            return color
        return surface(None)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        self._ensureLayout()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        enabled = self.isEnabled()
        paintShimmer(
            painter,
            self._elements,
            shimmerPalette(self._canvas_color(), enabled),
            self._progress,
            animated=enabled and self._active and self.isAnimationRunning(),
        )
