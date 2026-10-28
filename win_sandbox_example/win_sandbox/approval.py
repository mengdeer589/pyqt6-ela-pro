"""能力申请 / 人工审批的数据结构与回调协议。

OpenShell 的 advisor 是「agent 提窄规则、人审」。这里做最小版：被策略拒绝时，
宿主弹一个确认框；用户批准后**本次**放行（不记住目录，不扩大范围）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalRequest:
    tool: str
    path: str
    operation: str
    reason: str
    suggestion: str


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    note: str = ""


ApprovalHandler = Callable[[ApprovalRequest], ApprovalDecision]
