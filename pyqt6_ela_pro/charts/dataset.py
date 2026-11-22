"""``dataset`` / ``encode`` / ``transform`` 展开。

在 option 归一化阶段把行式数据展开成 series.data / 轴类目；渲染器只读展开
后的结果。支持 filter / sort / aggregate 三类 transform，不执行任意代码。
"""

from __future__ import annotations

import math

from ._utils import warn_once
from .models import ChartOption

_NUMERIC_TRANSFORMS = ("sum", "avg", "average", "mean", "min", "max", "count")


def _dimension_index(dimensions: list[str], value) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    name = str(value or "").strip()
    if name in dimensions:
        return dimensions.index(name)
    try:
        return max(0, int(name))
    except (TypeError, ValueError, OverflowError):
        return 0


def _datasets(option) -> list:
    raw = option.get("dataset")
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _records(dataset: dict):
    """dataset → ``(dimensions, rows)``（rows 为 ``list[list]``）。"""
    source = dataset.get("source")
    if source is None:
        source = dataset.get("data")
    if not isinstance(source, (list, tuple)):
        return [], []
    raw = list(source)
    if not raw:
        return [], []
    if isinstance(raw[0], dict):
        dimensions = []
        for record in raw:
            for key in record:
                if str(key) not in dimensions:
                    dimensions.append(str(key))
        explicit = dataset.get("dimensions")
        if isinstance(explicit, (list, tuple)) and explicit:
            dimensions = [
                str(item.get("name") if isinstance(item, dict) else item)
                for item in explicit
            ]
        rows = [
            [record.get(name, record.get(str(name))) for name in dimensions]
            for record in raw
            if isinstance(record, dict)
        ]
        return dimensions, rows
    first = raw[0] if isinstance(raw[0], (list, tuple)) else []
    explicit = dataset.get("dimensions")
    if isinstance(explicit, (list, tuple)) and explicit:
        dimensions = [
            str(item.get("name") if isinstance(item, dict) else item)
            for item in explicit
        ]
        rows = [list(row) for row in raw if isinstance(row, (list, tuple))]
        return dimensions, rows
    header = bool(dataset.get("sourceHeader", False))
    if (
        "sourceHeader" not in dataset
        and not header
        and first
        and all(isinstance(cell, str) for cell in first)
    ):
        header = True
    if header:
        dimensions = [str(cell) for cell in first]
        rows = [list(row) for row in raw[1:] if isinstance(row, (list, tuple))]
    else:
        width = max(
            (len(row) for row in raw if isinstance(row, (list, tuple))), default=0
        )
        dimensions = [f"dim{index}" for index in range(width)]
        rows = [list(row) for row in raw if isinstance(row, (list, tuple))]
    return dimensions, rows


def _filter_rows(rows: list, dimensions: list[str], config: dict) -> list:
    if not isinstance(config, dict):
        return rows
    index = _dimension_index(dimensions, config.get("dimension", 0))
    checks = []
    for key, op in (
        ("eq", lambda a, b: a == b),
        ("ne", lambda a, b: a != b),
        ("gt", lambda a, b: a > b),
        ("gte", lambda a, b: a >= b),
        ("lt", lambda a, b: a < b),
        ("lte", lambda a, b: a <= b),
        ("in", lambda a, b: a in b),
        ("notIn", lambda a, b: a not in b),
    ):
        if key in config:
            checks.append((op, config[key]))
    if not checks:
        return rows
    out = []
    for row in rows:
        if index >= len(row):
            continue
        value = row[index]
        try:
            if all(op(value, expected) for op, expected in checks):
                out.append(row)
        except TypeError:
            continue
    return out


def _sort_rows(rows: list, dimensions: list[str], config: dict) -> list:
    if not isinstance(config, dict):
        return rows
    index = _dimension_index(dimensions, config.get("dimension", 0))
    reverse = str(config.get("order") or "asc").lower() == "desc"

    def key(row):
        value = row[index] if index < len(row) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return (0, float(value))
        return (1, str(value or "").lower())

    try:
        return sorted(rows, key=key, reverse=reverse)
    except Exception:
        return rows


def _aggregate_rows(rows: list, dimensions: list[str], config: dict) -> tuple:
    if not isinstance(config, dict):
        return dimensions, rows
    group = config.get("groupBy")
    if isinstance(group, (list, tuple)):
        groups = list(group)
    elif group is None or group == "":
        groups = []
    else:
        groups = [group]
    group_idx = [_dimension_index(dimensions, item) for item in groups]
    target = config.get("dimension")
    if target is None:
        candidates = [
            index for index in range(len(dimensions)) if index not in group_idx
        ]
        target_idx = candidates[-1] if candidates else 0
    else:
        target_idx = _dimension_index(dimensions, target)
    if not 0 <= target_idx < len(dimensions):
        candidates = [
            index for index in range(len(dimensions)) if index not in group_idx
        ]
        target_idx = candidates[-1] if candidates else 0
    method = str(config.get("method") or config.get("type") or "sum").lower()
    if method not in _NUMERIC_TRANSFORMS:
        warn_once(
            f"dataset-aggregate:{method or '?'}",
            f"dataset.aggregate 不支持 {method!r}，已跳过该项",
        )
        return dimensions, rows
    buckets: dict[tuple, list] = {}
    for row in rows:
        key = tuple(row[index] if index < len(row) else None for index in group_idx)
        buckets.setdefault(key, []).append(
            row[target_idx] if target_idx < len(row) else None
        )

    def number(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value) if math.isfinite(float(value)) else None
        try:
            number_value = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number_value if math.isfinite(number_value) else None

    out = []
    for key, values in buckets.items():
        nums = [n for n in (number(v) for v in values) if n is not None]
        if method == "count":
            result = len(values)
        elif not nums:
            result = None
        elif method in ("avg", "average", "mean"):
            result = sum(nums) / len(nums)
        elif method == "min":
            result = min(nums)
        elif method == "max":
            result = max(nums)
        else:
            result = sum(nums)
        out.append([*key, result])
    new_dimensions = [dimensions[index] for index in group_idx] + [
        f"{dimensions[target_idx]}_{method}"
    ]
    return new_dimensions, out


def _apply_transforms(dimensions: list[str], rows: list, transforms) -> tuple:
    if not isinstance(transforms, (list, tuple)):
        return dimensions, rows
    for transform in transforms:
        if not isinstance(transform, dict):
            continue
        kind = str(transform.get("type") or "").lower()
        config = transform.get("config")
        if not isinstance(config, dict):
            config = transform
        if kind == "filter":
            rows = _filter_rows(rows, dimensions, config)
        elif kind == "sort":
            rows = _sort_rows(rows, dimensions, config)
        elif kind == "aggregate":
            dimensions, rows = _aggregate_rows(rows, dimensions, config)
        else:
            warn_once(
                f"dataset-transform:{kind or '?'}",
                f"dataset.transform 不支持 {kind!r}，已跳过该项",
            )
    return dimensions, rows


def _encode_dim(encode: dict, key: str, dimensions: list[str], default=None):
    value = encode.get(key)
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        value = value[0] if value else default
    return _dimension_index(dimensions, value)


def _copy_axis_container(value):
    """只复制轴 dict / list，不复制类目数组（展开时只替换 data 键）。"""
    if isinstance(value, (list, tuple)):
        return [dict(item) if isinstance(item, dict) else item for item in value]
    if isinstance(value, dict):
        return dict(value)
    return value


def _axis_list(option: dict, key: str, index: int) -> dict:
    axis = option.get(key)
    if isinstance(axis, list):
        while len(axis) <= index:
            axis.append({"type": "category"})
        item = axis[index]
        if not isinstance(item, dict):
            item = {}
            axis[index] = item
        return item
    if isinstance(axis, dict):
        return axis
    item = {"type": "category"}
    option[key] = item
    return item


def _unique(values: list) -> list:
    out = []
    seen = set()
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _expand_series(
    template: dict,
    dimensions: list[str],
    rows: list,
    option: dict,
) -> list:
    kind = str(template.get("type") or "line")
    encode = template.get("encode")
    encode = encode if isinstance(encode, dict) else {}
    x_dim = _encode_dim(encode, "x", dimensions, 0)
    y_dims = encode.get("y")
    if isinstance(y_dims, (list, tuple)):
        y_dims = [_dimension_index(dimensions, item) for item in y_dims]
    elif y_dims is not None:
        y_dims = [_dimension_index(dimensions, y_dims)]
    else:
        value_dim = _encode_dim(encode, "value", dimensions, None)
        y_dims = [value_dim if value_dim is not None else min(1, len(dimensions) - 1)]

    def cell(row, index):
        return row[index] if 0 <= index < len(row) else None

    series_name_dim = encode.get("seriesName")
    if series_name_dim is not None:
        series_name_dim = _dimension_index(dimensions, series_name_dim)
    groups = {}
    for row in rows:
        key = cell(row, series_name_dim) if series_name_dim is not None else None
        groups.setdefault(str(key) if key is not None else "", []).append(row)
    if len(groups) <= 1:
        groups = {next(iter(groups), ""): rows}

    cartesian = kind not in (
        "pie",
        "funnel",
        "gauge",
        "map",
        "graph",
        "tree",
        "treemap",
        "sunburst",
        "sankey",
        "themeRiver",
        "radar",
        "parallel",
    )
    expanded = []
    for group_name, group_rows in groups.items():
        series = dict(template)
        series.pop("encode", None)
        x_axis = option.get("xAxis")
        category_axis = (
            isinstance(x_axis, dict)
            and str(x_axis.get("type") or "category") == "category"
        )
        if isinstance(x_axis, list):
            index = template.get("xAxisIndex", 0)
            axis = (
                x_axis[index]
                if isinstance(index, int) and 0 <= index < len(x_axis)
                else None
            )
            category_axis = (
                isinstance(axis, dict)
                and str(axis.get("type") or "category") == "category"
            )
        if kind == "heatmap":
            hx = _encode_dim(encode, "x", dimensions, x_dim)
            hy = _encode_dim(encode, "y", dimensions, 1)
            hv = _encode_dim(encode, "value", dimensions, 2)
            data = [[cell(row, hx), cell(row, hy), cell(row, hv)] for row in group_rows]
            series["data"] = data
            x_values = _unique([cell(row, hx) for row in group_rows])
            y_values = _unique([cell(row, hy) for row in group_rows])
            _axis_list(option, "xAxis", int(template.get("xAxisIndex", 0) or 0))[
                "data"
            ] = x_values
            _axis_list(option, "yAxis", int(template.get("yAxisIndex", 0) or 0))[
                "data"
            ] = y_values
        elif cartesian:
            if category_axis:
                categories = _unique([cell(row, x_dim) for row in group_rows])
                _axis_list(option, "xAxis", int(template.get("xAxisIndex", 0) or 0))[
                    "data"
                ] = categories
                if len(y_dims) == 1:
                    series["data"] = [cell(row, y_dims[0]) for row in group_rows]
                else:
                    series["data"] = [
                        [cell(row, index) for index in y_dims] for row in group_rows
                    ]
            else:
                series["data"] = [
                    [cell(row, x_dim), *[cell(row, index) for index in y_dims]]
                    for row in group_rows
                ]
        else:
            name_dim = _encode_dim(encode, "itemName", dimensions, x_dim)
            value_dim = _encode_dim(
                encode, "value", dimensions, y_dims[0] if y_dims else 1
            )
            series["data"] = [
                {"name": cell(row, name_dim), "value": cell(row, value_dim)}
                for row in group_rows
            ]
        if group_name:
            series["name"] = group_name
        expanded.append(series)
    return expanded


def _auto_layout_series(
    template: dict,
    dimensions: list[str],
    rows: list,
    option: dict,
    layout: str,
) -> list:
    if layout not in ("row", "column") or not dimensions or not rows:
        return []
    if template.get("encode"):
        return []
    kind = str(template.get("type") or "line")
    if kind not in (
        "bar",
        "line",
        "scatter",
        "effectScatter",
        "pictorialBar",
    ):
        return []
    x_index = template.get("xAxisIndex", 0)
    try:
        x_index = max(0, int(x_index or 0))
    except (TypeError, ValueError, OverflowError):
        x_index = 0
    x_axis = _axis_list(option, "xAxis", x_index)
    series_list = []
    if layout == "column":
        categories = [row[0] if row else None for row in rows]
        x_axis["data"] = categories
        for col in range(1, len(dimensions)):
            series = dict(template)
            series.pop("encode", None)
            series["name"] = dimensions[col]
            series["data"] = [row[col] if col < len(row) else None for row in rows]
            series_list.append(series)
    else:
        categories = list(dimensions[1:])
        x_axis["data"] = categories
        for row in rows:
            if not row:
                continue
            series = dict(template)
            series.pop("encode", None)
            series["name"] = row[0]
            series["data"] = list(row[1:])
            series_list.append(series)
    return series_list


def expandDataset(option, base=None) -> ChartOption:
    """展开 ``dataset`` / ``encode`` / ``transform``，返回新的 ``ChartOption``。

    :param base: 当前 option；增量更新未带轴时沿用其轴类型 / 类目
    """
    if isinstance(option, dict) and not isinstance(option, ChartOption):
        option = ChartOption.from_dict(option)
    if not isinstance(option, ChartOption):
        return option
    datasets = _datasets(option)
    if not datasets:
        return option
    payload = dict(option)
    if isinstance(base, ChartOption):
        for key in ("xAxis", "yAxis", "singleAxis"):
            if key not in payload and base.get(key) is not None:
                payload[key] = _copy_axis_container(base.get(key))
    for key in ("xAxis", "yAxis", "singleAxis"):
        if key in payload:
            payload[key] = _copy_axis_container(payload[key])
    prepared = []
    for dataset in datasets:
        dimensions, rows = _records(dataset)
        if not dimensions:
            prepared.append(([], []))
            continue
        dimensions, rows = _apply_transforms(
            dimensions, rows, dataset.get("transform") or dataset.get("transforms")
        )
        prepared.append((dimensions, rows))

    series_list = payload.get("series")
    if not isinstance(series_list, list):
        return option
    expanded = []
    for series in series_list:
        if not isinstance(series, dict):
            continue
        index = series.get("datasetIndex", 0)
        try:
            index = int(index)
        except (TypeError, ValueError, OverflowError):
            index = 0
        if not (0 <= index < len(prepared)):
            index = 0
        dimensions, rows = prepared[index]
        if not dimensions:
            expanded.append(series)
            continue
        if series.get("data") and not series.get("encode"):
            expanded.append(series)
            continue
        layout = str(datasets[index].get("seriesLayoutBy") or "").lower()
        if len(series_list) == 1 and layout in ("row", "column"):
            auto = _auto_layout_series(series, dimensions, rows, payload, layout)
            if auto:
                expanded.extend(auto)
                continue
        expanded.extend(_expand_series(series, dimensions, rows, payload))
    payload["series"] = expanded
    return ChartOption.from_dict(payload)
