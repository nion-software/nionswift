"""
Provide a library of processing functions.

The processing functions declare their item sources and input parameters along with a identifier, title, and
what UI sections they are likely to appear in.

The processing functions also declare how they are applied to sequences/collections and what form
their output takes (scalar or not).
"""

from __future__ import annotations

# standard libraries
import functools
import gettext
import typing

# third party libraries
import numpy
import scipy.signal

# local libraries
from nion.data import DataAndMetadata
from nion.data import xdata_1_0 as xd
from nion.swift.model import DataItem
from nion.swift.model import Symbolic
from nion.utils import Registry

if typing.TYPE_CHECKING:
    from nion.swift import Facade

PersistentDictType = typing.Dict[str, typing.Any]
_ImageDataType = DataAndMetadata._ImageDataType
_ProcessingResult = typing.Union[DataAndMetadata.DataAndMetadata, DataAndMetadata.ScalarAndMetadata, None]

_ = gettext.gettext


class ProcessingComputation:
    def __init__(self, processing_component: ProcessingBase, computation: Facade.Computation, **kwargs: typing.Any) -> None:
        self.computation = computation
        self.processing_component = processing_component
        self.__data: typing.Optional[_ImageDataType] = None
        self.__xdata: typing.Optional[_ProcessingResult] = None

    def execute(self, **kwargs: typing.Any) -> None:
        # let the processing component do the processing and store result in the xdata field.
        # TODO: handle multiple sources (broadcasting)
        is_mapped = self.processing_component.is_scalar or kwargs.get("mapping", "none") != "none"
        if is_mapped and len(self.processing_component.sources) == 1 and kwargs[self.processing_component.sources[0]["name"]].xdata.is_collection:
            src_name = self.processing_component.sources[0]["name"]
            data_source = typing.cast("Facade.DataSource", kwargs[src_name])
            xdata = data_source.xdata
            assert xdata
            self.__xdata = None
            indexes = numpy.ndindex(xdata.navigation_dimension_shape)
            for index in indexes:
                index_data_source = DataItem.DataSource(data_source._display_data_channel, data_source.graphic._graphic if data_source.graphic else None, xdata[index])
                index_kw_args = {next(iter(kwargs.keys())): index_data_source}
                for k, v in list(kwargs.items())[1:]:
                    index_kw_args[k] = v
                processed_data = self.processing_component.process(**index_kw_args)
                if isinstance(processed_data, DataAndMetadata.DataAndMetadata):
                    # handle array data
                    index_xdata = processed_data
                    if self.__xdata is None:
                        self.__data = numpy.empty(xdata.navigation_dimension_shape + index_xdata.datum_dimension_shape, dtype=index_xdata.data_dtype)
                        self.__xdata = DataAndMetadata.new_data_and_metadata(
                            self.__data, index_xdata.intensity_calibration,
                            tuple(xdata.navigation_dimensional_calibrations) + tuple(index_xdata.datum_dimensional_calibrations),
                            None, None, DataAndMetadata.DataDescriptor(xdata.is_sequence, xdata.collection_dimension_count, index_xdata.datum_dimension_count))
                    if self.__data is not None:
                        self.__data[index] = index_xdata.data
                elif isinstance(processed_data, DataAndMetadata.ScalarAndMetadata):
                    # handle scalar data
                    index_scalar = processed_data
                    if self.__xdata is None:
                        self.__data = numpy.empty(xdata.navigation_dimension_shape, dtype=type(index_scalar.value))
                        self.__xdata = DataAndMetadata.new_data_and_metadata(
                            self.__data, index_scalar.calibration,
                            tuple(xdata.navigation_dimensional_calibrations),
                            None, None, DataAndMetadata.DataDescriptor(xdata.is_sequence, 0, xdata.collection_dimension_count))
                    if self.__data is not None:
                        self.__data[index] = index_scalar.value
        elif not self.processing_component.is_scalar:
            self.__xdata = self.processing_component.process(**kwargs)

    def commit(self) -> None:
        # store the xdata into the target. this is guaranteed to run on the main thread.
        if self.__xdata:
            self.computation.set_referenced_xdata("target", typing.cast(DataAndMetadata.DataAndMetadata, self.__xdata))


class ProcessingBase:
    def __init__(self) -> None:
        self.processing_id = str()
        self.title = str()
        self.sections: typing.Set[str] = set()
        self.sources: typing.List[PersistentDictType] = list()
        self.parameters: typing.List[PersistentDictType] = list()
        self.attributes: PersistentDictType = dict()
        self.is_mappable = False
        self.is_scalar = False

    def register_computation(self) -> None:
        Symbolic.register_computation_type(self.processing_id, functools.partial(ProcessingComputation, self))

    def process(self, *, src: DataItem.DataSource, **kwargs: typing.Any) -> _ProcessingResult: ...


class ProcessingFFT(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "fft"
        self.title = _("FFT")
        self.sections = {"fourier"}
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True, "requirements": [{"type": "datum_rank", "values": (1, 2)}]},
        ]
        self.is_mappable = True

    def process(self, *, src: DataItem.DataSource, **kwargs: typing.Any) -> _ProcessingResult:
        cropped_display_xdata = src.cropped_display_xdata
        return xd.fft(cropped_display_xdata) if cropped_display_xdata else None


class ProcessingIFFT(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "inverse_fft"
        self.title = _("Inverse FFT")
        self.sections = {"fourier"}
        self.sources = [
            {"name": "src", "label": _("Source"), "use_display_data": False, "requirements": [{"type": "datum_rank", "values": (1, 2)}]},
        ]

    def process(self, *, src: DataItem.DataSource, **kwargs: typing.Any) -> _ProcessingResult:
        src_xdata = src.xdata
        return xd.ifft(src_xdata) if src_xdata else None


class ProcessingGaussianWindow(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "gaussian_window"
        self.title = _("Gaussian Window")
        self.sections = {"windows"}
        self.sources = [
            {
                "name": "src",
                "label": _("Source"),
                "croppable": True,
                "requirements": [
                    {"type": "datum_rank", "values": (1, 2)},
                    {"type": "datum_calibrations", "units": "equal"},
                ]
            },
        ]
        self.parameters = [
            {"name": "sigma", "type": "real", "value": 1.0}
        ]
        self.is_mappable = True

    def process(self, *, src: DataItem.DataSource, **kwargs: typing.Any) -> _ProcessingResult:
        sigma = kwargs.get("sigma", 1.0)
        src_xdata = src.xdata
        if src_xdata and src_xdata.datum_dimension_count == 1:
            w = src_xdata.datum_dimension_shape[0]
            return src_xdata * scipy.signal.gaussian(src_xdata.datum_dimension_shape[0], std=w / 2)  # type: ignore
        elif src_xdata and src_xdata.datum_dimension_count == 2:
            # uses circularly rotated approach of generating 2D filter from 1D
            h, w = src_xdata.datum_dimension_shape
            y, x = numpy.meshgrid(numpy.linspace(-h / 2, h / 2, h), numpy.linspace(-w / 2, w / 2, w))
            s = 1 / (min(w, h) * sigma)
            r = numpy.sqrt(y * y + x * x) * s
            return src_xdata * numpy.exp(-0.5 * r * r)  # type: ignore
        return None


class ProcessingHammingWindow(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "hamming_window"
        self.title = _("Hamming Window")
        self.sections = {"windows"}
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True, "requirements": [{"type": "datum_rank", "values": (1, 2)}]},
        ]
        self.is_mappable = True

    def process(self, *, src: DataItem.DataSource, **kwargs: typing.Any) -> _ProcessingResult:
        src_xdata = src.xdata
        if src_xdata and src_xdata.datum_dimension_count == 1:
            return src_xdata * scipy.signal.hamming(src_xdata.datum_dimension_shape[0])  # type: ignore
        elif src_xdata and src_xdata.datum_dimension_count == 2:
            # uses outer product approach of generating 2D filter from 1D
            h, w = src_xdata.datum_dimension_shape
            w0 = numpy.reshape(scipy.signal.hamming(w), (1, w))
            w1 = numpy.reshape(scipy.signal.hamming(h), (h, 1))
            return src_xdata * w0 * w1
        return None


class ProcessingHannWindow(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "hann_window"
        self.title = _("Hann Window")
        self.sections = {"windows"}
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True, "requirements": [{"type": "datum_rank", "values": (1, 2)}]},
        ]
        self.is_mappable = True

    def process(self, *, src: DataItem.DataSource, **kwargs: typing.Any) -> _ProcessingResult:
        src_xdata = src.xdata
        if src_xdata and  src_xdata.datum_dimension_count == 1:
            return src_xdata * scipy.signal.hann(src_xdata.datum_dimension_shape[0])  # type: ignore
        elif src_xdata and src_xdata.datum_dimension_count == 2:
            # uses outer product approach of generating 2D filter from 1D
            h, w = src_xdata.datum_dimension_shape
            w0 = numpy.reshape(scipy.signal.hann(w), (1, w))
            w1 = numpy.reshape(scipy.signal.hann(h), (h, 1))
            return src_xdata * w0 * w1
        return None


class ProcessingMappedSum(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "mapped_sum"
        self.title = _("Mapped Sum")
        self.sections = {"scalar-maps"}
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True, "requirements": [{"type": "datum_rank", "values": (1, 2)}]},
        ]
        self.is_mappable = True
        self.is_scalar = True
        self.attributes["connection_type"] = "map"

    def process(self, *, src: DataItem.DataSource, **kwargs: typing.Any) -> _ProcessingResult:
        filtered_xdata = src.filtered_xdata
        if filtered_xdata:
            return DataAndMetadata.ScalarAndMetadata.from_value(numpy.sum(filtered_xdata), filtered_xdata.intensity_calibration)
        return None


class ProcessingMappedAverage(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "mapped_average"
        self.title = _("Mapped Average")
        self.sections = {"scalar-maps"}
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True, "requirements": [{"type": "datum_rank", "values": (1, 2)}]},
        ]
        self.is_mappable = True
        self.is_scalar = True
        self.attributes["connection_type"] = "map"

    def process(self, *, src: DataItem.DataSource, **kwargs: typing.Any) -> _ProcessingResult:
        filtered_xdata = src.filtered_xdata
        if filtered_xdata:
            return DataAndMetadata.ScalarAndMetadata.from_value(numpy.average(filtered_xdata), filtered_xdata.intensity_calibration)  # type: ignore
        return None


# Registry.register_component(ProcessingFFT(), {"processing-component"})
# Registry.register_component(ProcessingIFFT(), {"processing-component"})
Registry.register_component(ProcessingGaussianWindow(), {"processing-component"})
Registry.register_component(ProcessingHammingWindow(), {"processing-component"})
Registry.register_component(ProcessingHannWindow(), {"processing-component"})
Registry.register_component(ProcessingMappedSum(), {"processing-component"})
Registry.register_component(ProcessingMappedAverage(), {"processing-component"})


def init() -> None: pass
