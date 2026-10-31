"""时间线密度设置（``pyqt6_ela_pro.chat.timeline_detail``）。

对齐 opencode 的 ``timelineDetail``：每个分区（思考 / shell / 编辑 / 子代理 /
通知 / 工具）各有「出现方式」与「细节展开方式」两档。库只负责把设置翻译成
控件的可见性与默认开合，**不重建文档**（避免流式缓冲丢失与滚动跳变）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum, nonmember
from typing import Optional

from .message import _as_choice


class ElaChatDetailPlacementType(StrEnum):
    """分区出现方式。"""

    #: 不显示（工具仍留在数据 / 导出里，只是不占视线）
    Hidden = "hidden"
    #: 显示但默认收起
    Collapsed = "collapsed"
    #: 显示并默认展开
    Expanded = "expanded"

    #: 全部合法值（非枚举成员）
    All = nonmember((Hidden, Collapsed, Expanded))


class ElaChatDetailDepthType(StrEnum):
    """分区细节的默认展开方式。"""

    #: 默认收起
    Collapsed = "collapsed"
    #: 默认展开
    Expanded = "expanded"

    #: 全部合法值（非枚举成员）
    All = nonmember((Collapsed, Expanded))


@dataclass(frozen=True)
class ElaChatDetailSection:
    """一个分区的时间线密度设置。"""

    #: 出现方式（见 :class:`ElaChatDetailPlacementType`）
    placement: str = ElaChatDetailPlacementType.Collapsed
    #: 细节展开方式（见 :class:`ElaChatDetailDepthType`）
    details: str = ElaChatDetailDepthType.Collapsed

    def __post_init__(self) -> None:
        if self.placement not in ElaChatDetailPlacementType.All:
            raise ValueError(
                f"ElaChatDetailSection: placement 非法（{self.placement!r}），"
                "应为 hidden / collapsed / expanded"
            )
        if self.details not in ElaChatDetailDepthType.All:
            raise ValueError(
                f"ElaChatDetailSection: details 非法（{self.details!r}），"
                "应为 collapsed / expanded"
            )

    @property
    def hidden(self) -> bool:
        """是否隐藏整个分区。"""
        return self.placement == ElaChatDetailPlacementType.Hidden

    @property
    def expanded(self) -> bool:
        """是否默认展开（细节或整体）。"""
        return self.placement == ElaChatDetailPlacementType.Expanded or (
            self.details == ElaChatDetailDepthType.Expanded
        )

    def toDict(self) -> dict:
        """转为纯 JSON 字典。"""
        return {"placement": self.placement, "details": self.details}

    @classmethod
    def fromDict(cls, data) -> "ElaChatDetailSection":
        """从字典还原（缺失 / 非法字段取默认值）。"""
        if not isinstance(data, dict):
            return cls()
        return cls(
            placement=_as_choice(
                data.get("placement"),
                ElaChatDetailPlacementType.All,
                ElaChatDetailPlacementType.Collapsed,
            ),
            details=_as_choice(
                data.get("details"),
                ElaChatDetailDepthType.All,
                ElaChatDetailDepthType.Collapsed,
            ),
        )


@dataclass(frozen=True)
class ElaChatTimelineDetail:
    """整条时间线的密度设置（六个分区各一份）。"""

    #: 思考段
    thinking: ElaChatDetailSection = ElaChatDetailSection()
    #: shell 类工具
    shell: ElaChatDetailSection = ElaChatDetailSection()
    #: 编辑类工具（edit / write / patch / apply_patch）
    edit: ElaChatDetailSection = ElaChatDetailSection()
    #: 子代理类工具
    subagents: ElaChatDetailSection = ElaChatDetailSection()
    #: 时间线通知
    notices: ElaChatDetailSection = ElaChatDetailSection(
        placement=ElaChatDetailPlacementType.Expanded,
        details=ElaChatDetailDepthType.Expanded,
    )
    #: 其它工具的默认开合
    tools: ElaChatDetailSection = ElaChatDetailSection()

    @property
    def sections(self) -> tuple:
        """全部分区（按固定顺序，便于遍历）。"""
        return (
            ("thinking", self.thinking),
            ("shell", self.shell),
            ("edit", self.edit),
            ("subagents", self.subagents),
            ("notices", self.notices),
            ("tools", self.tools),
        )

    def section(self, name: str) -> ElaChatDetailSection:
        """按分区名取设置（未知名字抛 ``KeyError``）。"""
        for key, value in self.sections:
            if key == name:
                return value
        raise KeyError(f"ElaChatTimelineDetail: 未知分区 {name!r}")

    def withSection(self, name: str, **changes) -> "ElaChatTimelineDetail":
        """返回替换某个分区设置后的新快照。"""
        current = self.section(name)
        return replace(self, **{name: replace(current, **changes)})

    def toDict(self) -> dict:
        """转为纯 JSON 字典。"""
        return {key: value.toDict() for key, value in self.sections}

    @classmethod
    def fromDict(cls, data) -> "ElaChatTimelineDetail":
        """从字典还原（缺失 / 非法字段取默认值）。"""
        if not isinstance(data, dict):
            return cls()
        return cls(
            **{
                key: ElaChatDetailSection.fromDict(data.get(key))
                for key, _value in cls().sections
            }
        )


#: 默认密度（思考 / 工具默认收起，通知常显）
DEFAULT_TIMELINE_DETAIL = ElaChatTimelineDetail()


def coerceDetailSection(value) -> ElaChatDetailSection:
    """把 ``ElaChatDetailSection`` / 字典 / ``None`` 归一成 section。"""
    if isinstance(value, ElaChatDetailSection):
        return value
    if value is None:
        return ElaChatDetailSection()
    if isinstance(value, dict):
        return ElaChatDetailSection.fromDict(value)
    raise TypeError(
        f"时间线密度分区必须是 ElaChatDetailSection / dict / None，收到 {type(value)!r}"
    )


def coerceTimelineDetail(value: Optional[object]) -> ElaChatTimelineDetail:
    """把 ``ElaChatTimelineDetail`` / 字典 / ``None`` 归一成完整设置。"""
    if value is None:
        return DEFAULT_TIMELINE_DETAIL
    if isinstance(value, ElaChatTimelineDetail):
        return value
    if isinstance(value, dict):
        current = DEFAULT_TIMELINE_DETAIL
        sections = {}
        for key, _section in current.sections:
            if key in value:
                sections[key] = coerceDetailSection(value[key])
            else:
                sections[key] = _section
        return ElaChatTimelineDetail(**sections)
    raise TypeError(
        f"setTimelineDetail: 需要 ElaChatTimelineDetail / dict / None，收到 {type(value)!r}"
    )


__all__ = [
    "DEFAULT_TIMELINE_DETAIL",
    "ElaChatDetailDepthType",
    "ElaChatDetailPlacementType",
    "ElaChatDetailSection",
    "ElaChatTimelineDetail",
    "coerceDetailSection",
    "coerceTimelineDetail",
]
