import dataclasses
import typing


@dataclasses.dataclass
class FontMetrics:
    width: int
    height: int
    ascent: int
    descent: int
    leading: int


class UISettings(typing.Protocol):

    def get_font_metrics(self, font: str, text: str) -> FontMetrics:
        ...

    @property
    def cursor_tolerance(self) -> float: raise NotImplementedError()
