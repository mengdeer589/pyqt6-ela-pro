"""
内部工具模块。

包含仅供内部使用的工具函数，不应作为公共API直接调用。
"""

from __future__ import annotations

import sys
import traceback
import unicodedata
from functools import wraps
from typing import Any, Callable, Optional, Protocol, TypeVar, runtime_checkable

from PyQt6 import sip
from PyQt6.QtCore import QLocale, QObject, QPoint, QRect, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QRawFont,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QWidget,
)
from PyQt6ElaWidgetTools import ElaThemeType, eTheme

#: ``QWIDGETSIZE_MAX``（Qt5 的绑定从 QtWidgets 导出）；Qt6 的 PyQt6 / PySide6 都已移除，本地定义。
WIDGET_SIZE_MAX = 16777215

__all__ = [
    "single_shot_on",
    "catch_error",
    "connect_theme_signal",
    "disconnect_theme",
    "disconnect_theme_signal",
    "hideComboboxPopup",
    "is_deleted",
    "load_lazy_pinyin",
    "safe_call",
    "system_cjk_font_family",
    "to_logical_pos",
    "applyMissingGlyphFonts",
    "glyphCovers",
    "missingGlyphFont",
]

#: 缺字形兜底候选字体（单族；顺序即优先级）。
#: Segoe UI Symbol 是 Win7 自带的符号字体；Cambria Math 补组合重音；
#: Segoe UI Emoji 只在 Win8+ 存在（缺失时自动跳过）。
MISSING_GLYPH_FONT_CANDIDATES = (
    "Segoe UI Symbol",
    "Cambria Math",
    "Segoe UI Emoji",
)

_glyph_raw_fonts: dict[str, Optional[QRawFont]] = {}
_glyph_coverage: dict[tuple[str, str], bool] = {}
_glyph_fallback: dict[str, Optional[str]] = {}
_font_family_set: Optional[set] = None
#: 覆盖缓存上限（超大 / 多语言文档防无界增长；清空后重算即可）
_GLYPH_COVERAGE_MAX = 20000

F = TypeVar("F", bound=Callable[..., Any])


def is_deleted(obj: Any) -> bool:
    """对象是否已销毁（**``None`` 也算已销毁**）。

    不能直接用 ``sip.isdeleted(obj)``：``sip.isdeleted(None)`` 返回 **False**，
    写反会让「字段还是 None」走到使用已销毁对象的路径上。库内所有存活判断统一走本函数。
    非 sip 包装的普通 Python 对象按「存活」处理（``TypeError`` 兜底），与 shiboken
    的 ``isValid()`` 对任意 Python 对象返回 True 同口径。
    """
    if obj is None:
        return True
    try:
        return bool(sip.isdeleted(obj))
    except (RuntimeError, TypeError):
        return False


_lazy_pinyin = None
_lazy_pinyin_probed = False


def load_lazy_pinyin():
    """返回 ``pypinyin.lazy_pinyin`` 实现（**首次调用才导入**）。

    ``pypinyin`` 导入即加载约 50 MiB 拼音字典，不能在任何 ``import`` 期付掉；
    未安装时返回 ``None``（调用方降级为不参与拼音匹配 / 排序）。
    """
    global _lazy_pinyin, _lazy_pinyin_probed
    if not _lazy_pinyin_probed:
        _lazy_pinyin_probed = True
        try:
            from pypinyin import lazy_pinyin as impl
        except ImportError:  # pragma: no cover - 声明依赖，仅防御
            impl = None
        _lazy_pinyin = impl
    return _lazy_pinyin


_cjk_ui_font_family = None
_cjk_ui_font_probed = False


def system_cjk_font_family():
    """中文系统下可用的 CJK UI 字体族（其它系统 / 字体缺失返回 ``None``，进程级缓存）。

    Win7 上非 CJK 主字体渲染 CJK 内容走逐字形 fallback shaping（~3ms/行），且
    只要走过一次就进程级毒化其后一切文本绘制（10~250×，见「下游项目反馈bug.md」
    §2/§3），默认字体收成**单族** CJK 字体是库侧可控的**方向之一**。只认准
    「中文系统 + Microsoft YaHei」—— 唯一实测验证过的组合；其它 CJK 语言与
    字体不做推断。

    **第二个方向：主字体是 CJK、但文本含它 cmap 里没有的符号**（LLM 输出常带
    ↔ / ⇒ / □ / √ 等）同样走逐字形 fallback 并进程级毒化。雅黑对这些符号的
    覆盖并不完整（U+2610/2611 勾选框、U+25B8/25BE 折叠箭头都不在），所以
    **库自产并写进 QTextDocument 的标记必须选雅黑已有的字形** —— 任务列表用
    U+25A1/U+25A0（□/■），折叠标记用 ``+``/``−``。任意用户内容仍可能带缺字
    符号：查看器默认用 :func:`applyMissingGlyphFonts` 给缺字片段套**单族**符号
    字体（不改文本、复制保真，可经 ``setMissingGlyphFallbackEnabled`` 关闭）；
    终端等其它 QTextDocument 也可复用该工具（见 bug #20）。

    ``QFontDatabase.families()`` 慢且进程内不变，结果必须进程级缓存；调用点
    都在 QApplication 之后（控件构造路径），**禁止**在 import 期调用（无
    QGuiApplication 时查询字体会进程级 abort）。
    """
    global _cjk_ui_font_family, _cjk_ui_font_probed
    if not _cjk_ui_font_probed:
        _cjk_ui_font_probed = True
        try:
            if QLocale.system().language() == QLocale.Language.Chinese:
                if "Microsoft YaHei" in QFontDatabase.families():
                    _cjk_ui_font_family = "Microsoft YaHei"
        except Exception:
            _cjk_ui_font_family = None
    return _cjk_ui_font_family


def _fontFamilySet() -> set:
    """可用字体族集合（进程级缓存；字体安装变化不重扫）。"""
    global _font_family_set
    if _font_family_set is None:
        try:
            _font_family_set = set(QFontDatabase.families())
        except Exception:  # noqa: BLE001 —— 无 GUI 时查询字体不能把调用方带崩
            _font_family_set = set()
    return _font_family_set


def _glyphRawFont(family: str) -> Optional[QRawFont]:
    """字体族 → 原始字体（进程级缓存；字体不存在返回 ``None``）。"""
    if family in _glyph_raw_fonts:
        return _glyph_raw_fonts[family]
    raw: Optional[QRawFont] = None
    try:
        if family and family in _fontFamilySet():
            candidate = QRawFont.fromFont(QFont(family))
            if candidate is not None and candidate.isValid():
                raw = candidate
    except Exception:  # noqa: BLE001
        raw = None
    _glyph_raw_fonts[family] = raw
    return raw


def glyphCovers(family: str, char: str) -> bool:
    """``family`` 的 cmap 是否真含 ``char``（按 (族, 字符) 进程级缓存）。

    用 ``QRawFont.supportsCharacter`` 而不是 ``QFontMetrics.inFont``：后者在
    有字体回退时对缺字形字符也返回 ``True``（实测雅黑 + U+2610），判不出
    fallback。
    """
    key = (family, char)
    cached = _glyph_coverage.get(key)
    if cached is not None:
        return cached
    raw = _glyphRawFont(family)
    ok = False
    if raw is not None:
        try:
            ok = bool(raw.supportsCharacter(ord(char)))
        except Exception:  # noqa: BLE001
            ok = False
    _glyph_coverage[key] = ok
    if len(_glyph_coverage) >= _GLYPH_COVERAGE_MAX:
        _glyph_coverage.clear()
        _glyph_coverage[key] = ok
    return ok


def missingGlyphFont(char: str) -> Optional[str]:
    """给缺字形字符挑一个覆盖它的单族字体（无候选返回 ``None``）。"""
    if char in _glyph_fallback:
        return _glyph_fallback[char]
    chosen: Optional[str] = None
    for candidate in MISSING_GLYPH_FONT_CANDIDATES:
        if glyphCovers(candidate, char):
            chosen = candidate
            break
    _glyph_fallback[char] = chosen
    return chosen


def applyMissingGlyphFonts(
    document: QTextDocument, primaryFamily: str, start: int = 0
) -> int:
    """给 ``document`` 里主字体缺字形的字符套单族符号字体（**不改文本**）。

    用于 Win7 中文系统：主字体（雅黑）缺符号字形时会走逐字形 fallback 并
    进程级毒化。这里只给缺字字符的 ``QTextCharFormat`` 指定一个确实覆盖它的
    单族字体（:data:`MISSING_GLYPH_FONT_CANDIDATES`），文本 / 复制 / 导出
    全部保真；没有候选覆盖的字符保持原样。

    :param start: 只处理该文档位置之后的内容（增量渲染用；边界片段整段重扫，
        重复套同一字体的幂等操作）。传 0 处理全文。
    :return: 处理到的文档末尾位置（可作为下一次 ``start``）。
    """
    if document is None or not primaryFamily:
        return 0
    count = document.characterCount()
    if count <= 1:
        return count
    start = max(0, int(start))
    if start >= count:
        return count
    missing: set[str] = set()
    block = document.findBlock(start)
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                # 片段完全在 start 之前就跳过。边界片段**整段**扫：按 UTF-16
                # 位置切 Python 串在非 BMP 字符上会错位，而重复套字体是幂等的。
                if fragment.position() + fragment.length() <= start:
                    iterator += 1
                    continue
                for char in set(fragment.text()):
                    if char in missing or char in ("\n", "\r", "\t"):
                        continue
                    codepoint = ord(char)
                    # 变体选择符（emoji 的 U+FE0F 等）本身不需要字形
                    if 0xFE00 <= codepoint <= 0xFE0F or 0xE0100 <= codepoint <= 0xE01EF:
                        continue
                    # 格式控制符 / 私用区不需要字形
                    if unicodedata.category(char) in ("Cc", "Cf", "Cs", "Co"):
                        continue
                    if glyphCovers(primaryFamily, char):
                        continue
                    missing.add(char)
            iterator += 1
        block = block.next()
    if not missing:
        return count
    applied = 0
    edit = QTextCursor(document)
    edit.beginEditBlock()
    try:
        for char in missing:
            family = missingGlyphFont(char)
            if family is None:
                continue
            char_format = QTextCharFormat()
            char_format.setFontFamilies([family])
            cursor = QTextCursor(document)
            cursor.setPosition(min(start, count - 1))
            while True:
                found = document.find(char, cursor)
                if found.isNull():
                    break
                next_position = found.selectionEnd()
                found.mergeCharFormat(char_format)
                cursor.setPosition(
                    min(next_position, document.characterCount() - 1)
                )
                if next_position >= document.characterCount() - 1:
                    break
            applied += 1
    finally:
        edit.endEditBlock()
    return document.characterCount()


@runtime_checkable
class _ThemeAwareProtocol(Protocol):
    """_ThemeAwareMixin 所要求的宿主类接口。"""

    _theme_connected: bool
    _theme_mode: int

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None: ...


def single_shot_on(ctx: QObject, msec: int, slot) -> QTimer:
    """在 ``ctx`` 上挂一个**子** :class:`QTimer` 做延时调用。

    **不要用 ``QTimer.singleShot(ms, callable)``**：那个重载建的是没有接收方的
    ``QSingleShotTimer``，它不随任何控件销毁 —— 回调里摸控件就会在控件已释放
    时炸（``RuntimeError`` 穿出 Qt 回调 = 进程 ``0xC0000409`` 零 traceback
    终止）。实测 ``ela_tag_multi_box`` 的
    ``QTimer.singleShot(0, lambda: _pre_init_popup(self))`` 在「构造后立刻
    ``sip.delete``」下确定性崩。

    PyQt6 根本没有带 context 的 ``singleShot`` 重载（只有
    ``singleShot(ms, slot)`` / ``singleShot(ms, timerType, slot)``），所以
    「定时器本身是 ``ctx`` 的子对象」是唯一的保障 —— ``ctx`` 析构时 Qt 连带
    销毁它并丢掉待触发的 timeout。

    ``ctx`` 应当选**寿命覆盖整个延时窗口**的那个对象：延时到期前会被重建的
    控件（会被 ``deleteLater``）不能当 context，否则回调永远等不到。

    :param ctx: context 对象（定时器挂在它下面，优先传 QWidget / QObject）
    :param msec: 延迟毫秒
    :param slot: 槽
    :returns: 该定时器（需要取消时自行 ``stop()``）
    """
    timer = QTimer(ctx)
    timer.setSingleShot(True)
    timer.timeout.connect(slot)
    timer.start(int(msec))
    return timer


def catch_error(func: F) -> F:
    """装饰器：捕获函数执行中的异常并打印错误信息。"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            print(
                f"Error in {func.__name__}: {traceback.format_exc()}", file=sys.stderr
            )
            return None

    return wrapper  # type: ignore


def disconnect_theme_signal(slot: Callable[[Any], None]) -> None:
    """安全断开 eTheme.themeModeChanged 信号连接（抑制异常）。"""
    try:
        eTheme.themeModeChanged.disconnect(slot)
    except (TypeError, RuntimeError):
        pass


def safe_call(func: Optional[Callable[..., Any]], *args, **kwargs) -> Any:
    """安全调用函数，如果函数为 None 或调用失败返回 None。"""
    if func is None:
        return None
    try:
        return func(*args, **kwargs)
    except BaseException:
        print(f"Error calling {func}: {traceback.format_exc()}", file=sys.stderr)
        return None


def to_logical_pos(x: int, y: int) -> QPoint:
    """物理像素坐标 → Qt 逻辑坐标（按包含该点的屏幕 DPR 换算）。

    Win32 的 ``GetCursorPos`` / ``GetWindowRect`` 等返回物理像素，而
    ``QApplication.widgetAt`` 等 Qt 公开 API 在启用高 DPI 缩放
    （``AA_EnableHighDpiScaling``）后使用逻辑坐标，直接混用会命中错误控件。
    """
    try:
        app = QApplication.instance()
        if app is None:
            return QPoint(int(x), int(y))
        for screen in app.screens():
            dpr = float(screen.devicePixelRatio() or 1.0)
            geo = screen.geometry()
            left = int(geo.x() * dpr)
            top = int(geo.y() * dpr)
            if left <= x < left + int(geo.width() * dpr) and top <= y < top + int(
                geo.height() * dpr
            ):
                return QPoint(int(x / dpr), int(y / dpr))
        dpr = float(app.primaryScreen().devicePixelRatio() or 1.0)
        return QPoint(int(x / dpr), int(y / dpr))
    except Exception:
        return QPoint(int(x), int(y))


def execElaMenu(menu, global_pos) -> None:
    """弹出 ``ElaMenu``（阻塞到关闭）并在关闭后回收。

    兜住两处 ``ElaMenu`` 的坑（实测）：

    1. **非主屏上偶发不按 ``sizeHint`` 撑开**，只显示第一项。显式
       ``setMinimumSize(sizeHint())`` 可解，主屏无副作用；
    2. **``popup()`` 是异步的**，紧跟 ``deleteLater()`` 会在菜单显示前把它删掉 ——
       所以用阻塞的 ``exec_()``，返回后再回收（不留在控件树上累积）。

    :param menu: ``ElaMenu`` 实例
    :param global_pos: 弹出位置（全局坐标）
    """
    try:
        menu.setMinimumSize(menu.sizeHint())
        menu.exec(global_pos)
    finally:
        menu.deleteLater()


def hideComboboxPopup(combo) -> bool:  # noqa: N802 (与 Qt 命名一致)
    """无父控件时用 **Qt 原生**实现关弹层，返回 ``True``（调用方据此跳过 super）。

    上游 ``ElaComboBox::hidePopup`` / ``ElaMultiSelectComboBox::hidePopup`` 的
    收起动画在结束回调里无条件 ``QApplication::sendEvent(parentWidget(), ...)``，
    而 ``parentWidget()`` 在无父控件时是 ``nullptr`` —— 回调跑到那一步进程静默
    终止（0xC0000409 一类，无 traceback）。所以本库所有组合框子类的
    ``hidePopup`` 都要先过这道闸门：

    .. code-block:: python

        def hidePopup(self):
            ...
            if hideComboboxPopup(self):
                return          # 已用 Qt 原生实现关掉
            super().hidePopup()
    """
    if combo.parentWidget() is not None:
        return False
    QComboBox.hidePopup(combo)
    return True


def _draw_button_content(
    painter: QPainter,
    text: str,
    icon_name,
    icon_size: int,
    face_inset: int,
    widget_width: int,
    widget_height: int,
    text_color: QColor,
    icon_getter: Callable[[Any, QColor], Any],
) -> QRect:
    """绘制按钮图标和文字，返回文字区域 ``QRect``。"""
    if icon_name is not None:
        icon_sz = QSize(icon_size, icon_size)
        spacing = 8
        content_height = widget_height - 2 * face_inset

        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(text)
        total_content_width = icon_sz.width() + spacing + text_width
        start_x = (
            face_inset + (widget_width - 2 * face_inset - total_content_width) // 2
        )

        icon_y = face_inset + (content_height - icon_sz.height()) // 2
        icon_rect = QRect(start_x, icon_y, icon_sz.width(), icon_sz.height())

        text_rect = QRect(
            icon_rect.right() + spacing,
            face_inset,
            text_width,
            content_height,
        )
        icon = icon_getter(icon_name, text_color)
        painter.drawPixmap(icon_rect, icon.pixmap(icon_sz))
    else:
        rect = QRect(
            face_inset,
            face_inset,
            widget_width - 2 * face_inset,
            widget_height - 2 * face_inset,
        )
        text_rect = rect

    painter.setPen(text_color)
    painter.setFont(painter.font())
    painter.drawText(
        text_rect,
        Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
        text,
    )
    return text_rect


def _disconnect_theme_on_destroy(obj) -> None:
    """``destroyed`` 的清理槽（**必须是模块级普通函数**）。

    PyQt 不调用「绑定到自身」的 ``destroyed`` 槽（实测：``sip.delete()`` 下绑方法
    触发 0 次，模块级函数 / lambda 各 1 次），详见 AGENTS.md。
    """
    slot = getattr(obj, "_theme_slot", None)
    if slot is not None:
        try:
            obj._theme_connected = False
            obj._theme_slot = None
        except RuntimeError:  # 包装器已不可用
            pass
        disconnect_theme_signal(slot)


def connect_theme_signal(obj, slot: Optional[Callable[[Any], None]] = None) -> None:
    """把 ``eTheme.themeModeChanged`` 接到 ``obj`` 的主题槽并负责断开。

    供**不能继承** :class:`_ThemeAwareMixin` 的控件使用（动态定义的类、多继承基类
    不可控的第三方控件）。两条防线与 mixin 完全一致：

    1. 槽经 :func:`_make_theme_slot` 包一层（存进 ``obj._theme_slot``），并把
       **模块级** :func:`_disconnect_theme_on_destroy` 挂到 ``obj.destroyed``；
    2. 槽自身在 ``sip.isdeleted(obj)`` 时自愈断开，**不依赖 ``destroyed`` 送达**。

    :param slot: 默认为 ``obj._onThemeChanged``。签名必须能接一个模式参数
        （``def _onThemeChanged(self, mode)`` 或 ``(self, _mode=None)``）。
    """
    if slot is None:
        slot = obj._onThemeChanged
    if getattr(obj, "_theme_connected", False):
        return
    obj._theme_connected = True
    obj._theme_slot = _make_theme_slot(obj, slot)
    eTheme.themeModeChanged.connect(obj._theme_slot)
    obj.destroyed.connect(_disconnect_theme_on_destroy)


def disconnect_theme(obj) -> None:
    """主动断开 :func:`connect_theme_signal` 建立的连接（幂等）。

    **必须断 ``_theme_slot`` 而不是 ``_onThemeChanged``** —— ``disconnect`` 要拿到
    连上去的**同一个可调用对象**（lambda / ``functools.partial`` 必然断不掉；bound
    method 在 PyQt6 下宽容，但统一按这条写）。断失败会静默吞掉异常，连接从未真正
    断开（原实现正是这个 bug：断开失败 + 把 ``_theme_slot`` 置 ``None`` 丢掉引用，
    之后再 ``_init_theme_aware()`` 会**叠上第二条连接**，一次主题切换触发两次）。
    """
    if not getattr(obj, "_theme_connected", False):
        return
    slot = getattr(obj, "_theme_slot", None)
    obj._theme_connected = False
    obj._theme_slot = None
    disconnect_theme_signal(slot)


def _make_theme_slot(obj, slot: Optional[Callable[[Any], None]] = None):
    """造一个「带存活检查 + 自愈断开」的主题槽。

    ``eTheme`` 是进程级单例，``themeModeChanged`` 会一直连着所有创建过的控件；
    控件销毁后包装器可能还活着，信号再发一次就打进已释放的 C++ 对象 =
    0xC0000409 静默终止。所以槽第一件事是 ``sip.isdeleted()``，命中就顺手断开 ——
    **不依赖 ``destroyed`` 一定送达**（那正是本模块的第二条防线）。
    """
    if slot is None:
        slot = obj._onThemeChanged

    def _slot(mode):
        try:
            alive = not is_deleted(obj)
        except (RuntimeError, TypeError):
            alive = False
        if not alive:
            disconnect_theme_signal(_slot)
            return
        slot(mode)

    return _slot


class _ThemeAwareMixin:
    """Mixin that auto-connects theme signals and cleans up on destroy.

    Subclasses must define _onThemeChanged(self, mode) and call
    super().__init__(parent) or self._init_theme_aware().
    """

    # 类级默认值不能只有注解：``_init_theme_aware`` 在 ``__init__`` 链的最上游
    # 就要读 ``_theme_connected``，那时子类还没设过。
    _theme_connected: bool = False
    _theme_slot: object = None
    _theme_mode: ElaThemeType.ThemeMode

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._init_theme_aware()

    def _init_theme_aware(self) -> None:
        connect_theme_signal(self)

    def _theme_cleanup(self) -> None:
        """主动断开（供不需要等 ``destroyed`` 的场景显式调用）。"""
        disconnect_theme(self)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        """子类应重写此方法以响应主题切换。"""

    def deleteLater(self) -> None:
        self._theme_cleanup()
        super().deleteLater()  # type: ignore[misc]


POPUP_FOOTER_OBJECT_NAME = "ElaGhostPopupFooter"


def _prepare_combobox_popup(
    combo_box, top_extra: int = 0, bottom_extra: int = 0
) -> None:
    """在 ``super().showPopup()`` **之前**调用，把弹层附件高度交给 C++。

    C++ 的 showPopup 会按 ``_elaPopupTopExtraHeight`` / ``_elaPopupBottomExtraHeight``
    计算容器高度与 view 的动画终值，保证动画结束 ``addWidget(view())`` 时几何不再
    跳变。同时在这里复位上一次因屏幕空间不足而设置的固定高度（放在 showPopup 之后
    会打断正在跑的高度动画）。
    """
    combo_box.setProperty("_elaPopupTopExtraHeight", int(top_extra))
    combo_box.setProperty("_elaPopupBottomExtraHeight", int(bottom_extra))
    container = combo_box.findChild(QWidget, "ElaComboBoxContainer")
    if container is not None:
        container.setFixedHeight(WIDGET_SIZE_MAX)


def _adjust_combobox_popup(combo_box) -> None:
    """在 ``super().showPopup()`` 之后调用。用最终弹窗高度判断是否需要移到上方。"""
    container = combo_box.findChild(QWidget, "ElaComboBoxContainer")
    if not container or not container.isVisible():
        return

    combo_global = combo_box.mapToGlobal(QPoint(0, 0))
    combo_top = combo_global.y()
    combo_bottom = combo_top + combo_box.height()

    screen = QApplication.screenAt(combo_global)
    if not screen:
        return
    screen_geo = screen.availableGeometry()

    item_h = combo_box.view().sizeHintForRow(0) if combo_box.count() else 30
    if item_h <= 0:
        item_h = 30
    n = combo_box.maxVisibleItems()
    if combo_box.count() < n:
        n = combo_box.count()
    # 与 C++ showPopup 的 count() * 35 + 8 同一套算式，额外加上弹层附件。
    # 附件高度以 _prepare_combobox_popup 写进动态属性的值为准（底栏在展开动画
    # 期间是隐藏的，按控件可见性扫描会漏算）。
    extra_height = int(combo_box.property("_elaPopupTopExtraHeight") or 0)
    extra_height += int(combo_box.property("_elaPopupBottomExtraHeight") or 0)
    final_height = n * item_h + 8 + extra_height

    needed_below = combo_bottom + 3 + final_height

    if needed_below > screen_geo.bottom():
        new_y = combo_top - 3 - final_height
        if new_y >= screen_geo.top():
            container.move(container.x(), new_y)
        else:
            # 上方也不够 → 压缩高度
            max_h = combo_top - 3 - screen_geo.top()
            if max_h > 50:
                container.setFixedHeight(int(max_h))
                container.move(container.x(), screen_geo.top())
            else:
                # 上下都放不下（上方 ≤ 50px）：改为压到**下方**可用空间 ——
                # 什么都不做的话容器按默认（下方）位置渲染、超出屏幕底部被裁，
                # 列表尾部不可达。view 自带滚动条，压矮后仍能滚到最后一项。
                below_h = screen_geo.bottom() - combo_bottom - 3
                if below_h > 0:
                    container.setFixedHeight(int(min(final_height, below_h)))
