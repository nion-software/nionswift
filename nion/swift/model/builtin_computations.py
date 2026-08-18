"""Built-in host-side computations.

This module intentionally lives on the nionswift side of the boundary: it
registers concrete executors for built-in operations, but it does not define
or extend the computation API itself.
"""

from __future__ import annotations

import typing

from nion.data.annotated_array import primitives
from nion.swift.model.computation_api import v1 as computation_api


class FFTExecutor(computation_api.Executor):
    """Execute the built-in FFT computation."""

    def execute(self, parameters: computation_api.Parameters) -> typing.Mapping[str, typing.Any]:
        source = parameters.get_annotated_array("src")
        return {"target": primitives.fft(source)}


_definitions_registered = False


def register_builtin_computations() -> None:
    """Register all built-in host-side computation executors."""
    global _definitions_registered
    if _definitions_registered:
        return
    computation_api.get_api().register_executor("fft", FFTExecutor())
    _definitions_registered = True


__all__ = ["FFTExecutor", "register_builtin_computations"]
