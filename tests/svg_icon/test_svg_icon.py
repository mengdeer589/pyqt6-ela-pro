"""Tests for svg_icon module: svg_to_icon, svg_to_pixmap, ElaSvgIconLoader."""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QIcon, QPixmap

from pyqt6_ela_pro.svg_icon import (
    svg_to_icon,
    svg_to_pixmap,
    ElaSvgIconLoader,
    svg_icon_loader,
)


class TestSvgFunctions:
    """Test cases for svg_to_icon and svg_to_pixmap functions."""

    def test_svg_to_icon_returns_qicon(self):
        """Test svg_to_icon returns QIcon instance."""
        svg_data = (
            '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#FF0000"/></svg>'
        )
        icon = svg_to_icon(svg_data, size=30)

        assert isinstance(icon, QIcon)

    def test_svg_to_pixmap_returns_qpixmap(self):
        """Test svg_to_pixmap returns QPixmap instance."""
        svg_data = (
            '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#FF0000"/></svg>'
        )
        pixmap = svg_to_pixmap(svg_data, size=30)

        assert isinstance(pixmap, QPixmap)

    def test_svg_to_icon_replaces_color_placeholder(self):
        """Test svg_to_icon replaces <<<COLOR_CODE>>> placeholder."""
        svg_data = '<svg><rect fill="<<<COLOR_CODE>>>"/></svg>'
        icon = svg_to_icon(svg_data, size=30, color="#00FF00")

        assert icon is not None

    def test_svg_to_icon_default_size(self):
        """Test svg_to_icon uses default size of 30."""
        svg_data = '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'

        icon = svg_to_icon(svg_data)
        assert icon is not None


class TestElaSvgIconLoader:
    """Test cases for ElaSvgIconLoader class."""

    def test_get_instance_returns_same_instance(self):
        """Test getInstance returns singleton."""
        instance1 = ElaSvgIconLoader.getInstance()
        instance2 = ElaSvgIconLoader.getInstance()

        assert instance1 is instance2

    def test_set_default_color(self):
        """Test setDefaultColor stores color."""
        loader = ElaSvgIconLoader()
        loader.setDefaultColor("#FF0000")

        assert loader._default_color == "#FF0000"

    def test_default_color_property(self):
        """Test defaultColor property returns stored color."""
        loader = ElaSvgIconLoader()
        loader.setDefaultColor("#00FF00")

        assert loader.defaultColor == "#00FF00"

    def test_load_from_package_raises_on_missing_file(self):
        """Test loadFromPackage raises FileNotFoundError."""
        loader = ElaSvgIconLoader()

        with pytest.raises(FileNotFoundError):
            loader.loadFromPackage("nonexistent.icons")

    def test_append_adds_icon(self):
        """Test append adds icon to internal dict."""
        loader = ElaSvgIconLoader()
        loader.append("test_icon", "<svg>...</svg>")

        assert "test_icon" in loader._icons
        assert loader._icons["test_icon"] == "<svg>...</svg>"

    def test_get_svg_data_returns_icon_data(self):
        """Test getSvgData returns stored SVG data."""
        loader = ElaSvgIconLoader()
        loader.append("test_icon", "<svg>test</svg>")

        data = loader.getSvgData("test_icon")
        assert data == "<svg>test</svg>"

    def test_get_svg_data_raises_on_missing_icon(self):
        """Test getSvgData raises KeyError for missing icon."""
        loader = ElaSvgIconLoader()

        with pytest.raises(KeyError):
            loader.getSvgData("nonexistent")

    def test_get_svg_data_replaces_color_placeholder(self):
        """Test getSvgData replaces <<<COLOR_CODE>>> with color."""
        loader = ElaSvgIconLoader()
        loader.append("colored_icon", "<rect fill='<<<COLOR_CODE>>>'/>")

        data = loader.getSvgData("colored_icon", color="#FF0000")

        assert "<<<COLOR_CODE>>>" not in data
        assert "#FF0000" in data

    def test_get_icon_returns_qicon(self):
        """Test getIcon returns QIcon."""
        loader = ElaSvgIconLoader()
        loader.append("test_icon", "<svg><rect/></svg>")

        icon = loader.getIcon("test_icon", size=24)

        assert isinstance(icon, QIcon)

    def test_get_pixmap_returns_qpixmap(self):
        """Test getPixmap returns QPixmap."""
        loader = ElaSvgIconLoader()
        loader.append("test_icon", "<svg><rect/></svg>")

        pixmap = loader.getPixmap("test_icon", size=24)

        assert isinstance(pixmap, QPixmap)

    def test_icon_exists_returns_data_for_existing(self):
        """Test getIconData returns data for existing icon."""
        loader = ElaSvgIconLoader()
        loader.append("existing", "<svg/>")

        result = loader.getIconData("existing")

        assert result is not None

    def test_icon_exists_returns_none_for_missing(self):
        """Test getIconData returns None for missing icon."""
        loader = ElaSvgIconLoader()

        result = loader.getIconData("nonexistent")

        assert result is None

    def test_contains_operator(self):
        """Test __contains__ returns True for existing icon."""
        loader = ElaSvgIconLoader()
        loader.append("test", "<svg/>")

        assert "test" in loader

    def test_len_returns_icon_count(self):
        """Test __len__ returns number of icons."""
        loader = ElaSvgIconLoader()
        loader.append("icon1", "<svg/>")
        loader.append("icon2", "<svg/>")

        assert len(loader) == 2

    def test_icon_names_returns_list(self):
        """Test iconNames returns list of icon names."""
        loader = ElaSvgIconLoader()
        loader.append("icon1", "<svg/>")
        loader.append("icon2", "<svg/>")

        names = loader.iconNames()

        assert "icon1" in names
        assert "icon2" in names


class TestSvgIconLoader:
    """Test cases for svg_icon_loader function."""

    def test_svg_icon_loader_returns_loader_instance(self):
        """Test svg_icon_loader returns ElaSvgIconLoader."""
        loader = svg_icon_loader()

        assert isinstance(loader, ElaSvgIconLoader)

    def test_svg_icon_loader_is_singleton(self):
        """Test svg_icon_loader returns same instance on multiple calls."""
        loader1 = svg_icon_loader()
        loader2 = svg_icon_loader()

        assert loader1 is loader2
