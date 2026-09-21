from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import json, uuid, os, shutil, threading, time
import numpy as np
import rawpy  # noqa: F401  -- re-exported so tests can stub the decoder
from PIL import Image
from adjustments import ui_config
from xmp import parse as parse_xmp
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import paths
import render_worker
from render_worker import RASTER, RAW, decode, encode
from settings import FORMATS, Settings

ROOT = paths.resources()
DATA = paths.user_data()
DATA.mkdir(exist_ok=True, parents=True)
DESKTOP = os.environ.get("LIGHTLOOM_DESKTOP") == "1"
LOCK = threading.RLock()
RENDER_LOCK = threading.Lock()
JOBS = {}
JOB_LOCK = threading.Lock()
POOL = None
POOL_LOCK = threading.Lock()
app = FastAPI(title="나만의빛")


@app.middleware("http")
async def no_store(request, call_next):
    """Never let the webview cache the app itself.

    The window keeps its cache on disk between launches, so without this an
    updated build can come up running the previous version's page. Everything
    here is served from loopback, so caching buys nothing anyway.
    """
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
FORMAT_PATTERN = "^(" + "|".join(FORMATS) + ")$"


class Export(BaseModel):
    settings: Settings
    format: str = Field("jpeg", pattern=FORMAT_PATTERN)
    quality: int = Field(95, ge=10, le=100)
    long_edge: int = Field(0, ge=0, le=16000)
    dest: str | None = None


class BatchItem(BaseModel):
    id: str
    settings: Settings | None = None


class Batch(BaseModel):
    photos: list[BatchItem] = Field(min_length=1, max_length=500)
    format: str = Field("jpeg", pattern=FORMAT_PATTERN)
    quality: int = Field(95, ge=10, le=100)
    long_edge: int = Field(0, ge=0, le=16000)
    # A single photo may name its exact file; several need a folder to fill.
    dest: str | None = None
    folder: str | None = None


def record(pid):
    if not pid.isalnum() or not (DATA / pid / "meta.json").exists():
        raise HTTPException(404, "사진을 찾을 수 없습니다.")
    return json.loads((DATA / pid / "meta.json").read_text())


def save(pid, meta):
    with LOCK:
        tmp = DATA / pid / f"{uuid.uuid4().hex}.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False))
        tmp.replace(DATA / pid / "meta.json")


def pool():
    """One worker process, started the first time a full-size render is asked for.

    Spawning costs a second or two and most sessions never export, so it is not
    worth paying at launch.
    """
    global POOL
    with POOL_LOCK:
        if POOL is None:
            POOL = ProcessPoolExecutor(max_workers=1)
        return POOL


def develop(source, s, fmt="jpeg", quality=95, long_edge=0, dest=None):
    """Full-size render, off in the worker process so the window keeps painting."""
    args = (str(source), s.model_dump(), fmt, quality, long_edge, dest)
    try:
        return pool().submit(render_worker.develop, *args).result()
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error))
    except Exception as error:
        # A crashed worker leaves the pool unusable; drop it so the next export
        # starts a fresh one instead of failing forever.
        global POOL
        with POOL_LOCK:
            if POOL is not None:
                POOL.shutdown(wait=False, cancel_futures=True)
                POOL = None
        raise HTTPException(500, f"사진을 현상하지 못했습니다: {error}")


def render(base, s):
    return render_worker.render(base, s)


def job_state(jid):
    with JOB_LOCK:
        state = JOBS.get(jid)
        return dict(state) if state else None


def run_batch(jid, req):
    """Export each photo in turn, publishing progress the page can poll."""
    written, failed = [], []
    for index, item in enumerate(req.photos):
        with JOB_LOCK:
            if JOBS[jid]["cancelled"]:
                break
            JOBS[jid]["done"] = index
        try:
            meta = json.loads((DATA / item.id / "meta.json").read_text())
        except (OSError, ValueError):
            failed.append({"name": item.id, "error": "사진을 찾을 수 없습니다."})
            continue
        with JOB_LOCK:
            JOBS[jid]["current"] = meta["name"]
        s = item.settings or Settings(**meta["settings"])
        dest = req.dest
        if dest is None and req.folder:
            stem = Path(meta["name"]).stem
            dest = str(Path(req.folder) / f"{stem}-나만의빛{suffix_for(req.format)}")
        try:
            result = develop(
                DATA / item.id / meta["source"],
                s,
                req.format,
                req.quality,
                req.long_edge,
                dest,
            )
        except HTTPException as error:
            failed.append({"name": meta["name"], "error": str(error.detail)})
            continue
        if isinstance(result, bytes):
            with JOB_LOCK:
                JOBS[jid]["blob"] = result
            written.append(meta["name"])
        else:
            written.append(result)
    with JOB_LOCK:
        JOBS[jid].update(
            done=len(written) + len(failed),
            current=None,
            written=written,
            failed=failed,
            finished=True,
        )


def suffix_for(fmt):
    return {"jpeg": ".jpg", "tiff": ".tif"}.get(fmt, "." + fmt)


def writable_dir(path, what):
    folder = Path(path).expanduser()
    if not folder.is_absolute() or not folder.is_dir():
        raise HTTPException(400, f"{what}를 찾을 수 없습니다.")
    return folder


@app.get("/")
def index():
    return FileResponse(ROOT / "static/index.html")


@app.get("/api/photos")
def photos():
    return sorted(
        [json.loads(p.read_text()) for p in DATA.glob("*/meta.json")],
        key=lambda p: p["name"],
    )


@app.post("/api/photos")
def upload(file: UploadFile):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in RAW | RASTER:
        raise HTTPException(400, "지원하지 않는 이미지 형식입니다.")
    pid = uuid.uuid4().hex
    folder = DATA / pid
    folder.mkdir()
    path = folder / ("original" + suffix)
    try:
        size = 0
        with path.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > 250 * 1024 * 1024:
                    raise ValueError("파일은 250MB 이하여야 합니다.")
                out.write(chunk)
        with RENDER_LOCK:
            a = decode(path)
        h, w = a.shape[:2]
        im = Image.fromarray(np.uint8(a.clip(0, 1) * 255))
        im.thumbnail((1600, 1600))
        im.save(folder / "preview.png")
        thumb = im.copy()
        thumb.thumbnail((320, 320))
        thumb.save(folder / "thumb.jpg")
        meta = dict(
            id=pid,
            name=Path(file.filename).name,
            width=w,
            height=h,
            raw=suffix in RAW,
            size=size,
            source=path.name,
            settings=Settings().model_dump(),
            rating=0,
        )
        save(pid, meta)
        return meta
    except Exception as e:
        import shutil

        shutil.rmtree(folder)
        raise HTTPException(400, f"이미지를 열 수 없습니다: {e}")


@app.delete("/api/photos/{pid}")
def remove(pid: str):
    meta = record(pid)
    with LOCK:
        shutil.rmtree(DATA / pid, ignore_errors=True)
    return {"id": pid, "name": meta["name"]}


@app.get("/api/photos/{pid}/thumb")
def thumbnail(pid: str):
    record(pid)
    return FileResponse(DATA / pid / "thumb.jpg")


@app.post("/api/photos/{pid}/preview")
def preview(pid: str, s: Settings):
    record(pid)
    with Image.open(DATA / pid / "preview.png") as im:
        a = np.asarray(im, dtype=np.float32) / 255
    return Response(encode(render(a, s)), media_type="image/jpeg")


@app.post("/api/photos/{pid}/frame")
def frame(pid: str, s: Settings):
    """The proxy with every adjustment but the crop, for the crop tool to sit on."""
    record(pid)
    with Image.open(DATA / pid / "preview.png") as im:
        a = np.asarray(im, dtype=np.float32) / 255
    uncropped = s.model_copy(
        update={"crop_x": 0, "crop_y": 0, "crop_w": 1, "crop_h": 1, "crop": "original"}
    )
    return Response(encode(render(a, uncropped)), media_type="image/jpeg")


@app.put("/api/photos/{pid}/settings")
def settings(pid: str, s: Settings):
    with LOCK:
        meta = record(pid)
        meta["settings"] = s.model_dump()
        save(pid, meta)
    return meta


@app.post("/api/photos/{pid}/export")
def export(pid: str, req: Export):
    meta = record(pid)
    dest = None
    if req.dest is not None:
        # Desktop builds pick the destination with a native save panel, so the
        # bytes go straight to disk instead of through a browser download.
        if not DESKTOP:
            raise HTTPException(400, "저장 위치 지정은 데스크톱 앱에서만 지원합니다.")
        target = Path(req.dest).expanduser()
        if not target.is_absolute():
            raise HTTPException(400, "저장할 폴더를 찾을 수 없습니다.")
        writable_dir(target.parent, "저장할 폴더")
        dest = str(target)
    with RENDER_LOCK:
        result = develop(
            DATA / pid / meta["source"],
            req.settings,
            req.format,
            req.quality,
            req.long_edge,
            dest,
        )
    if dest is None:
        return Response(result, media_type="image/" + req.format)
    return {"path": result, "bytes": Path(result).stat().st_size}


@app.post("/api/export")
def export_batch(req: Batch):
    """Start a background export and hand back a job to poll for progress."""
    if req.dest is not None and len(req.photos) != 1:
        raise HTTPException(400, "파일 이름 지정은 사진 한 장일 때만 가능합니다.")
    if req.folder is None and req.dest is None and len(req.photos) != 1:
        raise HTTPException(400, "여러 장을 내보내려면 저장할 폴더가 필요합니다.")
    if (req.dest or req.folder) and not DESKTOP:
        raise HTTPException(400, "저장 위치 지정은 데스크톱 앱에서만 지원합니다.")
    if req.folder:
        writable_dir(req.folder, "저장할 폴더")
    if req.dest:
        writable_dir(Path(req.dest).expanduser().parent, "저장할 폴더")
    for item in req.photos:
        record(item.id)
    jid = uuid.uuid4().hex
    with JOB_LOCK:
        JOBS[jid] = dict(
            id=jid,
            total=len(req.photos),
            done=0,
            current=None,
            written=[],
            failed=[],
            finished=False,
            cancelled=False,
            blob=None,
            started=time.time(),
            format=req.format,
        )
    threading.Thread(
        target=run_batch, args=(jid, req), name=f"export-{jid[:8]}", daemon=True
    ).start()
    return {"job": jid, "total": len(req.photos)}


@app.get("/api/export/{jid}")
def export_status(jid: str):
    state = job_state(jid)
    if not state:
        raise HTTPException(404, "내보내기 작업을 찾을 수 없습니다.")
    state.pop("blob", None)
    state["elapsed"] = round(time.time() - state.pop("started"), 1)
    return state


@app.post("/api/export/{jid}/cancel")
def export_cancel(jid: str):
    with JOB_LOCK:
        if jid not in JOBS:
            raise HTTPException(404, "내보내기 작업을 찾을 수 없습니다.")
        JOBS[jid]["cancelled"] = True
    return {"cancelled": True}


@app.get("/api/export/{jid}/file")
def export_file(jid: str):
    """Browser mode: collect the single rendered image once the job is done."""
    state = job_state(jid)
    if not state:
        raise HTTPException(404, "내보내기 작업을 찾을 수 없습니다.")
    if not state["finished"] or not state["blob"]:
        raise HTTPException(409, "아직 내보내기가 끝나지 않았습니다.")
    return Response(state["blob"], media_type="image/" + state["format"])


@app.get("/advanced-config.js")
def advanced_config():
    return Response(
        "window.ADVANCED = " + json.dumps(ui_config(), ensure_ascii=False) + ";",
        media_type="application/javascript",
    )


@app.post("/api/presets/import")
def preset(file: UploadFile):
    data = file.file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(400, "XMP 파일은 2MB 이하여야 합니다.")
    try:
        return parse_xmp(data, file.filename, Settings)
    except ValueError as error:
        raise HTTPException(400, str(error))
    except Exception:
        raise HTTPException(400, "올바른 XMP XML 파일이 아닙니다.")


@app.get("/api/health")
def health():
    return {"app": "lightloom", "engine_version": 2}
