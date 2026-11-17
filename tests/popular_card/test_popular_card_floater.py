"""ElaPopularCard 浮动层生命周期（上游 C++ 轮子回归）。"""

from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QWidget
from PyQt6ElaWidgetTools import ElaPopularCard

_FLOATER = "ElaPopularCardFloater"


def _floater_count(host: QWidget) -> int:
    return len(host.findChildren(QWidget, _FLOATER))


def _flush_deferred_delete() -> None:
    # processEvents() 不处理 DeferredDelete；必须显式冲刷才会跑 ~QObject。
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_floater_is_destroyed_with_card(qapp, make):
    host = make(QWidget)
    host.show()
    card = make(ElaPopularCard, host)
    card.setFixedSize(300, 200)
    qapp.processEvents()
    assert _floater_count(host) == 1

    card.deleteLater()
    _flush_deferred_delete()
    assert _floater_count(host) == 0


def test_card_survives_floater_deletion(qapp, make):
    host = make(QWidget)
    host.show()
    card = make(ElaPopularCard, host)
    card.setFixedSize(300, 200)
    qapp.processEvents()
    floater = host.findChild(QWidget, _FLOATER)
    assert floater is not None

    floater.deleteLater()
    _flush_deferred_delete()
    assert _floater_count(host) == 0

    # floater 先消失时，卡片析构不能拿悬空指针二次删除。
    card.deleteLater()
    _flush_deferred_delete()
    assert _floater_count(host) == 0
