"""蓝图注册表测试（ElaNodeRegistry / register_node_type / 引脚配色）。"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro.blueprint import (
    PIN_COLORS,
    ElaNodeSpec,
    pin_color,
    register_node_type,
    register_pin_type,
)


def _spec(name="test_node", category="测试", inputs=(), outputs=(), description=""):
    return ElaNodeSpec(
        name,
        f"标题-{name}",
        category,
        inputs=list(inputs),
        outputs=list(outputs),
        description=description,
    )


class TestRegister:
    def test_register_and_spec(self, clean_registry):
        clean_registry.register(_spec("a"))
        assert clean_registry.spec("a") is not None
        assert clean_registry.spec("a").type_name == "a"

    def test_empty_type_name_raises(self, clean_registry):
        with pytest.raises(ValueError):
            clean_registry.register(_spec(""))

    def test_override_same_definition_idempotent(self, clean_registry):
        clean_registry.register(_spec("a", inputs=[{"id": "x"}]))
        clean_registry.register(_spec("a", inputs=[{"id": "x"}]))
        assert len(clean_registry.specs()) == 1

    def test_override_different_definition_warns(self, clean_registry, caplog):
        clean_registry.register(_spec("a", inputs=[{"id": "x"}]))
        with caplog.at_level("WARNING"):
            clean_registry.register(_spec("a", inputs=[{"id": "y"}]))
        assert any("重复注册" in r.message for r in caplog.records)

    def test_unregister(self, clean_registry):
        clean_registry.register(_spec("a"))
        assert clean_registry.unregister("a")
        assert not clean_registry.unregister("a")


class TestOwnerNamespace:
    def test_owner_isolates_same_name(self, clean_registry):
        clean_registry.register(
            _spec("load", outputs=[{"id": "img", "data_type": "image"}]),
            owner="plugin_a",
        )
        clean_registry.register(
            _spec("load", outputs=[{"id": "mat", "data_type": "tensor"}]),
            owner="plugin_b",
        )
        assert (
            clean_registry.spec("load", owner="plugin_a").outputs[0]["data_type"]
            == "image"
        )
        assert (
            clean_registry.spec("load", owner="plugin_b").outputs[0]["data_type"]
            == "tensor"
        )

    def test_scoped_query_includes_global(self, clean_registry):
        clean_registry.register(_spec("g1"), owner=None)
        clean_registry.register(_spec("p1"), owner="plug")
        assert clean_registry.spec("g1", owner="plug") is not None
        assert clean_registry.spec("p1", owner="plug") is not None

    def test_unregister_with_owner_does_not_touch_global(self, clean_registry):
        """带 owner 注销不得退到全局那条（否则插件能删掉别人的全局类型）。"""
        clean_registry.register(_spec("shared"), owner=None)
        clean_registry.register(_spec("shared"), owner="plugin_a")

        assert clean_registry.unregister("shared", owner="plugin_a") is True
        assert clean_registry.spec("shared", owner=None) is not None, (
            "全局定义被误删"
        )
        assert clean_registry.unregister("shared", owner="plugin_a") is False

    def test_unregister_global_needs_no_owner(self, clean_registry):
        clean_registry.register(_spec("only_global"), owner=None)
        assert clean_registry.unregister("only_global") is True
        assert clean_registry.spec("only_global") is None


class TestQuery:
    def test_categories_order_unique(self, clean_registry):
        clean_registry.register(_spec("a", category="流程"))
        clean_registry.register(_spec("b", category="处理"))
        clean_registry.register(_spec("c", category="流程"))
        assert clean_registry.categories() == ["流程", "处理"]

    def test_search_matches_title_and_description(self, clean_registry):
        clean_registry.register(_spec("resize", description="调整图像尺寸"))
        clean_registry.register(_spec("blur", description="高斯模糊"))
        names = [s.type_name for s in clean_registry.search("尺寸")]
        assert names == ["resize"]

    def test_search_empty_returns_all(self, clean_registry):
        clean_registry.register(_spec("a"))
        clean_registry.register(_spec("b"))
        assert len(clean_registry.search("")) == 2

    def test_specs_by_category(self, clean_registry):
        clean_registry.register(_spec("a", category="流程"))
        clean_registry.register(_spec("b", category="处理"))
        assert [s.type_name for s in clean_registry.specs(category="处理")] == ["b"]


class TestCreate:
    def test_create_builds_pins(self, clean_registry):
        clean_registry.register(
            _spec(
                "proc",
                inputs=[
                    {"id": "in", "name": "进入", "data_type": "exec", "multi": True}
                ],
                outputs=[{"id": "out", "data_type": "image"}],
            )
        )
        node = clean_registry.create("proc")
        assert node.type_name == "proc"
        assert node.inputs[0].id == "in" and node.inputs[0].multi
        assert node.outputs[0].data_type == "image"

    def test_create_unknown_type_raises(self, clean_registry):
        with pytest.raises(KeyError):
            clean_registry.create("不存在")

    def test_create_with_owner(self, clean_registry):
        clean_registry.register(_spec("t"), owner="plug")
        node = clean_registry.create("t", owner="plug")
        assert node is not None


class TestPinColors:
    def test_pin_color_known_and_fallback(self):
        # exec 为固定 hex；未知类型回退 any（令牌键，主题解析为 hex 字符串）
        assert pin_color("exec").startswith("#")
        assert pin_color("不存在的类型").startswith("#")

    def test_register_pin_type(self):
        register_pin_type("audio", "#E0A030")
        # 登记表里存原样（宿主读自己的值），但 **pin_color 一律归一成小写
        # hex** —— 与令牌路径（``T()`` -> ``QColor.name()``）的输出统一，
        # 上游按字符串比色时才不会被大小写咬到。
        assert PIN_COLORS["audio"] == "#E0A030"
        assert pin_color("audio") == "#e0a030"

    def test_register_pin_type_rejects_bad_color(self):
        with pytest.raises(ValueError):
            register_pin_type("bad", "totally-unknown-token")
        assert "bad" not in PIN_COLORS

    def test_pin_color_token_key_resolves(self):
        register_pin_type("mask", "danger")
        assert pin_color("mask").startswith("#")


class TestRegisterNodeType:
    def test_convenience_function(self, clean_registry):
        spec = register_node_type(
            "便利",
            "便利节点",
            "工具",
            inputs=[{"id": "x", "data_type": "int"}],
            description="便捷注册",
        )
        assert spec.type_name == "便利"
        assert clean_registry.spec("便利") is spec
