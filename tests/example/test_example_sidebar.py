"""示例侧边栏分组守卫：一级 6 组、页面标题唯一且与 PAGE_TITLE 一致。"""

from __future__ import annotations

from pyqt6_ela_pro import example as example_pkg
from pyqt6_ela_pro.example.__main__ import _PAGE_GROUPS

_EXPECTED_GROUPS = (
    "基础组件",
    "数据与图表",
    "内容渲染",
    "AI 对话",
    "动效与图形",
    "窗口与系统",
)


def _entries():
    return [
        (group, title, page_cls)
        for group, _group_icon, pages in _PAGE_GROUPS
        for title, page_cls, _page_icon in pages
    ]


def test_group_names_and_order():
    assert tuple(group for group, _icon, _pages in _PAGE_GROUPS) == _EXPECTED_GROUPS


def test_every_group_has_pages():
    for group, _icon, pages in _PAGE_GROUPS:
        assert pages, f"分组「{group}」没有页面"


def test_page_titles_are_unique():
    titles = [title for _group, title, _cls in _entries()]
    assert len(titles) == len(set(titles)), "页面标题重复"


def test_page_title_matches_widget_title():
    for _group, title, page_cls in _entries():
        assert page_cls.PAGE_TITLE == title, f"{page_cls.__name__} 标题不一致"


def test_manifest_covers_all_exported_pages():
    exported = set(example_pkg.__all__) - {"ExamplePage"}
    registered = {page_cls.__name__ for _group, _title, page_cls in _entries()}
    assert registered == exported
