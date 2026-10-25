"""气泡审批 / 提问交互与 dock 协调方法组。"""

from __future__ import annotations


from typing import Optional
from uuid import uuid4

from .._internal import is_deleted


from .blocks import (
    PermissionCard,
    PermissionRecord,
)
from .message import (
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatPermission,
    ElaChatPermissionStatusType,
    ElaChatStatusType,
)


class _BubblePermissionMixin:
    """方法组 mixin：状态由 ``ElaChatBubble.__init__`` 建立。"""

    def beginPermission(
        self, request: ElaChatPermission, partId: Optional[str] = None
    ) -> str:
        """登记一次工具审批 / 提问，返回分段 id。

        **交互卡不放在时间线上，而是交给输入区上方的 dock**
        （:attr:`permissionDockRequested` -> :meth:`ElaChatWidget.setDockWidget`）。
        理由：审批是**当前这一步**要用户做的事，摆在历史流里既窄又旧（提问正文
        会被压到折行、候选卡说明被页脚盖住），而且用户正在输入区附近，交互就该
        在那儿。opencode 的 ``session-question-dock`` 就是这个位置。

        时间线上此刻**只登记数据**（``_append_part(part, None)``），等用户答完再
        补一张「记录卡」—— 交互是大控件、记录是小控件，两者的排版需求完全不同，
        所以**不复用同一个 widget**，而是用已落定的 payload 新建一张。

        **只画卡 + 发 ``permissionRequested``，不阻塞。** 在 Qt 里挂起等用户
        点按钮会卡死事件循环；宿主拿到信号后自行决定怎么挂起后端。

        进来的 ``request`` 已经是**落定态**时（宿主重放后端历史、或自己判定完再补
        登记）直接落成时间线上的记录卡：不进 dock、不发 ``permissionRequested``。
        """
        self._ensure_parts_materialized()
        self._mark_generation_started()
        partId = partId or uuid4().hex[:12]
        part = ElaChatPart(
            id=partId,
            kind=ElaChatPartKindType.Permission,
            status=(
                ElaChatStatusType.Streaming
                if request.isPending
                else ElaChatStatusType.Done
            ),
            permission=request,
            step=self._step_index,
        )
        self._append_part(part, None)
        if not request.isPending:
            # 进来的就已经是**落定态**（宿主重放后端历史、或者自己判定完再补登记）
            # —— 直接落成记录卡：不进 dock、不发 ``permissionRequested``。
            # 硬塞进 dock 会得到一张没有按钮的空卡（``_sync_all`` 把动作区和页脚
            # 都藏了），用户看着一个空壳，既不能答也不能关。
            self._settle_permission_card(partId, request)
            return partId
        card = self._create_interactive_card(partId, request)
        self.permissionRequested.emit(str(request.request_id))
        self.permissionDockRequested.emit(card, partId)
        return partId

    def _create_interactive_card(self, partId: str, request: ElaChatPermission):
        """建交互卡并登记（``beginPermission`` 与 ``ensureInteractivePermissionCard`` 共用）。"""
        card = PermissionCard()
        card.replied.connect(
            lambda reply, answer, feedback, pid=partId: self._on_permission_replied(
                pid, reply, answer, feedback
            )
        )
        card.setPermission(request)
        self._interactive_cards[partId] = card
        return card

    def _on_permission_replied(
        self, partId: str, reply: str, answer: str, feedback: str
    ) -> None:
        # 卡片可能活得比气泡久（它被 dock 借用展示），用户点击时气泡可能已经
        # deleteLater 生效 —— 此时碰任何 C++ 成员都会抛 RuntimeError 穿出 Qt
        # 信号槽 = 0xC0000409。删除路径会先 cancelPendingPermissions，这里是兜底。
        if is_deleted(self):
            return
        part = self._find_part(partId)
        if part is None or part.permission is None:
            return
        settled = part.permission.withStatus(reply, answer, feedback)
        self._replace_part(
            partId, part.withPermission(settled).withStatus(ElaChatStatusType.Done)
        )
        self._settle_permission_card(partId, settled)
        self.permissionSettled.emit(partId)
        self.permissionReplied.emit(
            str(settled.request_id), str(reply), str(answer), str(feedback)
        )

    def _settle_permission_card(self, partId: str, settled: ElaChatPermission) -> None:
        """落定：把交互卡收掉，并在时间线的**原位**补一张记录卡。

        必须插回原位而不是 ``addWidget`` 追加 —— 审批之后往往还会来工具调用 /
        正文段，追加会让记录跑到整条消息的最末尾，顺序就错了。
        """
        if is_deleted(self):
            return
        interactive = self._interactive_cards.pop(partId, None)
        if interactive is not None and not is_deleted(interactive):
            interactive.setPermission(settled)  # 让 dock 里那张也显示最终态
            interactive.deleteLater()
        record = self._permission_cards.get(partId)
        if record is not None and not is_deleted(record):
            return  # 已有记录（例如重复落定），不重复建
        record = PermissionRecord(settled)
        self._permission_cards[partId] = record
        self._part_widgets[partId] = record
        if self._parts_layout is not None:
            self._parts_layout.insertWidget(self._part_layout_index(partId), record)
        else:
            record.setParent(self._parts_container or self._content or self)
        record.show()

    def _part_layout_index(self, partId: str) -> int:
        """该 part 在时间线布局里应处的位置。

        取「目标 part 之后第一个真正在 ``_parts_layout`` 里的控件下标」——
        不能按「前面有几个带控件的 part」数：上下文工具分组时 N 个 tool part
        共用同一张分组卡会被重复计数，已停靠底部行的用量徽标也不在时间轴里。
        """
        layout = self._parts_layout
        if layout is None:
            return 0
        found = False
        for part in self._parts:
            if part.id == partId:
                found = True
                continue
            if not found:
                continue
            widget = self._part_widgets.get(part.id)
            if widget is None or is_deleted(widget):
                continue
            index = layout.indexOf(widget)
            if index >= 0:
                return index
        return layout.count()

    def interactivePermissionCard(self, partId: str) -> Optional[PermissionCard]:
        """取仍在 dock 里等待用户操作的交互卡（非 dock 阶段 / 已销毁返回 ``None``）。"""
        card = self._interactive_cards.get(partId)
        if card is None or is_deleted(card):
            return None
        return card

    def ensureInteractivePermissionCard(self, partId: str) -> Optional[PermissionCard]:
        """取交互卡；缺失 / 已被销毁时按 part 的 pending 载荷**重建**。

        dock 撤卡（``clearPermissionDock``）等路径会让卡片先于审批落定被删，
        而 part 仍是 pending —— 重建保证「下一次 promote 顶上来」时还有卡可用，
        且不会把已释放的包装器塞回 dock。
        """
        card = self.interactivePermissionCard(partId)
        if card is not None:
            return card
        part = self._find_part(partId)
        if part is None or part.permission is None or not part.permission.isPending:
            return None
        return self._create_interactive_card(partId, part.permission)

    def resolvePermission(
        self, requestId: str, reply: str, answer: str = "", feedback: str = ""
    ) -> bool:
        """以编程方式落定一次审批（对应卡片按钮）；找不到 / 已落定返回 ``False``。

        已落定的请求**不再改写**（用户的原答案与已发出的信号都不能被二次调用
        覆盖）—— 与 :meth:`cancelPendingPermissions` 的 ``isPending`` 口径一致。
        """
        for part in self._parts:
            if (
                part.kind == ElaChatPartKindType.Permission
                and part.permission is not None
                and part.permission.request_id == requestId
            ):
                if not part.permission.isPending:
                    return False
                self._on_permission_replied(part.id, reply, answer, feedback)
                return True
        return False

    def permissionCard(self, requestId: str) -> Optional[PermissionCard]:
        """按 ``requestId`` 取时间线上的**记录卡**（不存在返回 ``None``）。

        等待用户操作期间的交互卡在 dock 里，不在这里 —— 用
        :meth:`interactivePermissionCard` + partId 取。
        """
        for part in self._parts:
            if (
                part.kind == ElaChatPartKindType.Permission
                and part.permission is not None
                and part.permission.request_id == requestId
            ):
                return self._permission_cards.get(part.id)
        return None

    def pendingPermissions(self) -> list:
        """获取全部**仍在等待用户回复**的审批请求快照。"""
        return [
            part.permission
            for part in self._parts
            if part.kind == ElaChatPartKindType.Permission
            and part.permission is not None
            and part.permission.isPending
        ]

    def pendingPermissionParts(self) -> list:
        """按时间线顺序返回 ``(partId, permission)``（仅仍待答复的）。

        dock 一次只能显示一张卡；这个列表让 :class:`ElaChatWidget` 在当前那张
        落定后**接着把下一张顶上**，而不是把其余的晾在一边点不到。
        """
        return [
            (part.id, part.permission)
            for part in self._parts
            if part.kind == ElaChatPartKindType.Permission
            and part.permission is not None
            and part.permission.isPending
        ]

    def cancelPendingPermissions(self, reason: str = "") -> None:
        """把所有未答复的审批作废（清话题 / 删消息 / 中止回合时必须先调）。

        否则界面上会留下永远点不动、也等不到回复的死卡，用户只能重启。
        这也是 opencode 漏掉的一环：它的 ``Permission.assert`` 在回合中止
        路径上只 ``pending.delete`` 而**不发事件**，客户端要靠重新 sync 才
        清得掉（``permission.ts:254-258``）。
        """
        for part in list(self._parts):
            if (
                part.kind == ElaChatPartKindType.Permission
                and part.permission is not None
                and part.permission.isPending
            ):
                self._on_permission_replied(
                    part.id,
                    ElaChatPermissionStatusType.Cancelled,
                    "",
                    reason or "",
                )
