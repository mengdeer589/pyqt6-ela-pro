"""
会话（话题）快照数据模型（``pyqt6_ela_pro.chat``）。

**多话题由宿主管理**：组件是「单话题视图」，多话题按「一话题一 widget」
放大（``ElaTabBar`` + ``QStackedWidget``，见 ``example/chat_session_page.py``）——
话题的新建 / 归档 / 切换 / 列表 UI 全是宿主的事，组件侧只用
``ElaChatWidget.setCurrentSessionId()` 记一个纯标记。

本模块提供：

- :class:`ElaChatSessionInfo`：话题元数据快照（``id`` / 标题 / 创建时间 /
  消息条数 / 工作目录），成对 ``toDict()`` / ``fromDict()`` 可直接落库；
- :class:`ElaChatSessionStats`：会话级用量汇总（计数 / 当前上下文四路词元 /
  使用率 / 累计成本 / 最后活动 / 工具调用统计 / 思考耗时合计），由
  ``ElaChatView.sessionStats(limit)`` 聚合；
- 整会话（元数据 + 消息 + 视图外观）的导出 / 导入见
  ``ElaChatView.exportSession()`` / ``importSession()`` —— 归档 / 恢复话题
  就是「导出 bundle → 销毁页面；重建页面 → 导入 bundle」。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

from .message import (
    ElaChatPartKindType,
    ElaChatRoleType,
    ElaChatToolStatusType,
    _as_float,
    _as_int,
    _as_str,
)

#: 会话 bundle 格式版本（与消息的 ``SCHEMA_VERSION`` 独立演进）
SESSION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ElaChatSessionInfo:
    """会话（话题）快照。"""

    #: 会话唯一标识
    id: str
    #: 会话标题
    title: str = "新话题"
    #: 创建时间（``time.time()`` 秒）
    created_at: float = 0.0
    #: 消息条数
    message_count: int = 0
    #: 关联工作目录（宿主自定义用途）
    work_dir: str = ""

    def withTitle(self, title: str) -> "ElaChatSessionInfo":
        """返回替换标题后的新快照。"""
        return replace(self, title=title or "新话题")

    def withMessageCount(self, count: int) -> "ElaChatSessionInfo":
        """返回替换消息条数后的新快照。"""
        return replace(self, message_count=_as_int(count))

    # -- 持久化 ------------------------------------------------------------

    def toDict(self) -> dict:
        """转为纯 JSON 字典，可直接 ``json.dumps`` 落库。"""
        return {
            "id": self.id,
            "title": self.title,
            "created_at": _as_float(self.created_at),
            "message_count": _as_int(self.message_count),
            "work_dir": self.work_dir,
        }

    @classmethod
    def fromDict(cls, data) -> "ElaChatSessionInfo":
        """从字典还原（容错：缺字段取默认、多余字段忽略、类型不对就强转）。"""
        if not isinstance(data, dict):
            return cls(id="")
        return cls(
            id=_as_str(data.get("id")),
            title=_as_str(data.get("title"), "新话题"),
            created_at=_as_float(data.get("created_at")),
            message_count=_as_int(data.get("message_count")),
            work_dir=_as_str(data.get("work_dir")),
        )


# ---------------------------------------------------------------------------
# 会话级用量汇总
# ---------------------------------------------------------------------------


def _last_stats(message):
    """消息的「最后一步」统计：优先最后一个 ``stats`` 段；没有段则退回消息级。"""
    for part in reversed(getattr(message, "parts", ()) or ()):
        if getattr(part, "kind", "") == ElaChatPartKindType.Stats:
            stats = getattr(part, "stats", None)
            if stats is not None:
                return stats
    return getattr(message, "stats", None)


def _stats_total(stats) -> int:
    """四路词元和；四路全 0 但服务端给了 ``total_tokens`` 时按它折算（老数据）。

    ``reasoning_tokens`` **不计入** —— 它是 ``completion_tokens`` 的子集
    （见 :class:`~pyqt6_ela_pro.chat.message.ElaChatStats`），再加一遍就是双计。
    """
    context = getattr(stats, "contextTokens", None)
    if callable(context):
        four = max(0, _as_int(context()))
    else:
        four = max(
            0,
            _as_int(getattr(stats, "prompt_tokens", 0))
            + _as_int(getattr(stats, "completion_tokens", 0))
            + _as_int(getattr(stats, "cache_read_tokens", 0))
            + _as_int(getattr(stats, "cache_write_tokens", 0)),
        )
    if four > 0:
        return four
    return max(0, _as_int(getattr(stats, "total_tokens", 0)))


def _message_cost(message) -> float:
    """单条消息的累计花费：优先消息级 ``stats``（= 各步 merge），否则收敛分段。"""
    stats = getattr(message, "stats", None)
    if stats is not None:
        return _as_float(getattr(stats, "cost_usd", 0.0))
    cost = 0.0
    for part in getattr(message, "parts", ()) or ():
        part_stats = getattr(part, "stats", None)
        if part_stats is not None:
            cost += _as_float(getattr(part_stats, "cost_usd", 0.0))
    return cost


def _add_tool_call(call, tool_counts: dict) -> tuple[int, int, int, int]:
    """把一个工具调用计入统计，返回 ``(总数, 失败, 中止, 在途)`` 的增量。"""
    name = _as_str(getattr(call, "name", "")).lower()
    if name:
        tool_counts[name] = tool_counts.get(name, 0) + 1
    status = getattr(call, "status", "")
    return (
        1,
        int(status == ElaChatToolStatusType.Error),
        int(status == ElaChatToolStatusType.Aborted),
        int(
            status
            in (
                ElaChatToolStatusType.Pending,
                ElaChatToolStatusType.Running,
            )
        ),
    )


@dataclass(frozen=True)
class ElaChatSessionStats:
    """会话级用量汇总（对齐 opencode ``getSessionContext`` 的口径）。

    **「当前用量」取最后一条有 tokens 的助手消息的最后一步** —— 多步工具轮里
    就是最近一次 LLM 调用（不是整轮 merge、也不是全会话求和），它回答的是
    「现在上下文占了多少」；累计成本则跨全部消息求和。

    字段对齐 opencode 的 context 面板：

    - 计数：``message_count`` / ``user_messages`` / ``assistant_messages``；
    - 当前上下文：``input_tokens`` / ``output_tokens`` / ``reasoning_tokens``
      / ``cache_read_tokens`` / ``cache_write_tokens`` / ``total_tokens``（四路和）；
    - ``usage_percent``：给了 ``limit``（模型上下文上限）时 = 四路和 / limit
      并夹在 ``0..100``；没给 / 无数据为 ``None``（**不谎报 0%**）；
    - ``total_cost_usd``：全会话累计（各消息 ``stats.cost_usd`` 求和）；
    - ``last_activity``：那条「最后有 tokens 的助手消息」的 ``created_at``
      （对齐 opencode 的 lastActivity）；
    - 工具统计（同一次遍历产出）：``tool_calls`` / ``tool_rounds`` —— 调用总
      次数与**轮数**（有工具调用的步骤数合计，消息内按 ``step`` 去重：一个
      step 并行多个调用算一轮，与 UI「工具面板每步一个」同口径）；
      ``tool_errors`` / ``tool_aborted`` / ``tool_unsettled`` —— 按
      :class:`ElaChatToolStatusType` 分档（``unsettled`` = pending + running；
      ``done`` 可由 ``calls - errors - aborted - unsettled`` 推得）；
      ``tool_counts`` —— 工具名（小写归一）-> 次数（全部状态都计、空名字不计）；
    - ``reasoning_ms``：全会话思考段 ``duration_ms`` 合计。

    会话标题 / 提供商 / 模型 / 创建时间属于**宿主会话元数据**
    （:class:`ElaChatSessionInfo` 或宿主自己的存储），库不推断。
    """

    #: 消息总数（含系统消息）
    message_count: int = 0
    #: 用户消息数
    user_messages: int = 0
    #: 助手消息数
    assistant_messages: int = 0
    #: 最近一次调用的输入词元
    input_tokens: int = 0
    #: 最近一次调用的输出词元（含推理）
    output_tokens: int = 0
    #: 最近一次调用的推理词元
    reasoning_tokens: int = 0
    #: 最近一次调用的缓存读词元
    cache_read_tokens: int = 0
    #: 最近一次调用的缓存写词元
    cache_write_tokens: int = 0
    #: 当前上下文词元总数（四路和）
    total_tokens: int = 0
    #: 上下文占用百分比（``limit <= 0`` 或无数据为 ``None``）
    usage_percent: Optional[int] = None
    #: 全会话累计花费（美元）
    total_cost_usd: float = 0.0
    #: 最后活动时间（最后一条有 tokens 的助手消息的 ``created_at``）
    last_activity: float = 0.0
    #: 工具调用总次数（全部状态合计）
    tool_calls: int = 0
    #: 工具调用轮数：有工具调用的步骤数合计（消息内按 ``step`` 去重）
    tool_rounds: int = 0
    #: 失败的工具调用数（``status == Error``）
    tool_errors: int = 0
    #: 被中止的工具调用数（``status == Aborted``）
    tool_aborted: int = 0
    #: 未落定的工具调用数（``Pending`` + ``Running``）
    tool_unsettled: int = 0
    #: 工具名（小写归一）-> 调用次数（全部状态都计；空名字不计入）
    tool_counts: dict = field(default_factory=dict)
    #: 全会话思考耗时合计（毫秒；各消息思考段 ``duration_ms`` 求和）
    reasoning_ms: float = 0.0

    @classmethod
    def fromMessages(cls, messages, limit: int = 0) -> "ElaChatSessionStats":
        """从消息快照聚合；``limit`` 是模型上下文上限（词元），``> 0`` 才算 ``usage_percent``。"""
        items = list(messages or ())
        user_messages = 0
        assistant_messages = 0
        total_cost = 0.0
        tool_calls = 0
        tool_rounds = 0
        tool_errors = 0
        tool_aborted = 0
        tool_unsettled = 0
        tool_counts: dict = {}
        reasoning_ms = 0.0
        for item in items:
            role = getattr(item, "role", "")
            if role == ElaChatRoleType.User:
                user_messages += 1
            elif role == ElaChatRoleType.Assistant:
                assistant_messages += 1
            total_cost += _message_cost(item)
            steps_with_tools: set = set()
            saw_tool = False
            saw_reasoning = False
            for part in getattr(item, "parts", ()) or ():
                kind = getattr(part, "kind", "")
                if kind == ElaChatPartKindType.Reasoning:
                    saw_reasoning = True
                    reasoning_ms += _as_float(getattr(part, "duration_ms", 0.0))
                elif kind == ElaChatPartKindType.Tool:
                    saw_tool = True
                    call = getattr(part, "tool_call", None)
                    if call is None:
                        # 坏数据（存储里缺 tool_call）：不是一次能数的调用，跳过
                        continue
                    count, errors, aborted, unsettled = _add_tool_call(
                        call, tool_counts
                    )
                    tool_calls += count
                    tool_errors += errors
                    tool_aborted += aborted
                    tool_unsettled += unsettled
                    steps_with_tools.add(max(1, _as_int(getattr(part, "step", 1), 1)))
            tool_rounds += len(steps_with_tools)
            # 旧格式（只有消息级字段、没有分段）：回退到 message.tool_calls /
            # message.reasoning_ms。没有 step 信息，工具按「一条消息一轮」计。
            if not saw_tool:
                legacy_calls = getattr(item, "tool_calls", ()) or ()
                legacy_any = False
                for call in legacy_calls:
                    if call is None:
                        continue
                    legacy_any = True
                    count, errors, aborted, unsettled = _add_tool_call(
                        call, tool_counts
                    )
                    tool_calls += count
                    tool_errors += errors
                    tool_aborted += aborted
                    tool_unsettled += unsettled
                if legacy_any:
                    tool_rounds += 1
            if not saw_reasoning:
                reasoning_ms += _as_float(getattr(item, "reasoning_ms", 0.0))

        latest = None
        latest_message = None
        for item in reversed(items):
            if getattr(item, "role", "") != ElaChatRoleType.Assistant:
                continue
            stats = _last_stats(item)
            if stats is None or _stats_total(stats) <= 0:
                continue
            latest = stats
            latest_message = item
            break

        total = _stats_total(latest) if latest is not None else 0
        window = max(0, _as_int(limit))
        percent = None
        if window > 0 and total > 0:
            percent = max(0, min(100, round(total * 100 / window)))
        return cls(
            message_count=len(items),
            user_messages=user_messages,
            assistant_messages=assistant_messages,
            input_tokens=_as_int(getattr(latest, "prompt_tokens", 0)),
            output_tokens=_as_int(getattr(latest, "completion_tokens", 0)),
            reasoning_tokens=_as_int(getattr(latest, "reasoning_tokens", 0)),
            cache_read_tokens=_as_int(getattr(latest, "cache_read_tokens", 0)),
            cache_write_tokens=_as_int(getattr(latest, "cache_write_tokens", 0)),
            total_tokens=total,
            usage_percent=percent,
            total_cost_usd=total_cost,
            last_activity=_as_float(getattr(latest_message, "created_at", 0.0)),
            tool_calls=tool_calls,
            tool_rounds=tool_rounds,
            tool_errors=tool_errors,
            tool_aborted=tool_aborted,
            tool_unsettled=tool_unsettled,
            tool_counts=tool_counts,
            reasoning_ms=reasoning_ms,
        )
