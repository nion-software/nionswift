"""
    Provide symbolic math services.

    The goal is to provide a module (namespace) where users can be provided with variables representing
    data items (directly or indirectly via reference to workspace panels).

    DataNodes represent data items, operations, numpy arrays, and constants.
"""

# standard libraries
import copy
import datetime
import logging
import numbers
import operator
import threading
import uuid

# third party libraries
import numpy

# local libraries
from nion.data import Core
from nion.data import DataAndMetadata
from nion.ui import Event
from nion.ui import Observable
from nion.ui import Persistence


_function2_map = {
    "fft": Core.function_fft,
    "ifft": Core.function_ifft,
    "autocorrelate": Core.function_autocorrelate,
    "crosscorrelate": Core.function_crosscorrelate,
    "sobel": Core.function_sobel,
    "laplace": Core.function_laplace,
    "gaussian_blur": Core.function_gaussian_blur,
    "median_filter": Core.function_median_filter,
    "uniform_filter": Core.function_uniform_filter,
    "transpose_flip": Core.function_transpose_flip,
    "crop": Core.function_crop,
    "slice_sum": Core.function_slice_sum,
    "pick": Core.function_pick,
    "project": Core.function_project,
    "resample_image": Core.function_resample_2d,
    "histogram": Core.function_histogram,
    "line_profile": Core.function_line_profile,
    "data_slice": DataAndMetadata.function_data_slice,
    "concatenate": Core.function_concatenate,
    "reshape": Core.function_reshape,
}

_operator_map = {
    "pow": ["**", 9],
    "neg": ["-", 8],
    "pos": ["+", 8],
    "add": ["+", 6],
    "sub": ["-", 6],
    "mul": ["*", 7],
    "div": ["/", 7],
    "truediv": ["/", 7],
    "floordiv": ["//", 7],
    "mod": ["%", 7],
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
    "column": Core.column,
    "row": Core.row,
    "radius": Core.radius,
    "item": Core.take_item,
    "amin": numpy.amin,
    "amax": numpy.amax,
    "arange": Core.arange,
    "median": numpy.median,
    "average": numpy.average,
    "mean": numpy.mean,
    "std": numpy.std,
    "var": numpy.var,
    # trig functions
    "sin": numpy.sin,
    "cos": numpy.cos,
    "tan": numpy.tan,
    "arcsin": numpy.arcsin,
    "arccos": numpy.arccos,
    "arctan": numpy.arctan,
    "hypot": numpy.hypot,
    "arctan2": numpy.arctan2,
    "degrees": numpy.degrees,
    "radians": numpy.radians,
    "rad2deg": numpy.rad2deg,
    "deg2rad": numpy.deg2rad,
    # rounding
    "around": numpy.around,
    "round": numpy.round,
    "rint": numpy.rint,
    "fix": numpy.fix,
    "floor": numpy.floor,
    "ceil": numpy.ceil,
    "trunc": numpy.trunc,
    # exponents and logarithms
    "exp": numpy.exp,
    "expm1": numpy.expm1,
    "exp2": numpy.exp2,
    "log": numpy.log,
    "log10": numpy.log10,
    "log2": numpy.log2,
    "log1p": numpy.log1p,
    # other functions
    "reciprocal": numpy.reciprocal,
    "clip": numpy.clip,
    "sqrt": numpy.sqrt,
    "square": numpy.square,
    "nan_to_num": numpy.nan_to_num,
    # complex numbers
    "angle": numpy.angle,
    "real": numpy.real,
    "imag": numpy.imag,
    "conj": numpy.conj,
    # conversions
    "astype": Core.astype,
    # data functions
    "data_shape": Core.data_shape,
    "shape": Core.function_make_shape,
    "vector": Core.function_make_vector,
    "rectangle_from_origin_size": Core.function_make_rectangle_origin_size,
    "rectangle_from_center_size": Core.function_make_rectangle_center_size,
    "normalized_point": Core.function_make_point,
    "normalized_size": Core.function_make_size,
    "normalized_interval": Core.function_make_interval,
}

def reconstruct_inputs(variable_map, inputs):
    input_texts = list()
    for input in inputs:
        text, precedence = input.reconstruct(variable_map)
        input_texts.append((text, precedence))
    return input_texts


def extract_data(evaluated_input):
    if isinstance(evaluated_input, DataAndMetadata.DataAndMetadata):
        return evaluated_input.data
    return evaluated_input


def key_to_list(key):
    if not isinstance(key, tuple):
        key = (key, )
    l = list()
    for k in key:
        if isinstance(k, slice):
            d = dict()
            if k.start is not None:
                d["start"] = k.start
            if k.stop is not None:
                d["stop"] = k.stop
            if k.step is not None:
                d["step"] = k.step
            l.append(d)
        elif isinstance(k, numbers.Integral):
            l.append({"index": k})
        elif isinstance(k, type(Ellipsis)):
            l.append({"ellipses": True})
        elif k is None:
            l.append({"newaxis": True})
        else:
            print(type(k))
            assert False
    return l


def list_to_key(l):
    key = list()
    for d in l:
        if "index" in d:
            key.append(d.get("index"))
        elif d.get("ellipses", False):
            key.append(Ellipsis)
        elif d.get("newaxis", False):
            key.append(None)
        else:
            key.append(slice(d.get("start"), d.get("stop"), d.get("step")))
    if len(key) == 1:
        return key[0]
    return key


dtype_map = {int: "int", float: "float", complex: "complex", numpy.int16: "int16", numpy.int32: "int32",
    numpy.int64: "int64", numpy.uint8: "uint8", numpy.uint16: "uint16", numpy.uint32: "uint32", numpy.uint64: "uint64",
    numpy.float32: "float32", numpy.float64: "float64", numpy.complex64: "complex64", numpy.complex128: "complex128"}

dtype_inverse_map = {dtype_map[k]: k for k in dtype_map}

def str_to_dtype(str: str) -> numpy.dtype:
    return dtype_inverse_map.get(str, float)

def dtype_to_str(dtype: numpy.dtype) -> str:
    return dtype_map.get(dtype, "float")


class DataNode(object):

    def __init__(self, inputs=None):
        self.uuid = uuid.uuid4()
        self.inputs = inputs if inputs is not None else list()

    def __deepcopy__(self, memo):
        new = self.__class__()
        new.deepcopy_from(self, memo)
        memo[id(self)] = new
        return new

    def deepcopy_from(self, node, memo):
        self.uuid = node.uuid
        self.inputs = [copy.deepcopy(input, memo) for input in node.inputs]

    @classmethod
    def factory(cls, d):
        data_node_type = d["data_node_type"]
        assert data_node_type in _node_map
        node = _node_map[data_node_type]()
        node.read(d)
        return node

    def read(self, d):
        self.uuid = uuid.UUID(d["uuid"])
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
        d["uuid"] = str(self.uuid)
        input_dicts = list()
        for input in self.inputs:
            input_dicts.append(input.write())
        if len(input_dicts) > 0:
            d["inputs"] = input_dicts
        return d

    @classmethod
    def make(cls, value):
        if isinstance(value, ScalarOperationDataNode):
            return value
        elif isinstance(value, DataNode):
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

    def evaluate(self, context):
        evaluated_inputs = list()
        for input in self.inputs:
            evaluated_input = input.evaluate(context)
            evaluated_inputs.append(evaluated_input)
        return self._evaluate_inputs(evaluated_inputs, context)

    def _evaluate_inputs(self, evaluated_inputs, context):
        raise NotImplementedError()

    def bind(self, context, bound_items):
        for input in self.inputs:
            input.bind(context, bound_items)

    def unbind(self):
        for input in self.inputs:
            input.unbind()

    def reconstruct(self, variable_map):
        raise NotImplemented()

    def print_mapping(self, context):
        for input in self.inputs:
            input.print_mapping(context)

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
        raise Exception("Use astype(data, complex128) instead.")

    def __int__(self):
        raise Exception("Use astype(data, int) instead.")

    def __long__(self):
        raise Exception("Use astype(data, int64) instead.")

    def __float__(self):
        raise Exception("Use astype(data, float64) instead.")

    def __getitem__(self, key):
        key = key_to_list(key)
        return FunctionOperationDataNode([self], "data_slice", {"key": key})


class ConstantDataNode(DataNode):
    """Represent a constant value."""

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

    def deepcopy_from(self, node, memo):
        super(ConstantDataNode, self).deepcopy_from(node, memo)
        self.__scalar = copy.deepcopy(node.__scalar)

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

    def _evaluate_inputs(self, evaluated_inputs, context):
        return self.__scalar

    def reconstruct(self, variable_map):
        return str(self.__scalar), 10

    def __str__(self):
        return "{0} ({1})".format(self.__repr__(), self.__scalar)


class ScalarOperationDataNode(DataNode):
    """Take a set of inputs and produce a scalar value output.

    For example, mean(src) will produce the mean value of the data item src.
    """

    def __init__(self, inputs=None, function_id=None, args=None):
        super(ScalarOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def deepcopy_from(self, node, memo):
        super(ScalarOperationDataNode, self).deepcopy_from(node, memo)
        self.__function_id = node.__function_id
        self.__args = [copy.deepcopy(arg, memo) for arg in node.__args]

    def read(self, d):
        super(ScalarOperationDataNode, self).read(d)
        function_id = d.get("function_id")
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

    def _evaluate_inputs(self, evaluated_inputs, context):
        if self.__function_id in _function_map and all(evaluated_input is not None for evaluated_input in evaluated_inputs):
            return _function_map[self.__function_id](*[extract_data(evaluated_input) for evaluated_input in evaluated_inputs], **self.__args)
        return None

    def reconstruct(self, variable_map):
        inputs = reconstruct_inputs(variable_map, self.inputs)
        input_texts = [input[0] for input in inputs]
        if self.__function_id == "item":
            return "{0}[{1}]".format(input_texts[0], self.__args["key"]), 10
        args_str = ", ".join([k + "=" + str(v) for k, v in self.__args.items()])
        if len(self.__args) > 0:
            args_str = ", " + args_str
        return "{0}({1}{2})".format(self.__function_id, ", ".join(input_texts), args_str), 10

    def __getitem__(self, key):
        return ScalarOperationDataNode([self], "item", {"key": key})

    def __str__(self):
        return "{0} {1}({2})".format(self.__repr__(), self.__function_id, self.inputs[0])


class UnaryOperationDataNode(DataNode):

    def __init__(self, inputs=None, function_id=None, args=None):
        super(UnaryOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def deepcopy_from(self, node, memo):
        super(UnaryOperationDataNode, self).deepcopy_from(node, memo)
        self.__function_id = node.__function_id
        self.__args = [copy.deepcopy(arg, memo) for arg in node.__args]

    def read(self, d):
        super(UnaryOperationDataNode, self).read(d)
        function_id = d.get("function_id")
        self.__function_id = function_id
        args = d.get("args")
        self.__args = copy.copy(args if args is not None else dict())
        # TODO: fix this special case by providing default arguments
        # the issue is that JSON is not able to store dict's with None
        # values. this is OK in most cases, but in this case, it prevents
        # the argument from being passed to column/row.
        if self.__function_id in ("column", "row"):
            self.__args.setdefault("start", None)
            self.__args.setdefault("stop", None)

    def write(self):
        d = super(UnaryOperationDataNode, self).write()
        d["data_node_type"] = "unary"
        d["function_id"] = self.__function_id
        if self.__args:
            d["args"] = self.__args
        return d

    def _evaluate_inputs(self, evaluated_inputs, context):
        def calculate_data():
            return _function_map[self.__function_id](extract_data(evaluated_inputs[0]), **self.__args)

        if self.__function_id in _function_map and all(evaluated_input is not None for evaluated_input in evaluated_inputs):
            if isinstance(evaluated_inputs[0], DataAndMetadata.DataAndMetadata):
                return DataAndMetadata.DataAndMetadata(calculate_data, evaluated_inputs[0].data_shape_and_dtype,
                                                       evaluated_inputs[0].intensity_calibration,
                                                       evaluated_inputs[0].dimensional_calibrations,
                                                       evaluated_inputs[0].metadata, datetime.datetime.utcnow())
            else:
                return numpy.array(_function_map[self.__function_id](evaluated_inputs[0]))
        return None

    def reconstruct(self, variable_map):
        inputs = reconstruct_inputs(variable_map, self.inputs)
        input_texts = [input[0] for input in inputs]
        operator_arg = input_texts[0]
        if self.__function_id in _operator_map:
            operator_text, precedence = _operator_map[self.__function_id]
            if precedence >= inputs[0][1]:
                operator_arg = "({0})".format(operator_arg)
            return "{0}{1}".format(operator_text, operator_arg), precedence
        if self.__function_id == "astype":
            return "{0}({1}, {2})".format(self.__function_id, operator_arg, self.__args["dtype"]), 10
        if self.__function_id in ("column", "row"):
            if self.__args.get("start") is None and self.__args.get("stop") is None:
                return "{0}({1})".format(self.__function_id, operator_arg), 10
        if self.__function_id == "radius":
            if self.__args.get("normalize", True) is True:
                return "{0}({1})".format(self.__function_id, operator_arg), 10
        args_str = ", ".join([k + "=" + str(v) for k, v in self.__args.items()])
        if len(self.__args) > 0:
            args_str = ", " + args_str
        return "{0}({1}{2})".format(self.__function_id, operator_arg, args_str), 10

    def __str__(self):
        return "{0} {1}({2})".format(self.__repr__(), self.__function_id, self.inputs[0])


class BinaryOperationDataNode(DataNode):

    def __init__(self, inputs=None, function_id=None, args=None):
        super(BinaryOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def deepcopy_from(self, node, memo):
        super(BinaryOperationDataNode, self).deepcopy_from(node, memo)
        self.__function_id = node.__function_id
        self.__args = [copy.deepcopy(arg, memo) for arg in node.__args]

    def read(self, d):
        super(BinaryOperationDataNode, self).read(d)
        function_id = d.get("function_id")
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

    def _evaluate_inputs(self, evaluated_inputs, context):
        def calculate_data():
            return _function_map[self.__function_id](extract_data(evaluated_inputs[0]), extract_data(evaluated_inputs[1]), **self.__args)

        # if the first input is not a data_and_metadata, use the second input
        src_evaluated_input = evaluated_inputs[0] if isinstance(evaluated_inputs[0], DataAndMetadata.DataAndMetadata) else evaluated_inputs[1]

        if self.__function_id in _function_map and all(evaluated_input is not None for evaluated_input in evaluated_inputs):
            if isinstance(src_evaluated_input, DataAndMetadata.DataAndMetadata):
                return DataAndMetadata.DataAndMetadata(calculate_data, src_evaluated_input.data_shape_and_dtype,
                                                       src_evaluated_input.intensity_calibration,
                                                       src_evaluated_input.dimensional_calibrations,
                                                       src_evaluated_input.metadata, datetime.datetime.utcnow())
            else:
                return numpy.array(_function_map[self.__function_id](evaluated_inputs[0], evaluated_inputs[1]))
        return None

    def reconstruct(self, variable_map):
        inputs = reconstruct_inputs(variable_map, self.inputs)
        input_texts = [input[0] for input in inputs]
        operator_left = input_texts[0]
        operator_right = input_texts[1]
        if self.__function_id in _operator_map:
            operator_text, precedence = _operator_map[self.__function_id]
            if precedence > inputs[0][1]:
                operator_left = "({0})".format(operator_left)
            if precedence > inputs[1][1]:
                operator_right = "({0})".format(operator_right)
            return "{1} {0} {2}".format(operator_text, operator_left, operator_right), precedence
        return "{0}({1}, {2})".format(self.__function_id, operator_left, operator_right), 10

    def __str__(self):
        return "{0} {1}({2}, {3})".format(self.__repr__(), self.__function_id, self.inputs[0], self.inputs[1])


class FunctionOperationDataNode(DataNode):

    def __init__(self, inputs=None, function_id=None, args=None):
        super(FunctionOperationDataNode, self).__init__(inputs=inputs)
        self.__function_id = function_id
        self.__args = copy.copy(args if args is not None else dict())

    def deepcopy_from(self, node, memo):
        super(FunctionOperationDataNode, self).deepcopy_from(node, memo)
        self.__function_id = node.__function_id
        self.__args = [copy.deepcopy(arg, memo) for arg in node.__args]

    def read(self, d):
        super(FunctionOperationDataNode, self).read(d)
        function_id = d.get("function_id")
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

    def _evaluate_inputs(self, evaluated_inputs, context):
        # don't pass the data; the functions are responsible for extracting the data correctly
        if self.__function_id in _function2_map and all(evaluated_input is not None for evaluated_input in evaluated_inputs):
            return _function2_map[self.__function_id](*evaluated_inputs, **self.__args)
        return None

    def reconstruct(self, variable_map):
        inputs = reconstruct_inputs(variable_map, self.inputs)
        input_texts = [input[0] for input in inputs]
        if self.__function_id == "data_slice":
            operator_arg = input_texts[0]
            slice_strs = list()
            for slice_or_index in list_to_key(self.__args["key"]):
                if isinstance(slice_or_index, slice):
                    slice_str = str(slice_or_index.start) if slice_or_index.start is not None else ""
                    slice_str += ":" + str(slice_or_index.stop) if slice_or_index.stop is not None else ":"
                    slice_str += ":" + str(slice_or_index.step) if slice_or_index.step is not None else ""
                    slice_strs.append(slice_str)
                elif isinstance(slice_or_index, numbers.Integral):
                    slice_str += str(slice_or_index)
                    slice_strs.append(slice_str)
            return "{0}[{1}]".format(operator_arg, ", ".join(slice_strs)), 10
        if self.__function_id == "concatenate":
            axis = self.__args.get("axis", 0)
            axis_str = (", " + str(axis)) if axis != 0 else str()
            return "{0}(({1}){2})".format(self.__function_id, ", ".join(input_texts), axis_str), 10
        if self.__function_id == "reshape":
            shape = self.__args.get("shape", 0)
            shape_str = (", " + str(shape)) if shape != 0 else str()
            return "{0}({1}{2})".format(self.__function_id, ", ".join(input_texts), shape_str), 10
        return "{0}({1})".format(self.__function_id, ", ".join(input_texts)), 10

    def __str__(self):
        return "{0} {1}({2}, {3})".format(self.__repr__(), self.__function_id, [str(input) for input in self.inputs], list(self.__args))


class DataItemDataNode(DataNode):

    def __init__(self, object_specifier=None):
        super(DataItemDataNode, self).__init__()
        self.__object_specifier = object_specifier
        self.__bound_item = None

    def deepcopy_from(self, node, memo):
        super(DataItemDataNode, self).deepcopy_from(node, memo)
        self.__object_specifier = copy.deepcopy(node.__object_specifier, memo)
        self.__bound_item = None

    @property
    def _bound_item_for_test(self):
        return self.__bound_item

    def read(self, d):
        super(DataItemDataNode, self).read(d)
        self.__object_specifier = d["object_specifier"]

    def write(self):
        d = super(DataItemDataNode, self).write()
        d["data_node_type"] = "data"
        d["object_specifier"] = copy.deepcopy(self.__object_specifier)
        return d

    def _evaluate_inputs(self, evaluated_inputs, context):
        if self.__bound_item:
            return self.__bound_item.value
        return None

    def print_mapping(self, context):
        logging.debug("%s: %s", self.__data_reference_uuid, self.__object_specifier)

    def bind(self, context, bound_items):
        self.__bound_item = context.resolve_object_specifier(self.__object_specifier)
        if self.__bound_item is not None:
            bound_items[self.uuid] = self.__bound_item

    def unbind(self):
        self.__bound_item = None

    def reconstruct(self, variable_map):
        variable_index = -1
        prefix = "d"
        for variable, object_specifier in variable_map.items():
            if object_specifier == self.__object_specifier:
                return variable, 10
            suffix = variable[len(prefix):]
            if suffix.isdigit():
                variable_index = max(variable_index, int(suffix) + 1)
        variable_index = max(variable_index, 0)
        variable_name = "{0}{1}".format(prefix, variable_index)
        variable_map[variable_name] = copy.deepcopy(self.__object_specifier)
        return variable_name, 10

    def __getattr__(self, name):
        return PropertyDataNode(self.__object_specifier, name)

    def __str__(self):
        return "{0} ({1})".format(self.__repr__(), self.__object_specifier)


class ReferenceDataNode(DataNode):

    def __init__(self, object_specifier=None):
        super(ReferenceDataNode, self).__init__()
        self.__object_specifier = object_specifier

    def deepcopy_from(self, node, memo):
        # should only be used as intermediate node, but here for error handling
        super(ReferenceDataNode, self).deepcopy_from(node, memo)
        self.__object_specifier = copy.deepcopy(node.__object_specifier, memo)

    def read(self, d):
        # should only be used as intermediate node, but here for error handling
        super(ReferenceDataNode, self).read(d)
        self.__object_specifier = d.get("object_specifier", {"type": "reference", "version": 1, "uuid": str(uuid.uuid4())})

    def write(self):
        # should only be used as intermediate node, but here for error handling
        d = super(ReferenceDataNode, self).write()
        d["data_node_type"] = "reference"
        d["object_specifier"] = copy.deepcopy(self.__object_specifier)
        return d

    def _evaluate_inputs(self, evaluated_inputs, context):
        return None

    def print_mapping(self, context):
        # should only be used as intermediate node, but here for error handling
        logging.debug("%s", self.__object_specifier)

    def bind(self, context, bound_items):
        pass  # should only be used as intermediate node

    def unbind(self):
        raise NotImplemented()  # should only be used as intermediate node

    def reconstruct(self, variable_map):
        variable_index = -1
        prefix = "ref"
        for variable, object_specifier in variable_map.items():
            if object_specifier == self.__object_specifier:
                return variable, 10
            suffix = variable[len(prefix):]
            if suffix.isdigit():
                variable_index = max(variable_index, int(suffix) + 1)
        variable_index = max(variable_index, 0)
        variable_name = "{0}{1}".format(prefix, variable_index)
        variable_map[variable_name] = copy.deepcopy(self.__object_specifier)
        return variable_name, 10

    def __getattr__(self, name):
        return PropertyDataNode(self.__object_specifier, name)

    def __str__(self):
        return "{0} ({1})".format(self.__repr__(), self.__reference_uuid)


class VariableDataNode(DataNode):

    def __init__(self, object_specifier=None):
        super(VariableDataNode, self).__init__()
        self.__object_specifier = object_specifier  # type: dict
        self.__bound_item = None

    def deepcopy_from(self, node, memo):
        super(VariableDataNode, self).deepcopy_from(node, memo)
        self.__object_specifier = copy.deepcopy(node.__object_specifier, memo)
        self.__bound_item = None

    def read(self, d):
        super(VariableDataNode, self).read(d)
        self.__object_specifier = d["object_specifier"]

    def write(self):
        d = super(VariableDataNode, self).write()
        d["data_node_type"] = "variable"
        d["object_specifier"] = copy.deepcopy(self.__object_specifier)
        return d

    def _evaluate_inputs(self, evaluated_inputs, context):
        if self.__bound_item:
            return self.__bound_item.value
        return None

    def print_mapping(self, context):
        logging.debug("%s", self.__object_specifier)

    def bind(self, context, bound_items):
        self.__bound_item = context.resolve_object_specifier(self.__object_specifier)
        if self.__bound_item is not None:
            bound_items[self.uuid] = self.__bound_item

    def unbind(self):
        self.__bound_item = None

    def reconstruct(self, variable_map):
        variable_index = -1
        object_specifier_type = self.__object_specifier["type"]
        if object_specifier_type == "variable":
            prefix = "x"
        for variable, object_specifier in sorted(variable_map.items()):
            if object_specifier == self.__object_specifier:
                return variable, 10
            if variable.startswith(prefix):
                suffix = variable[len(prefix):]
                if suffix.isdigit():
                    variable_index = max(variable_index, int(suffix) + 1)
        variable_index = max(variable_index, 0)
        variable_name = "{0}{1}".format(prefix, variable_index)
        variable_map[variable_name] = copy.deepcopy(self.__object_specifier)
        return variable_name, 10

    def __getattr__(self, name):
        return PropertyDataNode(self.__object_specifier, name)

    def __str__(self):
        return "{0} ({1})".format(self.__repr__(), self.__object_specifier)


class PropertyDataNode(DataNode):

    def __init__(self, object_specifier=None, property=None):
        super(PropertyDataNode, self).__init__()
        self.__object_specifier = object_specifier
        self.__property = str(property)
        self.__bound_item = None

    def deepcopy_from(self, node, memo):
        super(PropertyDataNode, self).deepcopy_from(node, memo)
        self.__object_specifier = copy.deepcopy(node.__object_specifier, memo)
        self.__property = node.__property
        self.__bound_item = None

    def read(self, d):
        super(PropertyDataNode, self).read(d)
        self.__object_specifier = d["object_specifier"]
        self.__property = d["property"]

    def write(self):
        d = super(PropertyDataNode, self).write()
        d["data_node_type"] = "property"
        d["object_specifier"] = copy.deepcopy(self.__object_specifier)
        d["property"] = self.__property
        return d

    def _evaluate_inputs(self, evaluated_inputs, resolve):
        if self.__bound_item:
            return self.__bound_item.value
        return None

    def print_mapping(self, context):
        logging.debug("%s.%s: %s", self.__property, self.__object_specifier)

    def bind(self, context, bound_items):
        self.__bound_item = context.resolve_object_specifier(self.__object_specifier, self.__property)
        if self.__bound_item is not None:
            bound_items[self.uuid] = self.__bound_item

    def unbind(self):
        self.__bound_item = None

    def reconstruct(self, variable_map):
        variable_index = -1
        object_specifier_type = self.__object_specifier["type"]
        if object_specifier_type == "data_item":
            prefix = "d"
        elif object_specifier_type == "region":
            prefix = "region"
        else:
            prefix = "object"
        for variable, object_specifier in sorted(variable_map.items()):
            if object_specifier == self.__object_specifier:
                return "{0}.{1}".format(variable, self.__property), 10
            if variable.startswith(prefix):
                suffix = variable[len(prefix):]
                if suffix.isdigit():
                    variable_index = max(variable_index, int(suffix) + 1)
        variable_index = max(variable_index, 0)
        variable_name = "{0}{1}".format(prefix, variable_index)
        variable_map[variable_name] = copy.deepcopy(self.__object_specifier)
        return "{0}.{1}".format(variable_name, self.__property), 10

    def __str__(self):
        return "{0} ({1}.{2})".format(self.__repr__(), self.__object_specifier, self.__property)


def data_by_uuid(context, data_uuid):
    object_specifier = context.get_data_item_specifier(data_uuid)
    return DataItemDataNode(object_specifier)


def region_by_uuid(context, region_uuid):
    object_specifier = context.get_region_specifier(region_uuid)
    if object_specifier:
        return ReferenceDataNode(object_specifier)
    return None


_node_map = {
    "constant": ConstantDataNode,
    "scalar": ScalarOperationDataNode,
    "unary": UnaryOperationDataNode,
    "binary": BinaryOperationDataNode,
    "function": FunctionOperationDataNode,
    "property": PropertyDataNode,
    "reference": ReferenceDataNode,
    "variable": VariableDataNode,
    "data": DataItemDataNode,  # TODO: file format: Rename symbolic node 'data' to 'dataitem'
}

def transpose_flip(data_node, transpose=False, flip_v=False, flip_h=False):
    return FunctionOperationDataNode([data_node, DataNode.make(transpose), DataNode.make(flip_v), DataNode.make(flip_h)], "transpose_flip")

def parse_expression(expression_lines, variable_map, context):
    code_lines = []
    code_lines.append("import uuid")
    g = dict()
    g["int16"] = numpy.int16
    g["int32"] = numpy.int32
    g["int64"] = numpy.int64
    g["uint8"] = numpy.uint8
    g["uint16"] = numpy.uint16
    g["uint32"] = numpy.uint32
    g["uint64"] = numpy.uint64
    g["float32"] = numpy.float32
    g["float64"] = numpy.float64
    g["complex64"] = numpy.complex64
    g["complex128"] = numpy.complex128
    g["astype"] = lambda data_node, dtype: UnaryOperationDataNode([data_node], "astype", {"dtype": dtype_to_str(dtype)})
    g["concatenate"] = lambda data_nodes, axis=0: FunctionOperationDataNode(tuple(data_nodes), "concatenate", {"axis": axis})
    g["reshape"] = lambda data_node, shape: FunctionOperationDataNode([data_node, DataNode.make(shape)], "reshape")
    g["data_slice"] = lambda data_node, key: FunctionOperationDataNode([data_node], "data_slice", {"key": key})
    g["item"] = lambda data_node, key: ScalarOperationDataNode([data_node], "item", {"key": key})
    g["column"] = lambda data_node, start=None, stop=None: UnaryOperationDataNode([data_node], "column", {"start": start, "stop": stop})
    g["row"] = lambda data_node, start=None, stop=None: UnaryOperationDataNode([data_node], "row", {"start": start, "stop": stop})
    g["radius"] = lambda data_node, normalize=True: UnaryOperationDataNode([data_node], "radius", {"normalize": normalize})
    g["amin"] = lambda data_node: ScalarOperationDataNode([data_node], "amin")
    g["amax"] = lambda data_node: ScalarOperationDataNode([data_node], "amax")
    g["arange"] = lambda data_node: ScalarOperationDataNode([data_node], "arange")
    g["median"] = lambda data_node: ScalarOperationDataNode([data_node], "median")
    g["average"] = lambda data_node: ScalarOperationDataNode([data_node], "average")
    g["mean"] = lambda data_node: ScalarOperationDataNode([data_node], "mean")
    g["std"] = lambda data_node: ScalarOperationDataNode([data_node], "std")
    g["var"] = lambda data_node: ScalarOperationDataNode([data_node], "var")
    g["sin"] = lambda data_node: UnaryOperationDataNode([data_node], "sin")
    g["cos"] = lambda data_node: UnaryOperationDataNode([data_node], "cos")
    g["tan"] = lambda data_node: UnaryOperationDataNode([data_node], "tan")
    g["arcsin"] = lambda data_node: UnaryOperationDataNode([data_node], "arcsin")
    g["arccos"] = lambda data_node: UnaryOperationDataNode([data_node], "arccos")
    g["arctan"] = lambda data_node: UnaryOperationDataNode([data_node], "arctan")
    g["hypot"] = lambda data_node: UnaryOperationDataNode([data_node], "hypot")
    g["arctan2"] = lambda data_node: UnaryOperationDataNode([data_node], "arctan2")
    g["degrees"] = lambda data_node: UnaryOperationDataNode([data_node], "degrees")
    g["radians"] = lambda data_node: UnaryOperationDataNode([data_node], "radians")
    g["rad2deg"] = lambda data_node: UnaryOperationDataNode([data_node], "rad2deg")
    g["deg2rad"] = lambda data_node: UnaryOperationDataNode([data_node], "deg2rad")
    g["around"] = lambda data_node: UnaryOperationDataNode([data_node], "around")
    g["round"] = lambda data_node: UnaryOperationDataNode([data_node], "round")
    g["rint"] = lambda data_node: UnaryOperationDataNode([data_node], "rint")
    g["fix"] = lambda data_node: UnaryOperationDataNode([data_node], "fix")
    g["floor"] = lambda data_node: UnaryOperationDataNode([data_node], "floor")
    g["ceil"] = lambda data_node: UnaryOperationDataNode([data_node], "ceil")
    g["trunc"] = lambda data_node: UnaryOperationDataNode([data_node], "trunc")
    g["exp"] = lambda data_node: UnaryOperationDataNode([data_node], "exp")
    g["expm1"] = lambda data_node: UnaryOperationDataNode([data_node], "expm1")
    g["exp2"] = lambda data_node: UnaryOperationDataNode([data_node], "exp2")
    g["log"] = lambda data_node: UnaryOperationDataNode([data_node], "log")
    g["log10"] = lambda data_node: UnaryOperationDataNode([data_node], "log10")
    g["log2"] = lambda data_node: UnaryOperationDataNode([data_node], "log2")
    g["log1p"] = lambda data_node: UnaryOperationDataNode([data_node], "log1p")
    g["reciprocal"] = lambda data_node: UnaryOperationDataNode([data_node], "reciprocal")
    g["clip"] = lambda data_node: UnaryOperationDataNode([data_node], "clip")
    g["sqrt"] = lambda data_node: UnaryOperationDataNode([data_node], "sqrt")
    g["square"] = lambda data_node: UnaryOperationDataNode([data_node], "square")
    g["nan_to_num"] = lambda data_node: UnaryOperationDataNode([data_node], "nan_to_num")
    g["angle"] = lambda data_node: UnaryOperationDataNode([data_node], "angle")
    g["real"] = lambda data_node: UnaryOperationDataNode([data_node], "real")
    g["imag"] = lambda data_node: UnaryOperationDataNode([data_node], "imag")
    g["conj"] = lambda data_node: UnaryOperationDataNode([data_node], "conj")
    g["fft"] = lambda data_node: FunctionOperationDataNode([data_node], "fft")
    g["ifft"] = lambda data_node: FunctionOperationDataNode([data_node], "ifft")
    g["autocorrelate"] = lambda data_node: FunctionOperationDataNode([data_node], "autocorrelate")
    g["crosscorrelate"] = lambda data_node1, data_node2: FunctionOperationDataNode([data_node1, data_node2], "crosscorrelate")
    g["sobel"] = lambda data_node: FunctionOperationDataNode([data_node], "sobel")
    g["laplace"] = lambda data_node: FunctionOperationDataNode([data_node], "laplace")
    g["gaussian_blur"] = lambda data_node, scalar_node: FunctionOperationDataNode([data_node, DataNode.make(scalar_node)], "gaussian_blur")
    g["median_filter"] = lambda data_node, scalar_node: FunctionOperationDataNode([data_node, DataNode.make(scalar_node)], "median_filter")
    g["uniform_filter"] = lambda data_node, scalar_node: FunctionOperationDataNode([data_node, DataNode.make(scalar_node)], "uniform_filter")
    g["transpose_flip"] = transpose_flip
    g["crop"] = lambda data_node, bounds_node: FunctionOperationDataNode([data_node, DataNode.make(bounds_node)], "crop")
    g["slice_sum"] = lambda data_node, scalar_node1, scalar_node2: FunctionOperationDataNode([data_node, DataNode.make(scalar_node1), DataNode.make(scalar_node2)], "slice_sum")
    g["pick"] = lambda data_node, position_node: FunctionOperationDataNode([data_node, DataNode.make(position_node)], "pick")
    g["project"] = lambda data_node: FunctionOperationDataNode([data_node], "project")
    g["resample_image"] = lambda data_node, shape: FunctionOperationDataNode([data_node, DataNode.make(shape)], "resample_image")
    g["histogram"] = lambda data_node, bins_node: FunctionOperationDataNode([data_node, DataNode.make(bins_node)], "histogram")
    g["line_profile"] = lambda data_node, vector_node, width_node: FunctionOperationDataNode([data_node, DataNode.make(vector_node), DataNode.make(width_node)], "line_profile")
    g["data_by_uuid"] = lambda data_uuid: data_by_uuid(context, data_uuid)
    g["region_by_uuid"] = lambda region_uuid: region_by_uuid(context, region_uuid)
    g["data_shape"] = lambda data_node: ScalarOperationDataNode([data_node], "data_shape")
    g["shape"] = lambda *args: ScalarOperationDataNode([DataNode.make(arg) for arg in args], "shape")
    g["rectangle_from_origin_size"] = lambda origin, size: ScalarOperationDataNode([DataNode.make(origin), DataNode.make(size)], "rectangle_from_origin_size")
    g["rectangle_from_center_size"] = lambda center, size: ScalarOperationDataNode([DataNode.make(center), DataNode.make(size)], "rectangle_from_center_size")
    g["vector"] = lambda start, end: ScalarOperationDataNode([DataNode.make(start), DataNode.make(end)], "vector")
    g["normalized_point"] = lambda y, x: ScalarOperationDataNode([DataNode.make(y), DataNode.make(x)], "normalized_point")
    g["normalized_size"] = lambda height, width: ScalarOperationDataNode([DataNode.make(height), DataNode.make(width)], "normalized_size")
    g["normalized_interval"] = lambda start, end: ScalarOperationDataNode([DataNode.make(start), DataNode.make(end)], "normalized_interval")
    l = dict()
    for variable_name, object_specifier in variable_map.items():
        if object_specifier["type"] == "data_item":
            reference_node = DataItemDataNode(object_specifier=object_specifier)
        elif object_specifier["type"] == "variable":
            reference_node = VariableDataNode(object_specifier=object_specifier)
        else:
            reference_node = ReferenceDataNode(object_specifier=object_specifier)
        g[variable_name] = reference_node
    g["newaxis"] = numpy.newaxis
    expression_lines = expression_lines[:-1] + ["result = {0}".format(expression_lines[-1]), ]
    code_lines.extend(expression_lines)
    code = "\n".join(code_lines)
    try:
        exec(code, g, l)
    except Exception as e:
        return None, str(e)
    return l["result"], None


class ComputationVariable(Observable.Observable, Persistence.PersistentObject):
    def __init__(self, name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None):  # defaults are None for factory
        super(ComputationVariable, self).__init__()
        self.define_type("variable")
        self.define_property("name", name, changed=self.__property_changed)
        self.define_property("label", name, changed=self.__property_changed)
        self.define_property("value_type", value_type, changed=self.__property_changed)
        self.define_property("value", value, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("value_default", value_default, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("value_min", value_min, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("value_max", value_max, changed=self.__property_changed, reader=self.__value_reader, writer=self.__value_writer)
        self.define_property("specifier", specifier, changed=self.__property_changed)
        self.define_property("control_type", control_type, changed=self.__property_changed)
        self.variable_type_changed_event = Event.Event()

    def read_from_dict(self, properties: dict) -> None:
        # ensure that value_type is read first
        value_type_property = self._get_persistent_property("value_type")
        value_type_property.read_from_dict(properties)
        super(ComputationVariable, self).read_from_dict(properties)

    def write_to_dict(self) -> dict:
        return super(ComputationVariable, self).write_to_dict()

    def __value_reader(self, persistent_property, properties):
        value_type = self.value_type
        raw_value = properties.get(persistent_property.key)
        if raw_value is not None:
            if value_type == "boolean":
                return bool(raw_value)
            elif value_type == "integral":
                return int(raw_value)
            elif value_type == "real":
                return float(raw_value)
            elif value_type == "complex":
                return complex(*raw_value)
            elif value_type == "string":
                return str(raw_value)
        return None

    def __value_writer(self, persistent_property, properties, value):
        value_type = self.value_type
        if value is not None:
            if value_type == "boolean":
                properties[persistent_property.key] = bool(value)
            if value_type == "integral":
                properties[persistent_property.key] = int(value)
            if value_type == "real":
                properties[persistent_property.key] = float(value)
            if value_type == "complex":
                properties[persistent_property.key] = complex(value).real, complex(value).imag
            if value_type == "string":
                properties[persistent_property.key] = str(value)

    @property
    def variable_specifier(self) -> dict:
        return {"type": "variable", "version": 1, "uuid": str(self.uuid)}

    @property
    def bound_variable(self):
        class BoundVariable(object):
            def __init__(self, variable):
                self.__variable = variable
                self.changed_event = Event.Event()
                def property_changed(key, value):
                    if key == "value":
                        self.changed_event.fire()
                self.__variable_property_changed_listener = variable.property_changed_event.listen(property_changed)
            @property
            def value(self):
                return self.__variable.value
            def close(self):
                self.__variable_property_changed_listener.close()
                self.__variable_property_changed_listener = None
        return BoundVariable(self)

    def __property_changed(self, name, value):
        self.notify_set_property(name, value)
        if name in ["name", "label"]:
            self.notify_set_property("display_label", self.display_label)

    def control_type_default(self, value_type: str) -> None:
        mapping = {"boolean": "checkbox", "integral": "slider", "real": "field", "complex": "field", "string": "field"}
        return mapping.get(value_type)

    @property
    def variable_type(self) -> str:
        if self.value_type is not None:
            return self.value_type
        elif self.specifier is not None:
            return self.specifier.get("type")
        return None

    @variable_type.setter
    def variable_type(self, value_type: str) -> None:
        if value_type != self.variable_type:
            if value_type in ("boolean", "integral", "real", "complex", "string"):
                self.specifier = None
                self.value_type = value_type
                self.control_type = self.control_type_default(value_type)
                if value_type == "boolean":
                    self.value_default = True
                elif value_type == "integral":
                    self.value_default = 0
                elif value_type == "real":
                    self.value_default = 0.0
                elif value_type == "complex":
                    self.value_default = 0 + 0j
                else:
                    self.value_default = None
                self.value_min = None
                self.value_max = None
            elif value_type in ("data_item", "region"):
                self.value_type = None
                self.control_type = None
                self.value_default = None
                self.value_min = None
                self.value_max = None
                self.specifier = {"type": value_type, "version": 1}
            self.variable_type_changed_event.fire()

    @property
    def display_label(self):
        return self.label or self.name

    @property
    def has_range(self):
        return self.value_type is not None and self.value_min is not None and self.value_max is not None


def variable_factory(lookup_id):
    build_map = {
        "variable": ComputationVariable,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None


class ComputationContext(object):
    def __init__(self, computation, context):
        self.__computation = computation
        self.__context = context

    def get_data_item_specifier(self, data_item_uuid):
        """Supports data item lookup by uuid."""
        return self.__context.get_object_specifier(self.__context.get_data_item_by_uuid(data_item_uuid))

    def get_region_specifier(self, region_uuid):
        """Supports region lookup by uuid."""
        for data_item in self.__context.data_items:
            for data_source in data_item.data_sources:
                for region in data_source.regions:
                    if region.uuid == region_uuid:
                        return self.__context.get_object_specifier(region)
        return None

    def resolve_object_specifier(self, object_specifier, property_name=None):
        """Resolve the object specifier, returning a bound variable.

        Ask the computation for the variable associated with the object specifier. If it doesn't exist, let the
        enclosing context handle it. Otherwise, check to see if the variable directly includes a value (i.e. has no
        specifier). If so, let the variable return the bound variable directly. Otherwise (again) let the enclosing
        context resolve, but use the specifier in the variable.

        Structuring this method this way allows the variable to provide a second level of indirection. The computation
        can store variable specifiers only. The variable specifiers can hold values directly or specifiers to the
        enclosing context. This isolates the computation further from the enclosing context.
        """
        variable = self.__computation.resolve_variable(object_specifier)
        if not variable:
            return self.__context.resolve_object_specifier(object_specifier, property_name)
        elif variable.specifier is None:
            return variable.bound_variable
        else:
            # BoundVariable is used here to watch for changes to the variable in addition to watching for changes
            # to the context of the variable. Fire changed_event for either type of change.
            class BoundVariable:
                def __init__(self, variable, context, property_name):
                    self.__bound_object_changed_listener = None
                    self.__variable = variable
                    self.changed_event = Event.Event()
                    def update_bound_object():
                        if self.__bound_object_changed_listener:
                            self.__bound_object_changed_listener.close()
                            self.__bound_object_changed_listener = None
                        self.__bound_object = context.resolve_object_specifier(self.__variable.specifier, property_name)
                        if self.__bound_object:
                            def bound_object_changed():
                                self.changed_event.fire()
                            self.__bound_object_changed_listener = self.__bound_object.changed_event.listen(bound_object_changed)
                    def property_changed(key, value):
                        if key == "specifier":
                            update_bound_object()
                            self.changed_event.fire()
                    self.__variable_property_changed_listener = variable.property_changed_event.listen(property_changed)
                    update_bound_object()
                @property
                def value(self):
                    return self.__bound_object.value if self.__bound_object else None
                def close(self):
                    self.__variable_property_changed_listener.close()
                    self.__variable_property_changed_listener = None
                    if self.__bound_object_changed_listener:
                        self.__bound_object_changed_listener.close()
                        self.__bound_object_changed_listener = None
            return BoundVariable(variable, self.__context, property_name)


class Computation(Observable.Observable, Persistence.PersistentObject):
    """A computation on data and other inputs using symbolic nodes.

    Watches for changes to the sources and fires a needs_update_event
    when a new computation needs to occur.

    Call parse_expression first to establish the computation. Bind will be automatically called.

    Call bind to establish connections after reloading. Call unbind to release connections.

    Listen to needs_update_event and call evaluate in response to perform
    computation (on thread).

    The computation will listen to any bound items established in the bind method. When those
    items signal a change, the needs_update_event will be fired.
    """

    def __init__(self):
        super(Computation, self).__init__()
        self.define_type("computation")
        self.define_property("node")
        self.define_property("original_expression")
        self.define_property("error_text")
        self.define_property("label", changed=self.__label_changed)
        self.define_relationship("variables", variable_factory)
        self.__bound_items = dict()
        self.__bound_item_listeners = dict()
        self.__data_node = None
        self.__evaluate_lock = threading.RLock()
        self.__evaluating = False
        self.needs_update = False
        self.needs_update_event = Event.Event()
        self.computation_mutated_event = Event.Event()
        self.variable_inserted_event = Event.Event()
        self.variable_removed_event = Event.Event()
        self._evaluation_count_for_test = 0

    def deepcopy_from(self, item, memo):
        super(Computation, self).deepcopy_from(item, memo)
        self.__data_node = DataNode.factory(self.node)

    @property
    def _data_node_for_test(self):
        return self.__data_node

    def read_from_dict(self, properties):
        super(Computation, self).read_from_dict(properties)
        self.__data_node = DataNode.factory(self.node)

    def __label_changed(self, name, value):
        self.notify_set_property(name, value)
        self.computation_mutated_event.fire()

    def add_variable(self, variable: ComputationVariable) -> None:
        count = self.item_count("variables")
        self.append_item("variables", variable)
        self.variable_inserted_event.fire(count, variable)
        self.computation_mutated_event.fire()

    def remove_variable(self, variable: ComputationVariable) -> None:
        index = self.item_index("variables", variable)
        self.remove_item("variables", variable)
        self.variable_removed_event.fire(index, variable)
        self.computation_mutated_event.fire()

    def create_variable(self, name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None) -> ComputationVariable:
        variable = ComputationVariable(name, value_type, value, value_default, value_min, value_max, control_type, specifier)
        self.add_variable(variable)
        return variable

    def create_object(self, name: str, object_specifier: dict) -> ComputationVariable:
        variable = ComputationVariable(name, specifier=object_specifier)
        self.add_variable(variable)
        return variable

    def resolve_variable(self, object_specifier: dict) -> ComputationVariable:
        uuid_str = object_specifier.get("uuid")
        uuid_ = uuid.UUID(uuid_str) if uuid_str else None
        if uuid_:
            for variable in self.variables:
                if variable.uuid == uuid_:
                    return variable
        return None

    def parse_expression(self, context, expression, variable_map):
        self.unbind()
        old_data_node = copy.deepcopy(self.__data_node)
        old_error_text = self.error_text
        self.original_expression = expression
        computation_context = ComputationContext(self, context)
        computation_variable_map = copy.copy(variable_map)
        for variable in self.variables:
            computation_variable_map[variable.name] = variable.variable_specifier
        self.__data_node, self.error_text = parse_expression(expression.split("\n"), computation_variable_map, computation_context)
        if self.__data_node:
            self.node = self.__data_node.write()
            self.bind(context)
        if self.__data_node != old_data_node or old_error_text != self.error_text:
            self.needs_update = True
            self.needs_update_event.fire()
            self.computation_mutated_event.fire()

    def begin_evaluate(self):
        with self.__evaluate_lock:
            evaluating = self.__evaluating
            self.__evaluating = True
            return not evaluating

    def end_evaluate(self):
        self.__evaluating = False

    def evaluate(self):
        """Evaluate the computation and return data and metadata."""
        self._evaluation_count_for_test += 1
        def resolve(uuid):
            bound_item = self.__bound_items[uuid]
            return bound_item.value
        result = None
        if self.__data_node:
            result = self.__data_node.evaluate(resolve)
        self.needs_update = False
        return result

    def bind(self, context) -> None:
        """Ask the data node for all bound items, then watch each for changes."""

        # make a computation context based on the enclosing context.
        computation_context = ComputationContext(self, context)

        # normally I would think re-bind should not be valid; but for testing, the expression
        # is often evaluated and bound. it also needs to be bound a new data item is added to a document
        # model. so special case to see if it already exists. this may prove troublesome down the road.
        if len(self.__bound_items) == 0:  # check if already bound
            if self.__data_node:  # error condition
                self.__data_node.bind(computation_context, self.__bound_items)

                def needs_update():
                    self.needs_update = True
                    self.needs_update_event.fire()

                for bound_item_uuid, bound_item in self.__bound_items.items():
                    self.__bound_item_listeners[bound_item_uuid] = bound_item.changed_event.listen(needs_update)

    def unbind(self):
        """Unlisten and close each bound item."""
        for bound_item, bound_item_listener in zip(self.__bound_items.values(), self.__bound_item_listeners.values()):
            bound_item.close()
            bound_item_listener.close()
        self.__bound_items = dict()
        self.__bound_item_listeners = dict()

    def __get_object_specifier_expression(self, specifier):
        if specifier.get("version") == 1:
            specifier_type = specifier["type"]
            if specifier_type == "data_item":
                object_uuid = uuid.UUID(specifier["uuid"])
                return "data_by_uuid(uuid.UUID('{0}'))".format(object_uuid)
            elif specifier_type == "region":
                object_uuid = uuid.UUID(specifier["uuid"])
                return "region_by_uuid(uuid.UUID('{0}'))".format(object_uuid)
        return None

    def reconstruct(self, variable_map):
        if self.__data_node:
            lines = list()
            # construct the variable map, which maps variables used in the text expression
            # to specifiers that can be resolved to specific objects and values.
            computation_variable_map = copy.copy(variable_map)
            for variable in self.variables:
                computation_variable_map[variable.name] = variable.variable_specifier
            variable_map_copy = copy.deepcopy(computation_variable_map)
            expression, precedence = self.__data_node.reconstruct(variable_map_copy)
            for variable, object_specifier in variable_map_copy.items():
                if not variable in computation_variable_map:
                    lines.append("{0} = {1}".format(variable, self.__get_object_specifier_expression(object_specifier)))
            lines.append(expression)
            return "\n".join(lines)
        return None
