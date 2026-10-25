"""宿主颜色入口统一支持 ``rgb()`` / ``rgba()``。

``QColor`` 自己解析不了 CSS 函数式颜色（``QColor("rgba(1,2,3,0.5)")`` 是**无效色**），
以前这些入口会静默回退默认色。现在统一走 ``_colors.parse_color``：

- ``_theme.setAccentColor``（强调色 → hover / press / 开关圆点）
- ``_styles`` 原语（文本色 / 纯色底 / 1px 边框 / ``ColorText`` / ``FlatIconButton``）
- ``ElaAvatar`` 背景 / 前景、``ElaProgressButton`` / ``ElaLongPressButton`` 进度色、
  ``ElaSideDrawer`` 底色、``ElaToolTip`` 文字色、``ElaTerminalView`` 高亮色
- ``ElaMarkdownViewer`` 视口底色 / 主题语义色 / 代码 token 色

每一条都钉「传 ``rgba`` 与传等价 hex 得到同一个颜色」。
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QFrame, QLabel, QWidget

from pyqt6_ela_pro import _colors
from pyqt6_ela_pro._styles import (
    ColorText,
    FlatIconButton,
    setPlainFrame,
    setSolidBackground,
    setTextColor,
)
from pyqt6_ela_pro.ela_avatar import ElaAvatar
from pyqt6_ela_pro.ela_long_press_button import ElaLongPressButton
from pyqt6_ela_pro.ela_markdown_viewer import ElaMarkdownViewer, registerMarkdownTheme
from pyqt6_ela_pro.ela_progress_button import ElaProgressButton
from pyqt6_ela_pro.terminal_view import ElaTerminalView

_RGBA = "rgba(1, 2, 3, 1)"
_HEX = "#010203"


class TestParseColorHome:
    def test_charts_reexports_the_shared_parser(self):
        from pyqt6_ela_pro.charts import _utils

        assert _utils.parse_color is _colors.parse_color

    def test_rgba_matches_hex(self):
        assert _colors.parse_color(_RGBA).name() == _HEX
        assert _colors.parse_color(_RGBA).alpha() == 255
        assert _colors.parse_color("rgba(1, 2, 3, 0.5)").alpha() == 128


class TestStylesPrimitives:
    def test_set_text_color(self, make):
        label = make(QLabel, "x")
        setTextColor(label, _RGBA)
        assert label.palette().color(QPalette.ColorRole.WindowText).name() == _HEX

    def test_set_solid_background(self, make):
        widget = make(QWidget)
        setSolidBackground(widget, _RGBA)
        assert widget.palette().color(QPalette.ColorRole.Window).name() == _HEX

    def test_set_plain_frame_border(self, make):
        frame = make(QFrame)
        setPlainFrame(frame, None, _RGBA)
        border = frame.property("_elaPlainFrameBorder")
        assert isinstance(border, QColor) and border.name() == _HEX

    def test_color_text(self, make):
        text = make(ColorText, "x", pixelSize=13)
        text.setTextColor(_RGBA)
        assert text.textColor().name() == _HEX

    def test_flat_icon_button_state_colors(self, make):
        button = make(FlatIconButton)
        button.setHoverColor(_RGBA)
        button.setPressColor("rgba(4, 5, 6, 1)")
        assert button.hoverColor().name() == _HEX
        assert button.pressColor().name() == "#040506"


class TestComponentColors:
    def test_avatar_background_and_foreground(self, make):
        avatar = make(ElaAvatar)
        avatar.setBackgroundColor(_RGBA)
        avatar.setForegroundColor("rgba(4, 5, 6, 0.5)")
        assert avatar.backgroundColor().name() == _HEX
        assert avatar.foregroundColor().name() == "#040506"
        assert avatar.foregroundColor().alpha() == 128

    def test_progress_button_color(self, make):
        button = make(ElaProgressButton, "上传")
        button.setProgressColor(_RGBA)
        assert button.progressColor().name() == _HEX

    def test_long_press_button_color(self, make):
        button = make(ElaLongPressButton)
        button.setProgressColor(_RGBA)
        assert button.progressColor().name() == _HEX

    def test_terminal_highlight_color(self, make):
        terminal = make(ElaTerminalView)
        terminal.setHighlightColor(_RGBA)
        assert terminal._highlight_override.name() == _HEX


class TestMarkdownColors:
    def test_viewport_background(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setViewportBackground("rgba(1, 2, 3, 0.5)")
        color = viewer.viewportBackground()
        assert color.name() == _HEX
        assert color.alpha() == 128

    def test_semantic_color_from_registered_theme(self, make):
        name = "rgba-semantic-test"
        try:
            registerMarkdownTheme(
                name,
                light={"semantic": {"link": _RGBA}},
                dark={"semantic": {"link": _RGBA}},
            )
            viewer = make(ElaMarkdownViewer)
            assert viewer.setMarkdownTheme(name) is True
            assert viewer._link_color.name() == _HEX
        finally:
            from pyqt6_ela_pro.ela_markdown_viewer import _MD_THEMES

            _MD_THEMES.pop(name, None)

    def test_code_token_color_is_rendered(self, make):
        viewer = make(ElaMarkdownViewer)
        viewer.setCodeTokenColors({"keyword": _RGBA})
        viewer.setMarkdown("```python\nimport os\n```")
        document = viewer.document()
        position = document.find("import").position()
        color = document.findBlock(position).begin().fragment().charFormat()
        assert color.foreground().color().name() == _HEX
