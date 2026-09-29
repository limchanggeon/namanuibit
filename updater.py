"""Finding, fetching and handing off new releases.

The app does not replace itself. It checks GitHub for a newer release, downloads
the installer for this platform and verifies it, then hands it to the operating
system: the Windows setup program replaces the install, and on macOS the disk
image opens for the usual drag into Applications. Without code signing that is
the only route Gatekeeper and SmartScreen reliably let through.
"""

from pathlib import Path
import hashlib
import json
import os
import ssl
import sys
import tempfile
import threading
import time
import urllib.request

import paths

REPO = "limchanggeon/namanuibit"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
ASSETS = {
    "mac": "Namanuibit-macOS-arm64.dmg",
    "windows": "Namanuibit-windows-x64-setup.exe",
}
CHECK_TTL = 600

_check_lock = threading.Lock()
_checked = {"at": 0.0, "result": None}
_job_lock = threading.Lock()
_job = None


def current_version() -> str:
    try:
        return (paths.resources() / "VERSION").read_text().strip()
    except OSError:
        return "0.0.0"


def parse(version: str) -> tuple:
    """`v1.10.2` -> (1, 10, 2); anything unparseable sorts below every release."""
    parts = []
    for piece in version.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            return (0,)
        parts.append(int(digits))
    return tuple(parts) or (0,)


def platform() -> str | None:
    if sys.platform == "darwin":
        return "mac"
    if os.name == "nt":
        return "windows"
    return None


def _context():
    # A frozen build does not see the system certificate store reliably, so
    # verify against certifi's bundle, which PyInstaller ships with the app.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _open(url, timeout):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"namanuibit-updater/{current_version()}",
            "Accept": "application/vnd.github+json",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout, context=_context())


def fetch_latest():
    with _open(LATEST, timeout=6) as response:
        return json.load(response)


def check(force=False):
    """What the newest release is and whether this build is behind it."""
    with _check_lock:
        if (
            not force
            and _checked["result"]
            and time.time() - _checked["at"] < CHECK_TTL
        ):
            return _checked["result"]
    release = fetch_latest()
    current = current_version()
    latest = release.get("tag_name", "").lstrip("vV")
    wanted = ASSETS.get(platform() or "")
    asset = next(
        (a for a in release.get("assets", []) if a.get("name") == wanted), None
    )
    result = {
        "current": current,
        "latest": latest,
        "newer": parse(latest) > parse(current),
        "notes": release.get("body") or "",
        "page": release.get("html_url"),
        "asset": None,
    }
    if asset and str(asset.get("browser_download_url", "")).startswith(DOWNLOAD_PREFIX):
        digest = str(asset.get("digest") or "")
        result["asset"] = {
            "name": asset["name"],
            "size": int(asset.get("size") or 0),
            "url": asset["browser_download_url"],
            "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else None,
        }
    with _check_lock:
        _checked.update(at=time.time(), result=result)
    return result


def download_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path(tempfile.gettempdir())


def _download(asset, target, state):
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    try:
        with _open(asset["url"], timeout=30) as response, partial.open("wb") as out:
            total = int(response.headers.get("Content-Length") or asset["size"] or 0)
            with _job_lock:
                state["total"] = total
            while chunk := response.read(1024 * 256):
                with _job_lock:
                    if state["cancelled"]:
                        raise InterruptedError("취소했습니다.")
                out.write(chunk)
                digest.update(chunk)
                with _job_lock:
                    state["done"] += len(chunk)
        if asset["size"] and partial.stat().st_size != asset["size"]:
            raise ValueError("받은 파일 크기가 릴리스와 다릅니다. 다시 시도해 주세요.")
        if asset["sha256"] and digest.hexdigest() != asset["sha256"]:
            raise ValueError(
                "받은 파일이 릴리스와 일치하지 않습니다. 다시 시도해 주세요."
            )
        partial.replace(target)
        with _job_lock:
            state.update(finished=True, path=str(target))
    except Exception as error:
        partial.unlink(missing_ok=True)
        with _job_lock:
            state.update(finished=True, error=str(error) or error.__class__.__name__)


def start_download():
    """Fetch the installer for this platform in the background."""
    global _job
    info = check()
    if not info["newer"]:
        raise ValueError("이미 최신 버전입니다.")
    asset = info["asset"]
    if not asset:
        raise ValueError("이 운영체제용 설치 파일이 릴리스에 없습니다.")
    with _job_lock:
        if _job and not _job["finished"]:
            return dict(_job)
        target = download_dir() / asset["name"].replace(
            "Namanuibit", f"Namanuibit-{info['latest']}"
        )
        _job = dict(
            version=info["latest"],
            name=target.name,
            done=0,
            total=asset["size"],
            finished=False,
            cancelled=False,
            error=None,
            path=None,
        )
        state = _job
    threading.Thread(
        target=_download,
        args=(asset, target, state),
        name="update-download",
        daemon=True,
    ).start()
    return dict(state)


def download_state():
    with _job_lock:
        return dict(_job) if _job else None


def cancel_download():
    with _job_lock:
        if _job and not _job["finished"]:
            _job["cancelled"] = True
