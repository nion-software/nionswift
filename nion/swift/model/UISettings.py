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

    _FONT_SIZES: typing.Mapping[str, int] = {
        "scale-marker": 14,
        "axis-label": 12,
        "interval-label": 12,
        "graphic-label": 11,
    }

    def __init__(self, font_sizes: typing.Mapping[str, int] | None = None) -> None:
        self.__font_sizes = dict(font_sizes) if font_sizes is not None else dict(self._FONT_SIZES)

    def get_font_size(self, part: str) -> int:
        return self.__font_sizes.get(part, 12)


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
        return pt * 4/3 * self.scale

    def scale_length(self, px: float) -> float:
        return px * self.scale

    def scale_stroke(self, px: float) -> float:
        return max(px, 2/3, self.device_pixel) * self.scale
