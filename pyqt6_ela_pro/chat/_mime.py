"""拖放 / 粘贴的 mime 解析（chat 内共用）。

编辑框（Ctrl+V 粘贴、拖到编辑框）、输入卡片（拖到卡片 / 工具栏）、聊天组件
（拖到消息区）三处都要判「这是不是本地文件 / 图片」，判定集中在这里，避免
各写一份、各漏一种 mime。
"""

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
    """mime 里的图片（从浏览器拖图 / 其它应用的图片剪贴板）；没有返回 ``None``。

    ``QMimeData.imageData()`` 可能给 ``QPixmap``（部分平台的拖放源），统一转
    ``QImage`` 后再交给附件条。
    """
    if mime is None or not mime.hasImage():
        return None
    data = mime.imageData()
    if isinstance(data, QPixmap):
        data = data.toImage()
    if isinstance(data, QImage) and not data.isNull():
        return data
    return None
