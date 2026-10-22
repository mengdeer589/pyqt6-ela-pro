"""非有限浮点（NaN / inf）不得击穿容错契约。

``OverflowError`` 既不是 ``TypeError`` 也不是 ``ValueError`` 的子类，而
``int(float('inf'))`` 抛的正是它。凡是「把外部数据转成整数」的地方漏掉它，一个
``inf`` 词元计数就会穿透 ``fromDict`` / journal 重放 —— 而这两处的成文契约都是
「一律容错」。

这里同时钉住 ``_as_int`` / ``_as_float`` / ``journal._int`` / ``journal._float``
四个孪生助手，以及 ``_json.loads`` 在**两个后端**下对非有限字面量的一致拒绝。
"""

from __future__ import annotations

import json

import pytest

from pyqt6_ela_pro.chat import _json
from pyqt6_ela_pro.chat.journal import (
    ElaChatTurnJournal,
    _float as journal_float,
    _int as journal_int,
)
from pyqt6_ela_pro.chat.message import (
    _as_float,
    _as_int,
    ElaChatMessage,
    ElaChatPart,
    ElaChatStats,
)

_NON_FINITE = [float("inf"), float("-inf"), float("nan"), "inf", "-Infinity", "nan"]


class TestIntCoercion:
    """``int(...)`` 系助手：inf 必须归默认值，不是抛异常。"""

    @pytest.mark.parametrize("value", _NON_FINITE, ids=repr)
    def test_as_int_non_finite_returns_default(self, value):
        # 回归：曾抛 OverflowError: cannot convert float infinity to integer
        assert _as_int(value) == 0
        assert _as_int(value, 7) == 7

    @pytest.mark.parametrize("value", _NON_FINITE, ids=repr)
    def test_journal_int_non_finite_returns_default(self, value):
        assert journal_int(value) == 0
        assert journal_int(value, 7) == 7

    def test_normal_values_still_work(self):
        assert _as_int(12) == 12
        assert _as_int("12") == 12
        assert _as_int("12.7") == 12  # 字符串小数截断
        assert _as_int(12.9) == 12
        assert _as_int(-3) == -3
        assert journal_int("42") == 42

    def test_bool_is_not_an_int(self):
        # bool 是 int 的子类，但语义上必须当「缺省」
        assert _as_int(True, 5) == 5
        assert journal_int(False, 5) == 5

    @pytest.mark.parametrize(
        "value", [None, object(), [], {}], ids=["none", "object", "list", "dict"]
    )
    def test_junk_returns_default(self, value):
        assert _as_int(value, 3) == 3
        assert journal_int(value, 3) == 3


class TestFloatCoercion:
    @pytest.mark.parametrize("value", _NON_FINITE, ids=repr)
    def test_non_finite_returns_default(self, value):
        assert _as_float(value) == 0.0
        assert journal_float(value) == 0.0

    def test_normal_values_still_work(self):
        assert _as_float(1.5) == pytest.approx(1.5)
        assert _as_float("2.5") == pytest.approx(2.5)
        assert journal_float("0.5") == pytest.approx(0.5)


class TestFromDictIsTotal:
    """``fromDict`` 的契约是「一律容错」—— 任何输入都不能抛。"""

    @pytest.mark.parametrize(
        "bad", [float("inf"), float("-inf"), float("nan")], ids=repr
    )
    def test_stats_from_dict(self, bad):
        stats = ElaChatStats.fromDict(
            {"prompt_tokens": bad, "completion_tokens": 5, "total_tokens": 5}
        )
        assert stats is not None
        assert stats.prompt_tokens == 0
        assert stats.completion_tokens == 5

    @pytest.mark.parametrize("bad", [float("inf"), float("nan")], ids=repr)
    def test_part_from_dict(self, bad):
        part = ElaChatPart.fromDict(
            {"id": "p1", "kind": "text", "text": "hi", "stats": {"prompt_tokens": bad}}
        )
        assert part is not None
        assert part.stats.prompt_tokens == 0

    @pytest.mark.parametrize("bad", [float("inf"), float("nan")], ids=repr)
    def test_message_from_dict(self, bad):
        message = ElaChatMessage.fromDict(
            {
                "id": 1,
                "role": "assistant",
                "parts": [
                    {
                        "id": "p1",
                        "kind": "text",
                        "text": "hi",
                        "stats": {"prompt_tokens": bad},
                    }
                ],
            }
        )
        assert message.parts[0].stats.prompt_tokens == 0

    def test_message_from_dict_survives_a_round_trip_with_infinity(self):
        """模拟「宿主用标准库 json 解析出一个 inf」的落库路径。"""
        payload = json.loads('{"id":1,"role":"assistant","duration_ms":1e999}')
        message = ElaChatMessage.fromDict(payload)
        assert message is not None


class TestJsonReadIsAsStrictAsWrite:
    """写入两端都拒非有限；读取也必须两端一致地拒。"""

    @pytest.mark.parametrize(
        "text",
        ['{"n": Infinity}', '{"n": -Infinity}', '{"n": NaN}'],
    )
    def test_non_finite_literal_rejected_by_both_backends(self, text, monkeypatch):
        # 先确认当前后端拒
        with pytest.raises(Exception):
            _json.loads(text)
        # 再切到标准库分支，确认同样拒 —— 这正是修复前分叉的地方
        monkeypatch.setattr(_json, "_orjson", None)
        with pytest.raises(ValueError):
            _json.loads(text)

    def test_legal_json_still_parses_on_both_backends(self, monkeypatch):
        for payload in ('{"n": 1}', '{"n": 1.5}', '{"s": "x"}', '{"a": [1, 2]}'):
            assert _json.loads(payload) == json.loads(payload)
            monkeypatch.setattr(_json, "_orjson", None)
            assert _json.loads(payload) == json.loads(payload)
            monkeypatch.undo()

    def test_write_side_still_rejects(self, monkeypatch):
        with pytest.raises(ValueError):
            _json.dumps({"n": float("inf")})
        monkeypatch.setattr(_json, "_orjson", None)
        with pytest.raises(ValueError):
            _json.dumps({"n": float("inf")})


class TestJournalReplayIsTotal:
    """journal 的契约是「单条坏事件不该毁掉整条恢复链路」。"""

    def _line(self, payload: str) -> str:
        return '{"v":1,"e":"st","n":0,"step":0,"data":%s}' % payload

    @pytest.mark.parametrize(
        "payload",
        [
            '{"prompt_tokens": Infinity, "completion_tokens": 5}',
            '{"prompt_tokens": NaN, "completion_tokens": 5}',
            '{"prompt_tokens": 1e999, "completion_tokens": 5}',
        ],
        ids=["inf", "nan", "1e999"],
    )
    def test_bad_stats_event_does_not_break_replay(self, payload, monkeypatch):
        monkeypatch.setattr(_json, "_orjson", None)  # 标准库分支：它会接受 Infinity
        journal = ElaChatTurnJournal.fromLines([self._line(payload)])
        # 要么这条被跳过，要么被容错成 0 —— 关键是不能抛
        stats = journal.message().stats
        assert stats is None or stats.completion_tokens == 5

    def test_good_events_still_replay(self):
        journal = ElaChatTurnJournal.fromLines(
            [self._line('{"prompt_tokens": 10, "completion_tokens": 5}')]
        )
        stats = journal.message().stats
        assert stats is not None
        assert stats.prompt_tokens == 10
