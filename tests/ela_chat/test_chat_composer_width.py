"""composer 宽度跟随阅读列，但不向宿主贡献滞后的固定下限。"""

from __future__ import annotations

from pyqt6_ela_pro.chat import ElaChatWidget


def _sync(chat, qapp, width: int) -> None:
    chat.resize(width, 400)
    qapp.processEvents()


def _prepared(qapp, make) -> ElaChatWidget:
    chat = make(ElaChatWidget)
    chat.chatView().setContentMaxWidth(0)
    chat.show()
    qapp.processEvents()
    return chat


def test_width_tracks_chat_without_stale_minimum(qapp, make):
    chat = _prepared(qapp, make)
    _sync(chat, qapp, 620)
    inp = chat.chatInput()
    assert inp.width() == 600
    assert inp.minimumWidth() == 0
    assert inp.x() == 10

    floor = chat.minimumSizeHint().width()
    _sync(chat, qapp, 500)
    assert inp.width() == 480
    assert inp.minimumWidth() == 0
    assert inp.x() == 10
    assert chat.minimumSizeHint().width() == floor


def test_content_max_width_caps_and_centers(qapp, make):
    chat = _prepared(qapp, make)
    chat.chatView().setContentMaxWidth(300)
    _sync(chat, qapp, 900)
    inp = chat.chatInput()
    assert inp.width() == 300
    assert inp.x() == 300
    assert [widget.maximumWidth() for widget in chat._composer_widgets] == [300] * 4


def test_narrow_width_removes_120_floor(qapp, make):
    chat = _prepared(qapp, make)
    chat.setFixedWidth(100)
    qapp.processEvents()
    inp = chat.chatInput()
    # 窗口管理器可能把顶层窗口抬到 120；关键是 composer 不再被钉到 120。
    assert inp.width() < 120
    assert inp.minimumWidth() == 0
    assert inp.maximumWidth() < 120


def test_all_composers_share_width_and_zero_minimum(qapp, make):
    chat = _prepared(qapp, make)
    _sync(chat, qapp, 620)
    assert [widget.maximumWidth() for widget in chat._composer_widgets] == [600] * 4
    assert [widget.minimumWidth() for widget in chat._composer_widgets] == [0] * 4


def test_sync_reflows_when_max_already_matches(qapp, make):
    chat = _prepared(qapp, make)
    _sync(chat, qapp, 620)
    inp = chat.chatInput()
    assert (inp.width(), inp.maximumWidth()) == (600, 600)

    # 复现 max 已正确、实际宽度滞后的残留态
    inp.resize(480, inp.height())
    assert inp.width() == 480

    chat._sync_composer_width()
    qapp.processEvents()
    assert inp.width() == 600
