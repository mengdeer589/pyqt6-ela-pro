"""JSON 编解码测试：orjson 优先 / 标准库回落，两套后端语义一致。"""

from __future__ import annotations

import json

import pytest

from pyqt6_ela_pro.chat import (
    ElaChatTurnJournal,
    _json,
    jsonBackend,
    jsonDumps,
    jsonLoads,
)


class TestBackendSelection:
    def test_backend_name_is_known(self):
        assert jsonBackend() in ("orjson", "json")

    def test_orjson_used_when_installed(self):
        pytest.importorskip("orjson")
        assert jsonBackend() == "orjson"

    def test_fallback_when_orjson_missing(self, monkeypatch):
        monkeypatch.setattr(_json, "_orjson", None)
        assert jsonBackend() == "json"
        assert jsonDumps({"a": 1, "中文": "值"}) == '{"a":1,"中文":"值"}'
        assert jsonLoads('{"a": [1, 2]}') == {"a": [1, 2]}


class TestDumps:
    def test_compact_utf8(self):
        assert jsonDumps({"b": [1, 2], "a": "中文"}) == '{"b":[1,2],"a":"中文"}'

    def test_rejects_non_finite_by_default(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError):
                jsonDumps({"x": value})
        # 嵌套（dict / list）同样要扫描到
        with pytest.raises(ValueError):
            jsonDumps([1.0, {"deep": [float("nan")]}])

    def test_allow_nan_passthrough(self):
        text = jsonDumps({"x": float("nan")}, allow_nan=True)
        if jsonBackend() == "orjson":
            assert text == '{"x":null}'  # orjson 默认把非有限浮点写成 null
        else:
            assert "NaN" in text  # 标准库保持原样（非规范 JSON）

    def test_backends_agree(self, monkeypatch):
        if _json._orjson is None:
            pytest.skip("orjson 未安装，无法对比两套后端")
        sample = {
            "a": [1, 2.5, True, None],
            "中文": {"nested": ["值", {"n": 3}]},
            7: "int-key",
        }
        via_orjson = jsonDumps(sample)
        monkeypatch.setattr(_json, "_orjson", None)
        assert jsonDumps(sample) == via_orjson
        # JSON 对象键只能是字符串：int 键经标准库 / OPT_NON_STR_KEYS 都转成 "7"
        assert jsonLoads(via_orjson) == {
            "a": [1, 2.5, True, None],
            "中文": {"nested": ["值", {"n": 3}]},
            "7": "int-key",
        }


class TestLoads:
    def test_accepts_bytes(self):
        assert jsonLoads(b'{"a":1}') == {"a": 1}

    def test_raises_on_invalid(self):
        with pytest.raises(ValueError):
            jsonLoads("{")


class TestJournalUsesCodec:
    def test_journal_dumps_compact_and_stdlib_parseable(self, qapp):

        journal = ElaChatTurnJournal(messageId=1)
        journal.begin()
        journal.beginStep()
        journal.text("中文分片")
        text = journal.dumps()
        lines = text.splitlines()
        assert len(lines) >= 2  # 每行一条事件
        # 无论走哪套后端，落库文本都必须能被标准库 json 读回
        assert '"中文分片"' in text
        assert all(json.loads(line)["e"] for line in lines)
        assert ElaChatTurnJournal.loadsLine(lines[-1]) is not None


class TestFloatExponentDifference:
    def test_backends_parse_to_same_value(self, monkeypatch):
        """浮点指数记法可能不同（1e-07 / 1e-7），但解析值必须一致。"""
        if _json._orjson is None:
            pytest.skip("orjson 未安装，无法对比两套后端")
        text_orjson = jsonDumps({"x": 1e-07})
        monkeypatch.setattr(_json, "_orjson", None)
        text_stdlib = jsonDumps({"x": 1e-07})
        assert text_orjson != text_stdlib  # 已知差异：不要拿文本做跨机器比对
        assert jsonLoads(text_orjson) == jsonLoads(text_stdlib) == {"x": 1e-07}
