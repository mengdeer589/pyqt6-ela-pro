"""审批的**位置契约**：交互在输入区上方的 dock，记录折叠在时间线上。

这是本轮最重要的一次架构调整，直接对应两张截图里暴露的问题：审批交互摆在
时间线上时既窄又旧 —— 提问正文被压到只显示一行、候选卡的说明文字被页脚盖住、
底部还弹出一条看起来像被切断的滚动条。opencode 的做法是**交互与记录分离**：

- 等待用户操作 -> :class:`ElaChatPermissionDock`（输入区上方，输入区照常可用）；
- 答完 -> 时间线上一张 :class:`PermissionRecord`，**默认折叠成一行**（与
  ``ToolGroupPanel`` 的 ``> 工具调用 (N)`` 同一套折叠交互）。

回归测试 `tests/ela_chat/test_chat_question_wizard.py` 钉交互细节，这里钉位置
与高度。
"""

from __future__ import annotations

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QScrollArea

from pyqt6_ela_pro.chat import (
    ElaChatBubble,
    ElaChatOption,
    ElaChatPermission,
    ElaChatPermissionStatusType,
    ElaChatQuestion,
    ElaChatRoleType,
    ElaChatWidget,
)
from pyqt6_ela_pro.chat.blocks import PermissionCard, PermissionRecord
from pyqt6_ela_pro.chat.docks import ElaChatPermissionDock
from pyqt6_ela_pro.chat._question import CARD_PADDING
from pyqt6_ela_pro.ela_button import ElaButton


def _turn(chat):
    chat.sendUserMessage("hi")
    return chat.beginAssistantMessage()


def _question(key="q0", **kwargs):
    return ElaChatQuestion(
        key=key,
        question="哪些目录需要一起看？",
        options=(
            ElaChatOption("pyqt6_ela_pro/", "组件库本体"),
            ElaChatOption("tests/", "回归测试"),
        ),
        **kwargs,
    )


def _ask(chat, mid, permission):
    chat.chatView().beginPermission(mid, permission)
    return chat.chatView().interactivePermissionCard(mid, permission.request_id)


class TestInteractionLivesInDock:
    def test_card_goes_to_permission_dock(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        card = _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            ),
        )
        assert chat.permissionDock().card() is card
        assert not chat.permissionDock().isHidden()
        assert chat.inputDock().widget() is None, "审批不该占用输入区 dock"
        assert not chat.inputDock().replacesInput()

    def test_input_stays_usable(self, qapp, make):
        """审批**不禁用输入区** —— 它不是「顶替输入区」。

        宿主自用的 ``setDockWidget(replace=True)`` 才会禁用输入区；审批是「现在
        要你在旁边点一下」，不是「此刻不许说话」。
        """
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            ),
        )
        assert chat.chatInput().isEnabled()
        chat.permissionDock().setCard(None)
        assert chat.chatInput().isEnabled()

    def test_timeline_has_nothing_while_waiting(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            ),
        )
        assert chat.chatView().permissionCard(mid, "r1") is None

    def test_queue_hint_counts_the_rest(self, qapp, make):
        """第二张审批不顶掉第一张（用户可能正在答），而是排队等位。"""
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question("q0"),)
            ),
        )
        first = view.interactivePermissionCard(mid, "r1")
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r2", action="question", questions=(_question("q1"),)
            ),
        )
        assert chat.permissionDock().card() is first, "先来的那张留在 dock 上"
        assert chat.permissionDock().queued() == 1

    def test_settling_promotes_the_next(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question("q0"),)
            ),
        )
        first = view.interactivePermissionCard(mid, "r1")
        assert chat.permissionDock().card() is first, "先到的审批先进 dock"
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r2", action="question", questions=(_question("q1"),)
            ),
        )
        second = view.interactivePermissionCard(mid, "r2")
        view.resolvePermission(mid, "r1", "allowed", '{"q0":"tests/"}')
        assert chat.permissionDock().card() is second, "第一张答完应接上第二张"
        view.resolvePermission(mid, "r2", "cancelled")
        assert chat.permissionDock().card() is None
        assert chat.permissionDock().isHidden()

    def test_clear_session_empties_the_dock(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            ),
        )
        chat.clear()
        assert chat.permissionDock().card() is None
        assert chat.permissionDock().isHidden()

    def test_remove_message_cancels_pending_first(self, qapp, make):
        """删消息前必须先 abort：否则 dock 上留下指向已不存在消息的死卡。"""
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        seen = []
        chat.permissionReplied.connect(lambda i, r, rep, a, f: seen.append(rep))
        _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            ),
        )
        chat.removeMessage(mid)
        assert seen == ["cancelled"]
        assert chat.permissionDock().card() is None

    def test_card_stays_hidden_until_the_dock_adopts_it(self, qapp, make):
        """**建卡时不给 parent，卡片不能自己 show。**

        ``bubble.beginPermission`` 建卡时不带 parent（气泡不知道 dock 的存在）。
        若 ``setPermission`` 里调 ``show()``，Qt 会把这个无父控件当**顶层窗口**弹
        出来：用户看到「小窗一闪 -> 变成输入区上那张卡」，连点几次就同时弹出好几个
        窗口（实测截图）。显示时机只归 dock 一家。
        """
        card = make.track(PermissionCard())
        assert card.isWindow(), "造出来就是个顶层控件，正是问题所在"
        card.setPermission(
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            )
        )
        assert card.isHidden(), "没人收养之前不许 show"

    def test_dock_shows_the_card_it_adopts(self, qapp, make):
        dock = make(ElaChatPermissionDock)
        card = make.track(PermissionCard())
        card.setPermission(
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            )
        )
        assert card.isHidden()
        dock.setCard(card)
        assert not card.isHidden(), "dock 收下就得显示"
        assert not card.isWindow(), "进了 dock 就不再是独立窗口"

    def test_queued_cards_are_never_adopted(self, qapp, make):
        """排队的卡**不进 dock**（也就不会变成窗口），dock 一次只放一张。"""
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        for index in range(4):
            view.beginPermission(
                mid,
                ElaChatPermission(
                    request_id=f"r{index}",
                    action="question",
                    questions=(_question(f"q{index}"),),
                ),
            )
        dock = chat.permissionDock()
        assert dock.card() is view.interactivePermissionCard(mid, "r0")
        assert dock.queued() == 3
        # 排队中的三张仍是顶层控件，但从未被 show 过
        for index in range(1, 4):
            assert view.interactivePermissionCard(mid, f"r{index}").isHidden()


class TestRecordIsCollapsed:
    def test_record_defaults_to_collapsed(self, qapp, make):
        """附加到时间线后**默认折叠**（与工具调用面板同一约定）。"""
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(request_id="r1", action="edit", resources=("src/a.py",)),
        )
        view.resolvePermission(mid, "r1", "allowed")
        record = view.permissionCard(mid, "r1")
        assert isinstance(record, PermissionRecord)
        assert not record.isOpened()
        assert record.isExpandable(), "有资源就该给折叠箭头"

    def test_record_expands_on_demand(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(request_id="r1", action="edit", resources=("src/a.py",)),
        )
        view.resolvePermission(mid, "r1", "allowed")
        record = view.permissionCard(mid, "r1")
        record.setOpened(True)
        assert record.isOpened()
        assert "src/a.py" in record._resources.text()

    def test_record_without_body_is_not_expandable(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            ),
        )
        view.resolvePermission(mid, "r1", "allowed", '{"q0":"tests/"}')
        record = view.permissionCard(mid, "r1")
        assert record.isExpandable()
        record.setOpened(True)
        assert "tests/" in record._detail.text()

    @pytest.mark.parametrize(
        "reply,title",
        [
            ("allowed", "已允许一次：edit"),
            ("always", "已允许并记住规则：edit"),
            ("rejected", "已拒绝：edit"),
            ("cancelled", "已作废：edit"),
        ],
    )
    def test_record_title_per_status(self, qapp, make, reply, title):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(mid, ElaChatPermission(request_id="r1", action="edit"))
        view.resolvePermission(mid, "r1", reply)
        assert view.permissionCard(mid, "r1").title() == title

    def test_interactive_and_record_are_different_widgets(self, qapp, make):
        """交互卡与记录卡**不复用同一个 widget**（排版需求正好相反）。"""
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            ),
        )
        interactive = view.interactivePermissionCard(mid, "r1")
        view.resolvePermission(mid, "r1", "allowed", '{"q0":"tests/"}')
        record = view.permissionCard(mid, "r1")
        assert interactive is not record


class TestLargeDiffEliding:
    """大量 diff 必须能折叠 —— 一次 ``git diff`` 动辄上千行。"""

    @staticmethod
    def _diff(lines):
        return "\n".join(f"+line {i}" for i in range(lines))

    def test_long_diff_is_truncated_by_default(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(request_id="r1", action="edit", detail=self._diff(200)),
        )
        card = view.interactivePermissionCard(mid, "r1")
        assert card._detail_toggle.isVisible() or not card._detail_toggle.isHidden()
        shown = card._detail.text().split("\n")
        assert len(shown) <= 10, shown
        assert "还有" in shown[-1]

    def test_expand_reveals_everything(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(request_id="r1", action="edit", detail=self._diff(200)),
        )
        card = view.interactivePermissionCard(mid, "r1")
        card._toggle_detail()
        assert len(card._detail.text().split("\n")) == 200
        card._toggle_detail()
        assert len(card._detail.text().split("\n")) <= 10

    def test_short_detail_needs_no_toggle(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid, ElaChatPermission(request_id="r1", action="edit", detail="+one line")
        )
        card = view.interactivePermissionCard(mid, "r1")
        assert card._detail_toggle.isHidden()
        assert "还有 -" not in card._detail.text(), "短详情不该拼出负行数"

    def test_single_huge_line_is_clipped(self, qapp, make):
        """行数少但单行巨长（minified / base64）也必须截断。"""
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid, ElaChatPermission(request_id="r1", action="edit", detail="x" * 5000)
        )
        card = view.interactivePermissionCard(mid, "r1")
        text = card._detail.text()
        assert len(text) < 1000
        assert "本行已截断" in text

    def test_record_elides_too(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        view = chat.chatView()
        view.beginPermission(
            mid,
            ElaChatPermission(request_id="r1", action="edit", detail=self._diff(200)),
        )
        view.resolvePermission(mid, "r1", "allowed")
        record = view.permissionCard(mid, "r1")
        assert not record.isOpened(), "长详情默认折叠，别占掉半屏"
        record.setOpened(True)
        assert "本行已截断" not in record._detail.text()
        assert len(record._detail.text().split("\n")) <= 200


class TestLayoutContract:
    """高度与排版契约。

    这一整段都在钉**同一件事**：选项区是普通容器，不是滚动区。

    踩过的坑（都来自真实截图，不是假想）：``QScrollArea`` 的 ``sizeHint()``
    是个无意义的小值，布局完全不知道里面有多高，于是内容被压扁、明明放得下也
    弹滚动条（实测 166px 的三行选项被压到 69px，第二个选项切掉半截）；改成
    「自己测内容再 ``setFixedHeight``」又形成反馈环（题面一度被撑到 250px）。
    而且内层滚动区滚到头之后事件会**冒泡到外层**，鼠标停在选项上滚一下会连整个
    消息区一起动（用户原话：「这个区域的滚动会跟外部容器的滚动连动」）。

    结论：不给内层滚动区，也**不设高度上限**。候选行是普通控件、行高固定，
    容器的 ``sizeHint`` 就是内容高度，布局自然给对。
    """

    def test_options_area_is_not_a_scroll_area(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        card = _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            ),
        )
        assert not isinstance(card._options_host, QScrollArea)
        assert card.findChildren(QScrollArea) == [], "交互卡内不该再有滚动区"

    def test_options_area_has_no_height_cap(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        card = _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            ),
        )
        assert card._options_host.maximumHeight() in (0, 16777215), (
            "选项区不该封顶：封顶就必须滚动，又回到 sizeHint 那个坑"
        )

    def test_options_area_uses_its_content_height(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.resize(900, 700)
        chat.show()
        mid = _turn(chat)
        card = _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            ),
        )
        qapp.processEvents()
        want = card._options_host.sizeHint().height()
        assert card._options_host.height() >= want - 1, (
            f"选项区 {card._options_host.height()}px < 内容 {want}px"
        )

    def test_many_options_are_not_clipped(self, qapp, make):
        """选项多的时候**内容一个都不能少**（不封顶的必然结果）。"""
        chat = make(ElaChatWidget)
        chat.resize(900, 900)
        chat.show()
        mid = _turn(chat)
        card = _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1",
                action="question",
                questions=(
                    ElaChatQuestion(
                        key="q0",
                        question="挑哪些？",
                        options=tuple(
                            ElaChatOption(f"item {i}", "说明") for i in range(14)
                        ),
                    ),
                ),
            ),
        )
        qapp.processEvents()
        assert len(card._option_buttons) == 15, "14 个候选 + 「输入自己的答案」"
        for row in card._option_buttons:
            assert row.isVisible(), "有选项被裁掉了"

    def test_question_text_is_not_clipped(self, qapp, make):
        """题面不能被压掉最后一行。

        空间不够时布局会压到 ``minimumSizeHint``（``QWidget`` 默认 0），换行标签
        于是只剩一行 —— 症状就是「问题显示不全」。
        """
        chat = make(ElaChatWidget)
        chat.resize(700, 700)
        chat.show()
        mid = _turn(chat)
        card = _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1",
                action="question",
                questions=(
                    ElaChatQuestion(
                        key="q0",
                        question="请说明这次改动要不要同时改 README 与"
                        "AGENTS.md 里的 API 表，以及是否需要补一条回归测试，"
                        "越详细越好。",
                        options=(ElaChatOption("要", "同步改文档"),),
                    ),
                ),
            ),
        )
        qapp.processEvents()
        label = card._question_text
        want = (
            label.fontMetrics()
            .boundingRect(
                QRect(0, 0, label.width() - 1, 100000),
                int(Qt.TextFlag.TextWordWrap),
                label.text(),
            )
            .height()
        )
        assert label.height() >= want, (
            f"题面 {label.height()}px < 需要 {want}px（被压掉了换行）"
        )

    def test_card_gets_its_size_hint(self, qapp, make):
        chat = make(ElaChatWidget)
        chat.resize(900, 700)
        chat.show()
        mid = _turn(chat)
        card = _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            ),
        )
        qapp.processEvents()
        assert card.height() >= card.sizeHint().height() - 1, (
            f"卡片 {card.height()}px 被压到 sizeHint {card.sizeHint().height()}px 以下"
        )

    def test_option_rows_are_compact(self, qapp, make):
        """候选行必须**紧凑**：高度正好等于内容需要，且内边距不超预算。

        起因是用户反馈「每个选项高度太高了」—— 46px 的行高在 5 个选项下就是
        250px，整张问题卡半屏都是框。

        **不要写死「一行 ≤ 40px」这种绝对值**：字体度量是平台相关的，实测
        同一份代码在 windows 上「13px 标题 + 12px 说明 + 1px 间距 + 上下各 4px」
        的自然高是 43px，在 offscreen 上只有 36px（12px 的行高分别是 16 和 12）。
        写死一个数就等于给某一个平台的度量定标准，另一个平台必假失败。

        这里钉的是两条真正的不变量：

        1. **高度 == ``sizeHint``**：多 1px 是「行里塞了空气」，少 1px 是
           「内容被裁」。这一条同时抓住「``sizeHint`` 里写死一个魔数下限、
           每行都比布局需要高几 px、累积起来把整张卡压到比 sizeHint 矮」
           那个真实 bug（见 ``_comfortable_minimum``）。
        2. **上下内边距 ≤ 4px**：这才是「行别太松」的可调杠杆，且与字体无关。
        """
        chat = make(ElaChatWidget)
        chat.resize(900, 700)
        chat.show()
        mid = _turn(chat)
        card = _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1", action="question", questions=(_question(),)
            ),
        )
        qapp.processEvents()
        assert card._option_buttons
        for row in card._option_buttons:
            assert row.height() == row.sizeHint().height(), (
                f"候选行 {row.height()}px ≠ sizeHint "
                f"{row.sizeHint().height()}px（有空气或被裁）"
            )
            margins = row.layout().contentsMargins()
            assert margins.top() <= 4 and margins.bottom() <= 4, (
                f"候选行上下内边距 {margins.top()}/{margins.bottom()} 超预算"
            )
            # 单行内容也不该有大块留白：高度必须由文字撑起来，而不是固定的
            content = row._texts_layout.sizeHint().height()
            assert row.height() <= content + 8, (
                f"候选行 {row.height()}px 比内容 {content}px 多出太多"
            )

    def test_long_description_grows_row(self, qapp, make):
        """说明折行时行高跟着长（修复「第二行被裁」的已知缺陷）。

        ``QAbstractButton`` 不把 ``heightForWidth`` 转发给布局，光靠 Qt 会在
        首次（行宽还是 0）按「一行」定死；``resizeEvent`` 里 ``updateGeometry()``
        让布局在宽度确定后重新问一次。这里按**实际宽度**折行算出的需求高度
        验证行高容得下。
        """
        chat = make(ElaChatWidget)
        chat.resize(900, 720)
        chat.show()
        mid = _turn(chat)
        long_desc = "组件库本体，改动会波及全部下游。" * 20
        card = _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1",
                action="question",
                questions=(
                    ElaChatQuestion(
                        key="q0",
                        question="哪些目录要不要一起看？",
                        options=(ElaChatOption("pyqt6_ela_pro/", long_desc),),
                    ),
                ),
            ),
        )
        for _ in range(3):
            qapp.processEvents()
        row = card._option_buttons[0]
        desc_line = row._desc.fontMetrics().height()
        assert row._desc.heightForWidth(row._desc.width()) > desc_line, (
            "说明应当折行（否则本用例失去鉴别力）"
        )
        needed = (
            row._label.heightForWidth(row._label.width())
            + row._desc.heightForWidth(row._desc.width())
            + row._texts_layout.spacing()
            + CARD_PADDING[1]
            + CARD_PADDING[3]
        )
        assert row.height() >= needed, (
            f"行高 {row.height()} 应容得下折行后的内容 {needed}"
        )


class TestFooterHasNoShortcutHints:
    """页脚**不写**快捷键提示（快捷键仍然生效，只是不印在按钮上）。"""

    def test_no_hint_labels(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        card = _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1",
                action="question",
                questions=(_question(), _question("q1")),
            ),
        )
        for name in ("_back_hint", "_next_hint", "_dismiss_hint"):
            assert not hasattr(card, name), f"{name} 已删除，别加回来"

    def test_shortcut_still_works(self, qapp, make):
        """键盘仍然能翻页 —— 只是不印出来了。"""
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        card = _ask(
            chat,
            mid,
            ElaChatPermission(
                request_id="r1",
                action="question",
                questions=(_question(), _question("q1")),
            ),
        )
        assert card._tab == 0
        card._go_next()
        assert card._tab == 1
        card._go_back()
        assert card._tab == 0


class TestApproveActions:
    """批准型的三个动作**按重要性分档**，且都是 ``ElaButton``。"""

    def _approve_card(self, make, **kwargs):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        chat.chatView().beginPermission(
            mid, ElaChatPermission(request_id="r1", action="bash", **kwargs)
        )
        return chat, mid, chat.chatView().interactivePermissionCard(mid, "r1")

    def test_three_ela_buttons(self, qapp, make):
        _chat, _mid, card = self._approve_card(make)
        buttons = card._action_buttons()
        assert len(buttons) == 3
        assert all(isinstance(b, ElaButton) for b in buttons)

    def test_colour_coded_by_importance(self, qapp, make):
        """允许=实心强调色 / 始终=描边 / 拒绝=危险色。"""
        _chat, _mid, card = self._approve_card(make)
        allow, always, reject = card._action_buttons()
        assert (allow.variant(), allow.color()) == ("solid", "primary")
        assert always.variant() == "outlined"
        assert reject.isDanger(), "拒绝必须走危险色，否则和「允许」长得一样"

    def test_actions_hidden_while_responding(self, qapp, make):
        chat, mid, card = self._approve_card(make)
        assert not card._actions.isHidden()
        # 宿主的两段式流程：setResponding(True) -> 等 HTTP -> setPermission 回填
        card.setResponding(True)
        qapp.processEvents()
        assert card._actions.isHidden()
        assert not any(b.isEnabled() for b in card._action_buttons())

    def test_reject_opens_feedback_row(self, qapp, make):
        _chat, _mid, card = self._approve_card(make)
        assert card._feedback_row.isHidden()
        card._action_buttons()[2].clicked.emit()
        assert not card._feedback_row.isHidden()


class TestSettledArrivesAlreadyDone:
    """进来的 ``request`` 已经是落定态 -> 直接落记录，不进 dock。"""

    def test_no_dock_and_no_signal(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        asked = []
        chat.permissionRequested.connect(asked.append)
        chat.chatView().beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1",
                action="bash",
                detail="x = 1",
                status=ElaChatPermissionStatusType.Allowed,
            ),
        )
        assert asked == [], "已经答完了还问宿主等回复？"
        assert chat.permissionDock().card() is None
        record = chat.chatView().permissionCard(mid, "r1")
        assert isinstance(record, PermissionRecord)
        assert not record.isOpened()

    def test_record_title_uses_question_header(self, qapp, make):
        """问答型记录**不把宿主随手填的 ``action`` 当标题**。

        实测渲染出来是「已允许一次：question」—— ``action="question"`` 这种内部
        占位值直接漏给了用户看。
        """
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        chat.chatView().beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1",
                action="question",
                questions=(_question(header="范围"),),
                status=ElaChatPermissionStatusType.Allowed,
            ),
        )
        assert chat.chatView().permissionCard(mid, "r1").title() == "已允许一次：范围"

    def test_record_title_falls_back_to_question_text(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        chat.chatView().beginPermission(
            mid,
            ElaChatPermission(
                request_id="r1",
                action="ask",
                questions=(_question(),),
                status=ElaChatPermissionStatusType.Rejected,
            ),
        )
        assert chat.chatView().permissionCard(mid, "r1").title() == (
            "已拒绝：哪些目录需要一起看？"
        )


class TestPendingPermissionLifetime:
    """未答复审批的生命周期：删消息 / 撤 dock / setParts 都不能留下死卡。

    回归的是三条**进程级崩溃**路径（Qt 槽内异常 = 0xC0000409 静默终止）：
    气泡删了卡还挂在 dock 上可点、``clearPermissionDock`` 后 promote 回填已删卡、
    ``setParts`` 清扫时对 ``None`` 控件调 ``setParent``。
    """

    def test_remove_message_cancels_pending(self, qapp, make):
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        _ask(chat, mid, ElaChatPermission(request_id="r1", action="edit"))
        assert chat.permissionDock().card() is not None

        chat.chatView().removeMessage(mid)
        qapp.processEvents()
        assert chat.permissionDock().card() is None
        assert chat.pendingPermissionCards() == []

    def test_undo_message_cancels_pending(self, qapp, make):
        chat = make(ElaChatWidget)
        userId = chat.sendUserMessage("问题")
        mid = chat.beginAssistantMessage()
        _ask(chat, mid, ElaChatPermission(request_id="r1", action="edit"))

        chat.undoMessage(userId)
        qapp.processEvents()
        assert chat.permissionDock().card() is None

    def test_clear_permission_dock_keeps_pending_answerable(self, qapp, make):
        """撤下 dock 不等于作废审批：卡只是被 dock 借用，不能再被销毁。"""
        chat = make(ElaChatWidget)
        mid = _turn(chat)
        card1 = _ask(chat, mid, ElaChatPermission(request_id="r1", action="edit"))
        _ask(chat, mid, ElaChatPermission(request_id="r2", action="edit"))

        chat.clearPermissionDock()
        qapp.processEvents()
        assert chat.permissionDock().card() is None
        assert sip.isdeleted(card1) is False, "dock 只是借用卡片，不能销毁它"

        # 再插一张把 dock 重新武装起来：落定后 promote 会把最早的 r1 顶回来
        _ask(chat, mid, ElaChatPermission(request_id="r3", action="edit"))
        assert chat.chatView().resolvePermission(mid, "r3", "allowed")
        assert chat.permissionDock().card() is not None

        # 这条路径以前会操作已释放的卡片（退出码 -1073740791）
        assert chat.chatView().resolvePermission(mid, "r1", "allowed")
        remaining = [p.request_id for p in chat.chatView().pendingPermissions(mid)]
        assert remaining == ["r2"]
        assert chat.chatView().resolvePermission(mid, "r2", "allowed")
        assert chat.chatView().pendingPermissions(mid) == []

    def test_set_parts_with_pending_permission_is_safe(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.beginPermission(ElaChatPermission(request_id="r1", action="edit"))
        # 待答复审批没有控件（_part_widgets 里是 None）：清扫必须跳过
        assert bubble.setParts([]) is True


class TestPermissionModelTolerance:
    def test_from_dict_requires_request_id(self):
        """与 Question 对空 key 的口径一致：空 request_id 整条丢掉。"""
        assert ElaChatPermission.fromDict({"action": "edit"}) is None
        assert ElaChatPermission.fromDict({"request_id": "", "action": "edit"}) is None
        got = ElaChatPermission.fromDict({"request_id": "r1", "action": "edit"})
        assert got is not None and got.request_id == "r1"


class TestNoNullWidgetWarning:
    def test_begin_permission_adds_no_null_widget(self, qapp, make):
        """审批 part 只登记数据、**没有时间线控件**（落定后才补记录卡）。

        回归：``_append_part(part, None)`` 直接 ``addWidget(None)``，Qt 在终端
        刷 ``QLayout: Cannot add a null widget to QVBoxLayout/``。警告本身无害，
        但它意味着审批路径每次插卡都在给布局塞空指针 —— 不能留。
        """
        from PyQt6.QtCore import qInstallMessageHandler

        chat = make(ElaChatWidget)
        view = chat.chatView()
        captured = []
        previous = qInstallMessageHandler(
            lambda _mode, _ctx, message: captured.append(message)
        )
        try:
            mid = view.beginMessage(ElaChatRoleType.Assistant)
            view.beginStep(mid)
            view.beginPermission(
                mid,
                ElaChatPermission(request_id="r1", action="edit", detail="diff"),
            )
            qapp.processEvents()
        finally:
            qInstallMessageHandler(previous)
        offenders = [m for m in captured if "null widget" in m]
        assert offenders == [], offenders
