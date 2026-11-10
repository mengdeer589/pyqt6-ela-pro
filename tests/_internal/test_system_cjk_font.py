"""``_internal.system_cjk_font_family``：中文系统探测 + 进程级缓存。

Win7 上的 CJK 字体策略（bug 报告 §2/§3）靠它判定「中文系统 + 雅黑可用」；
GDI 中文系统只登记本地化族名（「微软雅黑」），查询必须进程级缓存
（``QFontDatabase.families()`` 慢），且只在中文系统上查询。
"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro import _internal

_CJK = "Microsoft YaHei"


class _StubQLocale:
    """只实现被探测函数用到的部分：``system().language()`` 与 ``Language``。"""

    class Language:
        Chinese = "zh"
        English = "en"

    def __init__(self, language):
        self._language = language

    def system(self):
        return self

    def language(self):
        return self._language


class _StubQFontDatabase:
    def __init__(self, families):
        self.families_result = families
        self.calls = 0

    def families(self):
        self.calls += 1
        return list(self.families_result)


class _StubQFont:
    def __init__(self, name):
        self.name = name

    def exactMatch(self):
        return False


class _StubRawFont:
    family_name = "Tahoma"

    @classmethod
    def fromFont(cls, font):
        return cls()

    def isValid(self):
        return True

    def familyName(self):
        return self.family_name


class TestSystemCjkFontFamily:
    @pytest.fixture(autouse=True)
    def reset_cache(self, monkeypatch):
        monkeypatch.setattr(_internal, "_cjk_ui_font_probed", False)
        monkeypatch.setattr(_internal, "_cjk_ui_font_family", None)
        yield

    def _install(self, monkeypatch, language, families):
        monkeypatch.setattr(_internal, "QLocale", _StubQLocale(language))
        database = _StubQFontDatabase(families)
        monkeypatch.setattr(_internal, "QFontDatabase", database)
        return database

    def test_chinese_system_with_font(self, monkeypatch):
        database = self._install(monkeypatch, "zh", [_CJK, "Consolas"])
        assert _internal.system_cjk_font_family() == _CJK
        assert database.calls == 1

    def test_result_is_cached(self, monkeypatch):
        database = self._install(monkeypatch, "zh", [_CJK])
        assert _internal.system_cjk_font_family() == _CJK
        assert _internal.system_cjk_font_family() == _CJK
        assert database.calls == 1

    def test_chinese_system_with_localized_font(self, monkeypatch):
        database = self._install(monkeypatch, "zh", ["微软雅黑", "Consolas"])
        assert _internal.system_cjk_font_family() == "微软雅黑"
        assert database.calls == 1

    def test_english_name_preferred_when_both_listed(self, monkeypatch):
        self._install(monkeypatch, "zh", ["Microsoft YaHei", "微软雅黑"])
        assert _internal.system_cjk_font_family() == "Microsoft YaHei"

    def test_chinese_system_without_font(self, monkeypatch):
        self._install(monkeypatch, "zh", ["Consolas"])
        assert _internal.system_cjk_font_family() is None

    def test_non_chinese_system_skips_font_query(self, monkeypatch):
        database = self._install(monkeypatch, "en", [_CJK])
        assert _internal.system_cjk_font_family() is None
        assert database.calls == 0


class TestFontFamilyAvailable:
    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch):
        monkeypatch.setattr(
            _internal, "_font_family_set", {"微软雅黑", "宋体", "新宋体"}
        )
        monkeypatch.setattr(_internal, "QFont", _StubQFont)
        monkeypatch.setattr(_internal, "QRawFont", _StubRawFont)
        yield

    def test_localized_alias_is_available(self):
        assert _internal.fontFamilyAvailable("Microsoft YaHei") is True
        assert _internal.fontFamilyAvailable("SimSun") is True
        assert _internal.fontFamilyAvailable("NSimSun") is True

    def test_alias_is_case_insensitive(self):
        assert _internal.fontFamilyAvailable("MICROSOFT YAHEI") is True

    def test_unknown_family_is_unavailable(self):
        assert _internal.fontFamilyAvailable("NoSuchFontXYZ") is False
        assert _internal.fontFamilyAvailable("") is False

    def test_raw_family_name_is_available(self, monkeypatch):
        monkeypatch.setattr(_StubRawFont, "family_name", "LXGW WenKai")
        assert _internal.fontFamilyAvailable("LXGW WenKai") is True
