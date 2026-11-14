"""输入区下拉选择器：宿主直接实例化并放进工具栏。"""

from __future__ import annotations

from PyQt6ElaWidgetTools import ElaIconType

from pyqt6_ela_pro.chat import ElaChatInput, ElaChatSelector, ElaChatSelectorItem


class TestSelectors:
    def test_add_and_change(self, qapp, make):
        inp = make(ElaChatInput)
        selector = ElaChatSelector(
            "模型",
            [
                ElaChatSelectorItem(id="m1", label="m1"),
                ElaChatSelectorItem(id="m2", label="m2"),
            ],
            "m1",
            inp.inputSurface(),
        )
        seen = []
        selector.selectionChanged.connect(seen.append)
        assert selector.current() == "m1"
        assert selector.text() == "m1"
        selector.setCurrent("m2", emit=True)
        assert seen == ["m2"]
        assert selector.current() == "m2"
        selector.setItems(
            [ElaChatSelectorItem(id="m3", label="m3")],
            "m3",
        )
        assert selector.current() == "m3"

    def test_current_item_icon_syncs_to_button(self, qapp, make):
        inp = make(ElaChatInput)
        selector = ElaChatSelector(
            "模式",
            [
                ElaChatSelectorItem(
                    id="agent",
                    label="Agent",
                    icon=ElaIconType.IconName.Robot,
                ),
                ElaChatSelectorItem(
                    id="plan",
                    label="Plan",
                    icon=ElaIconType.IconName.ListCheck,
                ),
            ],
            "agent",
            inp.inputSurface(),
        )
        assert selector.elaIcon() == ElaIconType.IconName.Robot
        selector.setCurrent("plan", emit=True)
        assert selector.elaIcon() == ElaIconType.IconName.ListCheck
        selector.setItems([ElaChatSelectorItem(id="plain", label="Plain")], "plain")
        assert selector.elaIcon() == ElaIconType.IconName.None_


class TestSelectorPlacement:
    def test_toolbar_appends_after_usage_ring(self, qapp, make):
        inp = make(ElaChatInput)
        selector = ElaChatSelector("模式", ["agent"], "agent", inp.inputSurface())
        inp.toolBar().addWidget(selector, zone="leading", key="mode")
        bar = inp.toolBar()
        assert bar.item("mode") is selector
        assert bar._leading.indexOf(selector) > bar._leading.indexOf(inp._usage_ring)
        assert bar._leading.indexOf(selector) == bar._leading.count() - 1

    def test_shell_mode_hides_toolbar_selectors(self, qapp, make):
        inp = make(ElaChatInput)
        selector = ElaChatSelector("模式", ["agent"], "agent", inp.inputSurface())
        inp.toolBar().addWidget(selector, zone="leading", key="mode")
        inp.setShellMode(True)
        assert selector.isHidden()
        inp.setShellMode(False)
        assert not selector.isHidden()
