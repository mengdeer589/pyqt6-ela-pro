"""``_internal.system_cjk_font_family``：中文系统探测 + 进程级缓存。

Win7 上的 CJK 字体策略（bug 报告 §2/§3）靠它判定「中文系统 +
Microsoft YaHei 可用」；查询必须进程级缓存（``QFontDatabase.families()`` 慢），
且只在中文系统上查询。
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

    def test_chinese_system_without_font(self, monkeypatch):
        self._install(monkeypatch, "zh", ["Consolas"])
        assert _internal.system_cjk_font_family() is None

    def test_non_chinese_system_skips_font_query(self, monkeypatch):
        database = self._install(monkeypatch, "en", [_CJK])
        assert _internal.system_cjk_font_family() is None
        assert database.calls == 0
