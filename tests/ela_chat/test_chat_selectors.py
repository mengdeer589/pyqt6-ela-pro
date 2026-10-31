"""输入区下拉选择器。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import ElaChatInput, ElaChatSelectorItem


class TestSelectors:
    def test_add_and_change(self, qapp, make):
        inp = make(ElaChatInput)
        seen = []
        inp.selectorChanged.connect(lambda key, value: seen.append((key, value)))
        selector = inp.addSelector(
            "model",
            "模型",
            [
                ElaChatSelectorItem(id="m1", label="m1"),
                ElaChatSelectorItem(id="m2", label="m2"),
            ],
            "m1",
        )
        assert selector.current() == "m1"
        assert selector.text() == "m1"
        assert inp.selectorValue("model") == "m1"
        selector.setCurrent("m2", emit=True)
        assert seen == [("model", "m2")]
        assert inp.setSelectorItems(
            "model",
            [ElaChatSelectorItem(id="m3", label="m3")],
            "m3",
        )
        assert selector.current() == "m3"

    def test_remove(self, qapp, make):
        inp = make(ElaChatInput)
        inp.addSelector("agent", "Agent", [ElaChatSelectorItem(id="a", label="A")], "a")
        assert inp.removeSelector("agent")
        assert inp.selector("agent") is None
        assert not inp.removeSelector("agent")
