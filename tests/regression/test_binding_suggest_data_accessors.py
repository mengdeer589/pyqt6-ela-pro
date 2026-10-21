"""守卫 PyQt6 绑定里 ``ElaSuggestBox.SuggestData`` 的可读性。

``SuggestData`` 是 ElaSuggestBox 的**嵌套 struct**：绑定生成器刻意把嵌套 struct 的
``ELA_VARIABLE`` 从外层类扫描里排除（否则会生成属于 ElaSuggestBox 的假访问器），
于是 Python 侧只拿到一个没有任何成员的载荷对象 —— ``suggestionClicked`` 的信号
参数读不出任何东西（``getSuggestData()`` 等一律 AttributeError），
「搜索框点击 → 读 ElaPageKey → navigation(key)」这条用法整条断掉。

修复在绑定工程侧：``PyElaWidgetTools/scripts/pyqt/gen_widgets.py`` 的
``suggest_data_accessors`` 按头文件的 ``ELA_VARIABLE`` 生成 get/set 声明，
重编 ``pyqt6-elawidgettools`` wheel 后生效。本测试只验数据通路，不构造真实弹层。

附带守 pyi（同一处修复暴露出来的老伤）：嵌套 struct 曾让 pyi 生成器在 struct 的
``};`` 处**提前收掉 ElaSuggestBox**（真方法全部丢失），并且把 ``QList<ElaSuggestBox::SuggestData>``
原样写进注解（整个 pyi 是语法错误）。现在 pyi 必须能被 ``ast.parse``。
"""

from __future__ import annotations

import ast
import pathlib
import zipfile

import pytest
from PyQt6ElaWidgetTools import (
    ElaIconType,
    ElaSuggestBox,
    ElaText,
    ElaWindow,
)

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_WHEELS_DIR = _ROOT / "PyElaWidgetTools" / "wheels" / "pyqt6-win7"

_ACCESSOR_PAIRS = (
    ("ElaIcon", "getElaIcon", "setElaIcon"),
    ("SuggestText", "getSuggestText", "setSuggestText"),
    ("SuggestKey", "getSuggestKey", "setSuggestKey"),
    ("SuggestData", "getSuggestData", "setSuggestData"),
)


@pytest.fixture(scope="module")
def env(qapp):
    """最小主窗口 + 一个页面（只验 getNavigationSuggestDataList 的载荷）。"""
    window = ElaWindow()
    page = ElaText("page", window)
    window.addPageNode("Page-A", page, ElaIconType.IconName.House)
    yield window, page
    window.deleteLater()
    qapp.processEvents()


def _shipped_pyi() -> str | None:
    """取交付轮子里那份 pyi 的文本（找不到就跳过）。"""
    wheels = sorted(_WHEELS_DIR.glob("pyqt6_elawidgettools-*.whl"))
    if not wheels:
        return None
    with zipfile.ZipFile(wheels[-1]) as zf:
        names = [n for n in zf.namelist() if n.endswith("ElaWidgetTools.pyi")]
        if not names:
            return None
        return zf.read(names[0]).decode("utf-8")


class TestSuggestDataAccessors:
    def test_accessors_exist(self):
        """四个 ELA_VARIABLE 字段都要有 get/set（缺一个 = 装到没重编的旧轮子）。"""
        missing = []
        for field, getter, setter in _ACCESSOR_PAIRS:
            for name in (getter, setter):
                if not hasattr(ElaSuggestBox.SuggestData, name):
                    missing.append(f"{field}: {name}")
        assert missing == [], (
            "ElaSuggestBox.SuggestData 缺访问器（装到未重编的旧轮子？）: "
            + ", ".join(missing)
        )

    def test_ctor_roundtrip(self):
        data = ElaSuggestBox.SuggestData(
            ElaIconType.IconName.House, "text-a", {"ElaPageKey": "key-a"}
        )
        assert data.getSuggestText() == "text-a"
        assert data.getSuggestData()["ElaPageKey"] == "key-a"
        assert data.getElaIcon() == ElaIconType.IconName.House

    def test_navigation_suggestion_carries_page_key(self, env):
        """``getNavigationSuggestDataList()`` 的载荷要能读出页面 key。"""
        window, page = env
        suggestions = window.getNavigationSuggestDataList()
        assert len(suggestions) == 1
        payload = suggestions[0].getSuggestData()
        assert isinstance(payload, dict)
        assert payload["ElaPageKey"] == page.property("ElaPageKey")
        assert suggestions[0].getSuggestText() == "Page-A"

    def test_signal_payload_is_readable(self, env, make):
        """``suggestionClicked`` 的载荷在槽里可读（emit 走一遍同一条通路）。"""
        window, page = env
        box = make(ElaSuggestBox, window)
        seen = []
        box.suggestionClicked.connect(seen.append)

        data = window.getNavigationSuggestDataList()[0]
        box.suggestionClicked.emit(data)

        assert len(seen) == 1
        assert seen[0].getSuggestData()["ElaPageKey"] == page.property("ElaPageKey")

    def test_add_suggestion_accepts_navigation_list(self, env, make):
        """整份导航建议列表要能直接喂给 ``addSuggestion``（搜索框接线路径）。"""
        window, _page = env
        box = make(ElaSuggestBox, window)
        keys = box.addSuggestion(window.getNavigationSuggestDataList())
        assert len(keys) == 1 and keys[0]


class TestShippedPyi:
    def test_pyi_parses(self):
        """交付轮子里的 pyi 必须是合法 Python（嵌套 struct 曾把它整份改坏）。"""
        src = _shipped_pyi()
        if src is None:
            pytest.skip("找不到 pyqt6 交付轮子或其中没有 pyi")
        ast.parse(src)

    def test_pyi_has_nested_suggest_data(self):
        src = _shipped_pyi()
        if src is None:
            pytest.skip("找不到 pyqt6 交付轮子或其中没有 pyi")
        assert "class SuggestData:" in src
        assert "def getSuggestData(self)" in src
