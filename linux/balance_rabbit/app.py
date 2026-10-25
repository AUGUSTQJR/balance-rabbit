"""应用控制器：窗口编排、托盘、定时刷新、吸附状态机、账号与 API Key。"""

from __future__ import annotations

import subprocess
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QPropertyAnimation, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCursor, QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
    QVBoxLayout,
)

from . import painters, settings as settings_module
from .api import APIError, ApiClient
from .models import Stats
from .settings import Settings
from .util import money2
from .windows import BubbleWindow, DockWindow, PetWindow

APP_VERSION = "1.0.0"


class _Worker(QObject):
    finished = Signal(object)

    def __init__(self, api: ApiClient, key_provider) -> None:
        super().__init__()
        self.api = api
        self.key_provider = key_provider

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            key = self.key_provider()
            if not key:
                raise APIError("还没有填写 API Key")
            result = self.api.load_stats(key)
        except Exception as error:  # 任何异常都要回到 UI 线程显示，不能让 is_loading 卡死
            result = error
        self.finished.emit(result)


class Controller(QObject):
    def __init__(self, app: QApplication, single_instance=None) -> None:
        super().__init__()
        self.app = app
        self.instance = single_instance
        self.settings = Settings()
        self.api = ApiClient()
        self.worker = _Worker(self.api, settings_module.api_key)

        self.stats: Stats | None = None
        self.is_loading = False
        self.bubble_visible = False
        self.last_low_notify_at: datetime | None = None
        self.storage_warning_shown = False

        self.pet: PetWindow | None = None
        self.bubble: BubbleWindow | None = None
        self.dock: DockWindow | None = None
        self.tray: QSystemTrayIcon | None = None
        self.menu: QMenu | None = None
        self._animations: list[QPropertyAnimation] = []
        self._bubble_fade: QPropertyAnimation | None = None

        # 边缘吸附状态
        self.dock_edge: str | None = None
        self.dock_anchor = 0.0
        self.dock_hover_expanded = False
        self.dock_screen = None
        self.dock_drag_start = QPoint()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.bubble_hide_timer = QTimer(self)
        self.bubble_hide_timer.setSingleShot(True)
        self.bubble_hide_timer.timeout.connect(self.hide_bubble)

        self.worker.finished.connect(self._on_stats)
        self.settings.on_change(self._on_settings_changed)

        self._build_windows()
        self._build_tray()
        self._schedule_timer()
        self._connect_screens()

        QTimer.singleShot(0, lambda: self.refresh())
        QTimer.singleShot(800, self._welcome_once)
        QTimer.singleShot(1000, self._run_startup_account_check)
        QTimer.singleShot(1200, self._show_storage_warning)

    # ------------------------------------------------------------ 窗口搭建

    def _build_windows(self) -> None:
        side = int(self._clamp_size(self.settings.pet_size))
        pet = PetWindow(side)
        pet.set_pet_style(self.settings.pet_style)
        pet.activated.connect(self._pet_clicked)
        pet.context_requested.connect(self._show_context_menu)
        pet.dragged.connect(lambda _point: self.hide_bubble(False))
        pet.drag_finished.connect(self._pet_drag_finished)
        pet.resized_by_wheel.connect(self._resize_by_wheel)
        pet.setToolTip("余额兔")
        self.pet = pet
        self._place_pet_initial()
        if not self.settings.pet_hidden:
            pet.show_without_activating()
        else:
            pet.hide()

        bubble = BubbleWindow()
        bubble.refresh_requested.connect(lambda: self.refresh(show_bubble=True))
        bubble.close_requested.connect(self.hide_bubble)
        bubble.interaction.connect(self._schedule_bubble_hide)
        bubble.context_requested.connect(self._show_context_menu)
        bubble.set_low_threshold(self.settings.low_threshold)
        bubble.hide()
        self.bubble = bubble

    def _place_pet_initial(self) -> None:
        assert self.pet is not None
        size = self.pet.width()
        saved_x, saved_y = self.settings.pet_x, self.settings.pet_y
        if saved_x is not None and saved_y is not None:
            from PySide6.QtCore import QRect

            saved_frame = QRect(int(saved_x), int(saved_y), size, size)
            if any(screen.availableGeometry().intersects(saved_frame) for screen in QGuiApplication.screens()):
                self.pet.move(int(saved_x), int(saved_y))
                return
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        right = available.left() + available.width()
        bottom = available.top() + available.height()
        self.pet.move(right - size - 36, bottom - size - 24)

    def _build_tray(self) -> None:
        icon = QIcon(painters.icon_pixmap(64))
        self.app.setWindowIcon(icon)
        menu = QMenu()
        menu.aboutToShow.connect(self._populate_menu)
        self.menu = menu
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray = QSystemTrayIcon(icon, self)
            tray.setToolTip("余额兔")
            tray.setContextMenu(menu)
            tray.activated.connect(self._tray_activated)
            tray.show()
            self.tray = tray
        self._update_tray()

    def _bind_screen(self, screen) -> None:
        screen.geometryChanged.connect(lambda _rect: self._handle_screen_change())

    def _connect_screens(self) -> None:
        def on_screen_added(screen) -> None:
            self._bind_screen(screen)
            self._handle_screen_change()

        self.app.screenAdded.connect(on_screen_added)
        self.app.screenRemoved.connect(lambda _screen: self._handle_screen_change())
        self.app.primaryScreenChanged.connect(lambda _screen: self._handle_screen_change())
        for screen in QGuiApplication.screens():
            self._bind_screen(screen)

    # ------------------------------------------------------------ 数据刷新

    def _schedule_timer(self) -> None:
        self.refresh_timer.stop()
        minutes = self.settings.refresh_minutes
        if minutes > 0:
            self.refresh_timer.start(minutes * 60 * 1000)

    def refresh(self, show_bubble: bool = False) -> None:
        if self.is_loading:
            return
        self.is_loading = True
        assert self.pet is not None and self.bubble is not None
        self.pet.set_loading(True)
        self.bubble.set_stats(self.stats, loading=True)
        if show_bubble:
            self.show_bubble()
        self.worker.start()

    def _on_stats(self, result) -> None:
        self.is_loading = False
        assert self.pet is not None and self.bubble is not None
        self.pet.set_loading(False)
        if isinstance(result, Exception):
            message = result.message if isinstance(result, APIError) else str(result)
            stats = self.stats or Stats()
            stats.error = message
            self.stats = stats
        else:
            self.stats = result
        value = self.stats
        self.pet.set_low_balance(value.is_low(self.settings.low_threshold))
        self.bubble.set_stats(value, loading=False)
        self.bubble.reset_selection()
        self._update_tray()
        if self.bubble_visible:
            self._layout_bubble()
        if not isinstance(result, Exception):
            self._check_low_balance(value)

    def _check_low_balance(self, value: Stats) -> None:
        threshold = self.settings.low_threshold
        if value.balance is None or threshold <= 0 or value.balance >= threshold:
            return
        now = datetime.now()
        if self.last_low_notify_at and (now - self.last_low_notify_at).total_seconds() < 6 * 3600:
            return
        self.last_low_notify_at = now
        body = "余额 %s 已低于 ¥%d，记得充值～" % (money2(value.balance), int(threshold))
        self._notify("余额兔提醒", body)

    def _notify(self, title: str, body: str) -> None:
        icon = settings_module.icon_path()
        command = ["notify-send", "-a", "余额兔", "-u", "normal"]
        if Path(icon).exists():
            command += ["-i", str(icon)]
        command += [title, body]
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
        if self.tray is not None:
            self.tray.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 8000)

    # -------------------------------------------------------------- 气泡

    def _pet_clicked(self) -> None:
        if self.settings.pet_hidden:
            return
        if self.dock_edge is not None:
            self.undock()
            return
        if self.bubble_visible:
            self.hide_bubble()
        else:
            self.show_bubble()
        stale = self.stats is None or (datetime.now() - self.stats.updated_at).total_seconds() > 30
        if stale and not self.is_loading:
            self.refresh()

    def show_bubble(self) -> None:
        assert self.bubble is not None
        self.bubble_hide_timer.stop()
        self.bubble.set_stats(self.stats, loading=self.is_loading)
        self.bubble.set_low_threshold(self.settings.low_threshold)
        self.bubble.reset_selection()
        self._layout_bubble()
        self.bubble.setWindowOpacity(0.0)
        self.bubble.show_without_activating()
        if self._bubble_fade is not None:
            self._bubble_fade.stop()
        self._bubble_fade = self._fade(self.bubble, 0.0, 1.0, 160)
        self.bubble_visible = True
        self._schedule_bubble_hide()

    def _layout_bubble(self) -> None:
        assert self.bubble is not None and self.pet is not None
        host_widget = self.dock if self.dock_edge is not None and self.dock is not None else self.pet
        host = host_widget.frameGeometry()
        screen = self._screen_for_widget(host_widget) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        right = available.left() + available.width()
        bottom = available.top() + available.height()
        width, height = self.bubble.width(), self.bubble.height()
        center_x = host.x() + host.width() // 2
        x = center_x - width // 2
        # 与 macOS 一致：默认放在兔子/指示器上方（尖角朝下指向兔子），上方放不下才放下面。
        y = host.top() - height - 4
        tail_up = False
        if y < available.top():
            y = host.bottom() + 4
            tail_up = True
        x = min(max(available.left() + 4, x), right - width - 4)
        y = min(max(available.top() + 4, y), bottom - height - 4)
        self.bubble.set_tail(min(max(center_x - x, 26), width - 26), tail_up)
        self.bubble.move(x, y)

    def _schedule_bubble_hide(self) -> None:
        if self.bubble_visible:
            self.bubble_hide_timer.start(15_000)

    def hide_bubble(self, animated: bool = True) -> None:
        self.bubble_hide_timer.stop()
        assert self.bubble is not None
        self.bubble.reset_selection()
        if not self.bubble_visible:
            self.bubble.hide()
            return
        self.bubble_visible = False
        if self._bubble_fade is not None:
            self._bubble_fade.stop()
        if animated:
            self._bubble_fade = self._fade(self.bubble, self.bubble.windowOpacity(), 0.0, 150, self.bubble.hide)
        else:
            self.bubble.hide()

    def _fade(self, widget, start: float, end: float, duration: int, finished=None) -> QPropertyAnimation:
        animation = QPropertyAnimation(widget, b"windowOpacity", self)
        animation.setDuration(duration)
        animation.setStartValue(start)
        animation.setEndValue(end)
        if finished is not None:
            animation.finished.connect(finished)
        animation.finished.connect(lambda: self._animations.remove(animation) if animation in self._animations else None)
        self._animations.append(animation)
        animation.start()
        return animation

    # ------------------------------------------------------------ 吸附

    def _clamp_size(self, requested: float) -> float:
        screen = self._screen_for_widget(self.pet) or QGuiApplication.primaryScreen()
        # 极窄屏也不要让下限低于 96，否则窗口会小于设计画布
        maximum = max(96.0, min(320.0, screen.availableGeometry().height() - 40))
        return min(max(requested, 96.0), maximum)

    def _dock_target_edge(self) -> str | None:
        if not self.settings.edge_dock_enabled or self.settings.pet_hidden or self.pet is None:
            return None
        screen = self._screen_for_widget(self.pet) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        frame = self.pet.frameGeometry()
        right = available.left() + available.width()
        candidates = [
            ("left", frame.left() - available.left()),
            ("right", right - (frame.left() + frame.width())),
        ]
        edge, distance = min(candidates, key=lambda pair: pair[1])
        return edge if distance <= 28 else None

    def _dock_geometry(self, edge: str, expanded: bool) -> tuple[int, int]:
        screen = self._screen_for_widget(self.dock) or self.dock_screen or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        right = available.left() + available.width()
        size = DockWindow.SIZE
        hidden = int(painters.DOCK_EDGE_LINE * painters.DOCK_SCALE)  # 24
        peek = 14 if expanded else 0
        low_y = available.top()
        high_y = max(low_y, available.bottom() - size)
        y = min(max(low_y, int(self.dock_anchor - size / 2)), high_y)
        if edge == "left":
            x = available.left() - hidden + peek
        else:
            x = right - size + hidden - peek
        return x, y

    def dock_to(self, edge: str) -> None:
        assert self.pet is not None
        screen = self._screen_for_widget(self.pet) or QGuiApplication.primaryScreen()
        self.dock_screen = screen
        self.dock_edge = edge
        self.dock_hover_expanded = False
        self.hide_bubble(False)
        available = screen.availableGeometry()
        anchor = self.pet.frameGeometry().center().y()
        low = available.top() + DockWindow.SIZE / 2
        high = available.bottom() - DockWindow.SIZE / 2
        self.dock_anchor = min(max(anchor, low), high)

        if self.dock is None:
            dock = DockWindow()
            dock.activated.connect(self.undock)
            dock.context_requested.connect(self._show_context_menu)
            dock.hover_changed.connect(self._dock_hover_changed)
            dock.drag_began.connect(self._dock_drag_began)
            dock.drag_moved.connect(self._dock_drag_moved)
            dock.drag_finished.connect(self._dock_drag_finished)
            self.dock = dock
        dock = self.dock
        dock.set_edge(edge)
        dock.set_style(self.settings.dock_style)
        x, y = self._dock_geometry(edge, False)
        dock.move(x, y)
        dock.setWindowOpacity(0.0)
        dock.show_without_activating()
        self._fade(dock, 0.0, 1.0, 150)
        self._fade(self.pet, 1.0, 0.0, 100, self._hide_pet_after_dock)
        self.settings.pet_x = None
        self.settings.pet_y = None

    def _hide_pet_after_dock(self) -> None:
        assert self.pet is not None
        if self.dock_edge is not None:
            self.pet.hide()
        self.pet.setWindowOpacity(1.0)

    def _dock_hover_changed(self, hovering: bool) -> None:
        if self.dock_edge is None or self.dock is None:
            return
        if hovering == self.dock_hover_expanded:
            return
        self.dock_hover_expanded = hovering
        x, y = self._dock_geometry(self.dock_edge, hovering)
        self._animate_move(self.dock, x, y, 140)

    def _animate_move(self, widget, x: int, y: int, duration: int) -> None:
        animation = QPropertyAnimation(widget, b"pos", self)
        animation.setDuration(duration)
        animation.setStartValue(widget.pos())
        animation.setEndValue(QPoint(x, y))
        self._animations.append(animation)
        animation.finished.connect(lambda: self._animations.remove(animation) if animation in self._animations else None)
        animation.start()

    def _dock_drag_began(self) -> None:
        if self.dock is not None:
            self.dock_drag_start = self.dock.pos()
        if self.dock_hover_expanded:
            self._dock_hover_changed(False)

    def _dock_drag_moved(self, delta_y: int) -> None:
        if self.dock is None or self.dock_edge is None:
            return
        screen = self._screen_for_widget(self.dock) or self.dock_screen or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        size = DockWindow.SIZE
        y = self.dock_drag_start.y() + delta_y
        y = min(max(available.top(), y), max(available.top(), available.bottom() - size))
        x, _ = self._dock_geometry(self.dock_edge, self.dock_hover_expanded)
        self.dock.move(x, y)
        self.dock_anchor = y + size / 2
        if self.bubble_visible:
            self._layout_bubble()

    def undock(self) -> None:
        if self.dock_edge is None or self.pet is None:
            return
        edge = self.dock_edge
        screen = self._screen_for_widget(self.dock) or self.dock_screen or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        size = self.pet.width()
        right = available.left() + available.width()
        if edge == "left":
            x = available.left() + 8
        else:
            x = right - size - 8
        y = self.dock_anchor - size / 2
        y = min(max(available.top() + 6, y), available.bottom() - size - 6)
        if self.dock is not None:
            self.dock.hide()
        self.dock_edge = None
        self.dock_screen = None
        self.dock_hover_expanded = False
        self.pet.move(int(x), int(y))
        self.pet.setWindowOpacity(0.0)
        self.pet.show_without_activating()
        self._fade(self.pet, 0.0, 1.0, 180)
        self.save_pet_position()
        self.pet.update()
        if self.bubble_visible:
            self._layout_bubble()

    def _dock_drag_finished(self) -> None:
        # 吸附位置本来就不持久化（重启后一定是站立的大兔子），这里不写设置。
        pass

    # -------------------------------------------------------------- 拖动

    def _pet_drag_finished(self) -> None:
        if self.pet is None:
            return
        edge = self._dock_target_edge()
        if edge is not None:
            self.dock_to(edge)
        else:
            self._clamp_pet_on_screen()
            self.save_pet_position()

    def _screen_for_widget(self, widget):
        """取控件所在屏幕；屏幕被拔掉时 screen() 可能失效，逐级兜底。"""
        if widget is not None:
            screen = QGuiApplication.screenAt(widget.frameGeometry().center())
            if screen is not None:
                return screen
            try:
                screen = widget.screen()
            except RuntimeError:
                screen = None
            if screen is not None:
                return screen
        return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()

    def _clamp_pet_on_screen(self) -> None:
        if self.pet is None:
            return
        screen = self._screen_for_widget(self.pet) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        frame = self.pet.frameGeometry()
        right = available.left() + available.width()
        bottom = available.top() + available.height()
        x = min(max(available.left(), frame.left()), right - frame.width())
        y = min(max(available.top(), frame.top()), bottom - frame.height())
        if x != frame.left() or y != frame.top():
            self.pet.move(x, y)

    def save_pet_position(self) -> None:
        if self.pet is None:
            return
        self.settings.pet_x = float(self.pet.x())
        self.settings.pet_y = float(self.pet.y())

    # -------------------------------------------------------------- 缩放

    def _resize_by_wheel(self, delta: int) -> None:
        self.apply_pet_size(self.settings.pet_size + delta)

    def apply_pet_size(self, requested: float) -> None:
        if self.pet is None:
            return
        side = int(self._clamp_size(requested))
        old = self.pet.width()
        if side == old:
            return
        bottom = self.pet.y() + old
        self.pet.set_side(side)
        self.pet.move(self.pet.x() + (old - side) // 2, bottom - side)
        self._clamp_pet_on_screen()
        self.settings.pet_size = float(side)
        if self.dock_edge is None:
            self.save_pet_position()
        if self.bubble_visible:
            self._layout_bubble()

    # -------------------------------------------------------------- 托盘

    def _update_tray(self) -> None:
        if self.tray is None:
            return
        if self.is_loading:
            self.tray.setToolTip("余额兔 · 查询中…")
            return
        balance = self.stats.balance if self.stats else None
        if balance is None:
            self.tray.setToolTip("余额兔 · 余额 —")
            return
        text = "余额兔 · 余额 %s" % money2(balance)
        if self.stats is not None and self.stats.is_low(self.settings.low_threshold):
            text = "⚠ " + text
        if self.stats is not None:
            text += " · %s 更新" % self.stats.updated_at.strftime("%H:%M")
        self.tray.setToolTip(text)

    def _tray_activated(self, reason) -> None:
        if reason != QSystemTrayIcon.ActivationReason.Trigger:
            return
        if self.settings.pet_hidden:
            self._toggle_pet()
        elif self.dock_edge is not None:
            self.undock()
        elif self.bubble_visible:
            self.hide_bubble()
        else:
            self.show_bubble()

    def _show_context_menu(self, global_pos: QPoint) -> None:
        if self.menu is None:
            return
        self.menu.popup(global_pos)

    # -------------------------------------------------------------- 菜单

    def _action(self, menu: QMenu, title: str, handler, checkable: bool = False, checked: bool = False) -> QAction:
        action = QAction(title, menu)
        if checkable:
            action.setCheckable(True)
            action.setChecked(checked)
        action.triggered.connect(handler)
        menu.addAction(action)
        return action

    def _disabled(self, menu: QMenu, title: str) -> None:
        action = QAction(title, menu)
        action.setEnabled(False)
        menu.addAction(action)

    def _populate_menu(self) -> None:
        menu = self.menu
        if menu is None:
            return
        # QMenu.clear() 不会销毁 addMenu 创建的子菜单，必须手动释放，否则常驻程序会无界增长
        for child in menu.findChildren(QMenu):
            child.setParent(None)
            child.deleteLater()
        menu.clear()
        value = self.stats
        balance = value.balance if value else None

        self._disabled(menu, "余额 %s" % money2(balance) if balance is not None else "余额 —")
        if value is not None:
            if value.error:
                self._disabled(menu, "⚠︎ %s" % value.error)
            if value.account_user_id is not None:
                self._disabled(menu, "账户 #%d" % value.account_user_id)
            if value.multiple_accounts:
                self._disabled(menu, "⚠︎ 当前 Key 可见多个账户，已按账户过滤")
            hint = settings_module.key_hint()
            if hint:
                self._disabled(menu, "当前 Key 尾号 %s" % hint)
            if value.week_recharged > 0:
                self._disabled(menu, "近 7 天充值 %s" % money2(value.week_recharged))
            if value.account_inactive:
                # is_active 语义未知：朋友账号能正常调用也会返回 false，不能当停用告警
                self._disabled(menu, "接口状态：is_active = false（如能正常使用可忽略）")

        menu.addSeparator()
        self._action(menu, "刷新余额", lambda: self.refresh(show_bubble=True))
        self._action(menu, "复制余额", self._copy_balance)
        menu.addSeparator()
        self._action(menu, "打开商店 / 充值", self._open_store)
        menu.addSeparator()

        refresh_menu = menu.addMenu("自动刷新")
        for minutes in (0, 5, 10, 30, 60):
            title = "关闭定时刷新" if minutes == 0 else "每 %d 分钟" % minutes
            action = QAction(title, refresh_menu)
            action.setCheckable(True)
            action.setChecked(self.settings.refresh_minutes == minutes)
            action.triggered.connect(lambda _checked=False, m=minutes: self._set_refresh_minutes(m))
            refresh_menu.addAction(action)

        threshold_menu = menu.addMenu("低余额提醒")
        for threshold in (0.0, 10.0, 20.0, 50.0, 100.0):
            title = "关闭提醒" if threshold == 0 else "低于 ¥%d 时提醒" % int(threshold)
            action = QAction(title, threshold_menu)
            action.setCheckable(True)
            action.setChecked(abs(self.settings.low_threshold - threshold) < 0.01)
            action.triggered.connect(lambda _checked=False, t=threshold: self._set_threshold(t))
            threshold_menu.addAction(action)

        self._action(
            menu,
            "开机自动启动",
            self._toggle_login,
            checkable=True,
            checked=settings_module.login_item_enabled(),
        )
        menu.addSeparator()

        size_menu = menu.addMenu("兔子大小")
        for title, preset in (("小 · 120", 120), ("中 · 176", 176), ("大 · 240", 240), ("特大 · 300", 300)):
            action = QAction(title, size_menu)
            action.setCheckable(True)
            action.setChecked(abs(self.pet.width() - preset) < 2 if self.pet else False)
            action.triggered.connect(lambda _checked=False, p=preset: self.apply_pet_size(p))
            size_menu.addAction(action)
        size_menu.addSeparator()
        self._action(size_menu, "放大", lambda: self.apply_pet_size(self.settings.pet_size + 16))
        self._action(size_menu, "缩小", lambda: self.apply_pet_size(self.settings.pet_size - 16))
        hint = QAction("Ctrl / Alt + 滚轮可自由缩放", size_menu)
        hint.setEnabled(False)
        size_menu.addAction(hint)

        face_menu = menu.addMenu("兔子造型")
        for key, title in (
            ("cream", "奶油软萌"),
            ("sky", "蓝色圆环 · 弯弯眼"),
            ("line", "细线手绘"),
            ("chibi", "粉腮呆萌"),
        ):
            action = QAction(title, face_menu)
            action.setCheckable(True)
            action.setChecked(self.settings.pet_style == key)
            action.triggered.connect(lambda _checked=False, k=key: self._set_pet_style(k))
            face_menu.addAction(action)

        if self.dock_edge is not None:
            self._action(menu, "从边缘弹出", self.undock)
        self._action(
            menu,
            "拖到屏幕边缘自动吸附",
            self._toggle_dock_enabled,
            checkable=True,
            checked=self.settings.edge_dock_enabled,
        )

        style_menu = menu.addMenu("边缘图标样式")
        for title, style in (
            ("发光气泡", "bubbleGlow"),
            ("电子圆环", "bubbleRing"),
            ("箭头标签", "arrowTab"),
            ("极细弧线", "arcLine"),
        ):
            action = QAction(title, style_menu)
            action.setCheckable(True)
            action.setChecked(self.settings.dock_style == style)
            action.triggered.connect(lambda _checked=False, s=style: self._set_dock_style(s))
            style_menu.addAction(action)

        if self.settings.pet_hidden:
            self._action(menu, "显示兔子", self._toggle_pet)
        elif self.tray is None:
            self._disabled(menu, "隐藏兔子（本桌面没有系统托盘，隐藏后无法找回）")
        else:
            self._action(menu, "隐藏兔子", self._toggle_pet)
        self._action(menu, "把兔子放回屏幕右下角", self._reset_pet_position)
        menu.addSeparator()
        self._action(menu, "更换 API Key（换账号）…" if settings_module.has_key() else "设置 API Key…", lambda: self._show_key_dialog(False))
        self._action(menu, "关于账号与 API Key…", self._show_key_info)
        menu.addSeparator()
        self._disabled(menu, "余额兔 v%s" % APP_VERSION)
        self._action(menu, "退出余额兔", self.quit)

    def _copy_balance(self) -> None:
        if self.stats is None or self.stats.balance is None:
            return
        QApplication.clipboard().setText("%.2f" % self.stats.balance)
        self.show_bubble()

    def _open_store(self) -> None:
        QDesktopServices.openUrl(QUrl("https://www.rabbitj.top/shop"))

    def _set_refresh_minutes(self, minutes: int) -> None:
        self.settings.refresh_minutes = minutes
        self._schedule_timer()
        self.refresh(show_bubble=True)

    def _set_threshold(self, threshold: float) -> None:
        self.settings.low_threshold = threshold
        if self.stats is not None:
            self.pet.set_low_balance(self.stats.is_low(threshold))
        if self.bubble is not None:
            self.bubble.set_low_threshold(threshold)
        self.show_bubble()

    def _toggle_login(self) -> None:
        if settings_module.login_item_enabled():
            settings_module.disable_login()
        else:
            error = settings_module.enable_login()
            if error:
                QMessageBox.warning(None, "开启开机自启失败", error)

    def _toggle_dock_enabled(self) -> None:
        self.settings.edge_dock_enabled = not self.settings.edge_dock_enabled
        if not self.settings.edge_dock_enabled and self.dock_edge is not None:
            self.undock()

    def _set_pet_style(self, style: str) -> None:
        self.settings.pet_style = style
        if self.pet is not None:
            self.pet.set_pet_style(style)

    def _set_dock_style(self, style: str) -> None:
        self.settings.dock_style = style
        if self.dock is not None:
            self.dock.set_style(style)

    def _toggle_pet(self) -> None:
        self.settings.pet_hidden = not self.settings.pet_hidden
        assert self.pet is not None
        if self.settings.pet_hidden:
            self.pet.hide()
            if self.dock is not None:
                self.dock.hide()
            self.dock_edge = None
            self.dock_screen = None
            self.dock_hover_expanded = False
            self.hide_bubble(False)
        elif self.dock_edge is not None and self.dock is not None:
            x, y = self._dock_geometry(self.dock_edge, False)
            self.dock.move(x, y)
            self.dock.setWindowOpacity(1.0)
            self.dock.show_without_activating()
            self.show_bubble()
        else:
            self.pet.setWindowOpacity(1.0)
            self.pet.show_without_activating()
            self.show_bubble()

    def _reset_pet_position(self) -> None:
        assert self.pet is not None
        if self.dock_edge is not None:
            if self.settings.pet_hidden:
                if self.dock is not None:
                    self.dock.hide()
                self.dock_edge = None
                self.dock_screen = None
                self.dock_hover_expanded = False
            else:
                self.undock()
        screen = self._screen_for_widget(self.pet) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        size = self.pet.width()
        right = available.left() + available.width()
        bottom = available.top() + available.height()
        self.pet.move(right - size - 36, bottom - size - 24)
        self.save_pet_position()
        self.pet.setWindowOpacity(1.0)
        if not self.settings.pet_hidden:
            self.pet.show_without_activating()
            self.show_bubble()

    def _on_settings_changed(self) -> None:
        assert self.pet is not None and self.bubble is not None
        self.pet.set_low_balance(self.stats.is_low(self.settings.low_threshold) if self.stats else False)
        self.bubble.set_low_threshold(self.settings.low_threshold)
        self._schedule_timer()
        self._update_tray()

    # -------------------------------------------------------- 屏幕变化

    def _handle_screen_change(self) -> None:
        if self.dock_edge is not None and self.dock is not None:
            self.dock_screen = self._screen_for_widget(self.dock) or QGuiApplication.primaryScreen()
            available = self.dock_screen.availableGeometry()
            low = available.top() + DockWindow.SIZE / 2
            high = available.bottom() - DockWindow.SIZE / 2
            self.dock_anchor = min(max(self.dock_anchor, low), high)
            x, y = self._dock_geometry(self.dock_edge, self.dock_hover_expanded)
            self.dock.move(x, y)
        elif self.pet is not None:
            self._clamp_pet_on_screen()
            self.save_pet_position()
        if self.bubble_visible:
            self._layout_bubble()

    # ------------------------------------------------------ 账号 / Key

    def _welcome_once(self) -> None:
        if self.settings.did_welcome:
            return
        self.settings.did_welcome = True
        self.show_bubble()

    def _run_startup_account_check(self) -> None:
        version = APP_VERSION
        previous = self.settings.last_run_version
        if not settings_module.has_key():
            self._show_key_dialog(True)
        elif previous != version:
            self._confirm_account()
        self.settings.last_run_version = version

    def _confirm_account(self) -> None:
        hint = settings_module.key_hint() or ""
        text = (
            "检测到本机已保存 API Key（尾号 %s）。\n\n"
            "如果这台电脑现在换别人使用，继续用这个 Key 会显示原来账号的余额。\n"
            "要继续使用这个 Key 吗？" % hint
        )
        box = QMessageBox()
        box.setWindowTitle("余额兔 · 确认账号")
        box.setText(text)
        keep = box.addButton("是，继续使用", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("否，重新填写", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not keep:
            self._show_key_dialog(False)

    def _show_key_dialog(self, first_time: bool) -> None:
        dialog = QDialog()
        dialog.setWindowTitle("填写你自己的 rabbitj.top API Key")
        layout = QVBoxLayout(dialog)
        text = (
            "每个 Linux 用户 / 每台电脑都要填自己的 Key。\n"
            "填了别人的 Key 就会显示别人的余额。\n\n"
            "Key 以 sk- 开头，可在 rabbitj.top 的账号页复制；"
            "会保存到本机密钥环（没有密钥环时保存为仅本人可读的文件）。"
        )
        if settings_module.key_hint():
            text += "\n\n当前已保存的 Key 尾号：" + (settings_module.key_hint() or "")
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        field = QLineEdit()
        field.setPlaceholderText("sk-...")
        field.setEchoMode(QLineEdit.EchoMode.Password)
        if first_time and not settings_module.has_key():
            legacy = settings_module.legacy_shared_key()
            if legacy:
                field.setText(legacy)
        layout.addWidget(field)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("稍后再说" if first_time else "取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        field.setFocus()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        key = field.text().strip()
        if not key:
            return
        error = settings_module.save_key(key)
        if error:
            QMessageBox.warning(None, "保存失败", error)
            return
        self.settings.last_run_version = APP_VERSION
        self.refresh(show_bubble=True)

    def _show_key_info(self) -> None:
        hint = settings_module.key_hint() or "未设置"
        account = "#%d" % self.stats.account_user_id if self.stats and self.stats.account_user_id else "未知"
        text = (
            "当前 Key 尾号：%s\n账户：%s\n\n"
            "每个 Linux 用户 / 每台电脑都要填自己的 Key，填了别人的 Key 就会显示别人的余额。\n"
            "Key 只保存在本机密钥环或仅本人可读的文件里，不会写到任何共享文件。\n"
            "换账号时用菜单「更换 API Key（换账号）…」。\n\n"
            "数据来自 rabbitj.top（anyGPT）的账户接口。"
        ) % (hint, account)
        QMessageBox.information(None, "关于账号与 API Key", text)

    def _show_storage_warning(self) -> None:
        if settings_module.WRITABLE or self.storage_warning_shown:
            return
        self.storage_warning_shown = True
        QMessageBox.warning(
            None,
            "无法保存设置",
            "当前用户目录不可写，API Key 与设置只能本次运行有效。\n"
            "请检查 ~/.config 的权限。",
        )

    # -------------------------------------------------------------- 外部唤起

    def show_from_external(self) -> None:
        if self.settings.pet_hidden:
            self._toggle_pet()
        if self.dock_edge is not None:
            self.undock()
        if self.pet is not None:
            self.pet.setWindowOpacity(1.0)
            self.pet.show_without_activating()
        self.show_bubble()
        self.refresh()

    # -------------------------------------------------------------- 退出

    def quit(self) -> None:
        self.refresh_timer.stop()
        self.bubble_hide_timer.stop()
        for widget in (self.pet, self.bubble, self.dock):
            if widget is not None:
                widget.hide()
        if self.tray is not None:
            self.tray.hide()
        if self.instance is not None:
            self.instance.close()
        self.app.quit()
