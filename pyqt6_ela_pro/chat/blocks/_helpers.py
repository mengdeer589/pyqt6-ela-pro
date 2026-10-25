"""工具卡 / 思考标题等纯函数与常量（无 Qt 控件依赖）。（``pyqt6_ela_pro.chat`` 内部模块）。"""

from __future__ import annotations


import itertools
import math
import re
from pathlib import Path
from typing import Optional, Union

from PyQt6.QtCore import QSize
from PyQt6.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QImage,
    QPixmap,
)
from PyQt6ElaWidgetTools import (
    ElaIcon,
    ElaIconType,
)

from ...svg_icon import svg_to_pixmap
from .. import _json
from ..message import (
    ElaChatRoleType,
)
from ..renderers import (
    parseToolArguments,
)

AVATAR_SIZE = 30
AVATAR_RADIUS = 8
AVATAR_SHAPES = ("circle", "rounded", "square")
AVATAR_DEFAULT_SHAPE = "circle"
ElaChatAvatarSource = Union[str, bytes, QPixmap, QImage, QIcon]
ROLE_ICONS = {
    ElaChatRoleType.User: ElaIconType.IconName.User,
    ElaChatRoleType.Assistant: ElaIconType.IconName.Robot,
    ElaChatRoleType.System: ElaIconType.IconName.Comment,
}
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
CONTEXT_TOOLS = ("read", "glob", "grep", "list")
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
_IMAGE_THUMB_SIZE = (58, 46)
PREVIEW_MAX_CHARS = 72
DETAIL_COLLAPSED_LINES = 8
DETAIL_MAX_LINE_CHARS = 400
REASONING_FLUSH_INTERVAL_MS = 40
CARD_V_PADDING = 9
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


SHELL_TOOLS = ("bash", "shell", "run", "exec", "terminal")
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


_PREVIEW_ITEMS = 8
_ELIDE_SOURCE_MAX = 160


def _elide_source(text: str, cap: int, fm: QFontMetrics) -> str:
    """按目标像素宽度限制 ``elidedText`` 的源串长度。

    展示区只有 ``cap`` 像素宽，源串再长也不会多显示一个字符；按平均字符宽
    反推所需字符数，避免把 4KB 的 shell command 整串喂给字体测量。
    """
    if len(text) <= 64:
        return text
    needed = int(max(0, cap) / max(1.0, float(fm.averageCharWidth()))) + 8
    return text[: min(len(text), max(48, min(_ELIDE_SOURCE_MAX, needed)))]


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
