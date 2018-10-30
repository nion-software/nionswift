"""
    Contains classes related to display of data items.
"""

# standard libraries
import copy
import gettext
import math
import typing
import weakref

import numpy

from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift.model import Cache
from nion.utils import Event
from nion.utils import Observable
from nion.utils import Persistence


_ = gettext.gettext


class CalibrationList:

    def __init__(self, calibrations=None):
        self.list = list() if calibrations is None else copy.deepcopy(calibrations)

    def __len__(self):
        return len(self.list)

    def __getitem__(self, item):
        return self.list[item]

    def read_dict(self, storage_list):
        # storage_list will be whatever is returned by write_dict.
        new_list = list()
        for calibration_dict in storage_list:
            new_list.append(Calibration.Calibration().read_dict(calibration_dict))
        self.list = new_list
        return self  # for convenience

    def write_dict(self):
        list = []
        for calibration in self.list:
            list.append(calibration.write_dict())
        return list


class CalibrationStyle:
    label = None
    calibration_style_id = None
    is_calibrated = False

    def get_dimensional_calibrations(self, dimensional_shape, dimensional_calibrations) -> typing.Sequence[Calibration.Calibration]:
        return list()

    def get_intensity_calibration(self, xdata: DataAndMetadata.DataAndMetadata) -> Calibration.Calibration:
        return xdata.intensity_calibration if self.is_calibrated else Calibration.Calibration()


class CalibrationStyleNative(CalibrationStyle):
    label = _("Calibrated")
    calibration_style_id = "calibrated"
    is_calibrated = True

    def get_dimensional_calibrations(self, dimensional_shape, dimensional_calibrations) -> typing.Sequence[Calibration.Calibration]:
        return dimensional_calibrations


class CalibrationStylePixelsTopLeft(CalibrationStyle):
    label = _("Pixels (Top-Left)")
    calibration_style_id = "pixels-top-left"

    def get_dimensional_calibrations(self, dimensional_shape, dimensional_calibrations) -> typing.Sequence[Calibration.Calibration]:
        return [Calibration.Calibration() for display_dimension in dimensional_shape]


class CalibrationStylePixelsCenter(CalibrationStyle):
    label = _("Pixels (Center)")
    calibration_style_id = "pixels-center"

    def get_dimensional_calibrations(self, dimensional_shape, dimensional_calibrations) -> typing.Sequence[Calibration.Calibration]:
        return [Calibration.Calibration(offset=-display_dimension/2) for display_dimension in dimensional_shape]


class CalibrationStyleFractionalTopLeft(CalibrationStyle):
    label = _("Fractional (Top Left)")
    calibration_style_id = "relative-top-left"

    def get_dimensional_calibrations(self, dimensional_shape, dimensional_calibrations) -> typing.Sequence[Calibration.Calibration]:
        return [Calibration.Calibration(scale=1.0/display_dimension) for display_dimension in dimensional_shape]


class CalibrationStyleFractionalCenter(CalibrationStyle):
    label = _("Fractional (Center)")
    calibration_style_id = "relative-center"

    def get_dimensional_calibrations(self, dimensional_shape, dimensional_calibrations) -> typing.Sequence[Calibration.Calibration]:
        return [Calibration.Calibration(scale=2.0/display_dimension, offset=-1.0) for display_dimension in dimensional_shape]


class Display(Observable.Observable, Persistence.PersistentObject):
    """The display properties for a DataItem.

    Also handles conversion of raw data to formats suitable for display such as raster RGBA.

    Display data is the associated data item data after it has been reduced to basic form (1d, 2d) by slicing and/or
    conversion to scalar.

    RGB data is the display data after it has been converted to RGB for raster display.

    In order to be able to efficiently route data in a thread, and also to make the data consistent with a snapshot
    in time, display data and RGB data is managed via a DisplayValues object.

    In addition to regular observable events, this class also generates the following events:
        - about_to_be_removed_event: fired when about to be removed from parent container.
        - display_changed_event: fired when display changes in a way to affect drawing.
    """

    def __init__(self):
        super().__init__()
        self.__container_weak_ref = None
        self.__cache = Cache.ShadowCache()
        # calibration display
        self.define_property("calibration_style_id", "calibrated", key="dimensional_calibration_style", changed=self.__property_changed)
        # image zoom and position
        self.define_property("image_zoom", 1.0, changed=self.__property_changed)
        self.define_property("image_position", (0.5, 0.5), changed=self.__property_changed)
        self.define_property("image_canvas_mode", "fit", changed=self.__property_changed)
        # line plot axes and labels
        self.define_property("y_min", changed=self.__property_changed)
        self.define_property("y_max", changed=self.__property_changed)
        self.define_property("y_style", "linear", changed=self.__property_changed)
        self.define_property("left_channel", changed=self.__property_changed)
        self.define_property("right_channel", changed=self.__property_changed)
        self.define_property("legend_labels", changed=self.__property_changed)
        # display script
        self.define_property("display_script", changed=self.__property_changed)

        self.display_changed_event = Event.Event()

        self._display_type = None  # set by the display item

        self.__data_and_metadata = None  # the most recent data to be displayed. should have immediate data available.
        self.__dimensional_calibrations = None
        self.__intensity_calibration = None
        self.__dimensional_shape = None
        self.__scales = None

        self.about_to_be_removed_event = Event.Event()
        self._about_to_be_removed = False
        self._closed = False

    def close(self):
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None

    @property
    def container(self):
        return self.__container_weak_ref()

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        self.about_to_be_removed_event.fire()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True

    def insert_model_item(self, container, name, before_index, item):
        if self.__container_weak_ref:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        if self.__container_weak_ref:
            return self.container.remove_model_item(container, name, item, safe=safe)
        else:
            container.remove_item(name, item)
            return None

    def clone(self) -> "Display":
        display = Display()
        display.uuid = self.uuid
        return display

    def save_properties(self) -> typing.Tuple:
        return (
            self.left_channel,
            self.right_channel,
            self.y_min,
            self.y_max,
            self.y_style,
            self.image_zoom,
            self.image_position,
            self.image_canvas_mode,
            self.calibration_style_id,
            self.display_script
        )

    def restore_properties(self, properties: typing.Tuple) -> None:
        self.left_channel = properties[0]
        self.right_channel = properties[1]
        self.y_min = properties[2]
        self.y_max = properties[3]
        self.y_style = properties[4]
        self.image_zoom = properties[5]
        self.image_position = properties[6]
        self.image_canvas_mode = properties[7]
        self.calibration_style_id = properties[8]
        self.display_script = properties[9]

    @property
    def _display_cache(self):
        return self.__cache

    def view_to_intervals(self, data_and_metadata: DataAndMetadata.DataAndMetadata, intervals: typing.List[typing.Tuple[float, float]]) -> None:
        """Change the view to encompass the channels and data represented by the given intervals."""
        left = None
        right = None
        for interval in intervals:
            left = min(left, interval[0]) if left is not None else interval[0]
            right = max(right, interval[1]) if right is not None else interval[1]
        left = left if left is not None else 0.0
        right = right if right is not None else 1.0
        extra = (right - left) * 0.5
        self.left_channel = int(max(0.0, left - extra) * data_and_metadata.data_shape[-1])
        self.right_channel = int(min(1.0, right + extra) * data_and_metadata.data_shape[-1])
        data_min = numpy.amin(data_and_metadata.data[..., self.left_channel:self.right_channel])
        data_max = numpy.amax(data_and_metadata.data[..., self.left_channel:self.right_channel])
        if data_min > 0 and data_max > 0:
            self.y_min = 0.0
            self.y_max = data_max * 1.2
        elif data_min < 0 and data_max < 0:
            self.y_min = data_min * 1.2
            self.y_max = 0.0
        else:
            self.y_min = data_min * 1.2
            self.y_max = data_max * 1.2

    def __property_changed(self, property_name, value):
        # when one of the defined properties changes, this gets called
        self.notify_property_changed(property_name)
        if property_name in ("calibration_style_id", ):
            self.notify_property_changed("displayed_dimensional_scales")
            self.notify_property_changed("displayed_dimensional_calibrations")
            self.notify_property_changed("displayed_intensity_calibration")
        self.display_changed_event.fire()

    # message sent when data changes.
    # thread safe
    def update_xdata_list(self, xdata_list: typing.Sequence[DataAndMetadata.DataAndMetadata]) -> None:
        data_and_metadata = xdata_list[0] if len(xdata_list) == 1 else None

        if len(xdata_list) > 0 and xdata_list[0]:
            dimensional_calibrations = xdata_list[0].dimensional_calibrations
            if len(dimensional_calibrations) > 1:
                self.__dimensional_calibrations = dimensional_calibrations
                self.__intensity_calibration = xdata_list[0].intensity_calibration
                self.__scales = 0, xdata_list[0].dimensional_shape[-1]
                self.__dimensional_shape = xdata_list[0].dimensional_shape
            else:
                units = dimensional_calibrations[-1].units
                mn = math.inf
                mx = -math.inf
                for xdata in xdata_list:
                    if xdata and xdata.dimensional_calibrations[-1].units == units:
                        v = dimensional_calibrations[0].convert_from_calibrated_value(xdata.dimensional_calibrations[-1].convert_to_calibrated_value(0))
                        mn = min(mn, v)
                        mx = max(mx, v)
                        v = dimensional_calibrations[0].convert_from_calibrated_value(xdata.dimensional_calibrations[-1].convert_to_calibrated_value(xdata.dimensional_shape[-1]))
                        mn = min(mn, v)
                        mx = max(mx, v)
                self.__dimensional_calibrations = dimensional_calibrations
                self.__intensity_calibration = xdata_list[0].intensity_calibration
                self.__scales = mn, mx
                self.__dimensional_shape = (mx - mn, )
        else:
            self.__dimensional_calibrations = None
            self.__intensity_calibration = None
            self.__scales = 0, 1
            self.__dimensional_shape = None
        self.__data_and_metadata = data_and_metadata
        self.notify_property_changed("displayed_dimensional_scales")
        self.notify_property_changed("displayed_dimensional_calibrations")
        self.notify_property_changed("displayed_intensity_calibration")
        self.display_changed_event.fire()

    def set_storage_cache(self, storage_cache):
        self.__cache.set_storage_cache(storage_cache, self)

    @property
    def display_data_shape(self) -> typing.Optional[typing.Tuple[int, ...]]:
        if not self.__data_and_metadata:
            return None
        data_and_metadata = self.__data_and_metadata
        dimensional_shape = data_and_metadata.dimensional_shape
        next_dimension = 0
        if data_and_metadata.is_sequence:
            next_dimension += 1
        if data_and_metadata.is_collection:
            collection_dimension_count = data_and_metadata.collection_dimension_count
            datum_dimension_count = data_and_metadata.datum_dimension_count
            # next dimensions are treated as collection indexes.
            if collection_dimension_count == 1 and datum_dimension_count == 1:
                return dimensional_shape[next_dimension:next_dimension + collection_dimension_count + datum_dimension_count]
            elif collection_dimension_count == 2 and datum_dimension_count == 1:
                return dimensional_shape[next_dimension:next_dimension + collection_dimension_count]
            else:  # default, "pick"
                return dimensional_shape[next_dimension + collection_dimension_count:next_dimension + collection_dimension_count + datum_dimension_count]
        else:
            return dimensional_shape[next_dimension:]

    @property
    def dimensional_shape(self) -> typing.Optional[typing.Tuple[int, ...]]:
        if not self.__data_and_metadata:
            return None
        return self.__data_and_metadata.dimensional_shape

    @property
    def displayed_dimensional_scales(self) -> typing.Sequence[float]:
        """The scale of the fractional coordinate system.

        For displays associated with a single data item, this matches the size of the data.

        For displays associated with a composite data item, this must be stored in this class.
        """
        return self.__scales

    @property
    def displayed_dimensional_calibrations(self) -> typing.Sequence[Calibration.Calibration]:
        calibration_style = self.__get_calibration_style_for_id(self.calibration_style_id)
        calibration_style = CalibrationStyleNative() if not calibration_style else calibration_style
        if self.__dimensional_calibrations:
            return calibration_style.get_dimensional_calibrations(self.__dimensional_shape, self.__dimensional_calibrations)
        return [Calibration.Calibration() for c in self.__dimensional_calibrations] if self.__dimensional_calibrations else [Calibration.Calibration()]

    @property
    def displayed_intensity_calibration(self) -> Calibration.Calibration:
        calibration_style = self.__get_calibration_style_for_id(self.calibration_style_id)
        if self.__intensity_calibration and (not calibration_style or calibration_style.is_calibrated):
            return self.__intensity_calibration
        return Calibration.Calibration()

    @property
    def calibration_styles(self) -> typing.List[CalibrationStyle]:
        return [CalibrationStyleNative(), CalibrationStylePixelsTopLeft(), CalibrationStylePixelsCenter(),
                CalibrationStyleFractionalTopLeft(), CalibrationStyleFractionalCenter()]

    @property
    def default_calibrated_calibration_style(self):
        return CalibrationStyleNative()

    @property
    def default_uncalibrated_calibration_style(self):
        return CalibrationStylePixelsCenter()

    def __get_calibration_style_for_id(self, calibration_style_id: str) -> typing.Optional[CalibrationStyle]:
        return next(filter(lambda x: x.calibration_style_id == calibration_style_id, self.calibration_styles), None)

    @property
    def calibration_style(self) -> CalibrationStyle:
        return next(filter(lambda x: x.calibration_style_id == self.calibration_style_id, self.calibration_styles), self.default_calibrated_calibration_style)

    def __get_calibrated_value_text(self, value: float, intensity_calibration) -> str:
        if value is not None:
            return intensity_calibration.convert_to_calibrated_value_str(value)
        elif value is None:
            return _("N/A")
        else:
            return str(value)

    def get_value_and_position_text(self, display_data_channel, pos) -> (str, str):
        data_and_metadata = self.__data_and_metadata
        dimensional_calibrations = self.displayed_dimensional_calibrations
        intensity_calibration = self.displayed_intensity_calibration

        if data_and_metadata is None or pos is None:
            return str(), str()

        is_sequence = data_and_metadata.is_sequence
        collection_dimension_count = data_and_metadata.collection_dimension_count
        datum_dimension_count = data_and_metadata.datum_dimension_count
        if is_sequence:
            pos = (display_data_channel.sequence_index, ) + pos
        if collection_dimension_count == 2 and datum_dimension_count == 1:
            pos = pos + (display_data_channel.slice_center, )
        else:
            pos = tuple(display_data_channel.collection_index[0:collection_dimension_count]) + pos

        while len(pos) < data_and_metadata.datum_dimension_count:
            pos = (0,) + tuple(pos)

        assert len(pos) == len(data_and_metadata.dimensional_shape)

        position_text = ""
        value_text = ""
        data_shape = data_and_metadata.data_shape
        if len(pos) == 4:
            # 4d image
            # make sure the position is within the bounds of the image
            if 0 <= pos[0] < data_shape[0] and 0 <= pos[1] < data_shape[1] and 0 <= pos[2] < data_shape[2] and 0 <= pos[3] < data_shape[3]:
                position_text = u"{0}, {1}, {2}, {3}".format(
                    dimensional_calibrations[3].convert_to_calibrated_value_str(pos[3], value_range=(0, data_shape[3]), samples=data_shape[3]),
                    dimensional_calibrations[2].convert_to_calibrated_value_str(pos[2], value_range=(0, data_shape[2]), samples=data_shape[2]),
                    dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1], value_range=(0, data_shape[1]), samples=data_shape[1]),
                    dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0], value_range=(0, data_shape[0]), samples=data_shape[0]))
                value_text = self.__get_calibrated_value_text(data_and_metadata.get_data_value(pos), intensity_calibration)
        if len(pos) == 3:
            # 3d image
            # make sure the position is within the bounds of the image
            if 0 <= pos[0] < data_shape[0] and 0 <= pos[1] < data_shape[1] and 0 <= pos[2] < data_shape[2]:
                position_text = u"{0}, {1}, {2}".format(dimensional_calibrations[2].convert_to_calibrated_value_str(pos[2], value_range=(0, data_shape[2]), samples=data_shape[2]),
                    dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1], value_range=(0, data_shape[1]), samples=data_shape[1]),
                    dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0], value_range=(0, data_shape[0]), samples=data_shape[0]))
                value_text = self.__get_calibrated_value_text(data_and_metadata.get_data_value(pos), intensity_calibration)
        if len(pos) == 2:
            # 2d image
            # make sure the position is within the bounds of the image
            if len(data_shape) == 1:
                if pos[-1] >= 0 and pos[-1] < data_shape[-1]:
                    position_text = u"{0}".format(dimensional_calibrations[-1].convert_to_calibrated_value_str(pos[-1], value_range=(0, data_shape[-1]), samples=data_shape[-1]))
                    full_pos = [0, ] * len(data_shape)
                    full_pos[-1] = pos[-1]
                    value_text = self.__get_calibrated_value_text(data_and_metadata.get_data_value(full_pos), intensity_calibration)
            else:
                if pos[0] >= 0 and pos[0] < data_shape[0] and pos[1] >= 0 and pos[1] < data_shape[1]:
                    is_polar = dimensional_calibrations[0].units.startswith("1/") and dimensional_calibrations[0].units == dimensional_calibrations[1].units
                    is_polar = is_polar and abs(dimensional_calibrations[0].scale * data_shape[0] - dimensional_calibrations[1].scale * data_shape[1]) < 1e-12
                    is_polar = is_polar and abs(dimensional_calibrations[0].offset / (dimensional_calibrations[0].scale * data_shape[0]) + 0.5) < 1e-12
                    is_polar = is_polar and abs(dimensional_calibrations[1].offset / (dimensional_calibrations[1].scale * data_shape[1]) + 0.5) < 1e-12
                    if is_polar:
                        x = dimensional_calibrations[1].convert_to_calibrated_value(pos[1])
                        y = dimensional_calibrations[0].convert_to_calibrated_value(pos[0])
                        r = math.sqrt(x * x + y * y)
                        angle = -math.atan2(y, x)
                        r_str = dimensional_calibrations[0].convert_to_calibrated_value_str(dimensional_calibrations[0].convert_from_calibrated_value(r), value_range=(0, data_shape[0]), samples=data_shape[0], display_inverted=True)
                        position_text = u"{0}, {1:.4f}° ({2})".format(r_str, math.degrees(angle), _("polar"))
                    else:
                        position_text = u"{0}, {1}".format(dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1], value_range=(0, data_shape[1]), samples=data_shape[1], display_inverted=True),
                            dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0], value_range=(0, data_shape[0]), samples=data_shape[0], display_inverted=True))
                    value_text = self.__get_calibrated_value_text(data_and_metadata.get_data_value(pos), intensity_calibration)
        if len(pos) == 1:
            # 1d plot
            # make sure the position is within the bounds of the line plot
            if pos[0] >= 0 and pos[0] < data_shape[-1]:
                position_text = u"{0}".format(dimensional_calibrations[-1].convert_to_calibrated_value_str(pos[0], value_range=(0, data_shape[-1]), samples=data_shape[-1]))
                full_pos = [0, ] * len(data_shape)
                full_pos[-1] = pos[0]
                value_text = self.__get_calibrated_value_text(data_and_metadata.get_data_value(full_pos), intensity_calibration)
        return position_text, value_text


def display_factory(lookup_id):
    return Display()


class DisplayProperties:

    def __init__(self, display: Display):

        self.display_data_shape = display.display_data_shape

        self.displayed_dimensional_scales = display.displayed_dimensional_scales
        self.displayed_dimensional_calibrations = copy.deepcopy(display.displayed_dimensional_calibrations)
        self.displayed_intensity_calibration = copy.deepcopy(display.displayed_intensity_calibration)
        self.calibration_style = display.calibration_style

        self.image_zoom = display.image_zoom
        self.image_position = display.image_position
        self.image_canvas_mode = display.image_canvas_mode

        self.y_min = display.y_min
        self.y_max = display.y_max
        self.y_style = display.y_style
        self.left_channel = display.left_channel
        self.right_channel = display.right_channel
        self.legend_labels = display.legend_labels

        self.display_script = display.display_script

    def __ne__(self, display_properties):
        if not display_properties:
            return True
        if  self.display_data_shape != display_properties.display_data_shape:
            return True
        if  self.displayed_dimensional_scales != display_properties.displayed_dimensional_scales:
            return True
        if  self.displayed_dimensional_calibrations != display_properties.displayed_dimensional_calibrations:
            return True
        if  self.displayed_intensity_calibration != display_properties.displayed_intensity_calibration:
            return True
        if  type(self.calibration_style) != type(display_properties.calibration_style):
            return True
        if  self.image_zoom != display_properties.image_zoom:
            return True
        if  self.image_position != display_properties.image_position:
            return True
        if  self.image_canvas_mode != display_properties.image_canvas_mode:
            return True
        if  self.y_min != display_properties.y_min:
            return True
        if  self.y_max != display_properties.y_max:
            return True
        if  self.y_style != display_properties.y_style:
            return True
        if  self.left_channel != display_properties.left_channel:
            return True
        if  self.right_channel != display_properties.right_channel:
            return True
        if  self.legend_labels != display_properties.legend_labels:
            return True
        if  self.display_script != display_properties.display_script:
            return True
        return False
