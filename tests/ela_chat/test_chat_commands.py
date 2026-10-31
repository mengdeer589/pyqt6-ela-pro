"""``/`` 命令与 ``@`` mention 区间。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import ElaChatInput, ElaChatSuggestion


class TestCommands:
    def test_provider_and_select(self, qapp, make):
        inp = make(ElaChatInput)
        seen = []
        inp.commandSelected.connect(seen.append)
        inp.setCommandProvider(
            lambda query: [
                ElaChatSuggestion(id="compact", label="compact", description="压缩")
            ]
        )
        inp.setText("/")
        inp._update_popup()
        assert inp.popup().items()
        inp.popup().activateCurrent()
        assert inp.text().startswith("/compact ")
        assert seen == ["compact"]

    def test_command_submit_mode(self, qapp, make):
        inp = make(ElaChatInput)
        submitted = []
        commands = []
        inp.submitted.connect(submitted.append)
        inp.commandSubmitted.connect(commands.append)
        inp.setCommandProvider(lambda query: [ElaChatSuggestion(id="x", label="x")])
        inp.setCommandSubmitMode("signal")
        inp.setText("/x")
        assert inp.submit()
        assert submitted == []
        assert commands == ["/x"]
        assert inp.text() == ""

    def test_mention_spans(self, qapp, make):
        inp = make(ElaChatInput)
        inp.setMentionProvider(
            lambda query: [ElaChatSuggestion(id="a", label="a.py", kind="file")]
        )
        inp.setText("看 @")
        inp._update_popup()
        inp.popup().activateCurrent()
        spans = inp.mentionSpans()
        assert len(spans) == 1
        assert spans[0].kind == "file"
        text = inp.text()
        assert text[spans[0].start : spans[0].end] == "@a.py"
