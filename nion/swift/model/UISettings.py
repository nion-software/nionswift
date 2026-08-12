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


class DisplayStyle:
    _FONT_SIZES_PT: typing.Mapping[str, float] = {
        "scale-marker": 14,
        "axis-label": 12,
        "axis-label-superscript": 10,
        "legend": 12,
        "interval-label": 12,
        "graphic-label": 12,
    }

    def __init__(self) -> None:
        self.__font_sizes_pt = dict(self._FONT_SIZES_PT)

    def get_font_size(self, part: str) -> float:
        return self.__font_sizes_pt.get(part, 12)

    def get_font(self, part: str, device_metrics: DrawingMetrics) -> str:
        """Get the complete font string for a display style part."""
        size_pt = self.get_font_size(part) * device_metrics.scale
        scaled_size_str = f"{size_pt:.2f}".rstrip("0").rstrip(".")
        return f"normal {scaled_size_str}pt Helvetica, Arial, sans-serif"


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

    def scale_length(self, px: float) -> float:
        return px * self.scale

    def scale_stroke(self, px: float) -> float:
        return max(px, 2/3, self.device_pixel) * self.scale
