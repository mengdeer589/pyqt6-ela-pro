"""后台任务暴露的本地服务（端口 → URL 注册表）。

沙箱是**进程级**的，不是网络命名空间：后台任务监听的 127.0.0.1 端口
宿主本来就能直接访问。所以这里不需要真正的端口转发，只需要：

- 登记 ``task_id -> port``；
- 给 UI 一个可点的 URL；
- 任务结束时自动失效。
"""

from __future__ import annotations

import socket
import time
import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Service:
    task_id: str
    port: int
    name: str = ""
    host: str = "127.0.0.1"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created_at: float = field(default_factory=time.time)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"


def port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    """探测服务是否已监听；用于「启动后等端口就绪」。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
