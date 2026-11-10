"""Markdown 正文字体族：进程级默认、单族规范化与可用性探测。"""

from __future__ import annotations

import logging

from PyQt6.QtGui import QGuiApplication

from .._internal import fontFamilyAvailable

logger = logging.getLogger(__name__)

#: 新建查看器使用的正文字体族覆盖（空字符串 = 跟随主题）
_DEFAULT_BODY_FONT_FAMILY = ""

_WARNED: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key in _WARNED:
        return
    _WARNED.add(key)
    logger.warning(message)


def _normalize_font_family(value) -> str:
    """用户给的字体族 → 单个族名（多族在 Win7 上是慢 shaping 路径，取首个并告警）。"""
    if not isinstance(value, str):
        return ""
    text = value.strip().strip("'\"").strip()
    if not text:
        return ""
    parts = [p.strip().strip("'\"") for p in text.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) > 1:
        _warn_once(
            "markdown-font:multiple",
            f"Markdown 正文只支持单个字体族，已取 {parts[0]!r}"
            f"（忽略 {len(parts) - 1} 个回退族）",
        )
    return parts[0]


def isFontFamilyAvailable(family: str) -> bool:
    """字体族是否可用（兼容 GDI 中文系统的本地化族名；多族只检查第一个）。
    无 GUI 时返回 ``False``。
    """
    name = _normalize_font_family(family)
    if not name or QGuiApplication.instance() is None:
        return False
    return fontFamilyAvailable(name)


def defaultMarkdownBodyFontFamily() -> str:
    """新建 Markdown 查看器使用的正文字体族（空字符串 = 跟随主题）。"""
    return _DEFAULT_BODY_FONT_FAMILY


def setDefaultMarkdownBodyFontFamily(family: str) -> None:
    """设置新建查看器的正文字体族（只影响之后创建的实例）。

    空字符串恢复「跟随主题」；字体不存在时仍保存设置，实际渲染回退到主题字体。
    单族约束：传入多族只取第一个并告警。
    """
    global _DEFAULT_BODY_FONT_FAMILY
    name = _normalize_font_family(family)
    if (
        name
        and QGuiApplication.instance() is not None
        and not isFontFamilyAvailable(name)
    ):
        _warn_once(
            "markdown-font:missing",
            f"Markdown 正文字体 {name!r} 未安装，实际渲染将回退到可用字体",
        )
    _DEFAULT_BODY_FONT_FAMILY = name
