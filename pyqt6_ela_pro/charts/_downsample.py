"""charts 折线降采样适配层（tsdownsample，可选依赖）。

``analyze_x`` 一次性分析时间基，``downsample_indices`` 返回采样点下标；
tsdownsample 缺失时调用方退化到 ``bucket_minmax_indices``，numpy 也缺失时
走全量路径。
"""

from __future__ import annotations

import math

try:
    import numpy as np
except ImportError:  # numpy 可选；与 tsdownsample 的可用性独立
    np = None

try:
    from tsdownsample import (
        LTTBDownsampler,
        M4Downsampler,
        MinMaxDownsampler,
        MinMaxLTTBDownsampler,
    )

    _ALGORITHMS = {
        "minmax": MinMaxDownsampler,
        "m4": M4Downsampler,
        "lttb": LTTBDownsampler,
        "minmaxLTTB": MinMaxLTTBDownsampler,
    }
    _AVAILABLE = True
except ImportError:  # 可选依赖：未安装时只关闭 tsdownsample 算法
    LTTBDownsampler = M4Downsampler = MinMaxDownsampler = MinMaxLTTBDownsampler = None
    _ALGORITHMS = {}
    _AVAILABLE = False

__all__ = [
    "available",
    "is_sorted",
    "analyze_x",
    "downsample_indices",
    "bucket_minmax_indices",
    "min_out_for",
    "ALGORITHMS",
    "np",
]

ALGORITHMS = _ALGORITHMS

#: 各算法对 ``n_out`` 的下界与整除要求（越界即 Rust panic）：minmax ≥4 偶数；m4 ≥8 且 4 的倍数；lttb / minmaxLTTB ≥3。
_ALGORITHM_LIMITS = {
    "minmax": (4, 2),
    "m4": (8, 4),
    "lttb": (3, 1),
    "minmaxLTTB": (3, 1),
}


def min_out_for(algorithm: str) -> int:
    """该算法可用的最小 ``n_out``（调用方据此兜底，避免踩 panic）。"""
    return _ALGORITHM_LIMITS.get(str(algorithm), (3, 1))[0]


def available() -> bool:
    """tsdownsample 是否可用（numpy 是否可用单独看 ``np``）。"""
    return bool(_ALGORITHMS) and _AVAILABLE and np is not None


def bucket_minmax_indices(y, n_out: int):
    """纯 numpy 的「按桶 min/max」抽稀；返回升序下标数组，失败返回 ``None``。

    按**下标**分桶，不要求 x 有序（乱序 / 重复 x 也能抽稀），也不依赖
    tsdownsample；``n_out`` 会规整成偶数且至少 4。
    """
    if np is None or y is None:
        return None
    arr = np.asarray(y, dtype=np.float64)
    n = arr.size
    if n == 0:
        return None
    try:
        n_out = int(n_out)
    except (TypeError, ValueError, OverflowError):
        return None
    n_out = max(4, n_out)
    if n_out % 2:
        n_out += 1
    if n_out >= n:
        return np.arange(n, dtype=np.uint64)

    buckets = n_out // 2
    # 非有限值不参与比较：最小值只在有限值里挑（NaN 位置填 +inf），最大值同理
    # 填 -inf —— 否则 NaN 会被 argmax 选中，抽稀结果里冒出假点。
    finite = np.isfinite(arr)
    min_probe = np.where(finite, arr, np.inf)
    max_probe = np.where(finite, arr, -np.inf)
    edges = np.linspace(0, n, buckets + 1).astype(np.int64)
    picked = np.empty(buckets * 2, dtype=np.uint64)
    count = 0
    for b in range(buckets):
        lo, hi = int(edges[b]), int(edges[b + 1])
        if hi <= lo or not finite[lo:hi].any():
            continue
        i_min = lo + int(np.argmin(min_probe[lo:hi]))
        i_max = lo + int(np.argmax(max_probe[lo:hi]))
        if i_min == i_max:
            picked[count] = i_min
            count += 1
        else:
            picked[count] = min(i_min, i_max)
            picked[count + 1] = max(i_min, i_max)
            count += 2
    if count == 0:
        return None
    picked = np.unique(picked[:count])
    return picked.astype(np.uint64)


def is_sorted(x) -> bool:
    """x 是否单调**严格**递增（NaN / inf / 重复值均视为非法）。

    必须严格递增：tsdownsample 对 x 做 searchsorted，重复值会越界 Rust panic。
    """
    if np is None or x is None:
        return False
    x = np.asarray(x)
    if x.size < 2:
        return True
    if not np.all(np.isfinite(x)):
        return False
    return bool(np.all(np.diff(x) > 0))


#: 记录中断判定：相邻时间差 > 4.1 × 步长（对齐 flexviz 的显示级启发式）
_GAP_RATIO = 4.1
#: 时间基分析的点数下限（低于它连 diff 都不值得算）
_GAP_MIN_POINTS = 64
#: 步长估计的抽样上限（正差中位数的样本数）
_GAP_SAMPLE_CAP = 200_000

_EMPTY_I64 = None  # 惰性创建（numpy 是可选依赖）
_EMPTY_F64 = None


def analyze_x(x):
    """一次性分析 x 的时间基：单调性、步长、记录中断位置。

    返回 ``(monotone, strict, step, gap_pos, gap_dur)``：``monotone`` = 非降且
    全有限；``strict`` = 严格递增；``step`` = 正差中位数；``gap_*`` =
    ``diff > 4.1 × step`` 的位置与时长。调用方应按数据身份缓存（O(n) 一次性）。
    """
    global _EMPTY_I64, _EMPTY_F64
    if np is None:
        return False, False, 0.0, None, None
    if _EMPTY_I64 is None:
        _EMPTY_I64 = np.empty(0, dtype=np.int64)
        _EMPTY_F64 = np.empty(0, dtype=np.float64)
    if x is None:
        return False, False, 0.0, _EMPTY_I64, _EMPTY_F64
    arr = np.asarray(x)
    n = arr.size
    if n < 2:
        return True, True, 0.0, _EMPTY_I64, _EMPTY_F64
    if not bool(np.all(np.isfinite(arr))):
        return False, False, 0.0, _EMPTY_I64, _EMPTY_F64
    diff = np.diff(arr)
    if bool(np.any(diff < 0)):
        return False, False, 0.0, _EMPTY_I64, _EMPTY_F64
    if bool(np.any(diff == 0)):
        return True, False, 0.0, _EMPTY_I64, _EMPTY_F64
    if n < _GAP_MIN_POINTS:
        return True, True, 0.0, _EMPTY_I64, _EMPTY_F64
    stride = max(1, diff.size // _GAP_SAMPLE_CAP)
    step = float(np.median(diff[::stride]))
    if not (step > 0.0) or not math.isfinite(step):
        return True, True, 0.0, _EMPTY_I64, _EMPTY_F64
    pos = np.flatnonzero(diff > _GAP_RATIO * step)
    return True, True, step, pos, diff[pos]


def downsample_indices(
    x,
    y,
    n_out: int,
    algorithm: str = "minmax",
    parallel: bool = False,
    assume_sorted: bool = False,
):
    """按算法对 (x, y) 降采样，返回采样点下标 ndarray；失败返回 None。

    三道闸门：x 严格递增（可用 ``assume_sorted=True`` 声明已验过）、
    ``n_out`` 满足算法下界与整除要求、调用包 ``except BaseException``。
    返回 None 而不是抛 —— 这条路走 Qt 回调链，抛出即 0xC0000409 静默终止。
    tsdownsample 的 panic 是 ``PanicException``，继承 BaseException。
    """
    if not _AVAILABLE or np is None or x is None or y is None:
        return None
    x = np.asarray(x)
    y = np.asarray(y)
    n = x.size
    if n == 0 or y.size != n:
        return None
    if not assume_sorted and not is_sorted(x):
        return None

    cls = _ALGORITHMS.get(str(algorithm))
    if cls is None:
        return None
    low, step = _ALGORITHM_LIMITS.get(str(algorithm), (3, 1))
    try:
        n_out = int(n_out)
    except (TypeError, ValueError, OverflowError):
        return None
    n_out = max(low, n_out)
    if step > 1 and n_out % step:
        n_out += step - (n_out % step)  # 向上取整到 step 的倍数
    if n_out >= n:
        return np.arange(n, dtype=np.uint64)
    try:
        return cls().downsample(x, y, n_out=n_out, parallel=parallel)
    except BaseException:  # noqa: BLE001 - 含 Rust PanicException，见上文
        return None
