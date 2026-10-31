"""时间线状态与检索示例页。

通知 / 自动重试 / 活动行 / 密度 / 披露 / 搜索 / 待发送 / 身份与 @ 提及
集中在一个工作区，避免把「结果表达」和「轨迹状态」混在 Agent 工作区里。
"""

from __future__ import annotations

import time
import traceback
from typing import Optional

from PyQt6.QtWidgets import QVBoxLayout

from pyqt6_ela_pro import ElaButton
from pyqt6_ela_pro.chat import (
    ElaChatDetailSection,
    ElaChatMention,
    ElaChatNoticeType,
    ElaChatRoleType,
    ElaChatTimelineDetail,
    ElaChatWidget,
)

from .base_page import ExamplePage
from .chat_demo_kit import note, readonly_chat


class ChatTimelinePage(ExamplePage):
    """时间线状态、密度、披露、搜索与消息表达。"""

    PAGE_TITLE = "时间线与检索"

    def __init__(self, parent=None):
        self._chat: Optional[ElaChatWidget] = None
        self._active_note = None
        self._sample_id: Optional[int] = None
        self._user_id: Optional[int] = None
        self._reasoning_id = ""
        self._pending_id: Optional[int] = None
        self._retry_id: Optional[int] = None
        super().__init__(parent)

    def _addDemoContent(self, main_layout):
        main_layout.addWidget(
            note(
                self,
                "这一页展示「回答之外」的时间线语义：通知、自动重试、运行态、密度、"
                "逐段披露、会话内搜索、待发送消息与消息身份。下面共用一条预填会话。",
            )
        )
        self._chat = readonly_chat(
            self,
            empty_title="时间线与检索",
            empty_subtitle="点下面任意一节，往这条会话上叠加状态。",
        )
        self._chat.setFixedHeight(500)
        main_layout.addWidget(self._chat)
        self._ensure_sample()

        for section in (
            self._section(
                "01. 通知：模型 / agent / 目录 / 中断 / 指令 / 重启",
                self._demo_notices,
                (("插入全部通知", self._demo_notices),),
                "通知是弱化分隔行，不进 message.text；文案与副值由宿主提供。",
            ),
            self._section(
                "02. 自动重试：倒计时 + 立即重试 / 取消",
                self._demo_retry,
                (
                    ("插入 8 秒倒计时", self._demo_retry),
                    ("清除", self._demo_retry_clear),
                ),
                "nextAt 是 epoch 毫秒；卡片每秒刷新，过期后显示「正在重试…」。",
            ),
            self._section(
                "03. 运行态活动行",
                self._demo_activity,
                (
                    ("思考中", lambda: self._set_activity("thinking")),
                    ("执行工具", lambda: self._set_activity("tool")),
                    ("清空", lambda: self._set_activity("")),
                ),
                "底部一行动作文案；binder.setAutoActivity(True) 会自动维护同一接口。",
            ),
            self._section(
                "04. 时间线密度：紧凑 / 标准 / 详细",
                self._demo_density,
                (
                    ("紧凑", lambda: self._apply_density("compact")),
                    ("标准", lambda: self._apply_density("standard")),
                    ("详细", lambda: self._apply_density("detailed")),
                ),
                "六个分区 × hidden / collapsed / expanded；直接改已存在控件，不重建文档。",
            ),
            self._section(
                "05. 逐分段披露",
                self._demo_disclosure,
                (
                    ("展开思考段", lambda: self._set_disclosure(True)),
                    ("收起思考段", lambda: self._set_disclosure(False)),
                ),
                "view.setPartExpanded(partId, on) 覆盖全局密度默认值，随会话导出。",
            ),
            self._section(
                "06. 会话内搜索",
                self._demo_search,
                (
                    ("下一个", lambda: self._chat.chatView().searchNext()),
                    ("上一个", lambda: self._chat.chatView().searchPrev()),
                    ("关闭", lambda: self._chat.chatView().hideSearchBar()),
                ),
                "搜索只扫助手 Text 分段 + 用户文本；Ctrl+F 同入口，命中数有上限。",
            ),
            self._section(
                "07. 待发送消息（插话先上屏）",
                self._demo_pending,
                (
                    ("插入待发送", self._demo_pending),
                    ("标记已送达", self._resolve_pending),
                ),
                "pending 用户消息带「待发送·插话」状态；宿主负责移到队列 / 删除。",
            ),
            self._section(
                "08. 消息身份与 @ 提及",
                self._demo_identity,
                (("插入一条带身份的提问", self._demo_identity),),
                "agent / 模型 / 变体进入用户头与助手 meta；@ 区间由 ElaChatMention 高亮。",
            ),
        ):
            main_layout.addLayout(section)

    # -- 预填 --------------------------------------------------------------

    def _ensure_sample(self) -> None:
        if self._sample_id is not None:
            return
        view = self._chat.chatView()
        user_id = view.addMessage(
            ElaChatRoleType.User, "看 @a.py 里的 alpha 实现，顺便检查 beta。"
        )
        view.setMessageMentions(user_id, [ElaChatMention(start=2, end=7, kind="file")])
        view.setMessageIdentity(user_id, "coder", "deepseek-v4", "high")
        view.setMessageTimestamp(user_id, "14:02")
        self._user_id = user_id

        message_id = view.beginMessage(ElaChatRoleType.Assistant)
        view.setMessageIdentity(message_id, "coder", "deepseek-v4", "high")
        view.setMessageTimestamp(message_id, "14:02")
        view.beginReasoning(message_id)
        view.appendReasoning(message_id, "先定位 alpha 与 beta 的定义，再看调用点。")
        view.endReasoning(message_id, durationMs=900)
        self._reasoning_id = view.message(message_id).parts[0].id
        view.beginText(message_id)
        view.appendText(
            message_id,
            "alpha 在 `a.py` 里是纯函数；beta 需要补一个边界测试。",
        )
        view.endText(message_id)
        call_id = view.addToolCall(
            message_id, "read", '{"path": "a.py"}', toolCallId="read-a"
        )
        view.setToolCallResult(message_id, call_id, "1-40 行", ok=True)
        edit_call = view.addToolCall(
            message_id,
            "edit",
            '{"path": "a.py"}',
            toolCallId="edit-a",
            metadata={
                "files": [
                    {
                        "file": "a.py",
                        "patch": "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n",
                        "additions": 1,
                        "deletions": 1,
                    }
                ]
            },
        )
        view.setToolCallResult(message_id, edit_call, "已修改", ok=True)
        view.endMessage(message_id)
        self._sample_id = message_id

    # -- 各节 --------------------------------------------------------------

    def _demo_notices(self) -> None:
        """通知：六种语义各插一条（只改界面，不进 message.text）。"""
        view = self._chat.chatView()
        message_id = view.beginMessage(ElaChatRoleType.Assistant)
        for notice_type, text, detail in (
            (ElaChatNoticeType.ModelSwitched, "已切换模型", "deepseek-v4"),
            (ElaChatNoticeType.AgentSwitched, "已切换 agent", "coder"),
            (ElaChatNoticeType.LocationSwitched, "工作目录已切换", "src/"),
            (ElaChatNoticeType.InstructionsUpdated, "指令文件已更新", "AGENTS.md"),
            (ElaChatNoticeType.Interrupted, "上一轮已中断", "用户停止"),
            (ElaChatNoticeType.Restart, "进程重启后继续", ""),
        ):
            view.addNotice(message_id, notice_type, text, detail)
        view.beginText(message_id)
        view.appendText(message_id, "六种通知都在这一条消息里。")
        view.endText(message_id)
        view.endMessage(message_id)
        self._note("六种 Notice 已插入：细线 + 弱化文案，不占正文，也不进导出正文。")

    def _demo_retry(self) -> None:
        """自动重试：nextAt 用真实 epoch 毫秒，卡片内置倒计时。"""
        view = self._chat.chatView()
        message_id = view.beginMessage(ElaChatRoleType.Assistant)
        view.beginText(message_id)
        view.appendText(message_id, "上游暂时不可用……")
        view.endText(message_id)
        view.setRetry(
            message_id,
            3,
            "上游限流，稍后自动重试",
            time.time() * 1000 + 8_000,
        )
        view.endMessage(message_id)
        self._retry_id = message_id
        self._note("第 3 次重试 · 8 秒倒计时；倒计时结束显示「正在重试…」")

    def _demo_retry_clear(self) -> None:
        if self._retry_id is not None:
            self._chat.chatView().clearRetry(self._retry_id)
            self._note("已清除重试卡")

    def _demo_activity(self) -> None:
        self._set_activity("thinking")

    def _set_activity(self, kind: str) -> None:
        text = {
            "thinking": "正在思考…",
            "tool": "正在运行命令…",
            "": "",
        }.get(kind, kind)
        self._chat.chatView().setActivity(text)
        self._note(f"活动行：{text or '已清空'}")

    def _demo_density(self) -> None:
        self._apply_density("detailed")

    def _apply_density(self, mode: str) -> None:
        view = self._chat.chatView()
        if mode == "compact":
            detail = ElaChatTimelineDetail(
                thinking=ElaChatDetailSection(placement="hidden"),
                shell=ElaChatDetailSection(placement="collapsed"),
                edit=ElaChatDetailSection(placement="collapsed"),
                subagents=ElaChatDetailSection(placement="collapsed"),
                notices=ElaChatDetailSection(placement="hidden"),
                tools=ElaChatDetailSection(placement="collapsed"),
            )
        elif mode == "detailed":
            detail = ElaChatTimelineDetail(
                thinking=ElaChatDetailSection(placement="expanded"),
                shell=ElaChatDetailSection(placement="expanded"),
                edit=ElaChatDetailSection(placement="expanded"),
                subagents=ElaChatDetailSection(placement="expanded"),
                notices=ElaChatDetailSection(placement="expanded"),
                tools=ElaChatDetailSection(placement="expanded"),
            )
        else:
            detail = ElaChatTimelineDetail()
        view.setTimelineDetail(detail)
        self._note(f"密度：{mode}（思考 / shell / 编辑 / 子代理 / 通知 / 工具）")

    def _demo_disclosure(self) -> None:
        self._set_disclosure(True)

    def _set_disclosure(self, opened: bool) -> None:
        if not self._reasoning_id:
            return
        self._chat.chatView().setPartExpanded(self._reasoning_id, opened)
        self._note("思考段已" + ("展开" if opened else "收起") + "（覆盖全局密度）")

    def _demo_search(self) -> None:
        view = self._chat.chatView()
        count = view.searchText("alpha")
        view.showSearchBar("alpha")
        self._note(f"搜索 alpha：{count} 处命中；Enter / ↓ 下一个，Esc 关闭")

    def _demo_pending(self) -> None:
        view = self._chat.chatView()
        self._pending_id = view.addPendingUserMessage(
            "补充：只改 a.py，不要动 beta。",
            delivery="steer",
        )
        self._note("待发送用户消息已上屏；真实发送由宿主在 drainSteer 时结算")

    def _resolve_pending(self) -> None:
        if self._pending_id is not None:
            self._chat.chatView().resolvePendingUserMessage(self._pending_id, sent=True)
            self._note("待发送消息已标记为已送达")
            self._pending_id = None

    def _demo_identity(self) -> None:
        view = self._chat.chatView()
        message_id = view.addMessage(ElaChatRoleType.User, "看 @a.py 的实现")
        view.setMessageMentions(
            message_id, [ElaChatMention(start=2, end=7, kind="file")]
        )
        view.setMessageIdentity(message_id, "coder", "deepseek-v4", "high")
        self._note("用户头显示 coder · deepseek-v4 (high)，@a.py 高亮且复制为纯文本")

    # -- 小工具 ------------------------------------------------------------

    def _section(self, title, method, buttons, hint):
        box = QVBoxLayout()
        box.setSpacing(6)
        row = self._createHeaderRow(title, method)
        for text, callback in buttons:
            row.addWidget(self._button(text, callback))
        box.addLayout(row)
        label = note(self, hint)
        box.addWidget(label)
        self._active_note = label
        return box

    def _fire(self, callback):
        def run():
            try:
                callback()
            except Exception:
                traceback.print_exc()

        return run

    def _button(self, text, callback):
        button = ElaButton(text, variant="outlined", size="small", parent=self)
        button.setFixedWidth(max(96, 13 * len(text) + 26))
        button.clicked.connect(self._fire(callback))
        return button

    def _note(self, text: str) -> None:
        if self._active_note is not None:
            self._active_note.setText(text)


__all__ = ["ChatTimelinePage"]
