from io import BytesIO
import colorsys
import numpy as np
import pytest
from PIL import Image
from app import Settings, render
from engine import rgb_hsl, hsl_rgb, luminance, denoise
from adjustments import SPECS, CURVES, ui_config
from test_app import client, photo


@pytest.fixture
def scene():
    rng = np.random.default_rng(8)
    y, x = np.mgrid[0:96, 0:128]
    colors = np.array(
        [
            colorsys.hsv_to_rgb(h, 0.7, 0.65)
            for h in np.linspace(0, 1, 128, endpoint=False)
        ],
        dtype=np.float32,
    )
    a = np.clip(
        colors[None, :, :] * (0.2 + 0.8 * y[:, :, None] / 95)
        + rng.normal(0, 0.03, (96, 128, 3)),
        0,
        1,
    ).astype(np.float32)
    a[-16:] = np.linspace(0, 1, 128)[None, :, None]
    return a


def pixels(scene, **settings):
    return np.asarray(render(scene, Settings(**settings)), dtype=np.float32)


@pytest.mark.parametrize(
    "settings",
    [
        {"texture": 90},
        {"dehaze": 70},
        {"dehaze": -70},
        {"grain": 80},
        {"parametric_shadows": 80},
        {"parametric_darks": 80},
        {"parametric_lights": 80},
        {"parametric_highlights": 80},
        {"curve_rgb": [(0, 0), (128, 180), (255, 255)]},
        {"curve_red": [(0, 10), (128, 160), (255, 255)]},
        {"curve_green": [(0, 10), (128, 160), (255, 255)]},
        {"curve_blue": [(0, 10), (128, 160), (255, 255)]},
        *[
            {f"{kind}_{color}": 70}
            for color in [
                "red",
                "orange",
                "yellow",
                "green",
                "aqua",
                "blue",
                "purple",
                "magenta",
            ]
            for kind in ["hue", "sat", "lum"]
        ],
        *[
            {f"grade_{zone}_hue": 220, f"grade_{zone}_sat": 80}
            for zone in ["shadow", "midtone", "highlight", "global"]
        ],
        *[
            {f"grade_{zone}_lum": 60}
            for zone in ["shadow", "midtone", "highlight", "global"]
        ],
        *[
            {f"calibration_{color}_{kind}": 70}
            for color in ["red", "green", "blue"]
            for kind in ["hue", "sat"]
        ],
        {"shadow_tint": 70},
        {"noise_luminance": 100},
        {"noise_color": 100},
        {"defringe_purple": 20},
        {"defringe_green": 20},
    ],
)
def test_adjustment_has_visible_effect(scene, settings):
    base = pixels(scene)
    edited = pixels(scene, **settings)
    assert np.isfinite(edited).all()
    assert np.abs(base - edited).sum() > 10, settings


@pytest.mark.parametrize(
    "base,field,value",
    [
        ({"grain": 80}, "grain_size", 90),
        ({"grain": 80}, "grain_roughness", 100),
        ({"sharpness": 100}, "sharpen_radius", 3),
        ({"sharpness": 100}, "sharpen_detail", 100),
        ({"sharpness": 100}, "sharpen_masking", 100),
        ({"noise_luminance": 100}, "noise_detail", 0),
        ({"noise_luminance": 100}, "noise_contrast", 100),
        ({"noise_color": 100}, "noise_color_detail", 0),
        ({"noise_color": 100}, "noise_color_smooth", 100),
        ({"vignette": -80}, "vignette_midpoint", 10),
        ({"vignette": -80}, "vignette_roundness", 90),
        ({"vignette": -80}, "vignette_feather", 90),
        ({"vignette": -80}, "vignette_highlights", 100),
        ({"grade_shadow_sat": 80}, "grade_balance", 90),
        ({"grade_shadow_sat": 80}, "grade_blending", 100),
        ({"parametric_shadows": 80}, "shadow_split", 15),
        ({"parametric_darks": 80}, "midtone_split", 60),
        ({"parametric_highlights": 80}, "highlight_split", 90),
        ({"defringe_purple": 20}, "defringe_purple_lo", 0),
        ({"defringe_purple": 20}, "defringe_purple_hi", 100),
        ({"defringe_green": 20}, "defringe_green_lo", 0),
        ({"defringe_green": 20}, "defringe_green_hi", 100),
    ],
)
def test_modifier_changes_active_effect(scene, base, field, value):
    assert (
        np.abs(pixels(scene, **base) - pixels(scene, **{**base, field: value})).sum()
        > 1
    ), (base, field)


def test_hsl_roundtrip_and_achromatic():
    a = np.random.default_rng(9).random((30, 40, 3), dtype=np.float32)
    a[0, :] = 0.5
    a[1, :] = 0
    a[2, :] = 1
    h, s, l = rgb_hsl(a)
    np.testing.assert_allclose(hsl_rgb(h, s, l), a, atol=1e-6)


def test_grain_is_deterministic(scene):
    assert np.array_equal(pixels(scene, grain=80), pixels(scene, grain=80))


def test_hsl_red_does_not_change_blue():
    a = np.array([[[0.7, 0.1, 0.1], [0.1, 0.1, 0.7]]], dtype=np.float32)
    base = pixels(a)
    edit = pixels(a, hue_red=80, sat_red=-70)
    np.testing.assert_array_equal(base[:, 1], edit[:, 1])
    assert not np.array_equal(base[:, 0], edit[:, 0])


def test_noise_reduction_reduces_variance():
    a = np.clip(
        0.5 + np.random.default_rng(7).normal(0, 0.04, (128, 128, 3)), 0, 1
    ).astype(np.float32)
    b = denoise(
        a,
        Settings(
            noise_luminance=100, noise_color=100, noise_detail=0, noise_color_detail=0
        ),
        1,
    )
    assert b.var() < a.var() * 0.5


def test_neutral_render_and_extremes(scene):
    np.testing.assert_allclose(pixels(scene), np.round(scene * 255), atol=1)
    all_high = {key: row[4] for key, row in SPECS.items()}
    all_high.update(
        shadow_split=25,
        midtone_split=50,
        highlight_split=75,
        defringe_purple_lo=0,
        defringe_green_lo=0,
    )
    result = pixels(scene, **all_high)
    assert result.shape == scene.shape
    assert np.isfinite(result).all()


def test_invalid_curve_and_ranges_rejected(client):
    p = photo(client)
    for settings in [
        {"curve_rgb": [[0, 0], [0, 255]]},
        {"curve_blue": [[0, 0], [256, 0]]},
        {"shadow_split": 70},
        {"defringe_green_lo": 80},
    ]:
        assert (
            client.post(f"/api/photos/{p['id']}/preview", json=settings).status_code
            == 422
        )


XMP_START = '<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"><rdf:RDF><rdf:Description '


def import_xmp(client, attributes="", children=""):
    text = (
        XMP_START
        + attributes
        + ">"
        + children
        + "</rdf:Description></rdf:RDF></x:xmpmeta>"
    )
    return client.post(
        "/api/presets/import", files={"file": ("Test.xmp", text.encode())}
    )


def test_complete_xmp_and_scoped_nested_look(client):
    attributes = " ".join(f'crs:{row[6]}="{row[2]}"' for row in SPECS.values())
    attributes += ' crs:Exposure2012="0.75" crs:Cluster="User" crs:ShowInPresets="True" crs:RequiresRGBTables="False" crs:AutoLateralCA="0" crs:LensProfileEnable="0" crs:LensProfileSetup="LensDefaults" crs:CropConstrainToWarp="1"'
    curves = "".join(
        f"<crs:{key}><rdf:Seq><rdf:li>0, 10</rdf:li><rdf:li>128, 180</rdf:li><rdf:li>255, 255</rdf:li></rdf:Seq></crs:{key}>"
        for key in CURVES
    )
    children = (
        '<crs:Name><rdf:Alt><rdf:li xml:lang="x-default">Real preset name</rdf:li></rdf:Alt></crs:Name>'
        + curves
        + '<crs:Look><rdf:Description crs:Name="Adobe Color" crs:Exposure2012="4" crs:Amount="1"/></crs:Look><crs:PointColors><rdf:Seq/></crs:PointColors>'
    )
    r = import_xmp(client, attributes, children)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["name"] == "Real preset name"
    assert p["settings"]["exposure"] == 0.75
    assert p["settings"]["curve_blue"] == [[0, 10], [128, 180], [255, 255]]
    assert p["unsupported"] == ["Look"]
    assert p["partial"] is True
    assert "Cluster" in p["ignored"]
    assert "PointColors" in p["neutral"]
    assert p["applied_count"] == len(SPECS) + 5


def test_xmp_nonzero_unsupported_and_invalid(client):
    r = import_xmp(
        client,
        'crs:Exposure2012="0" crs:AutoLateralCA="1" crs:Texture="NaN"',
        "<crs:ToneCurvePV2012><rdf:Seq><rdf:li>1, 2</rdf:li><rdf:li>1, 10</rdf:li></rdf:Seq></crs:ToneCurvePV2012>",
    )
    p = r.json()
    assert p["unsupported"] == ["AutoLateralCA"]
    assert set(p["invalid"]) == {"Texture", "ToneCurvePV2012"}
    assert p["partial"]


def test_advanced_roundtrip_and_export(client):
    p = photo(client)
    settings = {
        "hue_red": 50,
        "texture": 25,
        "grain": 20,
        "curve_blue": [[0, 10], [128, 170], [255, 255]],
        "grade_shadow_sat": 20,
        "grade_shadow_hue": 240,
    }
    response = client.put(f"/api/photos/{p['id']}/settings", json=settings)
    assert response.status_code == 200
    saved = client.get("/api/photos").json()[0]["settings"]
    for key, value in settings.items():
        assert saved[key] == value
    for kind in ["preview", "export"]:
        body = saved if kind == "preview" else {"settings": saved, "format": "png"}
        r = client.post(f"/api/photos/{p['id']}/{kind}", json=body)
        assert r.status_code == 200, r.text
        im = Image.open(BytesIO(r.content))
        assert im.size == (120, 80)
    assert set(ui_config()["defaults"]).issubset(Settings.model_fields)


def test_curve_saturation_and_vignette_styles(scene):
    curve = {"curve_rgb": [(0, 0), (80, 30), (180, 220), (255, 255)]}
    assert (
        np.abs(
            pixels(scene, **curve, curve_saturation=0)
            - pixels(scene, **curve, curve_saturation=100)
        ).sum()
        > 10
    )
    baseline = pixels(scene, vignette=-80, vignette_style=0)
    for style in (1, 2):
        assert (
            np.abs(pixels(scene, vignette=-80, vignette_style=style) - baseline).sum()
            > 10
        )


def test_empty_pointcolor_sentinel_and_capture_metadata(client):
    r = import_xmp(
        client,
        'crs:Exposure2012="0" crs:AsShotTemperature="4200" crs:AsShotTint="43"',
        "<crs:PointColors><rdf:Seq><rdf:li>-1.000, -1.000, -1.000</rdf:li></rdf:Seq></crs:PointColors><crs:ColorVariance><rdf:Seq><rdf:li>-50</rdf:li></rdf:Seq></crs:ColorVariance>",
    )
    p = r.json()
    assert p["unsupported"] == []
    assert set(p["neutral"]) == {"PointColors", "ColorVariance"}
    assert set(p["ignored"]) == {"AsShotTemperature", "AsShotTint"}
