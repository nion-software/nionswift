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
from nion.swift import Decorators
from nion.swift.Decorators import timeit
from nion.swift import Image
from nion.swift import DataItem
from nion.swift import Graphics
from nion.swift import Storage
from nion.ui import UserInterfaceUtility

_ = gettext.gettext


class Operation(Storage.StorageBase):
    """
        Operation represents an operation on numpy data array.
        Pass in a description during construction. The description
        should describe what parameters are editable and how they
        are connected to the operation.
    """
    def __init__(self, operation_id):
        Storage.StorageBase.__init__(self)

        self.storage_type = "operation"

        # an operation gets one chance to find its behavior. if the behavior doesn't exist
        # then it will simply provide null data according to the saved parameters. if there
        # are no saved parameters, defaults are used.
        self.operation_behavior = OperationManager().build_operation_behavior(operation_id)
        if self.operation_behavior:
            self.operation_behavior.operation = self

        self.name = self.operation_behavior.name if self.operation_behavior else _("Unavailable Operation")
        self.__enabled = True

        # operation_id is immutable
        self.operation_id = operation_id

        # manage properties
        self.description = self.operation_behavior.description if self.operation_behavior else []
        self.properties = [description_entry["property"] for description_entry in self.description]
        self.values = {}

        # manage graphics
        self.graphic = None

        self.storage_properties += ["operation_id", "enabled", "values"]  # "dtype", "shape"
        self.storage_items += ["graphic"]

    # called when remove_ref causes ref_count to go to 0
    def about_to_delete(self):
        self.set_graphic("graphic", None)
        super(Operation, self).about_to_delete()

    @classmethod
    def build(cls, datastore, item_node, uuid_):
        operation_id = datastore.get_property(item_node, "operation_id")
        operation = cls(operation_id)
        operation.enabled = datastore.get_property(item_node, "enabled", True)
        operation.values = datastore.get_property(item_node, "values", dict())
        graphic = datastore.get_item(item_node, "graphic")
        operation.set_graphic("graphic", graphic)
        return operation

    def create_editor(self, ui):
        return None

    # enabled property
    def __get_enabled(self):
        return self.__enabled
    def __set_enabled(self, enabled):
        self.__enabled = enabled
        self.notify_set_property("enabled", enabled)
    enabled = property(__get_enabled, __set_enabled)

    # get a property.
    def get_property(self, property_id, default_value=None):
        if property_id in self.values:
            return self.values[property_id]
        if default_value is not None:
            return default_value
        for description_entry in self.description:
            if description_entry["property"] == property_id:
                return description_entry.get("default")
        return None

    # set a property.
    def set_property(self, property_id, value):
        self.values[property_id] = value
        self.notify_set_property("values", self.values)

    # update the default value for this operation.
    def __set_property_default(self, property_id, default_value):
        for description_entry in self.description:
            if description_entry["property"] == property_id:
                description_entry["default"] = default_value
                if property_id not in self.values or self.values[property_id] is None:
                    self.values[property_id] = default_value

    # clients call this to perform processing
    def process_data(self, data):
        if self.operation_behavior:
            return self.operation_behavior.process_data_in_place(data)
        else:
            return data.copy()

    # calibrations

    def get_processed_calibrations(self, data_shape, data_dtype, source_calibrations):
        if self.operation_behavior:
            return self.operation_behavior.get_processed_calibrations(data_shape, data_dtype, source_calibrations)
        else:
            return source_calibrations

    def get_processed_intensity_calibration(self, data_shape, data_dtype, intensity_calibration):
        if self.operation_behavior:
            return self.operation_behavior.get_processed_intensity_calibration(data_shape, data_dtype, intensity_calibration)
        else:
            return source_calibrations

    # data shape and type
    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        if self.operation_behavior:
            return self.operation_behavior.get_processed_data_shape_and_dtype(data_shape, data_dtype)
        return data_shape, data_dtype

    # default value handling.
    def update_data_shape_and_dtype(self, data_shape, data_dtype):
        if self.operation_behavior:
            default_values = self.operation_behavior.property_defaults_for_data_shape_and_dtype(data_shape, data_dtype)
            for property, default_value in default_values.iteritems():
                self.__set_property_default(property, default_value)

    # subclasses should override __deepcopy__ and deepcopy_from as necessary
    def __deepcopy__(self, memo):
        operation = self.__class__(self.operation_id)
        operation.deepcopy_from(self, memo)
        memo[id(self)] = operation
        return operation

    def deepcopy_from(self, operation, memo):
        values = copy.deepcopy(operation.values)
        # copy one by one to keep default values for missing keys
        for key in values.keys():
            self.values[key] = values[key]
        # TODO: Check use of memo here.
        if operation.graphic:
            self.set_graphic("graphic", operation.graphic)
        else:
            self.set_graphic("graphic", None)
        self.__enabled = operation.enabled

    def notify_set_property(self, key, value):
        super(Operation, self).notify_set_property(key, value)
        self.notify_listeners("operation_changed", self)

    def get_storage_item(self, key):
        if key == "graphic":
            return self.graphic
        return super(Operation, self).get_storage_item(key)

    def get_graphic(self, key):
        return self.get_storage_item(key)

    def set_graphic(self, key, graphic):
        if key == "graphic":
            if self.graphic:
                self.notify_clear_item("graphic")
                self.graphic.remove_observer(self)
                self.graphic.remove_ref()
                self.graphic = None
            if graphic:
                self.graphic = graphic
                graphic.add_observer(self)
                graphic.add_ref()
                self.notify_set_item("graphic", graphic)

    def property_changed(self, object, key, value):
        if object is not None and object == self.graphic:
            # TODO: check for specific key, such as 'bounds' for rectangle?
            self.notify_listeners("operation_changed", self)


class OperationBehavior(object):

    def __init__(self, name, operation_id, description=None):
        self.__weak_operation = None
        self.name = name
        self.operation_id = operation_id
        self.description = description if description else []

    # this needs to be set externally
    def __get_operation(self):
        return self.__weak_operation()
    def __set_operation(self, operation):
        self.__weak_operation = weakref.ref(operation)
    operation = property(__get_operation, __set_operation)

    # handle properties from the description of the operation.
    def get_property(self, property_id, default_value=None):
        return self.operation.get_property(property_id, default_value)

    # handle graphic
    def get_graphic(self, graphic_id):
        return self.operation.get_graphic(graphic_id)

    # subclasses can override this method to perform processing on a copy of the original data
    # this method should return either the copy itself or a new data set
    def process_data_copy(self, data_copy):
        raise NotImplementedError

    # subclasses can override this method to perform processing on the original data.
    # this method should always return a new copy of data
    def process_data_in_place(self, data):
        return self.process_data_copy(data.copy())

    # calibrations
    def get_processed_calibrations(self, data_shape, data_dtype, source_calibrations):
        return source_calibrations
    def get_processed_intensity_calibration(self, data_shape, data_dtype, intensity_calibration):
        return intensity_calibration

    # subclasses that change the type or shape of the data must override
    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        return data_shape, data_dtype

    # default value handling. this gives the operation a chance to update default
    # values when the data shape or dtype changes.
    def property_defaults_for_data_shape_and_dtype(self, data_shape, data_dtype):
        return dict()


class FFTOperationBehavior(OperationBehavior):

    def __init__(self):
        super(FFTOperationBehavior, self).__init__(_("FFT"), "fft-operation")

    def process_data_in_place(self, data):
        if Image.is_data_1d(data):
            return scipy.fftpack.fftshift(scipy.fftpack.fft(data))
        elif Image.is_data_2d(data):
            data_copy = data.copy()  # let other threads use data while we're processing
            return scipy.fftpack.fftshift(scipy.fftpack.fft2(data_copy))
        else:
            raise NotImplementedError()

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        return data_shape, numpy.dtype(numpy.complex128)

    def get_processed_calibrations(self, data_shape, data_dtype, source_calibrations):
        assert len(source_calibrations) == len(Image.spatial_shape_from_shape_and_dtype(data_shape, data_dtype))
        return [DataItem.Calibration(0.0,
                                     1.0 / (source_calibrations[i].scale * data_shape[i]),
                                     "1/" + source_calibrations[i].units) for i in range(len(source_calibrations))]


class IFFTOperationBehavior(OperationBehavior):

    def __init__(self):
        super(IFFTOperationBehavior, self).__init__(_("Inverse FFT"), "inverse-fft-operation")

    def process_data_in_place(self, data):
        if Image.is_data_1d(data):
            return scipy.fftpack.fftshift(scipy.fftpack.ifft(data))
        elif Image.is_data_2d(data):
            return scipy.fftpack.ifft2(scipy.fftpack.ifftshift(data))
        else:
            raise NotImplementedError()

    def get_processed_calibrations(self, data_shape, data_dtype, source_calibrations):
        assert len(source_calibrations) == len(Image.spatial_shape_from_shape_and_dtype(data_shape, data_dtype))
        return [DataItem.Calibration(0.0,
                                     1.0 / (source_calibrations[i].scale * data_shape[i]),
                                     "1/" + source_calibrations[i].units) for i in range(len(source_calibrations))]


class InvertOperationBehavior(OperationBehavior):

    def __init__(self):
        super(InvertOperationBehavior, self).__init__(_("Invert"), "invert-operation")

    def process_data_in_place(self, data_copy):
        if Image.is_data_rgba(data_copy) or Image.is_data_rgb(data_copy):
            if Image.is_data_rgba(data_copy):
                inverted = 255 - data_copy[:]
                inverted[...,3] = data_copy[...,3]
                return inverted
            else:
                return 255 - data_copy[:]
        else:
            return 1.0 - data_copy[:]


class GaussianBlurOperationBehavior(OperationBehavior):

    def __init__(self):
        description = [
            { "name": _("Radius"), "property": "sigma", "type": "scalar", "default": 0.3 }
        ]
        super(GaussianBlurOperationBehavior, self).__init__(_("Gaussian Blur"), "gaussian-blur-operation", description)

    def process_data_in_place(self, data_copy):
        return scipy.ndimage.gaussian_filter(data_copy, sigma=10*self.get_property("sigma"))


class Crop2dOperationBehavior(OperationBehavior):

    def __init__(self):
        super(Crop2dOperationBehavior, self).__init__(_("Crop"), "crop-operation", None)

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        shape = data_shape
        graphic = self.get_graphic("graphic")
        bounds = graphic.bounds if graphic else ((0, 0), (1, 1))
        bounds_int = ((int(shape[0] * bounds[0][0]), int(shape[1] * bounds[0][1])), (int(shape[0] * bounds[1][0]), int(shape[1] * bounds[1][1])))
        if Image.is_shape_and_dtype_rgba(data_shape, data_dtype) or Image.is_shape_and_dtype_rgb(data_shape, data_dtype):
            return bounds_int[1] + (data_shape[-1], ), data_dtype
        else:
            return bounds_int[1], data_dtype

    def process_data_in_place(self, data):
        graphic = self.get_graphic("graphic")
        if graphic:
            assert isinstance(graphic, Graphics.RectangleGraphic)
        shape = data.shape
        bounds = graphic.bounds if graphic else ((0, 0), (1, 1))
        bounds_int = ((int(shape[0] * bounds[0][0]), int(shape[1] * bounds[0][1])), (int(shape[0] * bounds[1][0]), int(shape[1] * bounds[1][1])))
        return data[bounds_int[0][0]:bounds_int[0][0] + bounds_int[1][0], bounds_int[0][1]:bounds_int[0][1] + bounds_int[1][1]].copy()


class Resample2dOperationBehavior(OperationBehavior):

    def __init__(self):
        description = [
            {"name": _("Width"), "property": "width", "type": "integer-field", "default": None},
            {"name": _("Height"), "property": "height", "type": "integer-field", "default": None},
        ]
        super(Resample2dOperationBehavior, self).__init__(_("Resample"), "resample-operation", description)

    def process_data_copy(self, data_copy):
        height = self.get_property("height", data_copy.shape[0])
        width = self.get_property("width", data_copy.shape[1])
        if data_copy.shape[1] == width and data_copy.shape[0] == height:
            return data_copy
        return Image.scaled(data_copy, (height, width))

    def get_processed_calibrations(self, data_shape, data_dtype, source_calibrations):
        assert len(source_calibrations) == 2
        height = self.get_property("height", data_shape[0])
        width = self.get_property("width", data_shape[1])
        dimensions = (height, width)
        return [DataItem.Calibration(source_calibrations[i].origin,
                                     source_calibrations[i].scale * data_shape[i] / dimensions[i],
                                     source_calibrations[i].units) for i in range(len(source_calibrations))]

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        height = self.get_property("height", data_shape[0])
        width = self.get_property("width", data_shape[1])
        if Image.is_shape_and_dtype_rgba(data_shape, data_dtype) or Image.is_shape_and_dtype_rgb(data_shape, data_dtype):
            return (height, width, data_shape[-1]), data_dtype
        else:
            return (height, width), data_dtype

    def property_defaults_for_data_shape_and_dtype(self, data_shape, data_dtype):
        property_defaults = {
            "height": data_shape[0],
            "width": data_shape[1],
        }
        return property_defaults


class HistogramOperationBehavior(OperationBehavior):

    def __init__(self):
        super(HistogramOperationBehavior, self).__init__(_("Histogram"), "histogram-operation")
        self.bins = 256

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        return (self.bins, ), numpy.dtype(numpy.int)

    def process_data_in_place(self, data):
        histogram_data = numpy.histogram(data, bins=self.bins)
        return histogram_data[0].astype(numpy.int)


class LineProfileOperationBehavior(OperationBehavior):

    def __init__(self):
        super(LineProfileOperationBehavior, self).__init__(_("Line Profile"), "line-profile-operation", None)

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        graphic = self.get_graphic("graphic")
        start = graphic.start if graphic else (0.25, 0.25)
        end = graphic.end if graphic else (0.75, 0.75)
        shape = data_shape
        start_data = (int(shape[0]*start[0]), int(shape[1]*start[1]))
        end_data = (int(shape[0]*end[0]), int(shape[1]*end[1]))
        length = int(math.sqrt((end_data[1] - start_data[1])**2 + (end_data[0] - start_data[0])**2))
        if Image.is_shape_and_dtype_rgba(data_shape, data_dtype) or Image.is_shape_and_dtype_rgb(data_shape, data_dtype):
            return (length, data_shape[-1]), data_dtype
        else:
            return (length, ), numpy.dtype(numpy.double)

    def get_processed_calibrations(self, data_shape, data_dtype, source_calibrations):
        return [DataItem.Calibration(0.0, source_calibrations[0].scale, source_calibrations[0].units)]

    def process_data_in_place(self, data):
        graphic = self.get_graphic("graphic")
        if graphic:
            assert isinstance(graphic, Graphics.LineGraphic)
        start = graphic.start if graphic else (0.25, 0.25)
        end = graphic.end if graphic else (0.75, 0.75)
        shape = data.shape
        start_data = (int(shape[0]*start[0]), int(shape[1]*start[1]))
        end_data = (int(shape[0]*end[0]), int(shape[1]*end[1]))
        length = int(math.sqrt((end_data[1] - start_data[1])**2 + (end_data[0] - start_data[0])**2))
        if length > 0:
            c0 = numpy.linspace(start_data[0], end_data[0]-1, length)
            c1 = numpy.linspace(start_data[1], end_data[1]-1, length)
            return data[c0.astype(numpy.int), c1.astype(numpy.int)]
        return numpy.zeros((1))


class ConvertToScalarOperationBehavior(OperationBehavior):

    def __init__(self):
        super(ConvertToScalarOperationBehavior, self).__init__(_("Convert to Scalar"), "convert-to-scalar-operation")

    def process_data_in_place(self, data):
        if Image.is_data_rgba(data) or Image.is_data_rgb(data):
            return Image.convert_to_grayscale(data, numpy.double)
        else:
            return data.copy()

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        if Image.is_shape_and_dtype_rgba(data_shape, data_dtype) or Image.is_shape_and_dtype_rgb(data_shape, data_dtype):
            return data_shape[:-1], numpy.dtype(numpy.double)
        return data_shape, data_dtype


class OperationPropertyBinding(UserInterfaceUtility.Binding):

    """
        Binds to a property of an operation object.

        This object records the 'values' property of the operation. Then it
        watches for changes to 'values' which match the watched property.
    """

    def __init__(self, source, property_name, converter=None):
        super(OperationPropertyBinding, self).__init__(source,  converter)
        self.__property_name = property_name
        self.source_setter = lambda value: self.source.set_property(self.__property_name, value)
        self.source_getter = lambda: self.source.get_property(self.__property_name)
        # use this to know when a specific property changes
        self.__values = copy.copy(source.values)

    # thread safe
    def property_changed(self, sender, property, property_value):
        if sender == self.source and property == "values":
            values = property_value
            new_value = values.get(self.__property_name)
            old_value = self.__values.get(self.__property_name)
            if new_value != old_value:
                # perform on the main thread
                self.add_task("update_target", lambda: self.update_target(new_value))
                self.__values = copy.copy(self.source.values)


class OperationManager(object):
    __metaclass__ = Decorators.Singleton

    def __init__(self):
        self.__operation_behaviors = dict()

    def register_operation_behavior(self, operation_id, create_operation_fn):
        self.__operation_behaviors[operation_id] = create_operation_fn

    def unregister_operation_behavior(self, operation_id):
        del self.__operation_behaviors[operation_id]

    def build_operation_behavior(self, operation_id):
        if operation_id in self.__operation_behaviors:
            return self.__operation_behaviors[operation_id]()
        return None


OperationManager().register_operation_behavior("fft-operation", lambda: FFTOperationBehavior())
OperationManager().register_operation_behavior("inverse-fft-operation", lambda: IFFTOperationBehavior())
OperationManager().register_operation_behavior("invert-operation", lambda: InvertOperationBehavior())
OperationManager().register_operation_behavior("gaussian-blur-operation", lambda: GaussianBlurOperationBehavior())
OperationManager().register_operation_behavior("crop-operation", lambda: Crop2dOperationBehavior())
OperationManager().register_operation_behavior("resample-operation", lambda: Resample2dOperationBehavior())
OperationManager().register_operation_behavior("histogram-operation", lambda: HistogramOperationBehavior())
OperationManager().register_operation_behavior("line-profile-operation", lambda: LineProfileOperationBehavior())
OperationManager().register_operation_behavior("convert-to-scalar-operation", lambda: ConvertToScalarOperationBehavior())
