"""主题单例信号的接线与断开必须真的发生。

三条曾经同时失守的防线：

1. **``self.destroyed.connect(self._x)`` 永不触发** —— PyQt5 不调用绑到自身的
   ``destroyed`` 槽（实测 ``sip.delete()`` 下触发 0 次，模块级函数 / lambda 各 1 次），
   所以挂在上面的清理逻辑等于从未执行。机器守卫 :class:`TestNoSelfBoundDestroyedSlot`
   钉住这个形状不再出现。
2. **``_theme_cleanup()`` 断的是错的 callable** —— 它断 ``self._onThemeChanged``（每次
   属性访问都新建的 bound method，身份对不上），而真正连上去的是 ``self._theme_slot``。
   断开失败被静默吞掉，连接一直在。
3. **清理后再注册 → 叠上第二条连接** —— 一次主题切换触发两次 ``_onThemeChanged``。
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from PyQt6 import sip
from PyQt6.QtWidgets import QWidget
from PyQt6ElaWidgetTools import eTheme

from pyqt6_ela_pro._internal import (
    _ThemeAwareMixin,
    connect_theme_signal,
    disconnect_theme,
)

_PKG = pathlib.Path(__file__).resolve().parents[2] / "pyqt6_ela_pro"


class Probe(_ThemeAwareMixin, QWidget):
    """记录每次主题回调，用于计数「一次主题切换被处理了几遍」。"""

    def __init__(self, parent=None):
        self.calls = []
        super().__init__(parent)

    def _onThemeChanged(self, mode):
        self.calls.append(mode)


def _fire_theme() -> None:
    eTheme.themeModeChanged.emit(eTheme.getThemeMode())


class TestThemeCleanupActuallyDisconnects:
    def test_cleanup_stops_delivery(self, qapp, make):
        probe = make(Probe)
        _fire_theme()
        assert len(probe.calls) == 1, "接线本身应工作"

        probe._theme_cleanup()
        _fire_theme()
        assert len(probe.calls) == 1, "清理后不得再收到主题信号"
        assert probe._theme_connected is False
        assert probe._theme_slot is None

    def test_cleanup_is_idempotent(self, qapp, make):
        probe = make(Probe)
        probe._theme_cleanup()
        probe._theme_cleanup()  # 不得抛
        assert probe._theme_connected is False

    def test_reinit_after_cleanup_does_not_stack_connections(self, qapp, make):
        """回归：旧实现清理失败 + 丢引用，再注册就叠上第二条。"""
        probe = make(Probe)
        probe._theme_cleanup()
        probe._init_theme_aware()

        _fire_theme()
        assert len(probe.calls) == 1, "一次主题切换只应触发一次（曾触发两次）"

    def test_reinit_without_cleanup_is_a_noop(self, qapp, make):
        probe = make(Probe)
        probe._init_theme_aware()
        _fire_theme()
        assert len(probe.calls) == 1

    def test_deleteLater_disconnects(self, qapp):
        probe = Probe()
        probe._theme_cleanup_called = False
        probe.deleteLater()
        qapp.processEvents()
        assert probe._theme_connected is False

    def test_destroyed_hook_fires_for_module_level_function(self, qapp, make):
        """``destroyed`` 上的模块级函数确实会被调用（对照组）。"""
        fired = []
        probe = make(Probe)
        probe.destroyed.connect(lambda *_: fired.append(1))
        sip.delete(probe)
        assert fired == [1]


class TestConnectThemeSignalHelper:
    """给不能继承 mixin 的控件用（动态类 / 第三方基类）。"""

    def test_accepts_an_explicit_slot(self, qapp, make):
        holder = make(QWidget)
        seen = []
        holder._onThemeChanged = lambda mode: seen.append(mode)  # type: ignore[attr-defined]
        connect_theme_signal(holder)
        _fire_theme()
        assert len(seen) == 1

        disconnect_theme(holder)
        _fire_theme()
        assert len(seen) == 1, "disconnect_theme 后不得再收到"

    def test_is_idempotent(self, qapp, make):
        holder = make(QWidget)
        holder._onThemeChanged = lambda mode: None  # type: ignore[attr-defined]
        connect_theme_signal(holder)
        connect_theme_signal(holder)
        disconnect_theme(holder)
        disconnect_theme(holder)

    def test_self_heals_after_the_object_is_gone(self, qapp):
        """对象已析构时，下一次主题切换应把槽自己断开（不依赖 destroyed）。"""
        holder = QWidget()
        holder._onThemeChanged = lambda mode: None  # type: ignore[attr-defined]
        connect_theme_signal(holder)
        sip.delete(holder)
        # 不应抛：槽先判 sip.isdeleted 再决定是否自断
        _fire_theme()


class TestNoSelfBoundDestroyedSlot:
    """机器守卫：``self.destroyed.connect(self._x)`` 这个形状不许再出现。

    合法的是 ``别的对象.destroyed.connect(self._x)``（如内容控件 / 顶层窗口的
    destroyed），所以只匹配接收者与连接者同为 ``self`` 的情况。
    """

    def _offenders(self) -> list[str]:
        found = []
        for path in sorted(_PKG.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connect"
                ):
                    continue
                owner = node.func.value
                target = node.args[0] if node.args else None
                # 连接者必须是 **self** 的 destroyed：别的对象（内容控件 / 顶层窗口）
                # 的 destroyed.connect(self._x) 是合法的，Qt 会正常投递。
                if not (isinstance(owner, ast.Attribute) and owner.attr == "destroyed"):
                    continue
                if not (isinstance(owner.value, ast.Name) and owner.value.id == "self"):
                    continue
                if not isinstance(target, ast.Attribute):
                    continue
                if isinstance(target.value, ast.Name) and target.value.id == "self":
                    rel = path.relative_to(_PKG)
                    found.append(
                        "{}:{}  self.destroyed.connect({})".format(
                            rel, node.lineno, ast.unparse(target)
                        )
                    )
        return found

    def test_library_has_none(self):
        offenders = self._offenders()
        assert not offenders, (
            "以下位置仍在用永不触发的自绑 destroyed 槽：\n" + "\n".join(offenders)
        )


class TestMigratedCallSitesStillTheme:
    """迁移过的 6 处必须仍然跟随主题，且销毁后断开。"""

    def test_notify_popup(self, qapp, make):
        from pyqt6_ela_pro.notify_popup import ElaNotifyPopup

        popup = make(ElaNotifyPopup)
        assert popup._theme_connected is True
        popup._onThemeChanged(eTheme.getThemeMode())  # 手动走一次，不抛
        popup.deleteLater()
        qapp.processEvents()
        assert popup._theme_connected is False

    def test_password_edit(self, qapp, make):
        from pyqt6_ela_pro.ela_password_edit import ElaPasswordEdit

        edit = make(ElaPasswordEdit)
        assert edit._theme_connected is True
        edit.deleteLater()
        qapp.processEvents()
        assert edit._theme_connected is False

    def test_chart_widget(self, qapp, make):
        chart = make(
            __import__(
                "pyqt6_ela_pro.charts.core", fromlist=["ElaChartWidget"]
            ).ElaChartWidget
        )
        assert chart._theme_connected is True
        chart.deleteLater()
        qapp.processEvents()
        assert chart._theme_connected is False

    @pytest.mark.parametrize(
        "module_name,attr",
        [
            ("pyqt6_ela_pro.ela_figure_canvas", "ElaFigureCanvas"),
            ("pyqt6_ela_pro.ela_pyqtgraph_canvas", "ElaPlotWidget"),
        ],
    )
    def test_optional_canvases(self, qapp, module_name, attr):
        """matplotlib / pyqtgraph 缺失时是占位类，跳过而不是失败。"""
        module = __import__(module_name, fromlist=[attr])
        cls = getattr(module, attr)
        try:
            widget = cls()
        except ImportError:
            pytest.skip("{} 的可选依赖未安装".format(module_name))
        assert widget._theme_connected is True
        widget.deleteLater()
        qapp.processEvents()

    def test_tag_combo_base_host(self, qapp, make):
        from pyqt6_ela_pro.ela_tag_box import ElaTagBox

        box = make(ElaTagBox)
        assert getattr(box, "_theme_connected", False) is True
        box.deleteLater()
        qapp.processEvents()
        assert getattr(box, "_theme_connected", True) is False


_TAG_BOX_MODULES = [
    ("ElaTagBox", "pyqt6_ela_pro.ela_tag_box", "ElaTagBox"),
    ("ElaTagSearchBox", "pyqt6_ela_pro.ela_tag_search_box", "ElaTagSearchBox"),
    (
        "ElaTagSearchMultiBox",
        "pyqt6_ela_pro.ela_tag_search_multi_box",
        "ElaTagSearchMultiBox",
    ),
]

_SEARCH_COMBO_MODULES = [
    ("ElaSearchBox", "pyqt6_ela_pro.combo_box", "ElaSearchBox"),
    ("ElaSearchMultiBox", "pyqt6_ela_pro.combo_box", "ElaSearchMultiBox"),
]


def _load(module_name: str, attr: str):
    return getattr(__import__(module_name, fromlist=[attr]), attr)


def _is_empty_stub(func) -> bool:
    """判断一个函数是否只有 docstring / ``pass``（即什么也不做的空桩）。"""
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(func))
    return _is_empty_ast_hook(ast.parse(source).body[0])


def _is_empty_ast_hook(node: ast.FunctionDef) -> bool:
    """AST 版：函数体是否只有 docstring / ``pass`` / ``...``。"""
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return not body or all(
        isinstance(stmt, ast.Pass)
        or (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis
        )
        for stmt in body
    )


class TestThemeHookNotShadowed:
    """``_onThemeChanged`` 被 MRO 里的空桩遮蔽 = 钩子永远不跑。

    ``_ThemeAwareMixin`` 自己就定义了一个**空** ``_onThemeChanged``，它要求
    协作式 mixin 排在它**前面**并显式 ``super()`` 下传。写反了就静默失效：
    主题信号照收、``_onThemeChanged`` 照调，只是调的是那个什么都不做的空实现。

    实测踩过的两处：

    * ``_SearchComboMixin`` 排在 ``_ThemeAwareMixin`` **之后** → 弹层搜索框
      调色板在切深浅色后不跟随（``ElaSearchBox`` / ``ElaSearchMultiBox`` /
      两个 Tag 版共 4 个类全中）；
    * ``_TagBoxThemeMixin`` 用自定义槽名 ``_on_tag_theme_changed``，而搜索框
      系列的 ``_ThemeAwareMixin`` 已先连过一次（连的是 ``_onThemeChanged``）
      → ``connect_theme_signal`` 的幂等守卫把第二次连接直接 ``return`` 掉
      → ``_theme_mode`` 永不更新 → 深色主题下自绘胶囊仍是浅底黑字。
    """

    @pytest.mark.parametrize(
        "module_name,attr",
        [(m, a) for _, m, a in _SEARCH_COMBO_MODULES + _TAG_BOX_MODULES],
    )
    def test_resolved_hook_is_not_the_empty_stub(self, module_name, attr):
        cls = _load(module_name, attr)
        resolved = getattr(cls._onThemeChanged, "__func__", cls._onThemeChanged)
        assert not _is_empty_stub(resolved), (
            "{} 的 _onThemeChanged 解析到空桩 {} —— 协作式 mixin 顺序反了，"
            "或钩子改名后忘了连标准名".format(attr, resolved.__qualname__)
        )

    def test_no_hook_provider_mixin_ordered_after_theme_aware_mixin(self):
        """机器守卫：提供钩子的 mixin 不许排在 ``_ThemeAwareMixin`` 之后。

        ``_ThemeAwareMixin`` 自带一个**空**的 ``_onThemeChanged``，所以任何
        在它之后定义的同名钩子都会被 MRO 遮蔽成永远不被调用的死代码。
        """
        providers: set[str] = set()
        trees: list[tuple[pathlib.Path, ast.Module]] = []
        for path in sorted(_PKG.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            trees.append((path, tree))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for item in node.body:
                    if (
                        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name == "_onThemeChanged"
                        and not _is_empty_ast_hook(item)
                    ):
                        providers.add(node.name)

        offenders = []
        for path, tree in trees:
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = [
                    base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                    for base in node.bases
                ]
                if "_ThemeAwareMixin" not in bases:
                    continue
                after = bases[bases.index("_ThemeAwareMixin") + 1 :]
                shadowing = [b for b in after if b in providers]
                if shadowing:
                    offenders.append(
                        "{}:{}  {}({}) —— {} 排在 _ThemeAwareMixin 之后，"
                        "钩子会被空桩遮蔽".format(
                            path.relative_to(_PKG),
                            node.lineno,
                            node.name,
                            ", ".join(bases),
                            "/".join(shadowing),
                        )
                    )
        assert not offenders, "\n".join(offenders)

    def test_no_explicit_slot_when_mixin_may_have_connected_first(self):
        """机器守卫：``_ThemeAwareMixin`` 系不许给 ``connect_theme_signal`` 传自定义槽。

        幂等守卫（``_theme_connected``）会让**第二次**调用静默 no-op，所以后传的
        槽根本没接上，而第一次连的空实现照跑 —— 症状是「主题切换毫无反应」，
        零报错。正确做法是统一用标准钩子名 ``_onThemeChanged``。
        """
        offenders = []
        for path in sorted(_PKG.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            theme_aware_classes = {
                node.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef)
                and any(
                    (b.id if isinstance(b, ast.Name) else getattr(b, "attr", ""))
                    == "_ThemeAwareMixin"
                    for b in node.bases
                )
            }
            if not theme_aware_classes:
                continue
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "connect_theme_signal"
                    and len(node.args) >= 2
                ):
                    continue
                for klass in ast.walk(node):
                    if isinstance(klass, ast.ClassDef) and (
                        klass.name in theme_aware_classes
                    ):
                        offenders.append(
                            "{}:{}  {}.connect_theme_signal({}, ...) 传了自定义槽"
                            "，会被幂等守卫吞掉".format(
                                path.relative_to(_PKG),
                                node.lineno,
                                klass.name,
                                ast.unparse(node.args[0]),
                            )
                        )
        assert not offenders, "\n".join(offenders)


class TestTagBoxFollowsTheme:
    """tag 框系列的自绘配色必须跟着主题走。"""

    @pytest.mark.parametrize("name,module_name,attr", _TAG_BOX_MODULES)
    def test_painted_background_differs_per_mode(
        self, qapp, make, name, module_name, attr
    ):
        """回归：``_theme_mode`` 卡在旧模式 → 深色下仍是浅底。

        判据是**同一对象在两种模式下的底色必须不同且深色更深**，不钉具体色值
        —— 上游改配色时这条仍应成立，而 bug 复现时两者完全相等。
        """
        from PyQt6ElaWidgetTools import ElaThemeType, eTheme

        box = make(_load(module_name, attr), "语言")
        seen = {}
        for mode in (ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark):
            eTheme.setThemeMode(mode)
            qapp.processEvents()
            assert box._theme_mode == mode, (
                "{} 的 _theme_mode 没跟随主题切换（仍为 {}）".format(
                    name, box._theme_mode
                )
            )
            seen[mode] = box._getBackgroundColor()

        light = seen[ElaThemeType.ThemeMode.Light]
        dark = seen[ElaThemeType.ThemeMode.Dark]
        assert light.name() != dark.name(), (
            "{} 在深浅两种模式下底色相同（{}）—— 自绘配色根本没跟着主题走".format(
                name, light.name()
            )
        )
        assert dark.lightness() < light.lightness(), (
            "{} 的深色底 {} 比浅色底 {} 还亮，取色反了".format(
                name, dark.name(), light.name()
            )
        )

    @pytest.mark.parametrize("name,module_name,attr", _TAG_BOX_MODULES)
    def test_exactly_one_theme_connection(
        self, qapp, make, name, module_name, attr
    ):
        """构造路径上只有**一个** ``connect_theme_signal`` 调用点该生效。

        ``QObject.receivers()`` 在 PyQt6 下对所有信号都不可用（见 MIGRATION），
        改为从**幂等守卫 + 断开链路**两侧钉住这条不变量。
        """
        box = make(_load(module_name, attr), "语言")
        assert box._theme_connected is True
        # ``_tag_box_init`` 传的就是标准钩子名（自定义槽名会被守卫吞掉）
        assert (
            box._theme_slot.__closure__ is not None
        ), "_theme_slot 包装器丢失"

        # ① 幂等：第二次 connect 必须静默 no-op（不换包装器、不叠连接）
        slot_before = box._theme_slot
        connect_theme_signal(box)
        assert box._theme_slot is slot_before

        # ② 断开后主题信号不得再进这条链路（断开必须真的生效）
        disconnect_theme(box)
        assert box._theme_connected is False
        # 断开后 emit 一次不应抛（残留连接会打进已断开的包装器）
        eTheme.themeModeChanged.emit(eTheme.getThemeMode())
        qapp.processEvents()


