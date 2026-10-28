"""用 pyqt6-ela-pro 的 ``ElaConfirmDialog`` 做沙箱审批框。

**必须在 GUI 线程创建**。工具线程调用 ``handler(request)`` 时，通过
``BlockingQueuedConnection`` 把请求投到 GUI 线程，弹阻塞式确认框，
用户点完再把结果带回工具线程。

``parent`` 可以是窗口，也可以是 ``lambda: main_window`` —— 后者允许
「先建 handler / sandbox、后建主窗口」（sandbox 必须早于 agent 创建）。

用法::

    from qt_approval import QtApprovalHandler
    from win_sandbox import ApprovalMode, Sandbox, SandboxPolicy

    approval = QtApprovalHandler(lambda: window)
    box = Sandbox(
        workspace,
        policy=SandboxPolicy(approval_mode=ApprovalMode.ASK),
        approval=approval,
    )
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from pyqt6_ela_pro import ElaConfirmDialog
from win_sandbox import ApprovalDecision, ApprovalRequest

ParentLike = QWidget | Callable[[], QWidget | None] | None


class QtApprovalHandler(QObject):
    """把 ``ApprovalRequest`` 弹成 ``ElaConfirmDialog``。"""

    _request = pyqtSignal(object)

    def __init__(self, parent: ParentLike = None) -> None:
        qobject_parent = parent if isinstance(parent, QWidget) else None
        super().__init__(qobject_parent)
        self._parent_ref: ParentLike = parent
        self._request.connect(
            self._on_request, Qt.ConnectionType.BlockingQueuedConnection
        )

    def setParentWidget(self, parent: ParentLike) -> None:
        self._parent_ref = parent

    def _resolve_parent(self) -> QWidget | None:
        parent = self._parent_ref() if callable(self._parent_ref) else self._parent_ref
        if parent is None:
            parent = QApplication.activeWindow()
        return parent

    def __call__(self, request: ApprovalRequest) -> ApprovalDecision:
        if QThread.currentThread() is self.thread():
            return self._ask(request)
        holder: dict[str, ApprovalDecision] = {}
        self._request.emit((request, holder))
        return holder.get(
            "decision", ApprovalDecision(approved=False, note="no decision")
        )

    def _on_request(self, payload: object) -> None:
        request, holder = payload  # type: ignore[misc]
        holder["decision"] = self._ask(request)

    def _ask(self, request: ApprovalRequest) -> ApprovalDecision:
        parent = self._resolve_parent()
        if parent is None:
            return ApprovalDecision(approved=False, note="no parent window")
        content = (
            f"工具：{request.tool}\n"
            f"操作：{request.operation}\n"
            f"路径：{request.path}\n\n"
            f"{request.suggestion}"
        )
        approved = ElaConfirmDialog.show(parent, "沙箱权限申请", content, "top")
        return ApprovalDecision(approved=approved)
