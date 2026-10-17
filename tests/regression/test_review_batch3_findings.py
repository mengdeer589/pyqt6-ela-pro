"""回归测试（第三批）：原生 Win32 / chat / blueprint / table，经实测确认的缺陷。

- ``stopGeneration()`` 先 emit 再收尾，宿主槽触发排队续发后 ``_streaming_id``
  已指向新消息，刚发出的续发回合被立刻置为 ``stopped``
- 错误回合不发 ``generationFinished``、不排空 ``autoSendQueue``
- ``bubble.beginStep()`` 只 detach 思考段而不 ``endReasoning()``
- ``ElaBrowserEmbedder.release()`` 签名与基类不符，基类的
  ``self.release(destroy=True)`` 抛 TypeError 并被吞掉 -> HWND 变孤儿
- ``_tryEmbedOnce`` 在 ``SetParent`` 之后失败无回滚，且 ``release()`` 会提前 return
- ``ElaClipboardCapture.capture()`` 不结算待恢复的剪贴板就重置基线 ->
  ``clipboard.clear()`` 清掉用户原内容
- ``ElaNodeContextMenu`` 缺 ``WA_DeleteOnClose``，画布每次右键泄漏一个 QMenu
- ``ElaNodeWidget`` 的引脚热区是构造时快照，之后 ``add_input`` 的引脚拖不出连线
- ``ElaNodeCreationMenu._first_item`` 未在 ``__init__`` 初始化
- ``_sort_numeric`` 把空/非数值单元格当 0，空值升序时排到最前
"""

from __future__ import annotations

import inspect

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from pyqt6_ela_pro import ElaBrowserEmbedder, ElaDataTable, ElaWindowEmbedder
from pyqt6_ela_pro.blueprint import (
    ElaBlueprintCanvas,
    ElaNodeContextMenu,
    ElaNodeCreationMenu,
    ElaNodeWidget,
)
from pyqt6_ela_pro.blueprint.model import ElaBlueprintNode

# ===================================================================== chat
from pyqt6_ela_pro.chat.binder import ElaChatStreamBinder
from pyqt6_ela_pro.chat.bubble import ElaChatBubble
from pyqt6_ela_pro.chat.message import ElaChatRoleType
from pyqt6_ela_pro.chat import ElaChatWidget
from pyqt6_ela_pro.selection_assistant import capture as capture_mod
from pyqt6_ela_pro.selection_assistant.capture import ElaClipboardCapture


class TestStopGenerationOrdering:
    """stopGeneration 必须先就地收尾旧流，再通知宿主。"""

    def test_new_turn_survives_stop(self, qapp):

        w = ElaChatWidget()
        w.resize(600, 400)
        w.show()
        qapp.processEvents()
        v = w.chatView()
        w.addMessage(ElaChatRoleType.User, "q1")
        w.beginAssistantMessage()

        repl = {}

        def on_stop():
            w.addMessage(ElaChatRoleType.User, "q2")
            repl["id"] = w.beginAssistantMessage()

        w.stopRequested.connect(on_stop)
        w.setGenerating(True)
        w.stopGeneration()
        qapp.processEvents()

        status = str(getattr(v.message(repl["id"]), "status", "")).lower()
        assert status != "stopped", (
            "刚被 stopRequested 宿主槽自动发出的续发回合被立刻置为 stopped"
        )

    def test_old_stream_is_still_stopped(self, qapp):

        w = ElaChatWidget()
        w.resize(600, 400)
        w.show()
        qapp.processEvents()
        w.addMessage(ElaChatRoleType.User, "q1")
        first = w.beginAssistantMessage()
        w.setGenerating(True)
        w.stopGeneration()
        qapp.processEvents()
        status = str(getattr(w.chatView().message(first), "status", "")).lower()
        assert status == "stopped", "被停止的旧回合本身仍应标记为 stopped"
        w.deleteLater()
        qapp.processEvents()

    def test_source_order_is_close_then_emit(self):

        src = inspect.getsource(ElaChatWidget.stopGeneration)
        assert src.index("_endActiveStream") < src.index("stopRequested.emit()")


class TestQueueDrainsAfterError:
    """错误回合也必须发 generationFinished 并排空队列。"""

    def test_generation_finished_emitted_after_error(self, qapp):

        w = ElaChatWidget()
        w.resize(600, 400)
        w.show()
        qapp.processEvents()
        fin = []
        w.generationFinished.connect(lambda *a: fin.append(1))
        w.addMessage(ElaChatRoleType.User, "q1")
        mid = w.beginAssistantMessage()
        w.chatView().appendText(mid, "x")
        # 走 widget 的 setMessageError：只有它会在出错后发 generationFinished
        # 并排空队列（widget 独占 generating 状态与排队续发）
        w.setMessageError("boom", mid)
        qapp.processEvents()
        assert len(fin) == 1, "setMessageError 之后必须发 generationFinished"
        w.deleteLater()
        qapp.processEvents()

    def test_end_assistant_message_error_branch_drains(self, qapp):

        w = ElaChatWidget()
        w.resize(600, 400)
        w.show()
        qapp.processEvents()
        w.addMessage(ElaChatRoleType.User, "q1")
        mid = w.beginAssistantMessage()
        w.chatView().setMessageError(mid, "boom")
        fin = []
        w.generationFinished.connect(lambda *a: fin.append(1))
        w.endAssistantMessage(mid)
        qapp.processEvents()
        assert len(fin) == 1, "对已出错消息再调 endAssistantMessage 仍要发完成信号"
        w.deleteLater()
        qapp.processEvents()

    def test_binder_finish_not_gated_on_is_generating(self):

        src = inspect.getsource(ElaChatStreamBinder.finish)
        assert "streamingMessageId()" in src, (
            "finish() 不能只在 isGenerating() 时收尾，否则错误回合后队列永不排空"
        )


class TestBeginStepEndsReasoning:
    def test_begin_step_calls_end_reasoning(self):

        src = inspect.getsource(ElaChatBubble.beginStep)
        assert "self.endText()" in src
        assert "self.endReasoning()" in src, (
            "beginStep 必须收尾思考段，否则转圈动画永停"
        )

    def test_no_part_left_streaming_after_begin_step(self, qapp):

        w = ElaChatWidget()
        w.resize(600, 400)
        w.show()
        qapp.processEvents()
        v = w.chatView()
        mid = w.beginAssistantMessage()
        v.beginReasoning(mid)
        v.appendText(mid, "answer")
        v.beginStep(mid)
        qapp.processEvents()
        statuses = [
            str(getattr(p, "status", "")).lower()
            for p in getattr(v.message(mid), "parts", [])
        ]
        assert all(not s.startswith("stream") for s in statuses), (
            f"beginStep 后仍有 part 处于 streaming：{statuses}"
        )
        w.deleteLater()
        qapp.processEvents()


# =============================================================== native/Win32
class TestEmbedderReleaseContract:
    """基类以 ``self.release(destroy=True)`` 调子类，签名必须兼容。"""

    def test_browser_release_accepts_destroy(self):

        params = inspect.signature(ElaBrowserEmbedder.release).parameters
        assert "destroy" in params, (
            "ElaBrowserEmbedder.release 必须接受 destroy，否则基类的 "
            "self.release(destroy=True) 抛 TypeError 并被 except 吞掉，HWND 变孤儿"
        )

    def test_base_calls_release_with_destroy(self):

        assert "self.release(destroy=True)" in inspect.getsource(
            ElaWindowEmbedder._tryEmbedOnce
        )

    def test_rollback_helper_exists(self):

        assert hasattr(ElaWindowEmbedder, "_rollbackPartialEmbed")
        src = inspect.getsource(ElaWindowEmbedder._tryEmbedOnce)
        assert "_rollbackPartialEmbed" in src, "SetParent 之后的异常分支必须回滚"


class TestClipboardRestoreSettledFirst:
    """第二次取词不能把待恢复的剪贴板基线清成空（否则 clear() 掉用户内容）。"""

    def test_second_capture_restores_instead_of_clearing(self, qapp, monkeypatch):

        cap = ElaClipboardCapture()
        calls = []

        class FakeClipboard:
            def setText(self, text):
                calls.append(("setText", text))

            def clear(self):
                calls.append(("clear",))

            def text(self):
                return "x"

        fake = FakeClipboard()
        monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda: fake))

        cap._old_text = "USER_PRECIOUS"
        # 假剪贴板声称自己持有的是 "x"（见上面 FakeClipboard.text），
        # 所以上一次取词放进剪贴板的也必须是 "x" —— 新契约下「剪贴板还是
        # 我们自己放的那份」是还原的前提（见 AGENTS.md 剪贴板恢复那条）
        cap._captured_text = "x"
        cap._need_restore = True
        cap._restore_delay_ms = 500
        # 快照取「当前」序列号，模拟「取词之后没人动过剪贴板」：
        # 恢复三道校验的第二道（序列号比对）必须放行，否则这里会跳过还原。
        cap._capture_seq = capture_mod.clipboard_sequence_number()

        cap.capture()

        assert ("clear",) not in calls, f"用户原有剪贴板被清空：{calls}"
        assert ("setText", "USER_PRECIOUS") in calls, (
            f"应在开始新手势前先结算上一次的恢复：{calls}"
        )

    def test_capture_settles_pending_restore(self):

        src = inspect.getsource(ElaClipboardCapture.capture)
        assert "_need_restore" in src and "_restore_clipboard" in src


# ================================================================ blueprint
class TestBlueprintMenuLifetime:
    def test_context_menu_has_delete_on_close(self):

        m = ElaNodeContextMenu("n1")
        assert m.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose) is True, (
            "画布每次右键都 new 一个，parent 是 canvas；不设 WA_DeleteOnClose "
            "会每次右键永久泄漏一个 QMenu"
        )
        m.deleteLater()

    def test_creation_menu_has_delete_on_close(self):

        m = ElaNodeCreationMenu()
        assert m.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose) is True
        m.deleteLater()

    def test_first_item_initialised(self):

        m = ElaNodeCreationMenu()
        assert hasattr(m, "_first_item"), (
            "_first_item 只在 _rebuild 赋值，首帧前按 Enter 会 AttributeError"
        )
        assert m._first_item is None
        m.deleteLater()


class TestBlueprintPinSync:
    """构造之后 add_input/add_output 的引脚也必须有热区。"""

    def test_new_pin_gets_handle(self, qapp):

        node = ElaBlueprintNode("t", "n1")
        w = ElaNodeWidget(node)
        w.show()
        qapp.processEvents()
        before = len(w._handles)

        node.add_input("extra_in")
        node.add_output("extra_out")
        qapp.processEvents()

        assert len(w._handles) == before + 2
        assert w.pin_widget("extra_in") is not None
        assert w.pin_widget("extra_out") is not None
        w.deleteLater()
        qapp.processEvents()

    def test_sync_pins_drops_stale(self, qapp):

        node = ElaBlueprintNode("t", "n2")
        node.add_input("a")
        node.add_output("b")
        w = ElaNodeWidget(node)
        w.show()
        qapp.processEvents()
        assert len(w._handles) == 2

        node.inputs.clear()
        node.changed.emit()
        qapp.processEvents()
        assert len(w._handles) == 1
        assert w.pin_widget("b") is not None
        w.deleteLater()
        qapp.processEvents()

    def test_canvas_installs_filter_on_new_handles(self, qapp):

        c = ElaBlueprintCanvas()
        c.resize(600, 400)
        c.show()
        qapp.processEvents()
        node = ElaBlueprintNode("t", "n3")
        c.graph.add_node(node)
        qapp.processEvents()
        widget = c._node_widgets.get(node.id)
        assert widget is not None

        seen = []
        widget.pinsSynced.connect(seen.append)
        node.add_input("late")
        qapp.processEvents()
        assert seen and seen[0], "新建热区应通过 pinsSynced 通知画布"
        c.deleteLater()
        qapp.processEvents()


# ==================================================================== table
class TestNumericSortBlanks:
    """空/非数值单元格必须排在最后，而不是当 0 顶到最前。"""

    def _sorted(self, qapp, rows, order):

        t = ElaDataTable()
        t.setTableData([["n"]] + rows, show_row_index=False)
        qapp.processEvents()
        t._sort_numeric(0, order)
        qapp.processEvents()
        return [t.model().item(r, 0).text() for r in range(t.model().rowCount())]

    def test_blank_sorts_last_ascending(self, qapp):
        vals = self._sorted(qapp, [["10"], [""], ["9"]], Qt.SortOrder.AscendingOrder)
        assert vals == ["9", "10", ""], f"升序空值跑到了最前：{vals}"

    def test_blank_sorts_last_descending(self, qapp):
        vals = self._sorted(qapp, [["10"], [""], ["9"]], Qt.SortOrder.DescendingOrder)
        assert vals == ["10", "9", ""], f"降序空值应在最后：{vals}"

    def test_non_numeric_sorts_last(self, qapp):
        vals = self._sorted(qapp, [["10"], ["abc"], ["9"]], Qt.SortOrder.AscendingOrder)
        assert vals[-1] == "abc", f"非数值单元格应在最后：{vals}"

    def test_numeric_order_unchanged(self, qapp):
        vals = self._sorted(qapp, [["10"], ["9"], ["2"]], Qt.SortOrder.AscendingOrder)
        assert vals == ["2", "9", "10"]
