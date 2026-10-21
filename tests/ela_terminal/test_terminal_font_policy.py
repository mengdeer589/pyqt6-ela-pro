"""终端默认字体策略（bug 报告 §2）：中文系统用单族 CJK 字体。

Win7 上 Consolas 渲染 CJK 走逐字形 fallback（~3ms/行 + 进程级毒化），
多族「等宽 + CJK 后备」列表同样是慢路径 —— 默认必须是单族。
探测函数 monkeypatch 注入，不依赖跑测机器的真实 locale。
"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro import terminal_view as terminal_module
from pyqt6_ela_pro.terminal_view import ElaTerminalView

_CJK = "Microsoft YaHei"


@pytest.fixture
def cjk_system(monkeypatch):
    monkeypatch.setattr(terminal_module, "system_cjk_font_family", lambda: _CJK)
    return _CJK


@pytest.fixture
def non_cjk_system(monkeypatch):
    monkeypatch.setattr(terminal_module, "system_cjk_font_family", lambda: None)
    return None


class TestDefaultFontFamilies:
    def test_cjk_default_is_single_cjk_family(self, make, cjk_system):
        view = make(ElaTerminalView)
        assert view.fontFamilies() == [_CJK]
        assert view._edit.font().families()[0] == _CJK

    def test_non_cjk_default_is_consolas(self, make, non_cjk_system):
        view = make(ElaTerminalView)
        assert view.fontFamilies() == ["Consolas"]

    def test_empty_override_falls_back_to_default(self, make, cjk_system):
        view = make(ElaTerminalView)
        view.setFontFamilies(["Courier New"])
        assert view.fontFamilies() == ["Courier New"]
        view.setFontFamilies([])
        assert view.fontFamilies() == [_CJK]

    def test_explicit_override_wins(self, make, cjk_system):
        view = make(ElaTerminalView)
        view.setFontFamilies(["Cascadia Mono", "Microsoft YaHei"])
        assert view.fontFamilies() == ["Cascadia Mono", "Microsoft YaHei"]
        assert view._edit.font().families()[0] == "Cascadia Mono"
