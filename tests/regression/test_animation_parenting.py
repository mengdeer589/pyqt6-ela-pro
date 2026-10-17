"""动画不得被挂到「它自己动的那个对象」上。

``QAbstractAnimation`` 家族的第三个构造参数是 parent。写成
``QPropertyAnimation(target, b"prop", target)`` 就让**动画成为自己目标的子对象** ——
目标被销毁时 Qt 会连带删掉这个**仍在 Running** 的子动画，而针对它的 ``finished``
发射可能还挂在事件队列里；槽随后跑在一半销毁的对象图上，实测
``0xC0000005``（access violation，无 traceback，崩在 fixture teardown 里）。

这条守卫钉住那个形状。已确认的受害者：``animation.shake_window``（动画 ``pos``，
目标是无父顶层窗）。``ela_ghost_box`` 曾命中同一形状，一并改掉了 —— 与其开白名单，
不如把整类隐患消掉。
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from PyQt6.QtCore import QPropertyAnimation
from PyQt6.QtWidgets import QWidget
from PyQt6 import sip

_PKG = pathlib.Path(__file__).resolve().parents[2] / "pyqt6_ela_pro"

_ANIMATION_NAMES = {
    "QPropertyAnimation",
    "QVariantAnimation",
    "QBasicAnimation",
    "QPauseAnimation",
    "QTimeLine",
}


def _self_parented_sites() -> list[tuple[str, int, str]]:
    """扫出 ``Animation(target, prop, target)`` 形态的位置。"""
    found: list[tuple[str, int, str]] = []
    for path in sorted(_PKG.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if ast.unparse(node.func) not in _ANIMATION_NAMES:
                continue
            args = [ast.unparse(a) for a in node.args]
            if len(args) >= 3 and args[0] == args[2]:
                found.append(
                    (str(path.relative_to(_PKG)), node.lineno, ast.unparse(node))
                )
    return found


class TestNoSelfParentedAnimations:
    def test_no_animation_is_parented_to_its_own_target(self):
        offenders = _self_parented_sites()
        assert not offenders, (
            "以下动画把自己动的对象同时当作 parent（目标销毁会连带销毁仍在运行的"
            "动画，槽随后跑在已释放对象上 = 0xC0000005）：\n"
            + "\n".join("  {}:{}  {}".format(*o) for o in offenders)
        )

    def test_ghost_box_expand_animation_is_not_self_parented(self, qapp, make):
        from pyqt6_ela_pro.ela_ghost_box import ElaGhostBox

        box = make(ElaGhostBox)
        assert box._expand_animation.targetObject() is box
        assert box._expand_animation.parent() is not box


class TestShakeWindowAnimationLifetime:
    """``shake_window`` 的动画不得挂在目标控件上。"""

    def test_animation_is_not_a_child_of_its_target(self, qapp, make):
        from pyqt6_ela_pro import shake_window

        widget = make(QWidget)
        widget.setFixedSize(200, 100)
        shake_window(widget, duration=120, loop_count=1)

        anim = widget._shake_animation
        assert isinstance(anim, QPropertyAnimation)
        assert anim.targetObject() is widget, "目标仍是那个控件"
        assert anim.parent() is not widget, "但**不能**同时是它的子对象"

    def test_completion_survives_a_destroyed_target(self, qapp, make):
        """回归：收尾槽曾硬碰已析构的控件包装器。"""

        from pyqt6_ela_pro import shake_window

        widget = QWidget()
        widget.setFixedSize(200, 100)
        shake_window(widget, duration=80, loop_count=1)
        sip.delete(widget)  # 目标先死

        # 让动画跑完 -> _cleanup 必须安静跳过
        from PyQt6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)
        loop.exec()

    @pytest.mark.parametrize("loop_count", [1, 2, 3])
    def test_loop_counts_still_honoured(self, qapp, make, loop_count):
        from pyqt6_ela_pro import shake_window

        widget = make(QWidget)
        widget.setFixedSize(200, 100)
        shake_window(widget, duration=120, loop_count=loop_count)
        assert widget._shake_animation.loopCount() == loop_count
