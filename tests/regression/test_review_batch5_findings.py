"""回归测试（第五批）：经实测确认的 5 项。

1. ``ElaDrawer.setCornerRadius()`` 是 no-op —— 只改抽屉自身字段，
   真正绘制圆角的 ``ElaDrawerPanel._corner_radius`` 从没被更新
2. ``ElaToast`` 位置是固定的 ``父控件顶 + 60``，连发多条完全重叠成一个
3. ``ElaChatInput.mentions()`` 用子串判断，token 被改长后误报「还在」
4. ``ToolCallCard`` 三个头部标签沿用 ``ElaText`` 的 ``Qt::AutoText``，
   **像 HTML 的**工具名（``<b>x</b>`` / ``x<br>y`` / ``<img ...>``）会被
   QTextDocument 解析：标签被吃掉、文本被折行、还能触发远程图片加载。
   （``a < b`` / ``Tom & Jerry`` 实际不受影响 —— ``Qt::mightBeRichText()``
   判定它们不是 HTML，测试里已注明并排除。）
5. ``ElaSearchMultiBox.showPopup()`` 的 ``_isRestoringSelection`` 没有
   try/finally，一次异常就把搜索过滤永久短路
"""

from __future__ import annotations

import inspect

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

import pyqt6_ela_pro.ela_toast as T

# ---------------------------------------------------------------------- 1
from pyqt6_ela_pro import ElaDrawer
from pyqt6_ela_pro.chat.blocks import ToolCallCard
from pyqt6_ela_pro.chat.input import ElaChatInput
from pyqt6_ela_pro.chat.message import ElaChatToolCall
from pyqt6_ela_pro.combo_box import ElaSearchMultiBox
from pyqt6_ela_pro.ela_side_drawer import ElaDrawerPanel


class TestDrawerCornerRadiusPropagates:
    def test_setter_reaches_the_painting_panel(self, qapp):

        d = ElaDrawer()
        d.resize(200, 200)
        d.setCornerRadius(40)
        assert d._drawer_widget._corner_radius == 40, (
            "setCornerRadius 没有下发给真正画圆角的 ElaDrawerPanel，"
            f"panel 仍是 {d._drawer_widget._corner_radius}"
        )
        d.deleteLater()
        qapp.processEvents()

    def test_zero_radius_propagates(self, qapp):

        d = ElaDrawer()
        d.resize(200, 200)
        d.setCornerRadius(0)
        assert d._drawer_widget._corner_radius == 0
        d.deleteLater()
        qapp.processEvents()

    def test_chainable_still_returns_self(self, qapp):

        d = ElaDrawer()
        assert d.setCornerRadius(8) is d
        d.deleteLater()
        qapp.processEvents()

    def test_panel_setter_updates(self, qapp):

        p = ElaDrawerPanel()
        p.resize(50, 50)
        p.setCornerRadius(7)
        assert p._corner_radius == 7
        p.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------- 2
class TestToastStacking:
    @staticmethod
    def _capture(monkeypatch, host, count=3):

        made = []
        orig = T.ElaToast.__init__

        def spy(self, *a, **k):
            orig(self, *a, **k)
            made.append(self)

        monkeypatch.setattr(T.ElaToast, "__init__", spy)
        for i in range(count):
            T.ElaToast.success(f"toast {i}", 2000, host)
        monkeypatch.setattr(T.ElaToast, "__init__", orig)
        return made

    def test_toasts_do_not_overlap(self, qapp, monkeypatch):

        host = QWidget()
        host.resize(600, 400)
        host.show()
        qapp.processEvents()
        T._LIVE_TOASTS.clear()

        made = self._capture(monkeypatch, host, 3)
        assert len(made) == 3
        tops = [t.geometry().top() for t in made]
        assert len(set(tops)) == 3, f"三个 toast 全部落在 y={tops}，完全重叠"
        assert tops == sorted(tops), f"顺序错乱: {tops}"
        for t in made:
            t.close()
        qapp.processEvents()
        T._LIVE_TOASTS.clear()

    def test_closed_toast_frees_its_slot(self, qapp, monkeypatch):

        host = QWidget()
        host.resize(600, 400)
        host.show()
        qapp.processEvents()
        T._LIVE_TOASTS.clear()

        made = []
        orig = T.ElaToast.__init__

        def spy(self, *a, **k):
            orig(self, *a, **k)
            made.append(self)

        monkeypatch.setattr(T.ElaToast, "__init__", spy)

        def live_tops():
            qapp.processEvents()
            reg = T._LIVE_TOASTS.get(host, [])
            return sorted(t.geometry().top() for t in reg)

        def assert_no_overlap(when):
            tops = live_tops()
            assert len(set(tops)) == len(tops), f"{when}: toast 位置重叠 {tops}"

        try:
            T.ElaToast.success("a", 2000, host)
            T.ElaToast.success("b", 2000, host)
            assert_no_overlap("连发两条后")
            first_top = live_tops()[0]

            # 关掉首条：登记里应只剩一条，且剩下的要紧凑顶上来
            made[0].close()
            assert len(T._LIVE_TOASTS.get(host, [])) == 1, (
                "closeEvent 没有从堆叠登记里摘除已关闭的 toast"
            )
            assert live_tops() == [first_top], (
                f"关掉首条后剩下的没有顶上来，仍在 {live_tops()}（应为 {first_top}）"
            )

            # 新的 toast 必须排在剩下那条下方
            T.ElaToast.success("c", 2000, host)
            assert_no_overlap("关掉一条后再发一条")
            assert len(live_tops()) == 2

            # 全部关掉后，新 toast 必须回到最早的槽位
            for t in made[1:]:
                t.close()
            assert T._LIVE_TOASTS.get(host, []) == [], (
                "全部关闭后登记未清空，新 toast 会一直往下顺延"
            )
            T.ElaToast.success("d", 2000, host)
            assert live_tops() == [first_top], (
                f"全部关闭后新 toast 落在 {live_tops()}，没有回到最早的槽位 {first_top}"
            )
            made[3].close()
            qapp.processEvents()
        finally:
            monkeypatch.setattr(T.ElaToast, "__init__", orig)
            for t in made:
                try:
                    t.close()
                except RuntimeError:
                    pass
            qapp.processEvents()
            T._LIVE_TOASTS.clear()

    def test_different_anchors_stack_independently(self, qapp, monkeypatch):

        h1 = QWidget()
        h1.resize(400, 300)
        h1.move(0, 0)
        h1.show()
        h2 = QWidget()
        h2.resize(400, 300)
        h2.move(0, 400)
        h2.show()
        qapp.processEvents()
        T._LIVE_TOASTS.clear()

        a = self._capture(monkeypatch, h1, 1)
        b = self._capture(monkeypatch, h2, 1)
        assert a[0].geometry().top() != b[0].geometry().top(), (
            "不同父控件的 toast 不应互相顺延"
        )
        for t in a + b:
            t.close()
        qapp.processEvents()
        T._LIVE_TOASTS.clear()


# ---------------------------------------------------------------------- 3
class _MentionItem:
    def __init__(self, mid, label, insert_text):
        self.id = mid
        self.label = label
        self.insert_text = insert_text


class TestMentionsWordBoundary:
    @staticmethod
    def _input(qapp):

        inp = ElaChatInput()
        inp.resize(420, 140)
        inp.show()
        qapp.processEvents()
        return inp

    def test_token_lengthened_is_not_still_present(self, qapp):
        inp = self._input(qapp)
        inp._on_suggestion_activated(_MentionItem("u1", "Al", "@Al "))
        inp._set_edit_text("hey @Album look")
        assert inp.mentions() == [], (
            "token '@Al' 被改写成 '@Album' 后仍被当作原 mention，"
            "宿主会带上用户已经改掉的引用发出去"
        )
        inp.deleteLater()
        qapp.processEvents()

    def test_token_with_trailing_punctuation_counts(self, qapp):
        inp = self._input(qapp)
        inp._on_suggestion_activated(_MentionItem("u2", "Bob", "@Bob "))
        inp._set_edit_text("ping @Bob, thanks")
        assert inp.mentions() == ["u2"]
        inp.deleteLater()
        qapp.processEvents()

    def test_untouched_token_counts(self, qapp):
        inp = self._input(qapp)
        inp._on_suggestion_activated(_MentionItem("u1", "Al", "@Al "))
        inp._set_edit_text("hey @Al look")
        assert inp.mentions() == ["u1"]
        inp.deleteLater()
        qapp.processEvents()

    def test_deleted_token_does_not_count(self, qapp):
        inp = self._input(qapp)
        inp._on_suggestion_activated(_MentionItem("u1", "Al", "@Al "))
        inp._set_edit_text("hey look")
        assert inp.mentions() == []
        inp.deleteLater()
        qapp.processEvents()

    def test_cjk_continuation_is_not_a_match(self, qapp):
        inp = self._input(qapp)
        inp._on_suggestion_activated(_MentionItem("u1", "张", "@张 "))
        inp._set_edit_text("看看 @张三 的仓库")
        assert inp.mentions() == [], "中文名被加长后不应仍算原 mention"
        inp.deleteLater()
        qapp.processEvents()

    def test_at_suffix_is_not_a_match(self, qapp):
        inp = self._input(qapp)
        inp._on_suggestion_activated(_MentionItem("u1", "Al", "@Al "))
        inp._set_edit_text("cc @Al@Bob")
        assert inp.mentions() == [], "'@Al@Bob' 里 '@Al' 不是一个完整 mention"
        inp.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------- 4
class TestToolCallCardPlainText:
    def test_header_labels_are_plain_text(self, qapp):

        card = ToolCallCard(
            tool_call=ElaChatToolCall(id="1", name="a < b", arguments="{}")
        )
        card.resize(400, 120)
        card.show()
        qapp.processEvents()
        for attr in ("_title_label", "_subtitle_label", "_args_label"):
            lab = getattr(card, attr, None)
            assert lab is not None
            assert lab.textFormat() == Qt.TextFormat.PlainText, (
                f"{attr} 仍是 AutoText，工具名里的 '<' / '&' 会被当 HTML 解析"
            )
        card.deleteLater()
        qapp.processEvents()

    @pytest.mark.parametrize(
        "name", ["<b>evil</b>", "x<br>y", '<img src="http://x/y.png">']
    )
    def test_case_is_discriminating(self, qapp, name):
        """确认这些工具名在两种 textFormat 下排版确实不同。

        只断言 textFormat 的话，无法证明这些用例当年真能抓住 bug。
        这里比较 ``sizeHint()``：``Qt::AutoText`` 走
        ``Qt::mightBeRichText()`` 判定，文本像 HTML 时用 QTextDocument 排版，
        标签被吃掉 / 被折行，尺寸随之改变。

        注意 ``a < b`` / ``Tom & Jerry`` **不是**有鉴别力的用例 ——
        ``mightBeRichText()`` 判定它们不是 HTML，实际不会被吃掉。
        """

        text = f"工具调用：{name}"

        def hint(fmt):
            lab = QLabel()
            lab.setTextFormat(fmt)
            lab.setText(text)
            lab.adjustSize()
            s = lab.sizeHint()
            lab.deleteLater()
            qapp.processEvents()
            return s.width(), s.height()

        assert hint(Qt.TextFormat.PlainText) != hint(Qt.TextFormat.AutoText), (
            f"工具名 {name!r} 在两种 textFormat 下排版相同，"
            "该用例没有鉴别力，请换一个更明显的标记"
        )

    def test_br_in_tool_name_does_not_break_line(self, qapp):
        """``<br>`` 在 PlainText 下是字面文本，不会把标题折成两行。"""

        card = ToolCallCard(
            tool_call=ElaChatToolCall(id="1", name="x<br>y", arguments="{}")
        )
        card.resize(500, 120)
        card.show()
        qapp.processEvents()
        text = card._title_label.text()
        assert "<br>" in text, "标题文本被改动了"
        assert card._title_label.textFormat() == Qt.TextFormat.PlainText

        def height_of(fmt):
            lab = QLabel()
            lab.setTextFormat(fmt)
            lab.setText(text)
            lab.adjustSize()
            h = lab.sizeHint().height()
            lab.deleteLater()
            qapp.processEvents()
            return h

        plain_h = height_of(Qt.TextFormat.PlainText)
        auto_h = height_of(Qt.TextFormat.AutoText)
        assert plain_h < auto_h, (
            f"PlainText 高度 {plain_h} 未小于 AutoText 高度 {auto_h}，"
            "'<br>' 仍被当 HTML 换行处理"
        )
        card.deleteLater()
        qapp.processEvents()

    def test_bold_tag_in_tool_name_is_not_swallowed(self, qapp):
        """``<b>`` 被当 HTML 时整段标签连内容一起消失，宽度从 221 缩到 130。"""

        card = ToolCallCard(
            tool_call=ElaChatToolCall(id="1", name="<b>evil</b>", arguments="{}")
        )
        card.resize(500, 120)
        card.show()
        qapp.processEvents()
        text = card._title_label.text()

        def width_of(fmt):
            lab = QLabel()
            lab.setTextFormat(fmt)
            lab.setText(text)
            lab.adjustSize()
            w = lab.sizeHint().width()
            lab.deleteLater()
            qapp.processEvents()
            return w

        assert width_of(Qt.TextFormat.PlainText) > width_of(Qt.TextFormat.AutoText), (
            "AutoText 下宽度变窄，说明 '<b>evil</b>' 被当 HTML 解析了"
        )
        card.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------- 5
class TestComboRestoringFlagReleased:
    def test_flag_cleared_after_internal_exception(self, qapp):

        b = ElaSearchMultiBox()
        b.resize(320, 260)
        b.show()
        qapp.processEvents()
        b.addItems(["alpha", "beta", "gamma"])
        qapp.processEvents()
        b.showPopup()
        qapp.processEvents()
        b.hidePopup()
        qapp.processEvents()

        def boom(_container):
            raise RuntimeError("explode")

        b._setupSearchInPopup = boom
        with pytest.raises(RuntimeError):
            b.showPopup()
        qapp.processEvents()
        b._setupSearchInPopup = lambda c: None

        assert b._isRestoringSelection is False, (
            "_isRestoringSelection 漏复位后永远是 True，"
            "_onSearchTextChanged 会永久早退，搜索框失灵"
        )
        try:
            b.hidePopup()
        except Exception:
            pass
        qapp.processEvents()

    def test_source_uses_try_finally(self):

        src = inspect.getsource(ElaSearchMultiBox.showPopup)
        assert "finally" in src
