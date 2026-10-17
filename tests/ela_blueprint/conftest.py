"""blueprint 测试公用 fixture。"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro.blueprint import ElaNodeRegistry


@pytest.fixture(autouse=True)
def clean_registry():
    """每个测试独立的节点注册表（单例内部字典直接重置，避免跨测试污染）。

    前后各重置一次：注册表是进程级单例，只在 setup 清空的话，
    后注册的 spec 会漏到下一个用例。
    """
    reg = ElaNodeRegistry.instance()
    reg._specs = {}
    yield reg
    reg._specs = {}
