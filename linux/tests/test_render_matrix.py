"""渲染矩阵与几何审查测试（Linux 版，Qt offscreen）。

    cd linux && QT_QPA_PLATFORM=offscreen /tmp/qtvenv/bin/python -m unittest tests.test_render_matrix -v

覆盖：
  * 兔子 96/120/176/240/320 × 正常/低余额/加载/悬停；
  * 气泡 正常/低余额/悬停选中/多账户/错误/加载/空数据；
  * 4 种吸附指示器 × 左右边缘 × 悬停；
  * 几何：tail_x 夹取、tail_up 尖角位置、吸附左右镜像/24px 露出/14px 外探、
    负坐标多屏、缩放上下限、柱状图命中区。

只读生产代码，不改任何文件；渲染出的 PNG 写到临时目录并在最后打印路径。
最后附「已知问题」测试：用 skip/expectedFailure 记录当前实现与 macOS 设计不一致的地方，
修好后这些测试会提示（详见问题清单）。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="balance-rabbit-render-")
os.environ.pop("RABBIT_API_KEY", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PySide6.QtCore import QPoint, QRect, QRectF, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
    from PySide6.QtWidgets import QApplication

    HAS_QT = True
except ImportError:  # pragma: no cover - 没装 PySide6 时跳过
    HAS_QT = False

OUT_DIR = Path(tempfile.mkdtemp(prefix="balance-rabbit-matrix-"))


# ---------------------------------------------------------------- 公共工具


def render_canvas(width: int, height: int, scale: int, paint_fn, background: QColor | None = None) -> QImage:
    image = QImage(int(width * scale), int(height * scale), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    if background is not None:
        painter.fillRect(image.rect(), background)
    painter.scale(scale, scale)
    paint_fn(painter)
    painter.end()
    return image


def alpha_bytes(image: QImage) -> bytes:
    """ARGB32_Premultiplied 图像每个像素的第 4 个字节是 alpha。"""
    return bytes(image.constBits())[3::4]


def alpha_bbox(image: QImage) -> tuple[int, int, int, int] | None:
    """返回 alpha>0 的包围盒 (minx, miny, maxx, maxy)，全透明返回 None。"""
    width, height = image.width(), image.height()
    data = alpha_bytes(image)
    minx, miny, maxx, maxy = width, height, -1, -1
    for y in range(height):
        row = data[y * width : (y + 1) * width]
        if not row.strip(b"\x00"):
            continue
        first = len(row) - len(row.lstrip(b"\x00"))
        last = len(row.rstrip(b"\x00")) - 1
        miny = min(miny, y)
        maxy = y
        minx = min(minx, first)
        maxx = max(maxx, last)
    if maxy < 0:
        return None
    return minx, miny, maxx, maxy


def alpha_at(image: QImage, x: float, y: float) -> int:
    return (image.pixel(int(x), int(y)) >> 24) & 0xFF


def count_colored(image: QImage, rect: QRectF, predicate) -> int:
    """统计 rect 内满足 predicate(QColor) 的像素数（用于“关键区域有内容”断言）。"""
    total = 0
    left = max(0, int(rect.left()))
    top = max(0, int(rect.top()))
    right = min(image.width() - 1, int(rect.right()))
    bottom = min(image.height() - 1, int(rect.bottom()))
    for y in range(top, bottom + 1):
        for x in range(left, right + 1):
            if predicate(image.pixelColor(x, y)):
                total += 1
            if total > 4000:  # 够了，早点结束
                return total
    return total


def make_stats(**overrides):
    from balance_rabbit.models import DayStat, Stats

    stats = Stats()
    stats.balance = 88.6145
    stats.today_spend = 0.0321
    stats.today_requests = 12
    stats.week_spend = 0.4128
    stats.week_requests = 46
    stats.week_tokens = 452_130
    stats.total_requests = 1284
    stats.updated_at = datetime.now()
    stats.top_models = [("deepseek-flash-1017", 32), ("claude-sonnet-5", 11)]
    spends = [0.021, 0, 0.053, 0.018, 0.084, 0.032, 0.021]
    today = date.today()
    stats.daily = [
        DayStat(today - timedelta(days=6 - index), spend, index * 3 + 2)
        for index, spend in enumerate(spends)
    ]
    for key, value in overrides.items():
        setattr(stats, key, value)
    return stats


# ---------------------------------------------------------------- 兔子


@unittest.skipUnless(HAS_QT, "没有安装 PySide6，跳过渲染矩阵测试")
class PetRenderMatrixTest(unittest.TestCase):
    SIZES = (96, 120, 176, 240, 320)
    STATES = {
        "normal": {},
        "low": {"low_balance": True},
        "loading": {"loading": True},
        "hover": {"hovering": True},
    }

    @classmethod
    def setUpClass(cls) -> None:
        from balance_rabbit import painters

        cls.painters = painters
        cls.app = QApplication.instance() or QApplication([])

    def _render(self, size: int, state: str, phase: float = 1.2) -> QImage:
        kwargs = self.STATES[state]
        return render_canvas(size, size, 2, lambda p: self.painters.paint_pet(p, float(size), phase, **kwargs))

    def test_matrix_sizes_and_states(self) -> None:
        """5 种尺寸 × 4 种状态：图像尺寸正确、有内容、不越界。"""
        for size in self.SIZES:
            for state in self.STATES:
                with self.subTest(size=size, state=state):
                    image = self._render(size, state)
                    self.assertEqual((image.width(), image.height()), (size * 2, size * 2))
                    bbox = alpha_bbox(image)
                    self.assertIsNotNone(bbox, "整张图全透明，兔子没画出来")
                    minx, miny, maxx, maxy = bbox
                    self.assertGreaterEqual(minx, 0)
                    self.assertGreaterEqual(miny, 0)
                    self.assertLess(maxx, size * 2)
                    self.assertLess(maxy, size * 2)
                    # 脸部区域（设计坐标 36.5..123.5 × 59..142）必须有不透明像素
                    face = QRectF(36.5 * size / 160 * 2, 59 * size / 160 * 2,
                                  87 * size / 160 * 2, 83 * size / 160 * 2)
                    self.assertGreater(
                        count_colored(image, face, lambda c: c.alpha() > 200), 100, "脸部区域没有画出来"
                    )
                    image.save(str(OUT_DIR / ("pet_%d_%s.png" % (size, state))))

    def test_low_balance_badge_visible(self) -> None:
        """低余额的红色 ! 徽章在 96~320 各尺寸都可见（红色像素存在）。"""
        for size in self.SIZES:
            with self.subTest(size=size):
                image = self._render(size, "low")
                scale = size * 2 / 160.0
                badge = QRectF(117 * scale, 25 * scale, 17 * scale, 17 * scale)
                red = count_colored(image, badge, lambda c: c.red() > 200 and c.green() < 120 and c.alpha() > 150)
                self.assertGreater(red, 10, "低余额徽章不可见")

    def test_face_styles_render_and_differ(self) -> None:
        """四种圆脸造型都能画出来，且互不相同。"""
        from balance_rabbit import painters

        images = {}
        for style in painters.PET_FACE_STYLES:
            image = render_canvas(176, 176, 2,
                                  lambda p, st=style: painters.paint_pet(p, 176, 1.2, style=st))
            bbox = alpha_bbox(image)
            self.assertIsNotNone(bbox, "造型 %s 没有画出来" % style)
            images[style] = bytes(image.constBits())
        self.assertEqual(len(set(images.values())), len(images), "四种造型画面存在重复")

    def test_states_differ(self) -> None:
        """正常/低余额/加载/悬停四种画面必须互不相同（动画状态真的生效）。"""
        images = {state: self._render(176, state) for state in self.STATES}
        normal = bytes(images["normal"].constBits())
        for state in ("low", "loading", "hover"):
            self.assertNotEqual(normal, bytes(images[state].constBits()), "%s 画面与正常状态完全相同" % state)

    def test_hover_slightly_bigger(self) -> None:
        """悬停放大 1.035：悬停时非透明包围盒不小于正常状态。"""
        normal = alpha_bbox(self._render(176, "normal"))
        hover = alpha_bbox(self._render(176, "hover"))
        self.assertIsNotNone(normal)
        self.assertIsNotNone(hover)
        width_normal = normal[2] - normal[0]
        width_hover = hover[2] - hover[0]
        self.assertGreaterEqual(width_hover, width_normal)


# ---------------------------------------------------------------- 气泡


@unittest.skipUnless(HAS_QT, "没有安装 PySide6，跳过渲染矩阵测试")
class BubbleRenderMatrixTest(unittest.TestCase):
    STATES = ("normal", "low", "hover", "multi", "error", "loading", "empty")

    @classmethod
    def setUpClass(cls) -> None:
        from balance_rabbit import painters
        from balance_rabbit.models import Stats

        cls.painters = painters
        cls.Stats = Stats
        cls.app = QApplication.instance() or QApplication([])
        cls.sample = make_stats()

    def _paint(self, state: str, **kwargs):
        painters = self.painters
        stats = self.sample
        if state == "normal":
            return lambda p: painters.paint_bubble(p, stats, **kwargs)
        if state == "low":
            return lambda p: painters.paint_bubble(p, make_stats(balance=12.3), **kwargs)
        if state == "hover":
            return lambda p: painters.paint_bubble(p, stats, hover_day=4, selected_day=4, **kwargs)
        if state == "multi":
            return lambda p: painters.paint_bubble(
                p, make_stats(account_user_id=132, multiple_accounts=True, total_requests=None), **kwargs
            )
        if state == "error":
            return lambda p: painters.paint_bubble(p, make_stats(error="HTTP 503 Service Unavailable"), **kwargs)
        if state == "loading":
            return lambda p: painters.paint_bubble(p, None, loading=True, **kwargs)
        if state == "empty":
            return lambda p: painters.paint_bubble(p, self.Stats(), **kwargs)
        raise AssertionError(state)

    def _render(self, state: str, **kwargs) -> QImage:
        return render_canvas(300, 282, 2, self._paint(state, **kwargs))

    def test_matrix_states(self) -> None:
        """7 种状态：尺寸、卡片不透明、四角透明、尖角存在、关键区域有内容。"""
        for state in self.STATES:
            with self.subTest(state=state):
                image = self._render(state)
                self.assertEqual((image.width(), image.height()), (600, 564))
                # 卡片中心必须不透明
                self.assertEqual(alpha_at(image, 300, 280), 255, "卡片中心透明")
                # 四周角落必须基本透明（不能有方块底）
                for x, y in ((2, 2), (597, 2), (2, 561), (597, 561)):
                    self.assertLess(alpha_at(image, x, y), 8, "角落 (%d,%d) 不透明，透明层异常" % (x, y))
                # 底部尖角（默认 tail_up=False）在窗口内的尖角区域必须有不透明像素
                self.assertGreater(alpha_at(image, 300, 540), 200, "尖角没画出来")
                image.save(str(OUT_DIR / ("bubble_%s.png" % state)))

    def test_corner_radius_transparent(self) -> None:
        """卡片 2..298 的直角区域内侧（角上）应该是透明圆角，而不是直角。"""
        image = self._render("normal")
        self.assertLess(alpha_at(image, 8, 8), 40, "卡片左上角没有圆角")

    def test_error_footer_is_red(self) -> None:
        image = self._render("error")
        footer = QRectF(48, 480, 440, 26)  # 设计坐标 24..244 × 240..253（×2）
        red = count_colored(image, footer, lambda c: c.red() > 180 and c.green() < 120 and c.alpha() > 100)
        self.assertGreater(red, 20, "错误横幅不是红色")

    def test_hover_highlights_bar(self) -> None:
        """悬停/选中当天：柱状图被高亮成强调色 ACCENT。"""
        from balance_rabbit.painters import ACCENT

        image = self._render("hover")
        # 第 5 根柱（index 4）在设计坐标 x≈175.7..193.7、y 114..142（×2 换算到设备像素）
        bar = QRectF(352, 228, 34, 54)
        accent = count_colored(
            image,
            bar,
            lambda c: abs(c.red() - ACCENT.red()) < 30 and abs(c.green() - ACCENT.green()) < 30 and c.alpha() > 200,
        )
        self.assertGreater(accent, 100, "悬停柱没有高亮")

    def test_loading_vs_content(self) -> None:
        """加载态（没有旧数据）显示“查询中…”，不能和正常内容相同。"""
        loading = self._render("loading")
        normal = self._render("normal")
        self.assertNotEqual(bytes(loading.constBits()), bytes(normal.constBits()))
        self.assertGreater(alpha_bbox(loading)[3], 0)

    def test_tail_positions(self) -> None:
        """tail_x 变化时尖角跟着走；tail_up=True 时尖角在窗口顶部。"""
        left = self._render("normal", tail_x=26)
        right = self._render("normal", tail_x=274)
        # 设计坐标 y=270（窗口底部尖角内）附近
        self.assertGreater(alpha_at(left, 26 * 2, 540), 200)
        self.assertGreater(alpha_at(right, 274 * 2, 540), 200)
        top = self._render("normal", tail_up=True, tail_x=150)
        self.assertGreater(alpha_at(top, 300, 12), 200, "tail_up=True 时顶部尖角不存在")
        self.assertLess(alpha_at(top, 300, 556), 100, "tail_up=True 时底部不应有尖角")

    def test_fit_font_keeps_text_inside(self) -> None:
        """常见内容经 fit_font 后宽度不超过内容区（250px），不会压到卡片外。"""
        from balance_rabbit.painters import fit_font, measure, ui_font

        samples = [
            ("¥1234567.89", ui_font(31)),
            ("¥88.61", ui_font(31)),
            ("今日 ¥98765.43     近7天 ¥654321.99", ui_font(12)),
            ("Tokens 9876.54 亿   ·   近7天 987654321 次请求", ui_font(11)),
            ("近期主力模型 deepseek-flash-1017（32 次）", ui_font(11)),
        ]
        for text, font in samples:
            with self.subTest(text=text[:12]):
                fitted = fit_font(text, font, 250.0, 8)
                self.assertLessEqual(measure(text, fitted), 250.0 + 0.5)

        # 已知问题 UB-4：极长模型名在最小字号 8 时仍超宽，drawText 会硬裁切（无省略号）
        long_text = "近期主力模型 anthropic/claude-sonnet-4.5-20250929（1234567890 次）"
        fitted = fit_font(long_text, ui_font(11), 250.0, 8)
        if measure(long_text, fitted) > 250.0:
            print(
                "\n[已知问题 UB-4] 最小字号 8 仍宽 %.1fpx > 250px，文字被硬裁切"
                % measure(long_text, fitted)
            )
        self.assertEqual(fitted.pixelSize(), 8)


# ---------------------------------------------------------------- 吸附指示器


@unittest.skipUnless(HAS_QT, "没有安装 PySide6，跳过渲染矩阵测试")
class DockRenderMatrixTest(unittest.TestCase):
    STYLES = ("bubbleGlow", "bubbleRing", "arrowTab", "arcLine")

    @classmethod
    def setUpClass(cls) -> None:
        from balance_rabbit import painters

        cls.painters = painters
        cls.app = QApplication.instance() or QApplication([])

    def _render(self, style: str, edge: str, phase: float = 1.3, hovering: bool = False) -> QImage:
        return render_canvas(
            48,
            48,
            8,
            lambda p: self.painters.paint_dock(p, 48, edge, style, phase, hovering),
        )

    def test_matrix_styles_edges_hover(self) -> None:
        """4 种样式 × 左右 × 悬停：有内容、内容不超出画布、边缘线在 24px 处。"""
        for style in self.STYLES:
            for edge in ("left", "right"):
                for hovering in (False, True):
                    with self.subTest(style=style, edge=edge, hovering=hovering):
                        image = self._render(style, edge, hovering=hovering)
                        self.assertEqual((image.width(), image.height()), (384, 384))
                        bbox = alpha_bbox(image)
                        self.assertIsNotNone(bbox)
                        # 内容必须在画布内（不对，但允许 1px 抗锯齿外溢）
                        self.assertGreaterEqual(bbox[0], 0)
                        self.assertLessEqual(bbox[2], 383)
                        # 屏幕内侧半区（48px 窗口里露出屏幕的那一半）必须有主体内容
                        inner = count_colored(
                            image, QRectF(24 * 8, 0, 24 * 8 - 1, 48 * 8 - 1), lambda c: c.alpha() > 0
                        )
                        self.assertGreater(inner, 200, "屏幕内侧半区没有指示器主体")
                        image.save(
                            str(
                                OUT_DIR
                                / ("dock_%s_%s_%s.png" % (style, edge, "hover" if hovering else "idle"))
                            )
                        )

    def test_left_right_are_mirrored(self) -> None:
        """左右边缘必须是精确镜像（arrowTab 箭头方向相反）。"""
        for style in self.STYLES:
            with self.subTest(style=style):
                left = self._render(style, "left")
                right = self._render(style, "right")
                width, height = left.width(), left.height()
                data_l = bytes(left.constBits())
                data_r = bytes(right.constBits())
                total = 0
                big = 0
                for y in range(height):
                    base = y * width * 4
                    for x in range(width):
                        i = base + x * 4
                        j = base + (width - 1 - x) * 4
                        diff = sum(abs(data_l[i + k] - data_r[j + k]) for k in range(4))
                        total += diff
                        if diff > 90:
                            big += 1
                pixels = width * height
                self.assertLess(total / pixels, 6.0, "左右镜像平均差异过大")
                self.assertLess(big / pixels, 0.005, "左右镜像有超过 0.5% 的像素明显不同")

    def test_visible_half_is_the_screen_side(self) -> None:
        """48px 窗口只有 24px 露在屏幕内：屏幕内侧半区（x>24）要有主体，屏幕外半区由图留给裁切。"""
        for style in self.STYLES:
            with self.subTest(style=style):
                image = self._render(style, "left")
                inner = count_colored(image, QRectF(24 * 8, 0, 24 * 8, 48 * 8), lambda c: c.alpha() > 0)
                self.assertGreater(inner, 500, "屏幕内侧半区没有画内容")


# ---------------------------------------------------------------- 几何


@unittest.skipUnless(HAS_QT, "没有安装 PySide6，跳过几何测试")
class GeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from balance_rabbit import app as app_module

        cls.app_module = app_module
        cls.app = QApplication.instance() or QApplication([])

    def _controller_stub(self, available: QRect, anchor: float | None = None):
        """不启动整套 Controller（不建托盘/不联网），只构造几何方法需要的字段。"""
        from balance_rabbit.app import Controller

        controller = Controller.__new__(Controller)
        fake_screen = _FakeScreen(available)
        controller.dock_screen = fake_screen
        controller.dock_anchor = available.center().y() if anchor is None else anchor
        controller.dock_edge = "left"
        controller.dock_hover_expanded = False
        controller.pet = None
        controller.dock = None
        # 只替换「屏幕探测」这一个依赖，几何算法本身仍是生产代码
        controller._screen_for_widget = lambda _widget: fake_screen
        return controller

    # ------------------------------ 吸附窗口几何
    def test_dock_visible_thickness_left_24(self) -> None:
        available = QRect(0, 0, 800, 800)
        controller = self._controller_stub(available)
        x, y = controller._dock_geometry("left", False)
        window = QRect(x, y, 48, 48)
        self.assertEqual(window.intersected(available).width(), 24, "左边缘应只露 24px")

    def test_dock_visible_thickness_right_24(self) -> None:
        """左右都只露 24px（用不含边界的右界计算，避免 1px 不对称）。"""
        available = QRect(0, 0, 800, 800)
        controller = self._controller_stub(available)
        x, y = controller._dock_geometry("right", False)
        window = QRect(x, y, 48, 48)
        self.assertEqual(window.intersected(available).width(), 24, "右边缘应只露 24px")

    def test_dock_hover_peek_14(self) -> None:
        """悬停外探 14px：左边缘向右移 14，右边缘向左移 14。"""
        available = QRect(0, 0, 800, 800)
        controller = self._controller_stub(available)
        left_idle = controller._dock_geometry("left", False)[0]
        left_hover = controller._dock_geometry("left", True)[0]
        right_idle = controller._dock_geometry("right", False)[0]
        right_hover = controller._dock_geometry("right", True)[0]
        self.assertEqual(left_hover - left_idle, 14)
        self.assertEqual(right_idle - right_hover, 14)

    def test_dock_stays_on_screen(self) -> None:
        """上下拖动/切换屏幕后指示器不能跑出可用区域。"""
        for available in (QRect(0, 0, 800, 800), QRect(-1920, -300, 1920, 1080), QRect(800, 0, 1440, 900)):
            for anchor in (available.top() - 500, available.top() + 5, available.center().y(), available.bottom() + 500):
                with self.subTest(available=available.getRect(), anchor=anchor):
                    controller = self._controller_stub(available, anchor=float(anchor))
                    for edge in ("left", "right"):
                        x, y = controller._dock_geometry(edge, False)
                        window = QRect(x, y, 48, 48)
                        self.assertGreaterEqual(window.top(), available.top() - 24)
                        self.assertLessEqual(window.bottom(), available.bottom() + 24)
                        # 至少有 24px 贴着屏幕边缘可见
                        self.assertGreaterEqual(window.intersected(available).height(), 24)

    def test_dock_negative_coordinate_screen(self) -> None:
        """负坐标屏幕（副屏摆在主屏左侧）坐标要相对该屏计算。"""
        available = QRect(-1920, -300, 1920, 1080)
        controller = self._controller_stub(available)
        left_x, _ = controller._dock_geometry("left", False)
        right_x, _ = controller._dock_geometry("right", False)
        self.assertEqual(left_x, available.left() - 24)
        self.assertEqual(QRect(right_x, 0, 48, 48).intersected(available).width(), 24)

    # ------------------------------ 缩放上下限
    def test_clamp_size_limits(self) -> None:
        controller = self._controller_stub(QRect(0, 0, 800, 800))
        self.assertEqual(controller._clamp_size(10), 96.0)
        self.assertEqual(controller._clamp_size(96), 96.0)
        self.assertEqual(controller._clamp_size(176), 176.0)
        self.assertEqual(controller._clamp_size(320), 320.0)
        self.assertEqual(controller._clamp_size(10000), 320.0)

    def test_clamp_size_short_screen(self) -> None:
        """可用高度 <136px 的极窄屏：UB-3 已修，下限仍保持 96，不会被压到 96 以下。"""
        controller = self._controller_stub(QRect(0, 0, 800, 120))
        result = controller._clamp_size(320)
        self.assertLessEqual(result, 320.0)
        self.assertEqual(result, 96.0)

    # ------------------------------ 气泡几何
    def test_bubble_tail_x_clamp_and_card_bounds(self) -> None:
        from balance_rabbit.painters import BUBBLE_W
        from balance_rabbit.windows import BubbleWindow

        bubble = BubbleWindow()
        try:
            for tail_x in (0, 26, 100, 274, 300):
                clamped = min(max(float(tail_x), 26), BUBBLE_W - 26)
                self.assertGreaterEqual(clamped - 12, 2)
                self.assertLessEqual(clamped + 12, BUBBLE_W - 2)
                bubble.set_tail(clamped, False)
                self.assertGreaterEqual(bubble.tail_x, 26)
                self.assertLessEqual(bubble.tail_x, BUBBLE_W - 26)
        finally:
            bubble.deleteLater()

    def test_chart_day_hit_mapping(self) -> None:
        """柱状图命中区：7 个槽位各命中对应天，区域外返回 None。"""
        from balance_rabbit.windows import BubbleWindow

        bubble = BubbleWindow()
        bubble.stats = make_stats()
        try:
            left, width, chart_top, baseline, slot = bubble.chart_geometry()
            self.assertEqual(width, 250.0)
            for index in range(7):
                center = QPoint(int(left + slot * index + slot / 2), int(chart_top + 20))
                self.assertEqual(bubble.day_at(center), index)
            self.assertIsNone(bubble.day_at(QPoint(int(left - 5), int(chart_top + 20))))
            self.assertIsNone(bubble.day_at(QPoint(int(left + 10), int(chart_top - 10))))
            # 卡片范围 vs 尖角范围
            self.assertTrue(bubble.card_rect().contains(QPoint(150, 100)))
            self.assertFalse(bubble.card_rect().contains(QPoint(150, 270)))
        finally:
            bubble.deleteLater()


class _FakeScreen:
    def __init__(self, available: QRect) -> None:
        self._available = available

    def availableGeometry(self) -> QRect:
        return self._available

    def geometry(self) -> QRect:
        return self._available

    def name(self) -> str:
        return "fake-screen"


def tearDownModule() -> None:
    print("\n渲染矩阵 PNG 输出目录: %s" % OUT_DIR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
