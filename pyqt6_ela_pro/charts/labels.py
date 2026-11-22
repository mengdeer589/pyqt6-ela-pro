"""数据标签绘制：富文本分段、背景 / 边框、内边距与旋转。"""

from __future__ import annotations

import re

from PyQt6.QtCore import QPointF, QRectF, QSizeF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen

from ._utils import parse_color, resolve_color_option, single_font_family, text_weight


_RICH_TOKEN = re.compile(r"\{([^|{}]+)\|([^{}]*)\}")


def parse_rich_text(text) -> list[tuple[str, str]]:
    """``"{a|标题}{b| 12}"`` → ``[("a","标题"),("b"," 12")]``；普通文本为单段。"""
    raw = str(text or "")
    if not raw or "{" not in raw:
        return [("", raw)]
    parts = []
    pos = 0
    for match in _RICH_TOKEN.finditer(raw):
        if match.start() > pos:
            parts.append(("", raw[pos : match.start()]))
        parts.append((match.group(1), match.group(2)))
        pos = match.end()
    if pos < len(raw):
        parts.append(("", raw[pos:]))
    return parts or [("", raw)]


def _padding(value) -> tuple[float, float, float, float]:
    """ECharts padding → ``(top, right, bottom, left)``。"""
    if isinstance(value, (list, tuple)):
        nums = []
        for item in value[:4]:
            try:
                nums.append(max(0.0, float(item)))
            except (TypeError, ValueError, OverflowError):
                nums.append(0.0)
        if len(nums) == 1:
            return nums[0], nums[0], nums[0], nums[0]
        if len(nums) == 2:
            return nums[0], nums[1], nums[0], nums[1]
        if len(nums) == 3:
            return nums[0], nums[1], nums[2], nums[1]
        if len(nums) == 4:
            return nums[0], nums[1], nums[2], nums[3]
        return 0.0, 0.0, 0.0, 0.0
    try:
        pad = max(0.0, float(value))
    except (TypeError, ValueError, OverflowError):
        pad = 0.0
    return pad, pad, pad, pad


def _font_for(
    base: QFont,
    style: dict,
    default_weight=None,
    default_italic: bool = False,
) -> QFont:
    font = QFont(base)
    size = style.get("fontSize")
    if size is not None:
        try:
            size = float(size)
        except (TypeError, ValueError, OverflowError):
            size = 0.0
        if size > 0:
            font.setPixelSize(min(4096, max(1, int(round(size)))))
    weight = text_weight(style.get("fontWeight"), default_weight)
    if weight is not None:
        try:
            font.setWeight(QFont.Weight(max(1, min(1000, weight))))
        except (TypeError, ValueError):
            font.setBold(weight >= 600)
    style_name = str(style.get("fontStyle") or "").lower()
    font.setItalic(
        style_name in ("italic", "oblique") if style_name else bool(default_italic)
    )
    family = single_font_family(style.get("fontFamily"))
    if family:
        font.setFamilies([family])
    return font


def _segment_fonts(text: str, base_font: QFont, rich: dict):
    """返回 ``[(text, font, style)]``；无 rich 时单段沿用 base_font。"""
    rich = rich if isinstance(rich, dict) else {}
    segments = []
    for name, chunk in parse_rich_text(text):
        style = rich.get(name) if name and isinstance(rich.get(name), dict) else {}
        font = _font_for(base_font, style)
        segments.append((chunk, font, style))
    return segments


def _align_flags(align):
    if align is None:
        return Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    return align


def _text_size(segments) -> tuple[float, float, float]:
    width = 0.0
    height = 0.0
    ascent = 0.0
    for text, font, _style in segments:
        metrics = QFontMetricsF(font)
        width += metrics.horizontalAdvance(text)
        height = max(height, metrics.height())
        ascent = max(ascent, metrics.ascent())
    return width, height, ascent


def _box_style(option: dict):
    background = option.get("backgroundColor")
    border = option.get("borderColor")
    border_w = option.get("borderWidth")
    radius = option.get("borderRadius")
    pad = _padding(option.get("padding"))
    try:
        border_w = max(0.0, float(border_w)) if border_w is not None else 0.0
    except (TypeError, ValueError, OverflowError):
        border_w = 0.0
    try:
        radius = max(0.0, float(radius)) if radius is not None else 0.0
    except (TypeError, ValueError, OverflowError):
        radius = 0.0
    return background, border, border_w, radius, pad


def paint_label(
    p: QPainter,
    rect: QRectF,
    text,
    *,
    font: QFont = None,
    color: QColor = None,
    option: dict = None,
    align=None,
    angle: float = 0.0,
    draw: bool = True,
) -> QRectF:
    """在 ``rect`` 内画标签；返回背景框（未绘制背景时为文字框）。"""
    option = option if isinstance(option, dict) else {}
    base_font = QFont(font or p.font())
    segments = _segment_fonts(str(text or ""), base_font, option.get("rich"))
    width, height, ascent = _text_size(segments)
    if width <= 0.0 or height <= 0.0:
        return QRectF(rect)
    flags = _align_flags(align)
    background, border, border_w, radius, pad = _box_style(option)
    pad_t, pad_r, pad_b, pad_l = pad
    box = QRectF(
        rect.center().x() - (width + pad_l + pad_r) / 2.0,
        rect.center().y() - (height + pad_t + pad_b) / 2.0,
        width + pad_l + pad_r,
        height + pad_t + pad_b,
    )
    if flags & Qt.AlignmentFlag.AlignLeft:
        box.moveLeft(rect.left())
    elif flags & Qt.AlignmentFlag.AlignRight:
        box.moveRight(rect.right())
    if flags & Qt.AlignmentFlag.AlignTop:
        box.moveTop(rect.top())
    elif flags & Qt.AlignmentFlag.AlignBottom:
        box.moveBottom(rect.bottom())

    if not draw:
        return _rotated(box, angle)

    if not isinstance(color, QColor) or not color.isValid():
        color = parse_color(p.pen().color())

    p.save()
    if abs(angle) > 1e-6:
        p.translate(box.center())
        p.rotate(angle)
        local = QRectF(
            -box.width() / 2.0,
            -box.height() / 2.0,
            box.width(),
            box.height(),
        )
    else:
        local = QRectF(box)

    if background is not None or (border is not None and border_w > 0):
        if background is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(parse_color(background))
            if radius > 0:
                p.drawRoundedRect(local, radius, radius)
            else:
                p.drawRect(local)
        if border is not None and border_w > 0:
            p.setPen(QPen(parse_color(border), border_w))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if radius > 0:
                p.drawRoundedRect(local, radius, radius)
            else:
                p.drawRect(local)

    inner = local.adjusted(pad_l, pad_t, -pad_r, -pad_b)
    total = sum(
        QFontMetricsF(font).horizontalAdvance(chunk) for chunk, font, _ in segments
    )
    if flags & Qt.AlignmentFlag.AlignLeft:
        x = inner.left()
    elif flags & Qt.AlignmentFlag.AlignRight:
        x = inner.right() - total
    else:
        x = inner.center().x() - total / 2.0
    baseline = inner.center().y() + ascent / 2.0 - _text_descent(segments) / 2.0
    p.setPen(color)
    for chunk, font, style in segments:
        segment_color = style.get("color")
        if isinstance(segment_color, QColor) and segment_color.isValid():
            p.setPen(segment_color)
        else:
            p.setPen(color)
        p.setFont(font)
        segment_metrics = QFontMetricsF(font)
        segment_w = segment_metrics.horizontalAdvance(chunk)
        segment_bg = style.get("backgroundColor")
        segment_border = style.get("borderColor")
        segment_border_w = style.get("borderWidth")
        try:
            segment_border_w = (
                max(0.0, float(segment_border_w))
                if segment_border_w is not None
                else 0.0
            )
        except (TypeError, ValueError, OverflowError):
            segment_border_w = 0.0
        if segment_bg is not None or (
            segment_border is not None and segment_border_w > 0
        ):
            segment_rect = QRectF(
                x,
                baseline - segment_metrics.ascent(),
                max(1.0, segment_w),
                segment_metrics.height(),
            ).adjusted(-1, 0, 1, 0)
            if segment_bg is not None:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(parse_color(segment_bg))
                p.drawRect(segment_rect)
                p.setPen(segment_color)
            if segment_border is not None and segment_border_w > 0:
                p.setPen(QPen(parse_color(segment_border), segment_border_w))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(segment_rect)
            p.setPen(
                segment_color
                if isinstance(segment_color, QColor) and segment_color.isValid()
                else color
            )
        p.drawText(QPointF(x, baseline), chunk)
        x += segment_w
    p.restore()
    return _rotated(box, angle)


def _text_descent(segments) -> float:
    return max(
        (QFontMetricsF(font).descent() for _text, font, _style in segments), default=0.0
    )


def _rotated(rect: QRectF, angle: float) -> QRectF:
    if abs(angle) < 1e-6:
        return QRectF(rect)
    from PyQt6.QtGui import QTransform

    transform = QTransform()
    transform.translate(rect.center().x(), rect.center().y())
    transform.rotate(angle)
    transform.translate(-rect.center().x(), -rect.center().y())
    return transform.mapRect(rect)


def label_text_size(text, font: QFont, option: dict = None) -> QSizeF:
    """富文本块尺寸（供 ``hideOverlap`` / 命中框复用）。"""
    option = option if isinstance(option, dict) else {}
    segments = _segment_fonts(str(text or ""), font, option.get("rich"))
    width, height, _ascent = _text_size(segments)
    return QSizeF(width, height)


def resolve_label_option(option: dict, chart=None) -> dict:
    """解析标签 option 的主题色（含 ``rich`` 子样式）。"""
    out = dict(option or {})
    for key in ("color", "backgroundColor", "borderColor"):
        value = out.get(key)
        if isinstance(value, str) and value.strip():
            color = resolve_color_option(value, chart)
            if color.isValid():
                out[key] = color
    rich = out.get("rich")
    if isinstance(rich, dict):
        resolved = {}
        for name, style in rich.items():
            if not isinstance(style, dict):
                resolved[name] = style
                continue
            local = dict(style)
            for key in ("color", "backgroundColor", "borderColor"):
                value = local.get(key)
                if isinstance(value, str) and value.strip():
                    color = resolve_color_option(value, chart)
                    if color.isValid():
                        local[key] = color
            resolved[name] = local
        out["rich"] = resolved
    return out
