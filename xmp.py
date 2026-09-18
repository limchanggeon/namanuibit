"""Camera Raw preset import, preserving the scope of nested profile resources."""

from pathlib import Path
import math
from defusedxml import ElementTree as ET
from pydantic import ValidationError
from adjustments import XMP_MAP, CURVES

NS = "{http://ns.adobe.com/camera-raw-settings/1.0/}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
BASE_MAP = {
    "Exposure2012": "exposure",
    "Contrast2012": "contrast",
    "Highlights2012": "highlights",
    "Shadows2012": "shadows",
    "Whites2012": "whites",
    "Blacks2012": "blacks",
    "Saturation": "saturation",
    "Vibrance": "vibrance",
    "Clarity2012": "clarity",
    "Sharpness": "sharpness",
    "PostCropVignetteAmount": "vignette",
    "Tint": "tint",
    "Temperature": "temperature",
}
MAP = {**BASE_MAP, **XMP_MAP}
META = set(
    "Name Version ProcessVersion PresetType UUID SupportsAmount SupportsAmount2 SupportsColor SupportsMonochrome SupportsHighDynamicRange SupportsNormalDynamicRange SupportsSceneReferred SupportsOutputReferred CameraModelRestriction Copyright ContactInfo HasSettings AlreadyApplied WhiteBalance Description Group SortName Cluster ShowInPresets ShowInQuickActions ShortName Stubbed AsShotTemperature AsShotTint".split()
)
# These are parameters of inactive features, not independently active operations.
DEPENDENTS = {
    "LensProfileSetup": "LensProfileEnable",
    "CropConstrainToWarp": "LensProfileEnable",
    "OverrideLookVignette": "Look",
    "CurveRefineSaturation": "ToneCurvePV2012",
    "PostCropVignetteStyle": "PostCropVignetteAmount",
}


def parse(data, filename, settings_model):
    root = ET.fromstring(data)
    values = {}
    elements = {}

    def visit(el):
        # Only descend through the RDF document, never into CRS profile resources.
        for key, value in el.attrib.items():
            if key.startswith(NS):
                values[key[len(NS) :]] = value
        for child in el:
            if child.tag.startswith(NS):
                key = child.tag[len(NS) :]
                elements[key] = child
                values[key] = " ".join(child.itertext()).strip()
                if child.attrib or len(child):
                    if not values[key] and key not in CURVES:
                        values[key] = (
                            "[resource]"
                            if child.attrib
                            or any(
                                len(c) or c.attrib or (c.text or "").strip()
                                for c in child
                            )
                            else ""
                        )
            else:
                visit(child)

    visit(root)
    result = {}
    unsupported = []
    ignored = []
    neutral = []
    invalid = []
    adjusted = []

    def inactive(key):
        value = values.get(key, "").strip()
        if key == "PointColors":
            try:
                numbers = [
                    float(n.strip())
                    for n in value.replace("\n", ",").split(",")
                    if n.strip()
                ]
                if numbers and all(n == -1 for n in numbers):
                    return True
            except ValueError:
                pass
        if (
            key == "ColorVariance"
            and "PointColors" in values
            and inactive("PointColors")
        ):
            return True

        if value.lower() in ("", "false", "none", "off"):
            return True
        try:
            return float(value) == 0
        except ValueError:
            return False

    for key, value in values.items():
        if key in META:
            ignored.append(key)
            continue
        if key in MAP:
            try:
                n = float(value)
                if not math.isfinite(n):
                    raise ValueError()
                if key == "Temperature":
                    n = (n - 6500) / 45
                field = MAP[key]
                info = settings_model.model_fields[field]
                lo = next(m.ge for m in info.metadata if hasattr(m, "ge"))
                hi = next(m.le for m in info.metadata if hasattr(m, "le"))
                result[field] = max(lo, min(hi, n))
                if result[field] != n:
                    adjusted.append(key)
            except (ValueError, StopIteration):
                invalid.append(key)
        elif key in CURVES:
            try:
                el = elements[key]
                points = [
                    tuple(float(n.strip()) for n in item.text.split(","))
                    for item in el.iter(RDF + "li")
                    if item.text
                ]
                field = CURVES[key]
                result[field] = settings_model(**{field: points}).model_dump()[field]
            except (ValueError, KeyError, ValidationError):
                invalid.append(key)
        elif key == "ConvertToGrayscale":
            if value.lower() in ("true", "false"):
                result["monochrome"] = value.lower() == "true"
            else:
                invalid.append(key)
        elif key == "ToneCurveName2012":
            if "ToneCurvePV2012" in values or value.lower() in ("linear", "custom", ""):
                ignored.append(key)
            else:
                unsupported.append(key)
        elif key in DEPENDENTS and inactive(DEPENDENTS[key]):
            neutral.append(key)
        elif inactive(key):
            neutral.append(key)
        else:
            unsupported.append(key)
    # Validate related ranges together; never silently turn malformed ranges into a different preset.
    try:
        settings_model(**result)
    except ValidationError:
        if not (
            result.get("shadow_split", 25)
            < result.get("midtone_split", 50)
            < result.get("highlight_split", 75)
        ):
            for field in ("shadow_split", "midtone_split", "highlight_split"):
                result.pop(field, None)
            invalid.append("ParametricSplits")
        for c in ("purple", "green"):
            default = settings_model()
            if result.get(
                f"defringe_{c}_lo", getattr(default, f"defringe_{c}_lo")
            ) >= result.get(f"defringe_{c}_hi", getattr(default, f"defringe_{c}_hi")):
                for suffix in ("lo", "hi"):
                    result.pop(f"defringe_{c}_{suffix}", None)
                invalid.append(f"Defringe{c.title()}HueRange")
        settings_model(**result)
    if not result:
        raise ValueError(
            "적용할 수 있는 보정값이 없습니다. 프로필 전용 XMP이거나 값이 잘못되었습니다."
        )
    return dict(
        name=values.get("Name") or Path(filename or "Preset").stem,
        settings=result,
        unsupported=unsupported,
        invalid=invalid,
        ignored=ignored,
        neutral=neutral,
        adjusted=adjusted,
        applied_count=len(result),
        partial=bool(unsupported or invalid),
        engine_version=2,
        note="나만의빛 보정 엔진으로 적용합니다. Adobe와 색감이 다를 수 있으며 색온도·원색 보정 등은 근사 처리합니다.",
    )
