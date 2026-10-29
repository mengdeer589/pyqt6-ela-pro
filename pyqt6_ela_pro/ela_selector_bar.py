"""分段控件（SelectorBar）：一排互斥选项 + 会「移动 + 绽开」的高亮指示器。

搬运自 ``Fluent-Qt/src/components/navigation/SelectorBar.*``。

指示器动画是本组件的全部价值，也是唯一需要动脑的部分
----------------------------------------------------
**三个关键帧的「压扁-移动-绽开」**::

    进度 0.00  →  旧位置的 16px 细条
    进度 0.55  →  新位置的 16px 细条     ← 只有 55% 的时间花在「移动」上
    进度 1.00  →  新位置的 20px 指示器   ← 剩下 45% 花在「绽开」上

机制是 ``QVariantAnimation`` **直接插值 ``QRect``**（``QRect`` 是注册过的 QVariant
类型，Qt 会逐分量 lerp），所以 x/y/w/h 各自独立动画，不需要任何 skew 变换。
**``QPropertyAnimation(geometry)`` 做不到这个** —— 它绑在具体控件上，而指示器不是一
个控件（它是画在 ``paintEvent`` 里的一块矩形）。

**为什么移动占 55%**：等速的话指示器会「先飘过去再鼓起来」，看着像两个动作拼在一起而
不是一次连贯的滑入。让移动占前 55%、抵达瞬间就开始变宽，观感上是一个动作。

**静止时 relayout 不打断在飞的动画**（只在动画不在跑时才对齐新几何）—— 否则用户改窗口
大小会把指示器「拽回去」再重播一遍。

动效
----
指示器是**过渡**（``Transition``）不是持续动效，所以 ``Reduced`` 下被压到 ≤50ms、
``Disabled`` 下同步落终值，走 ``_motion.start_transition``。收尾**只**通过它的
``on_complete`` 参数注册，不要再自己连 ``anim.finished``（叠连接 = 收尾跑两遍）。

**没有多选。** ``selectedIndex`` 是单个 int。``-1``（什么都不选）是合法状态：插入项时若
当前无选中会**自动选中**插入点附近的第一项（什么都不选的分段控件看起来像坏了），而
``clearSelection()`` 随时能回到无选中。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Any, List, Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import QWidget

from PyQt6ElaWidgetTools import ElaIconType

from ._motion import Duration, start_transition
from ._styles import drawElaIcon
from ._theme import (
    accent,
    blend,
    currentMode,
    surfaceRaised,
    text,
    textDisabled,
    textMuted,
)
from .widget_base import ElaThemeWidget

__all__ = ["ElaSelectorBar", "SelectorBarItem", "ElaSelectorBarOverflowType"]


class ElaSelectorBarOverflowType(IntEnum):
    """溢出时的交互方式。"""

    ScrollButtons = 0
    """两端各一个 40px 箭头按钮（默认）。到头时**置灰而不是隐藏**（位置恒定、宽度不跳）。"""

    MoreButton = 1
    """右端一个 40px 的「更多」按钮，溢出项由宿主在弹层里补。"""


@dataclass
class SelectorBarItem:
    """一个分段；``data`` 是任意负载（本控件不解释），``selected`` 是由
    ``setSelectedIndex`` 统一写的**派生镜像**，外部不要直接改。
    """

    text: str = ""
    icon: Optional[int] = None
    enabled: bool = True
    visible: bool = True
    selected: bool = False
    data: Any = None
    accessibleName: str = ""


class _Metrics:
    """行内几何。**写死不主题派生**（与 Fluent 一致）：这些数字是这套设计的骨架，
    跟着主题变会让分段控件在不同主题下长得不一样。"""

    rowHeight = 44
    itemVisualHeight = 36
    horizontalPadding = 16
    iconSize = 16
    iconGap = 8
    minItemWidth = 48
    maxItemWidth = 220
    overflowButtonWidth = 40
    indicatorHeight = 3
    indicatorWidth = 20
    #: 移动阶段的细条宽度（= 指示器最终宽度的 80%）。
    collapsedIndicatorWidth = 16
    #: 「移动」占整段动画的比例，剩下的都是「绽开」。
    travelRatio = 0.55
    defaultWidth = 520
    itemFontPx = 14


class ElaHitType(IntEnum):
    """命中目标。``None_`` 也涵盖「命中了但不可交互」（禁用项）。"""

    None_ = 0
    Item = 1
    OverflowBack = 2
    OverflowForward = 3
    OverflowMore = 4


class ElaSelectorBar(ElaThemeWidget):
    """分段控件。

    ::

        bar = ElaSelectorBar(parent)
        bar.addItems(["最近", "全部", "已归档"])
        bar.setSelectedIndex(0)
        bar.itemActivated.connect(lambda i, item: print(i, item.text))
    """

    itemCountChanged = pyqtSignal(int)
    itemsChanged = pyqtSignal()
    itemActivated = pyqtSignal(int, object)
    selectedIndexChanged = pyqtSignal(int)
    overflowBehaviorChanged = pyqtSignal(object)
    overflowActivated = pyqtSignal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._items: List[SelectorBarItem] = []
        self._selected_index = -1
        self._overflow_behavior = ElaSelectorBarOverflowType.ScrollButtons
        self._item_font_px = _Metrics.itemFontPx

        # 懒布局：几何按需重算，重算前标脏。
        self._layout_dirty = True
        self._item_rects: List[QRect] = []
        self._visible: List[int] = []
        self._first_visible = 0
        self._overflown = False
        self._overflow_back_rect = QRect()
        self._overflow_forward_rect = QRect()
        self._overflow_more_rect = QRect()

        self._indicator_rect = QRect()
        self._indicator_anim = QVariantAnimation(self)
        self._indicator_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # 只连一次（见 _animateIndicator 的说明）
        self._indicator_anim.valueChanged.connect(self._onIndicatorValue)

        self._pressed = ElaHitType.None_
        self._pressed_index = -1
        self._hovered = ElaHitType.None_
        self._hovered_index = -1

        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # -- 项 -----------------------------------------------------------------

    def itemCount(self) -> int:  # noqa: N802
        return len(self._items)

    def items(self) -> List[SelectorBarItem]:
        """全部项的**副本**列表。

        **返回副本而不是活对象**：``selected`` 是派生镜像、内部状态由 setter 维护，
        让宿主能直接改内部项等于给了一条「绕过全部校验与信号」的后门。要改就用
        ``setItemText`` / ``setItemEnabled`` 等。``itemAt()`` 同理。
        """
        return [
            SelectorBarItem(
                text=item.text,
                icon=item.icon,
                enabled=item.enabled,
                visible=item.visible,
                selected=item.selected,
                data=item.data,
                accessibleName=item.accessibleName,
            )
            for item in self._items
        ]

    def itemAt(self, index: int) -> Optional[SelectorBarItem]:  # noqa: N802
        """取第 ``index`` 项的**副本**；下标非法时返回 ``None``（不抛）。"""
        if not self._validIndex(index):
            return None
        source = self._items[index]
        return SelectorBarItem(
            text=source.text,
            icon=source.icon,
            enabled=source.enabled,
            visible=source.visible,
            selected=source.selected,
            data=source.data,
            accessibleName=source.accessibleName,
        )

    def addItem(self, text: str = "", icon: Optional[int] = None) -> int:  # noqa: N802
        """追加一项，返回新下标。"""
        return self.insertItem(len(self._items), SelectorBarItem(text=text, icon=icon))

    def addItems(self, texts) -> None:  # noqa: N802
        for value in texts:
            self.addItem(value)

    def insertItem(self, index: int, item: SelectorBarItem) -> int:  # noqa: N802
        """在 ``index`` 前插入（越界会被夹到合法范围），返回实际插入位置。

        **插入时若当前无选中，会自动选中插入点附近的第一项**（与 Fluent 一致）——
        一个什么都不选的分段控件看起来像坏了。宿主不想要就紧接着调
        ``clearSelection()``。

        **``item`` 存的是副本**。``items()`` / ``itemAt()`` 的出参都是副本
        （``selected`` 是派生镜像、内部状态由 setter 维护），而入口这一路
        原本直接持有了调用方的对象 —— 宿主 ``item.text = ...`` 就等于绕过
        了全部校验与信号，与出参那条约定自相矛盾。
        """
        if not isinstance(item, SelectorBarItem):
            raise TypeError(f"item 必须是 SelectorBarItem，收到 {type(item).__name__}")
        position = max(0, min(int(index), len(self._items)))
        self._items.insert(position, replace(item))
        if self._selected_index >= position:
            self._selected_index += 1
        self._repairSelection(position)
        self._invalidateLayout()
        self.itemCountChanged.emit(len(self._items))
        self.itemsChanged.emit()
        return position

    def removeItem(self, index: int) -> bool:  # noqa: N802
        """删除一项。删掉的是当前选中项时，选中落到**最近的仍可选**项。"""
        if not self._validIndex(index):
            return False
        was_selected = self._selected_index == index
        self._items.pop(index)
        if self._selected_index > index:
            self._selected_index -= 1
        elif was_selected:
            self._selected_index = -1
        self._repairSelection(min(index, len(self._items) - 1))
        self._invalidateLayout()
        self.itemCountChanged.emit(len(self._items))
        self.itemsChanged.emit()
        return True

    def clearItems(self) -> None:  # noqa: N802
        if not self._items:
            return
        self._items.clear()
        self._selected_index = -1
        self._first_visible = 0
        self._invalidateLayout()
        self.itemCountChanged.emit(0)
        self.itemsChanged.emit()

    def setItemText(self, index: int, text: str) -> bool:  # noqa: N802
        if not self._validIndex(index):
            return False
        self._items[index].text = "" if text is None else str(text)
        self._invalidateLayout()
        self.itemsChanged.emit()
        return True

    def setItemIcon(self, index: int, icon: Optional[int]) -> bool:  # noqa: N802
        """设 ElaAwesome 图标（``ElaIconType.IconName`` 的整数值）。"""
        if not self._validIndex(index):
            return False
        self._items[index].icon = icon
        self._invalidateLayout()
        self.itemsChanged.emit()
        return True

    def setItemData(self, index: int, data: Any) -> bool:  # noqa: N802
        if not self._validIndex(index):
            return False
        self._items[index].data = data
        self.itemsChanged.emit()
        return True

    def setItemAccessibleName(self, index: int, name: str) -> bool:  # noqa: N802
        if not self._validIndex(index):
            return False
        self._items[index].accessibleName = "" if name is None else str(name)
        self.itemsChanged.emit()
        return True

    def setItemEnabled(self, index: int, enabled: bool) -> bool:  # noqa: N802
        """禁用一项。**禁掉的是当前选中项时另选一个**（优先下一项，其次上一项）。"""
        if not self._validIndex(index):
            return False
        self._items[index].enabled = bool(enabled)
        if not enabled and self._selected_index == index:
            # **不要先把 ``_selected_index`` 置 -1**：``_repairSelection`` 末段有
            # ``if target == self._selected_index: return``，预置成 -1 之后，
            # 「一个可选项都不剩」的情形下 target 也是 -1-> 直接 return，
            # 于是 ``items()`` 的 ``selected`` 镜像永远留着上一项的 True，
            # 与 ``selectedIndex() == -1`` 互相矛盾（实测：逐项禁用到最后一项）。
            self._repairSelection(
                index + 1 if index + 1 < len(self._items) else index - 1
            )
        self.update()
        return True

    def setItemVisible(self, index: int, visible: bool) -> bool:  # noqa: N802
        """隐藏一项（与禁用不同：**不占位**）。隐藏当前选中项时另选一个。"""
        if not self._validIndex(index):
            return False
        self._items[index].visible = bool(visible)
        if not visible and self._selected_index == index:
            self._repairSelection(  # 同 setItemEnabled：不要预置 -1
                index + 1 if index + 1 < len(self._items) else index - 1
            )
        self._first_visible = 0
        self._invalidateLayout()
        self.update()
        return True

    # -- 选中 ---------------------------------------------------------------

    def selectedIndex(self) -> int:  # noqa: N802
        """当前选中下标，``-1`` = 无选中（**合法状态**）。"""
        return self._selected_index

    def selectedItem(self) -> Optional[SelectorBarItem]:  # noqa: N802
        return self.itemAt(self._selected_index)

    def setSelectedIndex(self, index: int) -> None:  # noqa: N802
        """设选中项。**静默忽略**非法 / 禁用 / 隐藏的下标（不抛、不发信号）。"""
        if index is None:
            self.clearSelection()
            return
        index = int(index)
        if index < 0:
            self.clearSelection()
            return
        if not self._selectableIndex(index):
            return
        if index == self._selected_index:
            return
        previous = self._selected_index
        self._selected_index = index
        for position, entry in enumerate(self._items):
            entry.selected = position == index
        self._ensureSelectionVisible(index)
        self._ensureLayout()
        target = self._indicatorTargetRect(index)
        source = (
            self._indicatorTargetRect(previous)
            if self._validIndex(previous)
            else QRect()
        )
        self._animateIndicator(source, target)
        self.selectedIndexChanged.emit(index)
        self.update()

    def clearSelection(self) -> None:  # noqa: N802
        if self._selected_index < 0:
            return
        previous = self._selected_index
        self._selected_index = -1
        for entry in self._items:
            entry.selected = False
        self._ensureLayout()
        self._animateIndicator(self._indicatorTargetRect(previous), QRect())
        self.selectedIndexChanged.emit(-1)
        self.update()

    def setItemSelected(self, index: int, selected: bool) -> bool:  # noqa: N802
        """单项选中开关；``selected=False`` 等价于 ``clearSelection()``。"""
        if selected:
            self.setSelectedIndex(index)
            return self._selected_index == index
        if index == self._selected_index:
            self.clearSelection()
        return True

    # -- 溢出 ---------------------------------------------------------------

    def overflowBehavior(self) -> ElaSelectorBarOverflowType:  # noqa: N802
        return self._overflow_behavior

    def setOverflowBehavior(self, behavior) -> None:  # noqa: N802
        value = ElaSelectorBarOverflowType(behavior)
        if value == self._overflow_behavior:
            return
        self._overflow_behavior = value
        self._first_visible = 0
        self._invalidateLayout()
        self.overflowBehaviorChanged.emit(value)

    def isOverflowing(self) -> bool:
        self._ensureLayout()
        return self._overflown

    def visibleItemIndexes(self) -> List[int]:  # noqa: N802
        self._ensureLayout()
        return list(self._visible)

    def hiddenItemIndexes(self) -> List[int]:  # noqa: N802
        self._ensureLayout()
        visible = set(self._visible)
        return [i for i in self._candidates() if i not in visible]

    def canScrollBack(self) -> bool:  # noqa: N802
        self._ensureLayout()
        return self._first_visible > 0

    def canScrollForward(self) -> bool:  # noqa: N802
        self._ensureLayout()
        candidates = self._candidates()
        return bool(self._visible) and candidates[-1] not in self._visible

    def scrollOverflow(self, direction: int) -> None:  # noqa: N802
        """按**一项**滚动可见窗口（一次点击一项，不跳页）。"""
        self._ensureLayout()
        candidates = self._candidates()
        if not candidates or not self._overflown:
            return
        target = self._first_visible + (1 if direction > 0 else -1)
        self._first_visible = max(0, min(len(candidates) - 1, target))
        self._layout_dirty = True
        self._ensureLayout()
        self.update()

    # -- 几何自省 -----------------------------------------------------------

    def itemGeometry(self, index: int) -> QRect:  # noqa: N802
        self._ensureLayout()
        if not self._validIndex(index):
            return QRect()
        return QRect(self._item_rects[index])

    def selectedIndicatorGeometry(self, index: int) -> QRect:  # noqa: N802
        """第 ``index`` 项上指示器**最终**该在的位置（不含动画中间态）。"""
        self._ensureLayout()
        return self._indicatorTargetRect(index)

    def indicatorGeometry(self) -> QRect:
        """指示器**当前**几何（含动画中间态）。"""
        return QRect(self._indicator_rect)

    def isIndicatorAnimating(self) -> bool:  # noqa: N802
        return self._indicator_anim.state() == QVariantAnimation.State.Running

    # -- 字体 / 尺寸 ---------------------------------------------------------

    def itemPixelSize(self) -> int:  # noqa: N802
        return self._item_font_px

    def setItemPixelSize(self, pixels: int) -> None:  # noqa: N802
        value = max(8, int(pixels))
        if value == self._item_font_px:
            return
        self._item_font_px = value
        self._invalidateLayout()
        self.update()

    def _itemFont(self) -> QFont:  # noqa: N802
        font = self.font()
        font.setPixelSize(self._item_font_px)
        return font

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(_Metrics.defaultWidth, _Metrics.rowHeight)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(_Metrics.overflowButtonWidth * 3, _Metrics.rowHeight)

    # -- 布局 ---------------------------------------------------------------

    def _validIndex(self, index) -> bool:  # noqa: N802
        return isinstance(index, int) and 0 <= index < len(self._items)

    def _selectableIndex(self, index: int) -> bool:  # noqa: N802
        return (
            self._validIndex(index)
            and self._items[index].enabled
            and self._items[index].visible
        )

    def _candidates(self) -> List[int]:
        """参与布局的下标（隐藏项不占位）。"""
        return [i for i, item in enumerate(self._items) if item.visible]

    def _nearestSelectableIndex(self, start: int) -> int:  # noqa: N802
        """从 ``start`` 螺旋找最近的可选项（同偏移量下先向前）。"""
        if not self._items:
            return -1
        if self._selectableIndex(start):
            return start
        for offset in range(1, len(self._items) + 1):
            for candidate in (start + offset, start - offset):
                if self._selectableIndex(candidate):
                    return candidate
        return -1

    def _repairSelection(self, near: int) -> None:  # noqa: N802
        """变更后修正选中：一个都不可选就保持「无选中」（-1），而不是硬选一个。"""
        if self._selected_index >= 0 and self._selectableIndex(self._selected_index):
            return
        target = self._nearestSelectableIndex(near)
        if target == self._selected_index:
            return
        self._selected_index = target
        for position, item in enumerate(self._items):
            item.selected = position == target

    def _itemNaturalWidth(self, item: SelectorBarItem) -> float:  # noqa: N802
        width = float(_Metrics.horizontalPadding * 2)
        # 用**条目字体**量：绘制是 _itemFont()（setItemPixelSize 可改），
        # 用 self.fontMetrics() 会在改字号后算窄、文字被裁
        width += QFontMetrics(self._itemFont()).horizontalAdvance(item.text or "")
        if item.icon is not None:
            width += _Metrics.iconSize + _Metrics.iconGap
        return max(
            float(_Metrics.minItemWidth), min(float(_Metrics.maxItemWidth), width)
        )

    def _invalidateLayout(self) -> None:  # noqa: N802
        self._layout_dirty = True
        self._ensureLayout()
        self.updateGeometry()

    def _ensureLayout(self) -> None:
        if not self._layout_dirty:
            return
        self._layout_dirty = False
        self._recomputeLayout()

    def _recomputeLayout(self) -> None:  # noqa: N802
        candidates = self._candidates()
        self._item_rects = [QRect() for _ in self._items]
        self._visible = []
        self._overflow_back_rect = QRect()
        self._overflow_forward_rect = QRect()
        self._overflow_more_rect = QRect()

        if not candidates:
            self._overflown = False
            self._first_visible = 0
            return

        natural = {i: self._itemNaturalWidth(self._items[i]) for i in candidates}
        rowWidth = float(self.width())
        reserve = self._overflowReserve()
        available = max(1.0, rowWidth - reserve)
        self._overflown = sum(natural.values()) > available + 0.5

        if not self._overflown:
            self._first_visible = 0
            visible = list(candidates)
        else:
            self._first_visible = max(0, min(len(candidates) - 1, self._first_visible))
            visible = []
            x = 0.0
            for position in range(self._first_visible, len(candidates)):
                index = candidates[position]
                width = natural[index]
                # 窗口的第一项**即使超宽也照画**（截断），不能什么都不显示。
                if visible and x + width > available + 0.5:
                    break
                visible.append(index)
                x += width

        top = int((_Metrics.rowHeight - _Metrics.itemVisualHeight) / 2)
        x = 0.0
        for index in visible:
            width = int(natural[index])
            self._item_rects[index] = QRect(
                int(x), top, width, _Metrics.itemVisualHeight
            )
            x += width
        self._visible = visible

        button = _Metrics.overflowButtonWidth
        if self._overflown:
            if self._overflow_behavior == ElaSelectorBarOverflowType.ScrollButtons:
                self._overflow_back_rect = QRect(
                    0, top, button, _Metrics.itemVisualHeight
                )
                self._overflow_forward_rect = QRect(
                    int(rowWidth) - button, top, button, _Metrics.itemVisualHeight
                )
            else:
                self._overflow_more_rect = QRect(
                    int(rowWidth) - button, top, button, _Metrics.itemVisualHeight
                )

        if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
            self._mirrorLayout()

    def _mirrorLayout(self) -> None:  # noqa: N802
        """RTL：把全部矩形水平镜像。

        布局**一律按 LTR 算**再镜像（而不是在算的时候到处判方向）—— 只有一处要改，
        且加了 RTL 支持后忘了改某处矩形的后果是「某一处没镜像」而不是「整体算错」。
        文字对齐不在镜像范围内（``drawText`` 按逻辑方向渲染，不用管）。
        """
        width = self.width()

        def mirror(rect: QRect) -> QRect:
            if rect.isEmpty():
                return rect
            return QRect(
                width - rect.right() - 1, rect.top(), rect.width(), rect.height()
            )

        self._item_rects = [mirror(rect) for rect in self._item_rects]
        self._overflow_back_rect = mirror(self._overflow_back_rect)
        self._overflow_forward_rect = mirror(self._overflow_forward_rect)
        self._overflow_more_rect = mirror(self._overflow_more_rect)
        if not self._indicator_rect.isEmpty():
            self._indicator_rect = mirror(self._indicator_rect)

    def _overflowReserve(self) -> float:  # noqa: N802
        if self._overflow_behavior == ElaSelectorBarOverflowType.ScrollButtons:
            return float(_Metrics.overflowButtonWidth * 2)
        return float(_Metrics.overflowButtonWidth)

    def _ensureSelectionVisible(self, index: int) -> None:  # noqa: N802
        """选中项必须滚进可见窗口 —— 不然指示器会指向一个看不见的项。

        **做法是「目标不可见就把窗口起点挪到它」**，而不是「按当前窗口大小倒推起点」。
        倒推看着更精细，实测会错：窗口大小依赖**重排后**的宽度，而此刻手里只有重排
        **前**的陈旧值 —— 先在宽 520 下算出「起点 = 目标 - 窗口容量 + 1」，再到窄 300
        下重排，容量变小、目标被挤出窗口，指示器就指着看不见的项（实测：选中第 24 项
        却只显示 ``[20,21,22]``）。
        """
        candidates = self._candidates()
        if index not in candidates:
            return
        if index in self._visible:
            return
        self._first_visible = max(0, min(len(candidates) - 1, candidates.index(index)))
        self._layout_dirty = True
        self._ensureLayout()

    # -- 指示器 -------------------------------------------------------------

    def _indicatorTargetRect(self, index: int) -> QRect:  # noqa: N802
        """第 ``index`` 项上指示器的最终位置（底部居中、20px 宽的胶囊）。"""
        if not self._validIndex(index):
            return QRect()
        rect = self._item_rects[index]
        if rect.isEmpty():
            return QRect()
        width = max(
            0,
            min(_Metrics.indicatorWidth, rect.width() - _Metrics.horizontalPadding * 2),
        )
        if width <= 0:
            return QRect()
        return QRect(
            rect.center().x() - width // 2,
            rect.bottom() - _Metrics.indicatorHeight + 1,
            width,
            _Metrics.indicatorHeight,
        )

    def _collapsedRect(self, rect: QRect) -> QRect:  # noqa: N802
        """压扁态：位置不变、宽度收到 16px（**y 与高度保持不变**，否则会「跳一下」）。"""
        if rect.isEmpty():
            return QRect()
        width = min(_Metrics.collapsedIndicatorWidth, rect.width())
        return QRect(rect.center().x() - width // 2, rect.top(), width, rect.height())

    def _setIndicatorRect(self, rect: QRect) -> None:  # noqa: N802
        if rect == self._indicator_rect:
            return
        self._indicator_rect = QRect(rect)
        self.update()

    def _animateIndicator(self, fromRect: QRect, toRect: QRect) -> None:  # noqa: N802
        self._indicator_anim.stop()
        if not self.isVisible() or toRect.isEmpty():
            # 不可见 / 无目标：直接落终值，不播「从 0 宽长出来」的入场。
            self._setIndicatorRect(toRect)
            return
        collapsedFrom = self._collapsedRect(
            fromRect if not fromRect.isEmpty() else toRect
        )
        collapsedTo = self._collapsedRect(toRect)
        # 先把起点摆到位 —— 切到一项还没选中过时不要播「从零长出来」。
        self._setIndicatorRect(collapsedFrom)
        self._indicator_anim.setStartValue(collapsedFrom)
        self._indicator_anim.setKeyValueAt(_Metrics.travelRatio, collapsedTo)
        self._indicator_anim.setEndValue(toRect)
        # ``valueChanged`` 在 ``__init__`` 里连一次即可 —— 这里每切一次就叠一个
        # 接收者（实测切 4 次变4 个），槽虽然幂等但每帧调用次数线性增长。
        # 收尾只通过 on_complete 注册，不要再自己连 ``finished``（叠连接 = 跑两遍）。
        start_transition(
            self._indicator_anim, Duration.Fast, on_complete=self._onIndicatorSettled
        )

    def _onIndicatorValue(self, value) -> None:  # noqa: N802
        """``QVariantAnimation`` 把 ``QRect`` 拆成 ``(x, y, w, h)`` 四元组发过来。"""
        if isinstance(value, QRect):
            self._setIndicatorRect(value)
            return
        try:
            x, y, w, h = value
        except (TypeError, ValueError):
            return
        self._setIndicatorRect(QRect(int(x), int(y), int(w), int(h)))

    def _onIndicatorSettled(self) -> None:  # noqa: N802
        self.update()

    def snapIndicator(self) -> None:
        """立刻把指示器落到选中项（跳帧到终态，用于测试与「不想等动画」的场景）。"""
        self._indicator_anim.stop()
        self._ensureLayout()
        self._setIndicatorRect(
            self._indicatorTargetRect(self._selected_index)
            if self._validIndex(self._selected_index)
            else QRect()
        )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_dirty = True
        self._ensureLayout()
        # 动画不在跑时才对齐新几何；**在跑时绝不能打断** —— 否则用户 resize 会把
        # 指示器「拽回去」再重播一遍，观感是抽搐。
        if not self.isIndicatorAnimating():
            self._indicator_anim.stop()
            self._setIndicatorRect(
                self._indicatorTargetRect(self._selected_index)
                if self._validIndex(self._selected_index)
                else QRect()
            )
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._layout_dirty = True

    def changeEvent(self, event) -> None:  # noqa: N802
        """布局方向变了必须重排 —— 否则 RTL 下第 0 项还在左边（镜像没跑）。"""
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.LayoutDirectionChange,
            QEvent.Type.FontChange,
            QEvent.Type.EnabledChange,
        ):
            self._layout_dirty = True
            self._ensureLayout()

    # -- 命中测试 -----------------------------------------------------------
    def _hitTest(self, pos) -> tuple:
        """返回 ``(ElaHitType, index)``。不可交互的命中一律归一化成 ``(ElaHitType.None_, -1)``。"""
        self._ensureLayout()
        point = QRectF(pos.x(), pos.y(), 1, 1)
        if self._overflown:
            if self._overflow_behavior == ElaSelectorBarOverflowType.ScrollButtons:
                if self._overflow_back_rect.contains(point.toRect()):
                    return ElaHitType.OverflowBack, -1
                if self._overflow_forward_rect.contains(point.toRect()):
                    return ElaHitType.OverflowForward, -1
            elif self._overflow_more_rect.contains(point.toRect()):
                return ElaHitType.OverflowMore, -1
        for index in self._visible:
            if self._item_rects[index].contains(point.toRect()):
                if self._selectableIndex(index):
                    return ElaHitType.Item, index
                return ElaHitType.None_, -1
        return ElaHitType.None_, -1

    # -- 事件 ---------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._pressed, self._pressed_index = self._hitTest(event.position().toPoint())
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        hit, index = self._hitTest(event.position().toPoint())
        if hit != self._hovered or index != self._hovered_index:
            self._hovered, self._hovered_index = hit, index
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        hit, index = self._hitTest(event.position().toPoint())
        pressed, pressed_index = self._pressed, self._pressed_index
        self._pressed, self._pressed_index = ElaHitType.None_, -1
        self.update()
        # 按下与抬起必须是**同一个目标**才激活 —— 按下后拖走 = 取消。
        if hit is not pressed or (hit is ElaHitType.Item and index != pressed_index):
            return
        if hit is ElaHitType.OverflowBack:
            self.scrollOverflow(-1)
        elif hit is ElaHitType.OverflowForward:
            self.scrollOverflow(1)
        elif hit is ElaHitType.OverflowMore:
            hidden = self.hiddenItemIndexes()
            if hidden:
                self.overflowActivated.emit(list(hidden))
        elif hit is ElaHitType.Item:
            self._activateIndex(index)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered, self._hovered_index = ElaHitType.None_, -1
        self._pressed, self._pressed_index = ElaHitType.None_, -1
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        selectable = [i for i in self._candidates() if self._selectableIndex(i)]
        if not selectable:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            current = (
                self._selected_index
                if self._selected_index in selectable
                else selectable[0]
            )
            self._activateIndex(current)
            event.accept()
            return
        current = (
            self._selected_index
            if self._selected_index in selectable
            else selectable[0]
        )
        position = selectable.index(current)
        # RTL 下布局已镜像（第 0 项在**右**边），所以「按左」是往后一项。
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        horizontal = -1 if rtl else 1
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            target = selectable[max(0, position - horizontal)]
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            target = selectable[min(len(selectable) - 1, position + horizontal)]
        elif key == Qt.Key.Key_Home:
            target = selectable[0]
        elif key == Qt.Key.Key_End:
            target = selectable[-1]
        else:
            super().keyPressEvent(event)
            return
        if target != self._selected_index:
            self.setSelectedIndex(target)
        event.accept()

    def focusInEvent(self, event) -> None:  # noqa: N802
        """拿到焦点时把选中补到一个可选项上。

        **必须走 ``setSelectedIndex``**：原先直接写 ``_selected_index``，
        于是三处状态互相矛盾 —— ``selectedIndex()`` 报了新下标、
        ``items()`` 的 ``selected`` 镜像全False、指示器几何是空的，而且
        **不发 ``selectedIndexChanged``**，宿主完全不知道选中变了。
        """
        super().focusInEvent(event)
        if not self._selectableIndex(self._selected_index):
            for index in self._candidates():
                if self._selectableIndex(index):
                    self.setSelectedIndex(index)
                    break
        self.update()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.update()

    def _activateIndex(self, index: int) -> None:  # noqa: N802
        if not self._selectableIndex(index):
            return
        # **先发 itemActivated 再提交选中** —— 宿主在槽里销毁控件也不会崩。
        # 发的是**副本**：信号参数也是出口，宿主不该有机会改内部状态（与 items() 同理）。
        self.itemActivated.emit(index, self.itemAt(index))
        self.setSelectedIndex(index)

    # -- 绘制 ---------------------------------------------------------------

    def _itemTextColor(self, index: int) -> QColor:  # noqa: N802
        if not self.isEnabled() or not self._selectableIndex(index):
            return textDisabled(currentMode())
        # 选中 / 悬浮 / 按下**三者同色** —— 只有 3px 指示器区分选中，没有独立选中色。
        if index == self._selected_index:
            return text(currentMode())
        return textMuted(currentMode())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        self._ensureLayout()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mode = currentMode()
        painter.fillRect(self.rect(), surfaceRaised(mode))
        for index in self._visible:
            self._paintItem(painter, index, mode)
        if self._overflown:
            self._paintOverflow(painter, mode)
        self._paintIndicator(painter, mode)

    def _paintItem(self, painter: QPainter, index: int, mode) -> None:  # noqa: N802
        item = self._items[index]
        rect = self._item_rects[index]
        if rect.isEmpty():
            return
        if self._hovered is ElaHitType.Item and self._hovered_index == index:
            # 悬浮底用一层极淡的强调色（8%），不用 QSS。
            painter.fillRect(rect, blend(surfaceRaised(mode), accent(mode), 0.08))

        color = self._itemTextColor(index)
        contentX = rect.left() + _Metrics.horizontalPadding
        if item.icon is not None:
            iconRect = QRect(
                contentX,
                rect.top() + (_Metrics.itemVisualHeight - _Metrics.iconSize) // 2,
                _Metrics.iconSize,
                _Metrics.iconSize,
            )
            ratio = painter.device().devicePixelRatioF() if painter.device() else 1.0
            drawElaIcon(painter, iconRect, item.icon, color, ratio=ratio)
            contentX = iconRect.right() + 1 + _Metrics.iconGap

        painter.setFont(self._itemFont())
        metrics = painter.fontMetrics()
        textRect = QRect(
            contentX,
            rect.top() + (rect.height() - metrics.height()) // 2,
            max(0, rect.right() - _Metrics.horizontalPadding - contentX + 1),
            metrics.height(),
        )
        painter.setPen(QPen(color))
        painter.drawText(
            textRect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            item.text or "",
        )

    def _paintOverflow(self, painter: QPainter, mode) -> None:  # noqa: N802
        painter.setFont(self._itemFont())
        metrics = painter.fontMetrics()
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        if self._overflow_behavior == ElaSelectorBarOverflowType.ScrollButtons:
            # 到头了**置灰而不是隐藏** —— 按钮位置恒定，控件宽度不随状态跳动。
            self._paintChevron(
                painter, self._overflow_back_rect, not self.canScrollBack(), rtl
            )
            self._paintChevron(
                painter,
                self._overflow_forward_rect,
                not self.canScrollForward(),
                not rtl,
            )
            return
        rect = self._overflow_more_rect
        if rect.isEmpty():
            return
        disabled = not self.hiddenItemIndexes()
        color = textDisabled(mode) if disabled else textMuted(mode)
        box = QRect(
            rect.left(),
            rect.top() + (rect.height() - metrics.height()) // 2,
            rect.width(),
            metrics.height(),
        )
        painter.setPen(QPen(color))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, "...")

    def _paintChevron(
        self, painter: QPainter, rect: QRect, disabled: bool, leftward: bool
    ) -> None:  # noqa: N802
        if rect.isEmpty():
            return
        color = textDisabled(currentMode()) if disabled else textMuted(currentMode())
        icon = (
            ElaIconType.IconName.AngleLeft
            if leftward
            else ElaIconType.IconName.AngleRight
        )
        drawElaIcon(
            painter,
            rect,
            icon,
            color,
            ratio=painter.device().devicePixelRatioF()
            if painter.device() is not None
            else 1.0,
        )

    def _paintIndicator(self, painter: QPainter, mode) -> None:  # noqa: N802
        rect = self._indicator_rect
        if rect.isEmpty():
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent(mode))
        # 全圆角胶囊（3px 高 → 1.5px 圆角）。画成「细条 + 小圆角」看着像一道划痕。
        painter.drawRoundedRect(QRectF(rect), rect.height() / 2.0, rect.height() / 2.0)

    def _onThemeChanged(self, mode) -> None:  # noqa: N802 (基类钩子)
        super()._onThemeChanged(mode)
        self.update()
