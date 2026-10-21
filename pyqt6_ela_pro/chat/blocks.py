"""
聊天消息内部子块组件（``pyqt6_ela_pro.chat``）。

实现件优先复用 Ela 原生组件：

- 卡片面 / 折叠块 / 错误卡：``ElaScrollPageArea``（圆角主题底）；
- 折叠箭头、关闭按钮、图片缩略：``ElaIconButton``；
- 运行中指示：``ElaProgressRing``（``IsBusying``）；
- 文本：``ElaText``；附件 chips：``ElaChip``；换行布局：``ElaFlowLayout``。

部件一览：

- :class:`MessageHeader`：头部层（头像 + 名称 + 时间 / 状态）；
- :class:`ReasoningBlock`：思考层（可折叠、耗时）；
- :class:`ThinkingRow`：思考行（``ElaProgressRing`` + 标题抽取）；
- :class:`ToolGroupPanel`：工具调用外层折叠面板（``工具调用 (N)``，
  对齐 agent_chat 的层级）；
- :class:`ToolCallCard`：工具层单卡片（对齐 opencode 的折叠语义）；
- :class:`ContextToolGroupCard`：上下文工具分组卡（read/glob/grep/list）；
- :class:`AttachmentStrip`：附件层（ElaChip / 图片缩略，可换行）；
- :class:`StatsBadge`：用量徽标；
- :class:`MessageActions`：底部操作栏；
- :class:`ErrorCard`：错误卡（左 danger 竖线）。
"""

from __future__ import annotations

import html
import itertools
import math
import re
from dataclasses import replace
from pathlib import Path
from typing import Optional, Union

from .._internal import is_deleted, system_cjk_font_family
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaFlowLayout,
    ElaIcon,
    ElaIconButton,
    ElaIconType,
    ElaPlainTextEdit,
    ElaProgressRing,
    ElaScrollPageArea,
    ElaText,
    ElaThemeType,
    eTheme,
)

from .._internal import _ThemeAwareMixin
from .._motion import idle_loop_running, start_idle_loop
from .._styles import BareButton, ColorText, setSolidBackground
from .._theme import ElaStatusRoleType, statusColor
from ..ela_button import ElaButton
from ..ela_chip import ElaChip
from ..svg_icon import svg_to_pixmap
from ..tooltips import ElaToolTipPositionType, remove_tooltip, set_tooltip
from ..widget_base import ElaThemeWidget
from . import _json
from ._question import (
    OPTION_GAP,
    SEGMENT_HIT,
    QuestionOptionCard,
    QuestionSegment,
    globalKeyAction,
    question_colors,
)
from ._theme import (
    accent_color,
    base_color,
    blend,
    mono_font,
    muted_color,
    text_color,
)
from .message import (
    ElaChatAttachment,
    ElaChatPermission,
    ElaChatPermissionStatusType,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
    ElaChatToolCall,
    ElaChatToolStatusType,
    _as_int,
)
from .renderers import (
    ToolRenderContext,
    parseToolArguments,
    toolRenderer,
    toolRendererSubtitle,
)
from .toolbar import ElaChatToolBar

#: 头像边长（像素）
AVATAR_SIZE = 30
#: 头像圆角半径（``"rounded"`` 形状用，Editorial Agent 风格）
AVATAR_RADIUS = 8
#: 头像形状取值：正圆 / 圆角方形 / 直角方形
AVATAR_SHAPES = ("circle", "rounded", "square")
#: 头像默认形状（正圆）
AVATAR_DEFAULT_SHAPE = "circle"
#: 自定义头像来源：SVG 数据 / SVG 或位图路径 / 原始字节 / Qt 位图对象
ElaChatAvatarSource = Union[str, bytes, QPixmap, QImage, QIcon]
#: 角色默认头像图标
ROLE_ICONS = {
    ElaChatRoleType.User: ElaIconType.IconName.User,
    ElaChatRoleType.Assistant: ElaIconType.IconName.Robot,
    ElaChatRoleType.System: ElaIconType.IconName.Comment,
}
#: 工具名 → 图标（对齐 opencode 的工具图标语义）
TOOL_ICONS = {
    "read": ElaIconType.IconName.Glasses,
    "list": ElaIconType.IconName.ListUl,
    "glob": ElaIconType.IconName.MagnifyingGlass,
    "grep": ElaIconType.IconName.MagnifyingGlass,
    "webfetch": ElaIconType.IconName.Window,
    "websearch": ElaIconType.IconName.Globe,
    "task": ElaIconType.IconName.ListCheck,
    "shell": ElaIconType.IconName.Terminal,
    "bash": ElaIconType.IconName.Terminal,
    "edit": ElaIconType.IconName.Code,
    "write": ElaIconType.IconName.Code,
    "patch": ElaIconType.IconName.Code,
    "apply_patch": ElaIconType.IconName.Code,
    "todowrite": ElaIconType.IconName.SquareCheck,
    "question": ElaIconType.IconName.Comment,
    "skill": ElaIconType.IconName.Brain,
}
#: 上下文工具（连续出现时合并为分组卡）
CONTEXT_TOOLS = ("read", "glob", "grep", "list")
#: 可原地重试的错误类型（小写比较；``binder.error(errorType, msg)`` 的首参）
#:
#: 判据是「**换次机会大概率会成功**」：限流 / 超时 / 网络抖动 / 服务端 5xx
#: 属于这一类；参数错误、鉴权失败、内容过滤、上下文超长重试只会再失败一次，
#: 所以不给「重试」按钮（仍给「重新生成」，换采样有时能绕开）。
RETRYABLE_ERROR_TYPES = frozenset(
    {
        "ratelimit",
        "rate_limit",
        "rate-limit",
        "timeout",
        "timedout",
        "timed_out",
        "network",
        "networkerror",
        "connection",
        "connectionerror",
        "overloaded",
        "servererror",
        "internalservererror",
        "serviceunavailable",
        "badgateway",
        "gatewaytimeout",
        "apierror",
        "transient",
    }
)
#: 子标题候选字段（按优先级）
_SUBTITLE_KEYS = (
    "description",
    "path",
    "filePath",
    "file",
    "pattern",
    "query",
    "command",
    "url",
    "prompt",
    "name",
    "id",
)
#: 图片附件缩略图尺寸
_IMAGE_THUMB_SIZE = (58, 46)
#: 压缩分隔卡折叠态的摘要预览最多几个字符
PREVIEW_MAX_CHARS = 72
#: 审批卡详情默认只露这么多行（超出折叠 + 「展开全部」链接）
DETAIL_COLLAPSED_LINES = 8
#: 单行超过这么多字符就截断（minified 文件 / 一整行 base64 都能炸）
DETAIL_MAX_LINE_CHARS = 400
#: 思考正文的合并刷新间隔（ms）。正文是整段 PlainText 标签，每次刷新都要重新折行
#: 全文；逐事件轮次刷新时 300 个分片（7.2KB）实测 9.6s，合并到每 5 片一次只要
#: 1.8s。40ms 对阅读几乎无感（约 25fps），但把重排次数砍掉一个量级。
REASONING_FLUSH_INTERVAL_MS = 40
#: 卡片上下内边距
CARD_V_PADDING = 9
#: 卡片纵向布局项之间的间距
LAYOUT_SPACING = 6


def _clip_detail(detail: str) -> str:
    """截断超长单行（展开态也照截，否则点开就炸）。"""
    out = []
    for line in detail.split("\n"):
        if len(line) > DETAIL_MAX_LINE_CHARS:
            line = line[:DETAIL_MAX_LINE_CHARS] + " …（本行已截断）"
        out.append(line)
    return "\n".join(out)


def _collapsed_detail(detail: str, expanded: bool) -> tuple:
    """按「行数 + 单行长度」双上限算详情展示文本。

    返回 ``(shown, overflow, total_lines)``。交互卡与记录卡共用这一份 ——
    两处各写一份时，交互卡那版在短详情上会拼出「… 还有 -5 行」。
    """
    full = _clip_detail(detail)
    lines = full.split("\n") if full else []
    overflow = len(lines) > DETAIL_COLLAPSED_LINES
    if expanded:
        return full, overflow, len(lines)
    kept = lines[:DETAIL_COLLAPSED_LINES]
    if overflow:
        kept.append(f"… 还有 {len(lines) - DETAIL_COLLAPSED_LINES} 行")
    return "\n".join(kept), overflow, len(lines)


# -- 工具卡默认展开策略 ---------------------------------------------------
#
# 「哪些工具默认展开」是**宿主的产品决策**，不该硬编码在库里 —— 所以默认策略
# 只包含一条与领域无关、且几乎 universally 正确的规则，其余由宿主注入。
# 签名刻意做成纯函数（无副作用、可单测），形态对齐 opencode 的
# ``partDefaultOpen``。

#: shell 类工具（小写匹配）—— 命令与输出是多行文本，折叠起来几乎读不到。
#: **两个消费者共用这一份清单**：默认展开策略（:func:`toolDefaultOpenCoding`）
#: 与 ``ToolCallCard`` 的「pending 时是否允许展开」（``bubble.addToolCall``），
#: 各写一份必然漂移。
SHELL_TOOLS = ("bash", "shell", "run", "exec", "terminal")

#: 写文件类工具（小写匹配）—— 展开可能很长，改动内容需要被看到
_WRITE_TOOLS = ("edit", "write", "patch", "apply_patch")


def toolDefaultOpen(name: str, arguments=None, ok: bool = True) -> bool:
    """库默认策略：**只有失败的工具调用默认展开**。

    失败时用户必须看到原因，折叠起来等于把最重要的信息藏起来 —— 这条规则
    与工具语义无关，任何宿主都成立。其余一律折叠：默认折叠是安全的一侧，
    展开的成本（视觉噪音、展开动画、渲染开销）远大于收益。

    宿主可用 :meth:`ElaChatBubble.setToolDefaultOpen` 换成自己的策略，典型
    需求是「shell / 写文件类默认展开」—— 见
    :func:`toolDefaultOpenCoding`。
    """
    if not ok:
        return True
    return False


def toolDefaultOpenCoding(name: str, arguments=None, ok: bool = True) -> bool:
    """编码 agent 场景的展开策略（供宿主注入，示例实现）。

    在库默认之上加两条编码 agent 特有的判断：

    - **shell / bash 默认展开** —— 命令与输出是多行文本，折叠起来几乎读不到；
    - **纯删除永远折叠** —— 删除的 diff 对用户是噪音，展开没有价值
      （对应 opencode 的 ``deletionOnly`` 判断：只看是否所有条目都是删除）；
    - 写文件类（edit / write / patch）仍走默认折叠，但**非纯删除时展开**
      —— 改动内容需要被看到。

    纯函数：宿主可先调 :func:`toolDefaultOpen` 再叠加自己的规则。
    """
    if toolDefaultOpen(name, arguments, ok):
        return True
    key = (name or "").lower()
    if key in SHELL_TOOLS:
        return True
    data = parseToolArguments(arguments) if arguments else {}
    # 只在**有证据**表明这是真实改动时才展开：参数里没有任何 diff 信息就保持
    # 折叠（安全的一侧）。空参数不该让每次写文件调用都自动摊开。
    if key in _WRITE_TOOLS and data and not _deletionOnly(data):
        return True
    return False


def _deletionOnly(data: dict) -> bool:
    """参数里是否**只有**删除项（对齐 opencode 的同名判断）。"""
    if not data:
        return False
    # files 数组：全部 type == "delete"
    files = data.get("files")
    if isinstance(files, list) and files:
        types = [
            item.get("type")
            for item in files
            if isinstance(item, dict) and item.get("type")
        ]
        if types and all(t == "delete" for t in types):
            return True
    # 计数式 diff：只有删除行
    additions = data.get("additions")
    deletions = data.get("deletions")
    if isinstance(additions, int) and isinstance(deletions, int):
        return additions == 0 and deletions > 0
    return False


#: 头像图标位图缓存：``(图标值, 尺寸, ARGB)`` → QPixmap。同一主题下助手头像
#: 完全同参，切主题时几十条消息不再各 rasterize 一次（Win7 上字体图标光栅化更贵）。
_AVATAR_PIXMAP_CACHE: dict = {}
_AVATAR_PIXMAP_CACHE_MAX = 64


def avatarPixmap(iconName, size: int, color: QColor) -> QPixmap:
    """按颜色渲染 Ela 图标位图（失败时返回空位图）。"""
    key = (
        int(getattr(iconName, "value", iconName)),
        int(size),
        QColor(color).rgba(),
    )
    cached = _AVATAR_PIXMAP_CACHE.get(key)
    if cached is not None:
        # 返回值可能是共享 pixmap：调用方只画不就地改，但仍给独立包装器，
        # 避免 ``cacheKey`` 相同的缓存对象被宿主改掉（同 ``svg_to_pixmap`` 的教训）。
        return QPixmap(cached)
    try:
        icon = ElaIcon.getInstance().getElaIcon(iconName, QColor(color))
        pixmap = icon.pixmap(QSize(size, size))
    except Exception:
        return QPixmap()
    if len(_AVATAR_PIXMAP_CACHE) >= _AVATAR_PIXMAP_CACHE_MAX:
        _AVATAR_PIXMAP_CACHE.clear()
    _AVATAR_PIXMAP_CACHE[key] = QPixmap(pixmap)
    return pixmap


def normalizeAvatarShape(shape) -> str:
    """校验头像形状取值，非法值回落为默认（``"circle"``）。"""
    return shape if shape in AVATAR_SHAPES else AVATAR_DEFAULT_SHAPE


def _load_avatar_pixmap(source, size: int) -> Optional[QPixmap]:
    """把自定义头像来源解析为 ``QPixmap``（失败返回 ``None``）。

    支持：``QPixmap`` / ``QImage`` / ``QIcon`` / ``bytes``（原始图片数据或
    UTF-8 SVG 数据）/ SVG 数据字符串 / 图片或 SVG 文件路径。
    """
    if source is None:
        return None
    if isinstance(source, QPixmap):
        return QPixmap(source)
    if isinstance(source, QImage):
        return QPixmap.fromImage(source)
    if isinstance(source, QIcon):
        pixmap = source.pixmap(QSize(size, size))
        return None if pixmap.isNull() else pixmap
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            return pixmap
        try:
            svg_data = data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        rendered = svg_to_pixmap(svg_data, size)
        return None if rendered.isNull() else rendered
    if isinstance(source, str) or hasattr(source, "__fspath__"):
        text = str(source)
        if "<svg" in text:
            rendered = svg_to_pixmap(text, size)
            return None if rendered.isNull() else rendered
        path = Path(text)
        if path.suffix.lower() == ".svg" and path.is_file():
            try:
                rendered = svg_to_pixmap(path.read_text(encoding="utf-8"), size)
            except (OSError, UnicodeDecodeError):
                return None
            return None if rendered.isNull() else rendered
        pixmap = QPixmap(text)
        return None if pixmap.isNull() else pixmap
    return None


def toolIconName(name: str):
    """工具名 → ``ElaIconType`` 图标（未知工具用 Cube）。"""
    return TOOL_ICONS.get((name or "").lower(), ElaIconType.IconName.Cube)


def toolSubtitleParts(arguments) -> tuple:
    """返回 ``(命中的键, 值)``；未命中返回 ``("", "")``。

    与 :func:`toolSubtitle` 同一套选取逻辑，但把**键**也带出来 —— 参数摘要
    需要据此排除，避免同一个值在副标题和参数里各出现一次
    （``read(path="a.py")`` 会显示两遍 ``a.py``）。
    """
    data = parseToolArguments(arguments)
    for key in _SUBTITLE_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return key, value.strip()
    for key, value in data.items():
        if isinstance(value, str) and value.strip():
            return key, value.strip()
    return "", ""


def toolSubtitle(name: str, arguments) -> str:
    """从工具参数中提取副标题（优先常见路径 / 查询 / 命令字段）。"""
    return toolSubtitleParts(arguments)[1]


#: 参数摘要里大容器的预览条数（只为看一眼「是什么形状」，不用看全）
_PREVIEW_ITEMS = 8

#: 头部省略的源串上限：``QFontMetrics.elidedText`` 成本随源串长度线性增长，
#: 而展示区最多几十字符。本 bundle 实测 613/1428 个工具副标题 >200 字
#: （最大 4124，shell command 全量）—— 不截源就每次 resize 都整串测量。
_ELIDE_SOURCE_MAX = 160


def _preview_value(value) -> str:
    """有界地序列化一个参数值（大容器只序列化前 ``_PREVIEW_ITEMS`` 项）。

    dict 分支走 ``itertools.islice``：``list(value.items())`` 会把**全部**
    键值对先物化一遍，docstring 承诺的「有界」就打了折（万级键的 dict 白付
    一次列表构造）。
    """
    if isinstance(value, dict):
        total = len(value)
        head = dict(itertools.islice(value.items(), _PREVIEW_ITEMS))
        suffix = f"…(+{total - len(head)} 键)" if total > len(head) else ""
    elif isinstance(value, (list, tuple)):
        total = len(value)
        head = list(value[:_PREVIEW_ITEMS])
        suffix = f"…(+{total - len(head)} 项)" if total > len(head) else ""
    else:
        return str(value)
    try:
        return _json.dumps(head) + suffix
    except (TypeError, ValueError):
        return str(head) + suffix


def toolArgumentPairs(arguments, limit: int = 3, excludeKey: str = "") -> list:
    """提取 ``key=value`` 形式的参数摘要（最多 ``limit`` 个）。

    副标题已经展示过的值**不该在参数里再出现一次**（纯噪音）：
    ``read(path="a.py")`` 因此只显示一次 ``a.py``，而不是副标题 + ``path=a.py``
    各一份。大容器（长列表 / 大对象）走**有界预览**，不会为了最终只留 47 个
    字符先把整个值全量序列化一遍。

    :param limit: 最多返回几条
    :param excludeKey: 要排除的键。调用方**自己**决定传什么：通用路径传
        :func:`toolSubtitleParts` 探测到的键；宿主注册了渲染器的工具传它
        ``subtitle`` 声明的来源键（那个键可能压根不是字符串，自动探测选不中，
        也可能根本不对应任何参数，比如「3 个文件」）。留空则不做排除。
    """
    data = parseToolArguments(arguments)
    pairs = []
    for key, value in data.items():
        if not key or key == excludeKey:
            continue
        if isinstance(value, str):
            text = value
        elif isinstance(value, (int, float, bool)):
            text = str(value)
        else:
            text = _preview_value(value)
        if len(text) > 48:
            text = text[:47] + "…"
        pairs.append(f"{key}={text}")
        if len(pairs) >= limit:
            break
    return pairs


def formatDuration(durationMs: float) -> str:
    """耗时格式化：``3.2s`` / ``1m 20s``（非有限值按「未统计」返回空串）。"""
    if not durationMs:
        return ""
    try:
        seconds = max(0.0, float(durationMs)) / 1000.0
    except (TypeError, ValueError, OverflowError):
        return ""
    if not math.isfinite(seconds):
        # inf // 60 是 nan，int(nan) 抛 ValueError —— 宿主 / 后端给个 inf 就能
        # 在 Qt 槽链上炸掉整个进程，这里按「未统计」处理。
        return ""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    return f"{minutes}m {int(seconds % 60)}s"


_HEADING_PATTERNS = (
    re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*\r?$", re.MULTILINE),
    re.compile(r"^[ \t]{0,3}\*\*(.+?)\*\*[ \t]*\r?$", re.MULTILINE),
    re.compile(r"^[ \t]{0,3}(.+?)\n[ \t]{0,3}[=-]{3,}[ \t]*\r?$", re.MULTILINE),
)

#: 标题候选行最大长度（展示层本就截断到 60 字符，超长行不可能成为标题）
_HEADING_LINE_LIMIT = 256


def _clean_heading(raw: str) -> str:
    """清洗标题原文（去行内标记与前导列表符号）。"""
    heading = re.sub(r"[*_`~]+", "", raw).strip()
    return re.sub(r"^[\-\*\d\.、\s]+", "", heading).strip()


def _iter_heading_matches(pattern, text):
    """按「单行上限」过滤的模式匹配（与 :class:`_HeadingScanner` 同口径）。"""
    for match in pattern.finditer(text):
        lines = match.group(0).replace("\r", "").split("\n")
        if any(len(line) > _HEADING_LINE_LIMIT for line in lines):
            continue
        yield match


def extractReasoningHeading(text: str) -> str:
    """从推理文本中抽取标题（ATX / 加粗行 / Setext），并清洗行内标记。

    按模式优先级（ATX > 加粗 > Setext）返回**首个清洗后非空**的命中；
    仅识别显式 Markdown 标题，普通正文不返回首行，避免与思考正文重复展示。
    与 :class:`_HeadingScanner` 的增量结果保持一致（同一语义两套实现）——
    **含「单行超长视为不可能」这一条**：增量扫描器为控成本跳过超长行，
    全量抽取此前不设上限，一行 300 字符的加粗文本会让两者给出不同结果。
    """
    if not text:
        return ""
    text = re.sub(r"\r+\n", "\n", text)
    for pattern in _HEADING_PATTERNS:
        for match in _iter_heading_matches(pattern, text):
            heading = _clean_heading(match.group(1))
            if heading:
                return heading
    return ""


class _HeadingScanner:
    """增量标题扫描器：逐分片喂入，结果与 ``extractReasoningHeading(全文)`` 一致。

    按行跟踪「上一完整行 + 当前行」：完整行的命中不可撤销（``_found``），
    当前行的命中是临时的（``_carry_found``，行继续增长可能失效后重算），
    结果按 ``_HEADING_PATTERNS`` 优先级（ATX > 加粗 > Setext）取最早命中；
    单行超过 ``_HEADING_LINE_LIMIT`` 视为不可能（展示层截断到 60 字符）。
    每分片开销与分片长度成正比，避免长思考文本的逐片全量正则扫描。
    """

    def __init__(self) -> None:
        self._prev: Optional[str] = None
        self._line = ""
        self._oversized = False
        self._found: dict = {}
        self._carry_found: dict = {}

    def push(self, chunk: str) -> str:
        """喂入一个分片，返回当前标题（无则空串）。"""
        if self._oversized:
            # 超长行：只等换行，行内容不再参与匹配（避免长行拼接的 O(n²)）
            if "\n" not in chunk:
                return self.result()
            _, chunk = chunk.split("\n", 1)
            self._oversized = False
            self._prev = ""
            self._line = ""
            if not chunk:
                return self.result()
        text = self._line + chunk
        while "\n" in text:
            line, text = text.split("\n", 1)
            line = line.rstrip("\r")
            self._record_complete(line)
            self._prev = line
        self._carry_found = {}
        if len(text) > _HEADING_LINE_LIMIT:
            self._oversized = True
            self._line = ""
        else:
            self._line = text
            self._check_inline(text, self._carry_found)
            self._check_setext(text, self._carry_found)
        return self.result()

    def result(self) -> str:
        """当前标题（完整行优先，再按模式优先级取最早命中）。"""
        for index in range(len(_HEADING_PATTERNS)):
            heading = self._found.get(index)
            if heading:
                return heading
            heading = self._carry_found.get(index)
            if heading:
                return heading
        return ""

    def _record_complete(self, line: str) -> None:
        """记录一个完整行的命中（不可撤销；仅记录该模式首次出现）。"""
        found: dict = {}
        self._check_inline(line, found)
        self._check_setext(line, found)
        for index, heading in found.items():
            self._found.setdefault(index, heading)

    def _check_inline(self, line: str, sink: dict) -> None:
        """检查单行标题（ATX / 整行加粗）；候选行超长直接跳过。"""
        if len(line) > _HEADING_LINE_LIMIT:
            return
        if 0 not in sink and 0 not in self._found:
            match = _HEADING_PATTERNS[0].fullmatch(line)
            if match:
                heading = _clean_heading(match.group(1))
                if heading:
                    sink[0] = heading
        if 1 not in sink and 1 not in self._found:
            match = _HEADING_PATTERNS[1].fullmatch(line)
            if match:
                heading = _clean_heading(match.group(1))
                if heading:
                    sink[1] = heading

    def _check_setext(self, line: str, sink: dict) -> None:
        """检查「上一行 + 当前行」构成的 Setext 标题。"""
        if 2 in sink or 2 in self._found or self._prev is None:
            return
        if len(line) > _HEADING_LINE_LIMIT or len(self._prev) > _HEADING_LINE_LIMIT:
            return
        match = _HEADING_PATTERNS[2].fullmatch(self._prev + "\n" + line)
        if match:
            heading = _clean_heading(match.group(1))
            if heading:
                sink[2] = heading


class _AvatarBadge(QWidget):
    """头像徽标（默认正圆；``setShape`` 可切圆角方形 / 直角方形）。

    默认主题色底 + ElaIcon 字形；支持自定义图片 / SVG（按当前形状裁切）。
    """

    def __init__(self, role: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._role = role
        self._icon_name = ROLE_ICONS.get(role, ElaIconType.IconName.Comment)
        self._bg = QColor()
        self._border = QColor()
        self._icon: Optional[QPixmap] = None
        self._custom: Optional[QPixmap] = None
        #: 自定义头像按 (宽, 高, DPR) 缩放后的缓存：paintEvent 每帧都做
        #: SmoothTransformation 很贵，而固定尺寸下缩放结果是不变量。
        self._scaled_custom: Optional[QPixmap] = None
        self._scaled_custom_key: Optional[tuple] = None
        self._shape = AVATAR_DEFAULT_SHAPE
        self._theme_mode = eTheme.getThemeMode()
        self.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._apply_theme()

    def setIconName(self, iconName: ElaIconType.IconName) -> None:
        """设置头像图标（``ElaIconType`` 成员）。"""
        self._icon_name = iconName
        self._apply_theme()
        self.update()

    def iconName(self):
        """获取当前头像图标。"""
        return self._icon_name

    # -- 形状 --------------------------------------------------------------

    def setShape(self, shape: str) -> None:
        """设置头像形状（``"circle"`` / ``"rounded"`` / ``"square"``）。

        非法值回落为默认（``"circle"``）。
        """
        shape = normalizeAvatarShape(shape)
        if shape == self._shape:
            return
        self._shape = shape
        self.update()

    def shape(self) -> str:
        """获取当前头像形状。"""
        return self._shape

    # -- 自定义头像 --------------------------------------------------------

    def setImage(self, source: ElaChatAvatarSource) -> None:
        """设置自定义头像图（``None`` 清除并回退到内置图标）。

        支持 SVG 数据字符串、SVG / 位图文件路径、``bytes`` 图片数据、
        ``QPixmap`` / ``QImage`` / ``QIcon``。
        """
        self._custom = _load_avatar_pixmap(source, AVATAR_SIZE * 2)
        self._scaled_custom = None
        self._scaled_custom_key = None
        self.update()

    def image(self) -> Optional[QPixmap]:
        """获取自定义头像图（未设置返回 ``None``）。"""
        return None if self._custom is None else QPixmap(self._custom)

    def hasCustomImage(self) -> bool:
        """是否已设置自定义头像图。"""
        return self._custom is not None and not self._custom.isNull()

    def setThemeMode(self, mode) -> None:
        """更新主题模式并重绘。"""
        self._theme_mode = mode
        self._apply_theme()

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        base = base_color(mode)
        text = text_color(mode)
        accent = accent_color(mode)
        if self._role == ElaChatRoleType.User:
            self._bg = blend(base, accent, 0.22)
            self._border = blend(base, accent, 0.38)
        else:
            self._bg = blend(base, text, 0.06)
            self._border = blend(base, text, 0.14)
        self._icon = avatarPixmap(
            self._icon_name, int(AVATAR_SIZE * 0.62), text_color(mode)
        )
        self.update()

    def _shape_path(self) -> QPainterPath:
        """头像外形路径（按当前形状生成圆 / 圆角方形 / 直角方形）。"""
        rect = QRectF(self.rect())
        path = QPainterPath()
        if self._shape == "square":
            path.addRect(rect)
        elif self._shape == "rounded":
            path.addRoundedRect(rect, AVATAR_RADIUS, AVATAR_RADIUS)
        else:
            path.addEllipse(rect)
        return path

    def _stroke_shape(self, painter: QPainter) -> None:
        """按当前形状描边（1px，内缩半像素避免发虚）。"""
        pen = QPen(self._border)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._shape == "square":
            painter.drawRect(rect)
        elif self._shape == "rounded":
            painter.drawRoundedRect(rect, AVATAR_RADIUS, AVATAR_RADIUS)
        else:
            painter.drawEllipse(rect)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        clip = self._shape_path()
        custom = self._custom
        if custom is not None and not custom.isNull():
            painter.setClipPath(clip)
            dpr = self.devicePixelRatioF() or 1.0
            key = (self.width(), self.height(), dpr)
            if self._scaled_custom_key != key or self._scaled_custom is None:
                target = QSize(
                    max(1, int(self.width() * dpr)),
                    max(1, int(self.height() * dpr)),
                )
                scaled = custom.scaled(
                    target,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                scaled.setDevicePixelRatio(dpr)
                self._scaled_custom = scaled
                self._scaled_custom_key = key
            scaled = self._scaled_custom
            offset = self._device_aligned_offset(
                scaled.width() / dpr, scaled.height() / dpr, dpr
            )
            painter.drawPixmap(offset, scaled)
            painter.setClipping(False)
            self._stroke_shape(painter)
            painter.end()
            return

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._bg)
        painter.drawPath(clip)
        self._stroke_shape(painter)
        if self._icon is not None and not self._icon.isNull():
            # 位图本身已按 DPR 渲染（``QIcon::pixmap`` 跟随应用 DPR），但**居中必须
            # 按逻辑尺寸算**并把落点对齐到设备像素网格：用物理尺寸居中（``(30-23)//2``）
            # 会让图标落在 3.75 设备像素上，叠加 SmoothPixmapTransform 一重采样就发虚
            # —— 125% / 150% 缩放下最明显（表现为头像「糊」且偏左上）。
            dpr = self._icon.devicePixelRatio() or 1.0
            painter.drawPixmap(
                self._device_aligned_offset(
                    self._icon.width() / dpr, self._icon.height() / dpr, dpr
                ),
                self._icon,
            )
        painter.end()

    def _device_aligned_offset(
        self, width: float, height: float, dpr: float
    ) -> QPointF:
        """把位图居中、并把左上角落到**设备像素整数网格**上（高 DPI 防发虚）。"""
        x = (self.width() - width) / 2.0
        y = (self.height() - height) / 2.0
        return QPointF(round(x * dpr) / dpr, round(y * dpr) / dpr)


#: 生成中状态点的呼吸周期（ms）。持续动效，Reduced/Disabled 下停掉（见 _motion）。
STATUS_DOT_BREATH_MS = 600


class _StatusDot(QWidget):
    """6px 状态点：生成中呼吸（明暗交替），其余状态静态。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(6, 6)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._color = QColor()
        self._active = False
        self._phase = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def setColor(self, color: QColor) -> None:
        """设置状态色。"""
        self._color = QColor(color)
        self.update()

    def setActive(self, on: bool) -> None:
        """呼吸开关（仅生成中开启；关闭时停止定时器避免空转）。"""
        on = bool(on)
        if on == self._active:
            return
        self._active = on
        if on:
            # 持续动效：Reduced/Disabled 下不启动（停掉，不是放慢 —— 转得更慢的
            # 呼吸看起来像卡住而不是在忙）。停掉时 paintEvent 画满不透明度的静态点。
            start_idle_loop(
                self._timer, STATUS_DOT_BREATH_MS, on_stop=self._settleStaticDot
            )
        else:
            self._timer.stop()
            self._phase = False
        self.update()

    def isActive(self) -> bool:
        """是否处于呼吸状态。"""
        return self._active

    def _tick(self) -> None:
        self._phase = not self._phase
        self.update()

    def _settleStaticDot(self) -> None:
        """呼吸循环停掉 → 相位归到「亮着」并重画。

        停掉时若停在低相位就是一个若隐若现的灰点，看不出「正在生成」。
        """
        self._phase = False
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._color)
        # 判据是「呼吸循环有没有真的在跑」而不是 _active：动效策略可能在运行期把
        # 循环停掉（_active 仍是 True），那时必须画**满不透明度**的静态点 ——
        # 停在低相位就是一个若隐若现的灰点，看不出「正在生成」。
        breathing = idle_loop_running(self._timer)
        color.setAlpha(255 if (not breathing or self._phase) else 110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(self.rect()))
        painter.end()


class MessageHeader(ElaThemeWidget):
    """消息头部层：头像 + 名称 + 时间 / 状态（状态点呼吸）。"""

    def __init__(
        self, role: str = ElaChatRoleType.Assistant, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._role = role
        self._title = ""
        self._timestamp = ""
        self._status_text = ""
        self._status_kind = ""
        self._avatar = _AvatarBadge(role, self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._texts = QVBoxLayout()
        self._texts.setContentsMargins(0, 1, 0, 1)
        self._texts.setSpacing(1)
        self._title_label = ElaText(self)
        self._title_label.setWordWrap(False)
        # 标题 / 时间 / 状态都可能是宿主或模型给的文本（模型名、自定义名），
        # AutoText 会把 "<b>" / "<img src=...>" 真解析。
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)

        self._subtitle_row = QWidget(self)
        self._subtitle_layout = QHBoxLayout(self._subtitle_row)
        self._subtitle_layout.setContentsMargins(0, 0, 0, 0)
        self._subtitle_layout.setSpacing(4)
        self._time_label = ColorText(self._subtitle_row)
        self._time_label.setWordWrap(False)
        self._time_label.setTextFormat(Qt.TextFormat.PlainText)
        self._sep_label = ColorText("·", self._subtitle_row)
        self._status_dot = _StatusDot(self._subtitle_row)
        self._status_label = ColorText(self._subtitle_row)
        self._status_label.setWordWrap(False)
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        if role == ElaChatRoleType.User:
            self._subtitle_layout.addStretch(1)
        self._subtitle_layout.addWidget(self._time_label)
        self._subtitle_layout.addWidget(self._sep_label)
        self._subtitle_layout.addWidget(self._status_dot)
        self._subtitle_layout.addWidget(self._status_label)
        if role != ElaChatRoleType.User:
            self._subtitle_layout.addStretch(1)

        self._texts.addWidget(self._title_label)
        self._texts.addWidget(self._subtitle_row)

        if role == ElaChatRoleType.User:
            layout.addStretch(1)
            self._texts.setAlignment(Qt.AlignmentFlag.AlignRight)
            self._title_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addLayout(self._texts)
            layout.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignTop)
        else:
            layout.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignTop)
            layout.addLayout(self._texts)
            layout.addStretch(1)

        self._sync_subtitle()
        self._apply_theme()

    # -- 内容 --------------------------------------------------------------

    def role(self) -> str:
        """获取头部所属消息角色。"""
        return self._role

    def setTitle(self, text: str) -> None:
        """设置名称 / 模型名。"""
        self._title = text or ""
        self._title_label.setText(self._title)

    def title(self) -> str:
        """获取名称 / 模型名。"""
        return self._title

    def setTimestamp(self, text: str) -> None:
        """设置时间文本。"""
        self._timestamp = text or ""
        self._sync_subtitle()

    def timestamp(self) -> str:
        """获取时间文本。"""
        return self._timestamp

    def setStatusText(self, text: str, kind: str = "") -> None:
        """设置状态文本与状态类型（排队中 / 生成中 / 已停止 / 出错）。"""
        self._status_text = text or ""
        self._status_kind = kind or ""
        self._sync_subtitle()
        self._apply_theme()

    def statusText(self) -> str:
        """获取状态文本。"""
        return self._status_text

    def statusKind(self) -> str:
        """获取状态类型（``ElaChatStatusType`` 取值，空表示无状态）。"""
        return self._status_kind

    def statusDot(self) -> _StatusDot:
        """获取状态点控件（测试 / 高级用法）。"""
        return self._status_dot

    def _sync_subtitle(self) -> None:
        has_time = bool(self._timestamp)
        has_status = bool(self._status_text)
        self._time_label.setText(self._timestamp)
        self._time_label.setVisible(has_time)
        self._sep_label.setVisible(has_time and has_status)
        self._status_label.setText(self._status_text)
        self._status_label.setVisible(has_status)
        self._status_dot.setVisible(has_status)
        self._status_dot.setActive(
            has_status
            and self._status_kind
            in (ElaChatStatusType.Streaming, ElaChatStatusType.Queued)
        )
        self._subtitle_row.setVisible(has_time or has_status)

    # -- 外观 --------------------------------------------------------------

    def avatar(self) -> _AvatarBadge:
        """获取头像控件。"""
        return self._avatar

    def setAvatarVisible(self, on: bool) -> None:
        """显示 / 隐藏头像。"""
        self._avatar.setVisible(bool(on) and self._role != ElaChatRoleType.System)

    def setAvatarIcon(self, iconName: ElaIconType.IconName) -> None:
        """设置头像图标（``ElaIconType`` 成员）。"""
        self._avatar.setIconName(iconName)

    def setAvatarImage(self, source: ElaChatAvatarSource) -> None:
        """设置自定义头像（SVG 数据 / 文件路径 / ``QPixmap`` 等）。

        ``None`` 清除自定义头像并回退到内置图标。
        """
        self._avatar.setImage(source)

    def avatarImage(self) -> Optional[QPixmap]:
        """获取自定义头像图（未设置返回 ``None``）。"""
        return self._avatar.image()

    def setAvatarShape(self, shape: str) -> None:
        """设置头像形状（``"circle"`` / ``"rounded"`` / ``"square"``）。"""
        self._avatar.setShape(shape)

    def avatarShape(self) -> str:
        """获取头像形状。"""
        return self._avatar.shape()

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _status_color(self) -> QColor:
        mode = self._theme_mode
        if self._status_kind == ElaChatStatusType.Error:
            return blend(
                text_color(mode), statusColor(mode, ElaStatusRoleType.Error), 0.55
            )
        if self._status_kind == ElaChatStatusType.Stopped:
            return blend(
                text_color(mode), statusColor(mode, ElaStatusRoleType.Warning), 0.5
            )
        return accent_color(mode)

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        muted = muted_color(mode, 0.5).name()
        # 标题不用 QSS：颜色即主题 BasicText（ElaText 默认色），字体按要求走 QFont。
        # 名称 / 模型名可能是中文：中文系统收成单族雅黑 —— 多族列表 + Segoe UI
        # 缺 CJK 字形在 Win7 上都是慢 shaping 路径且进程级毒化（见「下游项目反馈
        # bug.md」§3）；非中文系统保持「拉丁走 Segoe UI、中文逐字形回退雅黑」。
        title_font = QFont(self._title_label.font())
        cjk_family = system_cjk_font_family()
        title_font.setFamilies(
            [cjk_family]
            if cjk_family
            else ["Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei"]
        )
        title_font.setPixelSize(13)
        title_font.setWeight(QFont.Weight.DemiBold)
        self._title_label.setFont(title_font)
        self._time_label.setTextColor(muted)
        self._time_label.setFont(mono_font(11))
        self._sep_label.setTextColor(muted)
        self._sep_label.setTextPixelSize(11)
        self._status_label.setTextColor(self._status_color())
        self._status_label.setTextPixelSize(11)
        self._status_dot.setColor(self._status_color())
        self._avatar.setThemeMode(mode)


class MessageMeta(ElaThemeWidget):
    """消息底部 meta 标签：``名称 · 耗时``（无内容时自动隐藏）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = ""
        self._duration_ms = 0.0
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._label)
        self.hide()
        self._apply_theme()

    def setTitle(self, text: str) -> None:
        """设置名称 / 模型名。"""
        self._title = text or ""
        self._sync()

    def title(self) -> str:
        """获取名称 / 模型名。"""
        return self._title

    def setDuration(self, durationMs: float) -> None:
        """设置耗时（毫秒）。"""
        self._duration_ms = float(durationMs or 0.0)
        self._sync()

    def duration(self) -> float:
        """获取耗时（毫秒）。"""
        return self._duration_ms

    def _sync(self) -> None:
        parts = []
        if self._title:
            parts.append(self._title)
        duration = formatDuration(self._duration_ms)
        if duration:
            parts.append(f"耗时 {duration}")
        self._label.setText("  ·  ".join(parts))
        self.setVisible(bool(parts))

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        self._label.setTextColor(muted_color(self._theme_mode, 0.5))
        self._label.setTextPixelSize(11)


class _CollapsibleBlock(_ThemeAwareMixin, ElaScrollPageArea):
    """可折叠区块（``ElaScrollPageArea`` 圆角卡面 + ``ElaIconButton`` 箭头）。

    ``setSurfaceVisible(False)`` 可关闭卡面绘制（思考块等内联场景）。
    """

    #: 展开状态变化（参数：是否展开）
    toggled = pyqtSignal(bool)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        title: str = "",
        opened: bool = True,
        surface: bool = True,
    ) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        # ElaScrollPageArea 构造时 setFixedHeight(75)，卡片需按内容自适应
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setBorderRadius(8)
        self._title = title or ""
        self._surface = bool(surface)
        self._expandable = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(4)

        self._header = BareButton(self)
        self._header.setFlat(True)
        self._header.setCheckable(True)
        self._header.setChecked(bool(opened))
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_layout = QHBoxLayout(self._header)
        self._header_layout.setContentsMargins(0, 0, 0, 0)
        self._header_layout.setSpacing(6)
        self._chevron = ElaIconButton(
            ElaIconType.IconName.ChevronRight, 12, 16, 16, self
        )
        self._chevron.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chevron.setBorderRadius(4)
        self._title_label = ColorText(self)
        self._title_label.setWordWrap(False)
        # 折叠块标题含外部数据（工具名 / 审批 action）—— 一律纯文本渲染
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        #: 运行指示按需创建：历史消息里 99% 的折叠块从没运行过，构造期就建
        #: ``ElaProgressRing``（含两套 QPropertyAnimation）是纯浪费。
        self._busy: Optional[ElaProgressRing] = None
        self._busy_on = False
        self._header_layout.addWidget(self._chevron)
        self._header_layout.addWidget(self._title_label)
        self._header_layout.addStretch(1)

        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(22, 0, 0, 0)
        self._body_layout.setSpacing(4)
        self._body.setVisible(bool(opened))

        layout.addWidget(self._header)
        layout.addWidget(self._body)

        self._header.toggled.connect(self._on_toggled)
        self._sync_chevron()
        self._apply_theme()

    # -- 内容 --------------------------------------------------------------

    def setTitle(self, text: str) -> None:
        """设置标题文本。"""
        self._title = text or ""
        self._title_label.setText(self._title)

    def title(self) -> str:
        """获取标题文本。"""
        return self._title

    def setOpened(self, opened: bool) -> None:
        """展开 / 收起内容区（不可展开时忽略）。"""
        if not self._expandable and opened:
            return
        self._header.setChecked(bool(opened))

    def setOpenedSilently(self, opened: bool) -> None:
        """设置展开态但**不触发** toggled / 祖先布局链（恢复历史用）。

        恢复时每块都 ``setOpened(True)`` → ``setOpened(False)`` 会触发
        ``_relayoutAncestors``（最多 32 层）与 ``toggled`` 信号；几千个块累计
        上万次布局激活，纯属浪费。最终态由 ``setParts`` 收尾统一激活一次。
        """
        self._header.blockSignals(True)
        try:
            self._header.setChecked(bool(opened))
        finally:
            self._header.blockSignals(False)
        self._body.setVisible(bool(opened))
        self._sync_chevron()

    def isOpened(self) -> bool:
        """内容区是否展开。"""
        return self._header.isChecked()

    def setExpandable(self, on: bool) -> None:
        """设置是否允许展开（pending 工具锁定）。"""
        self._expandable = bool(on)
        self._chevron.setVisible(self._expandable)
        if not self._expandable:
            self._header.setChecked(False)
        self._header.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self._expandable
            else Qt.CursorShape.ArrowCursor
        )

    def isExpandable(self) -> bool:
        """是否允许展开。"""
        return self._expandable

    def setBusy(self, on: bool) -> None:
        """显示 / 隐藏运行中指示（``ElaProgressRing``）。

        关闭时必须 ``setIsBusying(False)``：``ElaProgressRing`` 的动画由
        ``IsBusying`` 驱动，仅隐藏控件会留下两个 QPropertyAnimation 永久
        空转（每个已完成的工具卡都会泄漏）。控件本身按需创建。
        """
        on = bool(on)
        self._busy_on = on
        if on:
            if self._busy is None:
                ring = ElaProgressRing(self)
                ring.setFixedSize(14, 14)
                ring.setIsTransparent(True)
                ring.setBusyingWidth(2)
                ring.hide()
                self._busy = ring
                self._header_layout.insertWidget(1, ring)
            self._busy.setIsBusying(True)
            self._busy.show()
            return
        if self._busy is not None:
            self._busy.setIsBusying(False)
            self._busy.hide()

    def isBusy(self) -> bool:
        """是否处于运行中状态（与父链可见性无关）。"""
        return self._busy_on

    def bodyLayout(self) -> QVBoxLayout:
        """获取内容区布局（向其添加自定义内容）。"""
        return self._body_layout

    def bodyWidget(self) -> QWidget:
        """获取内容区容器。"""
        return self._body

    def headerButton(self) -> QPushButton:
        """获取标题按钮句柄。"""
        return self._header

    def headerLayout(self) -> QHBoxLayout:
        """获取标题行布局（供子类插入图标 / 副标题 / 参数）。"""
        return self._header_layout

    def insertHeaderWidget(self, index: int, widget: QWidget) -> None:
        """在标题行指定位置插入控件。"""
        self._header_layout.insertWidget(index, widget)

    def setSurfaceVisible(self, on: bool) -> None:
        """显示 / 隐藏卡面背景。"""
        self._surface = bool(on)
        self.update()

    def surfaceVisible(self) -> bool:
        """卡面背景是否显示。"""
        return self._surface

    def setCardMargins(self, left: int, top: int, right: int, bottom: int) -> None:
        """调整卡片内边距（内联场景可收紧）。"""
        self.layout().setContentsMargins(left, top, right, bottom)

    def _on_toggled(self, checked: bool) -> None:
        if not self._expandable and checked:
            self._header.setChecked(False)
            return
        self._body.setVisible(bool(checked))
        self._sync_chevron()
        if self.layout() is not None:
            self.layout().activate()
        self.updateGeometry()
        self._relayoutAncestors()
        self.toggled.emit(bool(checked))

    def _relayoutAncestors(self) -> None:
        """同步刷新祖先布局链。

        Qt 的布局失效（``updateGeometry``）会逐级投递 ``LayoutRequest``，
        每层在独立的事件循环轮次里重排：展开 / 收起工具卡时表现为内容分
        2-3 帧逐级收缩，肉眼可见「抖动」。这里从自身向上依次激活布局，
        让整条链（卡片 → 工具面板 → 气泡 → 消息容器）在同一帧内完成重排。
        """
        widget = self
        for _ in range(32):  # 防御：避免异常父链导致死循环
            parent = widget.parentWidget()
            if parent is None:
                break
            layout = parent.layout()
            if layout is not None:
                layout.activate()
            widget = parent

    def _sync_chevron(self) -> None:
        icon = (
            ElaIconType.IconName.ChevronDown
            if self._header.isChecked()
            else ElaIconType.IconName.ChevronRight
        )
        self._chevron.setAwesome(icon)

    # -- 外观 --------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        if self._surface:
            super().paintEvent(event)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()

    def _apply_theme(self) -> None:
        self._title_label.setTextColor(text_color(self._theme_mode))
        self._title_label.setTextPixelSize(13)
        self._title_label.setTextWeight(QFont.Weight.DemiBold)


class ReasoningBlock(_CollapsibleBlock):
    """思考层：可折叠的推理文本，支持流式追加与耗时统计。"""

    def __init__(self, title: str = "思考中", parent: Optional[QWidget] = None) -> None:
        super().__init__(title=title, opened=False, parent=parent, surface=False)
        self.setCardMargins(0, 0, 0, 0)
        self._text = ""
        self._chunks: list = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush_chunks)
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.bodyLayout().addWidget(self._label)
        self._apply_theme()

    # -- 流式 --------------------------------------------------------------

    def begin(self) -> None:
        """进入思考状态（展开并显示「思考中」与运行指示）。"""
        self.setText("")
        self.setTitle("思考中")
        self.setBusy(True)
        self.setOpened(True)

    def end(self, durationMs: Optional[float] = None) -> None:
        """结束思考，标题显示耗时并自动收起。"""
        self._flush_chunks()
        self.setBusy(False)
        # 宿主可能传非数值（恢复历史时从 JSON 读到 "1.2s" 之类），
        # 直接做算术会抛 TypeError/ValueError；而本方法常在信号槽里被调用，
        # 异常穿出 Qt 回调就是 0xC0000409 静默 abort。
        try:
            millis = float(durationMs) if durationMs else 0.0
        except (TypeError, ValueError, OverflowError):
            millis = 0.0
        if millis > 0:
            self.setTitle(f"思考完成 ({millis / 1000:.1f}s)")
        else:
            self.setTitle("思考完成")
        self.setOpened(False)

    def finishSilently(self, durationMs: Optional[float] = None) -> None:
        """恢复历史时的收尾：直接落成「已完成 + 收起」，不触发 toggled / 布局链。"""
        self._flush_chunks()
        self.setBusy(False)
        try:
            millis = float(durationMs) if durationMs else 0.0
        except (TypeError, ValueError, OverflowError):
            millis = 0.0
        if millis > 0:
            self.setTitle(f"思考完成 ({millis / 1000:.1f}s)")
        else:
            self.setTitle("思考完成")
        self.setOpenedSilently(False)

    # -- 文本 --------------------------------------------------------------

    def text(self) -> str:
        """获取思考文本（含尚未刷新的分片）。"""
        self._flush_chunks()
        return self._text

    def setText(self, text: str) -> None:
        """整体替换思考文本。"""
        self._flush_timer.stop()
        self._chunks.clear()
        self._text = text or ""
        # 折叠态不把全文塞进 word-wrap 标签：QLabel 的首次 sizeHint /
        # heightForWidth 要整段折行（51KB 实测 12~45ms/次），958 个历史思考块
        # 全量物化就是秒级纯浪费（bug #17）。展开时再灌。
        if self.isOpened():
            self._sync_label_text()

    def appendText(self, chunk: str) -> None:
        """追加思考文本（流式；标签刷新按事件循环轮次合并）。"""
        if not chunk:
            return
        self._chunks.append(chunk)
        if not self._flush_timer.isActive():
            self._flush_timer.start(REASONING_FLUSH_INTERVAL_MS)

    def _flush_chunks(self) -> None:
        """把缓冲分片并入文本并刷新标签（定时器 / 读取前调用）。"""
        if not self._chunks or is_deleted(self):
            return
        self._text += "".join(self._chunks)
        self._chunks.clear()
        if self.isOpened():
            self._sync_label_text()

    def _sync_label_text(self) -> None:
        """把当前文本灌进标签（文本没变时不动，保住 ColorText 尺寸缓存）。"""
        text = self._displayText()
        if self._label.text() != text:
            self._label.setText(text)

    def _on_toggled(self, checked: bool) -> None:
        # 先把全文灌进标签再交给基类：基类会触发祖先布局激活，空标签先量一遍
        # 会把同一 (类别, 宽度) 算两次（ColorText 缓存按文本分键）。
        if checked and getattr(self, "_label", None) is not None:
            self._flush_chunks()
            self._sync_label_text()
        super()._on_toggled(checked)

    def setOpenedSilently(self, opened: bool) -> None:
        if opened and getattr(self, "_label", None) is not None:
            self._flush_chunks()
            self._sync_label_text()
        super().setOpenedSilently(opened)

    def _displayText(self) -> str:
        """喂给标签的文本：裁掉尾部空白（``self._text`` 保持原样）。

        模型常以若干换行收尾一段思考，而这是 PlainText 标签 —— 不像内联形态走
        Markdown 导入器（导入器本来就丢尾部空行），每个换行都真的画一行。
        只裁显示不裁数据：``text()`` / ``part.text`` / journal / 导出全部保真。
        """
        return self._text.rstrip()

    def label(self) -> ElaText:
        """获取内部文本标签（高级用法）。"""
        return self._label

    def _apply_theme(self) -> None:
        super()._apply_theme()
        label = getattr(self, "_label", None)
        if label is not None:
            label.setTextColor(muted_color(self._theme_mode, 0.55))
            label.setTextPixelSize(12)


class ThinkingRow(ElaThemeWidget):
    """思考行：``ElaProgressRing`` + 「思考中」+ 从推理抽取的标题。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._heading = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._ring = ElaProgressRing(self)
        self._ring.setFixedSize(14, 14)
        self._ring.setIsTransparent(True)
        self._ring.setBusyingWidth(2)
        self._ring.setIsBusying(True)
        self._label = ColorText("思考中", self)
        self._label.setWordWrap(False)
        self._heading_label = ColorText(self)
        self._heading_label.setWordWrap(False)
        # 标题来自 extractReasoningHeading（模型推理文本），必须按纯文本渲染
        self._heading_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._ring)
        layout.addWidget(self._label)
        layout.addWidget(self._heading_label, 1)
        self.hide()
        self._apply_theme()

    def begin(self) -> None:
        """进入思考状态（显示并清空标题）。"""
        self.setHeading("")
        self._ring.setIsBusying(True)
        self.show()

    def end(self) -> None:
        """结束思考（隐藏）。"""
        self._ring.setIsBusying(False)
        self.hide()

    def setHeading(self, text: str) -> None:
        """设置标题（长文本截断）。"""
        self._heading = text or ""
        display = self._heading
        if len(display) > 60:
            display = display[:59] + "…"
        self._heading_label.setText(display)

    def heading(self) -> str:
        """获取标题。"""
        return self._heading

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        self._label.setTextColor(muted_color(mode, 0.65))
        self._label.setTextPixelSize(12)
        self._heading_label.setTextColor(muted_color(mode, 0.45))
        self._heading_label.setTextPixelSize(12)


class ToolCallCard(_CollapsibleBlock):
    """工具层单卡片（对齐 opencode 语义）。

    - 默认折叠（由 :func:`toolDefaultOpen` 决定，宿主可经
      :meth:`ElaChatBubble.setToolDefaultOpen` 注入自己的策略）；
      ``Pending`` 状态锁定不可展开（shell / 显式放开除外）；
    - 标题为工具名，``Running`` 时以 ``ElaProgressRing`` 指示；
    - 副标题 / 参数摘要从调用参数提取（前 3 个 ``key=value``，**与副标题
      重复的那个键会被排除**）；
    - **运行中不显示参数摘要**（参数分片流式到达，半截参数既误导又引起
      整行宽度跳变），完成后再出现；
    - 内容区首次展开时才构建（defer）；
    - ``setResult(ok=False)`` 切换为错误卡样式（左 danger 竖线 + Ban 图标）。
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        tool_call: Optional[ElaChatToolCall] = None,
        name: str = "",
        arguments: str = "",
        toolCallId: str = "",
        allowOpenWhilePending: bool = False,
        defaultOpen: Optional[bool] = None,
    ) -> None:
        call = tool_call or ElaChatToolCall(
            id=toolCallId, name=name, arguments=arguments
        )
        opened = (
            bool(defaultOpen)
            if defaultOpen is not None
            else toolDefaultOpen(call.name, call.arguments)
        )
        super().__init__(title=f"工具调用：{call.name}", opened=opened, parent=parent)
        self._call = call
        self._allow_open_while_pending = bool(allowOpenWhilePending)
        self._body_built = False
        self._args_caption: Optional[ElaText] = None
        self._args_label: Optional[ElaText] = None
        self._result_caption: Optional[ElaText] = None
        self._result_label: Optional[ElaText] = None
        #: 所属消息 id（供渲染器上下文用，0 表示独立使用本卡）
        self._message_id = 0
        #: 宿主注册的渲染器（``None`` = 未注册，走默认纯文本 body）
        self._renderer = toolRenderer(call.name)
        #: **必须持有的 Python 引用**（见 :mod:`pyqt6_ela_pro.chat.renderers`
        #: 的「生命周期与线程约束」第 1 条：布局只转移 C++ 所有权，Python
        #: 包装器被 GC 后调用其方法就是解引用已释放内存 = 无 traceback 崩溃）
        self._renderer_widget = None
        self._renderer_body_holder: Optional[QWidget] = None

        self._icon = ElaIconButton(toolIconName(call.name), 14, 18, 18, self)
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._icon.setBorderRadius(4)
        # 记下默认图标色：Error -> Done 时 Q_PROPERTY 不会自动还原，得手动写回
        # （否则命令执行成功、图标还是失败红）。
        self._default_icon_light = self._icon.getLightIconColor()
        self._default_icon_dark = self._icon.getDarkIconColor()
        self.insertHeaderWidget(0, self._icon)
        self._subtitle_label = ColorText(self)
        self._subtitle_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._subtitle_label.setWordWrap(False)
        self._subtitle_label.setMinimumWidth(0)
        self._args_label = ColorText(self)
        self._args_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._args_label.setWordWrap(False)
        self._args_label.setMinimumWidth(0)
        # 这三个标签显示的是**模型给的内容**（工具名 / 副标题 / 参数摘要），
        # ElaText 默认 Qt::AutoText，会走 QTextDocument 的 HTML 分支：
        # 名字里带 "<" 或 "&" 会被当标签/实体吃掉（"a < b" 渲染成 "a "，
        # "Tom & Jerry" 渲染成 "Tom "），工具名还能注入任意富文本。
        # 与下面正文区 (_build_body) 的处理保持一致。
        for label in (self._title_label, self._subtitle_label, self._args_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.setMinimumWidth(0)
        self._title_text = f"工具调用：{call.name}"
        self._subtitle_text = ""
        self._args_text = ""
        #: ``(cap, len, hash, font)`` → 省略结果；resize / 主题切换会反复问
        self._elide_cache: dict = {}
        insert_at = self.headerLayout().count() - 1
        self.insertHeaderWidget(insert_at, self._subtitle_label)
        self.insertHeaderWidget(insert_at + 1, self._args_label)
        self._sync_header()
        self._apply_theme()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        # 初始展开（defaultOpen / 宿主策略）的卡：super().__init__ 先 setChecked
        # 后连 toggled，初始展开不会再触发 _on_toggled —— 首次显示时补建正文，
        # 否则箭头朝下却一块空白，要手动收再展开。
        super().showEvent(event)
        if self.isOpened() and not self._body_built:
            self._build_body()

    # -- 数据 --------------------------------------------------------------

    def toolCall(self, callId: Optional[str] = None) -> ElaChatToolCall:
        """获取当前工具调用快照（``callId`` 供容器统一路由，卡内忽略）。"""
        return self._call

    def toolCallId(self) -> str:
        """获取工具调用 id。"""
        return self._call.id

    def toolName(self) -> str:
        """获取工具名称。"""
        return self._call.name

    def setMessageId(self, messageId: int) -> None:
        """设置所属消息 id（供渲染器上下文用，建卡后可补设）。

        初始展开的卡在**拿到消息 id 之后**才建正文：渲染器上下文需要它，
        构造期抢跑的话快照里的 ``messageId`` 永远是 0。
        """
        self._message_id = int(messageId or 0)
        if self.isOpened() and not self._body_built:
            self._build_body()

    def setArguments(self, arguments: str) -> None:
        """设置调用参数文本。"""
        self._call = self._call.withArguments(arguments)
        self._sync_header()
        if self._body_built:
            self._sync_body()

    def arguments(self) -> str:
        """获取调用参数文本。"""
        return self._call.arguments

    def setResult(self, result: str, ok: bool = True) -> None:
        """设置调用结果与状态（``ok=False`` 标记失败）。"""
        status = ElaChatToolStatusType.Done if ok else ElaChatToolStatusType.Error
        self._call = self._call.withResult(result, status)
        self._sync_header()
        if status == ElaChatToolStatusType.Error:
            self.setOpened(True)
        if self._body_built:
            self._sync_body()

    def result(self) -> str:
        """获取调用结果文本。"""
        return self._call.result

    def setStatus(self, status: str) -> None:
        """设置调用状态（见 :class:`ElaChatToolStatusType`）。"""
        self._call = ElaChatToolCall(
            id=self._call.id,
            name=self._call.name,
            arguments=self._call.arguments,
            result=self._call.result,
            status=status,
        )
        self._sync_header()
        # 状态变化也要通知渲染器：展开状态下「运行中 -> 完成」不带着新状态，
        # 渲染器（diff / 进度 / 成功态）就永远停在运行态。原实现漏了这一步。
        if self._body_built:
            self._sync_body()

    def status(self) -> str:
        """获取调用状态。"""
        return self._call.status

    def setAllowOpenWhilePending(self, on: bool) -> None:
        """设置 pending 状态下是否允许展开（shell 类工具）。"""
        self._allow_open_while_pending = bool(on)
        self._sync_header()

    def updateResult(self, callId: str, result: str, ok: bool = True) -> None:
        """统一结果更新入口（``callId`` 由容器路由，卡内忽略）。"""
        self.setResult(result, ok=ok)

    # -- 展开与内容 --------------------------------------------------------

    def _on_toggled(self, checked: bool) -> None:
        if not checked or not self._expandable:
            # 不可展开（pending 锁定）：直接交给基类收回，**不能建 body** ——
            # 一次本该是 no-op 的点击会把渲染器工厂提前跑掉并永久钉住快照
            super()._on_toggled(checked)
            return
        if not self._body_built:
            self._build_body()
        super()._on_toggled(checked)

    def _build_body(self) -> None:
        """首次展开时才构建内容区（defer）。

        宿主注册了渲染器（:mod:`pyqt6_ela_pro.chat.renderers`）就只建它的控件，
        否则走默认的「参数 / 结果」纯文本。
        """
        self._body_built = True
        if self._build_renderer_body():
            self.updateGeometry()
            if self.layout() is not None:
                self.layout().activate()
            return
        self._args_caption = ColorText("参数", self)
        self._args_value = ColorText(self)
        self._result_caption = ColorText("结果", self)
        self._result_value = ColorText(self)
        for label in (self._args_value, self._result_value):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.bodyLayout().addWidget(self._args_caption)
        self.bodyLayout().addWidget(self._args_value)
        self.bodyLayout().addWidget(self._result_caption)
        self.bodyLayout().addWidget(self._result_value)
        self._sync_body()
        self._apply_theme()
        self.updateGeometry()
        if self.layout() is not None:
            self.layout().activate()

    def _renderer_context(self) -> ToolRenderContext:
        """建渲染器上下文快照（不可变，不持控件引用 → 无悬垂风险）。"""
        call = self._call
        return ToolRenderContext(
            messageId=self._message_id,
            toolCallId=call.id,
            name=call.name,
            arguments=call.arguments or "",
            result=call.result or "",
            status=call.status,
            isError=call.status == ElaChatToolStatusType.Error,
            allowOpenWhilePending=self._allow_open_while_pending,
        )

    def _build_renderer_body(self) -> bool:
        """尝试用宿主注册的渲染器填充内容区；返回是否接管成功。

        任何异常都落回默认纯文本 body：工厂跑在「用户点开卡片」的 Qt 回调
        链里，宿主渲染器的一个 bug 若冒出去就是 0xC0000409 静默终止整个进程
        （无 traceback）。渲染器是**增强**不是**可选功能**，不该有能力让聊天
        窗口消失。
        """
        factory = self._renderer
        if factory is None:
            return False
        try:
            widget = factory(self._renderer_context())
        except Exception:
            return False
        if widget is None:
            return False
        try:
            self._renderer_widget = widget  # 先持 Python 引用
            holder = QWidget(self)
            layout = QVBoxLayout(holder)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(widget)
            self._renderer_body_holder = holder
            self.bodyLayout().addWidget(holder)
        except Exception:
            self._renderer_widget = None
            self._renderer_body_holder = None
            return False
        return True

    def _notify_renderer(self) -> None:
        """把结果 / 状态推给渲染器（widget 无该方法则跳过）。

        三重守卫缺一不可：``self`` 可能在结果回调之后已被 ``removeMessage``
        销毁（Qt 回调里访问已删除控件抛 ``RuntimeError`` 同样是 abort），
        widget 由宿主构造、也可能已被自行 ``deleteLater``。
        """
        widget = self._renderer_widget
        if widget is None:
            return
        if is_deleted(self) or is_deleted(widget):
            return
        update = getattr(widget, "updateToolResult", None)
        if not callable(update):
            return
        try:
            update(self._call.result or "", self._call.status)
        except Exception:
            pass

    def _sync_body(self) -> None:
        self._notify_renderer()
        if self._args_caption is None:
            return
        self._args_value.setText(self._call.arguments or "—")
        self._result_value.setText(self._call.result or "—")
        self._args_caption.setVisible(bool(self._call.arguments))
        self._args_value.setVisible(bool(self._call.arguments))

    def _sync_header(self) -> None:
        call = self._call
        running = call.status in (
            ElaChatToolStatusType.Pending,
            ElaChatToolStatusType.Running,
        )
        self._icon.setAwesome(toolIconName(call.name))
        self._title_text = f"工具调用：{call.name}"
        self.setTitle(self._title_text)
        # 宿主注册了 subtitle 就用它（渲染器最清楚该显示什么），否则走通用
        # 键名启发式。两者都返回 (键, 值)，键传给 toolArgumentPairs 做去重 ——
        # 见 renderers 模块的「subtitle 契约」。
        _subtitle_key, self._subtitle_text = toolRendererSubtitle(
            call.name, call.arguments
        )
        if not self._subtitle_text:
            _subtitle_key, self._subtitle_text = toolSubtitleParts(call.arguments)
        self._subtitle_label.setVisible(bool(self._subtitle_text))
        self._args_text = "  ".join(
            toolArgumentPairs(call.arguments, excludeKey=_subtitle_key)
        )
        # 运行中**不显示**参数摘要：参数是分片流式到达的（同一 toolCallId
        # 重复上报会更新 arguments），显示半截参数既误导（看着像完整调用）
        # 又会因为撞上省略预算而让整行宽度反复跳变。完成后再一次性出现。
        self._args_label.setVisible(bool(self._args_text) and not running)
        # 先套主题（等宽字体生效）再省略，保证按 mono 宽度截断
        self._apply_theme()
        self._elide_header_texts()

        self.setBusy(running)
        pending = call.status == ElaChatToolStatusType.Pending
        self.setExpandable(not pending or self._allow_open_while_pending)

    def _elide_header_texts(self) -> None:
        """按卡片宽度省略标题 / 副标题 / 参数摘要。

        ``ElaText`` 默认开启 ``wordWrap``，头部空间不足时多行文本会叠在
        固定高度的标题行里（视觉上互相重叠）。这里按宽度分配配额并省略，
        保证三者始终单行且不重叠。
        """
        width = self.width() or self._header.width()
        if width <= 0:
            return
        avail = max(140, width - 96)  # 省略箭头 / 图标 / 进度环与间距
        title_cap = int(avail * 0.52)
        subtitle_cap = int(avail * 0.20)
        args_cap = max(60, avail - title_cap - subtitle_cap)
        for label, text, cap in (
            (self._title_label, self._title_text, title_cap),
            (self._subtitle_label, self._subtitle_text, subtitle_cap),
            (self._args_label, self._args_text, args_cap),
        ):
            if not text:
                label.setText("")
                continue
            # 先截源再测量：elidedText 的展示结果由 cap 决定，源串再长也不会
            # 多显示一个字符；而 Win7 上 4KB 串的逐字形测量很贵（bug #17）。
            source = (
                text if len(text) <= _ELIDE_SOURCE_MAX else text[:_ELIDE_SOURCE_MAX]
            )
            key = (cap, len(source), hash(source), label.font().toString())
            elided = self._elide_cache.get(key)
            if elided is None:
                elided = label.fontMetrics().elidedText(
                    source, Qt.TextElideMode.ElideRight, max(0, cap)
                )
                if len(self._elide_cache) >= 12:
                    self._elide_cache.clear()
                self._elide_cache[key] = elided
            if label.text() != elided:
                label.setText(elided)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._elide_header_texts()

    def _apply_theme(self) -> None:
        super()._apply_theme()
        if not hasattr(self, "_subtitle_label"):
            return
        mode = self._theme_mode
        is_error = self._call.status == ElaChatToolStatusType.Error
        danger = statusColor(mode, ElaStatusRoleType.Error)
        title_color = (
            blend(text_color(mode), danger, 0.45) if is_error else text_color(mode)
        )
        self._title_label.setTextColor(title_color)
        self._title_label.setTextPixelSize(13)
        self._title_label.setTextWeight(QFont.Weight.DemiBold)
        self._subtitle_label.setTextColor(muted_color(mode, 0.6))
        self._subtitle_label.setTextPixelSize(12)
        self._args_label.setTextColor(muted_color(mode, 0.45))
        self._args_label.setTextPixelSize(11)
        for caption in (
            getattr(self, "_args_caption", None),
            getattr(self, "_result_caption", None),
        ):
            if caption is not None:
                caption.setTextColor(muted_color(mode, 0.5))
                caption.setTextPixelSize(11)
        for value in (
            getattr(self, "_args_value", None),
            getattr(self, "_result_value", None),
        ):
            if value is not None:
                value.setTextColor(muted_color(mode, 0.75))
                value.setTextPixelSize(12)
        if is_error:
            self._icon.setAwesome(ElaIconType.IconName.Ban)
            self._icon.setLightIconColor(danger)
            self._icon.setDarkIconColor(danger)
        else:
            # Error -> Done 的重复上报要把图标字形与颜色**一起**还原，
            # 否则命令明明成功了、图标还是失败红。
            self._icon.setAwesome(toolIconName(self._call.name))
            self._icon.setLightIconColor(self._default_icon_light)
            self._icon.setDarkIconColor(self._default_icon_dark)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().paintEvent(event)
        if self._call.status != ElaChatToolStatusType.Error:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(statusColor(self._theme_mode, ElaStatusRoleType.Error))
        painter.drawRoundedRect(0, 6, 3, max(0, self.height() - 12), 1.5, 1.5)
        painter.end()


class ContextToolGroupCard(_CollapsibleBlock):
    """上下文工具分组卡：连续 read/glob/grep/list 合并为一张卡。"""

    def __init__(
        self, parent: Optional[QWidget] = None, defaultOpen: bool = False
    ) -> None:
        super().__init__(title="正在探索", opened=defaultOpen, parent=parent)
        self._calls: list[ElaChatToolCall] = []
        self._call_rows: dict = {}
        self._counts = {"read": 0, "glob": 0, "grep": 0, "list": 0}
        self._rows_container = QWidget(self)
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)
        self.bodyLayout().addWidget(self._rows_container)
        self._summary_label = ColorText(self)
        self._summary_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._summary_label.setWordWrap(False)
        self.insertHeaderWidget(self.headerLayout().count() - 1, self._summary_label)
        self._sync_header()
        self._apply_theme()

    # -- 数据 --------------------------------------------------------------

    def addToolCall(self, call: ElaChatToolCall) -> None:
        """追加上下文工具调用。"""
        self._calls.append(call)
        key = (call.name or "").lower()
        if key in self._counts:
            self._counts[key] += 1
        row = ColorText(self._rows_container)
        row.setTextFormat(Qt.TextFormat.PlainText)
        self._rows_layout.addWidget(row)
        self._call_rows[call.id] = row
        self._sync_row(call)
        self._sync_header()
        self._apply_theme()

    def toolCall(self, callId: str) -> Optional[ElaChatToolCall]:
        """按 id 获取包含的工具调用快照。"""
        for call in self._calls:
            if call.id == callId:
                return call
        return None

    def updateResult(self, callId: str, result: str, ok: bool = True) -> None:
        """按 id 更新某个工具调用的结果与状态。"""
        status = ElaChatToolStatusType.Done if ok else ElaChatToolStatusType.Error
        for index, call in enumerate(self._calls):
            if call.id == callId:
                updated = call.withResult(result, status)
                self._calls[index] = updated
                self._sync_row(updated)
                self._sync_header()
                return

    def updateArguments(self, callId: str, arguments: str) -> None:
        """按 id 更新某个工具调用的参数（重复上报时幂等更新）。"""
        for index, call in enumerate(self._calls):
            if call.id == callId:
                updated = call.withArguments(arguments)
                self._calls[index] = updated
                self._sync_row(updated)
                self._sync_header()
                return

    def _sync_row(self, call: ElaChatToolCall) -> None:
        row = self._call_rows.get(call.id)
        if row is None:
            return
        # 与 ToolCallCard._sync_header 同一套：先算副标题键，再据此排除参数，
        # 否则同一行会出现「a.py  path=a.py」（两条回归用例各守一半）
        subtitle_key, subtitle = toolRendererSubtitle(call.name, call.arguments)
        if not subtitle:
            subtitle_key, subtitle = toolSubtitleParts(call.arguments)
        pairs = "  ".join(
            toolArgumentPairs(call.arguments, limit=2, excludeKey=subtitle_key)
        )
        text = f"{call.name}  {subtitle}"
        if pairs:
            text += f"  {pairs}"
        if call.status == ElaChatToolStatusType.Error:
            text += "  · 失败"
        elif call.status == ElaChatToolStatusType.Aborted:
            text += "  · 已中止"
        if len(text) > 72:
            text = text[:71] + "…"
        row.setText(text)

    def finish(self) -> None:
        """全部完成（标题切「已探索」，隐藏忙碌环）。"""
        self.setTitle("已探索")
        self.setBusy(False)

    def toolCalls(self) -> list:
        """获取包含的工具调用快照。"""
        return list(self._calls)

    def count(self) -> int:
        """工具调用条数。"""
        return len(self._calls)

    def summary(self) -> str:
        """计数摘要文本（如 ``2 个文件 · 1 次搜索``）。"""
        parts = []
        if self._counts["read"]:
            parts.append(f"{self._counts['read']} 个文件")
        if self._counts["glob"]:
            parts.append(f"{self._counts['glob']} 次查找")
        if self._counts["grep"]:
            parts.append(f"{self._counts['grep']} 次搜索")
        if self._counts["list"]:
            parts.append(f"{self._counts['list']} 次列目录")
        return " · ".join(parts)

    def _sync_header(self) -> None:
        self._summary_label.setText(self.summary())
        self._summary_label.setVisible(bool(self.summary()))
        running = any(
            call.status
            in (ElaChatToolStatusType.Pending, ElaChatToolStatusType.Running)
            for call in self._calls
        )
        self.setBusy(running)
        if running:
            self.setTitle("正在探索")

    def _apply_theme(self) -> None:
        super()._apply_theme()
        if not hasattr(self, "_summary_label"):
            return
        self._summary_label.setTextColor(muted_color(self._theme_mode, 0.5))
        self._summary_label.setTextPixelSize(12)
        for row in self._call_rows.values():
            row.setTextColor(muted_color(self._theme_mode, 0.7))
            row.setTextPixelSize(12)


class ToolGroupPanel(_CollapsibleBlock):
    """工具调用外层折叠面板（对齐 agent_chat 的「工具调用 (N)」层级）。

    - 与思考折叠块**完全一致**的内联样式：无卡片底色（内层工具卡自带卡面），
      标题同为纯文本色（**不叠强调色**，见 :meth:`_apply_theme` 的说明），
      两者只靠「>」箭头与文案区分；
    - 标题：运行中 ``工具调用 (已完成/总数)``，全部结束 ``工具调用 (总数)``；
    - 运行指示：``ElaProgressRing``（继承自 :class:`_CollapsibleBlock`）；
    - 内容区承载 :class:`ToolCallCard` / :class:`ContextToolGroupCard`。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            title="工具调用 (0)", opened=False, parent=parent, surface=False
        )
        self.setCardMargins(0, 0, 0, 0)
        self._counts = (0, 0)
        self._running = False
        self._summary = ""
        self._summary_key = None
        self._title_key = None
        self._body_container = QWidget(self)
        self._tool_layout = QVBoxLayout(self._body_container)
        self._tool_layout.setContentsMargins(0, 0, 0, 0)
        self._tool_layout.setSpacing(2)
        self.bodyLayout().addWidget(self._body_container)
        # 标题 + 浅灰摘要共用一个 QLabel：富文本片段只用于颜色，外部文本全部转义。
        # 不额外建控件（历史会话满量物化时 1000+ 面板，每个多一个 label 都是净开销）。
        self._title_label.setTextFormat(Qt.TextFormat.RichText)
        self.hide()

    # -- 内容 --------------------------------------------------------------

    def toolLayout(self) -> QVBoxLayout:
        """获取工具卡片布局（向其添加卡片）。"""
        return self._tool_layout

    def toolContainer(self) -> QWidget:
        """获取工具卡片容器。"""
        return self._body_container

    def setCounts(
        self,
        done: int,
        total: int,
        running: Optional[bool] = None,
        summary: Optional[str] = None,
    ) -> None:
        """更新标题计数与折叠摘要（``running`` 为空时按 ``done < total`` 推断）。"""
        done = max(0, int(done))
        total = max(0, int(total))
        if running is None:
            running = done < total
        self._counts = (done, total)
        self._running = bool(running)
        if summary is not None:
            self._summary = str(summary or "")
        self._sync_title()

    def setSummary(self, summary: str) -> None:
        """设置折叠态的一行工具摘要（``shell · git status``）。"""
        self._summary = str(summary or "")
        self._sync_title()

    def counts(self) -> tuple:
        """获取 ``(已完成, 总数)``。"""
        return self._counts

    def isRunning(self) -> bool:
        """是否有工具仍在运行。"""
        return self._running

    def summary(self) -> str:
        """获取折叠态摘要文本（不含标题前缀）。"""
        return self._summary

    def _sync_title(self) -> None:
        done, total = getattr(self, "_counts", (0, 0))
        summary = " ".join(str(getattr(self, "_summary", "") or "").split())
        running = getattr(self, "_running", False)
        if running:
            base = f"工具调用 ({done}/{total})"
        else:
            base = f"工具调用 ({total})"
        self._title = base
        key = (self.width(), base, summary, self._theme_mode)
        if key == getattr(self, "_title_key", None):
            self.setBusy(running)
            return
        self._title_key = key
        if not summary:
            text = html.escape(base)
            tip = ""
        else:
            title_width = self._title_label.fontMetrics().horizontalAdvance(base)
            available = max(60, self.width() - title_width - 70)
            elided = self._title_label.fontMetrics().elidedText(
                summary, Qt.TextElideMode.ElideRight, available
            )
            color = muted_color(self._theme_mode, 0.6).name()
            text = (
                f"{html.escape(base)} "
                f'<span style="color:{color}">{html.escape(elided)}</span>'
            )
            tip = summary if elided != summary else ""
        if self._title_label.text() != text:
            self._title_label.setText(text)
        if self._title_label.toolTip() != tip:
            self._title_label.setToolTip(tip)
        self.setBusy(running)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._sync_title()

    def _apply_theme(self) -> None:
        super()._apply_theme()
        mode = self._theme_mode
        # 与思考块**同为纯文本色** —— 两者靠「>」箭头与文案本身区分，不靠颜色。
        # 曾经给工具面板标题叠了一层强调色（blend(text, accent, 0.35)），意图是
        # 「与思考块稍作区分」，实际两头不讨好：0.35 在深色主题下算出 #c1eaff，
        # 极淡的青在近黑底上 13px 小字里读不出着色过（浅色主题下却是明显的
        # #002443，所以只有深色才暴露），于是同一层级里出现两种几乎一样的
        # 亮色，视觉上更含混。回归测试 tests/ela_chat/test_chat_tool_theme.py
        # 钉住「工具面板标题 == 思考行标题 == 纯文本色」。
        self._title_label.setTextColor(text_color(mode))
        self._title_label.setTextPixelSize(13)
        self._title_label.setTextWeight(QFont.Weight.DemiBold)
        self._sync_title()


class _ImageAttachmentCard(QWidget):
    """图片附件缩略卡（``ElaIconButton`` 缩略图 + 右上角关闭按钮）。"""

    clicked = pyqtSignal()
    removed = pyqtSignal()

    def __init__(
        self,
        pixmap: QPixmap,
        tooltip: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        width, height = _IMAGE_THUMB_SIZE
        self.setFixedSize(width, height)
        thumb = pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._button = ElaIconButton(thumb, self)
        self._button.setFixedSize(width, height)
        self._button.setBorderRadius(6)
        self._button.setToolTip(tooltip)
        set_tooltip(self._button, tooltip, ElaToolTipPositionType.Top)
        self._button.clicked.connect(self.clicked)
        self._close = ElaIconButton(ElaIconType.IconName.CircleXmark, 11, 16, 16, self)
        self._close.setBorderRadius(8)
        self._close.setToolTip("移除附件")
        set_tooltip(self._close, "移除附件", ElaToolTipPositionType.Top)
        self._close.clicked.connect(self.removed)
        self._close.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._close.move(self.width() - self._close.width() + 4, -4)


class AttachmentStrip(ElaThemeWidget):
    """附件层：``ElaChip``（文件）+ 图片缩略卡，``ElaFlowLayout`` 自动换行。

    - 点击通知宿主，× / 关闭按钮移除；
    - ``setAlignment(AlignRight)`` 时自动收缩宽度并靠右（用户消息）；
    - 粘贴图片的图像挂在附件的 ``image`` 字段上（运行时，**不序列化**），
      以 ``digest`` 去重。
    """

    #: 附件被点击（参数：文件路径，可能为空）
    attachmentClicked = pyqtSignal(str)
    #: 附件被移除（参数：文件路径）
    attachmentRemoved = pyqtSignal(str)
    #: 附件列表变化（参数：``ElaChatAttachment`` 列表）
    changed = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._attachments: list[ElaChatAttachment] = []
        self._cards: list = []
        self._alignment = Qt.AlignmentFlag.AlignLeft
        self._layout = ElaFlowLayout(self, 0, 6, 6)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        #: 布局后补量一次（同一时刻只留一个待触发）
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(0)
        self._sync_timer.timeout.connect(self.syncWidth)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        # 隐藏期间加的附件可能在首次布局前算出了 1px 高度；显示后再量一次。
        self._schedule_sync()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        # 首次布局会先给一个 1px 高；等拿到真实宽度后再量一次（hfw 首轮可能是 0）。
        self._schedule_sync()

    # -- 数据 --------------------------------------------------------------

    def attachments(self) -> list:
        """附件快照列表（``ElaChatAttachment``）。"""
        return list(self._attachments)

    def count(self) -> int:
        """附件数量。"""
        return len(self._attachments)

    def isEmpty(self) -> bool:
        """是否没有附件。"""
        return not self._attachments

    def setAttachments(self, attachments) -> None:
        """整体替换附件列表（接受 ``ElaChatAttachment`` 或字典）。"""
        normalized = [self._normalize(item) for item in (attachments or [])]
        self._rebuild(normalized)
        self.changed.emit(self.attachments())
        self._schedule_sync()

    def addAttachment(
        self, name: str, path: str = "", size: int = 0
    ) -> ElaChatAttachment:
        """追加一个附件并返回快照（同路径自动去重）。"""
        attachment = ElaChatAttachment(name=name, path=path, size=_as_int(size))
        if path and any(item.path == path for item in self._attachments):
            return attachment
        self._append(attachment)
        self.changed.emit(self.attachments())
        self._schedule_sync()
        return attachment

    def addPastedImage(
        self,
        image: QImage,
        name: str = "粘贴的图片.png",
        digest: str = "",
    ) -> Optional[ElaChatAttachment]:
        """追加剪贴板图片附件（以 digest 去重），返回快照。

        图像挂在附件的 ``image`` 字段上（**不序列化**）：附件对象在输入区与
        消息之间流转，撤回回填 / 消息气泡都据此渲染缩略图。
        """
        if digest and any(item.digest == digest for item in self._attachments):
            return None
        attachment = ElaChatAttachment(
            name=name,
            path="",
            size=0,
            digest=digest,
            mime="image/png",
            image=image,
        )
        self._append(attachment)
        self.changed.emit(self.attachments())
        self._schedule_sync()
        return attachment

    def addAttachments(self, attachments) -> list:
        """批量追加附件（只发一次 ``changed``），返回新增快照列表。"""
        added = []
        for item in attachments or []:
            attachment = self._normalize(item)
            if attachment.path and any(
                existing.path == attachment.path for existing in self._attachments
            ):
                continue
            self._append(attachment)
            added.append(attachment)
        if added:
            self.changed.emit(self.attachments())
            self._schedule_sync()
        return added

    def removeAttachment(self, index: int) -> None:
        """按下标移除附件。"""
        if not 0 <= index < len(self._attachments):
            return
        attachment = self._attachments[index]
        self._remove_at(index)
        self.attachmentRemoved.emit(attachment.path or attachment.name)
        self.changed.emit(self.attachments())

    def removePath(self, path: str) -> None:
        """按路径移除附件。"""
        for index, attachment in enumerate(self._attachments):
            if attachment.path == path:
                self.removeAttachment(index)
                return

    def clear(self) -> None:
        """清空附件。"""
        if not self._attachments:
            return
        for card in self._cards:
            self._drop_card(card)
        self._attachments.clear()
        self._cards.clear()
        self.setVisible(False)
        self.changed.emit([])

    # -- 对齐与宽度 --------------------------------------------------------

    def setAlignment(self, alignment: Qt.AlignmentFlag) -> None:
        """设置 chips 行内对齐（用户消息常用 ``AlignRight``）。"""
        self._alignment = alignment
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(
            QSizePolicy.Policy.Fixed
            if alignment & Qt.AlignmentFlag.AlignRight
            else QSizePolicy.Policy.Expanding
        )
        self.setSizePolicy(policy)
        self.syncWidth()

    def alignment(self) -> Qt.AlignmentFlag:
        """获取 chips 行内对齐方式。"""
        return self._alignment

    def _schedule_sync(self) -> None:
        """布局完成后再量一次（气泡可能还没显示 / 还没完成首次布局）。"""
        self._sync_timer.start()

    def syncWidth(self, available: int = -1) -> None:
        """按内容宽度收缩（右对齐场景）或占满可用宽度，并同步高度。"""
        if not (self._alignment & Qt.AlignmentFlag.AlignRight):
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            self.updateGeometry()
            self._sync_height()
            return
        if available <= 0 and self.parentWidget() is not None:
            available = self.parentWidget().width()
        total = 0
        for index, card in enumerate(self._cards):
            total += card.sizeHint().width()
            if index:
                total += 6
        if available > 0:
            total = min(total, available)
        self.setFixedWidth(max(0, total))
        self.updateGeometry()
        self._sync_height()
        parent = self.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().activate()

    def _sync_height(self) -> None:
        """按当前宽度计算换行后的实际高度（ElaFlowLayout 的 heightForWidth）。"""
        if not self._cards:
            return
        width = self.width()
        if width <= 0:
            return
        height = self._layout.heightForWidth(width)
        if height <= 0:
            height = self._layout.minimumSize().height()
        height = max(1, int(height))
        if self.minimumHeight() != height or self.maximumHeight() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._sync_height()

    # -- 布局 --------------------------------------------------------------

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt 命名)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt 命名)
        return self._layout.heightForWidth(width)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        hint = self._layout.minimumSize()
        if not (self._alignment & Qt.AlignmentFlag.AlignRight):
            hint.setWidth(0)
        return hint

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        return self.sizeHint()

    # -- 内部 --------------------------------------------------------------

    @staticmethod
    def _normalize(item) -> ElaChatAttachment:
        if isinstance(item, ElaChatAttachment):
            return item
        if isinstance(item, dict):
            return ElaChatAttachment(
                name=str(item.get("name") or "文件"),
                path=str(item.get("path") or ""),
                size=_as_int(item.get("size")),
                digest=str(item.get("digest") or ""),
                mime=str(item.get("mime") or ""),
            )
        return ElaChatAttachment(name=str(item))

    def _rebuild(self, attachments: list) -> None:
        for card in self._cards:
            self._drop_card(card)
        self._attachments = []
        self._cards = []
        for attachment in attachments:
            self._append(attachment, notify=False)
        self.setVisible(bool(self._attachments))
        self.syncWidth()

    def _append(self, attachment: ElaChatAttachment, notify: bool = True) -> None:
        card = self._create_card(attachment)
        self._layout.addWidget(card)
        self._attachments.append(attachment)
        self._cards.append(card)
        self.setVisible(True)
        if notify:
            self.syncWidth()

    def _create_card(self, attachment: ElaChatAttachment) -> QWidget:
        tooltip = attachment.path or attachment.name
        if attachment.isImage:
            pixmap = None
            if attachment.image is not None:
                pixmap = QPixmap.fromImage(attachment.image)
            if (pixmap is None or pixmap.isNull()) and attachment.path:
                pixmap = QPixmap(attachment.path)
            if pixmap is not None and not pixmap.isNull():
                card = _ImageAttachmentCard(pixmap, tooltip, self)
                card.clicked.connect(
                    lambda a=attachment: self.attachmentClicked.emit(a.path or a.name)
                )
                card.removed.connect(lambda a=attachment: self._on_card_removed(a))
                card.setToolTip(tooltip)
                return card
        chip = ElaChip(self._chip_text(attachment), self)
        chip.setClosable(True)
        chip.setToolTip(tooltip)
        set_tooltip(chip, tooltip, ElaToolTipPositionType.Top)
        chip.closed.connect(lambda a=attachment: self._on_card_removed(a))
        chip.clicked.connect(
            lambda a=attachment: self.attachmentClicked.emit(a.path or a.name)
        )
        return chip

    def _drop_card(self, card: QWidget) -> None:
        self._layout.removeWidget(card)
        card.setParent(None)
        card.deleteLater()

    def _remove_at(self, index: int) -> None:
        self._attachments.pop(index)
        self._drop_card(self._cards.pop(index))
        self.setVisible(bool(self._attachments))
        self.syncWidth()

    def _on_card_removed(self, attachment: ElaChatAttachment) -> None:
        for index, item in enumerate(self._attachments):
            if item is attachment or item == attachment:
                self._remove_at(index)
                self.attachmentRemoved.emit(attachment.path or attachment.name)
                self.changed.emit(self.attachments())
                return

    @staticmethod
    def _chip_text(attachment: ElaChatAttachment) -> str:
        name = attachment.name
        if len(name) > 28:
            name = name[:27] + "…"
        if attachment.size:
            return f"{name} · {attachment.displaySize}"
        return name


class StatsBadge(ElaThemeWidget):
    """底部层用量行（单行 mono：``↑128 ↓96 · 总计 224 · 缓存 64`` + 悬停明细）。

    数值由气泡按展示模式注入：默认 ``"footer"`` 模式为整轮汇总
    （各步求和），``"steps"`` 模式为单个步骤的服务端原值。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._stats: Optional[ElaChatStats] = None
        self._message_duration_ms = 0.0
        self._tooltip_text = ""
        self._tooltip_bound_text = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addStretch(1)
        self._label = ColorText(self)
        self._label.setWordWrap(False)
        self._label.hide()
        layout.addWidget(self._label)
        self.hide()

    def setStats(self, stats: Optional[ElaChatStats]) -> None:
        """更新用量统计（``None`` 或全零则隐藏徽标）。"""
        self._stats = stats
        if stats is None or not (
            stats.total_tokens or stats.prompt_tokens or stats.completion_tokens
        ):
            self._apply_tooltip()
            self.hide()
            return
        parts = [
            f"↑{stats.prompt_tokens}",
            f"↓{stats.completion_tokens}",
            f"总计 {stats.total_tokens}",
        ]
        if stats.cache_read_tokens:
            parts.append(f"缓存读 {stats.cache_read_tokens}")
        if stats.cache_write_tokens:
            parts.append(f"缓存写 {stats.cache_write_tokens}")
        self._label.setText("  ·  ".join(parts))
        self._label.show()
        self._apply_tooltip()
        self._apply_theme()
        self.show()

    def setMessageDuration(self, durationMs: float) -> None:
        """设置消息级端到端耗时（合并进悬浮提示，与首字延时相邻显示）。"""
        self._message_duration_ms = float(durationMs or 0.0)
        self._apply_tooltip()

    def _apply_tooltip(self) -> None:
        """刷新悬浮提示（库内 ``ElaToolTip``）：首字 / 端到端耗时 / 词元速率 / 缓存。"""
        stats = self._stats
        durationLabel = "耗时"
        if stats is not None and self._message_duration_ms:
            stats = replace(stats, duration_ms=self._message_duration_ms)
            durationLabel = "端到端"
        text = stats.tooltip(durationLabel) if stats is not None else ""
        if text == self._tooltip_text:
            return
        self._tooltip_text = text
        self._label.setToolTip(text)
        # 隐藏徽标不建 ElaToolTip：footer 模式下大部分步骤徽标永远不显示，
        # 每个都建一个提示框纯浪费（bug #17）。显示时 showEvent 补建。
        if self.isVisible():
            self._bind_tooltip()

    def _bind_tooltip(self) -> None:
        """按当前文本绑定 / 更新提示框（只在可见时调用）。"""
        text = self._tooltip_text
        if text:
            set_tooltip(self._label, text, ElaToolTipPositionType.Top)
        else:
            remove_tooltip(self._label)
        self._tooltip_bound_text = text

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        if self._tooltip_bound_text != self._tooltip_text:
            self._bind_tooltip()

    def stats(self) -> Optional[ElaChatStats]:
        """获取当前用量统计。"""
        return self._stats

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        super()._onThemeChanged(mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        if self._stats is None:
            return
        self._label.setTextColor(muted_color(self._theme_mode, 0.7))
        self._label.setTextPixelSize(11)


class MessageActions(ElaChatToolBar):
    """底部层操作栏（复制 / 撤回 / 重新生成 + 自定义动作）。"""

    #: 复制
    copyRequested = pyqtSignal()
    #: 撤回
    undoRequested = pyqtSignal()
    #: 重新生成
    regenerateRequested = pyqtSignal()
    #: 自定义动作被点击（参数：key）
    actionTriggered = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, compact=True)
        self._mouse_transparent = False
        self.toolTriggered.connect(self._dispatch)

    # -- 鼠标穿透（hover 隐藏时阻止误点） ----------------------------------

    def setMouseTransparent(self, on: bool) -> None:
        """设置操作栏（含全部子按钮）是否鼠标穿透。

        隐藏态下穿透可避免点击到不可见按钮；程序化 ``click()`` 不受影响。
        """
        self._mouse_transparent = bool(on)
        self._apply_mouse_transparency()

    def mouseTransparent(self) -> bool:
        """操作栏是否鼠标穿透。"""
        return self._mouse_transparent

    def _apply_mouse_transparency(self) -> None:
        widgets = [self]
        widgets.extend(self.findChildren(QWidget))
        for widget in widgets:
            widget.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                self._mouse_transparent,
            )

    def addButton(self, *args, **kwargs) -> QPushButton:
        """添加按钮后同步鼠标穿透状态（宿主可随时追加自定义动作）。"""
        button = super().addButton(*args, **kwargs)
        button.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            self._mouse_transparent,
        )
        return button

    def addWidget(self, *args, **kwargs) -> QWidget:
        """添加控件后同步鼠标穿透状态。"""
        widget = super().addWidget(*args, **kwargs)
        widget.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            self._mouse_transparent,
        )
        return widget

    def addCopyAction(self) -> QPushButton:
        """添加「复制」按钮。"""
        return self.addButton(
            icon=ElaIconType.IconName.Copy, tooltip="复制", key="copy"
        )

    def addUndoAction(self) -> QPushButton:
        """添加「撤回」按钮（删除该轮及之后消息并回填输入框）。"""
        return self.addButton(
            icon=ElaIconType.IconName.ArrowRotateLeft,
            tooltip="撤回该轮及其后的消息",
            key="undo",
        )

    def addRegenerateAction(self) -> QPushButton:
        """添加「重新生成」按钮。"""
        return self.addButton(
            icon=ElaIconType.IconName.ArrowsRotate,
            tooltip="重新生成",
            key="regenerate",
        )

    def addCustomAction(
        self,
        key: str,
        icon=None,
        tooltip: str = "",
        callback=None,
    ) -> QPushButton:
        """添加自定义动作按钮（同时发 ``actionTriggered(key)``）。"""
        return self.addButton(icon=icon, tooltip=tooltip, key=key, callback=callback)

    def _dispatch(self, key: str) -> None:
        if key == "copy":
            self.copyRequested.emit()
        elif key == "undo":
            self.undoRequested.emit()
        elif key == "regenerate":
            self.regenerateRequested.emit()
        else:
            self.actionTriggered.emit(key)


class SteerNotice(_ThemeAwareMixin, QWidget):
    """插话回执行（``kind == Synthetic``）。

    渲染成一条极简的左竖线 + ``↳ <文本>``。**刻意不插一条用户气泡** ——
    助手消息正在流式输出，中途插一条用户消息视觉上很怪（opencode 就是那么
    做的，产物是时间线上「助手话说到一半、下面冒出一条用户消息」）。改成在
    同一条助手消息内追加一行旁注，语义是「插话已送达」，视觉连续，且随消息
    一起持久化。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self._text = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        self._rail = QWidget(self)
        self._rail.setFixedWidth(2)
        layout.addWidget(self._rail, 0, Qt.AlignmentFlag.AlignVCenter)
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._label, 1)
        self._apply_theme()

    def setText(self, text: str) -> None:
        """设置回执文本。"""
        self._text = text or ""
        self._label.setText(f"↳ {self._text}" if self._text else "")

    def text(self) -> str:
        """获取回执文本（不含 ``↳`` 前缀）。"""
        return self._text

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        setSolidBackground(self._rail, muted_color(mode, 0.4))
        self._label.setTextColor(muted_color(mode, 0.7))
        self._label.setTextPixelSize(12)
        self._label.setTextFormat(Qt.TextFormat.PlainText)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()


class CompactionSeparator(_ThemeAwareMixin, ElaScrollPageArea):
    """上下文压缩分隔卡（``kind == Compaction``）。

    「历史已被摘要替代」这件事**必须在时间线上如实表达**，否则用户看到的是
    一条断层：模型突然「忘了」前面说过什么。渲染成一条虚线 + 说明 + 可折叠
    的摘要正文（对齐 opencode ``SessionCompactionMessage``）。

    **库不实现压缩算法**：``SHRINK_STEPS`` 收缩循环 / 摘要模板 / 词元估算
    / transcript 边界全在 provider 抽象那一侧，超出 UI 库范围。本卡片只负责
    「能表达 + 能持久化」—— 压不压、压哪段、摘要怎么来由宿主决定。
    """

    #: 展开 / 收起摘要
    toggled = pyqtSignal(bool)

    #: 分隔文案模板（``{count}`` 会被替换成被压缩的历史条数）
    LABEL_TEMPLATE = "已压缩 {count} 条历史"
    #: **调用方没给条数时**用的文案。
    #:
    #: 绝不能写「已压缩 0 条历史」—— ``historyCount`` 默认 0 是「不知道」的意思，
    #: 不是「真的压了 0 条」。照实说，模型才不会被一条自相矛盾的时间线带偏
    #: （实测截图里就是一行「已压缩 0 条历史」）。
    LABEL_NO_COUNT = "已压缩历史"

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setBorderRadius(8)
        self._summary = ""
        self._count = 0
        self._status = ElaChatStatusType.Done
        self._body_built = False
        # **显式记展开态**，不要从 ``self._body.isVisible()`` 反推：控件还没被
        # show 过时 ``isVisible()`` 恒为 False（跟父链可见性走），反推出来的
        # 「展开了吗」在离屏测试与真实挂载前都是错的。
        self._opened = False
        self._summary_label: Optional[ElaText] = None
        self._preview: Optional[ColorText] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        self._header = QHBoxLayout()
        self._header.setContentsMargins(0, 0, 0, 0)
        self._header.setSpacing(6)
        self._icon = ElaIconButton(ElaIconType.IconName.BoxArchive, 12, 16, 16, self)
        self._icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._header.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self._label = ColorText(self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._header.addWidget(self._label, 1)
        self._chevron = ElaIconButton(
            ElaIconType.IconName.ChevronRight, 12, 16, 16, self
        )
        self._chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._header.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(self._header)
        # 折叠态的摘要首行。整张卡折叠着也要能回答「到底压掉了什么」——
        # 只留一行「已压缩 N 条历史」+ 箭头等于什么都没说（对齐 opencode 的
        # ``SessionCompactionMessage``：分隔条下面就是摘要正文）。
        self._preview = ColorText(self)
        self._preview.setTextFormat(Qt.TextFormat.PlainText)
        self._preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._preview.hide()
        layout.addWidget(self._preview)
        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        layout.addWidget(self._body)
        self._body.hide()
        # 整卡可点开关摘要（点标题行 / 图标 / 箭头都行）
        self._header_label = self._label
        for widget in (self._label, self._icon, self._chevron):
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label.mousePressEvent = self._toggle_from_header  # type: ignore[method-assign]
        self._icon.mousePressEvent = self._toggle_from_header  # type: ignore[method-assign]
        self._chevron.mousePressEvent = self._toggle_from_header  # type: ignore[method-assign]
        self._apply_theme()

    # -- 数据 --------------------------------------------------------------

    def setSummary(self, summary: str) -> None:
        """设置摘要文本。"""
        self._summary = summary or ""
        if self._body_built and self._summary_label is not None:
            self._summary_label.setText(self._summary)
        self._sync_preview()

    @staticmethod
    def _preview_text(summary: str) -> str:
        """折叠态那一行：摘要的首行，超长截断。

        ``ColorText`` 不按宽度省略（``ElaText.sizeHint`` 无视 ``wordWrap``），
        所以只能自己按字符数截，省略号自己加。
        """
        for line in (summary or "").splitlines():
            line = line.strip()
            if line:
                return (
                    line
                    if len(line) <= PREVIEW_MAX_CHARS
                    else (line[: PREVIEW_MAX_CHARS - 1] + "…")
                )
        return ""

    def _sync_preview(self) -> None:
        if self._preview is None:
            return
        text = self._preview_text(self._summary)
        self._preview.setText(text)
        # 展开后正文已经全露出来了，预览行就没必要重复
        self._preview.setVisible(bool(text) and not self._opened)

    def summary(self) -> str:
        """获取摘要文本。"""
        return self._summary

    def setHistoryCount(self, count: int) -> None:
        """设置被压缩的历史条数（只影响文案）。"""
        try:
            self._count = max(0, int(count))
        except (TypeError, ValueError, OverflowError):
            self._count = 0
        self._sync_label()

    def historyCount(self) -> int:
        """获取被压缩的历史条数。"""
        return self._count

    def setCompactionStatus(self, status: str) -> None:
        """设置压缩状态（``streaming`` 时标题追加「进行中」）。"""
        self._status = status or ElaChatStatusType.Done
        self._sync_label()

    def setOpened(self, opened: bool) -> None:
        """展开 / 收起摘要。"""
        if opened:
            self._build_body()
        self._opened = bool(opened)
        self._body.setVisible(self._opened)
        self._sync_preview()
        self._chevron.setAwesome(
            ElaIconType.IconName.ChevronDown
            if opened
            else ElaIconType.IconName.ChevronRight
        )
        if self.layout() is not None:
            self.layout().activate()
        self.updateGeometry()
        self.toggled.emit(bool(opened))

    def opened(self) -> bool:
        """摘要是否展开（读的是显式状态，与是否已 show 无关）。"""
        return self._opened

    def _toggle_from_header(self, _event=None) -> None:
        self.setOpened(not self._opened)

    def _build_body(self) -> None:
        if self._body_built:
            return
        self._body_built = True
        self._summary_label = ColorText(self._body)
        self._summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._body_layout.addWidget(self._summary_label)
        self._summary_label.setText(self._summary)
        self._apply_theme()

    def _sync_label(self) -> None:
        text = (
            self.LABEL_TEMPLATE.format(count=self._count)
            if self._count > 0
            else self.LABEL_NO_COUNT
        )
        if self._status == ElaChatStatusType.Streaming:
            text = f"{text} · 压缩中…"
        elif self._status == ElaChatStatusType.Error:
            text = f"{text} · 压缩失败"
        self._label.setText(text)

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        self._label.setTextColor(muted_color(mode, 0.7))
        self._label.setTextPixelSize(12)
        self._icon.setLightIconColor(muted_color(mode, 0.5))
        self._icon.setDarkIconColor(muted_color(mode, 0.5))
        self._chevron.setLightIconColor(muted_color(mode, 0.5))
        self._chevron.setDarkIconColor(muted_color(mode, 0.5))
        if self._preview is not None:
            self._preview.setTextColor(muted_color(mode, 0.62))
            self._preview.setTextPixelSize(12)
        if self._summary_label is not None:
            self._summary_label.setTextColor(muted_color(mode, 0.8))
            self._summary_label.setTextPixelSize(12)
            self._summary_label.setTextFormat(Qt.TextFormat.PlainText)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()


class PermissionCard(_ThemeAwareMixin, ElaScrollPageArea):
    """工具审批卡（``kind == Permission``）。

    **库不阻塞**：卡片只收集点击并发信号，挂起后端是宿主的事（见
    :class:`~pyqt6_ela_pro.chat.message.ElaChatPermission` 的流程说明）。
    在 Qt 里真的 ``wait()`` 等用户点按钮会卡死事件循环。

    两种形态，由 ``permission.questions`` 是否为空决定（**不另设标志位**）：

    - **批准型**（``questions`` 为空）：``允许一次`` / ``始终允许`` / ``拒绝…``
      三个动作 + 可选的理由输入行；
    - **问答型**（``questions`` 非空）：**逐题向导**（对齐 opencode 的
      ``session-question-dock.tsx``）—— 头部「N / M 个问题」+ 可点的进度段，
      中间是当前那道的题面 + 候选卡（两行：标题 + 说明，可多选），末行是
      「输入自己的答案」，页脚 ``忽略`` / ``上一步`` / ``下一步|提交``。

    **已落定**：折叠成一行结果摘要（仍可点开看当时的详情与答案）。

    「始终允许」只发信号，**规则存哪、怎么匹配由宿主决定**；库不持有任何
    权限状态。

    问答型的答案编码见 :meth:`_build_answer`。
    """

    #: 用户做出选择（参数：reply、answer、feedback）
    #:
    #: ``reply`` 取 :class:`~pyqt6_ela_pro.chat.message.ElaChatPermissionStatusType`
    #: 里的 ``Allowed`` / ``Always`` / ``Rejected`` / ``Cancelled``。问答型的
    #: ``answer`` 是 ``json.dumps({key: str | [str, ...]})``，批准型为空串。
    replied = pyqtSignal(str, str, str)

    _REJECT_ICON = ElaIconType.IconName.Ban
    _OK_ICON = ElaIconType.IconName.CircleCheck
    _QUESTION_ICON = ElaIconType.IconName.Question

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        # 圆角 0 + paintEvent 不画 = **透明**。本控件住在审批 dock 里，dock 本身
        # 就是那张卡；再画一层就成了「卡中卡」：两套圆角、两条边框、一次额外内缩。
        self.setBorderRadius(0)
        self._permission: Optional[ElaChatPermission] = None
        self._responding = False

        # 逐题向导的状态（key 全部来自 ElaChatQuestion.key）
        self._tab = 0
        self._answers: dict = {}  # key -> [已选 label]
        self._custom: dict = {}  # key -> 自定义答案文本
        self._custom_on: dict = {}  # key -> 自定义行是否处于「选中」
        self._drafts: dict = {}  # key -> 未提交的自定义草稿（刷新重建后恢复）
        self._editing = ""  # 正在编辑自定义答案的 key
        self._focus_row = 0  # 键盘焦点所在行号
        self._segments: list = []  # QuestionSegment
        self._rows: dict = {}  # key -> [QuestionOptionCard]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, CARD_V_PADDING, 12, CARD_V_PADDING)
        layout.setSpacing(LAYOUT_SPACING)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self._icon = ElaIconButton(ElaIconType.IconName.ShieldHalved, 14, 18, 18, self)
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        head.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self._title = ColorText(self)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        title_row.addWidget(self._title)
        # 题目的短标签（``ElaChatQuestion.header``）**放在标题行里，不单独占一行**。
        # 单独一行时它看起来就像「题面莫名换行了」，而且白白吃掉一行垂直空间。
        self._tag = ColorText(self)
        self._tag.setTextFormat(Qt.TextFormat.PlainText)
        self._tag.hide()
        title_row.addWidget(self._tag)
        title_row.addStretch(1)
        # 右边是**一组**进度：「2 / 2」紧挨着段条。
        # 之前「2 / 2」跟在短标签后面、段条又被推到最右，同一条信息被拆到两个
        # 地方，读起来像两句话；现在左右分工明确 —— 左边说「在答什么」，右边说
        # 「答到第几」。
        self._progress = ColorText(self)
        self._progress.setTextFormat(Qt.TextFormat.PlainText)
        self._progress.hide()
        title_row.addWidget(self._progress, 0, Qt.AlignmentFlag.AlignVCenter)
        # 进度段：只在**多题**时出现（单题时进度条是纯噪音）
        self._segment_box = QWidget(self)
        self._segment_box.setFixedHeight(SEGMENT_HIT)
        self._segment_layout = QHBoxLayout(self._segment_box)
        self._segment_layout.setContentsMargins(0, 0, 0, 0)
        self._segment_layout.setSpacing(4)
        self._segment_box.hide()
        title_row.addWidget(self._segment_box, 0, Qt.AlignmentFlag.AlignVCenter)
        titles.addLayout(title_row)
        self._resources = ColorText(self)
        self._resources.setTextFormat(Qt.TextFormat.PlainText)
        self._resources.setWordWrap(True)
        titles.addWidget(self._resources)
        head.addLayout(titles, 1)
        layout.addLayout(head)

        # 详情（diff / 命令行 / 问题描述 / 已落定的答案摘要）
        self._detail = ColorText(self)
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setWordWrap(True)
        self._detail.setFont(mono_font(11))
        self._detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._detail.hide()
        layout.addWidget(self._detail)
        # 大量 diff 必须能折叠 —— 一次 ``git diff`` 动辄上千行，全量摊在卡片里会把
        # 整条消息撑到几千像素，用户连「要不要批」都来不及看。
        self._detail_expanded = False
        #: 详情折叠态归属的请求 id（换请求才复位折叠）
        self._detail_request = ""
        self._detail_toggle = ElaButton(
            "展开全部", variant="link", size="small", parent=self
        )
        self._detail_toggle.clicked.connect(self._toggle_detail)
        self._detail_toggle.hide()
        layout.addWidget(self._detail_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        # ── 问答型：题面 + 提示 + 选项区 ─────────────────────────────────
        self._question_box = QWidget(self)
        question_layout = QVBoxLayout(self._question_box)
        # 顶部 4px + 段间距 10px ≈ opencode 的 ``gap:16px`` 减一点；标题行和题面
        # 挨太近会糊成一段
        question_layout.setContentsMargins(0, 4, 0, 0)
        question_layout.setSpacing(10)
        self._question_text = ColorText(self._question_box)
        self._question_text.setTextFormat(Qt.TextFormat.PlainText)
        self._question_text.setWordWrap(True)
        question_layout.addWidget(self._question_text)
        # 选项区是**普通容器，不是滚动区**。
        #
        # 用 ``QScrollArea`` 的话，布局只能看到它那个无意义的 ``sizeHint()``（一个
        # 小值），于是内容被压扁、明明放得下也弹滚动条（实测：166px 的三行选项被压到
        # 69px，第二个选项切掉半截）。改成「自己测内容再 ``setFixedHeight``」也不对
        # —— 测出来的宽度依赖布局本身，两边互相喂误差（题面一度被撑到 250px）。
        # 候选行是普通控件、行高固定，容器的 sizeHint 就是内容高度，布局自然给对。
        # **不设上限**：题目选项 seldom 超过 6 个；真很多，一屏高的问题卡会把消息区
        # 挤小，但输入区仍在、用户能滚消息区 —— 比「内容被裁到够不着」好。
        self._options_host = QWidget(self._question_box)
        self._options_box = QVBoxLayout(self._options_host)
        self._options_box.setContentsMargins(0, 0, 0, 0)
        self._options_box.setSpacing(OPTION_GAP)
        question_layout.addWidget(self._options_host)
        self._question_box.hide()
        layout.addWidget(self._question_box)
        self._option_buttons: list = []  # 兼容旧测试：当前题的全部候选卡
        self._custom_edit = None

        # ── 批准型的动作区（问答型不用） ───────────────────────────────
        # 三个动作**按重要性分档**，不是三个等权重的文字按钮：
        # 允许一次 = 主动作（实心强调色）／始终允许 = 次要承诺（描边）／拒绝 =
        # 危险（文字 + 危险色）。原先用 ElaChatToolBar（消息页脚那排小图标按钮的
        # 容器）时三个键长得一模一样，用户扫一眼分不出该点哪个。
        self._actions = QWidget(self)
        actions_layout = QHBoxLayout(self._actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        self._allow_button = ElaButton(
            "允许一次",
            variant="solid",
            color="primary",
            size="small",
            parent=self._actions,
        )
        self._allow_button.clicked.connect(
            lambda: self._emit_reply(ElaChatPermissionStatusType.Allowed, "", "")
        )
        actions_layout.addWidget(self._allow_button)
        self._always_button = ElaButton(
            "始终允许", variant="outlined", size="small", parent=self._actions
        )
        self._always_button.clicked.connect(
            lambda: self._emit_reply(ElaChatPermissionStatusType.Always, "", "")
        )
        actions_layout.addWidget(self._always_button)
        self._reject_button = ElaButton(
            "拒绝…", variant="text", danger=True, size="small", parent=self._actions
        )
        self._reject_button.clicked.connect(self._open_feedback)
        actions_layout.addWidget(self._reject_button)
        actions_layout.addStretch(1)
        self._actions.hide()
        layout.addWidget(self._actions)
        self._feedback_row = QWidget(self)
        feedback_layout = QHBoxLayout(self._feedback_row)
        feedback_layout.setContentsMargins(0, 0, 0, 0)
        feedback_layout.setSpacing(6)
        self._feedback_edit = ElaPlainTextEdit(self._feedback_row)
        self._feedback_edit.setPlaceholderText("为什么拒绝？（可留空，会回传给模型）")
        self._feedback_edit.setFixedHeight(30)
        feedback_layout.addWidget(self._feedback_edit, 1)
        self._feedback_send = ElaButton(
            "回车提交", size="small", parent=self._feedback_row
        )
        self._feedback_send.clicked.connect(self._submit_feedback)
        feedback_layout.addWidget(self._feedback_send, 0)
        self._feedback_row.hide()
        layout.addWidget(self._feedback_row)

        # ── 问答型的页脚托盘 ────────────────────────────────────────────
        self._footer = QWidget(self)
        footer_layout = QHBoxLayout(self._footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(6)
        self._dismiss_button = ElaButton(
            "忽略", variant="text", size="small", parent=self._footer
        )
        self._dismiss_button.clicked.connect(
            lambda: self._emit_reply(ElaChatPermissionStatusType.Cancelled, "", "")
        )
        footer_layout.addWidget(self._dismiss_button)
        footer_layout.addStretch(1)
        self._back_button = ElaButton(
            "上一步", variant="outlined", size="small", parent=self._footer
        )
        self._back_button.clicked.connect(self._go_back)
        footer_layout.addWidget(self._back_button)
        # 主动作 = 实心强调色，一眼分得出「这一步该点哪个」。快捷键**只在键盘上
        # 有效、不写在按钮上** —— 内联提示文字比按钮本身还抢眼（实测）。
        self._next_button = ElaButton(
            "下一步",
            variant="solid",
            color="primary",
            size="small",
            parent=self._footer,
        )
        self._next_button.clicked.connect(self._go_next)
        footer_layout.addWidget(self._next_button)
        self._footer.hide()
        layout.addWidget(self._footer)

        self.hide()
        self._apply_theme()

    # -- 尺寸契约 ----------------------------------------------------------

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        """按**内容布局**报高度；宽度交给父布局（0 = 别替我决定）。

        别继承 ``QAbstractScrollArea`` 那套：它的 ``sizeHint()`` 不是内容高度
        契约（按视口 + 框架估算）。审批 dock 正是靠它给卡片分配高度 ——
        实测卡片实际 249px 而继承来的 ``sizeHint`` 报 268px，选项多时差得更多，
        dock 与卡片之间就出现一截来源不明的空白（回归测试
        ``TestLayoutContract::test_card_gets_its_size_hint``）。

        内容高度取**布局的 minimumSize**：卡片里有可换行的题面与候选说明，
        ``sizeHint()`` 会按「不换行」估算而偏小。
        """
        return QSize(0, self.layout().minimumSize().height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        return self.sizeHint()

    # -- 数据 --------------------------------------------------------------

    def setPermission(self, permission: Optional[ElaChatPermission]) -> None:
        """设置审批请求（``None`` 隐藏整张卡）。

        换了一个**新的** request（``request_id`` 变了）时重置向导状态；同一
        request 只是状态推进（如 pending -> allowed）则**保留**草稿，这样宿主
        「先 setResponding(True) 再回填」的两段式流程不会把用户已选的东西抹掉。

        **这里不调 ``show()``** —— 卡片由
        :meth:`~pyqt6_ela_pro.chat.docks.ElaChatPermissionDock.setCard` 在收下它
        的那一刻才显示。``bubble.beginPermission`` 建卡时**故意不给 parent**（气泡
        不知道 dock 的存在），若在此处 show，一个无父控件会被 Qt 当成**顶层窗口**
        弹出来：用户看到「小窗一闪 -> 变成输入区上的卡片」（实测截图），连点几次就
        同时弹出好几个窗口。
        """
        previous = self._permission
        self._permission = permission
        # 只在「新请求进入等待」时清 responding。落定那次 setPermission 是
        # replied.emit() 的**同步回环**（_on_permission_replied -> setPermission），
        # 无条件清会把刚置上的 responding 又抹掉，双击守卫直接失效。
        is_new = previous is None or (
            permission is not None
            and previous is not None
            and previous.request_id != permission.request_id
        )
        if permission is not None and permission.isPending:
            self._responding = False
            if is_new:
                self._reset_wizard()
        if permission is None:
            self.hide()
            return
        self._sync_all()

    def permission(self) -> Optional[ElaChatPermission]:
        """获取当前审批快照。"""
        return self._permission

    def setResponding(self, on: bool) -> None:
        """设置「回复已在途」——期间禁用全部可交互部件，防双击重复提交。

        对齐 opencode 的 ``responding`` 状态：请求在飞的时候整张卡一起置灰。
        """
        self._responding = bool(on)
        self._sync_actions()
        self._sync_options_enabled()

    def responding(self) -> bool:
        """是否处于「回复在途」状态。"""
        return self._responding

    def answers(self) -> dict:
        """当前向导的答案（``{key: [label, ...]}``，未答的 key 不在字典里）。"""
        result = {}
        for question in self._questions():
            values = self._current_values(question)
            if values:
                result[question.key] = list(values)
        return result

    def tabIndex(self) -> int:  # noqa: N802
        """当前题号（从 0 起）。"""
        return self._tab

    def questionCount(self) -> int:  # noqa: N802
        """题目总数。"""
        return len(self._questions())

    # -- 内部：向导 --------------------------------------------------------

    def _questions(self) -> tuple:
        permission = self._permission
        if permission is None:
            return ()
        return permission.questions

    def _current_question(self):
        questions = self._questions()
        if not questions:
            return None
        return questions[min(self._tab, len(questions) - 1)]

    def _reset_wizard(self) -> None:
        self._tab = 0
        self._answers.clear()
        self._custom.clear()
        self._custom_on.clear()
        self._drafts.clear()
        self._editing = ""

    def _current_values(self, question) -> list:
        """该题当前的答案列表（自定义优先且与候选项互斥）。"""
        if self._custom_on.get(question.key) and self._custom.get(question.key):
            return [self._custom[question.key]]
        return list(self._answers.get(question.key) or ())

    def _build_answer(self) -> str:
        """把向导状态编码成 ``permissionReplied`` 的 ``answer``。

        规则（对齐 opencode 的 ``Object.fromEntries(flatMap(...))``）：

        - **单选塌缩成标量**：``{"q0": "选项 A"}``；
        - **多选发整个数组**：``{"q1": ["A", "B"]}``；
        - **未答题整条不进 payload**（不是空串、不是空数组）—— 模型据此知道
          「用户没答这道」，而空数组会被误读成「用户答了『一个都不选』」；
        - **自定义答案与候选项互斥**：写了自定义答案，这道题就答它（多选时
          仍是单元素数组），因为「选项 A 或我自己的话」没法同时成立。
        """
        payload = {}
        for question in self._questions():
            values = self._current_values(question)
            if not values:
                continue
            payload[question.key] = values if question.isMultiple else values[0]
        return _json.dumps(payload)

    def _sync_all(self) -> None:
        """刷新整张交互卡。

        **本控件只负责「正在等用户操作」这个状态**：落定之后它立刻被销毁，时间线上
        留下的是另一张 :class:`PermissionRecord`。所以这里**没有** settled 分支 ——
        一张卡同时管两态时，标题 / 图标 / 显隐全都是双份条件，越写越乱。
        """
        permission = self._permission
        if permission is None:
            return
        is_question = permission.isQuestion
        self._question_box.setVisible(is_question)
        self._footer.setVisible(is_question)
        # 动作区的显隐只有 ``_sync_actions`` 一处说了算（它还要看 responding）；
        # question 分支也必须调它 —— 否则同一张卡从批准型切到问答型时，批准三键
        # 与已展开的拒绝理由行会留在问答卡上。
        if is_question:
            self._sync_header(permission)
            self._sync_detail(permission)
            self._sync_question()
            self._sync_segments()
            self._sync_footer()
            self._sync_actions()
        else:
            self._segment_box.hide()
            self._progress.hide()
            self._tag.hide()
            self._sync_header(permission)
            self._sync_detail(permission)
            self._sync_actions()
        self._apply_theme()

    def _sync_header(self, permission: ElaChatPermission) -> None:
        title = permission.title or self._default_title(permission)
        self._title.setText(title)
        if permission.isQuestion:
            total = len(permission.questions)
            self._progress.setText(f"{self._tab + 1} / {total}")
            self._progress.setVisible(total > 1)
        else:
            self._progress.setText("")
            self._progress.hide()
        if permission.isQuestion:
            # 资源列表与「始终允许」规则对问答型无意义
            self._resources.setText("")
            self._resources.hide()
            return
        self._tag.setText("")
        self._tag.hide()
        resources = [item for item in permission.resources if item]
        if resources:
            shown = resources[:4]
            text = "\n".join(shown)
            if len(resources) > len(shown):
                text += f"\n… 另有 {len(resources) - len(shown)} 项"
            self._resources.setText(text)
            self._resources.show()
        else:
            self._resources.setText("")
            self._resources.hide()

    @staticmethod
    def _default_title(permission: ElaChatPermission) -> str:
        if permission.isQuestion:
            return "需要你回答"
        return f"需要确认：{permission.action or '工具执行'}"

    def _sync_detail(self, permission: ElaChatPermission) -> None:
        """交互期间只显示宿主给的 detail（diff / 命令行）。

        **答案摘要不在这里渲染** —— 那是 :class:`PermissionRecord` 的活：交互卡
        落定即销毁，没必要为一闪而过的状态再写一套。
        """
        if permission.request_id != self._detail_request:
            # 只在新请求时复位折叠；同一 request 的状态刷新（``setResponding``
            # 两段式的回填）不能把用户刚展开的长 diff 折回去。
            self._detail_expanded = False
            self._detail_request = permission.request_id
        self._sync_detail_text(permission.detail or "")

    def _sync_detail_text(self, detail: str) -> None:
        """写入详情，并按「行数 + 单行长度」双上限决定是否折叠。

        两个上限缺一不可：``git diff`` 是「行数多但每行短」，minified 文件 /
        一整行 base64 是「行数少但单行巨长」。只卡行数会被后者炸穿，只卡字符数
        会被前者撑成几千像素。
        """
        if not detail:
            self._detail.setText("")
            self._detail.hide()
            self._detail_toggle.hide()
            return
        shown, overflow, total = _collapsed_detail(detail, self._detail_expanded)
        self._detail.setText(shown)
        self._detail.show()
        self._detail_toggle.setVisible(overflow)
        self._detail_toggle.setText(
            f"收起（共 {total} 行）"
            if self._detail_expanded
            else f"展开全部（共 {total} 行）"
        )

    def _toggle_detail(self) -> None:
        permission = self._permission
        if permission is None:
            return
        self._detail_expanded = not self._detail_expanded
        self._sync_detail_text(permission.detail or "")

    def _sync_question(self) -> None:
        """重建选项区并显示当前题（切题时草稿从 ``_custom`` 恢复）。"""
        question = self._current_question()
        self._clear_options()
        if question is None:
            self._question_text.setText("")
            self._option_buttons = []
            self._editing = ""
            return
        # 短标签进标题行（不单独占一行）；前缀分隔符免得和标题糊成一片
        self._tag.setText(f"\u00b7 {question.header}" if question.header else "")
        self._tag.setVisible(bool(question.header))
        self._question_text.setText(question.question or question.header)
        # 「选择一个答案」只在**真的有候选项**时才有意义（只留自定义输入框时
        # 这句话是废话）
        rows = []
        for index, option in enumerate(question.options):
            rows.append(
                self._make_row(
                    question,
                    option.label,
                    option.description,
                    index,
                    custom=False,
                )
            )
        if question.custom:
            rows.append(self._make_row(question, "", "", len(rows), custom=True))
        for row in rows:
            self._options_box.addWidget(row)
        self._rows[question.key] = rows
        self._option_buttons = rows
        self._refresh_rows()
        if self._editing == question.key:
            # 同一题刷新（``setPermission`` 两段式回填）：编辑器原地恢复，
            # 草稿由 ``_refresh_rows`` 回填进新行
            self._enter_editing(question.key)
        else:
            # 切题 / 换请求：旧编辑态作废（草稿已在 ``_clear_options`` 暂存）
            self._editing = ""

    def _on_row_focused(self, index: int) -> None:
        """记住键盘焦点行号。

        **不轮询 ``hasFocus()``**：它要求窗口已激活，测试里（以及某些嵌套滚动
        场景下）根本不成立，于是方向键导航会静默失灵。行自己报上来最可靠。
        """
        self._focus_row = int(index)

    def _make_row(
        self, question, label: str, description: str, index: int, *, custom: bool
    ):
        row = QuestionOptionCard(
            self._options_host,
            value=label,
            description=description,
            multi=question.isMultiple,
            isCustom=custom,
        )
        row.setRowIndex(index)
        row.activate.connect(lambda value, q=question: self._on_activate(q, value))
        row.markClicked.connect(lambda v, q=question: self._on_mark_clicked(q, v))
        row.editCommitted.connect(lambda text, q=question: self._on_commit(q, text))
        row.moveFocus.connect(self._move_focus)
        row.rowFocused.connect(self._on_row_focused)
        # 数字键 / Ctrl+⏎ / Alt+← / Esc 必须由**持有全部行**的这一层派发 ——
        # 焦点常驻在候选行上，键盘事件发给行、不冒泡回卡片。
        row.globalKey.connect(self._on_global_key)
        return row

    def _clear_options(self) -> None:
        # 正在编辑的自定义草稿要先存下来：``setPermission`` 的刷新会走到这里
        # 销毁行控件，重建后草稿若不在 ``_drafts`` 里就永远找不回来了。
        # **不在这里清 ``_editing``**：``_sync_question`` 还要按它决定是否
        # 把编辑器原地恢复（同一题刷新）还是丢弃（切到别的题）。
        if self._editing:
            row = self._custom_row(self._editing)
            if row is not None and row.editorText():
                self._drafts[self._editing] = row.editorText()
        for rows in self._rows.values():
            for row in rows:
                self._options_box.removeWidget(row)
                row.setParent(None)
                row.deleteLater()
        self._rows.clear()
        self._option_buttons = []

    def _refresh_rows(self) -> None:
        """把 ``_answers`` / ``_custom`` 同步到当前题的每一张卡。

        顺带刷新进度段 —— 答完一道就该点亮一段，攒到切题时才更新会让「已答 /
        未答」的分界看起来随机。

        **自定义行的勾选态只认 ``_custom_on``**：它的 ``value()`` 是空串，而
        ``picked`` 里装的是**自定义文本**，``row.value() in picked`` 永远为假
        —— 于是提交了自定义答案那一行仍然不高亮、标记也不勾，提交完再点那个
        圆点还会把答案取消掉（用户报的现象：「单选时最后那项怎么都选不中」，
        单选 / 多选都中招）。对齐 opencode 的 ``data-picked={on()}``
        （``on = customOn[tab]``，与有没有文字无关）。
        """
        question = self._current_question()
        if question is not None:
            picked = set(self._current_values(question))
            custom_on = bool(self._custom_on.get(question.key))
            for row in self._rows.get(question.key, ()):
                if row.isCustom():
                    row.setPicked(custom_on)
                else:
                    row.setPicked(row.value() in picked)
                # 正在编辑的行不要覆盖：用户没提交的字比已提交值新（草稿优先）
                if row.isCustom() and not row.isEditing():
                    row.setEditorText(
                        self._drafts.get(question.key)
                        or self._custom.get(question.key, "")
                    )
        self._sync_segments()

    def _on_activate(self, question, value: str) -> None:
        """整行被激活：普通候选项 = 切换勾选；自定义行 = 展开编辑器。"""
        if not value:
            self._enter_editing(question.key)
            return
        already = value in (self._answers.get(question.key) or ())
        self._select_value(question, value, not already)

    def _on_mark_clicked(self, question, value: str) -> None:
        """点标记 / 按 Space。

        普通候选行 = 切换该行的勾选（``value`` 非空）；自定义行（``value`` 为
        空串）= **选中并展开编辑器**，一步到位就能开始输入（对齐 opencode 的
        ``customToggle`` —— 原实现「没敲内容就不给勾」，那个哑操作正是「点了
        没反应」的来源，而示例页写的又是「可只点标记勾上」，两边对不上）。

        单选下标记**不提供「再点一次取消」**：它是 radio，再点只会保持选中并
        重新展开输入框（要换答案点其它候选项）。取消语义只挂在多选上。
        """
        if value:
            already = value in (self._answers.get(question.key) or ())
            self._select_value(question, value, not already)
            return
        key = question.key
        if not question.options:
            # 没有候选项时标记没有意义，整行 = 展开编辑器
            self._enter_editing(key)
            return
        if question.isMultiple and self._custom_on.get(key, False):
            self._custom_on[key] = False
            self._close_custom_editor(key)
            self._refresh_rows()
            return
        self._enter_editing(key)

    def _on_commit(self, question, text: str) -> None:
        key = question.key
        self._custom[key] = text
        self._custom_on[key] = True
        self._answers.pop(key, None)
        self._drafts.pop(key, None)
        self._editing = ""
        row = self._custom_row(key)
        if row is not None:
            row.setEditing(False)
        self._refresh_rows()

    def _select_value(self, question, value: str, checked: bool) -> None:
        key = question.key
        if question.isMultiple:
            picked = list(self._answers.get(key) or ())
            if checked and value not in picked:
                picked.append(value)
            elif not checked and value in picked:
                picked.remove(value)
            self._answers[key] = picked
        else:
            self._answers[key] = [value] if checked else []
        # 选了候选项 -> 取消「自定义选中」（两者互斥，见 _build_answer）
        self._custom_on[key] = False
        # 输入框也一起收起：否则单选下候选项亮了、上一行还摊着个编辑器，
        # 同一题里两个答案并排看着像同时选中了
        self._close_custom_editor(key)
        self._refresh_rows()

    def _custom_row(self, key: str):
        for row in self._rows.get(key, ()):
            if row.isCustom():
                return row
        return None

    def _close_custom_editor(self, key: str) -> None:
        """收起自定义答案的输入框。

        ``_editing`` 是**卡片**层的状态机，行上的 ``setEditing(False)`` 才是
        收起编辑器本身 —— 两边要一起动，否则 ``_refresh_rows`` 会因为
        ``row.isEditing()`` 为真而跳过草稿回填。
        """
        if self._editing != key:
            return
        self._editing = ""
        row = self._custom_row(key)
        if row is not None:
            row.setEditing(False)

    def _commit_editing(self) -> None:
        """落定**正在编辑**的自定义答案（空文本等于没写，``commitEdit`` 自会跳过）。

        对齐 opencode ``next()`` 的 ``if (editing) commitCustom()``：用户敲完
        文字习惯直接点「下一步 / 提交」，不会先按 Enter；不在这里补一次提交，
        那段文字会被静默丢掉（实测 payload 是 ``{}``）。
        """
        if not self._editing:
            return
        row = self._custom_row(self._editing)
        if row is not None:
            row.commitEdit()

    def _enter_editing(self, key: str) -> None:
        self._editing = key
        # 展开编辑器 = 选中自定义（对齐 opencode 的 ``customOpen``）：单选下
        # 候选项随之取消，否则两根圆点同时亮着；多选下也遵守本库的互斥契约。
        self._custom_on[key] = True
        self._answers.pop(key, None)
        row = self._custom_row(key)
        if row is not None:
            # 编辑器里已有内容（Esc 保留的未提交草稿 / 行重建后恢复的草稿）就
            # 不要用已提交值覆盖 —— 那会把用户刚敲的字抹掉。
            if not row.editorText():
                row.setEditorText(self._drafts.get(key) or self._custom.get(key, ""))
            row.setEditing(True)
        self._refresh_rows()

    def _move_focus(self, delta: int) -> None:
        """方向键 / Home / End 在当前题的候选卡之间移动焦点。"""
        rows = self._option_buttons
        if not rows:
            return
        if delta == 0:
            target = 0
        elif delta == 2:
            target = len(rows) - 1
        else:
            target = max(0, min(len(rows) - 1, self._focus_row + delta))
        self._focus_row = target
        rows[target].setFocus()

    def focusedRowIndex(self) -> int:  # noqa: N802
        """当前键盘焦点所在行号（从 0 起）。"""
        return self._focus_row

    def _sync_segments(self) -> None:
        """进度段：只在**多题**时出现。"""
        questions = self._questions()
        while len(self._segments) > len(questions):
            segment = self._segments.pop()
            self._segment_layout.removeWidget(segment)
            segment.setParent(None)
            segment.deleteLater()
        while len(self._segments) < len(questions):
            index = len(self._segments)
            segment = QuestionSegment(index, self._segment_box)
            segment.jumped.connect(self._goto)
            self._segment_layout.addWidget(segment)
            self._segments.append(segment)
        for index, segment in enumerate(self._segments):
            question = questions[index]
            # 与 ``_build_answer`` / ``answers()`` 同一口径（``_current_values``）：
            # 只看 ``_custom`` 有没有文本会把「已取消勾选」的自定义答案判成已答。
            answered = bool(self._current_values(question))
            segment.setState(index == self._tab, answered)
        self._segment_box.setVisible(len(questions) > 1)

    def _sync_footer(self) -> None:
        """页脚：按钮文案随题号变，「上一步」只在有得退时出现。

        配色**不用手工注入** —— 三个都是 :class:`~pyqt6_ela_pro.ela_button.
        ElaButton`，它们自己连 ``themeModeChanged`` 取色（`text` 弱化 /
        `outlined` 中性 / `solid+primary` 主动作）。
        """
        questions = self._questions()
        last = self._tab >= len(questions) - 1
        self._back_button.setVisible(self._tab > 0)
        self._next_button.setText("提交" if last else "下一步")

    def _sync_options_enabled(self) -> None:
        permission = self._permission
        pending = permission is not None and permission.isPending
        enabled = pending and not self._responding
        for rows in self._rows.values():
            for row in rows:
                row.setEnabled(enabled)

    def _go_next(self) -> None:
        """「下一步」：还有题就前进，最后一题就是提交。"""
        questions = self._questions()
        if not questions:
            return
        # 编辑框里的文字先落定：用户很少会先按 Enter 再点按钮
        self._commit_editing()
        if self._tab < len(questions) - 1:
            self._set_tab(self._tab + 1)
            return
        self._submit_answers()

    def _go_back(self) -> None:
        if self._tab <= 0:
            return
        self._set_tab(self._tab - 1)

    def _goto(self, index: int) -> None:
        if not 0 <= index < len(self._questions()):
            return
        self._set_tab(index)

    def _set_tab(self, index: int) -> None:
        """切题的唯一入口（前进 / 后退 / 点进度段都走这里）。"""
        questions = self._questions()
        if not 0 <= index < len(questions) or index == self._tab:
            return
        # 走之前把这一题编辑框里的文字落定（草稿只在「行还在」时才是答案）
        self._commit_editing()
        self._tab = index
        self._focus_row = 0
        self._sync_question()
        self._sync_header(self._permission)
        self._sync_segments()
        self._sync_footer()
        if self._option_buttons:
            self._option_buttons[0].setFocus()

    def _submit_answers(self) -> None:
        self._emit_reply(ElaChatPermissionStatusType.Allowed, self._build_answer(), "")

    def _sync_actions(self) -> None:
        permission = self._permission
        if permission is None or permission.isQuestion:
            self._actions.hide()
            # 问答型不该看到批准型的拒绝理由行（同一张卡换请求类型时尤其明显）
            self._feedback_row.hide()
        else:
            pending = permission.isPending and not self._responding
            self._actions.setVisible(pending)
            for button in self._action_buttons():
                button.setEnabled(pending)
            if permission.isPending:
                # 用 isHidden 判据（isVisible 要求整条父链已显示，未 show 时恒 False）
                self._feedback_row.setVisible(
                    not self._feedback_row.isHidden() and pending
                )
            else:
                self._feedback_row.hide()
        # 问答型的页脚在 responding 期间一起置灰
        enabled = (
            permission is not None and permission.isPending and not self._responding
        )
        for button in (self._dismiss_button, self._back_button, self._next_button):
            button.setEnabled(enabled)
        self._sync_options_enabled()

    def _action_buttons(self) -> tuple:
        """批准型的三个动作按钮（**给宿主与测试用的稳定顺序**）。"""
        return (self._allow_button, self._always_button, self._reject_button)

    def _open_feedback(self) -> None:
        self._feedback_row.show()
        self._feedback_edit.setFocus()

    def _submit_feedback(self) -> None:
        text = self._feedback_edit.toPlainText().strip()
        self._feedback_row.hide()
        self._emit_reply(ElaChatPermissionStatusType.Rejected, "", text)

    def _emit_reply(self, reply: str, answer: str, feedback: str) -> None:
        # 两道闸：responding（回复在途，宿主可置）与 **已落定**（双击的第二下）。
        # 后者才是真正的兜底 —— 落定后动作区已撤掉，但程序化调用仍能打到这里。
        if self._responding or self._permission is None:
            return
        if not self._permission.isPending:
            return
        self._responding = True
        self._sync_actions()
        self.replied.emit(str(reply), str(answer), str(feedback))

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        permission = self._permission
        text = text_color(mode)
        # 标题 = **主文本色**（opencode ``question-header-title``：
        # ``14px / medium / var(--v2-text-text-base)``，与题面同色同级）。
        # 此前 pending 态用 ``blend(base, text, 0.35)`` 染成灰 —— 整条头部于是
        # 弱得读不出，而它恰恰是「现在需要你做什么」这句话本身。绿 / 红只属于
        # 记录卡（``PermissionRecord``），交互卡永远只处理等待态。
        self._title.setTextColor(text)
        self._title.setTextPixelSize(14)
        self._title.setTextWeight(QFont.Weight.Medium)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        # 进度与短标签退到 11px 弱化：它们是注记，不该和标题抢同一层级
        self._progress.setTextColor(muted_color(mode, 0.62))
        self._progress.setTextPixelSize(11)
        self._resources.setTextColor(muted_color(mode, 0.7))
        self._resources.setTextPixelSize(11)
        self._resources.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setTextColor(muted_color(mode, 0.8))
        self._detail.setTextPixelSize(11)
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail_toggle.setColor("primary")
        # 问答型各处的色（题面 / 说明 / 提示 / 选项卡）
        colors = question_colors(mode)
        self._tag.setTextColor(colors["hint"])
        self._tag.setTextPixelSize(11)
        self._tag.setTextFormat(Qt.TextFormat.PlainText)
        self._question_text.setTextColor(colors["ink"])
        self._question_text.setTextPixelSize(14)
        self._question_text.setTextWeight(QFont.Weight.DemiBold)
        for rows in self._rows.values():
            for row in rows:
                row.applyTheme(mode)
        # 交互卡只处理等待态：图标只有「提问」/「工具确认」两种，绿 / 红是记录卡的
        # 语义（``PermissionRecord``），这里不再有第三套分支
        icon = (
            self._QUESTION_ICON
            if permission is not None and permission.isQuestion
            else ElaIconType.IconName.ShieldHalved
        )
        self._icon.setAwesome(icon)
        self._icon.setLightIconColor(blend(base_color(mode), text, 0.5))
        self._icon.setDarkIconColor(blend(base_color(mode), text, 0.5))
        if permission is not None and permission.isQuestion:
            self._sync_footer()

    def paintEvent(self, _event) -> None:  # noqa: N802
        """**不画卡面**。

        本控件住在 :class:`~pyqt6_ela_pro.chat.docks.ElaChatPermissionDock` 里，
        dock 本身就是那张卡（圆角 + 边框）。这里再画一层就成了「卡中卡」：两套圆角
        半径、两条边框、一次额外内缩，视觉上立刻显得脏。
        """

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """卡片级快捷键（**焦点在卡片本体上时**的兜底路径）。

        主路径是候选行的 :attr:`QuestionOptionCard.globalKey` 信号 —— 焦点常驻
        在行上，键盘事件发给行、不冒泡回卡片。
        """
        if not self._handle_shortcut(event):
            super().keyPressEvent(event)

    def _on_global_key(self, action: str) -> None:
        """候选行转上来的卡片级快捷键。

        ``digit:<n>`` 只能在这一层派发：单行只知道自己的序号，不知道总共几行，
        而 ``1``–``9`` 的语义是「选中整组候选卡的第 n 个」（与焦点在哪一行无关）。
        """
        if not self._live():
            return
        if action == "next":
            self._go_next()
        elif action == "back":
            self._go_back()
        elif action == "dismiss":
            self._emit_reply(ElaChatPermissionStatusType.Cancelled, "", "")
        elif action.startswith("digit:"):
            try:
                index = int(action.split(":", 1)[1])
            except ValueError:
                return
            rows = self._option_buttons
            if 0 <= index < len(rows):
                rows[index].activate.emit(rows[index].value())

    def _live(self) -> bool:
        """卡片是否还能接受交互（待答复 + 不在途）。"""
        permission = self._permission
        return permission is not None and permission.isPending and not self._responding

    def _handle_shortcut(self, event) -> bool:
        """在卡片本体上复现同一套快捷键；返回是否已消费。"""
        if not self._live():
            return False
        action = globalKeyAction(event.key(), event.modifiers())
        if action is None:
            return False
        if action == "next":
            self._go_next()
        elif action == "back":
            self._go_back()
        elif action == "dismiss":
            self._emit_reply(ElaChatPermissionStatusType.Cancelled, "", "")
        else:
            self._on_global_key(action)
        return True


class PermissionRecord(_CollapsibleBlock):
    """审批 / 提问的**时间线记录卡**（落定之后留在消息里备查）。

    交互发生在输入区上方的 :class:`~pyqt6_ela_pro.chat.docks.
    ElaChatPermissionDock` —— 那里才是「现在要你动手」的位置；答完就只剩「当时
    问了什么、答了什么」需要留档，所以这里**默认折叠成一行**，点开才看详情，与
    工具调用面板（``> 工具调用 (N)``）完全同一套折叠交互与外观。

    与 :class:`PermissionCard` **不复用同一个 widget**：交互卡是大控件（题面 +
    候选卡 + 页脚），记录卡是一行摘要 + 可展开的详情，两者的排版需求正好相反。
    """

    def __init__(
        self, permission: ElaChatPermission, parent: Optional[QWidget] = None
    ) -> None:
        # **必须先于 super()** —— ``_CollapsibleBlock.__init__`` 末尾会调
        # ``_apply_theme()``，那里已经要读 ``self._permission`` 了。
        self._permission = None
        self._detail_expanded = False
        super().__init__(title="", opened=False, parent=parent, surface=True)
        self._permission = permission

        self._resources = ColorText(self._body)
        self._resources.setTextFormat(Qt.TextFormat.PlainText)
        self._resources.setWordWrap(True)
        self._resources.hide()
        self._body_layout.addWidget(self._resources)

        self._detail = ColorText(self._body)
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setWordWrap(True)
        self._detail.setFont(mono_font(11))
        self._detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._detail.hide()
        self._body_layout.addWidget(self._detail)

        self._detail_toggle = ElaButton(
            "展开全部", variant="link", size="small", parent=self._body
        )
        self._detail_toggle.clicked.connect(self._toggle_detail)
        self._detail_toggle.hide()
        self._body_layout.addWidget(self._detail_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.setPermission(permission)
        self._apply_theme()

    def permission(self) -> Optional[ElaChatPermission]:
        """审批快照。"""
        return self._permission

    def setPermission(self, permission: ElaChatPermission) -> None:  # noqa: N802
        """灌入审批快照并刷新标题与详情。

        **默认折叠**（与 ``ToolGroupPanel`` 的 ``工具调用 (N)`` 同一约定）：记录是
        给人「事后回看」的，不是让人在时间线里读的 —— 一条审批如果自带 200 行
        diff，展开着会把后面所有消息顶出屏幕。详情有点的才给折叠箭头。
        """
        self._permission = permission
        self._detail_expanded = False
        self.setTitle(self._summary_title(permission))
        self._sync_body()
        self.setExpandable(self._has_body())
        self.setOpened(False)

    @staticmethod
    def _summary_title(permission: ElaChatPermission) -> str:
        """一行摘要标题（记录卡默认折叠时唯一可见的东西）。

        问答型**不拿 ``action`` 当标题** —— 提问没有工具名，宿主随手填的
        ``action="question"`` / ``action="ask"`` 会原样漏给用户看（实测渲染出来是
        「已允许一次：question」）。改用第一道题的短标签，答的是什么一眼可见。
        """
        labels = {
            ElaChatPermissionStatusType.Allowed: "已允许一次",
            ElaChatPermissionStatusType.Always: "已允许并记住规则",
            ElaChatPermissionStatusType.Rejected: "已拒绝",
            ElaChatPermissionStatusType.Cancelled: "已作废",
        }
        status = (
            "等待中"
            if permission.isPending
            else labels.get(permission.status, "已处理")
        )
        if permission.isQuestion:
            target = ""
            for question in permission.questions:
                target = question.header or question.question or ""
                if target:
                    break
        else:
            target = permission.action or "工具执行"
        # 一行放不下就截断（省略号由 Qt 自己加，这里只挡超长的一整段）
        if len(target) > 40:
            target = target[:40] + "…"
        return f"{status}：{target}" if target else status

    def _has_body(self) -> bool:
        permission = self._permission
        if permission is None:
            return False
        return bool(
            permission.resources
            or permission.detail
            or permission.feedback
            or permission.answer
        )

    @staticmethod
    def _raw_detail(permission: ElaChatPermission) -> str:
        if permission.isQuestion:
            if permission.detail:
                return permission.detail
            answers = permission.parsedAnswer()
            lines = []
            for question in permission.questions:
                value = answers.get(question.key)
                if value is None:
                    continue
                shown = (
                    "、".join(str(item) for item in value)
                    if isinstance(value, list)
                    else str(value)
                )
                label = question.header or question.question or question.key
                lines.append(f"{label}: {shown}")
            return "\n".join(lines)
        if (
            permission.status == ElaChatPermissionStatusType.Rejected
            and permission.feedback
        ):
            return permission.feedback
        return permission.detail

    def _sync_body(self) -> None:
        permission = self._permission
        if permission is None:
            self._resources.hide()
            self._detail.hide()
            self._detail_toggle.hide()
            return
        resources = [item for item in permission.resources if item]
        if resources and not permission.isQuestion:
            shown = resources[:4]
            text = "\n".join(shown)
            if len(resources) > len(shown):
                text += f"\n… 另有 {len(resources) - len(shown)} 项"
            self._resources.setText(text)
            self._resources.show()
        else:
            self._resources.setText("")
            self._resources.hide()
        detail = self._raw_detail(permission)
        shown, overflow, total = _collapsed_detail(detail, self._detail_expanded)
        self._detail.setText(shown)
        self._detail.setVisible(bool(shown))
        self._detail_toggle.setVisible(overflow)
        self._detail_toggle.setText(
            f"收起（共 {total} 行）"
            if self._detail_expanded
            else f"展开全部（共 {total} 行）"
        )

    def _toggle_detail(self) -> None:
        self._detail_expanded = not self._detail_expanded
        self._sync_body()

    def _apply_theme(self) -> None:
        super()._apply_theme()
        if getattr(self, "_resources", None) is None:
            # ``_CollapsibleBlock.__init__`` 末尾就会调过来，那时子控件还没建。
            # 不挡住就是 AttributeError；而本类通常是在**点击信号的栈上**被构造的
            # （用户点「允许一次」-> replied.emit -> 建记录卡），异常穿过 C++ 边界
            # = 0xC0000409 静默终止。
            return
        mode = self._theme_mode
        permission = self._permission
        if permission is not None and permission.status == (
            ElaChatPermissionStatusType.Rejected
        ):
            accent = statusColor(mode, ElaStatusRoleType.Error)
        elif permission is not None and not permission.isPending:
            accent = statusColor(mode, ElaStatusRoleType.Success)
        else:
            accent = text_color(mode)
        self._title_label.setTextColor(accent)
        self._title_label.setTextPixelSize(12)
        self._title_label.setTextWeight(QFont.Weight.DemiBold)
        self._resources.setTextColor(muted_color(mode, 0.7))
        self._resources.setTextPixelSize(11)
        self._detail.setTextColor(muted_color(mode, 0.8))
        self._detail.setTextPixelSize(11)
        self._detail_toggle.setColor("primary")

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()


class ErrorCard(_ThemeAwareMixin, ElaScrollPageArea):
    """错误卡片（左 danger 竖线 + 图标 + 标题 + 详情 + 动作区）。

    动作区（**手动重试**，对齐 opencode 的 ``session-retry.tsx``）按错误类型
    点亮：

    - 「重试」—— 同参数重发。仅 :data:`RETRYABLE_ERROR_TYPES` 里的类型
      有意义（限流 / 超时 / 网络 / 5xx 这类**换次机会大概率会成功**的错误）；
      参数错误、鉴权失败、内容过滤这类重试只会再失败一次，不给按钮；
    - 「重新生成」—— 换采样重来，对任何错误都有意义，恒显示（复用气泡
      底部已有的 ``regenerateRequested`` 通道，不另开一条）。

    两个动作都只发信号，**不自己发请求** —— 后端怎么重试是宿主的事。
    """

    #: 点击「重试」（由气泡转发成 view / widget 的 ``retryRequested``）
    retryRequested = pyqtSignal()
    #: 点击「重新生成」（与气泡底部同一个语义）
    regenerateRequested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setBorderRadius(8)
        self._message = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 8, 10, 8)
        layout.setSpacing(8)
        self._rail = QWidget(self)
        self._rail.setFixedWidth(2)
        layout.addWidget(self._rail)
        self._icon = ElaIconButton(
            ElaIconType.IconName.TriangleExclamation, 14, 18, 18, self
        )
        self._icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        self._title = ColorText("出错了", self)
        self._label = ColorText(self)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        texts.addWidget(self._title)
        texts.addWidget(self._label)
        layout.addLayout(texts, 1)
        #: 错误类型（决定哪些动作可用；见 :meth:`setMessage`）
        self._error_type = ""
        #: 动作区（默认隐藏，无可用动作时不占位）
        self._actions = ElaChatToolBar(self)
        self._actions.setCompact(True)
        self._actions.setVisible(False)
        layout.addWidget(self._actions, 0, Qt.AlignmentFlag.AlignBottom)
        self.hide()
        self._apply_theme()

    def setMessage(self, message: str, errorType: str = "") -> None:
        """设置错误文本与类型（空文本则隐藏整张卡）。

        :param message: 面向用户的错误文本
        :param errorType: 错误类型（``"RateLimit"`` / ``"Timeout"`` / ...）。
            **只用于决定动作可用性，不拼进文案** —— 早期实现把它格式化成
            ``"[TypeError] ..."`` 塞进 message，类型就此丢失，宿主无法据此
            点亮「重试」还是「换个模型重试」。

        动作区按类型给（:data:`RETRYABLE_ERROR_TYPES` 命中 -> 点亮「重试」，
        任何类型都点亮「重新生成」）；两个都不可用时动作区隐藏。
        """
        self._message = message or ""
        self._error_type = str(errorType or "")
        if not self._message:
            self.hide()
            return
        self._label.setText(self._message)
        self._sync_actions()
        self.show()

    def message(self) -> str:
        """获取错误文本。"""
        return self._message

    def errorType(self) -> str:
        """获取错误类型。"""
        return self._error_type

    def canRetry(self) -> bool:
        """该错误是否可原地重试（同参数重发）。"""
        return self._error_type.lower() in RETRYABLE_ERROR_TYPES

    def _sync_actions(self) -> None:
        """按错误类型刷新动作区（无动作则隐藏，不留空占位）。"""
        self._actions.clear()
        if self.canRetry():
            self._actions.addButton(
                icon=ElaIconType.IconName.RotateRight,
                tooltip="重试",
                key="retry",
                callback=self.retryRequested.emit,
            )
        # 「重新生成」对任何错误都有意义（换采样重来），所以恒有
        if self._message:
            self._actions.addButton(
                icon=ElaIconType.IconName.RotateLeft,
                tooltip="重新生成",
                key="regenerate",
                callback=self.regenerateRequested.emit,
            )
        self._actions.setVisible(self._actions.count() > 0)

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        danger = statusColor(mode, ElaStatusRoleType.Error)
        base = base_color(mode)
        text = text_color(mode)
        setSolidBackground(self._rail, danger)
        self._title.setTextColor(blend(text, danger, 0.35))
        self._title.setTextPixelSize(12)
        self._title.setTextWeight(QFont.Weight.DemiBold)
        self._label.setTextColor(muted_color(mode, 0.75))
        self._label.setTextPixelSize(12)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._icon.setLightIconColor(blend(base, danger, 0.4))
        self._icon.setDarkIconColor(blend(base, danger, 0.4))

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()


__all__ = [
    "MessageHeader",
    "MessageMeta",
    "ReasoningBlock",
    "ThinkingRow",
    "ToolCallCard",
    "ContextToolGroupCard",
    "ToolGroupPanel",
    "AttachmentStrip",
    "StatsBadge",
    "MessageActions",
    "ErrorCard",
    "SteerNotice",
    "CompactionSeparator",
    "PermissionCard",
    "PermissionRecord",
    "RETRYABLE_ERROR_TYPES",
    "avatarPixmap",
    "normalizeAvatarShape",
    "toolIconName",
    "toolSubtitle",
    "toolSubtitleParts",
    "toolArgumentPairs",
    "toolDefaultOpen",
    "toolDefaultOpenCoding",
    "formatDuration",
    "extractReasoningHeading",
]
