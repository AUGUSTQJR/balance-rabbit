"""三个无边框透明窗口：兔子、余额气泡、边缘吸附指示器。"""

from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from . import painters
from .models import Stats

X11_OVERRIDE = os.environ.get("BALANCE_RABBIT_OVERRIDE", "0") == "1"


def overlay_flags() -> Qt.WindowType:
    flags = (
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.Tool
        | Qt.WindowType.WindowDoesNotAcceptFocus
    )
    platform = QGuiApplication.platformName() if QGuiApplication.instance() else ""
    if X11_OVERRIDE and platform == "xcb":
        flags |= Qt.WindowType.X11BypassWindowManagerHint
    return flags


class OverlayWindow(QWidget):
    def __init__(self, width: int, height: int) -> None:
        super().__init__(None)
        self.setWindowFlags(overlay_flags())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setFixedSize(width, height)

    def show_without_activating(self) -> None:
        self.show()
        self.raise_()


class PetWindow(OverlayWindow):
    activated = Signal()
    context_requested = Signal(QPoint)
    dragged = Signal(QPoint)
    drag_finished = Signal()
    resized_by_wheel = Signal(int)

    def __init__(self, side: int) -> None:
        super().__init__(side, side)
        self._side = side
        self.phase = 0.0
        self.hovering = False
        self.loading = False
        self.low_balance = False
        self.pet_style = "cream"
        self._dragging = False
        self._drag_start_global = QPoint()
        self._drag_start_pos = QPoint()
        self._timer = QTimer(self)
        self._timer.setInterval(42)  # 约 24fps
        self._timer.timeout.connect(self._tick)

    # -------------------------------------------------------------- 状态
    def set_side(self, side: int) -> None:
        self._side = side
        self.setFixedSize(side, side)
        self.update()

    def set_loading(self, value: bool) -> None:
        if self.loading != value:
            self.loading = value
            self.update()

    def set_pet_style(self, style: str) -> None:
        if self.pet_style != style:
            self.pet_style = style
            self.update()

    def set_low_balance(self, value: bool) -> None:
        if self.low_balance != value:
            self.low_balance = value
            self.update()

    # -------------------------------------------------------------- 动画
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        if not self.isVisible():
            return
        self.phase += 1.0 / 24.0
        self.update()

    # -------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painters.paint_pet(
            painter,
            float(self._side),
            self.phase,
            hovering=self.hovering,
            loading=self.loading,
            low_balance=self.low_balance,
            style=self.pet_style,
        )
        painter.end()

    # -------------------------------------------------------------- 交互
    def enterEvent(self, event) -> None:  # noqa: N802
        self.hovering = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.hovering = False
        self.unsetCursor()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self.context_requested.emit(event.globalPosition().toPoint())
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = False
        self._drag_start_global = event.globalPosition().toPoint()
        self._drag_start_pos = self.pos()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        delta = event.globalPosition().toPoint() - self._drag_start_global
        if not self._dragging:
            if delta.manhattanLength() < QGuiApplication.startDragDistance():
                return
            self._dragging = True
        target = self._drag_start_pos + delta
        self.move(target)
        self.dragged.emit(target)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging:
            self._dragging = False
            self.drag_finished.emit()
        else:
            self.activated.emit()
        event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802
        modifiers = event.modifiers()
        if modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            delta = event.angleDelta().y()
            if delta:
                self.resized_by_wheel.emit(8 if delta > 0 else -8)
            event.accept()
            return
        super().wheelEvent(event)


class BubbleWindow(OverlayWindow):
    refresh_requested = Signal()
    close_requested = Signal()
    interaction = Signal()
    context_requested = Signal(QPoint)

    def __init__(self) -> None:
        super().__init__(int(painters.BUBBLE_W), int(painters.BUBBLE_H))
        self.stats: Stats | None = None
        self.loading = False
        self.hover_day: int | None = None
        self.selected_day: int | None = None
        self.tail_x = 150.0
        self.tail_up = False
        self.low_threshold = 20.0
        self._tail_animation = None

    # -------------------------------------------------------------- 状态
    def set_stats(self, stats: Stats | None, loading: bool = False) -> None:
        self.stats = stats
        self.loading = loading
        self.update()

    def set_tail(self, tail_x: float, tail_up: bool) -> None:
        self.tail_x = tail_x
        self.tail_up = tail_up
        self.update()

    def set_low_threshold(self, threshold: float) -> None:
        self.low_threshold = threshold
        self.update()

    def reset_selection(self) -> None:
        self.hover_day = None
        self.selected_day = None
        self.update()

    # -------------------------------------------------------------- 几何
    def card_rect(self) -> QRectF:
        return QRectF(2, 20 if self.tail_up else 2, 296, 256)

    def chart_geometry(self) -> tuple[float, float, float, float, float]:
        card_top = 20.0 if self.tail_up else 2.0
        chart_top = card_top + 102
        baseline = chart_top + 40
        return 24.0, 250.0, chart_top, baseline, 250.0 / 7

    def day_at(self, position: QPointF) -> int | None:
        left, width, chart_top, baseline, slot = self.chart_geometry()
        hit = QRectF(left, chart_top - 4, width, 56)
        if not hit.contains(position):
            return None
        index = int((position.x() - left) / slot)
        return min(max(index, 0), 6)

    # -------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painters.paint_bubble(
            painter,
            self.stats,
            loading=self.loading,
            hover_day=self.hover_day,
            selected_day=self.selected_day,
            tail_x=self.tail_x,
            tail_up=self.tail_up,
            low_threshold=self.low_threshold,
        )
        painter.end()

    # -------------------------------------------------------------- 交互
    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        index = self.day_at(event.position())
        if index != self.hover_day:
            self.hover_day = index
            self.setCursor(Qt.CursorShape.PointingHandCursor if index is not None else Qt.CursorShape.ArrowCursor)
            self.update()
        self.interaction.emit()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self.hover_day is not None:
            self.hover_day = None
            self.unsetCursor()
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self.interaction.emit()
            self.context_requested.emit(event.globalPosition().toPoint())
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.interaction.emit()
        position = event.position()
        index = self.day_at(position)
        if index is not None:
            self.selected_day = None if self.selected_day == index else index
            self.update()
            return
        if self.card_rect().contains(position):
            self.refresh_requested.emit()
        else:
            self.close_requested.emit()


class DockWindow(OverlayWindow):
    activated = Signal()
    context_requested = Signal(QPoint)
    hover_changed = Signal(bool)
    drag_began = Signal()
    drag_moved = Signal(int)
    drag_finished = Signal()

    SIZE = int(painters.DOCK_DESIGN * painters.DOCK_SCALE)

    def __init__(self) -> None:
        super().__init__(self.SIZE, self.SIZE)
        self.edge = "left"
        self.style = "arrowTab"
        self.phase = 0.0
        self.hovering = False
        self._dragging = False
        self._drag_start = QPoint()
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # 约 30fps
        self._timer.timeout.connect(self._tick)

    def set_edge(self, edge: str) -> None:
        self.edge = edge
        self.update()

    def set_style(self, style: str) -> None:
        self.style = style
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        if not self.isVisible():
            return
        self.phase += 1.0 / 30.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painters.paint_dock(painter, float(self.SIZE), self.edge, self.style, self.phase, self.hovering)
        painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.hovering = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()
        self.hover_changed.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.hovering = False
        self.unsetCursor()
        self.update()
        self.hover_changed.emit(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self.context_requested.emit(event.globalPosition().toPoint())
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = False
        self._drag_start = event.globalPosition().toPoint()
        self.drag_began.emit()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        delta = event.globalPosition().toPoint() - self._drag_start
        if not self._dragging:
            if abs(delta.y()) < 3:  # macOS 吸附图标用 2px；X11 的 startDragDistance 常见 10px，太长
                return
            self._dragging = True
        self.drag_moved.emit(delta.y())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging:
            self._dragging = False
            self.drag_finished.emit()
        else:
            self.activated.emit()
        event.accept()
