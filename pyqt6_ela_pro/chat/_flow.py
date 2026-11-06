"""流式回合的共享状态：轮次、推理段、正文首段与计时（binder / journal 共用）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class TurnStreamState:
    """一个回合内与 UI 无关的流式状态。

    binder 用它驱动 view；journal 用它记录事件。两处共用同一套轮次 / 推理 /
    首段正文判定，避免各自维护一份状态机后悄然漂移。
    """

    clock: Callable[[], float]
    open: bool = False
    turn_start: float = 0.0
    round: int = 0
    round_start: float = 0.0
    round_started: bool = False
    reasoning_open: bool = False
    reasoning_start: float = 0.0
    had_text: bool = False
    finish_reason: str = ""
    cancelled: bool = False
    pending_text_lead: List[str] = field(default_factory=list)

    def begin_turn(self) -> None:
        self.open = True
        self.turn_start = self.clock()
        self.round = 0
        self.round_start = self.turn_start
        self.round_started = False
        self.reasoning_open = False
        self.reasoning_start = 0.0
        self.had_text = False
        self.finish_reason = ""
        self.cancelled = False
        self.pending_text_lead.clear()

    def reset(self) -> None:
        self.open = False
        self.turn_start = 0.0
        self.round = 0
        self.round_start = 0.0
        self.round_started = False
        self.reasoning_open = False
        self.reasoning_start = 0.0
        self.had_text = False
        self.finish_reason = ""
        self.cancelled = False
        self.pending_text_lead.clear()

    def begin_round(self) -> None:
        self.round_start = self.clock()
        self.round += 1
        self.round_started = True

    def begin_reasoning(self) -> None:
        if not self.reasoning_open:
            self.reasoning_open = True
            self.reasoning_start = self.clock()

    def end_reasoning(self) -> float:
        """结束当前推理段并返回毫秒数（未开启返回 0）。"""
        if not self.reasoning_open:
            return 0.0
        elapsed = max(0.0, (self.clock() - self.reasoning_start) * 1000.0)
        self.reasoning_open = False
        self.reasoning_start = 0.0
        return elapsed

    def note_content(self, text: str) -> bool:
        """记录一个正文分片；返回它是否包含非空白内容。"""
        if text and text.strip():
            self.had_text = True
            return True
        return False

    def take_text(self, chunk: str) -> Optional[str]:
        """空白分片先缓存；首个非空白分片返回拼接后的正文，否则 ``None``。"""
        if not chunk:
            return None
        if chunk.strip():
            lead = "".join(self.pending_text_lead)
            self.pending_text_lead.clear()
            return lead + chunk
        self.pending_text_lead.append(chunk)
        return None

    def turn_duration_ms(self) -> float:
        if not self.open:
            return 0.0
        return max(0.0, (self.clock() - self.turn_start) * 1000.0)

    def round_duration_ms(self) -> float:
        if not self.round_started:
            return 0.0
        return max(0.0, (self.clock() - self.round_start) * 1000.0)
