"""charts 大数组的紧凑存储与零拷贝摄入口径。

用途：把调用方传入的**大数值数组**按引用持有为紧凑缓冲区，避免
``setOption`` 的 ``copy.deepcopy`` 与 ``updateOption`` 的合并路径对百万级
数组逐元素复制。实测代价（本机，100 万点 float list）：``deepcopy`` 一次
约 60~95 ms；数据每次更新都付这个成本时，无论渲染多快都不可能实时。

对外可见语义（必须与既有行为完全一致）：

- ``ElaNumericBuffer`` 是 ``collections.abc.Sequence``，``len()`` / 下标 /
  切片 / ``iter()`` 行为与 ``list`` 一致；``==`` 支持与普通 list 比较
  （绘图与测试都依赖数据可比较）。
- 元素一律为原生 Python ``float``，不使用 numpy 标量 —— 后者与 ``int``
  的 ``==`` 虽然成立，但 ``repr`` 与类型断言会露出差异。
- ``getOption()`` / ``SeriesRenderer.data()`` 对外仍返回 **list**，调用方
  观察不到缓冲区的存在（见 ``core`` 中对 ``unwrapData`` 的使用）。

摄入口径（``toBuffer``）：

- ``ndarray`` / 缓冲协议对象：**按引用持有**（真正零拷贝）；
- 普通 list：转 ``numpy.float64`` 连续数组（O(n) 一次性），且仅在元素数量
  达到 ``_BUFFER_MIN_LEN`` 时才包装 —— 小数组直接深拷贝更省事，也不必为
  演示页的十来点数据平白增加包装对象。

**含 None 的间隙数据**：list 里的 ``None`` 在转数组时写成 ``NaN``，与既有
``LineSeriesRenderer._y_at`` 的 ``math.isfinite`` 判空口径一致，断点语义不变。

依赖说明：numpy / tsdownsample 是本模块的可选依赖（见 ``charts._downsample``），
未安装时全部降级为 ``array('d')`` 承载，语义一致。
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

    供上游判断「这个值能否直接当数值序列用」。合并逻辑曾只认
    ``list`` / ``tuple``，于是 numpy 数组既不匹配 list 分支、也不是缓冲区，
    落到兜底的「数据缺失」分支之后被当作空数据 —— 表现为
    **入图后曲线一个点都不画**。

    注意 ``list`` / ``tuple`` **不算**：它们仍需一次 O(n) 转换，那由
    ``toBuffer`` 负责，不属于「已经可以按引用拿着」。
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

    **只读语义**：不提供原地修改接口，避免调用方与图表共享可变状态时出现
    难以排查的错位。切片返回 ``list``（与 list 切片语义一致），大范围切片
    请直接用 ``toList()``。
    """

    __slots__ = ("_buf",)

    def __init__(self, buf) -> None:
        self._buf = buf

    # -- Sequence 协议 ---------------------------------------------------
    def __len__(self) -> int:
        return int(len(self._buf))

    def __getitem__(self, index):
        if isinstance(index, slice):
            # **别写 ``self.toList()[index]``**：那会把整个缓冲物化成 list
            # 再切。实测 10 万点缓冲切 ``[0:3]`` 要 0.79 ms（20 次切片
            # 15.8 ms），而 ndarray / ``array('d')`` 都能按 O(len(slice))
            # 直接切。只有下标取值才需要显式 ``float()``（int dtype 兼容）。
            if _np is not None and isinstance(self._buf, _np.ndarray):
                return self._buf[index].tolist()
            return [float(v) for v in self._buf[index]]
        return float(self._buf[index])

    def __iter__(self):
        if _np is not None and isinstance(self._buf, _np.ndarray):
            # tolist() 在 C 层完成 float64 -> Python float 转换，比逐个
            # 下标取值快一个数量级；大数组的迭代是热路径。
            return iter(self._buf.tolist())
        return (float(v) for v in self._buf)

    def __array__(self, dtype=None, copy=None):
        """支持 ``numpy.asarray(buffer)``（numpy 2 会传 ``copy`` 关键字）。

        两个坑都在这里：

        * **三元原先写反了** —— ``self._buf if _np is not None else
          _np.frombuffer(...)`` 在**没装 numpy** 的分支里去取 ``_np``，
          而那一刻 ``_np`` 正是 ``None`` → ``AttributeError: 'NoneType' object
          has no attribute 'frombuffer'``。也就是说「未安装时全部降级为
          ``array('d')`` 承载、语义一致」这条承诺的路径根本走不通。
          正确写法是「有 numpy 就用内部 ndarray，没有就把 ``array('d')``
          交给 numpy 自己转」—— 后者只在**真的调了 ``__array__``** 时才需要
          numpy，而能调到它就说明 numpy 装着。
        * **``copy=True`` 原先被忽略** —— 文档承诺「缓冲区只读」，但
          ``np.array(buf, copy=True)`` 与 ``buf.raw`` 仍共享内存
          （实测 ``np.shares_memory(...)`` 为 True），调用方改返回值就改到了
          内部状态。
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
        """深拷贝返回**自身**。

        本类只读，共享实例没有别名风险；而 ``copy.deepcopy`` 默认会连底层 ndarray /
        ``array('d')`` 一起复制 —— 合并路径 ``_merge_option_array`` 会深拷贝每一条
        series dict（1M 点 ≈ 1.6 MB 一份），「按引用持有大数组」的承诺就漏在这里。
        """
        memo[id(self)] = self
        return self

    # -- 与 list 的可比较性（绘图与测试都直接比较数据） -------------------
    def __eq__(self, other) -> bool:
        # **身份快路径必须在最前**：``None`` 间隙在缓冲里就是 NaN（见本模块
        # docstring），而 ``[nan] == [nan]`` 是 False —— 所以含 NaN 的缓冲
        # 自己跟自己都不相等（实测 ``buf == buf`` 为 False、``buf != buf`` 为
        # True），任何 ``if buffer == other:`` 都会走错分支。这不是边缘情形：
        # 只要数据里有任何一个 None 间隙就必然命中。
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

        ndarray 分支原先直接 ``tolist()``，对 **int dtype** 会返回 Python int
        （``[0, 1, 2]``），与本模块 docstring「元素一律为原生 Python float」
        及 ``__getitem__`` 的 ``float()`` 行为都不一致。``toBuffer`` 自己只造
        float64，但用户可以直接 ``ElaNumericBuffer(np.array([1, 2, 3]))``。
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

    返回 ``None`` 表示调用方应继续走原有的深拷贝路径（小数组、非数值序列、
    字典项 / ``[x, y]`` 对列表等结构型数据）。判断只看**长度与数值性**，
    不猜测语义。

    仅当序列中每个元素都是 ``int`` / ``float``（非 ``bool``）或 ``None``
    时才包装 —— 含 dict（如 pie 的 ``{"name","value"}``）或含嵌套列表（如
    candlestick 的 ``[o,c,l,h]``、``[x, y]`` 点对）的数据保持原样，交由既有
    渲染路径处理。
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
    # 抽样判别元素类型：只抽样即可，全量扫描会白白增加 O(n) Python 开销。
    # 抽样必须覆盖尾部（见下），否则「前段数值 + 后段结构」的混合数据会被
    # 误判为纯数值，包装后在 asarray 处抛异常。
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

    **裸 ndarray / ``array.array`` 也要转成 list**，不能原样返回。两条理由：

    * ``getOption()`` 的 docstring 承诺返回**脱离的副本**。原样返回裸 ndarray
      等于把内部缓冲的引用交出去 —— 宿主改一下返回值就污染了图表内部状态
      （实测：``out[0] = 999`` 直接改掉了调用方传进来的数组）。
    * 裸 ndarray **没有** ``__eq__ -> bool``，而 ``ElaNumericBuffer`` 有。
      任何 ``if data == other:``（库内与宿主代码都会写）在拿到 ndarray 时
      抛 ``ValueError: The truth value of an array with more than one element
      is ambiguous`` —— 从 Qt 回调里抛就是 0xC0000409。

    短数组（< ``_BUFFER_MIN_LEN``）不会包装成 ``ElaNumericBuffer``，所以裸
    ndarray 确实会走到这里，这是「可直接传 numpy 数组」这条承诺的必经之路。
    """
    if isinstance(value, ElaNumericBuffer):
        return value.toList()
    if isBufferLike(value):
        try:
            return [float(v) for v in value]
        except (TypeError, ValueError, OverflowError):
            return value
    return value
