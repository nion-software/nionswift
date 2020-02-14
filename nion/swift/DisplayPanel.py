# standard libraries
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

from nion.swift import DataItemThumbnailWidget
from nion.swift import DataPanel
from nion.swift import DisplayScriptCanvasItem
from nion.swift import ImageCanvasItem
from nion.swift import LinePlotCanvasItem
from nion.swift import MimeTypes
from nion.swift import Panel
from nion.swift import Thumbnails
from nion.swift import Undo
from nion.swift import Inspector
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Persistence
from nion.swift.model import Project
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import GridCanvasItem
from nion.ui import UserInterface
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel


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

    def __init__(self):
        super().__init__()
        self.wants_drag_events = True
        self.__is_dragging = False
        self.__drop_region = "none"
        self.__focused = False
        self.__selected = False
        self.__selected_style = "#CCC"  # TODO: platform dependent
        self.__focused_style = "#3876D6"  # TODO: platform dependent
        self.__drop_regions_map = dict()
        self.on_context_menu_event = None
        self.on_drag_enter = None
        self.on_drag_leave = None
        self.on_drag_move = None
        self.on_wants_drag_event = None
        self.on_drop = None
        self.on_key_pressed = None
        self.on_key_released = None

    def close(self):
        self.on_context_menu_event = None
        self.on_drag_enter = None
        self.on_drag_leave = None
        self.on_drag_move = None
        self.on_drop = None
        self.on_key_pressed = None
        self.on_key_released = None
        self.on_select_all = None
        super().close()

    @property
    def focused(self):
        return self.__focused

    @focused.setter
    def focused(self, value):
        if self.__focused != value:
            self.__focused = value
            self.update()

    @property
    def selected(self):
        return self.__selected

    @selected.setter
    def selected(self, selected):
        if self.__selected != selected:
            self.__selected = selected
            self.update()

    @property
    def selected_style(self):
        return self.__selected_style

    @selected_style.setter
    def selected_style(self, selected_style):
        self.__selected_style = selected_style

    @property
    def focused_style(self):
        return self.__focused_style

    @focused_style.setter
    def focused_style(self, focused_style):
        self.__focused_style = focused_style

    @property
    def drop_regions_map(self):
        return self.__drop_regions_map

    @drop_regions_map.setter
    def drop_regions_map(self, value):
        self.__drop_regions_map = value if value else dict()

    def __set_drop_region(self, drop_region):
        if self.__drop_region != drop_region:
            self.__drop_region = drop_region
            self.update()

    def _repaint(self, drawing_context):
        super()._repaint(drawing_context)

        # canvas size
        canvas_width = self.canvas_size[1]
        canvas_height = self.canvas_size[0]

        drop_regions_map = self.__drop_regions_map

        if self.__drop_region != "none":
            with drawing_context.saver():
                drawing_context.begin_path()
                if self.__drop_region in drop_regions_map:
                    drop_region_hit_rect, drop_region_draw_rect = drop_regions_map[self.__drop_region]
                    drawing_context.rect(drop_region_draw_rect.left, drop_region_draw_rect.top, drop_region_draw_rect.width, drop_region_draw_rect.height)
                elif self.__drop_region == "left":
                    drawing_context.rect(0, 0, int(canvas_width * 0.10), canvas_height)
                elif self.__drop_region == "right":
                    drawing_context.rect(int(canvas_width * 0.90), 0, int(canvas_width - canvas_width * 0.90), canvas_height)
                elif self.__drop_region == "top":
                    drawing_context.rect(0, 0, canvas_width, int(canvas_height * 0.10))
                elif self.__drop_region == "bottom":
                    drawing_context.rect(0, int(canvas_height * 0.90), canvas_width, int(canvas_height - canvas_height * 0.90))
                else:
                    drawing_context.rect(0, 0, canvas_width, canvas_height)
                drawing_context.fill_style = "rgba(255, 0, 0, 0.10)"
                drawing_context.fill()

        if self.selected:

            stroke_style = self.__focused_style if self.focused else self.__selected_style

            if stroke_style:
                with drawing_context.saver():
                    drawing_context.begin_path()
                    drawing_context.rect(2, 2, canvas_width - 4, canvas_height - 4)
                    drawing_context.line_join = "miter"
                    drawing_context.stroke_style = stroke_style
                    drawing_context.line_width = 4.0
                    drawing_context.stroke()

    def context_menu_event(self, x, y, gx, gy):
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

    def drag_leave(self):
        self.__is_dragging = False
        self.__set_drop_region("none")
        if self.on_drag_leave:
            self.on_drag_leave()
        return False

    def drag_move(self, mime_data, x, y):
        if self.on_drag_move:
            result = self.on_drag_move(mime_data, x, y)
            if result != "ignore":
                p = Geometry.IntPoint(y=y, x=x)
                canvas_size = Geometry.IntSize.make(self.canvas_size)
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

    def drop(self, mime_data, x, y):
        drop_region = self.__drop_region
        self.__is_dragging = False
        self.__set_drop_region("none")
        if self.on_drop:
            return self.on_drop(mime_data, drop_region, x, y)
        return "ignore"

    def key_pressed(self, key):
        if self.on_key_pressed:
            if self.on_key_pressed(key):
                return True
        return super().key_pressed(key)

    def key_released(self, key):
        if self.on_key_released:
            if self.on_key_released(key):
                return True
        return super().key_released(key)

    def handle_select_all(self):
        if callable(self.on_select_all):
            return self.on_select_all()
        return False


def create_display_canvas_item(display_item: DisplayItem.DisplayItem, get_font_metrics_fn, delegate, event_loop, draw_background: bool=True):
    display_type = display_item.used_display_type
    if display_type == "line_plot":
        return LinePlotCanvasItem.LinePlotCanvasItem(get_font_metrics_fn, delegate, event_loop, draw_background)
    elif display_type == "image":
        return ImageCanvasItem.ImageCanvasItem(get_font_metrics_fn, delegate, event_loop, draw_background)
    elif display_type == "display_script":
        return DisplayScriptCanvasItem.DisplayScriptCanvasItem(get_font_metrics_fn, delegate, event_loop, draw_background)
    else:
        return MissingDataCanvasItem(delegate)


def is_valid_display_type(display_type: str) -> bool:
    return display_type in ("image", "line_plot", "display_script")


class DisplayTypeMonitor:
    """Monitor a display for changes to the display type.

    Provides the display_type_changed(display_type) event.

    Provides the display_type r/o property.
    """

    def __init__(self, display_item: DisplayItem.DisplayItem):
        self.display_type_changed_event = Event.Event()
        self.__display_changed_event_listener = None
        self.__display_type = None
        self.__first = True  # handle case where there is no data, so display_type is always None and doesn't change
        if display_item:
            self.__display_changed_event_listener = display_item.display_changed_event.listen(functools.partial(self.__update_display_type, display_item))
        self.__update_display_type(display_item)

    def close(self):
        if self.__display_changed_event_listener:
            self.__display_changed_event_listener.close()
            self.__display_changed_event_listener = None

    def __update_display_type(self, display_item: DisplayItem.DisplayItem) -> None:
        display_type = display_item.used_display_type if display_item else None
        if self.__display_type != display_type or self.__first:
            self.__display_type = display_type
            self.display_type_changed_event.fire(display_type)
            self.__first = False


class RelatedIconsCanvasItem(CanvasItem.CanvasItemComposition):
    """Display icons to related items (sources and dependencies)."""

    def __init__(self, ui, document_model):
        super().__init__()
        self.ui = ui
        self.__document_model = document_model
        self.__source_thumbnails = CanvasItem.CanvasItemComposition()
        self.__source_thumbnails.layout = CanvasItem.CanvasItemRowLayout(spacing=8)
        self.__dependent_thumbnails = CanvasItem.CanvasItemComposition()
        self.__dependent_thumbnails.layout = CanvasItem.CanvasItemRowLayout(spacing=8)
        self.__thumbnail_size = Geometry.IntSize(height=24, width=24)
        row = CanvasItem.CanvasItemComposition()
        row.sizing.set_fixed_height(self.__thumbnail_size.height)
        row.layout = CanvasItem.CanvasItemRowLayout()
        row.add_spacing(12)
        row.add_canvas_item(self.__source_thumbnails)
        row.add_stretch()
        row.add_canvas_item(self.__dependent_thumbnails)
        row.add_spacing(12)
        self.layout = CanvasItem.CanvasItemColumnLayout()
        self.add_stretch()
        self.add_canvas_item(row)
        self.add_spacing(4)
        self.on_drag = None
        self.__display_item = None

    def close(self):
        self.set_display_item(None)
        super().close()

    @property
    def _source_thumbnails(self):
        return self.__source_thumbnails

    @property
    def _dependent_thumbnails(self):
        return self.__dependent_thumbnails

    def __related_items_changed(self, display_item, source_display_items, dependent_display_items):
        if self.__document_model.are_display_items_equal(display_item, self.__display_item):
            self.__source_thumbnails.remove_all_canvas_items()
            self.__dependent_thumbnails.remove_all_canvas_items()
            for source_display_item in source_display_items:
                thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(self.ui, display_item=source_display_item)
                thumbnail_canvas_item = DataItemThumbnailWidget.ThumbnailCanvasItem(self.ui, thumbnail_source, self.__thumbnail_size)
                thumbnail_canvas_item.on_drag = self.on_drag
                self.__source_thumbnails.add_canvas_item(thumbnail_canvas_item)
            for dependent_display_item in dependent_display_items:
                thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(self.ui, display_item=dependent_display_item)
                thumbnail_canvas_item = DataItemThumbnailWidget.ThumbnailCanvasItem(self.ui, thumbnail_source, self.__thumbnail_size)
                thumbnail_canvas_item.on_drag = self.on_drag
                self.__dependent_thumbnails.add_canvas_item(thumbnail_canvas_item)

    def set_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        if self.__display_item:
            self.__related_items_changed_listener.close()
            self.__related_items_changed_listener = None

        self.__display_item = display_item

        if self.__display_item:
            self.__related_items_changed_listener = self.__document_model.related_items_changed.listen(self.__related_items_changed)
            source_display_items = self.__document_model.get_source_display_items(self.__display_item)
            dependent_display_items = self.__document_model.get_dependent_display_items(self.__display_item)
            self.__related_items_changed(self.__display_item, source_display_items, dependent_display_items)
        else:
            self.__related_items_changed(self.__display_item, [], [])


class MissingDataCanvasItem(CanvasItem.CanvasItemComposition):
    """ Canvas item to draw background_color. """
    def __init__(self, delegate):
        super().__init__()
        self.__delegate = delegate

    def context_menu_event(self, x, y, gx, gy):
        return self.__delegate.show_display_context_menu(gx, gy)

    @property
    def default_aspect_ratio(self):
        return 1.0

    def update_display_values(self, display_values_list) -> None:
        pass

    def update_display_properties(self, display_calibration_info, display_properties, display_layers) -> None:
        pass

    def update_graphics_coordinate_system(self, graphics, graphic_selection, display_calibration_info) -> None:
        pass

    def handle_auto_display(self) -> bool:
        # enter key has been pressed
        return False

    def _repaint(self, drawing_context):
        # canvas size
        canvas_width = self.canvas_size[1]
        canvas_height = self.canvas_size[0]
        with drawing_context.saver():
            drawing_context.begin_path()
            drawing_context.rect(0, 0, canvas_width, canvas_height)
            drawing_context.fill_style = "#CCC"
            drawing_context.fill()
            drawing_context.begin_path()
            drawing_context.rect(0, 0, canvas_width, canvas_height)
            drawing_context.move_to(0, 0)
            drawing_context.line_to(canvas_width, canvas_height)
            drawing_context.move_to(0, canvas_height)
            drawing_context.line_to(canvas_width, 0)
            drawing_context.stroke_style = "#444"
            drawing_context.stroke()


class DisplayTracker:
    """Tracks messages from a display and passes them to associated display canvas item."""

    def __init__(self, display_item, get_font_metrics, delegate, event_loop, draw_background):
        self.__display_item = display_item
        self.__get_font_metrics = get_font_metrics
        self.__delegate = delegate
        self.__event_loop = event_loop
        self.__draw_background = draw_background

        self.__closing_lock = threading.RLock()

        self.__display_canvas_item = None

        # callbacks
        self.on_clear_display = None
        self.on_title_changed = None
        self.on_replace_display_canvas_item = None

        def clear_display():
            if callable(self.on_clear_display):
                self.on_clear_display()

        def display_item_property_changed(key):
            if key == "displayed_title":
                if callable(self.on_title_changed):
                    self.on_title_changed(display_item.displayed_title)

        self.__display_about_to_be_removed_event_listener = display_item.about_to_be_removed_event.listen(clear_display)
        self.__display_property_changed_event_listener = display_item.property_changed_event.listen(display_item_property_changed)

        # ensure data stays in memory while displayed
        display_item.increment_display_ref_count()

        # create a canvas item and add it to the container canvas item.

        self.__display_canvas_item = create_display_canvas_item(display_item, get_font_metrics, delegate, event_loop, draw_background=self.__draw_background)

        display_data_channel_shapes_ref = [list()]

        def display_graphics_changed(graphic_selection):
            # this message comes from the display when the graphic selection changes
            self.__display_canvas_item.update_graphics_coordinate_system(display_item.graphics, graphic_selection, DisplayItem.DisplayCalibrationInfo(display_item))

        def display_values_changed():
            # this notification is for the rgba values only
            # thread safe
            with self.__closing_lock:
                display_values_list = [display_data_channel.get_calculated_display_values() for display_data_channel in display_item.display_data_channels]
                self.__display_canvas_item.update_display_values(display_values_list)
            display_changed()
            # if the display data channel shapes change, update the graphics, but use the display channel to determine the shape; otherwise
            # the graphics update will use the shape from the last update. this design needs work.
            new_display_data_channel_shapes =  [display_data_channel.display_data_shape for display_data_channel in display_item.display_data_channels]
            if new_display_data_channel_shapes != display_data_channel_shapes_ref[0]:
                # use display data shape from the new shapes
                display_data_shape = new_display_data_channel_shapes[0] if len(new_display_data_channel_shapes) > 0 else None
                self.__display_canvas_item.update_graphics_coordinate_system(display_item.graphics, display_item.graphic_selection, DisplayItem.DisplayCalibrationInfo(display_item, display_data_shape))
                display_data_channel_shapes_ref[0] = new_display_data_channel_shapes

        def display_changed():
            # called when anything in the data item changes, including things like graphics or the data itself.
            # this notification does not cover the rgba data, which is handled in the function below.
            # thread safe
            with self.__closing_lock:
                self.__display_canvas_item.update_display_properties(DisplayItem.DisplayCalibrationInfo(display_item), display_item.display_properties, display_item.display_layers)

        def display_property_changed(property: str) -> None:
            if property in ("y_min", "y_max", "y_style", "left_channel", "right_channel", "image_zoom", "image_position", "image_canvas_mode"):
                display_changed()

        self.__next_calculated_display_values_listeners = list()

        def display_data_channel_inserted(key, value, before_index):
            if key == "display_data_channels":
                self.__next_calculated_display_values_listeners.insert(before_index, value.add_calculated_display_values_listener(display_values_changed))
                display_values_changed()

        def display_data_channel_removed(key, value, index):
            if key == "display_data_channels":
                self.__next_calculated_display_values_listeners[index].close()
                del self.__next_calculated_display_values_listeners[index]
                display_values_changed()

        self.__item_inserted_listener = display_item.item_inserted_event.listen(display_data_channel_inserted)
        self.__item_removed_listener = display_item.item_removed_event.listen(display_data_channel_removed)

        for index, display_data_channel in enumerate(display_item.display_data_channels):
            display_data_channel_inserted("display_data_channels", display_data_channel, index)

        self.__display_values_changed_event_listener = display_item.display_values_changed_event.listen(display_values_changed)
        self.__display_data_channel_property_changed_listener = display_item.property_changed_event.listen(display_property_changed)
        self.__display_graphics_changed_event_listener = display_item.graphics_changed_event.listen(display_graphics_changed)
        self.__display_changed_event_listener = display_item.display_changed_event.listen(display_changed)
        self.__display_property_changed_listener = display_item.display_property_changed_event.listen(display_property_changed)

        # this may throw exceptions (during testing). make sure to close if that happens, ensuring that the
        # layer items (image/line plot) get shut down.
        display_values_changed()
        display_changed()
        display_graphics_changed(display_item.graphic_selection)

        def display_type_changed(display_type):
            # called when the display type of the data item changes.
            old_display_canvas_item = self.__display_canvas_item
            new_display_canvas_item = create_display_canvas_item(display_item, self.__get_font_metrics, self.__delegate, self.__event_loop, draw_background=self.__draw_background)
            if callable(self.on_replace_display_canvas_item):
                self.on_replace_display_canvas_item(old_display_canvas_item, new_display_canvas_item)
            self.__display_canvas_item = new_display_canvas_item
            display_values_changed()
            display_changed()
            display_graphics_changed(display_item.graphic_selection)

        self.__display_type_monitor = DisplayTypeMonitor(display_item)
        self.__display_type_changed_event_listener =  self.__display_type_monitor.display_type_changed_event.listen(display_type_changed)

    def close(self):
        with self.__closing_lock:  # ensures that display pipeline finishes
            self.__display_changed_event_listener.close()
            self.__display_changed_event_listener = None
            self.__display_property_changed_listener.close()
            self.__display_property_changed_listener = None
            self.__display_values_changed_event_listener.close()
            self.__display_values_changed_event_listener = None
            self.__display_data_channel_property_changed_listener.close()
            self.__display_data_channel_property_changed_listener = None
            self.__display_graphics_changed_event_listener.close()
            self.__display_graphics_changed_event_listener = None
            for next_calculated_display_values_listener in self.__next_calculated_display_values_listeners:
                next_calculated_display_values_listener.close()
            self.__next_calculated_display_values_listeners = list()
            self.__item_inserted_listener.close()
            self.__item_inserted_listener = None
            self.__item_removed_listener.close()
            self.__item_removed_listener = None
        self.__display_type_changed_event_listener.close()
        self.__display_type_changed_event_listener = None
        self.__display_type_monitor.close()
        self.__display_type_monitor = None
        # decrement the ref count on the old item to release it from memory if no longer used.
        self.__display_item.decrement_display_ref_count()
        self.__display_about_to_be_removed_event_listener.close()
        self.__display_about_to_be_removed_event_listener = None
        self.__display_property_changed_event_listener.close()
        self.__display_property_changed_event_listener = None
        self.__display_canvas_item = None

    @property
    def display_canvas_item(self):
        return self.__display_canvas_item

    @display_canvas_item.setter
    def display_canvas_item(self, value):
        self.__display_canvas_item = value


class InsertGraphicsCommand(Undo.UndoableCommand):

    def __init__(self, document_controller, display_item: DisplayItem.DisplayItem, graphics: typing.Sequence[Graphics.Graphic], *, existing_graphics: typing.Sequence[Graphics.Graphic] = None):
        super().__init__(_("Insert Graphics"))
        self.__document_controller = document_controller
        self.__display_item_proxy = display_item.create_proxy()
        self.__graphics = graphics  # only used for perform
        self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
        self.__new_workspace_layout = None
        self.__graphics_properties = None
        self.__graphic_proxies = [graphic.create_proxy() for graphic in existing_graphics or list()]
        self.__undelete_logs = list()
        self.initialize()

    def close(self):
        self.__graphics_properties = None
        self.__document_controller = None
        self.__old_workspace_layout = None
        self.__new_workspace_layout = None
        for undelete_log in self.__undelete_logs:
            undelete_log.close()
        self.__undelete_logs = None
        for graphic_proxy in self.__graphic_proxies:
            graphic_proxy.close()
        self.__graphic_proxies = None
        self.__display_item_proxy.close()
        self.__display_item_proxy = None
        super().close()

    def perform(self):
        display_item = self.__display_item_proxy.item
        graphics = self.__graphics
        for graphic in graphics:
            display_item.add_graphic(graphic)
            new_graphic = display_item.graphics[-1]
            self.__graphic_proxies.append(new_graphic.create_proxy())
        self.__graphics = None

    def _get_modified_state(self):
        display_item = self.__display_item_proxy.item
        return display_item.modified_state, self.__document_controller.workspace_controller.document_model.modified_state

    def _set_modified_state(self, modified_state):
        display_item = self.__display_item_proxy.item
        display_item.modified_state, self.__document_controller.workspace_controller.document_model.modified_state = modified_state

    def _redo(self):
        for undelete_log in reversed(self.__undelete_logs):
            self.__document_controller.document_model.undelete_all(undelete_log)
            undelete_log.close()
        self.__undelete_logs.clear()
        self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

    def _undo(self):
        display_item = self.__display_item_proxy.item
        graphics = [graphic_proxy.item for graphic_proxy in self.__graphic_proxies]
        self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
        for graphic in graphics:
            self.__undelete_logs.append(display_item.remove_graphic(graphic, safe=True))
        self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)


class AppendDisplayDataChannelCommand(Undo.UndoableCommand):

    def __init__(self, document_model, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, *, title: str=None, command_id: str=None, **kwargs):
        super().__init__(title if title else _("Append Display"), command_id=command_id)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__data_item_proxy = data_item.create_proxy()
        self.__old_properties = None
        self.__display_data_channel_index = None
        self.__value_dict = kwargs
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__display_item_proxy.close()
        self.__display_item_proxy = None
        self.__data_item_proxy.close()
        self.__data_item_proxy = None
        super().close()

    def perform(self):
        display_item = self.__display_item_proxy.item
        data_item = self.__data_item_proxy.item
        self.__old_properties = display_item.save_properties()
        display_item.append_display_data_channel_for_data_item(data_item)
        self.__display_data_channel_index = display_item.display_data_channels.index(display_item.get_display_data_channel_for_data_item(data_item))

    def _get_modified_state(self):
        display_item = self.__display_item_proxy.item
        data_item = self.__data_item_proxy.item
        return data_item.modified_state, display_item.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state):
        display_item = self.__display_item_proxy.item
        data_item = self.__data_item_proxy.item
        data_item.modified_state, display_item.modified_state, self.__document_model.modified_state = modified_state

    def _undo(self):
        display_item = self.__display_item_proxy.item
        display_data_channel = display_item.display_data_channels[self.__display_data_channel_index]
        display_item.remove_display_data_channel(display_data_channel, safe=True)
        display_item.restore_properties(self.__old_properties)

    def _redo(self):
        self.perform()


class ChangeDisplayDataChannelCommand(Undo.UndoableCommand):

    def __init__(self, document_model, display_data_channel: DisplayItem.DisplayDataChannel, *, title: str=None, command_id: str=None, is_mergeable: bool=False, **kwargs):
        super().__init__(title if title else _("Change Display"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__display_data_channel_proxy = display_data_channel.create_proxy()
        self.__properties = display_data_channel.save_properties()
        self.__value_dict = kwargs
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__display_data_channel_proxy.close()
        self.__display_data_channel_proxy = None
        self.__properties = None
        super().close()

    def perform(self):
        display_data_channel = self.__display_data_channel_proxy.item
        for key, value in self.__value_dict.items():
            setattr(display_data_channel, key, value)

    def _get_modified_state(self):
        display_data_channel = self.__display_data_channel_proxy.item
        return display_data_channel.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state):
        display_data_channel = self.__display_data_channel_proxy.item
        display_data_channel.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self):
        display_data_channel = self.__display_data_channel_proxy.item
        properties = self.__properties
        self.__properties = display_data_channel.save_properties()
        display_data_channel.restore_properties(properties)

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeDisplayDataChannelCommand) and self.command_id and self.command_id == command.command_id and self.__display_data_channel_proxy.item == command.__display_data_channel_proxy.item


class MoveDisplayLayerCommand(Undo.UndoableCommand):

    def __init__(self, document_model,
                 old_display_item: DisplayItem.DisplayItem, old_display_layer_index: int,
                 new_display_item: DisplayItem.DisplayItem, new_display_layer_index: int,
                 *, title: str=None, command_id: str=None, is_mergeable: bool=False, **kwargs):
        super().__init__(title if title else _("Move Display Layer"), command_id=command_id, is_mergeable=is_mergeable)
        old_display_layer = old_display_item.display_layers[old_display_layer_index]
        old_display_data_channel_index = old_display_layer["data_index"]
        self.__document_model = document_model
        self.__old_display_item_proxy = old_display_item.create_proxy()
        self.__old_display_layer_index = old_display_layer_index
        self.__old_display_data_channel_index = old_display_data_channel_index
        self.__new_display_item_proxy = new_display_item.create_proxy()
        self.__new_display_layer_index = new_display_layer_index
        self.__new_display_data_channel_index = None
        self.__undelete_logs = list()
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__display_data_channel_uuid = None
        self.__properties = None
        for undelete_log in self.__undelete_logs:
            undelete_log.close()
        self.__undelete_logs = None
        self.__old_display_item_proxy.close()
        self.__old_display_item_proxy = None
        self.__new_display_item_proxy.close()
        self.__new_display_item_proxy = None
        super().close()

    def perform(self):
        # add display data channel and display layer to new display item
        old_display_item = self.__old_display_item_proxy.item
        old_display_layer = old_display_item.display_layers[self.__old_display_layer_index]
        new_display_item = self.__new_display_item_proxy.item
        self.__new_original_legend_position = new_display_item.get_display_property("legend_position")
        new_display_item.copy_display_layer(self.__new_display_layer_index, old_display_item, old_display_layer)
        self.__new_display_data_channel_index = len(new_display_item.display_data_channels) - 1
        # remove display layer and then display data channel from old display item
        self.__old_display_layers = copy.deepcopy(old_display_item.display_layers)
        old_display_item.remove_display_layer(self.__old_display_layer_index)
        self.__undelete_logs.append(old_display_item.remove_display_data_channel(old_display_item.display_data_channels[self.__old_display_data_channel_index]))

    def _get_modified_state(self):
        old_display_item = self.__old_display_item_proxy.item
        new_display_item = self.__new_display_item_proxy.item
        return old_display_item.modified_state, new_display_item.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state):
        old_display_item = self.__old_display_item_proxy.item
        new_display_item = self.__new_display_item_proxy.item
        old_display_item.modified_state, new_display_item.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0] and state1[1] == state2[1]

    def _undo(self):
        old_display_item = self.__old_display_item_proxy.item
        new_display_item = self.__new_display_item_proxy.item
        # restore original display item display data channel, display layer
        for undelete_log in reversed(self.__undelete_logs):
            self.__document_model.undelete_all(undelete_log)
            undelete_log.close()
        self.__undelete_logs.clear()
        old_display_item.display_layers = self.__old_display_layers
        # remove new display item display layer, display data channel, and restore legend state
        new_display_item.remove_display_layer(self.__new_display_layer_index)
        new_display_item.remove_display_data_channel(new_display_item.display_data_channels[self.__new_display_data_channel_index])
        new_display_item.set_display_property("legend_position", self.__new_original_legend_position)


class ChangeDisplayCommand(Undo.UndoableCommand):

    def __init__(self, document_model, display_item: DisplayItem.DisplayItem, *, title: str=None, command_id: str=None, is_mergeable: bool=False, **kwargs):
        super().__init__(title if title else _("Change Display"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__properties = display_item.save_properties()
        self.__value_dict = kwargs
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__display_item_proxy.close()
        self.__display_item_proxy = None
        self.__properties = None
        super().close()

    def perform(self):
        display_item = self.__display_item_proxy.item
        for key, value in self.__value_dict.items():
            display_item.set_display_property(key, value)

    def _get_modified_state(self):
        display_item = self.__display_item_proxy.item
        return display_item.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state):
        display_item = self.__display_item_proxy.item
        display_item.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self):
        display_item = self.__display_item_proxy.item
        properties = self.__properties
        self.__properties = display_item.save_properties()
        display_item.restore_properties(properties)

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeDisplayCommand) and self.command_id and self.command_id == command.command_id and self.__display_item_proxy.item == command.__display_item_proxy.item


class ChangeGraphicsCommand(Undo.UndoableCommand):

    def __init__(self, document_model, display_item, graphics, *, title: str=None, command_id: str=None, is_mergeable: bool=False, **kwargs):
        super().__init__(title if title else _("Change Graphics"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__display_item_proxy = display_item.create_proxy()
        self.__graphic_indexes = [display_item.graphics.index(graphic) for graphic in graphics]
        self.__properties = [graphic.write_to_dict() for graphic in graphics]
        self.__value_dict = kwargs
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__properties = None
        self.__display_item_proxy.close()
        self.__display_item_proxy = None
        self.__graphic_indexes = None
        super().close()

    def perform(self):
        display_item = self.__display_item_proxy.item
        graphics = [display_item.graphics[index] for index in self.__graphic_indexes]
        for key, value in self.__value_dict.items():
            for graphic in graphics:
                setattr(graphic, key, value)

    def _get_modified_state(self):
        display_item = self.__display_item_proxy.item
        return display_item.modified_state, self.__document_model.modified_state

    def _set_modified_state(self, modified_state):
        display_item = self.__display_item_proxy.item
        display_item.modified_state, self.__document_model.modified_state = modified_state

    def _compare_modified_states(self, state1, state2) -> bool:
        # override to allow the undo command to track state; but only use part of the state for comparison
        return state1[0] == state2[0]

    def _undo(self):
        display_item = self.__display_item_proxy.item
        properties = self.__properties
        graphics = [display_item.graphics[index] for index in self.__graphic_indexes]
        self.__properties = [graphic.write_to_dict() for graphic in graphics]
        for graphic, properties in zip(graphics, properties):
            # NOTE: use read_properties_from_dict (read properties only), not read_from_dict (used for initialization).
            graphic.read_properties_from_dict(properties)

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeGraphicsCommand) and self.command_id and self.command_id == command.command_id and self.__display_item_proxy.item == command.__display_item_proxy.item and self.__graphic_indexes == command.__graphic_indexes


class ReplaceDisplayPanelCommand(Undo.UndoableCommand):

    def __init__(self, workspace_controller: "Workspace", old_workspace_layout=None):
        super().__init__("Replace Display Panel")
        self.__workspace_controller = workspace_controller
        self.__old_workspace_layout = old_workspace_layout if old_workspace_layout else workspace_controller.deconstruct()
        self.__new_workspace_layout = None
        self.initialize()

    @property
    def _old_workspace_layout(self):
        return self.__old_workspace_layout

    def _get_modified_state(self):
        return self.__workspace_controller.document_model.modified_state

    def _set_modified_state(self, modified_state) -> None:
        self.__workspace_controller.document_model.modified_state = modified_state

    def _undo(self) -> None:
        self.__new_workspace_layout = self.__workspace_controller.deconstruct()
        self.__workspace_controller.reconstruct(self.__old_workspace_layout)

    def _redo(self) -> None:
        self.__workspace_controller.reconstruct(self.__new_workspace_layout)


class DisplayPanel(CanvasItem.CanvasItemComposition):
    """A canvas item to display a library item. Allows library item to be changed."""

    def __init__(self, document_controller, d, new_uuid: uuid.UUID=None):
        super().__init__()
        self.__weak_document_controller = weakref.ref(document_controller)
        document_controller.register_display_panel(self)
        self.wants_mouse_events = True
        self.uuid = uuid.UUID(d.get("uuid", str(new_uuid if new_uuid else uuid.uuid4())))
        self.__identifier = d.get("identifier", "".join([random.choice(string.ascii_uppercase) for _ in range(2)]))
        self.ui = document_controller.ui

        self.on_contents_changed = None  # useful for writing changes to disk quickly

        self.__content_canvas_item = DisplayPanelOverlayCanvasItem()
        self.__content_canvas_item.wants_mouse_events = True  # only when display_canvas_item is None
        self.__content_canvas_item.focusable = True
        self.__content_canvas_item.on_focus_changed = lambda focused: self.set_focused(focused)
        self.__content_canvas_item.on_context_menu_event = self.__handle_context_menu_event

        self.__header_canvas_item = Panel.HeaderCanvasItem(document_controller, display_close_control=True)

        def header_double_clicked(x, y, modifiers):
            display_item = self.display_item
            if display_item:
                from nion.swift import DisplayEditPopup
                size = Geometry.IntSize(width=400, height=40)
                canvas_bounds = self.__header_canvas_item.canvas_bounds
                pos = Geometry.IntPoint(x=canvas_bounds.center.x - size.width // 2, y=canvas_bounds.top)
                global_pos = self.__header_canvas_item.map_to_global(pos)
                DisplayEditPopup.pose_title_edit_popup(document_controller, display_item, global_pos, size)

        self.__header_canvas_item.on_double_clicked = header_double_clicked

        self.__footer_canvas_item = CanvasItem.CanvasItemComposition()
        self.__footer_canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        self.__footer_canvas_item.sizing.collapsible = True

        self.layout = CanvasItem.CanvasItemColumnLayout()
        self.add_canvas_item(self.__header_canvas_item)
        self.add_canvas_item(self.__content_canvas_item)
        self.add_canvas_item(self.__footer_canvas_item)

        self.__display_panel_id = None

        workspace_controller = self.__document_controller.workspace_controller

        def drag_enter(mime_data):
            display_canvas_item = self.display_canvas_item
            if display_canvas_item and hasattr(display_canvas_item, "get_drop_regions_map"):
                # give the display canvas item a chance to provide drop regions based on the display item being dropped
                display_item = None
                if mime_data.has_format(MimeTypes.DISPLAY_PANEL_MIME_TYPE):
                    display_item, d = MimeTypes.mime_data_get_panel(mime_data, self.document_controller.document_model)
                if not display_item:
                    display_item = MimeTypes.mime_data_get_display_item(mime_data, document_model)
                if display_item:
                    self.__content_canvas_item.drop_regions_map = display_canvas_item.get_drop_regions_map(display_item)
            else:
                self.__content_canvas_item.drop_regions_map = None
            if workspace_controller:
                return workspace_controller.handle_drag_enter(self, mime_data)
            return "ignore"

        def drag_leave():
            if workspace_controller:
                return workspace_controller.handle_drag_leave(self)
            return False

        def drag_move(mime_data, x, y):
            if workspace_controller:
                return workspace_controller.handle_drag_move(self, mime_data, x, y)
            return "ignore"

        def wants_drag_event(mime_data):
            if workspace_controller:
                return workspace_controller.should_handle_drag_for_mime_data(mime_data)
            return False

        def drop(mime_data, region, x, y):
            if workspace_controller:
                return workspace_controller.handle_drop(self, mime_data, region, x, y)
            return "ignore"

        # list to the content_canvas_item messages and pass them along to listeners of this class.
        self.__content_canvas_item.on_drag_enter = drag_enter
        self.__content_canvas_item.on_drag_leave = drag_leave
        self.__content_canvas_item.on_drag_move = drag_move
        self.__content_canvas_item.on_wants_drag_event = wants_drag_event
        self.__content_canvas_item.on_drop = drop
        self.__content_canvas_item.on_key_pressed = self._handle_key_pressed
        self.__content_canvas_item.on_key_released = self._handle_key_released
        self.__content_canvas_item.on_select_all = self.select_all

        def close():
            if len(workspace_controller.display_panels) > 1:
                command = workspace_controller.remove_display_panel(self)
                document_controller.push_undo_command(command)

        self.__header_canvas_item.on_select_pressed = self._select
        self.__header_canvas_item.on_drag_pressed = self.__handle_begin_drag
        self.__header_canvas_item.on_close_clicked = close

        ui = document_controller.ui

        self.__display_item = None
        self.__display_tracker = None
        self.__data_item_reference_changed_event_listener = None
        self.__data_item_reference_changed_task = None

        document_model = self.__document_controller.document_model

        # the display panel controller is an object which adds and controls additional UI on top of this display.
        self.__display_panel_controller = None

        # used for the (optional) display canvas item
        self.__closing_lock = threading.RLock()

        self.__related_icons_canvas_item = RelatedIconsCanvasItem(self.ui, document_model)
        self.__related_icons_canvas_item.on_drag = document_controller.drag

        # the data item panel consists of the data item display canvas item and the related icons canvas item
        self.__display_composition_canvas_item = CanvasItem.CanvasItemComposition()

        self.__display_composition_canvas_item.add_canvas_item(self.__related_icons_canvas_item)

        self.__selection = document_controller.filtered_display_items_model.make_selection()

        self.__selection_changed_event_listener = self.__selection.changed_event.listen(self.__selection_changed)

        def data_list_drag_started(mime_data, thumbnail_data):
            self.content_canvas_item.drag(mime_data, thumbnail_data)

        def key_pressed(key):
            if key.text == "v":
                self.__cycle_display()
                return True
            return False

        def map_display_item_to_display_item_adapter(display_item):
            return DataPanel.DisplayItemAdapter(display_item, ui)

        def unmap_display_item_to_display_item_adapter(display_item_adapter):
            display_item_adapter.close()

        self.__filtered_display_item_adapters_model = ListModel.MappedListModel(container=document_controller.filtered_display_items_model, master_items_key="display_items", items_key="display_item_adapters", map_fn=map_display_item_to_display_item_adapter, unmap_fn=unmap_display_item_to_display_item_adapter)

        def notify_focus_changed():
            self.__document_controller.notify_focused_display_changed(self.__display_item)

        def display_item_adapter_selection_changed(display_item_adapters):
            indexes = set()
            for index, display_item_adapter in enumerate(self.__filtered_display_item_adapters_model.display_item_adapters):
                if display_item_adapter in display_item_adapters:
                    indexes.add(index)
            self.__selection.set_multiple(indexes)
            notify_focus_changed()

        def double_clicked(display_item_adapter):
            display_item_adapter_selection_changed([display_item_adapter])
            self.__cycle_display()
            return True

        def focus_changed(focused):
            if focused:
                notify_focus_changed()

        def delete_display_item_adapters(display_item_adapters):
            document_controller.delete_display_items([display_item_adapter.display_item for display_item_adapter in display_item_adapters])

        self.__horizontal_data_grid_controller = DataPanel.DataGridController(document_controller.event_loop, document_controller.ui, self.__filtered_display_item_adapters_model, self.__selection, direction=GridCanvasItem.Direction.Row, wrap=False)
        self.__horizontal_data_grid_controller.on_display_item_adapter_selection_changed = display_item_adapter_selection_changed
        self.__horizontal_data_grid_controller.on_context_menu_event = self.__handle_context_menu_for_display
        self.__horizontal_data_grid_controller.on_display_item_adapter_double_clicked = double_clicked
        self.__horizontal_data_grid_controller.on_focus_changed = focus_changed
        self.__horizontal_data_grid_controller.on_delete_display_item_adapters = delete_display_item_adapters
        self.__horizontal_data_grid_controller.on_drag_started = data_list_drag_started
        self.__horizontal_data_grid_controller.on_key_pressed = key_pressed

        self.__grid_data_grid_controller = DataPanel.DataGridController(document_controller.event_loop, document_controller.ui, self.__filtered_display_item_adapters_model, self.__selection)
        self.__grid_data_grid_controller.on_display_item_adapter_selection_changed = display_item_adapter_selection_changed
        self.__grid_data_grid_controller.on_context_menu_event = self.__handle_context_menu_for_display
        self.__grid_data_grid_controller.on_display_item_adapter_double_clicked = double_clicked
        self.__grid_data_grid_controller.on_focus_changed = focus_changed
        self.__grid_data_grid_controller.on_delete_display_item_adapters = delete_display_item_adapters
        self.__grid_data_grid_controller.on_drag_started = data_list_drag_started
        self.__grid_data_grid_controller.on_key_pressed = key_pressed

        self.__horizontal_browser_canvas_item = self.__horizontal_data_grid_controller.canvas_item
        self.__horizontal_browser_canvas_item.sizing.set_fixed_height(80)
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

        self.__header_canvas_item.label = "#" + self.identifier

        self.__change_display_panel_content(document_controller, d)

    def close(self):
        self.on_contents_changed = None

        if self.__data_item_reference_changed_task:
            self.__data_item_reference_changed_task.cancel()
            self.__data_item_reference_changed_task = None
        if self.__data_item_reference_changed_event_listener:
            self.__data_item_reference_changed_event_listener.close()
            self.__data_item_reference_changed_event_listener = None

        with self.__closing_lock:  # ensures that display pipeline finishes
            self.set_display_item(None)  # required before destructing display thread
        # NOTE: the enclosing canvas item should be closed AFTER this close is called.
        self.__set_display_panel_controller(None)
        self.__horizontal_data_grid_controller.close()
        self.__horizontal_data_grid_controller = None
        self.__grid_data_grid_controller.close()
        self.__grid_data_grid_controller = None
        self.__selection_changed_event_listener.close()
        self.__selection_changed_event_listener = None
        self.__document_controller.filtered_display_items_model.release_selection(self.__selection)
        self.__filtered_display_item_adapters_model.close()
        self.__filtered_display_item_adapters_model = None
        self.__selection = None

        self.__content_canvas_item.on_focus_changed = None  # only necessary during tests

        # release references
        self.__content_canvas_item = None
        self.__header_canvas_item = None

        self.__document_controller.unregister_display_panel(self)
        self.__weak_document_controller = None
        super().close()

    @property
    def __document_controller(self):
        return self.__weak_document_controller()

    @property
    def document_controller(self):
        return self.__weak_document_controller()

    @property
    def _display_panel_controller_for_test(self):
        return self.__display_panel_controller

    @property
    def display_panel_controller(self):
        return self.__display_panel_controller

    @property
    def _display_canvas_item(self):
        return self.display_canvas_item

    @property
    def _display_item_adapters_for_test(self):
        return self.__filtered_display_item_adapters_model.display_item_adapters

    @property
    def _related_icons_canvas_item(self):
        return self.__related_icons_canvas_item

    @property
    def header_canvas_item(self):
        return self.__header_canvas_item

    @property
    def content_canvas_item(self):
        return self.__content_canvas_item

    @property
    def footer_canvas_item(self):
        return self.__footer_canvas_item

    @property
    def identifier(self) -> str:
        return self.__identifier

    @property
    def display_canvas_item(self):
        return self.__display_tracker.display_canvas_item if self.__display_tracker else None

    @property
    def display_panel_type(self):
        return self._display_panel_type

    @property
    def display_panel_id(self):
        return self.__display_panel_id

    @property
    def data_item(self) -> DataItem.DataItem:
        return self.__display_item.data_item if self.__display_item else None

    @property
    def display_item(self) -> DisplayItem.DisplayItem:
        return self.__display_item

    def save_contents(self):
        d = dict()
        if self.display_panel_id:
            d["display_panel_id"] = str(self.display_panel_id)
        if self.__display_panel_controller:
            d["controller_type"] = self.__display_panel_controller.type
            self.__display_panel_controller.save(d)
        if self.__display_item:
            d["display_item_specifier"] = self.__display_item.project.create_specifier(self.__display_item, allow_partial=False).write()
        if self.__display_panel_controller is None and self.__horizontal_browser_canvas_item.visible:
            d["browser_type"] = "horizontal"
        if self.__display_panel_controller is None and self.__grid_browser_canvas_item.visible:
            d["browser_type"] = "grid"
        d["uuid"] = str(self.uuid)
        d["identifier"] = self.identifier
        return d

    def restore_contents(self, d):
        try:
            display_panel_id = d.get("display_panel_id")
            if display_panel_id:
                self.__display_panel_id = display_panel_id
            self.__identifier = d.get("identifier", self.__identifier)
            controller_type = d.get("controller_type")
            self.__set_display_panel_controller(DisplayPanelManager().make_display_panel_controller(controller_type, self, d))
            if not self.__display_panel_controller:
                display_item = None
                if "display_item_specifier" in d:
                    display_item_specifier = Persistence.PersistentObjectSpecifier.read(d["display_item_specifier"])
                    display_item = self.document_controller.document_model.resolve_item_specifier(display_item_specifier)
                self.set_display_item(display_item)
                self.__update_selection_to_display()
                if d.get("browser_type") == "horizontal":
                    self.__switch_to_horizontal_browser()
                elif d.get("browser_type") == "grid":
                    self.__switch_to_grid_browser()
                else:
                    self.__switch_to_no_browser()
            self.__header_canvas_item.label = "#" + self.identifier
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
    def _display_panel_type(self):
        if self.__horizontal_browser_canvas_item.visible:
            return "horizontal"
        elif self.__grid_browser_canvas_item.visible:
            return "grid"
        elif self.__display_item:
            return "data_item"
        else:
            return "empty"

    def handle_drop_display_item(self, region, display_item) -> bool:
        if region == "plus":
            data_item = display_item.data_item if display_item else None
            if data_item:
                command = AppendDisplayDataChannelCommand(self.__document_controller.document_model, self.display_item, data_item)
                command.perform()
                self.__document_controller.push_undo_command(command)
                return True
        return False

    def _drag_finished(self, document_controller, action):
        if action == "move" and document_controller.replaced_display_panel_content is not None:
            d = document_controller.replaced_display_panel_content
            self.__change_display_panel_content(document_controller, d)
            last_command = document_controller.last_undo_command
            if isinstance(last_command, ReplaceDisplayPanelCommand):
                command = ReplaceDisplayPanelCommand(document_controller.workspace_controller, last_command._old_workspace_layout)
                document_controller.pop_undo_command()
                document_controller.push_undo_command(command)
        document_controller.replaced_display_panel_content = None

    def image_clicked(self, image_position, modifiers):
        return DisplayPanelManager().image_display_clicked(self, self.__display_item, image_position, modifiers)

    def image_mouse_pressed(self, image_position, modifiers):
        return DisplayPanelManager().image_display_mouse_pressed(self, self.__display_item, image_position, modifiers)

    def image_mouse_released(self, image_position, modifiers):
        return DisplayPanelManager().image_display_mouse_released(self, self.__display_item, image_position, modifiers)

    def image_mouse_position_changed(self, image_position, modifiers):
        return DisplayPanelManager().image_display_mouse_position_changed(self, self.__display_item, image_position, modifiers)

    def image_panel_get_font_metrics(self, font, text):
        return self.ui.get_font_metrics(font, text)

    def __set_display_panel_controller(self, display_panel_controller):
        if self.__display_panel_controller:
            self.__display_panel_controller.close()
            self.__display_panel_controller = None
        self.__display_panel_controller = display_panel_controller
        if not display_panel_controller:
            self.header_canvas_item.reset_header_colors()
        if self.__display_panel_controller:
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

        def handle_data_item_reference_changed():
            if self.__data_item_reference_changed_task:
                self.__data_item_reference_changed_task.cancel()
                self.__data_item_reference_changed_task = None

            async def update_display_item():
                self.set_display_item(self.document_controller.document_model.get_any_display_item_for_data_item(data_item_reference.data_item))

            self.__data_item_reference_changed_task = self.document_controller.event_loop.create_task(update_display_item())

        if data_item_reference:
            self.__data_item_reference_changed_event_listener = data_item_reference.data_item_reference_changed_event.listen(handle_data_item_reference_changed)
            self.set_display_item(self.document_controller.document_model.get_any_display_item_for_data_item(data_item_reference.data_item))

    def set_display_panel_data_item(self, data_item: DataItem.DataItem, detect_controller: bool=False) -> None:
        display_item = self.document_controller.document_model.get_any_display_item_for_data_item(data_item)
        if display_item:
            self.set_display_panel_display_item(display_item, detect_controller)

    def set_display_panel_display_item(self, display_item: DisplayItem.DisplayItem, detect_controller: bool=False) -> None:
        if display_item:
            d = {"type": "image", "display_item_specifier": display_item.project.create_specifier(display_item, allow_partial=False).write()}
            if detect_controller:
                data_item = display_item.data_item
                if display_item == self.document_controller.document_model.get_any_display_item_for_data_item(data_item):
                    d2 = DisplayPanelManager().detect_controller(self.__document_controller.document_model, data_item)
                    if d2:
                        d.update(d2)
        else:
            d = {"type": "image"}
        self.change_display_panel_content(d)

    def change_display_panel_content(self, d):
        assert self.__document_controller is not None
        self.__change_display_panel_content(self.__document_controller, d)

    def __change_display_panel_content(self, document_controller, d):
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

        if is_selected:
            document_controller.notify_focused_display_changed(self.__display_item)

        if callable(self.on_contents_changed):
            self.on_contents_changed()

    # sets the data item that this panel displays
    # not thread safe
    def set_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        # listen for changes to display content and parameters, metadata, or the selection
        # changes to the underlying data will trigger changes in the display content

        did_display_change = self.__display_item != display_item

        if did_display_change:

            # remove any existing display canvas item
            if len(self.__display_composition_canvas_item.canvas_items) > 1:
                self.__display_composition_canvas_item.remove_canvas_item(self.__display_composition_canvas_item.canvas_items[0])

            old_display_tracker = self.__display_tracker
            self.__display_tracker = None

            if display_item:
                def clear_display() -> None:
                    self.set_display_item(None)

                def handle_title_changed(title: str) -> None:
                    self.header_canvas_item.title = title

                def replace_display_canvas_item(old_display_canvas_item, new_display_canvas_item):
                    self.__display_composition_canvas_item.replace_canvas_item(old_display_canvas_item, new_display_canvas_item)

                self.__display_tracker = DisplayTracker(display_item, self.ui.get_font_metrics, self, self.__document_controller.event_loop, True)
                self.__display_tracker.on_clear_display = clear_display
                self.__display_tracker.on_title_changed = handle_title_changed
                self.__display_tracker.on_replace_display_canvas_item = replace_display_canvas_item

                self.__display_composition_canvas_item.insert_canvas_item(0, self.__display_tracker.display_canvas_item)

            if old_display_tracker:
                old_display_tracker.close()

        self.__display_item = display_item

        # ensure the graphics get updated by triggering the graphics changed event.
        if self.__display_item:
            self.__display_item.graphics_changed_event.fire(self.__display_item.graphic_selection)

        # update the related icons canvas item with the new display.
        self.__related_icons_canvas_item.set_display_item(display_item)

        self.header_canvas_item.title = display_item.displayed_title if display_item else None

        # update want mouse and selected status.
        if self.__display_composition_canvas_item:  # may be closed
            self.__display_composition_canvas_item.wants_mouse_events = self.display_canvas_item is None
            self.__display_composition_canvas_item.selected = display_item and self._is_selected()

        if did_display_change:
            if self._is_focused:
                self.__document_controller.notify_focused_display_changed(self.__display_item)

    def _select(self):
        self.content_canvas_item.request_focus()

    # handle selection. selection means that the display panel is the most recent
    # item to have focus within the workspace, although it can be selected without
    # having focus. this can happen, for instance, when the user switches focus
    # to the data panel.

    def set_selected(self, selected):
        if self.__content_canvas_item:  # may be closed
            self.__content_canvas_item.selected = selected

    def _is_selected(self):
        """ Used for testing. """
        return self.__content_canvas_item.selected

    # this message comes from the canvas items via the on_focus_changed when their focus changes
    def set_focused(self, focused):
        self.__content_canvas_item.focused = focused
        if focused:
            self.__document_controller.selected_display_panel = self  # MARK
            self.__document_controller.notify_focused_display_changed(self.__display_item)

    def _is_focused(self):
        """ Used for testing. """
        return self.__content_canvas_item.focused

    def request_focus(self):
        self.__content_canvas_item.request_focus()

    @property
    def is_result_panel(self):
        return self._is_result_panel

    # this gets called when the user initiates a drag in the drag control to move the panel around
    def __handle_begin_drag(self):
        mime_data = self.ui.create_mime_data()
        if self.__display_item:
            MimeTypes.mime_data_put_display_item(mime_data, self.__display_item)
        MimeTypes.mime_data_put_panel(mime_data, None, self.save_contents())
        thumbnail_data = Thumbnails.ThumbnailManager().thumbnail_data_for_display_item(self.__display_item)
        self.__begin_drag(mime_data, thumbnail_data)

    def __begin_drag(self, mime_data, thumbnail_data):
        self.drag(mime_data, thumbnail_data, drag_finished_fn=functools.partial(self._drag_finished, self.__document_controller))

    # from the canvas item directly. dispatches to the display canvas item. if the display canvas item
    # doesn't handle it, gives the display controller a chance to handle it.
    def _handle_key_pressed(self, key):
        display_canvas_item = self.display_canvas_item
        if display_canvas_item and display_canvas_item.key_pressed(key):
            return True
        if self.__display_panel_controller and self.__display_panel_controller.key_pressed(key):
            return True
        if self.__display_panel_controller is None:
            # cycle views is only valid if there is no display_panel_controller
            if key.text == "v":
                self.__cycle_display()
                return True
        return DisplayPanelManager().key_pressed(self, key)

    def __cycle_display(self):
        # the second part of the if statement below handles the case where the data item has been changed by
        # the user so the cycle should go back to the main display.
        if self.__display_composition_canvas_item.visible and (not self.__horizontal_browser_canvas_item.visible or not self.__display_changed):
            if self.__horizontal_browser_canvas_item.visible:
                self.__switch_to_grid_browser()
                self.__update_selection_to_display()
                self.__grid_data_grid_controller.icon_view_canvas_item.request_focus()
            else:
                self.__switch_to_horizontal_browser()
                self.__update_selection_to_display()
                self.__horizontal_data_grid_controller.icon_view_canvas_item.request_focus()
        else:
            self.__switch_to_no_browser()
            self._select()
        self.__display_changed = False

    def __update_selection_to_display(self):
        display_items = [display_item_adapter.display_item for display_item_adapter in self.__filtered_display_item_adapters_model.display_item_adapters]
        if self.__display_item in display_items:
            self.__selection.set(display_items.index(self.__display_item))
            self.__horizontal_data_grid_controller.make_selection_visible()
            self.__grid_data_grid_controller.make_selection_visible()

    def __switch_to_no_browser(self):
        self.__display_composition_canvas_item.visible = True
        self.__horizontal_browser_canvas_item.visible = False
        self.__grid_browser_canvas_item.visible = False

    def __switch_to_horizontal_browser(self):
        self.__display_composition_canvas_item.visible = True
        self.__horizontal_browser_canvas_item.visible = True
        self.__grid_browser_canvas_item.visible = False

    def __switch_to_grid_browser(self):
        self.__display_composition_canvas_item.visible = False
        self.__horizontal_browser_canvas_item.visible = False
        self.__grid_browser_canvas_item.visible = True

    # from the canvas item directly. dispatches to the display canvas item. if the display canvas item
    # doesn't handle it, gives the display controller a chance to handle it.
    def _handle_key_released(self, key):
        display_canvas_item = self.display_canvas_item
        if display_canvas_item and display_canvas_item.key_released(key):
            return True
        if self.__display_panel_controller and self.__display_panel_controller.key_released(key):
            return True
        return DisplayPanelManager().key_released(self, key)

    def show_context_menu(self, menu, gx, gy):

        workspace_controller = self.__document_controller.workspace_controller

        def split_vertical():
            if workspace_controller:
                command = workspace_controller.insert_display_panel(self, "bottom")
                self.__document_controller.push_undo_command(command)

        def split_horizontal():
            if workspace_controller:
                command = workspace_controller.insert_display_panel(self, "right")
                self.__document_controller.push_undo_command(command)

        menu.add_separator()
        menu.add_menu_item(_("Split Into Top and Bottom"), split_vertical)
        menu.add_menu_item(_("Split Into Left and Right"), split_horizontal)
        menu.add_separator()
        DisplayPanelManager().build_menu(menu, self.__document_controller, self)
        menu.popup(gx, gy)
        return True

    def __handle_context_menu_event(self, x, y, gx, gy):
        menu = self.__document_controller.create_context_menu()
        return self.show_context_menu(menu, gx, gy)

    def __handle_context_menu_for_display(self, display_item, x, y, gx, gy):
        menu = self.__document_controller.create_context_menu_for_display(display_item, use_selection=True)
        return self.show_context_menu(menu, gx, gy)

    def perform_action(self, fn, *args, **keywords):
        display_canvas_item = self.display_canvas_item
        target = display_canvas_item
        if hasattr(target, fn):
            getattr(target, fn)(*args, **keywords)

    def select_all(self):
        if self.__display_item:
            self.__display_item.graphic_selection.add_range(range(len(self.__display_item.graphics)))
        return True

    def __selection_changed(self):
        if len(self.__selection.indexes) == 1:
            index = list(self.__selection.indexes)[0]
            display_item = self.__filtered_display_item_adapters_model.display_item_adapters[index].display_item
        else:
            display_item = None
        self.set_display_item(display_item)
        self.__display_changed = True

    # messages from the display canvas item

    def add_index_to_selection(self, index):
        self.__display_item.graphic_selection.add(index)

    def remove_index_from_selection(self, index):
        self.__display_item.graphic_selection.remove(index)

    def set_selection(self, index):
        self.__display_item.graphic_selection.set(index)

    def clear_selection(self):
        self.__display_item.graphic_selection.clear()

    def add_and_select_region(self, region: Graphics.Graphic) -> Undo.UndoableCommand:
        command = InsertGraphicsCommand(self.__document_controller, self.__display_item, [region])
        command.perform()
        # hack to select it. it will be the last item.
        self.__display_item.graphic_selection.set(len(self.__display_item.graphics) - 1)
        return command

    def nudge_selected_graphics(self, mapping, delta):
        all_graphics = self.__display_item.graphics
        graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if self.__display_item.graphic_selection.contains(graphic_index)]
        if graphics:
            command = ChangeGraphicsCommand(self.__document_controller.document_model, self.__display_item, graphics, command_id="nudge", is_mergeable=True)
            for graphic in graphics:
                graphic.nudge(mapping, delta)
            self.__document_controller.push_undo_command(command)

    def adjust_graphics(self, widget_mapping, graphic_drag_items, graphic_drag_part, graphic_part_data, graphic_drag_start_pos, pos, modifiers):
        with self.__display_item.display_item_changes():
            for graphic in graphic_drag_items:
                index = self.__display_item.graphics.index(graphic)
                part_data = (graphic_drag_part, ) + graphic_part_data[index]
                graphic.adjust_part(widget_mapping, graphic_drag_start_pos, Geometry.IntPoint.make(pos), part_data, modifiers)

    def nudge_slice(self, delta) -> None:
        display_data_channel = self.__display_item.display_data_channel if self.__display_item else None
        if display_data_channel:
            data_item = display_data_channel.data_item
            if data_item.is_sequence:
                mx = data_item.dimensional_shape[0] - 1  # sequence_index
                value = display_data_channel.sequence_index + delta
                if 0 <= value <= mx:
                    property_name = "sequence_index"
                    command = ChangeDisplayDataChannelCommand(self.__document_controller.document_model, display_data_channel, title=_("Change Display"), command_id="change_display_" + property_name, is_mergeable=True, **{property_name: value})
                    command.perform()
                    self.__document_controller.push_undo_command(command)
            if data_item.is_collection and data_item.collection_dimension_count == 1:
                # it's not a sequence at this point
                mx = data_item.dimensional_shape[0] - 1  # sequence_index
                value = display_data_channel.collection_index[0] + delta
                if 0 <= value <= mx:
                    property_name = "collection_index"
                    command = ChangeDisplayDataChannelCommand(self.__document_controller.document_model, display_data_channel, title=_("Change Display"), command_id="change_display_" + property_name, is_mergeable=True, **{property_name: (value, )})
                    command.perform()
                    self.__document_controller.push_undo_command(command)

    @property
    def tool_mode(self):
        return self.__document_controller.tool_mode

    @tool_mode.setter
    def tool_mode(self, value):
        self.__document_controller.tool_mode = value

    def show_display_context_menu(self, gx, gy) -> bool:
        document_controller = self.__document_controller
        menu = document_controller.create_context_menu_for_display(self.__display_item, container=document_controller.document_model, use_selection=False)
        return self.show_context_menu(menu, gx, gy)

    def begin_mouse_tracking(self):
        self.__mouse_tracking_transaction = self.__document_controller.document_model.begin_display_item_transaction(self.__display_item)

    def create_mime_data(self) -> UserInterface.MimeData:
        return self.ui.create_mime_data()

    def create_rgba_image(self, drawing_context: DrawingContext.DrawingContext, width: int, height: int):
        return self.ui.create_rgba_image(drawing_context, width, height)

    def get_display_item(self) -> DisplayItem.DisplayItem:
        return self.display_item

    def get_document_model(self) -> DocumentModel.DocumentModel:
        return self.document_controller.document_model

    def end_mouse_tracking(self, undo_command):
        self.__mouse_tracking_transaction.close()
        self.__mouse_tracking_transaction = None
        if undo_command:
            self.__document_controller.push_undo_command(undo_command)

    def delete_key_pressed(self):
        self.__document_controller.remove_selected_graphics()

    def enter_key_pressed(self):
        command = ChangeDisplayCommand(self.__document_controller.document_model, self.__display_item)
        result = self.display_canvas_item.handle_auto_display()
        if result:
            self.__document_controller.push_undo_command(command)
        else:
            command.close()
        return result

    def cursor_changed(self, pos):
        position_text, value_text = str(), str()
        try:
            if pos is not None:
                position_text, value_text = self.__display_item.get_value_and_position_text(self.__display_item.display_data_channel, pos)
        except Exception as e:
            global _test_log_exceptions
            if _test_log_exceptions:
                import traceback
                traceback.print_exc()
        position_and_value_text = []
        if position_text:
            position_and_value_text.append(_("Position: ") + position_text)
        if value_text:
            position_and_value_text.append(_("Value: ") + value_text)
        if len(position_text) == 0:
            self.__document_controller.cursor_changed(None)
        else:
            self.__document_controller.cursor_changed(position_and_value_text)

    def drag_graphics(self, graphics):
        display_item = self.display_item
        if display_item:
            mime_data = self.ui.create_mime_data()
            MimeTypes.mime_data_put_data_source(mime_data, display_item, graphics[0] if len(graphics) == 1 else None)
            thumbnail_data = Thumbnails.ThumbnailManager().thumbnail_data_for_display_item(display_item)
            self.__begin_drag(mime_data, thumbnail_data)

    def update_display_properties(self, display_properties):
        for key, value in iter(display_properties.items()):
            self.__display_item.set_display_property(key, value)

    def update_display_data_channel_properties(self, display_data_channel_properties: typing.Mapping) -> None:
        display_data_channel = self.__display_item.display_data_channel if self.__display_item else None
        if display_data_channel:
            for key, value in iter(display_data_channel_properties.items()):
                setattr(display_data_channel, key, value)

    def create_insert_graphics_command(self, graphics: typing.Sequence[Graphics.Graphic]) -> InsertGraphicsCommand:
        return InsertGraphicsCommand(self.__document_controller, self.__display_item, list(), existing_graphics=graphics)

    def create_change_display_command(self, *, command_id: str=None, is_mergeable: bool=False) -> ChangeDisplayCommand:
        return ChangeDisplayCommand(self.__document_controller.document_model, self.__display_item, command_id=command_id, is_mergeable=is_mergeable)

    def create_move_display_layer_command(self, display_item: DisplayItem.DisplayItem, src_index: int, target_index: int) -> MoveDisplayLayerCommand:
        return MoveDisplayLayerCommand(self.__document_controller.document_model, display_item, src_index, self.__display_item, target_index)

    def create_change_display_item_property_command(self, display_item: DisplayItem.DisplayItem, property_name: str, value) -> Inspector.ChangeDisplayItemPropertyCommand:
        return Inspector.ChangeDisplayItemPropertyCommand(self.__document_controller.document_model, display_item, property_name, value)

    def create_change_graphics_command(self) -> ChangeGraphicsCommand:
        all_graphics = self.__display_item.graphics
        graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if self.__display_item.graphic_selection.contains(graphic_index)]
        return ChangeGraphicsCommand(self.__document_controller.document_model, self.__display_item, graphics)

    def push_undo_command(self, command: Undo.UndoableCommand) -> None:
        self.__document_controller.push_undo_command(command)

    def create_rectangle(self, pos):
        bounds = tuple(pos), (0, 0)
        self.__display_item.graphic_selection.clear()
        region = Graphics.RectangleGraphic()
        region.bounds = bounds
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_ellipse(self, pos):
        bounds = tuple(pos), (0, 0)
        self.__display_item.graphic_selection.clear()
        region = Graphics.EllipseGraphic()
        region.bounds = bounds
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_line(self, pos):
        pos = tuple(pos)
        self.__display_item.graphic_selection.clear()
        region = Graphics.LineGraphic()
        region.start = pos
        region.end = pos
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_point(self, pos):
        pos = tuple(pos)
        self.__display_item.graphic_selection.clear()
        region = Graphics.PointGraphic()
        region.position = pos
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_line_profile(self, pos):
        display_item = self.__display_item
        if display_item:
            pos = tuple(pos)
            self.__display_item.graphic_selection.clear()
            line_profile_region = Graphics.LineProfileGraphic()
            line_profile_region.start = pos
            line_profile_region.end = pos
            self.__display_item.add_graphic(line_profile_region)
            document_controller = self.__document_controller
            document_model = document_controller.document_model
            line_profile_data_item = document_model.get_line_profile_new(display_item, None, line_profile_region)
            line_profile_display_item = document_model.get_display_item_for_data_item(line_profile_data_item)
            document_controller.show_display_item(line_profile_display_item)
            return line_profile_region
        return None

    def create_spot(self, pos):
        data_shape = self.__display_item.data_item.data_shape
        mapping = ImageCanvasItem.ImageCanvasItemMapping(data_shape, None, self.__display_item.datum_calibrations)
        bounds = Geometry.FloatRect.from_center_and_size(pos - mapping.calibrated_origin_image_norm, Geometry.FloatSize())
        self.__display_item.graphic_selection.clear()
        region = Graphics.SpotGraphic()
        region.bounds = bounds
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_wedge(self, angle):
        self.__display_item.graphic_selection.clear()
        region = Graphics.WedgeGraphic()
        region.end_angle = angle
        region.start_angle = angle + math.pi
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_ring(self, radius):
        self.__display_item.graphic_selection.clear()
        region = Graphics.RingGraphic()
        region.radius_1 = radius
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region

    def create_lattice(self, u_pos):
        data_shape = self.__display_item.data_item.data_shape
        mapping = ImageCanvasItem.ImageCanvasItemMapping(data_shape, None, self.__display_item.datum_calibrations)
        self.__display_item.graphic_selection.clear()
        region = Graphics.LatticeGraphic()
        region.u_pos = u_pos - mapping.calibrated_origin_image_norm
        self.__display_item.add_graphic(region)
        self.__display_item.graphic_selection.set(self.__display_item.graphics.index(region))
        return region


class DisplayPanelManager(metaclass=Utility.Singleton):
    """ Acts as a broker for significant events occurring regarding display panels. Listeners can attach themselves to
    this object and receive messages regarding display panels. For instance, when the user presses a key on an display
    panel that isn't handled directly, listeners will be advised of this event. """

    def __init__(self):
        super().__init__()
        self.__display_panel_controllers = dict()  # maps controller_type to make_fn
        self.__display_controller_factories = dict()
        self.key_pressed_event = Event.Event()
        self.key_released_event = Event.Event()
        self.image_display_clicked_event = Event.Event()
        self.image_display_mouse_pressed_event = Event.Event()
        self.image_display_mouse_released_event = Event.Event()
        self.image_display_mouse_position_changed_event = Event.Event()

    # events from the image panels
    def key_pressed(self, display_panel, key):
        return self.key_pressed_event.fire_any(display_panel, key)

    # events from the image panels
    def key_released(self, display_panel, key):
        return self.key_released_event.fire_any(display_panel, key)

    def image_display_clicked(self, display_panel, display_item, image_position, modifiers):
        return self.image_display_clicked_event.fire_any(display_panel, display_item, image_position, modifiers)

    def image_display_mouse_pressed(self, display_panel, display_item, image_position, modifiers):
        return self.image_display_mouse_pressed_event.fire_any(display_panel, display_item, image_position, modifiers)

    def image_display_mouse_released(self, display_panel, display_item, image_position, modifiers):
        return self.image_display_mouse_released_event.fire_any(display_panel, display_item, image_position, modifiers)

    def image_display_mouse_position_changed(self, display_panel, display_item, image_position, modifiers):
        return self.image_display_mouse_position_changed_event.fire_any(display_panel, display_item, image_position, modifiers)

    def register_display_panel_controller_factory(self, factory_id, factory):
        assert factory_id not in self.__display_controller_factories
        self.__display_controller_factories[factory_id] = factory

    def unregister_display_panel_controller_factory(self, factory_id):
        assert factory_id in self.__display_controller_factories
        del self.__display_controller_factories[factory_id]

    def detect_controller(self, document_model, data_item: DataItem.DataItem) -> dict:
        priority = 0
        result = None
        for factory in self.__display_controller_factories.values():
            controller_type = factory.match(document_model, data_item)
            if controller_type and factory.priority > priority:
                priority = factory.priority
                result = controller_type
        return result

    def make_display_panel_controller(self, controller_type, display_panel, d):
        for factory in self.__display_controller_factories.values():
            display_panel_controller = factory.make_new(controller_type, display_panel, d)
            if display_panel_controller:
                return display_panel_controller
        return None

    def switch_to_display_content(self, document_controller, display_panel: DisplayPanel, display_panel_type, display_item: DisplayItem.DisplayItem = None):
        d = {"type": "image", "display-panel-type": display_panel_type}
        if display_item and display_panel_type != "empty-display-panel":
            d["display_item_specifier"] = display_item.project.create_specifier(display_item, allow_partial=False).write()
        command = ReplaceDisplayPanelCommand(document_controller.workspace_controller)
        display_panel.change_display_panel_content(d)
        document_controller.push_undo_command(command)

    def build_menu(self, display_type_menu, document_controller, display_panel):
        """Build the dynamic menu for the selected display panel.

        The user accesses this menu by right-clicking on the display panel.

        The basic menu items are to an empty display panel or a browser display panel.

        After that, each display controller factory is given a chance to add to the menu. The display
        controllers (for instance, a scan acquisition controller), may add its own menu items.
        """
        dynamic_live_actions = list()

        def switch_to_display_content(display_panel_type):
            self.switch_to_display_content(document_controller, display_panel, display_panel_type, display_panel.display_item)

        empty_action = display_type_menu.add_menu_item(_("Clear Display Panel"), functools.partial(switch_to_display_content, "empty-display-panel"))
        display_type_menu.add_separator()

        data_item_display_action = display_type_menu.add_menu_item(_("Display Item"), functools.partial(switch_to_display_content, "data-display-panel"))
        thumbnail_browser_action = display_type_menu.add_menu_item(_("Thumbnail Browser"), functools.partial(switch_to_display_content, "thumbnail-browser-display-panel"))
        grid_browser_action = display_type_menu.add_menu_item(_("Grid Browser"), functools.partial(switch_to_display_content, "browser-display-panel"))
        display_type_menu.add_separator()

        display_panel_type = display_panel.display_panel_type

        empty_action.checked = display_panel_type == "empty" and display_panel.display_panel_controller is None
        data_item_display_action.checked = display_panel_type == "data_item"
        thumbnail_browser_action.checked = display_panel_type == "horizontal"
        grid_browser_action.checked = display_panel_type == "grid"

        dynamic_live_actions.append(empty_action)
        dynamic_live_actions.append(data_item_display_action)
        dynamic_live_actions.append(thumbnail_browser_action)
        dynamic_live_actions.append(grid_browser_action)

        for factory in self.__display_controller_factories.values():
            dynamic_live_actions.extend(factory.build_menu(display_type_menu, display_panel))

        return dynamic_live_actions


def preview(get_font_metrics_fn, display_item: DisplayItem.DisplayItem, width: int, height: int) -> typing.Tuple[DrawingContext.DrawingContext, Geometry.IntSize]:
    drawing_context = DrawingContext.DrawingContext()
    shape = Geometry.IntSize()
    display_values_list = [display_data_channel.get_calculated_display_values(True) for display_data_channel in display_item.display_data_channels]
    display_canvas_item = create_display_canvas_item(display_item, get_font_metrics_fn, None, None, draw_background=False)
    if display_canvas_item:
        with contextlib.closing(display_canvas_item):
            display_calibration_info = DisplayItem.DisplayCalibrationInfo(display_item)
            display_canvas_item.update_display_values(display_values_list)
            display_canvas_item.update_display_properties(display_calibration_info, display_item.display_properties, display_item.display_layers)
            display_canvas_item.update_graphics_coordinate_system(display_item.graphics, DisplayItem.GraphicSelection(), display_calibration_info)
            with drawing_context.saver():
                frame_width, frame_height = width, int(width / display_canvas_item.default_aspect_ratio)
                display_canvas_item.repaint_immediate(drawing_context, Geometry.IntSize(height=frame_height, width=frame_width))
                shape = Geometry.IntSize(height=frame_height, width=frame_width)
    return drawing_context, shape
