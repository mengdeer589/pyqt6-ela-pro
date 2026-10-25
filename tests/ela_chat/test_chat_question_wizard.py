"""问答型审批（逐题向导）的行为契约。

对应 opencode ``session-question-dock.tsx``。这里钉的是**不该被改回去**的
几条不变式，其中大半是踩过的坑：

1. **选中不发信号**。旧实现是「点候选项 = 立即 ``replied.emit``」，所以
   模型一次问三道题时，用户答第一道就把整轮提交了。逐题向导必须先收齐再提交。
2. **未答题整条不进 payload** —— 不是空串、不是空数组。空数组会被模型读成
   「用户答了『一个都不选』」。
3. **自定义答案要真的进答案**。旧实现在「自己写一个」那行挂了输入框，但
   ``toPlainText()`` 一次都没被调用 —— 纯装饰品。
4. **候选卡不开 ``setCheckable``**。勾选真相只有一份（外层状态机灌进来的
   ``_picked``）；Qt 自己那份 ``checked`` 永远是 False，于是每次点击都发
   ``toggled(True)``，多选的「再点一下取消」直接失效。
5. **快捷键必须挂在候选行上**。焦点常驻在行里，键盘事件发给行、不冒泡回卡片
   —— 只在卡片上重写 ``keyPressEvent`` 的话，数字键和 ``Ctrl+⏎`` 永远收不到。
6. **写颜色测试别读 ``palette()``**（``ColorText`` 的 palette 是绘制前才自愈
   的陈旧值），offscreen 下 ``render()`` / ``grab()`` 也不渲染文字 —— 逐像素
   比对在这套件里不可用，只能断言意图色。

断言可见性一律用 ``isHidden()`` 而不是 ``isVisible()``：后者要求整条父链可见，
而这里的控件都挂在没 ``show()`` 的 chat 里，用 ``isVisible()`` 断言「该藏的藏了」
会假通过。
"""

from __future__ import annotations

import json

from _qthelpers import wait_until as _wait_until

import pytest
from PyQt6.QtCore import QEvent, QPoint, Qt, QPointF
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6ElaWidgetTools import (
    ElaCheckBox,
    ElaRadioButton,
    ElaThemeType,
    eTheme,
)

from pyqt6_ela_pro._styles import ColorText
from pyqt6_ela_pro.chat import (
    ElaChatOption,
    ElaChatPermission,
    ElaChatPermissionStatusType,
    ElaChatQuestion,
    ElaChatWidget,
)
from pyqt6_ela_pro.chat._question import (
    CUSTOM_ANSWER_LABEL,
    GLOW_ALPHA,
    QuestionOptionCard,
    question_colors,
)
from pyqt6_ela_pro.chat.blocks import PermissionCard, PermissionRecord


@pytest.fixture
def dark_mode():
    previous = eTheme.getThemeMode()
    eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
    yield
    eTheme.setThemeMode(previous)


def _q(key, question="?", options=(("A", ""), ("B", "")), **kwargs):
    return ElaChatQuestion(
        key=key,
        question=question,
        options=tuple(ElaChatOption(label, desc) for label, desc in options),
        **kwargs,
    )


def _turn(chat):
    chat.sendUserMessage("hi")
    return chat.beginAssistantMessage()


def _interactive(chat, mid, request_id="r1"):
    """取**仍在 dock 里等待用户操作**的交互卡。

    审批的交互不在时间线上（那是「现在要你动手」的位置，摆在历史流里既窄又旧），
    落定之后才会变成时间线上的记录卡。所以测交互一律走这里。
    """
    card = chat.chatView().interactivePermissionCard(mid, request_id)
    assert card is not None, f"消息 {mid} 上没有待答复的审批卡 {request_id}"
    return card


def _record(chat, mid, request_id="r1"):
    """取时间线上的**记录卡**（用户答完之后才有）。"""
    return chat.chatView().permissionCard(mid, request_id)


def _single(chat, mid, **kwargs):
    request = ElaChatPermission(
        request_id="r1", action="question", questions=(_q("q0", **kwargs),)
    )
    chat.chatView().beginPermission(mid, request)
    return _interactive(chat, mid)


def _wizard(chat, mid, count=2, **kwargs):
    chat.chatView().beginPermission(
        mid,
        ElaChatPermission(
            request_id="r1",
            action="question",
            questions=tuple(_q(f"q{i}", **kwargs) for i in range(count)),
        ),
    )
    return _interactive(chat, mid)


def _press(card, key, mods=Qt.KeyboardModifier.NoModifier, row=0):
    """把按键发到**候选行**上（真实路径：焦点在行里，事件不冒泡回卡片）。"""
    qapp = QApplication.instance()
    target = card._option_buttons[row] if row is not None else card
    qapp.sendEvent(target, QKeyEvent(QEvent.Type.KeyPress, key, mods))
    qapp.processEvents()


class TestWizardShape:
    """单题 / 多题的形态。"""

    def test_single_question_has_no_progress(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat))
        assert card.questionCount() == 1
        assert card._segment_box.isHidden(), "单题时进度条是纯噪音"
        assert card._progress.isHidden()

    def test_multi_question_shows_progress(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=3)
        assert card.questionCount() == 3
        assert not card._segment_box.isHidden()
        assert len(card._segments) == 3
        assert card._progress.text() == "1 / 3"
        assert [seg._active for seg in card._segments] == [True, False, False]

    def test_progress_tracks_tab(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=3)
        card._set_tab(2)
        assert card._progress.text() == "3 / 3"

    def test_custom_row_is_last(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""), ("B", "")))
        rows = card._option_buttons
        assert len(rows) == 3
        assert not rows[0].isCustom() and not rows[1].isCustom()
        assert rows[2].isCustom()
        assert rows[2]._label.text() == CUSTOM_ANSWER_LABEL

    def test_custom_false_hides_row(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), custom=False)
        assert not any(row.isCustom() for row in card._option_buttons)

    @pytest.mark.parametrize("multi", [False, True])
    def test_no_duplicate_hint_row(self, qapp, make, multi):
        """**不设**「可多选 / 选择一个答案」提示行。

        题面里通常已经写了「（可多选）」，再来一行是纯重复；而单选 / 多选本来
        就该由标记形态（圆 / 方）传达，opencode 的 dock 也没有这一行。少一行是
        少一行垂直空间。
        """
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), multiple=multi)
        assert not hasattr(card, "_question_hint")

    @pytest.mark.parametrize(
        "multi,cls", [(False, ElaRadioButton), (True, ElaCheckBox)]
    )
    def test_mark_widget_matches_multiplicity(self, qapp, make, multi, cls):
        """单选 = ``ElaRadioButton``（圆），多选 = ``ElaCheckBox``（方）。

        自绘版本两种模式画得一模一样，用户根本分不出单选还是多选 —— 而这恰恰是
        这个控件唯一要传达的信息。
        """
        chat = make(ElaChatWidget)
        card = _single(
            chat, _turn(chat), multiple=multi, options=(("A", ""), ("B", ""))
        )
        marks = [row.markWidget() for row in card._option_buttons]
        assert marks
        assert all(isinstance(m, cls) for m in marks), marks

    def test_marks_follow_picked_state(self, qapp, make):
        """标记的勾选态由卡片状态机灌进去（``setChecked``），自己不自己算。"""
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""), ("B", "")))
        row = card._option_buttons[1]
        row.activate.emit("B")
        assert row.markWidget().isChecked()
        assert not card._option_buttons[0].markWidget().isChecked()

    def test_header_runs_inline_in_the_title_row(self, qapp, make):
        """短标签走**标题行**，不单独占一行。

        单独一行时它看起来就像「题面莫名换行了」—— 一行弱化小字 + 一行正文，
        读者会以为是宽度不够导致的折行。
        """
        chat = make(ElaChatWidget)
        card = _single(
            chat,
            _turn(chat),
            header="STEP",
        )
        assert not card._tag.isHidden()
        # 前缀分隔符：标题「需要你回答」+ 短标签「范围」不加区分会糊成一片
        assert card._tag.text() == "\u00b7 STEP"

    def test_no_header_means_no_tag(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), header="")
        assert card._tag.isHidden()

    def test_title_is_primary_text_colour_not_muted(self, qapp, make, dark_mode):
        """标题 = **主文本色**，不是灰的。

        对齐 opencode ``[data-slot="question-header-title"]``：
        ``14px / medium / var(--v2-text-text-base)`` —— 与题面同色同级。
        此前 pending 态把标题染成 ``blend(base, text, 0.35)``，整条头部弱得读不出，
        而它恰恰是「现在需要你做什么」这句话本身（用户反馈：「顶部怎么能是灰色」）。
        """
        from pyqt6_ela_pro.chat._theme import text_color

        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), header="范围")
        assert card._title.textColor() == text_color(eTheme.getThemeMode())
        assert card._title.font().pixelSize() == 14

    def test_tag_and_progress_stay_muted(self, qapp, make):
        """短标签与「N / M」是注记，退到弱化色（但标题不退）。"""
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=2)
        colors = question_colors(eTheme.getThemeMode())
        assert card._tag.textColor() == colors["hint"]
        assert card._progress.textColor() != card._title.textColor()

    def test_progress_segments_are_capsules(self, qapp, make):
        """进度段 = 16×2 **全圆角胶囊**（opencode ``border-radius: 999px``）。

        「细条像划痕」的观感其实来自圆角：画成 1px 圆角就成了方头短横。
        """
        from pyqt6_ela_pro.chat._question import SEGMENT_BAR, SEGMENT_HIT

        assert SEGMENT_BAR == (16, 2)
        assert SEGMENT_HIT == 16
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=3)
        assert not card._segment_box.isHidden()

    def test_approve_has_no_tag(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        chat.chatView().beginPermission(
            mid, ElaChatPermission(request_id="r1", action="edit")
        )
        assert _interactive(chat, mid)._tag.isHidden()


class TestAnswerPayload:
    """答案编码：单选塌缩、多选发数组、未答整条省略。"""

    def test_single_select_is_scalar(self, qapp, make):
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(
            lambda i, r, rep, a, f: seen.append((rep, json.loads(a)))
        )
        card = _single(chat, _turn(chat))
        card._option_buttons[1].activate.emit("B")
        card._go_next()
        assert seen == [("allowed", {"q0": "B"})]

    def test_selecting_does_not_emit(self, qapp, make):
        """选中**不能**立刻发信号（旧实现就是这里错的）。"""
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        card = _single(chat, _turn(chat))
        card._option_buttons[0].activate.emit("A")
        assert seen == [], "逐题向导要先收齐再提交"

    def test_multi_select_is_array(self, qapp, make):
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(
            lambda i, r, rep, a, f: seen.append((rep, json.loads(a)))
        )
        card = _single(
            chat, _turn(chat), multiple=True, options=(("A", ""), ("B", ""), ("C", ""))
        )
        card._option_buttons[0].activate.emit("A")
        card._option_buttons[2].activate.emit("C")
        card._go_next()
        assert seen == [("allowed", {"q0": ["A", "C"]})]

    def test_toggle_off_multi(self, qapp, make):
        """多选再点一次 = 取消（**这条曾经是坏的**，见模块 docstring 第 4 点）。"""
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), multiple=True)
        row = card._option_buttons[0]
        row.activate.emit("A")
        assert card.answers() == {"q0": ["A"]}
        row.activate.emit("A")
        assert card.answers() == {}, "再点一次要能取消"
        row.activate.emit("A")
        card._option_buttons[1].activate.emit("B")
        assert card.answers() == {"q0": ["A", "B"]}

    def test_unanswered_question_omitted(self, qapp, make):
        """未答题**整条不进 payload** —— 不是空串、不是空数组。"""
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(a))
        card = _wizard(chat, _turn(chat), count=3)
        card._option_buttons[0].activate.emit("A")
        card._set_tab(2)
        card._go_next()
        assert json.loads(seen[0]) == {"q0": "A"}

    def test_all_answered(self, qapp, make):
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(a))
        card = _wizard(chat, _turn(chat), count=2)
        card._option_buttons[0].activate.emit("A")
        card._go_next()
        card._option_buttons[1].activate.emit("B")
        card._go_next()
        assert json.loads(seen[0]) == {"q0": "A", "q1": "B"}

    def test_selection_survives_tab_switch(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=2)
        card._option_buttons[1].activate.emit("B")
        card._set_tab(1)
        card._set_tab(0)
        assert card.answers() == {"q0": ["B"]}
        assert card._option_buttons[1].isPicked(), "切回来选中态要还在"

    def test_custom_answer_reaches_payload(self, qapp, make):
        """自定义答案要真的进答案（**旧实现是纯装饰品**）。"""
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(
            lambda i, r, rep, a, f: seen.append(json.loads(a))
        )
        card = _single(chat, _turn(chat), options=())
        custom = card._option_buttons[0]
        custom.activate.emit("")
        assert custom.isEditing()
        custom.setEditorText("none of them")
        custom.commitEdit()
        card._go_next()
        assert seen == [{"q0": "none of them"}]

    def test_custom_multi_becomes_single_element_array(self, qapp, make):
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(
            lambda i, r, rep, a, f: seen.append(json.loads(a))
        )
        card = _single(chat, _turn(chat), multiple=True, options=())
        custom = card._option_buttons[0]
        custom.activate.emit("")
        custom.setEditorText("all of them")
        custom.commitEdit()
        card._go_next()
        assert seen == [{"q0": ["all of them"]}]

    def test_custom_and_option_are_exclusive(self, qapp, make):
        """选了候选项就取消自定义选中 —— 二者没法同时成立。"""
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""),))
        custom = card._option_buttons[-1]
        custom.activate.emit("")
        custom.setEditorText("mine")
        custom.commitEdit()
        assert card.answers() == {"q0": ["mine"]}
        card._option_buttons[0].activate.emit("A")
        assert card.answers() == {"q0": ["A"]}, "选了候选项就应丢掉自定义"

    def test_custom_draft_survives_tab_switch(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=2)
        custom = card._option_buttons[-1]
        custom.activate.emit("")
        custom.setEditorText("draft")
        custom.commitEdit()
        card._set_tab(1)
        card._set_tab(0)
        assert card.answers() == {"q0": ["draft"]}

    def test_empty_custom_text_not_accepted(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=())
        custom = card._option_buttons[0]
        custom.activate.emit("")
        custom.setEditorText("   ")
        custom.commitEdit()
        assert card.answers() == {}, "空白不算答案"

    def test_mark_click_checks_and_opens_editor(self, qapp, make):
        """点标记（自定义行）= 选中并展开输入框；没敲内容仍**不算答案**。

        对齐 opencode 的 ``customToggle``：标记不再是个「没内容就哑掉」的装饰。
        空文本不进 payload 是 ``_current_values`` 兜住的（答案编码契约不变）。
        """
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""),))
        question = card._questions()[0]
        custom = card._option_buttons[-1]
        card._on_mark_clicked(question, "")
        assert custom.isPicked() and custom.markWidget().isChecked()
        assert custom.isEditing(), "点标记就该能直接开始输入"
        assert card.answers() == {}, "没敲内容不算答案"

    @pytest.mark.parametrize("multi", [False, True])
    def test_custom_row_is_checked_after_commit(self, qapp, make, multi):
        """提交自定义答案后那一行必须亮起来（单选 = 圆点、多选 = 方框都勾上）。

        回归「单选时最后那项『输入自己的答案』选不中」：``_refresh_rows`` 原先
        用 ``row.value() in picked`` 分发选中态，而自定义行的 ``value()`` 是空串、
        ``picked`` 里装的是自定义文本 —— 答案进去了，行却永远不高亮、标记也不勾。
        """
        chat = make(ElaChatWidget)
        card = _single(
            chat, _turn(chat), multiple=multi, options=(("A", ""), ("B", ""))
        )
        custom = card._option_buttons[-1]
        custom.activate.emit("")
        custom.setEditorText("mine")
        custom.commitEdit()
        assert card.answers() == {"q0": ["mine"]}
        assert custom.isPicked()
        assert custom.markWidget().isChecked()

    def test_single_select_mark_never_cancels(self, qapp, make):
        """单选是 radio：再点自定义行的标记**不取消**答案，只是重新展开编辑器。

        旧行为（先「没内容哑掉」再「有内容就 toggle」）组合起来的后果是：用户敲完
        提交、再去点那个圆点确认一下，答案反而被取消 —— 表现就是「怎么都选不中」。
        """
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""),))
        custom = card._option_buttons[-1]
        custom.activate.emit("")
        custom.setEditorText("mine")
        custom.commitEdit()
        card._on_mark_clicked(card._questions()[0], "")
        assert card.answers() == {"q0": ["mine"]}
        assert custom.isPicked()

    def test_opening_editor_selects_custom_and_clears_option(self, qapp, make):
        """点整行展开 = 选中自定义（对齐 opencode 的 ``customOpen``）。

        单选下必须同时取消候选项，否则两根圆点同时亮着。
        """
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""),))
        card._option_buttons[0].activate.emit("A")
        custom = card._option_buttons[-1]
        custom.activate.emit("")
        assert custom.isEditing()
        assert custom.isPicked()
        assert not card._option_buttons[0].isPicked()
        assert card.answers() == {}, "还没敲字，自定义不构成答案"

    def test_picking_option_closes_custom_editor(self, qapp, make):
        """选中普通候选项时收起自定义输入框（别让两个答案并排看着同时选中）。"""
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""),))
        custom = card._option_buttons[-1]
        custom.activate.emit("")
        assert custom.isEditing()
        card._option_buttons[0].activate.emit("A")
        assert not custom.isEditing()
        assert not custom.isPicked()
        assert card.answers() == {"q0": ["A"]}

    def test_submit_commits_typed_custom_text(self, qapp, make):
        """敲了字**没按 Enter**、直接点「提交」—— 文本必须进 payload。

        回归：``commitEdit`` 原来只在 Enter 时被调，用户直接点提交（这是最常见的
        手势）就把那段文字静默丢掉了，实测 answer 是 ``{}``。对齐 opencode
        ``next()`` 的 ``if (editing) commitCustom()``。
        """
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(
            lambda i, r, rep, a, f: seen.append((rep, json.loads(a)))
        )
        card = _single(chat, _turn(chat), options=(("A", ""),))
        custom = card._option_buttons[-1]
        custom.activate.emit("")
        custom.setEditorText("typed but no enter")
        card._next_button.click()  # 真实按钮路径
        assert seen == [("allowed", {"q0": "typed but no enter"})]

    def test_next_commits_draft_before_leaving_question(self, qapp, make):
        """点「下一步」先落定这一题编辑框里的文字，再切题。"""
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=2)
        custom = card._option_buttons[-1]
        custom.activate.emit("")
        custom.setEditorText("draft")
        card._go_next()
        assert card.tabIndex() == 1
        assert card.answers() == {"q0": ["draft"]}

    def test_mark_click_toggles_off(self, qapp, make):
        """多选：再点一次标记 = 取消自定义勾选**并收起输入框**（单选没有这个语义）。"""
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), multiple=True, options=(("A", ""),))
        custom = card._option_buttons[-1]
        custom.activate.emit("")
        custom.setEditorText("mine")
        custom.commitEdit()
        assert card.answers() == {"q0": ["mine"]}
        card._on_mark_clicked(card._questions()[0], "")
        assert card.answers() == {}, "再点一次标记应取消自定义选中"
        assert not custom.isPicked()
        assert not custom.isEditing()

    def test_mark_click_on_normal_row_toggles_it(self, qapp, make):
        """普通候选行的标记 = 切该行勾选（与整行点击一致）。"""
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), multiple=True, options=(("A", ""), ("B", "")))
        question = card._questions()[0]
        card._on_mark_clicked(question, "A")
        assert card.answers() == {"q0": ["A"]}
        card._on_mark_clicked(question, "A")
        assert card.answers() == {}


class TestNavigation:
    def test_next_then_submit(self, qapp, make):
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        card = _wizard(chat, _turn(chat), count=2)
        assert card._next_button.text() == "下一步"
        assert card._back_button.isHidden()
        card._go_next()
        assert card.tabIndex() == 1
        assert not card._back_button.isHidden()
        assert card._next_button.text() == "提交"
        card._go_next()
        assert seen == ["allowed"]

    def test_back_button(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=2)
        card._go_next()
        card._go_back()
        assert card.tabIndex() == 0
        assert card._back_button.isHidden()

    def test_back_clamps_at_zero(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat))
        card._go_back()
        assert card.tabIndex() == 0

    def test_set_tab_rejects_out_of_range(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=2)
        card._set_tab(9)
        assert card.tabIndex() == 0
        card._set_tab(-1)
        assert card.tabIndex() == 0

    def test_segment_click_jumps(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=3)
        card._segments[2].jumped.emit(2)
        assert card.tabIndex() == 2
        assert [seg._active for seg in card._segments] == [False, False, True]

    def test_answered_segment_marked(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=2)
        card._option_buttons[0].activate.emit("A")
        assert [seg._answered for seg in card._segments] == [True, False]

    def test_segment_count_shrinks_with_questions(self, qapp, make):
        """换成一个更少题的请求，进度段要跟着收缩（不残留幽灵段）。"""
        card = make(PermissionCard)
        card.setPermission(
            ElaChatPermission(
                request_id="r1",
                action="question",
                questions=tuple(_q(f"q{i}") for i in range(3)),
            )
        )
        assert len(card._segments) == 3
        card.setPermission(
            ElaChatPermission(request_id="r2", action="question", questions=(_q("n0"),))
        )
        assert len(card._segments) == 1
        assert card._segment_box.isHidden(), "退回单题就该藏起进度条"

    def test_new_request_resets_wizard(self, qapp, make):
        """换 request_id -> 草稿归零（否则上一轮的答案会漏进下一轮）。

        直接对卡片调 —— ``view.beginPermission`` 每次都会新建一张卡，测不到
        「同一张卡上换请求」这条路径。
        """
        card = make(PermissionCard)
        card.setPermission(
            ElaChatPermission(request_id="r1", action="question", questions=(_q("q0"),))
        )
        card._option_buttons[0].activate.emit("A")
        assert card.answers() == {"q0": ["A"]}
        card.setPermission(
            ElaChatPermission(request_id="r2", action="question", questions=(_q("q0"),))
        )
        assert card.answers() == {}
        assert card.tabIndex() == 0

    def test_same_request_keeps_draft(self, qapp, make):
        """同一 request 只是状态推进时**保留**草稿。

        宿主常见两段式：``setResponding(True)`` -> 等 HTTP -> 回填。回填走的是
        同一张卡的 ``setPermission``，无脑清零会把用户刚选的东西抹掉。
        """
        card = make(PermissionCard)
        request = ElaChatPermission(
            request_id="r1", action="question", questions=(_q("q0"),)
        )
        card.setPermission(request)
        card._option_buttons[0].activate.emit("A")
        card.setPermission(request)
        assert card.answers() == {"q0": ["A"]}
        assert card.responding() is False, (
            "重新 setPermission 同一个待答复请求要解双击守卫"
        )


class TestKeyboard:
    """``1``-``9`` / ``Space`` / 方向键 / ``Ctrl+⏎`` / ``Alt+←`` / ``Esc``。

    全部走 ``QApplication.sendEvent(row, ...)`` 这条真实路径。直接调
    ``row.keyPressEvent`` 会跳过卡片那一层的过滤器 —— 数字键和 ``Ctrl+⏎``
    恰恰是在那一层派发的（行只知道自己的序号，不知道总共几行）。
    """

    def test_digit_selects_by_index_not_by_focus(self, qapp, make):
        """焦点在第 1 行时按 ``2``，选中的是**第 2 个**选项。"""
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat))
        _press(card, Qt.Key.Key_2)
        assert card.answers() == {"q0": ["B"]}

    def test_digit_works_from_any_row(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""), ("B", ""), ("C", "")))
        _press(card, Qt.Key.Key_1, row=2)
        assert card.answers() == {"q0": ["A"]}

    def test_digit_past_last_row_ignored(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""),))
        _press(card, Qt.Key.Key_5)
        assert card.answers() == {}, "超出候选数的数字键不该选中任何东西"

    def test_space_toggles_multi(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), multiple=True)
        _press(card, Qt.Key.Key_Space)
        assert card.answers() == {"q0": ["A"]}
        _press(card, Qt.Key.Key_Space)
        assert card.answers() == {}

    def test_space_on_custom_selects_and_expands(self, qapp, make):
        """Space 在自定义行 = 选中并展开编辑器（与点标记 / 点整行同一件事）。

        对齐 opencode：那一行是 ``<button>``，Space 走的就是 ``onClick``。
        """
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""),))
        _press(card, Qt.Key.Key_Space, row=len(card._option_buttons) - 1)
        custom = card._option_buttons[-1]
        assert custom.isEditing()
        assert custom.isPicked()

    def test_arrows_move_focus(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""), ("B", ""), ("C", "")))
        assert card.focusedRowIndex() == 0
        _press(card, Qt.Key.Key_Down)
        assert card.focusedRowIndex() == 1
        _press(card, Qt.Key.Key_Up)
        assert card.focusedRowIndex() == 0

    def test_left_right_same_as_up_down(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""), ("B", ""), ("C", "")))
        _press(card, Qt.Key.Key_Right)
        assert card.focusedRowIndex() == 1
        _press(card, Qt.Key.Key_Left)
        assert card.focusedRowIndex() == 0

    def test_home_and_end(self, qapp, make):
        """``End`` 落在**最后一行** —— 3 个候选 + 「自己写」= 4 行。"""
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""), ("B", ""), ("C", "")))
        assert len(card._option_buttons) == 4
        _press(card, Qt.Key.Key_End)
        assert card.focusedRowIndex() == 3
        _press(card, Qt.Key.Key_Home)
        assert card.focusedRowIndex() == 0

    def test_focus_clamps_at_edges(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""), ("B", "")))
        _press(card, Qt.Key.Key_Up)
        assert card.focusedRowIndex() == 0, "不能越过首行"
        _press(card, Qt.Key.Key_End)
        _press(card, Qt.Key.Key_Down)
        assert card.focusedRowIndex() == 2, "不能越过末行"

    def test_focus_resets_on_tab_switch(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=2)
        _press(card, Qt.Key.Key_End)
        assert card.focusedRowIndex() == 2
        card._set_tab(1)
        assert card.focusedRowIndex() == 0, "切题后焦点回到首行"

    def test_modifiers_pass_through(self, qapp, make):
        """带 Ctrl 的方向键不当作导航（留给 ``Ctrl+⏎``）。"""
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=(("A", ""), ("B", "")))
        _press(card, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
        assert card.focusedRowIndex() == 0

    def test_ctrl_enter_advances_then_submits(self, qapp, make):
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        card = _wizard(chat, _turn(chat), count=2)
        _press(card, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        assert card.tabIndex() == 1
        _press(card, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        assert seen == ["allowed"]

    def test_alt_left_goes_back(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=2)
        card._set_tab(1)
        _press(card, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
        assert card.tabIndex() == 0

    def test_escape_dismisses_from_row(self, qapp, make):
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        card = _single(chat, _turn(chat))
        _press(card, Qt.Key.Key_Escape)
        assert seen == ["cancelled"]

    def test_shortcuts_ignored_while_responding(self, qapp, make):
        """回复在途时快捷键全部失灵（防重复提交的第二道闸）。"""
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        card = _single(chat, _turn(chat))
        card.setResponding(True)
        _press(card, Qt.Key.Key_Escape)
        _press(card, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        _press(card, Qt.Key.Key_2)
        assert seen == []
        assert card.answers() == {}

    def test_shortcuts_ignored_after_settled(self, qapp, make):
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        card = _single(chat, _turn(chat))
        card._emit_reply("allowed", "", "")
        seen.clear()
        _press(card, Qt.Key.Key_Escape)
        _press(card, Qt.Key.Key_2)
        assert seen == []

    def test_escape_in_editor_only_exits_editing(self, qapp, make):
        """编辑器里 Esc = 退出编辑但**保留已输入的文字**，不是忽略整个问题。"""
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        card = _single(chat, _turn(chat), options=())
        custom = card._option_buttons[0]
        custom.activate.emit("")
        custom.setEditorText("typed")
        qapp.sendEvent(
            custom._editor,
            QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
            ),
        )
        assert not custom.isEditing()
        assert custom.editorText() == "typed", "Esc 不能丢掉已输入的文字"
        assert seen == []

    def test_enter_in_editor_commits(self, qapp, make):
        """Enter 提交自定义答案。``answers()`` 一律给 list，塌缩只发生在 payload。"""
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=())
        custom = card._option_buttons[0]
        custom.activate.emit("")
        custom.setEditorText("this way")
        qapp.sendEvent(
            custom._editor,
            QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
            ),
        )
        assert card.answers() == {"q0": ["this way"]}
        assert json.loads(card._build_answer()) == {"q0": "this way"}

    def test_ctrl_enter_in_editor_advances_and_commits(self, qapp, make):
        """编辑器里 ``Ctrl+⏎`` 是「下一步」，不是「提交整轮」。

        但**编辑框里的文字要先落定**（对齐 opencode ``next()``）—— 走题了还把
        字留在输入框里等于这段答案从来没被记下。
        """
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        card = _wizard(chat, _turn(chat), count=2)
        custom = card._option_buttons[-1]
        custom.activate.emit("")
        custom.setEditorText("typed")
        qapp.sendEvent(
            custom._editor,
            QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Return,
                Qt.KeyboardModifier.ControlModifier,
            ),
        )
        assert card.tabIndex() == 1
        assert seen == [], "不该在这一步就提交整轮"
        assert card.answers() == {"q0": ["typed"]}

    def test_shift_enter_newline(self, qapp, make):
        """Shift+Enter 在编辑器里换行，不提交。"""
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=())
        custom = card._option_buttons[0]
        custom.activate.emit("")
        custom.setEditorText("第一行")
        qapp.sendEvent(
            custom._editor,
            QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Return,
                Qt.KeyboardModifier.ShiftModifier,
            ),
        )
        assert "\n" in custom.editorText(), "Shift+Enter 要放行给编辑器换行"
        assert card.answers() == {}

    def test_editor_grows_with_lines(self, qapp, make):
        """自增高按行数走（**不是** ``document().size()``，那是逻辑单位）。"""
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=())
        custom = card._option_buttons[0]
        custom.activate.emit("")
        custom.setEditorText("one")
        one = custom._editor.sizeHint().height()
        custom.setEditorText("one\ntwo\nthree")
        three = custom._editor.sizeHint().height()
        assert three > one + 20, f"三行应比一行高不少：{one} -> {three}"


class TestRespondingAndSettled:
    def test_responding_disables_everything(self, qapp, make):
        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=2)
        card.setResponding(True)
        assert not card._next_button.isEnabled()
        assert not card._dismiss_button.isEnabled()
        assert not card._back_button.isEnabled()
        for row in card._option_buttons:
            assert not row.isEnabled()

    def test_responding_cleared_by_new_pending_request(self, qapp, make):
        card = make(PermissionCard)
        request = ElaChatPermission(
            request_id="r1", action="question", questions=(_q("q0"),)
        )
        card.setPermission(request)
        card.setResponding(True)
        assert card.responding()
        card.setPermission(request)
        assert not card.responding()

    def test_settled_hides_wizard(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_q("q0"),)
            ),
        )
        _interactive(chat, mid)._option_buttons[0].activate.emit("A")
        view.resolvePermission(mid, "r1", "allowed", '{"q0":"A"}')
        record = _record(chat, mid)
        assert isinstance(record, PermissionRecord), "落定后留下一张记录卡"
        # 记录卡**默认折叠成一行**（与工具调用面板同一套折叠交互）
        assert not record.isOpened()
        assert record.title() == "已允许一次：?"  # "?" 是 _q 的默认题面

    def test_interactive_card_is_not_in_timeline(self, qapp, make):
        """等待期间时间线上**没有**卡片（交互在 dock 上）。"""
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        chat.chatView().beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_q("q0"),)
            ),
        )
        assert _record(chat, mid) is None
        assert _interactive(chat, mid) is not None
        assert chat.pendingPermissionCards() == [_interactive(chat, mid)]

    def test_settled_card_lands_in_timeline(self, qapp, make):
        """落定后记录卡插在**该 part 的原位**，不是追加到末尾。"""
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        part_id = view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_q("q0"),)
            ),
        )
        bubble = view.bubble(mid)
        assert bubble._part_widgets.get(part_id) is None, "等待期间不占时间线位置"
        view.resolvePermission(mid, "r1", "allowed", '{"q0":"A"}')
        widget = bubble._part_widgets.get(part_id)
        assert widget is _record(chat, mid)
        assert view.permissionCard(mid, "r1") is widget
        assert chat.pendingPermissionCards() == [], "落定后 dock 上不该还有卡"

    def test_record_order_follows_timeline(self, qapp, make):
        """审批之后来的正文段，记录卡必须排在它**前面**。"""
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_q("q0"),)
            ),
        )
        view.resolvePermission(mid, "r1", "allowed", '{"q0":"A"}')
        view.beginText(mid)
        view.appendText(mid, "done")
        view.endText(mid)
        bubble = view.bubble(mid)
        order = [type(w).__name__ for w in bubble._part_widgets.values() if w]
        assert order.index("PermissionRecord") < len(order) - 1, order

    def test_settled_shows_answer_summary(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1",
                action="question",
                questions=(
                    _q(
                        "q0",
                        question="which?",
                        options=(("change to B", ""),),
                    ),
                ),
            ),
        )
        view.resolvePermission(mid, "r1", "allowed", '{"q0":"change to B"}')
        card = _record(chat, mid)
        assert "change to B" in card._detail.text()
        assert not card._detail.isHidden()

    def test_settled_multi_shows_joined(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1",
                action="question",
                questions=(_q("q0", options=(("A", ""), ("B", ""))),),
            ),
        )
        view.resolvePermission(mid, "r1", "allowed", '{"q0":["A","B"]}')
        assert "A" in _record(chat, mid)._detail.text()

    def test_cancelled_hides_wizard(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_q("q0"),)
            ),
        )
        view.resolvePermission(mid, "r1", "cancelled")
        record = _record(chat, mid)
        assert record.title() == "已作废：?"

    def test_answers_accessor_mid_wizard(self, qapp, make):
        """``permissionAnswers`` 要能在**还没提交**时读到当前进度。"""
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1",
                action="question",
                questions=(_q("q0"), _q("q1")),
            ),
        )
        assert view.permissionAnswers(mid, "r1") == {}
        _interactive(chat, mid)._option_buttons[0].activate.emit("A")
        assert view.permissionAnswers(mid, "r1") == {"q0": ["A"]}

    def test_permission_answers_unknown_request(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        assert chat.chatView().permissionAnswers(mid, "nope") == {}


class TestApproveShapeUnchanged:
    """批准型不能被问答型的改动带坏。"""

    def test_three_buttons(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        chat.chatView().beginPermission(
            mid,
            ElaChatPermission(request_id="r1", action="shell", detail="rm -rf /"),
        )
        card = _interactive(chat, mid)
        assert card.questionCount() == 0
        assert card._question_box.isHidden()
        assert card._footer.isHidden()
        assert len(card._action_buttons()) == 3

    def test_no_segment_for_approve(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        chat.chatView().beginPermission(
            mid, ElaChatPermission(request_id="r1", action="edit")
        )
        card = _interactive(chat, mid)
        assert card._segment_box.isHidden()
        assert card.permission().isQuestion is False

    def test_approve_shortcuts_inert(self, qapp, make):
        """批准型不该有数字键选候选（压根没有候选）。"""
        seen = []
        chat = make(ElaChatWidget)
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        mid = _turn(chat)
        chat.chatView().beginPermission(
            mid, ElaChatPermission(request_id="r1", action="edit")
        )
        card = _interactive(chat, mid)
        _press(card, Qt.Key.Key_2, row=None)
        assert seen == []


class TestTheming:
    """颜色必须全部来自主题令牌（**不硬编码 opencode 的品牌色**）。"""

    def test_picked_row_uses_accent_from_theme(self, qapp, make, dark_mode):
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat))
        card._option_buttons[0].activate.emit("A")
        colors = question_colors(eTheme.getThemeMode())
        assert colors["accent"] != QColor("#034cff"), (
            "强调色必须取自 eTheme，不能抄 opencode 的品牌色"
        )
        assert colors["picked"] != QColor("#034cff")
        row = card._option_buttons[0]
        assert row._label.textColor() == colors["ink"]
        assert row._desc.textColor() == colors["muted"]

    def test_glow_is_transparent_accent(self, qapp, make, dark_mode):
        chat = make(ElaChatWidget)
        _single(chat, _turn(chat))
        colors = question_colors(eTheme.getThemeMode())
        assert colors["glow"].alpha() == GLOW_ALPHA
        assert (
            colors["glow"].red(),
            colors["glow"].green(),
            colors["glow"].blue(),
        ) == (
            colors["accent"].red(),
            colors["accent"].green(),
            colors["accent"].blue(),
        )

    @pytest.mark.parametrize(
        "mode", [ElaThemeType.ThemeMode.Light, ElaThemeType.ThemeMode.Dark]
    )
    def test_rows_have_explicit_intent_colors(self, qapp, make, mode):
        """深色下不能靠回落 ``BasicText``（那就是「看不见的字」）。"""
        eTheme.setThemeMode(mode)
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat))
        for row in card._option_buttons:
            for label in (row._label, row._desc):
                assert isinstance(label, ColorText)
                assert label.textColor().isValid()
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)

    def test_contrast_against_card(self, qapp, make, dark_mode):
        """字色与卡底要有足够明度差。"""
        chat = make(ElaChatWidget)
        _single(chat, _turn(chat))
        colors = question_colors(eTheme.getThemeMode())
        assert abs(colors["ink"].lightness() - colors["card"].lightness()) > 40
        assert abs(colors["muted"].lightness() - colors["card"].lightness()) > 30

    def test_theme_switch_refreshes_rows(self, qapp, make):
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat))
        light = card._option_buttons[0]._label.textColor()
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
        qapp.processEvents()
        assert card._option_buttons[0]._label.textColor() != light, (
            "运行期切主题后选项文字色没变"
        )
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)

    def test_footer_buttons_are_ela_buttons(self, qapp, make):
        """页脚三个动作都用 **ElaButton**（不另造自绘按钮）。

        配色分级：`text` 弱化 / `outlined` 中性 / `solid+primary` 主动作 ——
        一眼能分出「这一步该点哪个」。

        **按钮上不印快捷键**：``Alt+←`` / ``Ctrl+⏎`` 这种内联提示比按钮本身还抢眼
        （实测截图里「忽略」被两个提示压成了配角），而快捷键仍然照常生效。
        """
        from pyqt6_ela_pro.ela_button import ElaButton

        chat = make(ElaChatWidget)
        card = _wizard(chat, _turn(chat), count=2)
        assert isinstance(card._dismiss_button, ElaButton)
        assert isinstance(card._back_button, ElaButton)
        assert isinstance(card._next_button, ElaButton)
        assert card._dismiss_button.variant() == "text"
        assert card._back_button.variant() == "outlined"
        assert card._next_button.variant() == "solid"
        assert card._next_button.color() == "primary"

    @pytest.mark.parametrize("text", ["", "one", "one\ntwo\nthree"])
    def test_theme_switch_with_editing_row_survives(self, qapp, make, text):
        """**自定义答案编辑态下切主题不能崩**（这条曾经崩，且崩在信号链上）。

        原实现往 ``ElaPlainTextEdit`` 调 ``setTextColor`` —— 该方法**不存在**，
        ``AttributeError`` 穿过 C++ 边界 = 0xC0000409 静默终止、连 traceback 都
        没有。**空文本也崩**（编辑器只要被创建出来就崩），所以三种长度都要钉。
        """
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)
        chat = make(ElaChatWidget)
        card = _single(chat, _turn(chat), options=())
        custom = card._option_buttons[0]
        custom.activate.emit("")
        if text:
            custom.setEditorText(text)
        qapp.processEvents()
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Dark)
        qapp.processEvents()
        assert custom.isEditing(), "编辑态不该被主题切换打断"
        eTheme.setThemeMode(ElaThemeType.ThemeMode.Light)


class TestOptionCardContract:
    """``QuestionOptionCard`` 是不开 checkable 的纯输入面。"""

    def test_not_checkable(self, qapp, make):
        row = make(QuestionOptionCard, value="A", description="desc")
        assert not row.isCheckable()
        assert not row.isChecked()

    def test_set_picked_does_not_emit(self, qapp, make):
        """``setPicked`` 不发任何信号（否则外层状态机会自激成环）。"""
        row = make(QuestionOptionCard, value="A")
        seen = []
        row.activate.connect(seen.append)
        row.markClicked.connect(seen.append)
        row.toggled.connect(lambda *a: seen.append("toggled"))
        row.setPicked(True)
        assert seen == []
        assert row.isPicked()

    def test_description_can_be_empty(self, qapp, make):
        row = make(QuestionOptionCard, value="A")
        assert row._desc.isHidden()

    def test_multi_flag_reads_back(self, qapp, make):
        assert make(QuestionOptionCard, value="A", multi=True).isMulti()
        assert not make(QuestionOptionCard, value="A", multi=False).isMulti()

    def test_parent_is_first_positional(self, qapp, make):
        host = make(QWidget)
        row = make(QuestionOptionCard, host, value="A")
        assert row.parent() is host

    def test_mark_click_emits_separately(self, qapp, make):
        """点左侧 16px 标记区 = 只切勾选，不当作整行激活。"""
        row = make(QuestionOptionCard, value="A")
        row.resize(300, 44)
        marks, rows = [], []
        row.markClicked.connect(marks.append)
        row.activate.connect(rows.append)
        mark = row._mark_rect()
        row.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(QPoint(int(mark.center().x()), int(mark.center().y()))),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert marks == ["A"]
        assert rows == []

    def test_click_left_of_mark_is_not_mark(self, qapp, make):
        """标记左侧那 10px 内边距不算标记区（对齐 opencode 的 padding-left）。"""
        row = make(QuestionOptionCard, value="A")
        row.resize(300, 44)
        # 必须先激活布局：未布局时子控件还是默认几何 (0,0,100,30)，x=2 会被
        # 当成落在标记区里（新轮子的 ElaRadioButton 不再在构造时固定 17×17）。
        row.layout().activate()
        marks = []
        row.markClicked.connect(marks.append)
        row.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(QPoint(2, 22)),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert marks == []

    def test_body_click_emits_activate(self, qapp, make):
        row = make(QuestionOptionCard, value="A")
        row.resize(300, 44)
        rows = []
        row.activate.connect(rows.append)
        row.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(QPoint(160, 22)),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert rows == ["A"]

    def test_editor_grows(self, qapp, make):
        row = make(QuestionOptionCard, value="", isCustom=True)
        row.resize(300, 44)
        row.setEditing(True)
        row.setEditorText("a")
        one = row._editor.sizeHint().height()
        row.setEditorText("a\nb\nc")
        assert row._editor.sizeHint().height() > one + 20

    def test_full_mark_click_toggles_once(self, qapp, make):
        """完整按下 + 松开：只切一次勾选（release 不得补发 activate 抵消）。"""
        row = make(QuestionOptionCard, value="A")
        row.resize(300, 44)
        picks, acts = [], []
        row.markClicked.connect(picks.append)
        row.activate.connect(acts.append)
        mark = row._mark_rect()
        pos = QPoint(int(mark.center().x()), int(mark.center().y()))
        row.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(pos),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        row.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(pos),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert picks == ["A"]
        assert acts == []

    def test_full_custom_mark_click_does_not_open_editor(self, qapp, make):
        row = make(QuestionOptionCard, value="", isCustom=True)
        row.resize(300, 44)
        mark = row._mark_rect()
        pos = QPoint(int(mark.center().x()), int(mark.center().y()))
        row.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(pos),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        row.mouseReleaseEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(pos),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert not row.isEditing()

    def test_full_custom_mark_click_while_editing(self, qapp, make):
        """编辑态下标记仍可点 —— 多选要能「再点一次 = 取消并收起输入框」。

        对齐 opencode：标记在 ``<form>`` 内，编辑时照样点得到。
        """
        row = make(QuestionOptionCard, value="", isCustom=True)
        row.resize(300, 44)
        row.setEditing(True)
        picks = []
        row.markClicked.connect(picks.append)
        mark = row._mark_rect()
        pos = QPoint(int(mark.center().x()), int(mark.center().y()))
        row.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(pos),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert picks == [""]
        assert row.isEditing(), "收起输入框归外层卡片（它才知道该不该取消勾选）"

    def test_body_click_while_editing_does_not_activate(self, qapp, make):
        """编辑态下点标签 / 说明：不再当整行激活，并把焦点还给编辑器。

        走 ``QAbstractButton`` 会抢走焦点，随后按 Enter 落到行上等于什么都没发生。
        """
        row = make(QuestionOptionCard, value="", isCustom=True)
        row.resize(300, 44)
        row.setEditing(True)
        acts = []
        row.activate.connect(acts.append)
        row.mousePressEvent(
            QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(QPoint(200, 22)),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert acts == []
        assert row.isEditing()


class TestWizardDraftRetention:
    """向导状态与提交 payload 同口径；未提交草稿不能一刷新就没。"""

    def _card(self, make, **kwargs):
        card = make(PermissionCard)
        question = _q("q0", "选一个", **kwargs)
        card.setPermission(
            ElaChatPermission(
                request_id="r1",
                action="ask",
                status=ElaChatPermissionStatusType.Pending,
                questions=(question,),
            )
        )
        return card, question

    def test_custom_uncheck_clears_answered_segment(self, qapp, make):
        """取消自定义勾选后这道题回到未答（进度段随之熄灭）。

        取消语义只挂在**多选**上：单选是 radio，点自定义行的标记只会保持选中。
        """
        card, question = self._card(make, multiple=True)
        card._on_commit(question, "自己写的")
        assert card._segments[0]._answered is True

        card._on_mark_clicked(question, "")

        assert card._segments[0]._answered is False
        assert card.answers() == {}

    def test_reenter_editing_keeps_uncommitted_draft(self, qapp, make):
        card, _question = self._card(make)
        row = card._custom_row("q0")
        row.setEditing(True)
        row.setEditorText("打了一半的草稿")
        row.setEditing(False)  # Esc：文本保留在编辑器里

        card._enter_editing("q0")

        assert row.editorText() == "打了一半的草稿"


class TestCustomEditorHeight:
    """自定义答案输入框必须真的长高（不能只改 sizeHint 不改几何）。"""

    def test_editor_height_matches_content(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.resize(820, 640)
        chat.show()
        qapp.processEvents()
        card = _single(chat, _turn(chat), options=(("A", ""),))
        card._enter_editing("q0")
        row = card._custom_row("q0")
        editor = row._editor
        assert _wait_until(qapp, lambda: editor.height() == editor.sizeHint().height())
        base = editor.height()

        editor.setPlainText("一\n二\n三\n四\n五\n六")
        assert _wait_until(
            qapp,
            lambda: editor.height() > base + 20
            and editor.height() == editor.sizeHint().height(),
        )

        # 长单段（折行）同样要长高；旧实现按 blockCount 算，永远只报一行。
        editor.setPlainText("这是一段很长的自定义答案，" * 40)
        assert _wait_until(
            qapp,
            lambda: editor.height() > base + 60
            and editor.height() == editor.sizeHint().height(),
        )
