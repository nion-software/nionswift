# standard libraries
import gettext
import math

# third party libraries
import numpy
import scipy
import scipy.fftpack
import scipy.ndimage
import scipy.ndimage.filters
import scipy.ndimage.fourier

# local libraries
from nion.swift import Calibration
from nion.swift import Image

_ = gettext.gettext


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

    # public method to do processing. double check that data is a copy and not the original.
    def get_processed_data(self, data):
        new_data = self.process(data)
        if data is not None:
            assert(id(new_data) != id(data))
        if new_data.base is not None:
            assert(id(new_data.base) != id(data))
        return new_data

    # calibrations
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
        if Image.is_data_rgba(data) or Image.is_data_rgb(data):
            if Image.is_data_rgba(data):
                inverted = 255 - data[:]
                inverted[...,3] = data[...,3]
                return inverted
            else:
                return 255 - data[:]
        else:
            return -data[:]


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

    def get_processed_data_shape_and_dtype(self, data_shape, data_dtype):
        shape = data_shape
        bounds = self.get_property("bounds")
        bounds_int = ((int(shape[0] * bounds[0][0]), int(shape[1] * bounds[0][1])), (int(shape[0] * bounds[1][0]), int(shape[1] * bounds[1][1])))
        if Image.is_shape_and_dtype_rgba(data_shape, data_dtype) or Image.is_shape_and_dtype_rgb(data_shape, data_dtype):
            return bounds_int[1] + (data_shape[-1], ), data_dtype
        else:
            return bounds_int[1], data_dtype

    def process(self, data):
        shape = data.shape
        bounds = self.get_property("bounds")
        bounds_int = ((int(shape[0] * bounds[0][0]), int(shape[1] * bounds[0][1])), (int(shape[0] * bounds[1][0]), int(shape[1] * bounds[1][1])))
        return data[bounds_int[0][0]:bounds_int[0][0] + bounds_int[1][0], bounds_int[0][1]:bounds_int[0][1] + bounds_int[1][1]].copy()


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
        return [Calibration.Calibration(source_calibrations[i].origin,
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
        if Image.is_shape_and_dtype_rgba(data_shape, data_dtype) or Image.is_shape_and_dtype_rgb(data_shape, data_dtype):
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
        integration_width = self.get_property("integration_width")
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
        if Image.is_shape_and_dtype_rgba(data_shape, data_dtype) or Image.is_shape_and_dtype_rgb(data_shape, data_dtype):
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


OperationManager().register_operation("fft-operation", lambda: FFTOperation())
OperationManager().register_operation("inverse-fft-operation", lambda: IFFTOperation())
OperationManager().register_operation("invert-operation", lambda: InvertOperation())
OperationManager().register_operation("gaussian-blur-operation", lambda: GaussianBlurOperation())
OperationManager().register_operation("crop-operation", lambda: Crop2dOperation())
OperationManager().register_operation("resample-operation", lambda: Resample2dOperation())
OperationManager().register_operation("histogram-operation", lambda: HistogramOperation())
OperationManager().register_operation("line-profile-operation", lambda: LineProfileOperation())
OperationManager().register_operation("convert-to-scalar-operation", lambda: ConvertToScalarOperation())
