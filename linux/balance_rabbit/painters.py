"""矢量绘制：兔子、余额气泡、边缘吸附指示器。

坐标全部沿用 macOS 版的设计画布（兔子 160×160、气泡 300×282、指示器 80×80），
在 Linux 上用 QPainter 按同一套坐标重绘，保证跨平台观感一致。
"""

from __future__ import annotations

import math
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

from .models import Stats
from .util import money2, money_smart, short_date, time_text, tokens_text

# ------------------------------------------------------------------ 配色

FUR = QColor(253, 248, 239)
FUR_SHADE = QColor(240, 230, 216)
PINK = QColor(246, 196, 196)
INK = QColor(52, 45, 40)
LOW_RED = QColor(230, 56, 47)
CARD = QColor(254, 252, 249)
ACCENT = QColor(90, 87, 214)
TEXT_GRAY = QColor(102, 102, 102)
TEXT_LIGHT = QColor(153, 153, 153)
TEXT_DARK = QColor(31, 31, 31)
BLUE_DEEP = QColor(39, 96, 250)
BLUE_LIGHT = QColor(109, 205, 255)
CYAN = QColor(156, 242, 255)
BAR_GRAY = QColor(191, 191, 201)

PET_DESIGN = 160.0
BUBBLE_W, BUBBLE_H = 300.0, 282.0
DOCK_DESIGN = 80.0
DOCK_SCALE = 0.6
DOCK_EDGE_LINE = 40.0

_UI_FAMILIES = [
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "Ubuntu",
    "PingFang SC",
    "Hiragino Sans GB",
    "Microsoft YaHei",
    "DejaVu Sans",
    "sans-serif",
]
_MONO_FAMILIES = [
    "JetBrains Mono",
    "Noto Sans Mono",
    "DejaVu Sans Mono",
    "Liberation Mono",
    "Menlo",
    "Monaco",
    "monospace",
]

_ui_family: str | None = None
_mono_family: str | None = None


def _pick_family(candidates: list[str]) -> str:
    available = set(QFontDatabase.families())
    for family in candidates:
        if family in available:
            return family
    return candidates[-1]


def ui_family() -> str:
    global _ui_family
    if _ui_family is None:
        _ui_family = _pick_family(_UI_FAMILIES)
    return _ui_family


def mono_family() -> str:
    global _mono_family
    if _mono_family is None:
        _mono_family = _pick_family(_MONO_FAMILIES)
    return _mono_family


def ui_font(size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(ui_family())
    # 设计画布单位是逻辑像素（与 macOS 的 pt 在该尺寸下等价），
    # 用 pixelSize 才能保证不同发行版 DPI 下排版一致，不会把字号放大 1.33 倍。
    font.setPixelSize(max(1, int(round(size))))
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def mono_font(size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(mono_family())
    font.setPixelSize(max(1, int(round(size))))
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def _with_size(font: QFont, size: float) -> QFont:
    copy = QFont(font)
    copy.setPixelSize(max(1, int(round(size))))
    return copy


def measure(text: str, font: QFont) -> float:
    return QFontMetricsF(font).horizontalAdvance(text)


def fit_font(text: str, font: QFont, max_width: float, min_size: float = 8.0) -> QFont:
    """放不下时逐级缩小字号（0.5 pt 一档），保证不压字、不截断。"""
    if max_width <= 0:
        return font
    size = float(font.pixelSize())
    current = font
    while size > min_size:
        if measure(text, current) <= max_width:
            return current
        size -= 1
        current = _with_size(font, size)
    return current


def elide_middle(text: str, font: QFont, max_width: float) -> str:
    """超宽时从中间截断并加省略号，保留首尾（模型名首尾更有辨识度）。"""
    if max_width <= 0 or measure(text, font) <= max_width:
        return text
    if len(text) <= 2:
        return "…"
    left, right = 1, len(text) - 1
    best = "…"
    while left + right <= len(text):
        break
    # 简单二分：保留前缀 head 个字符 + 后缀 (len-head) 的思路，逐步减少中间部分
    head = (len(text) + 1) // 2
    tail = len(text) - head
    while head > 1 or tail > 1:
        candidate = text[:head] + "…" + (text[-tail:] if tail else "")
        if measure(candidate, font) <= max_width:
            return candidate
        if head >= tail and head > 1:
            head -= 1
        elif tail > 1:
            tail -= 1
        else:
            head -= 1
    return "…"


def draw_text(
    painter: QPainter,
    text: str,
    rect: QRectF,
    font: QFont,
    color: QColor,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
) -> None:
    painter.save()
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(rect, int(align), text)
    painter.restore()


# ------------------------------------------------------------- 柔和阴影


def _soft_shadow(
    painter: QPainter,
    path: QPainterPath,
    dx: float,
    dy: float,
    blur: float,
    alpha: int,
    color: QColor | None = None,
) -> None:
    """用逐圈加粗的半透明描边模拟高斯阴影（比引入模糊特效便宜，且可自绘）。"""
    base = QColor(color) if color is not None else QColor(0, 0, 0)
    painter.save()
    painter.translate(dx, dy)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    steps = 8
    for index in range(steps):
        width = blur * (index + 1) / steps
        ratio = 1.0 - index / float(steps)
        shade = QColor(base)
        shade.setAlpha(int(alpha * ratio / steps * 1.35))
        painter.setPen(QPen(shade, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)
    fill = QColor(base)
    fill.setAlpha(alpha)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawPath(path)
    painter.restore()


def _rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


# ------------------------------------------------------------------ 兔子


PET_FACE_STYLES = ("cream", "sky", "line", "chibi")
PET_FACE_TITLES = {
    "cream": "奶油软萌",
    "sky": "蓝色圆环 · 弯弯眼",
    "line": "细线手绘",
    "chibi": "粉腮呆萌",
}


def _color(hex_value: int, alpha: float = 1.0) -> QColor:
    color = QColor((hex_value >> 16) & 0xFF, (hex_value >> 8) & 0xFF, hex_value & 0xFF)
    color.setAlphaF(alpha)
    return color


def _pet_palette(style: str) -> dict:
    if style == "sky":
        return dict(
            badge=_color(0xEAF6FD), face=QColor(255, 255, 255), ring=None,
            ring_highlight=None, head_outline=None, head_line=0.0,
            ear_fill=QColor(255, 255, 255), ear_inner=_color(0xF4C0CB),
            cheek=_color(0xF6AAB8, 0.37), ink=_color(0x3B2B26),
            nose=_color(0xE28598), mouth=_color(0x8A6552),
            whiskers=False, closed_eyes=True, open_mouth=False, chibi=False,
        )
    if style == "line":
        return dict(
            badge=QColor(255, 255, 255), face=QColor(255, 255, 255), ring=_color(0x58443A),
            ring_highlight=_color(0x58443A), head_outline=_color(0x58443A), head_line=2.2,
            ear_fill=QColor(255, 255, 255), ear_inner=_color(0xFBD3DA),
            cheek=_color(0xFACDD6, 0.55), ink=_color(0x58443A),
            nose=_color(0x58443A), mouth=_color(0x58443A),
            whiskers=False, closed_eyes=False, open_mouth=False, chibi=False,
        )
    if style == "chibi":
        return dict(
            badge=_color(0xFFE6EB), face=_color(0xFFF9F4), ring=_color(0xF0A9BB),
            ring_highlight=_color(0xFFFFFF, 0.6), head_outline=_color(0xF3C5D0), head_line=1.2,
            ear_fill=_color(0xFFF9F4), ear_inner=_color(0xF3A9BA),
            cheek=_color(0xF591A6, 0.6), ink=_color(0x3B2B26),
            nose=_color(0xE07A90), mouth=_color(0x8A6552),
            whiskers=False, closed_eyes=False, open_mouth=True, chibi=True,
        )
    return dict(
        badge=_color(0xFBEEDB), face=_color(0xFFFDF7), ring=_color(0xDDB88D),
        ring_highlight=_color(0xFFFFFF, 0.45), head_outline=_color(0xE3C6AC), head_line=1.4,
        ear_fill=_color(0xFFFDF7), ear_inner=_color(0xF6C3CC),
        cheek=_color(0xF6A6B4, 0.47), ink=_color(0x3B2B26),
        nose=_color(0xE28598), mouth=_color(0x8A6552),
        whiskers=True, closed_eyes=False, open_mouth=False, chibi=False,
    )


def paint_pet(
    painter: QPainter,
    size: float,
    phase: float,
    hovering: bool = False,
    loading: bool = False,
    low_balance: bool = False,
    icon_mode: bool = False,
    style: str = "cream",
) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.save()
    scale = size / PET_DESIGN
    painter.scale(scale, scale)

    if icon_mode:
        background = _rounded_path(QRectF(4, 4, 152, 152), 36)
        gradient = QLinearGradient(0, 4, 0, 156)
        gradient.setColorAt(0, QColor(255, 249, 241))
        gradient.setColorAt(1, QColor(255, 237, 226))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawPath(background)

    breathe = 1 + 0.016 * math.sin(phase * 1.9)
    hop = -3.5 * abs(math.sin(phase * 4.2)) if loading else 0.0
    hover_scale = 1.035 if hovering else 1.0
    factor = breathe * hover_scale

    painter.translate(80, 96 + hop)
    painter.scale(factor, factor)
    painter.translate(-80, -96)
    _draw_face(painter, phase, low_balance, style)
    painter.restore()


def _capsule(cx: float, cy: float, width: float, height: float, rotation: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(-width / 2, -height / 2, width, height), width / 2, width / 2)
    from PySide6.QtGui import QTransform

    # Qt 的变换是「后写的先应用」：先平移到中心、再绕原点旋转。
    return QTransform().translate(cx, cy).rotate(rotation).map(path)


def _draw_face(painter: QPainter, phase: float, low_balance: bool, style: str) -> None:
    palette = _pet_palette(style)
    badge_rect = QRectF(16.5, 19.5, 127, 127)
    head_rect = QRectF(36.5, 59, 87, 83)
    badge_path = QPainterPath()
    badge_path.addEllipse(badge_rect)

    # 圆框底 + 柔和投影
    _soft_shadow(painter, badge_path, 0, 1.8, 5, 30)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(palette["badge"])
    painter.drawPath(badge_path)

    # 圆环
    if palette["ring"] is not None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(palette["ring"], 3.4))
        painter.drawEllipse(badge_rect.adjusted(1.7, 1.7, -1.7, -1.7))
        if palette["ring_highlight"] is not None:
            painter.setPen(QPen(palette["ring_highlight"], 1.1))
            painter.drawEllipse(badge_rect.adjusted(0.7, 0.7, -0.7, -0.7))
    else:
        gradient = QLinearGradient(badge_rect.left(), 0, badge_rect.right(), 0)
        gradient.setColorAt(0, _color(0x4CC2E0))
        gradient.setColorAt(1, _color(0x2D80E0))
        painter.setBrush(gradient)
        painter.drawEllipse(badge_rect)
        painter.setBrush(palette["badge"])
        painter.drawEllipse(badge_rect.adjusted(3.4, 3.4, -3.4, -3.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_color(0x2F7DE1, 0.18), 0.9))
        painter.drawEllipse(badge_rect.adjusted(4.6, 4.6, -4.6, -4.6))

    # 耳朵（在头后面）
    sway = math.sin(phase * 1.15) * 2.2
    chibi = palette["chibi"]
    ear_w = 15.0 if chibi else 16.5
    ear_h = 46.0 if chibi else 52.0
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(palette["ear_fill"])
    left_ear = _capsule(65.5, 54, ear_w, ear_h, -11 + sway)
    right_ear = _capsule(94.5, 54, ear_w, ear_h, 11 + sway * 0.85)
    painter.drawPath(left_ear)
    painter.drawPath(right_ear)
    if palette["head_outline"] is not None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(palette["head_outline"], palette["head_line"]))
        painter.drawPath(left_ear)
        painter.drawPath(right_ear)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(palette["ear_inner"])
    painter.drawPath(_capsule(65.5, 53.5, ear_w - 6.5, ear_h - 17, -11 + sway))
    painter.drawPath(_capsule(94.5, 53.5, ear_w - 6.5, ear_h - 17, 11 + sway * 0.85))

    # 头 + 顶部高光 + 底部暖影
    head_path = QPainterPath()
    head_path.addEllipse(head_rect)
    painter.setBrush(palette["face"])
    painter.drawPath(head_path)
    painter.save()
    painter.setClipPath(head_path)
    top_light = QLinearGradient(0, head_rect.top(), 0, head_rect.bottom())
    top_light.setColorAt(0, _color(0xFFFFFF, 0.55))
    top_light.setColorAt(0.55, _color(0xFFFFFF, 0.0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(top_light)
    painter.drawRect(head_rect)
    bottom_warm = QLinearGradient(0, head_rect.top(), 0, head_rect.bottom())
    bottom_warm.setColorAt(0.55, _color(0xEAC6A8, 0.0))
    bottom_warm.setColorAt(1, _color(0xEAC6A8, 0.20))
    painter.setBrush(bottom_warm)
    painter.drawRect(head_rect)
    painter.restore()
    if palette["head_outline"] is not None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(palette["head_outline"], palette["head_line"]))
        painter.drawPath(head_path)

    # 腮红
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(palette["cheek"])
    painter.drawEllipse(QRectF(43.5, 105.5, 15, 12.5))
    painter.drawEllipse(QRectF(101.5, 105.5, 15, 12.5))

    # 眼睛
    eye_y = 96.5
    eye_r = 5.75 if chibi else 5.25
    if palette["closed_eyes"]:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(palette["ink"], 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for cx in (64.0, 96.0):
            eye = QPainterPath()
            eye.moveTo(cx - 5.5, eye_y + 1.5)
            eye.cubicTo(cx - 3.5, eye_y - 4.5, cx + 3.5, eye_y - 4.5, cx + 5.5, eye_y + 1.5)
            painter.drawPath(eye)
    else:
        cycle = math.fmod(phase, 3.8)
        eye_scale = 1.0
        if cycle > 3.62:
            eye_scale = 0.10
        elif cycle > 3.5:
            eye_scale = 0.55
        eye_height = eye_r * 2 * eye_scale
        painter.setPen(Qt.PenStyle.NoPen)
        for cx in (64.0, 96.0):
            painter.setBrush(palette["ink"])
            painter.drawEllipse(QRectF(cx - eye_r, eye_y - eye_height / 2, eye_r * 2, eye_height))
            if eye_scale > 0.6:
                painter.setBrush(_color(0xFFFFFF, 0.92))
                painter.drawEllipse(QRectF(cx - 3.4, eye_y - eye_r + 1.4, 3.1, 3.1))
                if chibi:
                    painter.setBrush(_color(0xFFFFFF, 0.55))
                    painter.drawEllipse(QRectF(cx + 0.5, eye_y + 0.6, 1.9, 1.9))

    # 鼻子
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(palette["nose"])
    nose = QPainterPath()
    nose.moveTo(77, 106)
    nose.lineTo(83, 106)
    nose.lineTo(80, 109.5)
    nose.closeSubpath()
    painter.drawPath(nose)

    # 嘴
    if palette["open_mouth"]:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(palette["nose"], 1.5))
        painter.drawEllipse(QRectF(77.5, 112, 5, 6.5))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette["cheek"])
        painter.drawEllipse(QRectF(78.6, 115.4, 2.8, 2.2))
    else:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(palette["mouth"], 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(80, 109.5, 80, 111.5)
        mouth = QPainterPath()
        mouth.moveTo(80, 111.5)
        mouth.cubicTo(77.2, 115, 74.6, 116.4, 73.5, 115.8)
        mouth.moveTo(80, 111.5)
        mouth.cubicTo(82.8, 115, 85.4, 116.4, 86.5, 115.8)
        painter.drawPath(mouth)

    # 胡须（奶油款）
    if palette["whiskers"]:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_color(0xC49C80, 0.42), 0.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for index in range(3):
            dx = index * 1.1
            y = 107 + index * 4
            painter.drawLine(35 + dx, y, 44.5 + dx, y - 1.5)
            painter.drawLine(125 - dx, y, 115.5 - dx, y - 1.5)

    # 低余额：圆框右上角感叹号
    if low_balance:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 59, 48))
        painter.drawEllipse(QRectF(117, 25, 17, 17))
        draw_text(
            painter,
            "!",
            QRectF(117, 25, 17, 17),
            ui_font(11, QFont.Weight.Bold),
            QColor(255, 255, 255),
            Qt.AlignmentFlag.AlignCenter,
        )


def paint_bubble(
    painter: QPainter,
    stats: Stats | None,
    loading: bool = False,
    hover_day: int | None = None,
    selected_day: int | None = None,
    tail_x: float = 150,
    tail_up: bool = False,
    low_threshold: float = 20.0,
) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    card_top = 20.0 if tail_up else 2.0
    card = QRectF(2, card_top, 296, 256)

    _draw_card(painter, card, tail_x, tail_up)

    if loading and (stats is None or stats.balance is None):
        _draw_loading(painter, card_top)
    elif stats is not None:
        _draw_content(painter, card, stats, loading, hover_day, selected_day, low_threshold)
    else:
        _draw_empty(painter, card_top)


def _draw_card(painter: QPainter, card: QRectF, tail_x: float, tail_up: bool) -> None:
    half, length = 12.0, 15.0
    path = QPainterPath()
    path.addRoundedRect(card, 18, 18)
    tail = QPainterPath()
    if tail_up:
        tail.moveTo(tail_x - half, card.top() + 2)
        tail.lineTo(tail_x + half, card.top() + 2)
        tail.lineTo(tail_x, card.top() - length)
    else:
        tail.moveTo(tail_x - half, card.bottom() - 2)
        tail.lineTo(tail_x + half, card.bottom() - 2)
        tail.lineTo(tail_x, card.bottom() + length)
    tail.closeSubpath()
    path = path.united(tail)
    _soft_shadow(painter, path, 0, 4 if not tail_up else -4, 18, 42)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(CARD)
    painter.drawPath(path)

    border = QColor(0, 0, 0)
    border.setAlphaF(0.06)
    painter.setPen(QPen(border, 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_rounded_path(card.adjusted(0.5, 0.5, -0.5, -0.5), 18))


def _draw_content(
    painter: QPainter,
    card: QRectF,
    value: Stats,
    loading: bool,
    hover_day: int | None,
    selected_day: int | None,
    low_threshold: float,
) -> None:
    top = card.top()
    left, right = 24.0, 274.0
    content_width = right - left

    caption_font = ui_font(11, QFont.Weight.Medium)
    caption = "当前余额"
    caption_width = math.ceil(measure(caption, caption_font)) + 2
    draw_text(painter, caption, QRectF(left, top + 18, caption_width, 15), caption_font, TEXT_GRAY)

    updated = "%s 更新" % time_text(value.updated_at)
    updated_font = fit_font(updated, ui_font(10), content_width - caption_width - 14, 8)
    draw_text(
        painter,
        updated,
        QRectF(right - 150, top + 19, 150, 14),
        updated_font,
        TEXT_LIGHT,
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
    )

    low = value.is_low(low_threshold)
    balance_text = money2(value.balance) if value.balance is not None else "—"
    balance_font = fit_font(balance_text, ui_font(31, QFont.Weight.DemiBold), content_width, 18)
    draw_text(
        painter,
        balance_text,
        QRectF(left - 2, top + 33, content_width + 2, 42),
        balance_font,
        LOW_RED if low else QColor(31, 31, 31),
    )

    overview = "今日 %s     近7天 %s" % (money_smart(value.today_spend), money_smart(value.week_spend))
    overview_font = fit_font(overview, ui_font(12), content_width, 9)
    draw_text(painter, overview, QRectF(left, top + 80, content_width, 16), overview_font, TEXT_GRAY)

    chart_top = top + 102
    baseline = chart_top + 40
    _draw_chart(painter, card, value, chart_top, baseline, hover_day, selected_day)

    divider = QColor(0, 0, 0)
    divider.setAlphaF(0.07)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(divider)
    painter.drawRect(QRectF(left, top + 174, content_width, 1))

    token_line = "Tokens %s   ·   近7天 %d 次请求" % (tokens_text(value.week_tokens), value.week_requests)
    draw_text(
        painter,
        token_line,
        QRectF(left, top + 184, content_width, 15),
        fit_font(token_line, ui_font(11), content_width, 8),
        TEXT_GRAY,
    )

    if value.top_models:
        name, count = value.top_models[0]
        prefix, suffix = "近期主力模型 ", "（%d 次）" % count
        name_font = ui_font(11)
        name_width = content_width - measure(prefix, name_font) - measure(suffix, name_font)
        model_line = prefix + elide_middle(name, name_font, name_width) + suffix
        model_color = TEXT_GRAY
    else:
        model_line = "近 7 天暂无模型使用记录"
        model_color = TEXT_LIGHT
    draw_text(
        painter,
        model_line,
        QRectF(left, top + 203, content_width, 15),
        fit_font(model_line, ui_font(11), content_width, 8),
        model_color,
    )

    if low:
        low_line = "余额低于提醒阈值 %s，右键可打开充值" % money2(low_threshold)
        draw_text(
            painter,
            low_line,
            QRectF(left, top + 222, content_width, 15),
            fit_font(low_line, ui_font(10.5, QFont.Weight.Medium), content_width, 8),
            LOW_RED,
        )
    elif value.multiple_accounts:
        identifier = str(value.account_user_id) if value.account_user_id is not None else "?"
        line = "当前 Key 可见多个账户，已按账户 #%s 过滤" % identifier
        draw_text(
            painter,
            line,
            QRectF(left, top + 222, content_width, 15),
            fit_font(line, ui_font(10, QFont.Weight.Medium), content_width, 8),
            QColor(217, 128, 13),
        )

    _draw_footer(painter, card, value, hover_day, selected_day)


def _draw_footer(
    painter: QPainter,
    card: QRectF,
    value: Stats,
    hover_day: int | None,
    selected_day: int | None,
) -> None:
    top = card.top()
    left, right = 24.0, 274.0
    content_width = right - left
    footer_font = ui_font(9.5)
    hint = "左键刷新 · 右键更多"
    hint_width = math.ceil(measure(hint, footer_font)) + 2

    index = selected_day if selected_day is not None else hover_day
    if index is not None and 0 <= index < len(value.daily):
        day = value.daily[index]
        detail = "%s 花费 %s · %d 次" % (short_date(day.date), money_smart(day.spend), day.requests)
        available = content_width - hint_width - 10
        draw_text(
            painter,
            detail,
            QRectF(left, top + 240, available, 13),
            fit_font(detail, footer_font, available, 8),
            ACCENT,
        )
    elif value.error:
        line = "⚠ 刷新失败：%s" % value.error
        available = content_width - hint_width - 10
        draw_text(
            painter,
            line,
            QRectF(left, top + 240, available, 12),
            fit_font(line, footer_font, available, 8),
            LOW_RED,
        )
    elif value.partial:
        line = "记录过多，近 7 天统计已截断"
        available = content_width - hint_width - 10
        draw_text(
            painter,
            line,
            QRectF(left, top + 240, available, 12),
            fit_font(line, footer_font, available, 8),
            QColor(217, 128, 13),
        )
    elif value.total_requests is not None:
        line = "累计 %d 次请求" % value.total_requests
        available = content_width - hint_width - 10
        draw_text(
            painter,
            line,
            QRectF(left, top + 240, available, 12),
            fit_font(line, footer_font, available, 8),
            TEXT_LIGHT,
        )
    elif value.account_user_id is not None:
        line = "账户 #%d" % value.account_user_id
        draw_text(
            painter,
            line,
            QRectF(left, top + 240, content_width - hint_width - 10, 12),
            footer_font,
            TEXT_LIGHT,
        )

    draw_text(
        painter,
        hint,
        QRectF(right - hint_width - 2, top + 240, hint_width + 2, 12),
        footer_font,
        TEXT_LIGHT,
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
    )


def _draw_chart(
    painter: QPainter,
    card: QRectF,
    value: Stats,
    chart_top: float,
    baseline: float,
    hover_day: int | None,
    selected_day: int | None,
) -> None:
    daily = value.daily
    if len(daily) != 7:
        return
    left, width = 24.0, 250.0
    bar_width, bar_max_height = 18.0, 28.0
    slot = width / 7
    today_index = 6
    peak = max((day.spend for day in daily), default=0.0)
    max_spend = max(peak, 0.0001)

    for index, day in enumerate(daily):
        height = 2.0 if day.spend <= 0 else max(3.0, bar_max_height * day.spend / max_spend)
        x = left + slot * index + (slot - bar_width) / 2
        highlighted = index == hover_day or index == selected_day
        if day.spend <= 0:
            color = QColor(0, 0, 0)
            color.setAlphaF(0.10)
        elif highlighted:
            color = ACCENT
        elif index == today_index:
            color = QColor(ACCENT)
            color.setAlphaF(0.75)
        else:
            color = BAR_GRAY
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(x, baseline - height, bar_width, height), 4, 4)

        if highlighted:
            label_color = QColor(64, 64, 64)
        elif index == today_index:
            label_color = TEXT_GRAY
        else:
            label_color = QColor(158, 158, 158)
        draw_text(
            painter,
            short_date(day.date),
            QRectF(x - 8, baseline + 4, bar_width + 16, 12),
            ui_font(9),
            label_color,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
        )

    if peak <= 0:
        return
    peak_index = next((index for index, day in enumerate(daily) if day.spend == peak), None)
    if peak_index is None:
        return
    peak_text = "峰值 %s" % money_smart(peak)
    peak_font = ui_font(9)
    measured = measure(peak_text, peak_font)
    width_limited = min(width, math.ceil(measured) + 2)
    height_limited = min(16.0, max(12.0, QFontMetricsF(peak_font).height() + 1))
    center = left + slot * peak_index + slot / 2
    x = min(max(left, center - width_limited / 2), left + width - width_limited)
    bar_top = baseline - bar_max_height
    y = max(card.top() + 96, bar_top - height_limited - 2)
    draw_text(
        painter,
        peak_text,
        QRectF(x, y, width_limited, height_limited),
        peak_font,
        TEXT_LIGHT,
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
    )


def _draw_loading(painter: QPainter, top: float) -> None:
    draw_text(
        painter,
        "查询中…",
        QRectF(24, top + 34, 250, 40),
        ui_font(26, QFont.Weight.DemiBold),
        QColor(153, 153, 153),
    )
    draw_text(
        painter,
        "正在读取最近 7 天的用量记录…",
        QRectF(24, top + 82, 250, 16),
        ui_font(12),
        TEXT_GRAY,
    )


def _draw_empty(painter: QPainter, top: float) -> None:
    draw_text(
        painter,
        "点我查余额",
        QRectF(24, top + 40, 250, 36),
        ui_font(22, QFont.Weight.DemiBold),
        TEXT_DARK,
    )
    draw_text(
        painter,
        "读取 rabbitj.top 账户余额与用量",
        QRectF(24, top + 84, 250, 16),
        ui_font(12),
        TEXT_GRAY,
    )


# ------------------------------------------------------- 边缘吸附指示器


def paint_dock(
    painter: QPainter,
    size: float,
    edge: str,
    style: str,
    phase: float,
    hovering: bool = False,
) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.save()
    scale = size / DOCK_DESIGN
    painter.scale(scale, scale)
    if edge == "right":
        painter.translate(DOCK_DESIGN, 0)
        painter.scale(-1, 1)

    center = QPointF(DOCK_EDGE_LINE, DOCK_DESIGN / 2)
    if style == "bubbleRing":
        _draw_bubble_ring(painter, center, phase, hovering)
    elif style == "arrowTab":
        _draw_arrow_tab(painter, center, phase, hovering)
    elif style == "arcLine":
        _draw_arc_line(painter, center, phase, hovering)
    else:
        _draw_bubble_glow(painter, center, phase, hovering)
    painter.restore()


def _pulse(phase: float) -> float:
    return 1 + 0.045 * math.sin(phase * 2.1)


def _glow_circle(painter: QPainter, center: QPointF, radius: float, alpha: float) -> None:
    color = QColor(BLUE_DEEP)
    color.setAlphaF(alpha)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(center, radius, radius)


def _radial_glow(painter: QPainter, center: QPointF, radius: float, alpha: float) -> None:
    """放射渐变发光，比叠几个实心圆更接近 macOS 的柔和光晕。"""
    gradient = QRadialGradient(center, radius)
    inner = QColor(BLUE_DEEP)
    inner.setAlphaF(alpha)
    outer = QColor(BLUE_DEEP)
    outer.setAlphaF(0.0)
    gradient.setColorAt(0.0, inner)
    gradient.setColorAt(0.62, QColor(inner.red(), inner.green(), inner.blue(), int(alpha * 255 * 0.55)))
    gradient.setColorAt(1.0, outer)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawEllipse(center, radius, radius)


def _draw_bubble_glow(painter: QPainter, center: QPointF, phase: float, hovering: bool) -> None:
    radius = 27 * _pulse(phase) * (1.04 if hovering else 1.0)
    boost = 1.35 if hovering else 1.0

    for extra, alpha in ((6.0, 0.16), (13.0, 0.09), (22.0, 0.045)):
        _radial_glow(painter, center, radius + extra, alpha * boost)

    gradient = QLinearGradient(center.x(), center.y() - radius, center.x(), center.y() + radius)
    gradient.setColorAt(0, BLUE_DEEP)
    gradient.setColorAt(1, BLUE_LIGHT)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawEllipse(center, radius, radius)

    painter.setBrush(QColor(255, 255, 255, 87))
    painter.drawEllipse(QRectF(center.x() - radius * 0.62, center.y() - radius * 0.72, radius * 0.72, radius * 0.46))

    ring = QColor(CYAN)
    ring.setAlphaF(0.75)
    painter.setPen(QPen(ring, 1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(center, radius, radius)

    start = math.fmod(phase * 55, 360)
    painter.setPen(QPen(QColor(255, 255, 255, 217), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawArc(QRectF(center.x() - radius - 0.5, center.y() - radius - 0.5, radius * 2 + 1, radius * 2 + 1),
                    int(start * 16), int(64 * 16))


def _draw_bubble_ring(painter: QPainter, center: QPointF, phase: float, hovering: bool) -> None:
    radius = 24.0
    for extra, alpha in ((7.0, 0.10), (15.0, 0.05)):
        _radial_glow(painter, center, radius + extra, alpha * (1.4 if hovering else 1.0))

    base = QColor(BLUE_DEEP)
    base.setAlphaF(0.30)
    painter.setPen(QPen(base, 5))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(center, radius, radius)

    start = math.fmod(phase * 90, 360)
    painter.setPen(QPen(CYAN, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawArc(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
                    int(start * 16), int(100 * 16))

    dot_radius = 4.2 + 1.6 * math.sin(phase * 2.6)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(BLUE_LIGHT)
    painter.drawEllipse(center, dot_radius, dot_radius)
    painter.setBrush(QColor(255, 255, 255, 178))
    painter.drawEllipse(center, 1.6, 1.6)


def _draw_arrow_tab(painter: QPainter, center: QPointF, phase: float, hovering: bool) -> None:
    bob = (3.0 if hovering else 2.0) * math.sin(phase * 2.2)
    tab_rect = QRectF(DOCK_EDGE_LINE - 4, center.y() - 17, 34, 34)
    tab = _rounded_path(tab_rect, 15)

    _soft_shadow(painter, tab, 0, 0, 10 if hovering else 7, 150, BLUE_DEEP)

    gradient = QLinearGradient(tab_rect.left(), tab_rect.top(), tab_rect.right(), tab_rect.bottom())
    gradient.setColorAt(0, BLUE_LIGHT)
    gradient.setColorAt(1, BLUE_DEEP)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawPath(tab)

    border = QColor(CYAN)
    border.setAlphaF(0.7)
    painter.setPen(QPen(border, 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(tab)
    painter.setPen(QPen(QColor(255, 255, 255, 71), 1))
    painter.drawPath(_rounded_path(tab_rect.adjusted(3, 3, -3, -3), 12))

    arrow_x = tab_rect.center().x() + 1 + bob
    arrow = QPainterPath()
    arrow.moveTo(arrow_x - 3, tab_rect.center().y() - 6)
    arrow.lineTo(arrow_x + 2, tab_rect.center().y())
    arrow.lineTo(arrow_x - 3, tab_rect.center().y() + 6)
    painter.setPen(QPen(QColor(255, 255, 255), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(arrow)


def _draw_arc_line(painter: QPainter, center: QPointF, phase: float, hovering: bool) -> None:
    radius = 26.0
    rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)

    glow = QColor(BLUE_DEEP)
    glow.setAlphaF(0.28 * (1.5 if hovering else 1.0))
    painter.setPen(QPen(glow, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(rect, int(-88 * 16), int(176 * 16))

    painter.setPen(QPen(CYAN, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawArc(rect, int(-88 * 16), int(176 * 16))

    t = math.fmod(phase * 0.55, 1)
    angle = math.radians(-88 + 176 * t)
    dot_center = QPointF(center.x() + math.cos(angle) * radius, center.y() - math.sin(angle) * radius)
    painter.setPen(Qt.PenStyle.NoPen)
    for r, alpha in ((7.0, 0.20), (4.0, 0.45), (2.0, 1.0)):
        color = QColor(255, 255, 255)
        color.setAlphaF(alpha)
        painter.setBrush(color)
        painter.drawEllipse(dot_center, r, r)


# --------------------------------------------------------------- 预览图


def _paint_to_image(width: int, height: int, scale: int, painter_fn) -> QImage:
    image = QImage(width * scale, height * scale, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.scale(scale, scale)
    painter_fn(painter)
    painter.end()
    return image


def render_previews(directory: str) -> list[str]:
    """生成 PNG 预览（供视觉检查 / 应用图标）。"""
    import os

    from PySide6.QtGui import QGuiApplication

    _ = QGuiApplication.instance() or QGuiApplication([])
    os.makedirs(directory, exist_ok=True)
    written: list[str] = []

    def save(name: str, image: QImage, background: QColor | None = None) -> None:
        if background is not None:
            canvas = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
            canvas.fill(background)
            painter = QPainter(canvas)
            painter.drawImage(0, 0, image)
            painter.end()
            image = canvas
        path = os.path.join(directory, name)
        image.save(path)
        written.append(path)

    for style in PET_FACE_STYLES:
        save(
            "pet_%s.png" % style,
            _paint_to_image(176, 176, 3, lambda p, st=style: paint_pet(p, 176, 1.2, style=st)),
        )
    icon_image = _paint_to_image(1024, 1024, 1, lambda p: paint_pet(p, 1024, 1.0, icon_mode=True))
    save("icon_1024.png", icon_image)
    save("icon.png", icon_image.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    for style in ("bubbleGlow", "bubbleRing", "arrowTab", "arcLine"):
        for edge in ("left", "right"):
            save(
                "dock_%s_%s.png" % (style, edge),
                _paint_to_image(48, 48, 8, lambda p, s=style, e=edge: paint_dock(p, 48, e, s, 0.0)),
            )

    sample = Stats()
    sample.balance = 88.6145
    sample.today_spend = 0.0321
    sample.today_requests = 12
    sample.week_spend = 0.4128
    sample.week_requests = 46
    sample.week_tokens = 452_130
    sample.total_requests = 1284
    sample.updated_at = datetime.now()
    sample.top_models = [("deepseek-flash-1017", 32), ("claude-sonnet-5", 11)]
    spends = [0.021, 0, 0.053, 0.018, 0.084, 0.032, 0.021]
    from datetime import date, timedelta

    today = date.today()
    sample.daily = [
        # 用简化的 DayStat 就够画图
        type("D", (), {"date": today - timedelta(days=6 - index), "spend": spend, "requests": index * 3 + 2})()
        for index, spend in enumerate(spends)
    ]

    background = QColor(219, 219, 219)
    save(
        "bubble.png",
        _paint_to_image(300, 282, 2, lambda p: paint_bubble(p, sample)),
        background,
    )
    low = Stats(**{**sample.__dict__, "balance": 12.3})
    save(
        "bubble_low.png",
        _paint_to_image(300, 282, 2, lambda p: paint_bubble(p, low)),
        background,
    )
    hover = Stats(**{**sample.__dict__, "balance": 88.61, "account_user_id": 132})
    save(
        "bubble_hover.png",
        _paint_to_image(
            300,
            282,
            2,
            lambda p: paint_bubble(p, hover, hover_day=4, selected_day=4),
        ),
        background,
    )
    multi = Stats(**{**sample.__dict__, "account_user_id": 132, "multiple_accounts": True, "total_requests": None})
    save(
        "bubble_multi.png",
        _paint_to_image(300, 282, 2, lambda p: paint_bubble(p, multi)),
        background,
    )
    return written


def icon_pixmap(size: int) -> QPixmap:
    """托盘 / 桌面图标：奶油色圆角底 + 兔子。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    paint_pet(painter, float(size), phase=1.0, icon_mode=True)
    painter.end()
    return pixmap
