"""``setResizeReflowDeferred``：连续 resize（动画 / 拖窗）期间的「钉尺寸 + 防抖重排」。

契约：
1. 连续 resize（间隔 < 60ms）→ 控件被钉住、不逐帧跟上；静止 ``delayMs`` 后放开，父布局
   按当前尺寸重排；
2. 单次 resize（间隔大）→ 不钉，尺寸立刻生效；
3. 放开时**恢复控件原有的 min/max 约束**（宿主自己设的固定尺寸不能被工具吃掉）；
4. 幂等（重复挂只有一个守卫）、可关（``on=False`` 立刻放开）；
5. 顶层窗口被忽略（尺寸归窗口管理器）并记 WARNING。

注意：**隐藏控件不派发 ``Resize`` 事件**（实测探针 0 次），所以本文件所有用例都
``show()``（真实用法也一样）。
"""

from __future__ import annotations

import logging

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from pyqt6_ela_pro import setResizeReflowDeferred

#: 钉住断言用的超长防抖：保证 burst 期间绝不释放（测试机节奏不稳）
_LONG_MS = 60000


def _page_in_host(make, qapp, host_size=(500, 400)):
    """造一个「可见的父控件 + 布局里的页面」——真实用法就是这一级控件。"""
    host = make(QWidget)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    page = make(QWidget, host)
    layout.addWidget(page)
    host.resize(*host_size)
    host.show()
    qapp.processEvents()
    return host, page


def _grow_host(host, qapp, count=6, step=2) -> None:
    """连续 resize（每步都比上一次大一点，间隔远小于 60ms 判据）。"""
    for index in range(count):
        host.resize(host.width() + step * (index + 1), host.height())
        qapp.processEvents()
        QTest.qWait(2)


def _settle(qapp) -> None:
    """等防抖到期 + 让父布局把新尺寸落地。"""
    QTest.qWait(250)
    qapp.processEvents()


class TestResizeReflowGuard:
    def test_rapid_resizes_are_pinned(self, qapp, make):
        host, page = _page_in_host(make, qapp)
        setResizeReflowDeferred(page, delayMs=_LONG_MS)

        _grow_host(host, qapp)

        assert page.width() < host.width(), "连续 resize 期间不该逐帧跟上"

    def test_release_follows_latest_size(self, qapp, make):
        host, page = _page_in_host(make, qapp)
        setResizeReflowDeferred(page, delayMs=80)

        _grow_host(host, qapp)
        assert page.width() < host.width(), "防抖未到期时应钉住"

        _settle(qapp)
        assert page.width() == host.width(), "放开后父布局应按当前尺寸重排"

    def test_single_resize_is_not_pinned(self, qapp, make):
        host, page = _page_in_host(make, qapp)
        setResizeReflowDeferred(page, delayMs=_LONG_MS)

        host.resize(700, 400)
        qapp.processEvents()

        assert page.width() == host.width(), "单次 resize 不该被钉住"

    def test_release_restores_original_limits(self, qapp, make):
        host, page = _page_in_host(make, qapp, host_size=(600, 400))
        page.setMinimumSize(100, 80)
        page.setMaximumSize(900, 700)
        qapp.processEvents()
        setResizeReflowDeferred(page, delayMs=80)

        _grow_host(host, qapp)
        _settle(qapp)

        assert (page.minimumWidth(), page.minimumHeight()) == (100, 80)
        assert (page.maximumWidth(), page.maximumHeight()) == (900, 700)

    def test_disable_releases_immediately(self, qapp, make):
        host, page = _page_in_host(make, qapp)
        setResizeReflowDeferred(page, delayMs=_LONG_MS)

        _grow_host(host, qapp)
        assert page.width() < host.width(), "防抖极长时也应处于钉住状态"

        setResizeReflowDeferred(page, on=False)
        qapp.processEvents()

        assert page.width() == host.width(), "关掉后应立刻按当前尺寸重排"

    def test_attach_is_idempotent(self, qapp, make):
        host, page = _page_in_host(make, qapp)
        setResizeReflowDeferred(page, delayMs=_LONG_MS)
        setResizeReflowDeferred(page, delayMs=_LONG_MS)

        _grow_host(host, qapp)
        assert page.width() < host.width()

        setResizeReflowDeferred(page, on=False)
        qapp.processEvents()
        assert page.width() == host.width()

    def test_window_is_ignored_with_warning(self, qapp, caplog, make):
        window = make(QWidget)  # 无父控件 = 顶层窗口
        window.resize(400, 300)
        window.show()
        qapp.processEvents()
        setResizeReflowDeferred(window, delayMs=_LONG_MS)

        with caplog.at_level(logging.WARNING):
            window.resize(460, 300)
            qapp.processEvents()

        window.hide()
        assert any("顶层窗口" in rec.message for rec in caplog.records)
        assert window.width() == 460, "窗口不应被钉住"
