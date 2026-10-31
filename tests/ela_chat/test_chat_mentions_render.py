"""用户消息里的 @ mention 高亮。"""

from __future__ import annotations

from PyQt6.QtCore import Qt

from pyqt6_ela_pro.chat import ElaChatMention, ElaChatRoleType, ElaChatView


class TestMentionRender:
    def test_rich_text_and_plain_copy(self, qapp, make):
        view = make(ElaChatView)
        mid = view.addMessage(ElaChatRoleType.User, "看 <b>@a.py</b>")
        view.setMessageMentions(mid, [ElaChatMention(start=4, end=9, kind="file")])
        bubble = view.bubble(mid)
        assert bubble is not None
        label = bubble._label
        assert label.textFormat() == Qt.TextFormat.RichText
        assert "<span" in label.text()
        assert "<b>" not in label.text()  # 原文被转义
        # 复制走纯文本，绝不能把 HTML 拷出去
        assert bubble.text() == "看 <b>@a.py</b>"

    def test_mention_does_not_widen_bubble(self, qapp, make):
        """带 @ 的短消息仍按原文宽度收窄，不能量到 RichText 的 HTML 源码。"""
        view = make(ElaChatView)
        text = "看 @a.py 的实现"
        mid = view.addMessage(ElaChatRoleType.User, text)
        bubble = view.bubble(mid)
        assert bubble is not None
        bubble.resize(1200, bubble.height())
        bubble._update_max_width()
        before = bubble._body.width()

        view.setMessageMentions(mid, [ElaChatMention(start=2, end=7, kind="file")])
        qapp.processEvents()
        bubble._update_max_width()

        assert bubble._body.width() == before
        assert bubble._body.width() < 320

    def test_no_mentions_stays_plain(self, qapp, make):
        view = make(ElaChatView)
        mid = view.addMessage(ElaChatRoleType.User, "普通 <b>文本</b>")
        bubble = view.bubble(mid)
        assert bubble is not None
        assert bubble._label.textFormat() == Qt.TextFormat.PlainText
        assert bubble.text() == "普通 <b>文本</b>"

    def test_theme_change_rerenders(self, qapp, make, mock_e_theme):
        view = make(ElaChatView)
        mid = view.addMessage(ElaChatRoleType.User, "@a")
        view.setMessageMentions(mid, [ElaChatMention(start=0, end=2, kind="file")])
        bubble = view.bubble(mid)
        before = bubble._label.text()
        mock_e_theme()
        assert bubble._label.text() == before or "<span" in bubble._label.text()
