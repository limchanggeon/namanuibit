"""Native desktop shell: runs the render server in-process behind a webview window."""

from pathlib import Path
import os
import socket
import subprocess
import sys
import threading
import time

import paths

os.environ.setdefault("LIGHTLOOM_DESKTOP", "1")

WINDOW_TITLE = "나만의빛"
FORMAT_FILTER = {
    "jpeg": ("JPEG 이미지 (*.jpg)", ".jpg"),
    "png": ("PNG 이미지 (*.png)", ".png"),
    "tiff": ("TIFF 이미지 (*.tif)", ".tif"),
}


def free_port() -> int:
    """A loopback port for the render server; LIGHTLOOM_PORT pins it for debugging."""
    pinned = os.environ.get("LIGHTLOOM_PORT")
    if pinned:
        return int(pinned)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server(threading.Thread):
    """Uvicorn on a loopback port, started before the window is shown."""

    daemon = True

    def __init__(self, port: int) -> None:
        super().__init__(name="lightloom-server")
        import uvicorn
        from app import app

        self.port = port
        self._server = uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=port, log_level="warning", access_log=False
            )
        )

    def run(self) -> None:
        self._server.run()

    def wait_until_ready(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if getattr(self._server, "started", False):
                return True
            if not self.is_alive():
                return False
            time.sleep(0.05)
        return False

    def stop(self) -> None:
        self._server.should_exit = True


def reveal(path: Path) -> None:
    """Show a file or folder in Finder / Explorer / the desktop file manager."""
    try:
        if sys.platform == "darwin":
            subprocess.run(
                ["open", "-R", str(path)] if path.is_file() else ["open", str(path)],
                check=False,
            )
        elif os.name == "nt":
            if path.is_file():
                subprocess.run(["explorer", f"/select,{path}"], check=False)
            else:
                os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.run(
                ["xdg-open", str(path if path.is_dir() else path.parent)], check=False
            )
    except Exception:
        pass


class Bridge:
    """Methods the page calls through `window.pywebview.api`."""

    def __init__(self) -> None:
        self.window = None

    def save_dialog(self, filename: str, fmt: str = "jpeg"):
        import webview

        label, suffix = FORMAT_FILTER.get(fmt, FORMAT_FILTER["jpeg"])
        result = self.window.create_file_dialog(
            webview.SAVE_DIALOG,
            directory=str(Path.home() / "Pictures")
            if (Path.home() / "Pictures").is_dir()
            else str(Path.home()),
            save_filename=filename,
            file_types=(f"{label}",),
        )
        if not result:
            return None
        chosen = Path(result if isinstance(result, str) else result[0])
        if chosen.suffix.lower() not in {
            suffix,
            ".jpeg" if suffix == ".jpg" else suffix,
        }:
            chosen = chosen.with_suffix(suffix)
        return str(chosen)

    def reveal(self, path: str):
        reveal(Path(path))

    def open_library(self):
        reveal(paths.user_data())

    def platform(self):
        return {
            "desktop": True,
            "os": "mac"
            if sys.platform == "darwin"
            else "windows"
            if os.name == "nt"
            else "linux",
        }


def build_menu(bridge: Bridge):
    from webview.menu import Menu, MenuAction, MenuSeparator

    def click(element_id: str):
        return lambda: bridge.window.evaluate_js(
            f"document.getElementById({element_id!r})?.click()"
        )

    return [
        Menu(
            "사진",
            [
                MenuAction("사진 불러오기…", click("importTop")),
                MenuAction("XMP 프리셋 가져오기…", click("xmpButton")),
                MenuSeparator(),
                MenuAction("내보내기…", click("exportTop")),
                MenuSeparator(),
                MenuAction("라이브러리 폴더 열기", bridge.open_library),
            ],
        ),
        Menu(
            "보정",
            [
                MenuAction("실행 취소", click("undo")),
                MenuAction("다시 실행", click("redo")),
                MenuSeparator(),
                MenuAction("보정 초기화", click("reset")),
                MenuAction("원본과 비교", click("compare")),
                MenuSeparator(),
                MenuAction("라이브러리 보기", click("libraryTab")),
                MenuAction("현상 보기", click("editTab")),
                MenuSeparator(),
                MenuAction("화면 맞춤", click("fit")),
                MenuAction("100%", click("zoom")),
                MenuAction("단축키 보기", click("shortcutsButton")),
            ],
        ),
    ]


def use_dark_titlebar() -> None:
    """The window chrome would otherwise follow a light system theme."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApp, NSAppearance

        NSApp.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
    except Exception:
        pass


def main() -> int:
    import webview

    port = free_port()
    server = Server(port)
    server.start()
    if not server.wait_until_ready():
        return 1

    bridge = Bridge()
    storage = paths.web_storage()
    storage.mkdir(parents=True, exist_ok=True)

    bridge.window = webview.create_window(
        WINDOW_TITLE,
        f"http://127.0.0.1:{port}/",
        js_api=bridge,
        width=1440,
        height=920,
        min_size=(1040, 680),
        background_color="#17191B",
        text_select=True,  # page CSS handles selection; blanket blocking breaks inputs
        confirm_close=False,
    )
    bridge.window.events.closed += server.stop
    webview.start(
        use_dark_titlebar,
        menu=build_menu(bridge),
        private_mode=False,  # keeps imported XMP presets in localStorage
        storage_path=str(storage),
        debug=os.environ.get("LIGHTLOOM_DEBUG") == "1",
    )
    server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
