"""``ElaPivot.sizeHint()`` 必须随页签内容增长。

上游（ElaWidgetTools）原先没覆写 ``sizeHint()``，宽高落到 ``QAbstractScrollArea``
默认的 256x192：放进「HBox + addStretch」这类只按 sizeHint 分配宽度的容器时，
第 4 个页签会被裁到视口外（横向滚动条又是 AlwaysOff）。这里钉住修复后的契约。
"""

from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QListView, QWidget
from PyQt6ElaWidgetTools import ElaPivot

TITLES = ("Key 管理", "MCP 服务", "问答技能", "个人知识库")


def _view(pivot: ElaPivot) -> QListView:
    view = pivot.findChild(QListView)
    assert view is not None
    return view


def _content_width(pivot: ElaPivot) -> int:
    """页签总宽 + 视口两侧边框（与 C++ 侧 sizeHint 的计算口径一致）。"""
    view = _view(pivot)
    total = view.frameWidth() * 2
    for row in range(view.model().rowCount()):
        total += view.sizeHintForIndex(view.model().index(row, 0)).width()
    return total


def test_size_hint_matches_content(qapp, make):
    pivot = make(ElaPivot)
    assert pivot.sizeHint().width() == _content_width(pivot)  # 空：只剩边框

    for title in TITLES:
        pivot.appendPivot(title)
    assert pivot.sizeHint().width() == _content_width(pivot)
    assert pivot.sizeHint().width() > 0


def test_size_hint_shrinks_when_items_removed(qapp, make):
    pivot = make(ElaPivot)
    for title in TITLES:
        pivot.appendPivot(title)
    full = pivot.sizeHint().width()

    pivot.removePivot(TITLES[-1])
    assert pivot.sizeHint().width() < full
    pivot.clearPivot()
    assert pivot.sizeHint().width() == _content_width(pivot)
    assert pivot.getPivotTitle() == []


def test_size_hint_follows_text_pixel_size(qapp, make):
    pivot = make(ElaPivot)
    for title in TITLES:
        pivot.appendPivot(title)
    pivot.setTextPixelSize(12)
    small = pivot.sizeHint().width()
    pivot.setTextPixelSize(20)
    assert pivot.sizeHint().width() > small


def test_all_tabs_visible_in_stretched_row(qapp, make):
    """真实症状：HBox 里靠 ``addStretch`` 吃余量时，pivot 只能拿到 sizeHint 宽。"""
    host = make(QWidget)
    host.resize(800, 200)
    layout = QHBoxLayout(host)
    pivot = make(ElaPivot)
    pivot.setTextPixelSize(14)
    for title in TITLES:
        pivot.appendPivot(title)
    layout.addWidget(pivot)
    layout.addStretch(1)
    host.show()
    qapp.processEvents()

    view = _view(pivot)
    assert pivot.width() == pivot.sizeHint().width()
    assert pivot.width() >= _content_width(pivot)
    right_edge = view.viewport().width()
    for row in range(view.model().rowCount()):
        rect = view.visualRect(view.model().index(row, 0))
        assert rect.x() + rect.width() <= right_edge, f"第 {row} 个页签被裁到视口外"


def test_layout_refreshes_after_append(qapp, make):
    """追加页签后必须通知父布局重算（``updateGeometry``）。"""
    host = make(QWidget)
    host.resize(800, 200)
    layout = QHBoxLayout(host)
    pivot = make(ElaPivot)
    layout.addWidget(pivot)
    layout.addStretch(1)
    host.show()
    qapp.processEvents()
    empty_width = pivot.width()

    pivot.setTextPixelSize(14)
    for title in TITLES:
        pivot.appendPivot(title)
    qapp.processEvents()

    assert pivot.width() > empty_width
    assert pivot.width() == pivot.sizeHint().width()
