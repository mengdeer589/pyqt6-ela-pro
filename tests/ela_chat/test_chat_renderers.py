"""工具结果富渲染注册表（``pyqt6_ela_pro.chat.renderers``）。

守三件容易踩的事：

1. **生命周期** —— 卡片把渲染器 widget ``addWidget`` 进布局后**必须自己持有
   Python 引用**，否则包装器被 GC，之后调 ``updateToolResult`` 就是解引用已
   释放内存 = 无 traceback 崩溃（与 ``setItemDelegate`` 同一死法）；
2. **异常隔离** —— 工厂跑在「用户点开卡片」的 Qt 回调链里，宿主渲染器的
   bug 冒出去就是 0xC0000409 静默终止整个进程。渲染器是增强不是可选功能；
3. **副标题去重** —— 注册表的 ``subtitle`` 返回 ``(键, 值)``，那个键要自动
   从参数摘要里排除，否则「3 个文件 files=[...]」同一个值显示两遍。
"""

from __future__ import annotations

import gc

import pytest
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from pyqt6_ela_pro.chat import (
    ElaChatBubble,
    ToolRenderContext,
    clearToolRenderers,
    registerToolRenderer,
    toolRenderer,
    toolRendererGroupable,
    toolRendererNames,
    unregisterToolRenderer,
)
from pyqt6_ela_pro.chat.blocks import (
    CONTEXT_TOOLS,
    ToolCallCard,
    toolArgumentPairs,
)
from pyqt6_ela_pro.chat.message import ElaChatToolCall, ElaChatToolStatusType
from pyqt6_ela_pro.chat.renderers import (
    _CONTEXT_TOOLS,
    parseToolArguments,
    toolRendererSubtitle,
)


class TestContextToolsParity:
    def test_renderers_copy_matches_blocks(self):
        """renderers 不能 import blocks（成环），复制的上下文工具清单必须一致。"""
        assert set(CONTEXT_TOOLS) == set(_CONTEXT_TOOLS)


@pytest.fixture(autouse=True)
def _clean_registry():
    """用例之间隔离注册表状态。"""
    clearToolRenderers()
    yield
    clearToolRenderers()


class _Recorder(QWidget):
    """记录收到的推送；带 ``sip`` 守卫模拟宿主自行 ``deleteLater``。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.pushes: list = []
        self.label = QLabel(self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)

    def updateToolResult(self, result: str, status: str) -> None:
        self.pushes.append((result, status))
        self.label.setText(result or "")


class _Plain(QWidget):
    """没有 ``updateToolResult`` 的渲染器（协议可选）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        QVBoxLayout(self)


def _card(name="patch", args='{"files": ["a.py"]}', make=None) -> ToolCallCard:
    return ToolCallCard(
        tool_call=ElaChatToolCall(id="c1", name=name, arguments=args),
        defaultOpen=True,
    )


def _open(card: ToolCallCard, qapp=None) -> None:
    card.resize(640, 60)
    card.show()
    card._on_toggled(True)
    if qapp is not None:
        qapp.processEvents()


# ------------------------------------------------------------------ 注册表契约
class TestRegistryContract:
    def test_register_and_lookup(self):
        def factory(ctx):
            return QWidget()

        registerToolRenderer("demo", factory)
        assert toolRenderer("demo") is factory
        assert toolRendererNames() == ["demo"]
        assert unregisterToolRenderer("demo") is True
        assert toolRenderer("demo") is None
        assert unregisterToolRenderer("demo") is False

    def test_duplicate_registration_raises(self):
        registerToolRenderer("demo", lambda ctx: QWidget())
        with pytest.raises(ValueError):
            registerToolRenderer("demo", lambda ctx: QWidget())
        # 显式覆盖才允许
        replacement = lambda ctx: QWidget()  # noqa: E731
        registerToolRenderer("demo", replacement, replace=True)
        assert toolRenderer("demo") is replacement

    @pytest.mark.parametrize(
        "name,factory", [("", lambda ctx: QWidget()), ("x", "not callable")]
    )
    def test_invalid_arguments_raise(self, name, factory):
        with pytest.raises(ValueError):
            registerToolRenderer(name, factory)

    def test_groupable_defaults(self):
        # 上下文工具注册渲染器 -> 默认退出分组（否则会被分组卡绕过）
        registerToolRenderer("read", lambda ctx: QWidget())
        registerToolRenderer("patch", lambda ctx: QWidget())
        assert toolRendererGroupable("read") is False
        assert toolRendererGroupable("patch") is True
        # 未注册的工具行为与注册表引入前一致
        assert toolRendererGroupable("grep") is True

    def test_groupable_explicit_override(self):
        registerToolRenderer("read", lambda ctx: QWidget(), groupable=True)
        assert toolRendererGroupable("read") is True

    def test_subtitle_shape_and_failure_fallback(self):
        registerToolRenderer(
            "demo", lambda ctx: QWidget(), subtitle=lambda a: ("k", "v")
        )
        assert toolRendererSubtitle("demo", "{}") == ("k", "v")
        # 抛异常 / 形状不对 / 未注册 —— 一律落回 ("", "")，宿主 bug 不该弄崩卡片
        registerToolRenderer("boom", lambda ctx: QWidget(), subtitle=lambda a: 1 / 0)
        assert toolRendererSubtitle("boom", "{}") == ("", "")
        registerToolRenderer("bad", lambda ctx: QWidget(), subtitle=lambda a: "only")
        assert toolRendererSubtitle("bad", "{}") == ("", "")
        assert toolRendererSubtitle("missing", "{}") == ("", "")


# ------------------------------------------------------------------ 参数解析
class TestParseToolArguments:
    def test_dict_passthrough(self):
        assert parseToolArguments({"a": 1}) == {"a": 1}

    def test_json_object(self):
        assert parseToolArguments('{"a": 1}') == {"a": 1}

    @pytest.mark.parametrize("bad", ["", "   ", None, 123, "[1,2]", "null"])
    def test_bad_inputs_give_empty(self, bad):
        assert parseToolArguments(bad) == {}

    def test_truncated_json_keeps_raw_text(self):
        """流式半截参数不能整段消失（否则卡片上一片空白）。"""
        assert parseToolArguments('"path": "src/a') == {"": '"path": "src/a'}


# ------------------------------------------------------------------ 卡片集成
class TestCardIntegration:
    def test_unregistered_tool_keeps_text_body(self, qapp, make):
        card = _card()
        make.track(card)
        _open(card, qapp)
        assert card._renderer_widget is None
        assert card._args_caption is not None
        assert card._args_value.text() == '{"files": ["a.py"]}'
        assert toolArgumentPairs('{"files": ["a.py"]}') == ['files=["a.py"]']

    def test_registered_renderer_replaces_body(self, qapp, make):
        registerToolRenderer("patch", lambda ctx: _Recorder())
        card = _card()
        make.track(card)
        _open(card, qapp)
        assert card._renderer_widget is not None
        # 默认纯文本区没有建
        assert card._args_caption is None
        assert isinstance(card._renderer_widget, _Recorder)

    def test_factory_exception_falls_back_to_text(self, qapp, make):
        def boom(ctx):
            raise RuntimeError("渲染器炸了")

        registerToolRenderer("patch", boom)
        card = _card()
        make.track(card)
        _open(card, qapp)  # 不崩 = 通过
        assert card._renderer_widget is None
        assert card._args_caption is not None

    def test_factory_returning_none_falls_back(self, qapp, make):
        registerToolRenderer("patch", lambda ctx: None)
        card = _card()
        make.track(card)
        _open(card, qapp)
        assert card._renderer_widget is None
        assert card._args_caption is not None

    def test_context_carries_snapshot(self, qapp, make):
        seen = {}

        def factory(ctx):
            seen["ctx"] = ctx
            return _Recorder()

        registerToolRenderer("patch", factory)
        card = _card()
        make.track(card)
        card.setMessageId(42)
        _open(card, qapp)
        ctx = seen["ctx"]
        assert isinstance(ctx, ToolRenderContext)
        assert ctx.messageId == 42
        assert ctx.toolCallId == "c1"
        assert ctx.name == "patch"
        assert ctx.parsedArguments() == {"files": ["a.py"]}
        assert ctx.status == ElaChatToolStatusType.Running
        assert ctx.isError is False
        # 快照不可变
        with pytest.raises(Exception):
            ctx.status = "done"


class TestUpdateProtocol:
    def test_result_change_is_pushed(self, qapp, make):
        registerToolRenderer("patch", lambda ctx: _Recorder())
        card = _card()
        make.track(card)
        _open(card, qapp)
        widget = card._renderer_widget
        card.setResult("done!", ok=True)
        assert widget.pushes[-1] == ("done!", ElaChatToolStatusType.Done)

    def test_status_change_is_pushed(self, qapp, make):
        registerToolRenderer("patch", lambda ctx: _Recorder())
        card = _card()
        make.track(card)
        _open(card, qapp)
        widget = card._renderer_widget
        card.setStatus(ElaChatToolStatusType.Done)
        assert widget.pushes[-1][1] == ElaChatToolStatusType.Done

    def test_widget_without_protocol_is_fine(self, qapp, make):
        registerToolRenderer("patch", lambda ctx: _Plain())
        card = _card()
        make.track(card)
        _open(card, qapp)
        card.setResult("x", ok=True)  # 不崩 = 通过
        assert card._renderer_widget is not None

    def test_push_exception_is_swallowed(self, qapp, make):
        class Hostile(_Recorder):
            def updateToolResult(self, result, status):
                raise ValueError("宿主 bug")

        registerToolRenderer("patch", lambda ctx: Hostile())
        card = _card()
        make.track(card)
        _open(card, qapp)
        card.setResult("x", ok=True)  # 不崩 = 通过

    def test_push_after_card_destroyed_is_guarded(self, qapp, make):
        registerToolRenderer("patch", lambda ctx: _Recorder())
        card = _card()
        _open(card, qapp)
        make.track(card)
        card.deleteLater()
        qapp.processEvents()
        qapp.processEvents()
        # 迟到推送：sip 守卫拦住，不抛 RuntimeError（那同样是 abort）
        card._notify_renderer()


class TestLifetime:
    def test_card_holds_python_reference(self, qapp, make):
        """坑 1 的正面证明：渲染器 widget 不会被提前回收。"""
        registerToolRenderer("patch", lambda ctx: _Recorder())
        card = _card()
        make.track(card)
        _open(card, qapp)
        widget = card._renderer_widget
        gc.collect()  # 没有 Python 引用的话这里就死了
        assert widget.pushes == [], "刚建好还没推送过，且对象仍可访问"
        widget.updateToolResult("still alive", "done")
        assert widget.pushes[-1] == ("still alive", "done")


# ------------------------------------------------------------------ 副标题去重
class TestSubtitleDedup:
    def test_registry_subtitle_key_is_excluded_from_args(self, qapp, make):
        args = '{"files": ["a.py", "b.py"], "root": "src"}'
        registerToolRenderer(
            "patch",
            lambda ctx: _Recorder(),
            subtitle=lambda a: ("files", "2 个文件"),
        )
        card = _card(args=args)
        make.track(card)
        card.resize(900, 40)
        card.show()
        qapp.processEvents()
        assert card._subtitle_text == "2 个文件"
        assert "files=" not in card._args_text, card._args_text
        assert "root=src" in card._args_text

    def test_subtitle_not_matching_any_key(self, qapp, make):
        """副标题不对应任何参数键时，参数摘要照常全显（不误排除）。"""
        registerToolRenderer(
            "patch",
            lambda ctx: _Recorder(),
            subtitle=lambda a: ("", "3 个文件"),
        )
        card = _card(args='{"files": ["a.py"]}')
        make.track(card)
        card.resize(900, 40)
        card.show()
        qapp.processEvents()
        assert card._subtitle_text == "3 个文件"
        assert 'files=["a.py"]' in card._args_text


# ------------------------------------------------------------------ 气泡集成
class TestBubbleIntegration:
    def test_message_id_reaches_context(self, qapp, make):
        seen = {}
        registerToolRenderer(
            "patch", lambda ctx: (seen.__setitem__("ctx", ctx), _Recorder())[1]
        )
        bubble = make(ElaChatBubble, "assistant")
        bubble.setMessageId(7)
        callId = bubble.addToolCall("patch", '{"files": []}')
        assert callId
        card = bubble.toolPanel().findChild(ToolCallCard)
        assert card is not None
        card.setOpened(True)
        assert seen["ctx"].messageId == 7

    def test_context_tool_renderer_bypasses_grouping(self, qapp, make):
        bubble = make(ElaChatBubble, "assistant")
        registerToolRenderer("read", lambda ctx: _Recorder())
        assert bubble.toolGrouping() is True
        bubble.addToolCall("read", '{"path": "a.py"}')
        # 没进分组卡 => 没有 ContextToolGroupCard
        from pyqt6_ela_pro.chat.blocks import ContextToolGroupCard

        assert bubble.toolPanel().findChild(ContextToolGroupCard) is None
        assert bubble.toolPanel().findChild(ToolCallCard) is not None

    def test_context_tool_without_renderer_still_groups(self, qapp, make):
        from pyqt6_ela_pro.chat.blocks import ContextToolGroupCard

        bubble = make(ElaChatBubble, "assistant")
        bubble.addToolCall("read", '{"path": "a.py"}')
        assert bubble.toolPanel().findChild(ContextToolGroupCard) is not None
