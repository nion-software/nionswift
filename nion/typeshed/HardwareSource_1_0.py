import datetime
import numpy
import typing
import uuid
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.utils import Geometry


class RecordTask:

    def cancel(self) -> None:
        ...

    def close(self) -> None:
        """Close the task.

        .. versionadded:: 1.0


        This method must be called when the task is no longer needed.
        """
        ...

    def grab(self) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab list of data/metadata from the task.

        .. versionadded:: 1.0

        This method will wait until the task finishes.

        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`
        """
        ...

    @property
    def is_finished(self) -> bool:
        """Return a boolean indicating whether the task is finished.

        .. versionadded:: 1.0
        """
        ...


class ViewTask:

    def close(self) -> None:
        """Close the task.

        .. versionadded:: 1.0

        This method must be called when the task is no longer needed.
        """
        ...

    def grab_earliest(self) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab list of data/metadata from the task.

        .. versionadded:: 1.0

        This method will return the earliest item in the buffer or wait for the next one to finish.

        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`
        """
        ...

    def grab_immediate(self) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab list of data/metadata from the task.

        .. versionadded:: 1.0

        This method will return immediately if data is available.

        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`
        """
        ...

    def grab_next_to_finish(self) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab list of data/metadata from the task.

        .. versionadded:: 1.0

        This method will wait until the current frame completes.

        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`
        """
        ...

    def grab_next_to_start(self) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab list of data/metadata from the task.

        .. versionadded:: 1.0

        This method will wait until the current frame completes and the next one finishes.

        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`
        """
        ...


class HardwareSource:

    def abort_playing(self) -> None:
        ...

    def abort_recording(self) -> None:
        ...

    def close(self) -> None:
        ...

    def create_record_task(self, frame_parameters: dict=None, channels_enabled: typing.List[bool]=None) -> RecordTask:
        """Create a record task for this hardware source.

        .. versionadded:: 1.0

        :param frame_parameters: The frame parameters for the record. Pass None for defaults.
        :type frame_parameters: :py:class:`FrameParameters`
        :param channels_enabled: The enabled channels for the record. Pass None for defaults.
        :type channels_enabled: List of booleans.
        :return: The :py:class:`RecordTask` object.
        :rtype: :py:class:`RecordTask`

        Callers should call close on the returned task when finished.

        See :py:class:`RecordTask` for examples of how to use.
        """
        ...

    def create_view_task(self, frame_parameters: dict=None, channels_enabled: typing.List[bool]=None, buffer_size: int=1) -> ViewTask:
        """Create a view task for this hardware source.

        .. versionadded:: 1.0

        :param frame_parameters: The frame parameters for the view. Pass None for defaults.
        :type frame_parameters: :py:class:`FrameParameters`
        :param channels_enabled: The enabled channels for the view. Pass None for defaults.
        :type channels_enabled: List of booleans.
        :param buffer_size: The buffer size if using the grab_earliest method. Default is 1.
        :type buffer_size: int
        :return: The :py:class:`ViewTask` object.
        :rtype: :py:class:`ViewTask`

        Callers should call close on the returned task when finished.

        See :py:class:`ViewTask` for examples of how to use.
        """
        ...

    def get_default_frame_parameters(self) -> dict:
        ...

    def get_frame_parameters(self) -> dict:
        ...

    def get_frame_parameters_for_profile_by_index(self, profile_index: int) -> dict:
        ...

    def get_property_as_bool(self, name):
        ...

    def get_property_as_float(self, name):
        ...

    def get_property_as_float_point(self, name):
        ...

    def get_property_as_int(self, name):
        ...

    def get_property_as_str(self, name):
        ...

    def grab_next_to_finish(self, timeout: float=None) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grabs the next frame to finish and returns it as data and metadata.

        .. versionadded:: 1.0

        :param timeout: The timeout in seconds. Pass None to use default.
        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`

        If the view is not already started, it will be started automatically.

        Scriptable: Yes
        """
        ...

    def grab_next_to_start(self, frame_parameters: dict=None, channels_enabled: typing.List[bool]=None, timeout: float=None) -> typing.List[DataAndMetadata.DataAndMetadata]:
        ...

    def record(self, frame_parameters: dict=None, channels_enabled: typing.List[bool]=None, timeout: float=None) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Record data and return a list of data_and_metadata objects.

        .. versionadded:: 1.0

        :param frame_parameters: The frame parameters for the record. Pass None for defaults.
        :type frame_parameters: :py:class:`FrameParameters`
        :param channels_enabled: The enabled channels for the record. Pass None for defaults.
        :type channels_enabled: List of booleans.
        :param timeout: The timeout in seconds. Pass None to use default.
        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`
        """
        ...

    def set_frame_parameters(self, frame_parameters: dict) -> None:
        ...

    def set_frame_parameters_for_profile_by_index(self, profile_index: int, frame_parameters: dict) -> None:
        ...

    def set_property_as_bool(self, name, value) -> None:
        ...

    def set_property_as_float(self, name, value) -> None:
        ...

    def set_property_as_float_point(self, name, value) -> None:
        ...

    def set_property_as_int(self, name, value) -> None:
        ...

    def set_property_as_str(self, name, value) -> None:
        ...

    def start_playing(self, frame_parameters: dict=None, channels_enabled: typing.List[bool]=None) -> None:
        ...

    def start_recording(self, frame_parameters: dict=None, channels_enabled: typing.List[bool]=None):
        ...

    def stop_playing(self) -> None:
        ...

    @property
    def is_playing(self) -> bool:
        ...

    @property
    def is_recording(self) -> bool:
        ...

    @property
    def profile_index(self) -> int:
        ...

    @profile_index.setter
    def profile_index(self, value: int) -> None:
        ...


class Instrument:
    """Represents an instrument with controls and properties.

    A control is part of a network of dependent properties where the output is the weighted sum of inputs with an added
    value.

    A property is a simple value with a specific type that can be set or read.

    The instrument class provides the ability to have temporary states where changes to the instrument are recorded and
    restored when finished. Calls to begin/end temporary state should be matched.

    The class also provides the ability to group a set of operations and have them be applied together. Calls to
    begin/end transaction should be matched.
    """

    def close(self) -> None:
        ...

    def get_control_output(self, name: str) -> float:
        """Return the value of a control.

        :return: The control value.

        Raises exception if control with name doesn't exist.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def get_control_state(self, name: str) -> str:
        ...

    def get_property_as_bool(self, name: str) -> bool:
        ...

    def get_property_as_float(self, name: str) -> float:
        """Return the value of a float property.

        :return: The property value (float).

        Raises exception if property with name doesn't exist.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def get_property_as_float_point(self, name: str) -> Geometry.FloatPoint:
        ...

    def get_property_as_int(self, name: str) -> int:
        ...

    def get_property_as_str(self, name: str) -> str:
        ...

    def set_control_output(self, name: str, value: float, *, options: dict=None) -> None:
        """Set the value of a control asynchronously.

        :param name: The name of the control (string).
        :param value: The control value (float).
        :param options: A dict of custom options to pass to the instrument for setting the value.

        Options are:
            value_type: local, delta, output. output is default.
            confirm, confirm_tolerance_factor, confirm_timeout: confirm value gets set.
            inform: True to keep dependent control outputs constant by adjusting their internal values. False is
            default.

        Default value of confirm is False.

        Default confirm_tolerance_factor is 1.0. A value of 1.0 is the nominal tolerance for that control. Passing a
        higher tolerance factor (for example 1.5) will increase the permitted error margin and passing lower tolerance
        factor (for example 0.5) will decrease the permitted error margin and consequently make a timeout more likely.
        The tolerance factor value 0.0 is a special value which removes all checking and only waits for any change at
        all and then returns.

        Default confirm_timeout is 16.0 (seconds).

        Raises exception if control with name doesn't exist.

        Raises TimeoutException if confirm is True and timeout occurs.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def set_property_as_bool(self, name: str, value: bool) -> None:
        ...

    def set_property_as_float(self, name: str, value: float) -> None:
        """Set the value of a float property.

        :param name: The name of the property (string).
        :param value: The property value (float).

        Raises exception if property with name doesn't exist.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def set_property_as_float_point(self, name: str, value: Geometry.FloatPoint) -> None:
        ...

    def set_property_as_int(self, name: str, value: int) -> None:
        ...

    def set_property_as_str(self, name: str, value: str) -> None:
        ...

version = "~1.0"
