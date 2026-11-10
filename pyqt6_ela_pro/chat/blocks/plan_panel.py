"""计划 / 待办面板（``kind == Plan``）：折叠摘要 + 可展开 checklist。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PyQt6ElaWidgetTools import (
    ElaIconButton,
    ElaIconType,
    ElaThemeType,
    eTheme,
)

from ..._internal import _ThemeAwareMixin, is_deleted
from ..._styles import ColorText
from ..._theme import ElaStatusRoleType, statusColor
from .._theme import muted_color, text_color
from ..message import ElaChatPlan, ElaChatPlanItemStatusType
from .collapsible import _CollapsibleBlock

#: 状态 → 图标
_STATUS_ICONS = {
    ElaChatPlanItemStatusType.Completed: ElaIconType.IconName.CircleCheck,
    ElaChatPlanItemStatusType.InProgress: ElaIconType.IconName.ArrowRight,
    ElaChatPlanItemStatusType.Cancelled: ElaIconType.IconName.Ban,
    ElaChatPlanItemStatusType.Pending: ElaIconType.IconName.SquareDashed,
}


class PlanListView(_ThemeAwareMixin, QWidget):
    """只读计划清单（不折叠；``PlanPanel`` 与 todo 工具渲染器复用）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme_mode = eTheme.getThemeMode()
        self._plan = ElaChatPlan()
        self._rows: list = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def setPlan(self, plan) -> None:
        """替换整份计划（计划项通常很少，直接重建行）。"""
        value = ElaChatPlan.coerce(plan)
        self._plan = value or ElaChatPlan()
        self._rebuild()

    def plan(self) -> ElaChatPlan:
        """获取当前计划快照。"""
        return self._plan

    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        self._rows.clear()
        for entry in self._plan.items:
            row = QWidget(self)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            icon = ElaIconButton(
                _STATUS_ICONS.get(entry.status, ElaIconType.IconName.SquareDashed),
                11,
                14,
                14,
                row,
            )
            icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            label = ColorText(row)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText(entry.text)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
            row_layout.addWidget(label, 1)
            self._layout.addWidget(row)
            self._rows.append((icon, label, entry.status))
        self._apply_theme()
        self.updateGeometry()

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt 命名)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt 命名)
        return max(0, self._layout.heightForWidth(int(width)))

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        hint = self._layout.sizeHint()
        return QSize(hint.width(), max(0, hint.height()))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        return QSize(120, 0)

    def _apply_theme(self) -> None:
        mode = self._theme_mode
        danger = statusColor(mode, ElaStatusRoleType.Error)
        for icon, label, status in self._rows:
            if is_deleted(icon) or is_deleted(label):
                continue
            if status == ElaChatPlanItemStatusType.Completed:
                color = muted_color(mode, 0.5)
            elif status == ElaChatPlanItemStatusType.Cancelled:
                color = danger
            elif status == ElaChatPlanItemStatusType.InProgress:
                color = text_color(mode)
            else:
                color = muted_color(mode, 0.7)
            label.setTextColor(color)
            label.setTextPixelSize(12)
            icon.setLightIconColor(color)
            icon.setDarkIconColor(color)

    def _onThemeChanged(self, mode: ElaThemeType.ThemeMode) -> None:
        self._theme_mode = mode
        self._apply_theme()


class PlanPanel(_CollapsibleBlock):
    """计划卡：折叠态显示当前项 + 进度，展开显示完整 checklist。"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        plan: Optional[ElaChatPlan] = None,
    ) -> None:
        super().__init__(title="计划", opened=False, parent=parent, surface=False)
        self.setCardMargins(0, 0, 0, 0)
        self._plan = plan or ElaChatPlan()
        self._list: Optional[PlanListView] = None
        self._summary_label = ColorText(self)
        self._summary_label.setWordWrap(False)
        self._summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.insertHeaderWidget(self.headerLayout().count() - 1, self._summary_label)
        self.setPlan(self._plan)

    def setPlan(self, plan) -> None:
        """替换计划快照并立即刷新摘要 / 清单。"""
        value = ElaChatPlan.coerce(plan)
        self._plan = value or ElaChatPlan()
        self.setTitle(self._plan.title or "计划")
        if self._list is not None:
            self._list.setPlan(self._plan)
        self._sync_summary()
        self._apply_theme()

    def _build_body(self) -> None:
        if self._list is not None:
            return
        self._list = PlanListView(self)
        self._list.setPlan(self._plan)
        self.bodyLayout().addWidget(self._list)
        self._apply_theme()
        self.updateGeometry()
        if self.layout() is not None:
            self.layout().activate()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        if self.isOpened():
            self._build_body()

    def _on_toggled(self, checked: bool) -> None:
        if checked:
            self._build_body()
        super()._on_toggled(checked)

    def setOpenedSilently(self, opened: bool) -> None:
        if opened:
            self._build_body()
        super().setOpenedSilently(opened)

    def plan(self) -> ElaChatPlan:
        """获取当前计划快照。"""
        return self._plan

    def _sync_summary(self) -> None:
        done, total = self._plan.progress()
        if not total:
            text = ""
        elif self._plan.isComplete():
            text = f"已完成 {total} 项"
        else:
            current = self._plan.current()
            head = current.text if current is not None else "待开始"
            head = " ".join(str(head or "").split())
            if len(head) > 60:
                head = head[:59] + "…"
            text = f"{done}/{total} · {head}"
        self._summary_label.setText(text)
        self._summary_label.setVisible(bool(text))

    def _apply_theme(self) -> None:
        super()._apply_theme()
        if not hasattr(self, "_summary_label"):
            return
        self._summary_label.setTextColor(muted_color(self._theme_mode, 0.6))
        self._summary_label.setTextPixelSize(12)


__all__ = ["PlanListView", "PlanPanel"]
