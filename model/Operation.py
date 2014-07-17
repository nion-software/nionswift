# standard libraries
import copy
import gettext
import logging
import math
import uuid
import weakref

# third party libraries
import numpy
import scipy
import scipy.fftpack
import scipy.ndimage
import scipy.ndimage.filters
import scipy.ndimage.fourier

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import Graphics
from nion.swift.model import Image
from nion.ui import Binding
from nion.ui import Observable

_ = gettext.gettext


class LineProfileGraphic(Graphics.LineTypeGraphic):
    def __init__(self):
        super(LineProfileGraphic, self).__init__("line-profile-graphic", _("Line Profile"))
        self.define_property("width", 1.0, changed=self._property_changed)
    # accessors
    def draw(self, ctx, mapping, is_selected=False):
        p1 = mapping.map_point_image_norm_to_widget(self.start)
        p2 = mapping.map_point_image_norm_to_widget(self.end)
        ctx.save()
        ctx.begin_path()
        ctx.move_to(p1[1], p1[0])
        ctx.line_to(p2[1], p2[0])
        if self.start_arrow_enabled:
            self.draw_arrow(ctx, p2, p1)
        if self.end_arrow_enabled:
            self.draw_arrow(ctx, p1, p2)
        ctx.line_width = 1
        ctx.stroke_style = self.color
        ctx.stroke()
        if self.width > 1.0:
            half_width = self.width * 0.5
            length = math.sqrt(math.pow(p2[0] - p1[0],2) + math.pow(p2[1] - p1[1], 2))
            dy = (p2[0] - p1[0]) / length
            dx = (p2[1] - p1[1]) / length
            ctx.save()
            ctx.begin_path()
            ctx.move_to(p1[1] + dy * half_width, p1[0] - dx * half_width)
            ctx.line_to(p2[1] + dy * half_width, p2[0] - dx * half_width)
            ctx.line_to(p2[1] - dy * half_width, p2[0] + dx * half_width)
            ctx.line_to(p1[1] - dy * half_width, p1[0] + dx * half_width)
            ctx.close_path()
            ctx.line_width = 1
            ctx.line_dash = 2
            ctx.stroke_style = self.color
            ctx.stroke()
            ctx.restore()
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, p1)
            self.draw_marker(ctx, p2)


class OperationItem(Observable.Observable, Observable.Broadcaster, Observable.ManagedObject):
    """
        OperationItem represents an operation on numpy data array.
        Pass in a description during construction. The description
        should describe what parameters are editable and how they
        are connected to the operation.
        """
    def __init__(self, operation_id):
        super(OperationItem, self).__init__()

        self.__weak_data_item = None

        self.__weak_region = None

        class UuidToStringConverter(object):
            def convert(self, value):
                return str(value) if value is not None else None
            def convert_back(self, value):
                return uuid.UUID(value) if value is not None else None

        self.define_property("operation_id", operation_id, read_only=True)
        self.define_property("enabled", True, changed=self.__property_changed)
        self.define_property("values", dict(), changed=self.__property_changed)
        self.define_property("region_uuid", None, converter=UuidToStringConverter())

        # an operation gets one chance to find its behavior. if the behavior doesn't exist
        # then it will simply provide null data according to the saved parameters. if there
        # are no saved parameters, defaults are used.
        self.operation = OperationManager().build_operation(operation_id)

        self.__bindings = list()

        self.name = self.operation.name if self.operation else _("Unavailable Operation")

        # manage properties
        self.description = self.operation.description if self.operation else []
        self.properties = [description_entry["property"] for description_entry in self.description]

    def __deepcopy__(self, memo):
        deepcopy = self.__class__(self.operation_id)
        deepcopy.deepcopy_from(self, memo)
        memo[id(self)] = deepcopy
        return deepcopy

    def about_to_be_removed(self):
        """ When the operation is about to be removed, remove the region on data source, if any. """
        region = self.__weak_region and self.__weak_region()
        data_item = self.data_item
        data_source = data_item and data_item.data_source
        if region and data_source:
            # this is a hack because graphics can cause operations to be
            # deleted in multiple ways. there are tests to account for the
            # various ways, but there is probably a better way to handle this
            # in the long run.
            if region in data_source.regions:
                data_source.remove_region(region)

    def managed_object_context_changed(self):
        """ Override from ManagedObject. """
        region_uuid = self.region_uuid
        if region_uuid is not None:
            def registered(region):
                self.__set_region(region)
            def unregistered(region=None):
                for binding in self.__bindings:
                    binding.close()
                self.__bindings = list()
            if self.managed_object_context:
                self.managed_object_context.subscribe(region_uuid, registered, unregistered)
            else:
                unregistered()

    def read_from_dict(self, properties):
        super(OperationItem, self).read_from_dict(properties)
        # update items one by one to update operation
        for key in self.values.keys():
            if self.operation:
                setattr(self.operation, key, self.values[key])
        self.managed_object_context_changed()

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    data_item = property(__get_data_item)

    # called from data item when added/removed.
    def _set_data_item(self, data_item):
        self.__weak_data_item = weakref.ref(data_item) if data_item else None

    def __property_changed(self, name, value):
        self.notify_set_property(name, value)
        self.notify_listeners("operation_changed", self)

    def __set_region(self, region):
        # TODO: operation item should not have to know about specific operations (for regions)
        if self.operation_id == "line-profile-operation":
            assert region.type == "line-region"
            self.__bindings.append(OperationPropertyToRegionBinding(self, "start", region, "start"))
            self.__bindings.append(OperationPropertyToRegionBinding(self, "end", region, "end"))
            self.__bindings.append(OperationPropertyToRegionBinding(self, "integration_width", region, "width"))
            self.set_property("start", region.start)
            self.set_property("end", region.end)
            self.set_property("width", region.width)
            region.add_listener(self)
            self.__weak_region = weakref.ref(region)
        elif self.operation_id == "crop-operation":
            assert region.type == "rectangle-region"
            self.__bindings.append(OperationPropertyToRegionBinding(self, "bounds", region, "bounds"))
            self.set_property("bounds", region.bounds)
            region.add_listener(self)
            self.__weak_region = weakref.ref(region)

    # this message comes from the region.
    # it is generated when the user deletes a region graphic
    # that informs the display which notifies the graphic which
    # notifies the operation which notifies this data item. ugh.
    def remove_region_because_graphic_removed(self, region):
        self.notify_listeners("request_remove_data_item_because_operation_removed", self)

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
        values = self.values
        values[property_id] = value
        self.values = values
        if self.operation:
            setattr(self.operation, property_id, value)

    # update the default value for this operation.
    def __set_property_default(self, property_id, default_value):
        for description_entry in self.description:
            if description_entry["property"] == property_id:
                description_entry["default"] = default_value
                if property_id not in self.values or self.values[property_id] is None:
                    self.set_property(property_id, default_value)

    # clients call this to perform processing
    def process_data_list(self, data_list):
        if len(data_list) == 1:
            data = data_list[0]
            if self.operation:
                return [self.operation.get_processed_data(data)]
            else:
                return [data.copy()]
        return []

    # calibrations

    def get_processed_intermediate_data_items(self, data_inputs):
        if self.operation:
            return self.operation.get_processed_intermediate_data_items(data_inputs)
        else:
            class CopyOperation(Operation):
                def __init__(self):
                    super(CopyOperation, self).__init__("Intermediate Copy", "intermediate-copy")
                def process(self, data):
                    return data.copy()
            return CopyOperation().get_processed_intermediate_data_items(data_inputs)

    # default value handling.
    def update_data_shapes_and_dtypes(self, data_shapes_and_dtypes):
        if len(data_shapes_and_dtypes) == 1:
            data_shape, data_dtype = data_shapes_and_dtypes[0][0], data_shapes_and_dtypes[0][1]
            if self.operation:
                default_values = self.operation.property_defaults_for_data_shape_and_dtype(data_shape, data_dtype)
                for property, default_value in default_values.iteritems():
                    self.__set_property_default(property, default_value)

    def deepcopy_from(self, operation_item, memo):
        super(OperationItem, self).deepcopy_from(operation_item, memo)
        values = self.values
        # copy one by one to keep default values for missing keys
        for key in values.keys():
            self.set_property(key, values[key])


class Singleton(type):
    def __init__(cls, name, bases, dict):
        super(Singleton, cls).__init__(name, bases, dict)
        cls.instance = None

    def __call__(cls,*args,**kw):
        if cls.instance is None:
            cls.instance = super(Singleton, cls).__call__(*args, **kw)
        return cls.instance


class Operation(object):

    def __init__(self, name, operation_id, description=None):
        self.name = name
        self.operation_id = operation_id
        self.description = description if description else []

    # handle properties from the description of the operation.
    def get_property(self, property_id, default_value=None):
        return getattr(self, property_id) if hasattr(self, property_id) else default_value

    # subclasses must override this method to perform processing on the original data.
    # this method should always return a new copy of data
    def process(self, data):
        raise NotImplementedError()

    # return the processed data inputs
    def get_processed_intermediate_data_items(self, data_inputs):

        class ProcessedDataItem(object):

            """
                Constructs an object that is able to perform operation and return results.

                Delays the calculation until it is requested using closures.
            """

            def __init__(self, operation, data_inputs):
                super(ProcessedDataItem, self).__init__()
                self.__operation = operation
                self.__data_inputs = data_inputs

            def __get_data_shape_and_dtype(self):
                assert len(self.__data_inputs) == 1
                input_data_shape_and_dtype = self.__data_inputs[0].data_shape_and_dtype
                input_data_shape = input_data_shape_and_dtype[0]
                input_data_dtype = input_data_shape_and_dtype[1]
                if input_data_shape is not None and input_data_dtype is not None:
                    return self.__operation.get_processed_data_shape_and_dtype(input_data_shape, input_data_dtype)
                return None, None
            data_shape_and_dtype = property(__get_data_shape_and_dtype)

            def __get_calculated_intensity_calibration(self):
                assert len(self.__data_inputs) == 1
                input_data_shape_and_dtype = self.__data_inputs[0].data_shape_and_dtype
                input_data_shape = input_data_shape_and_dtype[0]
                input_data_dtype = input_data_shape_and_dtype[1]
                input_intensity_calibration = self.__data_inputs[0].calculated_intensity_calibration
                return self.__operation.get_processed_intensity_calibration(input_data_shape, input_data_dtype, input_intensity_calibration)
            calculated_intensity_calibration = property(__get_calculated_intensity_calibration)

            def __get_calculated_calibrations(self):
                assert len(self.__data_inputs) == 1
                input_data_shape_and_dtype = self.__data_inputs[0].data_shape_and_dtype
                input_data_shape = input_data_shape_and_dtype[0]
                input_data_dtype = input_data_shape_and_dtype[1]
                input_spatial_calibrations = self.__data_inputs[0].calculated_calibrations
                return self.__operation.get_processed_spatial_calibrations(input_data_shape, input_data_dtype, input_spatial_calibrations)
            calculated_calibrations = property(__get_calculated_calibrations)

            def __get_data(self):
                assert len(self.__data_inputs) == 1
                return self.__operation.get_processed_data(self.__data_inputs[0].data)
            data = property(__get_data)

        if len(data_inputs) == 1:
            return [ProcessedDataItem(self, data_inputs)]

        return []

    # public method to do processing. double check that data is a copy and not the original.
    def get_processed_data(self, data):
        new_data = self.process(data) if data is not None else None
        if data is not None:
            assert(id(new_data) != id(data))
        if new_data is not None and new_data.base is not None:
            assert(id(new_data.base) != id(data))
        return new_data

    # spatial calibrations
    def get_processed_spatial_calibrations(self, data_shape, data_dtype, spatial_calibrations):
        return spatial_calibrations

    # intensity calibration
    def get_processed_intensity_calibration(self, data_shape, data_dtype, intensity_calibration):
        return intensity_calibration

    # subclasses that change the type or shape of the data must override
    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        return data_shape, data_dtype

    # default value handling. this gives the operation a chance to update default
    # values when the data shape or dtype changes.
    def property_defaults_for_data_shape_and_dtype(self, data_shape, data_dtype):
        return dict()


class SelectorOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Index"), "property": "index", "type": "integer-field", "default": 0 }
        ]
        super(SelectorOperation, self).__init__(_("Selector"), "selector-operation", description)
        self.index = 0

    # return the processed data inputs
    def get_processed_intermediate_data_items(self, data_inputs):
        index = self.get_property("index")
        if len(data_inputs) > index:
            return [data_inputs[index]]
        return []


class FFTOperation(Operation):

    def __init__(self):
        super(FFTOperation, self).__init__(_("FFT"), "fft-operation")

    def process(self, data):
        if Image.is_data_1d(data):
            return scipy.fftpack.fftshift(scipy.fftpack.fft(data))
        elif Image.is_data_2d(data):
            data_copy = data.copy()  # let other threads use data while we're processing
            return scipy.fftpack.fftshift(scipy.fftpack.fft2(data_copy))
        else:
            raise NotImplementedError()

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        return data_shape, numpy.dtype(numpy.complex128)

    def get_processed_spatial_calibrations(self, data_shape, data_dtype, source_calibrations):
        assert len(source_calibrations) == len(Image.spatial_shape_from_shape_and_dtype(data_shape, data_dtype))
        return [Calibration.Calibration(0.0,
                                     1.0 / (source_calibrations[i].scale * data_shape[i]),
                                     "1/" + source_calibrations[i].units) for i in range(len(source_calibrations))]


class IFFTOperation(Operation):

    def __init__(self):
        super(IFFTOperation, self).__init__(_("Inverse FFT"), "inverse-fft-operation")

    def process(self, data):
        if Image.is_data_1d(data):
            return scipy.fftpack.fftshift(scipy.fftpack.ifft(data))
        elif Image.is_data_2d(data):
            return scipy.fftpack.ifft2(scipy.fftpack.ifftshift(data))
        else:
            raise NotImplementedError()

    def get_processed_spatial_calibrations(self, data_shape, data_dtype, source_calibrations):
        assert len(source_calibrations) == len(Image.spatial_shape_from_shape_and_dtype(data_shape, data_dtype))
        return [Calibration.Calibration(0.0,
                                     1.0 / (source_calibrations[i].scale * data_shape[i]),
                                     "1/" + source_calibrations[i].units) for i in range(len(source_calibrations))]


class InvertOperation(Operation):

    def __init__(self):
        super(InvertOperation, self).__init__(_("Invert"), "invert-operation")

    def process(self, data):
        if data is not None:
            if Image.is_data_rgba(data) or Image.is_data_rgb(data):
                if Image.is_data_rgba(data):
                    inverted = 255 - data[:]
                    inverted[...,3] = data[...,3]
                    return inverted
                else:
                    return 255 - data[:]
            else:
                return -data[:]
        return None


class GaussianBlurOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Radius"), "property": "sigma", "type": "scalar", "default": 0.3 }
        ]
        super(GaussianBlurOperation, self).__init__(_("Gaussian Blur"), "gaussian-blur-operation", description)
        self.sigma = 0.3

    def process(self, data):
        return scipy.ndimage.gaussian_filter(data, sigma=10*self.get_property("sigma"))


class Crop2dOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Bounds"), "property": "bounds", "type": "rectangle", "default": ((0.0, 0.0), (1.0, 1.0)) }
        ]
        super(Crop2dOperation, self).__init__(_("Crop"), "crop-operation", description)
        self.bounds = (0.0, 0.0), (1.0, 1.0)

    def get_processed_spatial_calibrations(self, data_shape, data_dtype, spatial_calibrations):
        cropped_spatial_calibrations = list()
        bounds = self.get_property("bounds")
        for index, spatial_calibration in enumerate(spatial_calibrations):
            cropped_calibration = Calibration.Calibration(spatial_calibration.offset + data_shape[index] * bounds[0][index] * spatial_calibration.scale,
                                                          spatial_calibration.scale,
                                                          spatial_calibration.units)
            cropped_spatial_calibrations.append(cropped_calibration)
        return cropped_spatial_calibrations

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        shape = data_shape
        bounds = self.get_property("bounds")
        bounds_int = ((int(shape[0] * bounds[0][0]), int(shape[1] * bounds[0][1])), (int(shape[0] * bounds[1][0]), int(shape[1] * bounds[1][1])))
        if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
            return bounds_int[1] + (data_shape[-1], ), data_dtype
        else:
            return bounds_int[1], data_dtype

    def process(self, data):
        shape = data.shape
        bounds = self.get_property("bounds")
        bounds_int = ((int(shape[0] * bounds[0][0]), int(shape[1] * bounds[0][1])), (int(shape[0] * bounds[1][0]), int(shape[1] * bounds[1][1])))
        return data[bounds_int[0][0]:bounds_int[0][0] + bounds_int[1][0], bounds_int[0][1]:bounds_int[0][1] + bounds_int[1][1]].copy()


class Slice3dOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Slice"), "property": "slice", "type": "slice-field", "default": 0 }
        ]
        super(Slice3dOperation, self).__init__(_("Slice"), "slice-operation", description)
        self.slice = 0

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        return data_shape[1:], data_dtype

    def process(self, data):
        shape = data.shape
        slice = self.get_property("slice")
        return data[slice,:].copy()


class Projection2dOperation(Operation):

    def __init__(self):
        # hardcoded to axis 0 right now
        super(Projection2dOperation, self).__init__(_("Projection"), "projection-operation")

    def get_processed_spatial_calibrations(self, data_shape, data_dtype, spatial_calibrations):
        return copy.deepcopy(spatial_calibrations)[1:]

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        return data_shape[1:], data_dtype

    def process(self, data):
        if Image.is_shape_and_dtype_rgb_type(data.shape, data.dtype):
            if Image.is_shape_and_dtype_rgb(data.shape, data.dtype):
                rgb_image = numpy.empty(data.shape[1:], numpy.uint8)
                rgb_image[:,0] = numpy.average(data[...,0], 0)
                rgb_image[:,1] = numpy.average(data[...,1], 0)
                rgb_image[:,2] = numpy.average(data[...,2], 0)
                return rgb_image
            else:
                rgba_image = numpy.empty(data.shape[1:], numpy.uint8)
                rgba_image[:,0] = numpy.average(data[...,0], 0)
                rgba_image[:,1] = numpy.average(data[...,1], 0)
                rgba_image[:,2] = numpy.average(data[...,2], 0)
                rgba_image[:,3] = numpy.average(data[...,3], 0)
                return rgba_image
        else:
            return numpy.average(data, 0)


class Resample2dOperation(Operation):

    def __init__(self):
        description = [
            {"name": _("Width"), "property": "width", "type": "integer-field", "default": None},
            {"name": _("Height"), "property": "height", "type": "integer-field", "default": None},
        ]
        super(Resample2dOperation, self).__init__(_("Resample"), "resample-operation", description)
        self.width = 0
        self.height = 0

    def process(self, data):
        height = self.get_property("height", data.shape[0])
        width = self.get_property("width", data.shape[1])
        if data.shape[1] == width and data.shape[0] == height:
            return data.copy()
        return Image.scaled(data, (height, width))

    def get_processed_spatial_calibrations(self, data_shape, data_dtype, source_calibrations):
        assert len(source_calibrations) == 2
        height = self.get_property("height", data_shape[0])
        width = self.get_property("width", data_shape[1])
        dimensions = (height, width)
        return [Calibration.Calibration(source_calibrations[i].offset,
                                     source_calibrations[i].scale * data_shape[i] / dimensions[i],
                                     source_calibrations[i].units) for i in range(len(source_calibrations))]

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        height = self.get_property("height", data_shape[0])
        width = self.get_property("width", data_shape[1])
        if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
            return (height, width, data_shape[-1]), data_dtype
        else:
            return (height, width), data_dtype

    def property_defaults_for_data_shape_and_dtype(self, data_shape, data_dtype):
        property_defaults = {
            "height": data_shape[0],
            "width": data_shape[1],
        }
        return property_defaults


class HistogramOperation(Operation):

    def __init__(self):
        super(HistogramOperation, self).__init__(_("Histogram"), "histogram-operation")
        self.bins = 256

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        return (self.bins, ), numpy.dtype(numpy.int)

    def process(self, data):
        histogram_data = numpy.histogram(data, bins=self.bins)
        return histogram_data[0].astype(numpy.int)


class LineProfileOperation(Operation):

    def __init__(self):
        description = [
            { "name": _("Start"), "property": "start", "type": "point", "default": (0.25, 0.25) },
            { "name": _("End"), "property": "end", "type": "point", "default": (0.75, 0.75) },
            { "name": _("Integration Width"), "property": "integration_width", "type": "integer-field", "default": 1 }
        ]
        super(LineProfileOperation, self).__init__(_("Line Profile"), "line-profile-operation", description)
        self.start = (0.25, 0.25)
        self.end = (0.75, 0.75)
        self.integration_width = 1

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        start = self.get_property("start")
        end = self.get_property("end")
        shape = data_shape
        start_data = (int(shape[0]*start[0]), int(shape[1]*start[1]))
        end_data = (int(shape[0]*end[0]), int(shape[1]*end[1]))
        length = int(math.sqrt((end_data[1] - start_data[1])**2 + (end_data[0] - start_data[0])**2))
        if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
            return (length, ), numpy.dtype(numpy.double)
        else:
            return (length, ), numpy.dtype(numpy.double)

    def get_processed_spatial_calibrations(self, data_shape, data_dtype, source_calibrations):
        return [Calibration.Calibration(0.0, source_calibrations[0].scale, source_calibrations[0].units)]

    # calculate grid of coordinates. returns n coordinate arrays for each row.
    # start and end are in data coordinates.
    # n is a positive integer, not zero
    def __coordinates(self, start, end, n):
        assert n > 0 and int(n) == n
        # n=1 => 0
        # n=2 => -0.5, 0.5
        # n=3 => -1, 0, 1
        # n=4 => -1.5, -0.5, 0.5, 1.5
        length = math.sqrt(math.pow(end[0] - start[0], 2) + math.pow(end[1] - start[1], 2))
        l = math.floor(length)
        a = numpy.linspace(0, length, l)  # along
        t = numpy.linspace(-(n-1)*0.5, (n-1)*0.5, n)  # transverse
        dy = (end[0] - start[0]) / length
        dx = (end[1] - start[1]) / length
        ix, iy = numpy.meshgrid(a, t)
        yy = start[0] + dy * ix + dx * iy
        xx = start[1] + dx * ix - dy * iy
        return xx, yy

    # xx, yy = __coordinates(None, (4,4), (8,4), 3)

    def process(self, data):
        assert Image.is_data_2d(data)
        if Image.is_data_rgb_type(data):
            data = Image.convert_to_grayscale(data, numpy.double)
        start = self.get_property("start")
        end = self.get_property("end")
        integration_width = int(self.get_property("integration_width"))
        shape = data.shape
        integration_width = min(max(shape[0], shape[1]), integration_width)  # limit integration width to sensible value
        start_data = (int(shape[0]*start[0]), int(shape[1]*start[1]))
        end_data = (int(shape[0]*end[0]), int(shape[1]*end[1]))
        length = math.sqrt(math.pow(end_data[1] - start_data[1], 2) + math.pow(end_data[0] - start_data[0], 2))
        if length > 1.0:
            spline_order_lookup = { "nearest": 0, "linear": 1, "quadratic": 2, "cubic": 3 }
            method = "nearest"
            spline_order = spline_order_lookup[method]
            xx, yy = self.__coordinates(start_data, end_data, integration_width)
            samples = scipy.ndimage.map_coordinates(data, (yy, xx), order=spline_order)
            if len(samples.shape) > 1:
                return numpy.sum(samples, 0) / integration_width
            else:
                return samples
        return numpy.zeros((1))


class ConvertToScalarOperation(Operation):

    def __init__(self):
        super(ConvertToScalarOperation, self).__init__(_("Convert to Scalar"), "convert-to-scalar-operation")

    def process(self, data):
        if Image.is_data_rgba(data) or Image.is_data_rgb(data):
            return Image.convert_to_grayscale(data, numpy.double)
        elif Image.is_data_complex_type(data):
            return Image.scalar_from_array(data)
        else:
            return data.copy()

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
            return data_shape[:-1], numpy.dtype(numpy.double)
        elif Image.is_shape_and_dtype_complex_type(data_shape, data_dtype):
            if Image.is_shape_and_dtype_complex64(data_shape, data_dtype):
                return data_shape, numpy.dtype(numpy.float32)
            else:
                return data_shape, numpy.dtype(numpy.float64)
        else:
            return data_shape, data_dtype


class OperationManager(object):
    __metaclass__ = Singleton

    def __init__(self):
        self.__operations = dict()

    def register_operation(self, operation_id, create_operation_fn):
        self.__operations[operation_id] = create_operation_fn

    def unregister_operation(self, operation_id):
        del self.__operations[operation_id]

    def build_operation(self, operation_id):
        if operation_id in self.__operations:
            return self.__operations[operation_id]()
        return None


class OperationPropertyBinding(Binding.Binding):

    """
        Binds to a property of an operation item.

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
                self.update_target(new_value)
                self.__values = copy.copy(self.source.values)


class SliceOperationPropertyBinding(Binding.Binding):

    """
        Binds to a property of an operation item.

        This object records the 'values' property of the operation. Then it
        watches for changes to 'values' which match the watched property.
        """

    def __init__(self, source, property_name, converter=None):
        super(SliceOperationPropertyBinding, self).__init__(source,  converter)
        self.__property_name = property_name
        def validate_and_set(value):
            value = min(value, self.source.data_item.spatial_shape[0])
            value = max(value, 0)
            self.source.set_property(self.__property_name, value)
        self.source_setter = validate_and_set
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
                self.update_target(new_value)
                self.__values = copy.copy(self.source.values)


class OperationPropertyToRegionBinding(OperationPropertyBinding):

    """
        Binds a property of an operation item to a property of a graphic item.
    """

    def __init__(self, operation, operation_property_name, region, region_property_name):
        super(OperationPropertyToRegionBinding, self).__init__(operation, operation_property_name)
        self.__region = region
        self.__region.add_observer(self)
        self.__region_property_name = region_property_name
        self.__operation_property_name = operation_property_name
        self.target_setter = lambda value: setattr(self.__region, region_property_name, value)

    def close(self):
        self.__region.remove_observer(self)
        self.__region = None
        super(OperationPropertyToRegionBinding, self).close()

    # watch for property changes on the region.
    def property_changed(self, sender, property_name, property_value):
        super(OperationPropertyToRegionBinding, self).property_changed(sender, property_name, property_value)
        if sender == self.__region and property_name == self.__region_property_name:
            old_property_value = self.source.get_property(self.__operation_property_name)
            # to prevent message loops, check to make sure it changed
            if property_value != old_property_value:
                self.update_source(property_value)


OperationManager().register_operation("selector-operation", lambda: SelectorOperation())
OperationManager().register_operation("fft-operation", lambda: FFTOperation())
OperationManager().register_operation("inverse-fft-operation", lambda: IFFTOperation())
OperationManager().register_operation("invert-operation", lambda: InvertOperation())
OperationManager().register_operation("gaussian-blur-operation", lambda: GaussianBlurOperation())
OperationManager().register_operation("crop-operation", lambda: Crop2dOperation())
OperationManager().register_operation("slice-operation", lambda: Slice3dOperation())
OperationManager().register_operation("projection-operation", lambda: Projection2dOperation())
OperationManager().register_operation("resample-operation", lambda: Resample2dOperation())
OperationManager().register_operation("histogram-operation", lambda: HistogramOperation())
OperationManager().register_operation("line-profile-operation", lambda: LineProfileOperation())
OperationManager().register_operation("convert-to-scalar-operation", lambda: ConvertToScalarOperation())


def operation_item_factory(lookup_id):
    return OperationItem(lookup_id("operation_id"))
