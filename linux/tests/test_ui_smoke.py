"""界面冒烟测试：在 offscreen 模式下把窗口/菜单/吸附状态机跑一遍，防止改崩。

    QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_ui_smoke -v

只验证「不抛异常 + 状态正确」，真实置顶/透明/托盘仍需 Linux 实机验证。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="balance-rabbit-test-")
os.environ.pop("RABBIT_API_KEY", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    HAS_QT = True
except ImportError:  # pragma: no cover - 没装 PySide6 时跳过
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "没有安装 PySide6，跳过界面冒烟测试")
class UiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from balance_rabbit.app import APP_VERSION, Controller
        from balance_rabbit.settings import Settings, save_key

        # 预置一个假 Key + 版本号，避免启动时弹出「填 Key / 确认账号」模态框
        save_key("sk-test-ui-smoke")
        settings = Settings()
        settings.last_run_version = APP_VERSION
        settings.did_welcome = True

        self.controller = Controller(self.app)

        class _OfflineApi:
            def load_stats(self, _key):
                from balance_rabbit.api import APIError

                raise APIError("测试模式不联网")

        self.controller.worker.api = _OfflineApi()
        self._spin(0.2)

    def tearDown(self) -> None:
        self.controller.quit()
        self._spin(0.1)

    def _spin(self, seconds: float) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

    def test_windows_and_bubble(self) -> None:
        controller = self.controller
        self.assertIsNotNone(controller.pet)
        self.assertIsNotNone(controller.bubble)
        controller.show_bubble()
        self._spin(0.1)
        self.assertTrue(controller.bubble_visible)
        controller.hide_bubble(False)
        self.assertFalse(controller.bubble_visible)

    def test_dock_cycle(self) -> None:
        controller = self.controller
        controller.dock_to("left")
        self._spin(0.2)
        self.assertEqual(controller.dock_edge, "left")
        controller._dock_hover_changed(True)
        controller._dock_drag_moved(20)
        self._spin(0.1)
        controller.undock()
        self._spin(0.2)
        self.assertIsNone(controller.dock_edge)
        self.assertIsNotNone(controller.dock)
        self.assertFalse(controller.dock.isVisible())

        controller.dock_to("right")
        self._spin(0.2)
        self.assertEqual(controller.dock_edge, "right")
        controller._dock_hover_changed(False)
        controller.undock()
        self._spin(0.1)

    def test_resize_and_menu(self) -> None:
        controller = self.controller
        controller.apply_pet_size(240)
        self.assertEqual(controller.pet.width(), 240)
        controller.apply_pet_size(96)
        self.assertEqual(controller.pet.width(), 96)
        controller.apply_pet_size(400)
        self.assertLessEqual(controller.pet.width(), 320)

        controller._populate_menu()
        titles = [action.text() for action in controller.menu.actions()]
        self.assertTrue(any("刷新余额" in title for title in titles))
        self.assertTrue(any("边缘图标样式" in title for title in titles))
        self.assertTrue(any("退出余额兔" in title for title in titles))

        controller._toggle_pet()
        self.assertTrue(controller.settings.pet_hidden)
        controller._toggle_pet()
        self.assertFalse(controller.settings.pet_hidden)
        controller._reset_pet_position()

    def test_painters(self) -> None:
        from balance_rabbit import painters

        directory = tempfile.mkdtemp(prefix="balance-rabbit-preview-")
        written = painters.render_previews(directory)
        self.assertGreaterEqual(len(written), 14)
        for path in written:
            self.assertGreater(os.path.getsize(path), 200, path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
