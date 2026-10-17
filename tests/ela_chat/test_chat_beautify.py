"""Editorial Agent 外观测试：头部状态点 / 圆形头像 / 气泡逐角圆角。"""

from __future__ import annotations

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from _pixels import skip_if_no_pixels

from pyqt6_ela_pro.chat import (
    ElaChatBubble,
    ElaChatRoleType,
    ElaChatStats,
    ElaChatStatusType,
)


def _bubble_in_window(qapp, make, bubble: ElaChatBubble):
    host = make(QWidget)
    host.resize(480, 420)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.addWidget(bubble)
    layout.addStretch(1)
    host.show()
    for _ in range(10):
        qapp.processEvents()
    return host


def _grab(widget):
    for _ in range(5):
        widget.repaint()
    image = widget.grab().toImage()
    colors = {
        image.pixelColor(x, y).name()
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 200
    }
    skip_if_no_pixels(colors, "气泡 / 头像形状像素")
    return image


class TestStatsLine:
    def test_single_line_no_wrap(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        _bubble_in_window(qapp, make, bubble)
        bubble.setStepStats(
            ElaChatStats(prompt_tokens=15721, completion_tokens=1069, total_tokens=6790)
        )
        badge = bubble.statsBadge()
        assert badge._label.wordWrap() is False
        assert "\n" not in badge._label.text()
        assert "↑15721" in badge._label.text()
        assert "↓1069" in badge._label.text()
        assert "总计 6790" in badge._label.text()


class TestHeaderStatus:
    def test_streaming_dot_breathing_then_hidden(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        _bubble_in_window(qapp, make, bubble)
        bubble.beginStream()
        dot = bubble.header().statusDot()
        # 阶段一：排队中（等待 TTFT），呼吸点同样激活
        assert dot.isVisible()
        assert dot.isActive() is True
        assert bubble.header().statusKind() == ElaChatStatusType.Queued
        bubble.appendText("第一片")
        # 阶段二：生成中
        assert dot.isActive() is True
        assert bubble.header().statusKind() == ElaChatStatusType.Streaming

        bubble.endStream()
        assert dot.isActive() is False
        assert dot.isVisible() is False  # Done 无状态文本

    def test_error_dot_static_and_colored(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        _bubble_in_window(qapp, make, bubble)
        bubble.setError("接口超时")
        dot = bubble.header().statusDot()
        assert dot.isVisible()
        assert dot.isActive() is False
        assert bubble.header().statusKind() == ElaChatStatusType.Error
        assert dot._color.name() == bubble.header()._status_color().name()


class TestShapes:
    def test_avatar_default_circle(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        _bubble_in_window(qapp, make, bubble)
        avatar = bubble.header().avatar()
        assert avatar.shape() == "circle"
        bg = avatar._bg.name()
        image = _grab(avatar)
        # 圆外：角点与左肩 (5, 2)（圆角方形时 (5, 2) 已是填充）
        assert image.pixelColor(1, 1).name() != bg
        assert image.pixelColor(5, 2).name() != bg
        # 顶部中段 / 左侧中段在圆内 → 头像底色
        assert image.pixelColor(avatar.width() // 2, 2).name() == bg
        assert image.pixelColor(2, avatar.height() // 2).name() == bg

    def test_avatar_shape_switch(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.Assistant)
        _bubble_in_window(qapp, make, bubble)
        avatar = bubble.header().avatar()
        bg = avatar._bg.name()

        # 圆角方形：左肩 (5, 2) 进入 8px 圆角内，角点仍在弧外
        bubble.setAvatarShape("rounded")
        assert bubble.avatarShape() == "rounded"
        assert avatar.shape() == "rounded"
        image = _grab(avatar)
        assert image.pixelColor(5, 2).name() == bg
        assert image.pixelColor(1, 1).name() != bg

        # 直角方形：连角点都是填充
        bubble.setAvatarShape("square")
        image = _grab(avatar)
        assert image.pixelColor(1, 1).name() == bg
        assert image.pixelColor(5, 2).name() == bg

        # 非法值回落默认圆形
        bubble.setAvatarShape("triangle")
        assert bubble.avatarShape() == "circle"
        assert avatar.shape() == "circle"

    def test_user_bubble_asymmetric_corners(self, qapp, make):
        bubble = make(ElaChatBubble, ElaChatRoleType.User, "你好，给我一个很长的回答")
        _bubble_in_window(qapp, make, bubble)
        body = bubble._body
        image = _grab(body)
        width, height = image.width(), image.height()
        bg = body._bg.name()
        # 左上 12px 大圆角 / 右下 4px 小角 → 角上露出宿主底色（不取样文字区域）
        assert image.pixelColor(1, 1).name() != bg
        assert image.pixelColor(width - 1, height - 1).name() != bg
        # 左右直边中段为气泡底色
        assert image.pixelColor(2, height // 2).name() == bg
        assert image.pixelColor(width - 2, height // 2).name() == bg
