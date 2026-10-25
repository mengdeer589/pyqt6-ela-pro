"""
聊天 JSON 编解码（优先 ``orjson``，缺失时回落标准库 ``json``）。
``pyqt6_ela_pro.chat`` 内部的持久化 / journal / 工具参数解析统一走这里：

- 装了 ``orjson``：由它序列化（更快、原生 UTF-8）；``allow_nan=False``
  的严格性用一次快速扫描保持与标准库一致（orjson 默认会把 NaN / Infinity
  写成 ``null``，静默丢数据）；
- 没装：``json.dumps(ensure_ascii=False, separators=(",", ":"))``。
  两套后端产出**同为紧凑 UTF-8 文本**、``allow_nan=False`` 语义一致，但
  **浮点指数记法可能不同**（标准库 ``1e-07`` / orjson ``1e-7``）——不要拿
  输出文本做跨机器逐字节比对（解析后的值相同）。

**写入与读取都严格**：两端都拒非有限浮点（写入抛 ``ValueError``，读取按非法 JSON
拒掉），否则 ``float('inf')`` 会流进整数字段把 ``fromDict`` 打断。

宿主也可直接用 ``pyqt6_ela_pro.chat.jsonDumps`` / ``jsonLoads`` /
``jsonBackend``（见 ``chat/__init__.py``）。
"""

from __future__ import annotations

import json
import math
from typing import Any

try:  # pragma: no cover - 分支取决于安装环境
    import orjson as _orjson
except ImportError:  # pragma: no cover
    _orjson = None

#: orjson 对非字符串键的兼容开关（旧版本没有该属性时退化为 0，仅字符串键可用）
_ORJSON_OPTIONS = getattr(_orjson, "OPT_NON_STR_KEYS", 0) if _orjson else 0


def backend() -> str:
    """当前 JSON 后端名（``"orjson"`` / ``"json"``）。"""
    return "orjson" if _orjson is not None else "json"


def _has_non_finite(value: Any) -> bool:
    """迭代扫描 NaN / Infinity（不递归，避免深层数据触发递归上限）。"""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, float):
            if not math.isfinite(item):
                return True
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return False


def dumps(obj: Any, allow_nan: bool = False) -> str:
    """序列化为紧凑 UTF-8 JSON 文本（``str``）。

    :param allow_nan: ``False``（默认）时 NaN / Infinity 抛
        :class:`ValueError`（与标准库同语义，避免把非 JSON 数值静默写成
        ``null`` / ``NaN``）；``True`` 时交给后端默认行为。
    """
    if _orjson is not None:
        if not allow_nan and _has_non_finite(obj):
            raise ValueError("Out of range float values are not JSON compliant")
        return _orjson.dumps(obj, option=_ORJSON_OPTIONS).decode("utf-8")
    return json.dumps(
        obj,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=allow_nan,
    )


def _reject_constant(name: str) -> Any:
    """标准库 ``json`` 的 ``parse_constant`` 钩子：拒绝非有限字面量。

    ``json.loads`` 默认**接受** ``NaN`` / ``Infinity`` / ``-Infinity`` 并返回
    ``float('inf')``；而 ``orjson.loads`` 直接拒。这让两个后端在读取端行为分叉 ——
    装了 orjson 的机器上看不出问题，没装的机器上 ``inf`` 会一路流到 ``_as_int`` /
    ``journal._int``。加这个钩子让两端一致：**非有限字面量一律按非法 JSON 拒掉**。

    ``1e999`` 这种合法数字语法不在此列（它不是常量），但同样会被解析成 ``inf``；
    那条路由各 ``_as_*`` 的 finite 守卫负责。
    """
    raise ValueError(f"非有限字面量不是合法 JSON：{name}")


def _finite_float(text: str) -> float:
    """标准库 ``json`` 的 ``parse_float``：拒掉溢出成 ``inf`` 的合法数字语法。

    ``1e999`` 语法合法、标准库解析成 ``inf``，而 orjson 直接拒 —— 不拦就会
    「装了 orjson 的机器看不到、没装的机器中招」。与 `_reject_constant` 一起
    把两端的读取端语义钉成一致。
    """
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"非有限数字不是合法 JSON：{text}")
    return value


def loads(data: Any) -> Any:
    """解析 JSON 文本 / 字节（``str`` / ``bytes`` / ``bytearray``）。

    两端（orjson / 标准库）行为一致：**内容非法抛 ``ValueError``**、
    **输入类型非法抛 ``TypeError``**；``NaN`` / ``Infinity`` / ``1e999``
    一律按非法 JSON 拒掉。
    """
    if not isinstance(data, (str, bytes, bytearray)):
        raise TypeError(
            f"jsonLoads 需要 str / bytes / bytearray，收到 {type(data).__name__}"
        )
    if _orjson is not None:
        return _orjson.loads(data)
    return json.loads(data, parse_constant=_reject_constant, parse_float=_finite_float)
