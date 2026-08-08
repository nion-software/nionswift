from __future__ import annotations

import dataclasses
import enum
import typing


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


_PT_TO_PX = 4 / 3  # 1pt = 1/72in, 1px = 1/96in


class DisplayStyle:
    _FONT_SIZES_PX: typing.Mapping[str, float] = {
        "scale-marker": 14 / _PT_TO_PX,
        "axis-label": 12 / _PT_TO_PX,
        "axis-label-superscript": 10 / _PT_TO_PX,
        "interval-label": 12 / _PT_TO_PX,
        "graphic-label": 11 / _PT_TO_PX,
    }

    def __init__(self, font_sizes_px: typing.Mapping[str, float] | None = None) -> None:
        self.__font_sizes_px = dict(font_sizes_px) if font_sizes_px is not None else dict(self._FONT_SIZES_PX)

    def get_font_size(self, part: str) -> float:
        return self.__font_sizes_px.get(part, 12 / _PT_TO_PX)

    def get_font(self, part: str, device_metrics: DrawingMetrics) -> str:
        """Get the complete font string for a display style part."""
        size_px = self.get_font_size(part)
        scaled_size_px = int(device_metrics.scale_font(size_px))
        return f"normal {scaled_size_px}px serif"


@dataclasses.dataclass
class DrawingMetrics:
    ui_settings: UISettings  # get_font_metrics, truncate_string_to_width
    ppi: float | None = None  # None for vector output

    @property
    def device_pixel(self) -> float:
        return 96 / self.ppi if self.ppi else 0.0

    @property
    def scale(self) -> float:
        return self.ppi / 96 if self.ppi else 1.0

    def scale_font(self, pt: float) -> float:
        return pt * _PT_TO_PX * self.scale

    def scale_length(self, px: float) -> float:
        return px * self.scale

    def scale_stroke(self, px: float) -> float:
        return max(px, 2/3, self.device_pixel) * self.scale
