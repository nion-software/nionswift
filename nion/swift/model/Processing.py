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
import scipy.signal.windows

# local libraries
from nion.data import Core
from nion.data import DataAndMetadata
from nion.data import xdata_1_0 as xd
from nion.swift.model import Symbolic
from nion.utils import Registry

if typing.TYPE_CHECKING:
    from nion.swift import Facade

PersistentDictType = typing.Dict[str, typing.Any]
_ImageDataType = DataAndMetadata._ImageDataType
_ProcessingResult = DataAndMetadata.DataAndMetadata | DataAndMetadata.ScalarAndMetadata | None

_ = gettext.gettext


class ProcessingComputation:
    """A computation handler that applies a processing base subclass point by point over navigable data.

    An individual processing computation is created for each processing base subclass when it is registered.
    """
    def __init__(self, processing_component: ProcessingBase, computation: Facade.Computation, **kwargs: typing.Any) -> None:
        self.computation = computation
        self.processing_component = processing_component
        self.__data_map = dict[str, _ImageDataType]()
        self.__xdata_map = dict[str, DataAndMetadata.DataAndMetadata]()
        self.__filter_xdata: DataAndMetadata.DataAndMetadata | None = None

    def __get_input_navigation_dimension_shape(self, **kwargs: typing.Any) -> DataAndMetadata.ShapeType | None:
        # return the common navigation dimension shape for all sources, ensuring that they are compatible.
        # if not input exists, or if inputs are mismatched in navigation dimension shape, datum dimension shape,
        # or the calibrations of either, raise an error.
        navigation_dimension_shape: DataAndMetadata.ShapeType | None = None
        navigation_calibrations: DataAndMetadata.CalibrationListType | None = None
        datum_dimension_shape: DataAndMetadata.ShapeType | None = None
        datum_calibrations: DataAndMetadata.CalibrationListType | None = None
        for source_d in self.processing_component.sources:
            source = Symbolic.ComputationProcessorSource.from_dict(source_d)
            data_source = typing.cast("Facade.DataSource | None", kwargs.get(source.name, None))
            xdata = data_source.xdata if data_source else None
            if xdata:
                if navigation_dimension_shape is None:
                    navigation_dimension_shape = xdata.navigation_dimension_shape
                if datum_dimension_shape is None:
                    datum_dimension_shape = xdata.datum_dimension_shape
                if navigation_calibrations is None:
                    navigation_calibrations = xdata.navigation_dimensional_calibrations
                if datum_calibrations is None:
                    datum_calibrations = xdata.datum_dimensional_calibrations
                # check whether all items have the same navigation dimension shapes
                if navigation_dimension_shape != xdata.navigation_dimension_shape:
                    raise ValueError("Mismatched navigation dimension shapes between sources.")
                # check whether all items have the same datum dimension shapes
                if datum_dimension_shape != xdata.datum_dimension_shape:
                    raise ValueError("Mismatched datum dimension shapes between sources.")
                # check whether all items have the same navigation dimension calibrations
                for i, cal in enumerate(xdata.navigation_dimensional_calibrations):
                    if navigation_calibrations[i] != cal:
                        raise ValueError("Mismatched navigation dimension calibrations between sources.")
                # check whether all items have the same datum dimension calibrations
                for i, cal in enumerate(xdata.datum_dimensional_calibrations):
                    if datum_calibrations[i] != cal:
                        raise ValueError("Mismatched datum dimension calibrations between sources.")
        if navigation_dimension_shape is None or datum_dimension_shape is None or navigation_calibrations is None or datum_calibrations is None:
            raise ValueError("Could not determine navigation and datum dimension shapes and calibrations from sources.")
        return navigation_dimension_shape

    def __get_input_data(self, index: tuple[slice | int | numpy.int32 | numpy.int64] | None, **kwargs: typing.Any) -> dict[str, DataAndMetadata.DataAndMetadata]:
        # return a map of source name to xdata for the given index. if index is None, return the full xdata for each source.
        data_map = dict[str, DataAndMetadata.DataAndMetadata]()
        for source_d in self.processing_component.sources:
            source = Symbolic.ComputationProcessorSource.from_dict(source_d)
            data_source = typing.cast("Facade.DataSource | None", kwargs.get(source.name, None))
            if data_source:
                xdata: DataAndMetadata.DataAndMetadata | None = None
                if index is not None:
                    xdata = data_source.xdata[index] if data_source.xdata and data_source.xdata.is_navigable else None
                # if the index is None, xdata will be None here. in that case, we use the element xdata from the data
                # source, which will be based on the UI collection index and slices.
                if xdata is None:
                    xdata = data_source.element_xdata
                if xdata:
                    if source.data_type == "xdata":
                        if source.is_croppable:
                            xdata = data_source._data_source._crop_xdata(xdata)
                    elif source.data_type == "filtered_xdata":
                        if not self.__filter_xdata:
                            self.__filter_xdata = data_source.filter_xdata
                        if self.__filter_xdata:
                            if xdata.is_data_complex_type:
                                xdata = Core.function_fourier_mask(xdata, self.__filter_xdata)
                            else:
                                xdata = self.__filter_xdata * xdata
                    else:
                        raise ValueError(f"Unsupported source data type: {source.data_type}")
                    if xdata:
                        data_map[source.name] = xdata
        return data_map

    def execute(self, **kwargs: typing.Any) -> None:
        # let the processing component do the processing and store results in the xdata map.
        is_mapped = self.processing_component.is_scalar or kwargs.get("mapping", "none") != "none"
        output_keys = [output["name"] for output in self.processing_component.outputs]
        navigation_dimension_shape = self.__get_input_navigation_dimension_shape(**kwargs)
        if is_mapped and navigation_dimension_shape is not None:
            src_name = self.processing_component.sources[0]["name"]
            data_source = typing.cast("Facade.DataSource", kwargs[src_name])
            xdata = data_source.xdata
            assert xdata
            indexes = numpy.ndindex(xdata.navigation_dimension_shape)
            for index in indexes:
                data_sources = self.__get_input_data(index, **kwargs)
                index_kw_args = dict[str, typing.Any]()
                for k, v in list(kwargs.items()):
                    if k not in data_sources:
                        index_kw_args[k] = v
                processed_data_map = self.processing_component.process(data_sources, **index_kw_args)
                for key, processed_data in processed_data_map.items():
                    assert key in output_keys
                    if isinstance(processed_data, DataAndMetadata.DataAndMetadata):
                        # handle array data
                        index_xdata = processed_data
                        if key not in self.__xdata_map:
                            self.__data_map[key] = numpy.empty(xdata.navigation_dimension_shape + index_xdata.datum_dimension_shape, dtype=index_xdata.data_dtype)
                            self.__xdata_map[key] = DataAndMetadata.new_data_and_metadata(
                                self.__data_map[key], index_xdata.intensity_calibration,
                                tuple(xdata.navigation_dimensional_calibrations) + tuple(index_xdata.datum_dimensional_calibrations),
                                None, None, DataAndMetadata.DataDescriptor(xdata.is_sequence, xdata.collection_dimension_count, index_xdata.datum_dimension_count))
                        self.__data_map[key][index] = index_xdata.data
                    elif isinstance(processed_data, DataAndMetadata.ScalarAndMetadata):
                        # handle scalar data
                        index_scalar = processed_data
                        if key not in self.__xdata_map:
                            self.__data_map[key] = numpy.empty(xdata.navigation_dimension_shape, dtype=type(index_scalar.value))
                            is_sequence = xdata.is_sequence and xdata.collection_dimension_count == 2
                            datum_dimension_count = min(2, xdata.navigation_dimension_count)
                            self.__xdata_map[key] = DataAndMetadata.new_data_and_metadata(
                                self.__data_map[key], index_scalar.calibration,
                                tuple(xdata.navigation_dimensional_calibrations),
                                None, None, DataAndMetadata.DataDescriptor(is_sequence, 0, datum_dimension_count))
                        self.__data_map[key][index] = index_scalar.value
        elif not self.processing_component.is_scalar:
            data_sources = self.__get_input_data(None, **kwargs)
            index_kw_args = dict[str, typing.Any]()
            for k, v in list(kwargs.items()):
                if k not in data_sources:
                    index_kw_args[k] = v
            processed_data_map = self.processing_component.process(data_sources, **index_kw_args)
            for key, processed_data in processed_data_map.items():
                assert key in output_keys
                if isinstance(processed_data, DataAndMetadata.DataAndMetadata):
                    self.__xdata_map[key] = processed_data

    def commit(self) -> None:
        # this is guaranteed to run on the main thread.
        for output_d in self.processing_component.outputs:
            key = output_d["name"]
            xdata = self.__xdata_map.get(key, None)
            if xdata:
                self.computation.set_referenced_xdata(key, xdata)


class ProcessingBase:
    def __init__(self) -> None:
        self.processing_id = str()
        self.title = str()
        self.sections = set[str]()
        self.sources = list[PersistentDictType]()
        self.parameters = list[PersistentDictType]()
        self.outputs = list[PersistentDictType]()
        self.attributes: PersistentDictType = dict()
        # if processing is mappable, it can be applied to elements of a sequence/collection (navigable) data item
        self.is_mappable = False
        # if processing produces scalar data, it must be applied to a sequence/collection (navigable) data item
        self.is_scalar = False

    def register_computation(self) -> None:
        Symbolic.register_computation_type(self.processing_id, functools.partial(ProcessingComputation, self))

    def process(self, data_sources: typing.Mapping[str, DataAndMetadata.DataAndMetadata], **kwargs: typing.Any) -> typing.Mapping[str, _ProcessingResult]:
        raise NotImplementedError()


class ProcessingFFT(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "fft"
        self.title = _("FFT")
        self.sections = {"fourier"}
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True, "data_type": "xdata", "requirements": [{"type": "datum_rank", "values": (1, 2)}]},
        ]
        self.outputs = [
            {"name": "target", "label": _("Result")},
        ]
        self.is_mappable = True

    def process(self, data_sources: typing.Mapping[str, DataAndMetadata.DataAndMetadata], **kwargs: typing.Any) -> typing.Mapping[str, _ProcessingResult]:
        src_xdata = data_sources.get("src", None)
        if src_xdata:
            return {"target": xd.fft(src_xdata)}
        return dict()


class ProcessingIFFT(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "inverse_fft"
        self.title = _("Inverse FFT")
        self.sections = {"fourier"}
        self.sources = [
            {"name": "src", "label": _("Source"), "use_display_data": False, "data_type": "xdata", "requirements": [{"type": "datum_rank", "values": (1, 2)}]},
        ]
        self.outputs = [
            {"name": "target", "label": _("Result")},
        ]

    def process(self, data_sources: typing.Mapping[str, DataAndMetadata.DataAndMetadata], **kwargs: typing.Any) -> typing.Mapping[str, _ProcessingResult]:
        src_xdata = data_sources.get("src", None)
        if src_xdata:
            return {"target": xd.ifft(src_xdata)}
        return dict()


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
                "data_type": "xdata",
                "requirements": [
                    {"type": "datum_rank", "values": (1, 2)},
                    {"type": "datum_calibrations", "units": "equal"},
                ]
            },
        ]
        self.parameters = [
            {"name": "sigma", "type": "real", "value": 1.0}
        ]
        self.outputs = [
            {"name": "target", "label": _("Result")},
        ]
        self.is_mappable = True

    def process(self, data_sources: typing.Mapping[str, DataAndMetadata.DataAndMetadata], **kwargs: typing.Any) -> typing.Mapping[str, _ProcessingResult]:
        src_xdata = data_sources.get("src", None)
        sigma = kwargs.get("sigma", 1.0)
        if src_xdata and src_xdata.datum_dimension_count == 1:
            w = src_xdata.datum_dimension_shape[0]
            return {"target": src_xdata * scipy.signal.windows.gaussian(src_xdata.datum_dimension_shape[0], std=w / 2)}
        elif src_xdata and src_xdata.datum_dimension_count == 2:
            # uses circularly rotated approach of generating 2D filter from 1D
            h, w = src_xdata.datum_dimension_shape
            y, x = numpy.meshgrid(numpy.linspace(-h / 2, h / 2, h), numpy.linspace(-w / 2, w / 2, w), indexing='ij')
            s = 1 / (min(w, h) * sigma)
            r = numpy.sqrt(y * y + x * x) * s
            return {"target": src_xdata * numpy.exp(-0.5 * r * r)}
        return dict()


class ProcessingHammingWindow(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "hamming_window"
        self.title = _("Hamming Window")
        self.sections = {"windows"}
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True, "data_type": "xdata", "requirements": [{"type": "datum_rank", "values": (1, 2)}]},
        ]
        self.outputs = [
            {"name": "target", "label": _("Result")},
        ]
        self.is_mappable = True

    def process(self, data_sources: typing.Mapping[str, DataAndMetadata.DataAndMetadata], **kwargs: typing.Any) -> typing.Mapping[str, _ProcessingResult]:
        src_xdata = data_sources.get("src", None)
        if src_xdata and src_xdata.datum_dimension_count == 1:
            return {"target": src_xdata * scipy.signal.windows.hamming(src_xdata.datum_dimension_shape[0])}
        elif src_xdata and src_xdata.datum_dimension_count == 2:
            # uses outer product approach of generating 2D filter from 1D
            h, w = src_xdata.datum_dimension_shape
            w0 = numpy.reshape(scipy.signal.windows.hamming(w), (1, w))
            w1 = numpy.reshape(scipy.signal.windows.hamming(h), (h, 1))
            return {"target": src_xdata * w0 * w1}
        return dict()


class ProcessingHannWindow(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "hann_window"
        self.title = _("Hann Window")
        self.sections = {"windows"}
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True, "data_type": "xdata", "requirements": [{"type": "datum_rank", "values": (1, 2)}]},
        ]
        self.outputs = [
            {"name": "target", "label": _("Result")},
        ]
        self.is_mappable = True

    def process(self, data_sources: typing.Mapping[str, DataAndMetadata.DataAndMetadata], **kwargs: typing.Any) -> typing.Mapping[str, _ProcessingResult]:
        src_xdata = data_sources.get("src", None)
        if src_xdata and  src_xdata.datum_dimension_count == 1:
            return {"target": src_xdata * scipy.signal.windows.hann(src_xdata.datum_dimension_shape[0])}
        elif src_xdata and src_xdata.datum_dimension_count == 2:
            # uses outer product approach of generating 2D filter from 1D
            h, w = src_xdata.datum_dimension_shape
            w0 = numpy.reshape(scipy.signal.windows.hann(w), (1, w))
            w1 = numpy.reshape(scipy.signal.windows.hann(h), (h, 1))
            return {"target": src_xdata * w0 * w1}
        return dict()


class ProcessingMappedSum(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "mapped_sum"
        self.title = _("Mapped Sum")
        self.sections = {"scalar-maps"}
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True, "data_type": "filtered_xdata", "requirements": [{"type": "datum_rank", "values": (1, 2)}]},
        ]
        self.outputs = [
            {"name": "target", "label": _("Result")},
        ]
        self.is_mappable = True
        self.is_scalar = True
        self.attributes["connection_type"] = "map"

    def process(self, data_sources: typing.Mapping[str, DataAndMetadata.DataAndMetadata], **kwargs: typing.Any) -> typing.Mapping[str, _ProcessingResult]:
        filtered_xdata = data_sources.get("src", None)
        if filtered_xdata:
            return {"target": DataAndMetadata.ScalarAndMetadata.from_value(numpy.sum(filtered_xdata), filtered_xdata.intensity_calibration)}
        return dict()


class ProcessingMappedAverage(ProcessingBase):
    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__()
        self.processing_id = "mapped_average"
        self.title = _("Mapped Average")
        self.sections = {"scalar-maps"}
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True, "data_type": "filtered_xdata", "requirements": [{"type": "datum_rank", "values": (1, 2)}]},
        ]
        self.outputs = [
            {"name": "target", "label": _("Result")}
        ]
        self.is_mappable = True
        self.is_scalar = True
        self.attributes["connection_type"] = "map"

    def process(self, data_sources: typing.Mapping[str, DataAndMetadata.DataAndMetadata], **kwargs: typing.Any) -> typing.Mapping[str, _ProcessingResult]:
        filtered_xdata = data_sources.get("src", None)
        if filtered_xdata:
            return {"target": DataAndMetadata.ScalarAndMetadata.from_value(numpy.average(filtered_xdata), filtered_xdata.intensity_calibration)}
        return dict()


# registered components show up in two places in the UI:
#  - in the Processing > Fourier sub-menu if they have 'windows' in the 'sections' property.
#  - as menu items referencing the processing_id.

# Registry.register_component(ProcessingFFT(), {"processing-component"})
# Registry.register_component(ProcessingIFFT(), {"processing-component"})
Registry.register_component(ProcessingGaussianWindow(), {"processing-component"})
Registry.register_component(ProcessingHammingWindow(), {"processing-component"})
Registry.register_component(ProcessingHannWindow(), {"processing-component"})
Registry.register_component(ProcessingMappedSum(), {"processing-component"})
Registry.register_component(ProcessingMappedAverage(), {"processing-component"})


def init() -> None: pass
