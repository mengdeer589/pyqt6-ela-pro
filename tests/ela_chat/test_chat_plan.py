"""计划面板：数据模型、气泡 API、视图持久化与 journal 重放。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import (
    ElaChatBubble,
    ElaChatPart,
    ElaChatPartKindType,
    ElaChatPlan,
    ElaChatPlanItem,
    ElaChatPlanItemStatusType,
    ElaChatRoleType,
    ElaChatStatusType,
    ElaChatTurnJournal,
    ElaChatView,
    PlanPanel,
)


def _plan() -> ElaChatPlan:
    return ElaChatPlan(
        title="收尾",
        items=(
            ElaChatPlanItem("读代码", ElaChatPlanItemStatusType.Completed),
            ElaChatPlanItem("改实现", ElaChatPlanItemStatusType.InProgress),
            ElaChatPlanItem("补测试", ElaChatPlanItemStatusType.Pending),
        ),
    )


class TestPlanModel:
    def test_from_markdown(self):
        plan = ElaChatPlan.fromMarkdown(
            "# 计划\n- [x] 读代码\n- [>] 改实现\n- [ ] 补测试\n- [~] 取消项"
        )
        assert plan is not None
        assert [item.status for item in plan.items] == [
            ElaChatPlanItemStatusType.Completed,
            ElaChatPlanItemStatusType.InProgress,
            ElaChatPlanItemStatusType.Pending,
            ElaChatPlanItemStatusType.InProgress,
        ]
        assert plan.progress() == (1, 4)
        assert plan.current().text == "改实现"
        assert not plan.isComplete()

    def test_coerce_shapes(self):
        assert ElaChatPlan.coerce(None) is None
        assert ElaChatPlan.coerce("没有清单") is None
        assert ElaChatPlan.coerce([{"text": "a"}]).progress() == (0, 1)
        assert ElaChatPlan.coerce({"items": ["a", {"content": "b", "status": "done"}]})
        plan = _plan()
        assert ElaChatPlan.coerce(plan) is plan
        assert ElaChatPlan.coerce(plan.toDict()).progress() == (1, 3)

    def test_part_roundtrip(self):
        part = ElaChatPart(
            id="p1",
            kind=ElaChatPartKindType.Plan,
            status=ElaChatStatusType.Done,
            plan=_plan(),
            step=2,
        )
        restored = ElaChatPart.fromDict(part.toDict())
        assert restored is not None
        assert restored.plan == part.plan
        assert restored.kind == ElaChatPartKindType.Plan


class TestPlanBubble:
    def test_set_plan_reuses_part(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        first = bubble.setPlan(_plan())
        second = bubble.setPlan(ElaChatPlan(items=(ElaChatPlanItem("只剩一步"),)))
        assert first == second
        parts = [p for p in bubble.parts() if p.kind == ElaChatPartKindType.Plan]
        assert len(parts) == 1
        assert parts[0].plan.items[0].text == "只剩一步"
        assert bubble.plan().items[0].text == "只剩一步"

    def test_panel_summary(self, qapp, make):
        panel = make(PlanPanel)
        panel.setOpened(True)
        panel.setPlan(_plan())
        assert "1/3" in panel._summary_label.text()
        assert "改实现" in panel._summary_label.text()
        panel.setPlan(
            ElaChatPlan(
                items=(
                    ElaChatPlanItem("a", ElaChatPlanItemStatusType.Completed),
                    ElaChatPlanItem("b", ElaChatPlanItemStatusType.Completed),
                )
            )
        )
        assert "已完成 2 项" in panel._summary_label.text()
        assert len(panel._list._rows) == 2

    def test_clear_plan(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        bubble.setPlan(_plan())
        bubble.clearPlan()
        assert bubble.plan() is None
        assert not [p for p in bubble.parts() if p.kind == ElaChatPartKindType.Plan]


class TestPlanView:
    def test_set_plan_and_bundle(self, qapp, make):
        view = make(ElaChatView)
        view.resize(640, 480)
        messageId = view.beginMessage(ElaChatRoleType.Assistant)
        partId = view.setPlan(messageId, _plan())
        view.endMessage(messageId)
        assert partId
        assert view.plan(messageId).progress() == (1, 3)
        assert view.planPart(messageId).kind == ElaChatPartKindType.Plan

        bundle = view.exportSession()
        other = make(ElaChatView)
        other.importSession(bundle, clear=True)
        restored = other.messages()[0]
        plan_part = next(
            p for p in restored.parts if p.kind == ElaChatPartKindType.Plan
        )
        assert plan_part.plan.progress() == (1, 3)

    def test_set_plan_without_bubble_updates_snapshot(self, qapp, make):
        view = make(ElaChatView)
        messageId = view.addMessage(ElaChatRoleType.Assistant, "")
        partId = view.setPlan(messageId, _plan())
        assert view.plan(messageId).progress() == (1, 3)
        view.clearPlan(messageId)
        assert view.plan(messageId) is None
        assert partId


class TestPlanJournal:
    def test_plan_replay(self):
        journal = ElaChatTurnJournal(messageId=1).begin(1)
        journal.setPlan(_plan())
        journal.setPlan(ElaChatPlan(items=(ElaChatPlanItem("最终"),)))
        journal.end()
        parts = [
            p for p in journal.message().parts if p.kind == ElaChatPartKindType.Plan
        ]
        assert len(parts) == 1
        assert parts[0].plan.items[0].text == "最终"

        restored = ElaChatTurnJournal.fromLines(journal.dumps().splitlines())
        parts = [
            p for p in restored.message().parts if p.kind == ElaChatPartKindType.Plan
        ]
        assert len(parts) == 1
        assert parts[0].plan.items[0].text == "最终"
