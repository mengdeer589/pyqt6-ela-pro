"""ECharts 风格 option：合并、拷贝、紧凑数据归一化（纯函数，无 Qt 依赖）。"""

from __future__ import annotations

import copy

from . import data as _cdata


def _hold_value(v):
    """合并 / 存入 option 时的取值策略：大数组按引用，其余深拷贝。

    按引用持有意味着调用方在 ``setOption`` 之后不得原地修改该数组。
    """
    if _cdata.isBufferLike(v):
        return v
    return copy.deepcopy(v)


def _deep_merge(dst: dict, src: dict) -> dict:
    """递归合并 src 到 dst（dict 深合并，list / 标量整体替换），返回 dst。"""
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = _hold_value(v)
    return dst


#: setOption 合并时按组件数组「逐项合并」的顶层键；``visualMap`` 天生是
#: 数组语义（多个色带各绑一个系列），整体替换会丢掉其余色带。
_MERGE_ARRAY_KEYS = frozenset({"series", "dataZoom", "graphic", "visualMap"})
#: 坐标轴数组：只按下标逐项合并（轴的 ``name`` 是轴名不是身份，
#: 按 name 匹配会把「给第 2 条轴改名」合并到同名的第 1 条上）。
_AXIS_ARRAY_KEYS = frozenset({"xAxis", "yAxis", "singleAxis"})


def _match_option_index(new_item, old_list: list, index: int) -> int:
    """组件 / 系列数组项匹配（ECharts 语义）：``id`` → ``name`` → 序号。

    显式给了 ``id`` 且没匹配上时必须返回 -1，不能回退到序号 —— 否则会
    静默覆盖旧系列（ECharts ``mappingByIndex``：带 id 的新项只能填洞或追加）。
    """
    if isinstance(new_item, dict):
        new_id = new_item.get("id")
        if new_id is not None:
            for i, old in enumerate(old_list):
                if isinstance(old, dict) and old.get("id") == new_id:
                    return i
            # 显式 id 未命中 -> 只能新增，绝不按序号覆盖别人
            return -1
        new_name = new_item.get("name")
        if new_name:
            for i, old in enumerate(old_list):
                if isinstance(old, dict) and old.get("name") == new_name:
                    return i
    # 序号回退只认 dict 旧项：``None`` / 数字是空洞，否则
    # ``_deep_merge(None, ...)`` 抛 TypeError（JSON 里的 null 可达）。
    if 0 <= index < len(old_list) and isinstance(old_list[index], dict):
        return index
    return -1


def _merge_option_array(old_list: list, new_list: list) -> list:
    """ECharts 风格组件数组合并（``series`` / ``dataZoom`` / ``graphic``）。

    新项按 ``id`` → ``name`` → 序号匹配旧项并深合并，未匹配的追加；旧项保留
    （合并模式下传空数组不删项，需 ``notMerge=True`` 或 ``clear()``）。
    """
    old_list = list(old_list or [])
    new_list = list(new_list or [])
    if any(not isinstance(item, dict) for item in new_list):
        # 标量数组无法逐项合并 → 整体替换（逐项按引用持有，见 ``_hold_value``）。
        return [_hold_value(i) for i in new_list]
    # 旧项按引用复用、匹配项就地合并：``old_list`` 就是 ``_option`` 的内部
    # 列表（首次写入已深拷贝），而 ``[x, y]`` 结构化数据不走 ElaNumericBuffer，
    # 每拷一次就是百万级对象复制。
    result = list(old_list)
    used = set()
    for i, new_item in enumerate(new_list):
        idx = _match_option_index(new_item, old_list, i)
        if idx >= 0 and idx not in used:
            merged = old_list[idx]
            _deep_merge(merged, new_item)
            result[idx] = _normalize_series_entry(merged)
            used.add(idx)
        elif i < len(result) and not isinstance(result[i], dict) and i not in used:
            # 旧项是 ``None`` / 数字（JSON 的 null）：填洞而不是追加，
            # 否则 ``series`` 里会多出一个被丢弃的空位。
            result[i] = _copy_series_entry(new_item)
            used.add(i)
        else:
            result.append(_copy_series_entry(new_item))
    return result


def _axis_option_list(value) -> list:
    """坐标轴 option → list（单 dict 与数组两种写法）。"""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _merge_axis_option(old, new):
    """坐标轴合并：单对象与数组互相等价，一律按下标逐项合并。

    单对象 = 「只给第 0 条」；只认 list → list 会把多轴塌成一条。返回形状
    跟旧值（dict 回 dict、数组回数组），``getOption()`` 形状不漂移。
    """
    old_is_list = isinstance(old, (list, tuple))
    result = [_hold_value(item) for item in _axis_option_list(old)]
    for index, new_item in enumerate(_axis_option_list(new)):
        if not isinstance(new_item, dict):
            if index < len(result):
                result[index] = _hold_value(new_item)
            else:
                result.append(_hold_value(new_item))
            continue
        if index < len(result) and isinstance(result[index], dict):
            _deep_merge(result[index], new_item)
        else:
            result.append(_hold_value(new_item))
    if not old_is_list and len(result) == 1:
        return result[0]
    return result


def _int_attr(obj, name: str) -> int:
    """安全取整型属性；缺失 / 非法一律 0（诊断接口不因缺字段而抛异常）。"""
    try:
        return int(getattr(obj, name, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


#: 各系列渲染器存放「几何图元」的属性名（取最大长度者）：折线 ``_points``、
#: bar ``_bars``、scatter ``_dots``、pie ``_sectors``……
_SERIES_GEOM_ATTRS = (
    "_points",
    "_bars",
    "_dots",
    "_sectors",
    "_cells",
    "_boxes",
    "_lines",
    "_nodes",
    "_links",
    "_tiles",
    "_rings",
)


def _series_type_name(r) -> str:
    """系列类型名（取 option 的 ``type``，回退到类名去后缀）。"""
    t = (
        getattr(r, "opt", {}).get("type")
        if isinstance(getattr(r, "opt", None), dict)
        else None
    )
    if t:
        return str(t)
    return type(r).__name__.replace("SeriesRenderer", "")


def _series_data_len(r) -> int:
    """系列数据量：优先折线的 ``_data_len``（stack 叠加后也正确），
    其余回退 ``data()`` 长度 —— 几何属性只反映采样后的绘制规模。
    """
    n = _int_attr(r, "_data_len")
    if n:
        return n
    data = r.data() if hasattr(r, "data") else []
    try:
        return len(data)
    except TypeError:
        return 0


def _series_geom_len(r) -> int:
    """系列实际绘制的几何元素数（折线点 / 柱 / 散点…… 各不相同）。"""
    best = 0
    for name in _SERIES_GEOM_ATTRS:
        try:
            value = getattr(r, name, None)
            best = max(best, len(value) if value is not None else 0)
        except TypeError:
            continue
    return best


def _animation_enabled(cur_option: dict, new_option: dict) -> bool:
    """本次 setOption 是否可能用到过渡动画数据（旧数据快照）。

    任一侧 ``animation`` 不是显式 False 就认为可能要用 —— 宁可多算一次快照。
    """
    for opt in (cur_option, new_option):
        if isinstance(opt, dict) and opt.get("animation", True) is False:
            return False
    return True


def _snapshot_series_data(r):
    """取系列旧数据用于插值：大数组按引用，其余物化成 list。

    快照只用于「上一帧画过什么」，``_rebuild`` 之后即被弃用。
    """
    d = r.data()
    if _cdata.isBufferLike(d):
        return d
    return list(d)


def _normalize_series_entry(entry):
    """把 series 项**直接**的 ``data`` 大数值数组包成紧凑存储（就地）。

    只认 series 自己的 ``data``（不碰 ``xAxis.data`` 等按 list 语义读取的
    键），也不递归；``toBuffer`` 对结构型数据返回 None，故语义零变化。
    """
    if not isinstance(entry, dict):
        return entry
    buf = _cdata.toBuffer(entry.get("data"))
    if buf is not None:
        entry["data"] = buf
    return entry


def _copy_option_shallow_arrays(option: dict) -> dict:
    """``notMerge`` 全量替换用的拷贝：大数组按引用，其余深拷贝。

    ``self._option`` 与调用方传入的 dict 不共享可变结构，只有只读的大数组共享。
    """
    if not isinstance(option, dict):
        return {}
    out = {}
    for key, value in option.items():
        if key == "series" and isinstance(value, list):
            out[key] = [_copy_series_entry(series) for series in value]
        else:
            out[key] = _hold_value(value)
    return out


def _copy_series_entry(s):
    """单个 series 项的拷贝：大 ``data`` 按引用，其余深拷贝。"""
    if not isinstance(s, dict):
        return _hold_value(s)
    return _normalize_series_entry({k: _hold_value(v) for k, v in s.items()})


def _copy_any(v):
    """递归拷贝：大数组按引用，其余深拷贝（供 getOption 使用）。"""
    if _cdata.isBufferLike(v):
        return v
    if isinstance(v, dict):
        return {k: _copy_any(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_copy_any(x) for x in v]
    return copy.deepcopy(v)


def _unwrap_option(option):
    """把 option 树中的紧凑存储还原为普通 list（``getOption`` 对外出口）。"""
    if isinstance(option, dict):
        return {k: _unwrap_option(v) for k, v in option.items()}
    if isinstance(option, list):
        return [_unwrap_option(v) for v in option]
    return _cdata.unwrapData(option)


def _merge_option(dst: dict, src: dict) -> dict:
    """ECharts 风格 option 合并：dict 深合并 / 组件数组逐项合并 / 其余整体替换。"""
    for k, v in (src or {}).items():
        if (
            k in _MERGE_ARRAY_KEYS
            and isinstance(v, list)
            and isinstance(dst.get(k), list)
        ):
            dst[k] = _merge_option_array(dst[k], v)
        elif k in _AXIS_ARRAY_KEYS and isinstance(v, (dict, list)):
            dst[k] = _merge_axis_option(dst.get(k), v)
        elif k == "series" and isinstance(v, list):
            # series 首次出现：逐项拷贝并包装大数组，别把首次注入的数据深拷贝一遍。
            dst[k] = [_copy_series_entry(s) for s in v]
        elif isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge_option(dst[k], v)
        else:
            dst[k] = _hold_value(v)
    return dst
