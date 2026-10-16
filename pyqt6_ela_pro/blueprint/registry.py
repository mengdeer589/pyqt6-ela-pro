"""
蓝图注册表（扩展性核心）。

- ``ElaNodeSpec``：节点类型描述（引脚、分类、强调色、自定义体构建器、描述）；
- ``ElaNodeRegistry``：单例注册表，``register`` / ``create`` / ``specs`` /
  ``categories`` / ``search``；
- ``register_node_type``：一行代码注册节点类型的便捷函数；
- ``PIN_COLORS`` / ``register_pin_type`` / ``pin_color``：引脚类型配色。

``body_builder`` 是最重要的扩展点：签名为
``Callable[[ElaBlueprintNode, QWidget], None]``，第二个参数是节点体容器
（透明背景、自带垂直布局 ``container.layout()``）。

命名空间（owner）隔离：注册 / 查询 / 创建可携带 ``owner`` 划定命名空间，
同名类型在不同 owner 下互不影响；``owner=None`` 为全局命名空间。
指定 owner 的查询 / 创建范围为「该 owner + 全局」。

移植自 InstructionX_UIKit.blueprint.registry（原库为 PyQt6，
类名 Ela* 前缀；主题令牌经 blueprint._tokens 适配 eTheme；原库无 LICENSE，
保留出处）。
"""

from dataclasses import dataclass, field
import logging
from typing import Callable, Optional

from PyQt6.QtGui import QColor

from ._tokens import T
from .model import ElaBlueprintNode

logger = logging.getLogger(__name__)

__all__ = [
    "ElaNodeSpec",
    "ElaNodeRegistry",
    "register_node_type",
    "PIN_COLORS",
    "register_pin_type",
    "pin_color",
]


# ---------------------------------------------------------------------------
# 引脚类型配色
# ---------------------------------------------------------------------------

#: 引脚类型 → 颜色。值可以是令牌键（如 ``"success"`` 即 ``color.success``）
#: 或 ``#hex`` 颜色字符串。``exec`` 为执行流引脚（浅灰白）。
PIN_COLORS = {
    "any": "text.tertiary",
    "int": "success",
    "float": "primary",
    "str": "warning",
    "image": "#C080D0",
    "tensor": "#4FA8A0",
    "exec": "#E8E8E8",
}


def register_pin_type(name: str, color: str) -> None:
    """注册 / 覆盖一种引脚类型配色。

    :param name: 类型名（``ElaPin.data_type`` 使用的键，如 ``"audio"``）
    :param color: 令牌键（``"success"`` 等）或 hex
    :raises ValueError: 颜色既不是合法 ``QColor`` 字面量也不是已知令牌
        （``name`` 不能覆盖内置的 ``"any"``，否则兜底链就断了）

    **必须注册期校验**：``pin_color()`` 只在绘制期被调用（``node_widget``
    ``_draw_pins``、``edge_widget`` ``_color`` / ``draw``，全在 ``paintEvent``
    链上），而 ``T()`` 对未知键抛 ``KeyError`` —— 不校验就等于把「宿主填错
    了一个词」变成**绘制时静默终止进程**。
    """
    key = str(name)
    if key == "any":
        # ``any`` 是未知类型的兜底目标（``pin_color`` 的最后一层），
        # 覆盖它等于剪断整条降级链
        raise ValueError("引脚类型名 'any' 是内置兜底条目，不可覆盖")
    value = str(color)
    _resolve_pin_color(key, value)  # 校验：非法就地抛 ValueError
    PIN_COLORS[key] = value


def _resolve_pin_color(name: str, value: str) -> str:
    """把一个引脚配色值解析成 hex 字符串；非法就地抛 ``ValueError``。

    两种合法形态：``T()`` 认识的令牌键，或 ``QColor`` 认识的颜色字面量
    （``#rrggbb`` / SVG 具名色如 ``"red"``）。

    **注意 ``rgb(1,2,3)`` 不合法**：``QColor`` 只吃 ``#rrggbb`` 与具名色，
    不解析 CSS 函数记法（实测 ``QColor("rgb(1,2,3)").isValid()`` 为
    ``False``）。原先这里有句 ``value.startswith("rgb")`` 就原样放行，
    结果是下游 ``QColor(...)`` 拿到**无效色静默变黑** —— 引脚看上去「没
    上色」而零报错。
    """
    try:
        return str(T(f"color.{value}"))
    except KeyError:
        pass
    color = QColor(value)
    if not color.isValid():
        raise ValueError(
            f"引脚类型 {name!r} 的颜色 {value!r} 既不是已知令牌，也不是合法的"
            f"颜色字面量（QColor 只接受 #rrggbb / 具名色，不接受 rgb(...) 记法）"
        )
    return color.name()


def pin_color(data_type: str) -> str:
    """取引脚类型对应的实时颜色（hex 字符串），主题感知。

    值若为令牌键则经 ``T("color.<key>")`` 实时解析；未知类型回退 ``any``。

    **这一层仍要兜底**：``PIN_COLORS`` 是模块级 dict，宿主可以直接往里写而
    绕过 ``register_pin_type`` 的校验 —— 而绘制期没有第二次机会，非法值
    在这里必须降级成 ``any`` 而不是抛。
    """
    value = PIN_COLORS.get(data_type, PIN_COLORS["any"])
    try:
        return _resolve_pin_color(data_type, value)
    except ValueError:
        # 兜底目标是 ``PIN_COLORS["any"]`` 本身（而不是硬编码某个令牌）——
        # 它是内置表里保证可解析的条目。用 ``T("color.any")`` 会二次失败：
        # 内置值是 ``"text.tertiary"``，令牌键名并不是 ``any``。
        logger.warning("引脚类型 %r 的配色 %r 非法，回退到 any", data_type, value)
        return _resolve_pin_color(data_type, PIN_COLORS["any"])


# ---------------------------------------------------------------------------
# 节点类型描述
# ---------------------------------------------------------------------------


@dataclass
class ElaNodeSpec:
    """节点类型描述（注册表条目）。

    ``inputs`` / ``outputs`` 是引脚字典列表，每项 ``{"id", "name", "data_type",
    "multi"}``（后三个可缺省，``id`` 必须非空）；``accent`` 是标题栏强调色
    （令牌键或 hex，``None`` 用默认灰）；``body_builder`` 为 ``None`` 时按
    properties 键值对展示节点体。
    """

    type_name: str
    title: str
    category: str
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    accent: Optional[str] = None
    body_builder: Optional[Callable] = None
    description: str = ""
    owner: Optional[str] = None


# ---------------------------------------------------------------------------
# 注册表（单例）
# ---------------------------------------------------------------------------


class ElaNodeRegistry:
    """节点类型注册表（单例），内部以 ``(owner, type_name)`` 为键。

    ``owner=None`` 为全局命名空间；各插件 / 模块可传自己的 owner 注册
    同名类型而互不覆盖。指定 owner 的查询 / 创建范围为「该 owner + 全局」。
    """

    _instance = None

    def __init__(self):
        #: 注册表存储：键为 ``(owner, type_name)``，owner 为 None 即全局
        self._specs = {}

    @classmethod
    def instance(cls) -> "ElaNodeRegistry":
        """返回全局唯一注册表实例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -- 注册 ------------------------------------------------------------
    def register(self, spec: ElaNodeSpec, owner: str = None) -> ElaNodeSpec:
        """注册节点类型（同命名空间内同 ``type_name`` 覆盖），返回 ``spec``。

        注册期校验引脚定义（``inputs`` / ``outputs`` 的每项必须是带非空
        ``id`` 的字典）：缺 id 的定义会在 ``create()`` 里抛 ``KeyError``，
        而 ``create`` 常在菜单 / 拖线回调（Qt 槽）里被调用 —— 槽内异常 =
        0xC0000409 零 traceback 终止。注册是唯一能给出清晰报错的时机。
        """
        if not spec.type_name:
            raise ValueError("ElaNodeSpec.type_name 不能为空")
        self._validate_pin_defs(spec.inputs, "输入")
        self._validate_pin_defs(spec.outputs, "输出")
        if owner is None:
            owner = spec.owner
        spec.owner = owner
        key = (owner, spec.type_name)
        existing = self._specs.get(key)
        if existing is not None and not self._same_definition(existing, spec):
            logger.warning(
                "节点类型 %r 在命名空间 %r 中被重复注册且引脚定义不同，旧定义已被覆盖",
                spec.type_name,
                owner,
            )
        self._specs[key] = spec
        return spec

    @staticmethod
    def _validate_pin_defs(pins, kind: str) -> None:
        """校验引脚定义列表（供 ``register`` 与测试直接调用）。"""
        for pd in pins or ():
            if not isinstance(pd, dict) or not str(pd.get("id") or "").strip():
                raise ValueError(f"{kind}引脚定义必须是带非空 id 的字典，实际 {pd!r}")

    @staticmethod
    def _same_definition(a: ElaNodeSpec, b: ElaNodeSpec) -> bool:
        """判断两条 spec 引脚定义是否一致（覆盖时幂等判定）。"""
        return a.inputs == b.inputs and a.outputs == b.outputs

    def unregister(self, type_name: str, owner: str = None) -> bool:
        """注销节点类型；不存在返回 ``False``。

        **给了 ``owner`` 就只删那个命名空间里的那条**，删不到就返回 ``False`` ——
        绝不退到全局那条：查询时「owner + 全局」是**读取**的宽松（找不到全局能
        顶上），删除上这么宽松就等于「插件注销自己命名空间」把别人的全局类型删了，
        之后 ``create()`` 直接 KeyError。
        """
        key = (owner, type_name)
        return self._specs.pop(key, None) is not None

    def spec(self, type_name: str, owner: str = None):
        """按类型名取 ``ElaNodeSpec``，未注册返回 ``None``。

        :param owner: 给定时只查「该 owner + 全局」；为 ``None`` 时先查
            全局，未命中再查全部命名空间（多命中记 WARNING 并返回首个）。
        """
        if owner is not None:
            found = self._specs.get((owner, type_name))
            if found is not None:
                return found
            return self._specs.get((None, type_name))
        found = self._specs.get((None, type_name))
        if found is not None:
            return found
        hits = [s for (o, t), s in self._specs.items() if t == type_name]
        if len(hits) > 1:
            logger.warning(
                "节点类型 %r 在多个命名空间中均有定义且全局未注册，"
                "未指定 owner 的查询返回首个命中（共 %d 个）",
                type_name,
                len(hits),
            )
        return hits[0] if hits else None

    # -- 查询 ------------------------------------------------------------
    def _scoped_specs(self, owner: str = None) -> list:
        """按 owner 取范围内的 spec（None 全空间，否则该 owner + 全局）。"""
        if owner is None:
            return list(self._specs.values())
        return [s for (o, _t), s in self._specs.items() if o is None or o == owner]

    def specs(self, category: str = None, owner: str = None) -> list:
        """``ElaNodeSpec`` 列表（可按分类 / 命名空间过滤），按注册顺序返回。"""
        items = self._scoped_specs(owner)
        if category is not None:
            items = [s for s in items if s.category == category]
        return items

    def categories(self, owner: str = None) -> list:
        """全部分类名（按注册出现顺序，去重）；可按命名空间限定范围。"""
        seen = []
        for spec in self._scoped_specs(owner):
            if spec.category not in seen:
                seen.append(spec.category)
        return seen

    def search(self, keyword: str, owner: str = None) -> list:
        """按关键字模糊搜索（匹配类型名 / 标题 / 分类 / 描述，忽略大小写）。"""
        kw = str(keyword).strip().lower()
        if not kw:
            return self.specs(owner=owner)
        result = []
        for spec in self._scoped_specs(owner):
            hay = (
                spec.type_name + spec.title + spec.category + spec.description
            ).lower()
            if kw in hay:
                result.append(spec)
        return result

    # -- 创建 ------------------------------------------------------------
    def create(self, type_name: str, owner: str = None) -> ElaBlueprintNode:
        """按类型创建 ``ElaBlueprintNode``：引脚 / 标题 / 强调色按 spec 就位。

        未注册的类型抛 ``KeyError``。``body_builder`` 不在此调用——它由
        ``ElaNodeWidget`` 在构建节点体时执行（UI 层职责）。
        """
        spec = self.spec(type_name, owner=owner)
        if spec is None:
            raise KeyError(f"未注册的节点类型: {type_name!r}")
        node = ElaBlueprintNode(spec.type_name, spec.title)
        node.accent = spec.accent
        for pd in spec.inputs:
            node.add_input(
                pd["id"],
                pd.get("name"),
                pd.get("data_type", "any"),
                bool(pd.get("multi", False)),
            )
        for pd in spec.outputs:
            node.add_output(
                pd["id"],
                pd.get("name"),
                pd.get("data_type", "any"),
                bool(pd.get("multi", False)),
            )
        return node


def register_node_type(
    type_name: str,
    title: str,
    category: str,
    inputs=(),
    outputs=(),
    accent=None,
    body_builder=None,
    description: str = "",
    owner: str = None,
) -> ElaNodeSpec:
    """便捷函数：一行注册节点类型（等价 ``ElaNodeRegistry.instance().register``）。"""
    spec = ElaNodeSpec(
        type_name=type_name,
        title=title,
        category=category,
        inputs=list(inputs),
        outputs=list(outputs),
        accent=accent,
        body_builder=body_builder,
        description=description,
        owner=owner,
    )
    return ElaNodeRegistry.instance().register(spec, owner=owner)
