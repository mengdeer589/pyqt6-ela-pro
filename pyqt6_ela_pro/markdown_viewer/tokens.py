"""渲染 / 绘制共享的占位符、QTextFormat 属性与几何常量。"""

from __future__ import annotations

from PyQt6.QtGui import QTextFormat


_CODE_TOKEN_PREFIX = "\ue000elacode"

_CODE_TOKEN_SUFFIX = "\ue001"

#: 行内语法转换期间保护链接目标 / 裸 URL / HTML 标签的占位符（guard 前还原）
_PROTECT_TOKEN_PREFIX = "\ue000elaprot"

_INLINE_CODE_TOKEN_PREFIX = "\ue000elainline"

_MERMAID_TOKEN_PREFIX = "\ue000elamermaid"

_MERMAID_IMAGE_PREFIX = "elamermaid://"

_MERMAID_TIP_PREFIX = "Mermaid: "

_MERMAID_PENDING_PREFIX = "mermaid-pending-"

_FOLD_TOKEN_PREFIX = "\ue000elafold"

_FOLD_END_TOKEN_PREFIX = "\ue000elafoldend"

_CONTROL_ANCHOR_PREFIXES = (
    "#elafold-",
    "#elacode-expand-",
    "#elatask-",
    "#fn-",
    "#fnref-",
)

_CODE_CELL_PADDING_TOP = 9.0

_CODE_CELL_PADDING_BOTTOM = 9.0

_CODE_CELL_PADDING_RIGHT = 14.0

_CODE_CELL_LEFT_PADDING = 14.0

_LINE_NUMBER_LEFT_GAP = 4.0

_LINE_NUMBER_RIGHT_GAP = 8.0

_LINE_NUMBER_MIN_DIGITS = 2

_FOOTNOTE_REF_PREFIX = "\ue000elafnref"

_FOOTNOTE_DEF_PREFIX = "\ue000elafndef"

_MARK_TOKEN_PREFIX = "\ue000elamark"

_CALLOUT_TOKEN_PREFIX = "\ue000elacallout"

_TOC_TOKEN = "\ue000elatoc\ue001"

_CODE_MARKER = QTextFormat.Property.UserProperty + 101

_CODE_TEXT_PROPERTY = QTextFormat.Property.UserProperty + 102

_CODE_SOURCE_PROPERTY = QTextFormat.Property.UserProperty + 103

_CODE_LANG_PROPERTY = QTextFormat.Property.UserProperty + 104

_HR_MARK = QTextFormat.Property.UserProperty + 105

_CALLOUT_RAIL_PROPERTY = QTextFormat.Property.UserProperty + 106

_INLINE_CODE_MARK = QTextFormat.Property.UserProperty + 107

_CODE_MARKER_VALUE = "elacode"

_CODE_BUTTON_SIZE = 24

_CODE_VIEW_CULL_MARGIN = 64.0
