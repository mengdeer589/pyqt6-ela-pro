"""
聊天消息数据模型：不可变快照 + 纯 JSON 持久化（``toDict`` / ``fromDict``）。

助手消息内容以 ``parts`` 时间线为唯一来源，``text`` / ``reasoning`` /
``tool_calls`` / ``stats`` 是 :meth:`ElaChatMessage.withParts` 派生的视图。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import StrEnum, nonmember
from typing import Any, Optional, Tuple

from ._json import loads as _loads
from ._pricing import formatCost

#: 持久化格式版本。字段语义发生不兼容变更时 +1，读取方应按版本分支处理。
SCHEMA_VERSION = 1


def _as_str(value, default: str = "") -> str:
    """容错取字符串（``None`` -> 默认值，其余 ``str()``）。"""
    if value is None:
        return default
    return value if isinstance(value, str) else str(value)


def _as_int(value, default: int = 0) -> int:
    """容错取整数（浮点截断、字符串解析、失败取默认值）。

    必须显式捕获 ``OverflowError``：``int(float('inf'))`` 抛的是它，而它不是
    ``TypeError`` / ``ValueError`` 的子类。
    """
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        try:
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            return default


def _as_float(value, default: float = 0.0) -> float:
    """容错取浮点数。"""
    if value is None or isinstance(value, bool):
        return default
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    # NaN / inf 落库后会毁掉整个文档的可序列化性，直接归零
    return out if out == out and out not in (float("inf"), float("-inf")) else default


def _as_tuple_of(value, factory) -> tuple:
    """容错取元素序列（``None`` -> 空元组，元素逐个转换）。"""
    if not value:
        return ()
    if isinstance(value, (str, bytes, dict)):
        return ()
    try:
        return tuple(factory(item) for item in value)
    except TypeError:
        return ()


def _as_choice(value, allowed, default: str) -> str:
    """容错取枚举字符串（不在白名单内则取默认值）。"""
    text = _as_str(value)
    return text if text in allowed else default


def _as_bool(value, default: bool = False) -> bool:
    """容错取布尔值（``0/1`` 与 ``"true"/"false"`` 按语义解析）。

    ``bool("false")`` 是 ``True``，字符串布尔必须显式解析。
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return default


class ElaChatRoleType(StrEnum):
    """消息角色常量。"""

    #: 用户消息
    User = "user"
    #: 助手（AI）消息
    Assistant = "assistant"
    #: 系统提示消息（居中弱化样式）
    System = "system"

    #: 全部合法角色（非枚举成员）
    All = nonmember((User, Assistant, System))


class ElaChatStatusType(StrEnum):
    """消息状态常量。"""

    #: 正在流式生成
    Streaming = "streaming"
    #: 已提交、等待模型首个输出（TTFT 阶段）；仅头部展示态，数据仍记 ``Streaming``
    Queued = "queued"
    #: 已完成
    Done = "done"
    #: 用户手动停止
    Stopped = "stopped"
    #: 渲染/生成失败
    Error = "error"

    #: 全部合法状态（不含仅展示用的 :data:`Queued`；非枚举成员）
    All = nonmember((Streaming, Done, Stopped, Error))


class ElaChatToolStatusType(StrEnum):
    """工具调用状态常量。"""

    #: 已创建、尚未开始执行（不可展开，对齐 opencode）
    Pending = "pending"
    #: 调用中
    Running = "running"
    #: 调用成功
    Done = "done"
    #: 调用失败
    Error = "error"
    #: 回合被停止 / 中断时仍未完成（不会真的失败，故与 Error 分开）
    Aborted = "aborted"

    #: 已落定（不再显示忙碌环）的状态（非枚举成员）
    Settled = nonmember((Done, Error, Aborted))
    #: 全部合法状态（非枚举成员）
    All = nonmember((Pending, Running, Done, Error, Aborted))


def _format_size(size) -> str:
    """把字节数格式化为人类可读文本。

    容错解析 ``"1.2 MB"`` 这类字符串；解析不出就原样回显（常在绘制路径上调用）。
    """
    if isinstance(size, str):
        text = size.strip()
        # "1.2 MB" -> 1258291.2；纯数字直接用
        try:
            value = float(text)
        except ValueError:
            digits = ""
            for ch in text:
                if ch.isdigit() or ch == ".":
                    digits += ch
                else:
                    break
            try:
                value = float(digits) if digits else 0.0
            except ValueError:
                value = 0.0
            # 带上单位后缀时按 1024 进制还原
            upper = text.upper()
            for unit, factor in (
                ("TB", 1024.0**4),
                ("GB", 1024.0**3),
                ("MB", 1024.0**2),
                ("KB", 1024.0),
            ):
                if unit in upper:
                    value *= factor
                    break
        size = value
    try:
        value = float(max(0.0, float(size)))
    except (TypeError, ValueError, OverflowError):
        return str(size) if size is not None else ""
    if not math.isfinite(value):
        # +inf（如 JSON 的 1e999）：循环会一路除到 TB 输出 "inf TB"，
        # 按「未知大小」处理而不是显示怪值。
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{int(value)} B"


@dataclass(frozen=True)
class ElaChatAttachment:
    """消息附件快照（文件路径由宿主负责解析与拷贝）。"""

    #: 展示名（默认取文件名）
    name: str
    #: 文件路径（可为空，表示仅展示 / 剪贴板图片）
    path: str = ""
    #: 文件大小（字节，0 表示未知）
    size: int = 0
    #: 内容摘要（SHA-1 等，宿主可填；用于粘贴图片去重）
    digest: str = ""
    #: MIME 类型（可选）
    mime: str = ""
    #: 运行时图像（粘贴图片的原图；**不序列化**，落库后为 ``None``）
    image: Optional[Any] = None

    #: 视为图片的扩展名
    ImageSuffixes = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

    @property
    def displaySize(self) -> str:
        """人类可读的大小文本（如 ``12.3 KB``）。"""
        return _format_size(self.size)

    @property
    def isImage(self) -> bool:
        """是否图片附件（按 MIME 或扩展名判断）。"""
        if (self.mime or "").startswith("image/"):
            return True
        name = (self.name or self.path).lower()
        return name.endswith(self.ImageSuffixes)

    def withName(self, name: str) -> "ElaChatAttachment":
        """返回替换展示名后的新快照。"""
        return replace(self, name=name)

    # -- 持久化 ------------------------------------------------------------

    def toDict(self) -> dict:
        """转为纯 JSON 字典。"""
        return {
            "name": self.name,
            "path": self.path,
            "size": _as_int(self.size),
            "digest": self.digest,
            "mime": self.mime,
        }

    @classmethod
    def fromDict(cls, data) -> "ElaChatAttachment":
        """从字典还原（容错：缺字段取默认、多余字段忽略）。"""
        if not isinstance(data, dict):
            return cls(name="")
        return cls(
            name=_as_str(data.get("name")),
            path=_as_str(data.get("path")),
            size=_as_int(data.get("size")),
            digest=_as_str(data.get("digest")),
            mime=_as_str(data.get("mime")),
        )


@dataclass(frozen=True)
class ElaChatToolCall:
    """工具调用快照（工具名称 / 参数 / 结果 / 状态）。"""

    #: 调用 id（宿主生成，用于更新结果）
    id: str
    #: 工具名称
    name: str
    #: 调用参数（原始文本，通常为 JSON 字符串）
    arguments: str = ""
    #: 调用结果文本
    result: str = ""
    #: 状态（见 :class:`ElaChatToolStatusType`）
    status: str = ElaChatToolStatusType.Running
    #: 结构化附加数据（文件变更 / shell 状态 / 诊断等，JSON 安全；库原样交给渲染器）
    metadata: dict = field(default_factory=dict)

    @property
    def isRunning(self) -> bool:
        """是否仍在调用中。"""
        return self.status == ElaChatToolStatusType.Running

    @property
    def isDone(self) -> bool:
        """是否调用成功。"""
        return self.status == ElaChatToolStatusType.Done

    @property
    def isError(self) -> bool:
        """是否调用失败。"""
        return self.status == ElaChatToolStatusType.Error

    def withResult(self, result: str, status: str = ElaChatToolStatusType.Done):
        """返回带结果与状态的新快照。"""
        return replace(self, result=result or "", status=status)

    def withArguments(self, arguments: str):
        """返回替换参数后的新快照。"""
        return replace(self, arguments=arguments or "")

    def withStatus(self, status: str):
        """返回替换状态后的新快照（用于回合终止时结算未完成的调用）。"""
        return replace(self, status=status)

    def withMetadata(self, metadata) -> "ElaChatToolCall":
        """返回替换结构化附加数据后的新快照（非字典按空字典处理）。"""
        return replace(
            self, metadata=dict(metadata) if isinstance(metadata, dict) else {}
        )

    # -- 持久化 ------------------------------------------------------------

    def toDict(self) -> dict:
        """转为纯 JSON 字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
            "result": self.result,
            "status": self.status,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def fromDict(cls, data) -> "ElaChatToolCall":
        """从字典还原（容错）。

        状态不在白名单内也原样保留：存储里的 ``"running"`` 必须保持 running
        （宿主重启后仍可补结果），未知状态宁可原样留着也不要谎报成功。
        """
        if not isinstance(data, dict):
            return cls(id="", name="")
        status = _as_str(data.get("status"), ElaChatToolStatusType.Running)
        return cls(
            id=_as_str(data.get("id")),
            name=_as_str(data.get("name")),
            arguments=_as_str(data.get("arguments")),
            result=_as_str(data.get("result")),
            status=status or ElaChatToolStatusType.Running,
            metadata=dict(data.get("metadata"))
            if isinstance(data.get("metadata"), dict)
            else {},
        )


@dataclass(frozen=True)
class ElaChatStats:
    """消息用量统计快照（单步原始数字，:meth:`merge` 求整轮汇总）。

    四路词元互不重叠：``prompt`` 只含**未命中缓存**的输入，``completion``
    （含 ``reasoning``）/ ``cache_read`` / ``cache_write`` 各占一路。
    """

    #: 输入词元
    prompt_tokens: int = 0
    #: 输出词元（**含推理词元** —— 上游 usage 里 reasoning 通常是 completion 的子集）
    completion_tokens: int = 0
    #: 总词元（服务端给的原始值，不保证等于四路和）
    total_tokens: int = 0
    #: 推理词元（completion 的子集，单独拆出来只为展示 / 统计）
    reasoning_tokens: int = 0
    #: 缓存读词元（命中缓存的输入；旧字段 ``cached_tokens`` 已重构为此名）
    cache_read_tokens: int = 0
    #: 缓存写词元（写入缓存的输入；多数 OpenAI 兼容端点没有这一路，为 0）
    cache_write_tokens: int = 0
    #: 首字耗时（毫秒）
    ttft_ms: float = 0.0
    #: 生成速度（词元/秒）
    tps: float = 0.0
    #: 本步回复耗时（毫秒，0 表示未统计）
    duration_ms: float = 0.0
    #: 本步花费（美元，0 表示未统计）；定价表归宿主，库不内置
    cost_usd: float = 0.0

    @staticmethod
    def merge(items) -> Optional["ElaChatStats"]:
        """把多个步骤用量合并为整轮汇总（``None`` 与空序列返回 ``None``）。

        词元与 ``cost_usd`` 求和，``ttft_ms`` 取首个非零值，``tps`` 按合计输出 /
        合计耗时重算，``duration_ms`` 置 0（整轮耗时由消息级字段承载）。
        """
        values = [item for item in (items or ()) if item is not None]
        if not values:
            return None
        if len(values) == 1:
            return values[0]
        prompt = sum(item.prompt_tokens for item in values)
        completion = sum(item.completion_tokens for item in values)
        total = sum(item.total_tokens for item in values)
        reasoning = sum(item.reasoning_tokens for item in values)
        cache_read = sum(item.cache_read_tokens for item in values)
        cache_write = sum(item.cache_write_tokens for item in values)
        ttft = next((item.ttft_ms for item in values if item.ttft_ms), 0.0)
        duration = sum(item.duration_ms for item in values if item.duration_ms)
        tps = (completion / (duration / 1000.0)) if duration > 0 else 0.0
        return ElaChatStats(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            reasoning_tokens=reasoning,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            ttft_ms=float(ttft),
            tps=float(tps),
            cost_usd=sum(item.cost_usd for item in values),
        )

    def contextTokens(self) -> int:
        """四路词元和（``prompt`` 已不含缓存；``reasoning`` 已含在 completion 里）。"""
        return max(
            0,
            _as_int(self.prompt_tokens)
            + _as_int(self.completion_tokens)
            + _as_int(self.cache_read_tokens)
            + _as_int(self.cache_write_tokens),
        )

    def tooltip(self, durationLabel: str = "耗时") -> str:
        """组合提示文本（花费 / 首字 / 耗时 / 速度 / 缓存）。

        ``durationLabel`` 是耗时字段的前缀（消息级端到端耗时传 ``"端到端"``）。
        """
        # 先洗一遍：后端 usage 是外部数据，``inf`` 直接进 int()/格式化会把
        # Qt 槽链上的调用点炸掉（``int(inf)`` -> OverflowError）。
        cost = _as_float(self.cost_usd)
        ttft = _as_float(self.ttft_ms)
        duration = _as_float(self.duration_ms)
        tps = _as_float(self.tps)
        cache_read = _as_int(self.cache_read_tokens)
        cache_write = _as_int(self.cache_write_tokens)
        parts = []
        if cost:
            parts.append(f"花费 {formatCost(cost)}")
        if ttft:
            parts.append(f"首字 {int(ttft)} ms")
        if duration:
            seconds = max(0.0, duration) / 1000.0
            if seconds < 60:
                parts.append(f"{durationLabel} {seconds:.1f}s")
            else:
                minutes = int(seconds // 60)
                parts.append(f"{durationLabel} {minutes}m {int(seconds % 60)}s")
        if tps:
            parts.append(f"{tps:.1f} 词元/s")
        if cache_read:
            parts.append(f"缓存读 {cache_read} 词元")
        if cache_write:
            parts.append(f"缓存写 {cache_write} 词元")
        return "  ·  ".join(parts)

    # -- 持久化 ------------------------------------------------------------

    def toDict(self) -> dict:
        """转为纯 JSON 字典。"""
        return {
            "prompt_tokens": _as_int(self.prompt_tokens),
            "completion_tokens": _as_int(self.completion_tokens),
            "total_tokens": _as_int(self.total_tokens),
            "reasoning_tokens": _as_int(self.reasoning_tokens),
            "cache_read_tokens": _as_int(self.cache_read_tokens),
            "cache_write_tokens": _as_int(self.cache_write_tokens),
            "ttft_ms": _as_float(self.ttft_ms),
            "tps": _as_float(self.tps),
            "duration_ms": _as_float(self.duration_ms),
            "cost_usd": _as_float(self.cost_usd),
        }

    @classmethod
    def fromDict(cls, data) -> Optional["ElaChatStats"]:
        """从字典还原；``None`` / 非字典返回 ``None``（表示未统计）。"""
        if not isinstance(data, dict):
            return None
        return cls(
            prompt_tokens=_as_int(data.get("prompt_tokens")),
            completion_tokens=_as_int(data.get("completion_tokens")),
            total_tokens=_as_int(data.get("total_tokens")),
            reasoning_tokens=_as_int(data.get("reasoning_tokens")),
            cache_read_tokens=_as_int(data.get("cache_read_tokens")),
            cache_write_tokens=_as_int(data.get("cache_write_tokens")),
            ttft_ms=_as_float(data.get("ttft_ms")),
            tps=_as_float(data.get("tps")),
            duration_ms=_as_float(data.get("duration_ms")),
            cost_usd=_as_float(data.get("cost_usd")),
        )


class ElaChatPartKindType(StrEnum):
    """消息内容分段类型常量（助手消息按步骤有序排列）。"""

    #: 思考段
    Reasoning = "reasoning"
    #: 正文段（Markdown）
    Text = "text"
    #: 工具调用段
    Tool = "tool"
    #: 步骤词元用量段
    Stats = "stats"
    #: 合成上下文段（steer 回执 / 断流续写标记等）；内容装 ``text``，不新增字段
    Synthetic = "synthetic"
    #: 上下文压缩段（summary 在 ``text``，``status`` 记 streaming / done / error）
    Compaction = "compaction"
    #: 工具审批段（等用户确认；结构化数据在 :attr:`ElaChatPart.permission`）
    Permission = "permission"
    #: 时间线通知段（语义标签在 ``notice_type``，文案在 ``text`` / ``detail``）
    Notice = "notice"

    #: 全部合法类型（非枚举成员）
    All = nonmember(
        (
            Reasoning,
            Text,
            Tool,
            Stats,
            Synthetic,
            Compaction,
            Permission,
            Notice,
        )
    )


class ElaChatNoticeType(StrEnum):
    """时间线通知类型（``kind == Notice`` 的语义标签）；库只排版与持久化，不推断语义。"""

    #: 模型切换（``detail`` 放模型名）
    ModelSwitched = "model-switched"
    #: agent 切换（``detail`` 放 agent 名）
    AgentSwitched = "agent-switched"
    #: 工作目录切换（``detail`` 放目录）
    LocationSwitched = "location-switched"
    #: 回合被中断（``detail`` 可放原因）
    Interrupted = "interrupted"
    #: 指令 / 规则文件更新（``detail`` 可放文件列表）
    InstructionsUpdated = "instructions-updated"
    #: 进程重启后继续
    Restart = "restart"

    #: 全部合法类型（非枚举成员）
    All = nonmember(
        (
            ModelSwitched,
            AgentSwitched,
            LocationSwitched,
            Interrupted,
            InstructionsUpdated,
            Restart,
        )
    )


class ElaChatReasoningStyleType(StrEnum):
    """思考展示形态常量（``setReasoningStyle`` 取值）。"""

    #: 可折叠思考块（默认）
    Collapse = "collapse"
    #: 内联思考（muted Markdown + 思考行）
    Inline = "inline"

    #: 全部合法形态（非枚举成员）
    All = nonmember((Collapse, Inline))


class ElaChatPermissionStatusType(StrEnum):
    """工具审批状态常量。"""

    #: 等待用户选择
    Pending = "pending"
    #: 允许这一次
    Allowed = "allowed"
    #: 允许并记住规则（后续同类自动放行）
    Always = "always"
    #: 拒绝（``feedback`` 记录用户填的原因，会回传给宿主）
    Rejected = "rejected"
    #: 会话结束 / 消息被删导致未答复就作废
    Cancelled = "cancelled"

    #: 已落定（不再是「等用户」状态；非枚举成员）
    Settled = nonmember((Allowed, Always, Rejected, Cancelled))
    #: 全部合法状态（非枚举成员）
    All = nonmember((Pending, Allowed, Always, Rejected, Cancelled))


@dataclass(frozen=True)
class ElaChatOption:
    """一个候选项（标题 + 一行说明）；描述不是可选项，缺了用户只能靠猜。"""

    #: 展示文本（也是回传的标识 —— opencode 的 ``value`` 恒等于 ``label``）
    label: str
    #: 说明文字（解释这个选项意味着什么）
    description: str = ""

    def toDict(self) -> dict:
        """转为纯 JSON 字典。"""
        return {"label": _as_str(self.label), "description": _as_str(self.description)}

    @classmethod
    def fromDict(cls, data) -> Optional["ElaChatOption"]:
        """从字典还原；``None`` / 非字典 / 空 label 返回 ``None``。"""
        if not isinstance(data, dict):
            return None
        label = _as_str(data.get("label"))
        return (
            cls(label=label, description=_as_str(data.get("description")))
            if label
            else None
        )


@dataclass(frozen=True)
class ElaChatQuestion:
    """一道待用户回答的问题（``key`` + 短标签 + 正文 + 候选项）。

    模型一次可问多道题，组件做成逐题向导（一次只展示一道、每题独立草稿）。
    """

    #: 宿主侧的关联键；回传的答案以它为键
    key: str
    #: 短标签（对应 ``Form.Field.title``；opencode 的 ``header``，≤30 字）
    header: str = ""
    #: 完整问题正文（对应 ``Form.Field.description``；opencode 的 ``question``）
    question: str = ""
    #: 候选项
    options: Tuple[ElaChatOption, ...] = field(default_factory=tuple)
    #: 是否允许多选（``True`` -> checkbox，可累积；``False`` -> radio 互斥）
    multiple: bool = False
    #: 是否追加「输入自己的答案」行（opencode 的 ``custom``，那边恒为 True）
    custom: bool = True

    @property
    def isMultiple(self) -> bool:
        """别名（``multiple`` 字段撞 ``QWidget`` 语义，调用处读起来更清楚）。"""
        return bool(self.multiple)

    def toDict(self) -> dict:
        """转为纯 JSON 字典。"""
        return {
            "key": _as_str(self.key),
            "header": _as_str(self.header),
            "question": _as_str(self.question),
            "options": [item.toDict() for item in self.options],
            "multiple": bool(self.multiple),
            "custom": bool(self.custom),
        }

    @classmethod
    def fromDict(cls, data) -> Optional["ElaChatQuestion"]:
        """从字典还原；``None`` / 非字典 / 空 key 返回 ``None``。"""
        if not isinstance(data, dict):
            return None
        key = _as_str(data.get("key"))
        if not key:
            return None
        return cls(
            key=key,
            header=_as_str(data.get("header")),
            question=_as_str(data.get("question")),
            options=_as_tuple_of(data.get("options"), ElaChatOption.fromDict),
            multiple=_as_bool(data.get("multiple"), False),
            # 缺省 True：与 opencode 一致（模型无法关掉「自己写」那一行）
            custom=_as_bool(data.get("custom"), True),
        )


@dataclass(frozen=True)
class ElaChatPermission:
    """一次工具执行审批请求（``kind == Permission`` 的分段载荷）。

    库只画卡 + 收集回复 + 发信号，绝不阻塞等待（Qt 里挂起会卡死事件循环）。
    ``questions`` 为空 = 批准型，非空 = 问答型（逐题向导）。
    """

    #: 请求 id（宿主与组件之间的关联键；同一条消息内唯一）
    request_id: str
    #: 动作名（``"edit"`` / ``"shell"`` / ``"question"`` ...），宿主据此选规则
    action: str
    #: 受影响资源（文件路径 / 命令模式等），原样交宿主做「始终允许」匹配
    resources: Tuple[str, ...] = field(default_factory=tuple)
    #: 卡片标题（空则由组件按 action 生成）
    title: str = ""
    #: 展开显示的详情（diff / 命令行 / 问题描述）
    detail: str = ""
    #: 待回答的问题（**非空 = 问答型**；空 = 批准型，见类 docstring）
    questions: Tuple[ElaChatQuestion, ...] = field(default_factory=tuple)
    #: 状态（见 :class:`ElaChatPermissionStatusType`）
    status: str = ElaChatPermissionStatusType.Pending
    #: 用户选择 / 填写的答案（批准型为空；问答型是 JSON 串）
    answer: str = ""
    #: 拒绝时填的原因（回传给宿主，宿主可据此让模型换做法）
    feedback: str = ""

    @property
    def isPending(self) -> bool:
        """是否仍在等待用户回复。"""
        return self.status == ElaChatPermissionStatusType.Pending

    @property
    def isQuestion(self) -> bool:
        """是否问答型（由 :attr:`questions` 是否为空决定，勿另设标志位）。"""
        return bool(self.questions)

    def parsedAnswer(self) -> dict:
        """:attr:`answer` 的结构化形式（``{key: str | [str, ...]}``）。

        批准型 / 未答复 / 非法 JSON 一律返回空字典 —— 这个方法只做**解析**，
        不解释语义。
        """
        if not self.answer:
            return {}
        try:
            data = _loads(self.answer)
        except (ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def withStatus(
        self, status: str, answer: str = "", feedback: str = ""
    ) -> "ElaChatPermission":
        """返回替换状态后的新快照（非法状态回落 ``Pending``）。"""
        return replace(
            self,
            status=(
                status
                if status in ElaChatPermissionStatusType.All
                else ElaChatPermissionStatusType.Pending
            ),
            answer=answer or "",
            feedback=feedback or "",
        )

    def toDict(self) -> dict:
        """转为纯 JSON 字典。"""
        return {
            "request_id": _as_str(self.request_id),
            "action": _as_str(self.action),
            "resources": [_as_str(item) for item in self.resources],
            "title": _as_str(self.title),
            "detail": _as_str(self.detail),
            "questions": [item.toDict() for item in self.questions],
            "status": _as_choice(
                self.status,
                ElaChatPermissionStatusType.All,
                ElaChatPermissionStatusType.Pending,
            ),
            "answer": _as_str(self.answer),
            "feedback": _as_str(self.feedback),
        }

    @classmethod
    def fromDict(cls, data) -> Optional["ElaChatPermission"]:
        """从字典还原；``None`` / 非字典 / **空 ``request_id``** 返回 ``None``。

        ``request_id`` 是宿主与组件的关联键，空的没法作答，宁可整条丢掉。
        """
        if not isinstance(data, dict):
            return None
        request_id = _as_str(data.get("request_id"))
        if not request_id:
            return None
        return cls(
            request_id=request_id,
            action=_as_str(data.get("action")),
            resources=_as_tuple_of(data.get("resources"), _as_str),
            title=_as_str(data.get("title")),
            detail=_as_str(data.get("detail")),
            questions=_as_tuple_of(data.get("questions"), ElaChatQuestion.fromDict),
            status=_as_choice(
                data.get("status"),
                ElaChatPermissionStatusType.All,
                ElaChatPermissionStatusType.Pending,
            ),
            answer=_as_str(data.get("answer")),
            feedback=_as_str(data.get("feedback")),
        )


@dataclass(frozen=True)
class ElaChatMention:
    """用户文本里的一个 ``@`` 引用区间（用于消息内高亮）。

    偏移量按 Python ``str`` 下标计、**左闭右开**，与编辑器里的选区一致。
    越界 / 反序的区间在渲染时直接跳过（宿主数据脏了不该让整条消息消失）。
    """

    #: 起始下标（含）
    start: int = 0
    #: 结束下标（不含）
    end: int = 0
    #: 类型（``file`` / ``agent`` / 其它宿主自定义）
    kind: str = ""

    @property
    def isValid(self) -> bool:
        """区间是否有效（非负且 start < end）。"""
        return 0 <= self.start < self.end

    def toDict(self) -> dict:
        """转为纯 JSON 字典。"""
        return {
            "start": _as_int(self.start),
            "end": _as_int(self.end),
            "kind": _as_str(self.kind),
        }

    @classmethod
    def fromDict(cls, data) -> Optional["ElaChatMention"]:
        """从字典还原；``None`` / 非字典返回 ``None``。"""
        if not isinstance(data, dict):
            return None
        return cls(
            start=_as_int(data.get("start")),
            end=_as_int(data.get("end")),
            kind=_as_str(data.get("kind")),
        )


@dataclass(frozen=True)
class ElaChatPart:
    """助手消息的内容分段快照（按加入顺序构成消息时间线）。"""

    #: 分段唯一标识
    id: str
    #: 分段类型（见 :class:`ElaChatPartKindType`）
    kind: str
    #: 文本内容（思考 / 正文 / 压缩摘要 / 插话回执）
    text: str = ""
    #: 状态（见 :class:`ElaChatStatusType`）
    status: str = ElaChatStatusType.Done
    #: 工具调用快照（``kind == Tool``）
    tool_call: Optional[ElaChatToolCall] = None
    #: 步骤词元用量（``kind == Stats``）
    stats: Optional[ElaChatStats] = None
    #: 审批请求（``kind == Permission``）
    permission: Optional[ElaChatPermission] = None
    #: 思考耗时（毫秒，``kind == Reasoning``）
    duration_ms: float = 0.0
    #: 所属步骤序号（从 1 开始）
    step: int = 1
    #: 通知类型（``kind == Notice``，见 :class:`ElaChatNoticeType`）
    notice_type: str = ""
    #: 通知副值（模型名 / 目录 / 原因等；``kind == Notice``）
    detail: str = ""
    #: 压缩掉的历史条数（``kind == Compaction``；``0`` = 不知道，不是「压了 0 条」）
    history_count: int = 0
    #: 截止时间（epoch 毫秒；``kind == Notice`` 的 Retry 预留，暂未使用）
    deadline: float = 0.0

    def withText(self, text: str) -> "ElaChatPart":
        """返回替换文本后的新快照。"""
        return replace(self, text=text)

    def withStatus(self, status: str) -> "ElaChatPart":
        """返回替换状态后的新快照。"""
        return replace(self, status=status)

    def withToolCall(self, toolCall: ElaChatToolCall) -> "ElaChatPart":
        """返回替换工具调用后的新快照。"""
        return replace(self, tool_call=toolCall)

    def withStats(self, stats: Optional[ElaChatStats]) -> "ElaChatPart":
        """返回替换用量后的新快照。"""
        return replace(self, stats=stats)

    def withPermission(self, permission: Optional[ElaChatPermission]) -> "ElaChatPart":
        """返回替换审批请求后的新快照。"""
        return replace(self, permission=permission)

    def withDuration(self, durationMs: float) -> "ElaChatPart":
        """返回替换耗时后的新快照。"""
        return replace(self, duration_ms=float(durationMs or 0.0))

    def withHistoryCount(self, count: int) -> "ElaChatPart":
        """返回替换压缩历史条数后的新快照。"""
        return replace(self, history_count=max(0, _as_int(count)))

    # -- 持久化 ------------------------------------------------------------

    def toDict(self) -> dict:
        """转为纯 JSON 字典。"""
        return {
            "id": _as_str(self.id),
            "kind": _as_str(self.kind),
            "text": self.text,
            "status": self.status,
            "tool_call": self.tool_call.toDict() if self.tool_call else None,
            "stats": self.stats.toDict() if self.stats else None,
            "permission": self.permission.toDict() if self.permission else None,
            "duration_ms": _as_float(self.duration_ms),
            "step": _as_int(self.step, 1),
            "notice_type": _as_str(self.notice_type),
            "detail": _as_str(self.detail),
            "history_count": max(0, _as_int(self.history_count)),
            "deadline": _as_float(self.deadline),
        }

    @classmethod
    def fromDict(cls, data) -> Optional["ElaChatPart"]:
        """从字典还原；``None`` / 非字典 / **未知 ``kind``** 返回 ``None``。

        未知 ``kind`` 必须丢弃而不是回落成 ``Text``：把新类型的结构标记当正文
        渲染远比少渲染一段糟糕。
        """
        if not isinstance(data, dict):
            return None
        kind = _as_str(data.get("kind"))
        if kind not in ElaChatPartKindType.All:
            return None
        call = data.get("tool_call")
        return cls(
            id=_as_str(data.get("id")),
            kind=kind,
            text=_as_str(data.get("text")),
            status=_as_choice(
                data.get("status"), ElaChatStatusType.All, ElaChatStatusType.Done
            ),
            tool_call=ElaChatToolCall.fromDict(call)
            if isinstance(call, dict)
            else None,
            stats=ElaChatStats.fromDict(data.get("stats")),
            permission=ElaChatPermission.fromDict(data.get("permission")),
            duration_ms=_as_float(data.get("duration_ms")),
            step=max(1, _as_int(data.get("step"), 1)),
            notice_type=_as_str(data.get("notice_type")),
            detail=_as_str(data.get("detail")),
            history_count=max(0, _as_int(data.get("history_count"))),
            deadline=_as_float(data.get("deadline")),
        )


@dataclass(frozen=True)
class ElaChatMessage:
    """不可变消息快照（``messages()`` 返回值，修改请用组件方法）。

    助手消息以 ``parts`` 为唯一内容来源，``text`` / ``reasoning`` /
    ``tool_calls`` / ``stats`` 由 :meth:`withParts` 派生；流式期间在途分片只
    存在气泡缓冲里，所以派生字段在回合结束前是空串。
    """

    #: 消息序号（同一会话内自增，从 1 开始）
    id: int
    #: 角色（见 :class:`ElaChatRoleType`）
    role: str
    #: 消息文本（助手消息为 Markdown 源）
    text: str = ""
    #: 状态（见 :class:`ElaChatStatusType`）
    status: str = ElaChatStatusType.Done
    #: 创建时间（``time.time()`` 秒）
    created_at: float = 0.0
    #: 显示名（用户 / 助手 / 模型名），空则用角色默认
    title: str = ""
    #: agent 名（历史消息的「谁在说话」；空则不显示）
    agent: str = ""
    #: 模型名（历史消息的「哪个模型」；空则不显示）
    model: str = ""
    #: 模型变体（思考强度 / 档位；空则不显示）
    model_variant: str = ""
    #: 显示用时间文本（由宿主提供，空则不显示）
    timestamp: str = ""
    #: 投递方式（``steer`` = 插话；空 = 普通 / 队列；仅用户消息有意义）
    delivery: str = ""
    #: 用户文本里的 @ 引用区间（仅用户消息；空 = 不做高亮）
    mentions: Tuple[ElaChatMention, ...] = field(default_factory=tuple)
    #: 思考过程文本（思考层）
    reasoning: str = ""
    #: 思考耗时（毫秒，0 表示未统计）
    reasoning_ms: float = 0.0
    #: 本轮总耗时（毫秒，0 表示未统计）
    duration_ms: float = 0.0
    #: 工具调用快照（工具层）
    tool_calls: Tuple[ElaChatToolCall, ...] = field(default_factory=tuple)
    #: 附件快照（附件层）
    attachments: Tuple[ElaChatAttachment, ...] = field(default_factory=tuple)
    #: 用量统计（底部层，各步求和汇总，``None`` 表示未统计）
    stats: Optional[ElaChatStats] = None
    #: 错误文本（错误卡片，空表示无错误）
    error: str = ""
    #: 错误类型（``binder.error(errorType, message)`` 的第一个参数；空表示未知）
    error_type: str = ""
    #: 助手消息内容分段（按加入顺序；用户 / 系统消息为空，文本见 ``text``）
    parts: Tuple[ElaChatPart, ...] = field(default_factory=tuple)

    # -- 分段查询 ----------------------------------------------------------

    def part(self, partId: str) -> Optional[ElaChatPart]:
        """按 id 查询分段快照（不存在返回 ``None``）。"""
        for item in self.parts:
            if item.id == partId:
                return item
        return None

    def partsOfKind(self, kind: str) -> list:
        """按类型查询分段快照列表。"""
        return [item for item in self.parts if item.kind == kind]

    def stepParts(self, step: int) -> list:
        """查询指定步骤的全部分段。"""
        return [item for item in self.parts if item.step == int(step)]

    @property
    def stepCount(self) -> int:
        """步骤数量（无分段时为 0）。"""
        return max((item.step for item in self.parts), default=0)

    def withParts(self, parts) -> "ElaChatMessage":
        """替换内容分段并重算派生字段（text / reasoning / tool_calls / stats）。

        ``Synthetic`` / ``Compaction`` / ``Permission`` 段的 ``text`` 不并入
        ``text`` —— 它们不是模型正文。
        """
        parts = tuple(parts or ())
        text = "".join(
            item.text for item in parts if item.kind == ElaChatPartKindType.Text
        )
        reasoning = "".join(
            item.text for item in parts if item.kind == ElaChatPartKindType.Reasoning
        )
        reasoningMs = sum(
            item.duration_ms
            for item in parts
            if item.kind == ElaChatPartKindType.Reasoning
        )
        toolCalls = tuple(
            item.tool_call
            for item in parts
            if item.kind == ElaChatPartKindType.Tool and item.tool_call is not None
        )
        stats = ElaChatStats.merge(
            item.stats for item in parts if item.stats is not None
        )
        return replace(
            self,
            parts=parts,
            text=text,
            reasoning=reasoning,
            reasoning_ms=reasoningMs,
            tool_calls=toolCalls,
            stats=stats,
        )

    @property
    def isUser(self) -> bool:
        """是否用户消息。"""
        return self.role == ElaChatRoleType.User

    @property
    def isAssistant(self) -> bool:
        """是否助手消息。"""
        return self.role == ElaChatRoleType.Assistant

    @property
    def isSystem(self) -> bool:
        """是否系统消息。"""
        return self.role == ElaChatRoleType.System

    @property
    def isStreaming(self) -> bool:
        """是否仍在流式生成。"""
        return self.status == ElaChatStatusType.Streaming

    @property
    def isInterrupted(self) -> bool:
        """是否被用户停止（用于 meta 行的「已中断」标记）。"""
        return self.status == ElaChatStatusType.Stopped

    def withText(self, text: str) -> "ElaChatMessage":
        """返回替换文本后的新快照。"""
        return replace(self, text=text)

    def withStatus(self, status: str) -> "ElaChatMessage":
        """返回替换状态后的新快照。"""
        return replace(self, status=status)

    def withTitle(self, title: str) -> "ElaChatMessage":
        """返回替换显示名后的新快照。"""
        return replace(self, title=title or "")

    def withIdentity(
        self,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        modelVariant: Optional[str] = None,
    ) -> "ElaChatMessage":
        """返回替换 agent / 模型 / 变体后的新快照（``None`` 表示保持原值）。"""
        return replace(
            self,
            agent=self.agent if agent is None else str(agent or ""),
            model=self.model if model is None else str(model or ""),
            model_variant=(
                self.model_variant if modelVariant is None else str(modelVariant or "")
            ),
        )

    def withMentions(self, mentions) -> "ElaChatMessage":
        """返回替换 @ 引用区间后的新快照（只保留有效区间）。"""
        items = []
        for item in mentions or ():
            value = (
                item
                if isinstance(item, ElaChatMention)
                else ElaChatMention.fromDict(item)
            )
            if value is not None and value.isValid:
                items.append(value)
        return replace(self, mentions=tuple(items))

    def withDelivery(self, delivery: str) -> "ElaChatMessage":
        """返回替换投递方式后的新快照。"""
        return replace(self, delivery=_as_str(delivery))

    def withTimestamp(self, timestamp: str) -> "ElaChatMessage":
        """返回替换时间文本后的新快照。"""
        return replace(self, timestamp=timestamp or "")

    def withReasoning(
        self, reasoning: str, reasoningMs: Optional[float] = None
    ) -> "ElaChatMessage":
        """返回替换思考层后的新快照。"""
        if reasoningMs is None:
            return replace(self, reasoning=reasoning or "")
        return replace(self, reasoning=reasoning or "", reasoning_ms=float(reasoningMs))

    def withToolCalls(self, toolCalls) -> "ElaChatMessage":
        """返回替换工具层后的新快照。"""
        return replace(self, tool_calls=tuple(toolCalls or ()))

    def withToolCall(self, toolCall: ElaChatToolCall) -> "ElaChatMessage":
        """按 id 合并单个工具调用（不存在则追加）。"""
        calls = list(self.tool_calls)
        for index, call in enumerate(calls):
            if call.id == toolCall.id:
                calls[index] = toolCall
                break
        else:
            calls.append(toolCall)
        return replace(self, tool_calls=tuple(calls))

    def withAttachments(self, attachments) -> "ElaChatMessage":
        """返回替换附件层后的新快照。"""
        return replace(self, attachments=tuple(attachments or ()))

    def withStats(self, stats: Optional[ElaChatStats]) -> "ElaChatMessage":
        """返回替换用量统计后的新快照。"""
        return replace(self, stats=stats)

    def withDuration(self, durationMs: float) -> "ElaChatMessage":
        """返回替换总耗时后的新快照。"""
        return replace(self, duration_ms=float(durationMs or 0.0))

    def withError(
        self, error: str, errorType: Optional[str] = None
    ) -> "ElaChatMessage":
        """返回替换错误文本后的新快照（``errorType=None`` 表示保持原值）。"""
        if errorType is None:
            return replace(self, error=error or "")
        return replace(self, error=error or "", error_type=str(errorType or ""))

    # -- 持久化 ------------------------------------------------------------

    @staticmethod
    def schemaOf(data) -> int:
        """读取字典里的格式版本（非字典 / 无版本返回 0）。"""
        if not isinstance(data, dict):
            return 0
        return _as_int(data.get("schema"), 0)

    def toDict(self) -> dict:
        """转为纯 JSON 字典，可直接 ``json.dumps`` 落库。

        ``parts`` 是助手消息的唯一真相，其余派生字段只是冗余写出来方便不装
        本库的读取方；读取时一律以 ``parts`` 重算。
        """
        return {
            "schema": SCHEMA_VERSION,
            "id": _as_int(self.id),
            "role": self.role,
            "text": self.text,
            "status": self.status,
            "created_at": _as_float(self.created_at),
            "title": self.title,
            "agent": self.agent,
            "model": self.model,
            "model_variant": self.model_variant,
            "timestamp": self.timestamp,
            "delivery": self.delivery,
            "mentions": [item.toDict() for item in self.mentions],
            "reasoning": self.reasoning,
            "reasoning_ms": _as_float(self.reasoning_ms),
            "duration_ms": _as_float(self.duration_ms),
            "tool_calls": [call.toDict() for call in self.tool_calls],
            "attachments": [item.toDict() for item in self.attachments],
            "stats": self.stats.toDict() if self.stats else None,
            "error": self.error,
            "error_type": self.error_type,
            "parts": [part.toDict() for part in self.parts],
        }

    @classmethod
    def fromDict(cls, data) -> "ElaChatMessage":
        """从字典还原（容错：缺字段取默认、多余字段忽略、类型不对就强转）。

        助手消息的派生字段不信存储里的值，一律用 ``parts`` 经 :meth:`withParts`
        重算，避免派生字段与分段互相矛盾。
        """
        if not isinstance(data, dict):
            return cls(id=0, role=ElaChatRoleType.Assistant)
        base = cls(
            id=_as_int(data.get("id")),
            role=_as_choice(
                data.get("role"), ElaChatRoleType.All, ElaChatRoleType.Assistant
            ),
            text=_as_str(data.get("text")),
            status=_as_choice(
                data.get("status"), ElaChatStatusType.All, ElaChatStatusType.Done
            ),
            created_at=_as_float(data.get("created_at")),
            title=_as_str(data.get("title")),
            agent=_as_str(data.get("agent")),
            model=_as_str(data.get("model")),
            model_variant=_as_str(data.get("model_variant")),
            timestamp=_as_str(data.get("timestamp")),
            delivery=_as_str(data.get("delivery")),
            mentions=tuple(
                item
                for item in _as_tuple_of(data.get("mentions"), ElaChatMention.fromDict)
                if item is not None and item.isValid
            ),
            duration_ms=_as_float(data.get("duration_ms")),
            attachments=_as_tuple_of(
                data.get("attachments"), ElaChatAttachment.fromDict
            ),
            error=_as_str(data.get("error")),
            error_type=_as_str(data.get("error_type")),
        )
        parts = tuple(
            part
            for part in _as_tuple_of(data.get("parts"), ElaChatPart.fromDict)
            if part is not None
        )
        if parts:
            # 有分段 -> 派生字段全部由 parts 重算
            return base.withParts(parts)
        # 无分段（用户 / 系统消息，或老版本只有纯文本）：信存储的派生字段
        return replace(
            base,
            reasoning=_as_str(data.get("reasoning")),
            reasoning_ms=_as_float(data.get("reasoning_ms")),
            tool_calls=_as_tuple_of(data.get("tool_calls"), ElaChatToolCall.fromDict),
            stats=ElaChatStats.fromDict(data.get("stats")),
        )

    def withId(self, messageId: int) -> "ElaChatMessage":
        """返回替换消息序号后的新快照（恢复时重映射 id 用；非法值归 0）。"""
        return replace(self, id=_as_int(messageId))
