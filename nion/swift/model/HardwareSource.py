"""Deprecated. Hardware source has been moved to nionswift-instrumentation-kit.

For backwards compatibility, a few functions are provided until all packages can be migrated to
the new API available in nionswift-instrumentation-kit.
"""
import contextlib
import typing

import numpy.typing

from nion.data import DataAndMetadata
from nion.utils import Registry

_NDArray = numpy.typing.NDArray[typing.Any]
FrameParametersDictType = typing.Dict[str, typing.Any]


class ViewTaskLike(typing.Protocol):
    def close(self) -> None: ...
    def grab_immediate(self) -> typing.Sequence[DataAndMetadata.DataAndMetadata]: ...
    def grab_next_to_finish(self) -> typing.Sequence[DataAndMetadata.DataAndMetadata]: ...
    def grab_next_to_start(self) -> typing.Sequence[DataAndMetadata.DataAndMetadata]: ...
    def grab_earliest(self) -> typing.Sequence[DataAndMetadata.DataAndMetadata]: ...


class FrameParametersLike(typing.Protocol):
    def as_dict(self) -> FrameParametersDictType: ...


class RecordTaskLike(typing.Protocol):

    @property
    def is_started(self) -> bool:
        raise NotImplementedError()

    @property
    def is_finished(self) -> bool:
        raise NotImplementedError()

    def wait_started(self, *, timeout: typing.Optional[float] = None) -> None:
        raise NotImplementedError()

    def wait_finished(self, *, timeout: typing.Optional[float] = None) -> None:
        raise NotImplementedError()

    def grab_xdatas(self, *, timeout: typing.Optional[float] = None) -> typing.Sequence[typing.Optional[DataAndMetadata.DataAndMetadata]]:
        raise NotImplementedError()


class HardwareSourceLike(typing.Protocol):
    @property
    def hardware_source_id(self) -> str: raise NotImplementedError()

    @property
    def selected_profile_index(self) -> int: raise NotImplementedError()

    @property
    def is_playing(self) -> bool: raise NotImplementedError()

    @property
    def is_recording(self) -> bool: raise NotImplementedError()

    def get_record_frame_parameters(self) -> FrameParametersLike: ...
    def set_record_frame_parameters(self, frame_parameters: FrameParametersLike) -> None: ...
    def get_current_frame_parameters(self) -> FrameParametersLike: ...
    def set_current_frame_parameters(self, frame_parameters: FrameParametersLike) -> None: ...
    def get_frame_parameters(self, index: int) -> FrameParametersLike: ...
    def set_frame_parameters(self, index: int, frame_parameters: FrameParametersLike) -> None: ...
    def get_frame_parameters_from_dict(self, d: typing.Mapping[str, typing.Any]) -> FrameParametersLike: ...
    def set_channel_enabled(self, channel_index: int, enabled: bool) -> bool: ...
    def start_playing(self) -> None: ...
    def abort_playing(self) -> None: ...
    def stop_playing(self) -> None: ...
    def start_recording(self) -> RecordTaskLike: ...
    def abort_recording(self) -> None: ...
    def get_next_xdatas_to_finish(self, timeout: typing.Optional[float] = None) -> typing.Sequence[typing.Optional[DataAndMetadata.DataAndMetadata]]: ...
    def get_next_xdatas_to_start(self, timeout: typing.Optional[float] = None) -> typing.Sequence[typing.Optional[DataAndMetadata.DataAndMetadata]]: ...
    def create_view_task(self, frame_parameters: typing.Optional[FrameParametersLike] = None, channels_enabled: typing.Optional[typing.Sequence[bool]] = None, buffer_size: int = 1) -> ViewTaskLike: ...
    def set_selected_profile_index(self, index: int) -> None: ...
    def get_property(self, name: str) -> typing.Any: ...
    def set_property(self, name: str, value: typing.Any) -> None: ...


class InstrumentLike(typing.Protocol):
    @property
    def instrument_id(self) -> str: raise NotImplementedError()

    def set_control_output(self, name: str, value: typing.Any, options: typing.Optional[typing.Mapping[str, typing.Any]] = None) -> None: ...
    def get_control_output(self, name: str) -> float: ...
    def get_control_state(self, name: str) -> str: ...
    def get_property(self, name: str) -> typing.Any: ...
    def set_property(self, name: str, value: typing.Any) -> None: ...


class HardwareSourceManagerInterface(typing.Protocol):
    def register_hardware_source(self, hardware_source: HardwareSourceLike) -> None: ...
    def get_all_instrument_ids(self) -> typing.List[str]: ...
    def get_all_hardware_source_ids(self) -> typing.List[str]: ...
    def get_instrument_by_id(self, instrument_id: str) -> InstrumentLike: ...
    def get_hardware_source_for_hardware_source_id(self, hardware_source_id: str) -> typing.Optional[HardwareSourceLike]: ...
    def make_delegate_hardware_source(self, delegate: typing.Any, hardware_source_id: str, hardware_source_name: str) -> HardwareSourceLike: ...


def hardware_source_manager() -> HardwareSourceManagerInterface:
    return typing.cast(HardwareSourceManagerInterface, Registry.get_component("hardware_source_manager"))


def HardwareSourceManager() -> HardwareSourceManagerInterface:
    return hardware_source_manager()


@contextlib.contextmanager
def get_data_generator_by_id(hardware_source_id: str, sync: bool = True) -> typing.Any:
    """Return a generator for data.

    :param bool sync: whether to wait for current frame to finish then collect next frame

    NOTE: a new ndarray is created for each call.
    """
    hardware_source = HardwareSourceManager().get_hardware_source_for_hardware_source_id(hardware_source_id)
    assert hardware_source

    def get_last_data() -> _NDArray:
        assert hardware_source
        xdata0 = hardware_source.get_next_xdatas_to_finish()[0]
        data = xdata0.data if xdata0 else None
        assert data is not None
        return data.copy()

    yield get_last_data
