"""``_internal.glyphCovers``：GDI 只登记本地化族名时仍要查到真实 cmap。"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro import _internal


class _StubQFont:
    def __init__(self, name):
        self.name = name

    def exactMatch(self):
        return False


class _StubRawFont:
    def __init__(self, family, codepoints):
        self._family = family
        self._codepoints = codepoints

    @classmethod
    def fromFont(cls, font):
        if font.name in ("Microsoft YaHei", "微软雅黑"):
            return cls("微软雅黑", {0x41, 0x2460, 0x25A1})
        return cls("Tahoma", {0x41})

    def isValid(self):
        return True

    def familyName(self):
        return self._family

    def supportsCharacter(self, codepoint):
        return codepoint in self._codepoints


@pytest.fixture(autouse=True)
def _gdi_font_registry(monkeypatch):
    monkeypatch.setattr(_internal, "_font_family_set", {"微软雅黑", "宋体"})
    monkeypatch.setattr(_internal, "QFont", _StubQFont)
    monkeypatch.setattr(_internal, "QRawFont", _StubRawFont)
    monkeypatch.setattr(_internal, "_glyph_raw_fonts", {})
    monkeypatch.setattr(_internal, "_glyph_coverage", {})
    monkeypatch.setattr(_internal, "_glyph_fallback", {})


def test_english_primary_uses_localized_alias():
    assert _internal.glyphCovers("Microsoft YaHei", "\u2460") is True
    assert _internal.glyphCovers("Microsoft YaHei", "\u25a1") is True


def test_unknown_family_is_not_covered_by_default_font():
    assert _internal.glyphCovers("NoSuchFontXYZ", "A") is False
