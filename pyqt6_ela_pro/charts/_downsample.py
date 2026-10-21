"""
charts 折线降采样适配层（tsdownsample，可选依赖）。

- ``available()``：tsdownsample / numpy 是否可用；
- ``is_sorted(x)``：x 是否单调不减（tsdownsample 算法要求有序 x，
  非单调时返回空结果，调用方须退化为不采样）；
- ``analyze_x(x)``：一次性分析时间基（单调性 / 步长 / 记录中断位置），
  调用方按数据身份缓存，替代每次布局都跑的 ``is_sorted``；
- ``downsample_indices(x, y, n_out, algorithm, assume_sorted)``：按算法返回
  采样点下标（uint64 ndarray），失败 / 不可用返回 None。

算法名对齐 tsdownsample：minmax / m4 / lttb / minmaxLTTB。
未安装 tsdownsample 时本模块全部降级（渲染走原始全量路径，不崩溃）。
"""

from __future__ import annotations

import math

try:
    import numpy as np

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
except ImportError:  # 可选依赖：未安装时降级
    np = None
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

#: 各算法对 ``n_out`` 的下界与整除要求（越界即 Rust panic，实测）。
#: ``minmax`` 要求 n_out >= 4 且为偶数；``m4`` 要求 n_out >= 8 且是 4 的倍数；
#: ``lttb`` / ``minmaxLTTB`` 要求 n_out >= 3。``n_out == 2`` 会让前三个全部 panic。
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
    """tsdownsample 与 numpy 是否可用。"""
    return _ALGORITHMS and _AVAILABLE and np is not None


def bucket_minmax_indices(y, n_out: int):
    """纯 numpy 的「按桶 min/max」抽稀；返回升序下标数组，失败返回 ``None``。

    与 tsdownsample 的 ``minmax`` 同类（每桶保留最小 / 最大两点，视觉上是
    包络保形），但有两条它做不到的能力：

    1. **不要求 x 有序** —— 按**下标**分桶，乱序 / 重复 x 的数据也能抽稀
       （方形波、回环轨迹这类 line 数据的 x 往往不单调）；
    2. **不依赖 tsdownsample** —— 只装 numpy 的宿主同样能拿到按像素级的绘制量。

    ``n_out`` 会被规整成偶数（每桶两点），且至少 4。
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
    """x 是否单调**严格**递增（NaN / inf / 重复值均视为非法，返回 False）。

    必须是**严格**递增而不是「不减」：tsdownsample 内部对 x 做 searchsorted，
    遇到重复值会算出越界下标并直接 Rust panic（``index out of bounds``）。
    """
    if not _AVAILABLE or np is None or x is None:
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

    返回 ``(monotone, strict, step, gap_pos, gap_dur)``：

    - ``monotone``：非降且全有限 —— ``searchsorted`` 窗口可用；
    - ``strict``：严格递增且全有限 —— tsdownsample 可用、中断检测有定义；
    - ``step``：正差的**中位数**（抽样估计；抗浮点抖动与重复值）；
    - ``gap_pos`` / ``gap_dur``：``diff > 4.1 × step`` 的位置（int64 下标）
      与时长 —— 即「记录中断」。序列过短 / 非严格递增 / 非有限时为两个空数组。

    调用方**按数据身份缓存**结果：这是 O(n) 的一次性开销，不是每帧成本。
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

    三道闸门，任一不满足就返回 None 走全量路径（**返回 None 而不是抛**——
    这条路走的是 Qt 回调链，抛出去就是 0xC0000409 静默终止）：

    1. x 严格递增（``is_sorted``）—— 重复值 / 非单调会让 Rust 侧 searchsorted
       越界 panic。调用方可用 ``assume_sorted=True`` 声明「已按数据身份验过」
       （每帧重扫是 O(n)：1M≈1.4ms、5M≈7ms，见 ``analyze_x``）；
    2. ``n_out`` 满足该算法的下界与整除要求；
    3. 真正的调用再包一层 ``except BaseException``。

    第 3 条的 ``BaseException`` 不是笔误：tsdownsample 的 panic 以
    ``pyo3_runtime.PanicException`` 抛出，它**继承 BaseException 而不是
    Exception**，``except Exception`` 接不住（实测 mro 为
    ``[PanicException, BaseException, object]``）。
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
