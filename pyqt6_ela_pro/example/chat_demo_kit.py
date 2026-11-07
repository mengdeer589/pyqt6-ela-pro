"""[pyqt6_ela_pro] 聊天示例页的共用零件。"""

from PyQt6.QtWidgets import QVBoxLayout

from pyqt6_ela_pro import ElaButton
from pyqt6_ela_pro._styles import ColorText
from pyqt6_ela_pro.chat import ElaChatWidget


def readonly_chat(
    parent,
    *,
    assistant="deepseek-v4",
    placeholder=None,
    empty_title=None,
    empty_subtitle=None,
):
    """建只读聊天组件（隐藏输入区）；每个能力域共用一个。"""
    chat = ElaChatWidget(parent)
    chat.setUserName("我")
    chat.setAssistantName(assistant)
    chat.setGenerating(False)
    chat.chatInput().setVisible(False)
    if placeholder:
        chat.setPlaceholderText(placeholder)
    if empty_title:
        chat.chatView().setEmptyTitle(empty_title)
    if empty_subtitle:
        chat.chatView().setEmptySubtitle(empty_subtitle)
    return chat


def note(page, text: str, pixel: int = 12) -> ColorText:
    """一行说明文字（已设字号，禁止 Markdown 强调）。"""
    label = ColorText(text, page)
    label.setTextPixelSize(pixel)
    label.setWordWrap(True)
    return label


def replay_section(
    page, title, method, player, build_steps, *, interval=40, buttons=(), hint=None
):
    """一节 = 标题行（含「</> 代码」）+ 若干按钮 + 说明。

    返回 ``(layout, note_label)``；``buttons`` 为 ``[(文案, 回调), ...]``，``build_steps`` 每次重新调用。
    """
    row = page._createHeaderRow(title, method)  # noqa: SLF001 —— 示例页内部约定
    row.addWidget(
        _button(page, "重播流式", lambda: player.play(build_steps(), interval=interval))
    )
    for text, callback in buttons:
        row.addWidget(_button(page, text, callback))

    box = QVBoxLayout()
    box.setSpacing(6)
    box.addLayout(row)
    label = note(page, hint or "")
    box.addWidget(label)
    return box, label


def set_note(label: ColorText, text: str) -> None:
    """更新某节的说明行（脚本回调里用）。"""
    label.setText(text)


def _button(page, text, callback):
    button = ElaButton(text, variant="outlined", size="small", parent=page)
    button.clicked.connect(callback)
    return button
