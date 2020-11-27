"""
    A versioned interface to Swift.

    on_xyz methods are used when a callback needs a return value and has only a single listener.

    events are used when a callback is optional and may have multiple listeners.

    Versions numbering follows semantic version numbering: http://semver.org/
       * Backward compatible changes increment minor revision
       * Incompatible changes increment major revision
       * Ideally old API can be implemented in terms of new API

    Maintain backwards compatibility:
       * Prefer backwards compatibility rather than new API
       * Breaking backward compatibility will cause clients to defer upgrading.
       * Behavior with same parameters should not change.
       * Weakened preconditions or strengthened post conditions are ok.
       * Write strong tests at introduction to codify as many assumptions as possible.
       * Deprecation is a warning that a part of the API will not be available in the future.
       * Delegation is the reimplementation of backwards compatible code in terms of new code.

    Plan for evolution:
       * Choose objects, methods, and properties that can be maintained in the long term.
       * Avoid API versioning when possible as this limits backward compatibility.
       * Only expose what is absolutely necessary for functionality.
       * Keep API as small as possible.

    When are new objects needed?
       * Items in containers, e.g. Graphic items within the Data Item
       * If they represent typing information, e.g. a Data Item vs . Display Item

    Notes:
       * API (application programming interface) is a client calling into this application.
       * SPI (service programming interface) is this application calling into a client.
"""

# standard libraries
import contextlib
import copy
import collections
import datetime
import gettext
import numbers
import pickle
import threading
import typing
import uuid as uuid_module
import weakref

# third party libraries
import numpy

# local libraries
from nion.data import Calibration as CalibrationModule
from nion.data import DataAndMetadata
from nion.swift import Application as ApplicationModule
from nion.swift import DisplayPanel as DisplayPanelModule
from nion.swift import Panel as PanelModule
from nion.swift import Workspace
from nion.swift.model import ApplicationData
from nion.swift.model import DataStructure as DataStructureModule
from nion.swift.model import DataItem as DataItemModule
from nion.swift.model import DisplayItem as DisplayItemModule
from nion.swift.model import DocumentModel as DocumentModelModule
from nion.swift.model import Graphics
from nion.swift.model import HardwareSource as HardwareSourceModule
from nion.swift.model import ImportExportManager
from nion.swift.model import Metadata
from nion.swift.model import Persistence
from nion.swift.model import PlugInManager
from nion.swift.model import Symbolic
from nion.swift.model import Utility
from nion.ui import CanvasItem as CanvasItemModule
from nion.ui import Declarative
from nion.utils import Geometry

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController

__all__ = ["get_api"]


_ = gettext.gettext


NormIntervalType = typing.Tuple[float, float]
NormRectangleType = typing.Tuple[typing.Tuple[float, float], typing.Tuple[float, float]]
NormPointType = typing.Tuple[float, float]
NormSizeType = typing.Tuple[float, float]
NormVectorType = typing.Tuple[NormPointType, NormPointType]


# ideally these can be alphabetical, but some orders may need to be switched to ensure that
# a class is defined before it is used as a type annotation.
api_public = [
    "Graphic", "DataItem", "DisplayPanel", "Display", "DataGroup",
    "Library", "DocumentWindow", "Application", "API_1",
]
hardware_source_public = [
    "RecordTask", "ViewTask", "HardwareSource", "Instrument",
]
nionlib_public = [
    "Graphic", "DataItem", "DisplayPanel", "Display", "DataGroup",
    "Library", "DocumentWindow", "Application", "API_1",
    "HardwareSource", "Instrument",
]
alias = {"API_1": "API"}


class SharedInstance(type):
    """A metadclass for API objects to return the same instance if the underlying object is the same.

    This ensures that API objects using this metaclass can be compared for equality.
    """
    def __init__(cls, name, bases, d):
        super(SharedInstance, cls).__init__(name, bases, d)
        cls.__lock = threading.RLock()
        cls.instances = dict()

    def __call__(cls, *args, **kw):
        assert len(args) == 1

        def remove_instance_ref(instance_ref):
            with cls.__lock:
                cls.instances = { k: v for k, v in cls.instances.items() if v != instance_ref }

        with cls.__lock:
            instance_ref = cls.instances.get(args[0])
            if not instance_ref:
                instance = super(SharedInstance, cls).__call__(*args, **kw)
                instance_ref = weakref.ref(instance, remove_instance_ref)
                cls.instances[args[0]] = instance_ref
            return instance_ref()


class ObjectSpecifier:

    def __init__(self, object_type, object_uuid=None, object_id=None):
        self.object_type = object_type
        self.object_uuid = str(object_uuid) if object_uuid else None
        self.object_id = str(object_id) if object_id else None

    @property
    def rpc_dict(self):
        d = {"version": 1, "type": self.object_type}
        if self.object_uuid:
            d["uuid"] = self.object_uuid
        if self.object_id:
            d["id"]  = self.object_id
        return d

    @classmethod
    def resolve(cls, d):
        if d is None:
            return get_api("~1.0", "~1.0")
        object_type = d.get("type")
        object_uuid_str = d.get("uuid")
        object_id = d.get("id")
        object_uuid = uuid_module.UUID(object_uuid_str) if object_uuid_str else None
        document_model = ApplicationModule.app.document_controllers[0].document_model
        if object_type == "application":
            return Application(ApplicationModule.app)
        elif object_type == "library":
            return Library(document_model)
        elif object_type == "document_controller":
            document_controller = next(iter(filter(lambda x: x.uuid == object_uuid, ApplicationModule.app.document_controllers)), None)
            return DocumentWindow(document_controller) if document_controller else None
        elif object_type == "display_panel":
            for document_controller in ApplicationModule.app.document_controllers:
                display_panel = next(iter(filter(lambda x: x.uuid == object_uuid, document_controller.workspace_controller.display_panels)), None)
                if display_panel:
                    return DisplayPanel(display_panel)
            return None
        elif object_type == "data_item":
            data_item_uuid = uuid_module.UUID(object_uuid_str)
            data_item_specifier = Persistence.PersistentObjectSpecifier(item_uuid=data_item_uuid)
            data_item = document_model.resolve_item_specifier(data_item_specifier)
            return DataItem(typing.cast(DataItemModule.DataItem, data_item)) if data_item else None
        elif object_type == "data_group":
            return DataGroup(document_model.get_data_group_by_uuid(uuid_module.UUID(object_uuid_str)))
        elif object_type in ("region", "graphic"):
            for display_item in document_model.display_items:
                for graphic in display_item.graphics:
                    if graphic.uuid == object_uuid:
                        return Graphic(graphic)
        elif object_type == "display_item":
            for display_item in document_model.display_items:
                if display_item.uuid == object_uuid:
                    return Display(display_item)
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
    def current_item(self):
        return self.__combo_box_widget.current_item

    @current_item.setter
    def current_item(self, value):
        self.__combo_box_widget.current_item = value

    @property
    def current_index(self):
        return self.__combo_box_widget.current_index

    @current_index.setter
    def current_index(self, value):
        self.__combo_box_widget.current_index = value

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

    def request_refocus(self):
        self.__line_edit_widget.request_refocus()

    def select_all(self):
        self.__line_edit_widget.select_all()


class TextEditWidget:

    def __init__(self, ui):
        self.__ui = ui
        self.__text_edit_widget = self.__ui.create_text_edit_widget()

    @property
    def _widget(self):
        return self.__text_edit_widget

    @property
    def text(self):
        return self.__text_edit_widget.text

    @text.setter
    def text(self, value):
        self.__text_edit_widget.text = value

    @property
    def on_editing_finished(self):
        return self.__text_edit_widget.on_editing_finished

    @on_editing_finished.setter
    def on_editing_finished(self, value):
        self.__text_edit_widget.on_editing_finished = value

    def request_refocus(self):
        self.__text_edit_widget.request_refocus()

    def select_all(self):
        self.__text_edit_widget.select_all()

    def append_text(self, text):
        self.__text_edit_widget.append_text(text)

    def insert_text(self, text):
        self.__text_edit_widget.insert_text(text)

    @property
    def selected_text(self):
        return self.__text_edit_widget.selected_text

    @property
    def cursor_position(self):
        return self.__text_edit_widget.cursor_position

    @property
    def selection(self):
        return self.__text_edit_widget.selection

    def clear_selection(self):
        self.__text_edit_widget.clear_selection()

    def move_cursor_position(self, operation, mode=None, n=1):
        self.__text_edit_widget.move_cursor_position(operation, mode, n)


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

class ProgressBarWidget:

    def __init__(self, ui):
        self.__ui = ui
        # pass some sizing to prevent ProgressBar being collapsed by a stretch
        self.__progress_bar_widget = self.__ui.create_progress_bar_widget(properties={"height": 18, "min-width": 64})

    @property
    def _widget(self):
        return self.__progress_bar_widget

    @property
    def value(self):
        return self.__progress_bar_widget.value

    @value.setter
    def value(self, value):
        self.__progress_bar_widget.value = value

    @property
    def minimum(self):
        return self.__progress_bar_widget.minimum

    @minimum.setter
    def minimum(self, value):
        self.__progress_bar_widget.minimum = value

    @property
    def maximum(self):
        return self.__progress_bar_widget.maximum

    @maximum.setter
    def maximum(self, value):
        self.__progress_bar_widget.maximum = value


class UserInterface:

    def __init__(self, ui_version, ui):
        actual_version = "1.0.0"
        if Utility.compare_versions(ui_version, actual_version) > 0:
            raise NotImplementedError("UI API requested version %s is greater than %s." % (ui_version, actual_version))
        self.__ui = ui

    @property
    def _ui(self):
        return self.__ui

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
        raise NotImplementedError()

    def create_tab_widget(self):
        raise NotImplementedError()

    def create_stack_widget(self):
        raise NotImplementedError()

    def create_scroll_area_widget(self):
        raise NotImplementedError()

    def create_combo_box_widget(self, items=None, item_text_getter=None):
        combo_box_widget = ComboBoxWidget(self.__ui)
        combo_box_widget.item_text_getter = item_text_getter
        combo_box_widget.items = items if items is not None else list()
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
        raise NotImplementedError()

    def create_check_box_widget(self, text=None):
        check_box_widget = CheckBoxWidget(self.__ui)
        check_box_widget.text = text
        return check_box_widget

    def create_slider_widget(self):
        raise NotImplementedError()

    def create_text_edit_widget(self, text=None):
        text_edit_widget = TextEditWidget(self.__ui)
        text_edit_widget.text = text
        return text_edit_widget

    def create_progress_bar_widget(self, value=None, minimum=None, maximum=None):
        progress_bar_widget = ProgressBarWidget(self.__ui)
        progress_bar_widget.minimum = minimum if minimum is not None else 0
        progress_bar_widget.maximum = maximum if maximum is not None else 100
        progress_bar_widget.value = value if value is not None else 0
        return progress_bar_widget

    @property
    def data_file_path(self):
        return self.__ui.get_data_location()

    @property
    def document_file_path(self):
        return self.__ui.get_document_location()


class Panel(PanelModule.Panel):

    def __init__(self, document_controller, panel_delegate, panel_id, properties):
        super().__init__(document_controller, panel_id, panel_id)
        self.panel_delegate = panel_delegate

    def close(self):
        if callable(getattr(self.panel_delegate, "close", None)):
            self.panel_delegate.close()
        super().close()


class Graphic(metaclass=SharedInstance):

    release = ["uuid", "type", "label", "graphic_type", "graphic_id", "get_property", "set_property", "region", "mask_xdata_with_shape", "angle", "bounds", "center", "end",
        "interval", "position", "size", "start", "vector", "width"]

    graphic_to_region_type_map = {
        "point-graphic": "point-region",
        "rect-graphic": "rectangle-region",
        "ellipse-graphic": "ellipse-region",
        "line-graphic": "line-region",
        "line-profile-graphic": "line-region",
        "interval-graphic": "interval-region",
        "channel-graphic": "channel-region",
    }

    def __init__(self, graphic):
        self.__graphic = graphic

    @property
    def _item(self):
        return self._graphic

    @property
    def _graphic(self):
        return self.__graphic

    @property
    def specifier(self):
        return ObjectSpecifier("graphic", self.__graphic.uuid)

    @property
    def uuid(self) -> uuid_module.UUID:
        """Return the uuid of this object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__graphic.uuid

    @property
    def type(self) -> str:
        """Return the region type property.

        The region type is different from the preferred 'graphic_type' in that it is backwards compatible with older versions.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return Graphic.graphic_to_region_type_map.get(self.__graphic.type)

    @property
    def graphic_type(self) -> str:
        """Return the type of this graphic.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__graphic.type

    @property
    def region(self) -> "Graphic":
        return self

    @property
    def label(self) -> str:
        """Return the graphic label.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__graphic.label

    @label.setter
    def label(self, value: str) -> None:
        """Set the graphic label.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__graphic.label = value

    @property
    def graphic_id(self) -> str:
        """Return the graphic identifier.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__graphic.graphic_id

    @graphic_id.setter
    def graphic_id(self, value: str) -> None:
        """Set the graphic identifier.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__graphic.graphic_id = value

    def get_property(self, property: str):
        return getattr(self.__graphic, property)

    def set_property(self, property: str, value) -> None:
        setattr(self.__graphic, property, value)

    def mask_xdata_with_shape(self, shape: DataAndMetadata.ShapeType) -> DataAndMetadata.DataAndMetadata:
        """Return the mask created by this graphic as extended data.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        mask = self._graphic.get_mask(shape)
        return DataAndMetadata.DataAndMetadata.from_data(mask)

    # position, start, end, vector, center, size, bounds, angle

    @property
    def angle(self) -> float:
        """Return the angle (radians) property."""
        return self.get_property("angle")

    @angle.setter
    def angle(self, value: float) -> None:
        """Set the angle (radians) property."""
        self.set_property("angle", value)

    @property
    def bounds(self) -> NormRectangleType:
        """Return the bounds property in relative coordinates.

        Bounds is a tuple ((top, left), (height, width))"""
        return self.get_property("bounds")

    @bounds.setter
    def bounds(self, value: NormRectangleType) -> None:
        """Set the bounds property in relative coordinates.

        Bounds is a tuple ((top, left), (height, width))"""
        self.set_property("bounds", value)

    @property
    def center(self) -> NormPointType:
        """Return the center property in relative coordinates.

        Center is a tuple (y, x)."""
        return self.get_property("center")

    @center.setter
    def center(self, value) -> None:
        """Set the center in relative coordinates.

        Center is a tuple (y, x)."""
        self.set_property("center", value)

    @property
    def end(self) -> typing.Union[float, NormPointType]:
        """Return the end property in relative coordinates.

        End may be a float when graphic is an Interval or a tuple (y, x) when graphic is a Line."""
        return self.get_property("end")

    @end.setter
    def end(self, value: typing.Union[float, NormPointType]) -> None:
        """Set the end property in relative coordinates.

        End may be a float when graphic is an Interval or a tuple (y, x) when graphic is a Line."""
        self.set_property("end", value)

    @property
    def interval(self) -> NormIntervalType:
        """Return the interval property in relative coordinates.

        Interval is a tuple of floats (start, end)."""
        return self.get_property("interval")

    @interval.setter
    def interval(self, value: NormIntervalType) -> None:
        """Set the interval property in relative coordinates.

        Interval is a tuple of floats (start, end)."""
        self.set_property("interval", value)

    @property
    def position(self) -> NormPointType:
        """Return the position property in relative coordinates.

        Position is a tuple of floats (y, x)."""
        return self.get_property("position")

    @position.setter
    def position(self, value: NormPointType) -> None:
        """Set the position property in relative coordinates.

        Position is a tuple of floats (y, x)."""
        self.set_property("position", value)

    @property
    def size(self) -> NormSizeType:
        """Return the size property in relative coordinates.

        Size is a tuple of floats (height, width)."""
        return self.get_property("size")

    @size.setter
    def size(self, value: NormSizeType) -> None:
        """Set the size property in relative coordinates.

        Size is a tuple of floats (height, width)."""
        self.set_property("size", value)

    @property
    def start(self) -> typing.Union[float, NormPointType]:
        """Return the start property in relative coordinates.

        Start may be a float when graphic is an Interval or a tuple (y, x) when graphic is a Line."""
        return self.get_property("start")

    @start.setter
    def start(self, value: typing.Union[float, NormPointType]) -> None:
        """Set the end property in relative coordinates.

        End may be a float when graphic is an Interval or a tuple (y, x) when graphic is a Line."""
        self.set_property("start", value)

    @property
    def vector(self) -> NormVectorType:
        """Return the vector property in relative coordinates.

        Vector will be a tuple of tuples ((y_start, x_start), (y_end, x_end))."""
        return self.get_property("vector")

    @vector.setter
    def vector(self, value: NormVectorType) -> None:
        """Set the vector property in relative coordinates.

        Vector will be a tuple of tuples ((y_start, x_start), (y_end, x_end))."""
        self.set_property("vector", value)

    @property
    def line_width(self) -> float:
        """Return the line width property in pixel coordinates."""
        return self.get_property("width")

    @line_width.setter
    def line_width(self, value: float) -> None:
        """Set the line width property in pixel coordinates."""
        self.set_property("width", value)


# TODO: add group maps to map dotted key to a metadata dict
# TODO: add dict typing which converts the dict to json when externalized


class DataItem(metaclass=SharedInstance):
    release = ["uuid", "title", "created", "modified", "data", "set_data", "xdata", "display_xdata",
               "intensity_calibration", "set_intensity_calibration", "dimensional_calibrations",
               "set_dimensional_calibrations", "metadata", "set_metadata", "has_metadata_value", "get_metadata_value",
               "set_metadata_value", "delete_metadata_value", "data_and_metadata", "set_data_and_metadata", "regions",
               "graphics", "display", "add_point_region", "add_rectangle_region", "add_ellipse_region",
               "add_line_region", "add_interval_region", "add_channel_region", "remove_region", "mask_xdata"]

    def __init__(self, data_item: DataItemModule.DataItem):
        self.__data_item = data_item

    @property
    def _item(self):
        return self._data_item

    @property
    def _data_item(self) -> DataItemModule.DataItem:
        return self.__data_item

    @property
    def specifier(self):
        return ObjectSpecifier("data_item", self.__data_item.uuid)

    @property
    def __display_item(self) -> DisplayItemModule.DisplayItem:
        # TODO: remove data item / document model hack (required to access display items)
        display_item = self.__data_item._document_model.get_best_display_item_for_data_item(self.__data_item) if self.__data_item.container else None
        return display_item

    @property
    def uuid(self) -> uuid_module.UUID:
        """Return the uuid of this object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.uuid

    @property
    def created(self) -> datetime.datetime:
        """Return the created timestamp (UTC) as a datetime object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.created

    @property
    def modified(self) -> datetime.datetime:
        """Return the modified timestamp (UTC) as a datetime object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.modified

    @property
    def title(self) -> str:
        """Return the title as a string.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.title

    @title.setter
    def title(self, value: str) -> None:
        """Set the title to a string.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__data_item.title = value

    @property
    def data(self) -> numpy.ndarray:
        """Return the data as a numpy ndarray.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.data

    @data.setter
    def data(self, data: numpy.ndarray) -> None:
        """Set the data.

        :param data: A numpy ndarray.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__data_item.set_data(numpy.copy(data))

    def set_data(self, data: numpy.ndarray) -> None:
        """Set the data.

        :param data: A numpy ndarray.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.data = data

    @property
    def xdata(self) -> DataAndMetadata.DataAndMetadata:
        """Return the extended data of this data item.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.xdata

    @xdata.setter
    def xdata(self, data_and_metadata: DataAndMetadata.DataAndMetadata) -> None:
        """Set the extended data of this data item.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__data_item.set_xdata(data_and_metadata)

    @property
    def display_xdata(self) -> DataAndMetadata.DataAndMetadata:
        """Return the extended data of this data item display.

        Display data will always be 1d or 2d and either int, float, or RGB data type.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        display_data_channel = self.__display_item.display_data_channel
        return display_data_channel.get_calculated_display_values().display_data_and_metadata

    @property
    def intensity_calibration(self) -> CalibrationModule.Calibration:
        """Return a copy of the intensity calibration.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.intensity_calibration

    def set_intensity_calibration(self, intensity_calibration: CalibrationModule.Calibration) -> None:
        """Set the intensity calibration.

        :param intensity_calibration: The intensity calibration.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__data_item.set_intensity_calibration(intensity_calibration)

    @property
    def dimensional_calibrations(self) -> typing.List[CalibrationModule.Calibration]:
        """Return a copy of the list of dimensional calibrations.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.dimensional_calibrations

    def set_dimensional_calibrations(self, dimensional_calibrations: typing.List[CalibrationModule.Calibration]) -> None:
        """Set the dimensional calibrations.

        :param dimensional_calibrations: A list of calibrations, must match the dimensions of the data.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__data_item.set_dimensional_calibrations(dimensional_calibrations)

    @property
    def metadata(self) -> dict:
        """Return a copy of the metadata as a dict.

        For best future compatibility, prefer using the ``get_metadata_value`` and ``set_metadata_value`` methods over
        directly accessing ``metadata``.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_item.metadata

    def set_metadata(self, metadata: dict) -> None:
        """Set the metadata dict.

        :param metadata: The metadata dict.

        The metadata dict must be convertible to JSON, e.g. ``json.dumps(metadata)`` must succeed.

        For best future compatibility, prefer using the ``get_metadata_value`` and ``set_metadata_value`` methods over
        directly accessing ``metadata``.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__data_item.metadata = metadata

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
        return self._data_item.has_metadata_value(key)

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
        return self._data_item.get_metadata_value(key)

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
        self._data_item.set_metadata_value(key, value)

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
        self._data_item.delete_metadata_value(key)

    @property
    def data_and_metadata(self) -> DataAndMetadata.DataAndMetadata:
        """Return the extended data.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:attr:`~nion.swift.Facade.DataItem.xdata` instead.

        Scriptable: Yes
        """
        return self.__data_item.xdata

    def set_data_and_metadata(self, data_and_metadata: DataAndMetadata.DataAndMetadata) -> None:
        """Set the data and metadata.

        :param data_and_metadata: The data and metadata.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        self.__data_item.set_xdata(data_and_metadata)

    @property
    def regions(self) -> typing.List[Graphic]:
        """Return the graphics attached to this data item.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:attr:`~nion.swift.Facade.Display.graphics` instead.

        Scriptable: Yes
        """
        return self.graphics

    @property
    def graphics(self) -> typing.List[Graphic]:
        """Return the graphics attached to this data item.

        .. versionadded:: 1.0
        .. deprecated:: 15
           Use :py:meth:`~nion.swift.Facade.Display.graphics` instead.

        Scriptable: Yes
        """
        return [Graphic(graphic) for graphic in self.__display_item.graphics]

    @property
    def display(self) -> "Display":
        """Return a display for the data item, preferring the oldest single data item display.

        If no single data item display exists, return the oldest multi data item display.

        Scriptable: Yes
        """
        return Display(self.__display_item)

    def add_point_region(self, y: float, x: float) -> Graphic:
        """Add a point graphic to the data item.

        :param x: The x coordinate, in relative units [0.0, 1.0]
        :param y: The y coordinate, in relative units [0.0, 1.0]
        :return: The :py:class:`nion.swift.Facade.Graphic` object that was added.

        .. versionadded:: 1.0
        .. deprecated:: 15
           Use :py:meth:`~nion.swift.Facade.Display.add_graphic` instead.

        Scriptable: Yes
        """
        graphic = Graphics.PointGraphic()
        graphic.position = Geometry.FloatPoint(y, x)
        self.__display_item.add_graphic(graphic)
        return Graphic(graphic)

    def add_rectangle_region(self, center_y: float, center_x: float, height: float, width: float) -> Graphic:
        graphic = Graphics.RectangleGraphic()
        graphic.center = Geometry.FloatPoint(center_y, center_x)
        graphic.size = Geometry.FloatSize(height, width)
        self.__display_item.add_graphic(graphic)
        return Graphic(graphic)

    def add_ellipse_region(self, center_y: float, center_x: float, height: float, width: float) -> Graphic:
        graphic = Graphics.EllipseGraphic()
        graphic.center = Geometry.FloatPoint(center_y, center_x)
        graphic.size = Geometry.FloatSize(height, width)
        self.__display_item.add_graphic(graphic)
        return Graphic(graphic)

    def add_line_region(self, start_y: float, start_x: float, end_y: float, end_x: float) -> Graphic:
        graphic = Graphics.LineGraphic()
        graphic.start = Geometry.FloatPoint(start_y, start_x)
        graphic.end = Geometry.FloatPoint(end_y, end_x)
        self.__display_item.add_graphic(graphic)
        return Graphic(graphic)

    def add_interval_region(self, start: float, end: float) -> Graphic:
        graphic = Graphics.IntervalGraphic()
        graphic.start = start
        graphic.end = end
        self.__display_item.add_graphic(graphic)
        return Graphic(graphic)

    def add_channel_region(self, position: float) -> Graphic:
        graphic = Graphics.ChannelGraphic()
        graphic.position = position
        self.__display_item.add_graphic(graphic)
        return Graphic(graphic)

    def remove_region(self, graphic: Graphic) -> None:
        self.__display_item.remove_graphic(graphic._graphic)

    def mask_xdata(self) -> DataAndMetadata.DataAndMetadata:
        """Return the mask by combining any mask graphics on this data item as extended data.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        display_data_channel = self.__display_item.display_data_channel
        shape = display_data_channel.display_data_shape
        calibrated_origin = Geometry.FloatPoint(y=self.__display_item.datum_calibrations[0].convert_from_calibrated_value(0.0),
                                                x=self.__display_item.datum_calibrations[1].convert_from_calibrated_value(0.0))
        mask = DataItemModule.create_mask_data(self.__display_item.graphics, shape, calibrated_origin)
        return DataAndMetadata.DataAndMetadata.from_data(mask)

    def data_item_to_svg(self):
        drawing_context, shape = DisplayPanelModule.preview(DisplayPanelModule.FixedUISettings(), self.__display_item, 320, 240)

        view_box = Geometry.IntRect(Geometry.IntPoint(), shape)

        return drawing_context.to_svg(shape, view_box)


class DataSource(metaclass=SharedInstance):

    def __init__(self, data_source):
        self.__data_source = data_source

    @property
    def _item(self):
        return self._data_source

    @property
    def _data_source(self):
        return self.__data_source

    @property
    def specifier(self):
        return ObjectSpecifier("data_source", uuid_module.uuid4())

    @property
    def _display_data_channel(self) -> DisplayItemModule.DisplayDataChannel:
        return self.__data_source.display_data_channel

    @property
    def display_item(self) -> "Display":
        return Display(self.__data_source.display_item)

    @property
    def data_item(self) -> DataItem:
        return DataItem(self.__data_source.data_item)

    @property
    def graphic(self) -> Graphic:
        return Graphic(self.__data_source.graphic)

    @property
    def cropped_element_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.cropped_element_xdata

    @property
    def cropped_display_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.cropped_display_xdata

    @property
    def cropped_normalized_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.cropped_normalized_xdata

    @property
    def cropped_adjusted_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.cropped_adjusted_xdata

    @property
    def cropped_transformed_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.cropped_transformed_xdata

    @property
    def cropped_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.cropped_xdata

    @property
    def data(self) -> numpy.ndarray:
        return self.__data_source.data

    @property
    def element_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.element_xdata

    @property
    def display_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.display_xdata

    @property
    def display_rgba(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.display_rgba

    @property
    def normalized_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.normalized_xdata

    @property
    def adjusted_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.adjusted_xdata

    @property
    def transformed_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.transformed_xdata

    @property
    def filter_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.filter_xdata

    @property
    def filtered_xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.filtered_xdata

    @property
    def xdata(self) -> DataAndMetadata.DataAndMetadata:
        return self.__data_source.xdata


class DisplayPanel(metaclass=SharedInstance):

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
        """Return the data item associated with this display panel.

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
            display_item = data_item._data_item.container.get_display_item_for_data_item(data_item._data_item) if data_item._data_item.container else None
            display_panel.set_display_panel_display_item(display_item)


class Display(metaclass=SharedInstance):

    release = ["uuid", "display_type", "selected_graphics", "graphics", "data_item", "data_items", "get_graphic_by_id"]

    def __init__(self, display_item):
        self.__display_item = display_item

    @property
    def _item(self):
        return self._display_item

    @property
    def _display_item(self) -> DisplayItemModule.DisplayItem:
        return self.__display_item

    @property
    def _display(self) -> DisplayItemModule.DisplayItem:
        return self.__display_item

    @property
    def specifier(self):
        return ObjectSpecifier("display_item", self.__display_item.uuid)

    @property
    def uuid(self) -> uuid_module.UUID:
        """Return the uuid of this object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__display_item.uuid

    @property
    def display_type(self) -> str:
        return self.__display_item.display_type

    @display_type.setter
    def display_type(self, value: str) -> None:
        self.__display_item.display_type = value

    @property
    def selected_graphics(self) -> typing.List[Graphic]:
        return [Graphic(graphic) for graphic in self.__display_item.selected_graphics]

    @property
    def graphics(self) -> typing.List[Graphic]:
        """Return the graphics attached to this display.

        .. versionadded:: 15

        Scriptable: Yes
        """
        return [Graphic(graphic) for graphic in self.__display_item.graphics]

    @property
    def data_item(self) -> typing.Optional[DataItem]:
        data_item = self.__display_item.data_item
        return DataItem(data_item) if data_item else None

    @property
    def data_items(self) -> typing.List[DataItem]:
        return [DataItem(data_item) for data_item in self.__display_item.data_items]

    @property
    def xdata(self) -> typing.Optional[DataAndMetadata.DataAndMetadata]:
        return self.data_item.xdata if self.data_item else None

    @property
    def data(self) -> typing.Optional[numpy.ndarray]:
        return self.data_item.data if self.data_item else None

    @property
    def metadata(self) -> typing.Optional[typing.Dict]:
        return self.data_item.metadata if self.data_item else None

    def add_graphic(self, graphic_description: typing.Mapping) -> typing.Optional[Graphic]:
        """Add graphic described in graphic_description to the display.

        Graphic description must include a 'type' key with one of the following values:
            'rect-graphic'
            'ellipse-graphic'
            'line-graphic'
            'point-graphic'
            'interval-graphic'
            'channel-graphic'
            'spot-graphic'
            'wedge-graphic'
            'ring-graphic'
            'lattice-graphic'

        Rectangle and ellipse graphic can include the following keys:
            'bounds' ((top, left), (height, width)) or Geometry.FloatRect
            'center' (cy, cx) or Geometry.FloatPoint, default 0.5, 0.5
            'size' (height, width) or Geometry.FloatSize, default 1.0, 1.0
            'rotation' (float, default 0)

        Line graphic can include the following keys:
            'vector' ((start_y, start_x), (end_y, end_x))
            'start' (y, x) or Geometry.FloatPoint, default 0.0, 0.0
            'end' (y, x) or Geometry.FloatPoint, default 1.0, 1.0
            'start_arrow_enabled' (bool, default False)
            'end_arrow_enabled' (bool, default False)
            'angle' (float)
            'length' (float)

        Point graphic can include the following keys:
            'position' (y, x) or Geometry.FloatPoint, default 0.5, 0.5

        Interval graphic can include the following keys:
            'start' (float, default 0.0)
            'end' (float, default 1.0)

        Channel graphic can include the following keys:
            'position' (int, default 0.5)

        Spot graphic can include the following keys:
            'bounds' ((top, left), (height, width)) or Geometry.FloatRect
            'center' (cy, cx) or Geometry.FloatPoint, default 0.5, 0.5
            'size' (height, width) or Geometry.FloatSize, default 1.0, 1.0
            'rotation' (float, default 0)

        Wedge graphic can include the following keys:
            'angle_interval' (tuple(float, float), default 0, math.pi)
            'start_angle' (float)
            'end_angle' (float)

        Ring graphic can include the follow keys:
            'radius_1' (float, default 0.2)
            'radius_2' (float, default 0.2)
            'mode' (string ['band-pass', 'high-pass', 'low-pass'], default 'bandpass')

        Lattice graphic can include the follow keys:
            'u_pos' (y, x) or Geometry.FloatPoint, default ( 0.00, 0.25)
            'v_pos' (y, x) or Geometry.FloatPoint, default (-0.25, 0.00)
            'u_count' (integer, default 1)
            'v_count' (integer, default 1)
            'radius' (float, 0.1)

        All graphics can optionally include the following attributes:
            'fill_color' (string, default None)
            'graphic_id' (string, default None)
            'is_bounds_constrained' (bool, default False)
            'is_position_locked' (bool, default False)
            'is_shape_locked' (bool, default False)
            'label' (string, default None)
            'stroke_color' (string, default None)
            'role' (string, default None)

        Returns the new Graphic.

        .. versionadded:: 15

        Scriptable: Yes
        """
        attributes = ["fill_color", "graphic_id", "is_bounds_constrained", "is_position_locked",
                      "is_shape_locked", "label", "stroke_color", "role"]
        graphic = None
        graphic_table = [
            ["rect-graphic", Graphics.RectangleGraphic, ["bounds", "center", "size", "rotation"]],
            ["ellipse-graphic", Graphics.EllipseGraphic, ["bounds", "center", "size", "rotation"]],
            ["line-graphic", Graphics.LineGraphic, ["vector", "start", "end", "start_arrow_enabled", "end_arrow_enabled", "angle", "length"]],
            ["point-graphic", Graphics.PointGraphic, ["position"]],
            ["interval-graphic", Graphics.IntervalGraphic, ["start", "end"]],
            ["channel-graphic", Graphics.ChannelGraphic, ["position"]],
            ["spot-graphic", Graphics.SpotGraphic, ["bounds", "center", "size", "rotation"]],
            ["wedge-graphic", Graphics.WedgeGraphic, ["angle_interval", "start_angle", "end_angle"]],
            ["ring-graphic", Graphics.RingGraphic, ["radius_1", "radius_2", "mode"]],
            ["lattice-graphic", Graphics.LatticeGraphic, ["u_pos", "v_pos", "u_count", "v_count", "radius"]],
        ]
        for graphic_entry in graphic_table:
            if graphic_description.get("type") == graphic_entry[0]:
                graphic = graphic_entry[1]()
                attributes += graphic_entry[2]
                for attribute in attributes:
                    if attribute in graphic_description:
                        setattr(graphic, attribute, graphic_description[attribute])
                self.__display_item.add_graphic(graphic)
                return Graphic(graphic)
        return None

    def add_point_graphic(self, y: float, x: float) -> Graphic:
        graphic = Graphics.PointGraphic()
        graphic.position = Geometry.FloatPoint(y, x)
        self.__display_item.add_graphic(graphic)
        return Graphic(graphic)

    def get_graphic_by_id(self, graphic_id: str) -> typing.Optional[Graphic]:
        for graphic in self.__display_item.graphics:
            if graphic.graphic_id == graphic_id:
                return Graphic(graphic)
        return None


class DataGroup(metaclass=SharedInstance):

    release = ["uuid", "add_data_item"]

    def __init__(self, data_group):
        self.__data_group = data_group

    @property
    def specifier(self):
        return ObjectSpecifier("data_group", self.__data_group.uuid)

    @property
    def uuid(self) -> uuid_module.UUID:
        """Return the uuid of this object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_group.uuid

    def add_data_item(self, data_item: DataItem) -> None:
        """Add a data item to the group.

        :param data_item: The :py:class:`nion.swift.Facade.DataItem` object to add.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        display_item = data_item._data_item.container.get_display_item_for_data_item(data_item._data_item) if data_item._data_item.container else None
        if display_item:
            self.__data_group.append_display_item(display_item)

    def remove_data_item(self, data_item: DataItem) -> None:
        raise NotImplementedError()

    def remove_all_data_items(self) -> None:
        raise NotImplementedError()

    @property
    def data_items(self) -> typing.List[DataItem]:
        raise AttributeError()


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

        # synchronize start of thread; if this sync doesn't occur, the task can be closed before the acquisition
        # is started. in that case a deadlock occurs because the abort doesn't apply and the thread is waiting
        # for the acquisition.
        self.__recording_started = threading.Event()

        def record_thread():
            self.__hardware_source.start_recording()
            self.__recording_started.set()
            self.__data_and_metadata_list = self.__hardware_source.get_next_xdatas_to_finish()

        self.__thread = threading.Thread(target=record_thread)
        self.__thread.start()

        self.__recording_started.wait()

    def close(self) -> None:
        """Close the task.

        .. versionadded:: 1.0


        This method must be called when the task is no longer needed.
        """
        if self.__thread.is_alive():
            self.__hardware_source.abort_recording()
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


class HardwareSource(metaclass=SharedInstance):

    release = ["close", "profile_index", "get_default_frame_parameters", "get_frame_parameters", "get_frame_parameters_for_profile_by_index",
        "set_frame_parameters", "set_frame_parameters_for_profile_by_index", "start_playing", "stop_playing", "abort_playing", "is_playing",
        "start_recording", "abort_recording", "is_recording", "record", "create_record_task", "create_view_task", "grab_next_to_finish",
        "grab_next_to_start", "get_property_as_float", "set_property_as_float", "get_property_as_int", "set_property_as_int", "get_property_as_bool",
        "set_property_as_bool", "get_property_as_str", "set_property_as_str", "get_property_as_float_point", "set_property_as_float_point"]

    threadsafe = ["record", "grab_next_to_finish", "grab_next_to_start", "set_property_as_float", "set_property_as_int", "set_property_as_bool",
        "set_property_as_str", "set_property_as_float_point"]

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
        return self.__hardware_source.get_next_xdatas_to_finish(timeout)

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

    def grab_next_to_finish(self, timeout: float=None) -> typing.List[DataAndMetadata.DataAndMetadata]:
        """Grabs the next frame to finish and returns it as data and metadata.

        .. versionadded:: 1.0

        :param timeout: The timeout in seconds. Pass None to use default.
        :return: The list of data and metadata items that were read.
        :rtype: list of :py:class:`DataAndMetadata`

        If the view is not already started, it will be started automatically.

        Scriptable: Yes
        """
        self.start_playing()
        return self.__hardware_source.get_next_xdatas_to_finish(timeout)

    def grab_next_to_start(self, frame_parameters: dict=None, channels_enabled: typing.List[bool]=None, timeout: float=None) -> typing.List[DataAndMetadata.DataAndMetadata]:
        self.start_playing(frame_parameters, channels_enabled)
        return self.__hardware_source.get_next_xdatas_to_start(timeout)

    def execute_command(self, command, args_str, kwargs_str):
        args = pickle.loads(args_str)
        kwargs = pickle.loads(kwargs_str)
        result = getattr(self.__hardware_source, command)(*args, **kwargs)
        result_str = pickle.dumps(result)
        return result_str

    def get_property_as_float(self, name):
        return float(self.__hardware_source.get_property(name))

    def set_property_as_float(self, name, value) -> None:
        self.__hardware_source.set_property(name, float(value))

    def get_property_as_int(self, name):
        return int(self.__hardware_source.get_property(name))

    def set_property_as_int(self, name, value) -> None:
        self.__hardware_source.set_property(name, int(value))

    def get_property_as_bool(self, name):
        return bool(self.__hardware_source.get_property(name))

    def set_property_as_bool(self, name, value) -> None:
        self.__hardware_source.set_property(name, bool(value))

    def get_property_as_str(self, name):
        return str(self.__hardware_source.get_property(name))

    def set_property_as_str(self, name, value) -> None:
        self.__hardware_source.set_property(name, str(value))

    def get_property_as_float_point(self, name):
        return tuple(Geometry.FloatPoint.make(self.__hardware_source.get_property(name)))

    def set_property_as_float_point(self, name, value) -> None:
        self.__hardware_source.set_property(name, tuple(Geometry.FloatPoint.make(value)))


class Instrument(metaclass=SharedInstance):

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
        value = self.__instrument.get_property(name)
        return Geometry.FloatPoint.make(value) if value else None

    def set_property_as_float_point(self, name: str, value: Geometry.FloatPoint) -> None:
        self.__instrument.set_property(name, tuple(Geometry.FloatPoint.make(value)))

    def get_property(self, name: str):
        # deprecated
        return self.__instrument.get_property(name)

    def set_property(self, name: str, value) -> None:
        # deprecated
        self.__instrument.set_property(name, value)

    def execute_command(self, command, args_str, kwargs_str):
        args = pickle.loads(args_str)
        kwargs = pickle.loads(kwargs_str)
        result = getattr(self.__instrument, command)(*args, **kwargs)
        result_str = pickle.dumps(result)
        return result_str


class DataStructure(metaclass=SharedInstance):
    release = ["uuid"]

    def __init__(self, data_structure: DataStructureModule.DataStructure):
        self.__data_structure = data_structure

    @property
    def _item(self):
        return self._data_structure

    @property
    def _data_structure(self) -> DataStructureModule.DataStructure:
        return self.__data_structure

    @property
    def specifier(self):
        return ObjectSpecifier("library")

    @property
    def uuid(self) -> uuid_module.UUID:
        """Return the uuid of this object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__data_structure.uuid

    def get_property(self, property: str):
        return self.__data_structure.get_property_value(property)

    def set_property(self, property: str, value) -> None:
        self.__data_structure.set_property_value(property, value)


class Computation(metaclass=SharedInstance):
    release = ["uuid"]

    def __init__(self, computation: Symbolic.Computation):
        self.__computation = computation

    @property
    def _computation(self) -> Symbolic.Computation:
        return self.__computation

    @property
    def specifier(self):
        return ObjectSpecifier("library")

    @property
    def uuid(self) -> uuid_module.UUID:
        """Return the uuid of this object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__computation.uuid

    def set_input_value(self, name: str, value):
        # support lists here?
        if isinstance(value, (str, bool, numbers.Integral, numbers.Real, numbers.Complex)):
            self.__computation.set_input_value(name, value)
        if isinstance(value, dict) and value.get("object"):
            object = value.get("object")
            object_type = value.get("type")
            if object_type == "data_source":
                document_model = self.__computation.container.container.document_model
                display_item = document_model.get_display_item_for_data_item(object._data_item)
                display_data_channel = display_item.display_data_channel
                input_value = Symbolic.make_item(display_data_channel)
            else:
                input_value = Symbolic.make_item(object._item)
            self.__computation.set_input_item(name, input_value)
        elif hasattr(value, "_item"):
            input_value = Symbolic.make_item(value._item)
            self.__computation.set_input_item(name, input_value)

    def get_result(self, name: str, value=None):
        result = self.__computation.get_output(name)
        if isinstance(result, list):
            return [_new_api_object(bound_item) for bound_item in result]
        if result:
            return _new_api_object(result)
        return None

    def set_result(self, name: str, value) -> None:
        if isinstance(value, list):
            output_items = Symbolic.make_item_list([v._item for v in value])
            for result in self.__computation.results:
                if result.name == name:
                    self.__computation.set_output_item(name, output_items)
                    return
            self.__computation.create_output_item(name, output_items)
        else:
            output_item = Symbolic.make_item(value._item) if value else None
            for result in self.__computation.results:
                if result.name == name:
                    self.__computation.set_output_item(name, output_item)
                    return
            self.__computation.create_output_item(name, output_item)

    def set_referenced_data(self, name: str, data: numpy.ndarray) -> None:
        data_item = self.get_result(name)
        if not data_item:
            data_item = self.api.library.create_data_item()
            self.set_result(name, data_item)
        data_item.data = data

    def set_referenced_xdata(self, name: str, xdata: DataAndMetadata.DataAndMetadata) -> None:
        data_item = self.get_result(name)
        if not data_item:
            data_item = self.api.library.create_data_item()
            self.set_result(name, data_item)
        data_item.xdata = xdata

    def clear_referenced_data(self, name: str) -> None:
        data_item = self.get_result(name)
        if data_item:
            self.api.library.remove_data_item(data_item)


class Library(metaclass=SharedInstance):
    release = ["uuid", "data_item_count", "data_items", "display_items", "create_data_item",
               "create_data_item_from_data", "create_data_item_from_data_and_metadata",
               "get_or_create_data_group", "data_ref_for_data_item", "get_data_item_for_hardware_source",
               "get_data_item_for_reference_key", "get_data_item_by_uuid", "get_graphic_by_uuid", "get_item_by_specifier",
               "get_source_data_items", "get_dependent_data_items", "has_library_value", "get_library_value",
               "set_library_value", "delete_library_value",
               "copy_data_item", "snapshot_data_item"]

    def __init__(self, document_model: DocumentModelModule.DocumentModel):
        assert document_model
        self.__document_model = document_model

    @property
    def _document_model(self) -> DocumentModelModule.DocumentModel:
        return self.__document_model

    @property
    def specifier(self):
        return ObjectSpecifier("library")

    @property
    def uuid(self) -> uuid_module.UUID:
        """Return the uuid of this object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return self.__document_model.uuid

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

    @property
    def display_items(self) -> typing.List[Display]:
        """Return the list of display items.

        :return: The list of :py:class:`nion.swift.Facade.Display` objects.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return [Display(display_item) for display_item in self.__document_model.display_items]

    def get_source_data_items(self, data_item: DataItem) -> typing.List[DataItem]:
        """Return the list of data items that are data sources for the data item.

        :return: The list of :py:class:`nion.swift.Facade.DataItem` objects.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return [DataItem(data_item) for data_item in self._document_model.get_source_data_items(data_item._data_item)] if data_item else None

    def get_dependent_data_items(self, data_item: DataItem) -> typing.List[DataItem]:
        """Return the dependent data items the data item argument.

        :return: The list of :py:class:`nion.swift.Facade.DataItem` objects.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return [DataItem(data_item) for data_item in self._document_model.get_dependent_data_items(data_item._data_item)] if data_item else None

    def create_data_item(self, title: str=None) -> DataItem:
        """Create an empty data item in the library.

        :param title: The title of the data item (optional).
        :return: The new :py:class:`nion.swift.Facade.DataItem` object.
        :rtype: :py:class:`nion.swift.Facade.DataItem`

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        data_item = DataItemModule.DataItem()
        data_item.ensure_data_source()
        if title is not None:
            data_item.title = title
        self.__document_model.append_data_item(data_item)
        return DataItem(data_item)

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
        return self.create_data_item_from_data_and_metadata(DataAndMetadata.DataAndMetadata.from_data(data), title)

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
        data_item = DataItemModule.new_data_item(data_and_metadata)
        if title is not None:
            data_item.title = title
        self.__document_model.append_data_item(data_item)
        return DataItem(data_item)

    def copy_data_item(self, data_item: DataItem) -> DataItem:
        """Copy a data item.

        .. versionadded:: 1.0

        Scriptable: No
        """
        data_item = copy.deepcopy(data_item._data_item)
        self.__document_model.append_data_item(data_item)
        return DataItem(data_item)

    def snapshot_data_item(self, data_item: DataItem) -> DataItem:
        """Snapshot a data item. Similar to copy but with a data snapshot.

        .. versionadded:: 1.0

        Scriptable: No
        """
        data_item = data_item._data_item.snapshot()
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
                self.__transaction = self.__document_model.item_transaction(self.__data_item._data_item)
                self.__data_item._data_item.increment_data_ref_count()
                return self

            def __exit__(self, type, value, traceback):
                self.__data_item._data_item.decrement_data_ref_count()
                self.__transaction.close()
                self.__transaction = None

            @property
            def data(self):
                return self.__data_item.data

            @data.setter
            def data(self, data):
                self.__data_item._data_item.set_data(data)

            def __setitem__(self, key, value):
                with self.__data_item._data_item.data_ref() as data_ref:
                    data_ref.data[key] = value
                    data_ref.data_updated()

        return DataRef(self.__document_model, data_item)

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
        assert hardware_source is not None
        hardware_source_id = hardware_source._hardware_source.hardware_source_id
        document_model = self._document_model
        data_item_reference_key = document_model.make_data_item_reference_key(hardware_source_id, channel_id, processor_id)
        return self.get_data_item_for_reference_key(data_item_reference_key, create_if_needed=create_if_needed, large_format=large_format)

    def get_data_item_for_reference_key(self, data_item_reference_key: str=None, create_if_needed: bool=False, large_format: bool=False) -> DataItem:
        """Get the data item associated with data item reference key. Optionally create if missing.

        :param data_item_reference_key: The data item reference key.
        :param create_if_needed: Whether to create a new data item if none is found.
        :return: The associated data item. May be None.

        .. versionadded:: 1.0

        Status: Provisional
        Scriptable: Yes
        """
        document_model = self._document_model
        data_item_reference = document_model.get_data_item_reference(data_item_reference_key)
        data_item = data_item_reference.data_item
        if data_item is None and create_if_needed:
            data_item = DataItemModule.DataItem(large_format=large_format)
            data_item.ensure_data_source()
            document_model.append_data_item(data_item)
            document_model.setup_channel(data_item_reference_key, data_item)
            data_item.session_id = document_model.session_id
            data_item = document_model.get_data_item_reference(data_item_reference_key).data_item
        return DataItem(data_item) if data_item else None

    def get_data_item_by_uuid(self, data_item_uuid: uuid_module.UUID) -> DataItem:
        """Get the data item with the given UUID.

        .. versionadded:: 1.0
        .. deprecated:: 2.0
           Use :py:meth:`~nion.swift.Facade.API_1.get_item_by_specifier` instead.

        Status: Provisional
        Scriptable: Yes
        """
        data_items = list()
        for data_item in self._document_model.data_items:
            if data_item.uuid == data_item_uuid:
                data_items.append(data_item)
        return DataItem(data_items[0]) if len(data_items) == 1 else None

    def get_graphic_by_uuid(self, graphic_uuid: uuid_module.UUID) -> Graphic:
        """Get the graphic with the given UUID.

        .. versionadded:: 1.0
        .. deprecated:: 2.0
           Use :py:meth:`~nion.swift.Facade.API_1.get_item_by_specifier` instead.

        Status: Provisional
        Scriptable: Yes
        """
        graphics = list()
        for display_item in self._document_model.display_items:
            for graphic in display_item.graphics:
                if graphic.uuid == graphic_uuid:
                    graphics.append(graphic)
        return Graphic(graphics[0]) if len(graphics) == 1 else None

    def get_item_by_specifier(self, item_specifier: Persistence.PersistentObjectSpecifier) -> typing.Optional[Persistence.PersistentObject]:
        """Get the library item with the given item specifier.

        .. versionadded:: 2.0

        Scriptable: No
        """
        return _new_api_object(self.__document_model.resolve_item_specifier(item_specifier))

    def has_library_value(self, key: str) -> bool:
        """Return whether the library value for the given key exists.

        Please consult the developer documentation for a list of valid keys.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        desc = Metadata.session_key_map.get(key)
        if desc is not None:
            field_id = desc["paths"][-1]
            return bool(getattr(ApplicationData.get_session_metadata_model(), field_id, None))
        return False

    def get_library_value(self, key: str) -> typing.Any:
        """Get the library value for the given key.

        Please consult the developer documentation for a list of valid keys.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        desc = Metadata.session_key_map.get(key)
        if desc is not None:
            field_id = desc["paths"][-1]
            return getattr(ApplicationData.get_session_metadata_model(), field_id)
        raise KeyError()

    def set_library_value(self, key: str, value: typing.Any) -> None:
        """Set the library value for the given key.

        Please consult the developer documentation for a list of valid keys.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        desc = Metadata.session_key_map.get(key)
        if desc is not None:
            field_id = desc["paths"][-1]
            setattr(ApplicationData.get_session_metadata_model(), field_id, value)
            return
        raise KeyError()

    def delete_library_value(self, key: str) -> None:
        """Delete the library value for the given key.

        Please consult the developer documentation for a list of valid keys.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        desc = Metadata.session_key_map.get(key)
        if desc is not None:
            field_id = desc["paths"][-1]
            setattr(ApplicationData.get_session_metadata_model(), field_id, None)
            return
        raise KeyError()

    def create_computation(self, computation_type_id, inputs, outputs) -> Computation:
        computation = self.__document_model.create_computation()
        for name, item in inputs.items():
            if isinstance(item, str):
                computation.create_variable(name, value_type="string", value=item)
            elif isinstance(item, bool):
                computation.create_variable(name, value_type="boolean", value=item)
            elif isinstance(item, numbers.Integral):
                computation.create_variable(name, value_type="integral", value=item)
            elif isinstance(item, numbers.Real):
                computation.create_variable(name, value_type="real", value=item)
            elif isinstance(item, numbers.Complex):
                computation.create_variable(name, value_type="complex", value=item)
            elif isinstance(item, dict) and item.get("object"):
                object = item.get("object")
                object_type = item.get("type")
                if object_type == "data_source":
                    display_item = self.__document_model.get_display_item_for_data_item(object._data_item)
                    display_data_channel = display_item.display_data_channel
                    input_item = Symbolic.make_item(display_data_channel)
                else:
                    input_item = Symbolic.make_item(object._item, type=object_type)
                computation.create_input_item(name, input_item)
            elif isinstance(item, list):
                # TODO: handle more than just objects
                computation.create_input_item(name, Symbolic.make_item_list([i._item for i in item]))
            else:
                computation.create_input_item(name, Symbolic.make_item(item._item))
        for name, item in outputs.items():
            computation.create_output_item(name, Symbolic.make_item(item._item) if item else None)
        computation.processing_id = computation_type_id
        self._document_model.append_computation(computation)
        return Computation(computation)


class DocumentWindow(metaclass=SharedInstance):

    release = ["library", "all_display_panels", "get_display_panel_by_id", "display_data_item", "target_display",
               "target_data_item", "show_get_string_message_box", "show_confirmation_message_box",
               "show_modeless_dialog", "queue_task", "clear_queued_tasks", "add_data", "create_data_item_from_data",
               "create_data_item_from_data_and_metadata", "get_or_create_data_group"]

    def __init__(self, document_controller):
        self.__document_controller = document_controller

    @property
    def specifier(self):
        return ObjectSpecifier("document_controller", self.__document_controller.uuid)

    @property
    def _document_controller(self) -> "DocumentController.DocumentController":
        return self.__document_controller

    @property
    def _document_window(self) -> "DocumentController.DocumentController":
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
            display_item = self.__document_controller.document_model.get_display_item_for_data_item(data_item._data_item)
            result_display_panel.set_display_panel_display_item(display_item)
            result_display_panel.request_focus()
            return DisplayPanel(result_display_panel)
        return None

    @property
    def target_display_panel(self):
        raise AttributeError()

    @property
    def target_display(self) -> Display:
        display_item = self.__document_controller.selected_display_item
        return Display(display_item)

    @property
    def target_data_item(self) -> DataItem:
        data_item = self.__document_controller.selected_data_item
        return DataItem(data_item) if data_item else None

    def create_task_context_manager(self, title, task_type):
        return self.__document_controller.create_task_context_manager(title, task_type)

    def show_get_string_message_box(self, caption: str, text: str, accepted_fn, rejected_fn=None, accepted_text: str=None, rejected_text: str=None) -> None:
        """Show a dialog box and ask for a string.

        Caption describes the user prompt. Text is the initial/default string.

        Accepted function must be a function taking one argument which is the resulting text if the user accepts the
        message dialog. It will only be called if the user clicks OK.

        Rejected function can be a function taking no arguments, called if the user clicks Cancel.

        .. versionadded:: 1.0

        Scriptable: No
        """
        workspace = self.__document_controller.workspace_controller
        workspace.pose_get_string_message_box(caption, text, accepted_fn, rejected_fn, accepted_text, rejected_text)

    def show_confirmation_message_box(self, caption: str, accepted_fn, rejected_fn=None, accepted_text: str=None, rejected_text: str=None, display_rejected: str=False) -> None:
        workspace = self.__document_controller.workspace_controller
        workspace.pose_confirmation_message_box(caption, accepted_fn, rejected_fn, accepted_text, rejected_text, display_rejected)

    def show_modeless_dialog(self, item, handler=None):
        if isinstance(item, dict) and item.get("type") == "modeless_dialog":
            if handler and not getattr(handler, "get_object_converter", None):
                handler.get_object_converter = lambda c: ObjectConverter(self, c)
            window = self._document_controller
            dialog = Declarative.construct(window.ui, window, item, handler)
            dialog.show()

    def queue_task(self, fn) -> None:
        self.__document_controller.queue_task(fn)

    def clear_queued_tasks(self) -> None:
        self.__document_controller.clear_queued_tasks()

    def add_data(self, data: numpy.ndarray, title: str=None) -> DataItem:
        """Create a data item in the library from data.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:meth:`~nion.swift.Facade.Library.create_data_item_from_data` instead.

        Scriptable: No
        """
        return self.create_data_item_from_data(data, title)

    def create_data_item_from_data(self, data: numpy.ndarray, title: str=None) -> DataItem:
        """Create a data item in the library from data.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:meth:`~nion.swift.Facade.Library.create_data_item_from_data` instead.

        Scriptable: No
        """
        return DataItem(self.__document_controller.add_data(data, title))

    def create_data_item_from_data_and_metadata(self, data_and_metadata: DataAndMetadata.DataAndMetadata, title: str=None) -> DataItem:
        """Create a data item in the library from the data and metadata.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:meth:`~nion.swift.Facade.Library.create_data_item_from_data_and_metadata` instead.

        Scriptable: No
        """
        data_item = DataItemModule.new_data_item(data_and_metadata)
        if title is not None:
            data_item.title = title
        self.__document_controller.document_model.append_data_item(data_item)
        return DataItem(data_item)

    def get_or_create_data_group(self, title: str) -> DataGroup:
        """Get (or create) a data group.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:meth:`~nion.swift.Facade.Library.create_data_item_from_data` instead.

        Scriptable: No
        """
        return DataGroup(self.__document_controller.document_model.get_or_create_data_group(title))


class Application(metaclass=SharedInstance):

    release = ["library", "document_controllers", "document_windows", "data_location", "document_location", "configuration_location"]

    def __init__(self, application):
        self.__application = application

    @property
    def _application(self):
        return self.__application

    @property
    def specifier(self):
        return ObjectSpecifier("application")

    @property
    def library(self) -> Library:
        """Return the library object.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return Library(self.__application.document_model)

    @property
    def document_controllers(self) -> typing.List[DocumentWindow]:
        """Return the document controllers.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:attr:`~nion.swift.Facade.Application.document_windows` instead.

        Scriptable: Yes
        """
        return self.document_windows

    @property
    def document_windows(self) -> typing.List[DocumentWindow]:
        """Return the document windows.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return [DocumentWindow(document_controller) for document_controller in self.__application.document_controllers]

    @property
    def data_location(self):
        return self.__application.ui.get_data_location()

    @property
    def document_location(self):
        return self.__application.ui.get_document_location()

    @property
    def configuration_location(self):
        return self.__application.ui.get_configuration_location()


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

    release = ["create_calibration", "create_data_descriptor", "create_data_and_metadata",
               "create_data_and_metadata_from_data", "create_data_and_metadata_io_handler",
               "create_menu_item", "create_hardware_source", "create_panel", "create_specifier",
               "get_all_hardware_source_ids", "get_all_instrument_ids",
               "get_hardware_source_by_id", "get_instrument_by_id", "application", "library", "queue_task",
               "clear_queued_tasks"]

    def __init__(self, ui_version, app):
        super().__init__()
        self.__ui_version = ui_version
        self.__app = app

    @property
    def rpc_dict(self):
        return None

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

    def create_data_descriptor(self, is_sequence: bool, collection_dimension_count: int, datum_dimension_count: int) -> DataAndMetadata.DataDescriptor:
        """Create a data descriptor.

        :param is_sequence: whether the descriptor describes a sequence of data.
        :param collection_dimension_count: the number of collection dimensions represented by the descriptor.
        :param datum_dimension_count: the number of datum dimensions represented by the descriptor.

        .. versionadded:: 1.0

        Scriptable: Yes
        """
        return DataAndMetadata.DataDescriptor(is_sequence, collection_dimension_count, datum_dimension_count)

    def create_data_and_metadata(self, data: numpy.ndarray, intensity_calibration: CalibrationModule.Calibration = None,
                                 dimensional_calibrations: typing.List[CalibrationModule.Calibration] = None, metadata: dict = None,
                                 timestamp: str = None, data_descriptor: DataAndMetadata.DataDescriptor = None) -> DataAndMetadata.DataAndMetadata:
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
        return DataAndMetadata.new_data_and_metadata(data, intensity_calibration, dimensional_calibrations, metadata, timestamp, data_descriptor)

    def create_data_and_metadata_from_data(self, data: numpy.ndarray, intensity_calibration: CalibrationModule.Calibration=None, dimensional_calibrations: typing.List[CalibrationModule.Calibration]=None, metadata: dict=None, timestamp: str=None) -> DataAndMetadata.DataAndMetadata:
        """Create a data_and_metadata object from data.

        .. versionadded:: 1.0
        .. deprecated:: 1.1
           Use :py:meth:`~nion.swift.Facade.DataItem.create_data_and_metadata` instead.

        Scriptable: No
        """
        return self.create_data_and_metadata(numpy.copy(data), intensity_calibration, dimensional_calibrations, metadata, timestamp)

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
                data_element = ImportExportManager.create_data_element_from_extended_data(data_and_metadata)
                return [data_element]

            def can_write(self, data_and_metadata, extension):
                return io_handler_delegate.can_write_data_and_metadata(data_and_metadata, extension)

            def write_display_item(self, ui, display_item: DisplayItemModule.DisplayItem, file_path: str, extension: str) -> None:
                data_item = display_item.data_item
                if data_item:
                    self.write_data_item(ui, data_item, file_path, extension)

            def write_data_item(self, ui, data_item, file_path, extension):
                data_and_metadata = data_item.xdata
                data = data_and_metadata.data
                if data is not None:
                    if hasattr(io_handler_delegate, "write_data_item"):
                        io_handler_delegate.write_data_item(DataItem(data_item), file_path, extension)
                    else:
                        assert hasattr(io_handler_delegate, "write_data_and_metadata")
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
                facade_document_controller = DocumentWindow(document_controller)
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
                super()._stop_acquisition()

        class FacadeHardwareSource(HardwareSourceModule.HardwareSource):

            def __init__(self):
                super().__init__(hardware_source_delegate.hardware_source_id, hardware_source_delegate.hardware_source_name)
                self.features["is_video"] = True
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
            panel = Panel(document_controller, panel_delegate, panel_id, properties)
            ui = UserInterface(self.__ui_version, document_controller.ui)
            document_controller = DocumentWindow(document_controller)
            panel.widget = panel_delegate.create_panel_widget(ui, document_controller)._widget
            return panel

        class PanelReference:

            def __init__(self):
                workspace_manager.register_panel(create_facade_panel, panel_id, panel_name, panel_positions, panel_position, properties)

            def close(self):
                pass

        return PanelReference()

    def create_specifier(self, item_uuid: uuid_module.UUID, context_uuid: uuid_module.UUID) -> Persistence.PersistentObjectSpecifier:
        """Create an item specifier from item_uuid and context_uuid.

        .. versionadded:: 2.0

        Scriptable: No
        """
        return Persistence.PersistentObjectSpecifier(item_uuid=item_uuid, context_uuid=context_uuid)

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
        return HardwareSource(hardware_source) if hardware_source else None

    def get_instrument_by_id(self, instrument_id: str, version: str):
        actual_version = "1.0.0"
        if Utility.compare_versions(version, actual_version) > 0:
            raise NotImplementedError("Hardware API requested version %s is greater than %s." % (version, actual_version))
        instrument = HardwareSourceModule.HardwareSourceManager().get_instrument_by_id(instrument_id)
        return Instrument(instrument) if instrument else None

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
        assert self.__app.document_model
        return Library(self.__app.document_model)

    def register_computation_type(self, computation_type_id, compute_class):
        Symbolic.register_computation_type(computation_type_id, compute_class)

    def show(self, item: typing.Any, *parameters) -> None:
        window = self.application.document_windows[0]
        if isinstance(item, numpy.ndarray):
            data_item = self.library.create_data_item_from_data(item)
            window.display_data_item(data_item)
        elif isinstance(item, DataAndMetadata.DataAndMetadata):
            data_item = self.library.create_data_item_from_data_and_metadata(item)
            window.display_data_item(data_item)
        elif isinstance(item, dict) and item.get("type") == "modeless_dialog":
            window.show_modeless_dialog(item, *parameters)

    def run_script(self, *, file_path=None, stdout=None) -> None:
        import ast
        import contextlib
        import os
        with open(file_path) as f:
            script = f.read()
        script_name = os.path.basename(file_path)
        script_ast = ast.parse(script, script_name, 'exec')

        class AddCallFunctionNodeTransformer(ast.NodeTransformer):
            def __init__(self, func_id, arg_id):
                self.__func_id = func_id
                self.__arg_id = arg_id

            def visit_Module(self, node):
                name_expr = ast.Name(id=self.__func_id, ctx=ast.Load())
                arg_expr = ast.Name(id=self.__arg_id, ctx=ast.Load())
                call_expr = ast.Expr(value=ast.Call(func=name_expr, args=[arg_expr], keywords=[]))
                new_node = copy.deepcopy(node)
                new_node.body.append(call_expr)
                ast.fix_missing_locations(new_node)
                return new_node

        # if script_main exists, add a node to call it
        for node in script_ast.body:
            if getattr(node, "name", None) == "script_main":
                script_ast = AddCallFunctionNodeTransformer('script_main', 'api_broker').visit(script_ast)

        compiled = compile(script_ast, script_name, 'exec')

        if not stdout:
            print_fn = print
            class StdoutCatcher:
                def __init__(self):
                    pass
                def write(self, stuff):
                    print_fn(stuff.rstrip())
                def flush(self):
                    pass
            stdout = StdoutCatcher()

        class APIBroker:
            def get_api(self, version, ui_version=None):
                ui_version = ui_version if ui_version else "~1.0"
                return PlugInManager.api_broker_fn(version, ui_version)
            def get_ui(self, version):
                actual_version = "1.0.0"
                if Utility.compare_versions(version, actual_version) > 0:
                    raise NotImplementedError("API requested version %s is greater than %s." % (version, actual_version))
                return Declarative.DeclarativeUI()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stdout):
            g = dict()
            g["api_broker"] = APIBroker()
            g["print"] = stdout.write
            exec(compiled, g)

    def resolve_api_object_specifier(self, d):
        return ObjectSpecifier.resolve(d)

    def _new_api_object(self, object):
        return _new_api_object(object)

    # provisional
    def queue_task(self, fn) -> None:
        self.__app.document_controllers[0].queue_task(fn)

    # provisional
    def clear_queued_tasks(self) -> None:
        self.__app.document_controllers[0].clear_queued_tasks()

    def raise_requirements_exception(self, reason) -> None:
        raise PlugInManager.RequirementsException(reason)


def _new_api_object(object):
    if isinstance(object, DocumentModelModule.DocumentModel):
        return Library(object)
    if isinstance(object, DataItemModule.DataItem):
        return DataItem(object)
    if isinstance(object, DisplayItemModule.DisplayItem):
        return Display(object)
    if isinstance(object, Graphics.Graphic):
        return Graphic(object)
    if isinstance(object, DataItemModule.DataSource):
        return DataSource(object)
    if isinstance(object, Symbolic.Computation):
        return Computation(object)
    if isinstance(object, DataStructureModule.DataStructure):
        return DataStructure(object)
    return None


def _get_api_with_app(version: str, ui_version: str, app: ApplicationModule.Application) -> API_1:
    actual_version = "1.0.0"
    if Utility.compare_versions(version, actual_version) > 0:
        raise NotImplementedError("API requested version %s is greater than %s." % (version, actual_version))
    return API_1(ui_version, app)


def get_api(version: str, ui_version: str=None) -> API_1:
    """Get a versioned interface matching the given version and ui_version.

    version is a string in the form "1.0.2".
    """
    ui_version = ui_version if ui_version else "~1.0"
    return _get_api_with_app(version, ui_version, ApplicationModule.app)


import base64
import functools
import io
import pickle
import threading

from nion.data import Calibration
from nion.data import DataAndMetadata

from xmlrpc.server import SimpleXMLRPCServer

all_classes = API_1, Application, DataGroup, DataItem, Display, DisplayPanel, DocumentWindow, HardwareSource, Instrument, Library, Graphic
class_names = {API_1: "API"}
all_structs = Calibration.Calibration, DataAndMetadata.DataAndMetadata
struct_names = {DataAndMetadata.DataAndMetadata: "ExtendedData"}


class Pickler(pickle.Pickler):

    @classmethod
    def pickle(cls, x):
        f = io.BytesIO()
        cls(f).dump(x)
        return base64.b64encode(f.getvalue()).decode('utf-8')

    def persistent_id(self, obj):
        for class_ in all_classes:
            if isinstance(obj, class_):
                obj_specifier = obj.specifier
                return class_names.get(class_, class_.__name__), getattr(obj_specifier, "rpc_dict", None)
        for struct in all_structs:
            if isinstance(obj, struct):
                return struct_names.get(struct, struct.__name__), obj.rpc_dict
        return None


class Unpickler(pickle.Unpickler):
    def __init__(self, file, api):
        super().__init__(file)
        self.__api = api
    def persistent_load(self, pid):
        type_tag, d = pid
        for class_ in all_classes:
            if type_tag == class_names.get(class_, class_.__name__):
                return self.__api.resolve_api_object_specifier(d)
        for struct in all_structs:
            if type_tag == struct_names.get(struct, struct.__name__):
                return struct.from_rpc_dict(d)

        # Always raises an error if you cannot return the correct object.
        # Otherwise, the unpickler will think None is the object referenced
        # by the persistent ID.
        raise pickle.UnpicklingError("unsupported persistent object")


def queued(method):
    def queued(*args, **kw):
        result_ref = []
        exception_ref = []
        finished_event = threading.Event()
        def run():
            try:
                result_ref.append(method(*args, **kw))
            except Exception as e:
                exception_ref.append(e)
            finally:
                finished_event.set()
        args[0].queue_task(run)
        finished_event.wait()
        if len(exception_ref) > 0:
            raise exception_ref[0]
        return result_ref[0]
    return queued


def call_threadsafe_method(api, pickled_object, method_name, pickled_args, pickled_kwargs):
    object = Unpickler(io.BytesIO(base64.b64decode(pickled_object.encode('utf-8'))), api).load()
    args = Unpickler(io.BytesIO(base64.b64decode(pickled_args.encode('utf-8'))), api).load()
    kwargs = Unpickler(io.BytesIO(base64.b64decode(pickled_kwargs.encode('utf-8'))), api).load()
    result = getattr(object, method_name)(*args, **kwargs)
    return Pickler.pickle(result)


@queued
def call_method(api, pickled_object, method_name, pickled_args, pickled_kwargs):
    return call_threadsafe_method(api, pickled_object, method_name, pickled_args, pickled_kwargs)


@queued
def get_property(api, pickled_object, name):
    object = Unpickler(io.BytesIO(base64.b64decode(pickled_object.encode('utf-8'))), api).load()
    return Pickler.pickle(getattr(object, name))


@queued
def set_property(api, pickled_object, name, pickled_value):
    object = Unpickler(io.BytesIO(base64.b64decode(pickled_object.encode('utf-8'))), api).load()
    value = Unpickler(io.BytesIO(base64.b64decode(pickled_value.encode('utf-8'))), api).load()
    setattr(object, name, value)


class ObjectConverter:

    def __init__(self, item, converter):
        self.__converter = converter

    def convert(self, value):
        """ Convert value to string using format string """
        if value.__class__.__name__ == "Display":
            value = value._item
        return self.__converter.convert(value) if self.__converter else value

    def convert_back(self, formatted_value):
        """ Convert string to value using standard int conversion """
        if formatted_value.__class__.__name__ == "DisplayItem":
            formatted_value = Display(formatted_value)
        return self.__converter.convert_back(formatted_value) if self.__converter else formatted_value


def runOnThread(api):
    server = SimpleXMLRPCServer(("localhost", 8199), allow_none=True, logRequests=False)
    server.register_function(functools.partial(call_method, api), "call_method")
    server.register_function(functools.partial(call_threadsafe_method, api), "call_threadsafe_method")
    server.register_function(functools.partial(get_property, api), "get_property")
    server.register_function(functools.partial(set_property, api), "set_property")
    server.serve_forever()


# this will be called when Facade is imported. this allows the plug-in manager access to the api_broker.
# for this to work, Facade must be imported early in the startup process.
def initialize():
    PlugInManager.register_api_broker_fn(get_api)

def start_server():
    api = get_api(version="1", ui_version="1")
    thread = threading.Thread(target=runOnThread, args=(api, ))
    thread.daemon = True
    thread.start()
