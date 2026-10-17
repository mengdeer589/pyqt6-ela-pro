"""
Markdown 查看器组件，风格参考 ElaWidgetTools 的 ElaMarkdownViewer。

基于 QTextBrowser 渲染 Markdown，支持主题自适应、流式追加（AI 对话场景）、
代码语法高亮（可选 Pygments）与轻量数学公式渲染。

由于 Qt 5.15 的 Markdown 导入器存在以下限制，本组件在原生渲染前做了
轻量预处理与渲染后处理：

- 围栏代码块不会渲染为等宽字体，也没有背景色；
- 行内代码 ``code`` 完全丢失代码语义；
- 链接颜色硬编码为蓝色，无法通过样式表或调色板覆盖，暗色主题下可读性差；
- 表格为左右贴边的全网格线且无内边距，观感陈旧；
- 任务列表 ``- [x]`` 不渲染勾选框；数学公式与锚点均不支持；
- 脚注、``==高亮==`` / ``~x~`` / ``^x^`` / emoji 短代码、GitHub Alert
  提示块、``[toc]`` 目录等扩展语法均不支持。

处理方式：围栏代码块在预处理时替换为占位符，解析后按占位符精确插入
代码内容并套用代码格式（可带语言标签行与悬浮复制按钮）；行内代码在解析后
按文本顺序定位并套用代码样式；正文与链接统一补上主题色；表格与代码块使用
与背景预混合的轻量色块，并预留上下间距；任务列表在预处理时替换为 ☑/☐；
数学公式由 :mod:`pyqt6_ela_pro.math_lite` 渲染为图片后按占位标记嵌入；
标题自动生成 slug 锚点并可由 ``[toc]`` 生成目录；脚注定义抽取到文末并
支持上标跳转；提示块按语义色加淡底。

流式增量渲染（``appendMarkdown``）与公式占位标记方案参考
InstructionX_UIKit（原库无 LICENSE，思路移植）：
稳定段（围栏/公式块之外的空行边界）只渲染一次并追加进文档，未稳定尾部
在每次节流刷新时整体重渲染替换（超长段落退化为句末标点提交以限制重排
规模）；最终 ``endStream`` 全量重渲染，保证与一次性 ``setMarkdown`` 的
内容完全一致。超过 :data:`_LARGE_RENDER_CHARS` 的超长文档走分块渲染路径，
按时间片让出事件循环并发出 ``renderingProgress`` / ``renderingFinished``。

用法::

    viewer = ElaMarkdownViewer(parent=self)
    viewer.setMarkdown("# 标题\\n\\n正文内容")

    # 流式追加（AI 逐 token 输出）
    viewer.beginStream()
    viewer.appendMarkdown("# 标题\\n")
    viewer.appendMarkdown("正文 ")
    viewer.endStream()
"""

from __future__ import annotations

import base64
from urllib.parse import unquote_to_bytes
import hashlib
import math
import mimetypes
import os
import re
import sys
from typing import Optional

from PyQt6.QtCore import (
    QBuffer,
    QByteArray,
    QElapsedTimer,
    QEvent,
    QFileInfo,
    QIODevice,
    QMarginsF,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QImage,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
    QShowEvent,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
    QTextFormat,
    QTextImageFormat,
    QTextLength,
    QTextOption,
    QTextTable,
    QTextTableCellFormat,
    QTextTableFormat,
    QPageLayout,
    QPageSize,
    QPdfWriter,
)
from ._internal import is_deleted
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from PyQt6ElaWidgetTools import (
    eTheme,
    ElaIcon,
    ElaIconType,
    ElaMenu,
    ElaScrollBar,
    ElaThemeType,
)

from ._internal import execElaMenu, single_shot_on
from ._motion import start_idle_loop
from ._styles import FlatIconButton, setTextBaseColor
from .math_lite import (
    MATH_ENVS,
    clear_cache as clear_math_cache,
    extract_math,
    render_formula,
)
from . import mermaid_support
from .mermaid_support import ElaMermaidRenderer
from .widget_base import ElaThemeWidget

#: 行内代码：`` `code` `` / ``` ``code`` ```（不允许跨行、不允许空内容）
_INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")

_FENCE_MARKERS = ("```", "~~~")


def _fence_open(line: str) -> tuple[str, str]:
    """判断一行是否开启围栏代码块。

    :returns: ``(完整围栏串, 语言)``；不是围栏则 ``("", "")``。围栏串是
        **完整**的连续标记（`` ```` `` / `` ```` ``），不是固定 3 个字符。
    """
    stripped = line.lstrip()
    if not stripped.startswith(_FENCE_MARKERS):
        return "", ""
    i = 0
    while i < len(stripped) and stripped[i] in "`~":
        i += 1
    marker = stripped[:i]
    # 纯标记行（没有语言）时长度就是围栏长度；有语言时取标记部分
    return marker, stripped[i:].strip().split(" ", 1)[0].lower()


def _fence_close(line: str, fence: str) -> bool:
    """判断一行是否闭合 ``fence`` 开启的围栏。

    两条规则都必要，缺一条就会静默改坏代码内容：

    * **长度必须 ≥ 开围栏且不得更长的同类串** —— CommonMark 里用 4 个反引号
      包裹 3 个反引号是标准写法，只看前 3 字符会让内层 ``` 提前闭合围栏。
    * **闭合行除空白外不得有其它字符** —— ```` ```not-a-close ```` 不是闭合标记。
    """
    if not fence:
        return False
    stripped = line.strip()
    if not stripped.startswith(fence):
        return False
    rest = stripped[len(fence) :]
    if rest and rest[0] == fence[0]:
        return False
    return not rest.strip()


#: 围栏代码块占位符（私有区字符，正常文本不会出现）：
#: 预处理时替换为占位符，Markdown 解析后再用真实代码内容替换
_CODE_TOKEN_PREFIX = "\ue000elacode"
_CODE_TOKEN_SUFFIX = "\ue001"

#: 行内代码占位符。**必须用占位符而不是「渲染后按文本 find 反推位置」** ——
#: 后者在同一串文本更早处以非代码形式出现过时会把标记打到错的地方
#: （见 _preprocess 里 transform 的注释与 _apply_inline_code_formats）。
_INLINE_CODE_TOKEN_PREFIX = "\ue000elainline"

#: Mermaid 围栏占位符与图片资源前缀
_MERMAID_TOKEN_PREFIX = "\ue000elamermaid"
_MERMAID_IMAGE_PREFIX = "elamermaid://"
_MERMAID_TIP_PREFIX = "Mermaid: "
#: Mermaid 待渲染任务视口优先级刷新间隔（毫秒）
_MERMAID_PRIORITY_INTERVAL_MS = 80
#: Mermaid 占位/降级图锚点前缀（异步结果按此定位）
_MERMAID_PENDING_PREFIX = "mermaid-pending-"
#: Mermaid 图片左右留白（与视口宽度相减）
_MERMAID_IMAGE_MARGIN = 24

#: 可折叠块（推理块 / details）：起始与结束占位符
_FOLD_TOKEN_PREFIX = "\ue000elafold"
_FOLD_END_TOKEN_PREFIX = "\ue000elafoldend"
#: 右键菜单行高（ElaMenu，与 terminal_view.py 一致）
_CONTEXT_MENU_ITEM_HEIGHT = 28

#: 内部控件锚点前缀（不显示 href tooltip）
_CONTROL_ANCHOR_PREFIXES = (
    "#elafold-",
    "#elacode-expand-",
    "#elatask-",
    "#fn-",
    "#fnref-",
)

#: 允许交给 ``QDesktopServices``（即系统 shell）打开的 scheme 白名单。
#: 模型输出是不可信输入，而 ``setOpenExternalLinks`` 默认开着 —— 没有白名单
#: 时 ``javascript:`` / ``file:`` / ``data:`` / ``ms-msdt:`` 都会被原样交给
#: shell，Windows 上 ``file:`` 指向 exe 会被 ShellExecuteEx 直接启动。
#: 宿主可用 ``setExternalLinkSchemes`` 收窄或放宽。
_EXTERNAL_LINK_SCHEMES = frozenset({"http", "https", "mailto"})

#: 推理块标签（默认 `` ... ``，可经 ``setReasoningTag`` 修改/关闭）
_DEFAULT_REASONING_TAG = "think"
_DEFAULT_REASONING_LABEL = "思考过程"

#: front matter（YAML 头部）由 Qt 6 的 Markdown 导入器原生剥离（`---` 开头且成对闭合），
#: 本库不再自己预处理（Qt 5.15 需要，迁移到 Qt6 后是死代码）。

#: details 折叠块：``<details>`` + 可选 ``<summary>``
_DETAILS_OPEN_RE = re.compile(r"^<details>\s*$", re.IGNORECASE)
_DETAILS_CLOSE_RE = re.compile(r"^</details>\s*$", re.IGNORECASE)
_SUMMARY_RE = re.compile(r"^<summary>(.*)</summary>\s*$", re.IGNORECASE)

#: 任务列表：``- [x]`` / ``- [ ]`` → ☑ / ☐（保留列表标记与缩进）
_TASK_LIST_RE = re.compile(r"^([ \t]*(?:[-+*]|\d+[.)])[ \t]+)\[([ xX])\][ \t]?")

#: 空 alt 图片：``![](src)`` / ``![][ref]``。Qt 5.15 的 Markdown 导入器对 alt
#: 为空的图片**整张静默丢弃**（``![ ](src)`` 就正常渲染），预处理时补一个空格。
#: 只改「紧跟 ``(`` / ``[``」的形态，正文里字面量 ``![]`` 不受影响。
_EMPTY_ALT_IMAGE_RE = re.compile(r"!\[\](?=[\(\[])")

#: 图片语法探测（预处理后的源里出现才跑 ``_apply_images``：
#: 无图的文档整趟跳过全块 × 片段遍历，分块渲染时每块一次）
_IMAGE_SYNTAX_RE = re.compile(r"!\[|<img", re.IGNORECASE)

#: 行内下标 ``H~2~O`` / 上标 ``x^2^``（内容不含空白/方括号；不匹配 ``~~删除线~~``）
_SUB_RE = re.compile(r"(?<!~)~([^~\s\[\]]+)~(?!~)")
_SUP_RE = re.compile(r"(?<!\^)\^([^\^\s\[\]]+)\^(?!\^)")

#: 行内高亮 ``==text==``（内容含 Markdown 特殊符时不做处理，交给原生解析）
_MARK_RE = re.compile(r"==([^=\s](?:[^=]*[^=\s])?)==")
_MARK_SPECIAL_CHARS = ("*", "_", "[", "]", "`", "~", "<", ">")

#: emoji 短代码 ``:smile:`` → Unicode（仅覆盖常用集合，未知短代码原样保留）
_EMOJI_RE = re.compile(r":([a-z0-9_+-]+):")
_EMOJI_MAP = {
    "smile": "😄",
    "grin": "😁",
    "joy": "😂",
    "rofl": "🤣",
    "wink": "😉",
    "blush": "😊",
    "heart": "❤️",
    "broken_heart": "💔",
    "thumbsup": "👍",
    "+1": "👍",
    "thumbsdown": "👎",
    "-1": "👎",
    "ok_hand": "👌",
    "clap": "👏",
    "pray": "🙏",
    "muscle": "💪",
    "wave": "👋",
    "point_right": "👉",
    "point_left": "👈",
    "eyes": "👀",
    "thinking": "🤔",
    "sweat_smile": "😅",
    "cry": "😢",
    "sob": "😭",
    "angry": "😠",
    "rage": "😡",
    "scream": "😱",
    "sunglasses": "😎",
    "star": "⭐",
    "star2": "🌟",
    "sparkles": "✨",
    "fire": "🔥",
    "rocket": "🚀",
    "tada": "🎉",
    "balloon": "🎈",
    "gift": "🎁",
    "trophy": "🏆",
    "medal": "🏅",
    "warning": "⚠️",
    "check": "✅",
    "heavy_check_mark": "✔️",
    "x": "❌",
    "cross_mark": "❌",
    "question": "❓",
    "no_entry": "⛔",
    "bulb": "💡",
    "book": "📖",
    "books": "📚",
    "pencil": "📝",
    "gear": "⚙️",
    "wrench": "🔧",
    "hammer": "🔨",
    "bug": "🐛",
    "zap": "⚡",
    "boom": "💥",
    "100": "💯",
    "clock": "🕐",
    "hourglass": "⏳",
    "calendar": "📅",
    "pushpin": "📌",
    "paperclip": "📎",
    "link": "🔗",
    "lock": "🔒",
    "key": "🔑",
    "mag": "🔍",
    "chart": "📈",
    "package": "📦",
    "computer": "💻",
    "phone": "📱",
    "email": "📧",
    "speech_balloon": "💬",
    "arrow_right": "➡️",
    "arrow_left": "⬅️",
    "arrow_up": "⬆️",
    "arrow_down": "⬇️",
    "information_source": "ℹ️",
    "heavy_plus_sign": "➕",
    "heavy_minus_sign": "➖",
}

#: Callout 提示块：``> [!NOTE]`` 等（GitHub 风格）
_CALLOUT_RE = re.compile(
    r"^>[ \t]*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*$", re.IGNORECASE
)
_CALLOUT_LABELS = {
    "note": "提示",
    "tip": "技巧",
    "important": "重要",
    "warning": "警告",
    "caution": "注意",
}
_CALLOUT_COLORS = {
    "note": {"light": "#0969da", "dark": "#4493f8"},
    "tip": {"light": "#1a7f37", "dark": "#3fb950"},
    "important": {"light": "#8250df", "dark": "#ab7df8"},
    "warning": {"light": "#9a6700", "dark": "#d29922"},
    "caution": {"light": "#cf222e", "dark": "#f85149"},
}

#: 脚注定义 ``[^id]: text``（id 不允许空白）与引用 ``[^id]``
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]\s]+)\]:[ \t]*(.*)$")
_FOOTNOTE_REF_RE = re.compile(r"\[\^([^\]\s]+)\]")

#: 独立目录行 ``[toc]``
_TOC_LINE_RE = re.compile(r"^\[toc\]$", re.IGNORECASE)

#: 引用块左缩进判定阈值（Qt Markdown 导入器为引用块设置 ~40px 左缩进）
_QUOTE_LEFT_MARGIN = 20.0

#: Typora（github.css）标题排版：级别 → (字号倍率, 上边距, 下边距, 行高%)
_HEADING_TYPOGRAPHY = {
    1: (2.25, 16.0, 16.0, 120.0),
    2: (1.75, 16.0, 16.0, 122.0),
    3: (1.5, 16.0, 16.0, 143.0),
    4: (1.25, 16.0, 16.0, 150.0),
    5: (1.0, 16.0, 16.0, 150.0),
    6: (1.0, 16.0, 16.0, 150.0),
}
#: 正文行高（百分比，Typora 风格松弛行距）
_BODY_LINE_HEIGHT = 160.0
#: 列表项 / 引用块的行间距（比段落紧凑）
_LIST_ITEM_MARGIN = 4.0
_QUOTE_BLOCK_MARGIN = 8.0
#: 普通段落的下边距（Typora 0.8em ≈ 12px）
_PARAGRAPH_MARGIN = 12.0
#: 表格与前后块的间距（Typora 0.8em ≈ 12px）
_TABLE_BLOCK_MARGIN = 12.0
#: h1 / h2 底部分隔线厚度（像素）
_HEADING_RULE_WIDTH = 1.0
#: 引用块左侧竖线（宽度 / 内缩，像素）
_QUOTE_RAIL_WIDTH = 4.0
_QUOTE_RAIL_INSET = 4.0
#: 分割线（hr）厚度（像素，opencode TUI 为 1px 正文色线）
_HR_LINE_WIDTH = 1.0
#: 代码卡圆角半径（像素，软卡片：无描边）
_CODE_CARD_RADIUS = 6.0
#: 行内代码水平内边距 / 圆角（像素）
_INLINE_CODE_PADDING = 3.0
_INLINE_CODE_RADIUS = 3.0

#: 脚注 / Callout / 高亮 / 目录占位符前缀（末尾拼索引或 id + ``_CODE_TOKEN_SUFFIX``）
_FOOTNOTE_REF_PREFIX = "\ue000elafnref"
_FOOTNOTE_DEF_PREFIX = "\ue000elafndef"
_MARK_TOKEN_PREFIX = "\ue000elamark"
_CALLOUT_TOKEN_PREFIX = "\ue000elacallout"
_TOC_TOKEN = "\ue000elatoc\ue001"

#: 代码块包裹表标记（存于 QTextTableFormat，fragment 复制后仍保留）
_CODE_MARKER = QTextFormat.Property.UserProperty + 101
#: 代码块原始文本（存于 QTextTableFormat，供复制按钮精确取值）
_CODE_TEXT_PROPERTY = QTextFormat.Property.UserProperty + 102
#: 代码块源行范围 "start,end"（存于 QTextTableFormat，供引用回复还原）
_CODE_SOURCE_PROPERTY = QTextFormat.Property.UserProperty + 103
#: 代码块语言（存于 QTextTableFormat，供复制按钮 tooltip）
_CODE_LANG_PROPERTY = QTextFormat.Property.UserProperty + 104
#: 分割线（hr）标记（存于块格式，Qt 自带横线颜色不可控，改为自绘 2px 线）
_HR_MARK = QTextFormat.Property.UserProperty + 105
#: Callout 竖线颜色（存于块格式，值为 #rrggbb 字符串）
_CALLOUT_RAIL_PROPERTY = QTextFormat.Property.UserProperty + 106
#: 行内代码标记（存于字符格式，供自绘圆角底与边框）
_INLINE_CODE_MARK = QTextFormat.Property.UserProperty + 107
_CODE_MARKER_VALUE = "elacode"
#: 代码复制按钮尺寸（像素）
_CODE_BUTTON_SIZE = 24
#: 代码卡视口粗筛余量（像素）：帧矩形离视口在此距离内的表仍按可见处理
#: （帧矩形与 cursorRect 反推的实际矩形有几像素出入，余量兜住边界）
_CODE_VIEW_CULL_MARGIN = 64.0

#: 优先使用的代码字体（Windows 常见等宽字体），均不可用时回退系统等宽字体
_PREFERRED_CODE_FONTS = ("Consolas", "Cascadia Mono", "Courier New")

#: 超过该长度的代码块不做语法高亮（避免流式重排时词法分析开销）
_HIGHLIGHT_MAX_CHARS = 20000
#: 流式渲染中未闭合围栏超过该长度时暂不高亮（闭合后自动恢复）
_STREAM_HIGHLIGHT_MAX_CHARS = 4096
#: 高亮结果缓存条数
_HIGHLIGHT_CACHE_CAP = 32

#: 内部锚点返回栈上限
_ANCHOR_HISTORY_CAP = 50

#: 滚动跟随判定余量（像素）
_SCROLL_MARGIN = 4

#: 嵌入模式「真实布局完成」的视口宽度下限（像素）。低于该值说明首次布局还没跑。
_EMBED_MIN_VALID_WIDTH = 8
#: 文档 ``textWidth`` 与视口宽的容差（像素）：超过说明文档还没按当前宽度重排。
_EMBED_WIDTH_SLACK = 2
#: 嵌入模式高度同步诊断日志（``ELACHAT_DEBUG_LAYOUT=1`` 时每次测量打一行 stderr）。
#:
#: 慢机器上「思考内容 ↔ 后续分段之间多出数行空白」属于时序问题，本机很难复现；
#: 打开该开关后把 stderr 里的 ``[ElaMarkdownViewer]`` 行留下来即可定位。
_DEBUG_LAYOUT = os.environ.get("ELACHAT_DEBUG_LAYOUT", "").strip().lower() not in (
    "",
    "0",
    "false",
    "no",
    "off",
)


def _clamp_pos(document: QTextDocument, position: int) -> int:
    """把字符位置钳进文档合法区间（``0 .. characterCount - 1``）。

    Qt 对越界位置只打一条 ``QTextCursor::setPosition`` 警告、光标原地不动 ——
    随后的 ``movePosition`` / ``mergeCharFormat`` 就落在错误的位置上。本模块的
    位置都取自文档自身，但异步路径（流式增量重建 / mermaid 回调）里文档可能在
    取值与设值之间变小，统一钳一道，警告与错位都不会发生。
    """
    try:
        limit = max(0, int(document.characterCount()) - 1)
    except Exception:  # noqa: BLE001 —— 文档已析构等异常形态
        return 0
    return max(0, min(int(position), limit))


#: 流式刷新间隔（毫秒）：按未稳定尾部大小自适应。
#:
#: 40ms 实测只有约 10.7 次视觉更新/秒 —— 不刷屏，但明显"跳"，读起来是分段
#: 出现而非逐字浮现（人眼平滑阈值约 20-40 次/秒，对齐 opencode 的 24ms 节奏）。
#: 改为 24ms 后实测 16.9-17.5 次/秒，**墙钟时间不变**（12 万字流式仍 7 次渲染、
#: 0.69s），即平滑度提升不花吞吐代价。150/400ms 两档保持不变 —— 它们负责
#: 在超长尾部时保护渲染吞吐，不该为观感让路。
_STREAM_INTERVAL = 24
_STREAM_INTERVAL_MID = 150
_STREAM_INTERVAL_LONG = 400
_STREAM_MID_CHARS = 16000
_STREAM_LONG_CHARS = 64000
#: 流式打字光标的闪烁周期（ms）。持续动效 —— Reduced/Disabled 下**停闪烁但保留
#: 光标**（停在不可见相位等于告诉用户「卡住了」），见 ``_stop_stream_caret``。
STREAM_CARET_BLINK_MS = 500

#: 超长段落流式补充提交：未稳定尾部超过该长度后在句末标点处提交
_STREAM_SENTENCE_MIN = 4096
#: 超过该长度仍无句末标点时，退化为最近空白处软切（限制尾部重排规模）
_STREAM_SENTENCE_MAX = 16384
_SENTENCE_RE = re.compile(r"[。！？!?;；]")

#: 大文档分块渲染：超过该长度走分块路径（按空行边界切块，逐块提交）
_LARGE_RENDER_CHARS = 65536
_LARGE_RENDER_CHUNK = 8192
_LARGE_RENDER_BUDGET_MS = 16

#: Pygments 惰性导入状态（{"loaded": bool, "module": (get_lexer_by_name, Token) | None}）
_PYGMENTS_STATE = {"loaded": False, "module": None}

#: markdown 内置主题注册表：名称 → {"light": {...}, "dark": {...}}。
#: 每套主题含 ``semantic``（标题 / 加粗 / 斜体 / 行内代码 / 链接 / 引用 /
#: 列表勾选框 / 高亮底色）与 ``syntax``（13 个语法高亮 token 键）；结构色
#: （背景 / 正文 / 边框）仍由 eTheme 令牌提供。用 :func:`registerMarkdownTheme`
#: 可注册自定义主题，:func:`setDefaultMarkdownTheme` 改默认，查看器实例上
#: ``setMarkdownTheme(name)`` 切换。
_MD_THEME_SEMANTIC_KEYS = (
    "heading",
    "strong",
    "emphasis",
    "code",
    "link",
    "quote",
    "list",
    "mark",
)
_MD_THEME_SYNTAX_KEYS = (
    "keyword",
    "constant",
    "type",
    "function",
    "class",
    "decorator",
    "builtin",
    "attribute",
    "tag",
    "string",
    "number",
    "comment",
    "operator",
)

_MD_THEMES = {
    # opencode 终端版（默认）：标题紫/深橙、斜体黄、行内码绿、链接青；
    # 加粗暗色橙、亮色与正文同色（列表文字一律正文色，见 _apply_fragment_colors）
    "opencode": {
        "light": {
            "semantic": {
                # 标题加深到 5.25:1（原 #d68c27 在白底上只有 2.75:1）；加粗
                # 回归正文色 —— 强调色只留给标题，避免「处处强调 = 没有强调」
                "heading": "#9d5d00",
                "strong": "#000000",
                "emphasis": "#b0851f",
                "code": "#3d9a57",
                "link": "#318795",
                "quote": "#b0851f",
                # list 现在只用于任务勾选框（Qt 的 bullet 用调色板绘制、
                # 字符格式染不上，列表文字也不再整块上色，见 _apply_fragment_colors）
                "list": "#9d5d00",
                "mark": "#f2cc0c",
            },
            "syntax": {
                "keyword": "#d68c27",
                "constant": "#d68c27",
                "type": "#b0851f",
                "function": "#3b7dd8",
                "class": "#b0851f",
                "decorator": "#3b7dd8",
                "builtin": "#3b7dd8",
                "attribute": "#d1383d",
                "tag": "#d1383d",
                "string": "#3d9a57",
                "number": "#d68c27",
                "comment": "#8a8a8a",
                "operator": "#318795",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#9d7cd8",
                "strong": "#f5a742",
                "emphasis": "#e5c07b",
                "code": "#7fd88f",
                "link": "#56b6c2",
                "quote": "#e5c07b",
                "list": "#9d7cd8",
                "mark": "#f2cc0c",
            },
            "syntax": {
                "keyword": "#9d7cd8",
                "constant": "#f5a742",
                "type": "#e5c07b",
                "function": "#fab283",
                "class": "#e5c07b",
                "decorator": "#fab283",
                "builtin": "#fab283",
                "attribute": "#e06c75",
                "tag": "#e06c75",
                "string": "#7fd88f",
                "number": "#f5a742",
                "comment": "#808080",
                "operator": "#56b6c2",
            },
        },
    },
    # GitHub 风格：标题 / 强调沿用正文色（靠字重 / 斜体区分），链接蓝
    "github": {
        "light": {
            "semantic": {
                "heading": "#1f2328",
                "strong": "#1f2328",
                "emphasis": "#1f2328",
                "code": "#1f2328",
                "link": "#0969da",
                "quote": "#59636e",
                "list": "#1f2328",
                "mark": "#ffd33d",
            },
            "syntax": {
                "keyword": "#cf222e",
                "constant": "#0550ae",
                "type": "#953800",
                "function": "#8250df",
                "class": "#953800",
                "decorator": "#8250df",
                "builtin": "#0550ae",
                "attribute": "#0550ae",
                "tag": "#116329",
                "string": "#0a3069",
                "number": "#0550ae",
                "comment": "#59636e",
                "operator": "#59636e",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#f0f6fc",
                "strong": "#f0f6fc",
                "emphasis": "#f0f6fc",
                "code": "#f0f6fc",
                "link": "#4493f8",
                "quote": "#9198a1",
                "list": "#f0f6fc",
                "mark": "#d29922",
            },
            "syntax": {
                "keyword": "#ff7b72",
                "constant": "#79c0ff",
                "type": "#ffa657",
                "function": "#d2a8ff",
                "class": "#ffa657",
                "decorator": "#d2a8ff",
                "builtin": "#79c0ff",
                "attribute": "#79c0ff",
                "tag": "#7ee787",
                "string": "#a5d6ff",
                "number": "#79c0ff",
                "comment": "#8b949e",
                "operator": "#c9d1d9",
            },
        },
    },
    # Solarized：黄 / 橙 / 紫 / 绿 / 蓝 五色语义
    "solarized": {
        "light": {
            "semantic": {
                "heading": "#b58900",
                "strong": "#cb4b16",
                "emphasis": "#6c71c4",
                "code": "#859900",
                "link": "#268bd2",
                "quote": "#657b83",
                "list": "#268bd2",
                "mark": "#b58900",
            },
            "syntax": {
                "keyword": "#859900",
                "constant": "#d33682",
                "type": "#b58900",
                "function": "#268bd2",
                "class": "#b58900",
                "decorator": "#6c71c4",
                "builtin": "#268bd2",
                "attribute": "#dc322f",
                "tag": "#dc322f",
                "string": "#2aa198",
                "number": "#d33682",
                "comment": "#93a1a1",
                "operator": "#657b83",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#b58900",
                "strong": "#cb4b16",
                "emphasis": "#6c71c4",
                "code": "#859900",
                "link": "#268bd2",
                "quote": "#93a1a1",
                "list": "#268bd2",
                "mark": "#b58900",
            },
            "syntax": {
                "keyword": "#859900",
                "constant": "#d33682",
                "type": "#b58900",
                "function": "#268bd2",
                "class": "#b58900",
                "decorator": "#6c71c4",
                "builtin": "#268bd2",
                "attribute": "#dc322f",
                "tag": "#dc322f",
                "string": "#2aa198",
                "number": "#d33682",
                "comment": "#586e75",
                "operator": "#93a1a1",
            },
        },
    },
    # Dracula（深色）/ Alucard（浅色）
    "dracula": {
        "light": {
            "semantic": {
                "heading": "#644ac9",
                "strong": "#a34d14",
                "emphasis": "#846e15",
                "code": "#14710a",
                "link": "#036a96",
                "quote": "#6c664b",
                "list": "#a3144d",
                "mark": "#f1fa8c",
            },
            "syntax": {
                "keyword": "#a3144d",
                "constant": "#a3144d",
                "type": "#644ac9",
                "function": "#14710a",
                "class": "#644ac9",
                "decorator": "#14710a",
                "builtin": "#036a96",
                "attribute": "#a34d14",
                "tag": "#a34d14",
                "string": "#846e15",
                "number": "#644ac9",
                "comment": "#6c664b",
                "operator": "#a3144d",
            },
        },
        "dark": {
            "semantic": {
                "heading": "#bd93f9",
                "strong": "#ffb86c",
                "emphasis": "#f1fa8c",
                "code": "#50fa7b",
                "link": "#8be9fd",
                "quote": "#f1fa8c",
                "list": "#ff79c6",
                "mark": "#f1fa8c",
            },
            "syntax": {
                "keyword": "#ff79c6",
                "constant": "#bd93f9",
                "type": "#8be9fd",
                "function": "#50fa7b",
                "class": "#8be9fd",
                "decorator": "#50fa7b",
                "builtin": "#8be9fd",
                "attribute": "#ffb86c",
                "tag": "#ff79c6",
                "string": "#f1fa8c",
                "number": "#bd93f9",
                "comment": "#6272a4",
                "operator": "#ff79c6",
            },
        },
    },
}
#: 默认 markdown 主题（可用 setDefaultMarkdownTheme 调整，影响之后新建的查看器）
_DEFAULT_MD_THEME = "opencode"


def _md_theme_spec(name: str) -> dict:
    """取主题定义（未知名称回落默认主题）。"""
    return _MD_THEMES.get(name) or _MD_THEMES[_DEFAULT_MD_THEME]


def markdownThemes() -> list:
    """全部内置 / 已注册的 markdown 主题名（按注册顺序）。"""
    return list(_MD_THEMES)


def defaultMarkdownTheme() -> str:
    """获取新建查看器使用的默认 markdown 主题名。"""
    return _DEFAULT_MD_THEME


def setDefaultMarkdownTheme(name: str) -> bool:
    """设置默认 markdown 主题（只影响之后新建的查看器，不重渲染已有实例）；
    主题存在才返回 ``True``。
    """
    global _DEFAULT_MD_THEME
    if name not in _MD_THEMES:
        return False
    _DEFAULT_MD_THEME = name
    return True


def registerMarkdownTheme(
    name: str, light: Optional[dict] = None, dark: Optional[dict] = None
) -> None:
    """注册 / 覆盖一套 markdown 主题（``name`` 同名即覆盖）。

    ``light`` / ``dark`` 是 ``{"semantic": {...}, "syntax": {...}}``，可省略或只
    给部分键（其余合并自 opencode 默认主题）。``semantic`` 的 8 个键：
    ``heading`` / ``strong`` / ``emphasis`` / ``code`` / ``link`` / ``quote`` /
    ``list``（任务勾选框等列表标记；列表**文字**保持正文色 —— Qt 的 bullet 由
    调色板绘制、字符格式染不上）/ ``mark``（``==高亮==`` 底色的基色，与背景混合
    后使用）。
    """
    if not isinstance(name, str) or not name:
        raise ValueError("registerMarkdownTheme: 主题名不能为空")
    base = _MD_THEMES.get("opencode") or {}
    _MD_THEMES[name] = {
        variant: _merge_md_variant(base.get(variant, {}), patch)
        for variant, patch in (("light", light), ("dark", dark))
    }


def unregisterMarkdownTheme(name: str) -> bool:
    """移除已注册主题（``"opencode"`` 不可移除）；返回是否移除成功。"""
    if name == "opencode" or name not in _MD_THEMES:
        return False
    _MD_THEMES.pop(name, None)
    return True


def _merge_md_variant(base: dict, patch: Optional[dict]) -> dict:
    """把主题补丁合并到基准变体上（只接受已存在的键与字符串值）。"""
    merged = {
        "semantic": dict(base.get("semantic") or {}),
        "syntax": dict(base.get("syntax") or {}),
    }
    if isinstance(patch, dict):
        for section in ("semantic", "syntax"):
            values = patch.get(section)
            if isinstance(values, dict):
                for key, value in values.items():
                    if key in merged[section] and isinstance(value, str):
                        merged[section][key] = value
    return merged


_DEFAULT_CODE_FONT_FAMILY: Optional[str] = None


def _default_code_font_family() -> str:
    """选择默认代码字体族（**进程级缓存**）。

    ``QFontDatabase.families()`` 要枚举系统字体（慢机上更贵），而它是进程内不变的；
    viewer 通常是「一页一个 / 一批」地建，每个都查一次纯属浪费。宿主用
    ``setCodeFontFamily("")`` 恢复默认时也会命中这里的缓存。
    """
    global _DEFAULT_CODE_FONT_FAMILY
    if _DEFAULT_CODE_FONT_FAMILY is None:
        families = set(QFontDatabase.families())
        for name in _PREFERRED_CODE_FONTS:
            if name in families:
                _DEFAULT_CODE_FONT_FAMILY = name
                break
        else:
            fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
            _DEFAULT_CODE_FONT_FAMILY = fixed_font.family() or _PREFERRED_CODE_FONTS[0]
    return _DEFAULT_CODE_FONT_FAMILY


def _decode_data_uri(url: QUrl) -> QByteArray:
    """``data:`` URL → 原始字节（格式非法 / 体积过大返回空）。

    ``data:`` 是本库自己就会生成的格式（导出 / 复制图片见
    :meth:`_embed_image_data_uri`），所以必须能读回来。模型输出里的 base64
    图片动辄几 MB 到几十 MB，而这份内容**未经信任** —— 不设上限就等于让
    一行 Markdown 分配任意内存。
    """
    payload = url.path() or url.toString(QUrl.ComponentFormattingOption.FullyEncoded)
    if not payload:
        return QByteArray()
    try:
        header, _, encoded = payload.partition(",")
        if not _:
            return QByteArray()
        if header.rstrip().lower().endswith(";base64"):
            # validate=True：畸形 base64 直接拒绝，不让QImage 去猜
            data = base64.b64decode(_safe_b64_text(encoded), validate=True)
        else:
            data = unquote_to_bytes(encoded)
    except Exception:
        return QByteArray()
    if not data or len(data) > _MAX_DATA_URI_BYTES:
        return QByteArray()
    return QByteArray(data)


def _safe_b64_text(text: str) -> str:
    """容忍 base64 里的换行 / 空白（``b64decode(validate=True)`` 不接受）。"""
    return "".join(text.split())


#: ``data:`` 图片的字节上限（base64 解码后）。超过按「取不到」处理。
#: 取 32 MiB：远高于任何真实内嵌图片，又不至于让一行 Markdown 把内存吃光。
_MAX_DATA_URI_BYTES = 32 * 1024 * 1024


#: 引用回复：源行 → 归一化文本（去 Markdown 标记，用于块级近似匹配）
_SOURCE_DECOR_RE = re.compile(
    r"^\s*(?:>+\s*|[-+*]\s+|\d+[.)]\s+|\[[ xX]\]\s+|#{1,6}\s+)+"
)
_INLINE_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_INLINE_SYMBOL_RE = re.compile(
    r"(\*\*|\*|__|_|~~|==|`+|<sub>|</sub>|<sup>|</sup>|~|\^)"
)


def _strip_inline_links(text: str) -> str:
    """``[文字](目标)`` / ``![alt](src)`` → 只留 ``文字``（去掉链接语法）。

    语义与 ``_INLINE_LINK_RE.sub(lambda m: m.group(1), text)`` 一致，但
    **必须是手写扫描而不是那条正则**：``\\([^)]*\\)`` 在「有 ``[`` 而没有
    ``)``」的长行上是 **O(n²)** —— 每个 ``[`` 候选都要让 ``[^)]*`` 扫到
    行尾再逐字符回溯。而它挂在 ``_normalize_text`` 上，也就是**每一次全量
    渲染**（引用回复的源行映射每块最多调 80×40 次）：实测 8 万字符的单行
    要 364ms，输入翻倍耗时变 4 倍，主题切换 / 勾选任务 / 展开折叠全都吃
    这一刀。

    线性靠两点：``find("](")`` 单调前进不回退；``)`` 的位置用 ``paren``
    缓存（``op`` 递增时「下一个 ``)``」单调不减，所以缓存不会失效到重复
    扫描），否则「N 个 ``[a](b`` 末尾只有一个 ``)``」仍然是二次的。

    语义上有一处必须照抄正则的**最左匹配**优先级：``[`` 取「上一个 ``]``
    之后的第一个 ``[``」，而不是「离``]`` 最近的 ``[``」—— ``[a[b]](c)`` 的
    label 是 ``a[b]``，取最近的 ``[`` 会把开头的 ``[`` 漏在label 外。
    """
    out: list[str] = []
    i = 0
    n = len(text)
    paren = -1  # 缓存：下一个 ')' 的位置，-1 表示待求值
    while i < n:
        op = text.find("](", i)
        if op < 0:
            out.append(text[i:])
            break
        # label 里不得含 ']'（等价原正则的 [^\]]*）：所以 '[' 必须在最后一个
        # ']' 之后
        prev_close = text.rfind("]", i, op)
        lb = text.find("[", prev_close + 1 if prev_close >= 0 else i, op)
        if lb < 0:
            out.append(text[i : op + 2])
            i = op + 2
            continue
        if paren != -1 and paren <= op + 1:
            paren = -1
        if paren == -1:
            paren = text.find(")", op + 2)
        if paren < 0:
            out.append(text[i:])
            break
        start = lb - 1 if lb > i and text[lb - 1] == "!" else lb
        out.append(text[i:start])
        out.append(text[lb + 1 : op])
        i = paren + 1
        paren = -1
    return "".join(out)


def _normalize_text(text: str) -> str:
    """块/行文本归一化：去装饰符、链接语法与全部空白（含任务标记）。"""
    text = text.replace("☑", "").replace("☐", "")
    text = _strip_inline_links(text)
    text = _SOURCE_DECOR_RE.sub("", text)
    text = _INLINE_SYMBOL_RE.sub("", text)
    return "".join(text.split())


def _source_line_text(line: str) -> str:
    """源行 → 归一化文本；不可匹配的行（代码围栏/占位符/标签/脚注定义）返回空。"""
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped.startswith(_FENCE_MARKERS):
        return ""
    if any(
        token in stripped
        for token in (
            _FOLD_TOKEN_PREFIX,
            _FOLD_END_TOKEN_PREFIX,
            _CODE_TOKEN_PREFIX,
            _MERMAID_TOKEN_PREFIX,
            _FOOTNOTE_DEF_PREFIX,
            _TOC_TOKEN,
            _CALLOUT_TOKEN_PREFIX,
        )
    ):
        return ""
    if stripped.startswith(("<", "[")) and (
        _DETAILS_OPEN_RE.match(stripped)
        or _DETAILS_CLOSE_RE.match(stripped)
        or _SUMMARY_RE.match(stripped)
        or _FOOTNOTE_DEF_RE.match(line)
    ):
        return ""
    return _normalize_text(line)


def _match_source_lines(lines: list, start: int, block_text: str):
    """从 ``start`` 起搜索与块文本匹配的源行（支持跨行段落/合并引用）。

    ``lines`` 是**预计算**的 ``_source_line_text`` 结果（不可匹配的行为空串），
    由 :meth:`ElaMarkdownViewer._build_block_source_map` 一次生成、逐块复用。

    在窗口内逐行作为起点尝试消费；累计文本必须是目标的前缀才继续，
    否则换下一行起点（避免把无关行误吞进匹配）。

    :returns: ``(匹配起始行号, 结束行号)``；无法匹配返回 ``None``
    """
    target = _normalize_text(block_text)
    if not target:
        return None
    total = len(lines)
    index = start
    while index < total and index < start + 80:
        if not lines[index]:
            index += 1
            continue
        accumulated = ""
        cursor = index
        while cursor < total and cursor < index + 40:
            part = lines[cursor]
            cursor += 1
            if not part:
                continue
            accumulated += part
            if accumulated == target:
                return (index, cursor)
            if not target.startswith(accumulated):
                break
        index += 1
    return None


def _stable_cut(
    text: str,
    committed: int = 0,
    allow_sentence: bool = False,
    safe_from: int = 0,
) -> tuple[int, int]:
    """返回 ``(稳定提交边界偏移, 下次可复用的安全扫描起点)``（无边界时切点为 0）。

    稳定段只包含边界之前的内容；未闭合的围栏与公式块整体留在尾部，
    由流式刷新按当前结构渲染。``allow_sentence`` 用于超长段落：当没有
    空行边界且未稳定尾部过长时，退而在句末标点（或最近空白）处提交，
    避免每次刷新都重排整段超长文本。

    ``safe_from`` 是调用方已知**位于围栏 / 公式块之外**的起点（默认 0），
    本次只扫描它之后的文本：每次从第 0 行全量重扫会随流式长度线性变慢
    （实测 25KB 流 0.2s / 10 秒窗口，整体 O(n²)）。返回值第二项可直接作为
    下一次调用的 ``safe_from``；切点若落在未闭合围栏内（超长尾部兜底提交），
    则回退到围栏之前 —— 否则下一轮会把围栏中段当普通文本，把围栏内的
    空行误判成稳定边界。
    """
    length = len(text)
    base = min(max(int(safe_from), 0), length)
    line_start = text.rfind("\n", 0, base) + 1 if base else 0
    lines = text[line_start:].split("\n")
    n = len(lines)
    offsets = [0]
    for line in lines[:-1]:
        offsets.append(offsets[-1] + len(line) + 1)
    first_line_is_doc_start = line_start == 0
    cut = 0
    sentence_cut = 0
    #: 已知在围栏 / 公式块之外的最大偏移（供下一次增量扫描用）
    outside_end = base
    i = 0
    while i < n:
        line = lines[i]
        stripped = line.strip()
        opened, _lang = _fence_open(line)
        if opened:
            i += 1
            while i < n and not _fence_close(lines[i], opened):
                i += 1
            i += 1
            continue
        closer = None
        env_m = re.match(r"\\begin\{(\w+\*?)\}\s*$", stripped)
        if stripped in ("$$", "\\["):
            closer = stripped if stripped == "$$" else "\\]"
        elif env_m and env_m.group(1).rstrip("*") in MATH_ENVS:
            closer = "\\end{" + env_m.group(1) + "}"
        if closer is not None:
            i += 1
            while i < n and lines[i].strip() != closer:
                i += 1
            i += 1
            continue
        if line == "" and (i > 0 or not first_line_is_doc_start) and i < n - 1:
            cut = line_start + offsets[i + 1]
        elif allow_sentence and not line.startswith(("    ", "\t")):
            for match in _SENTENCE_RE.finditer(line):
                sentence_cut = line_start + offsets[i] + match.end()
        outside_end = line_start + offsets[i] + len(line) + 1
        i += 1

    if cut > committed:
        return cut, cut
    if allow_sentence:
        if sentence_cut > committed and sentence_cut - committed >= _STREAM_SENTENCE_MIN:
            return sentence_cut, sentence_cut
        if length - committed >= _STREAM_SENTENCE_MAX:
            limit = min(committed + _STREAM_SENTENCE_MAX, length)
            pos = max(
                text.rfind(" ", committed, limit),
                text.rfind("\n", committed, limit),
            )
            if pos > committed:
                return pos + 1, min(pos + 1, outside_end)
    return cut, min(cut, outside_end)


def _load_pygments():
    """惰性导入 Pygments，返回 ``(get_lexer_by_name, Token)``；缺失时返回
    ``None``（组件自动降级为纯代码块样式）。
    """
    if _PYGMENTS_STATE["loaded"]:
        return _PYGMENTS_STATE["module"]
    _PYGMENTS_STATE["loaded"] = True
    try:
        from pygments.lexers import get_lexer_by_name
        from pygments.token import Token

        _PYGMENTS_STATE["module"] = (get_lexer_by_name, Token)
    except ImportError:
        _PYGMENTS_STATE["module"] = None
    return _PYGMENTS_STATE["module"]


#: Pygments 词法器实例缓存（按语言）。``get_lexer_by_name`` 带
#: ``stripnl/ensurenl`` 参数时每次调用约 0.1ms 且不命中 pygments 自带缓存，
#: 每个代码块构造一次会随块数线性变慢。词法器跨调用无状态，可安全复用。
_LEXER_CACHE: dict = {}
_LEXER_MISS = object()


#: Pygments token 类型 → 分类名的缓存（token 类型是进程级单例、可哈希）：
#: 逐个 token 走 ``in`` 链时 4282 个代码块的文档要查 77 万次包含判断
#: （实测 ≈ 0.2s），分类与调色板无关，可按类型缓存。
_TOKEN_KIND_CACHE: dict = {}
_TOKEN_KIND_MISS = object()
#: 分类 → ``(调色板键, 是否斜体)``
_TOKEN_KIND_STYLES = {
    "comment": ("comment", True),
    "type": ("type", False),
    "constant": ("constant", False),
    "keyword": ("keyword", True),
    "function": ("function", False),
    "class": ("class", False),
    "decorator": ("decorator", False),
    "builtin": ("builtin", False),
    "attribute": ("attribute", False),
    "tag": ("tag", False),
    "string": ("string", False),
    "number": ("number", False),
    "operator": ("operator", False),
}


def _token_kind(token_type, token):
    """Pygments token → 分类名（``None`` = 未覆盖）；结果按 token 类型缓存。"""
    kind = _TOKEN_KIND_CACHE.get(token_type, _TOKEN_KIND_MISS)
    if kind is _TOKEN_KIND_MISS:
        if token_type in token.Comment:
            kind = "comment"
        elif token_type in token.Keyword.Type:
            kind = "type"
        elif token_type in token.Keyword.Constant:
            kind = "constant"
        elif token_type in token.Keyword:
            kind = "keyword"
        elif token_type in token.Name.Function:
            kind = "function"
        elif token_type in token.Name.Class:
            kind = "class"
        elif token_type in token.Name.Decorator:
            kind = "decorator"
        elif token_type in token.Name.Builtin:
            kind = "builtin"
        elif token_type in token.Name.Attribute:
            kind = "attribute"
        elif token_type in token.Name.Tag:
            kind = "tag"
        elif token_type in token.String:
            kind = "string"
        elif token_type in token.Number:
            kind = "number"
        elif token_type in token.Operator:
            kind = "operator"
        else:
            kind = None
        _TOKEN_KIND_CACHE[token_type] = kind
    return kind


def _token_style(token_type, token, palette):
    """Pygments token → ``(颜色, 斜体)``；未覆盖的 token 返回 ``None``。"""
    kind = _token_kind(token_type, token)
    if kind is None:
        return None
    key, italic = _TOKEN_KIND_STYLES[kind]
    return palette[key], italic


class _ElaTextBrowser(QTextBrowser):
    """内部 QTextBrowser：按开关拦截远程图片资源（默认关闭）。"""

    #: 左键单击图片时发射（参数为文档位置）
    imageClicked = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.remote_images_enabled = False
        #: 嵌入模式：滚轮事件不消费，交给外层滚动容器
        self.forward_wheel = False
        self._press_pos = None

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self.forward_wheel:
            event.ignore()
            return
        super().wheelEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """先画行内代码底、再走文档绘制、最后画装饰线（Typora 风格）。"""
        viewer = self.parent()
        under = getattr(viewer, "_paint_inline_code_backgrounds", None)
        if callable(under):
            painter = QPainter(self.viewport())
            try:
                under(self, painter)
            finally:
                painter.end()
        super().paintEvent(event)
        over = getattr(viewer, "_paint_document_decorations", None)
        if callable(over):
            painter = QPainter(self.viewport())
            try:
                over(self, painter)
            finally:
                painter.end()

    def loadResource(self, resource_type, url):  # noqa: N802 (Qt 命名)
        if (
            resource_type == QTextDocument.ResourceType.ImageResource
            and not self.remote_images_enabled
            and url.scheme() in ("http", "https")
        ):
            return None
        return super().loadResource(resource_type, url)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        press_pos = self._press_pos
        self._press_pos = None
        if press_pos is None or (event.position().toPoint() - press_pos).manhattanLength() > 4:
            return
        if self.textCursor().hasSelection():
            return
        cursor = self.cursorForPosition(event.position().toPoint())
        if cursor.charFormat().isImageFormat():
            self.imageClicked.emit(cursor.position())


class ElaMarkdownViewer(ElaThemeWidget):
    """Markdown 查看器。

    基于 QTextBrowser 渲染 Markdown，支持深浅色主题适配。

    - 围栏代码块渲染为带语言标签的卡片，可选语法高亮（Pygments），
      鼠标悬停右上角可一键复制，支持行号显示与超长折叠；
    - 行内代码以等宽字体 + 主题背景色渲染；
    - 任务列表 ``- [x]`` / ``- [ ]`` 渲染为可点击勾选的 ☑ / ☐；
    - 数学公式（``$...$`` / ``$$...$$``）由内置轻量渲染器绘制为图片，
      悬浮显示 LaTeX 源码，右键可复制；
    - Mermaid 围栏（`` ```mermaid ``）在安装可选依赖 ``mermaidx`` 时异步渲染为
      图片（缺失/失败时回退代码卡片），支持右键复制源码；
    - 表格去除全网格线，改为表头底色 + 行分隔线的轻量样式；
    - GitHub Alert 提示块（``> [!NOTE]`` 等）、脚注、``[toc]`` 目录、
      ``==高亮==`` / ``~x~`` / ``^x^`` / emoji 短代码；
    - 标题自动生成锚点，内部 ``#anchor`` 链接可跳转；
    - 图片支持基准路径（``setBaseUrl``）、超宽缩放与远程默认拦截，
      单击图片发出 ``imageClicked``；
    - 链接颜色跟随主题（``PrimaryNormal``），``linkActivated`` 转发点击；
    - 缩放（``setZoomFactor``）、搜索高亮（``searchText`` / ``findNext``）、
      导出（``toHtml`` / ``toPlainText`` / ``exportPdf``）；
    - ``appendMarkdown`` 支持流式追加（AI 逐 token 输出），贴底时自动跟随，
      末尾绘制闪烁打字光标；超长文档自动分块渲染并发出
      ``renderingProgress`` / ``renderingFinished``；
    - 主题切换时自动重新渲染已设置的内容。

    :param parent: 父控件
    """

    #: 流式追加收尾（``endStream``）时发射
    streamFinished = pyqtSignal()
    #: 链接被点击时发射（参数为 URL 字符串，含内部 ``#anchor``）
    linkActivated = pyqtSignal(str)
    #: 代码块内容被复制时发射（参数为代码文本）
    codeCopied = pyqtSignal(str)
    #: 公式 LaTeX 源码被复制时发射
    formulaCopied = pyqtSignal(str)
    #: Mermaid 源码被复制时发射
    mermaidCopied = pyqtSignal(str)
    #: 选中内容复制为 Markdown 时发射（参数为 Markdown 源）
    selectionQuoted = pyqtSignal(str)
    #: 图片被点击时发射（参数为解析后的 URL）
    imageClicked = pyqtSignal(str)
    #: 任务列表项被点击切换时发射（参数为序号与勾选状态）
    taskToggled = pyqtSignal(int, bool)
    #: 大文档分块渲染进度（0-100）
    renderingProgress = pyqtSignal(int)
    #: 大文档分块渲染完成
    renderingFinished = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._border_radius = 0
        #: 宿主显式设置的视口底色（None = 自动：嵌入/圆角透出，否则不透明 BasicPress）
        self._viewport_bg: Optional[QColor] = None
        #: 嵌入模式（透明背景 + 隐藏滚动条 + 高度随文档自适应）
        self._embedded = False
        #: 嵌入模式高度附加余量（避免取整误差触发内部滚动）
        self._embedded_extra = 2
        #: 嵌入模式是否裁剪文末空白（最后一段落的下边距不计入高度）
        self._embedded_trim_bottom = False
        #: 原始 Markdown 文本（``markdown()`` 原样返回，避免 toMarkdown 往返丢失）
        self._source = ""
        #: 行内代码文本（解析后按顺序定位并套用代码样式）
        self._inline_codes: list[str] = []
        #: 围栏代码块内容（预处理时转为占位符，解析后替换）：[(lang, code, closed)]
        self._fenced_blocks: list[tuple[str, str, bool]] = []
        #: Mermaid 代码块源码（与 ``_MERMAID_TOKEN_PREFIX`` 占位符索引对应）
        self._mermaid_blocks: list[str] = []
        #: Mermaid 渲染配置（``None`` 时自动探测 mermaidx）
        self._mermaid_override = None
        self._mermaid_disabled = False
        self._mermaid_renderer: Optional[ElaMermaidRenderer] = None
        #: Mermaid 待渲染任务队列（按视口距离优先，逐个提交给渲染器）
        self._mermaid_jobs: list[dict] = []
        self._mermaid_job_keys: set = set()
        #: 在途 Mermaid 请求数（引擎串行，>0 时不再提交下一个）
        self._mermaid_active = 0
        #: 引擎预热开关（默认关闭；开启后首次渲染不必等待引擎冷启动）
        self._mermaid_prewarm = False
        #: 视口优先级刷新计时器（滚动时节流重算）
        self._mermaid_priority_timer = QTimer(self)
        self._mermaid_priority_timer.setSingleShot(True)
        self._mermaid_priority_timer.setInterval(_MERMAID_PRIORITY_INTERVAL_MS)
        self._mermaid_priority_timer.timeout.connect(self._refresh_mermaid_priorities)
        #: 任务提交计时器（延后一拍，先让文档滚动/贴底逻辑生效再选下一个任务）
        self._mermaid_pump_timer = QTimer(self)
        self._mermaid_pump_timer.setSingleShot(True)
        self._mermaid_pump_timer.setInterval(0)
        self._mermaid_pump_timer.timeout.connect(self._pump_mermaid)
        #: 行内高亮文本（``==text==``，解析后按顺序套用背景色）
        self._mark_texts: list[str] = []
        #: 脚注定义（预处理时抽取到文末）：[(id, text)]
        self._footnote_defs: list[tuple[str, str]] = []
        #: Callout 类型序列（与占位符索引对应）
        self._callout_types: list[str] = []
        #: 任务列表项（预处理时记录）：[(源行号, 是否勾选)]
        self._task_items: list[tuple[int, bool]] = []
        #: 本文档标题列表（解析后收集）：[(level, text, slug)]
        self._headings: list[tuple[int, str, str]] = []
        #: 代码字体族
        self._code_font_family = _default_code_font_family()
        #: 超长代码折叠行数（0 表示关闭）
        self._code_collapse_lines = 0
        #: 已展开的代码块索引集合
        self._expanded_code_blocks: set[int] = set()
        #: 推理块标签（``None`` 关闭；默认 `` ... ``）
        self._reasoning_tag: Optional[str] = _DEFAULT_REASONING_TAG
        self._reasoning_label = _DEFAULT_REASONING_LABEL
        #: 可折叠块（推理 / ``<details>``）元数据与展开状态
        self._fold_blocks: list[dict] = []
        self._expanded_folds: set[int] = set()
        #: 围栏代码块的源行范围（与 ``_fenced_blocks`` 对应）：[(start, end)]
        self._fenced_source_lines: list[tuple[int, int]] = []
        #: 文档块号 → 源行范围（引用回复用；``None`` 表示未映射）。
        #: **懒建**：``None`` = 尚未构建，``markdownSelection()`` 首次使用时才
        #: 调 ``_build_block_source_map()`` —— 它逐块做源行双指针匹配，实测
        #: 51KB 文档 0.45s（占全量渲染 40%+），而「引用回复」多数会话根本不触发。
        self._block_source_map: Optional[dict] = None
        #: 渲染降级记录：[(类型, 详情)]，全量渲染时重置
        self._render_issues: list[tuple[str, str]] = []
        #: 行号显示开关
        self._line_numbers_enabled = False
        #: 表格斑马纹开关与列宽（百分比列表；``None`` 表示自动）
        self._table_zebra = False
        self._table_column_widths: Optional[list] = None
        #: markdown 主题名（``setMarkdownTheme`` 切换，按浅 / 深自动取对应变体）
        self._md_theme = defaultMarkdownTheme()
        #: token 颜色覆盖（setCodeTokenColors；对所有主题生效）
        self._token_overrides: dict = {}
        #: 当前生效的 token 调色板（_applyThemeStyle 填充：主题 + 覆盖）
        self._token_palette: dict = {}
        #: 公式占位标记模板（实例唯一，跨实例零碰撞；结尾 q 是终止符）
        self._math_mark = f"elamath{id(self):x}z{{}}q"
        #: 高亮结果缓存 {(lang, code, theme_key): [(text, QColor, bold, italic)]}
        self._highlight_cache: dict = {}
        self._highlight_cache_cap = _HIGHLIGHT_CACHE_CAP
        #: 主题 / 配色族变更时若不可见则只标记，等 showEvent 补渲染（见 _ensure_rendered）
        self._needs_render = False
        # 主题色缓存（_applyThemeStyle 填充）
        self._text_color = QColor()
        self._link_color = QColor()
        self._code_bg = QColor()
        self._code_border = QColor()
        self._code_text = QColor()
        self._is_dark_theme = False
        self._table_header_bg = QColor()
        self._table_border = QColor()
        self._table_stripe_bg = QColor()
        self._base_bg = QColor()
        self._mark_bg = QColor()
        self._muted_color = QColor()
        self._placeholder_color = QColor()
        self._quote_rail_color = QColor()
        self._heading_rule_color = QColor()
        self._hr_color = QColor()
        self._search_bg = QColor()
        self._inline_code_bg = QColor()
        self._inline_code_border = QColor()
        self._code_button_hover_bg = QColor()
        self._code_button_press_bg = QColor()
        self._diff_add_bg = QColor()
        self._diff_del_bg = QColor()
        self._diff_hunk_bg = QColor()
        self.setObjectName("ElaMarkdownViewer")

        # 图片 / 占位 / 缩放 / 搜索状态
        self._base_url = QUrl()
        self._remote_images_enabled = False
        self._placeholder = ""
        self._zoom_factor = 1.0
        self._search_selections: list = []
        self._last_search = ""
        #: 内部锚点跳转前的滚动位置栈（供 backToPreviousAnchor 返回）
        self._anchor_back_stack: list[int] = []

        # 代码块悬浮复制按钮
        self._code_buttons: list[QToolButton] = []
        self._code_buttons_tables: list = []
        self._code_button_rects: list = []
        #: 按钮控件集合（eventFilter 的归属判断 O(1)，不再对列表做线性 in）
        self._code_button_widgets: set = set()
        #: 当前显示的复制按钮下标（-1 = 无；显隐只动前后两个按钮）
        self._shown_code_button = -1
        #: 图片扫描水位：``_image_scan_watermark`` 之前的块已按
        #: ``_image_scan_width`` 的视口宽度处理过（增量重排只扫新增块；
        #: 宽度变化或文档整体替换后重置，见 _reset_image_scan）
        self._image_scan_width = -1
        self._image_scan_watermark = 0

        # 流式状态
        self._stream_active = False
        self._stream_source = ""
        self._stream_committed = 0
        self._stream_tail_pos = 0
        #: ``_stable_cut`` 的增量扫描起点（已知在围栏 / 公式块之外，≤ 已提交位置）
        self._stream_cut_from = 0
        self._stream_first_flush = True
        self._stream_capture_at_bottom = True
        self._stick_to_bottom = True
        self._stream_timer = QTimer(self)
        self._stream_timer.setSingleShot(True)
        self._stream_timer.timeout.connect(self._stream_flush)

        # 流式末尾打字光标
        self._caret_visible = False
        self._caret_timer = QTimer(self)
        self._caret_timer.timeout.connect(self._toggle_stream_caret)

        # 大文档分块渲染状态
        self._large_render_chunks: list[str] = []
        self._large_render_index = 0
        self._large_render_timer = QTimer(self)
        self._large_render_timer.setSingleShot(True)
        self._large_render_timer.timeout.connect(self._render_large_step)

        self._text_browser = _ElaTextBrowser(self)
        self._text_browser.setFrameShape(QFrame.Shape.NoFrame)
        self._text_browser.setReadOnly(True)
        # 必须为 False：Qt 的 QTextBrowserPrivate::_q_anchorClicked 在
        # openExternalLinks 为真时会先调 QDesktopServices::openUrl() 并**直接
        # return**，不再发出 anchorClicked —— 那样任务列表复选框（#elatask-）、
        # 代码/思考折叠（#elafold- / #elacode-expand-）与内部锚点跳转全部失效。
        # 外部链接改由 _on_anchor_clicked 自行打开（见 _open_external_links）。
        self._open_external_links = True
        # 只有白名单里的 scheme 才会真的交给系统 shell（见 _EXTERNAL_LINK_SCHEMES）
        self._external_link_schemes = _EXTERNAL_LINK_SCHEMES
        self._text_browser.setOpenExternalLinks(False)
        self._text_browser.setWordWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        self._text_browser.document().setUndoRedoEnabled(False)
        # 不按键也接收 MouseMove，代码块悬停复制按钮依赖此设置
        self._text_browser.viewport().setMouseTracking(True)
        self._text_browser.setVerticalScrollBar(ElaScrollBar(self._text_browser))
        self._text_browser.setHorizontalScrollBar(
            ElaScrollBar(Qt.Orientation.Horizontal, self._text_browser)
        )
        self._text_browser.anchorClicked.connect(self._on_anchor_clicked)
        self._text_browser.imageClicked.connect(self._on_image_clicked)
        self._text_browser.installEventFilter(self)
        self._text_browser.viewport().installEventFilter(self)
        self._text_browser.verticalScrollBar().valueChanged.connect(
            self._on_view_scrolled
        )
        self._text_browser.document().documentLayout().documentSizeChanged.connect(
            self._on_document_size_changed
        )

        base_font = self._text_browser.document().defaultFont()
        self._base_font_point_size = base_font.pointSizeF()
        if self._base_font_point_size <= 0:
            pixel = base_font.pixelSize()
            self._base_font_point_size = pixel * 0.75 if pixel > 0 else 10.0

        # 布局刷新（滚动/尺寸变化后重排代码复制按钮与图片宽度）
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._on_layout_refresh)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._text_browser)

        self._applyThemeStyle()

    # -- 内容 --------------------------------------------------------------

    def setMarkdown(self, text: str) -> None:
        """设置 Markdown 内容（重置流式状态；超长文本自动分块渲染）。"""
        self._stop_stream()
        self._cancel_large_render()
        self._expanded_code_blocks.clear()
        self._expanded_folds.clear()
        self._source = text or ""
        if len(self._source) > _LARGE_RENDER_CHARS:
            self._begin_large_render()
        else:
            self._render()

    def markdown(self) -> str:
        """当前 Markdown 内容（与传入的文本一致）。"""
        return self._source

    def clear(self) -> None:
        """清空内容。"""
        self.setMarkdown("")

    def document(self) -> QTextDocument:
        """返回底层 ``QTextDocument``，便于设置默认字体等高级选项。"""
        return self._text_browser.document()

    def textBrowser(self) -> QTextBrowser:
        """返回底层 ``QTextBrowser``（可访问 ``anchorClicked`` 等信号）。"""
        return self._text_browser

    def setOpenExternalLinks(self, on: bool) -> None:
        """设置链接是否用系统浏览器打开。

        内部锚点（``#elatask-`` / ``#elafold-`` / ``#elacode-expand-`` / ``#sec``）
        始终由组件自己处理；本开关只影响**带 scheme 的外部链接**是否交给系统浏览器。

        即使开关为 ``True``，**只有 :data:`_EXTERNAL_LINK_SCHEMES` 白名单里的
        scheme 会被打开**，其余（``javascript:`` / ``file:`` / ``data:`` /
        ``ms-msdt:`` 等）一律只发 ``linkActivated`` 而不交给系统 shell。
        白名单可用 :meth:`setExternalLinkSchemes` 调整。

        :param on: ``True`` 时外部链接用系统浏览器打开
        """
        self._open_external_links = bool(on)

    def openExternalLinks(self) -> bool:
        """外部链接是否使用系统浏览器打开。"""
        return self._open_external_links

    def setExternalLinkSchemes(self, schemes) -> None:
        """设置允许交给系统打开的 scheme 白名单（默认 http / https / mailto；
        元素大小写不敏感）。
        """
        self._external_link_schemes = frozenset(
            str(s).strip().lower() for s in schemes if str(s).strip()
        )

    def externalLinkSchemes(self) -> frozenset:
        """当前允许交给系统打开的 scheme 白名单。"""
        return self._external_link_schemes

    def scrollToAnchor(self, name: str) -> None:
        self._text_browser.scrollToAnchor(name)

    def backToPreviousAnchor(self) -> bool:
        """回到上一个内部锚点跳转前的位置；历史为空返回 ``False``。"""
        if not self._anchor_back_stack:
            return False
        value = self._anchor_back_stack.pop()
        bar = self._text_browser.verticalScrollBar()
        bar.setValue(min(value, bar.maximum()))
        return True

    def clearAnchorHistory(self) -> None:
        """清空内部锚点访问历史。"""
        self._anchor_back_stack.clear()

    def _on_anchor_clicked(self, url: QUrl) -> None:
        """链接点击：内部锚点跳转 / 折叠与任务勾选控制 + 外部链接 + 转发 ``linkActivated``。"""
        target = url.toString()
        if target.startswith("#elacode-expand-"):
            self._toggle_code_block_expanded(target[len("#elacode-expand-") :])
            return
        if target.startswith("#elafold-"):
            self._toggle_fold_expanded(target[len("#elafold-") :])
            return
        if target.startswith("#elatask-"):
            self._toggle_task_by_ordinal(target[len("#elatask-") :])
            return
        if not url.scheme() and url.fragment():
            self._anchor_back_stack.append(
                self._text_browser.verticalScrollBar().value()
            )
            if len(self._anchor_back_stack) > _ANCHOR_HISTORY_CAP:
                self._anchor_back_stack.pop(0)
            self._text_browser.scrollToAnchor(url.fragment())
            self.linkActivated.emit(target)
            return
        # 带 scheme / 绝对地址：外部链接。Qt 侧的 openExternalLinks 恒为 False
        # （否则 anchorClicked 不会发出），所以这里自己交给系统浏览器。
        #
        # **必须过scheme 白名单。** 模型输出属于不可信输入，而
        # ``setOpenExternalLinks`` 默认是**开**的：没有白名单时
        # ``[click](javascript:...)`` / ``<a href="file:///C:/.../calc.exe">``
        # 都会原样交给 ``QDesktopServices`` → 系统 shell（Windows 上 file:
        # 指向 exe 会被 ShellExecuteEx 直接启动）。这不是 XSS —— Qt 富文本
        # 没有 JS 引擎，``<script>`` / ``onerror=`` 全部被忽略；问题只在
        # 「任意 scheme 交给 shell」。被拒的链接**仍然照常发
        # ``linkActivated``**，宿主想自己处理（弹确认框、复制到剪贴板）
        # 都还来得及。
        if (
            self._open_external_links
            and url.scheme().lower() in self._external_link_schemes
        ):
            QDesktopServices.openUrl(url)
        self.linkActivated.emit(target)

    def _toggle_code_block_expanded(self, raw_index: str) -> None:
        """折叠链接点击：切换代码块展开状态并重渲染。"""
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            return
        if index in self._expanded_code_blocks:
            self._expanded_code_blocks.discard(index)
        else:
            self._expanded_code_blocks.add(index)
        self._render()

    def _toggle_fold_expanded(self, raw_index: str) -> None:
        """推理块 / details 折叠标签点击：切换展开状态并重渲染。"""
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            return
        if index in self._expanded_folds:
            self._expanded_folds.discard(index)
        else:
            self._expanded_folds.add(index)
        self._render()

    def _toggle_task_by_ordinal(self, raw: str) -> None:
        """任务复选框点击：翻转源文本并重渲染（流式期间忽略）。"""
        if self._stream_active:
            return
        try:
            ordinal = int(raw)
        except (TypeError, ValueError):
            return
        if not 0 <= ordinal < len(self._task_items):
            return
        line_index, checked = self._task_items[ordinal]
        lines = self._source.split("\n")
        if not 0 <= line_index < len(lines):
            return
        new_checked = not checked

        def flip(match):
            prefix = match.group(1)
            rest = match.group(0)[len(prefix) :]
            body = rest[3:]
            return prefix + ("[x]" if new_checked else "[ ]") + body

        replaced, count = _TASK_LIST_RE.subn(flip, lines[line_index], count=1)
        if count == 0:
            return
        lines[line_index] = replaced
        self._source = "\n".join(lines)
        self._render()
        self.taskToggled.emit(ordinal, new_checked)

    def _on_image_clicked(self, position: int) -> None:
        """图片单击：公式/Mermaid 复制源码，普通图片发射 ``imageClicked``。"""
        cursor = QTextCursor(self.document())
        cursor.setPosition(max(0, min(position, self.document().characterCount() - 1)))
        candidates = [cursor.charFormat()]
        probe = QTextCursor(cursor)
        if probe.movePosition(
            QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor
        ):
            candidates.append(probe.charFormat())
        for fmt in candidates:
            if not fmt.isImageFormat():
                continue
            image_format = fmt.toImageFormat()
            name = image_format.name()
            tooltip = image_format.toolTip()
            if name.startswith("elamath://"):
                if tooltip.startswith("LaTeX: "):
                    latex = tooltip[len("LaTeX: ") :]
                    QApplication.clipboard().setText(latex)
                    self.formulaCopied.emit(latex)
                return
            if name.startswith(_MERMAID_IMAGE_PREFIX):
                if tooltip.startswith(_MERMAID_TIP_PREFIX):
                    code = tooltip[len(_MERMAID_TIP_PREFIX) :]
                    QApplication.clipboard().setText(code)
                    self.mermaidCopied.emit(code)
                return
            url = self._resolve_image_url(name, self.document().baseUrl())
            self.imageClicked.emit(url.toString())
            return

    # -- 占位 / 缩放 / 搜索 / 图片 / 导出 ----------------------------------

    def setPlaceholderText(self, text: str) -> None:
        """内容为空时的居中占位文本（如"正在生成…"），空字符串关闭。"""
        self._placeholder = text or ""
        self.update()

    def placeholderText(self) -> str:
        """获取占位文本。"""
        return self._placeholder

    def setZoomFactor(self, factor: float) -> None:
        """缩放系数（相对默认字号，同时影响公式尺寸），夹在 0.25–4.0。"""
        factor = max(0.25, min(4.0, float(factor)))
        if abs(factor - self._zoom_factor) < 1e-6:
            return
        self._zoom_factor = factor
        font = self.document().defaultFont()
        font.setPointSizeF(self._base_font_point_size * factor)
        self.document().setDefaultFont(font)
        if self._source:
            self._render()

    def zoomFactor(self) -> float:
        """获取缩放系数。"""
        return self._zoom_factor

    def zoomIn(self, step: float = 0.1) -> None:
        """放大一级。"""
        self.setZoomFactor(self._zoom_factor + step)

    def zoomOut(self, step: float = 0.1) -> None:
        """缩小一级。"""
        self.setZoomFactor(self._zoom_factor - step)

    def searchText(self, text: str, caseSensitive: bool = False) -> int:
        """高亮全部匹配并选中第一处，返回匹配数量。"""
        self.clearSearch()
        if not text:
            return 0
        flags = QTextDocument.FindFlag(0)
        if caseSensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        cursor = QTextCursor(self.document())
        while True:
            found = self.document().find(text, cursor, flags)
            if found.isNull():
                break
            selection = QTextEdit.ExtraSelection()
            selection.cursor = found
            fmt = QTextCharFormat()
            fmt.setBackground(self._search_bg)
            selection.format = fmt
            self._search_selections.append(selection)
            cursor = found
        if self._search_selections:
            self._text_browser.setExtraSelections(self._search_selections)
            self._text_browser.setTextCursor(self._search_selections[0].cursor)
            self._last_search = text
        return len(self._search_selections)

    def findNext(self, backward: bool = False) -> bool:
        """在 :meth:`searchText` 的匹配间循环跳转，返回是否成功跳转。"""
        if not self._search_selections:
            return False
        current = self._text_browser.textCursor().selectionStart()
        positions = [s.cursor.selectionStart() for s in self._search_selections]
        if backward:
            candidates = [p for p in positions if p < current]
            target = max(candidates) if candidates else positions[-1]
        else:
            candidates = [p for p in positions if p > current]
            target = min(candidates) if candidates else positions[0]
        self._text_browser.setTextCursor(
            self._search_selections[positions.index(target)].cursor
        )
        return True

    def clearSearch(self) -> None:
        """清除搜索高亮。"""
        self._search_selections = []
        self._last_search = ""
        self._text_browser.setExtraSelections([])

    def setBaseUrl(self, url) -> None:
        """图片等资源的基准路径（本地目录路径串 / URL 串 / ``QUrl``）。"""
        if isinstance(url, QUrl):
            qurl = QUrl(url)
        elif isinstance(url, str):
            if url.startswith(("http://", "https://", "file:")):
                qurl = QUrl(url)
            else:
                qurl = QUrl.fromLocalFile(url)
        else:
            raise TypeError(f"url 应为 str 或 QUrl，收到 {type(url).__name__}")
        if qurl.isLocalFile() and not qurl.path().endswith("/"):
            qurl.setPath(qurl.path() + "/")
        self._base_url = qurl
        self._text_browser.document().setBaseUrl(qurl)

    def baseUrl(self) -> QUrl:
        """获取资源基准路径。"""
        return self._base_url

    def setRemoteImagesEnabled(self, on: bool) -> None:
        """是否允许加载远程（http/https）图片，默认关闭；``False`` 时拦截并显示占位文本。"""
        self._remote_images_enabled = bool(on)
        self._text_browser.remote_images_enabled = bool(on)
        if self._source:
            self._render()

    def remoteImagesEnabled(self) -> bool:
        """是否允许加载远程图片。"""
        return self._remote_images_enabled

    def toHtml(self, embedImages: bool = False) -> str:
        """导出当前渲染结果为 HTML；``embedImages=True`` 时把公式 / Mermaid /
        本地图片内嵌成 data URI（单文件分享用，远程图片保持原样），默认关闭。
        """
        html = self.document().toHtml()
        if not embedImages:
            return html

        def replace(match: re.Match) -> str:
            embedded = self._embed_image_data_uri(match.group(2))
            if not embedded:
                return match.group(0)
            return match.group(1) + embedded + match.group(3)

        return re.sub(r'(<img\b[^>]*?\ssrc=")([^"]*)(")', replace, html)

    def _embed_image_data_uri(self, name: str) -> str:
        """图片名 → data URI（生成图片 / 本地文件；远程或缺失返回空串）。"""
        url = self._resolve_image_url(name, self.document().baseUrl())
        if url.scheme() in ("elamath", "elamermaid"):
            resource = self.document().resource(
                QTextDocument.ResourceType.ImageResource, url
            )
            if not isinstance(resource, QImage):
                # ``data:`` 资源是 QByteArray（见 _load_image_resource 的说明），
                # 这里只处理 elamath / elamermaid，但仍不能假设类型
                converter = getattr(resource, "toImage", None)
                resource = converter() if callable(converter) else None
            if resource is None:
                return ""
            image = resource
            if image.isNull():
                return ""
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            data = bytes(buffer.data())
            return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
        if not url.isLocalFile():
            return ""
        path = url.toLocalFile()
        if not os.path.isfile(path):
            return ""
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as handle:
            data = handle.read()
        return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")

    def toPlainText(self) -> str:
        """导出当前渲染结果为纯文本。"""
        return self.document().toPlainText()

    def renderIssues(self) -> list:
        """获取本次渲染的降级记录。

        :returns: ``[(类型, 详情)]``，类型为 ``"math"`` / ``"mermaid"`` / ``"image"``；
            全量渲染时重置，流式期间追加
        """
        return list(self._render_issues)

    def markdownSelection(self) -> str:
        """把当前选中内容还原为 Markdown 源（块级近似）。

        - 代码块按源围栏精确还原（含围栏行）；
        - 普通块按归一化文本匹配源行，多块合并为连续切片；
        - 任一块无法映射时退回选中纯文本（无选中内容时返回空串）。
        """
        cursor = self._text_browser.textCursor()
        raw_selection = cursor.selection().toPlainText()
        if not cursor.hasSelection():
            return ""
        document = self.document()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        first = document.findBlock(start)
        last = document.findBlock(max(end - 1, start))
        if not first.isValid() or not last.isValid():
            return raw_selection
        ranges: list[tuple[int, int]] = []
        mapping = self._ensure_source_map()
        block = first
        while block.isValid():
            mapped = mapping.get(block.blockNumber())
            if block.text().strip() or mapped is not None:
                if mapped is None:
                    return raw_selection
                ranges.append(mapped)
            if block.blockNumber() >= last.blockNumber():
                break
            block = block.next()
        if not ranges:
            return raw_selection
        lines = self._source.split("\n")
        quote_start = min(item[0] for item in ranges)
        quote_end = max(item[1] for item in ranges)
        quote = "\n".join(lines[quote_start:quote_end]).strip("\n")
        return quote or raw_selection

    def _ensure_source_map(self) -> dict:
        """取源行映射；未构建时**按需**构建一次并缓存。

        渲染入口一律把它置回 ``None``（作废），构建成本只由真正用到
        ``markdownSelection()``（引用回复）的会话支付。
        """
        mapping = self._block_source_map
        if mapping is None:
            mapping = self._build_block_source_map()
            self._block_source_map = mapping
        return mapping

    def _build_block_source_map(self) -> dict:
        """构建 文档块号 → 源行范围 的近似映射（引用回复用）。

        代码块使用表格式上记录的源围栏范围；普通块用归一化文本双指针匹配。
        源行归一化结果**预计算一次**（原先每个候选起点重复归一次，实测
        51KB / 200 块文档归一化 10 万次 ≈ 0.4s）。
        """
        lines = self._source.split("\n")
        normalized = [_source_line_text(line) for line in lines]
        code_ranges: dict = {}
        for table in self._iter_tables(self.document()):
            stored = table.format().property(_CODE_SOURCE_PROPERTY)
            if not isinstance(stored, str):
                continue
            start_text, _, end_text = stored.partition(",")
            try:
                code_range = (int(start_text), int(end_text))
            except ValueError:
                continue
            for row in range(table.rows()):
                cell = table.cellAt(row, 0)
                first = cell.firstCursorPosition().blockNumber()
                last = cell.lastCursorPosition().blockNumber()
                for number in range(first, last + 1):
                    code_ranges[number] = code_range
        mapping: dict = {}
        source_index = 0
        block = self.document().begin()
        while block.isValid():
            number = block.blockNumber()
            code_range = code_ranges.get(number)
            if code_range is not None:
                mapping[number] = code_range
                source_index = max(source_index, code_range[1])
            else:
                text = block.text().strip()
                if not text:
                    mapping[number] = None
                else:
                    matched = _match_source_lines(normalized, source_index, text)
                    if matched is not None:
                        mapping[number] = matched
                        source_index = matched[1]
                    else:
                        mapping[number] = None
            block = block.next()
        return mapping

    def exportPdf(
        self,
        path: str,
        *,
        pageSize="A4",
        marginsMm=15.0,
    ) -> bool:
        """把当前渲染结果导出为 PDF 文件。

        ``pageSize`` 是纸张（``"A4"`` / ``"Letter"`` 等
        :class:`QPageSize.PageSizeId` 名称，或直接传 :class:`QPageSize`）；
        ``marginsMm`` 是页边距（毫米）：单值表示四边一致，二元组 ``(水平, 垂直)``
        或四元组 ``(左, 上, 右, 下)``。
        """
        if not path:
            return False
        if isinstance(pageSize, QPageSize):
            size = pageSize
        else:
            size_id = getattr(
                QPageSize.PageSizeId, str(pageSize).upper(), QPageSize.PageSizeId.A4
            )
            size = QPageSize(size_id)
        if isinstance(marginsMm, (int, float)):
            margins = QMarginsF(*([float(marginsMm)] * 4))
        else:
            values = [float(value) for value in marginsMm]
            if len(values) == 2:
                margins = QMarginsF(values[0], values[1], values[0], values[1])
            elif len(values) == 4:
                margins = QMarginsF(*values)
            else:
                margins = QMarginsF(15.0, 15.0, 15.0, 15.0)
        try:
            writer = QPdfWriter(str(path))
            writer.setResolution(96)
            writer.setPageSize(size)
            writer.setPageMargins(margins, QPageLayout.Unit.Millimeter)
            self.document().print(writer)
        except Exception:
            return False
        return os.path.exists(path)

    def printDocument(self, printer=None) -> bool:
        """打印当前渲染内容。

        ``printer`` 为已配置的 :class:`QPrinter`；``None`` 时弹系统打印对话框
        （取消返回 ``False``）。
        """
        try:
            if printer is None:
                from PyQt6.QtPrintSupport import QPrintDialog, QPrinter

                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                dialog = QPrintDialog(printer, self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return False
            self.document().print(printer)
        except Exception:
            return False
        return True

    def isRendering(self) -> bool:
        """是否正在分块渲染大文档。"""
        return bool(self._large_render_chunks)

    def clearCache(self) -> None:
        """清空代码高亮、公式与 Mermaid 渲染缓存。"""
        self._highlight_cache.clear()
        clear_math_cache()
        if self._mermaid_renderer is not None:
            self._mermaid_renderer.clearCache()

    def setHighlightCacheSize(self, size: int) -> None:
        """代码高亮缓存条数上限（``<= 0`` 时清空并停止缓存）。"""
        self._highlight_cache_cap = max(0, int(size))
        while (
            self._highlight_cache
            and len(self._highlight_cache) > self._highlight_cache_cap
        ):
            self._highlight_cache.pop(next(iter(self._highlight_cache)))

    def highlightCacheSize(self) -> int:
        """获取代码高亮缓存条数上限（0 表示不缓存）。"""
        return self._highlight_cache_cap

    # -- 流式追加 ----------------------------------------------------------

    def beginStream(self) -> None:
        """开始流式模式：清空内容，等待 ``appendMarkdown`` 追加。"""
        self._stop_stream()
        self._cancel_large_render()
        self._expanded_code_blocks.clear()
        self._expanded_folds.clear()
        self._block_source_map = None
        self._stream_active = True
        self._stream_source = ""
        self._stream_committed = 0
        self._stream_tail_pos = 0
        self._stream_cut_from = 0
        self._stream_first_flush = True
        self._stream_capture_at_bottom = True
        self._source = ""
        # 清空文档会销毁旧代码表对象；按钮 / 表格引用必须同步失效，
        # 否则重绘或布局刷新会访问已删除的 C++ 对象（PyQt 静默 abort）
        self._rebuild_code_buttons([])
        self._reset_image_scan()
        self._text_browser.document().clear()
        self._caret_visible = True
        # 持续动效：Reduced/Disabled 下不闪，但**光标必须留在可见态** ——
        # 闪烁的静态基态是「亮着」，停在 phase 0 等于把光标删掉，用户会以为
        # 流式卡住了。on_stop 负责摆静态基态（启动时和运行期切策略都会调）。
        start_idle_loop(
            self._caret_timer, STREAM_CARET_BLINK_MS, on_stop=self._stop_stream_caret
        )

    def appendMarkdown(self, chunk: str) -> None:
        """流式追加 Markdown 片段（AI 逐 token 输出场景）。

        稳定段只增量提交一次；未稳定的尾部按节流整体重渲染替换。
        贴底时自动跟随滚动，用户上翻后保持阅读位置。最终内容以
        ``endStream`` 的全量渲染为准。

        :param chunk: Markdown 片段
        """
        if not isinstance(chunk, str):
            raise TypeError(f"chunk 应为 str，收到 {type(chunk).__name__}")
        if not self._stream_active:
            self._cancel_large_render()
            bar = self._text_browser.verticalScrollBar()
            captured_at_bottom = bar.value() >= bar.maximum() - _SCROLL_MARGIN
            prefix = self._source
            self.beginStream()
            self._stream_capture_at_bottom = captured_at_bottom
            self._stream_source = prefix
        self._stream_source += chunk
        self._source = self._stream_source

        # 首个分片不走节流：此刻文档还是空的，等一个 24ms 节拍会在屏幕上留下
        # 「空查看器」窗口（慢机器上更久）；越早渲染，布局越早拿到真实内容与
        # 高度。只在文档为空且定时器空闲时走这条快路径，不会变成逐片全量渲染。
        if not self._stream_timer.isActive() and (
            self._text_browser.document().characterCount() <= 1
        ):
            self._stream_flush()
            return
        if self._stream_timer.isActive():
            return
        tail_len = len(self._stream_source) - self._stream_committed
        if tail_len > _STREAM_LONG_CHARS:
            interval = _STREAM_INTERVAL_LONG
        elif tail_len > _STREAM_MID_CHARS:
            interval = _STREAM_INTERVAL_MID
        else:
            interval = _STREAM_INTERVAL
        self._stream_timer.start(interval)

    def endStream(self) -> None:
        """结束流式模式：全量重渲染，保证与一次性设置内容一致。"""
        if not self._stream_active:
            return
        self._stop_stream()
        self._source = self._stream_source
        self._render()
        self.streamFinished.emit()

    def isStreaming(self) -> bool:
        """当前是否处于流式模式。"""
        return self._stream_active

    def setStickToBottom(self, on: bool) -> None:
        """贴底时是否自动跟随滚动（``True`` = 内容在底部则追加后自动滚到底）。"""
        self._stick_to_bottom = bool(on)

    def stickToBottom(self) -> bool:
        """是否贴底自动跟随。"""
        return self._stick_to_bottom

    def _stop_stream(self) -> None:
        if not is_deleted(self._stream_timer):
            self._stream_timer.stop()
        if not is_deleted(self._caret_timer):
            self._caret_timer.stop()
        if self._caret_visible:
            self._caret_visible = False
            if not is_deleted(self):
                self.update()
        self._stream_active = False

    def _stop_stream_caret(self) -> None:
        """停掉闪烁但**把光标留在可见态**。

        闪烁的静态基态是「亮着」。直接 ``_caret_timer.stop()`` 的话光标会停在
        当拍的相位 —— 有 50% 概率停在「不可见」，流式输出看起来就像卡住没在动。
        「停掉」不等于「不画」：必须显式摆好静态态。
        """
        if is_deleted(self._caret_timer):
            return
        self._caret_timer.stop()
        if not self._caret_visible:
            self._caret_visible = True
            if not is_deleted(self):
                self.update()

    def _toggle_stream_caret(self) -> None:
        """流式末尾打字光标闪烁。"""
        if is_deleted(self):
            return
        self._caret_visible = not self._caret_visible
        self.update()

    # -- 大文档分块渲染 ----------------------------------------------------

    @staticmethod
    def _split_large_chunks(text: str) -> list:
        """按空行 / 换行 / 空白边界把超长文本切成渲染块。"""
        chunks: list[str] = []
        start = 0
        length = len(text)
        while start < length:
            end = min(start + _LARGE_RENDER_CHUNK, length)
            if end < length:
                floor = start + _LARGE_RENDER_CHUNK // 2
                cut = text.rfind("\n\n", floor, end)
                if cut == -1:
                    cut = text.rfind("\n", floor, end)
                if cut == -1:
                    cut = text.rfind(" ", floor, end)
                if cut != -1:
                    end = cut + 1
            chunks.append(text[start:end])
            start = end
        return chunks

    def _begin_large_render(self) -> None:
        """启动分块渲染：清空文档后按时间片逐块提交。"""
        self._large_render_chunks = self._split_large_chunks(self._source)
        self._large_render_index = 0
        self._render_issues = []
        # 同 beginStream：清空文档前先让旧代码表引用失效（分块渲染期间
        # 事件循环仍会重绘，访问已删除表格会 PyQt abort）
        self._rebuild_code_buttons([])
        # **同 beginStream：必须作废源行映射**。懒建后只置 ``None``（下次
        # ``markdownSelection()`` 重建）；旧映射若留着，行号区间会被套到新
        # 文档上，``markdownSelection()`` 会返回**别的段落**的内容。
        self._block_source_map = None
        self._reset_image_scan()
        self._text_browser.document().clear()
        self._large_render_timer.start(0)

    def _render_large_step(self) -> None:
        """渲染一个时间片内的若干块，随后让出事件循环。"""
        if is_deleted(self) or is_deleted(self._text_browser):
            return
        if not self._large_render_chunks:
            return
        timer = QElapsedTimer()
        timer.start()
        document = self._text_browser.document()
        total = len(self._large_render_chunks)
        while (
            self._large_render_index < total
            and timer.elapsed() < _LARGE_RENDER_BUDGET_MS
        ):
            chunk = self._large_render_chunks[self._large_render_index]
            fragment, block_format = self._render_fragment(chunk, document)
            cursor = QTextCursor(document)
            cursor.movePosition(QTextCursor.MoveOperation.End)
            if document.characterCount() > 1:
                cursor.insertBlock(block_format, QTextCharFormat())
            cursor.insertFragment(fragment)
            self._large_render_index += 1
        self.renderingProgress.emit(int(self._large_render_index * 100 / total))
        if self._large_render_index >= total:
            self._finish_large_render()
        else:
            self._large_render_timer.start(0)

    def _finish_large_render(self) -> None:
        self._large_render_chunks = []
        self._large_render_index = 0
        # 源行映射懒建（markdownSelection 首次使用时构建）：分块路径全程不调
        # _render()，这里同样只作废，绝不提前付出逐块匹配的代价。
        self._block_source_map = None
        self.renderingProgress.emit(100)
        self._sync_code_buttons()
        self._schedule_layout_refresh()
        self.renderingFinished.emit()

    def _cancel_large_render(self) -> None:
        self._large_render_timer.stop()
        self._large_render_chunks = []
        self._large_render_index = 0

    def _stream_flush(self) -> None:
        """流式刷新：提交新稳定段并替换未稳定尾部。

        迟到的定时器回调可能落在控件已销毁之后（窗口关闭 / 消息重建），
        此时直接忽略，避免访问已删除的 C++ 对象（PyQt 会 abort）。
        """
        if is_deleted(self) or is_deleted(self._text_browser):
            return
        try:
            self._flush_stream()
        except Exception:
            if is_deleted(self) or is_deleted(self._text_browser):
                return
            # 增量状态异常：退回全量渲染，保证内容正确
            self._stop_stream()
            self._render()

    def _flush_stream(self) -> None:
        browser = self._text_browser
        document = browser.document()
        bar = browser.verticalScrollBar()
        old_value, old_max = bar.value(), bar.maximum()
        at_bottom = old_value >= old_max - _SCROLL_MARGIN
        if self._stream_first_flush:
            # 从静态模式续写时 beginStream 会清空文档，首个 flush 的
            # max==0 不能作为贴底依据；使用清空前捕获的滚动状态
            at_bottom = self._stream_capture_at_bottom
            self._stream_first_flush = False

        browser.setUpdatesEnabled(False)
        try:
            cut, next_scan = _stable_cut(
                self._stream_source,
                self._stream_committed,
                allow_sentence=True,
                safe_from=self._stream_cut_from,
            )
            self._stream_cut_from = next_scan
            cut = max(cut, self._stream_committed)

            # 删除旧尾部
            if document.characterCount() > 1:
                # 尾段里的代码卡 QTextTable 会随内容一起析构，但**不做全量清空**：
                # 稳定段的表对象不受影响，按钮按表身份增量复用（见
                # _sync_code_buttons）。失效表由那里的 is_deleted 过滤，
                # _position_code_buttons / _paint_code_card_chrome 各自也判存活 ——
                # 期间滚动信号触发的重绘 / 定位不会访问已析构对象。
                cursor = QTextCursor(document)
                position = max(
                    0, min(self._stream_tail_pos, document.characterCount() - 1)
                )
                cursor.setPosition(position)
                cursor.movePosition(
                    QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor
                )
                cursor.removeSelectedText()
            else:
                self._stream_tail_pos = 0

            # 提交新稳定段（只渲染一次）
            if cut > self._stream_committed:
                segment = self._stream_source[self._stream_committed : cut]
                fragment, block_format = self._render_fragment(segment, document)
                cursor = QTextCursor(document)
                cursor.movePosition(QTextCursor.MoveOperation.End)
                if document.characterCount() > 1:
                    cursor.insertBlock(block_format, QTextCharFormat())
                cursor.insertFragment(fragment)
                self._stream_committed = cut

            self._stream_tail_pos = document.characterCount() - 1

            # 渲染未稳定尾部
            tail = self._stream_source[self._stream_committed :]
            if tail:
                cursor = QTextCursor(document)
                cursor.movePosition(QTextCursor.MoveOperation.End)
                tail_fragment, tail_block_format = self._render_fragment(tail, document)
                if document.characterCount() > 1:
                    cursor.insertBlock(tail_block_format, QTextCharFormat())
                cursor.insertFragment(tail_fragment)
        finally:
            browser.setUpdatesEnabled(True)

        if self._stick_to_bottom and at_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(min(old_value, bar.maximum()))
        browser.viewport().update()
        self._sync_embedded_height()
        # 立刻重建代码按钮（不要等 80ms 后的 _schedule_layout_refresh）
        self._sync_code_buttons()
        self._schedule_layout_refresh()

    def _render_fragment(self, text: str, resource_doc: QTextDocument) -> tuple:
        """把一段 Markdown 渲染为可插入主文档的片段。

        使用临时文档走与全量渲染完全相同的管线（代码/表格/公式/主题色），
        因此片段插入后与一次性渲染结果一致；公式图片资源注册在主文档上，
        片段插入后仍可解析。

        :returns: ``(片段, 片段首块的 QTextBlockFormat)``。``insertFragment`` 把片段
            首块并入光标所在块**并沿用该块自己的格式**，所以造分块必须用首块格式，
            否则这一段的段距 / 行高 / 标题属性全丢。
        """
        scratch = QTextDocument()
        scratch.setDefaultStyleSheet(self._document_css())
        scratch.setDefaultFont(self.document().defaultFont())
        scratch.setBaseUrl(self._text_browser.document().baseUrl())
        self._render_into(scratch, text, resource_doc=resource_doc)
        cursor = QTextCursor(scratch)
        cursor.select(QTextCursor.SelectionType.Document)
        fragment = QTextDocumentFragment(cursor)
        first = scratch.firstBlock()
        block_format = first.blockFormat() if first.isValid() else QTextBlockFormat()
        return fragment, block_format

    # -- 外观 --------------------------------------------------------------

    def setCodeFontFamily(self, family: str) -> None:
        """代码字体族；空字符串恢复系统等宽字体。"""
        if family:
            self._code_font_family = family
        else:
            self._code_font_family = _default_code_font_family()
        self._highlight_cache.clear()
        self._applyThemeStyle()

    def codeFontFamily(self) -> str:
        """获取代码字体族。"""
        return self._code_font_family

    def setCodeBlockCollapseLines(self, lines: int) -> None:
        """超长代码块折叠后的行数（``0`` 关闭折叠）。"""
        self._code_collapse_lines = max(0, int(lines))
        if self._source:
            self._render()

    def codeBlockCollapseLines(self) -> int:
        """获取代码块折叠行数。"""
        return self._code_collapse_lines

    def setLineNumbersEnabled(self, on: bool) -> None:
        """代码块行号显示（默认关闭；复制内容不含行号）。"""
        on = bool(on)
        if on == self._line_numbers_enabled:
            return
        self._line_numbers_enabled = on
        if self._source:
            self._render()

    def lineNumbersEnabled(self) -> bool:
        """是否显示代码块行号。"""
        return self._line_numbers_enabled

    def setCodeTokenColors(self, colors: Optional[dict] = None) -> None:
        """覆盖代码高亮 token 颜色（``None`` 清除覆盖、回到主题自带配色）。

        可用键：``keyword/constant/type/function/class/decorator/builtin/
        attribute/tag/string/number/comment/operator``（未提供的键保留主题默认，
        覆盖对浅 / 深两套同时生效）。
        """
        overrides = {}
        if colors:
            for key, value in colors.items():
                if key in _MD_THEME_SYNTAX_KEYS and isinstance(value, str):
                    overrides[key] = value
        self._token_overrides = overrides
        self._applyThemeStyle()

    def codeTokenColors(self) -> dict:
        """获取当前主题 / 模式下的 token 调色板（含覆盖；颜色为 hex 字符串）。"""
        return dict(self._token_palette)

    def setMarkdownTheme(self, name: str) -> bool:
        """切换 markdown 主题（内置 / 已注册），立即重渲染已有内容。

        切换成功（或本来就是该主题）返回 ``True``；未知名称返回 ``False`` 且
        不改动当前主题。
        """
        if name not in _MD_THEMES:
            return False
        if name == self._md_theme:
            return True
        self._md_theme = name
        self._applyThemeStyle()
        return True

    def markdownTheme(self) -> str:
        """当前 markdown 主题名（默认取 :func:`defaultMarkdownTheme`）。"""
        return self._md_theme

    def setTableZebra(self, on: bool) -> None:
        """表格斑马纹（数据行奇偶淡底）。"""
        on = bool(on)
        if on == self._table_zebra:
            return
        self._table_zebra = on
        if self._source:
            self._render()

    def tableZebra(self) -> bool:
        """是否启用表格斑马纹。"""
        return self._table_zebra

    def setTableColumnWidths(self, widths: Optional[list] = None) -> None:
        """按百分比设置表格列宽（``None`` 恢复自动）；数量与表格列数不一致时
        该表忽略设置。
        """
        if widths is None:
            self._table_column_widths = None
        else:
            try:
                values = [float(width) for width in widths]
            except (TypeError, ValueError, OverflowError):
                # ``float(10 ** 400)`` 抛OverflowError 而**不是** ValueError
                # —— 本方法docstring 承诺「数量与列数不一致时忽略设置」，
                # 是一条容错路径，就该把这类输入也容错掉。
                return
            if not values or any(width <= 0 for width in values):
                self._table_column_widths = None
            else:
                self._table_column_widths = values
        if self._source:
            self._render()

    def tableColumnWidths(self) -> Optional[list]:
        """获取当前表格列宽设置（``None`` 表示自动）。"""
        if self._table_column_widths is None:
            return None
        return list(self._table_column_widths)

    def setBorderRadius(self, r: int) -> None:
        self._border_radius = max(0, r)
        # 圆角需要视口透出（不透明底色会把四角补成方角）；0 恢复正常底色策略
        self._apply_viewport_base()
        self.update()

    def borderRadius(self) -> int:
        return self._border_radius

    def setViewportBackground(self, color: Optional[QColor]) -> None:
        """设置文本视口的显式底色（``None`` = 恢复按模式自动）。

        自动策略：非嵌入且无圆角时用与自绘背景一致的 ``BasicPress`` **不透明**底色
        （外观等价，避开透明视口在部分平台（Win7）上的慢速重绘路径）；嵌入模式或
        圆角形态保持透明，由外层容器 / 圆角遮罩提供底色。显式传色时一律以该色作
        不透明视口底色；确实需要严格透出下层时传透明色（``QColor(0, 0, 0, 0)``）。
        """
        self._viewport_bg = QColor(color) if color is not None else None
        self._apply_viewport_base()

    def viewportBackground(self) -> Optional[QColor]:
        """获取宿主显式设置的视口底色（``None`` = 未设置、走自动策略）。"""
        return QColor(self._viewport_bg) if self._viewport_bg is not None else None

    def _apply_viewport_base(self) -> None:
        """按「显式底色 > 嵌入 / 圆角透明 > 不透明 BasicPress」应用视口底色。"""
        if is_deleted(self._text_browser):
            return
        if self._viewport_bg is not None:
            setTextBaseColor(self._text_browser, self._viewport_bg)
        elif self._embedded or self._border_radius > 0:
            setTextBaseColor(self._text_browser, None)
        else:
            setTextBaseColor(
                self._text_browser,
                eTheme.getThemeColor(
                    self._theme_mode, ElaThemeType.ThemeColor.BasicPress
                ),
            )

    # -- 嵌入模式 ----------------------------------------------------------

    def setEmbeddedMode(self, on: bool) -> None:
        """嵌入模式：透明背景、隐藏内部滚动条、高度随文档自适应。

        适合把查看器嵌进聊天消息等外层滚动容器：

        - 不再自绘背景（由父容器提供底色）；
        - 两个滚动条始终隐藏，滚轮事件交给外层容器；
        - 文档高度变化（含流式追加）时自动调整控件高度（默认关闭，关闭后恢复原有行为）。
        """
        on = bool(on)
        if on == self._embedded:
            return
        self._embedded = on
        self._apply_viewport_base()
        policy = (
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            if on
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._text_browser.setVerticalScrollBarPolicy(policy)
        self._text_browser.setHorizontalScrollBarPolicy(policy)
        self._text_browser.forward_wheel = on
        if on:
            self._sync_embedded_height()
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.updateGeometry()
        self.update()

    def embeddedMode(self) -> bool:
        """是否处于嵌入模式。"""
        return self._embedded

    def setEmbeddedExtra(self, extra: int) -> None:
        """嵌入模式高度余量（像素，默认 2）：追加到文档高度上，避免取整误差
        触发内部滚动。
        """
        self._embedded_extra = max(0, int(extra))
        self._sync_embedded_height()

    def embeddedExtra(self) -> int:
        """获取嵌入模式高度余量（像素）。"""
        return self._embedded_extra

    def setEmbeddedTrimBottom(self, on: bool) -> None:
        """设置嵌入模式是否裁剪文末空白（默认关闭）。

        开启后，控件高度不再包含文末段落的下边距（Qt Markdown 导入器会给
        每个段落加下边距，最后一个段落的下边距是纯空白），控件底边贴合
        正文内容 —— 聊天消息中「正文 → 工具面板 / 下一步思考」的视觉间距
        因此与其它分段间距一致。表格 / 代码块等非段落结尾按块边界取更小
        值（``min``），不会裁剪内容。
        """
        on = bool(on)
        if on == self._embedded_trim_bottom:
            return
        self._embedded_trim_bottom = on
        self._sync_embedded_height()

    def embeddedTrimBottom(self) -> bool:
        """是否裁剪嵌入模式下的文末空白。"""
        return self._embedded_trim_bottom

    def _sync_embedded_height(self) -> None:
        """嵌入模式下按文档高度更新控件高度（幂等，仅变化时应用）。

        **测量值不可信时宁可不动**（保留上一次高度）。三道护栏对应同一条慢机器
        时序：查看器刚创建 / 文档刚被清空时布局还没跑，此时按占位宽度（实测
        98px，不是 0）折行测出的高度一旦 ``setFixedHeight`` 就被冻结，直到下一
        次流式 flush 或 80ms 重排才纠正 —— 慢 CPU 上事件循环被分片占满，这个
        窗口会拉长到肉眼可见（「思考内容与后续分段之间多出数行空白」）。护栏：

        - 视口宽小于真实布局下限（首次布局还没跑）；
        - 文档 ``textWidth`` 与视口宽不符（还没按当前宽度重排，``document.size()``
          是旧宽度的测量值）；
        - ``_source`` 非空却测出 0 高度（``beginStream`` 清空后布局未跑，套用会
          把控件压成 2px 细缝）。
        """
        if not self._embedded:
            return
        document = self._text_browser.document()
        margins = self._text_browser.contentsMargins()
        viewport_width = self._text_browser.viewport().width()
        text_width = document.textWidth()
        content = document.size().height()
        if self._embedded_trim_bottom:
            content = min(content, self._embedded_content_bottom(document))
        reliable = (
            viewport_width > _EMBED_MIN_VALID_WIDTH
            and (
                text_width <= 0
                or abs(text_width - viewport_width) <= _EMBED_WIDTH_SLACK
            )
            and (content > 0 or not self._source)
        )
        height = (
            int(math.ceil(max(0.0, content) + margins.top() + margins.bottom()))
            + self._embedded_extra
        )
        height = max(1, height)
        if not reliable:
            self._debug_height_sync(
                "skipped(unreliable)", height, viewport_width, text_width, content
            )
            return
        if self._embedded_trim_bottom:
            # 裁剪后控件高度小于文档高度，内部出现可滚动范围：必须把滚动位置
            # 归零（否则 QTextBrowser 会贴底显示文末边距、并裁掉首行上边距）。
            bar = self._text_browser.verticalScrollBar()
            if bar.value() != 0:
                bar.setValue(0)
        if self.minimumHeight() == height and self.maximumHeight() == height:
            self._debug_height_sync(
                "unchanged", height, viewport_width, text_width, content
            )
            return
        self._debug_height_sync("applied", height, viewport_width, text_width, content)
        self.setFixedHeight(height)

    def _debug_height_sync(
        self,
        action: str,
        height: int,
        viewport_width: int,
        text_width: float,
        content: float,
    ) -> None:
        """嵌入高度同步诊断日志（``ELACHAT_DEBUG_LAYOUT=1`` 时输出到 stderr）。"""
        if not _DEBUG_LAYOUT:
            return
        sys.stderr.write(
            "[ElaMarkdownViewer] height sync %s: height=%d viewportW=%d textW=%.1f"
            " content=%.1f srcLen=%d streaming=%s\n"
            % (
                action,
                height,
                viewport_width,
                text_width,
                content,
                len(self._source),
                self._stream_active,
            )
        )

    @staticmethod
    def _embedded_content_bottom(document: QTextDocument) -> float:
        """文末内容底边（不含最后一段落的下边距与文末文档边距）。

        布局未就绪（流式首帧 / 宽度为 0）时返回文档高度，保持原行为。
        """
        total = document.size().height()
        last = document.lastBlock()
        if not last.isValid():
            return total
        rect = document.documentLayout().blockBoundingRect(last)
        if rect.height() <= 0 or rect.bottom() <= 0:
            return total
        return rect.bottom()

    # -- 渲染 --------------------------------------------------------------

    def _render(self) -> None:
        """按当前主题全量渲染 ``_source``。"""
        browser = self._text_browser
        document = browser.document()
        bar = browser.verticalScrollBar()
        old_value, old_max = bar.value(), bar.maximum()
        at_bottom = old_value >= old_max - _SCROLL_MARGIN

        browser.setUpdatesEnabled(False)
        try:
            self._render_issues = []
            self._render_into(document, self._source)
        finally:
            browser.setUpdatesEnabled(True)
        # 源行映射懒建：渲染路径不付逐块双指针匹配的代价（实测 51KB 文档
        # 0.45s、占全量渲染 40%+），markdownSelection() 首次使用时才构建
        self._block_source_map = None
        # _render_into 已按当前视口宽度处理过全部图片：记录扫描水位，
        # 后续增量重排只扫新增块
        self._mark_images_scanned()
        if self._stream_active:
            # 全量渲染后增量状态失效，从头重新提交
            self._stream_committed = 0
            self._stream_tail_pos = 0
            self._stream_cut_from = 0
        if at_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(min(old_value, bar.maximum()))
        browser.viewport().update()
        self._sync_code_buttons()
        self._sync_embedded_height()
        self._schedule_layout_refresh()
        self._needs_render = False

    def _ensure_rendered(self) -> None:
        """可见时补齐被懒掉的重建（主题 / 配色族在隐藏时只标记，见 _applyThemeStyle）。"""
        if self._needs_render and self._source:
            self._needs_render = False
            self._render()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._ensure_rendered()

    @staticmethod
    def _replace_tokens_in_order(document: QTextDocument, entries, replace) -> None:
        """按文档顺序替换占位符：把上一次命中处作为下一次的搜索起点。

        占位符由预处理按文档顺序生成。逐次 ``document.find`` 都从**文档头**
        全量扫描时，N 个占位符的总代价是 O(N × 文档长)（实测 400 个 ≈ 0.1s、
        占全量渲染 20%）。

        ``entries`` 为 ``[(token, payload)]``，``replace(found, payload)`` 负责
        单次替换；替换后从 ``found.position()``（替换文本末尾）继续 —— 替换
        内容是用户文本或私有区占位符，不会再包含后续 token。
        """
        search = QTextCursor(document)
        for token, payload in entries:
            found = document.find(token, search)
            if found.isNull():
                continue
            replace(found, payload)
            search.setPosition(found.position())

    def _render_into(
        self,
        document: QTextDocument,
        source: str,
        resource_doc: Optional[QTextDocument] = None,
    ) -> None:
        """完整渲染管线（主文档与流式片段临时文档共用）。

        ``resource_doc`` 是公式图片的资源注册文档，缺省为目标文档。

        后处理分**两段编辑块**，把逐项 ``beginEditBlock`` 触发的重排从几十次
        压到两次（实测 51KB / 200 代码块文档光 ``endEditBlock`` 就 0.27s）。
        两段的分界是**帧树**：编辑块内 Qt 的帧树是陈旧的（实测
        ``cursor.currentTable()`` 恒 ``None``、``rootFrame().childFrames()``
        看不到新表），依赖它的排版 / 表格样式必须等第一段编辑块结束后再跑。
        """
        edit = QTextCursor(document)
        edit.beginEditBlock()
        try:
            processed, maths = extract_math(source, self._math_mark)
            processed = self._preprocess(processed)
            document.setMarkdown(processed)
            self._insert_fenced_code(document)
            self._apply_inline_code_formats(document)
            self._replace_mark_tokens(document)
            self._replace_footnote_refs(document)
            self._apply_footnote_defs(document)
            self._apply_heading_anchors(document)
            self._replace_toc_token(document)
            self._apply_folds(document)
            self._style_callouts(document)
        finally:
            edit.endEditBlock()
        # 第二段：排版 / 表格（读帧树）+ 其余纯模型阶段
        edit = QTextCursor(document)
        edit.beginEditBlock()
        try:
            self._style_typography(document)
            self._style_tables(document)
            self._apply_fragment_colors(document)
            self._style_task_markers(document)
            if maths:
                self._embed_math(document, maths, resource_doc or document)
            # 无图片语法时整趟跳过：``_apply_images`` 走全部块 × 片段的
            # Python 遍历（分块渲染里每块一次、实测 524KB 文档 ≈ 0.5s），
            # 而图片只可能来自 Markdown 图片语法 / ``<img>``。
            # （Mermaid / 公式图片由各自阶段插入，不经这里。）
            if _IMAGE_SYNTAX_RE.search(processed):
                self._apply_images(document, resource_doc)
            self._embed_mermaid(
                document,
                resource_doc,
                reset=document is self._text_browser.document(),
            )
        finally:
            edit.endEditBlock()

    @staticmethod
    def _collect_footnote_defs(lines: list[str]) -> tuple[list, set]:
        """收集围栏之外的脚注定义行，返回 ``[(id, text)]`` 与定义行号集合。"""
        defs: list[tuple[str, str]] = []
        indices: set[int] = set()
        seen: set[str] = set()
        fence: Optional[str] = None
        for index, line in enumerate(lines):
            if fence is not None:
                if _fence_close(line, fence):
                    fence = None
                continue
            opened, _lang = _fence_open(line)
            if opened:
                fence = opened
                continue
            match = _FOOTNOTE_DEF_RE.match(line)
            if match and match.group(1) not in seen:
                seen.add(match.group(1))
                indices.add(index)
                defs.append((match.group(1), match.group(2).strip()))
        return defs, indices

    def _extract_folds(self, lines: list[str]) -> tuple[list[str], list[dict]]:
        """扫描可折叠块（推理标签 / ``<details>``）并替换为占位符行。

        - 围栏代码块内的标签不处理；
        - 未闭合的块标记 ``pending``（流式期间标签显示"思考中…"）；
        - 内容行原样保留（渲染后按展开状态隐藏或展示）。

        返回 ``(改写后的行, [(kind, label, pending)])``。
        """
        result: list[str] = []
        folds: list[dict] = []
        tag = (self._reasoning_tag or "").strip()
        open_re = (
            re.compile(rf"^<{re.escape(tag)}>\s*$", re.IGNORECASE) if tag else None
        )
        close_re = (
            re.compile(rf"^</{re.escape(tag)}>\s*$", re.IGNORECASE) if tag else None
        )
        fence: Optional[str] = None
        index = 0
        i = 0
        total = len(lines)
        index_map: list[int] = []

        def append(text: str, raw_index: int) -> None:
            result.append(text)
            index_map.append(raw_index)

        def append_fold(
            start: int, end: int, meta: dict, closed: bool, anchor: int
        ) -> None:
            nonlocal index
            if result and result[-1].strip():
                append("", anchor)
            append(f"{_FOLD_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", anchor)
            append("", anchor)
            for raw in range(start, end):
                append(lines[raw], raw)
            if closed:
                append("", anchor)
                append(f"{_FOLD_END_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", anchor)
                append("", anchor)
            folds.append(meta)
            index += 1

        while i < total:
            stripped = lines[i].strip()
            if fence is not None:
                if _fence_close(lines[i], fence):
                    fence = None
                append(lines[i], i)
                i += 1
                continue
            opened, _lang = _fence_open(lines[i])
            if opened:
                fence = opened
                append(lines[i], i)
                i += 1
                continue
            if open_re is not None and open_re.match(stripped):
                j = i + 1
                while j < total and not close_re.match(lines[j].strip()):
                    j += 1
                closed = j < total
                append_fold(
                    i + 1,
                    j,
                    {
                        "kind": "reasoning",
                        "label": self._reasoning_label if closed else "思考中…",
                        "pending": not closed,
                    },
                    closed,
                    i,
                )
                i = j + 1 if closed else total
                continue
            if _DETAILS_OPEN_RE.match(stripped):
                depth = 1
                label = "详情"
                content_start = i + 1
                if content_start < total:
                    summary = _SUMMARY_RE.match(lines[content_start].strip())
                    if summary:
                        label = summary.group(1).strip() or label
                        content_start += 1
                k = content_start
                while k < total and depth > 0:
                    inner = lines[k].strip()
                    if _DETAILS_OPEN_RE.match(inner):
                        depth += 1
                    elif _DETAILS_CLOSE_RE.match(inner):
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                closed = depth == 0
                append_fold(
                    content_start,
                    k if closed else total,
                    {"kind": "details", "label": label, "pending": not closed},
                    closed,
                    i,
                )
                i = k + 1 if closed else total
                continue
            append(lines[i], i)
            i += 1
        return result, folds, index_map

    def _preprocess(self, text: str) -> str:
        """预处理 Markdown 源文。

        - 围栏代码块（含未闭合）替换为唯一占位符，解析后精确插入；
        - 任务列表 ``- [x]`` / ``- [ ]`` 替换为 ☑ / ☐；
        - 行内代码记录文本，解析后按顺序定位上色；
        - 行内下标 ``~x~``/上标 ``^x^`` 改写为 ``<sub>/<sup>``，
          ``==高亮==`` 记录后着色，``:emoji:`` 替换为 Unicode；
        - 脚注定义抽取到文末，引用替换为占位符；
        - Callout 标记行替换为占位符，解析后套用提示块样式；
        - 独立 ``[toc]`` 行替换为占位符，解析后生成目录；
        - 推理标签 / ``<details>`` 折叠块替换为占位符，解析后按状态折叠。
        """
        # front matter（`---` 头部）：Qt 6 的 Markdown 导入器原生剥离，无需预处理
        raw_lines = text.split("\n")
        lines, folds, index_map = self._extract_folds(raw_lines)
        fn_defs, fn_def_lines = self._collect_footnote_defs(raw_lines)
        defined = {fid for fid, _ in fn_defs}

        out: list[str] = []
        inline_codes: list[str] = []
        fenced_blocks: list[tuple[str, str]] = []
        fenced_source_lines: list[tuple[int, int]] = []
        mermaid_blocks: list[str] = []
        marks: list[str] = []
        callouts: list[str] = []
        tasks: list[tuple[int, bool]] = []
        fence: Optional[str] = None
        fence_lang = ""
        fence_start = 0
        buffer: list[str] = []

        def emit_closed_fence(
            lang: str, code: str, start_line: int, end_line: int
        ) -> None:
            """闭合围栏：mermaid 且启用渲染时产出 Mermaid 占位符，否则代码卡片。"""
            if lang == "mermaid" and code.strip() and self._mermaid_enabled():
                mermaid_blocks.append(code)
                out.append(
                    f"{_MERMAID_TOKEN_PREFIX}{len(mermaid_blocks) - 1}"
                    f"{_CODE_TOKEN_SUFFIX}"
                )
                return
            token = f"{_CODE_TOKEN_PREFIX}{len(fenced_blocks)}{_CODE_TOKEN_SUFFIX}"
            fenced_blocks.append((lang, code, True))
            fenced_source_lines.append((start_line, end_line))
            out.append(token)

        def transform(segment: str) -> str:
            if not segment:
                return segment

            # 空 alt 图片补一个空格，否则 Qt 导入器整张丢弃（见正则注释）
            segment = _EMPTY_ALT_IMAGE_RE.sub("![ ]", segment)

            def replace_ref(match):
                fid = match.group(1)
                if fid not in defined:
                    return match.group(0)
                return f"{_FOOTNOTE_REF_PREFIX}{fid}{_CODE_TOKEN_SUFFIX}"

            # 脚注引用先替换为占位符，避免 ``^`` 被上标规则误配
            segment = _FOOTNOTE_REF_RE.sub(replace_ref, segment)
            segment = _SUB_RE.sub(lambda m: f"<sub>{m.group(1)}</sub>", segment)
            segment = _SUP_RE.sub(lambda m: f"<sup>{m.group(1)}</sup>", segment)

            def replace_mark(match):
                content = match.group(1)
                if any(ch in content for ch in _MARK_SPECIAL_CHARS):
                    return match.group(0)
                marks.append(content)
                return f"{_MARK_TOKEN_PREFIX}{len(marks) - 1}{_CODE_TOKEN_SUFFIX}"

            segment = _MARK_RE.sub(replace_mark, segment)
            return _EMOJI_RE.sub(
                lambda m: _EMOJI_MAP.get(m.group(1).lower(), m.group(0)), segment
            )

        def transform_line(line: str) -> str:
            """行内语法转换（行内代码换成唯一占位符，文本另存）。"""
            pieces: list[str] = []
            last = 0
            for match in _INLINE_CODE_RE.finditer(line):
                pieces.append(transform(line[last : match.start()]))
                # **换成唯一占位符而不是把原文留在文档里**。原先渲染后靠
                # ``document.find(文本)`` 反推位置，只要同一串文本在更早处以
                # 非代码形式出现过，标记就整体错位：普通文本被染成代码（等宽
                # +圆角底），而真正的 `code` 一点样式都没有。实测
                # 「正文先提术语、再用反引号引用」这种 AI 输出最高频的形状
                # 必中。占位符含私有区字符，与用户文本零碰撞 —— 与
                # ``_replace_mark_tokens`` / 脚注 / callout 同一套路子。
                inline_codes.append(match.group(2))
                pieces.append(
                    f"{_INLINE_CODE_TOKEN_PREFIX}{len(inline_codes) - 1}"
                    f"{_CODE_TOKEN_SUFFIX}"
                )
                last = match.end()
            pieces.append(transform(line[last:]))
            return "".join(pieces)

        for line_no, line in enumerate(lines):
            raw_index = index_map[line_no]
            stripped = line.strip()
            if fence is not None:
                if _fence_close(line, fence):
                    emit_closed_fence(
                        fence_lang, "\n".join(buffer), fence_start, raw_index + 1
                    )
                    fence = None
                    fence_lang = ""
                    buffer = []
                else:
                    buffer.append(line)
                continue

            if raw_index in fn_def_lines:
                # 定义行抽取到文末；正文以空行占位避免段落粘连
                out.append("")
                continue

            opened, opened_lang = _fence_open(line)
            if opened:
                fence = opened
                fence_lang = opened_lang
                fence_start = raw_index
                continue

            callout = _CALLOUT_RE.match(stripped)
            if callout is not None:
                callouts.append(callout.group(1).lower())
                out.append(
                    f"> {_CALLOUT_TOKEN_PREFIX}{len(callouts) - 1}{_CODE_TOKEN_SUFFIX}"
                )
                continue

            if _TOC_LINE_RE.match(stripped):
                out.append(_TOC_TOKEN)
                continue

            def replace_task(match, line_index=raw_index):
                checked = match.group(2).lower() == "x"
                tasks.append((line_index, checked))
                marker = "☑" if checked else "☐"
                return f"{match.group(1)}[{marker}](#elatask-{len(tasks) - 1})"

            line = _TASK_LIST_RE.sub(replace_task, line)
            out.append(transform_line(line))

        if fence is not None:
            # 未闭合围栏：同样按代码块渲染（GitHub 语义），流式期间体验更好
            token = f"{_CODE_TOKEN_PREFIX}{len(fenced_blocks)}{_CODE_TOKEN_SUFFIX}"
            fenced_blocks.append((fence_lang, "\n".join(buffer), False))
            fenced_source_lines.append((fence_start, len(lines)))
            out.append(token)

        if fn_defs:
            out.append("")
            out.append("---")
            out.append("")
            for index, (fid, body) in enumerate(fn_defs, start=1):
                out.append(
                    f"{_FOOTNOTE_DEF_PREFIX}{index}{_CODE_TOKEN_SUFFIX} [{index}] {body}"
                )
                out.append("")

        self._inline_codes = inline_codes
        self._fenced_blocks = fenced_blocks
        self._fenced_source_lines = fenced_source_lines
        self._mark_texts = marks
        self._footnote_defs = fn_defs
        self._callout_types = callouts
        self._task_items = tasks
        self._mermaid_blocks = mermaid_blocks
        self._fold_blocks = folds
        return "\n".join(out)

    # -- 代码块 ------------------------------------------------------------

    def _code_format(self) -> QTextCharFormat:
        """行内代码格式（等宽 + 标记属性；底色/圆角由自绘提供）。"""
        fmt = QTextCharFormat()
        fmt.setFontFamilies(
            [self._code_font_family, "Microsoft YaHei UI", "Microsoft YaHei"]
        )
        fmt.setFontFixedPitch(True)
        point_size = self._math_point_size()
        if point_size > 0:
            fmt.setFontPointSize(point_size * 0.92)
        fmt.setProperty(_INLINE_CODE_MARK, True)
        fmt.setForeground(self._md_code_color)
        return fmt

    def _code_text_format(self) -> QTextCharFormat:
        """围栏代码文本格式（0.9em 等宽，Typora 风格；底色由单元格提供）。"""
        fmt = QTextCharFormat()
        fmt.setFontFamilies(
            [self._code_font_family, "Microsoft YaHei UI", "Microsoft YaHei"]
        )
        fmt.setFontFixedPitch(True)
        fmt.setForeground(self._code_text)
        base_font = self.document().defaultFont()
        point_size = base_font.pointSizeF()
        if point_size > 0:
            fmt.setFontPointSize(point_size * 0.9)
        return fmt

    def _code_table_format(
        self,
        lang: str,
        code: str,
        source_lines: Optional[tuple] = None,
    ) -> QTextTableFormat:
        """代码块包裹表格式：整行宽度、无边框（Typora 风格纯底色卡片）。"""
        fmt = QTextTableFormat()
        fmt.setBorder(0)
        fmt.setBorderCollapse(True)
        fmt.setCellPadding(0)
        fmt.setCellSpacing(0)
        fmt.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
        fmt.setTopMargin(8)
        fmt.setBottomMargin(8)
        fmt.setAlignment(Qt.AlignmentFlag.AlignLeft)
        fmt.setProperty(_CODE_MARKER, _CODE_MARKER_VALUE)
        fmt.setProperty(_CODE_TEXT_PROPERTY, code)
        fmt.setProperty(_CODE_LANG_PROPERTY, lang)
        if source_lines is not None:
            fmt.setProperty(
                _CODE_SOURCE_PROPERTY, f"{source_lines[0]},{source_lines[1]}"
            )
        return fmt

    def _code_cell_format(self) -> QTextTableCellFormat:
        """代码单元格格式：底色 + 内边距（Qt 富文本无块级 padding）。"""
        fmt = QTextTableCellFormat()
        fmt.setBackground(QBrush(self._code_bg))
        fmt.setBorder(0)
        fmt.setTopPadding(9)
        fmt.setBottomPadding(9)
        fmt.setLeftPadding(14)
        fmt.setRightPadding(14)
        return fmt

    def _insert_fenced_code(self, document: QTextDocument) -> None:
        """用真实代码内容替换占位符：表格包裹（可选语言标签行）+ 语法高亮。

        逐行字符底色会覆盖块 margin，导致多段围栏灰色连片、无内边距；
        改为表格：底色与 padding 由单元格提供，块间距由表格外边距提供。
        有语言时首行渲染语言标签；支持超长代码折叠与行号显示。
        """
        if not self._fenced_blocks:
            return
        # 多张代码卡合并成一次编辑块：每张卡内部的 endEditBlock 都会触发重排，
        # 一页几十个代码块时能省下可观的布局时间（嵌套编辑块 Qt 会一并合并）
        outer = QTextCursor(document)
        outer.beginEditBlock()
        try:
            entries = []
            for index, (lang, code_text, closed) in enumerate(self._fenced_blocks):
                token = f"{_CODE_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}"
                source_lines = (
                    self._fenced_source_lines[index]
                    if index < len(self._fenced_source_lines)
                    else None
                )
                entries.append((token, (index, lang, code_text, closed, source_lines)))

            def replace(found: QTextCursor, data) -> None:
                index, lang, code_text, closed, source_lines = data
                self._insert_code_card(
                    found,
                    lang,
                    code_text,
                    closed=closed,
                    fold_index=index,
                    source_lines=source_lines,
                )

            self._replace_tokens_in_order(document, entries, replace)
        finally:
            outer.endEditBlock()

    def _insert_code_card(
        self,
        cursor: QTextCursor,
        lang: str,
        code_text: str,
        closed: bool = True,
        fold_index: Optional[int] = None,
        source_lines: Optional[tuple] = None,
    ) -> None:
        """把当前选中的占位符替换为代码卡片（Typora 风格：无头栏、单行）。

        语言标签不再占一行，改为存入表格式供复制按钮 tooltip 展示。

        不自己开关编辑块：调用方（``_insert_fenced_code`` / ``_embed_mermaid``）
        已在批处理编辑块内，逐卡 begin/end 纯属开销（实测 200 卡 ≈ 0.04s）。
        """
        document = cursor.document()
        cursor.removeSelectedText()
        table = cursor.insertTable(
            1, 1, self._code_table_format(lang, code_text, source_lines)
        )
        code_cell = table.cellAt(0, 0)
        code_cell.setFormat(self._code_cell_format())
        cell_cursor = code_cell.firstCursorPosition()

        lines = code_text.split("\n")
        collapsed = (
            fold_index is not None
            and self._code_collapse_lines > 0
            and not self._stream_active
            and len(lines) > self._code_collapse_lines + 1
            and fold_index not in self._expanded_code_blocks
        )
        visible_code = (
            "\n".join(lines[: self._code_collapse_lines]) if collapsed else code_text
        )
        highlight_lang = lang
        if not closed and len(visible_code) > _STREAM_HIGHLIGHT_MAX_CHARS:
            # 未闭合围栏的中间态跳过高亮：内容每次刷新都在增长，
            # 全量词法分析且缓存中间态会显著拖慢流式渲染
            highlight_lang = ""
        self._insert_code_text(cell_cursor, visible_code, highlight_lang)
        if fold_index is not None:
            self._insert_code_fold_link(cell_cursor, fold_index, lines, collapsed)
        self._style_code_cell_blocks(document, code_cell)

    def _insert_code_text(
        self, cell_cursor: QTextCursor, code_text: str, lang: str
    ) -> None:
        """把代码写入单元格（可选行号；``diff`` 行级底色；逐行拆分保留高亮）。"""
        styles = self._highlight_code(code_text, lang)
        is_diff = lang.lower() == "diff"
        if not self._line_numbers_enabled and not is_diff:
            for text, fmt in styles:
                if text:
                    cell_cursor.insertText(text, fmt)
            return
        lines = self._split_styled_lines(styles)
        width = len(str(len(lines)))
        number_format = self._line_number_format()
        for position, parts in enumerate(lines):
            if position:
                cell_cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
            line_bg = self._diff_line_background(parts) if is_diff else None
            if self._line_numbers_enabled:
                number_fmt = number_format
                if line_bg is not None:
                    number_fmt = QTextCharFormat(number_format)
                    number_fmt.setBackground(line_bg)
                cell_cursor.insertText(f"{position + 1:>{width}}  ", number_fmt)
            for text, fmt in parts:
                if not text:
                    continue
                if line_bg is not None:
                    fmt = QTextCharFormat(fmt)
                    fmt.setBackground(line_bg)
                cell_cursor.insertText(text, fmt)

    def _diff_line_background(self, parts: list) -> Optional[QBrush]:
        """``diff`` 代码行底色：``+`` 绿、``-`` 红、``@@`` 蓝（其余无）。"""
        text = "".join(part[0] for part in parts).lstrip()
        if text.startswith("@@"):
            return QBrush(self._diff_hunk_bg)
        if text.startswith("+") and not text.startswith("+++"):
            return QBrush(self._diff_add_bg)
        if text.startswith("-") and not text.startswith("---"):
            return QBrush(self._diff_del_bg)
        return None

    def _insert_code_fold_link(
        self, cell_cursor: QTextCursor, index: int, lines: list, collapsed: bool
    ) -> None:
        """折叠/展开链接行（仅在启用折叠且代码足够长时插入）。"""
        if self._code_collapse_lines <= 0 or self._stream_active:
            return
        if len(lines) <= self._code_collapse_lines + 1:
            return
        cell_cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
        fmt = QTextCharFormat(self._code_text_format())
        fmt.setAnchor(True)
        fmt.setAnchorHref(f"#elacode-expand-{index}")
        fmt.setForeground(self._link_color)
        if collapsed:
            remaining = len(lines) - self._code_collapse_lines
            cell_cursor.insertText(f"▸ 展开其余 {remaining} 行", fmt)
        else:
            cell_cursor.insertText("▾ 收起", fmt)

    @staticmethod
    def _split_styled_lines(styles: list) -> list:
        """高亮 token 序列按换行拆分为每行的 [(文本, 格式)]。"""
        lines: list[list] = [[]]
        for text, fmt in styles:
            parts = text.split("\n")
            for position, part in enumerate(parts):
                if position:
                    lines.append([])
                if part:
                    lines[-1].append((part, fmt))
        return lines

    def _line_number_format(self) -> QTextCharFormat:
        """行号字符格式：等宽、次级文字色。"""
        fmt = QTextCharFormat(self._code_text_format())
        fmt.setForeground(self._muted_color)
        return fmt

    @staticmethod
    def _style_code_cell_blocks(document: QTextDocument, cell) -> None:
        """代码单元格内块：行高 130%、上下 margin 0（间距由单元格 padding 提供）。"""
        first = cell.firstCursorPosition().blockNumber()
        last = cell.lastCursorPosition().blockNumber()
        block = document.findBlockByNumber(first)
        while block.isValid() and block.blockNumber() <= last:
            block_format = block.blockFormat()
            block_format.setLineHeight(
                130.0, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
            )
            block_format.setTopMargin(0)
            block_format.setBottomMargin(0)
            cursor = QTextCursor(document)
            cursor.setPosition(block.position())
            cursor.setBlockFormat(block_format)
            block = block.next()

    def _highlight_code(self, code: str, lang: str) -> list:
        """代码 → [(文本, 字符格式)]；未安装 Pygments / 无语言时整段底色。"""
        base = self._code_text_format()
        module = _load_pygments()
        if module is None or not lang or len(code) > _HIGHLIGHT_MAX_CHARS:
            return [(code, base)]
        get_lexer_by_name, token_module = module
        theme_key = "dark" if self._is_dark_theme else "light"
        cache_key = (lang, code, theme_key)
        cached = self._highlight_cache.get(cache_key)
        if cached is not None:
            return cached
        lexer = _LEXER_CACHE.get(lang, _LEXER_MISS)
        if lexer is _LEXER_MISS:
            try:
                lexer = get_lexer_by_name(lang, stripnl=False, ensurenl=False)
            except Exception:
                lexer = None
            _LEXER_CACHE[lang] = lexer
        if lexer is None:
            return [(code, base)]
        palette = self._token_palette
        result = []
        try:
            for token_type, value in lexer.get_tokens(code):
                if not value:
                    continue
                fmt = QTextCharFormat(base)
                style = _token_style(token_type, token_module, palette)
                if style is not None:
                    color, italic = style
                    fmt.setForeground(QColor(color))
                    if italic:
                        fmt.setFontItalic(True)
                result.append((value, fmt))
        except Exception:
            return [(code, base)]
        if not result:
            return [(code, base)]
        if self._highlight_cache_cap > 0:
            while len(self._highlight_cache) >= self._highlight_cache_cap:
                self._highlight_cache.pop(next(iter(self._highlight_cache)))
            self._highlight_cache[cache_key] = result
        return result

    def _in_code_table(self, cursor: QTextCursor) -> bool:
        """游标是否位于代码块包裹表内。"""
        frame = cursor.currentFrame()
        while frame is not None:
            if isinstance(frame, QTextTable) and self._is_code_table(frame):
                return True
            frame = frame.parentFrame()
        return False

    # -- 行内增强 / 脚注 / 锚点 / Callout -----------------------------------

    def _replace_mark_tokens(self, document: QTextDocument) -> None:
        """把 ``==高亮==`` 占位符替换为带主题背景色的文本。"""
        if not self._mark_texts:
            return
        fmt = QTextCharFormat()
        fmt.setBackground(QBrush(self._mark_bg))
        entries = [
            (f"{_MARK_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", content)
            for index, content in enumerate(self._mark_texts)
        ]

        def replace(found: QTextCursor, content: str) -> None:
            found.removeSelectedText()
            found.insertText(content, fmt)

        self._replace_tokens_in_order(document, entries, replace)

    def _replace_footnote_refs(self, document: QTextDocument) -> None:
        """把脚注引用占位符替换为上标编号链接（``[n](#fn-id)``）。

        每个脚注的首次引用处同时附加 ``fnref-id`` 锚点，供定义区编号回跳。
        同一脚注可被引用多次，所以每个 id 用自己的搜索游标循环（id 数量少，
        保序扫描的收益可忽略，这里只去掉逐次 begin/end 编辑块）。
        """
        if not self._footnote_defs:
            return
        anchored: set[str] = set()
        for index, (fid, _body) in enumerate(self._footnote_defs, start=1):
            token = f"{_FOOTNOTE_REF_PREFIX}{fid}{_CODE_TOKEN_SUFFIX}"
            search = QTextCursor(document)
            while True:
                found = document.find(token, search)
                if found.isNull():
                    break
                fmt = QTextCharFormat()
                fmt.setAnchor(True)
                fmt.setAnchorHref(f"#fn-{fid}")
                if fid not in anchored:
                    fmt.setAnchorNames([f"fnref-{fid}"])
                    anchored.add(fid)
                fmt.setVerticalAlignment(
                    QTextCharFormat.VerticalAlignment.AlignSuperScript
                )
                fmt.setForeground(self._link_color)
                found.removeSelectedText()
                found.insertText(f"[{index}]", fmt)
                search.setPosition(found.position())

    def _apply_footnote_defs(self, document: QTextDocument) -> None:
        """给文末脚注定义块设置锚点（``fn-id``）并着色编号。"""
        if not self._footnote_defs:
            return
        entries = [
            (f"{_FOOTNOTE_DEF_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", (index, fid))
            for index, (fid, _body) in enumerate(self._footnote_defs, start=1)
        ]

        def replace(found: QTextCursor, data) -> None:
            index, fid = data
            found.removeSelectedText()
            if found.block().text().startswith(" "):
                found.deleteChar()
            block = found.block()
            block_format = block.blockFormat()
            block_format.setTopMargin(2)
            block_format.setBottomMargin(2)
            found.setBlockFormat(block_format)

            number = document.find(f"[{index}]", block.position())
            if (
                not number.isNull()
                and number.block() == block
                and number.selectionEnd() <= block.position() + block.length()
            ):
                number_fmt = QTextCharFormat()
                number_fmt.setAnchor(True)
                number_fmt.setAnchorHref(f"#fnref-{fid}")
                number_fmt.setForeground(self._link_color)
                number.mergeCharFormat(number_fmt)

            anchor_fmt = QTextCharFormat()
            anchor_fmt.setAnchor(True)
            anchor_fmt.setAnchorNames([f"fn-{fid}"])
            cursor = QTextCursor(document)
            cursor.setPosition(block.position())
            cursor.setPosition(
                _clamp_pos(document, block.position() + max(block.length() - 1, 0)),
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.mergeCharFormat(anchor_fmt)

        self._replace_tokens_in_order(document, entries, replace)

    @staticmethod
    def _slugify(text: str, used: dict) -> str:
        """标题文本 → GitHub 风格锚点（保留 CJK，去标点，重名追加序号）。"""
        slug = re.sub(r"elamath[0-9a-f]+z\d+q", "", text).strip().lower()
        slug = re.sub(r"[^\w\u4e00-\u9fff -]+", "", slug)
        slug = re.sub(r"[\s-]+", "-", slug).strip("-")
        if not slug:
            slug = "section"
        base = slug
        index = 1
        while slug in used:
            slug = f"{base}-{index}"
            index += 1
        used[slug] = True
        return slug

    def _apply_heading_anchors(self, document: QTextDocument) -> None:
        """给标题块附加锚点名称，并记录标题列表（供目录生成）。"""
        self._headings = []
        used: dict = {}
        block = document.begin()
        while block.isValid():
            level = block.blockFormat().headingLevel()
            if level > 0:
                text = re.sub(r"elamath[0-9a-f]+z\d+q", "", block.text()).strip()
                slug = self._slugify(text, used)
                fmt = QTextCharFormat()
                fmt.setAnchor(True)
                fmt.setAnchorNames([slug])
                cursor = QTextCursor(document)
                cursor.setPosition(block.position())
                cursor.setPosition(
                    _clamp_pos(document, block.position() + max(block.length() - 1, 0)),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                cursor.mergeCharFormat(fmt)
                self._headings.append((level, text, slug))
            block = block.next()

    def _replace_toc_token(self, document: QTextDocument) -> None:
        """把 ``[toc]`` 占位符替换为标题链接列表。"""
        found = document.find(_TOC_TOKEN)
        if found.isNull():
            return
        if not self._headings:
            found.removeSelectedText()
            return
        cursor = QTextCursor(found)
        cursor.removeSelectedText()
        for index, (level, text, slug) in enumerate(self._headings):
            if index > 0:
                cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
            indent = "  " * max(level - 1, 0)
            if indent:
                cursor.insertText(indent)
            cursor.insertText("• ")
            link_fmt = QTextCharFormat()
            link_fmt.setAnchor(True)
            link_fmt.setAnchorHref(f"#{slug}")
            link_fmt.setForeground(self._link_color)
            cursor.insertText(text or slug, link_fmt)

    def _apply_folds(self, document: QTextDocument) -> None:
        """把折叠占位符替换为可点击标签，并按展开状态隐藏/展示内容。"""
        if not self._fold_blocks:
            return
        start_search = QTextCursor(document)
        end_search = QTextCursor(document)
        for index, fold in enumerate(self._fold_blocks):
            start_token = f"{_FOLD_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}"
            end_token = f"{_FOLD_END_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}"
            found = document.find(start_token, start_search)
            if found.isNull():
                continue
            expanded = index in self._expanded_folds
            label = fold.get("label") or ""
            marker = "▾" if expanded else "▸"
            fmt = QTextCharFormat()
            fmt.setForeground(self._muted_color)
            fmt.setFontItalic(True)
            fmt.setAnchor(True)
            fmt.setAnchorHref(f"#elafold-{index}")
            found.removeSelectedText()
            found.insertText(f"{marker} {label}", fmt)
            start_search.setPosition(found.position())
            label_block = document.findBlock(max(found.position() - 1, 0))
            if not label_block.isValid():
                continue
            end_found = document.find(end_token, end_search)
            if not end_found.isNull():
                end_search.setPosition(end_found.position())
            end_number = (
                end_found.block().blockNumber()
                if not end_found.isNull()
                else document.blockCount() - 1
            )
            if expanded:
                block = label_block.next()
                while block.isValid() and block.blockNumber() < end_number:
                    self._style_fold_block(document, block)
                    block = block.next()
                if not end_found.isNull():
                    self._delete_blocks(document, end_number, end_number)
            else:
                self._delete_blocks(document, label_block.blockNumber() + 1, end_number)

    @staticmethod
    def _delete_blocks(document: QTextDocument, first: int, last: int) -> None:
        """按块号区间删除块（从后往前，避免块号失效）。"""
        for number in range(last, first - 1, -1):
            block = document.findBlockByNumber(number)
            if not block.isValid():
                continue
            cursor = QTextCursor(document)
            cursor.setPosition(block.position())
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()

    def _style_fold_block(self, document: QTextDocument, block) -> None:
        """展开的折叠内容：左缩进 + 次级文字色。"""
        block_format = block.blockFormat()
        block_format.setLeftMargin(block_format.leftMargin() + 12)
        cursor = QTextCursor(document)
        cursor.setPosition(block.position())
        cursor.setBlockFormat(block_format)
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and (
                fragment.charFormat().foreground().style() == Qt.BrushStyle.NoBrush
            ):
                edit = QTextCursor(document)
                edit.setPosition(fragment.position())
                edit.setPosition(
                    _clamp_pos(document, fragment.position() + fragment.length()),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                fmt = QTextCharFormat()
                fmt.setForeground(self._muted_color)
                edit.mergeCharFormat(fmt)
            iterator += 1

    def _style_callouts(self, document: QTextDocument) -> None:
        """Callout：标记行替换为彩色标签，整段引用块加语义色淡底。"""
        if not self._callout_types:
            return
        tint = 0.14 if self._is_dark_theme else 0.08
        entries = [
            (f"{_CALLOUT_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", kind)
            for index, kind in enumerate(self._callout_types)
        ]

        def replace(found: QTextCursor, kind: str) -> None:
            label = _CALLOUT_LABELS.get(kind, kind)
            color = QColor(
                _CALLOUT_COLORS.get(kind, _CALLOUT_COLORS["note"])[
                    "dark" if self._is_dark_theme else "light"
                ]
            )
            background = QBrush(self._blend(self._base_bg, color, tint))
            label_fmt = QTextCharFormat()
            label_fmt.setFontWeight(QFont.Weight.DemiBold)
            label_fmt.setForeground(color)

            found.removeSelectedText()
            first_number = found.blockNumber()
            on_empty_line = found.atBlockEnd()
            found.insertText(label, label_fmt)
            if not on_empty_line:
                found.insertBlock(QTextBlockFormat(), QTextCharFormat())

            block = document.findBlockByNumber(first_number)
            while block.isValid():
                block_format = block.blockFormat()
                if block_format.leftMargin() < _QUOTE_LEFT_MARGIN:
                    break
                block_format.setBackground(background)
                # 语义色左竖线（GitHub / Typora 风格），由自绘统一绘制
                block_format.setProperty(_CALLOUT_RAIL_PROPERTY, color.name())
                cursor = QTextCursor(document)
                cursor.setPosition(block.position())
                cursor.setBlockFormat(block_format)
                block = block.next()

        self._replace_tokens_in_order(document, entries, replace)

    def _apply_inline_code_formats(self, document: QTextDocument) -> None:
        """把行内代码占位符换回真实文本，并套用格式（等宽 + 高亮底 + 内边距）。

        按**占位符**定位而不是按文本 —— 占位符含私有区字符且全文唯一，
        与用户文本零碰撞，所以「第 N 个行内代码」永远就是「第 N 个占位符」。

        原先是 ``document.find(行内代码文本)`` 顺序反推位置：只要同一串
        文本在更早处以非代码形式出现过，标记就整体错位一位—— 普通文本被
        染成代码（等宽 + 圆角底），而真正的 `code` 一点样式都没有。实测
        「正文先提术语、再用反引号引用」这种 AI 输出最高频的形状必中。
        """
        if not self._inline_codes:
            return
        fmt = self._code_format()
        entries = [
            (f"{_INLINE_CODE_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}", code_text)
            for index, code_text in enumerate(self._inline_codes)
        ]

        def replace(found: QTextCursor, code_text: str) -> None:
            found.removeSelectedText()
            found.insertText(code_text, fmt)

        self._replace_tokens_in_order(document, entries, replace)

    # -- 表格 / 排版 -------------------------------------------------------

    def _style_typography(self, document: QTextDocument) -> None:
        """Typora 风格排版：正文行高、标题层级字号与间距、引用块与列表间距。

        在 ``_style_callouts`` 之后调用：Callout 已带底色，引用块样式不再覆盖；
        表格单元格仅统一行高（代码卡片保持自身行高）。
        """
        base = document.defaultFont().pointSizeF()
        if base <= 0:
            pixel = document.defaultFont().pixelSize()
            base = pixel * 0.75 if pixel > 0 else 10.0
        cursor = QTextCursor(document)
        probe = QTextCursor(document)
        # 整个排版阶段合并成一次编辑块：逐块 setBlockFormat 会各自触发一次重排，
        # 几百个块的文档会明显卡顿（实测 760 块 ≈ 108ms）；合并后只在末尾重排一次
        cursor.beginEditBlock()
        try:
            block = document.begin()
            while block.isValid():
                probe.setPosition(block.position())
                table = probe.currentTable()
                if table is not None:
                    if self._in_code_table(probe):
                        block = block.next()
                        continue
                    table_format = block.blockFormat()
                    table_format.setLineHeight(
                        150.0, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
                    )
                    # 单元格内统一无块边距（间距由单元格 padding 提供），
                    # 避免导入器给首格加的默认段落边距造成表头基线不齐
                    table_format.setTopMargin(0)
                    table_format.setBottomMargin(0)
                    self._apply_block_format(document, block, table_format, cursor)
                    block = block.next()
                    continue
                block_format = block.blockFormat()
                level = block_format.headingLevel()
                if level:
                    scale, top, bottom, line_height = _HEADING_TYPOGRAPHY.get(
                        level, (1.0, 16.0, 16.0, 150.0)
                    )
                    block_format.setTopMargin(top)
                    block_format.setBottomMargin(bottom)
                    block_format.setLineHeight(
                        line_height, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
                    )
                    self._apply_block_format(document, block, block_format, cursor)
                    self._style_heading_fragments(
                        document, block, base * scale, level, cursor
                    )
                elif block_format.hasProperty(
                    QTextFormat.Property.BlockTrailingHorizontalRulerWidth
                ):
                    # hr：Qt 自带横线仅 1px 且颜色不可控（实测属性/调色板均无效），
                    # 清除属性后由 _paint_document_decorations 自绘 2px 主题线
                    block_format.clearProperty(
                        QTextFormat.Property.BlockTrailingHorizontalRulerWidth
                    )
                    block_format.setProperty(_HR_MARK, True)
                    block_format.setTopMargin(16.0)
                    block_format.setBottomMargin(16.0)
                    self._apply_block_format(document, block, block_format, cursor)
                else:
                    block_format.setLineHeight(
                        _BODY_LINE_HEIGHT,
                        QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
                    )
                    if block.textList() is not None:
                        block_format.setTopMargin(_LIST_ITEM_MARGIN)
                        block_format.setBottomMargin(_LIST_ITEM_MARGIN)
                    elif block_format.leftMargin() >= _QUOTE_LEFT_MARGIN:
                        block_format.setLeftMargin(_QUOTE_LEFT_MARGIN)
                        block_format.setTopMargin(_QUOTE_BLOCK_MARGIN)
                        block_format.setBottomMargin(_QUOTE_BLOCK_MARGIN)
                        self._mute_quote_fragments(document, block, cursor)
                    elif block.text().strip():
                        block_format.setBottomMargin(_PARAGRAPH_MARGIN)
                    self._apply_block_format(document, block, block_format, cursor)
                block = block.next()
        finally:
            cursor.endEditBlock()

    @staticmethod
    def _apply_block_format(
        document: QTextDocument,
        block,
        block_format: QTextBlockFormat,
        cursor: Optional[QTextCursor] = None,
    ) -> None:
        """把块格式写回指定块（``cursor`` 可复用以避免逐块创建）。"""
        cursor = cursor if cursor is not None else QTextCursor(document)
        cursor.setPosition(block.position())
        cursor.setBlockFormat(block_format)

    def _style_heading_fragments(
        self,
        document: QTextDocument,
        block,
        point_size: float,
        level: int,
        cursor: Optional[QTextCursor] = None,
    ) -> None:
        """标题片段：按层级放大字号、加粗，并强制为正文色（h6 次级色）。

        Qt Markdown 导入器可能给标题带上默认前景色（如深蓝），样式表无法
        覆盖；这里显式着色，保证深浅主题下标题颜色可控（Typora 风格）。
        """
        weight = QFont.Weight.Bold
        color = self._muted_color if level >= 6 else self._md_heading_color
        edit = cursor if cursor is not None else QTextCursor(document)
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.text():
                edit.setPosition(fragment.position())
                edit.setPosition(
                    _clamp_pos(document, fragment.position() + fragment.length()),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                fmt = QTextCharFormat()
                fmt.setFontPointSize(point_size)
                fmt.setFontWeight(weight)
                fmt.setForeground(color)
                edit.mergeCharFormat(fmt)
            iterator += 1

    def _mute_quote_fragments(
        self, document: QTextDocument, block, cursor: Optional[QTextCursor] = None
    ) -> None:
        """引用块正文：opencode TUI 风格（斜体 + 引用色；链接 / 行内代码保持自身颜色）。"""
        edit = cursor if cursor is not None else QTextCursor(document)
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and (
                fragment.charFormat().foreground().style() == Qt.BrushStyle.NoBrush
            ):
                edit.setPosition(fragment.position())
                edit.setPosition(
                    _clamp_pos(document, fragment.position() + fragment.length()),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                fmt = QTextCharFormat()
                fmt.setForeground(self._md_quote_color)
                fmt.setFontItalic(True)
                edit.mergeCharFormat(fmt)
            iterator += 1

    def _style_task_markers(self, document: QTextDocument) -> None:
        """任务复选框跟随主题 list 色（仍可点击，避免显示成整段链接色）。

        任务项整行是 anchor（点击切换勾选），文字会拿到链接色；勾选框单独
        取 list 色，既跟主题走，又与链接色区分得开。
        """
        if not self._task_items:
            return
        for marker in ("☑", "☐"):
            cursor = QTextCursor(document)
            while True:
                found = document.find(marker, cursor)
                if found.isNull():
                    break
                fmt = found.charFormat()
                if fmt.isAnchor() and fmt.anchorHref().startswith("#elatask-"):
                    plain = QTextCharFormat()
                    plain.setForeground(self._md_list_color)
                    found.mergeCharFormat(plain)
                cursor = found

    def _style_tables(self, document: QTextDocument) -> None:
        """美化 Markdown 表格。

        Qt 默认表格为左右贴边的全网格线且无内边距，这里改为：
        表头行主题底色 + 半粗体、单元格内边距、仅保留行分隔线。
        """
        header_brush = QBrush(self._table_header_bg)
        border_brush = QBrush(self._table_border)

        # 同段落排版：整轮表格样式合并成一次编辑块，避免每个单元格重排一次
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        try:
            stack = [document.rootFrame()]
            while stack:
                frame = stack.pop()
                for child in frame.childFrames():
                    stack.append(child)
                    if isinstance(child, QTextTable):
                        if self._is_code_table(child):
                            continue
                        self._trim_table_cell_blocks(document, child)
                        self._style_table(child, header_brush, border_brush)
                        self._set_table_margins(document, child)
        finally:
            cursor.endEditBlock()

    def _trim_table_cell_blocks(
        self, document: QTextDocument, table: QTextTable
    ) -> None:
        """移除单元格首尾的纯空块。

        Qt Markdown 导入器在引用块 / 代码块之后的表格首格会多插一个空块
        （渲染时把表头首格文字挤到第二行），这里用段落合并清理
        （单元格内 ``removeSelectedText`` 删除块无效，改用 ``deletePreviousChar``）。
        """
        for row in range(table.rows()):
            for column in range(table.columns()):
                cell = table.cellAt(row, column)
                while True:
                    first = cell.firstCursorPosition().blockNumber()
                    last = cell.lastCursorPosition().blockNumber()
                    if last <= first:
                        break
                    block = document.findBlockByNumber(first)
                    if not block.isValid() or block.text().strip():
                        break
                    following = document.findBlockByNumber(first + 1)
                    if not following.isValid():
                        break
                    cursor = QTextCursor(document)
                    cursor.setPosition(following.position())
                    cursor.deletePreviousChar()
                while True:
                    first = cell.firstCursorPosition().blockNumber()
                    last = cell.lastCursorPosition().blockNumber()
                    if last <= first:
                        break
                    block = document.findBlockByNumber(last)
                    if not block.isValid() or block.text().strip():
                        break
                    cursor = QTextCursor(document)
                    cursor.setPosition(block.position())
                    cursor.deletePreviousChar()

    def _set_table_margins(self, document: QTextDocument, table: QTextTable) -> None:
        """给表格前后的块留出上下间距。

        注意 ``table.firstCursorPosition()`` 指向首个单元格内部，
        直接改它的块边距会把表头首格文字顶下来；应改表格外的相邻块。
        """
        before_pos = table.firstPosition() - 1
        if before_pos >= 0:
            before = document.findBlock(before_pos)
            if before.isValid() and before.position() < table.firstPosition():
                self._set_block_margins(document, before, bottom=_TABLE_BLOCK_MARGIN)
        after_pos = table.lastPosition() + 1
        if after_pos < document.characterCount():
            after = document.findBlock(after_pos)
            if after.isValid() and after.position() > table.lastPosition():
                self._set_block_margins(document, after, top=_TABLE_BLOCK_MARGIN)

    def _is_code_table(self, table: QTextTable) -> bool:
        """是否为代码块包裹表（表格式标记优先，单列同色兜底）。

        兜底仅限单列、最多两行的表：浅色主题下表格表头底色与代码底色
        恰好相同，多列普通表格不能按颜色判定。
        """
        if table.rows() < 1 or table.columns() < 1:
            return False
        if table.format().property(_CODE_MARKER) == _CODE_MARKER_VALUE:
            return True
        if table.columns() != 1 or table.rows() > 2:
            return False
        cell = table.cellAt(0, 0)
        if cell is None:
            # cellAt() 对被合并覆盖的单元格返回 None
            return False
        background = cell.format().background()
        return (
            background.style() != Qt.BrushStyle.NoBrush
            and background.color() == self._code_bg
        )

    @staticmethod
    def _set_block_margins(
        document: QTextDocument,
        block,
        top: Optional[float] = None,
        bottom: Optional[float] = None,
    ) -> None:
        """设置指定块的上下外边距（None 表示保持不变）。"""
        block_format = block.blockFormat()
        if top is not None:
            block_format.setTopMargin(top)
        if bottom is not None:
            block_format.setBottomMargin(bottom)
        cursor = QTextCursor(document)
        cursor.setPosition(block.position())
        cursor.setBlockFormat(block_format)

    @staticmethod
    def _blend(base: QColor, over: QColor, alpha: float) -> QColor:
        """将 over 按 alpha 比例混合到 base 上，返回不透明颜色。"""
        return QColor(
            int(base.red() * (1 - alpha) + over.red() * alpha),
            int(base.green() * (1 - alpha) + over.green() * alpha),
            int(base.blue() * (1 - alpha) + over.blue() * alpha),
        )

    def _style_table(
        self, table: QTextTable, header_brush: QBrush, border_brush: QBrush
    ) -> None:
        table_format = QTextTableFormat(table.format())
        table_format.setBorder(0)
        table_format.setBorderCollapse(True)
        table_format.setCellPadding(0)
        table_format.setCellSpacing(0)
        if (
            self._table_column_widths
            and len(self._table_column_widths) == table.columns()
        ):
            table_format.setColumnWidthConstraints(
                [
                    QTextLength(QTextLength.Type.PercentageLength, width)
                    for width in self._table_column_widths
                ]
            )
        table.setFormat(table_format)

        stripe_brush = QBrush(self._table_stripe_bg)
        for row in range(table.rows()):
            for column in range(table.columns()):
                cell = table.cellAt(row, column)
                cell_format = cell.format().toTableCellFormat()
                # Typora（github.css）：单元格 6px 13px 内边距 + 全网格 1px
                cell_format.setTopPadding(6)
                cell_format.setBottomPadding(6)
                cell_format.setLeftPadding(13)
                cell_format.setRightPadding(13)
                cell_format.setBorderBrush(border_brush)
                cell_format.setBorder(1.0)
                if row == 0:
                    cell_format.setBackground(header_brush)
                    cell_format.setFontWeight(QFont.Weight.Bold)
                    cell_format.setForeground(QBrush(self._md_heading_color))
                elif self._table_zebra and row % 2 == 0:
                    cell_format.setBackground(stripe_brush)
                cell.setFormat(cell_format)
                if row == 0:
                    self._color_table_header_text(cell)

    def _color_table_header_text(self, cell) -> None:
        """表头文字显式着标题色（片段级，避免被后置的正文着色覆盖）。"""
        start = cell.firstCursorPosition()
        end = cell.lastCursorPosition()
        if end.position() <= start.position():
            return
        start.setPosition(end.position(), QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setForeground(self._md_heading_color)
        start.mergeCharFormat(fmt)

    # -- 公式 --------------------------------------------------------------

    def _math_point_size(self) -> float:
        """公式字号（pt）：跟随文档默认字体。"""
        font = self.document().defaultFont()
        size = font.pointSizeF()
        if size > 0:
            return size
        pixel = font.pixelSize()
        return pixel * 0.75 if pixel > 0 else 10.0

    def _embed_math(self, document: QTextDocument, maths: list, resource_doc) -> None:
        """把公式占位标记替换为渲染图片（结构错误时保留源码文本）。

        行内公式按正文字号的 1.2 倍渲染并垂直居中（``AlignMiddle``），
        避免 Qt 内联图片"底部贴基线"造成的整体上浮；块级按 1.35 倍并居中。
        容错渲染（未知命令字面显示）的公式也会记入 ``renderIssues()``。
        """
        base_point_size = self._math_point_size()
        plain_format = QTextCharFormat()
        plain_format.setForeground(self._text_color)
        search = QTextCursor(document)
        for index, (latex, display) in enumerate(maths):
            marker = self._math_mark.format(index)
            found = document.find(marker, search)
            if found.isNull():
                continue
            search.setPosition(found.position())
            point_size = base_point_size * (1.55 if display else 1.3)
            report: dict = {}
            image = render_formula(
                latex, self._text_color, point_size, display, report=report
            )
            if image is None:
                self._record_issue("math", latex)
                text = latex if display else f"${latex}$"
                found.insertText(text, plain_format)
                if display:
                    block_format = found.blockFormat()
                    block_format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                    found.setBlockFormat(block_format)
                continue
            if report.get("degraded") and not report.get("repaired"):
                self._record_issue("math", latex)
            digest = hashlib.md5(
                f"{latex}|{self._text_color.name()}|{point_size:.2f}|{display}".encode(
                    "utf-8"
                )
            ).hexdigest()
            url = f"elamath://{digest}"
            resource_doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), image)
            image_format = QTextImageFormat()
            image_format.setName(url)
            image_format.setWidth(image.width() / 2.0)
            image_format.setHeight(image.height() / 2.0)
            image_format.setToolTip(f"LaTeX: {latex}")
            image_format.setVerticalAlignment(
                QTextCharFormat.VerticalAlignment.AlignMiddle
            )
            found.insertImage(image_format)
            if display:
                block_format = found.blockFormat()
                block_format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                block_format.setTopMargin(10)
                block_format.setBottomMargin(10)
                found.setBlockFormat(block_format)

    # -- Mermaid -----------------------------------------------------------

    def setMermaidRenderer(self, renderer=None) -> None:
        """设置 Mermaid 渲染器（``None`` 关闭，回退为代码卡片）。

        :param renderer: ``callable(code, theme) -> QImage | None``、
            :class:`~pyqt6_ela_pro.mermaid_support.ElaMermaidRenderer`
            或 ``None``（关闭）
        """
        if isinstance(renderer, ElaMermaidRenderer):
            if self._mermaid_renderer is not renderer:
                self._disconnect_mermaid_renderer()
                self._mermaid_renderer = renderer
                self._mermaidSlot = self._on_mermaid_rendered  # 断连要同一对象
                renderer.rendered.connect(self._mermaidSlot)
            self._mermaid_override = None
            self._mermaid_disabled = False
        elif renderer is None:
            self._disconnect_mermaid_renderer()
            self._mermaid_override = None
            self._mermaid_disabled = True
        else:
            self._disconnect_mermaid_renderer()
            self._mermaid_override = renderer
            self._mermaid_disabled = False
        if self._source:
            self._render()

    def setMermaidEnabled(self, on: bool) -> None:
        """启用/禁用 Mermaid 渲染（启用时自动探测 mermaidx）。"""
        on = bool(on)
        if on == (not self._mermaid_disabled):
            return
        self._disconnect_mermaid_renderer()
        self._mermaid_disabled = not on
        if on:
            self._mermaid_override = None
        if self._source:
            self._render()

    def mermaidAvailable(self) -> bool:
        """当前是否有可用的 Mermaid 渲染后端。"""
        return self._mermaid_enabled()

    def mermaidEnabled(self) -> bool:
        """是否启用 Mermaid 渲染（``setMermaidEnabled`` 的开关状态）。"""
        return not self._mermaid_disabled

    def setMermaidPrewarm(self, on: bool) -> None:
        """设置是否后台预热 Mermaid 引擎（默认关闭）。

        开启后立即创建渲染器并在后台启动 mermaid.js 引擎（约 0.4s），
        首次出图不再叠加冷启动耗时；仅在未设置自定义渲染函数时生效。
        """
        self._mermaid_prewarm = bool(on)
        if not self._mermaid_prewarm:
            return
        had_renderer = self._mermaid_renderer is not None
        renderer = self._ensure_mermaid_renderer()
        # 新建渲染器时 _ensure_mermaid_renderer 已触发预热，这里只补已有渲染器
        if renderer is not None and had_renderer:
            renderer.prewarm()

    def mermaidPrewarm(self) -> bool:
        """获取 Mermaid 引擎预热开关状态。"""
        return self._mermaid_prewarm

    def mermaidRenderer(self) -> Optional[ElaMermaidRenderer]:
        """获取（惰性创建的）Mermaid 渲染器。"""
        return self._ensure_mermaid_renderer()

    # -- 推理块折叠 --------------------------------------------------------

    def setReasoningTag(self, tag: Optional[str]) -> None:
        """推理块标签名（默认 ``"think"``，即 `` ... `` 语法）；``None`` 关闭折叠，
        标签内容按原文渲染。
        """
        self._reasoning_tag = tag
        if self._source:
            self._render()

    def reasoningTag(self) -> Optional[str]:
        """获取当前推理块标签名。"""
        return self._reasoning_tag

    def setReasoningLabel(self, label: str) -> None:
        """设置推理块折叠标签文案（默认"思考过程"）。"""
        self._reasoning_label = label or _DEFAULT_REASONING_LABEL
        if self._source:
            self._render()

    def reasoningLabel(self) -> str:
        """获取推理块折叠标签文案。"""
        return self._reasoning_label

    def _disconnect_mermaid_renderer(self) -> None:
        if self._mermaid_renderer is not None:
            try:
                self._mermaid_renderer.rendered.disconnect(self._mermaidSlot)
            except TypeError:
                pass
            self._mermaid_renderer = None
        # 旧渲染器的在途结果不再回调（信号已断开），计数一并复位
        self._mermaid_active = 0
        self._mermaid_jobs.clear()
        self._mermaid_job_keys.clear()

    def _mermaid_enabled(self) -> bool:
        if self._mermaid_disabled:
            return False
        if self._mermaid_override is not None:
            return True
        return mermaid_support.mermaidx_available()

    def _ensure_mermaid_renderer(self) -> Optional[ElaMermaidRenderer]:
        if self._mermaid_disabled:
            return None
        if self._mermaid_renderer is None:
            renderer = ElaMermaidRenderer(parent=self)
            if self._mermaid_override is not None:
                renderer.setRenderer(self._mermaid_override)
            if not renderer.available():
                return None
            self._mermaidSlot = self._on_mermaid_rendered  # 断连要同一对象
            renderer.rendered.connect(self._mermaidSlot)
            self._mermaid_renderer = renderer
            if self._mermaid_prewarm:
                renderer.prewarm()
        return self._mermaid_renderer

    def _theme_key(self) -> str:
        return "dark" if self._is_dark_theme else "light"

    def _embed_mermaid(
        self, document: QTextDocument, resource_doc, reset: bool = False
    ) -> None:
        """把 Mermaid 占位符替换为渲染图片（异步；失败/未装回退代码卡片）。

        未命中缓存的图进入待渲染队列（:attr:`_mermaid_jobs`），由
        :meth:`_pump_mermaid` 按**距视口距离**逐个提交（引擎串行，逐个提交
        不损失吞吐，但能保证当前可见的图最先出图）。

        :param reset: 全量渲染（主文档）时重置任务队列；流式片段渲染
            （临时文档）只追加，避免丢弃前面片段尚未完成的占位任务
        """
        if reset:
            self._mermaid_jobs.clear()
            self._mermaid_job_keys.clear()
        if not self._mermaid_blocks:
            return
        theme = self._theme_key()
        renderer = self._ensure_mermaid_renderer()
        resource_document = resource_doc or document
        for index, code in enumerate(self._mermaid_blocks):
            token = f"{_MERMAID_TOKEN_PREFIX}{index}{_CODE_TOKEN_SUFFIX}"
            found = document.find(token)
            if found.isNull():
                continue
            if renderer is None:
                self._insert_code_card(found, "mermaid", code)
                continue
            known, image = renderer.lookup(code, theme)
            if known:
                if image is None:
                    self._insert_code_card(found, "mermaid", code)
                else:
                    self._insert_mermaid_image(
                        found, code, image, resource_document, theme
                    )
                continue
            # 其它主题已有同源码图片时先顶上（避免主题切换时长期空白），
            # 挂上 pending 锚点，当前主题渲染完成后再替换。
            anchor = f"{_MERMAID_PENDING_PREFIX}{self._mermaid_digest(code)}-{index}"
            known_other, other_theme, other_image = renderer.lookupAnyTheme(code, theme)
            if known_other and other_image is not None:
                self._insert_mermaid_image(
                    found,
                    code,
                    other_image,
                    resource_document,
                    other_theme,
                    pending_anchor=anchor,
                )
            else:
                self._insert_mermaid_placeholder(found, index, code, anchor)
            key = (self._mermaid_digest(code), theme)
            if key in self._mermaid_job_keys:
                continue
            self._mermaid_job_keys.add(key)
            self._mermaid_jobs.append(
                {
                    "index": index,
                    "code": code,
                    "digest": key[0],
                    "anchor": anchor,
                    "theme": theme,
                    "distance": float("inf"),
                }
            )
        self._refresh_mermaid_priorities()
        self._schedule_mermaid_pump()

    def _mermaid_view_max_width(self) -> float:
        """当前视口可用的图片最大宽度（像素）。"""
        return max(self._text_browser.viewport().width() - _MERMAID_IMAGE_MARGIN, 120)

    def _mermaid_anchor_positions(self) -> dict:
        """一次遍历收集 ``mermaid-pending-`` 锚点的视口 y 坐标。"""
        positions: dict = {}
        if not self._mermaid_jobs:
            return positions
        browser = self._text_browser
        document = self.document()
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    for name in fragment.charFormat().anchorNames():
                        if name.startswith(_MERMAID_PENDING_PREFIX):
                            cursor = QTextCursor(document)
                            cursor.setPosition(fragment.position())
                            positions[name] = browser.cursorRect(cursor).center().y()
                iterator += 1
            block = block.next()
        return positions

    def _refresh_mermaid_priorities(self) -> None:
        """重算待渲染任务与视口中心的距离（滚动/文档变化后调用）。"""
        if is_deleted(self) or not self._mermaid_jobs:
            return
        center = max(1, self._text_browser.viewport().height()) / 2.0
        positions = self._mermaid_anchor_positions()
        for job in self._mermaid_jobs:
            y = positions.get(job.get("anchor"))
            job["distance"] = float("inf") if y is None else abs(y - center)

    def _schedule_mermaid_pump(self, delay: int = 0) -> None:
        """延后提交下一个任务（让贴底/滚动逻辑先更新视口位置）。"""
        if not self._mermaid_pump_timer.isActive():
            self._mermaid_pump_timer.start(delay)

    def _pump_mermaid(self) -> None:
        """提交下一个待渲染任务（引擎串行，同一时刻只保留一个在途请求）。"""
        if is_deleted(self):
            return
        if self._mermaid_disabled or not self._mermaid_jobs or self._mermaid_active:
            return
        renderer = self._ensure_mermaid_renderer()
        if renderer is None:
            return
        theme = self._theme_key()
        self._refresh_mermaid_priorities()
        renderer.setMaxImageWidth(self._mermaid_view_max_width())
        while self._mermaid_jobs:
            job = min(self._mermaid_jobs, key=lambda item: item["distance"])
            self._mermaid_jobs.remove(job)
            job_theme = job.get("theme", theme)
            if job_theme != theme:
                continue  # 旧主题任务：主题已切换，丢弃
            known, image = renderer.lookup(job["code"], theme)
            if known:
                self._replace_mermaid_pending(job["code"], theme, image)
                continue
            self._mermaid_active += 1
            renderer.request(job["code"], theme)
            return

    def _replace_mermaid_pending(self, code: str, theme: str, image) -> None:
        """把文档中该源码的 pending 锚点（占位文本/旧主题图）替换为最终结果。"""
        prefix = f"mermaid-pending-{self._mermaid_digest(code)}-"
        ranges = self._find_anchor_ranges(self.document(), prefix)
        if not ranges:
            return
        document = self.document()
        for start, end in reversed(ranges):
            cursor = QTextCursor(document)
            cursor.setPosition(_clamp_pos(document, start))
            cursor.setPosition(
                _clamp_pos(document, end), QTextCursor.MoveMode.KeepAnchor
            )
            if image is None:
                self._record_issue("mermaid", code)
                self._insert_code_card(cursor, "mermaid", code)
            else:
                self._insert_mermaid_image(cursor, code, image, document, theme)

    @staticmethod
    def _mermaid_digest(code: str) -> str:
        return hashlib.md5(code.encode("utf-8")).hexdigest()[:12]

    def _insert_mermaid_placeholder(
        self, cursor: QTextCursor, index: int, code: str, anchor: Optional[str] = None
    ) -> None:
        """渲染进行中占位（带唯一锚点名，供异步结果定位替换）。"""
        name = anchor or f"mermaid-pending-{self._mermaid_digest(code)}-{index}"
        fmt = QTextCharFormat()
        fmt.setForeground(self._muted_color)
        fmt.setFontItalic(True)
        fmt.setAnchorNames([name])
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        cursor.insertText("Mermaid 渲染中…", fmt)
        cursor.endEditBlock()

    def _insert_mermaid_image(
        self,
        cursor: QTextCursor,
        code: str,
        image: QImage,
        resource_doc: QTextDocument,
        theme: str,
        pending_anchor: Optional[str] = None,
    ) -> None:
        """把占位符替换为 Mermaid 渲染图片（居中、限宽、tooltip 存源码）。

        :param pending_anchor: 非空时给图片挂上 pending 锚点（旧主题降级图），
            当前主题渲染完成后可再次定位替换
        """
        digest = hashlib.md5(f"{code}|{theme}".encode("utf-8")).hexdigest()
        url = f"{_MERMAID_IMAGE_PREFIX}{digest}"
        resource_doc.addResource(
            QTextDocument.ResourceType.ImageResource, QUrl(url), image
        )
        width = image.width() / 2.0
        height = image.height() / 2.0
        max_width = self._mermaid_view_max_width()
        if width > max_width > 0:
            height = height * max_width / width
            width = max_width
        image_format = QTextImageFormat()
        image_format.setName(url)
        image_format.setWidth(width)
        image_format.setHeight(height)
        image_format.setToolTip(f"{_MERMAID_TIP_PREFIX}{code}")
        image_format.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignMiddle)
        if pending_anchor:
            image_format.setAnchorNames([pending_anchor])
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        cursor.insertImage(image_format)
        block_format = cursor.blockFormat()
        block_format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        block_format.setTopMargin(6)
        block_format.setBottomMargin(6)
        cursor.setBlockFormat(block_format)
        cursor.endEditBlock()

    def _find_anchor_ranges(self, document: QTextDocument, prefix: str) -> list:
        """扫描文档中锚点名以 ``prefix`` 开头的片段范围 ``[(start, end)]``。"""
        ranges: list = []
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    names = fragment.charFormat().anchorNames()
                    if any(name.startswith(prefix) for name in names):
                        ranges.append(
                            (
                                fragment.position(),
                                fragment.position() + fragment.length(),
                            )
                        )
                iterator += 1
            block = block.next()
        return ranges

    def _on_mermaid_rendered(self, code: str, theme: str, image) -> None:
        """渲染完成（GUI 线程）：替换对应占位符/降级图，并提交下一个任务。"""
        self._mermaid_active = max(0, self._mermaid_active - 1)
        if self._mermaid_disabled:
            return
        try:
            if theme == self._theme_key():
                self._replace_mermaid_pending(code, theme, image)
        finally:
            # 延后一拍：替换图片可能引起滚动/贴底，下一个任务按最新视口选择
            self._schedule_mermaid_pump()

    def _image_format_at_cursor(self) -> Optional[QTextImageFormat]:
        """光标处（含前一字符）的图片格式；没有则返回 ``None``。"""
        cursor = self._text_browser.textCursor()
        candidates = [cursor.charFormat()]
        probe = QTextCursor(cursor)
        if probe.movePosition(
            QTextCursor.MoveOperation.PreviousCharacter, QTextCursor.MoveMode.KeepAnchor
        ):
            candidates.append(probe.charFormat())
        for fmt in candidates:
            if fmt.isImageFormat():
                return fmt.toImageFormat()
        return None

    def _image_source_at_cursor(self, url_prefix: str, tip_prefix: str) -> str:
        """光标处图片的源码（``url_prefix`` / ``tip_prefix`` 匹配；否则空串）。"""
        image_format = self._image_format_at_cursor()
        if image_format is None:
            return ""
        if not image_format.name().startswith(url_prefix):
            return ""
        tooltip = image_format.toolTip()
        if tooltip.startswith(tip_prefix):
            return tooltip[len(tip_prefix) :]
        return ""

    def _mermaid_source_at_cursor(self) -> str:
        return self._image_source_at_cursor(_MERMAID_IMAGE_PREFIX, _MERMAID_TIP_PREFIX)

    def _copy_mermaid_at_cursor(self) -> None:
        code = self._mermaid_source_at_cursor()
        if not code:
            return
        QApplication.clipboard().setText(code)
        self.mermaidCopied.emit(code)

    def _load_image_resource(
        self, target_doc: QTextDocument, source: QUrl
    ) -> Optional[QImage]:
        """取资源里的图片；取不到 / 类型不对一律返回 ``None``（走占位符）。

        **返回类型必须是真``QImage``，不能把 ``loadResource`` 的原样返回交给
        调用方。** Qt 对 ``data:`` URL 返回**解码后的 ``QByteArray``** 而不是
        ``QImage``，而 ``QByteArray`` 恰好也有 ``isNull()`` —— 于是原先
        ``if image is None or image.isNull()`` 这道守卫放它过去，紧接着的
        ``image.width()`` 抛 ``AttributeError``。那条路有两条都致命：
        ``setMarkdown`` 直接调用时是宿主可见异常 + 文档半成品；流式路径下
        ``_stream_flush`` 的兜底 ``_render()`` 会**再抛一次并穿出 ``QTimer``
        槽** = ``0xC0000409`` 零 traceback 终止（实测退出码 -1073740791）。

        ``data:`` 不是边缘格式：:meth:`_image_data_uri` 导出/复制图片时
        **本库自己**就生成 ``data:image/png;base64,...``，所以往返必须成立，
        不能只当失败处理 —— 走 ``QImage.fromData`` 真正解码。
        """
        if source.scheme() == "data":
            image = QImage.fromData(_decode_data_uri(source))
            if not image.isNull():
                target_doc.addResource(
                    QTextDocument.ResourceType.ImageResource, source, image
                )
            return None if image.isNull() else image

        image = target_doc.resource(QTextDocument.ResourceType.ImageResource, source)
        if image is not None and not isinstance(image, QImage):
            converter = getattr(image, "toImage", None)
            if callable(converter):
                image = converter()
        if not isinstance(image, QImage):
            # QVariant / QByteArray / 任何非图片类型：视作取不到
            image = None
        if image is not None and not image.isNull():
            return image
        if source.isLocalFile():
            loaded = QImage(source.toLocalFile())
            if not loaded.isNull():
                target_doc.addResource(
                    QTextDocument.ResourceType.ImageResource, source, loaded
                )
                return loaded
        return None

    def _image_local_path_at_cursor(self) -> str:
        """光标处本地图片的磁盘路径（远程 / 生成图片返回空串）。"""
        image_format = self._image_format_at_cursor()
        if image_format is None:
            return ""
        url = self._resolve_image_url(image_format.name(), self.document().baseUrl())
        if not url.isLocalFile():
            return ""
        path = url.toLocalFile()
        return path if os.path.isfile(path) else ""

    def _save_image_at_cursor(self) -> None:
        """把光标处的本地图片另存为 PNG / JPEG。"""
        path = self._image_local_path_at_cursor()
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            return
        info = QFileInfo(path)
        suggested = os.path.join(info.absolutePath(), info.completeBaseName() + ".png")
        target, _ = QFileDialog.getSaveFileName(
            self,
            "图片另存为",
            suggested,
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg);;所有文件 (*)",
        )
        if not target:
            return
        image.save(target)

    # -- 主题 --------------------------------------------------------------

    def _applyThemeStyle(self) -> None:
        """应用主题色（样式表 + 调色板），并重新渲染已有内容。"""
        mode = self._theme_mode
        self._text_color = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicText)
        self._code_text = self._text_color
        # 表格 / 代码背景：与查看器背景预混合成不透明色
        # （QTextDocument 的 CSS 不支持 alpha 通道，且纯 BasicBaseDeep 在
        # 暗色主题下过亮，代码块与表格色块连片会显得"重"）
        background = eTheme.getThemeColor(mode, ElaThemeType.ThemeColor.BasicPress)
        self._is_dark_theme = background.lightness() < 128
        # 语义配色 / 语法高亮走 markdown 主题注册表（内置 opencode / github /
        # solarized / dracula，可注册自定义）；背景 / 正文 / 边框仍由 eTheme
        # 令牌提供，保证与 Ela 主题整体协调
        variant = _md_theme_spec(self._md_theme)[
            "dark" if self._is_dark_theme else "light"
        ]
        semantic = variant["semantic"]
        self._token_palette = dict(variant["syntax"])
        self._token_palette.update(self._token_overrides)
        self._link_color = QColor(semantic["link"])
        self._md_heading_color = QColor(semantic["heading"])
        self._md_strong_color = QColor(semantic["strong"])
        self._md_emphasis_color = QColor(semantic["emphasis"])
        self._md_code_color = QColor(semantic["code"])
        self._md_quote_color = QColor(semantic["quote"])
        self._md_list_color = QColor(semantic["list"])
        self._md_mark_color = QColor(semantic["mark"])
        code_alpha = 0.1 if self._is_dark_theme else 0.06
        self._code_bg = self._blend(background, self._text_color, code_alpha)
        self._code_border = self._blend(background, self._text_color, 0.18)
        self._table_header_bg = self._blend(
            background, self._text_color, 0.05 if self._is_dark_theme else 0.035
        )
        self._table_border = self._blend(background, self._text_color, 0.14)
        self._table_stripe_bg = self._blend(
            background, self._text_color, 0.06 if self._is_dark_theme else 0.035
        )
        self._base_bg = QColor(background)
        self._mark_bg = self._blend(
            background, self._md_mark_color, 0.26 if self._is_dark_theme else 0.34
        )
        self._muted_color = self._blend(background, self._text_color, 0.45)
        self._placeholder_color = self._blend(background, self._text_color, 0.38)
        # opencode TUI：引用竖线与 hr 都用正文色
        self._quote_rail_color = QColor(self._text_color)
        self._heading_rule_color = self._blend(
            background, self._text_color, 0.16 if self._is_dark_theme else 0.08
        )
        self._hr_color = QColor(self._text_color)
        self._search_bg = self._blend(
            background, QColor("#ff922b"), 0.4 if self._is_dark_theme else 0.5
        )
        self._inline_code_bg = self._blend(
            background, self._text_color, 0.12 if self._is_dark_theme else 0.07
        )
        self._inline_code_border = self._blend(
            background, self._text_color, 0.2 if self._is_dark_theme else 0.12
        )
        self._code_button_hover_bg = self._blend(background, self._text_color, 0.16)
        self._code_button_press_bg = self._blend(background, self._text_color, 0.24)
        self._diff_add_bg = self._blend(
            self._code_bg, QColor("#2da44e"), 0.16 if self._is_dark_theme else 0.12
        )
        self._diff_del_bg = self._blend(
            self._code_bg, QColor("#cf222e"), 0.14 if self._is_dark_theme else 0.1
        )
        self._diff_hunk_bg = self._blend(
            self._code_bg, QColor("#0969da"), 0.12 if self._is_dark_theme else 0.08
        )
        # 刻意**不清** ``_highlight_cache``：它的 key 是 (lang, code, theme_key)，
        # 本来就按主题分键；清掉等于把上一次主题的高亮结果扔掉（实测反复切换永远命中
        # 不了缓存）。改字号 / 换配色族走的是另一条会清缓存的路径（base 格式带字体）。

        document = self._text_browser.document()
        document.setDefaultStyleSheet(self._document_css())

        palette = self._text_browser.palette()
        palette.setColor(QPalette.ColorRole.Text, self._text_color)
        palette.setColor(QPalette.ColorRole.Link, self._link_color)
        self._text_browser.setPalette(palette)
        self._apply_viewport_base()

        if self._source:
            if self.isVisible():
                self._render()
            else:
                # 隐藏时不重建：整篇重解析 + 重高亮 + 重排版在宿主规模下是秒级
                # （实测 3×3800 行 + 10k 行终端全隐藏时切一次主题 2.3s → 53ms），
                # 等真正可见时由 showEvent 补齐 —— 文档文本不变，只有颜色是旧的。
                self._needs_render = True
        self.update()
        self._layout_timer.start(0)

    def _document_css(self) -> str:
        """文档默认样式：代码块与行内代码的字体/背景/文字色。"""
        return (
            f"pre, code, tt {{ font-family: '{self._code_font_family}';"
            f" background-color: {self._code_bg.name()};"
            f" color: {self._code_text.name()}; }}"
        )

    def _apply_fragment_colors(self, document: QTextDocument) -> None:
        """为正文 / 链接 / 加粗 / 斜体 / 删除线补上语义色（opencode TUI 风格）。

        Qt Markdown 导入器把链接硬编码为蓝色（内联样式），样式表无法覆盖，
        因此解析后统一改写字符格式；同时给未指定前景色的正文片段显式着色：

        - 链接 → 链接色 + 下划线（TUI 风格；URL 仍走 tooltip）
        - 删除线 → 次级色（保留删除线，比 TUI 的"仅变灰"在 GUI 更清晰）
        - 加粗 → strong 色；斜体 → emphasis 色
        - 其余正文（含列表项文字）→ 正文色

        **列表项不整块上色**：Qt 5.15 的 ``drawListItem`` 里，bullet（disc /
        circle / square）用的是 ``context.palette.Text``，字符格式根本染不上；
        只有数字 / 字母序号读 ``bl.charFormat()``。整块染色只会得到「文字变了
        色、符号反而还是原色」的反效果 —— 列表文字保持正文色、符号跟随控件
        前景色；``list`` 语义只留给任务勾选框（``☑ / ☐`` 是文本字形、能染色，
        见 :meth:`_style_task_markers`）。

        标题 / 行内代码等已有显式前景色的片段**不覆盖**（由各自阶段负责）。
        全部改写合并进一个编辑块，逐片段开销只有几个格式读取。
        """
        edit_cursor = QTextCursor(document)
        edit_cursor.beginEditBlock()

        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    fmt = fragment.charFormat()
                    color: Optional[QColor] = None
                    if fmt.isAnchor() and fmt.anchorHref():
                        color = self._link_color
                    elif fmt.foreground().style() == Qt.BrushStyle.NoBrush:
                        if fmt.fontStrikeOut():
                            color = self._muted_color
                        elif int(fmt.fontWeight()) >= int(QFont.Weight.DemiBold):
                            color = self._md_strong_color
                        elif fmt.fontItalic():
                            color = self._md_emphasis_color
                        else:
                            color = self._text_color
                    if color is not None:
                        edit_cursor.setPosition(fragment.position())
                        edit_cursor.setPosition(
                            _clamp_pos(
                                document, fragment.position() + fragment.length()
                            ),
                            QTextCursor.MoveMode.KeepAnchor,
                        )
                        char_format = QTextCharFormat()
                        char_format.setForeground(color)
                        if fmt.isAnchor():
                            # opencode TUI：链接带下划线
                            char_format.setFontUnderline(True)
                        href = fmt.anchorHref()
                        if (
                            fmt.isAnchor()
                            and href
                            and not fmt.toolTip()
                            and not href.startswith(_CONTROL_ANCHOR_PREFIXES)
                        ):
                            char_format.setToolTip(href)
                        edit_cursor.mergeCharFormat(char_format)
                iterator += 1
            block = block.next()

        edit_cursor.endEditBlock()

    # -- 图片 / 交互 / 布局 ------------------------------------------------

    def _apply_images(
        self, document: QTextDocument, resource_doc=None, start_block: int = 0
    ) -> None:
        """处理图片片段：本地加载注册、超宽缩放、远程按开关拦截。

        ``start_block`` 起（含）的块才参与处理 —— 宽度未变的增量重排只需扫
        新增块；宽度变化时调用方传 0 全量重扫。
        """
        base = document.baseUrl()
        target_doc = resource_doc or document
        max_width = max(self._text_browser.viewport().width() - 24, 120)
        placeholder_fmt = QTextCharFormat()
        placeholder_fmt.setForeground(self._muted_color)
        block = document.findBlockByNumber(start_block)
        if not block.isValid():
            return
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid():
                    fmt = fragment.charFormat()
                    if fmt.isImageFormat():
                        image_fmt = fmt.toImageFormat()
                        if not image_fmt.name().startswith("elamath://"):
                            self._apply_image_fragment(
                                document,
                                target_doc,
                                fragment,
                                image_fmt,
                                base,
                                max_width,
                                placeholder_fmt,
                            )
                iterator += 1
            block = block.next()
        self._center_standalone_images(document, start_block)

    def _center_standalone_images(
        self, document: QTextDocument, start_block: int = 0
    ) -> None:
        """独占一行的图片居中（Typora 风格；行内公式图片不参与）。"""
        block = document.findBlockByNumber(start_block)
        if not block.isValid():
            return
        while block.isValid():
            if block.text().strip() == "\ufffc":
                has_image = False
                has_math = False
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    if fragment.isValid() and fragment.charFormat().isImageFormat():
                        if (
                            fragment.charFormat()
                            .toImageFormat()
                            .name()
                            .startswith("elamath://")
                        ):
                            has_math = True
                        else:
                            has_image = True
                    iterator += 1
                if has_image and not has_math:
                    block_format = block.blockFormat()
                    block_format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                    self._apply_block_format(document, block, block_format)
            block = block.next()

    def _apply_image_fragment(
        self,
        document: QTextDocument,
        target_doc: QTextDocument,
        fragment,
        image_fmt: QTextImageFormat,
        base: QUrl,
        max_width: int,
        placeholder_fmt: QTextCharFormat,
    ) -> None:
        """单个图片片段：解析 URL、加载资源、必要时缩放或替换占位。"""
        source = self._resolve_image_url(image_fmt.name(), base)
        if source.scheme() in ("http", "https"):
            if not self._remote_images_enabled:
                self._replace_image_with_placeholder(
                    document, fragment, placeholder_fmt, source.toString()
                )
            return

        image = self._load_image_resource(target_doc, source)
        if image is None:
            self._replace_image_with_placeholder(
                document, fragment, placeholder_fmt, source.toString()
            )
            return

        width = image.width()
        height = image.height()
        if source.scheme() == "elamermaid":
            # Mermaid 按 2x 超采样渲染，显示尺寸减半
            width /= 2.0
            height /= 2.0
        if width > max_width > 0:
            height = height * max_width / float(width)
            width = max_width
        cursor = QTextCursor(document)
        cursor.setPosition(fragment.position())
        cursor.setPosition(
            _clamp_pos(document, fragment.position() + fragment.length()),
            QTextCursor.MoveMode.KeepAnchor,
        )
        scaled = QTextImageFormat()
        scaled.setName(source.toString())
        scaled.setWidth(width)
        scaled.setHeight(height)
        cursor.mergeCharFormat(scaled)

    @staticmethod
    def _resolve_image_url(name: str, base: QUrl) -> QUrl:
        """图片名 → 绝对 URL（兼容 Windows 盘符路径与相对路径）。"""
        if re.match(r"^[A-Za-z]:[\\/]", name):
            return QUrl.fromLocalFile(name)
        source = QUrl(name)
        if source.isRelative() and not base.isEmpty():
            source = base.resolved(source)
        return source

    def _replace_image_with_placeholder(
        self,
        document: QTextDocument,
        fragment,
        placeholder_fmt: QTextCharFormat,
        detail: str = "",
    ) -> None:
        """把无法加载的图片替换为灰字占位（记录到渲染问题）。"""
        if detail:
            self._record_issue("image", detail)
        cursor = QTextCursor(document)
        cursor.setPosition(fragment.position())
        cursor.setPosition(
            _clamp_pos(document, fragment.position() + fragment.length()),
            QTextCursor.MoveMode.KeepAnchor,
        )
        cursor.removeSelectedText()
        cursor.insertText("[图片]", placeholder_fmt)

    def _record_issue(self, kind: str, detail: str) -> None:
        """记录一次渲染降级（去重）。"""
        entry = (kind, detail)
        if entry not in self._render_issues:
            self._render_issues.append(entry)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt 命名)
        """拦截右键菜单，并在鼠标移动时管理代码复制按钮显隐。"""
        viewport = self._text_browser.viewport()
        event_type = event.type()
        if event_type == QEvent.Type.ContextMenu and obj in (
            self._text_browser,
            viewport,
        ):
            # 右键实际投递到 **viewport**（QAbstractScrollArea 的视口）—— 只拦
            # QTextBrowser 本体的话走的是 Qt 自带菜单（复制 / 复制链接 / 全选），
            # 自建菜单可达性为 0。坐标统一用 globalPos，免得再换算视口偏移。
            self._show_context_menu(event.globalPos())
            return True
        if obj is viewport:
            if event_type == QEvent.Type.MouseMove:
                pressed = bool(
                    event.buttons()
                    & (
                        Qt.MouseButton.LeftButton
                        | Qt.MouseButton.RightButton
                        | Qt.MouseButton.MiddleButton
                    )
                )
                self._update_code_button_hover(
                    event.position().toPoint(), pressed=pressed
                )
            elif event_type == QEvent.Type.Leave:
                # 移向复制按钮（viewport 子控件）也会触发 Leave：
                # 按光标实际位置判定，避免按钮在点击前消失
                self._on_viewport_leave()
        elif obj in self._code_button_widgets and event_type == QEvent.Type.Leave:
            single_shot_on(self, 0, self._hover_from_cursor)
        return super().eventFilter(obj, event)

    def _on_viewport_leave(self, global_pos=None) -> None:
        """viewport 离开处理：光标仍落在代码块矩形内（如按钮上）时保持显示。"""
        if global_pos is None:
            global_pos = QCursor.pos()
        pos = QPointF(self._text_browser.viewport().mapFromGlobal(global_pos))
        for rect in self._code_button_rects:
            if not rect.isNull() and rect.contains(pos):
                return
        self._hide_code_buttons()

    def _show_context_menu(self, global_pos) -> None:
        # 副屏上 ElaMenu 偶发不按 sizeHint 撑开（只显示第一项）—— execElaMenu 兜底
        execElaMenu(self._create_context_menu(), global_pos)

    def _create_context_menu(self) -> ElaMenu:
        """构建右键菜单（Ela 风格：图标 + 统一行高）。

        只保留只读视图真正可用的动作 —— Qt 标准菜单里的撤销 / 剪切 / 粘贴 /
        删除对本组件没有意义（`setReadOnly(True)`），所以不用
        ``createStandardContextMenu()``，改为自建（对齐 ``terminal_view.py`` 的
        右键菜单写法）。
        """
        browser = self._text_browser
        cursor = browser.textCursor()
        menu = ElaMenu(self)
        menu.setMenuItemHeight(_CONTEXT_MENU_ITEM_HEIGHT)

        copy = menu.addElaIconAction(ElaIconType.IconName.Copy, "复制")
        copy.setEnabled(cursor.hasSelection())
        copy.triggered.connect(browser.copy)
        select_all = menu.addElaIconAction(ElaIconType.IconName.BorderAll, "全选")
        select_all.triggered.connect(browser.selectAll)

        menu.addSeparator()
        copy_code = menu.addElaIconAction(ElaIconType.IconName.Code, "复制代码块")
        copy_code.setEnabled(self._in_code_table(cursor))
        copy_code.triggered.connect(self._copy_code_at_cursor)
        copy_formula = menu.addElaIconAction(
            ElaIconType.IconName.SquareRootVariable, "复制 LaTeX 公式"
        )
        copy_formula.setEnabled(bool(self._formula_latex_at_cursor()))
        copy_formula.triggered.connect(self._copy_formula_at_cursor)
        copy_mermaid = menu.addElaIconAction(
            ElaIconType.IconName.DiagramProject, "复制 Mermaid 源码"
        )
        copy_mermaid.setEnabled(bool(self._mermaid_source_at_cursor()))
        copy_mermaid.triggered.connect(self._copy_mermaid_at_cursor)
        save_image = menu.addElaIconAction(
            ElaIconType.IconName.FloppyDisk, "图片另存为…"
        )
        save_image.setEnabled(bool(self._image_local_path_at_cursor()))
        save_image.triggered.connect(self._save_image_at_cursor)

        menu.addSeparator()
        quote = menu.addElaIconAction(
            ElaIconType.IconName.FileCode, "复制选中为 Markdown"
        )
        quote.setEnabled(cursor.hasSelection())
        quote.triggered.connect(self._copy_selection_markdown)
        copy_all = menu.addElaIconAction(ElaIconType.IconName.ClipboardList, "复制全文")
        copy_all.triggered.connect(self._copy_all)
        return menu

    def _formula_latex_at_cursor(self) -> str:
        """光标处的公式 LaTeX 源码（非公式返回空字符串）。"""
        return self._image_source_at_cursor("elamath://", "LaTeX: ")

    def _copy_formula_at_cursor(self) -> None:
        latex = self._formula_latex_at_cursor()
        if not latex:
            return
        QApplication.clipboard().setText(latex)
        self.formulaCopied.emit(latex)

    @staticmethod
    def _code_table_text(table: QTextTable) -> str:
        """提取代码表内容（优先读取表格式上的原始代码，跳过语言标签行）。"""
        stored = table.format().property(_CODE_TEXT_PROPERTY)
        if isinstance(stored, str):
            return stored
        start = 1 if table.rows() > 1 else 0
        parts = []
        for row in range(start, table.rows()):
            cell = table.cellAt(row, 0)
            cursor = QTextCursor(cell.firstCursorPosition())
            cursor.setPosition(
                cell.lastCursorPosition().position(),
                QTextCursor.MoveMode.KeepAnchor,
            )
            parts.append(cursor.selection().toPlainText())
        return "\n".join(parts)

    def _copy_code_at_cursor(self) -> None:
        frame = self._text_browser.textCursor().currentFrame()
        while frame is not None:
            if isinstance(frame, QTextTable) and self._is_code_table(frame):
                self._copy_text(self._code_table_text(frame))
                return
            frame = frame.parentFrame()

    def _copy_all(self) -> None:
        self._copy_text(self.document().toPlainText())

    def _copy_selection_markdown(self) -> None:
        """复制选中内容为 Markdown 源（并发出 ``selectionQuoted``）。"""
        quote = self.markdownSelection()
        if not quote:
            return
        QApplication.clipboard().setText(quote)
        self.selectionQuoted.emit(quote)

    def _copy_text(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.codeCopied.emit(text)

    def _on_layout_refresh(self) -> None:
        """尺寸变化后重排：图片宽度与代码复制按钮位置。"""
        if is_deleted(self) or is_deleted(self._text_browser):
            return
        if self._source:
            # 宽度未变的常规重排只扫上次水位之后的新增块（流式追加时每次
            # 全文档遍历是纯浪费）；宽度变了才全量重新缩放
            width = self._text_browser.viewport().width()
            start = 0 if width != self._image_scan_width else self._image_scan_watermark
            self._apply_images(self.document(), start_block=start)
            self._mark_images_scanned()
        if self._large_render_chunks:
            # 分块渲染期间**不同步按钮**：每次布局刷新都是一趟全表树遍历 +
            # 全量定位，几千个代码块时是 O(n²)（实测 524KB / 4282 表 ≈ 1.9s）；
            # 按钮统一在 _finish_large_render 里建一次。
            self._sync_embedded_height()
            return
        self._sync_code_buttons()
        self._sync_embedded_height()

    def _on_view_scrolled(self, _value: int) -> None:
        # 滚动不改变文档结构：只需重摆按钮位置，不必重扫表格列表
        self._position_code_buttons()
        if self._mermaid_jobs and not self._mermaid_priority_timer.isActive():
            self._mermaid_priority_timer.start()

    def _on_document_size_changed(self, _size) -> None:
        self._schedule_layout_refresh()

    def _schedule_layout_refresh(self, delay: int = 80) -> None:
        """前缘去抖：定时器已激活时不重置，避免文档规模抖动造成无限推迟。"""
        if not self._layout_timer.isActive():
            self._layout_timer.start(delay)

    def _reset_image_scan(self) -> None:
        """文档被整体替换 / 清空：作废图片扫描水位（下次重排全量重扫）。"""
        self._image_scan_width = -1
        self._image_scan_watermark = 0

    def _mark_images_scanned(self) -> None:
        """记录「当前文档全部图片已按当前视口宽度处理过」。"""
        self._image_scan_width = self._text_browser.viewport().width()
        self._image_scan_watermark = self._text_browser.document().blockCount()

    def _sync_code_buttons(self) -> None:
        """同步代码复制按钮：按表对象身份做**增量**，只为新增代码块建按钮。

        原先列表一变就整体重建（流式每次 flush 销毁 + 重建几十个
        ``FlatIconButton``，实测 10 秒约 2.3 万个），是流式卡顿的最大单笔
        开销。稳定段里的代码表对象不会被替换，按钮可以直接复用。
        """
        try:
            tables = [
                table
                for table in self._iter_tables(self.document())
                if self._is_code_table(table)
            ]
        except RuntimeError:
            # 文档正在销毁（窗口关闭路径）：丢弃本轮同步
            return
        # 上一轮的表可能已随文档改动析构（尾段替换 / clear）：逐个判存活，
        # **失效表的按钮必须显式回收**（只从列表里摘掉的话控件仍留在视口里、
        # eventFilter 也还挂着 —— 换文档 / 换主题时按钮数会虚长）
        surviving: list = []
        for table, button in zip(self._code_buttons_tables, self._code_buttons):
            if is_deleted(table):
                self._drop_code_button(button)
            else:
                surviving.append((table, button))
        kept_tables = [table for table, _ in surviving]
        if len(kept_tables) <= len(tables) and all(
            a is b for a, b in zip(kept_tables, tables)
        ):
            # 存活表是新列表的前缀：复用按钮，只补尾部新增
            self._code_buttons_tables = tables
            self._code_buttons = [button for _, button in surviving]
            for index in range(len(kept_tables), len(tables)):
                self._code_buttons.append(self._create_code_button(index))
            self._position_code_buttons()
            return
        self._rebuild_code_buttons(tables)

    @staticmethod
    def _iter_tables(document: QTextDocument) -> list:
        """按文档顺序收集全部表格（含嵌套）。"""
        tables = []
        stack = [document.rootFrame()]
        while stack:
            frame = stack.pop()
            for child in frame.childFrames():
                if isinstance(child, QTextTable):
                    tables.append(child)
                stack.append(child)
        tables.sort(key=lambda t: t.firstPosition())
        return tables

    def _rebuild_code_buttons(self, tables: list) -> None:
        """重建全部代码复制按钮（文档重渲染后表对象会失效）。"""
        for button in self._code_buttons:
            self._drop_code_button(button)
        self._code_buttons = []
        self._code_button_rects = []
        self._shown_code_button = -1
        self._code_buttons_tables = list(tables)
        for index in range(len(tables)):
            self._code_buttons.append(self._create_code_button(index))
        self._position_code_buttons()

    def _create_code_button(self, index: int) -> QToolButton:
        """创建单个复制按钮（``index`` 为代码表序号）。"""
        viewport = self._text_browser.viewport()
        button = FlatIconButton(viewport)
        button.setObjectName("ElaMarkdownCopyButton")
        button.setFixedSize(_CODE_BUTTON_SIZE, _CODE_BUTTON_SIZE)
        button.setIconSize(QSize(14, 14))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoRaise(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lang = (
            self._code_buttons_tables[index].format().property(_CODE_LANG_PROPERTY)
            or ""
        )
        button.setToolTip(f"复制代码 · {lang}" if lang else "复制代码")
        button.clicked.connect(lambda _checked=False, i=index: self._copy_code_block(i))
        button.installEventFilter(self)
        button.hide()
        self._apply_code_button_style(button)
        self._code_button_widgets.add(button)
        return button

    def _drop_code_button(self, button: QToolButton) -> None:
        """移除单个复制按钮（隐藏 + 延迟销毁 + 退出归属集合）。"""
        button.hide()
        button.deleteLater()
        self._code_button_widgets.discard(button)

    def _apply_code_button_style(self, button: QToolButton) -> None:
        """按钮图标与悬浮 / 按下底色（随主题刷新；自绘，不用 QSS）。"""
        button.setIcon(self._code_copy_icon())
        button.setHoverColor(self._code_button_hover_bg)
        button.setPressColor(self._code_button_press_bg)
        button.setCornerRadius(6)

    def _code_copy_icon(self):
        return ElaIcon.getInstance().getElaIcon(
            ElaIconType.IconName.Copy, self._muted_color
        )

    def _code_check_icon(self):
        return ElaIcon.getInstance().getElaIcon(
            ElaIconType.IconName.Check, self._link_color
        )

    def _code_table_in_view(
        self, table, layout, offset: int, viewport_height: int
    ) -> bool:
        """代码表是否落在视口附近（文档坐标 vs 滚动偏移）。

        先用便宜的帧矩形做粗筛，只有可见的表才走昂贵的 ``cursorRect`` 几何；
        否则每一帧 / 每次滚动都要为全部代码块（含离屏）算一遍。
        """
        if is_deleted(table):
            return False
        frame = layout.frameBoundingRect(table)
        if frame.isNull():
            return False
        return (
            frame.bottom() >= offset - _CODE_VIEW_CULL_MARGIN
            and frame.top() <= offset + viewport_height + _CODE_VIEW_CULL_MARGIN
        )

    def _position_code_buttons(self) -> None:
        """把按钮摆到各代码块右上角（随滚动/尺寸变化；只算可见的表）。"""
        viewport_height = self._text_browser.viewport().height()
        offset = self._text_browser.verticalScrollBar().value()
        layout = self.document().documentLayout()
        self._code_button_rects = []
        for button, table in zip(self._code_buttons, self._code_buttons_tables):
            if not self._code_table_in_view(table, layout, offset, viewport_height):
                self._code_button_rects.append(QRectF())
                self._hide_code_button_widget(button)
                continue
            rect = self._code_table_viewport_rect(table)
            self._code_button_rects.append(rect)
            if rect.isNull() or rect.top() < 0 or rect.top() > viewport_height:
                self._hide_code_button_widget(button)
                continue
            x = int(rect.right() - button.width() - 6)
            y = self._code_button_y(table, rect, button)
            button.move(max(0, x), max(0, y))

    def _code_button_y(self, table: QTextTable, rect: QRectF, button) -> int:
        """复制按钮的纵向位置（无头栏，固定在代码卡右上角）。"""
        return int(rect.top() + 6)

    def _hide_code_button_widget(self, button) -> None:
        """隐藏单个按钮并同步「当前显示」标记（按钮可能因离屏被隐）。"""
        if button.isVisible():
            button.hide()
        if (
            0 <= self._shown_code_button < len(self._code_buttons)
            and self._code_buttons[self._shown_code_button] is button
        ):
            self._shown_code_button = -1

    def _code_table_viewport_rect(self, table: QTextTable) -> QRectF:
        """代码表在 viewport 坐标系中的矩形（用于按钮定位与悬浮判定）。

        Qt 的 ``frameBoundingRect`` 对表格返回的 x/y 会被首个单元格的
        内边距整体平移（宽度与高度可信），因此这里用首个单元格光标位置
        反推左上角；代码表宽度固定 100%，右边界取文档内容右缘。
        """
        if is_deleted(table) or table.rows() < 1 or table.columns() < 1:
            return QRectF()
        layout = self.document().documentLayout()
        frame_rect = layout.frameBoundingRect(table)
        if frame_rect.isNull():
            return QRectF()
        document = self.document()
        cell = table.cellAt(0, 0)
        cell_format = cell.format().toTableCellFormat()
        table_format = table.format()
        border = table_format.border()
        caret = self._text_browser.cursorRect(QTextCursor(cell.firstCursorPosition()))
        left = caret.left() - cell_format.leftPadding() - border
        top = caret.top() - cell_format.topPadding() - border
        right = self._text_browser.viewport().width() - 2 * document.documentMargin()

        # 底边：最后一行文本 + 单元格下内边距 + 边框 + 表格下外边距
        bottom = top + frame_rect.height()
        code_cell = table.cellAt(table.rows() - 1, 0)
        code_format = code_cell.format().toTableCellFormat()
        last_caret = self._text_browser.cursorRect(
            QTextCursor(code_cell.lastCursorPosition().block())
        )
        if last_caret.isValid():
            candidate = (
                last_caret.y()
                + last_caret.height()
                + code_format.bottomPadding()
                + border
                + table_format.bottomMargin()
            )
            bottom = max(top, candidate)
        return QRectF(left, top, max(right - left, 0.0), max(bottom - top, 0.0))

    # -- 自绘装饰（Typora 风格） -------------------------------------------

    def _visible_blocks(self, browser) -> tuple:
        """当前视口内可见的块范围 ``(first, last)``。"""
        document = self.document()
        viewport = browser.viewport()
        first = document.findBlock(browser.cursorForPosition(QPoint(0, 0)).position())
        last = document.findBlock(
            browser.cursorForPosition(
                QPoint(0, max(0, viewport.height() - 1))
            ).position()
        )
        if not first.isValid():
            first = document.begin()
        if not last.isValid():
            last = first
        return first, last

    def _paint_inline_code_backgrounds(self, browser, painter) -> None:
        """行内代码圆角底 + 边框（在文档绘制之前调用，避免盖住文字）。

        画笔（描边）+ 画刷（底色）在循环外设一次：全部标记共用同一对，
        密集行内代码时省掉每标记两次状态切换。
        """
        document = self.document()
        layout = document.documentLayout()
        offset = browser.verticalScrollBar().value()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._inline_code_border)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(self._inline_code_bg)
        first, last = self._visible_blocks(browser)
        block = first
        while block.isValid():
            rect = layout.blockBoundingRect(block)
            if rect.top() - offset > browser.viewport().height():
                break
            self._paint_block_inline_codes(browser, painter, block)
            if block.blockNumber() >= last.blockNumber():
                break
            block = block.next()

    def _paint_block_inline_codes(self, browser, painter, block) -> None:
        """绘制单个块内全部行内代码标记的圆角底与边框。

        坐标一律用 ``cursorRect``（**视觉行起点**的真实视口位置）反推行原点，
        ``cursorToX`` 只负责段内宽度——列表缩进 / 引用缩进 / 表格单元格
        局部坐标三种场景都成立（曾因 ``cursorRect + cursorToX`` 重复计入
        缩进而错位）。

        ``cursorRect`` 是本路径最贵的一步（~0.1ms/次）：**每个视觉行只取一次**
        （原先每个标记段一次 —— 行内代码密集时单帧几十次），画笔 / 画刷由
        调用方在循环外设好（全部标记共用同一对），每个标记只画一次圆角矩形。
        """
        text_layout = block.layout()
        if text_layout is None:
            return
        block_start = block.position()
        marks = []
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().property(_INLINE_CODE_MARK):
                marks.append((fragment.position() - block_start, fragment.length()))
            iterator += 1
        if not marks:
            return
        document = self.document()
        cursor = QTextCursor(document)
        for index in range(text_layout.lineCount()):
            line = text_layout.lineAt(index)
            line_start = line.textStart()
            line_end = line_start + line.textLength()
            cursor.setPosition(_clamp_pos(document, block_start + line_start))
            line_rect = browser.cursorRect(cursor)
            if not line_rect.isValid():
                continue
            origin_x = line_rect.left() - line.cursorToX(line_start)[0]
            for frag_pos, frag_len in marks:
                segment_start = max(frag_pos, line_start)
                segment_end = min(frag_pos + frag_len, line_end)
                if segment_end <= segment_start:
                    continue
                x1 = origin_x + line.cursorToX(segment_start)[0]
                x2 = origin_x + line.cursorToX(segment_end)[0]
                if x2 <= x1:
                    continue
                background = QRectF(
                    x1 - _INLINE_CODE_PADDING,
                    line_rect.top() + 1.0,
                    (x2 - x1) + 2 * _INLINE_CODE_PADDING,
                    max(1.0, line_rect.height() - 2.0),
                )
                painter.drawRoundedRect(
                    background, _INLINE_CODE_RADIUS, _INLINE_CODE_RADIUS
                )

    def _paint_document_decorations(self, browser, painter) -> None:
        """标题分隔线 / hr / 引用竖线 / 代码卡圆角（文档绘制之后调用）。"""
        document = self.document()
        layout = document.documentLayout()
        offset = browser.verticalScrollBar().value()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        first, last = self._visible_blocks(browser)
        block = first
        while block.isValid():
            rect = layout.blockBoundingRect(block)
            if rect.top() - offset > browser.viewport().height():
                break
            block_format = block.blockFormat()
            level = block_format.headingLevel()
            if level in (1, 2):
                painter.fillRect(
                    QRectF(
                        rect.x(),
                        rect.bottom() - offset - _HEADING_RULE_WIDTH,
                        rect.width(),
                        _HEADING_RULE_WIDTH,
                    ),
                    self._heading_rule_color,
                )
            if block_format.property(_HR_MARK):
                painter.fillRect(
                    QRectF(
                        rect.x(),
                        rect.center().y() - offset - _HR_LINE_WIDTH / 2.0,
                        rect.width(),
                        _HR_LINE_WIDTH,
                    ),
                    self._hr_color,
                )
            quote_level = block_format.property(QTextFormat.Property.BlockQuoteLevel) or 0
            if quote_level:
                rail = block_format.property(_CALLOUT_RAIL_PROPERTY)
                color = QColor(rail) if rail else self._quote_rail_color
                painter.fillRect(
                    QRectF(
                        rect.x()
                        + _QUOTE_RAIL_INSET
                        + (int(quote_level) - 1) * _QUOTE_LEFT_MARGIN,
                        rect.top() - offset,
                        _QUOTE_RAIL_WIDTH,
                        rect.height(),
                    ),
                    color,
                )
            if block.blockNumber() >= last.blockNumber():
                break
            block = block.next()
        self._paint_code_card_chrome(browser, painter)

    def _paint_code_card_chrome(self, browser, painter) -> None:
        """代码软卡片：6px 圆角（无描边，Qt 表格无圆角 API，用四角遮罩补齐）。

        先按帧矩形做视口裁剪：只给可见的表算几何（离屏的代码块再多也不付
        ``cursorRect`` 代价，否则重绘成本随全文档代码块数线性上升）。
        """
        viewport_height = browser.viewport().height()
        offset = browser.verticalScrollBar().value()
        layout = self.document().documentLayout()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for table in self._code_buttons_tables:
            if not self._code_table_in_view(table, layout, offset, viewport_height):
                continue
            rect = self._code_table_viewport_rect(table)
            if rect.isNull() or rect.bottom() < 0 or rect.top() > viewport_height:
                continue
            rounded = QRectF(rect)
            path = QPainterPath()
            path.addRoundedRect(rounded, _CODE_CARD_RADIUS, _CODE_CARD_RADIUS)
            painter.save()
            painter.setClipRect(rect)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._base_bg)
            outer = QPainterPath()
            outer.addRect(rect)
            painter.drawPath(outer.subtracted(path))
            painter.restore()

    def _update_code_button_hover(self, pos, pressed: bool = False) -> None:
        """鼠标移动时显示所在代码块的复制按钮，其余隐藏；``pressed`` 为真
        （拖选文本）时不弹按钮。
        """
        if pressed or QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            # 拖选文本期间不弹出按钮，避免遮挡选择
            self._hide_code_buttons()
            return
        for index, rect in enumerate(self._code_button_rects):
            if rect.isNull():
                continue
            if rect.contains(QPointF(pos)):
                self._show_code_button(index)
                return
        self._hide_code_buttons()

    def _show_code_button(self, index: int) -> None:
        """显示指定代码块的复制按钮（只动前后两个按钮，O(1)）。"""
        rect = (
            self._code_button_rects[index]
            if index < len(self._code_button_rects)
            else QRectF()
        )
        visible = (
            not rect.isNull()
            and 0 <= rect.top() <= self._text_browser.viewport().height()
        )
        if index == self._shown_code_button:
            if visible:
                if not self._code_buttons[index].isVisible():
                    # 被 _position_code_buttons 因离屏隐藏过：补显示
                    self._code_buttons[index].setVisible(True)
            else:
                self._hide_code_buttons()
            return
        self._hide_code_buttons()
        if visible and 0 <= index < len(self._code_buttons):
            self._code_buttons[index].setVisible(True)
            self._shown_code_button = index

    def _hide_code_buttons(self) -> None:
        index = self._shown_code_button
        self._shown_code_button = -1
        if 0 <= index < len(self._code_buttons):
            self._code_buttons[index].hide()

    def _hover_from_cursor(self) -> None:
        pos = self._text_browser.viewport().mapFromGlobal(QCursor.pos())
        self._update_code_button_hover(pos)

    def _copy_code_block(self, index: int) -> None:
        """复制指定代码块并给出短暂的对勾反馈。"""
        if not 0 <= index < len(self._code_buttons_tables):
            return
        table = self._code_buttons_tables[index]
        if is_deleted(table):
            return
        self._copy_text(self._code_table_text(table))
        button = self._code_buttons[index]
        button.setIcon(self._code_check_icon())
        single_shot_on(self, 1000, lambda: self._restore_code_button_icon(button))

    def _restore_code_button_icon(self, button: QToolButton) -> None:
        try:
            button.setIcon(self._code_copy_icon())
        except RuntimeError:
            # 控件已随文档重渲染销毁
            pass

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        if self._embedded:
            # 宽度变化后**同步**校正一次嵌入高度：不能只依赖 80ms 去抖 ——
            # 慢机器上按旧宽度冻住的高度会一直留到下一次流式 flush / 重排
            # （表现为「思考内容与后续分段之间多出数行空白」）。先激活内层
            # 布局让浏览器落到新尺寸、文档按新宽度重排，再测量；测不准时
            # _sync_embedded_height 会自己跳过并保留旧值。
            layout = self.layout()
            if layout is not None:
                layout.activate()
            self._sync_embedded_height()
        self._schedule_layout_refresh()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._applyThemeStyle()

    def paintEvent(self, _event: Optional[QPaintEvent]) -> None:
        """绘制圆角背景（圆角半径为 0 时绘制普通矩形背景）；嵌入模式跳过。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._embedded:
            bg_color = eTheme.getThemeColor(
                self._theme_mode, ElaThemeType.ThemeColor.BasicPress
            )
            if self._border_radius > 0:
                path = QPainterPath()
                path.addRoundedRect(
                    QRectF(self.rect()), self._border_radius, self._border_radius
                )
                painter.fillPath(path, bg_color)
            else:
                painter.fillRect(self.rect(), bg_color)
        if self._placeholder and not self._source:
            painter.setPen(self._placeholder_color)
            font = QFont(painter.font())
            font.setPointSizeF(max(self._base_font_point_size, 9.0))
            painter.setFont(font)
            painter.drawText(
                self.rect().adjusted(16, 16, -16, -16),
                int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap),
                self._placeholder,
            )
        self._paint_stream_caret(painter)
        painter.end()

    def _paint_stream_caret(self, painter: QPainter) -> None:
        """流式期间在文档末尾绘制闪烁打字光标。"""
        if not (self._stream_active and self._caret_visible and self._source):
            return
        document = self.document()
        if document.characterCount() <= 1:
            return
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        rect = self._text_browser.cursorRect(cursor)
        if not rect.isValid():
            return
        top_left = self._text_browser.viewport().mapTo(self, rect.topLeft())
        painter.fillRect(
            QRectF(float(top_left.x()), float(top_left.y()), 2.0, float(rect.height())),
            self._text_color,
        )
