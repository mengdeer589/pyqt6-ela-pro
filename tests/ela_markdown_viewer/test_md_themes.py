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
from pyqt6_ela_pro.ela_markdown_viewer import (
    _MD_LAYOUT_DEFAULTS,
    _MD_THEMES,
    _md_layout_spec,
)


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
        for expected in (
            "bear",
            "lark",
            "typo",
            "vue",
            "ayu",
            "solarized",
            "indigo",
        ):
            assert expected in names

    def test_default_is_bear(self):
        assert defaultMarkdownTheme() == "bear"
        v = ElaMarkdownViewer()
        assert v.markdownTheme() == "bear"
        v.deleteLater()

    def test_switch_recolors_content(self, qapp):
        v = _shown(qapp)
        v.setMarkdown("## 标题\n\n[链接](https://example.com) 与 `code`")
        assert _fragment_color(v, "标题") == "#262626"  # bear 浅色

        assert v.setMarkdownTheme("lark") is True
        assert v.markdownTheme() == "lark"
        assert _fragment_color(v, "标题") == "#1f2329"
        assert _fragment_color(v, "链接") == "#3370ff"

        assert v.setMarkdownTheme("vue") is True
        assert _fragment_color(v, "标题") == "#34495e"
        v.deleteLater()

    def test_syntax_cache_is_theme_scoped(self, qapp):
        v = ElaMarkdownViewer()
        v.setMarkdown("```python\nimport os\n```")
        variant = "dark" if v._is_dark_theme else "light"
        bear = _fragment_color(v, "import")
        assert bear == _MD_THEMES["bear"][variant]["syntax"]["keyword"]

        assert v.setMarkdownTheme("vue") is True
        v.setMarkdown("```python\nimport os\n```")
        vue = _fragment_color(v, "import")
        assert vue == _MD_THEMES["vue"][variant]["syntax"]["keyword"]
        assert vue != bear
        v.deleteLater()

    def test_unknown_theme_rejected(self):
        v = ElaMarkdownViewer()
        assert v.setMarkdownTheme("nosuch") is False
        assert v.markdownTheme() == "bear"
        v.deleteLater()

    def test_dark_variant_selected(self, qapp):

        v = _shown(qapp)
        v.setMarkdown("## 标题")
        assert _fragment_color(v, "标题") == "#262626"

        v._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert _fragment_color(v, "标题") == "#cbdee5"
        v.deleteLater()

    def test_default_theme_applies_to_new_viewers(self, qapp):
        assert setDefaultMarkdownTheme("solarized") is True
        try:
            v = ElaMarkdownViewer()
            assert v.markdownTheme() == "solarized"
            v.setMarkdown("## 标题")
            assert _fragment_color(v, "标题") == "#3b4f54"
            v.deleteLater()
        finally:
            assert setDefaultMarkdownTheme("bear") is True

    def test_set_default_rejects_unknown(self):
        assert setDefaultMarkdownTheme("nosuch") is False
        assert defaultMarkdownTheme() == "bear"


class TestListAndMarkTheming:
    """列表文字 / 任务勾选框 / ==高亮== 与 markdown 主题的关系。

    契约演进：

    - 早期列表文字一直用 eTheme 正文色（不跟主题）；
    - 中间一版让列表**整块**跟随 ``list`` 色 —— 但 Qt 5.15 的 bullet 由
      ``context.palette.Text`` 绘制、字符格式染不上（``drawListItem``），
      结果是「文字变色、符号还是原色」，浅色高强调主题下叠出整页橙黄；
    - 现在：列表**文字**固定正文色，``list`` 语义只服务任务勾选框
      （``■ / □`` 是文本字形、能染色）。
    """

    SOURCE = "- 无序项\n1. 有序项\n- [x] 任务项\n\n普通正文 ==高亮==\n"

    def test_all_builtin_themes_define_new_keys(self):

        for name in (
            "bear",
            "lark",
            "typo",
            "vue",
            "ayu",
            "solarized",
            "indigo",
        ):
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

        for theme in ("lark", "vue", "indigo"):
            assert v.setMarkdownTheme(theme) is True
            assert _fragment_color(v, "无序项") == "#000000"
            assert _fragment_color(v, "有序项") == "#000000"
        v.deleteLater()

    def test_task_marker_follows_theme(self, qapp):
        v = _shown(qapp)
        v.setMarkdown(self.SOURCE)
        assert v.setMarkdownTheme("lark") is True
        doc = v.document()
        block = doc.begin()
        found = []
        while block.isValid():
            if block.textList() is not None and "■" in block.text():
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    if fragment.isValid() and fragment.text().strip() == "■":
                        found.append(fragment.charFormat().foreground().color().name())
                    iterator += 1
            block = block.next()
        assert found == ["#3370ff"]  # lark 浅色 list 色
        v.deleteLater()

    def test_mark_background_follows_theme(self, qapp):
        v = ElaMarkdownViewer()
        v.setMarkdown(self.SOURCE)
        bear_mark = v._mark_bg.name()
        assert v.setMarkdownTheme("solarized") is True
        # 高亮底色由主题 mark 色与背景混合而来，换主题必须跟着变
        assert v._mark_bg.name() != bear_mark
        assert v._md_mark_color.name() == "#caff93"
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
            assert _fragment_color(v, "■") == "#0f0f0f"
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
            # 未指定的键合并自默认主题
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
            # 未覆盖的 token 仍来自默认主题
            assert v._token_palette["string"] == "#b43d15"
            v.deleteLater()
        finally:
            unregisterMarkdownTheme("unit-test-syntax")

    def test_builtin_themes_cannot_be_unregistered(self):
        for name in ("bear", "lark", "vue"):
            assert unregisterMarkdownTheme(name) is False
            assert name in markdownThemes()

    def test_code_token_override_survives_theme_switch(self, qapp):
        v = ElaMarkdownViewer()
        v.setCodeTokenColors({"keyword": "#abcdef"})
        assert v.codeTokenColors()["keyword"] == "#abcdef"
        v.setMarkdownTheme("lark")
        assert v.codeTokenColors()["keyword"] == "#abcdef"
        v.setCodeTokenColors(None)
        assert v.codeTokenColors()["keyword"] == "#cf222e"  # lark 浅色
        v.deleteLater()

    def test_layout_defaults_and_overrides(self):
        assert _md_layout_spec("bear")["body_line_height"] == 165.0
        assert _md_layout_spec("lark")["body_line_height"] == 168.0
        assert _md_layout_spec("typo")["body_line_height"] == 180.0
        assert _md_layout_spec("vue")["table"]["zebra"] is True
        assert _md_layout_spec("indigo")["heading_rule"]["levels"] == (1, 2)
        assert _md_layout_spec("bear")["heading_rule"]["levels"] == ()

    def test_theme_switch_updates_layout(self, qapp):
        v = ElaMarkdownViewer()
        assert v._md_layout["body_line_height"] == 165.0

        assert v.setMarkdownTheme("lark") is True
        assert v._md_layout["body_line_height"] == 168.0

        assert v.setMarkdownTheme("vue") is True
        assert v._md_layout["table"]["zebra"] is True
        assert v.tableZebra() is True

        assert v.setMarkdownTheme("bear") is True
        assert v.tableZebra() is False
        v.deleteLater()

    def test_register_custom_layout(self):
        registerMarkdownTheme(
            "unit-test-layout",
            layout={"body_line_height": 200.0, "table": {"zebra": True}},
        )
        try:
            layout = _md_layout_spec("unit-test-layout")
            assert layout["body_line_height"] == 200.0
            assert layout["table"]["zebra"] is True
            assert layout["paragraph_margin"] == _MD_LAYOUT_DEFAULTS["paragraph_margin"]
        finally:
            unregisterMarkdownTheme("unit-test-layout")
