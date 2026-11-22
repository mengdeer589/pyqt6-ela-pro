"""图表 option / 事件 / 查询结果模型。

``OptionModel`` 是 ``dict`` 的薄包装：键保持 ECharts 名称，Python 属性按
``snake_case`` 读写；不再为每个 option 键维护 dataclass 字段。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from . import data as _cdata


def _snake_to_camel(name: str) -> str:
    parts = str(name).split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def _to_plain(value):
    if isinstance(value, (_cdata.ElaNumericBuffer, _cdata.DataRing)):
        return value.toList()
    if isinstance(value, OptionModel):
        return value.to_dict()
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if isinstance(value, tuple):
        return [_to_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_plain(v) for k, v in value.items()}
    return value


class OptionModel(dict):
    """dict 兼容的 option 容器：任意键 + ``snake_case`` 属性访问。"""

    #: 少数非 ECharts camelCase 的公开键（如 ``ChartTheme.palette_dark``）。
    _ALIASES: dict[str, str] = {}
    #: 事件 / action 载荷的默认键（ECharts 名称）。
    _DEFAULTS: dict[str, Any] = {}

    def __init__(self, *args, **kwargs) -> None:
        dict.__init__(self)
        if args:
            self.update(*args)
        for key, value in self._DEFAULTS.items():
            self.setdefault(key, copy.copy(value))
        for key, value in kwargs.items():
            self[_snake_to_camel(key)] = value

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        key = self._ALIASES.get(name, name)
        if key in self:
            return dict.__getitem__(self, key)
        camel = _snake_to_camel(name)
        if camel in self:
            return dict.__getitem__(self, camel)
        return None

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        dict.__setitem__(self, self._ALIASES.get(name, _snake_to_camel(name)), value)

    def __delattr__(self, name: str) -> None:
        if name.startswith("_"):
            object.__delattr__(self, name)
            return
        self.pop(self._ALIASES.get(name, _snake_to_camel(name)), None)

    def to_dict(self) -> dict:
        """递归转普通 dict（ECharts 键名）。"""
        return {key: _to_plain(value) for key, value in self.items()}

    def as_dict(self) -> dict:
        return self.to_dict()

    def copy(self):  # type: ignore[override]
        return type(self).from_dict(self)

    @classmethod
    def from_dict(cls, data=None, **overrides):
        if isinstance(data, cls):
            obj = cls()
            for key, value in data.items():
                obj[key] = value
        else:
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise TypeError(
                    f"{cls.__name__}.from_dict 需要 dict，收到 {type(data).__name__}"
                )
            obj = cls()
            for key, value in data.items():
                obj[key] = value
        for key, value in overrides.items():
            setattr(obj, key, value)
        return obj


class ChartOption(OptionModel):
    """图表顶层 option；``series`` / 轴按下标或对象保持薄模型。"""

    @classmethod
    def from_dict(cls, data=None, **overrides):
        obj = super().from_dict(data, **overrides)
        series = obj.get("series")
        if isinstance(series, (list, tuple)):
            obj["series"] = [
                item
                if isinstance(item, SeriesOption)
                else (SeriesOption.from_dict(item) if isinstance(item, dict) else item)
                for item in series
            ]
        for key in ("xAxis", "yAxis", "singleAxis"):
            value = obj.get(key)
            if isinstance(value, (list, tuple)):
                obj[key] = [
                    item
                    if isinstance(item, AxisOption)
                    else (AxisOption.from_dict(item) if isinstance(item, dict) else item)
                    for item in value
                ]
            elif isinstance(value, dict):
                obj[key] = (
                    value if isinstance(value, AxisOption) else AxisOption.from_dict(value)
                )
        return obj


class SeriesOption(OptionModel):
    """系列 option；嵌套样式保持普通 dict，大数组不动。"""


class AxisOption(OptionModel):
    """坐标轴 option。"""


class ActionPayload(OptionModel):
    _DEFAULTS = {
        "type": "",
        "seriesName": None,
        "seriesIndex": None,
        "seriesId": None,
        "dataIndex": None,
        "name": None,
        "start": None,
        "end": None,
        "startValue": None,
        "endValue": None,
    }


class ChartEvent(OptionModel):
    _DEFAULTS = {
        "type": "",
        "componentType": "series",
        "seriesType": "",
        "seriesIndex": -1,
        "seriesName": "",
        "name": "",
        "dataIndex": None,
        "data": None,
        "value": None,
        "color": None,
        "offsetX": 0.0,
        "offsetY": 0.0,
        "event": None,
    }

    def __eq__(self, other):
        if isinstance(other, ChartEvent):
            return dict.__eq__(self, other)
        if isinstance(other, dict):
            # 兼容既有测试 / 宿主：只比较对方提供的键。
            return all(
                key in self and dict.__getitem__(self, key) == value
                for key, value in other.items()
            )
        return NotImplemented

    __hash__ = None


def event_from_dict(name: str, params=None) -> ChartEvent:
    if isinstance(params, ChartEvent):
        if not params.type:
            params.type = name
        return params
    payload = dict(params or {})
    payload.setdefault("type", name)
    return ChartEvent.from_dict(payload)


@dataclass(frozen=True)
class OptionIssue:
    path: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class SeriesItem:
    series_name: str
    series_index: int
    data_index: int
    name: str
    value: Any
    color: Any = None
    pos: Any = None
    rect: Any = None


@dataclass(frozen=True)
class LabelHit:
    data_index: int
    rect: Any
    text: str


@dataclass(frozen=True)
class HitResult:
    series_name: str
    series_index: int
    data_index: Any
    item: Any


class ChartTheme(OptionModel):
    """图表配色主题定义（属性访问 + dict 下标兼容）。"""

    _ALIASES = {"palette_dark": "palette_dark"}
    _DEFAULTS = {
        "name": "",
        "palette": [],
        "palette_dark": [],
        "light": {},
        "dark": {},
    }

    def __init__(
        self,
        name: str = "",
        palette=None,
        palette_dark=None,
        light=None,
        dark=None,
        **kwargs,
    ) -> None:
        super().__init__()
        self.name = name
        self.palette = list(palette or [])
        self.palette_dark = list(palette_dark or [])
        self.light = dict(light or {})
        self.dark = dict(dark or {})
        for key, value in kwargs.items():
            self[key] = value


__all__ = [
    "ActionPayload",
    "AxisOption",
    "ChartEvent",
    "ChartOption",
    "ChartTheme",
    "HitResult",
    "LabelHit",
    "OptionIssue",
    "OptionModel",
    "SeriesItem",
    "SeriesOption",
    "event_from_dict",
]
