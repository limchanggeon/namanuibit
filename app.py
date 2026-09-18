from pathlib import Path
from io import BytesIO
import json, uuid, os, threading
import numpy as np
import rawpy
from PIL import Image, ImageOps, ImageCms
from adjustments import AdvancedSettings, ui_config
from engine import process
from xmp import parse as parse_xmp
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import paths

ROOT = paths.resources()
DATA = paths.user_data()
DATA.mkdir(exist_ok=True, parents=True)
DESKTOP = os.environ.get("LIGHTLOOM_DESKTOP") == "1"
LOCK = threading.RLock()
RENDER_LOCK = threading.Lock()
app = FastAPI(title="나만의빛")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
RAW = {
    ".cr2",
    ".cr3",
    ".nef",
    ".nrw",
    ".arw",
    ".dng",
    ".raf",
    ".orf",
    ".rw2",
    ".pef",
    ".srw",
    ".raw",
}


class Settings(AdvancedSettings):
    exposure: float = Field(0, ge=-5, le=5)
    contrast: float = Field(0, ge=-100, le=100)
    highlights: float = Field(0, ge=-100, le=100)
    shadows: float = Field(0, ge=-100, le=100)
    whites: float = Field(0, ge=-100, le=100)
    blacks: float = Field(0, ge=-100, le=100)
    temperature: float = Field(0, ge=-100, le=100)
    tint: float = Field(0, ge=-100, le=100)
    vibrance: float = Field(0, ge=-100, le=100)
    saturation: float = Field(0, ge=-100, le=100)
    clarity: float = Field(0, ge=-100, le=100)
    sharpness: float = Field(0, ge=0, le=150)
    vignette: float = Field(0, ge=-100, le=100)
    rotation: int = Field(0, ge=0, le=3)
    crop: str = Field("original", pattern="^(original|1:1|4:3|3:2|16:9)$")
    monochrome: bool = False


class Export(BaseModel):
    settings: Settings
    format: str = Field("jpeg", pattern="^(jpeg|png|tiff)$")
    quality: int = Field(95, ge=10, le=100)
    long_edge: int = Field(0, ge=0, le=16000)
    dest: str | None = None


def record(pid):
    if not pid.isalnum() or not (DATA / pid / "meta.json").exists():
        raise HTTPException(404, "사진을 찾을 수 없습니다.")
    return json.loads((DATA / pid / "meta.json").read_text())


def save(pid, meta):
    with LOCK:
        tmp = DATA / pid / f"{uuid.uuid4().hex}.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False))
        tmp.replace(DATA / pid / "meta.json")


def decode(path):
    if path.suffix.lower() in RAW:
        with rawpy.imread(str(path)) as raw:
            return (
                raw.postprocess(
                    use_camera_wb=True, no_auto_bright=True, output_bps=16
                ).astype(np.float32)
                / 65535
            )
    with Image.open(path) as source:
        im = ImageOps.exif_transpose(source)
        if source.info.get("icc_profile"):
            im = ImageCms.profileToProfile(
                im,
                ImageCms.ImageCmsProfile(BytesIO(source.info["icc_profile"])),
                ImageCms.createProfile("sRGB"),
                outputMode="RGB",
            )
        return np.asarray(im.convert("RGB"), dtype=np.float32) / 255


def render(base, s):
    return process(base, s)


def encode(im, fmt="jpeg", quality=92):
    out = BytesIO()
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    im.save(out, format=fmt.upper(), quality=quality, icc_profile=icc)
    return out.getvalue()


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
    if suffix not in RAW | {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}:
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
    with RENDER_LOCK:
        im = render(decode(DATA / pid / meta["source"]), req.settings)
        if req.long_edge:
            im.thumbnail((req.long_edge, req.long_edge), Image.Resampling.LANCZOS)
        data = encode(im, req.format, req.quality)
    if req.dest is None:
        return Response(data, media_type="image/" + req.format)
    # Desktop builds pick the destination with a native save panel, so the
    # bytes go straight to disk instead of through a browser download.
    if not DESKTOP:
        raise HTTPException(400, "저장 위치 지정은 데스크톱 앱에서만 지원합니다.")
    target = Path(req.dest).expanduser()
    if not target.is_absolute() or not target.parent.is_dir():
        raise HTTPException(400, "저장할 폴더를 찾을 수 없습니다.")
    try:
        target.write_bytes(data)
    except OSError as error:
        raise HTTPException(400, f"파일을 저장하지 못했습니다: {error}")
    return {"path": str(target), "bytes": len(data)}


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
