"""聊天 JSON 编解码（优先 ``orjson``，缺失时回落标准库 ``json``）。

两套后端产出同为紧凑 UTF-8 文本，但浮点指数记法可能不同 —— 不要拿输出文本做
跨机器逐字节比对。写入与读取都严格拒非有限浮点（orjson 默认会把 NaN / Infinity
写成 ``null``，静默丢数据）。
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

    ``allow_nan=False``（默认）时 NaN / Infinity 抛 :class:`ValueError`。
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

    与 ``orjson.loads`` 对齐（标准库默认接受 ``NaN`` / ``Infinity``）。
    """
    raise ValueError(f"非有限字面量不是合法 JSON：{name}")


def _finite_float(text: str) -> float:
    """标准库 ``json`` 的 ``parse_float``：拒掉溢出成 ``inf`` 的合法数字语法。"""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"非有限数字不是合法 JSON：{text}")
    return value


def loads(data: Any) -> Any:
    """解析 JSON 文本 / 字节；内容非法抛 ``ValueError``、输入类型非法抛 ``TypeError``。"""
    if not isinstance(data, (str, bytes, bytearray)):
        raise TypeError(
            f"jsonLoads 需要 str / bytes / bytearray，收到 {type(data).__name__}"
        )
    if _orjson is not None:
        return _orjson.loads(data)
    return json.loads(data, parse_constant=_reject_constant, parse_float=_finite_float)
