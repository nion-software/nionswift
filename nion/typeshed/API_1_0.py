import datetime
import numpy
import typing
import uuid
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.utils import Geometry


class Graphic:

    def get_property(self, property: str):
        ...

    def mask_xdata_with_shape(self, shape: typing.Sequence[int]) -> DataAndMetadata.DataAndMetadata:
        """Return the mask created by this graphic as extended data.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def set_property(self, property: str, value) -> None:
        ...

    @property
    def angle(self) -> float:
        """Return the angle (radians) property."""
        ...

    @angle.setter
    def angle(self, value: float) -> None:
        """Set the angle (radians) property."""
        ...

    @property
    def bounds(self) -> typing.Tuple[typing.Tuple[float, float], typing.Tuple[float, float]]:
        """Return the bounds property in relative coordinates.

        Bounds is a tuple ((top, left), (height, width))"""
        ...

    @bounds.setter
    def bounds(self, value: typing.Tuple[typing.Tuple[float, float], typing.Tuple[float, float]]) -> None:
        """Set the bounds property in relative coordinates.

        Bounds is a tuple ((top, left), (height, width))"""
        ...

    @property
    def center(self) -> typing.Tuple[float, float]:
        """Return the center property in relative coordinates.

        Center is a tuple (y, x)."""
        ...

    @center.setter
    def center(self, value) -> None:
        """Set the center in relative coordinates.

        Center is a tuple (y, x)."""
        ...

    @property
    def end(self) -> typing.Union[float, typing.Tuple[float, float]]:
        """Return the end property in relative coordinates.

        End may be a float when graphic is an Interval or a tuple (y, x) when graphic is a Line."""
        ...

    @end.setter
    def end(self, value: typing.Union[float, typing.Tuple[float, float]]) -> None:
        """Set the end property in relative coordinates.

        End may be a float when graphic is an Interval or a tuple (y, x) when graphic is a Line."""
        ...

    @property
    def graphic_id(self) -> str:
        """Return the graphic identifier.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @graphic_id.setter
    def graphic_id(self, value: str) -> None:
        """Set the graphic identifier.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def graphic_type(self) -> str:
        """Return the type of this graphic.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def interval(self) -> typing.Tuple[float, float]:
        """Return the interval property in relative coordinates.

        Interval is a tuple of floats (start, end)."""
        ...

    @interval.setter
    def interval(self, value: typing.Tuple[float, float]) -> None:
        """Set the interval property in relative coordinates.

        Interval is a tuple of floats (start, end)."""
        ...

    @property
    def label(self) -> str:
        """Return the graphic label.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @label.setter
    def label(self, value: str) -> None:
        """Set the graphic label.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def position(self) -> typing.Tuple[float, float]:
        """Return the position property in relative coordinates.

        Position is a tuple of floats (y, x)."""
        ...

    @position.setter
    def position(self, value: typing.Tuple[float, float]) -> None:
        """Set the position property in relative coordinates.

        Position is a tuple of floats (y, x)."""
        ...

    @property
    def region(self) -> "Graphic":
        ...

    @property
    def size(self) -> typing.Tuple[float, float]:
        """Return the size property in relative coordinates.

        Size is a tuple of floats (height, width)."""
        ...

    @size.setter
    def size(self, value: typing.Tuple[float, float]) -> None:
        """Set the size property in relative coordinates.

        Size is a tuple of floats (height, width)."""
        ...

    @property
    def start(self) -> typing.Union[float, typing.Tuple[float, float]]:
        """Return the start property in relative coordinates.

        Start may be a float when graphic is an Interval or a tuple (y, x) when graphic is a Line."""
        ...

    @start.setter
    def start(self, value: typing.Union[float, typing.Tuple[float, float]]) -> None:
        """Set the end property in relative coordinates.

        End may be a float when graphic is an Interval or a tuple (y, x) when graphic is a Line."""
        ...

    @property
    def type(self) -> str:
        """Return the region type property.

        The region type is different from the preferred 'graphic_type' in that it is backwards compatible with older versions.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def uuid(self) -> uuid.UUID:
        """Return the uuid of this object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def vector(self) -> typing.Tuple[typing.Tuple[float, float], typing.Tuple[float, float]]:
        """Return the vector property in relative coordinates.

        Vector will be a tuple of tuples ((y_start, x_start), (y_end, x_end))."""
        ...

    @vector.setter
    def vector(self, value: typing.Tuple[typing.Tuple[float, float], typing.Tuple[float, float]]) -> None:
        """Set the vector property in relative coordinates.

        Vector will be a tuple of tuples ((y_start, x_start), (y_end, x_end))."""
        ...


class DataItem:

    def add_channel_region(self, position: float) -> Graphic:
        ...

    def add_ellipse_region(self, center_y: float, center_x: float, height: float, width: float) -> Graphic:
        ...

    def add_interval_region(self, start: float, end: float) -> Graphic:
        ...

    def add_line_region(self, start_y: float, start_x: float, end_y: float, end_x: float) -> Graphic:
        ...

    def add_point_region(self, y: float, x: float) -> Graphic:
        """Add a point graphic to the data item.

        :param x: The x coordinate, in relative units [0.0, 1.0]
        :param y: The y coordinate, in relative units [0.0, 1.0]
        :return: The :py:class:`nion.swift.Facade.Graphic` object that was added.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def add_rectangle_region(self, center_y: float, center_x: float, height: float, width: float) -> Graphic:
        ...

    def delete_metadata_value(self, key: str) -> None:
        """Delete the metadata value for the given key.

        There are a set of predefined keys that, when used, will be type checked and be interoperable with other
        applications. Please consult reference documentation for valid keys.

        If using a custom key, we recommend structuring your keys in the '<dotted>.<group>.<attribute>' format followed
        by the predefined keys. e.g. 'stem.session.instrument' or 'stm.camera.binning'.

        Also note that some predefined keys map to the metadata ``dict`` but others do not. For this reason, prefer
        using the ``metadata_value`` methods over directly accessing ``metadata``.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def get_metadata_value(self, key: str) -> typing.Any:
        """Get the metadata value for the given key.

        There are a set of predefined keys that, when used, will be type checked and be interoperable with other
        applications. Please consult reference documentation for valid keys.

        If using a custom key, we recommend structuring your keys in the '<group>.<attribute>' format followed
        by the predefined keys. e.g. 'session.instrument' or 'camera.binning'.

        Also note that some predefined keys map to the metadata ``dict`` but others do not. For this reason, prefer
        using the ``metadata_value`` methods over directly accessing ``metadata``.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def has_metadata_value(self, key: str) -> bool:
        """Return whether the metadata value for the given key exists.

        There are a set of predefined keys that, when used, will be type checked and be interoperable with other
        applications. Please consult reference documentation for valid keys.

        If using a custom key, we recommend structuring your keys in the '<group>.<attribute>' format followed
        by the predefined keys. e.g. 'session.instrument' or 'camera.binning'.

        Also note that some predefined keys map to the metadata ``dict`` but others do not. For this reason, prefer
        using the ``metadata_value`` methods over directly accessing ``metadata``.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def mask_xdata(self) -> DataAndMetadata.DataAndMetadata:
        """Return the mask by combining any mask graphics on this data item as extended data.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def remove_region(self, graphic: Graphic) -> None:
        ...

    def set_data(self, data: numpy.ndarray) -> None:
        """Set the data.

        :param data: A numpy ndarray.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def set_data_and_metadata(self, data_and_metadata: DataAndMetadata.DataAndMetadata) -> None:
        """Set the data and metadata.

        :param data_and_metadata: The data and metadata.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def set_dimensional_calibrations(self, dimensional_calibrations: typing.List[Calibration.Calibration]) -> None:
        """Set the dimensional calibrations.

        :param dimensional_calibrations: A list of calibrations, must match the dimensions of the data.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def set_intensity_calibration(self, intensity_calibration: Calibration.Calibration) -> None:
        """Set the intensity calibration.

        :param intensity_calibration: The intensity calibration.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def set_metadata(self, metadata: dict) -> None:
        """Set the metadata dict.

        :param metadata: The metadata dict.

        The metadata dict must be convertible to JSON, e.g. ``json.dumps(metadata)`` must succeed.

        For best future compatibility, prefer using the ``get_metadata_value`` and ``set_metadata_value`` methods over
        directly accessing ``metadata``.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def set_metadata_value(self, key: str, value: typing.Any) -> None:
        """Set the metadata value for the given key.

        There are a set of predefined keys that, when used, will be type checked and be interoperable with other
        applications. Please consult reference documentation for valid keys.

        If using a custom key, we recommend structuring your keys in the '<group>.<attribute>' format followed
        by the predefined keys. e.g. 'session.instrument' or 'camera.binning'.

        Also note that some predefined keys map to the metadata ``dict`` but others do not. For this reason, prefer
        using the ``metadata_value`` methods over directly accessing ``metadata``.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def created(self) -> datetime.datetime:
        """Return the created timestamp (UTC) as a datetime object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def data(self) -> numpy.ndarray:
        """Return the data as a numpy ndarray.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @data.setter
    def data(self, value: numpy.ndarray) -> None:
        """Set the data.

        :param data: A numpy ndarray.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def data_and_metadata(self) -> DataAndMetadata.DataAndMetadata:
        """Return the extended data.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:attr:`~nion.swift.Facade.DataItem.xdata` instead.

        Scriptable: Yes
        """
        ...

    @property
    def dimensional_calibrations(self) -> typing.List[Calibration.Calibration]:
        """Return a copy of the list of dimensional calibrations.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def display(self) -> "Display":
        ...

    @property
    def display_xdata(self) -> DataAndMetadata.DataAndMetadata:
        """Return the extended data of this data item display.

        Display data will always be 1d or 2d and either int, float, or RGB data type.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def graphics(self) -> typing.List[Graphic]:
        """Return the graphics attached to this data item.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def intensity_calibration(self) -> Calibration.Calibration:
        """Return a copy of the intensity calibration.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def metadata(self) -> dict:
        """Return a copy of the metadata as a dict.

        For best future compatibility, prefer using the ``get_metadata_value`` and ``set_metadata_value`` methods over
        directly accessing ``metadata``.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def modified(self) -> datetime.datetime:
        """Return the modified timestamp (UTC) as a datetime object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def regions(self) -> typing.List[Graphic]:
        """Return the graphics attached to this data item.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:attr:`~nion.swift.Facade.DataItem.graphics` instead.

        Scriptable: Yes
        """
        ...

    @property
    def title(self) -> str:
        """Return the title as a string.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @title.setter
    def title(self, value: str) -> None:
        """Set the title to a string.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def uuid(self) -> uuid.UUID:
        """Return the uuid of this object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def xdata(self) -> DataAndMetadata.DataAndMetadata:
        """Return the extended data of this data item.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @xdata.setter
    def xdata(self, value: DataAndMetadata.DataAndMetadata) -> None:
        """Set the extended data of this data item.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...


class DisplayPanel:

    def set_data_item(self, data_item: DataItem) -> None:
        """Set the data item associated with this display panel.

        :param data_item: The :py:class:`nion.swift.Facade.DataItem` object to add.

        This will replace whatever data item, browser, or controller is currently in the display panel with the single
        data item.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def data_item(self) -> DataItem:
        """Return the data item associated with this display panel.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...


class Display:

    def get_graphic_by_id(self, graphic_id: str) -> Graphic:
        ...

    @property
    def data_item(self) -> DataItem:
        ...

    @property
    def display_type(self) -> str:
        ...

    @display_type.setter
    def display_type(self, value: str) -> None:
        ...

    @property
    def graphics(self) -> typing.List[Graphic]:
        ...

    @property
    def selected_graphics(self) -> typing.List[Graphic]:
        ...

    @property
    def uuid(self) -> uuid.UUID:
        """Return the uuid of this object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...


class DataGroup:

    def add_data_item(self, data_item: DataItem) -> None:
        """Add a data item to the group.

        :param data_item: The :py:class:`nion.swift.Facade.DataItem` object to add.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def uuid(self) -> uuid.UUID:
        """Return the uuid of this object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...


class Library:

    def copy_data_item(self, data_item: DataItem) -> DataItem:
        """Copy a data item.

        .. versionadded:: 1.0

        Scriptable: No
        """
        ...

    def create_data_item(self, title: str=None) -> DataItem:
        """Create an empty data item in the library.

        :param title: The title of the data item (optional).
        :return: The new :py:class:`nion.swift.Facade.DataItem` object.
        :rtype: :py:class:`nion.swift.Facade.DataItem`

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def create_data_item_from_data(self, data: numpy.ndarray, title: str=None) -> DataItem:
        """Create a data item in the library from an ndarray.

        The data for the data item will be written to disk immediately and unloaded from memory. If you wish to delay
        writing to disk and keep using the data, create an empty data item and use the data item methods to modify
        the data.

        :param data: The data (ndarray).
        :param title: The title of the data item (optional).
        :return: The new :py:class:`nion.swift.Facade.DataItem` object.
        :rtype: :py:class:`nion.swift.Facade.DataItem`

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def create_data_item_from_data_and_metadata(self, data_and_metadata: DataAndMetadata.DataAndMetadata, title: str=None) -> DataItem:
        """Create a data item in the library from a data and metadata object.

        The data for the data item will be written to disk immediately and unloaded from memory. If you wish to delay
        writing to disk and keep using the data, create an empty data item and use the data item methods to modify
        the data.

        :param data_and_metadata: The data and metadata.
        :param title: The title of the data item (optional).
        :return: The new :py:class:`nion.swift.Facade.DataItem` object.
        :rtype: :py:class:`nion.swift.Facade.DataItem`

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def data_ref_for_data_item(self, data_item: DataItem):
        ...

    def delete_library_value(self, key: str) -> None:
        """Delete the library value for the given key.

        Please consult the developer documentation for a list of valid keys.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def get_data_item_by_uuid(self, data_item_uuid: uuid.UUID) -> DataItem:
        """Get the data item with the given UUID.

        .. versionadded:: 1.0

        Status: Provisional
        Scriptable: Yes
        """
        ...

    def get_data_item_for_hardware_source(self, hardware_source, channel_id: str=None, processor_id: str=None, create_if_needed: bool=False, large_format: bool=False) -> DataItem:
        """Get the data item associated with hardware source and (optional) channel id and processor_id. Optionally create if missing.

        :param hardware_source: The hardware_source.
        :param channel_id: The (optional) channel id.
        :param processor_id: The (optional) processor id for the channel.
        :param create_if_needed: Whether to create a new data item if none is found.
        :return: The associated data item. May be None.

        .. versionadded:: 1.0

        Status: Provisional
        Scriptable: Yes
        """
        ...

    def get_dependent_data_items(self, data_item: DataItem) -> typing.List[DataItem]:
        """Return the dependent data items the data item argument.

        :return: The list of :py:class:`nion.swift.Facade.DataItem` objects.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def get_graphic_by_uuid(self, graphic_uuid: uuid.UUID) -> Graphic:
        """Get the graphic with the given UUID.

        .. versionadded:: 1.0

        Status: Provisional
        Scriptable: Yes
        """
        ...

    def get_library_value(self, key: str) -> typing.Any:
        """Get the library value for the given key.

        Please consult the developer documentation for a list of valid keys.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def get_or_create_data_group(self, title: str) -> DataGroup:
        """Get (or create) a data group.

        :param title: The title of the data group.
        :return: The new :py:class:`nion.swift.Facade.DataGroup` object.
        :rtype: :py:class:`nion.swift.Facade.DataGroup`

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def get_source_data_items(self, data_item: DataItem) -> typing.List[DataItem]:
        """Return the list of data items that are data sources for the data item.

        :return: The list of :py:class:`nion.swift.Facade.DataItem` objects.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def has_library_value(self, key: str) -> bool:
        """Return whether the library value for the given key exists.

        Please consult the developer documentation for a list of valid keys.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def set_library_value(self, key: str, value: typing.Any) -> None:
        """Set the library value for the given key.

        Please consult the developer documentation for a list of valid keys.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def snapshot_data_item(self, data_item: DataItem) -> DataItem:
        """Snapshot a data item. Similar to copy but with a data snapshot.

        .. versionadded:: 1.0

        Scriptable: No
        """
        ...

    @property
    def data_item_count(self) -> int:
        """Return the data item count.

        :return: The number of data items.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def data_items(self) -> typing.List[DataItem]:
        """Return the list of data items.

        :return: The list of :py:class:`nion.swift.Facade.DataItem` objects.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def uuid(self) -> uuid.UUID:
        """Return the uuid of this object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...


class DocumentWindow:

    def add_data(self, data: numpy.ndarray, title: str=None) -> DataItem:
        """Create a data item in the library from data.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:meth:`~nion.swift.Facade.Library.create_data_item_from_data` instead.

        Scriptable: No
        """
        ...

    def create_data_item_from_data(self, data: numpy.ndarray, title: str=None) -> DataItem:
        """Create a data item in the library from data.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:meth:`~nion.swift.Facade.Library.create_data_item_from_data` instead.

        Scriptable: No
        """
        ...

    def create_data_item_from_data_and_metadata(self, data_and_metadata: DataAndMetadata.DataAndMetadata, title: str=None) -> DataItem:
        """Create a data item in the library from the data and metadata.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:meth:`~nion.swift.Facade.Library.create_data_item_from_data_and_metadata` instead.

        Scriptable: No
        """
        ...

    def display_data_item(self, data_item: DataItem, source_display_panel=None, source_data_item=None):
        """Display a new data item and gives it keyboard focus. Uses existing display if it is already displayed.

        .. versionadded:: 1.0

        Status: Provisional
        Scriptable: Yes
        """
        ...

    def get_display_panel_by_id(self, identifier: str) -> DisplayPanel:
        """Return display panel with the identifier.

        .. versionadded:: 1.0

        Status: Provisional
        Scriptable: Yes
        """
        ...

    def get_or_create_data_group(self, title: str) -> DataGroup:
        """Get (or create) a data group.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:meth:`~nion.swift.Facade.Library.create_data_item_from_data` instead.

        Scriptable: No
        """
        ...

    def queue_task(self, fn) -> None:
        ...

    def show_confirmation_message_box(self, caption: str, accepted_fn, rejected_fn=None, accepted_text: str=None, rejected_text: str=None, display_rejected: str=False) -> None:
        ...

    def show_get_string_message_box(self, caption: str, text: str, accepted_fn, rejected_fn=None, accepted_text: str=None, rejected_text: str=None) -> None:
        """Show a dialog box and ask for a string.

        Caption describes the user prompt. Text is the initial/default string.

        Accepted function must be a function taking one argument which is the resulting text if the user accepts the
        message dialog. It will only be called if the user clicks OK.

        Rejected function can be a function taking no arguments, called if the user clicks Cancel.

        .. versionadded:: 1.0

        Scriptable: No
        """
        ...

    @property
    def all_display_panels(self) -> typing.List[DisplayPanel]:
        """Return the list of display panels currently visible.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def library(self) -> Library:
        """Return the library object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def target_data_item(self) -> DataItem:
        ...

    @property
    def target_display(self) -> Display:
        ...


class Application:

    @property
    def document_controllers(self) -> typing.List[DocumentWindow]:
        """Return the document controllers.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:attr:`~nion.swift.Facade.Application.document_windows` instead.

        Scriptable: Yes
        """
        ...

    @property
    def document_windows(self) -> typing.List[DocumentWindow]:
        """Return the document windows.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def library(self) -> Library:
        """Return the library object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...


class API:
    """An interface to Nion Swift.

    This class cannot be instantiated directly. Use :samp:`api_broker.get_api(version)` to get access an instance of
    this class.
    """

    def create_calibration(self, offset: float=None, scale: float=None, units: str=None) -> Calibration.Calibration:
        """Create a calibration object with offset, scale, and units.

        :param offset: The offset of the calibration.
        :param scale: The scale of the calibration.
        :param units: The units of the calibration as a string.
        :return: The calibration object.

        .. versionadded:: 1.0

        Scriptable: Yes

        Calibrated units and uncalibrated units have the following relationship:
            :samp:`calibrated_value = offset + value * scale`
        """
        ...

    def create_data_and_metadata(self, data: numpy.ndarray, intensity_calibration: Calibration.Calibration=None, dimensional_calibrations: typing.List[Calibration.Calibration]=None, metadata: dict=None, timestamp: str=None, data_descriptor: DataAndMetadata.DataDescriptor=None) -> DataAndMetadata.DataAndMetadata:
        """Create a data_and_metadata object from data.

        :param data: an ndarray of data.
        :param intensity_calibration: An optional calibration object.
        :param dimensional_calibrations: An optional list of calibration objects.
        :param metadata: A dict of metadata.
        :param timestamp: A datetime object.
        :param data_descriptor: A data descriptor describing the dimensions.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def create_data_and_metadata_from_data(self, data: numpy.ndarray, intensity_calibration: Calibration.Calibration=None, dimensional_calibrations: typing.List[Calibration.Calibration]=None, metadata: dict=None, timestamp: str=None) -> DataAndMetadata.DataAndMetadata:
        """Create a data_and_metadata object from data.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:meth:`~nion.swift.Facade.DataItem.create_data_and_metadata` instead.

        Scriptable: No
        """
        ...

    def create_data_and_metadata_io_handler(self, io_handler_delegate):
        """Create an I/O handler that reads and writes a single data_and_metadata.

        :param io_handler_delegate: A delegate object :py:class:`DataAndMetadataIOHandlerInterface`

        .. versionadded:: 1.0

        Scriptable: No
        """
        ...

    def create_data_descriptor(self, is_sequence: bool, collection_dimension_count: int, datum_dimension_count: int) -> DataAndMetadata.DataDescriptor:
        """Create a data descriptor.

        :param is_sequence: whether the descriptor describes a sequence of data.
        :param collection_dimension_count: the number of collection dimensions represented by the descriptor.
        :param datum_dimension_count: the number of datum dimensions represented by the descriptor.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def create_hardware_source(self, hardware_source_delegate):
        ...

    def create_menu_item(self, menu_item_handler):
        ...

    def create_panel(self, panel_delegate):
        """Create a utility panel that can be attached to a window.

        .. versionadded:: 1.0

        Scriptable: No

         The panel_delegate should respond to the following:
            (property, read-only) panel_id
            (property, read-only) panel_name
            (property, read-only) panel_positions (a list from "top", "bottom", "left", "right", "all")
            (property, read-only) panel_position (from "top", "bottom", "left", "right", "none")
            (method, required) create_panel_widget(ui), returns a widget
            (method, optional) close()
        """
        ...

    def get_all_hardware_source_ids(self) -> typing.List[str]:
        ...

    def get_all_instrument_ids(self) -> typing.List[str]:
        ...

    def get_hardware_source_by_id(self, hardware_source_id: str, version: str):
        """Return the hardware source API matching the hardware_source_id and version.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    def get_instrument_by_id(self, instrument_id: str, version: str):
        ...

    def queue_task(self, fn) -> None:
        ...

    @property
    def application(self) -> Application:
        """Return the application object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

    @property
    def library(self) -> Library:
        """Return the library object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        ...

version = "~1.0"
