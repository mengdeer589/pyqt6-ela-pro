"""
charts 折线降采样适配层（tsdownsample，可选依赖）。

- ``available()``：tsdownsample / numpy 是否可用；
- ``is_sorted(x)``：x 是否单调不减（tsdownsample 算法要求有序 x，
  非单调时返回空结果，调用方须退化为不采样）；
- ``downsample_indices(x, y, n_out, algorithm)``：按算法返回采样点下标
  （uint64 ndarray），失败 / 不可用返回 None。

算法名对齐 tsdownsample：minmax / m4 / lttb / minmaxLTTB。
未安装 tsdownsample 时本模块全部降级（渲染走原始全量路径，不崩溃）。
"""

from __future__ import annotations

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
    "downsample_indices",
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


def downsample_indices(
    x, y, n_out: int, algorithm: str = "minmax", parallel: bool = False
):
    """按算法对 (x, y) 降采样，返回采样点下标 ndarray；失败返回 None。

    三道闸门，任一不满足就返回 None 走全量路径（**返回 None 而不是抛**——
    这条路走的是 Qt 回调链，抛出去就是 0xC0000409 静默终止）：

    1. x 严格递增（``is_sorted``）—— 重复值 / 非单调会让 Rust 侧 searchsorted
       越界 panic；
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
    if not is_sorted(x):
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
