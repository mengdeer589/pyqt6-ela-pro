"""
窗口淡入淡出动画模块。

两种用法：模块级函数 ``fade_in()`` / ``fade_out()``，或继承 ``ElaAnimatedMixin``
获得同名实例方法。

时长取 :mod:`pyqt6_ela_pro._motion` 的 ``Duration`` 令牌，实际播放受全局动效策略
约束：``Reduced`` 下过渡压到 ≤50ms、``Disabled`` 下同步落终值，收尾回调照常触发。
``shake_window`` 是纯装饰（不产生状态变化），在 ``Reduced`` / ``Disabled`` 下整体不播。
"""

from __future__ import annotations

import weakref
from typing import Callable, Optional

from PyQt6.QtCore import QPropertyAnimation, QPoint
from PyQt6.QtWidgets import QWidget
from ._internal import is_deleted

from ._internal import safe_call
from ._motion import Duration, ElaMotionKindType, start_transition


_animation_registry: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def fade_in(widget: QWidget, duration: int = Duration.Normal) -> None:
    """让窗口淡入（opacity: 0 → 1）。

    如果窗口尚未显示，会先设置 opacity=0，再 show，再启动动画。动画进行中再次调用会
    忽略新请求。

    :param widget: 目标窗口控件
    :param duration: ``Full`` 模式下的动画时长（毫秒），默认 ``Duration.Normal``
    """
    if not widget.isVisible():
        widget.setWindowOpacity(0)
        widget.show()

    if widget in _animation_registry:
        existing = _animation_registry[widget]
        if existing and existing.state() == QPropertyAnimation.State.Running:
            return

    animation = QPropertyAnimation(widget, b"windowOpacity")
    animation.setStartValue(0)
    animation.setEndValue(1)

    def _cleanup():
        if widget in _animation_registry and _animation_registry[widget] is animation:
            del _animation_registry[widget]

    # 故意**不**连 widget.destroyed：destroyed 在 C++ 析构之后才发出，此时对已失效
    # 的包装器取哈希会触发 0xC0000005（实测全量测试 6/6 必崩）；且 lambda 捕获 widget
    # 会形成引用环让包装器永不回收。条目清理由 WeakKeyDictionary 负责。
    # （tooltips._auto_remove 在 destroyed 里做同类哈希却实测 5 场景安全 ——
    # 两处时机/路径不同，结论并存；改任一处前先跑各自回归。）
    _animation_registry[widget] = animation
    start_transition(animation, duration, on_complete=_cleanup)


def fade_out(
    widget: QWidget,
    duration: int = Duration.Normal,
    on_finished: Optional[Callable[[], None]] = None,
) -> None:
    """让窗口淡出（opacity: 1 → 0）。

    仅将透明度渐变到 0，不会自动关闭窗口。动画结束后调用 ``on_finished`` 回调。
    动画进行中再次调用会忽略新请求。

    ``Disabled`` 模式下动画同步落终值，``on_finished`` 在 :func:`start_transition`
    内部当场触发（不排队事件循环），所以「淡出后关窗」在三种模式下都成立。

    :param widget: 目标窗口控件
    :param duration: ``Full`` 模式下的动画时长（毫秒），默认 ``Duration.Normal``
    """
    if widget in _animation_registry:
        existing = _animation_registry[widget]
        if existing and existing.state() == QPropertyAnimation.State.Running:
            return

    animation = QPropertyAnimation(widget, b"windowOpacity")
    animation.setStartValue(1)
    animation.setEndValue(0)

    def _on_finished():
        if widget in _animation_registry and _animation_registry[widget] is animation:
            del _animation_registry[widget]
        if on_finished is not None:
            safe_call(on_finished)

    # 同 fade_in：不连 destroyed（理由同上）
    _animation_registry[widget] = animation
    start_transition(animation, duration, on_complete=_on_finished)


def shake_window(
    widget: QWidget,
    duration: int = Duration.Fast,
    loop_count: int = 2,
    on_finished: Optional[Callable[[], None]] = None,
) -> None:
    """让窗口抖动（左右 + 上下晃回原位），动画进行中再次调用会被忽略。

    抖动**不产生任何状态变化**（终点即起点），属纯装饰动效，按
    ``ElaMotionKindType.Continuous`` 送策略 —— ``Reduced`` / ``Disabled`` 下整体不播
    （压成 50ms 的抖动只会像渲染故障，不会像反馈）。``duration`` 是 ``Full``
    模式下的总时长。
    """
    if hasattr(widget, "_shake_animation"):
        existing = widget._shake_animation
        # 上一次抖动的动画带 DeleteWhenStopped，C++ 可能已被删除，对已删对象取
        # state() 会抛 RuntimeError（进而 0xC0000409）。
        try:
            if existing is not None and not is_deleted(existing):
                if existing.state() == QPropertyAnimation.State.Running:
                    return
        except RuntimeError:
            pass

    # **不要把动画挂到它自己动的那个控件上**（第三参别传 widget）。
    # 目标控件被销毁时 Qt 会连带删掉这个仍在 Running 的子动画，而此时针对它的
    # ``finished`` 发射还可能挂在队列里 —— 槽随后就跑在一半销毁的对象图上，
    # 实测 0xC0000005（无 traceback）。改成 ``KeepWhenStopped`` 或给收尾加
    # ``is_deleted`` 守卫都**挡不住**：销毁是由 parent-child 关系驱动的，
    # 与删除策略无关。不挂 parent 后动画的生命周期只由 Python 引用决定。
    animation = QPropertyAnimation(widget, b"pos")
    widget._shake_animation = animation

    pos = widget.pos()
    x, y = pos.x(), pos.y()

    animation.setLoopCount(loop_count)
    animation.setKeyValueAt(0, QPoint(x, y))
    animation.setKeyValueAt(0.09, QPoint(x + 2, y - 2))
    animation.setKeyValueAt(0.18, QPoint(x + 4, y - 4))
    animation.setKeyValueAt(0.27, QPoint(x + 2, y - 6))
    animation.setKeyValueAt(0.36, QPoint(x, y - 8))
    animation.setKeyValueAt(0.45, QPoint(x - 2, y - 10))
    animation.setKeyValueAt(0.54, QPoint(x - 4, y - 8))
    animation.setKeyValueAt(0.63, QPoint(x - 6, y - 6))
    animation.setKeyValueAt(0.72, QPoint(x - 8, y - 4))
    animation.setKeyValueAt(0.81, QPoint(x - 6, y - 2))
    animation.setKeyValueAt(0.90, QPoint(x - 4, y))
    animation.setKeyValueAt(0.99, QPoint(x - 2, y + 2))
    animation.setEndValue(QPoint(x, y))

    def _cleanup():
        # ``widget`` 可能已被销毁（``shake_window`` 的目标常常是无父顶层窗，
        # ``deleteLater()`` 对它不生效，之后靠 GC 落地）。此时任何属性访问都不得
        # 硬碰那个已失效的包装器。
        try:
            alive = not is_deleted(widget)
        except (RuntimeError, TypeError):
            alive = False
        if alive and hasattr(widget, "_shake_animation"):
            try:
                delattr(widget, "_shake_animation")
            except AttributeError:
                pass
        if on_finished is not None:
            safe_call(on_finished)

    # DeleteWhenStopped：播完（含 snap 路径）C++ 对象当场销毁，所以上面的
    # ``is_deleted`` 守卫是必需的，不能简化成 anim.state()。
    start_transition(
        animation,
        duration,
        kind=ElaMotionKindType.Continuous,
        on_complete=_cleanup,
        deletion_policy=QPropertyAnimation.DeletionPolicy.DeleteWhenStopped,
    )


class ElaAnimatedMixin:
    """给窗口/对话框添加淡入淡出动画能力的混入类。

    动画实例被自身持有并复用（先 stop 旧的再启动新的），所以 ``fade_in`` →
    ``fade_out`` 连调不会攒下一串待销毁的 ``QPropertyAnimation``。

    Example::

        class MyDialog(ElaAnimatedMixin, QDialog):
            def show_with_animation(self):
                self.fade_in()

            def close_with_animation(self):
                self.fade_out(on_finished=self.close)
    """

    _fade_animation: Optional[QPropertyAnimation] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fade_animation = None

    def _fade_anim(self) -> QPropertyAnimation:
        if self._fade_animation is None:
            self._fade_animation = QPropertyAnimation(self, b"windowOpacity")  # type: ignore[arg-type]
        return self._fade_animation

    def fade_in(self, duration: int = Duration.Normal) -> None:
        """让窗口淡入（opacity: 0 → 1）。

        如果窗口尚未显示，会先设置 opacity=0，再 show，再启动动画。动画进行中再次调用会
        忽略新请求。

        :param duration: ``Full`` 模式下的动画时长（毫秒），默认 ``Duration.Normal``
        """
        if not self.isVisible():  # type: ignore[attr-defined]
            self.setWindowOpacity(0)  # type: ignore[attr-defined]
            self.show()  # type: ignore[attr-defined]

        if (
            self._fade_animation
            and self._fade_animation.state() == QPropertyAnimation.State.Running
        ):
            return

        animation = self._fade_anim()
        animation.stop()
        animation.setStartValue(0)
        animation.setEndValue(1)
        start_transition(animation, duration)

    def fade_out(
        self,
        duration: int = Duration.Normal,
        on_finished: Optional[Callable[[], None]] = None,
    ) -> None:
        """让窗口淡出（opacity: 1 → 0）。

        仅将透明度渐变到 0，不会自动关闭窗口。动画结束后调用 ``on_finished`` 回调。
        动画进行中再次调用会忽略新请求。

        :param duration: ``Full`` 模式下的动画时长（毫秒），默认 ``Duration.Normal``
        :param on_finished: 动画完成后的回调函数
        """
        if (
            self._fade_animation
            and self._fade_animation.state() == QPropertyAnimation.State.Running
        ):
            return

        animation = self._fade_anim()
        animation.stop()
        animation.setStartValue(1)
        animation.setEndValue(0)

        def _on_finished():
            if on_finished is not None:
                safe_call(on_finished)

        start_transition(animation, duration, on_complete=_on_finished)
