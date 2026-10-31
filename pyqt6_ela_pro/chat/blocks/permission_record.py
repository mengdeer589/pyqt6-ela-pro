"""审批落定后的时间线记录卡。（``pyqt6_ela_pro.chat`` 内部模块）。"""

from __future__ import annotations


from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QFont,
)
from PyQt6.QtWidgets import (
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaThemeType,
)

from ..._styles import ColorText
from ..._theme import ElaStatusRoleType, statusColor
from ...ela_button import ElaButton
from .._theme import (
    mono_font,
    muted_color,
    text_color,
)
from ..message import (
    ElaChatPermission,
    ElaChatPermissionStatusType,
)
from ._helpers import _collapsed_detail
from .collapsible import _CollapsibleBlock


class PermissionRecord(_CollapsibleBlock):
    """审批 / 提问的时间线记录卡（落定后留档）：默认折叠成一行，点开看详情。

    交互归输入区上方的 ``ElaChatPermissionDock``；与 :class:`PermissionCard` 不复用同一个 widget。
    """

    def __init__(
        self, permission: ElaChatPermission, parent: Optional[QWidget] = None
    ) -> None:
        # 必须先于 super()：``_CollapsibleBlock.__init__`` 末尾会调 ``_apply_theme()`` 读它。
        self._permission = None
        self._detail_expanded = False
        super().__init__(title="", opened=False, parent=parent, surface=True)
        self._permission = permission

        self._resources = ColorText(self._body)
        self._resources.setTextFormat(Qt.TextFormat.PlainText)
        self._resources.setWordWrap(True)
        self._resources.hide()
        self._body_layout.addWidget(self._resources)

        self._detail = ColorText(self._body)
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setWordWrap(True)
        self._detail.setFont(mono_font(11))
        self._detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._detail.hide()
        self._body_layout.addWidget(self._detail)

        self._detail_toggle = ElaButton(
            "展开全部", variant="link", size="small", parent=self._body
        )
        self._detail_toggle.clicked.connect(self._toggle_detail)
        self._detail_toggle.hide()
        self._body_layout.addWidget(self._detail_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.setPermission(permission)
        self._apply_theme()

    def permission(self) -> Optional[ElaChatPermission]:
        """审批快照。"""
        return self._permission

    def setPermission(self, permission: ElaChatPermission) -> None:  # noqa: N802
        """灌入审批快照并刷新标题与详情。

        默认折叠：记录是给人事后回看的，一条自带 200 行 diff 的审批展开着会把后面所有消息顶出屏幕。
        """
        self._permission = permission
        self._detail_expanded = False
        self.setTitle(self._summary_title(permission))
        self._sync_body()
        self.setExpandable(self._has_body())
        self.setOpened(False)

    @staticmethod
    def _summary_title(permission: ElaChatPermission) -> str:
        """一行摘要标题（记录卡折叠时唯一可见的东西）。

        问答型不拿 ``action`` 当标题：提问没有工具名，宿主随手填的 "question" 会漏给用户看。
        """
        labels = {
            ElaChatPermissionStatusType.Allowed: "已允许一次",
            ElaChatPermissionStatusType.Always: "已允许并记住规则",
            ElaChatPermissionStatusType.Rejected: "已拒绝",
            ElaChatPermissionStatusType.Cancelled: "已作废",
        }
        status = (
            "等待中"
            if permission.isPending
            else labels.get(permission.status, "已处理")
        )
        if permission.isQuestion:
            target = ""
            for question in permission.questions:
                target = question.header or question.question or ""
                if target:
                    break
        else:
            target = permission.action or "工具执行"
        # 一行放不下就截断（省略号由 Qt 自己加，这里只挡超长的一整段）
        if len(target) > 40:
            target = target[:40] + "…"
        return f"{status}：{target}" if target else status

    def _has_body(self) -> bool:
        permission = self._permission
        if permission is None:
            return False
        return bool(
            permission.resources
            or permission.detail
            or permission.feedback
            or permission.answer
        )

    @staticmethod
    def _raw_detail(permission: ElaChatPermission) -> str:
        if permission.isQuestion:
            if permission.detail:
                return permission.detail
            answers = permission.parsedAnswer()
            lines = []
            for question in permission.questions:
                value = answers.get(question.key)
                if value is None:
                    continue
                shown = (
                    "、".join(str(item) for item in value)
                    if isinstance(value, list)
                    else str(value)
                )
                label = question.header or question.question or question.key
                lines.append(f"{label}: {shown}")
            return "\n".join(lines)
        if (
            permission.status == ElaChatPermissionStatusType.Rejected
            and permission.feedback
        ):
            return permission.feedback
        return permission.detail

    def _sync_body(self) -> None:
        permission = self._permission
        if permission is None:
            self._resources.hide()
            self._detail.hide()
            self._detail_toggle.hide()
            return
        resources = [item for item in permission.resources if item]
        if resources and not permission.isQuestion:
            shown = resources[:4]
            text = "\n".join(shown)
            if len(resources) > len(shown):
                text += f"\n… 另有 {len(resources) - len(shown)} 项"
            self._resources.setText(text)
            self._resources.show()
        else:
            self._resources.setText("")
            self._resources.hide()
        detail = self._raw_detail(permission)
        shown, overflow, total = _collapsed_detail(detail, self._detail_expanded)
        self._detail.setText(shown)
        self._detail.setVisible(bool(shown))
        self._detail_toggle.setVisible(overflow)
        self._detail_toggle.setText(
            f"收起（共 {total} 行）"
            if self._detail_expanded
            else f"展开全部（共 {total} 行）"
        )

    def _toggle_detail(self) -> None:
        self._detail_expanded = not self._detail_expanded
        self._sync_body()

    def _apply_theme(self) -> None:
        super()._apply_theme()
        if getattr(self, "_resources", None) is None:
            # ``_CollapsibleBlock.__init__`` 末尾就会调过来，那时子控件还没建；本类常在
            # 点击信号的栈上被构造，异常穿出 C++ 边界 = 0xC0000409。
            return
        mode = self._theme_mode
        permission = self._permission
        if permission is not None and permission.status == (
            ElaChatPermissionStatusType.Rejected
        ):
            accent = statusColor(mode, ElaStatusRoleType.Error)
        elif permission is not None and not permission.isPending:
            accent = statusColor(mode, ElaStatusRoleType.Success)
        else:
            accent = text_color(mode)
        self._title_label.setTextColor(accent)
        self._title_label.setTextPixelSize(12)
        self._title_label.setTextWeight(QFont.Weight.DemiBold)
        self._resources.setTextColor(muted_color(mode, 0.7))
        self._resources.setTextPixelSize(11)
        self._detail.setTextColor(muted_color(mode, 0.8))
        self._detail.setTextPixelSize(11)
        self._detail_toggle.setColor("primary")

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()
