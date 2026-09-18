"""Shared adjustment definitions for validation, XMP mapping, and the editor UI."""

from typing import Annotated
from pydantic import BaseModel, Field, create_model, field_validator, model_validator

# key, label, default, minimum, maximum, step, Camera Raw property
GROUPS = [
    (
        "텍스처 · 대기",
        [
            ("texture", "텍스처", 0, -100, 100, 1, "Texture"),
            ("dehaze", "안개 제거", 0, -100, 100, 1, "Dehaze"),
        ],
    ),
    (
        "파라메트릭 커브",
        [
            ("parametric_shadows", "암부", 0, -100, 100, 1, "ParametricShadows"),
            ("parametric_darks", "어두운 톤", 0, -100, 100, 1, "ParametricDarks"),
            ("parametric_lights", "밝은 톤", 0, -100, 100, 1, "ParametricLights"),
            ("parametric_highlights", "명부", 0, -100, 100, 1, "ParametricHighlights"),
            ("shadow_split", "암부 경계", 25, 1, 97, 1, "ParametricShadowSplit"),
            ("midtone_split", "중간 경계", 50, 2, 98, 1, "ParametricMidtoneSplit"),
            ("highlight_split", "명부 경계", 75, 3, 99, 1, "ParametricHighlightSplit"),
        ],
    ),
]
COLORS = [
    ("red", "빨강", 0),
    ("orange", "주황", 30),
    ("yellow", "노랑", 60),
    ("green", "초록", 120),
    ("aqua", "아쿠아", 180),
    ("blue", "파랑", 240),
    ("purple", "보라", 270),
    ("magenta", "마젠타", 300),
]
for color, label, _ in COLORS:
    GROUPS.append(
        (
            f"HSL · {label}",
            [
                (
                    f"{kind}_{color}",
                    label2,
                    0,
                    -100,
                    100,
                    1,
                    f"{xmp}Adjustment{color.title()}",
                )
                for kind, label2, xmp in [
                    ("hue", "색상", "Hue"),
                    ("sat", "채도", "Saturation"),
                    ("lum", "명도", "Luminance"),
                ]
            ],
        )
    )
for zone, label, hue, sat, lum in [
    (
        "shadow",
        "어두운 영역",
        "SplitToningShadowHue",
        "SplitToningShadowSaturation",
        "ColorGradeShadowLum",
    ),
    (
        "midtone",
        "중간 영역",
        "ColorGradeMidtoneHue",
        "ColorGradeMidtoneSat",
        "ColorGradeMidtoneLum",
    ),
    (
        "highlight",
        "밝은 영역",
        "SplitToningHighlightHue",
        "SplitToningHighlightSaturation",
        "ColorGradeHighlightLum",
    ),
    (
        "global",
        "전체",
        "ColorGradeGlobalHue",
        "ColorGradeGlobalSat",
        "ColorGradeGlobalLum",
    ),
]:
    GROUPS.append(
        (
            f"컬러 그레이딩 · {label}",
            [
                (f"grade_{zone}_hue", "색상", 0, 0, 360, 1, hue),
                (f"grade_{zone}_sat", "채도", 0, 0, 100, 1, sat),
                (f"grade_{zone}_lum", "명도", 0, -100, 100, 1, lum),
            ],
        )
    )
GROUPS += [
    (
        "그레이딩 혼합",
        [
            ("grade_balance", "균형", 0, -100, 100, 1, "SplitToningBalance"),
            ("grade_blending", "혼합", 50, 0, 100, 1, "ColorGradeBlending"),
        ],
    ),
    (
        "선명도 세부 설정",
        [
            ("sharpen_radius", "반경", 1, 0.5, 3, 0.1, "SharpenRadius"),
            ("sharpen_detail", "세부", 25, 0, 100, 1, "SharpenDetail"),
            ("sharpen_masking", "가장자리 마스킹", 0, 0, 100, 1, "SharpenEdgeMasking"),
        ],
    ),
    (
        "노이즈 감소",
        [
            ("noise_luminance", "휘도 노이즈", 0, 0, 100, 1, "LuminanceSmoothing"),
            (
                "noise_detail",
                "휘도 세부 보존",
                50,
                0,
                100,
                1,
                "LuminanceNoiseReductionDetail",
            ),
            (
                "noise_contrast",
                "휘도 대비 보존",
                0,
                0,
                100,
                1,
                "LuminanceNoiseReductionContrast",
            ),
            ("noise_color", "색상 노이즈", 0, 0, 100, 1, "ColorNoiseReduction"),
            (
                "noise_color_detail",
                "색상 세부 보존",
                50,
                0,
                100,
                1,
                "ColorNoiseReductionDetail",
            ),
            (
                "noise_color_smooth",
                "색상 매끄러움",
                50,
                0,
                100,
                1,
                "ColorNoiseReductionSmoothness",
            ),
        ],
    ),
    (
        "그레인",
        [
            ("grain", "양", 0, 0, 100, 1, "GrainAmount"),
            ("grain_size", "크기", 25, 0, 100, 1, "GrainSize"),
            ("grain_roughness", "거칠기", 50, 0, 100, 1, "GrainFrequency"),
        ],
    ),
    (
        "비네팅 세부 설정",
        [
            ("vignette_midpoint", "중간점", 50, 0, 100, 1, "PostCropVignetteMidpoint"),
            (
                "vignette_roundness",
                "원형률",
                0,
                -100,
                100,
                1,
                "PostCropVignetteRoundness",
            ),
            ("vignette_feather", "페더", 50, 0, 100, 1, "PostCropVignetteFeather"),
            (
                "vignette_highlights",
                "밝은 영역 보호",
                0,
                0,
                100,
                1,
                "PostCropVignetteHighlightContrast",
            ),
        ],
    ),
    (
        "색상 보정 · 원색",
        [
            ("shadow_tint", "어두운 영역 색조", 0, -100, 100, 1, "ShadowTint"),
            *[
                (
                    f"calibration_{c}_{kind}",
                    f"{label} 원색 {kl}",
                    0,
                    -100,
                    100,
                    1,
                    f"{c.title()}{xmp}",
                )
                for c, label in [("red", "빨강"), ("green", "초록"), ("blue", "파랑")]
                for kind, kl, xmp in [
                    ("hue", "색상", "Hue"),
                    ("sat", "채도", "Saturation"),
                ]
            ],
        ],
    ),
    (
        "프린지 제거",
        [
            ("defringe_purple", "보라색 양", 0, 0, 20, 1, "DefringePurpleAmount"),
            (
                "defringe_purple_lo",
                "보라색 범위 시작",
                30,
                0,
                100,
                1,
                "DefringePurpleHueLo",
            ),
            (
                "defringe_purple_hi",
                "보라색 범위 끝",
                70,
                0,
                100,
                1,
                "DefringePurpleHueHi",
            ),
            ("defringe_green", "녹색 양", 0, 0, 20, 1, "DefringeGreenAmount"),
            (
                "defringe_green_lo",
                "녹색 범위 시작",
                40,
                0,
                100,
                1,
                "DefringeGreenHueLo",
            ),
            ("defringe_green_hi", "녹색 범위 끝", 60, 0, 100, 1, "DefringeGreenHueHi"),
        ],
    ),
]
GROUPS.append(
    (
        "포인트 커브 세부",
        [
            (
                "curve_saturation",
                "커브 채도 반영",
                100,
                0,
                100,
                1,
                "CurveRefineSaturation",
            )
        ],
    )
)
for title, rows in GROUPS:
    if title == "비네팅 세부 설정":
        rows.insert(
            0, ("vignette_style", "스타일", 0, 0, 2, 1, "PostCropVignetteStyle")
        )

CURVES = {
    "ToneCurvePV2012": "curve_rgb",
    "ToneCurvePV2012Red": "curve_red",
    "ToneCurvePV2012Green": "curve_green",
    "ToneCurvePV2012Blue": "curve_blue",
}
Point = tuple[
    Annotated[float, Field(ge=0, le=255)], Annotated[float, Field(ge=0, le=255)]
]


class CurveSettings(BaseModel):
    curve_rgb: list[Point] = Field(
        default_factory=lambda: [(0, 0), (255, 255)], min_length=2, max_length=32
    )
    curve_red: list[Point] = Field(
        default_factory=lambda: [(0, 0), (255, 255)], min_length=2, max_length=32
    )
    curve_green: list[Point] = Field(
        default_factory=lambda: [(0, 0), (255, 255)], min_length=2, max_length=32
    )
    curve_blue: list[Point] = Field(
        default_factory=lambda: [(0, 0), (255, 255)], min_length=2, max_length=32
    )

    @field_validator("curve_rgb", "curve_red", "curve_green", "curve_blue")
    @classmethod
    def ordered(cls, points):
        if any(a[0] >= b[0] for a, b in zip(points, points[1:])):
            raise ValueError("커브 입력 좌표는 중복 없이 오름차순이어야 합니다.")
        return points

    @model_validator(mode="after")
    def ranges(self):
        if (
            hasattr(self, "shadow_split")
            and not self.shadow_split < self.midtone_split < self.highlight_split
        ):
            raise ValueError("커브 경계는 암부 < 중간 < 명부 순서여야 합니다.")
        for c in ("purple", "green"):
            if hasattr(self, f"defringe_{c}_lo") and getattr(
                self, f"defringe_{c}_lo"
            ) >= getattr(self, f"defringe_{c}_hi"):
                raise ValueError("프린지 범위의 시작은 끝보다 작아야 합니다.")
        return self


SPECS = {row[0]: row for _, rows in GROUPS for row in rows}
AdvancedSettings = create_model(
    "AdvancedSettings",
    __base__=CurveSettings,
    **{key: (float, Field(row[2], ge=row[3], le=row[4])) for key, row in SPECS.items()},
)
XMP_MAP = {row[6]: key for key, row in SPECS.items()}


def ui_config():
    return {
        "defaults": AdvancedSettings().model_dump(),
        "groups": [
            [
                name,
                [
                    [key, label, lo, hi, step]
                    for key, label, default, lo, hi, step, xmp in rows
                ],
            ]
            for name, rows in GROUPS
        ],
    }
