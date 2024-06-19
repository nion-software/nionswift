from __future__ import annotations

# standard libraries
import asyncio
import contextlib
import copy
import functools
import gettext
import math
import random
import string
import threading
import typing
import uuid
import weakref

import numpy.typing

from nion.data import DataAndMetadata
from nion.data import Image
from nion.swift import DataItemThumbnailWidget
from nion.swift import DataPanel
from nion.swift import DisplayCanvasItem
from nion.swift import DisplayScriptCanvasItem
from nion.swift import ImageCanvasItem
from nion.swift import LinePlotCanvasItem
from nion.swift import MimeTypes
from nion.swift import Panel
from nion.swift import Thumbnails
from nion.swift import Undo
from nion.swift.model import Changes
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Persistence
from nion.swift.model import UISettings
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import GridCanvasItem
from nion.ui import UserInterface
from nion.ui import Window
from nion.utils import Color
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel
from nion.utils import Model
from nion.utils import Process
from nion.utils import ReferenceCounting
from nion.utils import Selection
from nion.utils import Stream

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController

_DropRegionType = typing.Tuple[Geometry.IntRect, Geometry.IntRect]
_DropRegionsMapType = typing.Mapping[str, typing.Tuple[Geometry.IntRect, Geometry.IntRect]]
_DropRegionsDictType = typing.Dict[str, typing.Tuple[Geometry.IntRect, Geometry.IntRect]]
_NDArray = numpy.typing.NDArray[typing.Any]
_DocumentControllerWeakRefType = typing.Callable[[], "DocumentController.DocumentController"]

_ = gettext.gettext

_test_log_exceptions = True


# coordinate systems:
#   widget (origin top left, size of the widget)
#   image_norm ((0,0), (1,1))
#   image_pixel (0,0 size of the image in pixels)
#   calibrated


# how sizing works:
#   the canvas is initially set to fit to the space, meaning all of it is visible
#   when the user presses the fit, fill, or 1:1 buttons, the canvas is resized to match that choice
#   when the window is resized, a best attempt is made to keep the view roughly the same. this may
#     be impossible when the shape of the view changes radically.
#   when the user zooms in/out, the canvas is made larger or smaller by the appropriate amount.

# how to make sure it works:
#   if the new view default is 'fill' or '1:1', do the scroll bars come up in the center?
#   for new view, does zoom go into the center point?
#   switch to 'fit', does zoom still go into center point?


# refer to Illustrator / Default keyboard shortcuts
# http://help.adobe.com/en_US/illustrator/cs/using/WS714a382cdf7d304e7e07d0100196cbc5f-6426a.html
# secondary Lightroom:
# http://helpx.adobe.com/lightroom/help/keyboard-shortcuts.html

# KEYS FOR CHOOSING TOOLS               ACTION/KEY
# selection tool (whole object)         v
# direct selection tool (parts)         a
# line tool                             \
# rectangle tool                        m
# ellipse tool                          l
# rotate tool                           r
# scale tool                            s
# hand tool (moving image)              h
# zoom tool (zooming image)             z

# KEYS FOR VIEWING IMAGES               ACTION/KEY
# fit image to area                     double w/ hand tool
# magnify to 100%                       double w/ zoom tool
# fit image to area                     0
# fill image to area                    Shift-0
# make image 1:1                        1
# display original image                o

# KEYS FOR DRAWING GRAPHICS             ACTION/KEY
# constrain shape                       shift-drag
# move while dragging                   spacebar-drag
# drag from center                      alt-drag (Windows), option-drag (Mac OS)

# KEYS FOR SELECTING GRAPHICS           ACTION/KEY
# use last used selection tool          ctrl (Windows), command (Mac OS)
# add/subtract from selection           alt (Windows), option (Mac OS)

# KEYS FOR MOVING SELECTION/IMAGE       ACTION/KEY
# move in small increments              arrow keys
# move in 10x increments                shift- arrow keys

# KEYS FOR USING PANELS                 ACTION/KEY
# hide all panels                       tab
# hide all panels except data panel     shift-tab

# FUNCTION KEYS                         ACTION/KEY
# tbd


class DisplayPanelOverlayCanvasItem(CanvasItem.CanvasItemComposition):
    """
        An overlay for image panels to draw and handle focus, selection, and drop targets.

        The overlay has a focused property, but this is not the same as the canvas focused_item.
        The focused property here is just a flag to indicate whether to draw the focus ring.

        Clients can connect to the following messages:
            on_context_menu_event(x, y, gx, gy)
            on_drag_enter(mime_data)
            on_drag_leave()
            on_drag_move(mime_data, x, y)
            on_drop(mime_data, drop_region, x, y)
            on_key_pressed(key)
            on_key_released(key)
    """

    def __init__(self, get_font_metrics_fn: typing.Callable[[str, str], UISettings.FontMetrics]) -> None:
        super().__init__()
        self.wants_drag_events = True
        self.__get_font_metrics = get_font_metrics_fn
        self.__is_dragging = False
        self.__drop_region = "none"
        self.__focused = False
        self.__selected = False
        self.__selected_style = "#CCC"  # TODO: platform dependent
        self.__focused_style = "#4682B4"  # steel blue. TODO: platform dependent
        self.__selection_number: typing.Optional[int] = None
        self.__line_dash: typing.Optional[int] = None
        self.__drop_regions_map: _DropRegionsDictType = dict()
        self.on_context_menu_event: typing.Optional[typing.Callable[[int, int, int, int], bool]] = None
        self.on_drag_enter: typing.Optional[typing.Callable[[UserInterface.MimeData], str]] = None
        self.on_drag_leave: typing.Optional[typing.Callable[[], str]] = None
        self.on_drag_move: typing.Optional[typing.Callable[[UserInterface.MimeData, int, int], str]] = None
        self.on_wants_drag_event: typing.Optional[typing.Callable[[UserInterface.MimeData], bool]] = None
        self.on_drop: typing.Optional[typing.Callable[[UserInterface.MimeData, str, int, int], str]] = None
        self.on_key_pressed: typing.Optional[typing.Callable[[UserInterface.Key], bool]] = None
        self.on_key_released: typing.Optional[typing.Callable[[UserInterface.Key], bool]] = None
        self.on_mouse_clicked_event: typing.Optional[typing.Callable[[int, int, UserInterface.KeyboardModifiers], bool]] = None
        self.on_adjust_secondary_focus: typing.Optional[typing.Callable[[UserInterface.KeyboardModifiers], None]] = None
        self.on_select_all: typing.Optional[typing.Callable[[], bool]] = None

    def close(self) -> None:
        self.on_context_menu_event = None
        self.on_drag_enter = None
        self.on_drag_leave = None
        self.on_drag_move = None
        self.on_drop = None
        self.on_key_pressed = None
        self.on_key_released = None
        self.on_mouse_clicked_event = None
        self.on_adjust_secondary_focus = None
        self.on_select_all = None
        super().close()

    @property
    def focused(self) -> bool:
        return self.__focused

    @focused.setter
    def focused(self, value: bool) -> None:
        if self.__focused != value:
            self.__focused = value
            self.update()

    @property
    def selected(self) -> bool:
        return self.__selected

    @selected.setter
    def selected(self, selected: bool) -> None:
        if self.__selected != selected:
            self.__selected = selected
            self.update()

    @property
    def selected_style(self) -> str:
        return self.__selected_style

    @selected_style.setter
    def selected_style(self, selected_style: str) -> None:
        if self.__selected_style != selected_style:
            self.__selected_style = selected_style
            self.update()

    @property
    def focused_style(self) -> str:
        return self.__focused_style

    @focused_style.setter
    def focused_style(self, focused_style: str) -> None:
        if self.__focused_style != focused_style:
            self.__focused_style = focused_style
            self.update()

    @property
    def line_dash(self) -> typing.Optional[int]:
        return self.__line_dash

    @line_dash.setter
    def line_dash(self, value: typing.Optional[int]) -> None:
        if self.__line_dash != value:
            self.__line_dash = value
            self.update()

    @property
    def selection_number(self) -> typing.Optional[int]:
        return self.__selection_number

    @selection_number.setter
    def selection_number(self, value: typing.Optional[int]) -> None:
        if self.__selection_number != value:
            self.__selection_number = value
            self.update()

    @property
    def drop_regions_map(self) -> _DropRegionsMapType:
        return self.__drop_regions_map

    @drop_regions_map.setter
    def drop_regions_map(self, value: _DropRegionsMapType) -> None:
        self.__drop_regions_map = dict(value) if value else dict()

    def __set_drop_region(self, drop_region: str) -> None:
        if self.__drop_region != drop_region:
            self.__drop_region = drop_region
            self.update()

    def _set_drop_region(self, drop_region: str) -> None:
        self.__set_drop_region(drop_region)

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        super()._repaint(drawing_context)

        # canvas size
        canvas_size = self.canvas_size
        if canvas_size:
            # draw the border
            with drawing_context.saver():
                drawing_context.begin_path()
                drawing_context.rect(0, 0, canvas_size.width, canvas_size.height)
                drawing_context.line_join = "miter"
                drawing_context.stroke_style = "#AAA"
                drawing_context.line_width = 0.5
                drawing_context.stroke()
    
            drop_regions_map = self.__drop_regions_map
    
            if self.__drop_region != "none":
                with drawing_context.saver():
                    drawing_context.begin_path()
                    if self.__drop_region in drop_regions_map:
                        drop_region_hit_rect, drop_region_draw_rect = drop_regions_map[self.__drop_region]
                        drawing_context.rect(drop_region_draw_rect.left, drop_region_draw_rect.top, drop_region_draw_rect.width, drop_region_draw_rect.height)
                    elif self.__drop_region == "left":
                        drawing_context.rect(0, 0, int(canvas_size.width * 0.10), canvas_size.height)
                    elif self.__drop_region == "right":
                        drawing_context.rect(int(canvas_size.width * 0.90), 0, int(canvas_size.width - canvas_size.width * 0.90), canvas_size.height)
                    elif self.__drop_region == "top":
                        drawing_context.rect(0, 0, canvas_size.width, int(canvas_size.height * 0.10))
                    elif self.__drop_region == "bottom":
                        drawing_context.rect(0, int(canvas_size.height * 0.90), canvas_size.width, int(canvas_size.height - canvas_size.height * 0.90))
                    else:
                        drawing_context.rect(0, 0, canvas_size.width, canvas_size.height)
                    drawing_context.fill_style = "rgba(255, 0, 0, 0.10)"
                    drawing_context.fill()
    
            if self.selected:
                stroke_style = self.__focused_style if self.focused else self.__selected_style
                if stroke_style:
                    with drawing_context.saver():
                        drawing_context.begin_path()
                        drawing_context.rect(2, 2, canvas_size.width - 4, canvas_size.height - 4)
                        drawing_context.line_join = "miter"
                        drawing_context.stroke_style = stroke_style
                        drawing_context.line_width = 4.0
                        if self.__line_dash:
                            with drawing_context.saver():
                                drawing_context.stroke_style = "#CCC"
                                drawing_context.stroke()
                            drawing_context.line_dash = self.__line_dash
                        drawing_context.stroke()
                    if self.__selection_number:
                        with drawing_context.saver():
                            font = "bold 12px serif"
                            selection_number_text = "+" + str(self.__selection_number)
                            font_metrics = self.__get_font_metrics(font, selection_number_text)
                            with drawing_context.saver():
                                drawing_context.fill_style = "rgba(192, 192, 192, 0.75)"
                                drawing_context.begin_path()
                                drawing_context.rect(6, 6, font_metrics.width + 4, font_metrics.height + 4)
                                drawing_context.fill()
                            drawing_context.font = font
                            drawing_context.fill_style = stroke_style
                            drawing_context.fill_text(selection_number_text, 6, 4 + font_metrics.height)

    def mouse_clicked(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_clicked(x, y, modifiers):
            return True
        if self.on_mouse_clicked_event:
            return self.on_mouse_clicked_event(x, y, modifiers)
        return False

    def context_menu_event(self, x: int, y: int, gx: int, gy: int) -> bool:
        if super().context_menu_event(x, y, gx, gy):
            return True
        if self.on_context_menu_event:
            self.on_context_menu_event(x, y, gx, gy)
        return False

    def wants_drag_event(self, mime_data: UserInterface.MimeData, x: int, y: int) -> bool:
        if self.on_wants_drag_event:
            return self.on_wants_drag_event(mime_data)
        return False

    def drag_enter(self, mime_data: UserInterface.MimeData) -> str:
        self.__is_dragging = True
        self.__set_drop_region("none")
        if self.on_drag_enter:
            self.on_drag_enter(mime_data)
        return "ignore"

    def drag_leave(self) -> str:
        self.__is_dragging = False
        self.__set_drop_region("none")
        if self.on_drag_leave:
            self.on_drag_leave()
        return "ignore"

    def drag_move(self, mime_data: UserInterface.MimeData, x: int, y: int) -> str:
        if self.on_drag_move:
            result = self.on_drag_move(mime_data, x, y)
            if result != "ignore":
                canvas_size = self.canvas_size
                if canvas_size:
                    p = Geometry.IntPoint(y=y, x=x)
                    for drop_region, (drop_region_hit_rect, drop_region_draw_rect) in self.__drop_regions_map.items():
                        if drop_region_hit_rect.contains_point(p):
                            self.__set_drop_region(drop_region)
                            return result
                    if x < int(canvas_size.width * 0.10):
                        self.__set_drop_region("left")
                    elif x > int(canvas_size.width * 0.90):
                        self.__set_drop_region("right")
                    elif y < int(canvas_size.height * 0.10):
                        self.__set_drop_region("top")
                    elif y > int(canvas_size.height * 0.90):
                        self.__set_drop_region("bottom")
                    else:
                        self.__set_drop_region("middle")
                    return result
        self.__set_drop_region("none")
        return "ignore"

    def drop(self, mime_data: UserInterface.MimeData, x: int, y: int) -> str:
        drop_region = self.__drop_region
        self.__is_dragging = False
        self.__set_drop_region("none")
        if self.on_drop:
            return self.on_drop(mime_data, drop_region, x, y)
        return "ignore"

    def key_pressed(self, key: UserInterface.Key) -> bool:
        if callable(self.on_key_pressed):
            if self.on_key_pressed(key):
                return True
        return super().key_pressed(key)

    def key_released(self, key: UserInterface.Key) -> bool:
        if callable(self.on_key_released):
            if self.on_key_released(key):
                return True
        return super().key_released(key)

    def handle_select_all(self) -> bool:
        if callable(self.on_select_all):
            return self.on_select_all()
        return False

    def adjust_secondary_focus(self, p: Geometry.IntPoint, modifiers: UserInterface.KeyboardModifiers) -> None:
        if modifiers.any_modifier:
            if callable(self.on_adjust_secondary_focus):
                self.on_adjust_secondary_focus(modifiers)


def create_display_canvas_item(display_item: DisplayItem.DisplayItem, ui_settings: UISettings.UISettings,
                               delegate: typing.Optional[DisplayCanvasItem.DisplayCanvasItemDelegate],
                               event_loop: typing.Optional[asyncio.AbstractEventLoop],
                               draw_background: bool = True) -> DisplayCanvasItem.DisplayCanvasItem:
    display_type = display_item.used_display_type
    if display_type == "line_plot":
        return LinePlotCanvasItem.LinePlotCanvasItem(ui_settings, delegate)
    elif display_type == "image":
        return ImageCanvasItem.ImageCanvasItem(ui_settings, delegate, event_loop, draw_background)
    elif display_type == "display_script":
        return DisplayScriptCanvasItem.DisplayScriptCanvasItem(ui_settings, delegate)
    else:
        return MissingDataCanvasItem(delegate)


def is_valid_display_type(display_type: str) -> bool:
    return display_type in ("image", "line_plot", "display_script")


class DisplayTypeMonitor:
    """Monitor a display for changes to the display type.

    Provides the display_type_changed(display_type) event.

    Provides the display_type r/o property.
    """

    def __init__(self, display_item: DisplayItem.DisplayItem) -> None:
        self.display_type_changed_event = Event.Event()
        self.__display_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.__display_type: typing.Optional[str] = None
        self.__first = True  # handle case where there is no data, so display_type is always None and doesn't change
        if display_item:
            self.__display_changed_event_listener = display_item.display_changed_event.listen(functools.partial(self.__update_display_type, display_item))
        self.__update_display_type(display_item)

    def close(self) -> None:
        if self.__display_changed_event_listener:
            self.__display_changed_event_listener.close()
            self.__display_changed_event_listener = None

    def __update_display_type(self, display_item: DisplayItem.DisplayItem) -> None:
        display_type = display_item.used_display_type if display_item else None
        if self.__display_type != display_type or self.__first:
            self.__display_type = display_type
            self.display_type_changed_event.fire(display_type)
            self.__first = False


class DisplayDataChannelValueStream(Stream.ValueStream[DisplayItem.DisplayDataChannel]):
    def __init__(self, display_item_value_stream: Stream.ValueStream[DisplayItem.DisplayItem]) -> None:
        super().__init__()
        self.__stream = display_item_value_stream.add_ref()
        self.__display_item_item_inserted_listener: typing.Optional[Event.EventListener] = None
        self.__display_item_item_removed_listener: typing.Optional[Event.EventListener] = None
        self.__stream_listener = self.__stream.value_stream.listen(self.__update_display_item)
        self.__display_item: typing.Optional[DisplayItem.DisplayItem] = None
        # display item is initialized to none and updated with update display item, which does a check
        # to see if the display changed. if it did, then the display item listeners are updated.
        self.__update_display_item(self.__stream.value)

    def about_to_delete(self) -> None:
        if self.__display_item_item_inserted_listener:
            self.__display_item_item_inserted_listener.close()
            self.__display_item_item_inserted_listener = None
        if self.__display_item_item_removed_listener:
            self.__display_item_item_removed_listener.close()
            self.__display_item_item_removed_listener = None
        self.__stream_listener.close()
        self.__stream_listener = typing.cast(typing.Any, None)
        self.__stream.remove_ref()
        self.__stream = typing.cast(typing.Any, None)
        super().about_to_delete()

    def __update_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        if display_item != self.__display_item:
            if self.__display_item_item_inserted_listener:
                self.__display_item_item_inserted_listener.close()
                self.__display_item_item_inserted_listener = None
            if self.__display_item_item_removed_listener:
                self.__display_item_item_removed_listener.close()
                self.__display_item_item_removed_listener = None
            self.__display_item = display_item
            if self.__display_item:
                self.__display_item_item_inserted_listener = self.__display_item.item_inserted_event.listen(
                    self.__handle_item_changed)
                self.__display_item_item_removed_listener = self.__display_item.item_inserted_event.listen(
                    self.__handle_item_changed)
            self.value = self.__display_item.display_data_channel if self.__display_item else None

    def __handle_item_changed(self, key: str, value: typing.Any, index: int) -> None:
        if key == "display_data_channels":
            assert self.__display_item
            self.value = self.__display_item.display_data_channel


class DisplayDataChannelDataDescriptorStream(Stream.ValueStream[DataAndMetadata.DataDescriptor]):
    def __init__(self, display_data_channel_stream: Stream.AbstractStream[DisplayItem.DisplayDataChannel]) -> None:
        super().__init__()
        self.__display_data_channel_stream = display_data_channel_stream
        self.__display_data_channel_stream_listener = self.__display_data_channel_stream.value_stream.listen(ReferenceCounting.weak_partial(DisplayDataChannelDataDescriptorStream.__update_display_data_channel, self))
        self.__data_item_listener: typing.Optional[Event.EventListener] = None
        self.__update_display_data_channel(self.__display_data_channel_stream.value)

    def __update_display_data_channel(self, display_data_channel: typing.Optional[DisplayItem.DisplayDataChannel]) -> None:
        if display_data_channel and (data_item := display_data_channel.data_item):
            self.__data_item_listener = data_item.property_changed_event.listen(ReferenceCounting.weak_partial(DisplayDataChannelDataDescriptorStream.__handle_data_item_property_changed, self, data_item))
            self.value = data_item.data_metadata.data_descriptor if data_item.data_metadata else None
        else:
            self.__data_item_listener = None
            self.value = None

    def __handle_data_item_property_changed(self, data_item: DataItem.DataItem, property_name: str) -> None:
        if property_name in ("collection_dimension_count", "is_sequence", "data_modified"):
            self.value = data_item.data_metadata.data_descriptor if data_item.data_metadata else None


class IndexValueAdapter(typing.Protocol):
    def get_index_value_stream(self, display_data_channel_value_stream: Stream.AbstractStream[DisplayItem.DisplayDataChannel]) -> Stream.AbstractStream[float]: ...
    def get_index_value(self, display_data_channel: DisplayItem.DisplayDataChannel) -> float: ...
    def get_index_str(self, display_data_channel: DisplayItem.DisplayDataChannel) -> str: ...
    def apply_index_value_change(self, display_data_channel: DisplayItem.DisplayDataChannel, value_change: Stream.ValueChange[float]) -> None: ...


class CollectionIndexAdapter(IndexValueAdapter):

    def __init__(self, document_controller: DocumentController.DocumentController, collection_index: int) -> None:
        self.__document_controller = document_controller
        self.__collection_index = collection_index

    def get_index_value_stream(self, display_data_channel_value_stream: Stream.AbstractStream[DisplayItem.DisplayDataChannel]) -> Stream.AbstractStream[float]:
        # given a display data channel stream, return a stream of the collection index values
        # an additional complexity is that if the underlying data changes, output stream needs to be updated
        # to accomplish this, we combine the display data channel stream with a stream of the data descriptor
        # to give a stream of tuples of (data_descriptor, display_data_channel) which we use to filter the stream
        # and then map the tuple back down to the display_data_channel from which we extract the sequence index.

        data_descriptor_value_stream = DisplayDataChannelDataDescriptorStream(display_data_channel_value_stream)
        combined_value_stream = Stream.CombineLatestStream[typing.Any, typing.Any]([data_descriptor_value_stream, display_data_channel_value_stream])

        def filter_combined_stream(tuple_value: typing.Optional[typing.Tuple[typing.Optional[DataAndMetadata.DataDescriptor], typing.Optional[DisplayItem.DisplayDataChannel]]]) -> bool:
            if tuple_value is not None:
                data_descriptor, display_data_channel = tuple_value
                return data_descriptor is not None and display_data_channel is not None and self.__collection_index < display_data_channel.collection_rank and display_data_channel.datum_rank == 2
            return False

        optional_display_data_channel_value_stream = Stream.OptionalStream(combined_value_stream, filter_combined_stream)

        def select_display_data_channel_from_tuple(tuple_value: typing.Optional[typing.Tuple[typing.Optional[DataAndMetadata.DataDescriptor], typing.Optional[DisplayItem.DisplayDataChannel]]]) -> typing.Optional[DisplayItem.DisplayDataChannel]:
            return tuple_value[1] if tuple_value is not None else None

        filtered_display_data_channel_value_stream = Stream.MapStream(optional_display_data_channel_value_stream, select_display_data_channel_from_tuple)

        def select_collection_index(collection_index: typing.Optional[typing.Tuple[int, ...]]) -> typing.Optional[int]:
            return collection_index[self.__collection_index] if collection_index is not None else None

        return Stream.MapStream(Stream.PropertyChangedEventStream(filtered_display_data_channel_value_stream, "collection_index"), select_collection_index)

    def get_index_value(self, display_data_channel: DisplayItem.DisplayDataChannel) -> float:
        index = self.__collection_index + (1 if display_data_channel.is_sequence else 0)
        dim_length = display_data_channel.dimensional_shape[index] if display_data_channel.dimensional_shape is not None else 0
        return display_data_channel.collection_index[self.__collection_index] / (dim_length - 1)

    def get_index_str(self, display_data_channel: DisplayItem.DisplayDataChannel) -> str:
        return str(display_data_channel.collection_index[self.__collection_index])

    def apply_index_value_change(self, display_data_channel: DisplayItem.DisplayDataChannel, value_change: Stream.ValueChange[float]) -> None:
        # mark the index property as a ghost when beginning the value change stream and restore it
        # when finished. this avoids writing to disk while the slider is dragging.
        if value_change.is_begin:
            display_data_channel.ghost_properties.update(["collection_index"])
        elif value_change.is_end:
            display_data_channel.ghost_properties.subtract(["collection_index"])
            self.set_index_value(display_data_channel, value_change.value or 0.0, True)
        else:
            self.set_index_value(display_data_channel, value_change.value or 0.0, False)

    def set_index_value(self, display_data_channel: DisplayItem.DisplayDataChannel, value: float, force_update: bool) -> None:
        index = self.__collection_index + (1 if display_data_channel.is_sequence else 0)
        dim_length = display_data_channel.dimensional_shape[index] if display_data_channel.dimensional_shape is not None else 0
        collection_index = list(display_data_channel.collection_index)
        collection_index[self.__collection_index] = round(value * (dim_length - 1))
        # display_data_channel.collection_index = collection_index
        document_model = self.__document_controller.document_model
        command = ChangeDisplayDataChannelCommand(document_model, display_data_channel, title=_("Change Display"),
                                                  command_id="change_display_collection_index", is_mergeable=True,
                                                  **{"collection_index": collection_index})
        command.perform()
        self.__document_controller.push_undo_command(command)
        if force_update:
            # this is required since the property had been a ghost property and the set property machinery
            # will skip writing if the value doesn't change. this forces the write to properties.
            display_data_channel._set_persistent_property_value("collection_index", collection_index, True)


class SequenceIndexAdapter(IndexValueAdapter):

    def __init__(self, document_controller: DocumentController.DocumentController) -> None:
        self.__document_controller = document_controller

    def get_index_value_stream(self, display_data_channel_value_stream: Stream.AbstractStream[DisplayItem.DisplayDataChannel]) -> Stream.AbstractStream[float]:
        # given a display data channel stream, return a stream of the sequence index value
        # an additional complexity is that if the underlying data changes, output stream needs to be updated
        # to accomplish this, we combine the display data channel stream with a stream of the data descriptor
        # to give a stream of tuples of (data_descriptor, display_data_channel) which we use to filter the stream
        # and then map the tuple back down to the display_data_channel from which we extract the sequence index.

        data_descriptor_value_stream = DisplayDataChannelDataDescriptorStream(display_data_channel_value_stream)
        combined_value_stream = Stream.CombineLatestStream[typing.Any, typing.Any]([data_descriptor_value_stream, display_data_channel_value_stream])

        def filter_combined_stream(tuple_value: typing.Optional[typing.Tuple[typing.Optional[DataAndMetadata.DataDescriptor], typing.Optional[DisplayItem.DisplayDataChannel]]]) -> bool:
            if tuple_value is not None:
                data_descriptor, display_data_channel = tuple_value
                return data_descriptor is not None and display_data_channel is not None and display_data_channel.is_sequence
            return False

        optional_display_data_channel_value_stream = Stream.OptionalStream(combined_value_stream, filter_combined_stream)

        def select_display_data_channel_from_tuple(tuple_value: typing.Optional[typing.Tuple[typing.Optional[DataAndMetadata.DataDescriptor], typing.Optional[DisplayItem.DisplayDataChannel]]]) -> typing.Optional[DisplayItem.DisplayDataChannel]:
            return tuple_value[1] if tuple_value is not None else None

        filtered_display_data_channel_value_stream = Stream.MapStream(optional_display_data_channel_value_stream, select_display_data_channel_from_tuple)
        return Stream.PropertyChangedEventStream(filtered_display_data_channel_value_stream, "sequence_index")

    def get_index_value(self, display_data_channel: DisplayItem.DisplayDataChannel) -> float:
        sequence_length = display_data_channel.dimensional_shape[0] if display_data_channel.dimensional_shape is not None else 0
        return display_data_channel.sequence_index / (sequence_length - 1) if sequence_length > 1 else 0.0

    def get_index_str(self, display_data_channel: DisplayItem.DisplayDataChannel) -> str:
        return str(display_data_channel.sequence_index)

    def apply_index_value_change(self, display_data_channel: DisplayItem.DisplayDataChannel, value_change: Stream.ValueChange[float]) -> None:
        # mark the index property as a ghost when beginning the value change stream and restore it
        # when finished. this avoids writing to disk while the slider is dragging.
        if value_change.is_begin:
            display_data_channel.ghost_properties.update(["sequence_index"])
        elif value_change.is_end:
            display_data_channel.ghost_properties.subtract(["sequence_index"])
            self.set_index_value(display_data_channel, value_change.value or 0.0, True)
        else:
            self.set_index_value(display_data_channel, value_change.value or 0.0, False)

    def set_index_value(self, display_data_channel: DisplayItem.DisplayDataChannel, value: float, force_update: bool) -> None:
        sequence_length = display_data_channel.dimensional_shape[0] if display_data_channel.dimensional_shape is not None else 0
        sequence_index = round(value * (sequence_length - 1))
        self.set_index_int_value(display_data_channel, sequence_index, force_update)

    def set_index_int_value(self, display_data_channel: DisplayItem.DisplayDataChannel, sequence_index: int, force_update: bool = False) -> None:
        # display_data_channel.sequence_index = sequence_index
        document_model = self.__document_controller.document_model
        command = ChangeDisplayDataChannelCommand(document_model, display_data_channel, title=_("Change Display"),
                                                  command_id="change_display_sequence_index", is_mergeable=True,
                                                  **{"sequence_index": sequence_index})
        command.perform()
        self.__document_controller.push_undo_command(command)
        if force_update:
            # this is required since the property had been a ghost property and the set property machinery
            # will skip writing if the value doesn't change. this forces the write to properties.
            display_data_channel._set_persistent_property_value("sequence_index", sequence_index, True)


class IndexValueSliderCanvasItem(CanvasItem.CanvasItemComposition):
    def __init__(self, title: str, display_item_value_stream: Stream.ValueStream[DisplayItem.DisplayItem],
                 index_value_adapter: IndexValueAdapter,
                 get_font_metrics_fn: typing.Callable[[str, str], UserInterface.FontMetrics],
                 event_loop: typing.Optional[asyncio.AbstractEventLoop] = None,
                 play_button_handler: typing.Optional[typing.Callable[[], None]] = None,
                 play_button_model: typing.Optional[Model.PropertyModel[bool]] = None) -> None:
        super().__init__()
        self.__event_loop = event_loop
        self.layout = CanvasItem.CanvasItemRowLayout()
        self.update_sizing(self.sizing.with_preferred_height(0))
        self.__slider_row = CanvasItem.CanvasItemComposition()
        self.__slider_row.layout = CanvasItem.CanvasItemRowLayout(spacing=4)
        self.__slider_canvas_item = CanvasItem.SliderCanvasItem()
        self.__slider_text = CanvasItem.StaticTextCanvasItem("9999")
        self.add_spacing(12)
        self.add_canvas_item(self.__slider_row)
        self.add_stretch()
        self.add_spacing(12)
        self.__display_item_value_stream = display_item_value_stream.add_ref()
        self.__get_font_metrics_fn = get_font_metrics_fn
        self.__value_change_stream_reactor: typing.Optional[Stream.ValueChangeStreamReactor[float]] = None
        self.__title = title
        self.__index_value_adapter = index_value_adapter
        self.__display_data_channel_value_stream = DisplayDataChannelValueStream(self.__display_item_value_stream)
        index_value_stream = self.__index_value_adapter.get_index_value_stream(self.__display_data_channel_value_stream)
        combined_stream = Stream.CombineLatestStream[typing.Any, typing.Any]([self.__display_item_value_stream, self.__display_data_channel_value_stream, index_value_stream])
        self.__stream_action = Stream.ValueStreamAction[typing.Tuple[DisplayItem.DisplayItem, DisplayItem.DisplayDataChannel, int]](combined_stream, self.__index_changed)
        self.__play_button_handler = play_button_handler
        self.__play_button_model = play_button_model
        self.__index_changed(combined_stream.value)

    def close(self) -> None:
        self.__stream_action.close()
        self.__stream_action = typing.cast(typing.Any, None)
        self.__display_item_value_stream.remove_ref()
        self.__display_item_value_stream = typing.cast(typing.Any, None)
        self.__value_change_stream_reactor = None
        super().close()

    def __index_changed(self, args: typing.Optional[typing.Tuple[DisplayItem.DisplayItem, DisplayItem.DisplayDataChannel, typing.Optional[int]]]) -> None:
        display_item, display_data_channel, index_value = args if args else (None, None, 0)
        if display_data_channel and index_value is not None:
            if not self.__slider_row.canvas_items:

                # async loop to track a value change stream from the slider canvas item.
                # the value change stream will be produced when the user changes the value
                # of the slider by either dragging or paging the thumb.
                async def track_slider_canvas_item_value(index_value_adapter: IndexValueAdapter,
                                                         display_data_channel_value_stream: Stream.ValueStream[DisplayItem.DisplayDataChannel],
                                                         r: Stream.ValueChangeStreamReactorInterface[float]) -> None:
                    while True:
                        value_change = await r.next_value_change()
                        if value_change.is_end:
                            break
                        display_data_channel = display_data_channel_value_stream.value
                        if display_data_channel:
                            index_value_adapter.apply_index_value_change(display_data_channel, value_change)
                        else:
                            break

                self.__value_change_stream_reactor = Stream.ValueChangeStreamReactor[float](
                    self.__slider_canvas_item.value_change_stream,
                    functools.partial(track_slider_canvas_item_value, self.__index_value_adapter, self.__display_data_channel_value_stream),
                    self.__event_loop)

                label = CanvasItem.StaticTextCanvasItem("WWW")
                label.size_to_content(self.__get_font_metrics_fn)
                label.text = self.__title
                self.__slider_row.add_canvas_item(label)
                if self.__play_button_model and callable(self.__play_button_handler):
                    def play_button_model_changed(value: typing.Optional[bool]) -> None:
                        value = value or False
                        play_pause_button.text = "\N{BLACK SQUARE}" if value else "\N{BLACK RIGHT-POINTING TRIANGLE}"
                        play_pause_button.size_to_content(self.__get_font_metrics_fn)

                    play_pause_button = CanvasItem.TextButtonCanvasItem("\N{BLACK RIGHT-POINTING TRIANGLE}")
                    play_pause_button.text_font = "12px"
                    play_pause_button.size_to_content(self.__get_font_metrics_fn)
                    play_pause_button.on_button_clicked = self.__play_button_handler
                    play_button_model_changed(self.__play_button_model.value or False)
                    self.__play_button_model.on_value_changed = play_button_model_changed
                    self.__slider_row.add_canvas_item(play_pause_button)
                    self.__slider_row.add_spacing(0)
                self.__slider_row.add_canvas_item(self.__slider_canvas_item)
                self.__slider_row.add_canvas_item(self.__slider_text)
            self.__slider_text.text = self.__index_value_adapter.get_index_str(display_data_channel)
            self.__slider_text.size_to_content(self.__get_font_metrics_fn)
            self.__slider_canvas_item.value = self.__index_value_adapter.get_index_value(display_data_channel)
            self.__slider_canvas_item.update_sizing(self.__slider_canvas_item.sizing.with_preferred_width(360))
        else:
            self.__value_change_stream_reactor = None
            self.__slider_row.remove_all_canvas_items()
            self.__slider_canvas_item = CanvasItem.SliderCanvasItem()
            self.__slider_text = CanvasItem.StaticTextCanvasItem("9999")


_RelatedItemsTuple = typing.Tuple[typing.List[DisplayItem.DisplayItem], typing.List[DisplayItem.DisplayItem]]

class RelatedItemsValueStream(Stream.ValueStream[_RelatedItemsTuple]):
    def __init__(self, document_model: DocumentModel.DocumentModel, display_item_value_stream: Stream.ValueStream[DisplayItem.DisplayItem]) -> None:
        super().__init__()
        self.__document_model = document_model
        self.__display_item_stream = display_item_value_stream.add_ref()
        self.__stream_listener = self.__display_item_stream.value_stream.listen(self.__update_display_item)
        self.__related_items_changed_listener: typing.Optional[Event.EventListener] = None
        self.__update_display_item(self.__display_item_stream.value)

    def about_to_delete(self) -> None:
        self.__stream_listener.close()
        self.__stream_listener = typing.cast(typing.Any, None)
        self.__display_item_stream.remove_ref()
        self.__display_item_stream = typing.cast(typing.Any, None)
        if self.__related_items_changed_listener:
            self.__related_items_changed_listener.close()
            self.__related_items_changed_listener = None
        super().about_to_delete()

    def __update_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        if self.__related_items_changed_listener:
            self.__related_items_changed_listener.close()
            self.__related_items_changed_listener = None
        if display_item:
            self.__related_items_changed_listener = self.__document_model.related_items_changed.listen(self.__related_items_changed)
            source_display_items = self.__document_model.get_source_display_items(display_item)
            dependent_display_items = self.__document_model.get_dependent_display_items(display_item)
            self.__related_items_changed(display_item, source_display_items, dependent_display_items)
        else:
            self.__related_items_changed(display_item, [], [])

    def __related_items_changed(self, display_item: typing.Optional[DisplayItem.DisplayItem], source_display_items: typing.List[DisplayItem.DisplayItem], dependent_display_items: typing.List[DisplayItem.DisplayItem]) -> None:
        if display_item == self.__display_item_stream.value:
            self.value = source_display_items, dependent_display_items


class RelatedIconsCanvasItem(CanvasItem.CanvasItemComposition):
    def __init__(self, ui: UserInterface.UserInterface, document_model: DocumentModel.DocumentModel,
                 display_item_value_stream: Stream.ValueStream[DisplayItem.DisplayItem],
                 drag_fn: typing.Callable[[UserInterface.MimeData, typing.Optional[_NDArray], int, int], None]) -> None:
        super().__init__()
        self.layout = CanvasItem.CanvasItemRowLayout()
        self.update_sizing(self.sizing.with_preferred_height(0))
        self.ui = ui
        self.__drag_fn = drag_fn
        self.__thumbnail_size = Geometry.IntSize(height=24, width=24)
        self.__source_thumbnails = CanvasItem.CanvasItemComposition()
        self.__source_thumbnails.layout = CanvasItem.CanvasItemRowLayout(spacing=8)
        self.__dependent_thumbnails = CanvasItem.CanvasItemComposition()
        self.__dependent_thumbnails.layout = CanvasItem.CanvasItemRowLayout(spacing=8)
        self.__source_display_items = list[DisplayItem.DisplayItem]()
        self.__dependent_display_items = list[DisplayItem.DisplayItem]()
        self.add_spacing(12)
        self.add_canvas_item(self.__source_thumbnails)
        self.add_stretch()
        self.add_canvas_item(self.__dependent_thumbnails)
        self.add_spacing(12)
        related_items_value_stream = RelatedItemsValueStream(document_model, display_item_value_stream)
        self.__related_items_stream_action = Stream.ValueStreamAction[_RelatedItemsTuple](related_items_value_stream, self.__related_items_changed)
        self.__related_items_changed(related_items_value_stream.value)

    def close(self) -> None:
        self.__related_items_stream_action.close()
        self.__related_items_stream_action = typing.cast(typing.Any, None)
        self.__source_display_items.clear()
        self.__dependent_display_items.clear()
        super().close()

    @property
    def _source_thumbnails(self) -> CanvasItem.CanvasItemComposition:
        return self.__source_thumbnails

    @property
    def _dependent_thumbnails(self) -> CanvasItem.CanvasItemComposition:
        return self.__dependent_thumbnails

    def __related_items_changed(self, items: typing.Optional[_RelatedItemsTuple]) -> None:
        assert items is not None
        source_display_items, dependent_display_items = items

        # try to reuse thumbnail canvas items if possible. the algorithm runs through the max of source display items
        # and canvas items. for iteration, if both source and canvas item exist, update it if it is changed. if only
        # the source item exists, create a new canvas item and add it to the canvas. if only the canvas item exists,
        # remove it from the canvas. this is repeated for the dependent display items. the canvas items for the list
        # of canvas items are stored in the source_display_items and dependent_display_items lists respectively, to
        # allow for quick comparison and updating.

        for index in range(max(len(source_display_items), self.__source_thumbnails.canvas_items_count)):
            source_display_item = source_display_items[index] if index < len(source_display_items) else None
            thumbnail_canvas_item = typing.cast(DataItemThumbnailWidget.ThumbnailCanvasItem, self.__source_thumbnails.canvas_items[index]) if index < self.__source_thumbnails.canvas_items_count else None
            if source_display_item and thumbnail_canvas_item:
                thumbnail_canvas_item = typing.cast(DataItemThumbnailWidget.ThumbnailCanvasItem, self.__source_thumbnails.canvas_items[index])
                if self.__source_display_items[index] != source_display_item:
                    thumbnail_canvas_item.set_thumbnail_source(DataItemThumbnailWidget.DataItemThumbnailSource(self.ui, display_item=source_display_item))
                    self.__source_display_items[index] = source_display_item
            elif not source_display_item and thumbnail_canvas_item:
                self.__source_thumbnails.remove_canvas_item(self.__source_thumbnails.canvas_items[-1])
                self.__source_display_items.pop(-1)
            elif source_display_item and not thumbnail_canvas_item:
                thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(self.ui, display_item=source_display_items[index])
                thumbnail_canvas_item = DataItemThumbnailWidget.ThumbnailCanvasItem(self.ui, thumbnail_source, self.__thumbnail_size)
                thumbnail_canvas_item.update_sizing(thumbnail_canvas_item.sizing.with_fixed_height(self.__thumbnail_size.height))
                thumbnail_canvas_item.on_drag = self.__drag_fn
                self.__source_thumbnails.add_canvas_item(thumbnail_canvas_item)
                self.__source_display_items.append(source_display_item)

        for index in range(max(len(dependent_display_items), self.__dependent_thumbnails.canvas_items_count)):
            dependent_display_item = dependent_display_items[index] if index < len(dependent_display_items) else None
            thumbnail_canvas_item = typing.cast(DataItemThumbnailWidget.ThumbnailCanvasItem, self.__dependent_thumbnails.canvas_items[index]) if index < self.__dependent_thumbnails.canvas_items_count else None
            if dependent_display_item and thumbnail_canvas_item:
                thumbnail_canvas_item = typing.cast(DataItemThumbnailWidget.ThumbnailCanvasItem, self.__dependent_thumbnails.canvas_items[index])
                if self.__dependent_display_items[index] != dependent_display_item:
                    thumbnail_canvas_item.set_thumbnail_source(DataItemThumbnailWidget.DataItemThumbnailSource(self.ui, display_item=dependent_display_item))
                    self.__dependent_display_items[index] = dependent_display_item
            elif not dependent_display_item and thumbnail_canvas_item:
                self.__dependent_thumbnails.remove_canvas_item(self.__dependent_thumbnails.canvas_items[-1])
                self.__dependent_display_items.pop(-1)
            elif dependent_display_item and not thumbnail_canvas_item:
                thumbnail_dependent = DataItemThumbnailWidget.DataItemThumbnailSource(self.ui, display_item=dependent_display_items[index])
                thumbnail_canvas_item = DataItemThumbnailWidget.ThumbnailCanvasItem(self.ui, thumbnail_dependent, self.__thumbnail_size)
                thumbnail_canvas_item.update_sizing(thumbnail_canvas_item.sizing.with_fixed_height(self.__thumbnail_size.height))
                thumbnail_canvas_item.on_drag = self.__drag_fn
                self.__dependent_thumbnails.add_canvas_item(thumbnail_canvas_item)
                self.__dependent_display_items.append(dependent_display_item)


class MissingDataCanvasItem(DisplayCanvasItem.DisplayCanvasItem):
    """ Canvas item to draw background_color. """
    def __init__(self, delegate: typing.Optional[DisplayCanvasItem.DisplayCanvasItemDelegate]) -> None:
        super().__init__()
        self.__delegate = delegate

    def context_menu_event(self, x: int, y: int, gx: int, gy: int) -> bool:
        return self.__delegate.show_display_context_menu(gx, gy) if self.__delegate else False

    @property
    def key_contexts(self) -> typing.Sequence[str]:
        return ["display_panel"]

    def add_display_control(self, display_control_canvas_item: CanvasItem.AbstractCanvasItem, role: typing.Optional[str] = None) -> None:
        display_control_canvas_item.close()

    def handle_auto_display(self) -> bool:
        # enter key has been pressed
        return False

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        # canvas size
        canvas_size = self.canvas_size
        if canvas_size:
            with drawing_context.saver():
                drawing_context.begin_path()
                drawing_context.rect(0, 0, canvas_size.width, canvas_size.height)
                drawing_context.fill_style = "#CCC"
                drawing_context.fill()
                drawing_context.begin_path()
                drawing_context.rect(0, 0, canvas_size.width, canvas_size.height)
                drawing_context.move_to(0, 0)
                drawing_context.line_to(canvas_size.width, canvas_size.height)
                drawing_context.move_to(0, canvas_size.height)
                drawing_context.line_to(canvas_size.width, 0)
                drawing_context.stroke_style = "#444"
                drawing_context.stroke()


class DisplayTracker:
    """Tracks messages from a display and passes them to associated display canvas item."""

    def __init__(self, display_item: DisplayItem.DisplayItem, ui_settings: UISettings.UISettings,
                 delegate: DisplayCanvasItem.DisplayCanvasItemDelegate, event_loop: asyncio.AbstractEventLoop,
                 draw_background: bool) -> None:
        self.__display_item = display_item
        self.__ui_settings = ui_settings
        self.__delegate = delegate
        self.__event_loop = event_loop
        self.__draw_background = draw_background
        self.__closing_lock = threading.RLock()

        # callbacks
        self.on_clear_display: typing.Optional[typing.Callable[[], None]] = None
        self.on_title_changed: typing.Optional[typing.Callable[[str], None]] = None
        self.on_replace_display_canvas_item: typing.Optional[typing.Callable[[DisplayCanvasItem.DisplayCanvasItem, DisplayCanvasItem.DisplayCanvasItem], None]] = None

        def clear_display() -> None:
            if callable(self.on_clear_display):
                self.on_clear_display()

        def display_item_property_changed(key: str) -> None:
            if key == "displayed_title":
                if callable(self.on_title_changed):
                    self.on_title_changed(display_item.displayed_title)

        self.__display_about_to_be_removed_event_listener = display_item.about_to_be_removed_event.listen(clear_display)
        self.__display_property_changed_event_listener = display_item.property_changed_event.listen(display_item_property_changed)

        # ensure data stays in memory while displayed
        display_item.increment_display_ref_count()

        # create a canvas item and add it to the container canvas item.

        self.__display_canvas_item = create_display_canvas_item(display_item, ui_settings, delegate, event_loop, draw_background=self.__draw_background)

        def handle_display_data_delta(display_data_delta: typing.Optional[DisplayItem.DisplayDataDelta]) -> None:
            with self.__closing_lock:
                assert display_data_delta
                self.__display_canvas_item.update_display_data_delta(display_data_delta)

        self.__display_data_delta_stream_action = Stream.ValueStreamAction[DisplayItem.DisplayDataDelta](display_item.display_data_delta_stream, handle_display_data_delta)

        def display_type_changed(display_type: typing.Optional[str]) -> None:
            # called when the display type of the data item changes.
            self.__display_data_delta_stream_action = typing.cast(typing.Any, None)
            old_display_canvas_item = self.__display_canvas_item
            new_display_canvas_item = create_display_canvas_item(display_item, ui_settings, self.__delegate, self.__event_loop, draw_background=self.__draw_background)
            if callable(self.on_replace_display_canvas_item):
                self.on_replace_display_canvas_item(old_display_canvas_item, new_display_canvas_item)
            self.__display_canvas_item = new_display_canvas_item
            self.__display_data_delta_stream_action = Stream.ValueStreamAction[DisplayItem.DisplayDataDelta](display_item.display_data_delta_stream, handle_display_data_delta)
            display_data_delta = display_item.display_data_delta_stream.value
            assert display_data_delta
            display_data_delta.mark_changed()
            handle_display_data_delta(display_data_delta)

        self.__display_type_monitor = DisplayTypeMonitor(display_item)
        self.__display_type_changed_event_listener =  self.__display_type_monitor.display_type_changed_event.listen(display_type_changed)

        display_data_delta = display_item.display_data_delta_stream.value
        assert display_data_delta
        display_data_delta.mark_changed()
        handle_display_data_delta(display_data_delta)

    def close(self) -> None:
        with self.__closing_lock:  # ensures that display pipeline finishes
            self.__display_type_changed_event_listener.close()
            self.__display_type_changed_event_listener = typing.cast(typing.Any, None)
            self.__display_type_monitor.close()
            self.__display_type_monitor = typing.cast(typing.Any, None)
            # decrement the ref count on the old item to release it from memory if no longer used.
            self.__display_item.decrement_display_ref_count()
            self.__display_about_to_be_removed_event_listener.close()
            self.__display_about_to_be_removed_event_listener = typing.cast(typing.Any, None)
            self.__display_property_changed_event_listener.close()
            self.__display_property_changed_event_listener = typing.cast(typing.Any, None)
            self.__display_canvas_item = typing.cast(typing.Any, None)
            self.__display_data_delta_stream_action = typing.cast(typing.Any, None)

    @property
    def display_canvas_item(self) -> DisplayCanvasItem.DisplayCanvasItem:
        return self.__display_canvas_item

    @display_canvas_item.setter
    def display_canvas_item(self, value: DisplayCanvasItem.DisplayCanvasItem) -> None:
        self.__display_canvas_item = value


class InsertGraphicsCommand(Undo.UndoableCommand):

    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem, graphics: typing.Sequence[Graphics.Graphic], *,
                 existing_graphics: typing.Optional[typing.Sequence[Graphics.Graphic]] = None) -> None:
        super().__init__(_("Insert Graphics"))
        self.__document_controller = document_controller
        self.__display_item_proxy = display_item.create_proxy()
        self.__graphics = graphics  # only used for perform
        workspace_controller = self.__document_controller.workspace_controller
        assert workspace_controller
        self.__old_workspace_layout: typing.Optional[Persistence.PersistentDictType] = workspace_controller.deconstruct()
        self.__new_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None
        self.__graphics_properties = None
        self.__graphic_proxies = [graphic.create_proxy() for graphic in existing_graphics or list()]
        self.__undelete_logs: typing.List[Changes.UndeleteLog] = list()
        self.initialize()

    def close(self) -> None:
        self.__graphics_properties = None
        self.__document_controller = typing.cast(typing.Any, None)
        self.__old_workspace_layout = None
        self.__new_workspace_layout = None
        for undelete_log in self.__undelete_logs:
            undelete_log.close()
        self.__undelete_logs = typing.cast(typing.Any, None)
        for graphic_proxy in self.__graphic_proxies:
            graphic_proxy.close()
        self.__graphic_proxies = typing.cast(typing.Any, None)
        self.__display_item_proxy.close()
        self.__display_item_proxy = typing.cast(typing.Any, None)
        super().close()

    def perform(self) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            graphics = self.__graphics
            for graphic in graphics:
                display_item.add_graphic(graphic)
                new_graphic = display_item.graphics[-1]
                self.__graphic_proxies.append(new_graphic.create_proxy())
            self.__graphics = typing.cast(typing.Any, None)

    def _get_modified_state(self) -> typing.Any:
        display_item = self.__display_item_proxy.item
        display_item_modified_state = display_item.modified_state if display_item else None
        workspace_controller = self.__document_controller.workspace_controller
        document_model_modified_state = workspace_controller.document_model.modified_state if workspace_controller else None
        return display_item_modified_state, document_model_modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.modified_state = modified_state[0]
        workspace_controller = self.__document_controller.workspace_controller
        if workspace_controller:
            workspace_controller.document_model.modified_state = modified_state[1]

    def _redo(self) -> None:
        for undelete_log in reversed(self.__undelete_logs):
            self.__document_controller.document_model.undelete_all(undelete_log)
            undelete_log.close()
        self.__undelete_logs.clear()
        workspace_controller = self.__document_controller.workspace_controller
        if workspace_controller and self.__new_workspace_layout is not None:
            workspace_controller.reconstruct(self.__new_workspace_layout)

    def _undo(self) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            graphics = [graphic_proxy.item for graphic_proxy in self.__graphic_proxies]
            workspace_controller = self.__document_controller.workspace_controller
            if workspace_controller:
                self.__new_workspace_layout = workspace_controller.deconstruct()
                for graphic in graphics:
                    if graphic:
                        self.__undelete_logs.append(display_item.remove_graphic(graphic, safe=True))
                if self.__old_workspace_layout is not None:
                    workspace_controller.reconstruct(self.__old_workspace_layout)


class AppendDisplayDataChannelCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem,
                 data_item: DataItem.DataItem, display_layer: DisplayItem.DisplayLayer, *, title: typing.Optional[str] = None,
                 command_id: typing.Optional[str] = None, **kwargs: typing.Any) -> None:
        super().__init__(title if title else _("Append Display"), command_id=command_id)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__data_item_proxy = data_item.create_proxy()
        self.__display_layer = copy.deepcopy(display_layer)
        self.__old_properties: typing.Optional[DisplayItem.DisplayItemSaveProperties] = None
        self.__display_data_channel_index = 0
        self.__value_dict = kwargs
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__display_item_proxy.close()
        self.__display_item_proxy = typing.cast(typing.Any, None)
        self.__data_item_proxy.close()
        self.__data_item_proxy = typing.cast(typing.Any, None)
        super().close()

    def perform(self) -> None:
        display_item = self.__display_item_proxy.item
        data_item = self.__data_item_proxy.item
        if display_item and data_item:
            self.__old_properties = display_item.save_properties()
            display_layer = copy.deepcopy(self.__display_layer)
            with contextlib.closing(display_layer):
                display_layer_color_str = display_layer.fill_color or display_layer.stroke_color or DisplayItem.DisplayItem.DEFAULT_COLORS[0]
                display_layer_color_str = display_item.get_unique_display_layer_color(Color.Color(display_layer_color_str))
                display_layer.fill_color = None
                display_layer.stroke_color = display_layer_color_str
                display_layer_properties = display_layer.get_display_layer_properties()
            display_item.append_display_data_channel_for_data_item(data_item, display_layer_properties)
            self.__display_data_channel_index = display_item.display_data_channels.index(display_item.get_display_data_channel_for_data_item(data_item))

    def _get_modified_state(self) -> typing.Any:
        display_item = self.__display_item_proxy.item
        display_item_modified_state = display_item.modified_state if display_item else None
        data_item = self.__data_item_proxy.item
        data_item_modified_state = data_item.modified_state if data_item else None
        return data_item_modified_state, display_item_modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        display_item = self.__display_item_proxy.item
        data_item = self.__data_item_proxy.item
        if data_item:
            data_item.modified_state = modified_state[0]
        if display_item:
            display_item.modified_state = modified_state[1]
        self.__document_model.modified_state = modified_state[2]

    def _undo(self) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_data_channel = display_item.display_data_channels[self.__display_data_channel_index]
            display_item.remove_display_data_channel(display_data_channel, safe=True).close()
            if self.__old_properties is not None:
                display_item.restore_properties(self.__old_properties)

    def _redo(self) -> None:
        self.perform()


class ChangeDisplayDataChannelCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel, display_data_channel: DisplayItem.DisplayDataChannel, *, title: typing.Optional[str] = None, command_id: typing.Optional[str] = None, is_mergeable: bool=False, **kwargs: typing.Any) -> None:
        super().__init__(title if title else _("Change Display"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__display_data_channel_proxy = display_data_channel.create_proxy()
        self.__properties = display_data_channel.save_properties()
        self.__value_dict = kwargs
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__display_data_channel_proxy.close()
        self.__display_data_channel_proxy = typing.cast(typing.Any, None)
        self.__properties = typing.cast(typing.Any, None)
        super().close()

    def perform(self) -> None:
        display_data_channel = self.__display_data_channel_proxy.item
        if display_data_channel:
            for key, value in self.__value_dict.items():
                setattr(display_data_channel, key, value)

    def _get_modified_state(self) -> typing.Any:
        display_data_channel = self.__display_data_channel_proxy.item
        display_data_channel_modified_state = display_data_channel.modified_state if display_data_channel else None
        return display_data_channel_modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        display_data_channel = self.__display_data_channel_proxy.item
        if display_data_channel:
            display_data_channel.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        display_data_channel = self.__display_data_channel_proxy.item
        if display_data_channel:
            properties = self.__properties
            self.__properties = display_data_channel.save_properties()
            display_data_channel.restore_properties(properties)

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeDisplayDataChannelCommand) and bool(self.command_id) and self.command_id == command.command_id and self.__display_data_channel_proxy.item == command.__display_data_channel_proxy.item


class AppendDisplayDataChannelUndo(Changes.UndeleteBase):
    def __init__(self, display_item: DisplayItem.DisplayItem, display_data_channel: DisplayItem.DisplayDataChannel) -> None:
        self.display_item_proxy = display_item.create_proxy()
        self.index = display_item.display_data_channels.index(display_data_channel)

    def close(self) -> None:
        self.display_item_proxy.close()

    def undelete(self, document_model: DocumentModel.DocumentModel) -> None:
        display_item = self.display_item_proxy.item
        # use the version of remove that does not cascade
        assert display_item
        display_item.remove_item("display_data_channels", display_item.display_data_channels[self.index])


class AppendDisplayLayerUndo(Changes.UndeleteBase):
    def __init__(self, display_item: DisplayItem.DisplayItem, display_layer: DisplayItem.DisplayLayer) -> None:
        self.display_item_proxy = display_item.create_proxy()
        self.index = display_item.display_layers.index(display_layer)

    def close(self) -> None:
        self.display_item_proxy.close()

    def undelete(self, document_model: DocumentModel.DocumentModel) -> None:
        display_item = self.display_item_proxy.item
        # use the version of remove that does not cascade
        assert display_item
        display_item.remove_item("display_layers", typing.cast(Persistence.PersistentObject, display_item.display_layers[self.index]))


class SetDisplayPropertyUndo(Changes.UndeleteBase):
    def __init__(self, display_item: DisplayItem.DisplayItem, name: str) -> None:
        self.display_item_proxy = display_item.create_proxy()
        self.name = name
        self.value = display_item.get_display_property(name)

    def close(self) -> None:
        self.display_item_proxy.close()

    def undelete(self, document_model: DocumentModel.DocumentModel) -> None:
        display_item = self.display_item_proxy.item
        assert display_item
        display_item.set_display_property(self.name, self.value)


class MoveDisplayLayerCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel,
                 old_display_item: DisplayItem.DisplayItem, old_display_layer_index: int,
                 new_display_item: DisplayItem.DisplayItem, new_display_layer_index: int,
                 *, title: typing.Optional[str] = None, command_id: typing.Optional[str] = None, is_mergeable: bool=False, **kwargs: typing.Any) -> None:
        super().__init__(title if title else _("Move Display Layer"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__old_legend_position = old_display_item.get_display_property("legend_position")
        self.__old_display_item_proxy = old_display_item.create_proxy()
        self.__old_display_layer_index = old_display_layer_index
        self.__new_legend_position = new_display_item.get_display_property("legend_position")
        self.__new_display_item_proxy = new_display_item.create_proxy()
        self.__new_display_layer_index = new_display_layer_index
        self.__undelete_logs: typing.List[Changes.UndeleteLog] = list()
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__old_display_item_proxy.close()
        self.__old_display_item_proxy = typing.cast(typing.Any, None)
        self.__new_display_item_proxy.close()
        self.__new_display_item_proxy = typing.cast(typing.Any, None)
        for undelete_log in self.__undelete_logs:
            undelete_log.close()
        self.__undelete_logs = typing.cast(typing.Any, None)
        super().close()

    def perform(self) -> None:
        # add display data channel and display layer to new display item
        # handle the following cases:
        #   different display item with associated display data channel used only by source display layer
        #   different display item with associated display data channel used by source display layer and others
        #   same display item with associated display data channel used only by source display layer
        #   same display item with associated display data channel used by source display layer and others

        # first get info about the old display layer
        old_display_item = self.__old_display_item_proxy.item
        assert old_display_item
        old_display_layer_index = self.__old_display_layer_index
        old_display_layer_properties = old_display_item.get_display_layer_properties(self.__old_display_layer_index)
        old_display_data_channel_index = old_display_item.display_data_channels.index(old_display_item.get_display_layer_display_data_channel(old_display_layer_index))
        # next get info about the new display layer
        new_display_item = self.__new_display_item_proxy.item
        assert new_display_item
        new_display_layer_index = self.__new_display_layer_index
        # save undo info about legend
        undelete_log = Changes.UndeleteLog()
        undelete_log.append(SetDisplayPropertyUndo(new_display_item, "legend_position"))
        undelete_log.append(SetDisplayPropertyUndo(old_display_item, "legend_position"))
        self.__undelete_logs.append(undelete_log)
        # create a copy of the old display data channel and add it
        old_display_data_channel = old_display_item.display_data_channels[old_display_data_channel_index]
        if old_display_item != new_display_item:
            new_display_data_channel = copy.deepcopy(old_display_data_channel)
            new_display_item.append_display_data_channel(new_display_data_channel)
            undelete_log = Changes.UndeleteLog()
            undelete_log.append(AppendDisplayDataChannelUndo(new_display_item, new_display_data_channel))
            self.__undelete_logs.append(undelete_log)
        else:
            new_display_data_channel = old_display_data_channel
        # adjust indexes if inserting into the same display item
        if old_display_item == new_display_item and new_display_layer_index > old_display_layer_index:
            new_display_layer_index += 1
        # add a new display layer with the old properties
        new_display_item.insert_display_layer_for_display_data_channel(new_display_layer_index, new_display_data_channel, **old_display_layer_properties)
        undelete_log = Changes.UndeleteLog()
        undelete_log.append(AppendDisplayLayerUndo(new_display_item, new_display_item.display_layers[new_display_layer_index]))
        self.__undelete_logs.append(undelete_log)
        # adjust indexes if inserting into the same display item
        if old_display_item == new_display_item and new_display_layer_index <= old_display_layer_index:
            old_display_layer_index += 1
        # remove the old display layer
        self.__undelete_logs.append(old_display_item.remove_display_layer(old_display_layer_index))
        # old display data channels will be removed when the last referencing display layer is removed by cascade.
        # if new_display_data_channel != old_display_data_channel and old_display_item.get_display_data_channel_layer_use_count(old_display_data_channel) == 0:
        #     self.__undelete_logs.append(old_display_item.remove_display_data_channel(old_display_data_channel))
        # update the legend
        new_display_item.auto_display_legend()
        old_display_item.auto_display_legend()

    def _get_modified_state(self) -> typing.Any:
        old_display_item = self.__old_display_item_proxy.item
        new_display_item = self.__new_display_item_proxy.item
        old_display_item_modified_state = old_display_item.modified_state if old_display_item else None
        new_display_item_modified_state = new_display_item.modified_state if new_display_item else None
        return old_display_item_modified_state, new_display_item_modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        old_display_item = self.__old_display_item_proxy.item
        new_display_item = self.__new_display_item_proxy.item
        if old_display_item:
            old_display_item.modified_state = modified_state[0]
        if new_display_item:
            new_display_item.modified_state = modified_state[1]
        self.__document_model.modified_state = modified_state[2]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0]) and bool(state1[1] == state2[1])

    def _undo(self) -> None:
        for undelete_log in reversed(self.__undelete_logs):
            self.__document_model.undelete_all(undelete_log)
            undelete_log.close()
        self.__undelete_logs.clear()

    def _redo(self) -> None:
        self.perform()


class AddDisplayLayerCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem, index: int,
                 *, title: typing.Optional[str] = None, command_id: typing.Optional[str] = None, is_mergeable: bool=False, **kwargs: typing.Any) -> None:
        super().__init__(title if title else _("Add Display Layer"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__old_properties = display_item.save_properties()
        self.__display_item_proxy = display_item.create_proxy()
        self.__index = index
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__old_properties = typing.cast(typing.Any, None)
        self.__display_item_proxy.close()
        self.__display_item_proxy = typing.cast(typing.Any, None)
        super().close()

    def perform(self) -> None:
        # add display data channel and display layer to new display item
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.insert_display_layer_for_display_data_channel(self.__index, display_item.display_data_channels[0])
            display_item.auto_display_legend()

    def _get_modified_state(self) -> typing.Any:
        display_item = self.__display_item_proxy.item
        display_item_modified_state = display_item.modified_state if display_item else None
        return display_item_modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _undo(self) -> None:
        # remove the new display layer and restore properties
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.remove_display_layer(self.__index).close()
            display_item.restore_properties(self.__old_properties)

    def _redo(self) -> None:
        self.perform()


class RemoveDisplayLayerCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem, index: int,
                 *, title: typing.Optional[str] = None, command_id: typing.Optional[str] = None, is_mergeable: bool=False, **kwargs: typing.Any) -> None:
        super().__init__(title if title else _("Remove Display Layer"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__old_properties = display_item.save_properties()
        self.__display_item_proxy = display_item.create_proxy()
        self.__index = index
        self.__undelete_logs: typing.List[Changes.UndeleteLog] = list()
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__old_properties = typing.cast(typing.Any, None)
        self.__display_item_proxy.close()
        self.__display_item_proxy = typing.cast(typing.Any, None)
        for undelete_log in self.__undelete_logs:
            undelete_log.close()
        self.__undelete_logs = typing.cast(typing.Any, None)
        super().close()

    def perform(self) -> None:
        # add display data channel and display layer to new display item
        display_item = self.__display_item_proxy.item
        if display_item:
            self.__undelete_logs.append(display_item.remove_display_layer(self.__index))
            display_item.auto_display_legend()

    def _get_modified_state(self) -> typing.Any:
        display_item = self.__display_item_proxy.item
        display_item_modified_state = display_item.modified_state if display_item else None
        return display_item_modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _undo(self) -> None:
        # remove the new display layer and restore properties
        display_item = self.__display_item_proxy.item
        if display_item:
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            display_item.restore_properties(self.__old_properties)

    def _redo(self) -> None:
        self.perform()


class ChangeDisplayCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem, *, title: typing.Optional[str] = None, command_id: typing.Optional[str] = None, is_mergeable: bool=False, **kwargs: typing.Any) -> None:
        super().__init__(title if title else _("Change Display"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__properties = display_item.save_properties()
        self.__value_dict = kwargs
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__display_item_proxy.close()
        self.__display_item_proxy = typing.cast(typing.Any, None)
        self.__properties = typing.cast(typing.Any, None)
        super().close()

    def perform(self) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            for key, value in self.__value_dict.items():
                display_item.set_display_property(key, value)

    def _get_modified_state(self) -> typing.Any:
        display_item = self.__display_item_proxy.item
        display_item_modified_state = display_item.modified_state if display_item else None
        return display_item_modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            properties = self.__properties
            self.__properties = display_item.save_properties()
            display_item.restore_properties(properties)

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeDisplayCommand) and bool(self.command_id) and self.command_id == command.command_id and self.__display_item_proxy.item == command.__display_item_proxy.item


class ChangeGraphicsCommand(Undo.UndoableCommand):

    def __init__(self, document_model: DocumentModel.DocumentModel, display_item: DisplayItem.DisplayItem, graphics: typing.Sequence[Graphics.Graphic], *, title: typing.Optional[str] = None, command_id: typing.Optional[str] = None, is_mergeable: bool=False, modify_fn: typing.Optional[typing.Callable[[Graphics.Graphic], None]] = None, **kwargs: typing.Any) -> None:
        super().__init__(title if title else _("Change Graphics"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__graphic_indexes = [display_item.graphics.index(graphic) for graphic in graphics]
        self.__graphic_properties = [graphic.write_to_dict() for graphic in graphics]
        self.__modify_fn = modify_fn
        self.__value_dict = kwargs
        self.initialize()

    def close(self) -> None:
        self.__document_model = typing.cast(typing.Any, None)
        self.__graphic_properties = typing.cast(typing.Any, None)
        self.__display_item_proxy.close()
        self.__display_item_proxy = typing.cast(typing.Any, None)
        self.__graphic_indexes = typing.cast(typing.Any, None)
        super().close()

    def perform(self) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            graphics = [display_item.graphics[index] for index in self.__graphic_indexes]
            for graphic in graphics:
                for key, value in self.__value_dict.items():
                    setattr(graphic, key, value)
                if callable(self.__modify_fn):
                    self.__modify_fn(graphic)

    def _get_modified_state(self) -> typing.Any:
        display_item = self.__display_item_proxy.item
        display_item_modified_state = display_item.modified_state if display_item else None
        return display_item_modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state: typing.Any) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            display_item.modified_state = modified_state[0]
        self.__document_model.modified_state = modified_state[1]

    def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return bool(state1[0] == state2[0])

    def _undo(self) -> None:
        display_item = self.__display_item_proxy.item
        if display_item:
            properties = self.__graphic_properties
            graphics = [display_item.graphics[index] for index in self.__graphic_indexes]
            self.__graphic_properties = [graphic.write_to_dict() for graphic in graphics]
            for graphic, graphic_properties in zip(graphics, properties):
                # NOTE: use read_properties_from_dict (read properties only), not read_from_dict (used for initialization).
                graphic.read_properties_from_dict(graphic_properties)

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeGraphicsCommand) and bool(self.command_id) and self.command_id == command.command_id and self.__display_item_proxy.item == command.__display_item_proxy.item and self.__graphic_indexes == command.__graphic_indexes


class DisplayPanelUISettings(UISettings.UISettings):
    def __init__(self, ui: UserInterface.UserInterface) -> None:
        self.__ui = ui

    def get_font_metrics(self, font: str, text: str) -> UISettings.FontMetrics:
        return typing.cast(UISettings.FontMetrics, self.__ui.get_font_metrics(font, text))

    @property
    def cursor_tolerance(self) -> float:
        return self.__ui.get_tolerance(UserInterface.ToleranceType.CURSOR)


class FixedUISettings(UISettings.UISettings):
    def __init__(self) -> None:
        pass

    def get_font_metrics(self, font: str, text: str) -> UISettings.FontMetrics:
        return UISettings.FontMetrics(width=round(6.5 * len(text)), height=15, ascent=12, descent=3, leading=0)

    @property
    def cursor_tolerance(self) -> float:
        return 5


class PlaybackController:
    def __init__(self, event_loop: asyncio.AbstractEventLoop) -> None:
        self.__event_loop = event_loop
        self.__display_data_channel: typing.Optional[DisplayItem.DisplayDataChannel] = None
        self.__task: typing.Optional[asyncio.Task[None]] = None
        self.is_movie_playing = Model.PropertyModel(False)
        self.index_adapter: typing.Optional[SequenceIndexAdapter] = None

    def handle_play_button(self) -> None:
        self.is_movie_playing.value = not self.is_movie_playing.value
        if self.is_movie_playing.value and self.__display_data_channel:
            assert not self.__task
            self.__task = self.__event_loop.create_task(self.__start_playing())
        else:
            self.__stop_playing()

    async def __start_playing(self) -> None:
        display_data_channel = self.__display_data_channel
        assert display_data_channel
        # do not write the project just for the sequence_index changing.
        # use a ghost property for this.
        display_data_channel.ghost_properties.update(["sequence_index"])
        assert self.index_adapter
        try:
            data_metadata = display_data_channel._get_data_metadata()
            if data_metadata and data_metadata.dimensional_shape is not None:
                max_index = data_metadata.max_sequence_index
                if display_data_channel.sequence_index + 1 >= max_index:
                    self.index_adapter.set_index_int_value(display_data_channel, 0)
                while display_data_channel.sequence_index + 1 < max_index:
                    await asyncio.sleep(0.05)
                    self.index_adapter.set_index_int_value(display_data_channel, display_data_channel.sequence_index + 1)
        finally:
            display_data_channel.ghost_properties.subtract(["sequence_index"])
            self.__stop_playing()
            self.index_adapter.set_index_int_value(display_data_channel, display_data_channel.sequence_index, True)

    def __stop_playing(self) -> None:
        if self.__task:
            self.__task.cancel()
            self.__task = None
        self.is_movie_playing.value = False

    @property
    def display_data_channel(self) -> typing.Optional[DisplayItem.DisplayDataChannel]:
        return self.__display_data_channel

    @display_data_channel.setter
    def display_data_channel(self, value: typing.Optional[DisplayItem.DisplayDataChannel]) -> None:
        self.__stop_playing()
        self.__display_data_channel = value


class ChangeGraphicsInteractiveTask(DisplayCanvasItem.InteractiveTask):
    def __init__(self, display_panel: DisplayPanel) -> None:
        super().__init__()
        self.__display_panel = display_panel
        display_item = display_panel.display_item
        assert display_item
        self.__display_item = display_item
        self.__undo_command: typing.Optional[Undo.UndoableCommand] = self.__display_panel.create_change_graphics_command()
        self.__display_panel.begin_mouse_tracking()

    def _close(self) -> None:
        self.__display_panel.end_mouse_tracking(None)
        if self.__undo_command:
            self.__undo_command.close()
            self.__undo_command = None

    def _commit(self) -> None:
        undo_command = self.__undo_command
        self.__undo_command = None
        assert undo_command
        undo_command.perform()
        self.__display_panel.document_controller.push_undo_command(undo_command)


class ChangeDisplayPropertiesInteractiveTask(DisplayCanvasItem.InteractiveTask):
    def __init__(self, display_panel: DisplayPanel) -> None:
        super().__init__()
        self.__display_panel = display_panel
        display_item = display_panel.display_item
        assert display_item
        self.__display_item = display_item
        self.__display_properties = copy.copy(display_item.display_properties)
        self.__undo_command: typing.Optional[Undo.UndoableCommand] = self.__display_panel.create_change_display_command()
        self.__display_panel.begin_mouse_tracking()

    def _close(self) -> None:
        self.__display_panel.end_mouse_tracking(None)
        if self.__undo_command:
            self.__undo_command.close()
            self.__undo_command = None

    def _commit(self) -> None:
        keys = set(self.__display_properties.keys()).union(set(self.__display_item.display_properties.keys()))
        changed_properties = dict[str, typing.Any]()
        for key in keys:
            if self.__display_properties.get(key) != self.__display_item.display_properties.get(key):
                changed_properties[key] = self.__display_item.display_properties.get(key)
        self.__display_panel.update_display_properties(changed_properties)
        undo_command = self.__undo_command
        self.__undo_command = None
        assert undo_command
        undo_command.perform()
        self.__display_panel.document_controller.push_undo_command(undo_command)


class CreateGraphicInteractiveTask(DisplayCanvasItem.InteractiveTask):
    def __init__(self, display_panel: DisplayPanel, graphic_type: str, start_position: Geometry.FloatPoint) -> None:
        super().__init__()
        self.__display_panel = display_panel
        display_item = display_panel.display_item
        assert display_item
        self.__display_item = display_item
        self.__graphic_type = graphic_type
        self.__graphic_properties = dict[str, typing.Any]()
        self.__display_panel.begin_mouse_tracking()
        from nion.swift import DocumentController  # avoid circular reference. needs rethinking.
        graphic_factory = DocumentController.graphic_factory_table[graphic_type]
        graphic_properties = graphic_factory.get_graphic_properties_from_position(self.__display_item, start_position)
        graphic = graphic_factory.create_graphic_in_display_item(display_panel.document_controller, display_item, graphic_properties)
        self.__undo_command: typing.Optional[Undo.UndoableCommand] = display_panel.create_insert_graphics_command([graphic])
        self._graphic = graphic

    def _close(self) -> None:
        self.__display_panel.end_mouse_tracking(None)
        if self.__undo_command:
            self.__undo_command.close()
            self.__undo_command = None

    def _commit(self) -> None:
        undo_command = self.__undo_command
        self.__undo_command = None
        assert undo_command
        undo_command.perform()
        self.__display_panel.document_controller.push_undo_command(undo_command)


class DisplayPanel(CanvasItem.LayerCanvasItem):
    """A canvas item to display a library item. Allows library item to be changed."""

    def __init__(self, document_controller: DocumentController.DocumentController, d: Persistence.PersistentDictType,
                 new_uuid: typing.Optional[uuid.UUID] = None) -> None:
        super().__init__()
        self.is_root_opaque = True  # mark it as an opaque item at the top level for drawing efficiency.
        self.__weak_document_controller = typing.cast(_DocumentControllerWeakRefType, weakref.ref(document_controller))
        document_controller.register_display_panel(self)
        self.wants_mouse_events = True
        self.uuid = uuid.UUID(d.get("uuid", str(new_uuid if new_uuid else uuid.uuid4())))
        self.__identifier: str = d.get("identifier", "".join([random.choice(string.ascii_uppercase) for _ in range(2)])) or str()
        self.ui = document_controller.ui

        self.on_contents_changed: typing.Optional[typing.Callable[[], None]] = None  # useful for writing changes to disk quickly

        self.__playback_controller = PlaybackController(document_controller.event_loop)

        self.__content_canvas_item = DisplayPanelOverlayCanvasItem(typing.cast(typing.Callable[[str, str], UISettings.FontMetrics], self.ui.get_font_metrics))
        self.__content_canvas_item.wants_mouse_events = True  # only when display_canvas_item is None
        self.__content_canvas_item.focusable = True
        self.__content_canvas_item.on_focus_changed = self.set_focused
        self.__content_canvas_item.on_context_menu_event = self.__handle_context_menu_event

        self.__header_canvas_item = Panel.HeaderCanvasItem(DisplayPanelUISettings(document_controller.ui), display_close_control=True)

        def header_double_clicked(x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
            action_context = document_controller._get_action_context()
            action_context.display_panel = self
            document_controller.perform_action_in_context("window.open_title_edit", action_context)
            return True

        self.__header_canvas_item.on_double_clicked = header_double_clicked

        def handle_header_tool_tip() -> typing.Optional[str]:
            if display_item := self.display_item:
                return display_item.tool_tip_str
            return None

        self.__header_canvas_item.on_tool_tip = handle_header_tool_tip

        self.__footer_canvas_item = CanvasItem.CanvasItemComposition()
        self.__footer_canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        self.__footer_canvas_item.update_sizing(self.__footer_canvas_item.sizing.with_collapsible(True))

        self.layout = CanvasItem.CanvasItemColumnLayout()
        self.add_canvas_item(self.__header_canvas_item)
        self.add_canvas_item(self.__content_canvas_item)
        self.add_canvas_item(self.__footer_canvas_item)

        self.__display_panel_id: typing.Optional[str] = None

        workspace_controller = self.__document_controller.workspace_controller

        def drag_enter(mime_data: UserInterface.MimeData) -> str:
            display_canvas_item = self.display_canvas_item
            if display_canvas_item and hasattr(display_canvas_item, "get_drop_regions_map"):
                # give the display canvas item a chance to provide drop regions based on the display item being dropped
                display_item = None
                if mime_data.has_format(MimeTypes.DISPLAY_PANEL_MIME_TYPE):
                    display_item, d = MimeTypes.mime_data_get_panel(mime_data, self.document_controller.document_model)
                if not display_item:
                    display_item = MimeTypes.mime_data_get_display_item(mime_data, self.document_controller.document_model)
                if display_item:
                    self.__content_canvas_item.drop_regions_map = getattr(display_canvas_item, "get_drop_regions_map")(display_item)
            else:
                self.__content_canvas_item.drop_regions_map = dict()
            if workspace_controller:
                return workspace_controller.handle_drag_enter(self, mime_data)
            return "ignore"

        def drag_leave() -> str:
            if workspace_controller:
                return workspace_controller.handle_drag_leave(self)
            return "ignore"

        def drag_move(mime_data: UserInterface.MimeData, x: int, y: int) -> str:
            if workspace_controller:
                return workspace_controller.handle_drag_move(self, mime_data, x, y)
            return "ignore"

        def wants_drag_event(mime_data: UserInterface.MimeData) -> bool:
            if workspace_controller:
                return workspace_controller.should_handle_drag_for_mime_data(mime_data)
            return False

        def drop(mime_data: UserInterface.MimeData, region: str, x: int, y: int) -> str:
            if workspace_controller:
                return workspace_controller.handle_drop(self, mime_data, region, x, y)
            return "ignore"

        def adjust_secondary_focus(modifiers: UserInterface.KeyboardModifiers) -> None:
            if modifiers.only_shift:
                self.__document_controller.add_secondary_display_panel(self)
            elif modifiers.only_control:
                self.__document_controller.toggle_secondary_display_panel(self)

        # list to the content_canvas_item messages and pass them along to listeners of this class.
        self.__content_canvas_item.on_drag_enter = drag_enter
        self.__content_canvas_item.on_drag_leave = drag_leave
        self.__content_canvas_item.on_drag_move = drag_move
        self.__content_canvas_item.on_wants_drag_event = wants_drag_event
        self.__content_canvas_item.on_drop = drop
        self.__content_canvas_item.on_key_pressed = self._handle_key_pressed
        self.__content_canvas_item.on_key_released = self._handle_key_released
        self.__content_canvas_item.on_mouse_clicked_event = self.__handle_mouse_clicked
        self.__content_canvas_item.on_select_all = self.select_all
        self.__content_canvas_item.on_adjust_secondary_focus = adjust_secondary_focus

        def close() -> None:
            if workspace_controller and len(workspace_controller.display_panels) > 1:
                command = workspace_controller.remove_display_panel(self)
                document_controller.push_undo_command(command)

        self.__header_canvas_item.on_select_pressed = self._select
        self.__header_canvas_item.on_drag_pressed = self.__handle_begin_drag
        self.__header_canvas_item.on_close_clicked = close

        ui = document_controller.ui

        self.__display_item: typing.Optional[DisplayItem.DisplayItem] = None
        self.__display_tracker: typing.Optional[DisplayTracker] = None
        self.__data_item_reference_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.__data_item_reference_changed_task: typing.Optional[asyncio.Task[None]] = None

        # the display panel controller is an object which adds and controls additional UI on top of this display.
        self.__display_panel_controller: typing.Optional[DisplayPanelControllerLike] = None

        # used for the (optional) display canvas item
        self.__closing_lock = threading.RLock()

        self.__display_item_value_stream = Stream.ValueStream[DisplayItem.DisplayItem]().add_ref()

        self.__related_icons_canvas_item: typing.Optional[RelatedIconsCanvasItem] = None

        # the data item panel consists of the data item display canvas item and the related icons canvas item
        self.__display_composition_canvas_item = CanvasItem.CanvasItemComposition()

        self.__selection = document_controller.filtered_display_items_model.make_selection()
        self.__selection.expanded_changed_event = True
        self.__selection_changed_event_listener = self.__selection.changed_event.listen(self.__selection_changed)

        # display_items_changed() is fired when the list of display items changes. after firing
        # display_items and display_item will return the proper values.
        self.display_items_changed_event = Event.Event()
        # the cached __display_items value is used to determine whether the display items have
        # changed since the last time the display_items_changed_event was fired.
        self.__display_items: typing.List[DisplayItem.DisplayItem] = list()

        def data_list_drag_started(mime_data: UserInterface.MimeData, thumbnail_data: typing.Optional[_NDArray]) -> None:
            self.content_canvas_item.drag(mime_data, thumbnail_data)

        # this handles the case of a key press in a grid or list controller.
        def key_pressed(key: UserInterface.Key) -> bool:
            action = Window.get_action_for_key(["display_panel_browser"], key)
            if action:
                self.document_controller.perform_action(action)
                return True
            return False

        def map_display_item_to_display_item_adapter(display_item: DisplayItem.DisplayItem) -> DataPanel.DisplayItemAdapter:
            return DataPanel.DisplayItemAdapter(display_item, ui)

        def unmap_display_item_to_display_item_adapter(display_item_adapter: DataPanel.DisplayItemAdapter) -> None:
            display_item_adapter.close()

        self.__filtered_display_item_adapters_model = ListModel.MappedListModel(container=document_controller.filtered_display_items_model, master_items_key="display_items", items_key="display_item_adapters", map_fn=map_display_item_to_display_item_adapter, unmap_fn=unmap_display_item_to_display_item_adapter)

        def display_item_adapter_selection_changed(display_item_adapters: typing.Sequence[DataPanel.DisplayItemAdapter]) -> None:
            indexes = set()
            for index, display_item_adapter in enumerate(self.__filtered_display_item_adapters_model.display_item_adapters):
                if display_item_adapter in display_item_adapters:
                    indexes.add(index)
            self.__selection.set_multiple(indexes)

        def double_clicked(display_item_adapter: DataPanel.DisplayItemAdapter) -> bool:
            display_item_adapter_selection_changed([display_item_adapter])
            self.__cycle_display()
            return True

        def focus_changed(focused: bool) -> None:
            # this is called when one of the browser items (grid or thumbnail) changes focus.
            # if receiving focus, tell the window (document_controller) that this display panel
            # is now the selected display panel.
            if focused:
                self.__document_controller.selected_display_panel = self

        def delete_display_item_adapters(display_item_adapters: typing.Sequence[DataPanel.DisplayItemAdapter]) -> None:
            document_controller.delete_display_items([display_item_adapter.display_item for display_item_adapter in display_item_adapters])

        self.__horizontal_data_grid_controller = DataPanel.DataGridController(document_controller.event_loop, document_controller.ui, self.__filtered_display_item_adapters_model, self.__selection, direction=GridCanvasItem.Direction.Row, wrap=False)
        self.__horizontal_data_grid_controller.on_context_menu_event = self.__handle_context_menu_for_display
        self.__horizontal_data_grid_controller.on_display_item_adapter_double_clicked = double_clicked
        self.__horizontal_data_grid_controller.on_focus_changed = focus_changed
        self.__horizontal_data_grid_controller.on_delete_display_item_adapters = delete_display_item_adapters
        self.__horizontal_data_grid_controller.on_drag_started = data_list_drag_started
        self.__horizontal_data_grid_controller.on_key_pressed = key_pressed

        self.__grid_data_grid_controller = DataPanel.DataGridController(document_controller.event_loop, document_controller.ui, self.__filtered_display_item_adapters_model, self.__selection)
        self.__grid_data_grid_controller.on_context_menu_event = self.__handle_context_menu_for_display
        self.__grid_data_grid_controller.on_display_item_adapter_double_clicked = double_clicked
        self.__grid_data_grid_controller.on_focus_changed = focus_changed
        self.__grid_data_grid_controller.on_delete_display_item_adapters = delete_display_item_adapters
        self.__grid_data_grid_controller.on_drag_started = data_list_drag_started
        self.__grid_data_grid_controller.on_key_pressed = key_pressed

        self.__horizontal_browser_canvas_item = self.__horizontal_data_grid_controller.canvas_item
        self.__horizontal_browser_canvas_item.update_sizing(self.__horizontal_browser_canvas_item.sizing.with_fixed_height(80))
        self.__horizontal_browser_canvas_item.visible = False

        self.__grid_browser_canvas_item = self.__grid_data_grid_controller.canvas_item
        self.__grid_browser_canvas_item.visible = False

        # the column composition layout permits displaying data item and horizontal browser simultaneously and also the
        # data item and grid as the only items just by selecting hiding/showing individual canvas items.
        self.__browser_composition_canvas_item = CanvasItem.CanvasItemComposition()
        self.__browser_composition_canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        self.__browser_composition_canvas_item.add_canvas_item(self.__display_composition_canvas_item)
        self.__browser_composition_canvas_item.add_canvas_item(self.__horizontal_browser_canvas_item)
        self.__browser_composition_canvas_item.add_canvas_item(self.__grid_browser_canvas_item)

        self.__content_canvas_item.add_canvas_item(self.__browser_composition_canvas_item)

        self.__display_changed = False  # put this at end of init to avoid transient initialization states

        self.__change_display_panel_content(d)

        self.__mapped_item_listener = DocumentModel.MappedItemManager().changed_event.listen(self.__update_title)

        self.__cursor_task: typing.Optional[asyncio.Task[None]] = None


    def close(self) -> None:
        if self.__cursor_task:
            self.__cursor_task.cancel()
            self.__cursor_task = None

        self.on_contents_changed = None

        self.__mapped_item_listener.close()
        self.__mapped_item_listener = typing.cast(typing.Any, None)

        if self.__data_item_reference_changed_task:
            self.__data_item_reference_changed_task.cancel()
            self.__data_item_reference_changed_task = None
        if self.__data_item_reference_changed_event_listener:
            self.__data_item_reference_changed_event_listener.close()
            self.__data_item_reference_changed_event_listener = None

        self.__display_item_value_stream.remove_ref()
        self.__display_item_value_stream = typing.cast(typing.Any, None)

        with self.__closing_lock:  # ensures that display pipeline finishes
            self.set_display_item(None)  # required before destructing display thread

        # NOTE: the enclosing canvas item should be closed AFTER this close is called.
        self.__set_display_panel_controller(None)
        self.__horizontal_data_grid_controller.close()
        self.__horizontal_data_grid_controller = typing.cast(typing.Any, None)
        self.__grid_data_grid_controller.close()
        self.__grid_data_grid_controller = typing.cast(typing.Any, None)
        self.__selection_changed_event_listener.close()
        self.__selection_changed_event_listener = typing.cast(typing.Any, None)
        self.__document_controller.filtered_display_items_model.release_selection(self.__selection)
        self.__filtered_display_item_adapters_model.close()
        self.__filtered_display_item_adapters_model = typing.cast(typing.Any, None)

        # define the selection used in the thumbnail and grid browsers.
        self.__selection = Selection.IndexedSelection()

        self.__content_canvas_item.on_focus_changed = None  # only necessary during tests

        # release references
        self.__content_canvas_item = typing.cast(typing.Any, None)
        self.__header_canvas_item = typing.cast(typing.Any, None)

        self.__document_controller.unregister_display_panel(self)
        self.__weak_document_controller = typing.cast(typing.Any, None)
        super().close()

    @property
    def __document_controller(self) -> DocumentController.DocumentController:
        return self.__weak_document_controller()

    @property
    def document_controller(self) -> DocumentController.DocumentController:
        return self.__weak_document_controller()

    @property
    def _display_panel_controller_for_test(self) -> typing.Optional[DisplayPanelControllerLike]:
        return self.__display_panel_controller

    @property
    def display_panel_controller(self) -> typing.Optional[DisplayPanelControllerLike]:
        return self.__display_panel_controller

    @property
    def _display_item_adapters_for_test(self) -> typing.Sequence[DataPanel.DisplayItemAdapter]:
        return typing.cast(typing.Sequence[DataPanel.DisplayItemAdapter], self.__filtered_display_item_adapters_model.display_item_adapters)

    @property
    def _selection_for_test(self) -> Selection.IndexedSelection:
        return self.__selection

    @property
    def _related_icons_canvas_item(self) -> typing.Optional[RelatedIconsCanvasItem]:
        return self.__related_icons_canvas_item

    @property
    def header_canvas_item(self) -> Panel.HeaderCanvasItem:
        return self.__header_canvas_item

    @property
    def content_canvas_item(self) -> DisplayPanelOverlayCanvasItem:
        return self.__content_canvas_item

    @property
    def footer_canvas_item(self) -> CanvasItem.CanvasItemComposition:
        return self.__footer_canvas_item

    @property
    def identifier(self) -> str:
        return self.__identifier

    @property
    def display_canvas_item(self) -> typing.Optional[DisplayCanvasItem.DisplayCanvasItem]:
        return self.__display_tracker.display_canvas_item if self.__display_tracker else None

    @property
    def display_panel_type(self) -> str:
        return self._display_panel_type

    @property
    def display_panel_id(self) -> typing.Optional[str]:
        return self.__display_panel_id

    @property
    def data_item(self) -> typing.Optional[DataItem.DataItem]:
        return self.__display_item.data_item if self.__display_item else None

    @property
    def display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        """Return the display item selected in the display panel, if any."""
        return self.__display_item

    @property
    def display_items(self) -> typing.Sequence[DisplayItem.DisplayItem]:
        """Return the display items selected in the display panel."""
        return self.__display_items

    def __update_display_items(self, old_display_items: typing.Sequence[DisplayItem.DisplayItem]) -> None:
        # update the cached display items and fire the display_items_changed event if anything changes.
        # the display items may be a single display item that might not be in the filtered display items.
        # otherwise it is the selected items from the filtered display items.
        display_items = list()
        if self.__display_item:
            display_items.append(self.__display_item)
        else:
            filtered_display_items = self.__document_controller.filtered_display_items_model.display_items
            for index in self.__selection.ordered_indexes:
                display_items.append(filtered_display_items[index])
        self.__display_items = display_items
        if self.__display_items != old_display_items:
            self.display_items_changed_event.fire()

    def save_contents(self) -> Persistence.PersistentDictType:
        d: Persistence.PersistentDictType = dict()
        if self.display_panel_id:
            d["display_panel_id"] = str(self.display_panel_id)
        if self.__display_panel_controller:
            d["controller_type"] = self.__display_panel_controller.type
            self.__display_panel_controller.save(d)
        if self.__display_item:
            d["display_item_specifier"] = Persistence.write_persistent_specifier(self.__display_item.uuid)
        if self.__display_panel_controller is None and self.__horizontal_browser_canvas_item.visible:
            d["browser_type"] = "horizontal"
        if self.__display_panel_controller is None and self.__grid_browser_canvas_item.visible:
            d["browser_type"] = "grid"
        d["uuid"] = str(self.uuid)
        d["identifier"] = self.identifier
        return d

    def restore_contents(self, d: Persistence.PersistentDictType) -> None:
        try:
            display_panel_id = d.get("display_panel_id")
            if display_panel_id:
                self.__display_panel_id = display_panel_id
            self.__identifier = d.get("identifier", self.__identifier)
            controller_type = typing.cast(str, d.get("controller_type"))
            self.__set_display_panel_controller(DisplayPanelManager().make_display_panel_controller(controller_type, self, d))
            if not self.__display_panel_controller:
                display_item: typing.Optional[DisplayItem.DisplayItem] = None
                if "display_item_specifier" in d:
                    display_item_specifier = Persistence.read_persistent_specifier(d["display_item_specifier"])
                    display_item = typing.cast(typing.Optional[DisplayItem.DisplayItem], self.document_controller.document_model.resolve_item_specifier(display_item_specifier)) if display_item_specifier else None
                self.set_display_item(display_item)
                if d.get("browser_type") == "horizontal":
                    self.__switch_to_horizontal_browser()
                elif d.get("browser_type") == "grid":
                    self.__switch_to_grid_browser()
                else:
                    self.__switch_to_no_browser()
        except Exception as e:
            # catch and print any exceptions, but kill the exception so layout stays intact
            global _test_log_exceptions
            if _test_log_exceptions:
                import traceback
                traceback.print_exc()

    @property
    def _is_result_panel(self) -> bool:
        return not self.__display_item and not self.__grid_browser_canvas_item.visible and not self.__display_panel_controller

    @property
    def _display_panel_type(self) -> str:
        if self.__horizontal_browser_canvas_item.visible:
            return "horizontal"
        elif self.__grid_browser_canvas_item.visible:
            return "grid"
        elif self.__display_item:
            return "data_item"
        else:
            return "empty"

    def handle_drop_display_item(self, region: str, display_item: typing.Optional[DisplayItem.DisplayItem]) -> bool:
        if region == "plus":
            target_display_item = self.display_item
            if target_display_item and display_item:
                new_display_item = self.__document_controller.add_display_data_channel_to_or_create_composite(target_display_item, display_item, self)
                if new_display_item:
                    return True
        return False

    def _drag_finished(self, document_controller: DocumentController.DocumentController, action: str) -> None:
        document_controller.display_panel_finish_drag(self, action)

    def display_clicked(self, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if self._is_selected() and not (modifiers.shift or modifiers.control):
            self.document_controller.clear_secondary_display_panels()
            return True
        return False

    def image_clicked(self, image_position: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if self.__display_item:
            if DisplayPanelManager().image_display_clicked(self, self.__display_item, image_position, modifiers):
                return True
        if self._is_selected() and not (modifiers.shift or modifiers.control):
            self.document_controller.clear_secondary_display_panels()
            return True
        return False

    def image_mouse_pressed(self, image_position: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if self.__display_item:
            return DisplayPanelManager().image_display_mouse_pressed(self, self.__display_item, image_position, modifiers)
        return False

    def image_mouse_released(self, image_position: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if self.__display_item:
            return DisplayPanelManager().image_display_mouse_released(self, self.__display_item, image_position, modifiers)
        return False

    def image_mouse_position_changed(self, image_position: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if self.__display_item:
            return DisplayPanelManager().image_display_mouse_position_changed(self, self.__display_item, image_position, modifiers)
        return False

    def image_panel_get_font_metrics(self, font: str, text: str) -> UserInterface.FontMetrics:
        return self.ui.get_font_metrics(font, text)

    def __set_display_panel_controller(self, display_panel_controller: typing.Optional[DisplayPanelControllerLike]) -> None:
        if self.__display_panel_controller:
            self.__display_panel_controller.close()
            self.__display_panel_controller = None
        self.__display_panel_controller = display_panel_controller
        if not display_panel_controller:
            self.header_canvas_item.reset_header_colors()
        if self.__display_panel_controller:
            self.__switch_to_no_browser()
            self.set_display_item(self.__display_item)

    # sets the data item that this panel displays
    # not thread safe
    def set_displayed_data_item(self, data_item: DataItem.DataItem) -> None:
        display_item = self.document_controller.document_model.get_any_display_item_for_data_item(data_item)
        self.set_display_item(display_item)

    def set_data_item_reference(self, data_item_reference: DocumentModel.DocumentModel.DataItemReference) -> None:
        if self.__data_item_reference_changed_event_listener:
            self.__data_item_reference_changed_event_listener.close()
            self.__data_item_reference_changed_event_listener = None

        def handle_data_item_reference_changed() -> None:
            if self.__data_item_reference_changed_task:
                self.__data_item_reference_changed_task.cancel()
                self.__data_item_reference_changed_task = None

            async def update_display_item() -> None:
                with Process.audit("update_display_item"):
                    self.set_display_item(self.document_controller.document_model.get_any_display_item_for_data_item(data_item_reference.data_item))

            self.__data_item_reference_changed_task = self.document_controller.event_loop.create_task(update_display_item())

        if data_item_reference:
            self.__data_item_reference_changed_event_listener = data_item_reference.data_item_reference_changed_event.listen(handle_data_item_reference_changed)
            self.set_display_item(self.document_controller.document_model.get_any_display_item_for_data_item(data_item_reference.data_item))

    def set_display_panel_data_item(self, data_item: DataItem.DataItem, detect_controller: bool=False) -> None:
        display_item = self.document_controller.document_model.get_any_display_item_for_data_item(data_item)
        if display_item:
            self.set_display_panel_display_item(display_item, detect_controller)

    def set_display_panel_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem], detect_controller: bool=False) -> None:
        if display_item:
            d = {"type": "image", "display_item_specifier": Persistence.write_persistent_specifier(display_item.uuid)}
            if detect_controller:
                data_item = display_item.data_item
                if display_item == self.document_controller.document_model.get_any_display_item_for_data_item(data_item) and data_item:
                    d2 = DisplayPanelManager().detect_controller(self.__document_controller.document_model, data_item)
                    if d2:
                        d.update(d2)
        else:
            d = {"type": "image"}
        self.change_display_panel_content(d)

    def change_display_panel_content(self, d: Persistence.PersistentDictType) -> None:
        self.__change_display_panel_content(d)

    def __change_display_panel_content(self, d: Persistence.PersistentDictType) -> None:
        is_selected = self._is_selected()
        is_focused = self._is_focused()

        display_panel_type = d.get("display-panel-type", "data-display-panel")
        if display_panel_type == "thumbnail-browser-display-panel":
            d["browser_type"] = "horizontal"
        elif display_panel_type == "browser-display-panel":
            d["browser_type"] = "grid"
        elif display_panel_type == "empty-display-panel":
            d["browser_type"] = "empty"

        self.restore_contents(d)

        self.set_selected(is_selected)

        if is_focused:
            self.request_focus()

        if callable(self.on_contents_changed):
            self.on_contents_changed()

    def set_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem], *, update_selection: bool = True) -> None:
        # sets the display item that this panel displays. this item does not have to be in the filtered display items.
        # the update_selection parameter can be set to false if this is being called in response to the selection of
        # filtered display items changing. otherwise, the selection is set to correspond to the display_item if it
        # exists in the filtered display items.
        # update the canvas item and handle title changes too.
        # this method is not thread safe.

        old_display_items = copy.copy(self.__display_items)

        did_display_change = self.__display_item != display_item

        if did_display_change:

            # remove any existing display canvas item
            if len(self.__display_composition_canvas_item.canvas_items) > 0:
                self.__display_composition_canvas_item.remove_canvas_item(self.__display_composition_canvas_item.canvas_items[0])

            old_display_tracker = self.__display_tracker
            self.__display_tracker = None

            if display_item:
                def clear_display() -> None:
                    self.set_display_panel_display_item(None, True)

                def handle_title_changed(title: str) -> None:
                    self.__update_title()

                def add_display_controls(display_canvas_item: DisplayCanvasItem.DisplayCanvasItem) -> None:
                    related_icons_canvas_item = RelatedIconsCanvasItem(self.ui, self.get_document_model(),
                                                                       self.__display_item_value_stream,
                                                                       self.document_controller.drag)
                    sequence_slider_row = IndexValueSliderCanvasItem(_("S"),
                                                                     self.__display_item_value_stream,
                                                                     SequenceIndexAdapter(self.document_controller),
                                                                     self.ui.get_font_metrics,
                                                                     self.__document_controller.event_loop,
                                                                     self.__playback_controller.handle_play_button,
                                                                     self.__playback_controller.is_movie_playing)
                    c0_slider_row = IndexValueSliderCanvasItem(_("C0"),
                                                               self.__display_item_value_stream,
                                                               CollectionIndexAdapter(self.document_controller, 0),
                                                               self.ui.get_font_metrics,
                                                               self.__document_controller.event_loop)
                    c1_slider_row = IndexValueSliderCanvasItem(_("C1"),
                                                               self.__display_item_value_stream,
                                                               CollectionIndexAdapter(self.document_controller, 1),
                                                               self.ui.get_font_metrics,
                                                               self.__document_controller.event_loop)
                    display_canvas_item.add_display_control(related_icons_canvas_item, "related_icons")
                    display_canvas_item.add_display_control(sequence_slider_row)
                    display_canvas_item.add_display_control(c0_slider_row)
                    display_canvas_item.add_display_control(c1_slider_row)
                    self.__related_icons_canvas_item = related_icons_canvas_item

                def replace_display_canvas_item(old_display_canvas_item: DisplayCanvasItem.DisplayCanvasItem, new_display_canvas_item: DisplayCanvasItem.DisplayCanvasItem) -> None:
                    self.__display_composition_canvas_item.replace_canvas_item(old_display_canvas_item, new_display_canvas_item)
                    add_display_controls(new_display_canvas_item)

                self.__display_tracker = DisplayTracker(display_item, DisplayPanelUISettings(self.ui), self, self.__document_controller.event_loop, True)
                self.__display_tracker.on_clear_display = clear_display
                self.__display_tracker.on_title_changed = handle_title_changed
                self.__display_tracker.on_replace_display_canvas_item = replace_display_canvas_item

                add_display_controls(self.__display_tracker.display_canvas_item)

                self.__display_composition_canvas_item.insert_canvas_item(0, self.__display_tracker.display_canvas_item)

            if old_display_tracker:
                old_display_tracker.close()

            self.__display_item = display_item

            self.__playback_controller.display_data_channel = self.display_item.display_data_channel if self.display_item else None
            self.__playback_controller.index_adapter = SequenceIndexAdapter(self.document_controller)

            if update_selection:
                self.__update_selection_to_display()

        # always update display items - this may be called when selection changes
        self.__update_display_items(old_display_items)

        # ensure the graphics get updated by triggering the graphics changed event.
        if self.__display_item:
            self.__display_item.graphics_changed_event.fire(self.__display_item.graphic_selection)

        # update the related icons canvas item with the new display if it changed.
        # setting the related icons canvas item is costly and can cause stuttering in operations
        # as simple as dragging a background selection in a background subtracted line plot as it
        # recalculates thumbnails on the main thread.
        if did_display_change and self.__display_item_value_stream:
            self.__display_item_value_stream.value = display_item

        self.__update_title()

    def _select(self) -> None:
        self.content_canvas_item.request_focus()

    def __update_title(self) -> None:
        if self.__display_item:
            displayed_title = self.__display_item.displayed_title
            if self.__display_item.is_live:
                live = _("Live")
                displayed_title = f"{displayed_title} ({live})"
            r_var = DocumentModel.MappedItemManager().get_item_r_var(self.__display_item)
            if r_var:
                displayed_title = f"{displayed_title} ({r_var})"
            self.header_canvas_item.title = displayed_title
        else:
            self.header_canvas_item.title = str()

    # handle selection. selection means that the display panel is the most recent
    # item to have focus within the workspace, although it can be selected without
    # having focus. this can happen, for instance, when the user switches focus
    # to the data panel.

    def set_selected(self, selected: bool) -> None:
        if self.__content_canvas_item:  # may be closed
            self.__content_canvas_item.selected = selected
            if selected:
                self.__content_canvas_item.focused_style = "#4682B4"  # steel blue
                self.__content_canvas_item.selection_number = None
                self.__content_canvas_item.line_dash = None

    def _is_selected(self) -> bool:
        """ Used for testing. """
        return self.__content_canvas_item.selected

    def set_secondary_index(self, secondary_index: typing.Optional[int]) -> None:
        if self.__content_canvas_item:  # may be closed
            if secondary_index is not None:
                self.__content_canvas_item.selected = True
                self.__content_canvas_item.selected_style = "#4682B4"  # steel blue
                self.__content_canvas_item.selection_number = secondary_index + 1
                self.__content_canvas_item.line_dash = 4
            else:
                self.__content_canvas_item.selection_number = None
                self.__content_canvas_item.line_dash = None

    # this message comes from the canvas items via the on_focus_changed when their focus changes
    # if the display panel is receiving focus, tell the window (document_controller) about it so
    # it can update the selected display items. also tell the display panel manager about it.
    def set_focused(self, focused: bool) -> None:
        self.__content_canvas_item.focused = focused
        if focused:
            self.__document_controller.selected_display_panel = self
        DisplayPanelManager().focus_changed(self, focused)

    def _is_focused(self) -> bool:
        """ Used for testing. """
        return self.__content_canvas_item.focused

    def request_focus(self) -> None:
        self.__content_canvas_item.request_focus()

    @property
    def is_result_panel(self) -> bool:
        return self._is_result_panel

    # this gets called when the user initiates a drag in the drag control to move the panel around
    def __handle_begin_drag(self) -> None:
        mime_data = self.ui.create_mime_data()
        if self.__display_item:
            MimeTypes.mime_data_put_display_item(mime_data, self.__display_item)
        MimeTypes.mime_data_put_panel(mime_data, None, self.save_contents())
        thumbnail_data = Thumbnails.ThumbnailManager().thumbnail_data_for_display_item(self.__display_item)
        thumbnail = Image.get_rgba_data_from_rgba(Image.scaled(Image.get_rgba_view_from_rgba_data(thumbnail_data), Geometry.IntSize(w=80, h=80).as_tuple())) if thumbnail_data is not None else None
        self.__begin_drag(mime_data, thumbnail)

    def __begin_drag(self, mime_data: UserInterface.MimeData, thumbnail_data: typing.Optional[_NDArray]) -> None:
        self.document_controller.replaced_display_panel_content_flag = True
        self.drag(mime_data, thumbnail_data, drag_finished_fn=functools.partial(self._drag_finished, self.__document_controller))

    def cycle_display(self) -> None:
        self.__cycle_display()

    def __cycle_display(self) -> None:
        # cycle display is only valid if there is no display panel controller.
        if self.__display_panel_controller is None:
            # the second part of the if statement below handles the case where the data item has been changed by
            # the user so the cycle should go back to the main display.
            if self.__display_composition_canvas_item.visible and (not self.__horizontal_browser_canvas_item.visible or not self.__display_changed):
                if self.__horizontal_browser_canvas_item.visible:
                    self.__switch_to_grid_browser()
                    self.__update_selection_to_display()
                    self.__grid_data_grid_controller.request_focus()
                else:
                    self.__switch_to_horizontal_browser()
                    self.__update_selection_to_display()
                    self.__horizontal_data_grid_controller.request_focus()
            else:
                self.__switch_to_no_browser()
                self._select()
            self.__display_changed = False

    def __update_selection_to_display(self) -> None:
        # match the selection in the browsers (thumbnail and grid) to the display item.
        # if the display item is not in the filtered display items, clear the selection.
        display_items = [display_item_adapter.display_item for display_item_adapter in self.__filtered_display_item_adapters_model.display_item_adapters if display_item_adapter.display_item is not None]
        # selection changed listener is only intended to observe external changes.
        # disable it here and re-enable it after we adjust the selection.
        self.__selection_changed_event_listener.close()
        self.__selection_changed_event_listener = typing.cast(typing.Any, None)
        if self.__display_item in display_items:
            self.__selection.set(display_items.index(self.__display_item))
            self.__horizontal_data_grid_controller.make_selection_visible()
            self.__grid_data_grid_controller.make_selection_visible()
        else:
            self.__selection.clear()
        self.__selection_changed_event_listener = self.__selection.changed_event.listen(self.__selection_changed)

    def __switch_to_no_browser(self) -> None:
        self.__display_composition_canvas_item.visible = True
        self.__horizontal_browser_canvas_item.visible = False
        self.__grid_browser_canvas_item.visible = False

    def __switch_to_horizontal_browser(self) -> None:
        self.__display_composition_canvas_item.visible = True
        self.__horizontal_browser_canvas_item.visible = True
        self.__grid_browser_canvas_item.visible = False

    def __switch_to_grid_browser(self) -> None:
        self.__display_composition_canvas_item.visible = False
        self.__horizontal_browser_canvas_item.visible = False
        self.__grid_browser_canvas_item.visible = True

    # from the canvas item directly. dispatches to the display canvas item. if the display canvas item
    # doesn't handle it, gives the display controller a chance to handle it.
    def _handle_key_pressed(self, key: UserInterface.Key) -> bool:
        display_canvas_item = self.display_canvas_item
        if display_canvas_item:
            # Alt+Shift+L and Alt+Shift+F are not currently expressible using key config.
            # Handle those two special cases here. This also serves to avoid key conflicts
            # with these debugging capabilities.
            action: typing.Optional[Window.Action]
            if key.key == 70 and key.modifiers.shift and key.modifiers.alt:
                action = Window.actions["display_panel.toggle_frame_rate"]
            elif key.key == 76 and key.modifiers.shift and key.modifiers.alt:
                action = Window.actions["display_panel.toggle_latency"]
            else:
                action = Window.get_action_for_key(["display_panel_browser"] + list(display_canvas_item.key_contexts), key)
            if action:
                self.document_controller.perform_action(action)
                return True
            if display_canvas_item.key_pressed(key):
                return True
        else:
            # handle case of empty display panel
            action = Window.get_action_for_key(["display_panel_browser"], key)
            if action:
                self.document_controller.perform_action(action)
                return True
        if self.__display_panel_controller and self.__display_panel_controller.key_pressed(key):
            return True
        return DisplayPanelManager().key_pressed(self, key)

    # from the canvas item directly. dispatches to the display canvas item. if the display canvas item
    # doesn't handle it, gives the display controller a chance to handle it.
    def _handle_key_released(self, key: UserInterface.Key) -> bool:
        display_canvas_item = self.display_canvas_item
        if display_canvas_item and display_canvas_item.key_released(key):
            return True
        if self.__display_panel_controller and self.__display_panel_controller.key_released(key):
            return True
        return DisplayPanelManager().key_released(self, key)

    def __handle_mouse_clicked(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        return self.display_clicked(modifiers)

    def __show_context_menu(self, display_items: typing.Sequence[DisplayItem.DisplayItem], gx: int, gy: int) -> bool:
        action_context = self.document_controller._get_action_context_for_display_items(display_items, self)
        menu = self.document_controller.create_context_menu()
        self.document_controller.populate_context_menu(menu, action_context)
        if self.__document_controller.is_action_enabled("display_panel.clear", action_context):
            menu.add_separator()
            self.__document_controller.add_action_to_menu(menu, "display_panel.clear", action_context)
        if self.__document_controller.is_action_enabled("display_panel.select_siblings", action_context):
            menu.add_separator()
            self.__document_controller.add_action_to_menu(menu, "display_panel.select_siblings", action_context)
        if action_context.display_panel:
            menu.add_separator()
            self.__document_controller.add_action_to_menu(menu, "workspace.split_vertical", action_context)
            self.__document_controller.add_action_to_menu(menu, "workspace.split_horizontal", action_context)
            menu.add_separator()
            split_menu = self.document_controller.create_sub_menu()
            menu.add_sub_menu(_("Display Panel Split"), split_menu)
            self.__document_controller.add_action_to_menu(split_menu, "workspace.split_2x2", action_context)
            self.__document_controller.add_action_to_menu(split_menu, "workspace.split_3x2", action_context)
            self.__document_controller.add_action_to_menu(split_menu, "workspace.split_3x3", action_context)
            self.__document_controller.add_action_to_menu(split_menu, "workspace.split_4x3", action_context)
            self.__document_controller.add_action_to_menu(split_menu, "workspace.split_4x4", action_context)
            self.__document_controller.add_action_to_menu(split_menu, "workspace.split_5x4", action_context)
        if self.__document_controller.is_action_enabled("display_panel.close", action_context):
            menu.add_separator()
            self.__document_controller.add_action_to_menu(menu, "display_panel.close", action_context)
        if self.__document_controller.is_action_enabled("item.delete", action_context):
            menu.add_separator()
            self.__document_controller.add_action_to_menu(menu, "item.delete", action_context)
        if action_context.display_panel:
            menu.add_separator()
            self.__document_controller.add_action_to_menu(menu, "display_panel.show_item", action_context)
            self.__document_controller.add_action_to_menu(menu, "display_panel.show_thumbnail_browser", action_context)
            self.__document_controller.add_action_to_menu(menu, "display_panel.show_grid_browser", action_context)
            menu.add_separator()
            DisplayPanelManager().build_menu(menu, self.__document_controller, self)
        menu.popup(gx, gy)
        return True

    def __handle_context_menu_event(self, x: int, y: int, gx: int, gy: int) -> bool:
        # this handles the context menu when display panel is empty
        return self.__show_context_menu([], gx, gy)

    def __handle_context_menu_for_display(self, display_item: typing.Optional[DisplayItem.DisplayItem], display_items: typing.List[DisplayItem.DisplayItem], x: int, y: int, gx: int, gy: int) -> bool:
        # this handles the context menu when requested from the thumbnail/grid browser
        return self.__show_context_menu(self.__document_controller.selected_display_items, gx, gy)

    def show_display_context_menu(self, gx: int, gy: int) -> bool:
        # this handles the context menu when requested from the display item
        return self.__show_context_menu([self.__display_item] if self.__display_item else [], gx, gy)

    def perform_action(self, fn: str, *args: typing.Any, **keywords: typing.Any) -> None:
        display_canvas_item = self.display_canvas_item
        target = display_canvas_item
        if hasattr(target, fn):
            getattr(target, fn)(*args, **keywords)

    def select_all(self) -> bool:
        if self.__display_item:
            self.__display_item.graphic_selection.add_range(range(len(self.__display_item.graphics)))
        return True

    def __selection_changed(self) -> None:
        # item displayed user deselects last item in browser => item stays displayed
        # item displayed but filter changes and no item remains => item stays displayed
        # item not displayed but user selects one item in browser => item gets displayed
        # item displayed but gets deleted => no display
        if len(self.__selection.indexes) == 1:
            index = list(self.__selection.indexes)[0]
            display_item = self.__filtered_display_item_adapters_model.display_item_adapters[index].display_item
            self.set_display_item(display_item, update_selection=False)  # do not sync the selection - it's already known
            self.__display_changed = True
        elif len(self.__selection.indexes) > 1:
            display_item = None
            self.set_display_item(display_item, update_selection=False)  # do not sync the selection - it's already known
            self.__display_changed = True

    # messages from the display canvas item

    def add_index_to_selection(self, index: int) -> None:
        if self.__display_item:
            self.__display_item.graphic_selection.add(index)

    def remove_index_from_selection(self, index: int) -> None:
        if self.__display_item:
            self.__display_item.graphic_selection.remove(index)

    def set_selection(self, index: int) -> None:
        if self.__display_item:
            self.__display_item.graphic_selection.set(index)

    def clear_selection(self) -> None:
        if self.__display_item:
            self.__display_item.graphic_selection.clear()

    def add_and_select_region(self, region: Graphics.Graphic) -> Undo.UndoableCommand:
        assert self.__display_item
        command = InsertGraphicsCommand(self.__document_controller, self.__display_item, [region])
        command.perform()
        # hack to select it. it will be the last item.
        self.__display_item.graphic_selection.set(len(self.__display_item.graphics) - 1)
        return command

    def nudge_selected_graphics(self, mapping: Graphics.CoordinateMappingLike, delta: Geometry.FloatSize) -> None:
        if self.__display_item:
            all_graphics = self.__display_item.graphics
            graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if self.__display_item.graphic_selection.contains(graphic_index)]
            if graphics:
                command = ChangeGraphicsCommand(self.__document_controller.document_model, self.__display_item, graphics, command_id="nudge", is_mergeable=True)
                for graphic in graphics:
                    graphic.nudge(mapping, delta)
                self.__document_controller.push_undo_command(command)

    def adjust_graphics(self, widget_mapping: Graphics.CoordinateMappingLike, graphic_drag_items: typing.Sequence[Graphics.Graphic], graphic_drag_part: str, graphic_part_data: typing.Dict[int, Graphics.DragPartData], graphic_drag_start_pos: Geometry.FloatPoint, pos: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> None:
        if self.__display_item:
            graphic_changed = False
            for graphic in graphic_drag_items:
                index = self.__display_item.graphics.index(graphic)
                part_data = (graphic_drag_part, ) + graphic_part_data[index]
                graphic_modified = graphic.modified_count
                graphic.adjust_part(widget_mapping, graphic_drag_start_pos, pos, part_data, modifiers)
                if graphic.modified_count != graphic_modified:
                    graphic_changed = True
            if graphic_changed:
                self.__display_item._begin_display_item_changes()
                self.__display_item._end_display_item_changes()

    def nudge_slice(self, delta: int) -> None:
        display_data_channel = self.__display_item.display_data_channel if self.__display_item else None
        if display_data_channel:
            data_item = display_data_channel.data_item
            if data_item and data_item.is_sequence:
                mx = data_item.dimensional_shape[0] - 1  # sequence_index
                value = display_data_channel.sequence_index + delta
                if 0 <= value <= mx:
                    property_name = "sequence_index"
                    command = ChangeDisplayDataChannelCommand(self.__document_controller.document_model, display_data_channel, title=_("Change Display"), command_id="change_display_" + property_name, is_mergeable=True, **{property_name: value})
                    command.perform()
                    self.__document_controller.push_undo_command(command)
            if data_item and data_item.is_collection and data_item.collection_dimension_count == 1:
                # it's not a sequence at this point
                mx = data_item.dimensional_shape[0] - 1  # sequence_index
                value = display_data_channel.collection_index[0] + delta
                if 0 <= value <= mx:
                    property_name = "collection_index"
                    command = ChangeDisplayDataChannelCommand(self.__document_controller.document_model, display_data_channel, title=_("Change Display"), command_id="change_display_" + property_name, is_mergeable=True, **{property_name: (value, )})
                    command.perform()
                    self.__document_controller.push_undo_command(command)

    @property
    def tool_mode(self) -> str:
        return self.__document_controller.tool_mode

    @tool_mode.setter
    def tool_mode(self, value: str) -> None:
        self.__document_controller.tool_mode = value

    def begin_mouse_tracking(self) -> None:
        assert self.__display_item
        self.__mouse_tracking_transaction = self.__document_controller.document_model.begin_display_item_transaction(self.__display_item)

    def create_mime_data(self) -> UserInterface.MimeData:
        return self.ui.create_mime_data()

    def create_rgba_image(self, drawing_context: DrawingContext.DrawingContext, width: int, height: int) -> typing.Optional[DrawingContext.RGBA32Type]:
        return self.ui.create_rgba_image(drawing_context, width, height)

    def get_display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        return self.display_item

    def get_document_model(self) -> DocumentModel.DocumentModel:
        return self.document_controller.document_model

    def end_mouse_tracking(self, undo_command: typing.Optional[Undo.UndoableCommand]) -> None:
        self.__mouse_tracking_transaction.close()
        self.__mouse_tracking_transaction = typing.cast(typing.Any, None)
        if undo_command:
            self.__document_controller.push_undo_command(undo_command)

    def delete_key_pressed(self) -> None:
        self.__document_controller.remove_selected_graphics()

    def enter_key_pressed(self) -> None:
        self.handle_auto_display()

    def handle_auto_display(self) -> bool:
        if self.__display_item:
            command = ChangeDisplayCommand(self.__document_controller.document_model, self.__display_item)
            if self.display_canvas_item:
                result = self.display_canvas_item.handle_auto_display()
                if result:
                    self.__document_controller.push_undo_command(command)
                else:
                    command.close()
                return result
        return False

    def cursor_changed(self, pos: typing.Optional[typing.Tuple[int, ...]]) -> None:
        # displaying the cursor position is one of a few places where the UI thread
        # accesses the data directly. however, some data may not give access immediately.
        # so put the update into an async method and access the data in a blocked async
        # thread. this is a stop gap until a better data reader than hdf5 is available.
        # to reproduce: use a larger hdf5 file (e.g. 742x512x2048), do a pick average,
        # and drag the region. the cursor display will try to update during dragging
        # and it will be locked out until the pick computation is complete, resulting
        # in stuttering. this async solution avoids this specific case.

        def update_cursor_(document_controller: typing.Optional[DocumentController.DocumentController], position_text: str, value_text: str) -> None:
            with Process.audit("update_cursor"):
                self.__cursor_task = None
                position_and_value_text = []
                if position_text:
                    position_and_value_text.append(_("Position: ") + position_text)
                if value_text:
                    position_and_value_text.append(_("Value: ") + value_text)
                if document_controller:
                    if len(position_text) == 0:
                        document_controller.cursor_changed(None)
                    else:
                        document_controller.cursor_changed(position_and_value_text)

        if not self.__cursor_task:
            if threading.current_thread() == threading.main_thread():

                # Python 3.9+: weakref typing
                async def update_cursor(document_controller_ref: typing.Any, display_item_ref: typing.Any) -> None:
                    document_controller = typing.cast(typing.Optional["DocumentController.DocumentController"], document_controller_ref())
                    display_item = typing.cast(typing.Optional[DisplayItem.DisplayItem], display_item_ref())
                    position_text, value_text = str(), str()
                    if pos is not None and display_item:
                        position_text, value_text = await display_item.get_value_and_position_text_async(pos)
                    update_cursor_(document_controller, position_text, value_text)

                self.__cursor_task = asyncio.get_event_loop_policy().get_event_loop().create_task(update_cursor(weakref.ref(self.__document_controller), weakref.ref(self.__display_item)))
            else:
                display_item = self.__display_item
                position_text, value_text = str(), str()
                if pos is not None and display_item:
                    position_text, value_text = display_item.get_value_and_position_text(pos)
                update_cursor_(self.__document_controller, position_text, value_text)

    def drag_graphics(self, graphics: typing.Sequence[Graphics.Graphic]) -> None:
        display_item = self.display_item
        if display_item:
            mime_data = self.ui.create_mime_data()
            MimeTypes.mime_data_put_data_source(mime_data, display_item, graphics[0] if len(graphics) == 1 else None)
            thumbnail_data = Thumbnails.ThumbnailManager().thumbnail_data_for_display_item(display_item)
            self.__begin_drag(mime_data, thumbnail_data)

    def update_display_properties(self, display_properties: Persistence.PersistentDictType) -> None:
        if self.__display_item:
            for key, value in iter(display_properties.items()):
                self.__display_item.set_display_property(key, value)

    def update_display_data_channel_properties(self, display_data_channel_properties: Persistence.PersistentDictType) -> None:
        display_data_channel = self.__display_item.display_data_channel if self.__display_item else None
        if display_data_channel:
            for key, value in iter(display_data_channel_properties.items()):
                setattr(display_data_channel, key, value)

    def create_insert_graphics_command(self, graphics: typing.Sequence[Graphics.Graphic]) -> InsertGraphicsCommand:
        assert self.__display_item
        return InsertGraphicsCommand(self.__document_controller, self.__display_item, list(), existing_graphics=graphics)

    def create_change_display_command(self, *, command_id: typing.Optional[str] = None, is_mergeable: bool=False) -> ChangeDisplayCommand:
        assert self.__display_item
        return ChangeDisplayCommand(self.__document_controller.document_model, self.__display_item, command_id=command_id, is_mergeable=is_mergeable)

    def create_move_display_layer_command(self, display_item: DisplayItem.DisplayItem, src_index: int, target_index: int) -> MoveDisplayLayerCommand:
        assert self.__display_item
        return MoveDisplayLayerCommand(self.__document_controller.document_model, display_item, src_index, self.__display_item, target_index)

    def create_change_graphics_command(self) -> ChangeGraphicsCommand:
        assert self.__display_item
        all_graphics = self.__display_item.graphics
        graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if self.__display_item.graphic_selection.contains(graphic_index)]
        return ChangeGraphicsCommand(self.__document_controller.document_model, self.__display_item, graphics)

    def push_undo_command(self, command: Undo.UndoableCommand) -> None:
        self.__document_controller.push_undo_command(command)

    def create_change_display_properties_task(self) -> DisplayCanvasItem.InteractiveTask:
        return ChangeDisplayPropertiesInteractiveTask(self)

    def create_change_graphics_task(self) -> DisplayCanvasItem.InteractiveTask:
        return ChangeGraphicsInteractiveTask(self)

    def create_create_graphic_task(self, graphic_type: str, start_position: Geometry.FloatPoint) -> DisplayCanvasItem.InteractiveTask:
        return CreateGraphicInteractiveTask(self, graphic_type, start_position)

    def create_rectangle(self, pos: Geometry.FloatPoint) -> Graphics.RectangleGraphic:
        assert self.__display_item
        self.__display_item.graphic_selection.clear()
        region = Graphics.RectangleGraphic()
        region.bounds = Geometry.FloatRect(pos, Geometry.FloatSize())
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_ellipse(self, pos: Geometry.FloatPoint) -> Graphics.EllipseGraphic:
        assert self.__display_item
        self.__display_item.graphic_selection.clear()
        region = Graphics.EllipseGraphic()
        region.bounds = Geometry.FloatRect(pos, Geometry.FloatSize())
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_line(self, pos: Geometry.FloatPoint) -> Graphics.LineGraphic:
        assert self.__display_item
        self.__display_item.graphic_selection.clear()
        region = Graphics.LineGraphic()
        region.start = pos
        region.end = pos
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_point(self, pos: Geometry.FloatPoint) -> Graphics.PointGraphic:
        assert self.__display_item
        self.__display_item.graphic_selection.clear()
        region = Graphics.PointGraphic()
        region.position = pos
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_line_profile(self, pos: Geometry.FloatPoint) -> Graphics.LineProfileGraphic:
        assert self.__display_item
        data_item = self.__display_item.data_item
        assert data_item
        self.__display_item.graphic_selection.clear()
        line_profile_region = Graphics.LineProfileGraphic()
        line_profile_region.start = pos
        line_profile_region.end = pos
        self.__display_item.add_graphic(line_profile_region)
        document_controller = self.__document_controller
        document_model = document_controller.document_model
        line_profile_data_item = document_model.get_line_profile_new(self.__display_item, data_item, None, line_profile_region)
        assert line_profile_data_item
        line_profile_display_item = document_model.get_display_item_for_data_item(line_profile_data_item)
        assert line_profile_display_item
        document_controller.show_display_item(line_profile_display_item)
        return line_profile_region

    def create_spot(self, pos: Geometry.FloatPoint) -> Graphics.SpotGraphic:
        assert self.__display_item
        display_data_channel = self.__display_item.display_data_channel
        assert display_data_channel
        display_values = display_data_channel.get_latest_computed_display_values()
        assert display_values
        element_data_and_metadata = display_values.element_data_and_metadata
        assert element_data_and_metadata
        data_shape = element_data_and_metadata.datum_dimension_shape
        mapping = ImageCanvasItem.ImageCanvasItemMapping.make(data_shape, Geometry.IntRect.unit_rect(), element_data_and_metadata.datum_dimensional_calibrations)
        assert mapping
        calibrated_origin_image_norm = mapping.calibrated_origin_image_norm
        assert calibrated_origin_image_norm
        bounds = Geometry.FloatRect.from_center_and_size(pos - calibrated_origin_image_norm, Geometry.FloatSize())
        self.__display_item.graphic_selection.clear()
        region = Graphics.SpotGraphic()
        region.bounds = bounds
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_wedge(self, angle: float) -> Graphics.WedgeGraphic:
        assert self.__display_item
        self.__display_item.graphic_selection.clear()
        region = Graphics.WedgeGraphic()
        region.end_angle = angle
        region.start_angle = angle + math.pi
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_ring(self, radius: float) -> Graphics.RingGraphic:
        assert self.__display_item
        self.__display_item.graphic_selection.clear()
        region = Graphics.RingGraphic()
        region.radius_1 = radius
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_lattice(self, u_pos: Geometry.FloatSize) -> Graphics.LatticeGraphic:
        assert self.__display_item
        display_data_channel = self.__display_item.display_data_channel
        assert display_data_channel
        display_values = display_data_channel.get_latest_computed_display_values()
        assert display_values
        element_data_and_metadata = display_values.element_data_and_metadata
        assert element_data_and_metadata
        data_shape = element_data_and_metadata.datum_dimension_shape
        mapping = ImageCanvasItem.ImageCanvasItemMapping.make(data_shape, Geometry.IntRect.unit_rect(), element_data_and_metadata.datum_dimensional_calibrations)
        assert mapping
        self.__display_item.graphic_selection.clear()
        region = Graphics.LatticeGraphic()
        calibrated_origin_image_norm = mapping.calibrated_origin_image_norm
        assert calibrated_origin_image_norm
        region.u_pos = u_pos - calibrated_origin_image_norm
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region


class DisplayPanelControllerLike(typing.Protocol):
    type: str
    def close(self) -> None: ...
    def save(self, d: Persistence.PersistentDictType) -> None: ...
    def key_pressed(self, key: UserInterface.Key) -> bool: ...
    def key_released(self, key: UserInterface.Key) -> bool: ...


class DisplayPanelControllerFactoryLike(typing.Protocol):
    def make_new(self, controller_type: str, display_panel: DisplayPanel, d: Persistence.PersistentDictType) -> typing.Optional[DisplayPanelControllerLike]: ...
    def match(self, document_model: DocumentModel.DocumentModel, data_item: DataItem.DataItem) -> typing.Optional[Persistence.PersistentDictType]: ...
    def build_menu(self, display_type_menu: UserInterface.Menu, selected_display_panel: typing.Optional[DisplayPanel]) -> typing.Sequence[UserInterface.MenuAction]: ...

    @property
    def priority(self) -> int: return 0


class DisplayPanelManager(metaclass=Utility.Singleton):
    """ Acts as a broker for significant events occurring regarding display panels. Listeners can attach themselves to
    this object and receive messages regarding display panels. For instance, when the user presses a key on an display
    panel that isn't handled directly, listeners will be advised of this event. """

    def __init__(self) -> None:
        super().__init__()
        self.__display_controller_factories: typing.Dict[str, DisplayPanelControllerFactoryLike] = dict()
        self.key_pressed_event = Event.Event()
        self.key_released_event = Event.Event()
        self.image_display_clicked_event = Event.Event()
        self.image_display_mouse_pressed_event = Event.Event()
        self.image_display_mouse_released_event = Event.Event()
        self.image_display_mouse_position_changed_event = Event.Event()

    def __get_kwargs(self, display_panel: DisplayPanel) -> typing.Dict[str, typing.Any]:
        kwargs: typing.Dict[str, typing.Any] = dict()
        kwargs["display_panel"] = display_panel
        if display_panel.data_item:
            kwargs["data_item"] = display_panel.data_item
        if display_panel.display_item:
            kwargs["display_item"] = display_panel.display_item
        return kwargs

    # events from the image panels
    def key_pressed(self, display_panel: DisplayPanel, key: UserInterface.Key) -> bool:
        if display_panel.document_controller.exec_action_events("key_pressed", key=key, **self.__get_kwargs(display_panel)):
            return True
        return self.key_pressed_event.fire_any(display_panel, key)

    # events from the image panels
    def key_released(self, display_panel: DisplayPanel, key: UserInterface.Key) -> bool:
        if display_panel.document_controller.exec_action_events("key_released", key=key, **self.__get_kwargs(display_panel)):
            return True
        return self.key_released_event.fire_any(display_panel, key)

    def focus_changed(self, display_panel: DisplayPanel, focused: bool) -> None:
        display_panel.document_controller.exec_action_events("focused" if focused else "unfocused", **self.__get_kwargs(display_panel))

    def image_display_clicked(self, display_panel: DisplayPanel, display_item: DisplayItem.DisplayItem, image_position: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if display_panel.document_controller.exec_action_events("mouse_clicked", image_position=image_position, modifiers=modifiers, **self.__get_kwargs(display_panel)):
            return True
        return self.image_display_clicked_event.fire_any(display_panel, display_item, image_position, modifiers)

    def image_display_mouse_pressed(self, display_panel: DisplayPanel, display_item: DisplayItem.DisplayItem, image_position: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if display_panel.document_controller.exec_action_events("mouse_pressed", image_position=image_position, modifiers=modifiers, **self.__get_kwargs(display_panel)):
            return True
        return self.image_display_mouse_pressed_event.fire_any(display_panel, display_item, image_position, modifiers)

    def image_display_mouse_released(self, display_panel: DisplayPanel, display_item: DisplayItem.DisplayItem, image_position: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if display_panel.document_controller.exec_action_events("mouse_released", image_position=image_position, modifiers=modifiers, **self.__get_kwargs(display_panel)):
            return True
        return self.image_display_mouse_released_event.fire_any(display_panel, display_item, image_position, modifiers)

    def image_display_mouse_position_changed(self, display_panel: DisplayPanel, display_item: DisplayItem.DisplayItem, image_position: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if display_panel.document_controller.exec_action_events("mouse_moved", image_position=image_position, modifiers=modifiers, **self.__get_kwargs(display_panel)):
            return True
        return self.image_display_mouse_position_changed_event.fire_any(display_panel, display_item, image_position, modifiers)

    def register_display_panel_controller_factory(self, factory_id: str, factory: DisplayPanelControllerFactoryLike) -> None:
        assert factory_id not in self.__display_controller_factories
        self.__display_controller_factories[factory_id] = factory

    def unregister_display_panel_controller_factory(self, factory_id: str) -> None:
        assert factory_id in self.__display_controller_factories
        del self.__display_controller_factories[factory_id]

    def detect_controller(self, document_model: DocumentModel.DocumentModel, data_item: DataItem.DataItem) -> typing.Optional[Persistence.PersistentDictType]:
        priority = 0
        result: typing.Optional[Persistence.PersistentDictType] = None
        for factory in self.__display_controller_factories.values():
            controller_type = factory.match(document_model, data_item)
            if controller_type and factory.priority > priority:
                priority = factory.priority
                result = controller_type
        return result

    def make_display_panel_controller(self, controller_type: str, display_panel: DisplayPanel, d: Persistence.PersistentDictType) -> typing.Optional[DisplayPanelControllerLike]:
        for factory in self.__display_controller_factories.values():
            display_panel_controller = factory.make_new(controller_type, display_panel, d)
            if display_panel_controller:
                return display_panel_controller
        return None

    def build_menu(self, display_type_menu: UserInterface.Menu, document_controller: DocumentController.DocumentController, display_panel: DisplayPanel) -> typing.Sequence[UserInterface.MenuAction]:
        """Build the dynamic menu for the selected display panel.

        The user accesses this menu by right-clicking on the display panel.

        The basic menu items are to an empty display panel or a browser display panel.

        After that, each display controller factory is given a chance to add to the menu. The display
        controllers (for instance, a scan acquisition controller), may add its own menu items.
        """
        dynamic_live_actions: typing.List[UserInterface.MenuAction] = list()

        for factory in self.__display_controller_factories.values():
            dynamic_live_actions.extend(factory.build_menu(display_type_menu, display_panel))

        return dynamic_live_actions


def preview(ui_settings: UISettings.UISettings, display_item: DisplayItem.DisplayItem, width: int, height: int) -> typing.Tuple[DrawingContext.DrawingContext, Geometry.IntSize]:
    drawing_context = DrawingContext.DrawingContext()
    shape = Geometry.IntSize()
    display_canvas_item = create_display_canvas_item(display_item, ui_settings, None, None, draw_background=False)
    if display_canvas_item:
        with contextlib.closing(display_canvas_item):
            display_data_delta = display_item.display_data_delta_stream.value
            assert display_data_delta
            display_data_delta.mark_changed()
            display_canvas_item.update_display_data_delta(display_data_delta)
            with drawing_context.saver():
                frame_width, frame_height = width, int(width / display_canvas_item.default_aspect_ratio)
                display_canvas_item.repaint_immediate(drawing_context, Geometry.IntSize(height=frame_height, width=frame_width))
                shape = Geometry.IntSize(height=frame_height, width=frame_width)
    return drawing_context, shape
