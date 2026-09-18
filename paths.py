"""Resource and data locations for both source checkouts and frozen bundles."""

from pathlib import Path
import os
import sys

APP_NAME = "나만의빛"
FROZEN = bool(getattr(sys, "frozen", False))


def resources() -> Path:
    """Read-only files shipped with the app (static/, icons)."""
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).parent


def _platform_data_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def user_data() -> Path:
    """Writable folder for photo copies, previews and adjustment JSON.

    A frozen bundle is read-only and may sit in /Applications or Program Files,
    so the library lives under the per-user data folder instead.
    """
    override = os.environ.get("LIGHTLOOM_DATA")
    if override:
        return Path(override).expanduser()
    if not FROZEN:
        return Path(__file__).parent / "data"
    return _platform_data_root() / APP_NAME / "library"


def web_storage() -> Path:
    """Where the embedded webview keeps localStorage (imported XMP presets)."""
    return _platform_data_root() / APP_NAME / "webview"
