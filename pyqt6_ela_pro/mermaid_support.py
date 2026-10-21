"""
Mermaid 渲染支持（可选依赖 `mermaidx <https://pypi.org/project/mermaidx/>`_）。

mermaidx 在进程内用 QuickJS 运行**真实的 mermaid.js v11**（无浏览器 / 无 Node），
再用 resvg 光栅化为 PNG；本模块把它包装成 Qt 友好的异步渲染器：

- ``QThreadPool`` 后台渲染（CPU 密集，避免阻塞 UI 线程）；
- 结果经 ``rendered`` 信号回到 GUI 线程（跨线程 emit 自动排队）；
- ``(code, theme)`` 维度的 LRU 缓存 + in-flight 去重，流式重渲染不重复出图；
- 采用 mermaid ``base`` 主题 + :data:`MERMAID_THEME_VARIABLES` 内置美化配色
  （GitHub 风格，跟随查看器亮/暗主题），可用
  :meth:`ElaMermaidRenderer.setThemeVariables` 覆盖；
- 未安装 mermaidx 时 ``available()`` 为 ``False``，调用方回退为代码块；
- 支持 ``setRenderer(callable)`` 注入自定义渲染器（测试或替换后端）。

用法::

    renderer = ElaMermaidRenderer(parent)
    known, image = renderer.lookup(code, "dark")
    renderer.request(code, "dark", lambda img: ...)   # 结果回调（GUI 线程）
"""

from __future__ import annotations

import math
import re
import warnings
import weakref
from collections import OrderedDict
from typing import Callable, Optional

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal
from PyQt6.QtGui import QImage

__all__ = [
    "ElaMermaidRenderer",
    "mermaidx_available",
    "mermaidx_error",
    "MERMAID_THEME_VARIABLES",
]

#: 渲染使用的 mermaid 基准主题（搭配 themeVariables 自定义配色）
_MERMAID_BASE_THEME = "base"
#: 内置美化主题变量（GitHub 风格；「light」/「dark」对应查看器主题）
MERMAID_THEME_VARIABLES = {
    "light": {
        "fontSize": "14px",
        "primaryColor": "#F6F8FA",
        "primaryBorderColor": "#C9D1D9",
        "primaryTextColor": "#1F2328",
        "secondaryColor": "#EEF2F7",
        "tertiaryColor": "#FFFFFF",
        "lineColor": "#57606A",
        "textColor": "#1F2328",
        "edgeLabelBackground": "#F8F8F8",
        "clusterBkg": "#FFFFFF",
        "clusterBorder": "#D0D7DE",
        "titleColor": "#1F2328",
        "noteBkgColor": "#FFF8C5",
        "noteTextColor": "#1F2328",
        "noteBorderColor": "#D4A72C",
        "actorBkg": "#F6F8FA",
        "actorBorder": "#C9D1D9",
        "actorTextColor": "#1F2328",
        "actorLineColor": "#C9D1D9",
        "signalColor": "#57606A",
        "signalTextColor": "#1F2328",
        "labelBoxBkgColor": "#F6F8FA",
        "labelBoxBorderColor": "#C9D1D9",
        "labelTextColor": "#1F2328",
        "loopTextColor": "#1F2328",
        "activationBorderColor": "#C9D1D9",
        "activationBkgColor": "#EEF2F7",
    },
    "dark": {
        "fontSize": "14px",
        "primaryColor": "#21262D",
        "primaryBorderColor": "#3D444D",
        "primaryTextColor": "#E6EDF3",
        "secondaryColor": "#30363D",
        "tertiaryColor": "#161B22",
        "lineColor": "#8B949E",
        "textColor": "#E6EDF3",
        "edgeLabelBackground": "#161B22",
        "clusterBkg": "#161B22",
        "clusterBorder": "#30363D",
        "titleColor": "#E6EDF3",
        "noteBkgColor": "#3B2E00",
        "noteTextColor": "#E6EDF3",
        "noteBorderColor": "#9E6A03",
        "actorBkg": "#21262D",
        "actorBorder": "#3D444D",
        "actorTextColor": "#E6EDF3",
        "actorLineColor": "#3D444D",
        "signalColor": "#8B949E",
        "signalTextColor": "#E6EDF3",
        "labelBoxBkgColor": "#21262D",
        "labelBoxBorderColor": "#3D444D",
        "labelTextColor": "#E6EDF3",
        "loopTextColor": "#E6EDF3",
        "activationBorderColor": "#3D444D",
        "activationBkgColor": "#30363D",
    },
}

#: 布局美化参数（曲线走向与间距）
_FLOWCHART_CONFIG = {
    "curve": "basis",
    "nodeSpacing": 40,
    "rankSpacing": 50,
    "padding": 10,
}
_SEQUENCE_CONFIG = {
    "mirrorActors": False,
    "actorMargin": 60,
    "messageMargin": 32,
    "boxMargin": 8,
}

#: 缓存条数上限
_CACHE_CAP = 32
#: 失败哨兵（缓存失败结果，避免流式重渲染反复触发）
_FAILED = object()

#: 预热用的极小图（只为启动 mermaid.js 引擎）
_PREWARM_CODE = "graph LR\n  A-->B"
#: 光栅化超采样倍率上限 / 下限（按目标显示宽度自适应）
_MAX_ZOOM = 2.0
_MIN_ZOOM = 0.5

_VIEWBOX_RE = re.compile(
    r"viewBox\s*=\s*[\"']\s*[\d.+-]+\s+[\d.+-]+\s+([\d.]+)\s+([\d.]+)"
)
_SIZE_RE = re.compile(
    r"\bwidth\s*=\s*[\"']([\d.]+)(?:px)?[\"'][^>]*\bheight\s*=\s*[\"']([\d.]+)(?:px)?[\"']"
)


def svg_size(svg: str) -> tuple:
    """从 SVG 文本提取原始宽高（``viewBox`` 优先，其次 width/height），失败返回 ``(0.0, 0.0)``。"""
    match = _VIEWBOX_RE.search(svg or "")
    if match:
        return float(match.group(1)), float(match.group(2))
    match = _SIZE_RE.search(svg or "")
    if match:
        return float(match.group(1)), float(match.group(2))
    return 0.0, 0.0


def adaptive_zoom(
    svg: str, max_px: Optional[float], default: float = _MAX_ZOOM
) -> float:
    """按目标显示宽度算光栅化倍率（窄图超采样、宽图降采样），结果夹在
    ``[_MIN_ZOOM, _MAX_ZOOM]``；``max_px`` 缺省或非正时返回 ``default``。
    """
    if not max_px or max_px <= 0:
        return default
    natural_w, _ = svg_size(svg)
    if natural_w <= 0:
        return default
    needed = (float(max_px) * default) / natural_w
    return max(_MIN_ZOOM, min(default, needed))


#: mermaidx 可用性探测缓存（进程级）
_AVAILABLE: Optional[bool] = None
#: mermaidx 导入失败原因（可用时为 None）
_AVAILABLE_ERROR: Optional[str] = None


def _build_config(theme: str, themeVariables: Optional[dict] = None) -> dict:
    """构造 mermaid 初始化配置（base 主题 + 自定义 themeVariables + 布局）。"""
    variables = dict(
        MERMAID_THEME_VARIABLES.get(theme, MERMAID_THEME_VARIABLES["light"])
    )
    if themeVariables:
        variables.update(themeVariables)
    return {
        "theme": _MERMAID_BASE_THEME,
        "themeVariables": variables,
        "flowchart": dict(_FLOWCHART_CONFIG),
        "sequence": dict(_SEQUENCE_CONFIG),
    }


def mermaidx_available() -> bool:
    """探测可选依赖 mermaidx 是否可用（结果缓存）。"""
    global _AVAILABLE, _AVAILABLE_ERROR
    if _AVAILABLE is None:
        try:
            import mermaidx  # noqa: F401
        except Exception as exc:
            _AVAILABLE = False
            _AVAILABLE_ERROR = f"{type(exc).__name__}: {exc}"
        else:
            _AVAILABLE = True
            _AVAILABLE_ERROR = None
    return _AVAILABLE


def mermaidx_error() -> Optional[str]:
    """mermaidx 不可用时的导入错误信息（可用时为 ``None``）。"""
    mermaidx_available()
    return _AVAILABLE_ERROR


def _clamp_zoom_to_budget(zoom: float, view_w: float, view_h: float) -> Optional[float]:
    """把 ``zoom`` 压到「输出仍在预算内」的最小值；压不动则返回 ``None``。

    ``zoom`` 越小输出越小，所以按面积开方缩放即可；下限是 ``_MIN_ZOOM`` ——
    再小会糊得看不清，那时宁可报「渲染不出来」（调用方降级成代码卡片），
    也不要默默给一张糊掉的图。
    """
    if not (math.isfinite(zoom) and math.isfinite(view_w) and math.isfinite(view_h)):
        return None
    area = view_w * view_h * zoom * zoom
    if _raster_budget_ok(view_w * zoom, view_h * zoom):
        return zoom
    scale = math.sqrt(_MAX_RASTER_PIXELS / area) if area > 0 else 0.0
    candidate = max(zoom * scale, _MIN_ZOOM)
    if _raster_budget_ok(view_w * candidate, view_h * candidate):
        return candidate
    # 单边也超了才算彻底不可行
    if (
        view_w * _MIN_ZOOM <= _MAX_RASTER_DIM
        and view_h * _MIN_ZOOM <= _MAX_RASTER_DIM
        and view_w * _MIN_ZOOM * view_h * _MIN_ZOOM <= _MAX_RASTER_PIXELS
    ):
        return _MIN_ZOOM
    return None


def _render_with_mermaidx(
    code: str,
    theme: str,
    themeVariables: Optional[dict] = None,
    max_px: Optional[float] = None,
) -> Optional[QImage]:
    """用 mermaidx 渲染 Mermaid 源码为 QImage（2x 超采样，按需自适应）。

    采用 mermaid ``base`` 主题 + :data:`MERMAID_THEME_VARIABLES` 美化配色
    （可经 ``themeVariables`` 覆盖）；mermaidx 自带 PNG 管线会强制使用
    内置 DejaVu 字体（不含 CJK，中文变方块），因此优先取 SVG 后用
    ``resvg_py`` 光栅化（默认加载系统字体，可回退中文字体）；直调失败时
    退回 mermaidx 的 PNG 输出。两者都失败时抛出异常（由调用方记录到
    :meth:`ElaMermaidRenderer.lastError`，便于排查）。

    :param max_px: 目标显示宽度；给出时按图宽自适应倍率（宽图降采样，
        避免超大图在固定 2x 下耗费光栅化时间与内存）
    """
    import mermaidx

    diagram = mermaidx.render(
        code,
        theme=_MERMAID_BASE_THEME,
        config=_build_config(theme, themeVariables),
    )
    svg = diagram.svg()
    try:
        import resvg_py

        zoom = adaptive_zoom(svg, max_px)
        # 输出预算：viewBox 规模 x zoom^2 才是真正要分配的光栅尺寸
        view_w, view_h = svg_size(svg)
        if view_w > 0 and view_h > 0:
            zoom = _clamp_zoom_to_budget(zoom, view_w, view_h)
            if zoom is None:
                raise RuntimeError(
                    f"Mermaid 图尺寸超出光栅化预算（{view_w:.0f}x{view_h:.0f}）"
                )
        data = resvg_py.svg_to_bytes(
            svg_string=svg,
            zoom=zoom,
            sans_serif_family="Microsoft YaHei",
        )
    except Exception as exc:
        first_error = f"{type(exc).__name__}: {exc}"
        try:
            data = diagram.png(scale=2.0)
        except Exception:
            raise RuntimeError(
                f"Mermaid 渲染失败（resvg 直调与 mermaidx PNG 均不可用）：{first_error}"
            ) from exc
    image = QImage.fromData(bytes(data), "PNG")
    if image.isNull():
        raise RuntimeError("Mermaid 渲染输出无法解码为图片")
    return image


class _RenderTask(QRunnable):
    """后台渲染任务（在 QThreadPool 线程中执行）。"""

    def __init__(self, renderer: "ElaMermaidRenderer", code: str, theme: str):
        super().__init__()
        # **弱引用**：渲染器通常是viewer 的子对象（``ElaMermaidRenderer(parent=self)``），
        # 宿主一销毁它就跟着 ``deleteChildren()`` 走。持强引用只会让 Python
        # 包装器活过 C++ 对象，于是 ``emit`` 打在已释放对象上抛 RuntimeError
        # —— 而这正好发生在 ``QRunnable::run()`` 里（工作线程）。
        self._renderer = weakref.ref(renderer)
        self._code = code
        self._theme = theme
        # 发起时的代次：回来时若已推进（``clearCache``），结果整条丢弃
        self._generation = renderer.currentGeneration()

    def run(self) -> None:  # pragma: no cover - 线程内执行
        error = None
        image = None
        renderer = self._renderer()
        if renderer is None:
            return  # 渲染器已随宿主销毁：没有接收方，不必 emit
        try:
            render = renderer._render_function()
            if render is not None:
                image = render(self._code, self._theme)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        try:
            renderer._notify(self._code, self._theme, image, error, self._generation)
        except RuntimeError:
            # 渲染在途中宿主被关掉了 —— 静默丢弃，这是正常路径不是错误
            pass


class _PrewarmTask(QRunnable):
    """后台预热任务：提前启动 mermaid.js 引擎，隐藏冷启动耗时。"""

    def __init__(self, renderer: "ElaMermaidRenderer"):
        super().__init__()
        self._renderer = weakref.ref(renderer)

    def run(self) -> None:  # pragma: no cover - 线程内执行
        renderer = self._renderer()
        if renderer is None:
            return
        try:
            render = renderer._render_function()
            if render is not None:
                render(_PREWARM_CODE, renderer._prewarm_theme())
        except Exception:
            pass


#: 光栅化输出的尺寸/像素预算。``zoom`` 夹在 [_MIN_ZOOM, _MAX_ZOOM]，
#: 但那管不住**总量**：SVG 的viewBox 由 mermaid 按图规模算，一个 5000 节点的
#: ``graph TD`` 可以到十万量级，zoom=0.5 时 resvg 就要分配
#: 50000x50000x4B ~= 10 GB。模型输出不可信 —— 一段 mermaid 不该能吃光内存。
#: 与 ``math_lite`` 的 ``_MAX_DIM`` / ``_MAX_PIXELS`` 同一套理由。
_MAX_RASTER_DIM = 20000
_MAX_RASTER_PIXELS = 64_000_000  # ARGB32 = 4B/px -> 256 MiB 上限


def _raster_budget_ok(width: float, height: float) -> bool:
    """光栅化输出尺寸是否在预算内（非有限值一律拒绝）。"""
    if not (math.isfinite(width) and math.isfinite(height)):
        return False
    if width <= 0 or height <= 0:
        return False
    if width > _MAX_RASTER_DIM or height > _MAX_RASTER_DIM:
        return False
    return width * height <= _MAX_RASTER_PIXELS


#: 销毁时等待在途渲染的上限（毫秒）。超时放线程自己结束 —— runnable 侧已
#: 改成弱引用持有渲染器，收尾会自行短路，不会打到已释放对象。
_POOL_SHUTDOWN_MS = 300


class ElaMermaidRenderer(QObject):
    """Mermaid 异步渲染器（可选依赖 ``mermaidx``，``cache_cap <= 0`` 表示不缓存）。"""

    #: 渲染完成（参数：源码、主题、``QImage`` 或 ``None`` 表示失败、失败原因）。
    #: **只发「当前代次」的结果** —— 已作废的在途任务由内部信号丢弃，走不到这里。
    rendered = pyqtSignal(str, str, object, str)

    #: 内部：工作线程 → GUI 线程，多带一个「发起代次」用于作废判定（不是公共契约）
    _renderedInternal = pyqtSignal(str, str, object, str, int)

    def __init__(
        self,
        cache_cap: int = _CACHE_CAP,
        themeVariables: Optional[dict] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._cache: "OrderedDict[tuple, object]" = OrderedDict()
        self._cache_cap = max(0, int(cache_cap))
        self._inflight: set = set()
        self._callbacks: dict = {}
        #: 渲染代次：``clearCache``（换渲染器 / 换 themeVariables）时自增，用来作废
        #: **在途**任务的回填。没有它，旧任务回来后会写缓存、还会 ``pop`` 掉同一
        #: key 上**新**请求的回调 —— 新请求拿到旧渲染器的图，而它自己的真图因为
        #: 回调已被消费而永远送不到。
        self._generation = 0
        self._override: Optional[Callable] = None
        self._last_error: Optional[str] = None
        self._logged_errors: set = set()
        #: 目标显示宽度（用于自适应光栅化倍率；``None`` 表示固定 2x）
        self._max_image_width: Optional[float] = None
        #: 引擎预热状态
        self._prewarmed = False
        #: 每套主题的 mermaid themeVariables（默认内置美化配色，可覆盖）
        self._theme_variables = {
            name: dict(values) for name, values in MERMAID_THEME_VARIABLES.items()
        }
        if themeVariables:
            for name, values in themeVariables.items():
                self._theme_variables.setdefault(name, {}).update(values)
        # **不要 parent=self**：``~QThreadPool`` 会等所有 runnable 跑完才返回。
        # 池是渲染器的 QObject 子对象时，销毁渲染器（= 宿主关窗口）会在 GUI
        # 线程同步阻塞到当前渲染结束 —— mermaidx 是进程内QuickJS 跑真实
        # mermaid.js，大图渲染是秒级到十秒级，不是「卡一下」。
        # 改成独立对象 + ``_cleanup`` 显式收，走「有上限的等待」而不是无限等。
        #
        # 已知取舍：宿主走 C++ 父链销毁（``deleteChildren`` 把渲染器带走）时，
        # Python 包装器被回收的瞬间 ``~QThreadPool`` 仍会等到在途渲染结束才
        # 返回（弱引用只保证收尾不碰死对象，缩短不了那一次渲染）。要彻底避免
        # 得把池提升为进程级；常规路径用 ``deleteLater()`` 已是有界等待。
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(2)
        self._renderedInternal.connect(self._on_rendered)

    # -- 主题 --------------------------------------------------------------

    def setThemeVariables(self, theme: str, variables: Optional[dict] = None) -> None:
        """覆盖指定主题（``"light"`` / ``"dark"``）的 mermaid ``themeVariables``，
        ``None`` 恢复内置美化配色。
        """
        if variables is None:
            self._theme_variables[theme] = dict(
                MERMAID_THEME_VARIABLES.get(theme, MERMAID_THEME_VARIABLES["light"])
            )
        else:
            self._theme_variables.setdefault(theme, {}).update(variables)
        self.clearCache()

    def themeVariables(self, theme: str) -> dict:
        """获取指定主题当前生效的 themeVariables 副本。"""
        return dict(self._theme_variables.get(theme, {}))

    # -- 配置 --------------------------------------------------------------

    def setRenderer(self, renderer: Optional[Callable]) -> None:
        """设置自定义渲染函数 ``(code, theme) -> QImage | None``，``None`` 回到内置后端。"""
        self._override = renderer
        self.clearCache()

    def renderer(self) -> Optional[Callable]:
        """获取自定义渲染函数（未设置返回 ``None``）。"""
        return self._override

    def available(self) -> bool:
        """当前是否有可用的渲染后端（不可用时可在 :meth:`lastError` 查看原因）。"""
        render = self._render_function()
        if render is None and self._last_error is None:
            self._last_error = (
                mermaidx_error() or "未安装可用的 Mermaid 渲染依赖（mermaidx）"
            )
        return render is not None

    def lastError(self) -> Optional[str]:
        """最近一次渲染失败原因（成功或尚未渲染时为 ``None``）。"""
        return self._last_error

    # -- 性能相关 ----------------------------------------------------------

    def setMaxImageWidth(self, width: Optional[float]) -> None:
        """设置目标显示宽度（像素）。

        内置后端据此自适应光栅化倍率：窄图仍 2x 超采样，宽图自动降采样，
        避免超大图在固定 2x 下耗费时间与内存。``None`` 恢复固定 2x。
        自定义渲染函数（:meth:`setRenderer`）不受影响。
        """
        self._max_image_width = float(width) if width and width > 0 else None

    def maxImageWidth(self) -> Optional[float]:
        """获取当前目标显示宽度（未设置返回 ``None``）。"""
        return self._max_image_width

    def prewarm(self) -> bool:
        """后台预热渲染引擎（隐藏首次渲染的引擎冷启动耗时）。

        仅在未设置自定义渲染函数且 mermaidx 可用时生效；幂等，重复调用只有
        第一次真正提交任务，且预热结果不进入缓存。

        :returns: 是否提交了预热任务
        """
        if self._prewarmed or self._override is not None:
            return False
        if not mermaidx_available():
            return False
        self._prewarmed = True
        self._pool.start(_PrewarmTask(self))
        return True

    def _prewarm_theme(self) -> str:
        """预热使用的主题键（优先 ``light``）。"""
        if "light" in self._theme_variables:
            return "light"
        return next(iter(self._theme_variables), "light")

    def _render_function(self) -> Optional[Callable]:
        if self._override is not None:
            return self._override
        if mermaidx_available():
            variables = self._theme_variables
            return lambda code, theme: _render_with_mermaidx(
                code, theme, variables.get(theme), self._max_image_width
            )
        return None

    # -- 缓存 / 请求 --------------------------------------------------------

    def lookup(self, code: str, theme: str):
        """查缓存，返回 ``(known, image)``；``known=True`` 且 ``image=None`` = 此前渲染失败。"""
        key = (code, theme)
        if key not in self._cache:
            return False, None
        value = self._cache[key]
        self._cache.move_to_end(key)
        return (True, None) if value is _FAILED else (True, value)

    def lookupAnyTheme(self, code: str, theme: str):
        """查询同一源码在**其它主题**下的缓存（用于主题切换即时降级显示）。

        :returns: ``(known, other_theme, image)``；``known=True, image=None``
            表示该主题此前渲染失败；未命中返回 ``(False, None, None)``
        """
        for key in reversed(self._cache):
            key_code, key_theme = key
            if key_code != code or key_theme == theme:
                continue
            value = self._cache[key]
            self._cache.move_to_end(key)
            return True, key_theme, (None if value is _FAILED else value)
        return False, None, None

    def request(
        self, code: str, theme: str, callback: Optional[Callable] = None
    ) -> None:
        """请求渲染（命中缓存时同步回调；否则后台执行并去重）。"""
        key = (code, theme)
        known, image = self.lookup(code, theme)
        if known:
            if callback is not None:
                callback(image)
            return
        render = self._render_function()
        if render is None:
            if callback is not None:
                callback(None)
            return
        if callback is not None:
            self._callbacks.setdefault(key, []).append(callback)
        if key in self._inflight:
            return
        self._inflight.add(key)
        self._pool.start(_RenderTask(self, code, theme))

    def clearCache(self) -> None:
        """清空渲染缓存与待回调，**并作废在途任务**（代次 +1）。

        **在途回调以 ``None`` 交付而不是直接丢掉。** 模块 docstring 把
        ``request(..., lambda img: ...)`` 当作对外用法，而 ``setRenderer()`` /
        ``setThemeVariables()`` 都会走到这里 —— 渲染在途时调用它们，宿主的
        ``cb`` 之前是**永远不会被调用**（不是被取消，是消失），那是个静默破坏
        契约的坑，调用方只能靠超时兜。

        在途任务的结果**整条丢弃**（不写缓存、不触发回调）：它是用旧的渲染器 /
        旧的 themeVariables 渲染的，写回缓存等于「换后端」之后继续用旧图。
        """
        self._generation += 1
        self._cache.clear()
        for key, callbacks in list(self._callbacks.items()):
            for callback in list(callbacks):
                try:
                    callback(None)
                except Exception:
                    pass
            self._callbacks.pop(key, None)
        # 在途的 key 一并清掉：否则某个 mermaid 图卡住后，该 (code, theme) 的
        # 每次 request 都只往 _callbacks 追加然后 return，列表无界增长。
        # 作废靠代次判定，不靠这个集合 —— 否则旧任务回来时会顺手 discard 掉新任务
        # 刚登记的同一个 key。
        self._inflight.clear()

    def deleteLater(self) -> None:  # noqa: N802 (Qt 命名)
        """销毁前有界地收线程池。

        池刻意**不是**渲染器的子对象（``~QThreadPool`` 会等所有 runnable 跑完
        才返回，当子对象时销毁渲染器会在 GUI 线程无限期阻塞到当前渲染结束），
        所以销毁路径必须自己收，且**必须有上限** —— 同样是 mermaidx 在跑
        真实 mermaid.js，不能让关窗口变成无限等待。超出上限就放线程自己结束
        （runnable 侧已经改成弱引用，收尾会自行短路）。
        """
        pool = getattr(self, "_pool", None)
        if pool is not None:
            try:
                pool.clear()
                pool.waitForDone(_POOL_SHUTDOWN_MS)
            except RuntimeError:
                pass
        super().deleteLater()

    # -- 内部 --------------------------------------------------------------

    def currentGeneration(self) -> int:  # noqa: N802 (与 Qt 命名一致)
        """当前渲染代次（``_RenderTask`` 发起时记录，回来时比对）。"""
        return self._generation

    def _notify(
        self, code: str, theme: str, image, error: Optional[str] = None, generation: int = 0
    ) -> None:  # 工作线程
        self._renderedInternal.emit(code, theme, image, error or "", int(generation))

    def _on_rendered(
        self, code: str, theme: str, image, error: str = "", generation: int = 0
    ) -> None:  # GUI 线程
        if int(generation) != self._generation:
            # 代次已推进（clearCache 换过渲染器 / themeVariables）：这张图是用旧
            # 后端渲的，整条丢弃 —— 不写缓存、不碰回调、不清 _inflight
            # （那个 key 可能属于新一代的在途任务）。
            return
        key = (code, theme)
        self._inflight.discard(key)
        self._last_error = error or None
        if error and error not in self._logged_errors:
            self._logged_errors.add(error)
            # 库内告警走 warnings（宿主管不了 stdout/stderr；测试 / 无控制台
            # 环境下也看不到），同一错误只提示一次
            warnings.warn(
                f"Mermaid 渲染失败：{error}",
                RuntimeWarning,
                stacklevel=2,
            )
        if self._cache_cap > 0:
            self._cache[key] = image if image is not None else _FAILED
            while len(self._cache) > self._cache_cap:
                self._cache.popitem(last=False)
        for callback in self._callbacks.pop(key, []):
            try:
                callback(image)
            except Exception:
                pass
        # 内部信号处理完再对外发：宿主的槽看到的已经是「缓存已更新、回调已交付」
        # 之后的状态（`_on_rendered` 在构造期最先连接，直接发会排在宿主槽前面）。
        self.rendered.emit(code, theme, image, error)
