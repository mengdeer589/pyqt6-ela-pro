"""Agent 级能力：手动重试 / steer 插话 / 工具审批 / 压缩表达 / 成本 / 上下文占用。

对照 opencode v2 的对应实现：

- 手动重试 ← ``session-ui/src/components/session-retry.tsx``（**只做手动**，
  不做自动退避、不做 ``CONTINUE_AFTER_INCOMPLETE_STREAM`` 断流续写）；
- steer ← ``schema/session-inbox.ts`` 的 ``Delivery = "steer" | "queue"``；
- 审批 ← ``core/src/permission.ts`` + ``core/src/form.ts``（但**不阻塞**）；
- 压缩表达 ← ``schema/session-message.ts`` 的 ``Compaction`` variant
  （**只做表达**，不做 ``SHRINK_STEPS`` 收缩算法）。
"""

from __future__ import annotations

import json

import pytest

from PyQt6.QtCore import QEvent, QPoint, Qt, QPointF
from PyQt6.QtGui import QMouseEvent

from pyqt6_ela_pro.chat import (
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolStatusType,
    ElaChatWidget,
    ModelPricing,
    cost_from_parts,
    formatCost,
    stats_cost,
)
from pyqt6_ela_pro.chat.blocks import (
    RETRYABLE_ERROR_TYPES,
    CompactionSeparator,
    PermissionRecord,
)
from pyqt6_ela_pro.chat.message import (
    ElaChatMessage,
    ElaChatOption,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatPermission,
    ElaChatPermissionStatusType,
    ElaChatQuestion,
)


@pytest.fixture
def chat(qapp, make):
    return make(ElaChatWidget)


def _turn(chat, text="hi"):
    chat.sendUserMessage(text)
    return chat.beginAssistantMessage()


# ================================================================== 手动重试
class TestManualRetry:
    def test_error_type_is_stored_separately(self, chat):
        mid = _turn(chat)
        chat.chatView().setMessageError(mid, "连接中断", "Timeout")
        message = chat.chatView().message(mid)
        assert message.error == "连接中断"
        assert message.error_type == "Timeout"
        assert chat.chatView().messageError(mid) == ("连接中断", "Timeout")

    def test_error_type_roundtrips(self):
        message = ElaChatMessage(
            id=1, role="assistant", error="boom", error_type="RateLimit"
        )
        assert ElaChatMessage.fromDict(message.toDict()) == message

    def test_retry_button_only_for_retryable(self, chat):
        mid = _turn(chat)
        chat.chatView().setMessageError(mid, "限流", "RateLimit")
        assert chat.chatView().bubble(mid).errorCard().canRetry() is True

        mid2 = _turn(chat, "second")
        chat.chatView().setMessageError(mid2, "密钥无效", "AuthenticationError")
        assert chat.chatView().bubble(mid2).errorCard().canRetry() is False

    @pytest.mark.parametrize("bad", ["BadRequest", "content_filter", "上下文超长", ""])
    def test_non_retryable_types(self, chat, bad):
        mid = _turn(chat)
        chat.chatView().setMessageError(mid, "x", bad)
        assert chat.chatView().bubble(mid).errorCard().canRetry() is False

    @pytest.mark.parametrize("good", sorted(RETRYABLE_ERROR_TYPES)[:6])
    def test_retryable_types(self, chat, good):
        mid = _turn(chat)
        chat.chatView().setMessageError(mid, "x", good)
        assert chat.chatView().bubble(mid).errorCard().canRetry() is True

    def test_regenerate_always_available(self, chat):
        mid = _turn(chat)
        chat.chatView().setMessageError(mid, "密钥无效", "AuthenticationError")
        card = chat.chatView().bubble(mid).errorCard()
        assert card._actions.keys() == ["regenerate"]

    def test_buttons_emit_signals(self, chat):
        seen = []
        chat.retryRequested.connect(lambda i: seen.append(("retry", i)))
        chat.regenerateRequested.connect(lambda i: seen.append(("regen", i)))
        mid = _turn(chat)
        chat.chatView().setMessageError(mid, "限流", "RateLimit")
        card = chat.chatView().bubble(mid).errorCard()
        card._actions.toolButton("retry").click()
        card._actions.toolButton("regenerate").click()
        assert seen == [("retry", mid), ("regen", mid)]

    def test_retry_message_keeps_position(self, chat):
        userId = chat.sendUserMessage("hi")
        mid = chat.beginAssistantMessage()
        chat.chatView().setMessageError(mid, "超时", "Timeout")
        before = chat.chatView().count()

        prompt = chat.retryMessage(mid)
        assert prompt is not None and prompt.id == userId
        # 消息不删（区别于 regenerateFrom），错误被清掉
        assert chat.chatView().count() == before
        assert chat.chatView().messageError(mid) == ("", "")

    def test_retry_message_without_user_message_is_noop(self, chat):
        mid = chat.beginAssistantMessage()
        chat.chatView().setMessageError(mid, "x", "Timeout")
        before = chat.chatView().count()
        assert chat.retryMessage(mid) is None
        assert chat.chatView().count() == before
        assert chat.chatView().messageError(mid)[0] == "x"

    def test_clear_error_resets_type(self, chat):
        mid = _turn(chat)
        chat.chatView().setMessageError(mid, "x", "Timeout")
        chat.chatView().clearMessageError(mid)
        assert chat.chatView().messageError(mid) == ("", "")

    def test_binder_does_not_mangle_type(self, qapp, make):
        from pyqt6_ela_pro.chat import ElaChatStreamBinder

        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat)
        mid = chat.beginAssistantMessage()
        binder.beginTurn()
        binder.beginRound()
        binder.error("RateLimit", "慢一点")
        message = chat.chatView().message(mid)
        assert message.error == "慢一点"
        assert message.error_type == "RateLimit"


# ================================================================== steer
class TestSteer:
    def test_steer_queue_is_separate_from_normal_queue(self, chat):
        chat.steerMessage("等等")
        chat.enqueueMessage("排队")
        assert chat.steerCount() == 1
        assert chat.queueCount() == 1
        assert len(chat.queuedMessages()) == 1
        assert chat.queuedMessages()[0]["text"] == "排队"

    def test_steer_idempotency(self, chat):
        first = chat.steerMessage("a", messageId="k1")
        again = chat.steerMessage("b", messageId="k1")
        assert first == again
        assert chat.steerCount() == 1
        assert chat.steerMessages()[0]["text"] == "a"

    def test_empty_text_rejected(self, chat):
        assert chat.steerMessage("   ") is None
        assert chat.steerCount() == 0

    def test_drain_one_at_a_time(self, chat):
        chat.steerMessage("一")
        chat.steerMessage("二")
        first = chat.drainSteer()
        assert first["text"] == "一"
        assert chat.steerCount() == 1
        chat.drainSteer()
        assert chat.drainSteer() is None

    def test_drain_emits_steer_ready(self, chat):
        seen = []
        chat.steerReady.connect(seen.append)
        chat.steerMessage("插一句")
        chat.drainSteer()
        assert len(seen) == 1
        assert seen[0]["text"] == "插一句"

    def test_drain_writes_receipt_into_streaming_message(self, chat):
        mid = chat.beginAssistantMessage()
        chat.steerMessage("别删那个文件")
        chat.drainSteer()
        parts = chat.chatView().message(mid).partsOfKind(ElaChatPartKindType.Synthetic)
        assert len(parts) == 1
        assert parts[0].text == "别删那个文件"

    def test_receipt_text_not_merged_into_message_text(self, chat):
        """插话回执是旁注，不能并进模型正文（否则导出/复制会带上）。"""
        mid = chat.beginAssistantMessage()
        chat.chatView().beginText(mid)
        chat.chatView().appendText(mid, "模型正文")
        chat.chatView().endText(mid)
        chat.chatView().addSteerNotice(mid, "插话")
        message = chat.chatView().message(mid)
        assert message.text == "模型正文"

    def test_binder_drains_at_step_boundary(self, qapp, make):
        from pyqt6_ela_pro.chat import ElaChatStreamBinder

        chat = make(ElaChatWidget)
        binder = ElaChatStreamBinder(chat)
        chat.beginAssistantMessage()
        binder.beginTurn()
        binder.beginRound()  # 第 1 轮：无插话
        chat.steerMessage("改主意了")
        binder.beginRound()  # 第 2 轮 = step 边界 -> 投递
        assert chat.steerCount() == 0

    def test_binder_respects_disabled_flag(self, qapp, make):
        from pyqt6_ela_pro.chat import ElaChatStreamBinder

        chat = make(ElaChatWidget)
        chat.setSteerEnabled(False)
        binder = ElaChatStreamBinder(chat)
        chat.beginAssistantMessage()
        binder.beginTurn()
        binder.beginRound()
        chat.steerMessage("留着")
        binder.beginRound()
        assert chat.steerCount() == 1

    def test_dequeue_and_clear(self, chat):
        sid = chat.steerMessage("a")
        assert chat.dequeueSteer(sid) is True
        assert chat.dequeueSteer(sid) is False
        chat.steerMessage("b")
        chat.steerMessage("c")
        chat.clearSteer()
        assert chat.steerCount() == 0

    def test_steer_changed_signal(self, chat):
        seen = []
        chat.steerChanged.connect(lambda items: seen.append(len(items)))
        chat.steerMessage("a")
        chat.drainSteer()
        assert seen == [1, 0]


# ================================================================== 工具审批
class TestPermission:
    def _request(self, **kwargs):
        base = {"request_id": "r1", "action": "shell"}
        base.update(kwargs)
        return ElaChatPermission(**base)

    def test_begin_emits_requested(self, chat):
        seen = []
        chat.permissionRequested.connect(lambda i, r: seen.append((i, r)))
        mid = _turn(chat)
        partId = chat.chatView().beginPermission(mid, self._request())
        assert partId
        assert seen == [(mid, "r1")]

    def test_does_not_block(self, chat):
        """库不阻塞：beginPermission 立即返回，事件循环照常转。"""
        mid = _turn(chat)
        chat.chatView().beginPermission(mid, self._request())
        assert len(chat.chatView().pendingPermissions(mid)) == 1

    def test_reply_updates_part_and_emits(self, chat):
        seen = []
        chat.permissionReplied.connect(
            lambda i, r, rep, a, f: seen.append((i, r, rep, a, f))
        )
        mid = _turn(chat)
        chat.chatView().beginPermission(mid, self._request(resources=("rm -rf /",)))
        assert chat.chatView().resolvePermission(mid, "r1", "rejected", "", "别删")
        assert seen == [(mid, "r1", "rejected", "", "别删")]
        parts = chat.chatView().message(mid).partsOfKind(ElaChatPartKindType.Permission)
        assert parts[0].permission.status == ElaChatPermissionStatusType.Rejected
        assert parts[0].permission.feedback == "别删"
        assert chat.chatView().pendingPermissions(mid) == []

    def test_card_buttons_emit(self, chat):
        seen = []
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        mid = _turn(chat)
        chat.chatView().beginPermission(mid, self._request())
        card = chat.chatView().interactivePermissionCard(mid, "r1")
        allow, always, _reject = card._action_buttons()
        assert [allow.text(), always.text()] == ["允许一次", "始终允许"]
        allow.click()
        # 落定后动作区整体撤掉（已答复的卡不该还能点「始终允许」）
        assert card._actions.isHidden()
        assert not any(b.isEnabled() for b in card._action_buttons())
        assert seen == ["allowed"]

    def test_always_button_emits_always(self, chat):
        seen = []
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        mid = _turn(chat)
        chat.chatView().beginPermission(mid, self._request())
        chat.chatView().interactivePermissionCard(mid, "r1")._action_buttons()[
            1
        ].click()
        assert seen == ["always"]

    def test_double_click_guarded(self, chat):
        """回复在途时第二次点击必须被吞掉（对齐 opencode 的 responding）。"""
        seen = []
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        mid = _turn(chat)
        chat.chatView().beginPermission(mid, self._request())
        card = chat.chatView().interactivePermissionCard(mid, "r1")
        card._emit_reply("allowed", "", "")
        card._emit_reply("always", "", "")  # responding 期间应被拦掉
        assert seen == ["allowed"]

    def test_question_options_render(self, chat):
        """问答型：候选卡渲染出来，选中后**提交**才发信号（不再是点一下就发）。"""
        seen = []
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append((rep, a)))
        mid = _turn(chat)
        chat.chatView().beginPermission(
            mid,
            self._request(
                action="question",
                questions=(
                    ElaChatQuestion(
                        key="q0",
                        question="改哪个？",
                        options=(
                            ElaChatOption("改成 B", "只动 blocks.py"),
                            ElaChatOption("改成 C", "两个都改"),
                        ),
                    ),
                ),
            ),
        )
        card = chat.chatView().interactivePermissionCard(mid, "r1")
        # 2 张候选卡 + 「输入自己的答案」那一行
        assert len(card._option_buttons) == 3
        assert card._option_buttons[2].isCustom()
        card._option_buttons[0].activate.emit("改成 B")
        assert seen == [], "选中不该立刻发信号 —— 逐题向导要先收齐再提交"
        assert card.answers() == {"q0": ["改成 B"]}
        card._go_next()  # 最后一题 = 提交
        assert seen == [("allowed", '{"q0":"改成 B"}')]

    def test_abort_cancels_pending(self, chat):
        """opencode 漏掉的一环：回合中止必须把未答复的审批作废，
        否则界面上留下永远点不动的死卡。"""
        seen = []
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        mid = _turn(chat)
        chat.chatView().beginPermission(mid, self._request())
        chat.chatView().bubble(mid).cancelPendingPermissions()
        assert chat.chatView().pendingPermissions(mid) == []
        assert seen == ["cancelled"]

    def test_end_stream_cancels_pending(self, chat):
        mid = _turn(chat)
        chat.chatView().beginPermission(mid, self._request())
        chat.endAssistantMessage(status=ElaChatStatusType.Done)
        assert chat.chatView().pendingPermissions(mid) == []

    def test_dict_request_accepted(self, chat):
        mid = _turn(chat)
        partId = chat.chatView().beginPermission(
            mid, {"request_id": "r9", "action": "edit"}
        )
        assert partId
        assert [p.request_id for p in chat.chatView().pendingPermissions(mid)] == ["r9"]

    def test_permission_roundtrips(self):
        part = ElaChatPart(
            id="p",
            kind=ElaChatPartKindType.Permission,
            permission=ElaChatPermission(
                request_id="r1",
                action="shell",
                resources=("a", "b"),
                detail="rm -rf /",
                status=ElaChatPermissionStatusType.Always,
            ),
        )
        assert ElaChatPart.fromDict(part.toDict()) == part

    def test_restored_card_is_a_read_only_record(self, chat, qapp, make):
        """恢复历史时的审批**一律是只读记录**。

        两条都不做：① **不发** ``permissionRequested`` —— 那次请求早已随上个进程
        消失，宿主此刻没在等这个回复；② **不放进 dock**、状态落成 ``Cancelled``
        —— dock 是「现在要你动手」的位置，历史里摆一张点不动的待答卡只会让人
        以为还能答。它照样显示（用户能看到「这里曾需要你确认」）。
        """
        part = ElaChatPart(
            id="p1",
            kind=ElaChatPartKindType.Permission,
            permission=ElaChatPermission(request_id="r1", action="edit"),
        )
        message = ElaChatMessage(id=1, role="assistant", parts=(part,)).withParts(
            (part,)
        )
        seen = []
        chat.permissionRequested.connect(lambda i, r: seen.append(r))
        mid = chat.chatView().addMessageFromDict(message.toDict())
        qapp.processEvents()
        assert seen == []
        view = chat.chatView()
        assert view.pendingPermissions(mid) == []
        assert view.interactivePermissionCard(mid, "r1") is None
        assert chat.pendingPermissionCards() == []
        record = view.permissionCard(mid, "r1")
        assert isinstance(record, PermissionRecord), "记录卡仍然要显示"
        assert record.permission().status == ElaChatPermissionStatusType.Cancelled

    def test_resolve_unknown_returns_false(self, chat):
        mid = _turn(chat)
        assert chat.chatView().resolvePermission(mid, "nope", "allowed") is False


# ================================================================== 压缩表达
class TestFontScale:
    """**每个 ``ColorText`` 都必须显式设字号。**

    ``ColorText`` 走 ``ElaText``，不调 ``setTextPixelSize`` 就是 ``ElaText`` 的
    默认字号 —— 实测 **28px**，比 chat 的 11-14px 标尺大一大截。这是个静默的坑：
    不报错、不崩，只是「大」，而且只在一处（某个渲染器 / 某张卡的正文区）冒出来，
    整张卡的比例就崩了（实测截图：工具卡的 diff 视图行比头部大一号）。

    这条测试把 chat 里每种分段都摆一遍，然后逐个 ``ColorText`` 查字号。
    """

    #: chat 允许的字号上限（工具卡头部 13px 是最大的正文级文字）
    MAX_PX = 14

    @staticmethod
    def _populate(chat):
        view = chat.chatView()
        view.setStatsMode("steps")
        mid = _turn(chat)
        view.beginStep(mid)
        view.beginReasoning(mid)
        view.appendReasoning(mid, "先想一下")
        view.endReasoning(mid, 1200)
        view.appendText(mid, "正文一段")
        view.addToolCall(mid, "read", {"filePath": "a.py"}, "文件内容")
        view.setStepStats(mid, ElaChatStats(prompt_tokens=10, completion_tokens=20))
        view.addToolCall(mid, "bash", {"cmd": "ls"}, "ok")
        partId = view.beginCompaction(mid, "auto")
        view.appendCompactionSummary(mid, partId, "摘要一行")
        view.endCompaction(mid, partId, historyCount=12)
        view.addSteerNotice(mid, "插话回执")
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="q1",
                action="question",
                questions=(
                    ElaChatQuestion(
                        key="q0",
                        header="范围",
                        question="哪些目录？",
                        options=(ElaChatOption("a/", "组件"),),
                    ),
                ),
            ),
        )
        view.resolvePermission(mid, "q1", "allowed", '{"q0": "a/"}')
        view.setMessageError(mid, "出错了", "Timeout")
        view.endMessage(mid, ElaChatStatusType.Done)
        return mid

    def test_every_color_text_has_an_explicit_size(self, qapp, make):
        from pyqt6_ela_pro._styles import ColorText

        chat = make(ElaChatWidget)
        self._populate(chat)
        qapp.processEvents()
        labels = chat.findChildren(ColorText)
        assert labels, "没抓到任何 ColorText，测试本身失效了"
        bad = [
            (label.font().pixelSize(), type(label.parent()).__name__, label.text()[:30])
            for label in labels
            if not 0 < label.font().pixelSize() <= self.MAX_PX
        ]
        assert not bad, f"字号失控（上限 {self.MAX_PX}px）：{bad}"

    def test_the_default_really_is_huge(self, qapp, make):
        """把「默认到底多大」钉住 —— 这是上面那条测试存在的原因。"""
        from pyqt6_ela_pro._styles import ColorText

        probe = make(ColorText, "probe")
        assert probe.font().pixelSize() > self.MAX_PX, (
            "ElaText 默认字号变小了的话，上面那条测试的上限可以再降"
        )


class TestCompactionLabel:
    """压缩分隔卡：文案要诚实，摘要要看得见。"""

    @staticmethod
    def _card(chat, summary="保留了：架构约定 / 三个 API 变更", count=0):
        view = chat.chatView()
        mid = _turn(chat)
        partId = view.beginCompaction(mid, "auto")
        view.appendCompactionSummary(mid, partId, summary)
        view.endCompaction(mid, partId, historyCount=count)
        cards = chat.findChildren(CompactionSeparator)
        assert cards, "没渲染出压缩分隔卡"
        return cards[0]

    def test_unknown_count_does_not_claim_zero(self, qapp, make):
        """**没给条数就不能写「0 条」** —— 那是在说谎。

        ``historyCount`` 默认 0 的含义是「不知道」，不是「真的压了 0 条」。
        实测截图里就是一行「已压缩 0 条历史」，读者会以为压缩出了问题。
        """
        chat = make(ElaChatWidget)
        card = self._card(chat, count=0)
        assert card._label.text() == CompactionSeparator.LABEL_NO_COUNT
        assert "0" not in card._label.text()

    def test_known_count_is_shown(self, qapp, make):
        chat = make(ElaChatWidget)
        card = self._card(chat, count=24)
        assert card._label.text() == "已压缩 24 条历史"

    def test_collapsed_card_still_shows_the_summary(self, qapp, make):
        """折叠着也要能回答「到底压掉了什么」。

        只留一行「已压缩 N 条历史」+ 一个箭头 = 什么都没说；这条分隔存在的意义
        就是如实表达「历史被摘要替代」，摘要首行必须露出来（对齐 opencode 的
        ``SessionCompactionMessage``）。
        """
        chat = make(ElaChatWidget)
        card = self._card(chat, summary="保留了：架构约定")
        assert not card.opened()
        assert "保留了" in card._preview.text()
        assert not card._preview.isHidden()

    def test_expanding_hides_the_preview(self, qapp, make):
        """展开后正文全露了，预览行就没必要重复。"""
        chat = make(ElaChatWidget)
        card = self._card(chat, summary="保留了：架构约定")
        card.setOpened(True)
        assert card._preview.isHidden()
        card.setOpened(False)
        assert not card._preview.isHidden()

    def test_preview_takes_the_first_non_empty_line(self, qapp, make):
        chat = make(ElaChatWidget)
        card = self._card(chat, summary="\n\n  真正的首行  \n第二行")
        assert card._preview.text() == "真正的首行"

    def test_long_summary_is_elided_by_hand(self, qapp, make):
        """``ColorText`` 不按宽度省略（``ElaText.sizeHint`` 无视 wordWrap），
        所以预览只能自己按字符数截。"""
        chat = make(ElaChatWidget)
        card = self._card(chat, summary="x" * 500)
        assert len(card._preview.text()) <= 72
        assert card._preview.text().endswith("…")

    def test_no_summary_means_no_preview_row(self, qapp, make):
        chat = make(ElaChatWidget)
        card = self._card(chat, summary="")
        assert card._preview.text() == ""
        assert card._preview.isHidden()


class TestCompaction:
    def test_compaction_part_lifecycle(self, chat):
        mid = _turn(chat)
        view = chat.chatView()
        partId = view.beginCompaction(mid, "auto")
        assert partId
        view.appendCompactionSummary(mid, partId, "## 目标")
        view.appendCompactionSummary(mid, partId, "\n- 修 bug")
        view.endCompaction(mid, partId, ElaChatStatusType.Done, 24)
        parts = view.message(mid).partsOfKind(ElaChatPartKindType.Compaction)
        assert len(parts) == 1
        assert parts[0].text == "## 目标\n- 修 bug"
        assert parts[0].status == ElaChatStatusType.Done

    def test_summary_not_merged_into_message_text(self, chat):
        mid = _turn(chat)
        view = chat.chatView()
        view.beginText(mid)
        view.appendText(mid, "正文")
        view.endText(mid)
        partId = view.beginCompaction(mid)
        view.appendCompactionSummary(mid, partId, "## 摘要")
        view.endCompaction(mid, partId)
        # 摘要是历史的替代物，并进 text 等于把同一段历史算两遍
        assert view.message(mid).text == "正文"

    def test_streaming_then_crash_settles(self, chat):
        mid = _turn(chat)
        view = chat.chatView()
        partId = view.beginCompaction(mid)
        view.appendCompactionSummary(mid, partId, "半截摘要")
        chat.endAssistantMessage(status=ElaChatStatusType.Stopped)
        parts = view.message(mid).partsOfKind(ElaChatPartKindType.Compaction)
        assert parts[0].status != ElaChatStatusType.Streaming

    def test_roundtrips_through_persistence(self, chat, qapp, make):
        mid = _turn(chat)
        view = chat.chatView()
        partId = view.beginCompaction(mid)
        view.appendCompactionSummary(mid, partId, "## 摘要")
        view.endCompaction(mid, partId, ElaChatStatusType.Done, 10)
        data = view.message(mid).toDict()

        other = make(ElaChatWidget)
        other.chatView().addMessageFromDict(data)
        parts = other.chatView().message(mid).partsOfKind(ElaChatPartKindType.Compaction)
        assert len(parts) == 1
        assert parts[0].text == "## 摘要"

    def test_journal_records_compaction(self):
        from pyqt6_ela_pro.chat import ElaChatTurnJournal

        journal = ElaChatTurnJournal(messageId=1).begin()
        journal.beginCompaction("auto")
        journal.compactionSummary("## 目标")
        journal.endCompaction(ElaChatStatusType.Done, 24)
        journal.end(ElaChatStatusType.Done)
        lines = journal.dumps().splitlines()
        for line in lines:
            assert ElaChatTurnJournal.loadsLine(line) is not None
        replayed = ElaChatTurnJournal.fromLines(lines).message()
        parts = replayed.partsOfKind(ElaChatPartKindType.Compaction)
        assert len(parts) == 1
        assert parts[0].text == "## 目标"
        assert parts[0].status == ElaChatStatusType.Done

    def test_journal_tolerates_truncated_compaction(self):
        from pyqt6_ela_pro.chat import ElaChatTurnJournal

        journal = ElaChatTurnJournal(messageId=1).begin()
        journal.beginCompaction("auto")
        journal.compactionSummary("## 目标")
        journal.end(ElaChatStatusType.Done)
        lines = journal.dumps().splitlines()
        broken = lines[:2] + [lines[2][:15]]
        message = ElaChatTurnJournal.fromLines(broken).message()
        assert isinstance(message, ElaChatMessage)


# ================================================================== 成本
class TestCost:
    def test_cost_field_roundtrips(self):
        stats = ElaChatStats(prompt_tokens=10, completion_tokens=5, cost_usd=0.0123)
        assert ElaChatStats.fromDict(stats.toDict()) == stats

    def test_cost_merged_by_sum(self):
        merged = ElaChatStats.merge(
            [ElaChatStats(cost_usd=0.01), ElaChatStats(cost_usd=0.02)]
        )
        assert merged.cost_usd == pytest.approx(0.03)

    def test_tooltip_shows_cost(self):
        stats = ElaChatStats(prompt_tokens=10, completion_tokens=5, cost_usd=0.0142)
        assert "花费 $0.0142" in stats.tooltip()

    def test_tooltip_omits_zero_cost(self):
        assert "花费" not in ElaChatStats(prompt_tokens=1).tooltip()

    def test_nan_cost_becomes_zero(self):
        stats = ElaChatStats.fromDict({"cost_usd": float("nan")})
        assert stats.cost_usd == 0.0

    def test_stats_cost_basic(self):
        price = ModelPricing(input_per_m=3.0, output_per_m=15.0, cache_read_per_m=0.3)
        stats = ElaChatStats(
            prompt_tokens=1000, completion_tokens=500, cache_read_tokens=200
        )
        expected = (1000 * 3.0 + 500 * 15.0 + 200 * 0.3) / 1_000_000
        assert stats_cost(stats, price) == pytest.approx(expected)

    def test_tier_selected_by_largest_matching(self):
        price = ModelPricing(
            input_per_m=3.0,
            output_per_m=15.0,
            tiers=(
                (100_000, ModelPricing(input_per_m=6.0, output_per_m=30.0)),
                (200_000, ModelPricing(input_per_m=12.0, output_per_m=60.0)),
            ),
        )
        small = ElaChatStats(prompt_tokens=1000, completion_tokens=1000)
        mid = ElaChatStats(prompt_tokens=150_000, completion_tokens=1000)
        big = ElaChatStats(prompt_tokens=250_000, completion_tokens=1000)
        # 1000 输入 + 1000 输出，基础档
        assert stats_cost(small, price) == pytest.approx((3000 + 15000) / 1_000_000)
        # 15 万输入 -> 命中 10 万档（6 / 30）
        assert stats_cost(mid, price) == pytest.approx((900_000 + 30_000) / 1_000_000)
        # 25 万输入 -> 命中 20 万档（12 / 60）
        assert stats_cost(big, price) == pytest.approx((3_000_000 + 60_000) / 1_000_000)

    @pytest.mark.parametrize(
        "stats,price",
        [
            (None, ModelPricing(input_per_m=1.0)),
            (ElaChatStats(prompt_tokens=1), None),
            (ElaChatStats(prompt_tokens=1), ModelPricing()),
        ],
    )
    def test_missing_inputs_give_zero(self, stats, price):
        assert stats_cost(stats, price) == 0.0

    def test_negative_and_nan_prices_give_zero(self):
        price = ModelPricing(input_per_m=-5.0, output_per_m=float("nan"))
        assert stats_cost(ElaChatStats(prompt_tokens=1000), price) == 0.0

    def test_cost_from_parts_splits_cache(self):
        price = ModelPricing(
            input_per_m=3.0,
            output_per_m=15.0,
            cache_read_per_m=0.3,
            cache_write_per_m=3.75,
        )
        got = cost_from_parts(1000, 500, cacheRead=200, cacheWrite=100, pricing=price)
        expected = (1000 * 3.0 + 500 * 15.0 + 200 * 0.3 + 100 * 3.75) / 1_000_000
        assert got == pytest.approx(expected)

    @pytest.mark.parametrize(
        "value,expected",
        [
            (0, "$0.00"),
            (0.0142, "$0.0142"),
            (1.234, "$1.23"),
            (12.4, "$12.40"),
            (1234.5, "$1234"),
            (-1, "$0.00"),
            (None, "$0.00"),
            (float("nan"), "$0.00"),
        ],
    )
    def test_format_cost(self, value, expected):
        assert formatCost(value) == expected

    def test_cost_survives_session_bundle(self, chat, qapp, make):
        mid = _turn(chat)
        chat.chatView().setStepStats(
            mid, ElaChatStats(prompt_tokens=10, completion_tokens=5, cost_usd=0.5)
        )
        bundle = chat.chatView().exportSession()
        raw = json.dumps(bundle, allow_nan=False)  # 纯 JSON，可落库
        other = make(ElaChatWidget)
        other.chatView().importSession(json.loads(raw))
        assert other.chatView().message(mid).stats.cost_usd == pytest.approx(0.5)


# ================================================================== 上下文占用
class TestContextUsage:
    """上下文占用圆环：长在**输入区底部工具栏**（与「清空上下文」同排），
    默认常驻、数据与 API 都归 :class:`ElaChatInput`（经 ``chatInput()`` 调用）。"""

    def test_default_visible_without_data(self, chat, qapp):
        """圆环是工具栏默认组件：没喂数据也显示（空底环 0%），与邻居按钮一致。"""
        input_ = chat.chatInput()
        chat.show()
        qapp.processEvents()
        ring = input_.contextUsageWidget()
        assert ring.isVisible()
        assert not ring.isHidden()

        input_.setContextUsage(1000, 0)  # window=0 → 按 0% 显示，不隐藏
        assert ring.isVisible()
        assert input_.contextUsagePercent() == 0

    def test_percent_computed(self, chat):
        chat.chatInput().setContextUsage(124_000, 200_000, 0.0142)
        assert chat.chatInput().contextUsagePercent() == 62
        assert chat.chatInput().contextUsage() == (124_000, 200_000, 0.0142)

    def test_levels(self, chat):
        ring = chat.chatInput().contextUsageWidget()
        chat.chatInput().setContextUsage(50_000, 200_000)
        assert ring.level() == 0
        chat.chatInput().setContextUsage(130_000, 200_000)
        assert ring.level() == 1
        chat.chatInput().setContextUsage(180_000, 200_000)
        assert ring.level() == 2

    def test_percent_clamped(self, chat):
        chat.chatInput().setContextUsage(999_999, 200_000)
        assert chat.chatInput().contextUsagePercent() == 100

    def test_tooltip_content(self, chat):
        chat.chatInput().setContextUsage(124_000, 200_000, 0.0142)
        text = chat.chatInput().contextUsageWidget().tooltipText()
        assert "花费 $0.0142" in text
        assert "62%" in text
        assert "124.0k" in text and "200.0k" in text

    def test_danger_hint_in_tooltip(self, chat):
        chat.chatInput().setContextUsage(190_000, 200_000)
        assert "建议压缩历史" in chat.chatInput().contextUsageWidget().tooltipText()

    def test_no_hint_when_healthy(self, chat):
        chat.chatInput().setContextUsage(10_000, 200_000)
        assert "建议压缩历史" not in chat.chatInput().contextUsageWidget().tooltipText()

    def test_indicator_lives_in_input_toolbar(self, chat, qapp):
        """圆环挂在**输入区底部工具栏**里（与「清空上下文」同排）。

        回归：它曾在 view 右上角当浮层 —— 压住第一条消息的用户头像，而且
        视图未显示时调 ``setContextUsage`` 会卡在 ``(0, 0)``。归位到输入区
        工具栏后由布局定位，与显示顺序无关。
        """
        input_ = chat.chatInput()
        input_.setContextUsage(18_000, 200_000, 0.09)  # 先喂数据、后显示
        chat.resize(700, 420)
        chat.show()
        qapp.processEvents()

        ring = input_.contextUsageWidget()
        assert ring.isVisible()
        # 同一行：圆环与「清空上下文」按钮都挂在工具栏下
        assert input_.toolBar().isAncestorOf(ring)
        assert input_.toolBar().isAncestorOf(input_.clearButton())

    def test_ring_stays_visible_and_resets_to_zero(self, chat, qapp):
        """喂数据 / 归零都只改百分比 —— 圆环始终常驻（换话题后回到 0%）。"""
        input_ = chat.chatInput()
        chat.show()
        qapp.processEvents()
        ring = input_.contextUsageWidget()
        assert ring.isVisible()

        input_.setContextUsage(50_000, 200_000)
        qapp.processEvents()
        assert ring.isVisible() and input_.contextUsagePercent() == 25

        input_.setContextUsage(0, 0)  # 换话题 / 清空后宿主应这样重置
        qapp.processEvents()
        assert ring.isVisible() and input_.contextUsagePercent() == 0

    def test_visibility_api_matches_neighbours(self, chat, qapp):
        """``setContextUsageVisible`` / ``contextUsageVisible``：与上传 / 清空同套。"""
        input_ = chat.chatInput()
        chat.show()
        qapp.processEvents()
        assert input_.contextUsageVisible() is True  # 默认显示

        input_.setContextUsageVisible(False)
        assert input_.contextUsageVisible() is False
        assert input_.contextUsageWidget().isHidden()

        input_.setContextUsage(50_000, 200_000)  # 隐藏态下喂数据不会把它顶出来
        assert input_.contextUsageVisible() is False

        input_.setContextUsageVisible(True)
        assert input_.contextUsageVisible() is True
        assert not input_.contextUsageWidget().isHidden()

    def test_ring_is_clickable(self, chat, qapp):
        """圆环当按钮用：左键点按 → input / widget 的 ``contextUsageClicked``。

        组件不做任何行为（弹什么面板归宿主），且拖出圆环再松开不算点击。
        """
        input_ = chat.chatInput()
        input_.setContextUsage(50_000, 200_000)
        chat.show()
        qapp.processEvents()
        ring = input_.contextUsageWidget()
        got = []
        input_.contextUsageClicked.connect(lambda: got.append("input"))
        chat.contextUsageClicked.connect(lambda: got.append("widget"))

        def click(at: QPoint) -> None:
            ring.mousePressEvent(
                QMouseEvent(
                    QEvent.Type.MouseButtonPress,
                    QPointF(at),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                )
            )
            ring.mouseReleaseEvent(
                QMouseEvent(
                    QEvent.Type.MouseButtonRelease,
                    QPointF(at),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier,
                )
            )

        click(QPoint(11, 11))
        # 两处都要到（投递顺序取决于连接先后：widget 的转发连接建得更早）
        assert sorted(got) == ["input", "widget"]

        # 拖出圆环再松开：不触发（与按钮语义一致）
        got.clear()
        ring.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(QPoint(11, 11)),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        ring.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(QPoint(-5, -5)),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert got == []

    def test_not_part_of_message_persistence(self, chat, qapp, make):
        """占用不是消息数据：不进 exportSession，换会话也不该被带走。"""
        mid = _turn(chat)
        chat.chatInput().setContextUsage(100_000, 200_000, 1.5)
        bundle = chat.chatView().exportSession()
        # 占用不是消息数据：view 段没有它，消息段也没有
        view_options = bundle.get("view", {})
        assert "context_usage" not in view_options
        assert "contextUsage" not in view_options
        assert all(
            not any("context" in key.lower() for key in row)
            for row in bundle.get("messages", [])
        )
        assert chat.chatView().message(mid).stats is None


# ================================================================== 工具状态回归
class TestToolStatusStillSettles:
    def test_failed_tool_not_read_as_retryable_error(self, chat):
        """工具失败由 tool_call.status 承载，不该污染消息级 error_type。"""
        mid = chat.beginAssistantMessage()
        callId = chat.chatView().addToolCall(mid, "shell", "ls")
        chat.chatView().setToolCallResult(mid, callId, "boom", ok=False)
        message = chat.chatView().message(mid)
        assert message.error_type == ""
        assert message.tool_calls[0].status == ElaChatToolStatusType.Error
