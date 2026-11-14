"""Tests for splitter module: ElaSplitter (upstream binding) and create_ela_splitter."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QBoxLayout, QSplitter, QWidget

from PyQt6ElaWidgetTools import ElaSplitter as BindingElaSplitter

from pyqt6_ela_pro.splitter import ElaSplitter, create_ela_splitter


@pytest.fixture
def splitter(make):
    return make(ElaSplitter)


class TestElaSplitter:
    """``ElaSplitter`` 直接复用绑定层实现。"""

    def test_is_upstream_class(self):
        """项目导出与绑定层是同一个类（不再本地重写）。"""
        assert ElaSplitter is BindingElaSplitter
        assert issubclass(ElaSplitter, QSplitter)

    def test_initialization_with_defaults(self, splitter):
        """Test splitter initializes with horizontal orientation."""
        assert splitter.orientation() == Qt.Orientation.Horizontal

    def test_initialization_with_custom_orientation(self, make):
        """Test splitter accepts custom orientation."""
        splitter = make(ElaSplitter, Qt.Orientation.Vertical)
        assert splitter.orientation() == Qt.Orientation.Vertical

    def test_add_widgets_and_sizes(self, make, splitter):
        """分割器可正常添加子控件并设置比例。"""
        first, second = make(QWidget), make(QWidget)
        splitter.addWidget(first)
        splitter.addWidget(second)
        splitter.setSizes([100, 200])
        assert splitter.count() == 2
        assert len(splitter.sizes()) == 2


class TestCreateElaSplitter:
    """Test cases for create_ela_splitter function."""

    @pytest.mark.parametrize("count", [2, 4])
    def test_creates_splitter_with_n_widgets(self, make, count):
        """Test create_ela_splitter works with 2 or more widgets."""
        widgets = [make(QWidget) for _ in range(count)]

        splitter = create_ela_splitter(widgets)

        assert isinstance(splitter, ElaSplitter)
        assert splitter.count() == count

    def test_creates_vertical_splitter(self, make):
        """Test create_ela_splitter creates vertical splitter."""
        splitter = create_ela_splitter(
            [make(QWidget), make(QWidget)], orientation=Qt.Orientation.Vertical
        )
        assert splitter.orientation() == Qt.Orientation.Vertical

    def test_with_sizes_parameter(self, make):
        """Test create_ela_splitter accepts sizes parameter."""
        splitter = create_ela_splitter([make(QWidget), make(QWidget)], sizes=[200, 300])
        assert len(splitter.sizes()) == 2

    @pytest.mark.parametrize(
        ("widgets", "sizes", "message"),
        [
            ([], None, "至少需要 2 个组件"),
            (None, None, "至少需要 2 个组件"),
        ],
        ids=["empty", "single"],
    )
    def test_raises_on_too_few_widgets(self, make, widgets, sizes, message):
        """Test create_ela_splitter raises ValueError with fewer than 2 widgets."""
        if widgets is None:
            widgets = [make(QWidget)]
        with pytest.raises(ValueError, match=message):
            create_ela_splitter(widgets, sizes=sizes)

    def test_sizes_wrong_length_raises(self, make):
        """Test create_ela_splitter raises on mismatched sizes length."""
        with pytest.raises(ValueError, match="sizes 列表长度"):
            create_ela_splitter([make(QWidget), make(QWidget)], sizes=[100])

    def test_parent_auto_detected_and_inserted_into_layout(self, make):
        """Test parent auto-detection and layout insertion."""
        container = make(QWidget)
        layout = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        container.setLayout(layout)

        children = [make(QWidget) for _ in range(3)]
        for child in children:
            layout.addWidget(child)

        splitter = create_ela_splitter(children[:2])

        assert splitter.parentWidget() is container
        assert layout.indexOf(splitter) == 0
        assert splitter.count() == 2

    def test_parent_auto_detected_parents_splitter_but_requires_mount(self, make):
        """parent 没有布局：splitter 不会被挂载，必须显式告警（F9）。

        返回的 splitter 以 container 为父，但没有任何布局把它摆出来（传入的
        widgets 已被 reparent 进去、从界面上消失）—— 调用方需自行把返回值
        挂进布局。行为本身保留（空图比报错更难排查），但要喊一声。
        """
        container = make(QWidget)
        with pytest.warns(RuntimeWarning, match="没有布局"):
            splitter = create_ela_splitter(
                [make(QWidget, container), make(QWidget, container)]
            )
        assert splitter.parentWidget() is container
        assert splitter.count() == 2
