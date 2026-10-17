"""折叠头部的颜色层级：思考行与工具面板标题**必须是同一个纯文本色**。

背景
----
``ToolGroupPanel`` 的标题曾经叠了一层强调色（``blend(text, accent, 0.35)``），
本意是「与思考块稍作区分」，实际两头不讨好：0.35 在深色主题下算出
``#c1eaff`` —— 极淡的青，在近黑底上 13px 小字里根本读不出着色过；而浅色
主题下同一比例是 ``#002443``，明显偏蓝。**只有深色主题暴露这个问题**，
结果就是同一层级里出现两种几乎一样的亮色，视觉上更含混。正解是去掉着色：
两者靠「>」箭头与文案本身区分即可。

这里刻意断言 ``ColorText.textColor()``（**意图色**）而不是
``label.palette().foregroundRole()`` —— 后者是陈旧值：``ColorText.paintEvent``
是在**绘制前**才把 palette 自愈回显式色的（``ElaText`` 在 C++ 构造里连了
``themeModeChanged``，信号一发就把 palette 刷回 ``BasicText``），绘制之外
读出来是 ``#000000``，看着像「深色下全黑」的 bug，其实在画的时候是对的。

踩过的另一个坑：offscreen 下 ``widget.render()`` / ``widget.grab()``
**根本不渲染文字**（只有控件形状），拿不到任何像素 —— **逐像素比对在这套件里
不可用**，只能断言意图色。
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QColor
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

from pyqt6_ela_pro._styles import ColorText
from pyqt6_ela_pro.chat import ElaChatWidget
from pyqt6_ela_pro.chat._theme import (
    accent_color,
    base_color,
    blend,
    muted_color,
    text_color,
)
from pyqt6_ela_pro.chat.blocks import ToolCallCard


@pytest.fixture
def dark_mode():
    """切到深色主题并在结束后还原（eTheme 是进程级全局状态）。"""
    previous = eTheme.getThemeMode()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
    yield
    eTheme.setThemeMode(previous)


def _tool_area(chat, mid):
    """跑一轮含「上下文工具 + shell 工具 + 失败工具」的消息。"""
    view = chat.chatView()
    view.beginStep(mid)
    c1 = view.addToolCall(mid, "read", '{"path": "a.py"}')
    view.setToolCallResult(mid, c1, "ok", ok=True)
    c2 = view.addToolCall(mid, "shell", '{"command": "ls -la"}')
    view.setToolCallResult(mid, c2, "boom", ok=False)
    chat.endAssistantMessage()
    return view.bubble(mid)


def _with_reasoning(chat, mid):
    view = chat.chatView()
    view.beginReasoning(mid)
    view.appendReasoning(mid, "先看看布局")
    view.endReasoning(mid, 400.0)
    return view


class TestCollapsibleHeaderColor:
    """思考行与工具面板标题是同一层级，颜色必须一致。"""

    def test_tool_panel_title_is_plain_text_color(self, qapp, make, dark_mode):
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        bubble = _tool_area(chat, mid)
        mode = eTheme.getThemeMode()
        for panel in bubble.toolPanels():
            assert panel._title_label.textColor() == text_color(mode), (
                f"工具面板标题 {panel._title_label.textColor().name()} "
                f"不是纯文本色 {text_color(mode).name()} —— 不该叠强调色"
            )

    def test_tool_panel_title_is_not_accent_tinted(self, qapp, make, dark_mode):
        """钉住「不叠强调色」这条不变式。

        曾经的 0.35 混合比在深色下算出 ``#c1eaff``：偏青但极淡，13px 小字里
        读不出着色过，视觉上与纯文本色几乎无差 —— 属于「看起来像 bug 又说不清
        哪里不对」的那类问题。
        """
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        bubble = _tool_area(chat, mid)
        mode = eTheme.getThemeMode()
        tinted = blend(text_color(mode), accent_color(mode), 0.35)
        for panel in bubble.toolPanels():
            got = panel._title_label.textColor()
            assert got != tinted
            assert got != accent_color(mode), "工具面板标题不能是纯强调色"

    def test_same_as_reasoning_block(self, qapp, make, dark_mode):
        """两者的标题色必须**完全相等**。"""
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        _with_reasoning(chat, mid)
        bubble = _tool_area(chat, mid)
        reasoning = bubble.reasoningBlock()._title_label.textColor()
        for panel in bubble.toolPanels():
            assert panel._title_label.textColor() == reasoning, (
                "工具面板与思考行是同一层级，标题色应一致"
            )

    def test_dark_mode_title_is_white(self, qapp, make, dark_mode):
        """深色主题下就是白色（用户明确要求）。"""
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        bubble = _tool_area(chat, mid)
        mode = eTheme.getThemeMode()
        white = text_color(mode)
        assert white.lightness() > 200, f"深色主题的文本色竟不是亮色：{white.name()}"
        for panel in bubble.toolPanels():
            assert panel._title_label.textColor() == white

    @pytest.mark.parametrize(
        "mode,want_dark",
        [(ElaThemeType.ThemeMode.Light, False), (ElaThemeType.ThemeMode.Dark, True)],
    )
    def test_tracks_theme_in_both_modes(self, qapp, make, mode, want_dark):
        eTheme.setThemeMode(mode)
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        bubble = _tool_area(chat, mid)
        expected = text_color(eTheme.getThemeMode())
        for panel in bubble.toolPanels():
            color = panel._title_label.textColor()
            assert color == expected
            assert (color.lightness() > 128) is want_dark
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)

    def test_runtime_switch_refreshes(self, qapp, make):
        """运行期切主题必须刷新（不能「建完就定格」）。"""
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        bubble = _tool_area(chat, mid)
        light = bubble.toolPanels()[-1]._title_label.textColor()
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
        qapp.processEvents()
        dark = bubble.toolPanels()[-1]._title_label.textColor()
        assert light != dark, "运行期切主题后工具面板标题色没变"
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)


class TestToolAreaLegibility:
    """工具区每个字都得有显式色，且与底色有足够对比。"""

    def test_all_labels_have_explicit_intent_color(self, qapp, make, dark_mode):
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        bubble = _tool_area(chat, mid)
        labels = []
        for panel in bubble.toolPanels():
            labels.append(panel._title_label)
            labels.extend(panel.findChildren(ColorText))
        card = bubble.toolPanels()[-1].findChild(ToolCallCard)
        if card is not None:
            labels.extend(
                lab
                for lab in (card._title_label, card._subtitle_label, card._args_label)
                if lab is not None
            )
        assert labels
        for label in labels:
            assert label._text_color is not None, (
                f"ColorText {label.text()!r} 没有显式色，深色下会回落 BasicText"
            )

    def test_contrast_against_background(self, qapp, make, dark_mode):
        """深色主题下字色与底色明度差要够（漏了显式色会退化成同色不可见）。"""
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        bubble = _tool_area(chat, mid)
        bg = base_color(eTheme.getThemeMode())
        for panel in bubble.toolPanels():
            for label in [panel._title_label, *panel.findChildren(ColorText)]:
                color = label._text_color
                if color is None:
                    continue
                contrast = abs(color.lightness() - bg.lightness())
                assert contrast > 40, (
                    f"{label.text()!r} 的 {color.name()} 与底色 {bg.name()} "
                    f"明度只差 {contrast}，深色下几乎看不见"
                )

    def test_paint_path_takes_self_heal_branch(self, qapp, make, dark_mode):
        """不能走进 ``ColorText.paintEvent`` 的旁路。

        旁路（无显式色 / 图标模式 / wrap-anywhere）会交回 ``ElaText`` 的
        ``paintEvent``，而它开头就把 palette 刷回主题 ``BasicText`` ——
        显式色直接丢失。
        """
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        bubble = _tool_area(chat, mid)
        for panel in bubble.toolPanels():
            for label in [panel._title_label, *panel.findChildren(ColorText)]:
                assert label._text_color is not None
                # ``getElaIcon()`` 在 PyQt6 返回枚举成员（``None_`` 恒真），要显式比 0
                icon = label.getElaIcon()
                assert icon is None or int(getattr(icon, "value", icon)) == 0, (
                    "工具区不该有图标模式 ColorText"
                )
                assert not label.getIsWrapAnywhere(), (
                    "工具区不该有 wrap-anywhere ColorText（会绕过自愈分支）"
                )

    def test_subtitle_and_args_are_muted(self, qapp, make, dark_mode):
        """卡内副标题 / 参数摘要走 muted 系（与标题拉开层级，仍要可读）。"""
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        bubble = _tool_area(chat, mid)
        card = bubble.toolPanels()[-1].findChild(ToolCallCard)
        assert card is not None
        mode = eTheme.getThemeMode()
        assert card._subtitle_label.textColor() == muted_color(mode, 0.6)
        assert card._args_label.textColor() == muted_color(mode, 0.45)

    def test_error_tint_readable_on_dark(self, qapp, make, dark_mode):
        """失败工具卡的红色标题在深色下要够亮。"""
        chat = make(ElaChatWidget)
        mid = chat.beginAssistantMessage()
        bubble = _tool_area(chat, mid)
        card = bubble.toolPanels()[-1].findChild(ToolCallCard)
        assert card is not None
        mode = eTheme.getThemeMode()
        title = card._title_label.textColor()
        assert title == blend(text_color(mode), QColor("#e81123"), 0.45)
        assert title.lightness() > 60, "错误标题在深色下太暗"
