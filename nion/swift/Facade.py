"""
    A versioned interface to Swift.

    on_xyz methods are used when a callback needs a return value and has only a single listener.

    events are used when a callback is optional and may have multiple listeners.

    Versions numbering follows semantic version numbering: http://semver.org/
"""

# standard libraries
import datetime
import gettext
import pickle
import threading
import typing
import uuid

# third party libraries
import numpy

# local libraries
from nion.data import Calibration as CalibrationModule
from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift import Application as ApplicationModule
from nion.swift import DisplayPanel as DisplayPanelModule
from nion.swift import Panel as PanelModule
from nion.swift import Workspace
from nion.swift.model import DataItem as DataItemModule
from nion.swift.model import DocumentModel as DocumentModelModule
from nion.swift.model import Graphics
from nion.swift.model import HardwareSource as HardwareSourceModule
from nion.swift.model import ImportExportManager
from nion.swift.model import PlugInManager
from nion.swift.model import Utility
from nion.ui import CanvasItem as CanvasItemModule
from nion.utils import Geometry

__all__ = ["get_api"]


_ = gettext.gettext


api_public = [
    "Region", "DataItem", "DisplayPanel", "Graphic", "Display", "DataGroup",
    "Instrument", "Library", "DocumentController", "Application", "API_1"]
hardware_source_public = [
    "RecordTask", "ViewTask", "HardwareSource"
]
alias = {"API_1": "API"}


class ObjectSpecifier:

    def __init__(self, object_type, object_uuid=None, object_id=None):
        self.object_type = object_type
        self.object_uuid = str(object_uuid) if object_uuid else None
        self.object_id = str(object_id) if object_id else None

    @classmethod
    def resolve(cls, d):
        if d is None:
            return get_api("1", "1")
        object_type = d.get("object_type")
        object_uuid_str = d.get("object_uuid")
        object_id = d.get("object_id")
        object_uuid = uuid.UUID(object_uuid_str) if object_uuid_str else None
        document_model = ApplicationModule.app.document_controllers[0].document_model
        if object_type == "application":
            return Application(ApplicationModule.app)
        elif object_type == "library":
            return Library(document_model)
        elif object_type == "document_controller":
            document_controller = next(iter(filter(lambda x: x.uuid == object_uuid, ApplicationModule.app.document_controllers)), None)
            return DocumentController(document_controller) if document_controller else None
        elif object_type == "display_panel":
            for document_controller in ApplicationModule.app.document_controllers:
                display_panel = next(iter(filter(lambda x: x.uuid == object_uuid, document_controller.workspace_controller.display_panels)), None)
                if display_panel:
                    return DisplayPanel(display_panel)
            return None
        elif object_type == "data_item":
            return DataItem(document_model.get_data_item_by_uuid(uuid.UUID(object_uuid_str)))
        elif object_type == "data_group":
            return DataGroup(document_model.get_data_group_by_uuid(uuid.UUID(object_uuid_str)))
        elif object_type in ("region", "graphic"):
            for data_item in document_model.data_items:
                for data_source in data_item.data_sources:
                    for display in data_source.displays:
                        for region in display.graphics:
                            if region.uuid == object_uuid:
                                return region
        elif object_type == "display":
            for data_item in document_model.data_items:
                for data_source in data_item.data_sources:
                    for display in data_source.displays:
                        if display.uuid == object_uuid:
                            return display
        elif object_type == "hardware_source":
            return HardwareSource(HardwareSourceModule.HardwareSourceManager().get_hardware_source_for_hardware_source_id(object_id))
        elif object_type == "instrument":
            return Instrument(HardwareSourceModule.HardwareSourceManager().get_instrument_by_id(object_id))
        return None


class CanvasItem(CanvasItemModule.AbstractCanvasItem):

    def __init__(self):
        super().__init__()
        self.on_repaint = None

    def _repaint(self, drawing_context):
        if self.on_repaint:
            self.on_repaint(drawing_context, Geometry.IntSize.make(self.canvas_size))


class RootCanvasItem(CanvasItemModule.RootCanvasItem):

    def __init__(self, ui, canvas_item, properties):
        super().__init__(ui, properties)
        self.__canvas_item = canvas_item

    @property
    def _widget(self):
        return self.canvas_widget

    @property
    def on_repaint(self):
        return self.__canvas_item.on_repaint

    @on_repaint.setter
    def on_repaint(self, value):
        self.__canvas_item.on_repaint = value


class ColumnWidget:

    def __init__(self, ui):
        self.__ui = ui
        self.__column_widget = self.__ui.create_column_widget()

    @property
    def _widget(self):
        return self.__column_widget

    def add_spacing(self, spacing):
        self.__column_widget.add_spacing(spacing)

    def add_stretch(self):
        self.__column_widget.add_stretch()

    def add(self, widget):
        self.__column_widget.add(widget._widget)


class RowWidget:

    def __init__(self, ui):
        self.__ui = ui
        self.__row_widget = self.__ui.create_row_widget()

    @property
    def _widget(self):
        return self.__row_widget

    def add_spacing(self, spacing):
        self.__row_widget.add_spacing(spacing)

    def add_stretch(self):
        self.__row_widget.add_stretch()

    def add(self, widget):
        self.__row_widget.add(widget._widget)


class ComboBoxWidget:

    def __init__(self, ui):
        self.__ui = ui
        self.__combo_box_widget = self.__ui.create_combo_box_widget()

    @property
    def _widget(self):
        return self.__combo_box_widget

    @property
    def items(self):
        return self.__combo_box_widget.items

    @items.setter
    def items(self, value):
        self.__combo_box_widget.items = value

    @property
    def item_text_getter(self):
        return self.__combo_box_widget.item_getter

    @item_text_getter.setter
    def item_text_getter(self, value):
        self.__combo_box_widget.item_getter = value

    @property
    def on_current_text_changed(self):
        return self.__combo_box_widget.on_current_text_changed

    @on_current_text_changed.setter
    def on_current_text_changed(self, value):
        self.__combo_box_widget.on_current_text_changed = value

    @property
    def on_current_item_changed(self):
        return self.__combo_box_widget.on_current_item_changed

    @on_current_item_changed.setter
    def on_current_item_changed(self, value):
        self.__combo_box_widget.on_current_item_changed = value


class LabelWidget:

    def __init__(self, ui):
        self.__ui = ui
        self.__label_widget = self.__ui.create_label_widget()

    @property
    def _widget(self):
        return self.__label_widget

    @property
    def text(self):
        return self.__label_widget.text

    @text.setter
    def text(self, value):
        self.__label_widget.text = value


class LineEditWidget:

    def __init__(self, ui):
        self.__ui = ui
        self.__line_edit_widget = self.__ui.create_line_edit_widget()

    @property
    def _widget(self):
        return self.__line_edit_widget

    @property
    def text(self):
        return self.__line_edit_widget.text

    @text.setter
    def text(self, value):
        self.__line_edit_widget.text = value

    @property
    def on_editing_finished(self):
        return self.__line_edit_widget.on_editing_finished

    @on_editing_finished.setter
    def on_editing_finished(self, value):
        self.__line_edit_widget.on_editing_finished = value

    def select_all(self):
        self.__line_edit_widget.select_all()


class PushButtonWidget:

    def __init__(self, ui):
        self.__ui = ui
        self.__push_button_widget = self.__ui.create_push_button_widget()

    @property
    def _widget(self):
        return self.__push_button_widget

    @property
    def text(self):
        return self.__push_button_widget.text

    @text.setter
    def text(self, value):
        self.__push_button_widget.text = value

    @property
    def on_clicked(self):
        return self.__push_button_widget.on_clicked

    @on_clicked.setter
    def on_clicked(self, value):
        self.__push_button_widget.on_clicked = value


class CheckBoxWidget:

    def __init__(self, ui):
        self.__ui = ui
        self.__check_box_widget = self.__ui.create_check_box_widget()

    @property
    def _widget(self):
        return self.__check_box_widget

    @property
    def text(self):
        return self.__check_box_widget.text

    @text.setter
    def text(self, value):
        self.__check_box_widget.text = value

    @property
    def checked(self):
        return self.__check_box_widget.checked

    @checked.setter
    def checked(self, value):
        self.__check_box_widget.checked = value

    @property
    def on_checked_changed(self):
        return self.__check_box_widget.on_checked_changed

    @on_checked_changed.setter
    def on_checked_changed(self, value):
        self.__check_box_widget.on_checked_changed = value

    @property
    def tristate(self):
        return self.__check_box_widget.tristate

    @tristate.setter
    def tristate(self, value):
        self.__check_box_widget.tristate = value

    @property
    def check_state(self):
        return self.__check_box_widget.check_state

    @check_state.setter
    def check_state(self, value):
        self.__check_box_widget.check_state = value

    @property
    def on_check_state_changed(self):
        return self.__check_box_widget.on_check_state_changed

    @on_check_state_changed.setter
    def on_check_state_changed(self, value):
        self.__check_box_widget.on_check_state_changed = value


class UserInterface:

    def __init__(self, ui_version, ui):
        actual_version = "1.0.0"
        if Utility.compare_versions(ui_version, actual_version) > 0:
            raise NotImplementedError("UI API requested version %s is greater than %s." % (ui_version, actual_version))
        self.__ui = ui

    def create_canvas_widget(self, height=None):
        properties = dict()
        if height is not None:
            properties["min-height"] = height
            properties["max-height"] = height
        canvas_item = CanvasItem()
        root_canvas_item = RootCanvasItem(self.__ui, canvas_item, properties=properties)
        root_canvas_item.add_canvas_item(canvas_item)
        return root_canvas_item

    def create_column_widget(self):
        return ColumnWidget(self.__ui)

    def create_row_widget(self):
        return RowWidget(self.__ui)

    def create_splitter_widget(self):
        raise NotImplemented()

    def create_tab_widget(self):
        raise NotImplemented()

    def create_stack_widget(self):
        raise NotImplemented()

    def create_scroll_area_widget(self):
        raise NotImplemented()

    def create_combo_box_widget(self, items=None, item_text_getter=None):
        combo_box_widget = ComboBoxWidget(self.__ui)
        combo_box_widget.items = items if items is not None else list()
        combo_box_widget.item_text_getter = item_text_getter
        return combo_box_widget

    def create_label_widget(self, text=None):
        label_widget = LabelWidget(self.__ui)
        label_widget.text = text
        return label_widget

    def create_line_edit_widget(self, text=None):
        line_edit_widget = LineEditWidget(self.__ui)
        line_edit_widget.text = text
        return line_edit_widget

    def create_push_button_widget(self, text=None):
        push_button_widget = PushButtonWidget(self.__ui)
        push_button_widget.text = text
        return push_button_widget

    def create_radio_button_widget(self, text=None):
        raise NotImplemented()

    def create_check_box_widget(self, text=None):
        check_box_widget = CheckBoxWidget(self.__ui)
        check_box_widget.text = text
        return check_box_widget

    def create_slider_widget(self):
        raise NotImplemented()

    def create_text_edit_widget(self):
        raise NotImplemented()

    @property
    def data_file_path(self):
        return self.__ui.get_data_location()

    @property
    def document_file_path(self):
        return self.__ui.get_document_location()


class Panel(PanelModule.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super().__init__(document_controller, panel_id, panel_id)
        self.on_close = None

    def close(self):
        if self.on_close:
            self.on_close()


class Region:

    release = ["type", "label", "get_property", "set_property"]

    region_to_graphic_type_map = {
        "point-graphic": "point-region",
        "rect-graphic": "rectangle-region",
        "ellipse-graphic": "ellipse-region",
        "line-graphic": "line-region",
        "line-profile-graphic": "line-region",
        "interval-graphic": "interval-region",
        "channel-graphic": "channel-region",
    }

    def __init__(self, region):
        self.__region = region

    @property
    def _region(self):
        return self.__region

    @property
    def specifier(self):
        return ObjectSpecifier("region", self.__region.uuid)

    @property
    def type(self) -> str:
        return Region.region_to_graphic_type_map.get(self.__region.type)

    @property
    def label(self) -> str:
        return self.__region.label

    @label.setter
    def label(self, value: str) -> None:
        self.__region.label = value

    def get_property(self, property: str):
        return getattr(self.__region, property)

    def set_property(self, property: str, value):
        setattr(self.__region, property, value)

    # position, start, end, vector, center, size, bounds, angle


class DataItem:

    release = ["data", "set_data", "intensity_calibration", "set_intensity_calibration", "dimensional_calibrations", "set_dimensional_calibrations",
        "metadata", "set_metadata", "data_and_metadata", "set_data_and_metadata", "regions", "display", "add_point_region", "add_rectangle_region",
        "add_ellipse_region", "add_line_region", "add_interval_region", "add_channel_region", "remove_region"]

    def __init__(self, data_item: DataItemModule.DataItem):
        self.__data_item = data_item

    @property
    def _data_item(self) -> DataItemModule.DataItem:
        return self.__data_item

    @property
    def specifier(self):
        return ObjectSpecifier("data_item", self.__data_item.uuid)

    @property
    def data(self) -> numpy.ndarray:
        """Return the data as a numpy ndarray.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        with self.__data_item.maybe_data_source.data_ref() as data_ref:
            return data_ref.data

    def set_data(self, data: numpy.ndarray) -> None:
        """Set the data.

        :param data: A numpy ndarray.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        with self.__data_item.maybe_data_source.data_ref() as data_ref:
            data_ref.data = data

    @property
    def intensity_calibration(self) -> CalibrationModule.Calibration:
        """Return a copy of the intensity calibration.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.maybe_data_source.intensity_calibration

    def set_intensity_calibration(self, intensity_calibration: CalibrationModule.Calibration) -> None:
        """Set the intensity calibration.

        :param intensity_calibration: The intensity calibration.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__data_item.maybe_data_source.set_intensity_calibration(intensity_calibration)

    @property
    def dimensional_calibrations(self) -> typing.List[CalibrationModule.Calibration]:
        """Return a copy of the list of dimensional calibrations.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.maybe_data_source.dimensional_calibrations

    def set_dimensional_calibrations(self, dimensional_calibrations: typing.List[CalibrationModule.Calibration]) -> None:
        """Set the dimensional calibrations.

        :param dimensional_calibrations: A list of calibrations, must match the dimensions of the data.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__data_item.maybe_data_source.set_dimensional_calibrations(dimensional_calibrations)

    @property
    def metadata(self) -> dict:
        """Return a copy of the metadata as a dict.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.maybe_data_source.metadata

    def set_metadata(self, metadata: dict) -> None:
        """Set the metadata.

        :param metadata: The metadata dict.

        The metadata dict must be convertible to JSON, e.g. ``json.dumps(metadata)`` must succeed.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__data_item.maybe_data_source.set_metadata(metadata)

    @property
    def data_and_metadata(self) -> DataAndMetadata.DataAndMetadata:
        """Return the data and metadata object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.maybe_data_source.data_and_metadata

    def set_data_and_metadata(self, data_and_metadata: DataAndMetadata.DataAndMetadata) -> None:
        """Set the data and metadata.

        :param data_and_metadata: The data and metadata.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__data_item.maybe_data_source.set_data_and_metadata(data_and_metadata)

    @property
    def regions(self) -> typing.List[Region]:
        return [Region(region) for region in self.__data_item.maybe_data_source.displays[0].graphics]

    @property
    def display(self) -> "Display":
        display_specifier = DataItemModule.DisplaySpecifier.from_data_item(self.__data_item)
        return Display(display_specifier.display)

    def add_point_region(self, y: float, x: float) -> Region:
        """Add a point region to the data item.

        :param x: The x coordinate, in relative units [0.0, 1.0]
        :param y: The y coordinate, in relative units [0.0, 1.0]
        :return: The :py:class:`nion.swift.Facade.Region` object that was added.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        region = Graphics.PointGraphic()
        region.position = Geometry.FloatPoint(y, x)
        self.__data_item.maybe_data_source.displays[0].add_graphic(region)
        return Region(region)

    def add_rectangle_region(self, center_y: float, center_x: float, height: float, width: float) -> Region:
        region = Graphics.RectangleGraphic()
        region.center = Geometry.FloatPoint(center_y, center_x)
        region.size = Geometry.FloatSize(height, width)
        self.__data_item.maybe_data_source.displays[0].add_graphic(region)
        return Region(region)

    def add_ellipse_region(self, center_y: float, center_x: float, height: float, width: float) -> Region:
        region = Graphics.EllipseGraphic()
        region.center = Geometry.FloatPoint(center_y, center_x)
        region.size = Geometry.FloatSize(height, width)
        self.__data_item.maybe_data_source.displays[0].add_graphic(region)
        return Region(region)

    def add_line_region(self, start_y: float, start_x: float, end_y: float, end_x: float) -> Region:
        region = Graphics.LineGraphic()
        region.start = Geometry.FloatPoint(start_y, start_x)
        region.end = Geometry.FloatPoint(end_y, end_x)
        self.__data_item.maybe_data_source.displays[0].add_graphic(region)
        return Region(region)

    def add_interval_region(self, start: float, end: float) -> Region:
        region = Graphics.IntervalGraphic()
        region.start = start
        region.end = end
        self.__data_item.maybe_data_source.displays[0].add_graphic(region)
        return Region(region)

    def add_channel_region(self, position: float) -> Region:
        region = Graphics.ChannelGraphic()
        region.position = position
        self.__data_item.maybe_data_source.displays[0].add_graphic(region)
        return Region(region)

    def remove_region(self, region: Region) -> None:
        self.__data_item.maybe_data_source.displays[0].remove_graphic(region._region)

    def data_item_to_svg(self):

        from nion.swift import LinePlotCanvasItem
        from nion.swift import ImageCanvasItem
        from nion.ui import DrawingContext

        import collections

        display_specifier = DataItemModule.DisplaySpecifier.from_data_item(self.__data_item)

        FontMetrics = collections.namedtuple("FontMetrics", ["width", "height", "ascent", "descent", "leading"])

        def get_font_metrics(font, text):
            return FontMetrics(width=6.5 * len(text), height=15, ascent=12, descent=3, leading=0)

        aspect_ratio = None

        buffered_data_source = display_specifier.buffered_data_source
        display = display_specifier.display

        if buffered_data_source.is_data_1d:
            display_canvas_item = LinePlotCanvasItem.LinePlotCanvasItem(get_font_metrics, None)
            aspect_ratio = 4.0 / 3.0 if not aspect_ratio else aspect_ratio
        else:
            display_canvas_item = ImageCanvasItem.ImageCanvasItem(get_font_metrics, None)
            aspect_ratio = float(buffered_data_source.dimensional_shape[-1]) / buffered_data_source.dimensional_shape[-2]

        viewbox = Geometry.IntRect(Geometry.IntPoint(), Geometry.IntSize(width=320 * 1.25, height=240 * 1.25))
        viewbox = Geometry.IntRect(Geometry.IntPoint(), Geometry.fit_to_aspect_ratio(viewbox, aspect_ratio).size)
        box = Geometry.IntRect(Geometry.IntPoint(), Geometry.IntSize(width=320, height=240))
        size = Geometry.fit_to_aspect_ratio(box, aspect_ratio).size

        try:
            display_canvas_item.update_layout(viewbox.origin, viewbox.size)
            display_type = "line_plot" if buffered_data_source.is_data_1d else "image"
            DisplayPanelModule.DataItemDataSourceDisplay.update_display(display_type, display_canvas_item, display)
            dc = DrawingContext.DrawingContext()
            display_canvas_item._repaint(dc)
            return dc.to_svg(size, viewbox)
        except Exception as e:
            import traceback
            traceback.print_exc()
            traceback.print_stack()


class DisplayPanel:

    release = ["data_item", "set_data_item"]

    def __init__(self, display_panel):
        self.__display_panel = display_panel

    @property
    def _display_panel(self):
        return self.__display_panel

    @property
    def specifier(self):
        return ObjectSpecifier("display_panel", self.__display_panel.uuid)

    @property
    def data_item(self) -> DataItem:
        """Return the data item, if any, associated with this display panel.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        display_panel = self.__display_panel
        if not display_panel:
            return None
        data_item = display_panel.data_item
        return DataItem(data_item) if data_item else None

    def set_data_item(self, data_item: DataItem) -> None:
        """Set the data item associated with this display panel.

        :param data_item: The :py:class:`nion.swift.Facade.DataItem` object to add.

        This will replace whatever data item, browser, or controller is currently in the display panel with the single
        data item.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        display_panel = self.__display_panel
        if display_panel:
            display_panel.set_displayed_data_item(data_item._data_item)


class Graphic:

    release = ["region"]

    def __init__(self, graphic):
        self.__graphic = graphic

    @property
    def specifier(self):
        return ObjectSpecifier("graphic", self.__graphic.uuid)

    @property
    def region(self) -> Region:
        return Region(self.__graphic.region)


class Display:

    release = ["display_type", "selected_graphics", "graphics", "data_item"]

    def __init__(self, display):
        self.__display = display

    @property
    def specifier(self):
        return ObjectSpecifier("display", self.__display.uuid)

    @property
    def display_type(self) -> str:
        return self.__display.display_type

    @display_type.setter
    def display_type(self, value: str) -> None:
        self.__display.display_type = value

    @property
    def selected_graphics(self) -> typing.List[Graphic]:
        return [Graphic(graphic) for graphic in self.__display.selected_graphics]

    @property
    def graphics(self) -> typing.List[Graphic]:
        return [Graphic(graphic) for graphic in self.__display.graphics]

    @property
    def data_item(self) -> DataItem:
        raise AttributeError()

    @property
    def data_item_list(self):
        raise AttributeError()


class DataGroup:

    release = ["add_data_item"]

    def __init__(self, data_group):
        self.__data_group = data_group

    @property
    def specifier(self):
        return ObjectSpecifier("data_group", self.__data_group.uuid)

    def add_data_item(self, data_item: DataItem) -> None:
        """Add a data item to the group.

        :param data_item: The :py:class:`nion.swift.Facade.DataItem` object to add.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__data_group.append_data_item(data_item._data_item)

    def remove_data_item(self, data_item: DataItem) -> None:
        raise NotImplementedError()

    def remove_all_data_items(self) -> None:
        raise NotImplementedError()

    @property
    def data_items(self) -> typing.List[DataItem]:
        raise AttributeError()


class Monitor:

    def __init__(self):
        self.on_data_and_metadata_list_available = None  # frame_index, data_and_metadata_list, frame_parameters
        self.on_start_playing = None
        self.on_stop_playing = None
        self.on_start_recording = None
        self.on_stop_recording = None

    def close(self):
        pass


class RecordTask:

    release = ["close", "is_finished", "grab", "cancel"]

    def __init__(self, hardware_source, frame_parameters, channels_enabled):
        self.__hardware_source = hardware_source
        if frame_parameters:
            self.__hardware_source.set_record_frame_parameters(self.__hardware_source.get_frame_parameters_from_dict(frame_parameters))
        if channels_enabled is not None:
            for channel_index, channel_enabled in enumerate(channels_enabled):
                self.__hardware_source.set_channel_enabled(channel_index, channel_enabled)

        self.__data_and_metadata_list = None

        def record_thread():
            self.__hardware_source.start_recording()
            data_elements = self.__hardware_source.get_next_data_elements_to_finish()
            self.__data_and_metadata_list = [HardwareSourceModule.convert_data_element_to_data_and_metadata(data_element) for
                data_element in data_elements]

        self.__thread = threading.Thread(target=record_thread)
        self.__thread.start()

    def close(self) -> None:
        """Close the task.

        .. versionadded:: 1.0


        This method must be called when the task is no longer needed.
        """
        self.__thread.join()
        self.__data_and_metadata_list = None

    @property
    def is_finished(self) -> bool:
        """Return a boolean indicating whether the task is finished.

        .. versionadded:: 1.0
        """
        return not self.__thread.is_alive()

    def grab(self) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab list of data/metadata from the task.

        .. versionadded:: 1.0

        This method will wait until the task finishes.

        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`
        """
        self.__thread.join()
        return self.__data_and_metadata_list

    def cancel(self) -> None:
        self.__hardware_source.abort_recording()


class ViewTask:

    release = ["close", "grab_earliest", "grab_immediate", "grab_next_to_finish", "grab_next_to_start"]

    def __init__(self, hardware_source: HardwareSourceModule.HardwareSource, frame_parameters: dict, channels_enabled: typing.List[bool], buffer_size: int):
        self.__hardware_source = hardware_source
        self.__was_playing = self.__hardware_source.is_playing
        if frame_parameters:
            self.__hardware_source.set_current_frame_parameters(self.__hardware_source.get_frame_parameters_from_dict(frame_parameters))
        if channels_enabled is not None:
            for channel_index, channel_enabled in enumerate(channels_enabled):
                self.__hardware_source.set_channel_enabled(channel_index, channel_enabled)
        if not self.__was_playing:
            self.__hardware_source.start_playing()
        self.__data_channel_buffer = HardwareSourceModule.DataChannelBuffer(self.__hardware_source.data_channels, buffer_size)
        self.__data_channel_buffer.start()
        self.on_will_start_frame = None  # prepare the hardware here
        self.on_did_finish_frame = None  # restore the hardware here, modify the data_and_metadata here

    def close(self) -> None:
        """Close the task.

        .. versionadded:: 1.0

        This method must be called when the task is no longer needed.
        """
        self.__data_channel_buffer.stop()
        self.__data_channel_buffer.close()
        self.__data_channel_buffer = None
        if not self.__was_playing:
            self.__hardware_source.stop_playing()

    def grab_immediate(self) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab list of data/metadata from the task.

        .. versionadded:: 1.0

        This method will return immediately if data is available.

        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`
        """
        return self.__data_channel_buffer.grab_latest()

    def grab_next_to_finish(self) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab list of data/metadata from the task.

        .. versionadded:: 1.0

        This method will wait until the current frame completes.

        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`
        """
        return self.__data_channel_buffer.grab_next()

    def grab_next_to_start(self) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab list of data/metadata from the task.

        .. versionadded:: 1.0

        This method will wait until the current frame completes and the next one finishes.

        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`
        """
        return self.__data_channel_buffer.grab_following()

    def grab_earliest(self) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grab list of data/metadata from the task.

        .. versionadded:: 1.0

        This method will return the earliest item in the buffer or wait for the next one to finish.

        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`
        """
        return self.__data_channel_buffer.grab_earliest()


class HardwareSource:

    release = ["close", "profile_index", "get_default_frame_parameters", "get_frame_parameters", "get_frame_parameters_for_profile_by_index",
        "set_frame_parameters", "set_frame_parameters_for_profile_by_index", "start_playing", "stop_playing", "abort_playing", "is_playing",
        "start_recording", "abort_recording", "is_recording", "record", "create_record_task", "create_view_task", "grab_next_to_finish",
        "grab_next_to_start", "get_property_as_float", "set_property_as_float", "get_property_as_int", "set_property_as_int", "get_property_as_bool",
        "set_property_as_bool", "get_property_as_str", "set_property_as_str", "get_property_as_float_point", "set_property_as_float_point"]

    def __init__(self, hardware_source):
        self.__hardware_source = hardware_source

    @property
    def _hardware_source(self):
        return self.__hardware_source

    def close(self) -> None:
        pass

    @property
    def specifier(self):
        return ObjectSpecifier("hardware_source", object_id=self.__hardware_source.hardware_source_id)

    @property
    def profile_index(self) -> int:
        return self.__hardware_source.selected_profile_index

    @profile_index.setter
    def profile_index(self, value: int) -> None:
        self.__hardware_source.set_selected_profile_index(value)

    def get_default_frame_parameters(self) -> dict:
        return self.__hardware_source.get_frame_parameters_from_dict(dict()).as_dict()

    def get_frame_parameters(self) -> dict:
        return self.__hardware_source.get_current_frame_parameters().as_dict()

    # TODO: deprecate this method. user should pass record parameters each time record is started, so no need to read them back.
    def get_record_frame_parameters(self):
        return self.__hardware_source.get_record_frame_parameters().as_dict()

    def get_frame_parameters_for_profile_by_index(self, profile_index: int) -> dict:
        return self.__hardware_source.get_frame_parameters(profile_index).as_dict()

    def set_frame_parameters(self, frame_parameters: dict) -> None:
        self.__hardware_source.set_current_frame_parameters(self.__hardware_source.get_frame_parameters_from_dict(frame_parameters))

    # TODO: deprecate this method. user should pass record parameters each time record is started.
    def set_record_frame_parameters(self, frame_parameters):
        self.__hardware_source.set_record_frame_parameters(self.__hardware_source.get_frame_parameters_from_dict(frame_parameters))

    def set_frame_parameters_for_profile_by_index(self, profile_index: int, frame_parameters: dict) -> None:
        self.__hardware_source.set_frame_parameters(profile_index, self.__hardware_source.get_frame_parameters_from_dict(frame_parameters))

    def start_playing(self, frame_parameters: dict=None, channels_enabled: typing.List[bool]=None) -> None:
        if frame_parameters:
            self.__hardware_source.set_current_frame_parameters(self.__hardware_source.get_frame_parameters_from_dict(frame_parameters))
        if channels_enabled is not None:
            for channel_index, channel_enabled in enumerate(channels_enabled):
                self.__hardware_source.set_channel_enabled(channel_index, channel_enabled)
        self.__hardware_source.start_playing()

    def stop_playing(self) -> None:
        self.__hardware_source.stop_playing()

    def abort_playing(self) -> None:
        self.__hardware_source.abort_playing()

    @property
    def is_playing(self) -> bool:
        return self.__hardware_source.is_playing

    def start_recording(self, frame_parameters: dict=None, channels_enabled: typing.List[bool]=None):
        if frame_parameters is not None:
            self.__hardware_source.set_record_frame_parameters(self.__hardware_source.get_frame_parameters_from_dict(frame_parameters))
        if channels_enabled is not None:
            for channel_index, channel_enabled in enumerate(channels_enabled):
                self.__hardware_source.set_channel_enabled(channel_index, channel_enabled)
        self.__hardware_source.start_recording()

    def abort_recording(self) -> None:
        self.__hardware_source.abort_recording()

    @property
    def is_recording(self) -> bool:
        return self.__hardware_source.is_recording

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
        if frame_parameters:
            self.__hardware_source.set_record_frame_parameters(self.__hardware_source.get_frame_parameters_from_dict(frame_parameters))
        if channels_enabled is not None:
            for channel_index, channel_enabled in enumerate(channels_enabled):
                self.__hardware_source.set_channel_enabled(channel_index, channel_enabled)
        self.__hardware_source.start_recording()
        data_elements = self.__hardware_source.get_next_data_elements_to_finish(timeout)
        return [HardwareSourceModule.convert_data_element_to_data_and_metadata(data_element) for data_element in data_elements]

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
        return RecordTask(self.__hardware_source, frame_parameters, channels_enabled)

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
        return ViewTask(self.__hardware_source, frame_parameters, channels_enabled, buffer_size)

    def grab_next_to_finish(self, timeout: float=None) -> DataAndMetadata.DataAndMetadata:
        """Grabs the next frame to finish and returns it as data and metadata.

        .. versionadded:: 1.0

        :param timeout: The timeout in seconds. Pass None to use default.
        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`

        If the view is not already started, it will be started automatically.

        Scriptable: Yes
        """
        self.start_playing()
        data_elements = self.__hardware_source.get_next_data_elements_to_finish(timeout)
        return [HardwareSourceModule.convert_data_element_to_data_and_metadata(data_element) for data_element in data_elements]

    def grab_next_to_start(self, frame_parameters: dict=None, channels_enabled: typing.List[bool]=None, timeout: float=None) -> DataAndMetadata.DataAndMetadata:
        self.start_playing(frame_parameters, channels_enabled)
        data_elements = self.__hardware_source.get_next_data_elements_to_start(timeout)
        return [HardwareSourceModule.convert_data_element_to_data_and_metadata(data_element) for data_element in data_elements]

    def execute_command(self, command, args_str, kwargs_str):
        args = pickle.loads(args_str)
        kwargs = pickle.loads(kwargs_str)
        result = getattr(self.__hardware_source, command)(*args, **kwargs)
        result_str = pickle.dumps(result)
        return result_str

    def get_property_as_float(self, name):
        return float(self.__hardware_source.get_property(name))

    def set_property_as_float(self, name, value):
        self.__hardware_source.set_property(name, float(value))

    def get_property_as_int(self, name):
        return int(self.__hardware_source.get_property(name))

    def set_property_as_int(self, name, value):
        self.__hardware_source.set_property(name, int(value))

    def get_property_as_bool(self, name):
        return bool(self.__hardware_source.get_property(name))

    def set_property_as_bool(self, name, value):
        self.__hardware_source.set_property(name, bool(value))

    def get_property_as_str(self, name):
        return str(self.__hardware_source.get_property(name))

    def set_property_as_str(self, name, value):
        self.__hardware_source.set_property(name, str(value))

    def get_property_as_float_point(self, name):
        return tuple(Geometry.FloatPoint.make(self.__hardware_source.get_property(name)))

    def set_property_as_float_point(self, name, value):
        self.__hardware_source.set_property(name, tuple(Geometry.FloatPoint.make(value)))


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

    release = ["close", "set_control_output", "get_control_output", "get_control_state", "get_property_as_float", "set_property_as_float",
        "get_property_as_int", "set_property_as_int", "get_property_as_bool", "set_property_as_bool", "get_property_as_str",
        "set_property_as_str", "get_property_as_float_point", "set_property_as_float_point"]

    def __init__(self, instrument):
        self.__instrument = instrument

    def close(self) -> None:
        pass

    @property
    def specifier(self):
        return ObjectSpecifier("instrument", object_id=self.__instrument.instrument_id)

    def set_control_output(self, name: str, value: float, options: dict=None) -> None:
        """Set the value of a control asynchronously.

        :param name: The name of the control (string).
        :param value: The control value (float).
        :param options: A dict of custom options to pass to the instrument for setting the value.

        Options are:
            value_type: local, delta, output. output is default.
            confirm, confirm_tolerance_factor, confirm_timeout: confirm value gets set.
            inform: True to keep dependent control outputs constant by adjusting their internal values. False is
            default.

        Default value of confirm is False. Default confirm_tolerance_factor is 0.02. Default confirm_timeout is 16.0
        (seconds).

        Raises exception if control with name doesn't exist.

        Raises TimeoutException if confirm is True and timeout occurs.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__instrument.set_control_output(name, value, options)

    def get_control_output(self, name: str) -> float:
        """Return the value of a control.

        :return: The control value.

        Raises exception if control with name doesn't exist.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__instrument.get_control_output(name)

    def get_control_state(self, name: str) -> str:
        # return None if value does not exist
        return self.__instrument.get_control_state(name)

    def get_property_as_float(self, name: str) -> float:
        """Return the value of a float property.

        :return: The property value (float).

        Raises exception if property with name doesn't exist.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return float(self.__instrument.get_property(name))

    def set_property_as_float(self, name: str, value: float) -> None:
        """Set the value of a float property.

        :param name: The name of the property (string).
        :param value: The property value (float).

        Raises exception if property with name doesn't exist.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__instrument.set_property(name, float(value))

    def get_property_as_int(self, name:str ) -> int:
        return int(self.__instrument.get_property(name))

    def set_property_as_int(self, name: str, value: int) -> None:
        self.__instrument.set_property(name, int(value))

    def get_property_as_bool(self, name: str) -> bool:
        return bool(self.__instrument.get_property(name))

    def set_property_as_bool(self, name: str, value: bool) -> None:
        self.__instrument.set_property(name, bool(value))

    def get_property_as_str(self, name: str) -> str:
        return str(self.__instrument.get_property(name))

    def set_property_as_str(self, name: str, value: str) -> None:
        self.__instrument.set_property(name, str(value))

    def get_property_as_float_point(self, name: str) -> Geometry.FloatPoint:
        return tuple(Geometry.FloatPoint.make(self.__instrument.get_property(name)))

    def set_property_as_float_point(self, name: str, value: Geometry.FloatPoint) -> None:
        self.__instrument.set_property(name, tuple(Geometry.FloatPoint.make(value)))

    def get_property(self, name: str):
        # deprecated
        return self.get_property_as_float(name)

    def set_property(self, name: str, value) -> None:
        # deprecated
        self.set_property_as_float(name, value)

    def execute_command(self, command, args_str, kwargs_str):
        args = pickle.loads(args_str)
        kwargs = pickle.loads(kwargs_str)
        result = getattr(self.__instrument, command)(*args, **kwargs)
        result_str = pickle.dumps(result)
        return result_str


class Library:

    release = ["data_item_count", "data_items", "create_data_item", "create_data_item_from_data", "create_data_item_from_data_and_metadata",
        "get_or_create_data_group", "data_ref_for_data_item", "get_data_item_for_hardware_source"]

    def __init__(self, document_model: DocumentModelModule.DocumentModel):
        self.__document_model = document_model

    @property
    def _document_model(self) -> DocumentModelModule.DocumentModel:
        return self.__document_model

    @property
    def specifier(self):
        return ObjectSpecifier("library")

    @property
    def data_item_count(self) -> int:
        """Return the data item count.

        :return: The number of data items.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return len(self.__document_model.data_items)

    @property
    def data_items(self) -> typing.List[DataItem]:
        """Return the list of data items.

        :return: The list of :py:class:`nion.swift.Facade.DataItem` objects.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return [DataItem(data_item) for data_item in self.__document_model.data_items]

    def create_data_item(self, title: str=None) -> DataItem:
        """Create an empty data item in the library.

        :param title: The title of the data item (optional).
        :return: The new :py:class:`nion.swift.Facade.DataItem` object.
        :rtype: :py:class:`nion.swift.Facade.DataItem`

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        data_item = DataItemModule.DataItem()
        data_item.append_data_source(DataItemModule.BufferedDataSource())
        if title is not None:
            data_item.title = title
        self.__document_model.append_data_item(data_item)
        return DataItem(data_item)

    def create_data_item_from_data(self, data: numpy.ndarray, title: str=None) -> DataItem:
        """Create a data item in the library from an ndarray.

        For efficiency, this method will directly use the data object without copying it. This means that the data
        should be considered to be owned by the library once this call is made. Changing the data outside of this API
        will result in undefined behavior.

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
        data_shape_and_dtype = Image.dimensional_shape_from_data(data), data.dtype
        intensity_calibration = CalibrationModule.Calibration()
        dimensional_calibrations = list()
        for _ in data_shape_and_dtype[0]:
            dimensional_calibrations.append(CalibrationModule.Calibration())
        metadata = dict()
        timestamp = datetime.datetime.utcnow()
        data_and_metadata = DataAndMetadata.DataAndMetadata.from_data(data, intensity_calibration, dimensional_calibrations, metadata, timestamp)
        return self.create_data_item_from_data_and_metadata(data_and_metadata, title)

    def create_data_item_from_data_and_metadata(self, data_and_metadata: DataAndMetadata.DataAndMetadata, title: str=None) -> DataItem:
        """Create a data item in the library from a data and metadata object.

        For efficiency, this method will directly use the data within the data_and_metadata object without copying
        it. This means that the data should be considered to be owned by the library once this call is made. Changing
        the data outside of this API will result in undefined behavior.

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
        data_item = DataItemModule.DataItem()
        if title is not None:
            data_item.title = title
        buffered_data_source = DataItemModule.BufferedDataSource(data_and_metadata.data)
        buffered_data_source.set_metadata(data_and_metadata.metadata)
        buffered_data_source.set_intensity_calibration(data_and_metadata.intensity_calibration)
        buffered_data_source.set_dimensional_calibrations(data_and_metadata.dimensional_calibrations)
        buffered_data_source.created = data_and_metadata.timestamp
        data_item.append_data_source(buffered_data_source)
        self.__document_model.append_data_item(data_item)
        return DataItem(data_item)

    def get_or_create_data_group(self, title: str) -> DataGroup:
        """Get (or create) a data group.

        :param title: The title of the data group.
        :return: The new :py:class:`nion.swift.Facade.DataGroup` object.
        :rtype: :py:class:`nion.swift.Facade.DataGroup`

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return DataGroup(self.__document_model.get_or_create_data_group(title))

    def data_ref_for_data_item(self, data_item: DataItem):

        class DataRef:

            def __init__(self, document_model, data_item):
                self.__document_model = document_model
                self.__data_item = data_item

            def __enter__(self):
                self.__document_model.begin_data_item_transaction(self.__data_item._data_item)
                self.__data_item._data_item.maybe_data_source.increment_data_ref_count()
                return self

            def __exit__(self, type, value, traceback):
                self.__data_item._data_item.maybe_data_source.decrement_data_ref_count()
                self.__document_model.end_data_item_transaction(self.__data_item._data_item)

            @property
            def data(self):
                return self.__data_item.data

            @data.setter
            def data(self, data):
                with self.__data_item._data_item.maybe_data_source.data_ref() as data_ref:
                    data_ref.data = data

            def __setitem__(self, key, value):
                with self.__data_item._data_item.maybe_data_source.data_ref() as data_ref:
                    data_ref.data[key] = value
                    data_ref.data_updated()

        return DataRef(self.__document_model, data_item)

    def get_data_item_for_hardware_source(self, hardware_source, channel_id: str=None, processor_id: str=None, create_if_needed: bool=False) -> DataItem:
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
        assert hardware_source is not None
        hardware_source_id = hardware_source._hardware_source.hardware_source_id
        document_model = self._document_model
        data_item_reference_key = document_model.make_data_item_reference_key(hardware_source_id, channel_id, processor_id)
        data_item_reference = document_model.get_data_item_reference(data_item_reference_key)
        data_item = data_item_reference.data_item
        if data_item is None and create_if_needed:
            data_item = DataItemModule.DataItem()
            data_item.append_data_source(DataItemModule.BufferedDataSource())
            document_model.append_data_item(data_item)
            document_model.setup_channel(data_item_reference_key, data_item)
            data_item.session_id = document_model.session_id
            data_item = document_model.get_data_item_reference(data_item_reference_key).data_item
        return DataItem(data_item) if data_item else None


class DocumentController:

    release = ["library", "all_display_panels", "get_display_panel_by_id", "display_data_item", "target_display", "target_data_item",
        "show_get_string_message_box", "show_confirmation_message_box", "queue_task", "add_data", "create_data_item_from_data",
        "create_data_item_from_data_and_metadata", "get_or_create_data_group"]

    def __init__(self, document_controller):
        self.__document_controller = document_controller

    @property
    def specifier(self):
        return ObjectSpecifier("document_controller", self.__document_controller.uuid)

    @property
    def _document_controller(self):
        return self.__document_controller

    @property
    def library(self) -> Library:
        """Return the library object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return Library(self.__document_controller.document_model)

    @property
    def all_display_panels(self) -> typing.List[DisplayPanel]:
        """Return the list of display panels currently visible.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return [DisplayPanel(display_panel) for display_panel in self.__document_controller.workspace_controller.display_panels]

    def get_display_panel_by_id(self, identifier: str) -> DisplayPanel:
        """Return display panel with the identifier.

        .. versionadded:: 1.0

        Status: Provisional
        Scriptable: Yes
        """
        display_panel = next(
            (display_panel for display_panel in self.__document_controller.workspace_controller.display_panels if
            display_panel.identifier.lower() == identifier.lower()), None)
        return DisplayPanel(display_panel) if display_panel else None

    def display_data_item(self, data_item: DataItem, source_display_panel=None, source_data_item=None):
        """Display a new data item and gives it keyboard focus. Uses existing display if it is already displayed.

        .. versionadded:: 1.0

        Status: Provisional
        Scriptable: Yes
        """
        for display_panel in self.__document_controller.workspace_controller.display_panels:
            if display_panel.data_item == data_item._data_item:
                display_panel.request_focus()
                return DisplayPanel(display_panel)
        result_display_panel = self.__document_controller.next_result_display_panel()
        if result_display_panel:
            result_display_panel.set_displayed_data_item(data_item._data_item)
            result_display_panel.request_focus()
        return DisplayPanel(result_display_panel)

    @property
    def target_display_panel(self):
        raise AttributeError()

    @property
    def target_display(self) -> Display:
        return Display(self.__document_controller.selected_display_specifier.display)

    @property
    def target_data_item(self) -> DataItem:
        return DataItem(self.__document_controller.selected_display_specifier.data_item)

    def create_task_context_manager(self, title, task_type):
        return self.__document_controller.create_task_context_manager(title, task_type)

    def show_get_string_message_box(self, caption: str, text: str, accepted_fn, rejected_fn=None, accepted_text: str=None, rejected_text: str=None) -> None:
        workspace = self.__document_controller.workspace_controller
        workspace.pose_get_string_message_box(caption, text, accepted_fn, rejected_fn, accepted_text, rejected_text)

    def show_confirmation_message_box(self, caption: str, accepted_fn, rejected_fn=None, accepted_text: str=None, rejected_text: str=None, display_rejected: str=False) -> None:
        workspace = self.__document_controller.workspace_controller
        workspace.pose_confirmation_message_box(caption, accepted_fn, rejected_fn, accepted_text, rejected_text, display_rejected)

    def queue_task(self, fn) -> None:
        self.__document_controller.queue_task(fn)

    def add_data(self, data: numpy.ndarray, title: str=None) -> DataItem:
        """Create a data item in the library from data.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:meth:`nion.swift.Facade.Library.create_data_item_from_data` instead.

        Scriptable: No
        """
        return self.create_data_item_from_data(data, title)

    def create_data_item_from_data(self, data: numpy.ndarray, title: str=None) -> DataItem:
        """Create a data item in the library from data.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use library.create_data_item_from_data instead.

        Scriptable: No
        """
        return DataItem(self.__document_controller.add_data(data, title))

    def create_data_item_from_data_and_metadata(self, data_and_metadata: DataAndMetadata.DataAndMetadata, title: str=None) -> DataItem:
        """Create a data item in the library from the data and metadata.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use library.create_data_item_from_data_and_metadata instead.

        Scriptable: No
        """
        data_item = DataItemModule.DataItem()
        if title is not None:
            data_item.title = title
        buffered_data_source = DataItemModule.BufferedDataSource(data_and_metadata.data)
        buffered_data_source.set_metadata(data_and_metadata.metadata)
        buffered_data_source.set_intensity_calibration(data_and_metadata.intensity_calibration)
        buffered_data_source.set_dimensional_calibrations(data_and_metadata.dimensional_calibrations)
        buffered_data_source.created = data_and_metadata.timestamp
        data_item.append_data_source(buffered_data_source)
        self.__document_controller.document_model.append_data_item(data_item)
        return DataItem(data_item)

    def get_or_create_data_group(self, title: str) -> DataGroup:
        """Get (or create) a data group.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use library.create_data_item_from_data instead.

        Scriptable: No
        """
        return DataGroup(self.__document_controller.document_model.get_or_create_data_group(title))


class Application:

    release = ["library", "document_controllers"]

    def __init__(self, application):
        self.__application = application

    @property
    def _application(self):
        return self.__application

    @property
    def specifier(self):
        return ObjectSpecifier("library")

    @property
    def library(self) -> Library:
        """Return the library object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return Library(self.__application.document_controllers[0].document_model)

    @property
    def document_controllers(self) -> typing.List[DocumentController]:
        """Return the document controllers.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return [DocumentController(document_controller) for document_controller in self.__application.document_controllers]


class DataAndMetadataIOHandlerInterface:
    """An interface for an IO handler delegate. Implement each of the methods and properties, as required."""

    @property
    def io_hander_id(self):
        """Unique identifier of the IO handler. This will be used to uniquely identify this IO handler.

        An example identifier might be "my.company.example.1".

        :rtype: str

        .. versionadded:: 1.0
        """
        raise AttributeError()

    @property
    def io_hander_name(self):
        """Name of the IO handler. This will appear to the user.

        :rtype: str

        .. versionadded:: 1.0
        """
        raise AttributeError()

    @property
    def io_handler_extensions(self):
        """List of extensions handled by the IO handler.

        :rtype: list of str

        .. versionadded:: 1.0
        """
        raise AttributeError()

    def read_data_and_metadata(self, extension, file_path):
        """Read data from the file_path and return it in a data_and_metadata object.

        .. versionadded:: 1.0

        :param extension: The extension of the file_path, e.g. "tif".
        :param file_path: The path to the file.
        :return: The data and metadata that was read.
        :rtype: :py:class:`DataAndMetadata`
        """
        raise NotImplementedError()

    def can_write_data_and_metadata(self, data_and_metadata, extension):
        """Return whether the data_and_metadata can be written to a file with the given extension.

        .. versionadded:: 1.0

        :param data_and_metadata: The data to write.
        :type data_and_metadata: :py:class:`DataAndMetadata`
        :param extension: The extension of the file, e.g. "tif".
        :return: Whether the file can be written.
        :rtype: boolean

        Implementers should not ask for data from the data_and_metadata object as this may affect performance.
        """
        raise NotImplementedError()

    def write_data_and_metadata(self, data_and_metadata, file_path, extension):
        """Write the data_and_metadata to the file_path with the given extension.

        .. versionadded:: 1.0

        :param data_and_metadata: A :py:class:`DataAndMetadata` object.
        :param file_path: The path to the file.
        :param extension: The extension of the file, e.g. "tif".
        """
        raise NotImplementedError()


class API_1:
    """An interface to Nion Swift.

    This class cannot be instantiated directly. Use :samp:`api_broker.get_api(version)` to get access an instance of
    this class.
    """

    # GOALS
    # Provide an API for any plug-in available
    # Provide an API for anything the user can do
    # Provide programmatic access for creating new extensions

    # RULES
    # clients should not be required to directly instantiate or subclass any classes
    # versions should be passed wherever a sub-system might be versioned separately

    # NAMING
    # add, insert, remove (not append)

    # MIGRATING
    # Allowed: add keyword arguments to end of existing methods as long as the default doesn't change functionality.
    # Allowed: add methods as long as they are optional.

    release = ["create_calibration", "create_data_and_metadata", "create_data_and_metadata_from_data", "create_data_and_metadata_io_handler",
        "create_menu_item", "create_hardware_source", "create_panel", "get_all_hardware_source_ids", "get_all_instrument_ids",
        "get_hardware_source_by_id", "get_instrument_by_id", "application", "library", "queue_task"]

    def __init__(self, ui_version, app):
        super().__init__()
        self.__ui_version = ui_version
        self.__app = app

    def create_calibration(self, offset: float=None, scale: float=None, units: str=None) -> CalibrationModule.Calibration:
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
        return CalibrationModule.Calibration(offset, scale, units)

    def create_data_and_metadata(self, data: numpy.ndarray, intensity_calibration: CalibrationModule.Calibration=None,
                                 dimensional_calibrations: typing.List[CalibrationModule.Calibration]=None, metadata: dict=None, timestamp: str=None) -> DataAndMetadata.DataAndMetadata:
        """Create a data_and_metadata object from data.

        :param data: an ndarray of data.
        :param intensity_calibration: An optional calibration object.
        :param dimensional_calibrations: An optional list of calibration objects.
        :param metadata: A dict of metadata.
        :param timestamp: A datetime object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        data_shape_and_dtype = Image.dimensional_shape_from_data(data), data.dtype
        if intensity_calibration is None:
            intensity_calibration = CalibrationModule.Calibration()
        if dimensional_calibrations is None:
            dimensional_calibrations = list()
            for _ in data_shape_and_dtype[0]:
                dimensional_calibrations.append(CalibrationModule.Calibration())
        if metadata is None:
            metadata = dict()
        timestamp = timestamp if timestamp else datetime.datetime.utcnow()
        return DataAndMetadata.DataAndMetadata.from_data(data, intensity_calibration, dimensional_calibrations, metadata, timestamp)

    def create_data_and_metadata_from_data(self, data: numpy.ndarray, intensity_calibration: CalibrationModule.Calibration=None, dimensional_calibrations: typing.List[CalibrationModule.Calibration]=None, metadata: dict=None, timestamp: str=None) -> DataAndMetadata.DataAndMetadata:
        """Create a data_and_metadata object from data.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use api.create_data_and_metadata instead.

        Scriptable: No
        """
        return self.create_data_and_metadata(data, intensity_calibration, dimensional_calibrations, metadata, timestamp)

    def create_data_and_metadata_io_handler(self, io_handler_delegate):
        """Create an I/O handler that reads and writes a single data_and_metadata.

        :param io_handler_delegate: A delegate object :py:class:`DataAndMetadataIOHandlerInterface`

        .. versionadded:: 1.0

        Scriptable: No
        """
        class DelegateIOHandler(ImportExportManager.ImportExportHandler):
            def __init__(self):
                super().__init__(io_handler_delegate.io_handler_id, io_handler_delegate.io_handler_name, io_handler_delegate.io_handler_extensions)

            def read_data_elements(self, ui, extension, file_path):
                data_and_metadata = io_handler_delegate.read_data_and_metadata(extension, file_path)
                data_element = dict()
                data_element["data"] = data_and_metadata.data
                dimensional_calibrations = list()
                for calibration in data_and_metadata.dimensional_calibrations:
                    dimensional_calibrations.append({ "offset": calibration.offset, "scale": calibration.scale, "units": calibration.units })
                data_element["spatial_calibrations"] = dimensional_calibrations
                calibration = data_and_metadata.intensity_calibration
                data_element["intensity_calibration"] = { "offset": calibration.offset, "scale": calibration.scale, "units": calibration.units }
                data_element["properties"] = data_and_metadata.metadata.get("hardware_source", dict())
                return [data_element]

            def can_write(self, data_and_metadata, extension):
                return io_handler_delegate.can_write_data_and_metadata(data_and_metadata, extension)

            def write(self, ui, data_item, file_path, extension):
                data_and_metadata = data_item.maybe_data_source.data_and_metadata
                data = data_and_metadata.data
                if data is not None:
                    io_handler_delegate.write_data_and_metadata(data_and_metadata, file_path, extension)

        class IOHandlerReference:

            def __init__(self):
                self.__io_handler_delegate = io_handler_delegate
                self.__io_handler = DelegateIOHandler()
                ImportExportManager.ImportExportManager().register_io_handler(self.__io_handler)

            def __del__(self):
                self.close()

            def close(self):
                if self.__io_handler_delegate:
                    io_handler_delegate_close_fn = getattr(self.__io_handler_delegate, "close", None)
                    if io_handler_delegate_close_fn:
                       io_handler_delegate_close_fn()
                    ImportExportManager.ImportExportManager().unregister_io_handler(self.__io_handler)
                    self.__io_handler_delegate = None

        return IOHandlerReference()

    def create_menu_item(self, menu_item_handler):

        # the build_menus function will be called whenever a new document window is created.
        # it will be passed the document_controller.
        def build_menus(document_controller):
            menu_id = getattr(menu_item_handler, "menu_id", None)
            if menu_id is None:
                menu_id = "script_menu"
                menu_name = _("Scripts")
                menu_before_id = "window_menu"
            else:
                menu_name = getattr(menu_item_handler, "menu_name", None)
                menu_before_id = getattr(menu_item_handler, "menu_before_id", None)
            if menu_name is not None and menu_before_id is not None:
                menu = document_controller.get_or_create_menu(menu_id, menu_name, menu_before_id)
            else:
                menu = document_controller.get_menu(menu_id)
            key_sequence = getattr(menu_item_handler, "menu_item_key_sequence", None)
            if menu:
                facade_document_controller = DocumentController(document_controller)
                menu.add_menu_item(menu_item_handler.menu_item_name, lambda: menu_item_handler.menu_item_execute(
                    facade_document_controller), key_sequence=key_sequence)

        class MenuItemReference:

            def __init__(self, app):
                self.__menu_item_handler = menu_item_handler
                app.register_menu_handler(build_menus)

            def __del__(self):
                self.close()

            def close(self):
                if self.__menu_item_handler:
                    menu_item_handler_close_fn = getattr(self.__menu_item_handler, "close", None)
                    if menu_item_handler_close_fn:
                       menu_item_handler_close_fn()
                    ApplicationModule.app.unregister_menu_handler(build_menus)
                    self.__menu_item_handler = None

        return MenuItemReference(self.__app)


    def create_hardware_source(self, hardware_source_delegate):

        class FacadeAcquisitionTask(HardwareSourceModule.AcquisitionTask):

            def __init__(self):
                super().__init__(True)

            def _start_acquisition(self) -> bool:
                if not super()._start_acquisition():
                    return False
                hardware_source_delegate.start_acquisition()
                return True

            def _acquire_data_elements(self):
                data_and_metadata = hardware_source_delegate.acquire_data_and_metadata()
                data_element = {
                    "version": 1,
                    "data": data_and_metadata.data,
                    "properties": {
                        "hardware_source_name": hardware_source_delegate.hardware_source_name,
                        "hardware_source_id": hardware_source_delegate.hardware_source_id,
                    }
                }
                return [data_element]

            def _stop_acquisition(self) -> None:
                hardware_source_delegate.stop_acquisition()

        class FacadeHardwareSource(HardwareSourceModule.HardwareSource):

            def __init__(self):
                super().__init__(hardware_source_delegate.hardware_source_id, hardware_source_delegate.hardware_source_name)
                self.add_data_channel()

            def _create_acquisition_view_task(self) -> FacadeAcquisitionTask:
                return FacadeAcquisitionTask()

        class HardwareSourceReference:

            def __init__(self):
                self.__hardware_source_delegate = hardware_source_delegate
                self.__hardware_source = FacadeHardwareSource()
                HardwareSourceModule.HardwareSourceManager().register_hardware_source(self.__hardware_source)

            def __del__(self):
                self.close()

            def close(self):
                pass  # closed automatically during application shutdown

        return HardwareSourceReference()

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

        panel_id = panel_delegate.panel_id
        panel_name = panel_delegate.panel_name
        panel_positions = getattr(panel_delegate, "panel_positions", ["left", "right"])
        panel_position = getattr(panel_delegate, "panel_position", "none")
        properties = getattr(panel_delegate, "panel_properties", None)

        workspace_manager = Workspace.WorkspaceManager()

        def create_facade_panel(document_controller, panel_id, properties):
            panel = Panel(document_controller, panel_id, properties)
            ui = UserInterface(self.__ui_version, document_controller.ui)
            document_controller = DocumentController(document_controller)
            panel.widget = panel_delegate.create_panel_widget(ui, document_controller)._widget
            return panel

        class PanelReference:

            def __init__(self):
                self.__panel_delegate = panel_delegate
                workspace_manager.register_panel(create_facade_panel, panel_id, panel_name, panel_positions, panel_position, properties)

            def __del__(self):
                self.close()

            def close(self):
                if self.__panel_delegate:
                    panel_delegate_close_fn = getattr(self.__panel_delegate, "close", None)
                    if panel_delegate_close_fn:
                       panel_delegate_close_fn()
                    workspace_manager.unregister_panel(panel_id)
                    self.__panel_delegate = None

        return PanelReference()

    def create_unary_operation(self, unary_operation_delegate):
        return None

    def get_all_hardware_source_ids(self) -> typing.List[str]:
        return HardwareSourceModule.HardwareSourceManager().get_all_hardware_source_ids()

    def get_all_instrument_ids(self) -> typing.List[str]:
        return HardwareSourceModule.HardwareSourceManager().get_all_instrument_ids()

    def get_hardware_source_by_id(self, hardware_source_id: str, version: str):
        """Return the hardware source API matching the hardware_source_id and version.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        actual_version = "1.0.0"
        if Utility.compare_versions(version, actual_version) > 0:
            raise NotImplementedError("Hardware API requested version %s is greater than %s." % (version, actual_version))
        hardware_source = HardwareSourceModule.HardwareSourceManager().get_hardware_source_for_hardware_source_id(hardware_source_id)
        return HardwareSource(hardware_source)

    def get_instrument_by_id(self, instrument_id: str, version: str) -> Instrument:
        actual_version = "1.0.0"
        if Utility.compare_versions(version, actual_version) > 0:
            raise NotImplementedError("Hardware API requested version %s is greater than %s." % (version, actual_version))
        instrument = HardwareSourceModule.HardwareSourceManager().get_instrument_by_id(instrument_id)
        return Instrument(instrument)

    @property
    def application(self) -> Application:
        """Return the application object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return Application(self.__app)

    @property
    def library(self) -> Library:
        """Return the library object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return Library(self.__app.document_controllers[0].document_model)

    def resolve_object_specifier(self, d):
        return ObjectSpecifier.resolve(d)

    # provisional
    def queue_task(self, fn) -> None:
        self.__app.document_controllers[0].queue_task(fn)

    def raise_requirements_exception(self, reason) -> None:
        raise PlugInManager.RequirementsException(reason)


def _get_api_with_app(version: str, ui_version: str, app: ApplicationModule.Application) -> API_1:
    actual_version = "1.0.0"
    if Utility.compare_versions(version, actual_version) > 0:
        raise NotImplementedError("API requested version %s is greater than %s." % (version, actual_version))
    return API_1(ui_version, app)


def get_api(version: str, ui_version: str) -> API_1:
    """Get a versioned interface matching the given version and ui_version.

    version is a string in the form "1.0.2".
    """
    return _get_api_with_app(version, ui_version, ApplicationModule.app)


# this will be called when Facade is imported. this allows the plug-in manager access to the api_broker.
# for this to work, Facade must be imported early in the startup process.
def initialize():
    PlugInManager.register_api_broker_fn(get_api)
