"""
工具结果富渲染注册表（``pyqt6_ela_pro.chat``）。

**问题**：``ToolCallCard`` 只会把 ``arguments`` / ``result`` 当纯文本显示。
编码 agent 里最高频的动作是「看 diff」，但改代码类工具的结果是一坨 JSON，
用户必须展开、滚动、盯着一坨括号找变化。opencode 为此做了 1800 行
``tool-renderer.tsx``，把 diff / 图片 / 终端输出各写一个渲染器。

**这里提供的是那个「注册表」抽象本身**，库内不内置任何具体渲染器 ——
渲染什么、怎么渲染是**宿主的产品决策**（就像
:func:`~pyqt6_ela_pro.chat.blocks.toolDefaultOpen` 一样交给宿主注入）。

.. code-block:: python

    # 宿主：把 patch / edit 的结果渲染成 diff
    def buildDiff(ctx: ToolRenderContext) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        for entry in ctx.parsedArguments().get("files", []):
            layout.addWidget(UnifiedDiffView(entry["diff"], parent=widget))
        return widget

    registerToolRenderer("patch", buildDiff,
                         subtitle=lambda args: ("files", "3 个文件"))

**与 opencode 的关键差异：我们只替换 body，不替换整个卡片。**

opencode 的 ``ToolDisplay`` 用 ``<Dynamic>`` 分发**整个组件**，每个渲染器都要
自己包一层 60 行的 ``BasicTool``（头部 / 图标 / 状态 / 展开逻辑），
13 个渲染器复述 13 遍。本模块的渲染器**只填内容区**，头部、chevron、宽度
省略、错误竖线、忙碌环、默认展开策略全部保留在 ``ToolCallCard`` 里。代价是
宿主改不了头部布局；收益是现有三条工具卡回归守卫（副标题去重 / 运行中不显示
参数 / default-open 纯函数）一条都不用改，且扩展点只有一个。

**生命周期与线程约束**（三条硬要求，违反会进程崩溃）：

1. **必须持 Python 引用** —— 卡片会把返回的 widget ``addWidget`` 进布局，
   但那只转移 C++ 所有权，Python 包装器会被 GC，之后调用其方法就是解引用已
   释放内存（与 ``setItemDelegate`` 同一死法）。``ToolCallCard`` 内部持有
   ``_renderer_widget`` 引用来保证不回收；宿主**不需要**、也**不应该**自己
   再去 ``del``。
2. **工厂在 GUI 线程的点击槽里被调用** —— 里面抛出的 Python 异常会穿过 C++
   边界导致进程直接终止（无 traceback）。``ToolCallCard`` 用 ``try/except``
   包住并落回默认文本 body，宿主渲染器里的 bug 不会让聊天窗口消失。
3. **不要在工厂里做重活** —— 它跑在「用户点开卡片」的那一帧里。数据量大的
   解析 / 网络请求请放后台线程，结果用信号回传。

**结果更新协议（可选）**：Solid 的响应式在 Qt 里没有对应物，这里切成两步 ——
建卡时给一份**不可变快照**（:class:`ToolRenderContext`，无引用 → 无悬垂风险），
之后结果变化时卡片**推送**给 widget（若它有 ``updateToolResult`` 方法）：

.. code-block:: python

    class DiffView(QWidget):
        def updateToolResult(self, result: str, status: str) -> None:
            self._reparse(result)      # 可选方法：有就调，没有就跳过

折叠状态下工具才完成的情况不需要额外处理：内容区是**首次展开时**才构建的，
工厂拿到的快照天然是当下最新的。

**``subtitle`` 契约**：签名是 ``(arguments: str) -> (key, value)``，与
:func:`~pyqt6_ela_pro.chat.blocks.toolSubtitleParts` 同形。**必须返回
``(键, 值)`` 而不是裸字符串 —— 参数摘要的去重机制是按键排除的**
（``toolArgumentPairs(..., excludeKey=键)``），宿主不声明来源键，参数里
的同一个值就会在副标题和参数摘要各出现一次。确实归因不到键时返回
``("", "")``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

from . import _json

__all__ = [
    "ToolRenderContext",
    "ToolRendererFactory",
    "ToolSubtitleFn",
    "clearToolRenderers",
    "registerToolRenderer",
    "toolRenderer",
    "toolRendererGroupable",
    "toolRendererNames",
    "toolRendererSubtitle",
    "unregisterToolRenderer",
]


#: 上下文工具（连续出现时会被折进分组卡，跳过自定义渲染）。
#: 与 :data:`pyqt6_ela_pro.chat.blocks.CONTEXT_TOOLS` 同值；此处独立声明是
#: 为了让 ``renderers`` **不 import** ``blocks``（否则 blocks 要用它就成环）。
_CONTEXT_TOOLS = frozenset({"read", "glob", "grep", "list"})


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

    def parsedArguments(self) -> dict:
        """解析参数为字典（容错，永不抛异常）。

        ``arguments`` 是**模型给的内容**，直接塞进 ``QLabel`` 前必须设
        ``setTextFormat(Qt.TextFormat.PlainText)`` —— 默认 ``AutoText`` 会把
        ``a < b`` / ``Tom & Jerry`` 里的 ``&``、``<`` 当富文本吃掉。
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

    - ``dict`` 原样返回；
    - 非法 JSON / 空串 / 非字典 JSON（如 ``[1,2]``）-> ``{}``；
    - **非 JSON 的纯文本**（流式半截参数、模型直接吐的命令行）-> ``{"": 原文}``，
      让副标题 / 参数摘要还能把它显示出来，而不是整段消失。

    最后一条是有意的：参数是**分片流式到达**的，展开前常常只有半截
    ``"path": "src/a`` —— 当成坏 JSON 丢掉的话卡片上就一片空白。
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

    :param name: 工具名（大小写敏感，建议小写）
    :param factory: ``(ToolRenderContext) -> QWidget``；返回 ``None`` 表示不接管，
        落回默认纯文本 body
    :param subtitle: ``(arguments) -> (键, 值)``，用于折叠态副标题；**返回的键
        会自动从参数摘要里排除**（防「3 个文件 files=[...]」这种重复）
    :param groupable: 是否仍参与上下文工具分组。``None``（默认）时
        **上下文工具（read / glob / grep / list）自动退出分组** —— 它们连续
        出现时会被折进 ``ContextToolGroupCard``，而那张卡只画一行汇总摘要，
        会把你的渲染器整个绕过。非上下文工具默认保持可分组。
    :param replace: 名字已被占用时是否允许覆盖（默认抛 :class:`ValueError`）

    :raises ValueError: 名字为空 / 不可调用 / 已被占用且 ``replace=False``

    **静默覆盖会掩盖 bug**（两个插件抢同一个名字、后注册的悄悄赢），所以这里
    拒绝而不是照抄 opencode 的 ``state[name] = input``。
    """
    key = str(name or "").strip()
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
        groupable=(key not in _CONTEXT_TOOLS) if groupable is None else bool(groupable),
    )


def unregisterToolRenderer(name: str) -> bool:
    """注销渲染器（原先未注册返回 ``False``）。"""
    return _REGISTRY.pop(str(name or "").strip(), None) is not None


def toolRenderer(name: str) -> Optional[ToolRendererFactory]:
    """取渲染器工厂（未注册返回 ``None``）。"""
    entry = _REGISTRY.get(str(name or "").strip())
    return entry.factory if entry is not None else None


def toolRendererNames() -> list:
    """已注册的工具名列表（按注册顺序）。"""
    return list(_REGISTRY)


def toolRendererGroupable(name: str) -> bool:
    """该工具是否仍参与上下文工具分组（未注册返回 ``True``）。

    未注册的工具行为与注册表引入前完全一致，所以默认 ``True``。
    """
    entry = _REGISTRY.get(str(name or "").strip())
    return True if entry is None else entry.groupable


def toolRendererSubtitle(name: str, arguments) -> Tuple[str, str]:
    """取注册表副标题；未注册或未提供 ``subtitle`` 时返回 ``("", "")``。

    **异常一律吞掉落回空副标题**：``subtitle`` 由宿主提供，而调用点在
    ``_sync_header``（可能处于 Qt 回调链上），宿主的一个 bug 不该让整张
    工具卡崩掉。调用方拿 ``("", "")`` 后会走原有的
    :func:`~pyqt6_ela_pro.chat.blocks.toolSubtitle` 兜底。
    """
    entry = _REGISTRY.get(str(name or "").strip())
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
