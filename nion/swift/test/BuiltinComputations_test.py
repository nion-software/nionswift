"""Tests for the built-in window/FFT computation executors.

These exercise `builtin_computations.py` executors directly against the real
`Symbolic.ComputationParameters` (the same class used by
`_ComputationAPIV1ExecutorHandler` in production), rather than a full
`DocumentModel`/computation round trip, so that the window-generation/fusion
logic (and its input validation) is covered independently of
document/persistence machinery while still exercising the real parameter
type-checking and default-handling behavior.
"""

import typing
import unittest

import numpy

from nion.data import annotated_array
from nion.swift.model import builtin_computations
from nion.swift.model import Symbolic


def _parameters(values: typing.Mapping[str, typing.Any]) -> Symbolic.ComputationParameters:
    """Build a real `Symbolic.ComputationParameters` from plain values."""
    return Symbolic.ComputationParameters({key: Symbolic.ComputationParameter(value) for key, value in values.items()})


def _make_1d_source(data: numpy.ndarray) -> annotated_array.AnnotatedArray:
    value_type = annotated_array.infer_value_type(data.dtype)
    axis_group = annotated_array.AxisGroup.from_1d_size(data.shape[0])
    descriptor = annotated_array.ArrayDescriptor((axis_group,), value_type=value_type)
    return annotated_array.AnnotatedArray(data=data, descriptor=descriptor)


class TestWindowExecutorFusion(unittest.TestCase):

    def test_hamming_window_executor_multiplies_known_window_into_real_source(self) -> None:
        """The executor's result must equal the source multiplied by the standalone generated window."""
        source = _make_1d_source(numpy.full(16, 2.0))
        parameters = _parameters({"src": source})
        result = builtin_computations.HammingWindowExecutor().execute(parameters)["target"]
        axis_group = source.descriptor.axis_groups[0]
        expected_window = annotated_array.hamming_window(axis_group)
        numpy.testing.assert_allclose(numpy.asarray(result.data), 2.0 * numpy.asarray(expected_window.data))
        self.assertEqual(result.descriptor.value_type, annotated_array.ValueType.SCALAR)

    def test_gaussian_window_executor_accepts_complex_source_and_preserves_complex_dtype(self) -> None:
        """A complex (e.g. post-FFT) source must remain complex after windowing, scaled by a real window."""
        data = numpy.full(16, 1 + 2j)
        source = _make_1d_source(data)
        parameters = _parameters({"src": source, "sigma": 0.3})
        result = builtin_computations.GaussianWindowExecutor().execute(parameters)["target"]
        self.assertTrue(numpy.iscomplexobj(result.data))
        self.assertEqual(result.descriptor.value_type, annotated_array.ValueType.COMPLEX)
        axis_group = source.descriptor.axis_groups[0]
        expected_window = annotated_array.gaussian_window(axis_group, 0.3)
        numpy.testing.assert_allclose(numpy.asarray(result.data), data * numpy.asarray(expected_window.data))

    def test_gaussian_window_executor_uses_default_sigma_when_omitted(self) -> None:
        """Omitting `sigma` entirely must fall back to the executor's documented default (0.3), not raise."""
        source = _make_1d_source(numpy.full(16, 2.0))
        parameters = _parameters({"src": source})
        result = builtin_computations.GaussianWindowExecutor().execute(parameters)["target"]
        axis_group = source.descriptor.axis_groups[0]
        expected_window = annotated_array.gaussian_window(axis_group, 0.3)
        numpy.testing.assert_allclose(numpy.asarray(result.data), 2.0 * numpy.asarray(expected_window.data))

    def test_hann_window_executor_rejects_rgba_source(self) -> None:
        """An RGBA source is not a meaningful windowing target and must be rejected."""
        rgba_dtype = numpy.dtype([("r", numpy.uint8), ("g", numpy.uint8), ("b", numpy.uint8), ("a", numpy.uint8)])
        data = numpy.zeros((16, 16), dtype=rgba_dtype)
        axis_group = annotated_array.AxisGroup.from_2d_size((16, 16))
        descriptor = annotated_array.ArrayDescriptor((axis_group,), value_type=annotated_array.ValueType.RGBA)
        source = annotated_array.AnnotatedArray(data=data, descriptor=descriptor)
        parameters = _parameters({"src": source})
        with self.assertRaises(ValueError):
            builtin_computations.HannWindowExecutor().execute(parameters)

    def test_gaussian_window_executor_rejects_source_with_multiple_axis_groups(self) -> None:
        """A source with more than one axis group (e.g. a navigation + signal group) must be rejected."""
        from nion.data.annotated_array._implementation import Axis
        navigation_group = annotated_array.AxisGroup(axes=(Axis("n", 4),))
        signal_group = annotated_array.AxisGroup(axes=(Axis("x", 8),))
        descriptor = annotated_array.ArrayDescriptor((navigation_group, signal_group))
        source = annotated_array.AnnotatedArray(data=numpy.zeros((4, 8)), descriptor=descriptor)
        parameters = _parameters({"src": source, "sigma": 0.3})
        with self.assertRaises(ValueError):
            builtin_computations.GaussianWindowExecutor().execute(parameters)


if __name__ == "__main__":
    unittest.main()
