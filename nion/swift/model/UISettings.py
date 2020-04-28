import abc
import collections


FontMetrics = collections.namedtuple("FontMetrics", ["width", "height", "ascent", "descent", "leading"])


class UISettings(abc.ABC):

    @abc.abstractmethod
    def get_font_metrics(self, font: str, text: str) -> FontMetrics:
        ...

    @property
    @abc.abstractmethod
    def cursor_tolerance(self) -> float:
        ...
