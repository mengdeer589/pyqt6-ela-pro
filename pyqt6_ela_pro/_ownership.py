"""内容控件所有权协议（Borrowed / Reparented / Owned）。

容器释放 ``setXxxWidget`` 传入的控件时按策略处理；细节见 ``docs/core.md``。"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

from ._internal import is_deleted
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget


class ElaWidgetOwnershipType(IntEnum):
    """容器释放内容控件时的策略。"""

    Borrowed = 0
    """默认。容器持强引用，释放时 ``setParent(None)`` 交还调用方。"""

    Reparented = 1
    """释放时把内容放回挂载前的 parent。"""

    Owned = 2
    """释放时由容器 ``deleteLater()``。"""


def releaseWidget(  # noqa: N802 (与 Qt 命名一致)
    widget: Optional[QWidget],
    ownership: ElaWidgetOwnershipType,
    originalParent: Optional[QWidget] = None,  # noqa: N803
    *,
    deleteOwned: bool = True,
    restoreParent: bool = True,
) -> None:
    """按策略处置一个内容控件（无状态版，:class:`ContentSlot` 内部也用它）。

    :param deleteOwned: ``False`` 时即使是 ``Owned`` 也不删 —— 析构路径要这个，
        因为 Qt 的 parent-child 删除会在 ``~Expander`` 之后再处理。
    :param restoreParent: ``False`` 时即使是 ``Reparented`` 也不还原 ——
        ``take`` 语义要这个（交还时必须是**无父**的）。
    """
    if widget is None or not isinstance(widget, QWidget):
        # 非控件对象：``is_deleted`` 把非 sip 包装对象按「存活」处理（TypeError 兜底），
        # 这里仍然显式挡 —— 调用方传进来的可能是任意 Python 对象。
        return
    try:
        if is_deleted(widget):
            return
    except (RuntimeError, TypeError):
        return

    if ownership == ElaWidgetOwnershipType.Owned and deleteOwned:
        widget.deleteLater()
        return
    if (
        ownership == ElaWidgetOwnershipType.Reparented
        and restoreParent
        and originalParent is not None
        and not is_deleted(originalParent)
    ):
        try:
            widget.setParent(originalParent)
        except RuntimeError:
            widget.setParent(None)
        return
    widget.setParent(None)


class ContentSlot(QObject):
    """「一个宿主控件持有一个外来内容控件」的全部记账（组合对象，非基类）。

    **刻意不做 host 的 QObject 子对象**：宿主析构会连带析构本槽，而 Python 包装器
    还活着，GC 时 PyQt 去 delete 已释放的 C++ 对象 = 0xC0000005。故生命周期只跟
    包装器走，每个碰 ``_host`` 的方法都判 ``is_deleted``。

    :param host: 容器控件（内容会被 reparent 到它下面）。
    :param name: 诊断用的槽位名，进拒绝/异常信息。
    """

    widgetChanged = pyqtSignal(object)
    ownershipChanged = pyqtSignal(object)

    def __init__(self, host: QWidget, name: str = "content") -> None:
        super().__init__()  # 刻意无 parent，见上面的 warning
        self._host = host
        self._name = name
        self._widget: Optional[QWidget] = None
        self._ownership = ElaWidgetOwnershipType.Borrowed
        self._originalParent: Optional[QWidget] = None

    def _aliveHost(self) -> Optional[QWidget]:  # noqa: N802
        """宿主还活着就返回它，否则 ``None``（宿主析构后槽仍可能被调用）。"""
        try:
            if self._host is None or is_deleted(self._host):
                return None
        except (RuntimeError, TypeError):
            return None
        return self._host

    def widget(self) -> Optional[QWidget]:
        """当前内容控件；已被外部销毁时返回 ``None``。"""
        return self._widget

    def ownership(self) -> ElaWidgetOwnershipType:
        return self._ownership

    def hasWidget(self) -> bool:  # noqa: N802
        return self._widget is not None

    def setWidget(  # noqa: N802
        self, widget: Optional[QWidget], ownership=ElaWidgetOwnershipType.Borrowed
    ) -> bool:
        """挂载内容。返回是否成功（自挂 / 挂祖先会被拒）。
        重复挂载同一个控件只更新所有权策略，不重复 reparent；**换成另一个控件时，
        上一个按它自己的策略被处置**（``Owned`` 删、``Borrowed``/``Reparented``
        """
        # 类型检查必须在任何 widget 方法调用前：非 QWidget 传进来时，
        # isAncestorOf 等会直接抛 AttributeError。
        if widget is not None and not isinstance(widget, QWidget):
            return False
        if widget is not None and is_deleted(widget):
            return False
        host = self._aliveHost()
        if host is None:
            return False
        if widget is host:
            return False
        if widget is not None:
            try:
                if widget.isAncestorOf(host):
                    return False
            except RuntimeError:
                return False
        try:
            ownership = ElaWidgetOwnershipType(ownership)
        except ValueError:
            return False

        if widget is self._widget:
            # 同一控件：只换策略
            if self._ownership != ownership:
                self._ownership = ownership
                self.ownershipChanged.emit(ownership)
            return True

        # 换内容时按**旧策略**处置上一个控件。漏掉这一步的后果是：``Owned`` 的
        # 永远不会 deleteLater（泄漏），``Borrowed`` 的变成无主孤儿（还挂在宿主布局里
        # 却不再被跟踪），而调用方也拿不回句柄去自己处置。
        previous = self._widget
        previousOwnership = self._ownership
        previousParent = self._originalParent
        if previous is not None:
            self._disconnectDestroyed()
            self._widget = None
            self._originalParent = None
            self._ownership = ElaWidgetOwnershipType.Borrowed
            releaseWidget(previous, previousOwnership, previousParent)

        self._disconnectDestroyed()
        self._widget = widget
        self._ownership = (
            ownership if widget is not None else ElaWidgetOwnershipType.Borrowed
        )
        # 先记原 parent 再 reparent，否则还原不回去。
        self._originalParent = widget.parentWidget() if widget is not None else None

        if widget is not None:
            if widget.isWindow():
                # 顶层控件不能当 child，会被 WM 当成独立窗口弹出（无父的
                # PermissionCard 建出来就是桌面上飘的小窗）
                widget.setWindowFlags(widget.windowFlags() | Qt.WindowType.Widget)
            widget.setParent(host)
            widget.show()
            self._destroyedSlot = (
                self._onWidgetDestroyed
            )  # 断连要同一对象（lambda / partial 必须存引用）
            widget.destroyed.connect(self._destroyedSlot)

        self.widgetChanged.emit(widget)
        if widget is not None:
            self.ownershipChanged.emit(self._ownership)
        return True

    def takeWidget(self) -> Optional[QWidget]:  # noqa: N802
        """交还内容控件：断连、置空、**无父**返回，**从不删除**。"""
        widget = self._widget
        self._disconnectDestroyed()
        self._widget = None
        original = self._originalParent
        self._originalParent = None
        self._ownership = ElaWidgetOwnershipType.Borrowed
        if widget is not None:
            widget.hide()
            releaseWidget(
                widget,
                ElaWidgetOwnershipType.Owned,  # 走不到 Owned 分支：take 永不删除
                original,
                deleteOwned=False,
                restoreParent=False,
            )
        self.widgetChanged.emit(None)
        return widget

    def releaseWidget(  # noqa: N802
        self, *, deleteOwned: bool = True, restoreParent: bool = True
    ) -> None:
        """按当前策略处置内容（= ``take`` + ``release``）。"""
        widget = self._widget
        if widget is None:
            return
        self._disconnectDestroyed()
        self._widget = None
        original = self._originalParent
        self._originalParent = None
        ownership = self._ownership
        self._ownership = ElaWidgetOwnershipType.Borrowed
        releaseWidget(
            widget,
            ownership,
            original,
            deleteOwned=deleteOwned,
            restoreParent=restoreParent,
        )
        self.widgetChanged.emit(None)

    def _disconnectDestroyed(self) -> None:
        widget = self._widget
        if widget is None:
            return
        try:
            if not is_deleted(widget):
                widget.destroyed.disconnect(self._destroyedSlot)
        except (TypeError, RuntimeError):
            pass

    def _onWidgetDestroyed(self, _obj=None) -> None:
        """内容被**外部**销毁时的自愈：清引用并发信号。
        这里只碰自己的字段，绝不碰那个已经失效的包装器（``destroyed`` 在 C++
        析构之后才发出，碰了就是 0xC0000005）。
        """
        self._widget = None
        self._originalParent = None
        self._ownership = ElaWidgetOwnershipType.Borrowed
        self.widgetChanged.emit(None)

    def __repr__(self) -> str:  # pragma: no cover - 诊断用
        return (
            f"<ContentSlot {self._name} widget={self._widget!r} "
            f"ownership={self._ownership.name}>"
        )
