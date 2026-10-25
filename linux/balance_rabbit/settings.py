"""设置、API Key 存储、开机自启（全部按当前 Linux 用户隔离）。"""

from __future__ import annotations

import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP_ID = "balance-rabbit"
APP_NAME = "余额兔"
SECRET_SERVICE = "balance-rabbit"
SECRET_USER = "api-key"


def _xdg(env: str, fallback: str) -> Path:
    value = os.environ.get(env)
    return Path(value) if value else Path.home() / fallback


CONFIG_HOME = _xdg("XDG_CONFIG_HOME", ".config")
CACHE_HOME = _xdg("XDG_CACHE_HOME", ".cache")


def _resolve_dir() -> tuple[Path, bool]:
    """设置目录；不可写时依次降级，全部失败则用默认路径（内存模式）。"""
    candidates = [
        CONFIG_HOME / APP_ID,
        CACHE_HOME / APP_ID,
        Path(tempfile.gettempdir()) / APP_ID,
    ]
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / (".write-test-%d" % os.getpid())
            probe.write_bytes(b"0")
            probe.unlink()
            return path, True
        except OSError:
            continue
    return candidates[0], False


CONFIG_DIR, WRITABLE = _resolve_dir()
SETTINGS_FILE = CONFIG_DIR / "settings.json"
KEY_FILE = CONFIG_DIR / "api-key"
LOCK_FILE = CONFIG_DIR / "instance.lock"
AUTOSTART_FILE = CONFIG_HOME / "autostart" / (APP_ID + ".desktop")


# --------------------------------------------------------------------- Key


def _run(cmd: list[str], stdin: str | None = None) -> tuple[int, str]:
    try:
        result = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode, (result.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def _secret_tool_available() -> bool:
    return shutil.which("secret-tool") is not None


def key_from_keyring() -> str | None:
    if not _secret_tool_available():
        return None
    code, output = _run(["secret-tool", "lookup", "service", SECRET_SERVICE, "username", SECRET_USER])
    return output if code == 0 and output else None


def key_from_file() -> str | None:
    try:
        value = KEY_FILE.read_text(encoding="utf-8").strip()
        return value or None
    except (OSError, UnicodeDecodeError):
        return None


# 菜单构建/刷新会多次读 Key；secret-tool 是子进程，必须缓存，保存/删除时失效。
_KEY_CACHE: dict = {"loaded": False, "value": None}


def invalidate_key_cache() -> None:
    _KEY_CACHE["loaded"] = False
    _KEY_CACHE["value"] = None


def api_key() -> str | None:
    """优先级：RABBIT_API_KEY 环境变量 > 当前用户密钥环 / 私有文件。"""
    env = os.environ.get("RABBIT_API_KEY", "").strip()
    if env:
        return env
    if _KEY_CACHE["loaded"]:
        return _KEY_CACHE["value"]
    value = key_from_keyring() or key_from_file()
    _KEY_CACHE["loaded"] = True
    _KEY_CACHE["value"] = value
    return value


def has_key() -> bool:
    return api_key() is not None


def key_hint() -> str | None:
    key = api_key()
    if key is None:
        return None
    return "…" + key[-4:] if len(key) >= 4 else "…"


def save_key(key: str) -> str | None:
    """保存 Key，成功返回 None，失败返回中文错误。"""
    key = key.strip()
    if not key:
        return "API Key 不能为空"
    if _secret_tool_available():
        code, _ = _run(
            ["secret-tool", "store", "--label", "余额兔 API Key", "service", SECRET_SERVICE, "username", SECRET_USER],
            stdin=key,
        )
        if code == 0:
            try:
                KEY_FILE.unlink()
            except OSError:
                pass
            _KEY_CACHE["loaded"] = True
            _KEY_CACHE["value"] = key
            return None
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_text(key, encoding="utf-8")
        os.chmod(KEY_FILE, 0o600)
        _KEY_CACHE["loaded"] = True
        _KEY_CACHE["value"] = key
        return None
    except OSError as error:
        return "保存 API Key 失败：%s" % error


def delete_key() -> None:
    _run(["secret-tool", "clear", "service", SECRET_SERVICE, "username", SECRET_USER])
    try:
        KEY_FILE.unlink()
    except OSError:
        pass
    _KEY_CACHE["loaded"] = True
    _KEY_CACHE["value"] = None


def legacy_shared_key() -> str | None:
    """仅用于首次填写 Key 时预填旧共享配置里的 Key，不会静默生效。"""
    path = Path.home() / ".dsh" / ".credentials.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("RABBIT_API_KEY:"):
            value = line.split(":", 1)[1].strip().strip("\"'")
            return value or None
    return None


# ----------------------------------------------------------------- 设置


DEFAULTS = {
    "refresh_minutes": 10,
    "low_threshold": 20.0,
    "pet_x": None,
    "pet_y": None,
    "pet_size": 176.0,
    "edge_dock_enabled": True,
    "pet_hidden": False,
    "dock_style": "arrowTab",
    "pet_style": "cream",
    "did_welcome": False,
    "last_run_version": None,
}


class Settings:
    def __init__(self) -> None:
        self._values = dict(DEFAULTS)
        self._callbacks: list = []
        self.load()

    # -- 持久化
    @staticmethod
    def _coerce(key: str, value):
        default = DEFAULTS[key]
        try:
            if key in ("pet_x", "pet_y"):
                if value is None:
                    return None
                number = float(value)
                return number if math.isfinite(number) else None
            if key == "last_run_version":
                return value if value is None or isinstance(value, str) else default
            if key == "refresh_minutes":
                return max(0, min(1440, int(value)))
            if key == "low_threshold":
                number = float(value)
                return max(0.0, number) if math.isfinite(number) else default
            if key == "pet_size":
                number = float(value)
                return max(96.0, min(320.0, number)) if math.isfinite(number) else default
            if key == "dock_style":
                return value if value in ("bubbleGlow", "bubbleRing", "arrowTab", "arcLine") else default
            if key == "pet_style":
                return value if value in ("cream", "sky", "line", "chibi") else default
            if isinstance(default, bool):
                return value if isinstance(value, bool) else default
            if isinstance(default, str):
                return value if isinstance(value, str) else default
        except (TypeError, ValueError):
            return default
        return default

    def load(self) -> None:
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return
        if isinstance(raw, dict):
            for key in DEFAULTS:
                if key in raw:
                    self._values[key] = self._coerce(key, raw[key])

    def save(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            temporary = SETTINGS_FILE.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(self._values, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, SETTINGS_FILE)
        except OSError:
            pass

    def on_change(self, callback) -> None:
        self._callbacks.append(callback)

    def _notify(self) -> None:
        self.save()
        for callback in list(self._callbacks):
            try:
                callback()
            except Exception:  # 回调失败不能影响设置本身
                pass

    # -- 属性
    def _get(self, key):
        return self._values.get(key, DEFAULTS[key])

    def _set(self, key, value, notify: bool = True) -> None:
        if self._values.get(key) == value:
            return
        self._values[key] = value
        if notify:
            self._notify()
        else:
            self.save()

    @property
    def refresh_minutes(self) -> int:
        return int(self._get("refresh_minutes") or 0)

    @refresh_minutes.setter
    def refresh_minutes(self, value: int) -> None:
        self._set("refresh_minutes", int(value))

    @property
    def low_threshold(self) -> float:
        return float(self._get("low_threshold") or 0)

    @low_threshold.setter
    def low_threshold(self, value: float) -> None:
        self._set("low_threshold", float(value))

    @property
    def pet_x(self) -> float | None:
        value = self._get("pet_x")
        return float(value) if value is not None else None

    @pet_x.setter
    def pet_x(self, value: float | None) -> None:
        self._set("pet_x", value, notify=False)

    @property
    def pet_y(self) -> float | None:
        value = self._get("pet_y")
        return float(value) if value is not None else None

    @pet_y.setter
    def pet_y(self, value: float | None) -> None:
        self._set("pet_y", value, notify=False)

    @property
    def pet_size(self) -> float:
        return float(self._get("pet_size") or 176)

    @pet_size.setter
    def pet_size(self, value: float) -> None:
        self._set("pet_size", float(value))

    @property
    def edge_dock_enabled(self) -> bool:
        return bool(self._get("edge_dock_enabled"))

    @edge_dock_enabled.setter
    def edge_dock_enabled(self, value: bool) -> None:
        self._set("edge_dock_enabled", bool(value))

    @property
    def pet_hidden(self) -> bool:
        return bool(self._get("pet_hidden"))

    @pet_hidden.setter
    def pet_hidden(self, value: bool) -> None:
        self._set("pet_hidden", bool(value))

    @property
    def pet_style(self) -> str:
        return str(self._get("pet_style") or "cream")

    @pet_style.setter
    def pet_style(self, value: str) -> None:
        self._set("pet_style", value)

    @property
    def dock_style(self) -> str:
        return str(self._get("dock_style") or "arrowTab")

    @dock_style.setter
    def dock_style(self, value: str) -> None:
        self._set("dock_style", value)

    @property
    def did_welcome(self) -> bool:
        return bool(self._get("did_welcome"))

    @did_welcome.setter
    def did_welcome(self, value: bool) -> None:
        self._set("did_welcome", bool(value))

    @property
    def last_run_version(self) -> str | None:
        return self._get("last_run_version")

    @last_run_version.setter
    def last_run_version(self, value: str | None) -> None:
        self._set("last_run_version", value, notify=False)


# --------------------------------------------------------------- 开机自启


def launcher_path() -> Path | None:
    """安装脚本创建的启动器；开发模式下没有。"""
    candidate = Path.home() / ".local" / "bin" / APP_ID
    return candidate if candidate.exists() else None


def app_root() -> Path:
    return Path(__file__).resolve().parent.parent


def login_item_command() -> list[str]:
    env_exec = os.environ.get("BALANCE_RABBIT_EXEC")
    if env_exec:
        return shlex.split(env_exec)
    launcher = launcher_path()
    if launcher is not None:
        return [str(launcher)]
    return [sys.executable, "-m", "balance_rabbit"]


def login_item_exec_line() -> str:
    """拼 .desktop 的 Exec：开发模式要带上 PYTHONPATH 才能 import 包。"""
    command = login_item_command()
    parts = [shlex.quote(part) for part in command]
    if os.environ.get("BALANCE_RABBIT_EXEC") or launcher_path() is not None:
        return " ".join(parts)
    return "env PYTHONPATH=%s %s" % (shlex.quote(str(app_root())), " ".join(parts))


def login_item_enabled() -> bool:
    return AUTOSTART_FILE.exists()


def enable_login() -> str | None:
    exec_line = login_item_exec_line()
    desktop = """[Desktop Entry]
Type=Application
Name=余额兔
Comment=桌面宠物余额监控
Exec={exec_line}
Icon={icon}
Terminal=false
X-GNOME-Autostart-enabled=true
""".format(exec_line=exec_line, icon=icon_path())
    try:
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(desktop, encoding="utf-8")
        os.chmod(AUTOSTART_FILE, 0o644)
        return None
    except OSError as error:
        return "写入自启配置失败：%s" % error


def disable_login() -> None:
    try:
        AUTOSTART_FILE.unlink()
    except OSError:
        pass


def icon_path() -> Path:
    """安装后 <app>/icon.png；开发模式用仓库里的 build/icon.png。"""
    for candidate in (app_root() / "icon.png", app_root() / "build" / "icon.png"):
        if candidate.exists():
            return candidate
    return app_root() / "icon.png"
