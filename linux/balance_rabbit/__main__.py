"""余额兔 · Linux 版入口。

用法：
  balance-rabbit                启动桌面兔子（默认）
  balance-rabbit --stats        命令行打印余额 / 今日 / 近 7 天 / 模型
  balance-rabbit --render DIR   生成预览 PNG（含应用图标）
  balance-rabbit --enable-login / --disable-login
  balance-rabbit --version
"""

from __future__ import annotations

import os
import sys


def _flag_value(args: list[str], flag: str) -> str | None:
    if flag in args:
        index = args.index(flag)
        if index + 1 < len(args):
            return args[index + 1]
    return None


def _prepare_qt_platform() -> None:
    """有 XWayland 时优先走 xcb：Wayland 不允许程序自己定位窗口，
    宠物/吸附/气泡位置会全部失效。用户可显式设置 QT_QPA_PLATFORM 覆盖。"""
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    elif not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


def stats_cli() -> int:
    from .api import APIError, ApiClient
    from .settings import api_key
    from .util import money_smart, short_date

    key = api_key()
    if not key:
        print("error=还没有填写 API Key（可用环境变量 RABBIT_API_KEY 临时指定）")
        return 1
    try:
        stats = ApiClient().load_stats(key)
    except APIError as error:
        print("error=%s" % error)
        return 1
    balance = "%.4f" % stats.balance if stats.balance is not None else "nil"
    print("balance=%s" % balance)
    print("today=%.4f week=%.4f" % (stats.today_spend, stats.week_spend))
    print(
        "weekRequests=%d weekTokens=%d total=%s"
        % (stats.week_requests, stats.week_tokens, stats.total_requests if stats.total_requests is not None else "nil")
    )
    print(
        "account=%s multiple=%s fromAPI=%s source=%s inactive=%s recharged=%.4f"
        % (
            stats.account_user_id if stats.account_user_id is not None else "nil",
            str(stats.multiple_accounts).lower(),
            str(stats.balance_from_api).lower(),
            stats.data_source,
            str(stats.account_inactive).lower(),
            stats.week_recharged,
        )
    )
    for day in stats.daily:
        print("day %s spend=%.4f req=%d" % (short_date(day.date), day.spend, day.requests))
    for name, count in stats.top_models:
        print("model %s %d" % (name, count))
    return 0


def render_cli(directory: str) -> int:
    from PySide6.QtGui import QGuiApplication

    from .painters import render_previews

    _ = QGuiApplication.instance() or QGuiApplication([])
    written = render_previews(directory)
    for path in written:
        print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if "--version" in args:
        from .app import APP_VERSION

        print(APP_VERSION)
        return 0

    if "--stats" in args:
        return stats_cli()

    render_dir = _flag_value(args, "--render")
    if render_dir is not None:
        _prepare_qt_platform()
        return render_cli(render_dir)

    if "--enable-login" in args:
        from .settings import enable_login

        print(enable_login() or "ok")
        return 0

    if "--disable-login" in args:
        from .settings import disable_login

        disable_login()
        print("ok")
        return 0

    _prepare_qt_platform()

    from PySide6.QtWidgets import QApplication

    from .app import APP_VERSION, Controller
    from .instance import SingleInstance

    app = QApplication(sys.argv[:1])
    app.setApplicationName("余额兔")
    app.setApplicationDisplayName("余额兔")
    app.setApplicationVersion(APP_VERSION)
    app.setDesktopFileName("balance-rabbit")
    app.setQuitOnLastWindowClosed(False)

    instance = SingleInstance()
    if not instance.claim():
        instance.notify_existing()
        return 0

    controller = Controller(app, instance)
    instance.on_show = controller.show_from_external
    app.aboutToQuit.connect(instance.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
