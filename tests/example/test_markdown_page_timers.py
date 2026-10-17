"""回归：``example/markdown_page.py`` 不许留「无主定时器」。

**踩过的坑**（症状：同一份脚本偶发 0xC0000409、无 traceback、崩在不同位置）：
页面里原来有「复制全文」和「导出 PDF」两个按钮，用
``QTimer.singleShot(1200, lambda: btn.setText(...))`` 把按钮文案改回去 ——
**没给 context 对象**。那个定时器不随任何控件销毁，页面销毁后它照样在
T+1200ms 触发，去摸已释放的按钮包装器 → ``RuntimeError`` 穿过 C++ 边界 →
进程静默终止。

这一页构造慢（要建好几个 markdown viewer），只有「点按钮 + 1200ms」晚于
「页面销毁」时才炸，所以很难稳定复现。两个按钮**已删除**；这里留两道守卫：

1. 静态：页面里所有 ``QTimer.singleShot`` 都必须带 context 对象；
2. 行为：把页面销毁后的事件循环跑到「旧定时器该触发」的时刻之后，进程必须还在。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

from pyqt6_ela_pro.ela_tag_multi_box import ElaTagMultiBox
from pyqt6_ela_pro.ela_tag_search_multi_box import ElaTagSearchMultiBox

_PAGE = (
    Path(__file__).resolve().parents[2]
    / "pyqt6_ela_pro"
    / "example"
    / "markdown_page.py"
)

#: 旧定时器的延迟（ms）。守卫要把事件循环跑过这个点才算数。
_OLD_TIMER_MS = 1200


def _pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    QCoreApplication.processEvents()


def _count_top_level_args(text: str) -> int:
    depth, count = 0, 1
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            count += 1
    return count


class TestNoUnparentedSingleShot:
    def test_every_single_shot_in_page_has_a_context(self):
        """页面里所有 ``QTimer.singleShot`` 都必须带 context 对象。

        无 context 的 ``singleShot`` 属于「无主定时器」：它不随任何控件销毁，
        回调里摸控件就可能在控件已释放时炸（0xC0000409 静默终止）。

        注意 PyQt5 的 ``singleShot(ms, ctx, callable)`` 重载**也不能单独当保障**
        （实测传了 context 照样崩）；这里只是要求「至少写了 context」，
        真要稳妥用「定时器作为 ctx 的子对象」或 ``sip.isdeleted()`` 自查。
        """
        src = _PAGE.read_text(encoding="utf-8")
        offenders = []
        for m in re.finditer(r"QTimer\.singleShot\((.*)\)\s*$", src, re.M):
            if _count_top_level_args(m.group(1)) < 2:
                line_no = src[: m.start()].count("\n") + 1
                offenders.append(f"markdown_page.py:{line_no}: {m.group(0)}")
        assert offenders == [], (
            "这些 singleShot 没有 context 对象，控件销毁后会打到已释放对象：\n"
            + "\n".join(offenders)
        )

    def test_removed_buttons_stay_removed(self):
        """那两个按钮不要「为了修 bug 又加回来」。

        它们唯一的作用就是演示「点一下改文案、过会儿改回来」，代价是一个
        无主定时器；要用这个效果就照注释里的写法（定时器做子对象）。
        """
        src = _PAGE.read_text(encoding="utf-8")
        for gone in ("copy_all", "export_pdf", "copy_full_text", "export_to_pdf"):
            assert gone not in src, f"{gone} 已删除，别再加回来"


class TestTeardownSurvivesOldTimerWindow:
    @pytest.mark.parametrize(
        "factory",
        [
            lambda: ElaTagMultiBox(),
            lambda: ElaTagSearchMultiBox(),
        ],
        ids=["tag_multi_box", "tag_search_multi_box"],
    )
    def test_tag_box_survives_destroy_before_deferred_init(self, qapp, factory):
        """两个 tag box 的 ``__init__`` 都靠**延迟一事件循环**做弹层预初始化。

        原先那是无主的 ``QTimer.singleShot(0, lambda: _pre_init_popup(self))``，
        而「构造后立刻销毁」是测试里极常见的时序 —— 回调去摸已释放的包装器 →
        ``RuntimeError`` 穿出 Qt 回调 → **进程 0xC0000409 零 traceback 终止**
        （实测 exit=-1073740791）。现在走 ``_internal.single_shot_on``：定时器
        是控件的子对象，控件析构时连带销毁并丢掉待触发的 timeout。
        """
        widget = factory()
        sip.delete(widget)  # 同步销毁（不走事件循环）
        assert sip.isdeleted(widget)
        _pump(_OLD_TIMER_MS + 400)  # 跑到「旧定时器该触发」之后
        QCoreApplication.processEvents()
        assert True

    def test_page_survives_teardown_past_old_timer_delay(self, qapp):
        """建页面 → 同步销毁 → 把事件循环跑过 1.2s，进程必须还在。

        ``sip.delete()`` 是**同步**销毁（不走事件循环），保证「控件已死、
        还有东西可能在后面触发」这个窗口真的出现过。不崩就是通过
        （崩了是 pytest 进程静默消失、零输出）。
        """
        from pyqt6_ela_pro.example.markdown_page import MarkdownPage

        page = MarkdownPage()
        page.show()
        _pump(120)
        sip.delete(page)
        assert sip.isdeleted(page)
        _pump(_OLD_TIMER_MS + 400)
        QCoreApplication.processEvents()
        assert True
