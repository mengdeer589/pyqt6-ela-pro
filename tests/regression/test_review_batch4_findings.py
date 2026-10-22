"""回归测试（第四批）：深度审查发现、经实测确认的 7 项。

1. ``ReasoningBlock.end()`` 收到非数值 durationMs 时抛 TypeError
   （常在信号槽里被调用 -> 0xC0000409 静默 abort）
2. ``ElaChatAttachment`` 尺寸为字符串（恢复历史场景）时 ``int()`` 抛 ValueError
3. ``ElaDrawerArea`` 不检查鼠标按键，右键/中键在头部松手也会展开收起
4. ``ElaRatingControl.setMaxRating()`` 不重新夹取，rating() > maxRating()
5. ``ElaDataTable.setTableData()`` 的 blockSignals 无 try/finally，
   一次异常永久阻塞模型（异步版已有，是遗漏）
6. blueprint ``_cached_pen()`` 返回共享实例，调用方 ``setDashOffset`` 互相污染
7. 划词助手 15ms 轮询回调无保护，宿主异常导致进程 abort
"""

from __future__ import annotations

import inspect
import warnings

import pytest
from PyQt6.QtCore import QEvent, QObject, QPoint, Qt, pyqtSignal, QPointF
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPixmap

from pyqt6_ela_pro import (
    ElaDataTable,
    ElaDrawerArea,
    ElaRatingControl,
)
from pyqt6_ela_pro import (
    ela_drawer_area as DA,
)
from pyqt6_ela_pro.blueprint import edge_widget as EW
from pyqt6_ela_pro.blueprint.edge_widget import _cached_pen
from pyqt6_ela_pro.chat.blocks import ReasoningBlock
from pyqt6_ela_pro.chat.message import ElaChatAttachment
from pyqt6_ela_pro.selection_assistant import _native as N
from pyqt6_ela_pro.selection_assistant import assistant
from pyqt6_ela_pro.selection_assistant._native import safe_connect


class _Sig(QObject):
    """带类级信号的最小 QObject（pyqtSignal 必须定义在类上才会成为绑定信号）。"""

    sig = pyqtSignal(object)


# ------------------------------------------------------------------ 1 & 2
class TestNonNumericInputs:
    @pytest.mark.parametrize(
        "bad", ["1.2s", "abc", None, object()], ids=["suffix", "text", "none", "object"]
    )
    def test_reasoning_end_tolerates_non_numeric_duration(self, qapp, bad):

        block = ReasoningBlock()
        block.resize(200, 60)
        block.show()
        qapp.processEvents()
        block.end(bad)  # 不得抛
        qapp.processEvents()
        block.deleteLater()
        qapp.processEvents()

    def test_reasoning_end_with_number_shows_duration(self, qapp):

        block = ReasoningBlock()
        block.resize(200, 60)
        block.show()
        qapp.processEvents()
        block.end(1500.0)
        qapp.processEvents()
        assert "1.5s" in block.title()
        block.deleteLater()
        qapp.processEvents()

    @pytest.mark.parametrize(
        "size,expect",
        [
            (0, "0 B"),
            (512, "512 B"),
            (1024, "1.0 KB"),
            (1024 * 1024, "1.0 MB"),
            ("1.2 MB", "1.2 MB"),
            ("512", "512 B"),
            (None, ""),
        ],
    )
    def test_attachment_display_size_tolerates_junk(self, qapp, size, expect):

        got = ElaChatAttachment(name="f", size=size).displaySize  # property
        assert got == expect, f"size={size!r} -> {got!r}，期望 {expect!r}"


# ---------------------------------------------------------------------- 3
class TestDrawerAreaButtonFilter:
    def test_only_left_button_toggles(self, qapp):

        area = ElaDrawerArea()
        area.resize(300, 200)
        area.show()
        qapp.processEvents()
        header = area._header
        assert header is not None

        def release(button):
            pos = QPoint(20, 10)
            glob = header.mapToGlobal(pos)
            qapp.sendEvent(
                header,
                QMouseEvent(
                    QEvent.Type.MouseButtonRelease,
                    QPointF(pos),
                    QPointF(glob),
                    button,
                    Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
            qapp.processEvents()

        before = area.getIsExpand()
        release(Qt.MouseButton.RightButton)
        assert area.getIsExpand() == before, "右键不应切换抽屉"

        release(Qt.MouseButton.MiddleButton)
        assert area.getIsExpand() == before, "中键不应切换抽屉"

        area.deleteLater()
        qapp.processEvents()

    def test_source_checks_button(self):

        assert "event.button()" in inspect.getsource(DA.ElaDrawerArea.eventFilter)


# ---------------------------------------------------------------------- 4
class TestRatingReclamps:
    def test_set_max_rating_reclamps_existing(self, qapp):

        r = ElaRatingControl()
        r.resize(200, 60)
        r.show()
        qapp.processEvents()
        r.setMaxRating(5)
        r.setRating(5)
        assert r.rating() == 5.0

        r.setMaxRating(3)
        assert r.rating() <= r.maxRating(), (
            f"rating()={r.rating()} > maxRating()={r.maxRating()}，值与界面不一致"
        )
        r.deleteLater()
        qapp.processEvents()

    def test_widening_max_keeps_rating(self, qapp):

        r = ElaRatingControl()
        r.resize(200, 60)
        r.show()
        qapp.processEvents()
        r.setMaxRating(3)
        r.setRating(2)
        r.setMaxRating(5)
        assert r.rating() == 2.0
        r.deleteLater()
        qapp.processEvents()

    def test_reclamp_emits_signal(self, qapp):

        r = ElaRatingControl()
        r.resize(200, 60)
        r.show()
        qapp.processEvents()
        r.setMaxRating(5)
        r.setRating(5)
        seen = []
        r.ratingChanged.connect(seen.append)
        r.setMaxRating(2)
        assert seen, "夹取当前评分应发 ratingChanged"
        r.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------- 5
class TestTableSignalsUnblocked:
    def test_exception_does_not_permanently_block_model(self, qapp):
        """一个会抛的单元格不得让模型永久 blockSignals(True)。"""

        class Boom:
            def __str__(self):
                raise RuntimeError("boom")

        t = ElaDataTable()
        t.resize(300, 200)
        t.show()
        qapp.processEvents()
        t.setTableData([["n"], ["1"], ["2"]])

        with pytest.raises(RuntimeError):
            t.setTableData([["n"], [Boom()]])

        assert t.model().blockSignals(False) is False, (
            "setTableData 抛异常后模型仍被 blockSignals(True)，视图永不更新"
        )
        # 还能正常写入
        t.setTableData([["n"], ["9"]])
        assert t.model().item(0, 0).text() == "9"
        t.deleteLater()
        qapp.processEvents()

    def test_source_has_try_finally(self):

        src = inspect.getsource(ElaDataTable.setTableData)
        assert "finally" in src and "blockSignals(False)" in src.split("finally")[-1]

    def test_row_index_column_cleared_when_disabled(self, qapp):
        """先以 show_row_index=True 填表，再关掉，行号必须清掉。"""

        t = ElaDataTable()
        t.resize(300, 200)
        t.show()
        qapp.processEvents()
        t.setTableData([["n"], ["a"], ["b"]], show_row_index=True)
        t.setTableData([["n"], ["x"], ["y"]], show_row_index=False)
        vh = t.verticalHeader()
        assert vh.isHidden() is True, "关掉行号后垂直表头应隐藏"
        t.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------- 6
class TestCachedPenIsolation:
    def test_mutable_returns_copy(self):

        c = QColor("#ff0000")
        shared = _cached_pen(c, 2.0, Qt.PenStyle.DashLine, [3.0, 3.0])
        copy = _cached_pen(c, 2.0, Qt.PenStyle.DashLine, [3.0, 3.0], mutable=True)
        copy.setDashOffset(99.0)
        assert shared.dashOffset() != 99.0, (
            "mutable=True 仍返回共享实例，setDashOffset 污染了缓存"
        )

    def test_shared_pen_unchanged_after_flowing_draw(self, qapp):

        pm = QPixmap(200, 200)
        p = QPainter(pm)
        try:
            base = EW._cached_pen(QColor("#00ff00"), 2.0, Qt.PenStyle.SolidLine)
            before = base.dashOffset()
            mut = EW._cached_pen(
                QColor("#00ff00"),
                2.0,
                Qt.PenStyle.SolidLine,
                mutable=True,
            )
            mut.setDashOffset(123.0)
            assert EW._cached_pen(QColor("#00ff00"), 2.0).dashOffset() == before
        finally:
            p.end()


# ---------------------------------------------------------------------- 7
class TestSelectionPollSafety:
    """划词 15ms 轮询的两道防线。

    关键事实（已实测）：**PyQt5 中槽抛出的异常不会传播给 emit 的调用方**，
    PyQt5 直接 abort（0xC0000409）。所以在 ``emit()`` 外面包 try/except 是
    无效的 —— 唯一有效的防线在槽侧（``safe_connect``）。
    """

    def test_poll_guards_win32_sampling(self, qapp, monkeypatch):
        """Win32 采样调用自身抛异常时，轮询不得让异常逃逸、边沿状态不得被污染。"""

        m = N.ElaMouseMonitor()  # 构造不启动轮询（AGENTS.md：不做真实全局拦截）
        m._reset_state()
        m._left_last = True  # 假装上轮左键按下
        calls = {"n": 0}

        def boom_cursor():
            calls["n"] += 1
            raise OSError("GetCursorPos failed")

        monkeypatch.setattr(N.ElaMouseMonitor, "_cursor_pos", staticmethod(boom_cursor))
        monkeypatch.setattr(
            N.ElaMouseMonitor, "_key_down", staticmethod(lambda vk: True)
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m._poll()  # 不得抛出
        assert calls["n"] == 1
        assert m._left_last is True, (
            "采样失败时不得清零边沿状态，否则下一轮会伪造一次「新的按下」"
        )
        m.deleteLater()
        qapp.processEvents()

    def test_poll_body_is_guarded(self):

        src = inspect.getsource(N.ElaMouseMonitor._poll)
        assert "except Exception" in src and "finally" in src
        assert "sampled" in src, "必须在采样成功时才推进边沿状态"

    def test_safe_connect_swallows_slot_exception(self, qapp):
        """safe_connect：槽抛异常必须被吞掉（这才是有效的那道防线）。"""

        m = _Sig()
        hits = []

        def bad(p):
            hits.append(p)
            raise RuntimeError("slot boom")

        safe_connect(m, "sig", bad, "bad")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m.sig.emit((1, 2))  # 不得 abort
            m.sig.emit((3, 4))
        assert hits == [(1, 2), (3, 4)], "槽未被调用"

    def test_safe_connect_forwards_to_real_slot(self, qapp):

        m = _Sig()
        got = []
        safe_connect(m, "sig", got.append, "collect")
        m.sig.emit(7)
        assert got == [7]

    def test_library_uses_safe_connect(self):
        """库内部连接 monitor 信号时必须走 safe_connect。"""

        src = inspect.getsource(assistant.ElaSelectionAssistant._connect_monitor)
        assert "safe_connect" in src
        assert ".leftPressed.connect(" not in src, (
            "直接 connect 会让宿主异常 abort 进程"
        )
