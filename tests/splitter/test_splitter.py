"""Tests for splitter module: ElaSplitter, ElaSplitterHandle, create_ela_splitter."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QBoxLayout, QWidget

from pyqt6_ela_pro.splitter import (
    ElaSplitter,
    ElaSplitterHandle,
    create_ela_splitter,
)


@pytest.fixture
def splitter(make):
    return make(ElaSplitter)


@pytest.fixture
def handle(make, splitter):
    """把手挂在 splitter 上（构造要求 parent）。"""
    return make(ElaSplitterHandle, Qt.Orientation.Horizontal, splitter)


class TestElaSplitter:
    """Test cases for ElaSplitter class."""

    def test_initialization_with_defaults(self, splitter):
        """Test splitter initializes with horizontal orientation."""
        assert splitter.orientation() == Qt.Orientation.Horizontal
        assert splitter._handle_width == 6

    def test_initialization_with_custom_orientation(self, make):
        """Test splitter accepts custom orientation."""
        splitter = make(ElaSplitter, orientation=Qt.Orientation.Vertical)
        assert splitter.orientation() == Qt.Orientation.Vertical

    def test_children_not_collapsible_by_default(self, splitter):
        """Test splitter children are not collapsible by default."""
        assert splitter.childrenCollapsible() is False

    def test_set_handle_width(self, splitter):
        """Test setHandleWidth updates handle width."""
        splitter.setHandleWidth(10)
        assert splitter._handle_width == 10
        assert splitter.handleWidth() == 10

    def test_set_grip_length(self, splitter):
        """Test set_grip_length updates grip length."""
        splitter.set_grip_length(50)
        assert splitter._grip_length == 50
        assert splitter.grip_length() == 50

    def test_create_handle_returns_ela_splitter_handle(self, splitter):
        """Test createHandle returns an ElaSplitterHandle."""
        assert isinstance(splitter.createHandle(), ElaSplitterHandle)

    def test_handle_inherits_grip_length(self, splitter):
        """Test createHandle sets grip length on handle."""
        splitter.set_grip_length(50)
        assert splitter.createHandle().get_grip_length() == 50


class TestElaSplitterHandle:
    """Test cases for ElaSplitterHandle class."""

    def test_initialization(self, handle, splitter):
        """Test handle initializes with orientation and parent."""
        assert handle.orientation() == Qt.Orientation.Horizontal
        assert handle.parent() is splitter

    def test_grip_length_roundtrip(self, handle):
        """Test set/get_grip_length round-trips."""
        handle.set_grip_length(24)
        assert handle._grip_length == 24
        assert handle.get_grip_length() == 24

    @pytest.mark.parametrize(
        ("attr", "expected"),
        [("_is_hover", False), ("_is_pressed", False)],
    )
    def test_initial_state(self, handle, attr, expected):
        assert getattr(handle, attr) == expected

    def test_has_theme_connection(self, handle):
        """Test handle connects to theme change signal."""
        assert hasattr(handle, "_onThemeChanged")

    def test_delete_later_disconnects_theme(self, handle, splitter):
        """Test deleteLater disconnects theme signal without error."""
        handle.deleteLater()
        splitter.deleteLater()


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
