"""回归测试：工具卡的三个 UI 决策（对照 opencode ``session-ui`` 的实现）。

A. **副标题与参数摘要去重** —— opencode 的 ``args()`` 有一组 ``skip``，把已被
   选作副标题的键从参数摘要里排除。我们原来没排除，``read(path="a.py")``
   会把 ``a.py`` 显示两遍（副标题 + ``path=a.py``），是纯冗余。

B. **运行中不显示参数摘要** —— 我们的工具参数是**分片流式到达**的（同一
   ``toolCallId`` 重复上报会更新 ``arguments``）。运行中显示半截参数既误导
   （看着像完整调用），又会因撞上省略预算而让整行宽度反复跳变。

C. **展开策略是可注入的纯函数** —— 「shell 要不要默认展开」「纯删除要不要
   折叠」是**宿主的产品决策**，与工具语义强相关，不该硬编码在库里。库默认
   只保留一条与领域无关且普遍正确的规则（失败时展开）。
"""

from __future__ import annotations

import json

import pytest
from PyQt6.QtWidgets import QLabel, QWidget

from pyqt6_ela_pro.chat import ElaChatView
from pyqt6_ela_pro.chat.blocks import (
    ContextToolGroupCard,
    ToolCallCard,
    toolArgumentPairs,
    toolDefaultOpen,
    toolDefaultOpenCoding,
    toolSubtitle,
    toolSubtitleParts,
)
from pyqt6_ela_pro.chat.bubble import ElaChatBubble
from pyqt6_ela_pro.chat.message import (
    ElaChatRoleType,
    ElaChatToolCall,
    ElaChatToolStatusType,
)


def _args(**kwargs) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


# ------------------------------------------------------------------ A
class TestSubtitleArgumentDedup:
    """去重**不变式**是「卡片头部不出现同一个值两遍」。

    实现上 ``toolArgumentPairs`` **不做隐式自动探测** —— 由调用方显式传
    ``excludeKey``。卡片是主要调用方：它先算出副标题（注册表优先，否则
    通用键名启发式），拿到键再传给 ``toolArgumentPairs``。之所以不把探测
    藏进 helper：注册表来的副标题可能压根不对应任何参数键（「3 个文件」），
    也可能对应一个自动探测选不中的键（``files`` 数组不是字符串），隐式
    探测对这两类一律失效。
    """

    def test_card_does_not_repeat_subtitle_value(self, qapp):
        """卡片级：``read(path=...)`` 的 path 只出现一次。"""
        card = ToolCallCard(
            tool_call=ElaChatToolCall(
                id="c1", name="read", arguments=_args(path="a.py", limit=10)
            )
        )
        card.resize(600, 40)
        card.show()
        qapp.processEvents()
        card.setArguments(_args(path="a.py", encoding="utf-8", limit=10))
        qapp.processEvents()
        assert card._subtitle_text == "a.py"
        assert card._args_text == "encoding=utf-8  limit=10"
        assert "path=" not in card._args_text

    def test_parts_returns_key_and_value(self):
        assert toolSubtitleParts(_args(path="a.py")) == ("path", "a.py")
        assert toolSubtitleParts(_args()) == ("", "")

    def test_pairs_without_exclude_key_are_raw(self):
        """不传 ``excludeKey`` 就是原始列表（不做隐式排除）。"""
        args = _args(path="a.py", limit=10)
        assert "path=a.py" in toolArgumentPairs(args)

    def test_exclude_key_drops_that_key(self):
        args = _args(path="a.py", encoding="utf-8", limit=10)
        pairs = toolArgumentPairs(args, excludeKey="path")
        assert pairs == ["encoding=utf-8", "limit=10"]

    def test_fallback_subtitle_key_also_excluded(self):
        """副标题的 fallback 分支（非白名单键）同样要参与去重。"""
        args = _args(zzz="唯一值", other=1)
        key, value = toolSubtitleParts(args)
        assert value == "唯一值"
        pairs = toolArgumentPairs(args, excludeKey=key)
        assert not any(p.startswith("zzz=") for p in pairs)

    def test_no_subtitle_key_means_nothing_excluded(self):
        """没有可作副标题的字符串时，不能误排除任何键。"""
        assert toolSubtitleParts(_args(n=5, flag=True)) == ("", "")
        pairs = toolArgumentPairs(_args(n=5, flag=True), excludeKey="")
        assert pairs == ["n=5", "flag=True"]

    @pytest.mark.parametrize("bad", ["not json", "", "{}", None, "[1,2]"])
    def test_bad_arguments_do_not_raise(self, bad):
        assert isinstance(toolArgumentPairs(bad), list)
        assert isinstance(toolSubtitle("read", bad), str)

    def test_group_card_rows_deduped(self, qapp):
        """分组卡的行也要去重（它同样显示副标题 + 参数）。"""
        card = ContextToolGroupCard()
        card.resize(500, 140)
        card.show()
        qapp.processEvents()
        card.addToolCall(
            ElaChatToolCall(id="c1", name="read", arguments=_args(path="a.py", limit=3))
        )
        card.addToolCall(
            ElaChatToolCall(
                id="c2", name="grep", arguments=_args(pattern="foo", path="b.py")
            )
        )
        qapp.processEvents()

        texts = [label.text() for label in card.findChildren(QLabel) if label.text()]
        assert any("a.py" in t for t in texts)
        assert not any("path=" in t for t in texts), (
            f"分组卡行里重复展示了 path：{texts}"
        )
        card.deleteLater()
        qapp.processEvents()


# ------------------------------------------------------------------ B
class TestHideArgsWhileRunning:
    def _card(self, qapp, arguments) -> ToolCallCard:
        card = ToolCallCard(
            tool_call=ElaChatToolCall(id="1", name="read", arguments=arguments)
        )
        card.resize(420, 90)
        card.show()
        qapp.processEvents()
        return card

    def test_hidden_while_running_shown_after_done(self, qapp):
        card = self._card(qapp, _args(path="a.py", limit=10))
        assert card._args_label.isVisible() is False, "运行中不应显示参数摘要"
        assert card._args_text, "文本仍要备好，只是不显示"
        card.setResult("文件内容", ok=True)
        qapp.processEvents()
        assert card._args_label.isVisible() is True, "完成后应显示参数摘要"
        card.deleteLater()
        qapp.processEvents()

    def test_hidden_for_partial_streamed_arguments(self, qapp):
        """参数只到一半时同样不显示（这是跳变的真正来源）。"""
        card = self._card(qapp, '{"path": "a')
        assert card._args_label.isVisible() is False
        card.setResult("done", ok=True)
        qapp.processEvents()
        card.deleteLater()
        qapp.processEvents()

    def test_subtitle_still_visible_while_running(self, qapp):
        """副标题不受影响 —— 它通常在参数第一片就完整了。"""
        card = self._card(qapp, _args(path="a.py"))
        assert card._subtitle_label.isVisible() is True
        card.deleteLater()
        qapp.processEvents()

    def test_error_result_shows_args(self, qapp):
        card = self._card(qapp, _args(path="a.py", limit=2))
        card.setResult("boom", ok=False)
        qapp.processEvents()
        assert card._args_label.isVisible() is True
        card.deleteLater()
        qapp.processEvents()


# ------------------------------------------------------------------ C
class TestDefaultOpenPolicy:
    def test_library_default_only_expands_failures(self):
        assert toolDefaultOpen("read", "{}", True) is False
        assert toolDefaultOpen("bash", "{}", False) is True, (
            "失败原因必须可见，折叠起来等于把最重要的信息藏起来"
        )

    @pytest.mark.parametrize("name", ["bash", "shell", "run", "exec", "terminal"])
    def test_coding_policy_expands_shell(self, name):
        assert toolDefaultOpenCoding(name, _args(command="ls -la"), True) is True

    @pytest.mark.parametrize(
        "arguments,expected",
        [
            ({"path": "a.py", "additions": 3, "deletions": 1}, True),
            ({"path": "a.py", "additions": 0, "deletions": 5}, False),
            ({"files": [{"type": "delete"}, {"type": "delete"}]}, False),
            ({"files": [{"type": "delete"}, {"type": "add"}]}, True),
            ({}, False),
        ],
    )
    def test_coding_policy_write_tools(self, arguments, expected):
        """写文件类：非纯删除展开、纯删除折叠（对齐 opencode 的 deletionOnly）。"""
        got = toolDefaultOpenCoding("edit", _args(**arguments), True)
        assert got is expected, f"{arguments} -> {got}，期望 {expected}"

    def test_coding_policy_still_expands_failures(self):
        assert toolDefaultOpenCoding("edit", "{}", False) is True

    def test_policy_is_pure(self):
        """纯函数：同样输入永远同样输出，无副作用。"""
        args = _args(command="ls")
        first = [toolDefaultOpenCoding("bash", args, True) for _ in range(5)]
        assert first == [True] * 5

    def test_bad_arguments_do_not_raise(self):
        for bad in (None, "", "not json", "[]", "null"):
            assert isinstance(toolDefaultOpenCoding("edit", bad, True), bool)


#: 宿主 QWidget 必须被强引用：局部变量被 GC 后 C++ 对象随之销毁，
#: 挂在它下面的气泡会连带失效（AGENTS.md 记的「顶层窗口必须保存引用」）。
_HOSTS: list = []


def _bubble(qapp) -> ElaChatBubble:

    host = QWidget()
    host.resize(700, 500)
    host.show()
    qapp.processEvents()
    _HOSTS.append(host)
    bubble = ElaChatBubble(ElaChatRoleType.Assistant, "", host)
    bubble.resize(600, 400)
    bubble.show()
    qapp.processEvents()
    return bubble


class TestPolicyInjection:
    def test_injected_policy_applied_to_single_card(self, qapp):
        bubble = _bubble(qapp)
        bubble.setToolDefaultOpen(lambda name, args, ok: name == "bash")
        bubble.addToolCall("bash", "{}")
        bubble.addToolCall("python", "{}")
        qapp.processEvents()
        cards = {call.name: bubble._tool_cards[call.id] for call in bubble.toolCalls()}
        assert isinstance(cards["bash"], ToolCallCard)
        assert cards["bash"].isOpened() is True
        assert cards["python"].isOpened() is False
        bubble.deleteLater()
        qapp.processEvents()

    def test_injected_policy_applied_to_group_card(self, qapp):
        """分组卡也走策略 —— 否则同一策略在两条路径上表现不一致。"""
        bubble = _bubble(qapp)
        bubble.setToolDefaultOpen(lambda name, args, ok: name == "read")
        bubble.addToolCall("read", "{}")
        qapp.processEvents()
        assert isinstance(bubble._group_card, ContextToolGroupCard)
        assert bubble._group_card.isOpened() is True
        bubble.deleteLater()
        qapp.processEvents()

    def test_raising_policy_falls_back(self, qapp):
        """宿主策略抛异常不得让建卡崩掉（回落到库默认）。"""
        bubble = _bubble(qapp)

        def boom(name, args, ok):
            raise RuntimeError("bad policy")

        bubble.setToolDefaultOpen(boom)
        callId = bubble.addToolCall("python", "{}")
        qapp.processEvents()
        card = bubble._tool_cards[callId]
        assert card.isOpened() is False  # 库默认 = 折叠
        bubble.deleteLater()
        qapp.processEvents()

    def test_none_resets_to_library_default(self, qapp):
        bubble = _bubble(qapp)
        bubble.setToolDefaultOpen(lambda *a: True)
        bubble.setToolDefaultOpen(None)
        callId = bubble.addToolCall("python", "{}")
        qapp.processEvents()
        assert bubble._tool_cards[callId].isOpened() is False
        bubble.deleteLater()
        qapp.processEvents()

    def test_coding_policy_end_to_end(self, qapp):
        """编码 agent 场景：直接注入库里提供的参考实现。"""
        bubble = _bubble(qapp)
        bubble.setToolDefaultOpen(toolDefaultOpenCoding)
        shellId = bubble.addToolCall("bash", _args(command="ls"))
        pyId = bubble.addToolCall("python", "{}")
        qapp.processEvents()
        assert bubble._tool_cards[shellId].isOpened() is True
        assert bubble._tool_cards[pyId].isOpened() is False
        bubble.deleteLater()
        qapp.processEvents()

    def test_existing_cards_untouched_by_policy_change(self, qapp):
        """策略只影响**新建**卡片，不该把用户手动折叠的卡片弹开。"""
        bubble = _bubble(qapp)
        callId = bubble.addToolCall("python", "{}")
        qapp.processEvents()
        card = bubble._tool_cards[callId]
        assert card.isOpened() is False
        bubble.setToolDefaultOpen(lambda *a: True)
        qapp.processEvents()
        assert card.isOpened() is False, "策略变更不得影响已存在的卡片"
        bubble.deleteLater()
        qapp.processEvents()

    def test_error_result_expands_regardless(self, qapp):
        """失败时展开是库默认策略的一部分，与注入的策略无关。"""
        bubble = _bubble(qapp)
        bubble.setToolDefaultOpen(lambda *a: False)
        callId = bubble.addToolCall("python", "{}")
        qapp.processEvents()
        card = bubble._tool_cards[callId]
        assert card.isOpened() is False
        card.setResult("boom", ok=False)
        qapp.processEvents()
        assert card.isOpened() is True, "失败原因必须可见"
        assert card.status() == ElaChatToolStatusType.Error
        bubble.deleteLater()
        qapp.processEvents()

    def test_new_card_is_not_treated_as_failed(self, qapp):
        """建卡时结果还没到，``ok`` 必须按「非失败」传。

        守卫一个真实踩过的坑：``ok`` 传 ``False`` 会被策略读成「已失败」，
        而库默认策略是「失败时展开」-> **每张卡都自动展开**。
        """
        bubble = _bubble(qapp)
        seen = []

        def policy(name, args, ok):
            seen.append(ok)
            return False

        bubble.setToolDefaultOpen(policy)
        bubble.addToolCall("python", "{}")
        qapp.processEvents()
        assert seen and all(ok is True for ok in seen), (
            f"建卡时把 ok 传成了 {seen}，策略会误判为失败"
        )
        bubble.deleteLater()
        qapp.processEvents()

    def test_default_cards_stay_collapsed(self, qapp):
        """最朴素的情形：库默认下普通成功的工具卡必须折叠。"""
        bubble = _bubble(qapp)
        for name in ("python", "fetch", "write", "edit", "bash"):
            callId = bubble.addToolCall(name, "{}")
            qapp.processEvents()
            assert bubble._tool_cards[callId].isOpened() is False, (
                f"{name} 在库默认策略下不应自动展开"
            )
        bubble.deleteLater()
        qapp.processEvents()


class TestViewLevelPolicy:
    """策略必须在 **view** 上可设 —— 气泡是内部对象，宿主拿到的是 view。"""

    def _view(self, qapp):

        host = QWidget()
        host.resize(760, 520)
        _HOSTS.append(host)
        host.show()
        qapp.processEvents()
        view = ElaChatView(host)
        view.resize(700, 480)
        view.show()
        qapp.processEvents()
        return view

    def test_view_exposes_setter_and_getter(self, qapp):
        view = self._view(qapp)
        assert callable(view.setToolDefaultOpen)
        assert view.toolDefaultOpenPolicy() is toolDefaultOpen
        view.setToolDefaultOpen(toolDefaultOpenCoding)
        assert view.toolDefaultOpenPolicy() is toolDefaultOpenCoding
        view.setToolDefaultOpen(None)
        assert view.toolDefaultOpenPolicy() is toolDefaultOpen

    def test_policy_applies_to_new_messages(self, qapp):
        view = self._view(qapp)
        view.setToolDefaultOpen(lambda name, args, ok: name == "bash")
        messageId = view.addMessage(ElaChatRoleType.Assistant, "")
        qapp.processEvents()
        bashId = view.addToolCall(messageId, "bash", "{}")
        pyId = view.addToolCall(messageId, "python", "{}")
        qapp.processEvents()
        cards = view._bubbles[messageId]._tool_cards
        assert cards[bashId].isOpened() is True
        assert cards[pyId].isOpened() is False

    def test_policy_applies_to_messages_created_before_setter(self, qapp):
        """先有消息、后设策略 —— 也要生效（与 setToolGrouping 同语义）。"""
        view = self._view(qapp)
        messageId = view.addMessage(ElaChatRoleType.Assistant, "")
        qapp.processEvents()
        view.addToolCall(messageId, "python", "{}")
        qapp.processEvents()
        view.setToolDefaultOpen(lambda name, args, ok: True)
        qapp.processEvents()
        # 已有卡片不被弹开（用户的折叠状态要保住）
        bubble = view._bubbles[messageId]
        assert all(not c.isOpened() for c in bubble._tool_cards.values()), (
            "改策略不得弹开已存在的卡片"
        )
        # 但之后的卡片走新策略
        newerId = view.addMessage(ElaChatRoleType.Assistant, "")
        qapp.processEvents()
        newCall = view.addToolCall(newerId, "python", "{}")
        qapp.processEvents()
        assert view._bubbles[newerId]._tool_cards[newCall].isOpened() is True

    def test_bad_policy_value_falls_back(self, qapp):
        view = self._view(qapp)
        view.setToolDefaultOpen("not callable")
        assert view.toolDefaultOpenPolicy() is toolDefaultOpen
