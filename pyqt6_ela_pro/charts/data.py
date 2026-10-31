"""charts 大数组的紧凑存储与零拷贝摄入口径。

``ndarray`` / 缓冲协议对象按引用持有，普通 list 达到 ``_BUFFER_MIN_LEN`` 才转
float64 数组包装（含 ``None`` 的间隙写成 NaN）；``getOption()`` / ``data()``
对外仍返回 list，numpy 缺失时降级为 ``array('d')`` 承载。
"""

from __future__ import annotations

from array import array as _array
from collections.abc import Sequence

from . import _downsample as _ds

__all__ = [
    "numpyAvailable",
    "ElaNumericBuffer",
    "toBuffer",
    "unwrapData",
    "isBufferLike",
]

#: 小于该长度的数据不做缓冲包装（小数组直接深拷贝更省事）。
_BUFFER_MIN_LEN = 256

_np = _ds.np


def numpyAvailable() -> bool:
    """当前环境是否可用 numpy（向量化采样与范围统计的加速前提）。"""
    return _np is not None


def isBufferLike(obj) -> bool:
    """是否为可按引用持有的紧凑存储（``ElaNumericBuffer`` / ndarray / array）。

    ``list`` / ``tuple`` 不算：它们仍需一次 O(n) 转换，那由 ``toBuffer`` 负责。
    """
    if isinstance(obj, ElaNumericBuffer):
        return True
    if _np is not None and isinstance(obj, _np.ndarray):
        return True
    if isinstance(obj, _array):
        return True
    return hasattr(obj, "__array_interface__")


class ElaNumericBuffer(Sequence):
    """大数值数组的紧凑容器（numpy ndarray 或 ``array('d')`` 承载）。

    只读语义：不提供原地修改接口；切片返回 ``list``（与 list 切片语义一致）。
    """

    __slots__ = ("_buf",)

    def __init__(self, buf) -> None:
        self._buf = buf

    # -- Sequence 协议 ---------------------------------------------------
    def __len__(self) -> int:
        return int(len(self._buf))

    def __getitem__(self, index):
        if isinstance(index, slice):
            # 别写 ``self.toList()[index]``：那会把整个缓冲物化成 list 再切
            # （10 万点切 ``[0:3]`` 要 0.79 ms），ndarray / array 都能直接切。
            if _np is not None and isinstance(self._buf, _np.ndarray):
                return self._buf[index].tolist()
            sliced = self._buf[index]
            if sliced and isinstance(sliced[0], (list, tuple)):
                return list(sliced)
            return [float(v) for v in sliced]
        value = self._buf[index]
        if isinstance(value, (list, tuple)):
            return value
        if _np is not None and isinstance(value, _np.ndarray):
            return value.tolist()
        return float(value)

    def __iter__(self):
        if _np is not None and isinstance(self._buf, _np.ndarray):
            # tolist() 在 C 层完成 float64 → float 转换，比逐个下标取值快一个数量级。
            return iter(self._buf.tolist())
        # 非 ndarray 的 2D buffer-like：行序列原样交出；1D array('d') 仍走 float 归一化。
        if len(self._buf):
            first = self._buf[0]
            if isinstance(first, (list, tuple)) or hasattr(first, "tolist"):
                return iter(
                    self._buf.tolist() if hasattr(self._buf, "tolist") else self._buf
                )
        return (float(v) for v in self._buf)

    def __array__(self, dtype=None, copy=None):
        """支持 ``numpy.asarray(buffer)``（numpy 2 会传 ``copy`` 关键字）。

        ``copy=True`` 必须真复制 —— 否则调用方改返回值会改到内部状态。
        """
        if _np is not None and isinstance(self._buf, _np.ndarray):
            arr = self._buf
        else:
            # 走到这里必然有 numpy（否则没人会调 __array__）
            import numpy as _np_local

            arr = _np_local.frombuffer(self._buf, dtype=float)
        needs_copy = bool(copy)
        if dtype is not None and _np is not None:
            if needs_copy:
                return arr.astype(dtype, copy=True)
            return arr.astype(dtype, copy=False)
        if needs_copy:
            return arr.copy()
        return arr

    def __repr__(self) -> str:
        return f"ElaNumericBuffer(len={len(self)})"

    def __deepcopy__(self, memo) -> "ElaNumericBuffer":
        """深拷贝返回**自身**：本类只读，而默认深拷贝会复制底层数组，
        「按引用持有大数组」的承诺就漏在这里。
        """
        memo[id(self)] = self
        return self

    # -- 与 list 的可比较性（绘图与测试都直接比较数据） -------------------
    def __eq__(self, other) -> bool:
        # 身份快路径必须在最前：``None`` 间隙在缓冲里是 NaN，而 ``[nan] == [nan]``
        # 为 False，含 NaN 的缓冲自己跟自己都不相等。
        if other is self:
            return True
        if isinstance(other, ElaNumericBuffer):
            other = other.toList()
        if isinstance(other, (list, tuple)):
            if len(other) != len(self):
                return False
            return self.toList() == list(other)
        return NotImplemented

    def __ne__(self, other) -> bool:
        if other is self:
            return False
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    __hash__ = None  # 可比较但不可哈希（与 list 一致）

    # -- 显式转换 --------------------------------------------------------
    def toList(self) -> list:
        """转为原生 Python float 列表（对外 API 的兼容出口）。

        int dtype 也要走 ``float()`` —— 直接 ``tolist()`` 会返回 Python int。
        """
        if _np is not None and isinstance(self._buf, _np.ndarray):
            if self._buf.dtype.kind == "f":
                return self._buf.tolist()
            return [float(v) for v in self._buf.tolist()]
        return [float(v) for v in self._buf]

    @property
    def raw(self):
        """底层数组（**只读**使用，供 numpy 向量化路径直接取用）。"""
        return self._buf


def toBuffer(data, minLen: int = _BUFFER_MIN_LEN):
    """把数值序列转为 ``ElaNumericBuffer``；不值得包装时返回 ``None``。

    ``None`` 表示调用方继续走深拷贝路径（小数组 / 非数值序列 / 结构型数据）。
    仅当元素全是 ``int`` / ``float``（非 bool）或 ``None`` 时才包装。
    """
    if data is None or isinstance(data, ElaNumericBuffer):
        return None
    if isBufferLike(data):
        try:
            n = len(data)
        except TypeError:
            return None
        return ElaNumericBuffer(data) if n >= minLen else None
    if not isinstance(data, (list, tuple)):
        return None
    n = len(data)
    if n < minLen:
        return None
    # 抽样判别元素类型（全量扫描白付 O(n)）；必须覆盖尾部，否则
    # 「前段数值 + 后段结构」的混合数据会被误判。
    step = max(1, n // 64)
    probes = set(range(0, n, step))
    probes.update(range(min(24, n)))
    probes.update(range(max(0, n - 24), n))
    for i in probes:
        v = data[i]
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
    try:
        if _np is not None:
            buf = _np.asarray(data, dtype=_np.float64)
        else:
            buf = _array(
                "d", [float(v) if v is not None else float("nan") for v in data]
            )
    except (TypeError, ValueError, OverflowError):
        return None
    return ElaNumericBuffer(buf)


def unwrapData(value):
    """把紧凑存储还原为 list（供 ``getOption`` 对外输出用）。

    裸 ndarray / ``array.array`` 也要转：``getOption()`` 承诺返回脱离的副本，
    且裸 ndarray 的 ``==`` 返回数组（``if data == other`` 会抛 ValueError，
    从 Qt 回调里抛就是 0xC0000409）。
    """
    if isinstance(value, ElaNumericBuffer):
        return value.toList()
    if isBufferLike(value):
        try:
            rows = value.tolist() if hasattr(value, "tolist") else list(value)
        except (TypeError, ValueError, OverflowError):
            return value
        if rows and isinstance(rows[0], (list, tuple)):
            # 2D（``[x, y]`` 点对）：逐行复制成 list，别把内部 ndarray 交出去
            return [list(row) for row in rows]
        try:
            return [float(v) for v in rows]
        except (TypeError, ValueError, OverflowError):
            return rows
    return value
