"""markdown 主题测试：内置注册表 / 切换 / 默认值 / 自定义注册。"""

from __future__ import annotations

from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro import (
    ElaMarkdownViewer,
    defaultMarkdownTheme,
    markdownThemes,
    registerMarkdownTheme,
    setDefaultMarkdownTheme,
    unregisterMarkdownTheme,
)
from pyqt6_ela_pro.ela_markdown_viewer import _MD_THEMES


def _fragment_color(viewer: ElaMarkdownViewer, needle: str) -> str:
    """取文档中包含 ``needle`` 的第一个文本片段的前景色。"""
    block = viewer.document().begin()
    while block.isValid():
        if needle in block.text():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and needle in fragment.text():
                    return fragment.charFormat().foreground().color().name()
                iterator += 1
        block = block.next()
    return ""


def _shown(qapp) -> ElaMarkdownViewer:
    """构造并显示：主题 / 配色族变更在隐藏时不重建文档，断言渲染结果需可见状态。"""
    v = ElaMarkdownViewer()
    v.show()
    qapp.processEvents()
    return v


class TestBuiltinThemes:
    def test_builtin_names(self):
        names = markdownThemes()
        for expected in ("opencode", "github", "solarized", "dracula"):
            assert expected in names

    def test_default_is_opencode(self):
        assert defaultMarkdownTheme() == "opencode"
        v = ElaMarkdownViewer()
        assert v.markdownTheme() == "opencode"
        v.deleteLater()

    def test_switch_recolors_content(self, qapp):
        v = _shown(qapp)
        v.setMarkdown("## 标题\n\n[链接](https://example.com) 与 `code`")
        assert _fragment_color(v, "标题") == "#9d5d00"  # opencode 浅色

        assert v.setMarkdownTheme("github") is True
        assert v.markdownTheme() == "github"
        assert _fragment_color(v, "标题") == "#1f2328"
        assert _fragment_color(v, "链接") == "#0969da"

        assert v.setMarkdownTheme("dracula") is True
        assert _fragment_color(v, "标题") == "#644ac9"
        v.deleteLater()

    def test_unknown_theme_rejected(self):
        v = ElaMarkdownViewer()
        assert v.setMarkdownTheme("nosuch") is False
        assert v.markdownTheme() == "opencode"
        v.deleteLater()

    def test_dark_variant_selected(self, qapp):

        v = _shown(qapp)
        v.setMarkdown("## 标题")
        assert _fragment_color(v, "标题") == "#9d5d00"

        v._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert _fragment_color(v, "标题") == "#9d7cd8"
        v.deleteLater()

    def test_default_theme_applies_to_new_viewers(self, qapp):
        assert setDefaultMarkdownTheme("solarized") is True
        try:
            v = ElaMarkdownViewer()
            assert v.markdownTheme() == "solarized"
            v.setMarkdown("## 标题")
            assert _fragment_color(v, "标题") == "#b58900"
            v.deleteLater()
        finally:
            assert setDefaultMarkdownTheme("opencode") is True

    def test_set_default_rejects_unknown(self):
        assert setDefaultMarkdownTheme("nosuch") is False
        assert defaultMarkdownTheme() == "opencode"


class TestListAndMarkTheming:
    """列表文字 / 任务勾选框 / ==高亮== 与 markdown 主题的关系。

    契约演进：

    - 早期列表文字一直用 eTheme 正文色（不跟主题）；
    - 中间一版让列表**整块**跟随 ``list`` 色 —— 但 Qt 5.15 的 bullet 由
      ``context.palette.Text`` 绘制、字符格式染不上（``drawListItem``），
      结果是「文字变色、符号还是原色」，浅色 opencode 下叠出整页橙黄；
    - 现在：列表**文字**固定正文色，``list`` 语义只服务任务勾选框
      （``☑ / ☐`` 是文本字形、能染色）。
    """

    SOURCE = "- 无序项\n1. 有序项\n- [x] 任务项\n\n普通正文 ==高亮==\n"

    def test_all_builtin_themes_define_new_keys(self):

        for name in ("opencode", "github", "solarized", "dracula"):
            for variant in ("light", "dark"):
                semantic = _MD_THEMES[name][variant]["semantic"]
                assert semantic["list"].startswith("#"), (name, variant)
                assert semantic["mark"].startswith("#"), (name, variant)

    def test_list_text_stays_neutral(self, qapp):
        """列表文字固定正文色：``list`` 语义不再染列表文字（只染勾选框）。"""
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)
        assert _fragment_color(v, "无序项") == "#000000"
        assert _fragment_color(v, "有序项") == "#000000"
        assert _fragment_color(v, "普通正文") == "#000000"

        for theme in ("solarized", "dracula", "github"):
            assert v.setMarkdownTheme(theme) is True
            assert _fragment_color(v, "无序项") == "#000000"
            assert _fragment_color(v, "有序项") == "#000000"
        v.deleteLater()

    def test_task_marker_follows_theme(self, qapp):
        v = _shown(qapp)
        v.setMarkdown(self.SOURCE)
        assert v.setMarkdownTheme("github") is True
        doc = v.document()
        block = doc.begin()
        found = []
        while block.isValid():
            if block.textList() is not None and "☑" in block.text():
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    if fragment.isValid() and fragment.text().strip() == "☑":
                        found.append(fragment.charFormat().foreground().color().name())
                    iterator += 1
            block = block.next()
        assert found == ["#1f2328"]  # github 浅色 list 色
        v.deleteLater()

    def test_mark_background_follows_theme(self, qapp):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)
        opencode_mark = v._mark_bg.name()
        assert v.setMarkdownTheme("solarized") is True
        # 高亮底色由主题 mark 色与背景混合而来，换主题必须跟着变
        assert v._mark_bg.name() != opencode_mark
        assert v._md_mark_color.name() == "#b58900"
        v.deleteLater()

    def test_custom_theme_can_override_list_marker(self, qapp):
        registerMarkdownTheme(
            "unit-test-list",
            light={"semantic": {"list": "#0f0f0f"}},
            dark={"semantic": {"list": "#f0f0f0"}},
        )
        try:
            v = _shown(qapp)
            v.setMarkdown("- [x] 项")
            assert v.setMarkdownTheme("unit-test-list") is True
            # list 色现在只落在勾选框字形上；文字不再被它染色
            assert _fragment_color(v, "☑") == "#0f0f0f"
            assert _fragment_color(v, "项") != "#0f0f0f"
            v.deleteLater()
        finally:
            assert unregisterMarkdownTheme("unit-test-list") is True


class TestCustomThemes:
    def test_register_switch_and_unregister(self, qapp):
        registerMarkdownTheme(
            "unit-test-theme",
            light={"semantic": {"link": "#123456"}},
            dark={"semantic": {"link": "#654321"}},
        )
        try:
            assert "unit-test-theme" in markdownThemes()
            v = _shown(qapp)
            v.setMarkdown("[链接](https://example.com)")
            assert v.setMarkdownTheme("unit-test-theme") is True
            assert _fragment_color(v, "链接") == "#123456"
            # 未指定的键合并自 opencode 默认主题
            assert _fragment_color(v, "链接") != ""
            v.deleteLater()
        finally:
            assert unregisterMarkdownTheme("unit-test-theme") is True
        assert "unit-test-theme" not in markdownThemes()

    def test_partial_theme_merges_syntax(self, qapp):
        registerMarkdownTheme(
            "unit-test-syntax",
            light={"syntax": {"keyword": "#010203"}},
        )
        try:
            v = ElaMarkdownViewer()
            v.setMarkdownTheme("unit-test-syntax")
            assert v._token_palette["keyword"] == "#010203"
            # 未覆盖的 token 仍来自 opencode
            assert v._token_palette["string"] == "#3d9a57"
            v.deleteLater()
        finally:
            unregisterMarkdownTheme("unit-test-syntax")

    def test_opencode_cannot_be_unregistered(self):
        assert unregisterMarkdownTheme("opencode") is False
        assert "opencode" in markdownThemes()

    def test_code_token_override_survives_theme_switch(self, qapp):
        v = ElaMarkdownViewer()
        v.setCodeTokenColors({"keyword": "#abcdef"})
        assert v.codeTokenColors()["keyword"] == "#abcdef"
        v.setMarkdownTheme("github")
        assert v.codeTokenColors()["keyword"] == "#abcdef"
        v.setCodeTokenColors(None)
        assert v.codeTokenColors()["keyword"] == "#cf222e"  # github 浅色
        v.deleteLater()
