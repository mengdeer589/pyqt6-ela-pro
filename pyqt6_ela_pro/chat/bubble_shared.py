"""气泡与其 mixin 共用的常量（避免宿主类与 mixin 互相 import）。"""

from .message import ElaChatStatusType

#: 用量徽标展示模式（底部整轮汇总 / 每步各自显示 / 完全不显示）
_STATS_MODES = ("footer", "steps", "none")

#: 状态对应的头部提示文本（``Queued`` 为展示态：流式开始后、首个模型输出前）
_STATUS_TEXTS = {
    ElaChatStatusType.Queued: "排队中…",
    ElaChatStatusType.Streaming: "生成中…",
    ElaChatStatusType.Stopped: "已停止",
    ElaChatStatusType.Error: "出错",
}

#: 助手流式占位文案
_STREAMING_PLACEHOLDER = "正在生成…"
