"""The adjustment model, kept free of FastAPI so render workers can import it."""

from pydantic import Field, model_validator

from adjustments import AdvancedSettings

CROP_RATIOS = ("original", "1:1", "4:3", "3:2", "16:9")
FORMATS = ("jpeg", "png", "tiff", "webp")


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
    # `crop` names the ratio the crop tool is locked to, which the UI needs to
    # restore its state. The rectangle below is what actually gets cut, in
    # fractions of the rotated frame, so a free crop needs no named ratio.
    crop: str = Field("original", pattern="^(original|free|custom|1:1|4:3|3:2|16:9)$")
    crop_x: float = Field(0, ge=0, le=1)
    crop_y: float = Field(0, ge=0, le=1)
    crop_w: float = Field(1, gt=0, le=1)
    crop_h: float = Field(1, gt=0, le=1)
    monochrome: bool = False

    @model_validator(mode="after")
    def _crop_inside_frame(self):
        if self.crop_x + self.crop_w > 1.0001 or self.crop_y + self.crop_h > 1.0001:
            raise ValueError("자르기 영역이 사진 밖으로 나갑니다.")
        return self

    def crop_box(self, width: int, height: int):
        """Pixel box to cut from a rotated frame, or None to keep all of it."""
        if (self.crop_x, self.crop_y, self.crop_w, self.crop_h) != (0, 0, 1, 1):
            x0 = min(int(round(self.crop_x * width)), width - 1)
            y0 = min(int(round(self.crop_y * height)), height - 1)
            x1 = max(
                x0 + 1, min(int(round((self.crop_x + self.crop_w) * width)), width)
            )
            y1 = max(
                y0 + 1, min(int(round((self.crop_y + self.crop_h) * height)), height)
            )
            return x0, y0, x1, y1
        # Libraries saved before the crop tool existed only carry a ratio name,
        # which used to mean a centred crop.
        if self.crop in ("original", "free", "custom"):
            return None
        rw, rh = map(int, self.crop.split(":"))
        ratio = rw / rh
        nw, nh = (
            (max(1, int(height * ratio)), height)
            if width / height > ratio
            else (width, max(1, int(width / ratio)))
        )
        x, y = (width - nw) // 2, (height - nh) // 2
        return x, y, x + nw, y + nh
