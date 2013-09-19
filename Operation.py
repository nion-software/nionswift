# standard libraries
import copy
import gettext
import logging
import math
import sys
import threading
import uuid
import weakref

# third party libraries
import numpy
import scipy
import scipy.fftpack
import scipy.ndimage

# local libraries
from nion.swift import Image
from nion.swift import DataItem
from nion.swift import Graphics
from nion.swift import Storage

_ = gettext.gettext


class Operation(Storage.StorageBase):
    """
        Operation represents an operation on numpy data array.
        Pass in a description during construction. The description
        should describe what parameters are editable and how they
        are connected to the operation.
        """
    def __init__(self, name, description=None):
        Storage.StorageBase.__init__(self)

        self.storage_properties += ["enabled"]
        self.storage_type = "operation"
        self.name = name
        self.__enabled = True
        self.description = description if description else []
        self.properties = [dict["property"] for dict in self.description]
        self.values = {}
        for dict in self.description:
            value = dict["default"]
            # TODO: allow defaults to be specified as functions?
            #if inspect.isfunction(value):
            #   value = value()
            self.values[dict["property"]] = value
        self.defaults = copy.deepcopy(self.values)
        self.storage_properties += self.properties
        self.__initialized = True
    @classmethod
    def build(cls, storage_reader, item_node):
        operation = cls()
        operation.enabled = storage_reader.get_property(item_node, "enabled", True)
        for property in operation.properties:
            setattr(operation, property, storage_reader.get_property(item_node, property, operation.defaults[property]))
        return operation
    # enabled property
    def __get_enabled(self):
        return self.__enabled
    def __set_enabled(self, enabled):
        self.__enabled = enabled
        self.notify_set_property("enabled", enabled)
    enabled = property(__get_enabled, __set_enabled)
    # handle properties from the description of the operation.
    def __getattr__(self, name):
        if name in self.properties:
            return self.values[name]
        logging.debug("Operation attribute missing %s", name)
        raise AttributeError
    def __setattr__(self, name, value):
        if not self.__dict__.has_key('_Operation__initialized'):  # this test allows attributes to be set in the __init__ method
            return object.__setattr__(self, name, value)
        if name in self.properties:
            self.values[name] = value
            self.notify_set_property(name, value)
        else:
            object.__setattr__(self, name, value)
    # subclasses can override this method to perform processing on a copy of the original data
    # this method should return either the copy itself or a new data set
    def process_data_copy(self, data_copy):
        raise NotImplementedError
    # subclasses can override this method to perform processing on the original data.
    # this method should always return a new copy of data
    def process_data_in_place(self, data):
        return self.process_data_copy(data.copy())
    def process_data(self, data):
        if self.enabled:
            data = self.process_data_in_place(data)
        return data
    # calibrations
    def get_processed_calibrations(self, data_shape, data_dtype, source_calibrations):
        return source_calibrations
    # subclasses that change the type or shape of the data must override
    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        return data_shape, data_dtype
    # default value handling.
    def update_data_shape_and_dtype(self, data_shape, data_dtype):
        pass
    # subclasses should override copy and copyFrom as necessary
    def copy(self):
        operation = self.__class__()
        operation.copyFrom(self)
        return operation
    def copyFrom(self, operation):
        values = copy.deepcopy(operation.values)
        # copy one by one to keep default values for missing keys
        for key in values.keys():
            self.values[key] = values[key]
        self.__enabled = operation.enabled
    def get_storage_property(self, key):
        if key == "enabled":
            return self.enabled
        if key in self.properties:
            return self.values[key]
        return Storage.StorageBase.get_storage_property(self, key)

class FFTOperation(Operation):
    def __init__(self):
        description = []
        super(FFTOperation, self).__init__(_("FFT"), description)
        self.storage_type = "fft-operation"

    def process_data_in_place(self, data):
        if Image.is_data_1d(data):
            return scipy.fftpack.fftshift(scipy.fftpack.fft(data))
        elif Image.is_data_2d(data):
            return scipy.fftpack.fftshift(scipy.fftpack.fft2(data))
        else:
            raise NotImplementedError()

    def get_processed_calibrations(self, data_shape, data_dtype, source_calibrations):
        assert len(source_calibrations) == 2
        return [DataItem.Calibration(0.0,
                                     1.0 / (source_calibrations[i].scale * data_shape[i]),
                                     "1/" + source_calibrations[i].units) for i in range(len(source_calibrations))]

class IFFTOperation(Operation):
    def __init__(self):
        description = []
        super(IFFTOperation, self).__init__(_("Inverse FFT"), description)
        self.storage_type = "inverse-fft-operation"

    def process_data_in_place(self, data):
        if Image.is_data_1d(data):
            return scipy.fftpack.fftshift(scipy.fftpack.ifft(data))
        elif Image.is_data_2d(data):
            return scipy.fftpack.ifft2(scipy.fftpack.ifftshift(data))
        else:
            raise NotImplementedError()

    def get_processed_calibrations(self, data_shape, data_dtype, source_calibrations):
        assert len(source_calibrations) == 2
        return [DataItem.Calibration(0.0,
                                     1.0 / (source_calibrations[i].scale * data_shape[i]),
                                     "1/" + source_calibrations[i].units) for i in range(len(source_calibrations))]


class InvertOperation(Operation):
    def __init__(self):
        description = []
        super(InvertOperation, self).__init__(_("Invert"), description)
        self.storage_type = "invert-operation"

    def process_data_in_place(self, data_copy):
        return 1.0 - data_copy[:]


class GaussianBlurOperation(Operation):
    def __init__(self):
        # Note: Do not initialize any properties in this class or else they will not work correctly.
        # __getattr__ only allows access to missing properties. Won't be missing if initialized.
        description = [
            {"name": _("Radius"), "property": "sigma", "type": "scalar", "default": 0.3}
        ]
        super(GaussianBlurOperation, self).__init__(_("Gaussian"), description)
        self.storage_type = "gaussian-blur-operation"

    def process_data_in_place(self, data_copy):
        return scipy.ndimage.gaussian_filter(data_copy, sigma=10*self.sigma)


class Crop2dOperation(Operation):
    def __init__(self, graphic=None):
        description = []
        super(Crop2dOperation, self).__init__(_("Crop"), description)
        self.__graphic = None
        self.storage_items += ["graphic"]
        self.storage_type = "crop-operation"
        if graphic:
            self.graphic = graphic

    def about_to_delete(self):
        self.graphic = None
        super(Crop2dOperation, self).about_to_delete()

    @classmethod
    def build(cls, storage_reader, item_node):
        crop_operation = super(Crop2dOperation, cls).build(storage_reader, item_node)
        graphic = storage_reader.get_item(item_node, "graphic")
        crop_operation.graphic = graphic
        return crop_operation

    def __get_graphic(self):
        return self.__graphic
    def __set_graphic(self, graphic):
        if self.__graphic:
            self.notify_clear_item("graphic")
            self.__graphic.remove_observer(self)
            self.__graphic.remove_ref()
        self.__graphic = graphic
        if graphic:
            assert isinstance(graphic, Graphics.RectangleGraphic)
        if self.__graphic:
            self.__graphic.add_observer(self)
            self.__graphic.add_ref()
            self.notify_set_item("graphic", graphic)
    graphic = property(__get_graphic, __set_graphic)

    def property_changed(self, graphic, key, value):
        if key == "bounds":
            self.notify_listeners("operation_changed", self)

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        graphic = self.graphic
        shape = data_shape
        bounds = graphic.bounds
        bounds_int = ((int(shape[0] * bounds[0][0]), int(shape[0] * bounds[0][1])), (int(shape[1] * bounds[1][0]), int(shape[1] * bounds[1][1])))
        return bounds_int[1], data_dtype

    def process_data_copy(self, data_copy):
        graphic = self.graphic
        assert isinstance(graphic, Graphics.RectangleGraphic)
        shape = data_copy.shape
        bounds = graphic.bounds
        bounds_int = ((int(shape[0] * bounds[0][0]), int(shape[0] * bounds[0][1])), (int(shape[1] * bounds[1][0]), int(shape[1] * bounds[1][1])))
        return data_copy[bounds_int[0][0]:bounds_int[0][0] + bounds_int[1][0], bounds_int[0][1]:bounds_int[0][1] + bounds_int[1][1]]


class Resample2dOperation(Operation):
    def __init__(self, width=None, height=None):
        description = [
            {"name": _("Width"), "property": "width", "type": "integer-field", "default": width},
            {"name": _("Height"), "property": "height", "type": "integer-field", "default": height},
        ]
        super(Resample2dOperation, self).__init__(_("Resample"), description)
        self.storage_type = "resample-operation"

    def process_data_copy(self, data_copy):
        height = self.height if self.height else data_copy.shape[0]
        width = self.width if self.width else data_copy.shape[1]
        if data_copy.shape[1] == width and data_copy.shape[0] == height:
            return data_copy
        return Image.scaled(data_copy, (height, width))

    def get_processed_calibrations(self, data_shape, data_dtype, source_calibrations):
        assert len(source_calibrations) == 2
        height = self.height if self.height else data_shape[0]
        width = self.width if self.width else data_shape[1]
        dimensions = (height, width)
        return [DataItem.Calibration(source_calibrations[i].origin,
                                     source_calibrations[i].scale * data_shape[i] / dimensions[i],
                                     source_calibrations[i].units) for i in range(len(source_calibrations))]

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        return (self.height, self.width), data_dtype

    def update_data_shape_and_dtype(self, data_shape, data_dtype):
        self.description[1]["default"] = data_shape[0]  # height = height
        self.description[0]["default"] = data_shape[1]  # width = width
        if "height" not in self.values or self.values["height"] is None:
            self.values["height"] = data_shape[0]
        if "width" not in self.values or self.values["width"] is None:
            self.values["width"] = data_shape[1]


class HistogramOperation(Operation):
    def __init__(self):
        description = []
        super(HistogramOperation, self).__init__(_("Histogram"), description)
        self.storage_type = "histogram-operation"

    @classmethod
    def build(cls, storage_reader, item_node):
        histogram_operation = super(HistogramOperation, cls).build(storage_reader, item_node)
        return histogram_operation

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        return (512, ), numpy.int

    def process_data_in_place(self, data):
        histogram_data = numpy.histogram(data, bins=512)
        return histogram_data[0].astype(numpy.int)


class LineProfileOperation(Operation):
    def __init__(self, graphic=None):
        description = []
        super(LineProfileOperation, self).__init__(_("Line Profile"), description)
        self.__graphic = None
        self.storage_items += ["graphic"]
        self.storage_type = "line-profile-operation"
        if graphic:
            self.graphic = graphic

    def about_to_delete(self):
        self.graphic = None
        super(LineProfileOperation, self).about_to_delete()

    @classmethod
    def build(cls, storage_reader, item_node):
        line_profile_operation = super(LineProfileOperation, cls).build(storage_reader, item_node)
        graphic = storage_reader.get_item(item_node, "graphic")
        line_profile_operation.graphic = graphic
        return line_profile_operation

    def __get_graphic(self):
        return self.__graphic
    def __set_graphic(self, graphic):
        if self.__graphic:
            self.notify_clear_item("graphic")
            self.__graphic.remove_observer(self)
            self.__graphic.remove_ref()
        self.__graphic = graphic
        if graphic:
            assert isinstance(graphic, Graphics.LineGraphic)
        if self.__graphic:
            self.__graphic.add_observer(self)
            self.__graphic.add_ref()
            self.notify_set_item("graphic", graphic)
    graphic = property(__get_graphic, __set_graphic)

    def property_changed(self, graphic, key, value):
        if key == "start" or key == "end":
            self.notify_listeners("operation_changed", self)

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        graphic = self.graphic
        start = graphic.start
        end = graphic.end
        shape = data_shape
        start_data = (int(shape[0]*start[0]), int(shape[1]*start[1]))
        end_data = (int(shape[0]*end[0]), int(shape[1]*end[1]))
        length = int(math.sqrt((end_data[1] - start_data[1])**2 + (end_data[0] - start_data[0])**2))
        if data_shape[-1] == 3:
            return (length, 3), numpy.uint8
        else:
            return (length, ), numpy.double

    def process_data_in_place(self, data):
        graphic = self.graphic
        assert isinstance(graphic, Graphics.LineGraphic)
        start = graphic.start
        end = graphic.end
        shape = data.shape
        start_data = (int(shape[0]*start[0]), int(shape[1]*start[1]))
        end_data = (int(shape[0]*end[0]), int(shape[1]*end[1]))
        length = int(math.sqrt((end_data[1] - start_data[1])**2 + (end_data[0] - start_data[0])**2))
        if length > 0:
            c0 = numpy.linspace(start_data[0], end_data[0]-1, length)
            c1 = numpy.linspace(start_data[1], end_data[1]-1, length)
            return data[c0.astype(numpy.int), c1.astype(numpy.int)]
        return numpy.zeros((1))
