"""
[pyqt6_ela_pro] 聊天示例页的共用零件

聊天组件有个别的示例页没有的性质：**很多能力只在「动起来」时才看得见**——
推理块逐步浮现、工具卡的忙碌环、流式期间底部行动作整条隐藏、步骤统计徽标
落定。纯静态截图看不出这些，所以聊天示例页统一用「**预填 + 可重播**」：

- **预填**：页面构造完就有内容，读者滚动即看完全貌，不用自己造一轮对话；
- **重播**：每节一个「重播流式」按钮，把这一节的过程重新走一遍。

两者用同一个 :class:`_ScriptPlayer` 实现 —— 区别只是「延迟 0ms 跑完」还是
「按脚本节奏走」。脚本里的每一步都是**真实公开 API 调用**（``view.beginText`` /
``view.appendText`` / ``view.addToolCall`` …），所以「</> 代码」按钮里读到的
就是用户真正要写的代码，而不是另一套内部机制。
"""

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
    """建一个**只读**的聊天组件（隐藏输入区），用于「陈列」而非「上手」。

    ``chatInput().setVisible(False)`` + ``setGenerating(False)`` 之后它就是一个
    纯消息画布。页面上每个能力域共用一个，不要每个小节都建一个 —— 6 个
    ``ElaChatWidget`` 叠起来比这个页面本身还重。
    """
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
    """一行说明文字。

    **每个 ``ColorText`` 都必须显式 ``setTextPixelSize``** —— 它走 ``ElaText``，
    不设就是 ``ElaText`` 的默认字号（实测 28px），一行注释突然冒出巨大字号，
    整页的比例就崩了。

    **不要写 Markdown 强调**（``**粗体`` / ```代码```）—— ``ElaText`` 只吃
    ``Qt::PlainText``，写进去就是原样显示的星号。要真上 Markdown 得用
    ``ElaMarkdownViewer``，代价是一整个子控件，不值得为一行说明付出。
    """
    label = ColorText(text, page)
    label.setTextPixelSize(pixel)
    label.setWordWrap(True)
    return label


def replay_section(
    page, title, method, player, build_steps, *, interval=40, buttons=(), hint=None
):
    """一节 = 标题行（含「</> 代码」）+ 若干按钮 + 说明。

    ``build_steps`` 是 ``() -> [(ms, callable), ...]``，**每次都重新调用** ——
    步骤里的闭包会捕获当轮的 ``messageId``，不能缓存。``buttons`` 是除「重播」
    之外的按钮 ``(文案, 回调)``。返回 ``(layout, note_label)``，``note_label``
    由步骤里的回调经 :func:`set_note` 更新。
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
