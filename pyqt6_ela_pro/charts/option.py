"""ECharts 风格 option：合并、拷贝、紧凑数据归一化。

纯函数模块（不依赖 Qt 控件 / 渲染器），供 ``core.ElaChartWidget`` 与
``appendData`` / ``getOption`` 共用。
"""

from __future__ import annotations

import copy

from . import data as _cdata


def _hold_value(v):
    """合并 / 存入 option 时的取值策略：**大数组按引用，其余深拷贝**。

    ``copy.deepcopy`` 对百万级 float list 是纯浪费（本机 100 万点约
    60~95 ms），而这些数组图表从不在内部修改它们。``ElaNumericBuffer`` /
    ndarray 一律按引用持有，其余走原有深拷贝路径。

    注意：按引用持有意味着**调用方在 setOption 之后不得原地修改该数组**
    （与 InstructionX 的口径一致，见 ``charts.data`` 模块 docstring）。
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


#: setOption 合并时按 ECharts 组件数组「逐项合并」的顶层键。
#: ``visualMap`` 也在这里 —— 它天生是数组语义（多个色带各绑一个系列），
#: 整体替换会让「只改第 1 个」静默丢掉其余色带。
_MERGE_ARRAY_KEYS = frozenset({"series", "dataZoom", "graphic", "visualMap"})
#: 坐标轴数组：**只按下标**逐项合并（轴的 ``name`` 是轴名，不是身份；
#: 按 name 匹配会把「给第 2 条轴改名」合并到同名的第 1 条上）
_AXIS_ARRAY_KEYS = frozenset({"xAxis", "yAxis", "singleAxis"})


def _match_option_index(new_item, old_list: list, index: int) -> int:
    """组件 / 系列数组项匹配（ECharts 语义）：``id`` → ``name`` → 序号。

    返回旧列表下标；未匹配返回 -1（调用方按「新增一项」处理）。

    **显式给了 ``id`` 且没匹配上时必须返回 -1，不能回退到序号。** ECharts 的
    ``mappingByIndex`` 写得很明确（``echarts/src/util/model.ts``）：

        (2) If new option has id, it can only set to a hole or append to the
            last. It should not be merged to the existings with different id.
            Because id should not be overwritten.

    回退到序号的后果是**静默毁掉一个系列**：``[a, b]`` + ``[{"id": "zzz"}]``
    会把 ``b`` 位置上的系列替换成 ``zzz``，``a`` 整个消失且无任何告警；而
    ECharts 期望 3 个系列。若新项只带 ``id`` 不带 ``name`` / ``type``，更糟 ——
    幸存者保留旧系列的 ``name`` / ``type`` 却拿到新数据，图上出现一个用户
    根本没要求过的系列。
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
    return index if 0 <= index < len(old_list) else -1


def _merge_option_array(old_list: list, new_list: list) -> list:
    """ECharts 风格组件数组合并（``series`` / ``dataZoom`` / ``graphic``）。

    新项按 ``id`` → ``name`` → 序号匹配旧项并深合并；未匹配的新项追加；
    旧列表中未被匹配的项保留（ECharts ``setOption`` 合并语义：合并模式下
    传空数组不会删除旧项，需 ``notMerge=True`` 或 ``clear()``）。
    标量数组无法逐项合并时整体替换。
    """
    old_list = list(old_list or [])
    new_list = list(new_list or [])
    if any(not isinstance(item, dict) for item in new_list):
        # 标量数组无法逐项合并 → 整体替换（逐项按引用持有，见 ``_hold_value``）。
        return [_hold_value(i) for i in new_list]
    result = [_hold_value(i) for i in old_list]
    used = set()
    for i, new_item in enumerate(new_list):
        idx = _match_option_index(new_item, old_list, i)
        if idx >= 0 and idx not in used:
            merged = _hold_value(old_list[idx])
            _deep_merge(merged, new_item)
            result[idx] = _normalize_series_entry(merged)
            used.add(idx)
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
    """坐标轴合并：单对象与数组**互相等价**，一律按下标逐项合并。

    单对象 = 「只给第 0 条」（ECharts 语义）。只认 list → list 的话，多轴图上
    一句 ``setOption({"xAxis": {"axisLabel": …}})`` 会把 2 条轴**塌成 1 条**
    （第二条连同 ``data`` 一起消失，且没有任何告警）。

    返回形状跟旧值：旧值是 dict 就回 dict（不逼 ``getOption()`` 改变形状），
    旧值是数组就回数组。
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


#: 各系列渲染器存放「几何图元」的属性名（取最大长度者）。
#: 折线存 ``_points``、bar 存 ``_bars``、scatter 存 ``_dots``、pie 存
#: ``_sectors`` …… 早期实现只读折线的属性名，导致 bar / scatter 的规模恒为
#: 0（实测 8 系列里两条读数为 0）。这里列出各渲染器实际使用的名字。
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
    """系列数据量。

    优先用折线的 ``_data_len``（它已是最终生效的数据长度，stack 叠加后也
    正确）；其余系列回退到 ``data()`` 的长度 —— 几何属性只反映**绘制**
    规模（采样后），不能当数据量用。
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

    与 ``_start_animation`` 的判定保持一致：任一侧的 ``animation`` 不是
    显式 ``False`` 就认为可能要用。宁可多算一次快照，也不能出现「该播动画
    却拿不到旧数据」的空插值。
    """
    for opt in (cur_option, new_option):
        if isinstance(opt, dict) and opt.get("animation", True) is False:
            return False
    return True


def _snapshot_series_data(r):
    """取系列旧数据用于插值：大数组按引用，其余物化成 list。

    快照的用途只是「上一帧画过什么」，插值时按下标读；缓冲区按引用持有
    不会读到错位数据（``_rebuild`` 之后 ``prev_data`` 即被弃用）。
    """
    d = r.data()
    if _cdata.isBufferLike(d):
        return d
    return list(d)


def _normalize_series_entry(entry):
    """把 series 项**直接**的 ``data`` 大数值数组包成紧凑存储（就地）。

    只认 series 项自己的 ``data``，不碰 ``xAxis.data`` 等其它按 list 语义
    读取的键（包装会破坏它们）；也不递归 —— ``markPoint.data`` /
    ``graphic[].data`` 等嵌套数据形态各异，交给既有渲染路径。

    ``toBuffer`` 只接受「扁平数值序列」，遇到 dict / ``[x, y]`` 对 /
    heatmap 的 ``[x, y, v]`` 一律返回 ``None``，故本函数对结构型数据是
    无操作，语义零变化。
    """
    if not isinstance(entry, dict):
        return entry
    buf = _cdata.toBuffer(entry.get("data"))
    if buf is not None:
        entry["data"] = buf
    return entry


def _copy_option_shallow_arrays(option: dict) -> dict:
    """``notMerge`` 全量替换用的拷贝：**大数组按引用，其余深拷贝**。

    与 ``copy.deepcopy`` 的唯一区别就是数组不再逐元素复制，语义上仍然保证
    ``self._option`` 与调用方传入的 dict 不共享可变结构（只有只读的大数组
    共享 —— 见 ``_hold_value`` 的说明）。
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
            # series 首次出现（dst 侧还不是 list）：逐项拷贝并包装大数组。
            # 少了这一支，默认的合并模式会把整个 series 深拷贝一遍 ——
            # 而首次注入的那份数据正是最该零拷贝的。
            dst[k] = [_copy_series_entry(s) for s in v]
        elif isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge_option(dst[k], v)
        else:
            dst[k] = _hold_value(v)
    return dst
