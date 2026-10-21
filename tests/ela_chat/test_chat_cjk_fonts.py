"""中文系统 chat 字体单族化（bug 报告 §3）：头部标题 + 等宽标签。

多族字体列表在 Win7 上是独立慢 shaping 路径且进程级毒化（与内容是否 CJK
无关）；头部名称 / 模型名与工具详情（耗时 / 差异 / 答案）都可能含 CJK，
中文系统统一收成单族雅黑。探测函数 monkeypatch 注入，不依赖跑测机器 locale。
"""

from __future__ import annotations

import pytest
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.chat import ElaChatBubble, ElaChatRoleType
from pyqt6_ela_pro.chat import _theme as chat_theme
from pyqt6_ela_pro.chat import blocks as chat_blocks

_CJK = "Microsoft YaHei"


@pytest.fixture
def cjk_system(monkeypatch):
    monkeypatch.setattr(chat_theme, "system_cjk_font_family", lambda: _CJK)
    monkeypatch.setattr(chat_blocks, "system_cjk_font_family", lambda: _CJK)
    return _CJK


@pytest.fixture
def non_cjk_system(monkeypatch):
    monkeypatch.setattr(chat_theme, "system_cjk_font_family", lambda: None)
    monkeypatch.setattr(chat_blocks, "system_cjk_font_family", lambda: None)
    return None


class TestMonoFont:
    def test_single_family_on_cjk(self, cjk_system):
        font = chat_theme.mono_font(11)
        assert font.families() == [_CJK]
        assert font.pixelSize() == 11

    def test_stack_without_cjk(self, non_cjk_system):
        font = chat_theme.mono_font(11)
        assert font.families() == list(chat_theme.MONO_FONT_STACK)


class TestMessageHeaderFonts:
    def test_title_single_family_on_cjk(self, qapp, make, cjk_system):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setTitle("助手")
        header = bubble.header()
        assert header._title_label.font().families() == [_CJK]
        assert header._title_label.font().pixelSize() == 13

    def test_mono_label_single_family_on_cjk(self, qapp, make, cjk_system):
        """耗时等标签走 ``mono_font``：中文系统下也应落到单族。"""
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        header = bubble.header()
        assert header._time_label.font().families() == [_CJK]

    def test_title_stack_without_cjk(self, qapp, make, non_cjk_system):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        header = bubble.header()
        assert header._title_label.font().families() == [
            "Segoe UI",
            "Microsoft YaHei UI",
            "Microsoft YaHei",
        ]

    def test_theme_switch_keeps_single_family(self, qapp, make, cjk_system):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        header = bubble.header()
        assert header._title_label.font().families() == [_CJK]
        assert header._time_label.font().families() == [_CJK]
