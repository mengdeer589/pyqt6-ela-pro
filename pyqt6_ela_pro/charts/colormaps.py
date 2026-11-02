"""Matplotlib 风格色带注册表（``image`` 系列 / imshow 用）。

色带是一组等距分布的颜色锚点；渲染时线性插值成 256 级 LUT。内置常用
matplotlib 色带，宿主可用 :func:`registerColormap` 注册自己的色带。
"""

from __future__ import annotations

from .._colors import parse_color


_BUILTIN_COLORMAPS = {
    "viridis": [
        "#440154",
        "#482878",
        "#3e4989",
        "#31688e",
        "#26828e",
        "#1f9e89",
        "#35b779",
        "#6ece58",
        "#b5de2b",
        "#fde725",
    ],
    "plasma": [
        "#0d0887",
        "#46039f",
        "#7201a8",
        "#9c179e",
        "#bd3786",
        "#d8576b",
        "#ed7953",
        "#fb9f3a",
        "#fdca26",
        "#f0f921",
    ],
    "inferno": [
        "#000004",
        "#1b0c41",
        "#4a0c6b",
        "#781c6d",
        "#a52c60",
        "#cf4446",
        "#ed6925",
        "#fb9b06",
        "#f7d13d",
        "#fcffa4",
    ],
    "magma": [
        "#000004",
        "#1c1044",
        "#4f127b",
        "#812581",
        "#b5367a",
        "#e55063",
        "#fb8761",
        "#fec287",
        "#fbfdbf",
    ],
    "cividis": [
        "#00224e",
        "#123570",
        "#3b496c",
        "#575d6d",
        "#707173",
        "#8a8678",
        "#a59c74",
        "#c3b369",
        "#e1cc55",
        "#fee838",
    ],
    "gray": ["#000000", "#ffffff"],
    "hot": [
        "#000000",
        "#b30000",
        "#ff0000",
        "#ff8000",
        "#ffff00",
        "#ffffff",
    ],
    "coolwarm": [
        "#3b4cc0",
        "#6f92f3",
        "#aac7fd",
        "#dddddd",
        "#f6b69b",
        "#e7745b",
        "#b40426",
    ],
    "jet": [
        "#000080",
        "#0000ff",
        "#00ffff",
        "#00ff00",
        "#ffff00",
        "#ff0000",
        "#800000",
    ],
}

_USER_COLORMAPS: dict = {}


def _validated(colors) -> list:
    """色带必须至少两个合法颜色；非法输入抛 ``ValueError``。"""
    if not isinstance(colors, (list, tuple)) or len(colors) < 2:
        raise ValueError("colormap 至少需要两个颜色")
    out = []
    for color in colors:
        if not isinstance(color, str) or not color.strip():
            raise ValueError("colormap 颜色必须是颜色字符串")
        if not parse_color(color).isValid():
            raise ValueError(f"无法解析的颜色: {color!r}")
        out.append(color.strip())
    return out


def registerColormap(name: str, colors) -> None:
    """注册 / 覆盖一条命名色带（``image`` 系列的 ``cmap`` 可直接引用）。"""
    key = str(name or "").strip().lower()
    if not key:
        raise ValueError("colormap 名称不能为空")
    _USER_COLORMAPS[key] = _validated(colors)


def colormapColors(name: str):
    """命名色带 → 颜色列表副本；未知名称返回 ``None``。"""
    key = str(name or "").strip().lower()
    colors = _USER_COLORMAPS.get(key) or _BUILTIN_COLORMAPS.get(key)
    return list(colors) if colors else None


def colormapNames() -> list:
    """当前可用的色带名称（含内置与宿主注册）。"""
    return sorted(set(_BUILTIN_COLORMAPS) | set(_USER_COLORMAPS))
