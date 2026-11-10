"""
内部工具模块。

包含仅供内部使用的工具函数，不应作为公共API直接调用。
"""

from __future__ import annotations

import inspect
import logging
import sys
import traceback
import unicodedata
import warnings
from functools import wraps
from typing import Any, Callable, Optional, Protocol, TypeVar, runtime_checkable

from PyQt6 import sip
from PyQt6.QtCore import QLocale, QObject, QPoint, QTimer
from PyQt6.QtGui import (
    QFont,
    QFontDatabase,
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

logger = logging.getLogger(__name__)

__all__ = [
    "single_shot_on",
    "catch_error",
    "guard_callback",
    "safe_connect",
    "connect_theme_signal",
    "disconnect_theme",
    "disconnect_theme_signal",
    "hideComboboxPopup",
    "is_deleted",
    "load_lazy_pinyin",
    "safe_call",
    "system_cjk_font_family",
    "fontFamilyAvailable",
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
    不能直接用 ``sip.isdeleted(obj)``：``None`` 与非 sip 包装的普通 Python 对象
    都会抛 ``TypeError``。库内所有存活判断统一走本函数；非包装对象按「存活」处理。
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

#: 中文系统 CJK UI 字体候选（顺序即优先级）。GDI 中文系统只登记本地化族名
#: （如「微软雅黑」），DirectWrite 则保留英文名。
_CJK_UI_FONT_CANDIDATES = ("Microsoft YaHei", "微软雅黑")

#: 同一字体在 GDI / DirectWrite 下的本地化族名别名（键为 casefold）。
_FONT_FAMILY_ALIASES = {
    "microsoft yahei": ("微软雅黑",),
    "微软雅黑": ("Microsoft YaHei",),
    "microsoft yahei ui": ("微软雅黑 UI",),
    "微软雅黑 ui": ("Microsoft YaHei UI",),
    "simsun": ("宋体",),
    "宋体": ("SimSun",),
    "nsimsun": ("新宋体",),
    "新宋体": ("NSimSun",),
    "simhei": ("黑体",),
    "黑体": ("SimHei",),
    "kaiti": ("楷体",),
    "楷体": ("KaiTi",),
    "fangsong": ("仿宋",),
    "仿宋": ("FangSong",),
}


def system_cjk_font_family():
    """中文系统下可用的 CJK UI 字体族（其它系统 / 字体缺失返回 ``None``）。
    候选见 ``_CJK_UI_FONT_CANDIDATES``（兼容 GDI 登记的本地化族名）；
    调用点必须在 QApplication 之后，结果进程级缓存。字体回退 / cmap 毒化的
    细节见 ``docs/core.md``。
    """
    global _cjk_ui_font_family, _cjk_ui_font_probed
    if not _cjk_ui_font_probed:
        _cjk_ui_font_probed = True
        try:
            if QLocale.system().language() == QLocale.Language.Chinese:
                families = set(QFontDatabase.families())
                for name in _CJK_UI_FONT_CANDIDATES:
                    if name in families:
                        _cjk_ui_font_family = name
                        break
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


def fontFamilyAvailable(family: str) -> bool:
    """字体族是否可用（兼容 GDI 中文系统只登记本地化族名）。

    ``QFont.exactMatch()`` 只认活动 face 名；GDI zh_CN 下英文名（如
    ``Microsoft YaHei``）会判不可用，但同一字体以「微软雅黑」登记。
    """
    name = (family or "").strip()
    if not name:
        return False
    try:
        if QFont(name).exactMatch():
            return True
    except Exception:  # noqa: BLE001 —— 字体探测失败按不可用处理
        return False
    families = _fontFamilySet()
    if name in families:
        return True
    folded = name.casefold()
    for alias in _FONT_FAMILY_ALIASES.get(folded, ()):
        if alias in families:
            return True
    try:
        raw = QRawFont.fromFont(QFont(name))
        return bool(raw.isValid() and raw.familyName().casefold() == folded)
    except Exception:  # noqa: BLE001
        return False


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

    用 ``QRawFont.supportsCharacter``；``QFontMetrics.inFont`` 对回退字体也返回真。
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
    """给 ``document`` 里主字体缺字形的字符套单族符号字体（不改文本）。

    只改缺字片段的 ``QTextCharFormat`` 字体族，复制 / 导出保真；没有候选覆盖的
    字符保持原样。
    :param start: 只处理该位置之后的内容（增量渲染），返回处理到的末尾位置。
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
                # 片段完全早于 start 就跳过。边界片段**整段**扫：按 UTF-16
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
                cursor.setPosition(min(next_position, document.characterCount() - 1))
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
    """在 ``ctx`` 上挂一个子 ``QTimer`` 做延时调用。

    不要用 ``QTimer.singleShot(ms, callable)``：它没有接收方，控件销毁后回调
    会在 Qt 回调链上炸（0xC0000409）。``ctx`` 的寿命必须覆盖整个延时窗口。
    槽异常在连接侧吞掉；定时器触发后自行 ``deleteLater``，不会把闭包留在
    ``ctx`` 上。返回的定时器只用于提前 ``stop()``，触发后不可再访问。

    :returns: 该定时器（取消时自行 ``stop()``）
    """
    timer = QTimer(ctx)
    timer.setSingleShot(True)

    def _invoke() -> None:
        timer.deleteLater()
        slot()

    safe_connect(timer, "timeout", _invoke, "single_shot_on", receiver=timer)
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


def _slot_arity(slot: Callable[..., Any]) -> Optional[int]:
    """槽能接受的最大位置参数个数（``None`` = 不限 / 无法判断）。

    Qt 信号只按自己的签名发参数，PyQt 会自动丢掉槽不需要的多余实参；连接侧
    包装器必须复刻这个行为，否则 ``clicked(bool)`` 会把零参方法打崩。
    """
    try:
        parameters = inspect.signature(slot).parameters.values()
    except (TypeError, ValueError):
        return None
    count = 0
    for parameter in parameters:
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            count += 1
        elif parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            return None
    return count


def _trim_args(arity: Optional[int], args):
    if arity is not None and len(args) > arity:
        return args[:arity]
    return args


def guard_callback(callback: Callable[..., Any], label: str = "") -> Callable[..., Any]:
    """把回调包成「异常不穿过 Qt/C++ 边界」的形状（无 QObject 接收者时用）。

    Qt 回调里未捕获的异常会直接 ``abort()``（0xC0000409），且不会传回
    ``emit()`` 调用方；连接非 QObject 槽时必须在连接侧包好。
    """
    name = label or getattr(callback, "__name__", repr(callback))
    arity = _slot_arity(callback)

    def guarded(*args, **kwargs):
        try:
            return callback(*_trim_args(arity, args), **kwargs)
        except Exception:  # noqa: BLE001 —— 槽异常绝不能逃逸
            logger.debug("%s 回调异常（已忽略）", name, exc_info=True)
            return None

    guarded.__name__ = "guarded_%s" % name
    return guarded


_SAFE_CONNECT_WARNED: set = set()


class _GuardedSlot(QObject):
    """槽包装器（QObject 接收者）：随接收者销毁自动断开，避免悬空回调。"""

    def __init__(self, receiver, slot, name: str) -> None:
        super().__init__(receiver)
        self._slot = slot
        self._name = name
        self._arity = _slot_arity(slot)

    def handle(self, *args, **kwargs):
        try:
            return self._slot(*_trim_args(self._arity, args), **kwargs)
        except Exception as exc:  # noqa: BLE001 —— 槽异常绝不能逃逸
            key = (self._name, type(exc))
            if key not in _SAFE_CONNECT_WARNED:
                _SAFE_CONNECT_WARNED.add(key)
                warnings.warn(
                    f"{self._name} 槽异常（已忽略）：{type(exc).__name__}: {exc}",
                    RuntimeWarning,
                    stacklevel=3,
                )
            return None


def safe_connect(obj, signal_name, slot, label: str = "", *, receiver=None) -> None:
    """连接受保护槽：槽内异常只告警一次，不会穿过 Qt 边界终止进程。

    PyQt6 中槽抛出的异常不会传播给 ``signal.emit()`` 调用方，而是在 Qt 回调
    边界直接 abort（0xC0000409）；唯一有效防线是在连接侧包装槽。

    :param obj: 拥有信号的对象；``signal_name`` 也可直接传信号对象
    :param signal_name: 信号名或信号对象
    :param slot: 槽（可调用）
    :param label: 告警标签（默认取槽的 ``__name__``）
    :param receiver: 接收者（默认从绑定方法推断）；QObject 接收者会获得一个
        子包装器，接收者销毁时 Qt 自动断开，避免包装器比 Qt 连接活得更久
    """
    name = label or getattr(slot, "__name__", repr(slot))
    arity = _slot_arity(slot)
    owner = receiver if receiver is not None else getattr(slot, "__self__", None)
    signal = getattr(obj, signal_name) if isinstance(signal_name, str) else signal_name
    if owner is None and isinstance(obj, QObject):
        # 匿名 lambda 没有绑定接收者：把包装器挂到信号发送者上，随发送者销毁断开。
        owner = obj

    if isinstance(owner, QObject):
        try:
            if is_deleted(owner):
                return None
        except (RuntimeError, TypeError):
            return None
        guard = _GuardedSlot(owner, slot, name)
        slots = getattr(owner, "_safe_connect_slots", None)
        if slots is None:
            slots = []
            setattr(owner, "_safe_connect_slots", slots)
        slots.append(guard)
        signal.connect(guard.handle)
        return None

    def guarded(*args, **kwargs):
        if owner is not None:
            try:
                if is_deleted(owner):
                    return None
            except (RuntimeError, TypeError):
                return None
        try:
            return slot(*_trim_args(arity, args), **kwargs)
        except Exception as exc:  # noqa: BLE001 —— 槽异常绝不能逃逸
            key = (name, type(exc))
            if key not in _SAFE_CONNECT_WARNED:
                _SAFE_CONNECT_WARNED.add(key)
                warnings.warn(
                    f"{name} 槽异常（已忽略）：{type(exc).__name__}: {exc}",
                    RuntimeWarning,
                    stacklevel=3,
                )
            return None

    guarded.__name__ = f"guarded_{name}"
    signal.connect(guarded)
    return None


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

    Win32 返回物理像素，Qt API 使用逻辑坐标，直接混用会命中错误控件。
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
    非主屏上偶发不按 ``sizeHint`` 撑开，先 ``setMinimumSize(sizeHint())``；
    ``popup()`` 是异步的，必须用阻塞的 ``exec()``，返回后再 ``deleteLater()``。
    """
    try:
        menu.setMinimumSize(menu.sizeHint())
        menu.exec(global_pos)
    finally:
        menu.deleteLater()


def hideComboboxPopup(combo) -> bool:  # noqa: N802 (与 Qt 命名一致)
    """无父控件时用 Qt 原生实现关弹层，返回 ``True``（调用方跳过 super）。
    上游 ``hidePopup`` 的收起动画会无条件 ``sendEvent(parentWidget())``；
    无父控件时是 ``nullptr``，进程静默终止（0xC0000409）。组合框子类都要先过这道闸。
    """
    if combo.parentWidget() is not None:
        return False
    QComboBox.hidePopup(combo)
    return True


def _disconnect_theme_on_destroy(obj) -> None:
    """``destroyed`` 清理槽（必须是模块级普通函数）。

    PyQt 不调用绑定到自身的 ``destroyed`` 槽。
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
    """把 ``eTheme.themeModeChanged`` 接到 ``obj`` 并负责断开。
    槽经 ``_theme_slot`` 包一层，模块级函数挂 ``destroyed``；槽自身在包装器
    已销毁时自愈断开。``slot`` 默认 ``obj._onThemeChanged``。
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
    必须断 ``_theme_slot`` 而不是 ``_onThemeChanged``：``disconnect`` 要求同一个
    可调用对象，否则会静默失败并叠上第二条连接。
    """
    if not getattr(obj, "_theme_connected", False):
        return
    slot = getattr(obj, "_theme_slot", None)
    obj._theme_connected = False
    obj._theme_slot = None
    disconnect_theme_signal(slot)


def _make_theme_slot(obj, slot: Optional[Callable[[Any], None]] = None):
    """造一个带存活检查 + 自愈断开的主题槽。

    ``eTheme`` 是进程级单例；控件销毁后信号仍可能送达，槽先 ``is_deleted()`` 自愈。
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
        try:
            slot(mode)
        except Exception:  # noqa: BLE001 —— 主题槽异常不能穿出 Qt
            logger.debug("主题槽异常（已忽略）", exc_info=True)

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
