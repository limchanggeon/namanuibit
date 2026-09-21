from io import BytesIO
import json
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient
import pytest
import app as studio


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(studio, "DATA", tmp_path)
    return TestClient(studio.app)


def photo(client, name="test.png"):
    a = np.zeros((80, 120, 3), dtype=np.uint8)
    a[:, :, 0] = np.arange(120) * 2
    a[:, :, 1] = 100
    a[:, :, 2] = 60
    out = BytesIO()
    Image.fromarray(a).save(out, "PNG")
    r = client.post("/api/photos", files={"file": (name, out.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    return r.json()


def test_import_edit_persist_export(client):
    p = photo(client)
    s = studio.Settings(exposure=1, rotation=1, crop="1:1").model_dump(mode="json")
    assert client.put(f"/api/photos/{p['id']}/settings", json=s).status_code == 200
    assert client.get("/api/photos").json()[0]["settings"] == s
    for fmt in ["jpeg", "png", "tiff"]:
        response = client.post(
            f"/api/photos/{p['id']}/export",
            json={"settings": s, "format": fmt, "long_edge": 40},
        )
        assert response.status_code == 200, response.text
        im = Image.open(BytesIO(response.content))
        assert im.size == (40, 40)
        assert im.format == fmt.upper()
        assert im.info.get("icc_profile")
    assert Image.open(studio.DATA / p["id"] / p["source"]).size == (120, 80)


def test_preview_changes_pixels(client):
    p = photo(client)
    url = f"/api/photos/{p['id']}/preview"
    base = client.post(url, json={})
    bright = client.post(url, json={"exposure": 1})
    assert base.status_code == bright.status_code == 200
    a = np.asarray(Image.open(BytesIO(base.content)))
    b = np.asarray(Image.open(BytesIO(bright.content)))
    assert b.mean() > a.mean() + 20


def test_xmp_attributes_elements_unsupported(client):
    xmp = b"""<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"><d crs:Exposure2012="1.25" crs:CameraProfile="Adobe Color"><crs:Saturation>-20</crs:Saturation><crs:Temperature>7400</crs:Temperature></d></x:xmpmeta>"""
    r = client.post("/api/presets/import", files={"file": ("test.xmp", xmp)})
    assert r.status_code == 200
    assert r.json()["settings"] == {
        "exposure": 1.25,
        "saturation": -20,
        "temperature": 20,
    }
    assert r.json()["unsupported"] == ["CameraProfile"]


def test_reject_invalid_files_and_settings(client):
    assert (
        client.post("/api/photos", files={"file": ("bad.nef", b"bad")}).status_code
        == 400
    )
    assert client.get("/api/photos").json() == []
    assert (
        client.post(
            "/api/presets/import",
            files={
                "file": (
                    "bad.xmp",
                    b'<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///etc/passwd">]><foo>&x;</foo>',
                )
            },
        ).status_code
        == 400
    )
    p = photo(client)
    assert (
        client.post(f"/api/photos/{p['id']}/preview", json={"exposure": 99}).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/photos/{p['id']}/export", json={"settings": {}, "format": "exe"}
        ).status_code
        == 422
    )


def test_raw_decoder_uses_16bit(monkeypatch, tmp_path):
    class Raw:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def postprocess(self, **kwargs):
            assert kwargs["output_bps"] == 16
            assert kwargs["use_camera_wb"] is True
            return np.full((10, 10, 3), 32768, dtype=np.uint16)

    monkeypatch.setattr(studio.rawpy, "imread", lambda path: Raw())
    decoded = studio.decode(tmp_path / "test.nef")
    assert decoded.dtype == np.float32
    assert 0.5 < decoded.mean() < 0.501


def test_export_to_path_requires_desktop(client, tmp_path, monkeypatch):
    p = photo(client)
    target = tmp_path / "out" / "saved.jpg"
    target.parent.mkdir()
    body = {"settings": {}, "format": "jpeg", "dest": str(target)}

    assert client.post(f"/api/photos/{p['id']}/export", json=body).status_code == 400

    monkeypatch.setattr(studio, "DESKTOP", True)
    saved = client.post(f"/api/photos/{p['id']}/export", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["path"] == str(target)
    assert Image.open(target).format == "JPEG"

    missing = {**body, "dest": str(tmp_path / "nope" / "saved.jpg")}
    assert client.post(f"/api/photos/{p['id']}/export", json=missing).status_code == 400
    relative = {**body, "dest": "saved.jpg"}
    assert (
        client.post(f"/api/photos/{p['id']}/export", json=relative).status_code == 400
    )


def test_frozen_bundle_uses_per_user_library(monkeypatch, tmp_path):
    import paths

    monkeypatch.delenv("LIGHTLOOM_DATA", raising=False)
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(paths, "_platform_data_root", lambda: tmp_path)
    assert paths.user_data() == tmp_path / "나만의빛" / "library"

    monkeypatch.setenv("LIGHTLOOM_DATA", str(tmp_path / "custom"))
    assert paths.user_data() == tmp_path / "custom"


def wait_for_job(client, jid, timeout=120):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get(f"/api/export/{jid}").json()
        if state["finished"]:
            return state
        time.sleep(0.05)
    raise AssertionError("export job never finished")


def test_delete_photo_removes_its_folder(client):
    p = photo(client)
    assert (studio.DATA / p["id"]).is_dir()
    assert client.delete(f"/api/photos/{p['id']}").json()["name"] == "test.png"
    assert not (studio.DATA / p["id"]).exists()
    assert client.get("/api/photos").json() == []
    assert client.delete(f"/api/photos/{p['id']}").status_code == 404


def test_webp_export_and_rejected_formats(client):
    p = photo(client)
    r = client.post(
        f"/api/photos/{p['id']}/export", json={"settings": {}, "format": "webp"}
    )
    assert r.status_code == 200, r.text
    im = Image.open(BytesIO(r.content))
    assert im.format == "WEBP" and im.size == (120, 80)
    assert (
        client.post(
            f"/api/photos/{p['id']}/export", json={"settings": {}, "format": "gif"}
        ).status_code
        == 422
    )


def test_free_crop_rectangle(client):
    p = photo(client)
    s = {"crop_x": 0.25, "crop_y": 0.5, "crop_w": 0.5, "crop_h": 0.25}
    r = client.post(f"/api/photos/{p['id']}/export", json={"settings": s})
    assert r.status_code == 200, r.text
    # The source is 120x80, so a quarter-tall half-width slice is 60x20.
    assert Image.open(BytesIO(r.content)).size == (60, 20)

    # The frame endpoint ignores the crop so the tool can show the whole photo.
    frame = client.post(f"/api/photos/{p['id']}/frame", json=s)
    assert Image.open(BytesIO(frame.content)).size == (120, 80)

    # A rectangle running off the edge is refused rather than silently clamped.
    off = {**s, "crop_x": 0.8, "crop_w": 0.5}
    assert client.post(f"/api/photos/{p['id']}/preview", json=off).status_code == 422


def test_named_ratio_still_crops_for_old_libraries(client):
    p = photo(client)
    r = client.post(f"/api/photos/{p['id']}/export", json={"settings": {"crop": "1:1"}})
    assert Image.open(BytesIO(r.content)).size == (80, 80)


def test_batch_export_writes_every_photo(client, tmp_path, monkeypatch):
    monkeypatch.setattr(studio, "DESKTOP", True)
    first, second = photo(client, "하나.png"), photo(client, "둘.png")
    folder = tmp_path / "out"
    folder.mkdir()
    started = client.post(
        "/api/export",
        json={
            "photos": [{"id": first["id"]}, {"id": second["id"]}],
            "format": "webp",
            "folder": str(folder),
        },
    )
    assert started.status_code == 200, started.text
    assert started.json()["total"] == 2
    state = wait_for_job(client, started.json()["job"])
    assert state["failed"] == [], state["failed"]
    assert len(state["written"]) == 2
    written = sorted(folder.glob("*.webp"))
    assert len(written) == 2
    assert Image.open(written[0]).format == "WEBP"


def test_batch_export_rejects_missing_folder_and_unknown_photos(
    client, tmp_path, monkeypatch
):
    monkeypatch.setattr(studio, "DESKTOP", True)
    first = photo(client)
    assert (
        client.post(
            "/api/export",
            json={
                "photos": [{"id": first["id"]}, {"id": "0" * 32}],
                "folder": str(tmp_path),
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/export",
            json={"photos": [{"id": first["id"]}, {"id": first["id"]}]},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/export",
            json={"photos": [{"id": first["id"]}], "folder": str(tmp_path / "nope")},
        ).status_code
        == 400
    )


def test_single_export_job_keeps_bytes_for_browser_download(client):
    p = photo(client)
    started = client.post("/api/export", json={"photos": [{"id": p["id"]}]})
    assert started.status_code == 200, started.text
    jid = started.json()["job"]
    state = wait_for_job(client, jid)
    assert state["failed"] == []
    assert "blob" not in state
    got = client.get(f"/api/export/{jid}/file")
    assert got.status_code == 200
    assert Image.open(BytesIO(got.content)).format == "JPEG"
