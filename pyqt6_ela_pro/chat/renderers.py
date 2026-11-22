"""工具结果富渲染注册表：宿主接管 ``ToolCallCard`` 的内容区。

渲染器必须持 Python 引用；细节见 ``docs/chat.md``。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

from . import _json

__all__ = [
    "ToolRenderContext",
    "ToolRendererFactory",
    "ToolSubtitleFn",
    "clearToolRenderers",
    "contextToolLabel",
    "contextTools",
    "isContextTool",
    "registerContextTool",
    "registerToolRenderer",
    "resetContextTools",
    "toolRenderer",
    "toolRendererGroupable",
    "toolRendererNames",
    "toolRendererSubtitle",
    "unregisterToolRenderer",
]


#: 默认上下文工具；值是分组摘要里的量词。
_DEFAULT_CONTEXT_TOOLS = {
    "read": "个文件",
    "glob": "次查找",
    "grep": "次搜索",
    "list": "次列目录",
}

#: 当前上下文工具（内置 + 宿主注册），保持插入顺序。
_CONTEXT_TOOLS: dict[str, str] = dict(_DEFAULT_CONTEXT_TOOLS)


def contextTools() -> tuple[str, ...]:
    """当前参与上下文分组的工具名（内置 + 宿主注册）。"""
    return tuple(_CONTEXT_TOOLS)


def isContextTool(name: str) -> bool:
    """工具名是否在上下文分组集合中。"""
    return str(name or "").strip().lower() in _CONTEXT_TOOLS


def registerContextTool(name: str, *, label: str = "", enabled: bool = True) -> None:
    """增删上下文分组工具；``label`` 是摘要量词（如 ``"个文件"``）。"""
    key = str(name or "").strip().lower()
    if not key:
        raise ValueError("registerContextTool: name 不能为空")
    if enabled:
        _CONTEXT_TOOLS[key] = str(label or "")
    else:
        _CONTEXT_TOOLS.pop(key, None)


def contextToolLabel(name: str) -> str:
    """工具在分组摘要里的量词；未注册返回空串。"""
    return _CONTEXT_TOOLS.get(str(name or "").strip().lower(), "")


def resetContextTools() -> None:
    """恢复内置上下文工具（只给测试隔离用）。"""
    _CONTEXT_TOOLS.clear()
    _CONTEXT_TOOLS.update(_DEFAULT_CONTEXT_TOOLS)


@dataclass(frozen=True)
class ToolRenderContext:
    """建卡那一刻的**不可变快照**（不持有任何控件引用）。"""

    #: 所属消息 id
    messageId: int
    #: 工具调用 id（同一 id 的重复上报会更新同一张卡）
    toolCallId: str
    #: 工具名（注册时的键）
    name: str
    #: 原始参数文本（JSON 串；解析用 :meth:`parsedArguments`）
    arguments: str
    #: 当前结果文本
    result: str
    #: 当前状态（见 :class:`~pyqt6_ela_pro.chat.message.ElaChatToolStatusType`）
    status: str
    #: 是否失败（``status == Error``）
    isError: bool
    #: ``Pending`` 时是否允许展开（shell 类工具会放开）
    allowOpenWhilePending: bool
    #: 结构化附加数据（``ElaChatToolCall.metadata`` 原样交出；缺省空字典）
    metadata: dict = field(default_factory=dict)
    #: 有效工具类别（见 :class:`~pyqt6_ela_pro.chat.message.ElaChatToolKindType`）
    kind: str = ""
    #: 人类可读标题（空表示按工具名生成）
    title: str = ""
    #: 访问 / 修改的文件位置（``ElaChatToolLocation`` 元组）
    locations: tuple = ()
    #: 父工具调用 id（子代理嵌套；空表示顶层）
    parentId: str = ""
    #: 耗时（毫秒；0 表示未知）
    durationMs: float = 0.0

    def parsedArguments(self) -> dict:
        """解析参数为字典（容错，永不抛异常）。
        ``arguments`` 是模型给的内容，塞进 ``QLabel`` 前必须设 ``PlainText``，
        否则 ``a < b`` 里的 ``&``、``<`` 会被当富文本吃掉。
        """
        return parseToolArguments(self.arguments)


#: 渲染器工厂：由上下文建一个控件（返回 ``None`` 等价于「不接管」）
ToolRendererFactory = Callable[[ToolRenderContext], object]

#: 副标题函数：``(arguments) -> (键, 值)``，对齐 ``toolSubtitleParts``
ToolSubtitleFn = Callable[[str], Tuple[str, str]]


@dataclass(frozen=True)
class _Entry:
    """注册表条目（名字就是 ``_REGISTRY`` 的 key，不再冗余存一份）。"""

    factory: ToolRendererFactory
    subtitle: Optional[ToolSubtitleFn]
    groupable: bool


#: 进程级注册表（模块私有，改动只经公开函数）
_REGISTRY: dict = {}


def parseToolArguments(arguments) -> dict:
    """容错解析工具参数为字典。
    ``dict`` 原样返回；非法 JSON / 空串 / 非字典 JSON -> ``{}``；非 JSON 纯文本
    （流式半截参数、模型直接吐的命令行）-> ``{"": 原文}``，避免卡片一片空白。
    """
    if isinstance(arguments, dict):
        return arguments
    text = (arguments or "").strip() if isinstance(arguments, str) else ""
    if not text:
        return {}
    try:
        data = _json.loads(text)
    except (ValueError, TypeError):
        return {"": text}
    return data if isinstance(data, dict) else {}


def registerToolRenderer(
    name: str,
    factory: ToolRendererFactory,
    *,
    subtitle: Optional[ToolSubtitleFn] = None,
    groupable: Optional[bool] = None,
    replace: bool = False,
) -> None:
    """注册一个工具结果渲染器（模块导入时调用一次即可）。
    ``factory`` 是 ``(ToolRenderContext) -> QWidget``，返回 ``None`` 表示不接管；
    ``subtitle`` 是 ``(arguments) -> (键, 值)``，返回的键会自动从参数摘要里排除；
    ``groupable=True`` 表示进入上下文分组（分组卡会绕过渲染器），默认 False。
    """
    key = str(name or "").strip().casefold()
    if not key:
        raise ValueError("registerToolRenderer: name 不能为空")
    if not callable(factory):
        raise ValueError(f"registerToolRenderer: {key} 的 factory 不可调用")
    if subtitle is not None and not callable(subtitle):
        raise ValueError(f"registerToolRenderer: {key} 的 subtitle 不可调用")
    if key in _REGISTRY and not replace:
        raise ValueError(
            f"registerToolRenderer: {key} 已注册（如需覆盖传 replace=True）"
        )
    _REGISTRY[key] = _Entry(
        factory=factory,
        subtitle=subtitle,
        groupable=False if groupable is None else bool(groupable),
    )


def unregisterToolRenderer(name: str) -> bool:
    """注销渲染器（未注册返回 ``False``）。"""
    return _REGISTRY.pop(str(name or "").strip().casefold(), None) is not None


def toolRenderer(name: str) -> Optional[ToolRendererFactory]:
    """取渲染器工厂（未注册返回 ``None``）。MCP 工具名按 ``mcp`` 前缀回退。"""
    key = str(name or "").strip().casefold()
    entry = _REGISTRY.get(key)
    if entry is None and (key.startswith("mcp_") or key.startswith("mcp.")):
        entry = _REGISTRY.get("mcp")
    return entry.factory if entry is not None else None


def toolRendererNames() -> list:
    """已注册的工具名列表（按注册顺序）。"""
    return list(_REGISTRY)


def toolRendererGroupable(name: str) -> bool:
    """该工具当前是否会进入上下文分组：注册表 ``groupable`` 优先；
    未注册时看 :func:`isContextTool`。"""
    key = str(name or "").strip().casefold()
    entry = _REGISTRY.get(key)
    return entry.groupable if entry is not None else isContextTool(key)


def toolRendererSubtitle(name: str, arguments) -> Tuple[str, str]:
    """取注册表副标题；未注册或未提供 ``subtitle`` 时返回 ``("", "")``。

    异常一律吞掉落回空副标题（调用点在 Qt 回调链上，宿主 bug 不该崩掉卡片）。
    """
    entry = _REGISTRY.get(str(name or "").strip().casefold())
    if entry is None or entry.subtitle is None:
        return ("", "")
    try:
        value = entry.subtitle(arguments)
    except Exception:
        return ("", "")
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return ("", "")
    return (str(value[0] or ""), str(value[1] or ""))


def clearToolRenderers() -> None:
    """清空注册表（**只给测试用** —— 用来隔离用例之间的注册状态）。"""
    _REGISTRY.clear()
