from __future__ import annotations

import dataclasses
import enum
import typing

from nion.utils import Platform


@dataclasses.dataclass
class FontMetrics:
    width: int
    height: int
    ascent: int
    descent: int
    leading: int


class TruncateModeType(enum.IntEnum):
    LEFT = 0
    RIGHT = 1
    MIDDLE = 2
    NONE = 3


class UISettings(typing.Protocol):

    def get_font_metrics(self, font: str, text: str) -> FontMetrics:
        ...

    def truncate_string_to_width(self, font_str: str, text: str, pixel_width: int, mode: TruncateModeType) -> str:
        ...

    @property
    def cursor_tolerance(self) -> float: raise NotImplementedError()


class DisplayStyle:
    # font sizes are as drawn on a 96dpi device
    _FONT_SIZES_PT: typing.Mapping[str, float] = {
        "scale-marker": 10,
        "axis-label": 9,
        "axis-label-superscript": 7,
        "legend": 9,
        "interval-label": 9,
        "graphic-label": 9,
    }

    def __init__(self) -> None:
        self.__font_sizes_pt = dict(self._FONT_SIZES_PT)

    def get_font_size_pt(self, part: str) -> float:
        return self.__font_sizes_pt.get(part, 9)

    def get_font(self, part: str, drawing_metrics: DrawingMetrics) -> str:
        """Get the complete font string for a display style part."""
        size_pt = self.get_font_size_pt(part) * drawing_metrics.scale * 96.0 / drawing_metrics.device_dpi
        scaled_size_str = f"{size_pt:.2f}".rstrip("0").rstrip(".")
        return f"normal {scaled_size_str}pt Helvetica, Arial, sans-serif"


@dataclasses.dataclass
class DrawingFontMetrics:
    width: float
    height: float
    ascent: float
    descent: float
    leading: float


class DrawingMetrics:
    def __init__(self, ui_settings: UISettings, ppi: float | None = None, device_dpi: float | None = None) -> None:
        self.__ui_settings = ui_settings
        self.__ppi = ppi
        self.__device_dpi = device_dpi

    @property
    def _ui_settings(self) -> UISettings:
        # for debugging
        return self.__ui_settings

    @property
    def cursor_tolerance(self) -> float:
        return self.__ui_settings.cursor_tolerance

    @property
    def device_dpi(self) -> float:
        return self.__device_dpi if self.__device_dpi else 96.0

    @property
    def scale(self) -> float:
        return self.__ppi / 96.0 if self.__ppi else 1.0

    def scale_length(self, px: float) -> float:
        return px * self.scale

    def scale_stroke(self, px: float) -> float:
        device_pixel = 96.0 / self.__ppi if self.__ppi else 0.0
        return max(px, 2/3, device_pixel) * self.scale

    def get_font_metrics(self, font: str, text: str) -> DrawingFontMetrics:
        # return font metrics in 96dpi units
        # macos measures fonts in 72dpi units, so needs to multiply by 4/3
        # windows and svg measure fonts in 96dpi units, so no adjustment
        # cast is a temporary workaround while typing is updated
        font_metrics = typing.cast(DrawingFontMetrics, typing.cast(object, self.__ui_settings.get_font_metrics(font, text)))
        font_scale = self.device_dpi / 72.0 if Platform.is_macos() else 1.0
        return DrawingFontMetrics(
            font_metrics.width * font_scale,
            font_metrics.height * font_scale,
            font_metrics.ascent * font_scale,
            font_metrics.descent * font_scale,
            font_metrics.leading * font_scale,
        )
