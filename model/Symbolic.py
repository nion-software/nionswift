"""
    Provide symbolic math services.

    The goal is to provide a module (namespace) where users can be provided with variables representing
    data items (directly or indirectly via reference to workspace panels).

    DataNodes represent data items, operations, numpy arrays, and constants.
"""

# futures
from __future__ import absolute_import

# standard libraries
import copy
import datetime
import logging
import numbers
import operator
import uuid

# third party libraries
import numpy
import scipy
import scipy.fftpack
import scipy.ndimage
import scipy.ndimage.filters
import scipy.ndimage.fourier
import scipy.signal

# local libraries
from nion.swift.model import Calibration
from nion.swift.model import DataAndMetadata
from nion.swift.model import Image
from nion.ui import Observable


def range(data):
    return numpy.amax(data) - numpy.amin(data)

def take_slice(data, key):
    return data[key].copy()


def function_fft(data_and_metadata):
    data_shape = data_and_metadata.data_shape
    data_dtype = data_and_metadata.data_dtype

    def calculate_data():
        data = data_and_metadata.data
        if data is None or not Image.is_data_valid(data):
            return None
        # scaling: numpy.sqrt(numpy.mean(numpy.absolute(data_copy)**2)) == numpy.sqrt(numpy.mean(numpy.absolute(data_copy_fft)**2))
        # see https://gist.github.com/endolith/1257010
        if Image.is_data_1d(data):
            scaling = 1.0 / numpy.sqrt(data_shape[0])
            return scipy.fftpack.fftshift(scipy.fftpack.fft(data) * scaling)
        elif Image.is_data_2d(data):
            data_copy = data.copy()  # let other threads use data while we're processing
            scaling = 1.0 / numpy.sqrt(data_shape[1] * data_shape[0])
            return scipy.fftpack.fftshift(scipy.fftpack.fft2(data_copy) * scaling)
        else:
            raise NotImplementedError()

    src_dimensional_calibrations = data_and_metadata.dimensional_calibrations

    if not Image.is_shape_and_dtype_valid(data_shape, data_dtype) or src_dimensional_calibrations is None:
        return None

    assert len(src_dimensional_calibrations) == len(
        Image.dimensional_shape_from_shape_and_dtype(data_shape, data_dtype))

    data_shape_and_dtype = data_shape, numpy.dtype(numpy.complex128)

    dimensional_calibrations = [Calibration.Calibration(0.0, 1.0 / (dimensional_calibration.scale * data_shape_n),
                                                        "1/" + dimensional_calibration.units) for
        dimensional_calibration, data_shape_n in zip(src_dimensional_calibrations, data_shape)]

    return DataAndMetadata.DataAndMetadata(calculate_data, data_shape_and_dtype, Calibration.Calibration(),
                                           dimensional_calibrations, dict(), datetime.datetime.utcnow())


def function_ifft(data_and_metadata):
    data_shape = data_and_metadata.data_shape
    data_dtype = data_and_metadata.data_dtype

    def calculate_data():
        data = data_and_metadata.data
        if data is None or not Image.is_data_valid(data):
            return None
        # scaling: numpy.sqrt(numpy.mean(numpy.absolute(data_copy)**2)) == numpy.sqrt(numpy.mean(numpy.absolute(data_copy_fft)**2))
        # see https://gist.github.com/endolith/1257010
        if Image.is_data_1d(data):
            scaling = numpy.sqrt(data_shape[0])
            return scipy.fftpack.fftshift(scipy.fftpack.ifft(data) * scaling)
        elif Image.is_data_2d(data):
            data_copy = data.copy()  # let other threads use data while we're processing
            scaling = numpy.sqrt(data_shape[1] * data_shape[0])
            return scipy.fftpack.ifft2(scipy.fftpack.ifftshift(data_copy) * scaling)
        else:
            raise NotImplementedError()

    src_dimensional_calibrations = data_and_metadata.dimensional_calibrations

    if not Image.is_shape_and_dtype_valid(data_shape, data_dtype) or src_dimensional_calibrations is None:
        return None

    assert len(src_dimensional_calibrations) == len(
        Image.dimensional_shape_from_shape_and_dtype(data_shape, data_dtype))

    data_shape_and_dtype = data_shape, data_dtype

    dimensional_calibrations = [Calibration.Calibration(0.0, 1.0 / (dimensional_calibration.scale * data_shape_n),
                                                        "1/" + dimensional_calibration.units) for
        dimensional_calibration, data_shape_n in zip(src_dimensional_calibrations, data_shape)]

    return DataAndMetadata.DataAndMetadata(calculate_data, data_shape_and_dtype, Calibration.Calibration(),
                                           dimensional_calibrations, dict(), datetime.datetime.utcnow())


def function_autocorrelate(data_and_metadata):
    def calculate_data():
        data = data_and_metadata.data
        if data is None or not Image.is_data_valid(data):
            return None
        if Image.is_data_2d(data):
            data_copy = data.copy()  # let other threads use data while we're processing
            data_std = data_copy.std(dtype=numpy.float64)
            if data_std != 0.0:
                data_norm = (data_copy - data_copy.mean(dtype=numpy.float64)) / data_std
            else:
                data_norm = data_copy
            scaling = 1.0 / (data_norm.shape[0] * data_norm.shape[1])
            data_norm = numpy.fft.rfft2(data_norm)
            return numpy.fft.fftshift(numpy.fft.irfft2(data_norm * numpy.conj(data_norm))) * scaling
            # this gives different results. why? because for some reason scipy pads out to 1023 and does calculation.
            # see https://github.com/scipy/scipy/blob/master/scipy/signal/signaltools.py
            # return scipy.signal.fftconvolve(data_copy, numpy.conj(data_copy), mode='same')
        return None

    if data_and_metadata is None:
        return None

    dimensional_calibrations = [Calibration.Calibration() for _ in data_and_metadata.data_shape]

    return DataAndMetadata.DataAndMetadata(calculate_data, data_and_metadata.data_shape_and_dtype,
                                           Calibration.Calibration(), dimensional_calibrations, dict(),
                                           datetime.datetime.utcnow())


def function_crosscorrelate(*args):
    if len(args) != 2:
        return None

    data_and_metadata1, data_and_metadata2 = args[0], args[1]

    def calculate_data():
        data1 = data_and_metadata1.data
        data2 = data_and_metadata2.data
        if data1 is None or data2 is None:
            return None
        if Image.is_data_2d(data1) and Image.is_data_2d(data2):
            data_std1 = data1.std(dtype=numpy.float64)
            if data_std1 != 0.0:
                norm1 = (data1 - data1.mean(dtype=numpy.float64)) / data_std1
            else:
                norm1 = data1
            data_std2 = data2.std(dtype=numpy.float64)
            if data_std2 != 0.0:
                norm2 = (data2 - data2.mean(dtype=numpy.float64)) / data_std2
            else:
                norm2 = data2
            scaling = 1.0 / (norm1.shape[0] * norm1.shape[1])
            return numpy.fft.fftshift(numpy.fft.irfft2(numpy.fft.rfft2(norm1) * numpy.conj(numpy.fft.rfft2(norm2)))) * scaling
            # this gives different results. why? because for some reason scipy pads out to 1023 and does calculation.
            # see https://github.com/scipy/scipy/blob/master/scipy/signal/signaltools.py
            # return scipy.signal.fftconvolve(data1.copy(), numpy.conj(data2.copy()), mode='same')
        return None

    if data_and_metadata1 is None or data_and_metadata2 is None:
        return None

    dimensional_calibrations = [Calibration.Calibration() for _ in data_and_metadata1.data_shape]

    return DataAndMetadata.DataAndMetadata(calculate_data, data_and_metadata1.data_shape_and_dtype,
                                           Calibration.Calibration(), dimensional_calibrations, dict(),
                                           datetime.datetime.utcnow())


def function_sobel(data_and_metadata):
    def calculate_data():
        data = data_and_metadata.data
        if not Image.is_data_valid(data):
            return None
        if Image.is_shape_and_dtype_rgb(data.shape, data.dtype):
            rgb = numpy.empty(data.shape[:-1] + (3,), numpy.uint8)
            rgb[..., 0] = scipy.ndimage.sobel(data[..., 0])
            rgb[..., 1] = scipy.ndimage.sobel(data[..., 1])
            rgb[..., 2] = scipy.ndimage.sobel(data[..., 2])
            return rgb
        elif Image.is_shape_and_dtype_rgba(data.shape, data.dtype):
            rgba = numpy.empty(data.shape[:-1] + (4,), numpy.uint8)
            rgba[..., 0] = scipy.ndimage.sobel(data[..., 0])
            rgba[..., 1] = scipy.ndimage.sobel(data[..., 1])
            rgba[..., 2] = scipy.ndimage.sobel(data[..., 2])
            rgba[..., 3] = data[..., 3]
            return rgba
        else:
            return scipy.ndimage.sobel(data)

    return DataAndMetadata.DataAndMetadata(calculate_data, data_and_metadata.data_shape_and_dtype,
                                           data_and_metadata.intensity_calibration,
                                           data_and_metadata.dimensional_calibrations, data_and_metadata.metadata,
                                           datetime.datetime.utcnow())


def function_laplace(data_and_metadata):
    def calculate_data():
        data = data_and_metadata.data
        if not Image.is_data_valid(data):
            return None
        if Image.is_shape_and_dtype_rgb(data.shape, data.dtype):
            rgb = numpy.empty(data.shape[:-1] + (3,), numpy.uint8)
            rgb[..., 0] = scipy.ndimage.laplace(data[..., 0])
            rgb[..., 1] = scipy.ndimage.laplace(data[..., 1])
            rgb[..., 2] = scipy.ndimage.laplace(data[..., 2])
            return rgb
        elif Image.is_shape_and_dtype_rgba(data.shape, data.dtype):
            rgba = numpy.empty(data.shape[:-1] + (4,), numpy.uint8)
            rgba[..., 0] = scipy.ndimage.laplace(data[..., 0])
            rgba[..., 1] = scipy.ndimage.laplace(data[..., 1])
            rgba[..., 2] = scipy.ndimage.laplace(data[..., 2])
            rgba[..., 3] = data[..., 3]
            return rgba
        else:
            return scipy.ndimage.laplace(data)

    return DataAndMetadata.DataAndMetadata(calculate_data, data_and_metadata.data_shape_and_dtype,
                                           data_and_metadata.intensity_calibration,
                                           data_and_metadata.dimensional_calibrations, data_and_metadata.metadata,
                                           datetime.datetime.utcnow())


def function_gaussian_blur(data_and_metadata, sigma):
    sigma = float(sigma)

    def calculate_data():
        data = data_and_metadata.data
        if not Image.is_data_valid(data):
            return None
        return scipy.ndimage.gaussian_filter(data, sigma=sigma)

    return DataAndMetadata.DataAndMetadata(calculate_data, data_and_metadata.data_shape_and_dtype,
                                           data_and_metadata.intensity_calibration,
                                           data_and_metadata.dimensional_calibrations, data_and_metadata.metadata,
                                           datetime.datetime.utcnow())


def function_median_filter(data_and_metadata, size):
    size = max(min(int(size), 999), 1)

    def calculate_data():
        data = data_and_metadata.data
        if not Image.is_data_valid(data):
            return None
        if Image.is_shape_and_dtype_rgb(data.shape, data.dtype):
            rgb = numpy.empty(data.shape[:-1] + (3,), numpy.uint8)
            rgb[..., 0] = scipy.ndimage.median_filter(data[..., 0], size=size)
            rgb[..., 1] = scipy.ndimage.median_filter(data[..., 1], size=size)
            rgb[..., 2] = scipy.ndimage.median_filter(data[..., 2], size=size)
            return rgb
        elif Image.is_shape_and_dtype_rgba(data.shape, data.dtype):
            rgba = numpy.empty(data.shape[:-1] + (4,), numpy.uint8)
            rgba[..., 0] = scipy.ndimage.median_filter(data[..., 0], size=size)
            rgba[..., 1] = scipy.ndimage.median_filter(data[..., 1], size=size)
            rgba[..., 2] = scipy.ndimage.median_filter(data[..., 2], size=size)
            rgba[..., 3] = data[..., 3]
            return rgba
        else:
            return scipy.ndimage.median_filter(data, size=size)

    return DataAndMetadata.DataAndMetadata(calculate_data, data_and_metadata.data_shape_and_dtype,
                                           data_and_metadata.intensity_calibration,
                                           data_and_metadata.dimensional_calibrations, data_and_metadata.metadata,
                                           datetime.datetime.utcnow())


def function_uniform_filter(data_and_metadata, size):
    size = max(min(int(size), 999), 1)

    def calculate_data():
        data = data_and_metadata.data
        if not Image.is_data_valid(data):
            return None
        if Image.is_shape_and_dtype_rgb(data.shape, data.dtype):
            rgb = numpy.empty(data.shape[:-1] + (3,), numpy.uint8)
            rgb[..., 0] = scipy.ndimage.uniform_filter(data[..., 0], size=size)
            rgb[..., 1] = scipy.ndimage.uniform_filter(data[..., 1], size=size)
            rgb[..., 2] = scipy.ndimage.uniform_filter(data[..., 2], size=size)
            return rgb
        elif Image.is_shape_and_dtype_rgba(data.shape, data.dtype):
            rgba = numpy.empty(data.shape[:-1] + (4,), numpy.uint8)
            rgba[..., 0] = scipy.ndimage.uniform_filter(data[..., 0], size=size)
            rgba[..., 1] = scipy.ndimage.uniform_filter(data[..., 1], size=size)
            rgba[..., 2] = scipy.ndimage.uniform_filter(data[..., 2], size=size)
            rgba[..., 3] = data[..., 3]
            return rgba
        else:
            return scipy.ndimage.uniform_filter(data, size=size)

    return DataAndMetadata.DataAndMetadata(calculate_data, data_and_metadata.data_shape_and_dtype,
                                           data_and_metadata.intensity_calibration,
                                           data_and_metadata.dimensional_calibrations, data_and_metadata.metadata,
                                           datetime.datetime.utcnow())


def function_transpose_flip(data_and_metadata, transpose=False, flip_v=False, flip_h=False):
    def calculate_data():
        data = data_and_metadata.data
        data_id = id(data)
        if not Image.is_data_valid(data):
            return None
        if transpose:
            if Image.is_shape_and_dtype_rgb_type(data.shape, data.dtype):
                data = numpy.transpose(data, [1, 0, 2])
            else:
                data = numpy.transpose(data, [1, 0])
        if flip_h:
            data = numpy.fliplr(data)
        if flip_v:
            data = numpy.flipud(data)
        if id(data) == data_id:  # ensure real data, not a view
            data = data.copy()
        return data

    data_shape = data_and_metadata.data_shape
    data_dtype = data_and_metadata.data_dtype

    if not Image.is_shape_and_dtype_valid(data_shape, data_dtype):
        return None

    if transpose:
        dimensional_calibrations = list(reversed(data_and_metadata.dimensional_calibrations))
    else:
        dimensional_calibrations = data_and_metadata.dimensional_calibrations

    if transpose:
        if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
            data_shape = list(reversed(data_shape[0:2])) + [data_shape[-1], ]
        else:
            data_shape = list(reversed(data_shape))

    return DataAndMetadata.DataAndMetadata(calculate_data, (data_shape, data_dtype),
                                           data_and_metadata.intensity_calibration, dimensional_calibrations,
                                           data_and_metadata.metadata, datetime.datetime.utcnow())


def function_crop(data_and_metadata, bounds):
    data_shape = data_and_metadata.data_shape
    data_dtype = data_and_metadata.data_dtype

    def calculate_data():
        data = data_and_metadata.data
        if not Image.is_data_valid(data):
            return None
        data_shape = data_and_metadata.data_shape
        bounds_int = ((int(data_shape[0] * bounds[0][0]), int(data_shape[1] * bounds[0][1])),
            (int(data_shape[0] * bounds[1][0]), int(data_shape[1] * bounds[1][1])))
        return data[bounds_int[0][0]:bounds_int[0][0] + bounds_int[1][0],
            bounds_int[0][1]:bounds_int[0][1] + bounds_int[1][1]].copy()

    dimensional_calibrations = data_and_metadata.dimensional_calibrations

    if not Image.is_shape_and_dtype_valid(data_shape, data_dtype) or dimensional_calibrations is None:
        return None

    bounds_int = ((int(data_shape[0] * bounds[0][0]), int(data_shape[1] * bounds[0][1])),
        (int(data_shape[0] * bounds[1][0]), int(data_shape[1] * bounds[1][1])))

    if Image.is_shape_and_dtype_rgb_type(data_shape, data_dtype):
        data_shape_and_dtype = bounds_int[1] + (data_shape[-1], ), data_dtype
    else:
        data_shape_and_dtype = bounds_int[1], data_dtype

    cropped_dimensional_calibrations = list()
    for index, dimensional_calibration in enumerate(dimensional_calibrations):
        cropped_calibration = Calibration.Calibration(
            dimensional_calibration.offset + data_shape[index] * bounds[0][index] * dimensional_calibration.scale,
            dimensional_calibration.scale, dimensional_calibration.units)
        cropped_dimensional_calibrations.append(cropped_calibration)

    return DataAndMetadata.DataAndMetadata(calculate_data, data_shape_and_dtype,
                                           data_and_metadata.intensity_calibration, cropped_dimensional_calibrations,
                                           data_and_metadata.metadata, datetime.datetime.utcnow())


_function2_map = {
    "fft": function_fft,
    "ifft": function_ifft,
    "autocorrelate": function_autocorrelate,
    "crosscorrelate": function_crosscorrelate,
    "sobel": function_sobel,
    "laplace": function_laplace,
    "gaussian_blur": function_gaussian_blur,
    "median_filter": function_median_filter,
    "uniform_filter": function_uniform_filter,
    "transpose_flip": function_transpose_flip,
    "crop": function_crop,
}

_function_map = {
    "abs": operator.abs,
    "neg": operator.neg,
    "pos": operator.pos,
    "add": operator.add,
    "sub": operator.sub,
    "mul": operator.mul,
    "div": operator.truediv,
    "truediv": operator.truediv,
    "floordiv": operator.floordiv,
    "mod": operator.mod,
    "pow": operator.pow,
    "slice": take_slice,
    "amin": numpy.amin,
    "amax": numpy.amax,
    "range": range,
    "median": numpy.median,
    "average": numpy.average,
    "mean": numpy.mean,
    "std": numpy.std,
    "var": numpy.var,
    "log": numpy.log,
    "log10": numpy.log10,
    "log2": numpy.log2,
}


class DataNode(object):

    def __init__(self, inputs=None):
        self.inputs = inputs if inputs is not None else list()

    @classmethod
    def factory(cls, d):
        data_node_type = d["data_node_type"]
        assert data_node_type in _node_map
        node = _node_map[data_node_type]()
        node.read(d)
        return node

    def read(self, d):
        inputs = list()
        input_dicts = d.get("inputs", list())
        for input_dict in input_dicts:
            node = DataNode.factory(input_dict)
            node.read(input_dict)
            inputs.append(node)
        self.inputs = inputs
        return d

    def write(self):
        d = dict()
        input_dicts = list()
        for input in self.inputs:
            input_dicts.append(input.write())
        if len(input_dicts) > 0:
            d["inputs"] = input_dicts
        return d

    @classmethod
    def make(cls, value):
        if isinstance(value, DataNode):
            return value
        elif isinstance(value, numbers.Integral):
            return ConstantDataNode(value)
        elif isinstance(value, numbers.Rational):
            return ConstantDataNode(value)
        elif isinstance(value, numbers.Real):
            return ConstantDataNode(value)
        elif isinstance(value, numbers.Complex):
            return ConstantDataNode(value)
        elif isinstance(value, DataItemDataNode):
            return value
        assert False
        return None

    def evaluate(self, resolve):
        evaluated_inputs = list()
        for input in self.inputs:
            evaluated_input = input.evaluate(resolve)
            evaluated_inputs.append(evaluated_input)
        return self._evaluate_inputs(evaluated_inputs, resolve)

    def _evaluate_inputs(self, evaluated_inputs, resolve):
        raise NotImplementedError()

    def __abs__(self):
        return UnaryOperationDataNode([self], "abs")

    def __neg__(self):
        return UnaryOperationDataNode([self], "neg")

    def __pos__(self):
        return UnaryOperationDataNode([self], "pos")

    def __add__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "add")

    def __radd__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "add")

    def __sub__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "sub")

    def __rsub__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "sub")

    def __mul__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "mul")

    def __rmul__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "mul")

    def __div__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "div")

    def __rdiv__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "div")

    def __truediv__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "truediv")

    def __rtruediv__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "truediv")

    def __floordiv__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "floordiv")

    def __rfloordiv__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "floordiv")

    def __mod__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "mod")

    def __rmod__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "mod")

    def __pow__(self, other):
        return BinaryOperationDataNode([self, DataNode.make(other)], "pow")

    def __rpow__(self, other):
        return BinaryOperationDataNode([DataNode.make(other), self], "pow")

    def __complex__(self):
        return ConstantDataNode(numpy.astype(numpy.complex128))

    def __int__(self):
        return ConstantDataNode(numpy.astype(numpy.uint32))

    def __long__(self):
        return ConstantDataNode(numpy.astype(numpy.int64))

    def __float__(self):
        return ConstantDataNode(numpy.astype(numpy.float64))

    def __getitem__(self, key):
        return UnaryOperationDataNode([self], "slice", {"key": key})


class ConstantDataNode(DataNode):

    def __init__(self, value=None):
        super(ConstantDataNode, self).__init__()
        self.__scalar = numpy.array(value)
        if isinstance(value, numbers.Integral):
            self.__scalar_type = "integral"
        elif isinstance(value, numbers.Rational):
            self.__scalar_type = "rational"
        elif isinstance(value, numbers.Real):
            self.__scalar_type = "real"
        elif isinstance(value, numbers.Complex):
            self.__scalar_type = "complex"
        # else:
        #     raise Exception("Invalid constant type [{}].".format(type(value)))

    def read(self, d):
        super(ConstantDataNode, self).read(d)
        scalar_type = d.get("scalar_type")
        if scalar_type == "integral":
            self.__scalar = numpy.array(int(d["value"]))
        elif scalar_type == "real":
            self.__scalar = numpy.array(float(d["value"]))
        elif scalar_type == "complex":
            self.__scalar = numpy.array(complex(*d["value"]))

    def write(self):
        d = super(ConstantDataNode, self).write()
        d["data_node_type"] = "constant"
        d["scalar_type"] = self.__scalar_type
        value = self.__scalar
        if self.__scalar_type == "integral":
            d["value"] = int(value)
        elif isinstance(value, numbers.Rational):
            pass
        elif self.__scalar_type == "real":
            d["value"] = float(value)
        elif self.__scalar_type == "complex":
            d["value"] = complex(float(value.real), float(value.imag))
        return d

    def _evaluate_inputs(self, evaluated_inputs, resolve):
        return self.__scalar

    def __str__(self):
        return "{0} ({1})".format(self.__repr__(), self.__scalar)


class ScalarOperationDataNode(DataNode):

    def __init__(self, inputs=None, function_id=None, args=None):
        super(ScalarOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def read(self, d):
        super(ScalarOperationDataNode, self).read(d)
        function_id = d.get("function_id")
        assert function_id in _function_map
        self.__function_id = function_id
        args = d.get("args")
        self.__args = copy.copy(args if args is not None else dict())

    def write(self):
        d = super(ScalarOperationDataNode, self).write()
        d["data_node_type"] = "scalar"
        d["function_id"] = self.__function_id
        if self.__args:
            d["args"] = self.__args
        return d

    def _evaluate_inputs(self, evaluated_inputs, resolve):
        def calculate_data():
            return _function_map[self.__function_id](evaluated_inputs[0].data, **self.__args)

        return DataAndMetadata.DataAndMetadata(calculate_data, evaluated_inputs[0].data_shape_and_dtype,
                                               Calibration.Calibration(), list(), dict(), datetime.datetime.utcnow())

    def __str__(self):
        return "{0} {1}({2})".format(self.__repr__(), self.__function_id, self.inputs[0])


class UnaryOperationDataNode(DataNode):

    def __init__(self, inputs=None, function_id=None, args=None):
        super(UnaryOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def read(self, d):
        super(UnaryOperationDataNode, self).read(d)
        function_id = d.get("function_id")
        assert function_id in _function_map
        self.__function_id = function_id
        args = d.get("args")
        self.__args = copy.copy(args if args is not None else dict())

    def write(self):
        d = super(UnaryOperationDataNode, self).write()
        d["data_node_type"] = "unary"
        d["function_id"] = self.__function_id
        if self.__args:
            d["args"] = self.__args
        return d

    def _evaluate_inputs(self, evaluated_inputs, resolve):
        def calculate_data():
            return _function_map[self.__function_id](evaluated_inputs[0].data, **self.__args)

        return DataAndMetadata.DataAndMetadata(calculate_data, evaluated_inputs[0].data_shape_and_dtype,
                                               evaluated_inputs[0].intensity_calibration,
                                               evaluated_inputs[0].dimensional_calibrations,
                                               evaluated_inputs[0].metadata, datetime.datetime.utcnow())

    def __str__(self):
        return "{0} {1}({2})".format(self.__repr__(), self.__function_id, self.inputs[0])


class BinaryOperationDataNode(DataNode):

    def __init__(self, inputs=None, function_id=None, args=None):
        super(BinaryOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def read(self, d):
        super(BinaryOperationDataNode, self).read(d)
        function_id = d.get("function_id")
        assert function_id in _function_map
        self.__function_id = function_id
        args = d.get("args")
        self.__args = copy.copy(args if args is not None else dict())

    def write(self):
        d = super(BinaryOperationDataNode, self).write()
        d["data_node_type"] = "binary"
        d["function_id"] = self.__function_id
        if self.__args:
            d["args"] = self.__args
        return d

    def _evaluate_inputs(self, evaluated_inputs, resolve):
        def calculate_data():
            return _function_map[self.__function_id](evaluated_inputs[0].data, evaluated_inputs[1].data, **self.__args)

        # if the first input is not a data_and_metadata, use the second input
        src_evaluated_input = evaluated_inputs[0] if isinstance(evaluated_inputs[0], DataAndMetadata.DataAndMetadata) else evaluated_inputs[1]

        return DataAndMetadata.DataAndMetadata(calculate_data, src_evaluated_input.data_shape_and_dtype,
                                               src_evaluated_input.intensity_calibration,
                                               src_evaluated_input.dimensional_calibrations,
                                               src_evaluated_input.metadata, datetime.datetime.utcnow())

    def __str__(self):
        return "{0} {1}({2}, {3})".format(self.__repr__(), self.__function_id, self.inputs[0], self.inputs[1])


class FunctionOperationDataNode(DataNode):

    def __init__(self, inputs=None, function_id=None, args=None):
        super(FunctionOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def read(self, d):
        super(FunctionOperationDataNode, self).read(d)
        function_id = d.get("function_id")
        assert function_id in _function2_map
        self.__function_id = function_id
        args = d.get("args")
        self.__args = copy.copy(args if args is not None else dict())

    def write(self):
        d = super(FunctionOperationDataNode, self).write()
        d["data_node_type"] = "function"
        d["function_id"] = self.__function_id
        if self.__args:
            d["args"] = self.__args
        return d

    def _evaluate_inputs(self, evaluated_inputs, resolve):
        return _function2_map[self.__function_id](*evaluated_inputs, **self.__args)

    def __str__(self):
        return "{0} {1}({2})".format(self.__repr__(), self.__function_id, self.inputs[0])


class DataItemDataNode(DataNode):

    def __init__(self, data_reference=None):
        super(DataItemDataNode, self).__init__()
        self.__data_reference_uuid = data_reference.uuid if data_reference else uuid.uuid4()

    def read(self, d):
        super(DataItemDataNode, self).read(d)
        data_reference_uuid_str = d.get("data_reference_uuid")
        if data_reference_uuid_str:
            self.__data_reference_uuid = uuid.UUID(data_reference_uuid_str)

    def write(self):
        d = super(DataItemDataNode, self).write()
        d["data_node_type"] = "data"
        if self.__data_reference_uuid:
            d["data_reference_uuid"] = str(self.__data_reference_uuid)
        return d

    @property
    def data_reference_uuid(self):
        return self.__data_reference_uuid

    def _evaluate_inputs(self, evaluated_inputs, resolve):
        return resolve(self.__data_reference_uuid) if self.__data_reference_uuid else None

    def __str__(self):
        return "{0} ({1})".format(self.__repr__(), self.__data_reference_uuid)


class ReferenceDataNode(DataNode):

    def __init__(self, reference=None):
        super(ReferenceDataNode, self).__init__()
        self.__reference_uuid = reference.uuid if reference else uuid.uuid4()

    def read(self, d):
        super(ReferenceDataNode, self).read(d)
        reference_uuid_str = d.get("reference_uuid")
        if reference_uuid_str:
            self.__reference_uuid = uuid.UUID(reference_uuid_str)

    def write(self):
        d = super(ReferenceDataNode, self).write()
        d["data_node_type"] = "reference"
        if self.__reference_uuid:
            d["reference_uuid"] = str(self.__reference_uuid)
        return d

    @property
    def reference_uuid(self):
        return self.__reference_uuid

    def __getattr__(self, name):
        return PropertyDataNode(self.__reference_uuid, name)

    def __str__(self):
        return "{0} ({1})".format(self.__repr__(), self.__reference_uuid)


class PropertyDataNode(DataNode):

    def __init__(self, reference_uuid=None, property=None):
        super(PropertyDataNode, self).__init__()
        self.__reference_uuid = reference_uuid
        self.__property = str(property)

    def read(self, d):
        super(PropertyDataNode, self).read(d)
        self.__reference_uuid = uuid.UUID(d.get("reference_uuid"))
        self.__property = str(d.get("property"))

    def write(self):
        d = super(PropertyDataNode, self).write()
        d["data_node_type"] = "property"
        d["reference_uuid"] = str(self.__reference_uuid)
        d["property"] = str(self.__property)
        return d

    def _evaluate_inputs(self, evaluated_inputs, resolve):
        return getattr(resolve(self.__reference_uuid), self.__property)

    def __str__(self):
        return "{0} ({1}.{2})".format(self.__repr__(), self.__reference_uuid, self.__property)


_node_map = {
    "constant": ConstantDataNode,
    "scalar": ScalarOperationDataNode,
    "unary": UnaryOperationDataNode,
    "binary": BinaryOperationDataNode,
    "function": FunctionOperationDataNode,
    "property": PropertyDataNode,
    "reference": ReferenceDataNode,
    "data": DataItemDataNode,
}


def parse_expression(calculation_script, variable_map):
    code_lines = []
    g = dict()
    g["min"] = lambda data_node: ScalarOperationDataNode([data_node], "amin")
    g["max"] = lambda data_node: ScalarOperationDataNode([data_node], "amax")
    g["range"] = lambda data_node: ScalarOperationDataNode([data_node], "range")
    g["median"] = lambda data_node: ScalarOperationDataNode([data_node], "median")
    g["average"] = lambda data_node: ScalarOperationDataNode([data_node], "average")
    g["mean"] = lambda data_node: ScalarOperationDataNode([data_node], "mean")
    g["std"] = lambda data_node: ScalarOperationDataNode([data_node], "std")
    g["var"] = lambda data_node: ScalarOperationDataNode([data_node], "var")
    g["log"] = lambda data_node: UnaryOperationDataNode([data_node], "log")
    g["log10"] = lambda data_node: UnaryOperationDataNode([data_node], "log10")
    g["log2"] = lambda data_node: UnaryOperationDataNode([data_node], "log2")
    g["fft"] = lambda data_node: FunctionOperationDataNode([data_node], "fft")
    g["ifft"] = lambda data_node: FunctionOperationDataNode([data_node], "ifft")
    g["autocorrelate"] = lambda data_node: FunctionOperationDataNode([data_node], "autocorrelate")
    g["crosscorrelate"] = lambda data_node1, data_node2: FunctionOperationDataNode([data_node1, data_node2], "crosscorrelate")
    g["sobel"] = lambda data_node: FunctionOperationDataNode([data_node], "sobel")
    g["laplace"] = lambda data_node: FunctionOperationDataNode([data_node], "laplace")
    g["gaussian_blur"] = lambda data_node, scalar_node: FunctionOperationDataNode([data_node, DataNode.make(scalar_node)], "gaussian_blur")
    g["median_filter"] = lambda data_node, scalar_node: FunctionOperationDataNode([data_node, DataNode.make(scalar_node)], "median_filter")
    g["uniform_filter"] = lambda data_node, scalar_node: FunctionOperationDataNode([data_node, DataNode.make(scalar_node)], "uniform_filter")
    def transpose_flip(data_node, transpose=False, flip_v=False, flip_h=False):
        return FunctionOperationDataNode([data_node], "transpose_flip", args={"transpose": transpose, "flip_v": flip_v, "flip_h": flip_h})
    g["transpose_flip"] = transpose_flip
    g["crop"] = lambda data_node, bounds_node: FunctionOperationDataNode([data_node, bounds_node], "crop")
    l = dict()
    mapping = dict()
    for variable_name, value in variable_map.items():
        if type(value).__name__ == "DataItem":  # avoid importing class
            reference_node = DataItemDataNode()
            mapping[reference_node.data_reference_uuid] = value
        else:
            reference_node = ReferenceDataNode()
            mapping[reference_node.reference_uuid] = value
        g[variable_name] = reference_node
    code_lines.append("result = {0}".format(calculation_script))
    code = "\n".join(code_lines)
    exec(code, g, l)
    return l["result"], mapping


class Computation(Observable.Observable, Observable.ManagedObject):

    def __init__(self):
        super(Computation, self).__init__()
        self.define_type("computation")
        self.define_property("node")
        self.define_property("specifiers")

    def parse_expression(self, context, expression, variable_map):
        data_node, mapping = parse_expression(expression, variable_map)
        object_specifiers = dict()
        for uuid, object in mapping.items():
            object_specifiers[str(uuid)] = context.get_object_specifier(object)
        self.node = data_node.write()
        self.specifiers = object_specifiers

    def evaluate(self, context):
        data_node = DataNode.factory(self.node)
        object_specifiers = self.specifiers
        def resolve(uuid):
            return context.resolve_object_specifier(object_specifiers[str(uuid)])
        return data_node.evaluate(resolve)
