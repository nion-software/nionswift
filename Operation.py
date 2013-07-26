# standard libraries
import copy
import gettext
#import inspect
import logging
import sys
import threading
import uuid
import weakref

# third party libraries
import numpy
from scipy import fftpack
from scipy import ndimage

# local libraries
import Image
import DataItem
import Graphics
import Storage

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
    def process_data_copy(self, data_array_copy):
        raise NotImplementedError
    # subclasses can override this method to perform processing on the original data.
    # this method should always return a new copy of data
    def process_data_in_place(self, data_array):
        return self.process_data_copy(data_array.copy())
    def process_data(self, data_array):
        if self.enabled:
            data_array = self.process_data_in_place(data_array)
        return data_array
    # calibrations
    def get_processed_calibrations(self, data_shape, data_type, source_calibrations):
        return source_calibrations
    def get_processed_data_shape_and_type(self, data_shape, data_type):
        return data_shape, data_type
    # default value handling
    def update_data_shape_and_type(self, data_shape, data_type):
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

    def process_data_in_place(self, data_array):
        return fftpack.fftshift(fftpack.fft2(data_array))

    def get_processed_calibrations(self, data_shape, data_type, source_calibrations):
        assert len(source_calibrations) == 2
        return [DataItem.Calibration(0.0,
                                     1.0 / (source_calibrations[i].scale * data_shape[i]),
                                     "1/" + source_calibrations[i].units) for i in range(len(source_calibrations))]

class IFFTOperation(Operation):
    def __init__(self):
        description = []
        super(IFFTOperation, self).__init__(_("Inverse FFT"), description)
        self.storage_type = "inverse-fft-operation"

    def process_data_in_place(self, data_array):
        return fftpack.ifft2(fftpack.ifftshift(data_array))

    def get_processed_calibrations(self, data_shape, data_type, source_calibrations):
        assert len(source_calibrations) == 2
        return [DataItem.Calibration(0.0,
                                     1.0 / (source_calibrations[i].scale * data_shape[i]),
                                     "1/" + source_calibrations[i].units) for i in range(len(source_calibrations))]


class InvertOperation(Operation):
    def __init__(self):
        description = []
        super(InvertOperation, self).__init__(_("Invert"), description)
        self.storage_type = "invert-operation"

    def process_data_in_place(self, data_array_copy):
        return 1.0 - data_array_copy[:, :]


class GaussianBlurOperation(Operation):
    def __init__(self):
        # Note: Do not initialize any properties in this class or else they will not work correctly.
        # __getattr__ only allows access to missing properties. Won't be missing if initialized.
        description = [
            {"name": _("Radius"), "property": "sigma", "type": "scalar", "default": 0.3}
        ]
        super(GaussianBlurOperation, self).__init__(_("Gaussian"), description)
        self.storage_type = "gaussian-blur-operation"

    def process_data_in_place(self, data_array_copy):
        return ndimage.gaussian_filter(data_array_copy, sigma=10*self.sigma)


class CropOperation(Operation):
    def __init__(self):
        description = []
        super(CropOperation, self).__init__(_("Crop"), description)
        self.__graphic = None
        self.storage_items += ["graphic"]
        self.storage_type = "crop-operation"

    @classmethod
    def build(cls, storage_reader, item_node):
        crop_operation = super(CropOperation, cls).build(storage_reader, item_node)
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

    def process_data_copy(self, data_array_copy):
        graphic = self.graphic
        shape = data_array_copy.shape
        assert isinstance(graphic, Graphics.RectangleGraphic)
        bounds = graphic.bounds
        bounds_int = ((int(shape[0] * bounds[0][0]), int(shape[0] * bounds[0][1])), (int(shape[1] * bounds[1][0]), int(shape[1] * bounds[1][1])))
        return data_array_copy[bounds_int[0][0]:bounds_int[0][0] + bounds_int[1][0], bounds_int[0][1]:bounds_int[0][1] + bounds_int[1][1]]


class ResampleOperation(Operation):
    def __init__(self):
        description = [
            {"name": _("Width"), "property": "width", "type": "integer-field", "default": None},
            {"name": _("Height"), "property": "height", "type": "integer-field", "default": None}
        ]
        super(ResampleOperation, self).__init__(_("Resample"), description)
        self.storage_type = "resample-operation"

    def process_data_copy(self, data_array_copy):
        height = self.height if self.height else data_array_copy.shape[0]
        width = self.width if self.width else data_array_copy.shape[1]
        if data_array_copy.shape[1] == width and data_array_copy.shape[0] == height:
            return data_array_copy
        return Image.scaled(data_array_copy, (height, width))

    def get_processed_calibrations(self, data_shape, data_type, source_calibrations):
        assert len(source_calibrations) == 2
        height = self.height if self.height else data_shape[0]
        width = self.width if self.width else data_shape[1]
        dimensions = (height, width)
        return [DataItem.Calibration(source_calibrations[i].origin,
                                     source_calibrations[i].scale * data_shape[i] / dimensions[i],
                                     source_calibrations[i].units) for i in range(len(source_calibrations))]

    def get_processed_data_shape_and_type(self, data_shape, data_type):
        return (self.height, self.width), data_type

    def update_data_shape_and_type(self, data_shape, data_type):
        self.description[1]["default"] = data_shape[0]  # height = height
        self.description[0]["default"] = data_shape[1]  # width = width
        if "height" not in self.values or self.values["height"] is None:
            self.values["height"] = data_shape[0]
        if "width" not in self.values or self.values["width"] is None:
            self.values["width"] = data_shape[1]
