"""SVG 字符串 → ``QIcon`` / ``QPixmap`` / ``QImage``，以及 ``.icons`` 包加载器。

本模块不提供按钮；带 SVG 图标的按钮用 ``ElaButton.setSvgIcon``。"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QIcon,
    QImage,
    QPainter,
    QPixmap,
)
from PyQt6.QtSvg import QSvgRenderer


@lru_cache(maxsize=256)
def _render_svg_image(svg_data: str, size: int, color: Optional[str] = None) -> QImage:
    """把 SVG 数据渲染成 ``QImage``（结果按参数缓存）。
    缓存必须是 ``QImage``：``QPixmap`` 是活对象，调用方一句 ``fill()`` 就改掉
    缓存里那一份；且 ``QPixmap`` 只能在 GUI 线程用，而缓存是进程级单例。
    """
    if color:
        svg_data = svg_data.replace("<<<COLOR_CODE>>>", color)
    renderer = QSvgRenderer(svg_data.encode("utf-8"))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    return image


def svg_to_icon(
    svg_data: str,
    size: int = 30,
    color: Optional[str] = None,
) -> QIcon:
    """将 SVG 数据转换为 QIcon。``color`` 会替换 SVG 中的 ``<<<COLOR_CODE>>>``。"""
    return QIcon(QPixmap.fromImage(_render_svg_image(svg_data, size, color)))


def svg_to_pixmap(
    svg_data: str,
    size: int = 30,
    color: Optional[str] = None,
) -> QPixmap:
    """将 SVG 数据转换为 QPixmap（每次返回新对象，调用方可自由 ``fill``）。"""
    return QPixmap.fromImage(_render_svg_image(svg_data, size, color))


def svg_to_image(
    svg_data: str,
    size: int = 30,
    color: Optional[str] = None,
) -> QImage:
    """将 SVG 数据转换为 QImage（值类型，可跨线程用）。

    ``svg_to_pixmap`` 最后一步 ``QPixmap.fromImage`` 要求 GUI 线程，这一路不要求。
    """
    return QImage(_render_svg_image(svg_data, size, color))


class ElaSvgIconLoader:
    """SVG 图标包加载器（``.icons`` 文本包）。
    ``.icons`` 一行一条：``##`` 开头是注释，其余形如 ``图标名////<svg .../>``。
    本库不带图标包，由宿主自行加载。
    """

    _instance: Optional["ElaSvgIconLoader"] = None

    def __init__(self) -> None:
        self._icons: dict[str, str] = {}
        self._default_color: Optional[str] = None
        self._package_dir: Optional[str] = None

    @classmethod
    def getInstance(cls) -> "ElaSvgIconLoader":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def setDefaultColor(self, color: str) -> None:
        """设置默认颜色"""
        self._default_color = color

    @property
    def defaultColor(self) -> Optional[str]:
        return self._default_color

    def setPackageDirectory(self, directory: str) -> None:
        """指定 :meth:`loadFromPackage` 的查找目录（缺省为库内置 ``icons/packages``）。

        宿主应显式设成自己的资源目录：向 site-packages 写文件会被 pip 覆盖且需管理员权限。
        """
        self._package_dir = directory

    def packageDirectory(self) -> Optional[str]:
        """当前图标包目录（``None`` 表示用库内置目录）。"""
        return self._package_dir

    def _getColor(self, color: Optional[str]) -> Optional[str]:
        return color if color is not None else self._default_color

    def loadFromPackage(self, package_name: str) -> None:
        """从图标包文件加载图标；缺目录先 :meth:`setPackageDirectory`。"""
        if self._package_dir:
            base = self._package_dir
        else:
            base = os.path.join(os.path.dirname(__file__), "icons", "packages")
        self.loadFromFile(os.path.join(base, package_name))

    def loadFromFile(self, path: str) -> None:
        """从 ``.icons`` 文件加载（一行一条，``##`` 为注释）。"""
        try:
            with open(path, encoding="utf-8") as file:
                for line in file.readlines():
                    if line.startswith("##"):
                        continue
                    if not line.strip():
                        continue

                    line = line.strip()
                    if "////" not in line:
                        continue

                    icon_name, icon_data = line.split("////", 1)
                    self._icons[icon_name.strip()] = icon_data
        except FileNotFoundError:
            raise FileNotFoundError(f"Icon package not found: {path}")

    def append(self, name: str, data: str) -> None:
        self._icons[name] = data

    def hasIcon(self, name: str) -> bool:
        """图标包中是否存在该图标名。
        绘制路径必须先问一句：图标名拼错或图标包未加载时应降级为不画，
        不能让 ``getSvgData`` 的 ``KeyError`` 抛进 Qt 回调（= 0xC0000409）。
        """
        return name in self._icons

    def getSvgData(self, name: str, color: Optional[str] = None) -> str:
        """取 SVG 数据（``<<<COLOR_CODE>>>`` 已替换成给定颜色）。"""
        if name not in self._icons:
            raise KeyError(f"Icon '{name}' not found")
        svg_data = self._icons[name]
        final_color = self._getColor(color)
        if final_color:
            svg_data = svg_data.replace("<<<COLOR_CODE>>>", final_color)
        return svg_data

    def getIcon(
        self,
        name: str,
        size: int = 30,
        color: Optional[str] = None,
    ) -> QIcon:
        svg_data = self.getSvgData(name, color)
        return svg_to_icon(svg_data, size)

    def getPixmap(
        self,
        name: str,
        size: int = 30,
        color: Optional[str] = None,
    ) -> QPixmap:
        svg_data = self.getSvgData(name, color)
        return svg_to_pixmap(svg_data, size)

    def getIconData(self, name: str) -> Optional[str]:
        return self._icons.get(name)

    def iconNames(self) -> list[str]:
        return list(self._icons.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._icons

    def __len__(self) -> int:
        return len(self._icons)


_svg_icon_loader: Optional[ElaSvgIconLoader] = None


def svg_icon_loader() -> ElaSvgIconLoader:
    """获取全局图标加载器实例。
    不自动加载任何图标包；未加载时 :meth:`ElaSvgIconLoader.hasIcon` 一律返回
    ``False``。
    """
    global _svg_icon_loader
    if _svg_icon_loader is None:
        _svg_icon_loader = ElaSvgIconLoader.getInstance()
    return _svg_icon_loader


__all__ = [
    "svg_to_icon",
    "svg_to_pixmap",
    "svg_to_image",
    "ElaSvgIconLoader",
    "svg_icon_loader",
]
