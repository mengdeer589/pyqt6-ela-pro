"""拖放 / 粘贴的 mime 解析（chat 内共用；编辑框 / 输入卡片 / 消息区三处同一份判定）。"""

from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtGui import QImage, QPixmap


def localFiles(mime) -> list:
    """mime 里的本地文件路径列表（只保留确实存在的文件）。"""
    if mime is None or not mime.hasUrls():
        return []
    paths = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if path and os.path.isfile(path):
            paths.append(path)
    return paths


def mimeImage(mime) -> Optional[QImage]:
    """mime 里的图片（没有返回 ``None``；``QPixmap`` 统一转 ``QImage``）。"""
    if mime is None or not mime.hasImage():
        return None
    data = mime.imageData()
    if isinstance(data, QPixmap):
        data = data.toImage()
    if isinstance(data, QImage) and not data.isNull():
        return data
    return None
