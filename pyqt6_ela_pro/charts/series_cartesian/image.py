"""矩阵图像系列（matplotlib imshow 风格）。（``pyqt6_ela_pro.charts`` 内部模块）。"""

from __future__ import annotations


import math

from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QColor, QImage, QPainter

from .. import _downsample as _ds
from .. import data as _cdata
from .._tokens import theme_ramp
from .._utils import parse_color, ramp_color, to_float as _to_float, warn_key, warn_once
from ..axes import GridCoord
from ..colormaps import colormapColors
from ..core import SeriesRenderer


#: 超过该像素数先按整数步长降采样再生成 QImage（保证缩放 / 悬停不卡死）
_MAX_IMAGE_CELLS = 16_000_000
_LUT_SIZE = 256


class ImageSeriesRenderer(SeriesRenderer):
    """矩阵图像系列：2D 标量矩阵按色带上色，或 3D RGB/RGBA 原样显示。

    ``data`` 支持 ``list[list[float]]`` / numpy ``M×N``（标量）与
    ``M×N×3/4``（RGB/RGBA；整数按 0–255、浮点按 0–1）。``extent``
    默认 ``[-0.5, N-0.5, -0.5, M-0.5]``，``origin="upper"`` 第 0 行在顶部；
    ``cmap`` 可给内置色带名或颜色列表，有 ``visualMap`` 时以它的色带为准
    （范围可由 ``vmin`` / ``vmax`` 覆盖）。图像按轴映射到绘图区，
    dataZoom / 缩放自动裁切；``aspect="equal"`` 时按 1:1 数据像素 letterbox，
    命中返回 ``(row, col, value)``。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._data_epoch = 0
        self._source_ref = None
        self._source_key = None
        self._matrix = None
        self._rows = 0
        self._cols = 0
        self._mode = ""
        self._rgb_float = False
        self._range_ref = None
        self._range = None
        self._lut_key = None
        self._lut = None
        self._lut_np = None
        self._image = None
        self._image_key = None
        self._image_ref = None
        self._image_rect = QRectF()
        self._origin = "upper"
        self._interpolation = "nearest"
        self._legend_color = None

    def _load_data(self) -> None:
        """数据被 ``updateSeries`` / ``appendData`` 替换后作废旧矩阵与图像缓存。"""
        self._data_epoch += 1
        self._source_ref = None
        self._source_key = None
        self._matrix = None
        self._range_ref = None
        self._range = None
        self._image = None
        self._image_key = None
        self._image_ref = None

    def _prepare_matrix(self) -> bool:
        raw = self.data()
        source = raw.raw if isinstance(raw, _cdata.ElaNumericBuffer) else raw
        key = (id(source), self._data_epoch)
        if (
            self._source_ref is source
            and self._source_key == key
            and self._matrix is not None
        ):
            return True
        self._matrix = None
        self._rows = self._cols = 0
        self._mode = ""
        self._rgb_float = False
        self._source_ref = source
        self._source_key = key
        if source is None:
            return False
        np_ = _ds.np
        if np_ is not None:
            arr = source
            if not isinstance(arr, np_.ndarray):
                try:
                    arr = np_.asarray(arr)
                except (TypeError, ValueError, OverflowError):
                    return False
            if arr.dtype.kind in "OUSV" or arr.ndim not in (2, 3):
                return False
            if arr.dtype.kind == "c":
                warn_once(
                    warn_key("image-complex", self.name),
                    "[charts] image data 是复数；请先取 np.abs(...) / np.real(...) 再传给 image 系列",
                )
                return False
            if arr.ndim == 2:
                mode = "scalar"
                try:
                    arr = arr.astype(np_.float64, copy=False)
                except (TypeError, ValueError, OverflowError):
                    return False
            elif arr.shape[2] in (3, 4):
                mode = "rgba" if arr.shape[2] == 4 else "rgb"
                self._rgb_float = arr.dtype.kind == "f"
            else:
                return False
            rows, cols = int(arr.shape[0]), int(arr.shape[1])
            if rows <= 0 or cols <= 0:
                return False
            self._matrix = arr
        else:
            if not isinstance(source, (list, tuple)) or not source:
                return False
            first = source[0]
            if not isinstance(first, (list, tuple)) or not first:
                return False
            rows, cols = len(source), len(first)
            nested = isinstance(first[0], (list, tuple))
            if nested:
                depth = len(first[0])
                if depth not in (3, 4):
                    return False
                mode = "rgba" if depth == 4 else "rgb"
                self._rgb_float = any(isinstance(v, float) for v in first[0])
                for row in source:
                    if not isinstance(row, (list, tuple)) or len(row) != cols:
                        return False
                    for cell in row:
                        if not isinstance(cell, (list, tuple)) or len(cell) != depth:
                            return False
            else:
                mode = "scalar"
                for row in source:
                    if not isinstance(row, (list, tuple)) or len(row) != cols:
                        return False
            self._matrix = source
        self._rows, self._cols = rows, cols
        self._mode = mode
        return True

    def _data_range(self):
        if self._range_ref is self._source_ref and self._range is not None:
            return self._range
        np_ = _ds.np
        lo = hi = None
        if np_ is not None and isinstance(self._matrix, np_.ndarray):
            finite = self._matrix[np_.isfinite(self._matrix)]
            if finite.size:
                lo, hi = float(finite.min()), float(finite.max())
        else:
            for row in self._matrix or ():
                for value in row:
                    v = _to_float(value, None)
                    if v is None:
                        continue
                    lo = v if lo is None else min(lo, v)
                    hi = v if hi is None else max(hi, v)
        if lo is None or hi is None:
            lo, hi = 0.0, 1.0
        self._range_ref = self._source_ref
        self._range = (lo, hi)
        return self._range

    def _extent(self):
        raw = self.opt.get("extent")
        if isinstance(raw, (list, tuple)) and len(raw) == 4:
            values = [_to_float(v, None) for v in raw]
            if (
                all(v is not None for v in values)
                and values[0] != values[1]
                and values[2] != values[3]
            ):
                return tuple(values)
        return (-0.5, self._cols - 0.5, -0.5, self._rows - 0.5)

    def _color_range(self):
        vmin = _to_float(self.opt.get("vmin"), None)
        vmax = _to_float(self.opt.get("vmax"), None)
        vm = self.visualMapComponent()
        if vm is not None:
            if vmin is None:
                vmin = _to_float(getattr(vm, "min", None), None)
            if vmax is None:
                vmax = _to_float(getattr(vm, "max", None), None)
        if vmin is None or vmax is None:
            lo, hi = self._data_range()
            vmin = lo if vmin is None else vmin
            vmax = hi if vmax is None else vmax
        if (
            vmin is None
            or vmax is None
            or not math.isfinite(vmin)
            or not math.isfinite(vmax)
            or vmax <= vmin
        ):
            lo, hi = self._data_range()
            vmin, vmax = lo, hi
        if vmax <= vmin:
            vmax = vmin + 1.0
        return float(vmin), float(vmax)

    def _colors(self):
        colors = None
        vm = self.visualMapComponent()
        if vm is not None:
            # visualMap 是引擎的正式配色 / 色条来源：有它就与色条保持一致，
            # 不再让 cmap 悄悄改图像而色条还是另一套颜色。
            try:
                colors = vm.colors()
            except Exception:
                colors = None
        cmap = self.opt.get("cmap")
        if colors is None and isinstance(cmap, str) and cmap.strip():
            colors = colormapColors(cmap)
            if colors is None:
                warn_once(
                    warn_key("image-cmap", cmap),
                    f"[charts] 未知色带 {cmap!r}，已回退主题色带",
                )
        elif colors is None and isinstance(cmap, (list, tuple)) and len(cmap) >= 2:
            colors = [
                c for c in cmap if isinstance(c, str) and parse_color(c).isValid()
            ]
            if len(colors) < 2:
                colors = None
        if not colors:
            colors = theme_ramp(self.chart)
        return colors

    def _build_lut(self, colors) -> None:
        key = tuple(parse_color(c).name(QColor.NameFormat.HexArgb) for c in colors)
        if self._lut_key == key and self._lut is not None:
            return
        lut = []
        for i in range(_LUT_SIZE):
            color = ramp_color(colors, i / (_LUT_SIZE - 1), self.chart)
            lut.append(tuple(color.getRgb()))
        self._lut = lut
        self._lut_key = key
        np_ = _ds.np
        self._lut_np = np_.array(lut, dtype=np_.uint8) if np_ is not None else None

    def _sample_for_image(self):
        cells = self._rows * self._cols
        if cells <= _MAX_IMAGE_CELLS:
            return self._matrix, self._rows, self._cols
        step = max(1, int(math.ceil(math.sqrt(cells / _MAX_IMAGE_CELLS))))
        warn_once(
            warn_key("image-downsample", self._rows, self._cols, step),
            f"[charts] 矩阵 {self._rows}×{self._cols} 超过 {_MAX_IMAGE_CELLS} 格，"
            f"按步长 {step} 降采样显示",
        )
        np_ = _ds.np
        if np_ is not None and isinstance(self._matrix, np_.ndarray):
            arr = (
                self._matrix[::step, ::step, :]
                if self._matrix.ndim == 3
                else self._matrix[::step, ::step]
            )
            rows = len(self._matrix[::step])
            cols = len(self._matrix[0][::step])
            return arr, rows, cols
        data = self._matrix[::step]
        if self._mode == "scalar":
            return [row[::step] for row in data], len(data), len(data[0])
        return (
            [[list(cell) for cell in row[::step]] for row in data],
            len(data),
            len(data[0]),
        )

    def _build_image(self) -> None:
        vmin, vmax = self._color_range()
        if self._mode == "scalar":
            colors = self._colors()
            self._build_lut(colors)
            self._legend_color = ramp_color(colors, 0.5, self.chart)
        else:
            colors = None
            self._legend_color = None
        key = (
            id(self._source_ref),
            self._data_epoch,
            self._mode,
            round(vmin, 12),
            round(vmax, 12),
            self._lut_key if self._mode == "scalar" else None,
            self._origin,
        )
        if key == self._image_key and self._image_ref is self._source_ref:
            return
        matrix, rows, cols = self._sample_for_image()
        if rows <= 0 or cols <= 0:
            self._image = None
            return
        np_ = _ds.np
        if self._mode == "scalar":
            if np_ is not None and isinstance(matrix, np_.ndarray):
                with np_.errstate(invalid="ignore", over="ignore"):
                    data = (matrix - vmin) / (vmax - vmin)
                np_.nan_to_num(data, copy=False, nan=0.0, posinf=1.0, neginf=0.0)
                np_.clip(data, 0.0, 1.0, out=data)
                index = (data * (_LUT_SIZE - 1)).astype(np_.uint8)
                rgba = np_.ascontiguousarray(self._lut_np[index])
                bad = ~np_.isfinite(matrix)
                if bad.any():
                    rgba[bad, 3] = 0
                image = QImage(
                    rgba.data,
                    cols,
                    rows,
                    4 * cols,
                    QImage.Format.Format_RGBA8888,
                ).copy()
            else:
                image = self._scalar_image_python(matrix, rows, cols, vmin, vmax)
        elif np_ is not None and isinstance(matrix, np_.ndarray):
            image = self._rgb_image_numpy(matrix, rows, cols)
        else:
            image = self._rgb_image_python(matrix, rows, cols)
        if image is not None and self._origin == "lower":
            image = image.mirrored(False, True)
        self._image = image if image is not None and not image.isNull() else None
        self._image_key = key
        self._image_ref = self._source_ref

    def _scalar_image_python(self, matrix, rows, cols, vmin, vmax):
        span = vmax - vmin
        buf = bytearray(rows * cols * 4)
        pos = 0
        for row in matrix:
            for value in row:
                v = _to_float(value, None)
                if v is None:
                    pos += 4
                    continue
                t = (v - vmin) / span if span else 0.0
                r, g, b, a = self._lut[int(max(0.0, min(1.0, t)) * (_LUT_SIZE - 1))]
                buf[pos] = r
                buf[pos + 1] = g
                buf[pos + 2] = b
                buf[pos + 3] = a
                pos += 4
        return QImage(
            bytes(buf), cols, rows, 4 * cols, QImage.Format.Format_RGBA8888
        ).copy()

    def _rgb_image_numpy(self, matrix, rows, cols):
        np_ = _ds.np
        data = matrix
        bad = None
        if self._rgb_float:
            with np_.errstate(invalid="ignore"):
                bad = ~np_.isfinite(data).all(axis=2)
                data = np_.clip(data, 0.0, 1.0) * 255.0
        else:
            data = np_.clip(data, 0, 255)
        np_.nan_to_num(data, copy=False, nan=0.0, posinf=255.0, neginf=0.0)
        data = np_.rint(data).astype(np_.uint8)
        if data.shape[2] == 3:
            rgba = np_.empty((rows, cols, 4), dtype=np_.uint8)
            rgba[..., :3] = data
            rgba[..., 3] = 255
        else:
            rgba = data
        if bad is not None and bad.any():
            rgba[bad, 3] = 0
        rgba = np_.ascontiguousarray(rgba)
        return QImage(
            rgba.data, cols, rows, 4 * cols, QImage.Format.Format_RGBA8888
        ).copy()

    def _rgb_image_python(self, matrix, rows, cols):
        has_float = False
        max_value = 0.0
        for row in matrix:
            for cell in row:
                for value in cell:
                    if isinstance(value, float):
                        has_float = True
                    v = _to_float(value, None)
                    if v is not None:
                        max_value = max(max_value, v)
        to_byte = 255.0 if has_float and max_value <= 1.0 else 1.0
        channels = len(matrix[0][0])
        buf = bytearray(rows * cols * 4)
        pos = 0
        for row in matrix:
            for cell in row:
                values = []
                bad = False
                for value in cell:
                    v = _to_float(value, None)
                    if v is None:
                        bad = True
                        break
                    values.append(
                        max(0, min(255, int(round(v * to_byte)))),
                    )
                if bad:
                    pos += 4
                    continue
                buf[pos] = values[0]
                buf[pos + 1] = values[1]
                buf[pos + 2] = values[2]
                buf[pos + 3] = values[3] if channels == 4 else 255
                pos += 4
        return QImage(
            bytes(buf), cols, rows, 4 * cols, QImage.Format.Format_RGBA8888
        ).copy()

    def layout(self, rect: QRectF) -> None:
        self._image_rect = QRectF()
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord) or not self._prepare_matrix():
            return
        origin = str(self.opt.get("origin") or "upper").strip().lower()
        self._origin = "lower" if origin == "lower" else "upper"
        interpolation = str(self.opt.get("interpolation") or "nearest").strip().lower()
        self._interpolation = (
            "bilinear"
            if interpolation in ("bilinear", "linear", "antialiased")
            else "nearest"
        )
        self._build_image()
        if self._image is None:
            return
        x0, x1, y0, y1 = self._extent()
        plot = coord.plot
        x_axis, y_axis = coord.x_axis, coord.y_axis
        try:
            if x_axis.type == "category":
                px0, px1 = plot.left(), plot.right()
            else:
                px0 = x_axis.map(x0, plot.left(), plot.right())
                px1 = x_axis.map(x1, plot.left(), plot.right())
            if y_axis.type == "category":
                py0, py1 = plot.bottom(), plot.top()
            else:
                py0 = y_axis.map(y0, plot.bottom(), plot.top())
                py1 = y_axis.map(y1, plot.bottom(), plot.top())
        except Exception:
            return
        values = (px0, px1, py0, py1)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            return
        left, width = min(px0, px1), abs(px1 - px0)
        top, height = min(py0, py1), abs(py1 - py0)
        if width <= 0.0 or height <= 0.0:
            return
        self._image_rect = QRectF(left, top, width, height)

    def paint(self, p: QPainter, anim_t: float) -> None:
        if self._image is None or self._image_rect.isNull():
            return
        coord = self.chart.coordFor(self.opt)
        p.save()
        if isinstance(coord, GridCoord):
            p.setClipRect(coord.plot)
        opacity = self.itemOpacity(None) * max(0.0, min(1.0, float(anim_t)))
        p.setOpacity(opacity)
        smooth = self._interpolation == "bilinear"
        previous = p.testRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
        p.drawImage(self._image_rect, self._image)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, previous)
        p.restore()

    def hitTest(self, pos: QPointF):
        if self._image is None or self._image_rect.isNull():
            return None
        if not self._image_rect.adjusted(-1.0, -1.0, 1.0, 1.0).contains(pos):
            return None
        coord = self.chart.coordFor(self.opt)
        if not isinstance(coord, GridCoord):
            return None
        plot = coord.plot
        x0, x1, y0, y1 = self._extent()
        x_axis, y_axis = coord.x_axis, coord.y_axis
        if x_axis.type == "category":
            tx = (pos.x() - plot.left()) / max(1.0, plot.width())
        else:
            xv = x_axis.invert(pos.x(), plot.left(), plot.right())
            if xv is None:
                return None
            tx = (xv - x0) / (x1 - x0) if x1 != x0 else 0.0
        if y_axis.type == "category":
            ty = (
                (pos.y() - plot.top()) / max(1.0, plot.height())
                if self._origin == "upper"
                else (plot.bottom() - pos.y()) / max(1.0, plot.height())
            )
        else:
            yv = y_axis.invert(pos.y(), plot.bottom(), plot.top())
            if yv is None:
                return None
            ty = (
                (
                    (y1 - yv) / (y1 - y0)
                    if self._origin == "upper"
                    else (yv - y0) / (y1 - y0)
                )
                if y1 != y0
                else 0.0
            )
        if not math.isfinite(tx) or not math.isfinite(ty):
            return None
        tx = max(0.0, min(1.0, tx))
        ty = max(0.0, min(1.0, ty))
        col = min(self._cols - 1, max(0, int(tx * self._cols)))
        row = min(self._rows - 1, max(0, int(ty * self._rows)))
        value = self._pixel_value(row, col)
        return {
            "name": f"[{row}, {col}]",
            "value": value,
            "color": self._pixel_color(row, col),
            "series": self.name,
            "dataIndex": row * self._cols + col,
            "title": f"{row}, {col}",
        }

    def _pixel_color(self, row: int, col: int):
        """命中点的实际渲染色（与图像 LUT / RGB 一致；取不到返回 ``None``）。"""
        value = self._pixel_value(row, col)
        if value is None:
            return None
        if self._mode == "scalar":
            if self._lut is None:
                return None
            vmin, vmax = self._color_range()
            span = vmax - vmin
            t = (value - vmin) / span if span else 0.0
            index = int(max(0.0, min(1.0, t)) * (_LUT_SIZE - 1))
            red, green, blue, alpha = self._lut[index]
            return QColor(red, green, blue, alpha)
        if isinstance(value, str):
            color = parse_color(value)
            return color if color.isValid() else None
        return None

    def _pixel_value(self, row: int, col: int):
        np_ = _ds.np
        if self._mode == "scalar":
            if np_ is not None and isinstance(self._matrix, np_.ndarray):
                value = float(self._matrix[row, col])
            else:
                value = _to_float(self._matrix[row][col], None)
            return value if value is not None and math.isfinite(value) else None
        if np_ is not None and isinstance(self._matrix, np_.ndarray):
            pixel = self._matrix[row, col]
        else:
            pixel = self._matrix[row][col]
        values = []
        for value in pixel:
            v = float(value)
            if not math.isfinite(v):
                return None
            values.append(v)
        scale = 255.0 if self._rgb_float else 1.0
        channels = [max(0, min(255, int(round(v * scale)))) for v in values[:3]]
        if len(values) >= 4:
            alpha = max(0, min(255, int(round(values[3] * scale))))
            color = QColor(channels[0], channels[1], channels[2], alpha)
            return color.name(QColor.NameFormat.HexArgb)
        return QColor(channels[0], channels[1], channels[2]).name()

    def legendItems(self) -> list:
        return [(self.name, self._legend_color or self.color())]
