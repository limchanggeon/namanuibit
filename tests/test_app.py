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


def photo(client):
    a = np.zeros((80, 120, 3), dtype=np.uint8)
    a[:, :, 0] = np.arange(120) * 2
    a[:, :, 1] = 100
    a[:, :, 2] = 60
    out = BytesIO()
    Image.fromarray(a).save(out, "PNG")
    r = client.post(
        "/api/photos", files={"file": ("test.png", out.getvalue(), "image/png")}
    )
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
    assert client.post(f"/api/photos/{p['id']}/export", json=relative).status_code == 400


def test_frozen_bundle_uses_per_user_library(monkeypatch, tmp_path):
    import paths

    monkeypatch.delenv("LIGHTLOOM_DATA", raising=False)
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(paths, "_platform_data_root", lambda: tmp_path)
    assert paths.user_data() == tmp_path / "나만의빛" / "library"

    monkeypatch.setenv("LIGHTLOOM_DATA", str(tmp_path / "custom"))
    assert paths.user_data() == tmp_path / "custom"
