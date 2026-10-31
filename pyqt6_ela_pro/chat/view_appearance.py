"""视图外观 / 空态 / 头像 / 展示模式 setter 方法组。"""

from __future__ import annotations


from typing import Optional


from .blocks import (
    ElaChatAvatarSource,
    normalizeAvatarShape,
    toolDefaultOpen,
)

from .message import (
    ElaChatReasoningStyleType,
    ElaChatRoleType,
)


class _ViewAppearanceMixin:
    """方法组 mixin：状态由 ``ElaChatView.__init__`` 建立。"""

    def setReasoningStyle(self, style: str) -> None:
        """设置思考展示形态（``"collapse"`` / ``"inline"``），对已有消息立即生效。"""
        self._reasoning_style = (
            style
            if style in ElaChatReasoningStyleType.All
            else ElaChatReasoningStyleType.Collapse
        )
        for bubble in self._bubbles.values():
            bubble.setReasoningStyle(self._reasoning_style)

    def reasoningStyle(self) -> str:
        """获取思考展示形态。"""
        return self._reasoning_style

    def setToolGrouping(self, on: bool) -> None:
        """设置是否把连续上下文工具合并为分组卡（含已存在消息）。"""
        self._tool_grouping = bool(on)
        for bubble in self._bubbles.values():
            bubble.setToolGrouping(self._tool_grouping)

    def toolGrouping(self) -> bool:
        """是否启用上下文工具分组。"""
        return self._tool_grouping

    def setDisclaimer(self, text: str) -> None:
        """设置助手消息底部的「内容由 AI 生成」提示（含已存在消息；空串等同隐藏）。"""
        self._disclaimer_text = str(text or "")
        self._disclaimer_visible = bool(self._disclaimer_text)
        for bubble in self._bubbles.values():
            bubble.setDisclaimer(self._disclaimer_text)
            bubble.setDisclaimerVisible(self._disclaimer_visible)

    def disclaimer(self) -> str:
        """获取「内容由 AI 生成」提示文案。"""
        return self._disclaimer_text

    def setDisclaimerVisible(self, on: bool) -> None:
        """显示 / 隐藏助手消息底部的「AI 生成」提示（含已存在消息，文案保留）。"""
        self._disclaimer_visible = bool(on)
        for bubble in self._bubbles.values():
            bubble.setDisclaimerVisible(self._disclaimer_visible)

    def disclaimerVisible(self) -> bool:
        """「AI 生成」提示是否可见。"""
        return self._disclaimer_visible

    def setCopyNotificationEnabled(self, on: bool) -> None:
        """设置点击「复制」后是否弹成功提示（默认开；应用偏好，不进 bundle 视图段）。"""
        self._copy_notification_enabled = bool(on)
        for bubble in self._bubbles.values():
            bubble.setCopyNotificationEnabled(self._copy_notification_enabled)

    def copyNotificationEnabled(self) -> bool:
        """复制后是否弹成功提示。"""
        return self._copy_notification_enabled

    def setWaitingPlaceholderEnabled(self, on: bool = True) -> None:
        """设置等待首个 token 期间是否显示骨架占位（默认开）。

        骨架不是 ``ElaChatPart``，不进时间线 / 导出；属应用偏好，不进 bundle。
        """
        self._waiting_placeholder_enabled = bool(on)
        for bubble in self._bubbles.values():
            bubble.setWaitingPlaceholderEnabled(self._waiting_placeholder_enabled)

    def waitingPlaceholderEnabled(self) -> bool:
        """等待首个 token 期间是否显示骨架占位。"""
        return self._waiting_placeholder_enabled

    def setToolDefaultOpen(self, policy) -> None:
        """注入「哪些工具卡默认展开」的策略 ``policy(toolName, arguments, ok) -> bool``。

        对全部消息生效，但只影响之后新建的卡片（不弹开用户手动折叠的卡）；
        传 ``None`` 恢复库默认。
        """
        self._tool_default_open = policy if callable(policy) else toolDefaultOpen
        for bubble in self._bubbles.values():
            bubble.setToolDefaultOpen(self._tool_default_open)

    def toolDefaultOpenPolicy(self):
        """获取当前工具卡展开策略（可调用对象）。"""
        return self._tool_default_open

    def setStatsMode(self, mode: str) -> None:
        """设置用量徽标展示模式（``"footer"`` / ``"steps"`` / ``"none"``），对已有消息立即生效。"""
        self._stats_mode = mode if mode in ("footer", "steps", "none") else "footer"
        for bubble in self._bubbles.values():
            bubble.setStatsMode(self._stats_mode)

    def statsMode(self) -> str:
        """获取用量徽标展示模式。"""
        return self._stats_mode

    def setAvatarVisible(self, on: bool) -> None:
        """显示/隐藏全部头像（含后续新增消息）。"""
        self._avatar_visible = bool(on)
        for bubble in self._bubbles.values():
            bubble.setAvatarVisible(self._avatar_visible)

    def avatarVisible(self) -> bool:
        """头像是否可见。"""
        return self._avatar_visible

    def setAvatarShape(self, shape: str) -> None:
        """设置头像形状（``"circle"`` / ``"rounded"`` / ``"square"``；非法值回落默认）。"""
        self._avatar_shape = normalizeAvatarShape(shape)
        for bubble in self._bubbles.values():
            bubble.setAvatarShape(self._avatar_shape)

    def avatarShape(self) -> str:
        """获取头像形状。"""
        return self._avatar_shape

    def setUserAvatar(self, source: ElaChatAvatarSource) -> None:
        """设置用户消息头像（含已存在消息与后续消息；``None`` 回退内置图标）。"""
        self._user_avatar = source
        for bubble in self._bubbles.values():
            if bubble.role() == ElaChatRoleType.User:
                bubble.setAvatarImage(source)

    def userAvatar(self) -> Optional[ElaChatAvatarSource]:
        """获取用户头像来源（未设置返回 ``None``）。"""
        return self._user_avatar

    def setAssistantAvatar(self, source: ElaChatAvatarSource) -> None:
        """设置助手消息头像（含已存在消息与后续消息；``None`` 回退内置图标）。"""
        self._assistant_avatar = source
        for bubble in self._bubbles.values():
            if bubble.role() == ElaChatRoleType.Assistant:
                bubble.setAvatarImage(source)

    def assistantAvatar(self) -> Optional[ElaChatAvatarSource]:
        """获取助手头像来源（未设置返回 ``None``）。"""
        return self._assistant_avatar

    def setUserBubbleMaxWidth(self, ratio: float) -> None:
        """设置用户气泡最大宽度比例（含后续新增消息）。"""
        self._user_bubble_ratio = max(0.1, min(1.0, float(ratio)))
        for bubble in self._bubbles.values():
            if bubble.role() == ElaChatRoleType.User:
                bubble.setMaxWidthRatio(self._user_bubble_ratio)

    def userBubbleMaxWidth(self) -> float:
        """获取用户气泡最大宽度比例。"""
        return self._user_bubble_ratio

    def setContentMaxWidth(self, width: int) -> None:
        """设置助手消息内容最大宽度（像素，``0`` 表示不限，默认不限）。

        限的是整列（``_column`` 同时装正文、附件条与底部行），否则宽窗口下
        底部行会伸出去。
        """
        self._content_max_width = max(0, int(width))
        for bubble in self._bubbles.values():
            if bubble.role() == ElaChatRoleType.Assistant:
                bubble.setContentMaxWidth(self._content_max_width)

    def contentMaxWidth(self) -> int:
        """获取助手消息内容最大宽度（``0`` 表示不限）。"""
        return self._content_max_width

    def setEmptyTitle(self, text: str) -> None:
        """设置空态标题。"""
        self._empty.setTitle(text)

    def emptyTitle(self) -> str:
        """获取空态标题。"""
        return self._empty.title()

    def setEmptySubtitle(self, text: str) -> None:
        """设置空态副标题。"""
        self._empty.setSubtitle(text)

    def emptySubtitle(self) -> str:
        """获取空态副标题。"""
        return self._empty.subtitle()

    def setSuggestions(self, suggestions: Optional[list]) -> None:
        """设置空态建议按钮列表。"""
        self._empty.setSuggestions(suggestions)

    def suggestions(self) -> list:
        """获取空态建议列表。"""
        return self._empty.suggestions()
