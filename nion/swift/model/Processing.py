# standard libraries
import copy
import functools
import gettext
import typing

# third party libraries
import numpy

# local libraries
from nion.data import DataAndMetadata
from nion.data import xdata_1_0 as xd
from nion.swift.model import DataItem
from nion.swift.model import Symbolic
from nion.utils import Registry

if typing.TYPE_CHECKING:
    from nion.swift import Facade

_ = gettext.gettext


class ProcessingComputation:
    def __init__(self, processing_component: "ProcessingBase", computation: "Facade.Computation", **kwargs):
        self.computation = computation
        self.processing_component = processing_component
        self.__data = None
        self.__xdata = None

    def execute(self, **kwargs):
        # let the processing component do the processing and store result in the xdata field.
        # TODO: handle multiple sources (broadcasting)
        is_mapped = self.processing_component.is_scalar or kwargs.get("mapping", "none") != "none"
        if is_mapped and len(self.processing_component.sources) == 1 and kwargs[self.processing_component.sources[0]["name"]].xdata.is_collection:
            src_name = self.processing_component.sources[0]["name"]
            data_source = typing.cast("Facade.DataSource", kwargs[src_name])
            xdata = data_source.xdata
            self.__xdata = None
            for index in numpy.ndindex(xdata.navigation_dimension_shape):
                index_data_source = DataItem.DataSource(data_source.display_item._display_item, data_source.graphic._graphic, xdata[index])
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
                    self.__data[index] = index_scalar.value
        elif not self.processing_component.is_scalar:
            self.__xdata = self.processing_component.process(**kwargs)

    def commit(self):
        # store the xdata into the target. this is guaranteed to run on the main thread.
        self.computation.set_referenced_xdata("target", self.__xdata)


class ProcessingBase:
    def __init__(self):
        self.processing_id = str()
        self.title = str()
        self.sources = list()
        self.parameters = list()
        self.is_mappable = False
        self.is_scalar = False

    def make_xdata(self, name: str, data_source: "Facade.DataSource"):
        for source in self.sources:
            if name == source["name"]:
                if source.get("use_display_data", True):
                    if source.get("croppable", False):
                        return data_source.cropped_display_xdata
                    elif source.get("use_filtered_data", False):
                        return data_source.display_xdata * data_source.filter_xdata
                    else:
                        return data_source.display_xdata
                else:
                    if source.get("croppable", False):
                        return data_source.cropped_xdata
                    elif source.get("use_filtered_data", False):
                        return data_source.filtered_xdata
                    else:
                        return data_source.xdata
        return data_source

    def register_computation(self) -> None:
        Symbolic.register_computation_type(self.processing_id, functools.partial(ProcessingComputation, self))

    def process(self, *, src: DataItem.DataSource, **kwargs) -> typing.Union[DataAndMetadata.DataAndMetadata, DataAndMetadata.ScalarAndMetadata]: ...


class ProcessingFFT(ProcessingBase):
    def __init__(self, **kwargs):
        super().__init__()
        self.processing_id = "fft"
        self.title = _("FFT")
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True},
        ]
        self.is_mappable = True

    def process(self, *, src: DataItem.DataSource, **kwargs) -> typing.Union[DataAndMetadata.DataAndMetadata, DataAndMetadata.ScalarAndMetadata]:
        return xd.fft(src.cropped_display_xdata)


class ProcessingIFFT(ProcessingBase):
    def __init__(self, **kwargs):
        super().__init__()
        self.processing_id = "inverse-fft"
        self.title = _("Inverse FFT")
        self.sources = [
            {"name": "src", "label": _("Source"), "use_display_data": False},
        ]

    def process(self, *, src: DataItem.DataSource, **kwargs) -> typing.Union[DataAndMetadata.DataAndMetadata, DataAndMetadata.ScalarAndMetadata]:
        return xd.ifft(src.xdata)


class ProcessingMappedSum(ProcessingBase):
    def __init__(self, **kwargs):
        super().__init__()
        self.processing_id = "mapped-sum"
        self.title = _("Mapped Sum")
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True},
        ]
        self.is_mappable = True
        self.is_scalar = True

    def process(self, *, src: DataItem.DataSource, **kwargs) -> typing.Union[DataAndMetadata.DataAndMetadata, DataAndMetadata.ScalarAndMetadata]:
        filtered_xdata = src.filtered_xdata
        return DataAndMetadata.ScalarAndMetadata.from_value(numpy.sum(filtered_xdata), filtered_xdata.intensity_calibration)


class ProcessingMappedAverage(ProcessingBase):
    def __init__(self, **kwargs):
        super().__init__()
        self.processing_id = "mapped-average"
        self.title = _("Mapped Average")
        self.sources = [
            {"name": "src", "label": _("Source"), "croppable": True},
        ]
        self.is_mappable = True
        self.is_scalar = True

    def process(self, *, src: DataItem.DataSource, **kwargs) -> typing.Union[DataAndMetadata.DataAndMetadata, DataAndMetadata.ScalarAndMetadata]:
        filtered_xdata = src.filtered_xdata
        return DataAndMetadata.ScalarAndMetadata.from_value(numpy.average(filtered_xdata), filtered_xdata.intensity_calibration)


# Registry.register_component(ProcessingFFT(), {"processing-component"})
# Registry.register_component(ProcessingIFFT(), {"processing-component"})
Registry.register_component(ProcessingMappedSum(), {"processing-component"})
Registry.register_component(ProcessingMappedAverage(), {"processing-component"})


def init(): pass
