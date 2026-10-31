"""ElaChartWidget 的标注 / 数据点标签双击编辑方法组。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional


from PyQt6.QtCore import (
    QPointF,
    QRectF,
    Qt,
)
from PyQt6.QtGui import (
    QColor,
    QPalette,
)

from ..._styles import editBorderlessStyle
from .._tokens import (
    T,
)
from ._shared import (
    _HOVERABLE_COMPONENTS,
)
from .annotation import _AnnotationEditor


if TYPE_CHECKING:
    pass


class _ChartAnnotationMixin:
    """方法组 mixin：状态由 ``ElaChartWidget.__init__`` 建立。"""

    def setAnnotationEditingEnabled(self, enabled: bool) -> None:
        """是否启用内置的标注标签双击行内编辑（默认开）。

        关闭后双击只发 ``annotationEditRequested``，宿主可自行弹框并调
        :meth:`setAnnotationText` 提交。
        """
        self._annotation_editable = bool(enabled)
        if not self._annotation_editable:
            self._hide_annotation_editor()

    def annotationEditingEnabled(self) -> bool:
        """内置标注编辑器是否启用。"""
        return bool(self._annotation_editable)

    def _annotation_target_at(self, pos: QPointF):
        """查找双击位置下的标注标签 → ``{component, ...}`` 或 None。"""
        for comp in self._components:
            if str(getattr(comp, "optionKey", "")) not in _HOVERABLE_COMPONENTS:
                continue
            hit = getattr(comp, "labelEditHit", None)
            if not callable(hit):
                continue
            try:
                found = hit(pos)
            except Exception:
                continue
            if not found:
                continue
            index, rect = found
            renderer = comp._renderer() if hasattr(comp, "_renderer") else None
            text = ""
            edit_text = getattr(comp, "labelEditText", None)
            if callable(edit_text):
                try:
                    text = edit_text(index)
                except Exception:
                    text = ""
            return {
                "component": comp,
                "componentType": str(getattr(comp, "optionKey", "")),
                "dataIndex": int(index),
                "rect": QRectF(rect),
                "text": text,
                "seriesName": renderer.name if renderer is not None else "",
            }
        return None

    def _series_label_target_at(self, pos: QPointF):
        """查找双击位置下的数据点标签 → 编辑目标 dict 或 None。"""
        for renderer in reversed(self._series):
            if not renderer.visible:
                continue
            hit = getattr(renderer, "labelHitTest", None)
            if not callable(hit):
                continue
            try:
                found = hit(pos)
            except Exception:
                continue
            if not found:
                continue
            index, rect, text = found
            return {
                "kind": "seriesLabel",
                "renderer": renderer,
                "componentType": "seriesLabel",
                "dataIndex": int(index),
                "rect": QRectF(rect),
                "text": str(text),
                "seriesName": renderer.name,
            }
        return None

    def _begin_annotation_edit(self, pos: QPointF) -> bool:
        """双击命中标注 / 数据点标签：发请求信号，按需打开内置编辑器。"""
        target = self._annotation_target_at(pos)
        if target is None:
            target = self._series_label_target_at(pos)
        if target is None:
            return False
        self.annotationEditRequested.emit(
            {
                "seriesName": target["seriesName"],
                "componentType": target["componentType"],
                "dataIndex": target["dataIndex"],
                "text": target["text"],
            }
        )
        if self._annotation_editable:
            self._show_annotation_editor(target)
        return True

    def _ensure_annotation_editor(self):
        if self._annotation_editor is not None:
            return self._annotation_editor
        editor = _AnnotationEditor(self)
        editor.setStyle(editBorderlessStyle())
        editor.setFrame(False)
        editor.setAutoFillBackground(True)
        editor.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        palette = editor.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(T("color.bg.elevated")))
        palette.setColor(QPalette.ColorRole.Window, QColor(T("color.bg.elevated")))
        palette.setColor(QPalette.ColorRole.Text, QColor(T("color.text.primary")))
        editor.setPalette(palette)
        editor.editingFinished.connect(self._commit_annotation_edit)
        editor.cancelled.connect(self._cancel_annotation_edit)
        self._annotation_editor = editor
        return editor

    def _show_annotation_editor(self, target: dict) -> None:
        editor = self._ensure_annotation_editor()
        self._annotation_target = target
        rect = QRectF(target["rect"]).adjusted(-4, -4, 4, 4)
        rect = rect.intersected(QRectF(self.rect()))
        if rect.width() < 40:
            rect.setWidth(min(160.0, max(40.0, self.width() - rect.left() - 4)))
        height = max(22.0, rect.height())
        editor.setGeometry(
            int(rect.left()), int(rect.top()), int(rect.width()), int(height)
        )
        editor.setText(str(target.get("text") or ""))
        editor.selectAll()
        editor.show()
        editor.raise_()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)

    def _hide_annotation_editor(self) -> None:
        self._annotation_target = None
        editor = self._annotation_editor
        if editor is not None:
            editor.hide()

    def _commit_annotation_edit(self) -> None:
        target = self._annotation_target
        editor = self._annotation_editor
        if target is None or editor is None:
            return
        text = editor.text()
        self._annotation_target = None
        editor.hide()
        if target.get("kind") == "seriesLabel":
            self.setSeriesLabelText(
                target.get("seriesName"),
                target.get("dataIndex"),
                text,
            )
        else:
            self.setAnnotationText(
                target.get("seriesName"),
                target.get("componentType"),
                target.get("dataIndex"),
                text,
            )
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _cancel_annotation_edit(self) -> None:
        self._hide_annotation_editor()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _resolve_series(
        self,
        seriesName: str = "",
        seriesIndex: Optional[int] = None,
        seriesId: Optional[str] = None,
    ):
        """按 id → name → 下标解析系列渲染器（name 为空取首个可见系列）。"""
        if seriesId is not None:
            key = str(seriesId).strip()
            if not key:
                return None
            for renderer in self._series:
                if str((getattr(renderer, "opt", {}) or {}).get("id") or "") == key:
                    return renderer
            return None
        if seriesIndex is not None:
            try:
                index = int(seriesIndex)
            except (TypeError, ValueError, OverflowError):
                return None
            return self._series[index] if 0 <= index < len(self._series) else None
        name = str(seriesName or "")
        for renderer in self._series:
            if name and renderer.name != name:
                continue
            if name or renderer.visible:
                return renderer
        return None

    def setAnnotationText(
        self,
        seriesName: str = "",
        componentType: str = "",
        dataIndex: int = 0,
        text: str = "",
        *,
        seriesIndex: Optional[int] = None,
        seriesId: Optional[str] = None,
        rebuild: bool = True,
    ) -> bool:
        """修改标注标签文本（markPoint / markLine 的 ``name``）。

        系列寻址：``seriesId`` → ``seriesName`` → ``seriesIndex``（都为空时取
        首个含该组件的系列）。返回是否成功。
        """
        wanted = str(componentType or "")
        explicit = seriesId is not None or seriesIndex is not None or bool(seriesName)
        renderer = self._resolve_series(seriesName, seriesIndex, seriesId)
        target_comp = None
        if renderer is not None:
            for comp in self._components:
                if str(getattr(comp, "optionKey", "")) != wanted:
                    continue
                comp_renderer = comp._renderer() if hasattr(comp, "_renderer") else None
                if comp_renderer is renderer:
                    target_comp = comp
                    break
        if target_comp is None and not explicit:
            for comp in self._components:
                if str(getattr(comp, "optionKey", "")) == wanted:
                    target_comp = comp
                    break
        if target_comp is None:
            return False
        resolved_name = renderer.name if renderer is not None else ""
        setter = getattr(target_comp, "setLabelText", None)
        if not callable(setter):
            return False
        try:
            if not setter(int(dataIndex), str(text)):
                return False
        except Exception:
            return False
        self._opt_version += 1
        if rebuild:
            self._rebuild()
            self.update()
        self.annotationEdited.emit(
            {
                "seriesName": resolved_name,
                "componentType": wanted,
                "dataIndex": int(dataIndex),
                "text": str(text),
            }
        )
        return True

    def setSeriesLabelText(
        self,
        seriesName: str = "",
        dataIndex: int = 0,
        text: str = "",
        *,
        seriesIndex: Optional[int] = None,
        seriesId: Optional[str] = None,
        rebuild: bool = False,
    ) -> bool:
        """修改某个数据点的标签文本（写入 ``series.labelTexts[str(index)]``）。

        系列寻址：``seriesId`` → ``seriesName`` → ``seriesIndex``（都为空时取
        首个可见系列）。空字符串 = 删除覆盖、恢复默认数值文案。默认只失效系列
        层位图（百万点图表上不卡顿），``rebuild=True`` 强制全量重建。
        """
        renderer = self._resolve_series(seriesName, seriesIndex, seriesId)
        if renderer is None or not hasattr(renderer, "setLabelText"):
            return False
        try:
            if not renderer.setLabelText(int(dataIndex), str(text)):
                return False
        except Exception:
            return False
        if rebuild:
            self._opt_version += 1
            self._rebuild()
        else:
            self.invalidateSeriesLayer()
        self.update()
        self.annotationEdited.emit(
            {
                "seriesName": renderer.name,
                "componentType": "seriesLabel",
                "dataIndex": int(dataIndex),
                "text": str(text),
            }
        )
        return True

    def seriesLabelTexts(
        self,
        seriesName: str = "",
        *,
        seriesIndex: Optional[int] = None,
        seriesId: Optional[str] = None,
    ) -> dict:
        """读取某系列的数据点标签覆盖表（``{str(index): text}`` 的副本）。"""
        renderer = self._resolve_series(seriesName, seriesIndex, seriesId)
        if renderer is None:
            return {}
        overrides = renderer._source_opt.get("labelTexts")
        return dict(overrides) if isinstance(overrides, dict) else {}

    def clearSeriesLabelTexts(
        self,
        seriesName: str = "",
        *,
        seriesIndex: Optional[int] = None,
        seriesId: Optional[str] = None,
    ) -> bool:
        """清空某系列的全部数据点标签覆盖（恢复默认数值文案）。"""
        renderer = self._resolve_series(seriesName, seriesIndex, seriesId)
        if renderer is None:
            return False
        renderer._source_opt.pop("labelTexts", None)
        renderer.opt.pop("labelTexts", None)
        self.invalidateSeriesLayer()
        self.update()
        return True
