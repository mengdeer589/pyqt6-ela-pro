"""
SVG 图标转换模块。

把 SVG 字符串渲染成 ``QIcon`` / ``QPixmap`` / ``QImage``，并提供一个可选的
图标包加载器（``.icons`` 文本包）。

**本模块不提供按钮。** 「带第三方 SVG 图标的按钮」是 :meth:`ElaButton.setSvgIcon`
的职责，不要在这里另起一个平行按钮类 —— 那样会拿不到 ``ElaButton`` 的
6 变体 × 16 色 × 3 尺寸、focus ring、loading 指示器与动效策略。

渲染结果按 ``(svg_data, size, color)`` 缓存，**缓存里存的是 ``QImage``**
（值类型、可跨线程），只在出参那一层做一次 ``QPixmap.fromImage``。
"""

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
    """把 SVG 数据渲染成 ``QImage``（内部公用方法，结果按参数缓存）。

    **缓存的是 ``QImage`` 而不是 ``QPixmap``**，两条理由：

    ① ``QPixmap`` 是**活对象**且缓存直接把它当返回值交出去 ——
       调用方一句 ``svg_to_pixmap(...).fill(red)`` 就把缓存里那一份改了，
       **之后所有拿到该缓存的调用方看到的都是被改过的图**（实测：
       ``#000000`` 被就地改成 ``#ff0000`` 且持续生效）。
    ② ``QPixmap`` 只能 GUI 线程用（Qt 文档明写非线程安全），而缓存是进程级
       单例；``QImage`` 则是可复制的值类型，渲染与缓存都不依赖 GUI 线程。

    ``QPixmap.fromImage()`` 只在**出参**那一层做一次，落在调用方自己的线程上。
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
    """将 SVG 数据转换为 QPixmap（**每次返回新对象**，调用方可自由 ``fill``）。

    缓存里存的是 ``QImage``，不是 ``QPixmap`` —— 后者是活对象，
    直接交出去会被调用方就地改掉，污染之后所有拿到该缓存的调用方。
    """
    return QPixmap.fromImage(_render_svg_image(svg_data, size, color))


def svg_to_image(
    svg_data: str,
    size: int = 30,
    color: Optional[str] = None,
) -> QImage:
    """将 SVG 数据转换为 QImage（**值类型**，可跨线程用）。

    需要在 GUI 线程之外渲染时用它 —— ``svg_to_pixmap`` 最后一步
    ``QPixmap.fromImage`` 要求 GUI 线程，而这一路（渲染 + 缓存）不要求。
    """
    return QImage(_render_svg_image(svg_data, size, color))


class ElaSvgIconLoader:
    """SVG 图标包加载器（``.icons`` 文本包）。

    ``.icons`` 是一行一条的文本包：``##`` 开头是注释，其余每行形如
    ``图标名////<svg .../>``。**本库不再自带图标包**（曾随包分发 3.66 MB /
    2604 个 Fluent UI 图标，那是替宿主选了一套设计语言），要用请让宿主自己
    提供：

    Example::

        loader = ElaSvgIconLoader()
        # ① 自带图标包文件（推荐：路径由宿主决定）
        loader.loadFromFile(r"D:/assets/my_icons.icons")
        # ② 或指定一个图标包目录，之后按文件名取
        loader.setPackageDirectory(r"D:/assets/icons")
        loader.loadFromPackage("my_icons.icons")

        loader.getIcon("ic_save_regular", size=24, color="#1570A5")
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
        """指定 :meth:`loadFromPackage` 查找图标包的目录。

        不设时用库自身的 ``icons/packages``（那里现在通常什么都没有）。
        **宿主应当显式设成自己的资源目录** —— 往 site-packages 里写文件既
        脆弱（pip 可能覆盖）又需要管理员权限。
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

        绘制路径（``paintEvent``）必须先问一句：图标名拼错、或图标包缺失
        （宿主还没 ``loadFromFile``）时，降级为「不画图标」而不是让
        ``getSvgData`` 的 ``KeyError`` 抛进 Qt 回调 —— 那会造成 0xC0000409
        静默进程终止。

        调用方（:meth:`ElaButton.setSvgIcon`）还应当据此 ``warnings.warn``
        一次：静默少一个图标，用户会去查图标名而不是查「图标包没加载」。
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

    **不自动加载任何图标包** —— 本库不再随包分发图标集（曾内置 3.66 MB /
    2604 个图标，替宿主选了一套设计语言，而绝大多数宿主根本不用）。
    要按名字取图标，宿主自己加载一次：

    ::

        svg_icon_loader().loadFromFile(r"D:/assets/my_icons.icons")

    未加载时 :meth:`ElaSvgIconLoader.hasIcon` 一律返回 ``False``，
    :meth:`ElaButton.setSvgIcon` 会因此只画文字并 ``warnings.warn`` 一次。
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
