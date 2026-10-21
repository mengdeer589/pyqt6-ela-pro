"""CJK 系统代码字体策略（bug 报告 §3）：默认代码字体与字符格式单族化。

Win7 上多族字体列表本身是慢 shaping 路径（逐字形族匹配，与各族是否 CJK
无关）且进程级毒化；中文系统必须收成**单族**。探测函数用 monkeypatch
注入，避免依赖跑测机器的真实 locale。
"""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QFont, QFontDatabase, QRawFont

from pyqt6_ela_pro import ela_markdown_viewer as viewer_module
from pyqt6_ela_pro._internal import missingGlyphFont
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer

_CJK = "Microsoft YaHei"


@pytest.fixture
def cjk_system(monkeypatch):
    monkeypatch.setattr(viewer_module, "system_cjk_font_family", lambda: _CJK)
    monkeypatch.setattr(viewer_module, "_DEFAULT_CODE_FONT_FAMILY", None)
    return _CJK


@pytest.fixture
def non_cjk_system(monkeypatch):
    monkeypatch.setattr(viewer_module, "system_cjk_font_family", lambda: None)
    monkeypatch.setattr(viewer_module, "_DEFAULT_CODE_FONT_FAMILY", None)
    return None


class TestDefaultCodeFontFamily:
    def test_cjk_system_uses_cjk_font(self, cjk_system):
        assert viewer_module._default_code_font_family() == _CJK

    def test_non_cjk_system_uses_preferred_monospace(self, non_cjk_system):
        family = viewer_module._default_code_font_family()
        assert family
        assert family in viewer_module._PREFERRED_CODE_FONTS

    def test_cjk_path_skips_families_scan(self, cjk_system, monkeypatch):
        """中文系统不扫全量字体族（结果来自 CJK 探测的进程级缓存）。"""

        class _Boom:
            @staticmethod
            def families():
                raise AssertionError("中文系统不应扫描全量字体族")

        monkeypatch.setattr(viewer_module, "QFontDatabase", _Boom)
        assert viewer_module._default_code_font_family() == _CJK

    def test_result_cached(self, cjk_system, monkeypatch):
        calls = {"n": 0}

        def counting():
            calls["n"] += 1
            return _CJK

        monkeypatch.setattr(viewer_module, "system_cjk_font_family", counting)
        assert viewer_module._default_code_font_family() == _CJK
        assert viewer_module._default_code_font_family() == _CJK
        assert calls["n"] == 1


class TestProducedGlyphs:
    """库自产进 QTextDocument 的标记必须是 CJK 主字体 cmap 内字形（bug #20）。

    旧标记 U+2610/U+2611（☐/☑）与 U+25B8/U+25BE（▸/▾）都不在雅黑 cmap，
    Win7 上会走逐字形 fallback 并进程级毒化。
    """

    @pytest.mark.parametrize("char", ["□", "■", "+", "−"])
    def test_marker_supported_by_cjk_font(self, qapp, cjk_system, char):
        if _CJK not in QFontDatabase.families():
            pytest.skip(f"本机没有 {_CJK}")
        raw = QRawFont.fromFont(QFont(cjk_system, 12))
        if not raw.isValid():
            pytest.skip("QRawFont 不可用")
        assert raw.supportsCharacter(char)

    def test_task_markers_use_covered_glyphs(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("- [ ] todo\n- [x] done\n")

        text = viewer.toPlainText()
        assert "□" in text and "■" in text
        assert "\u2610" not in text and "\u2611" not in text

    def test_fold_marker_uses_covered_glyph(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        # 用转义拼标签：避免工具链把尖括号标签当成控制标签吞掉
        source = (
            "前置\n\n\x3cthink\x3e\n内部推理\n\x3c/think\x3e\n\n后置"
        )
        viewer.setMarkdown(source)

        text = viewer.toPlainText()
        assert "+ 思考过程" in text
        assert "\u25b8" not in text and "\u25be" not in text


class TestMissingGlyphFallback:
    """主字体缺字形时给字符套单族符号字体（不改文本），bug #20。"""

    @staticmethod
    def _families_for(viewer, char):
        block = viewer.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.text() == char:
                    return fragment.charFormat().fontFamilies()
                iterator += 1
            block = block.next()
        return []

    @pytest.fixture(autouse=True)
    def _requires_candidate(self):
        if viewer_module.system_cjk_font_family() is None:
            pytest.skip("非中文系统（缺字形兜底默认关闭）")
        if missingGlyphFont("\u2194") is None:
            pytest.skip("本机没有覆盖 U+2194 的候选符号字体")

    def test_missing_glyph_gets_single_symbol_font(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("a \u2194 b\n")

        expected = missingGlyphFont("\u2194")
        assert self._families_for(viewer, "\u2194") == [expected]

    def test_text_is_unchanged(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("a \u2194 b \u21d2 c\n")

        text = viewer.toPlainText()
        assert "\u2194" in text and "\u21d2" in text

    def test_can_be_disabled(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMissingGlyphFallbackEnabled(False)
        viewer.setMarkdown("a \u2194 b\n")

        assert self._families_for(viewer, "\u2194") == []

    def test_disable_rerenders_existing_text(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.resize(420, 300)
        viewer.show()
        qapp.processEvents()
        viewer.setMarkdown("a \u2194 b\n")
        assert self._families_for(viewer, "\u2194") == [
            missingGlyphFont("\u2194")
        ]

        viewer.setMissingGlyphFallbackEnabled(False)
        qapp.processEvents()
        assert self._families_for(viewer, "\u2194") == []

    def test_covered_cjk_not_overridden(self, qapp, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setMarkdown("\u4e2d\u6587\n")

        assert self._families_for(viewer, "\u4e2d") == []


class TestCodeFormatFamilies:
    def test_single_family_on_cjk(self, cjk_system):
        assert viewer_module._code_format_families("Consolas") == ["Consolas"]
        assert viewer_module._code_format_families(_CJK) == [_CJK]

    def test_three_families_without_cjk(self, non_cjk_system):
        assert viewer_module._code_format_families("Consolas") == [
            "Consolas",
            "Microsoft YaHei UI",
            "Microsoft YaHei",
        ]

    def test_viewer_renders_single_family_on_cjk(self, qapp, make, cjk_system):
        v = make(ElaMarkdownViewer)
        assert v.codeFontFamily() == _CJK
        assert v._code_format().fontFamilies() == [_CJK]
        assert v._code_text_format().fontFamilies() == [_CJK]

        v.setMarkdown("行内 `code` 与\n\n```python\nx = 1\n```\n")
        seen = []
        block = v.document().begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.charFormat().fontFamilies():
                    seen.append(list(fragment.charFormat().fontFamilies()))
                iterator += 1
            block = block.next()
        assert seen, "文档里应有带字体族的片段（代码）"
        assert all(families == [_CJK] for families in seen)

    def test_host_override_stays_single_family_on_cjk(self, qapp, make, cjk_system):
        v = make(ElaMarkdownViewer)
        v.setCodeFontFamily("Courier New")
        assert v._code_format().fontFamilies() == ["Courier New"]
        assert v._code_text_format().fontFamilies() == ["Courier New"]
