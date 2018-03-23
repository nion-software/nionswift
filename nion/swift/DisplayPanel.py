# standard libraries
import contextlib
import functools
import gettext
import json
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
from nion.swift import Panel
from nion.swift import Thumbnails
from nion.swift import Undo
from nion.swift.model import DataItem
from nion.swift.model import Display
from nion.swift.model import Graphics
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import GridCanvasItem
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel


_ = gettext.gettext


DISPLAY_PANEL_MIME_TYPE = "text/vnd.nion.display_panel_type"

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
        self.__drop_region = "none"
        self.__focused = False
        self.__selected = False
        self.__selected_style = "#CCC"  # TODO: platform dependent
        self.__focused_style = "#3876D6"  # TODO: platform dependent
        self.on_context_menu_event = None
        self.on_drag_enter = None
        self.on_drag_leave = None
        self.on_drag_move = None
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

    def __set_drop_region(self, drop_region):
        if self.__drop_region != drop_region:
            self.__drop_region = drop_region
            self.update()

    def _repaint(self, drawing_context):
        super()._repaint(drawing_context)

        # canvas size
        canvas_width = self.canvas_size[1]
        canvas_height = self.canvas_size[0]

        if self.__drop_region != "none":
            with drawing_context.saver():
                drawing_context.begin_path()
                if self.__drop_region == "left":
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

    def drag_enter(self, mime_data):
        self.__set_drop_region("none")
        if self.on_drag_enter:
            self.on_drag_enter(mime_data)
        return "ignore"

    def drag_leave(self):
        self.__set_drop_region("none")
        if self.on_drag_leave:
            self.on_drag_leave()
        return False

    def drag_move(self, mime_data, x, y):
        if self.on_drag_move:
            result = self.on_drag_move(mime_data, x, y)
            if result != "ignore":
                canvas_size = Geometry.IntSize.make(self.canvas_size)
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


def create_display_canvas_item(display_type: str, get_font_metrics_fn, delegate, event_loop, draw_background: bool=True):
    if display_type == "line_plot":
        return LinePlotCanvasItem.LinePlotCanvasItem(get_font_metrics_fn, delegate, event_loop, draw_background)
    elif display_type == "image":
        return ImageCanvasItem.ImageCanvasItem(get_font_metrics_fn, delegate, event_loop, draw_background)
    elif display_type == "display_script":
        return DisplayScriptCanvasItem.DisplayScriptCanvasItem(get_font_metrics_fn, delegate, event_loop, draw_background)
    elif display_type == "composite-image":
        return CompositeDisplayCanvasItem(get_font_metrics_fn, delegate, event_loop, draw_background)
    else:
        return MissingDataCanvasItem(delegate)


def is_valid_display_type(display_type: str) -> bool:
    return display_type in ("image", "line_plot", "display_script")


class DisplayTypeMonitor:
    """Monitor a display for changes to the display type.

    Provides the display_type_changed(display_type) event.

    Provides the display_type r/o property.
    """

    def __init__(self, display):
        self.display_type_changed_event = Event.Event()
        self.__display_changed_event_listener = None
        self.__display_type = None
        self.__first = True  # handle case where there is no data, so display_type is always None and doesn't change
        if display:
            self.__display_changed_event_listener = display.display_changed_event.listen(functools.partial(self.__update_display_type, display))
        self.__update_display_type(display)

    def close(self):
        if self.__display_changed_event_listener:
            self.__display_changed_event_listener.close()
            self.__display_changed_event_listener = None

    def __update_display_type(self, display):
        display_type = display.actual_display_type if display else None
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
        self.__display = None

    def close(self):
        self.set_display(None)
        super().close()

    @property
    def _source_thumbnails(self):
        return self.__source_thumbnails

    @property
    def _dependent_thumbnails(self):
        return self.__dependent_thumbnails

    def __related_items_changed(self, display, source_displays, dependent_displays):
        if display == self.__display:
            self.__source_thumbnails.remove_all_canvas_items()
            self.__dependent_thumbnails.remove_all_canvas_items()
            for source_display in source_displays:
                thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(self.ui, display=source_display)
                thumbnail_canvas_item = DataItemThumbnailWidget.ThumbnailCanvasItem(self.ui, thumbnail_source, self.__thumbnail_size)
                thumbnail_canvas_item.on_drag = self.on_drag
                self.__source_thumbnails.add_canvas_item(thumbnail_canvas_item)
            for dependent_display in dependent_displays:
                thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(self.ui, display=dependent_display)
                thumbnail_canvas_item = DataItemThumbnailWidget.ThumbnailCanvasItem(self.ui, thumbnail_source, self.__thumbnail_size)
                thumbnail_canvas_item.on_drag = self.on_drag
                self.__dependent_thumbnails.add_canvas_item(thumbnail_canvas_item)

    def set_display(self, display: typing.Optional[Display.Display]) -> None:
        if self.__display:
            self.__related_items_changed_listener.close()
            self.__related_items_changed_listener = None

        self.__display = display

        if self.__display:
            self.__related_items_changed_listener = self.__document_model.related_items_changed.listen(self.__related_items_changed)
            source_displays = self.__document_model.get_source_displays(self.__display)
            dependent_displays = self.__document_model.get_dependent_displays(self.__display)
            self.__related_items_changed(self.__display, source_displays, dependent_displays)
        else:
            self.__related_items_changed(self.__display, [], [])


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

    def display_inserted(self, display, index):
        pass

    def display_removed(self, display, index):
        pass

    def display_rgba_changed(self, display, display_values):
        pass

    def display_data_and_metadata_changed(self, display, display_values):
        pass

    def update_display_values(self, display, display_values):
        pass

    def update_regions(self, display, graphic_selection):
        pass

    def handle_auto_display(self, display) -> bool:
        # enter key has been pressed
        return False

    def _repaint(self, drawing_context):
        # canvas size
        canvas_width = self.canvas_size[1]
        canvas_height = self.canvas_size[0]
        drawing_context.save()
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
        drawing_context.restore()


class CompositeDisplayCanvasItem(CanvasItem.LayerCanvasItem):
    """ Canvas item to draw background_color. """
    def __init__(self, get_font_metrics, delegate, event_loop, draw_background):
        super().__init__()
        self.__get_font_metrics = get_font_metrics
        self.__delegate = delegate
        self.__event_loop = event_loop
        self.__draw_background = draw_background
        self.__displays = list()
        self.__display_trackers = list()
        self.layout = CanvasItem.CanvasItemColumnLayout()
        self.__closed = False

    def close(self):
        self.__closed = True
        super().close()

    def context_menu_event(self, x, y, gx, gy):
        return self.__delegate.show_display_context_menu(gx, gy)

    @property
    def default_aspect_ratio(self):
        return 1.0

    def display_inserted(self, display, index):
        self.__displays.insert(index, display)
        display_tracker = DisplayTracker(display, self.__get_font_metrics, self, self.__event_loop, self.__draw_background)
        self.__display_trackers.insert(index, display_tracker)
        self.insert_canvas_item(index, display_tracker.display_canvas_item)

    def display_removed(self, display, index):
        if not self.__closed:
            self.remove_canvas_item(self.__display_trackers[index].display_canvas_item)
            self.__display_trackers[index].close()
            del self.__displays[index]
            del self.__display_trackers[index]

    def display_rgba_changed(self, display, display_values):
        pass

    def display_data_and_metadata_changed(self, display, display_values):
        pass

    def update_display_values(self, display, display_values):
        pass

    def update_regions(self, display, graphic_selection):
        pass

    def handle_auto_display(self, display) -> bool:
        # enter key has been pressed
        return False

    @property
    def _displays(self):
        return tuple(self.__displays)

    # delegate for image canvas items

    def show_display_context_menu(self, gx, gy) -> bool:
        return self.__delegate.show_display_context_menu(gx, gy)

    def begin_mouse_tracking(self):
        self.__delegate.begin_mouse_tracking()

    def end_mouse_tracking(self, undo_command):
        self.__delegate.end_mouse_tracking(undo_command)

    def delete_key_pressed(self):
        self.__delegate.delete_key_pressed()

    def enter_key_pressed(self):
        self.__delegate.enter_key_pressed()

    def cursor_changed(self, pos):
        self.__delegate.cursor_changed(pos)

    def add_index_to_selection(self, index):
        self.__delegate.add_index_to_selection(index)

    def remove_index_from_selection(self, index):
        self.__delegate.remove_index_from_selection(index)

    def set_selection(self, index):
        self.__delegate.set_selection(index)

    def clear_selection(self):
        self.__delegate.clear_selection()

    def image_clicked(self, image_position, modifiers):
        return False

    def image_mouse_pressed(self, image_position, modifiers):
        return False

    def image_mouse_released(self, image_position, modifiers):
        return False

    def image_mouse_position_changed(self, image_position, modifiers):
        return False

    def image_panel_get_font_metrics(self, font, text):
        return self.__get_font_metrics(font, text)

    @property
    def tool_mode(self):
        return self.__delegate.tool_mode

    @tool_mode.setter
    def tool_mode(self, value):
        self.__delegate.tool_mode = value


class DisplayTracker:
    """Tracks messages from a display and passes them to associated display canvas item."""

    def __init__(self, display, get_font_metrics, delegate, event_loop, draw_background):
        self.__display = display
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

        def display_property_changed(key):
            if key == "title":
                if callable(self.on_title_changed):
                    self.on_title_changed(display.title)

        self.__display_about_to_be_removed_event_listener = display.about_to_be_removed_event.listen(clear_display)
        self.__display_property_changed_event_listener = display.property_changed_event.listen(display_property_changed)

        # ensure data stays in memory while displayed
        display.increment_display_ref_count()

        # create a canvas item and add it to the container canvas item.

        self.__display_canvas_item = create_display_canvas_item(display.actual_display_type, get_font_metrics, delegate, event_loop, draw_background=self.__draw_background)

        def child_display_inserted(key, display, index):
            self.__display_canvas_item.display_inserted(display, index)

        def child_display_removed(key, display, index):
            self.__display_canvas_item.display_removed(display, index)

        self.__child_display_inserted_event_listener = display.child_displays_model.item_inserted_event.listen(child_display_inserted)
        self.__child_display_removed_event_listener = display.child_displays_model.item_removed_event.listen(child_display_removed)

        for index, child_display in enumerate(display.child_displays_model.displays):
            child_display_inserted("displays", child_display, index)

        def display_type_changed(display_type):
            # called when the display type of the data item changes.

            child_display_count = len(display.child_displays_model.displays)
            for index, child_display in enumerate(display.child_displays_model.displays):
                self.__display_canvas_item.display_removed(child_display, child_display_count - 1 - index)

            old_display_canvas_item = self.__display_canvas_item
            new_display_canvas_item = create_display_canvas_item(display_type, self.__get_font_metrics, self.__delegate, self.__event_loop, draw_background=self.__draw_background)
            if callable(self.on_replace_display_canvas_item):
                self.on_replace_display_canvas_item(old_display_canvas_item, new_display_canvas_item)
            self.__display_canvas_item = new_display_canvas_item

            for index, child_display in enumerate(display.child_displays_model.displays):
                self.__display_canvas_item.display_inserted(child_display, index)

        self.__display_type_monitor = DisplayTypeMonitor(display)
        self.__display_type_changed_event_listener =  self.__display_type_monitor.display_type_changed_event.listen(display_type_changed)

        def display_graphic_selection_changed(graphic_selection):
            # this message comes from the display when the graphic selection changes
            self.__display_canvas_item.update_regions(display, graphic_selection)

        def display_rgba_changed(display_values):
            with self.__closing_lock:
                self.__display_canvas_item.display_rgba_changed(display, display_values)

        def display_data_and_metadata_changed(display_values):
            with self.__closing_lock:
                self.__display_canvas_item.display_data_and_metadata_changed(display, display_values)

        def display_changed():
            # called when anything in the data item changes, including things like graphics or the data itself.
            # this notification does not cover the rgba data, which is handled in the function below.
            # thread safe
            display_values = display.get_calculated_display_values()
            display_data_and_metadata_changed(display_values)
            display_graphic_selection_changed(display.graphic_selection)

        def handle_next_calculated_display_values():
            # this notification is for the rgba values only
            # thread safe
            display_values = display.get_calculated_display_values()
            display_rgba_changed(display_values)

        def display_property_changed(property: str) -> None:
            if property in ("y_min", "y_max", "left_channel", "right_channel", "image_zoom", "image_position", "image_canvas_mode"):
                with self.__closing_lock:
                    display_values = display.get_calculated_display_values()
                    self.__display_canvas_item.update_display_values(display, display_values)

        self.__next_calculated_display_values_listener = display.add_calculated_display_values_listener(handle_next_calculated_display_values)
        self.__display_graphic_selection_changed_event_listener = display.display_graphic_selection_changed_event.listen(display_graphic_selection_changed)
        self.__display_changed_event_listener = display.display_changed_event.listen(display_changed)
        self.__display_property_changed_listener = display.property_changed_event.listen(display_property_changed)

        # this may throw exceptions (during testing). make sure to close if that happens, ensuring that the
        # layer items (image/line plot) get shut down.
        display_changed()

    def close(self):
        child_display_count = len(self.__display.child_displays_model.displays)
        for index, child_display in enumerate(self.__display.child_displays_model.displays):
            self.__display_canvas_item.display_removed(child_display, child_display_count - 1 - index)
        with self.__closing_lock:  # ensures that display pipeline finishes
            self.__display_changed_event_listener.close()
            self.__display_changed_event_listener = None
            self.__display_property_changed_listener.close()
            self.__display_property_changed_listener = None
            self.__display_graphic_selection_changed_event_listener.close()
            self.__display_graphic_selection_changed_event_listener = None
            self.__next_calculated_display_values_listener.close()
            self.__next_calculated_display_values_listener = None
        self.__display_type_changed_event_listener.close()
        self.__display_type_changed_event_listener = None
        self.__display_type_monitor.close()
        self.__display_type_monitor = None
        self.__child_display_inserted_event_listener.close()
        self.__child_display_inserted_event_listener = None
        self.__child_display_removed_event_listener.close()
        self.__child_display_removed_event_listener = None
        # decrement the ref count on the old item to release it from memory if no longer used.
        self.__display.decrement_display_ref_count()
        self.__display_about_to_be_removed_event_listener.close()
        self.__display_about_to_be_removed_event_listener = None
        self.__display_property_changed_event_listener.close()
        self.__display_property_changed_event_listener = None
        self.__display_canvas_item = None

    @property
    def display(self):
        return self.__display

    @property
    def display_canvas_item(self):
        return self.__display_canvas_item

    @display_canvas_item.setter
    def display_canvas_item(self, value):
        self.__display_canvas_item = value


class InsertGraphicsCommand(Undo.UndoableCommand):

    def __init__(self, document_controller, display: Display.Display, graphics: typing.Sequence[Graphics.Graphic]):
        super().__init__(_("Insert Graphics"))
        self.__document_controller = document_controller
        self.__display_uuid = display.uuid
        self.__graphics = graphics  # only used for perform
        self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
        self.__new_workspace_layout = None
        self.__graphics_properties = None
        self.__graphic_uuids = [graphic.uuid for graphic in graphics]
        self.__undelete_logs = None
        self.initialize()

    def close(self):
        self.__undelete_logs = None
        self.__graphics_properties = None
        self.__display_uuid = None
        self.__graphic_uuids = None
        self.__document_controller = None
        self.__old_workspace_layout = None
        self.__new_workspace_layout = None
        super().close()

    def perform(self):
        display = self.__document_controller.document_model.get_display_by_uuid(self.__display_uuid)
        graphics = self.__graphics
        for graphic in graphics:
            display.add_graphic(graphic)
        self.__graphic_uuids = [graphic.uuid for graphic in graphics]
        self.__graphics = None

    def _get_modified_state(self):
        display = self.__document_controller.document_model.get_display_by_uuid(self.__display_uuid)
        return display.modified_state, self.__document_controller.workspace_controller.document_model.modified_state

    def _set_modified_state(self, modified_state):
        display = self.__document_controller.document_model.get_display_by_uuid(self.__display_uuid)
        display.modified_state, self.__document_controller.workspace_controller.document_model.modified_state = modified_state

    def _redo(self):
        display = self.__document_controller.document_model.get_display_by_uuid(self.__display_uuid)
        for undelete_log in reversed(self.__undelete_logs):
            self.__document_controller.document_model.undelete_all(undelete_log)
        self.__graphic_uuids = [graphic.uuid for graphic in display.graphics[-len(self.__graphic_uuids):]]
        self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

    def _undo(self):
        display = self.__document_controller.document_model.get_display_by_uuid(self.__display_uuid)
        graphics = [self.__document_controller.document_model.get_graphic_by_uuid(graphic_uuid) for graphic_uuid in self.__graphic_uuids]
        self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
        self.__undelete_logs = list()
        for graphic in graphics:
            self.__undelete_logs.append(display.remove_graphic(graphic, safe=True))
        self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)


class ChangeDisplayCommand(Undo.UndoableCommand):

    def __init__(self, document_model, display: Display.Display, *, title: str=None, command_id: str=None, is_mergeable: bool=False, **kwargs):
        super().__init__(title if title else _("Change Display"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__display_uuid = display.uuid
        self.__properties = display.save_properties()
        self.__value_dict = kwargs
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__display_uuid = None
        self.__properties = None
        super().close()

    def perform(self):
        display = self.__document_model.get_display_by_uuid(self.__display_uuid)
        for key, value in self.__value_dict.items():
            setattr(display, key, value)

    def _get_modified_state(self):
        display = self.__document_model.get_display_by_uuid(self.__display_uuid)
        return display.modified_state

    def _set_modified_state(self, modified_state):
        display = self.__document_model.get_display_by_uuid(self.__display_uuid)
        display.modified_state = modified_state

    def _undo(self):
        display = self.__document_model.get_display_by_uuid(self.__display_uuid)
        properties = self.__properties
        self.__properties = display.save_properties()
        display.restore_properties(properties)

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeDisplayCommand) and self.command_id and self.command_id == command.command_id and self.__display_uuid == command.__display_uuid


class ChangeGraphicsCommand(Undo.UndoableCommand):

    def __init__(self, document_model, display, graphics, *, title: str=None, command_id: str=None, is_mergeable: bool=False, **kwargs):
        super().__init__(title if title else _("Change Graphics"), command_id=command_id, is_mergeable=is_mergeable)
        self.__document_model = document_model
        self.__display_uuid = display.uuid
        self.__graphic_indexes = [display.graphics.index(graphic) for graphic in graphics]
        self.__properties = [graphic.write_to_dict() for graphic in graphics]
        self.__value_dict = kwargs
        self.initialize()

    def close(self):
        self.__document_model = None
        self.__properties = None
        self.__display_uuid = None
        self.__graphic_indexes = None
        super().close()

    def perform(self):
        display = self.__document_model.get_display_by_uuid(self.__display_uuid)
        graphics = [display.graphics[index] for index in self.__graphic_indexes]
        for key, value in self.__value_dict.items():
            for graphic in graphics:
                setattr(graphic, key, value)

    def _get_modified_state(self):
        display = self.__document_model.get_display_by_uuid(self.__display_uuid)
        return display.modified_state

    def _set_modified_state(self, modified_state):
        display = self.__document_model.get_display_by_uuid(self.__display_uuid)
        display.modified_state = modified_state

    def _undo(self):
        display = self.__document_model.get_display_by_uuid(self.__display_uuid)
        properties = self.__properties
        graphics = [display.graphics[index] for index in self.__graphic_indexes]
        self.__properties = [graphic.write_to_dict() for graphic in graphics]
        for graphic, properties in zip(graphics, properties):
            graphic.read_from_dict(properties)

    def can_merge(self, command: Undo.UndoableCommand) -> bool:
        return isinstance(command, ChangeGraphicsCommand) and self.command_id and self.command_id == command.command_id and self.__display_uuid == command.__display_uuid and self.__graphic_indexes == command.__graphic_indexes


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

        def drop(mime_data, region, x, y):
            if workspace_controller:
                return workspace_controller.handle_drop(self, mime_data, region, x, y)
            return "ignore"

        # list to the content_canvas_item messages and pass them along to listeners of this class.
        self.__content_canvas_item.on_drag_enter = drag_enter
        self.__content_canvas_item.on_drag_leave = drag_leave
        self.__content_canvas_item.on_drag_move = drag_move
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

        self.__display = None
        self.__display_tracker = None

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

        self.__selection = document_controller.filtered_displays_model.make_selection()

        self.__selection_changed_event_listener = self.__selection.changed_event.listen(self.__selection_changed)

        def data_list_drag_started(mime_data, thumbnail_data):
            self.content_canvas_item.drag(mime_data, thumbnail_data)

        def key_pressed(key):
            if key.text == "v":
                self.__cycle_display()
                return True
            return False

        def map_display_to_display_item(display):
            return DataPanel.DisplayItem(display, ui)

        def unmap_display_to_display_item(display_item):
            display_item.close()

        self.__filtered_display_items_model = ListModel.MappedListModel(container=document_controller.filtered_displays_model, master_items_key="displays", items_key="display_items", map_fn=map_display_to_display_item, unmap_fn=unmap_display_to_display_item)

        def notify_focus_changed():
            self.__document_controller.notify_focused_display_changed(self.__display)

        def display_item_selection_changed(display_items):
            indexes = set()
            for index, display_item in enumerate(self.__filtered_display_items_model.display_items):
                if display_item in display_items:
                    indexes.add(index)
            self.__selection.set_multiple(indexes)
            notify_focus_changed()

        def double_clicked(display_item):
            display_item_selection_changed([display_item])
            self.__cycle_display()
            return True

        def focus_changed(focused):
            if focused:
                notify_focus_changed()

        def delete_display_items(display_items):
            document_controller.delete_displays([display_item.display for display_item in display_items])

        self.__horizontal_data_grid_controller = DataPanel.DataGridController(document_controller.event_loop, document_controller.ui, self.__filtered_display_items_model, self.__selection, direction=GridCanvasItem.Direction.Row, wrap=False)
        self.__horizontal_data_grid_controller.on_display_item_selection_changed = display_item_selection_changed
        self.__horizontal_data_grid_controller.on_context_menu_event = self.__handle_context_menu_for_display
        self.__horizontal_data_grid_controller.on_display_item_double_clicked = double_clicked
        self.__horizontal_data_grid_controller.on_focus_changed = focus_changed
        self.__horizontal_data_grid_controller.on_delete_display_items = delete_display_items
        self.__horizontal_data_grid_controller.on_drag_started = data_list_drag_started
        self.__horizontal_data_grid_controller.on_key_pressed = key_pressed

        self.__grid_data_grid_controller = DataPanel.DataGridController(document_controller.event_loop, document_controller.ui, self.__filtered_display_items_model, self.__selection)
        self.__grid_data_grid_controller.on_display_item_selection_changed = display_item_selection_changed
        self.__grid_data_grid_controller.on_context_menu_event = self.__handle_context_menu_for_display
        self.__grid_data_grid_controller.on_display_item_double_clicked = double_clicked
        self.__grid_data_grid_controller.on_focus_changed = focus_changed
        self.__grid_data_grid_controller.on_delete_display_items = delete_display_items
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

        with self.__closing_lock:  # ensures that display pipeline finishes
            self.set_display(None)  # required before destructing display thread
        # NOTE: the enclosing canvas item should be closed AFTER this close is called.
        self.__set_display_panel_controller(None)
        self.__horizontal_data_grid_controller.close()
        self.__horizontal_data_grid_controller = None
        self.__grid_data_grid_controller.close()
        self.__grid_data_grid_controller = None
        self.__selection_changed_event_listener.close()
        self.__selection_changed_event_listener = None
        self.__document_controller.filtered_displays_model.release_selection(self.__selection)
        self.__filtered_display_items_model.close()
        self.__filtered_display_items_model = None
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
    def _display_canvas_item(self):
        return self.display_canvas_item

    @property
    def _display_items_for_test(self):
        return self.__filtered_display_items_model.display_items

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
            document_controller.notify_focused_display_changed(self.__display)

        if callable(self.on_contents_changed):
            self.on_contents_changed()

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
    def data_item(self):
        return DataItem.DisplaySpecifier.from_display(self.display).data_item

    @property
    def library_item(self):
        return DataItem.DisplaySpecifier.from_display(self.display).library_item

    @property
    def display(self):
        return self.__display

    def save_contents(self):
        d = dict()
        if self.display_panel_id:
            d["display_panel_id"] = str(self.display_panel_id)
        if self.__display_panel_controller:
            d["controller_type"] = self.__display_panel_controller.type
            self.__display_panel_controller.save(d)
        if self.__display:
            d["data_item_uuid"] = str(self.library_item.uuid)
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
                data_item = None
                data_item_uuid_str = d.get("data_item_uuid")
                if data_item_uuid_str:
                    data_item = self.__document_controller.document_model.get_data_item_by_uuid(uuid.UUID(data_item_uuid_str))
                self.set_displayed_data_item(data_item)
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
        return not self.__display and not self.__grid_browser_canvas_item.visible and not self.__display_panel_controller

    @property
    def _display_panel_type(self):
        if self.__horizontal_browser_canvas_item.visible:
            return "horizontal"
        elif self.__grid_browser_canvas_item.visible:
            return "grid"
        elif self.__display:
            return "data_item"
        else:
            return "empty"

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
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
        return DisplayPanelManager().image_display_clicked(self, display_specifier, image_position, modifiers)

    def image_mouse_pressed(self, image_position, modifiers):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
        return DisplayPanelManager().image_display_mouse_pressed(self, display_specifier, image_position, modifiers)

    def image_mouse_released(self, image_position, modifiers):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
        return DisplayPanelManager().image_display_mouse_released(self, display_specifier, image_position, modifiers)

    def image_mouse_position_changed(self, image_position, modifiers):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
        return DisplayPanelManager().image_display_mouse_position_changed(self, display_specifier, image_position, modifiers)

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
            self.set_display(self.__display)

    # sets the data item that this panel displays
    # not thread safe
    def set_displayed_data_item(self, data_item: DataItem.DataItem) -> None:
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        self.set_display(display_specifier.display)

    # sets the data item that this panel displays
    # not thread safe
    def set_display(self, display: typing.Optional[Display.Display]) -> None:
        # listen for changes to display content and parameters, metadata, or the selection
        # changes to the underlying data will trigger changes in the display content

        did_display_change = self.__display != display

        if did_display_change:

            # remove any existing display canvas item
            if len(self.__display_composition_canvas_item.canvas_items) > 1:
                self.__display_composition_canvas_item.remove_canvas_item(self.__display_composition_canvas_item.canvas_items[0])

            old_display_tracker = self.__display_tracker
            self.__display_tracker = None

            if display:
                def clear_display() -> None:
                    self.set_display(None)

                def handle_title_changed(title: str) -> None:
                    self.header_canvas_item.title = title

                def replace_display_canvas_item(old_display_canvas_item, new_display_canvas_item):
                    self.__display_composition_canvas_item.replace_canvas_item(old_display_canvas_item, new_display_canvas_item)

                self.__display_tracker = DisplayTracker(display, self.ui.get_font_metrics, self, self.__document_controller.event_loop, True)
                self.__display_tracker.on_clear_display = clear_display
                self.__display_tracker.on_title_changed = handle_title_changed
                self.__display_tracker.on_replace_display_canvas_item = replace_display_canvas_item

                self.__display_composition_canvas_item.insert_canvas_item(0, self.__display_tracker.display_canvas_item)

            if old_display_tracker:
                old_display_tracker.close()

        self.__display = display

        # update the related icons canvas item with the new display.
        self.__related_icons_canvas_item.set_display(display)

        self.header_canvas_item.title = display.title if display else None

        # update want mouse and selected status.
        if self.__display_composition_canvas_item:  # may be closed
            self.__display_composition_canvas_item.wants_mouse_events = self.display_canvas_item is None
            self.__display_composition_canvas_item.selected = display is not None and self._is_selected()

        if did_display_change:
            if self._is_focused:
                self.__document_controller.notify_focused_display_changed(self.__display)

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
            self.__document_controller.notify_focused_display_changed(self.__display)

    def _is_focused(self):
        """ Used for testing. """
        return self.__content_canvas_item.focused

    def request_focus(self):
        self.__content_canvas_item.request_focus()

    def set_display_panel_data_item(self, library_item: DataItem.LibraryItem, detect_controller: bool=False) -> None:
        if library_item:
            d = {"type": "image", "data_item_uuid": str(library_item.uuid)}
            if detect_controller and isinstance(library_item, DataItem.DataItem):
                data_item = library_item
                d2 = DisplayPanelManager().detect_controller(self.__document_controller.document_model, data_item)
                if d2:
                    d.update(d2)
        else:
            d = {"type": "image"}
        self.change_display_panel_content(d)

    @property
    def is_result_panel(self):
        return self._is_result_panel

    # this gets called when the user initiates a drag in the drag control to move the panel around
    def __handle_begin_drag(self):
        if self.__display:
            display_specifier = DataItem.DisplaySpecifier.from_display(self.__display)
            mime_data = self.ui.create_mime_data()
            if display_specifier.library_item:
                mime_data.set_data_as_string("text/library_item_uuid", str(display_specifier.library_item.uuid))
            if display_specifier.data_item:
                mime_data.set_data_as_string("text/data_item_uuid", str(display_specifier.data_item.uuid))
            mime_data.set_data_as_string(DISPLAY_PANEL_MIME_TYPE, json.dumps(self.save_contents()))
            thumbnail_data = Thumbnails.ThumbnailManager().thumbnail_data_for_display(self.__display)
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
        displays = [display_item.display for display_item in self.__filtered_display_items_model.display_items]
        if self.__display in displays:
            self.__selection.set(displays.index(self.__display))
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
        menu = self.__document_controller.create_context_menu_for_display(display_item.display if display_item else None)
        return self.show_context_menu(menu, gx, gy)

    def perform_action(self, fn, *args, **keywords):
        display_canvas_item = self.display_canvas_item
        target = display_canvas_item
        if hasattr(target, fn):
            getattr(target, fn)(*args, **keywords)

    def select_all(self):
        if self.__display:
            self.__display.graphic_selection.add_range(range(len(self.__display.graphics)))
        return True

    def __selection_changed(self):
        if len(self.__selection.indexes) == 1:
            index = list(self.__selection.indexes)[0]
            display = self.__filtered_display_items_model.display_items[index].display
        else:
            display = None
        self.set_display(display)
        self.__display_changed = True

    # messages from the display canvas item

    def add_index_to_selection(self, index):
        self.__display.graphic_selection.add(index)

    def remove_index_from_selection(self, index):
        self.__display.graphic_selection.remove(index)

    def set_selection(self, index):
        self.__display.graphic_selection.set(index)

    def clear_selection(self):
        self.__display.graphic_selection.clear()

    def add_and_select_region(self, region: Graphics.Graphic) -> Undo.UndoableCommand:
        self.__display.add_graphic(region)  # this will also make a drawn graphic
        # hack to select it. it will be the last item.
        self.__display.graphic_selection.set(len(self.__display.graphics) - 1)
        return InsertGraphicsCommand(self.__document_controller, self.__display, [region])

    def nudge_selected_graphics(self, mapping, delta):
        all_graphics = self.__display.graphics
        graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if self.__display.graphic_selection.contains(graphic_index)]
        if graphics:
            command = ChangeGraphicsCommand(self.__document_controller.document_model, self.__display, graphics, command_id="nudge", is_mergeable=True)
            for graphic in graphics:
                graphic.nudge(mapping, delta)
            self.__document_controller.push_undo_command(command)

    def update_graphics(self, widget_mapping, graphic_drag_items, graphic_drag_part, graphic_part_data, graphic_drag_start_pos, pos, modifiers):
        with self.__display._changes():
            for graphic in graphic_drag_items:
                index = self.__display.graphics.index(graphic)
                part_data = (graphic_drag_part, ) + graphic_part_data[index]
                graphic.adjust_part(widget_mapping, graphic_drag_start_pos, Geometry.IntPoint.make(pos), part_data, modifiers)

    @property
    def tool_mode(self):
        return self.__document_controller.tool_mode

    @tool_mode.setter
    def tool_mode(self, value):
        self.__document_controller.tool_mode = value

    def show_display_context_menu(self, gx, gy) -> bool:
        document_controller = self.__document_controller
        menu = document_controller.create_context_menu_for_display(self.__display, container=document_controller.document_model)
        return self.show_context_menu(menu, gx, gy)

    def begin_mouse_tracking(self):
        self.__mouse_tracking_transaction = self.__document_controller.document_model.begin_display_transaction(self.__display)

    def end_mouse_tracking(self, undo_command):
        self.__mouse_tracking_transaction.close()
        self.__mouse_tracking_transaction = None
        if undo_command:
            self.__document_controller.push_undo_command(undo_command)

    def delete_key_pressed(self):
        self.__document_controller.remove_selected_graphics()

    def enter_key_pressed(self):
        command = ChangeDisplayCommand(self.__document_controller.document_model, self.__display)
        result = self.display_canvas_item.handle_auto_display(self.__display)
        if result:
            self.__document_controller.push_undo_command(command)
        else:
            command.close()
        return result

    def cursor_changed(self, pos):
        position_text, value_text = str(), str()
        try:
            if pos is not None:
                position_text, value_text = self.__display.get_value_and_position_text(pos)
        except Exception as e:
            global _test_log_exceptions
            if _test_log_exceptions:
                import traceback
                traceback.print_exc()
        if position_text and value_text:
            self.__document_controller.cursor_changed([_("Position: ") + position_text, _("Value: ") + value_text])
        else:
            self.__document_controller.cursor_changed(None)

    def drag_graphics(self, graphics):
        data_item = DataItem.DisplaySpecifier.from_display(self.__display).data_item
        if data_item:
            mime_data = self.ui.create_mime_data()
            mime_data_content = dict()
            mime_data_content["data_item_uuid"] = str(data_item.uuid)
            if graphics and len(graphics) == 1:
                mime_data_content["graphic_uuid"] = str(graphics[0].uuid)
            mime_data.set_data_as_string(DataItem.DataSource.DATA_SOURCE_MIME_TYPE, json.dumps(mime_data_content))
            thumbnail_data = Thumbnails.ThumbnailManager().thumbnail_data_for_display(data_item.displays[0])
            self.__begin_drag(mime_data, thumbnail_data)

    def update_display_properties(self, display_properties):
        for key, value in iter(display_properties.items()):
            setattr(self.__display, key, value)

    def create_insert_graphics_command(self, graphics: typing.Sequence[Graphics.Graphic]) -> InsertGraphicsCommand:
        return InsertGraphicsCommand(self.__document_controller, self.__display, graphics)

    def create_change_display_command(self, *, command_id: str=None, is_mergeable: bool=False) -> ChangeDisplayCommand:
        return ChangeDisplayCommand(self.__document_controller.document_model, self.__display, command_id=command_id, is_mergeable=is_mergeable)

    def create_change_graphics_command(self) -> ChangeGraphicsCommand:
        all_graphics = self.__display.graphics
        graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if self.__display.graphic_selection.contains(graphic_index)]
        return ChangeGraphicsCommand(self.__document_controller.document_model, self.__display, graphics)

    def push_undo_command(self, command: Undo.UndoableCommand) -> None:
        self.__document_controller.push_undo_command(command)

    def create_rectangle(self, pos):
        bounds = tuple(pos), (0, 0)
        self.__display.graphic_selection.clear()
        region = Graphics.RectangleGraphic()
        region.bounds = bounds
        self.__display.add_graphic(region)
        self.__display.graphic_selection.set(self.__display.graphics.index(region))
        return region

    def create_ellipse(self, pos):
        bounds = tuple(pos), (0, 0)
        self.__display.graphic_selection.clear()
        region = Graphics.EllipseGraphic()
        region.bounds = bounds
        self.__display.add_graphic(region)
        self.__display.graphic_selection.set(self.__display.graphics.index(region))
        return region

    def create_line(self, pos):
        pos = tuple(pos)
        self.__display.graphic_selection.clear()
        region = Graphics.LineGraphic()
        region.start = pos
        region.end = pos
        self.__display.add_graphic(region)
        self.__display.graphic_selection.set(self.__display.graphics.index(region))
        return region

    def create_point(self, pos):
        pos = tuple(pos)
        self.__display.graphic_selection.clear()
        region = Graphics.PointGraphic()
        region.position = pos
        self.__display.add_graphic(region)
        self.__display.graphic_selection.set(self.__display.graphics.index(region))
        return region

    def create_line_profile(self, pos):
        data_item = DataItem.DisplaySpecifier.from_display(self.__display).data_item
        if data_item:
            pos = tuple(pos)
            self.__display.graphic_selection.clear()
            line_profile_region = Graphics.LineProfileGraphic()
            line_profile_region.start = pos
            line_profile_region.end = pos
            self.__display.add_graphic(line_profile_region)
            document_controller = self.__document_controller
            document_model = document_controller.document_model
            line_profile_data_item = document_model.get_line_profile_new(data_item, None, line_profile_region)
            new_display_specifier = DataItem.DisplaySpecifier.from_data_item(line_profile_data_item)
            document_controller.display_data_item(new_display_specifier)
            return line_profile_region
        return None

    def create_spot(self, pos):
        bounds = tuple(pos), (0, 0)
        self.__display.graphic_selection.clear()
        region = Graphics.SpotGraphic()
        region.bounds = bounds
        self.__display.add_graphic(region)
        self.__display.graphic_selection.set(self.__display.graphics.index(region))
        return region

    def create_wedge(self, angle):
        self.__display.graphic_selection.clear()
        region = Graphics.WedgeGraphic()
        region.end_angle = angle
        region.start_angle = angle + math.pi
        self.__display.add_graphic(region)
        self.__display.graphic_selection.set(self.__display.graphics.index(region))
        return region

    def create_ring(self, radius):
        self.__display.graphic_selection.clear()
        region = Graphics.RingGraphic()
        region.radius_1 = radius
        self.__display.add_graphic(region)
        self.__display.graphic_selection.set(self.__display.graphics.index(region))
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

    def image_display_clicked(self, display_panel, display_specifier, image_position, modifiers):
        return self.image_display_clicked_event.fire_any(display_panel, display_specifier, image_position, modifiers)

    def image_display_mouse_pressed(self, display_panel, display_specifier, image_position, modifiers):
        return self.image_display_mouse_pressed_event.fire_any(display_panel, display_specifier, image_position, modifiers)

    def image_display_mouse_released(self, display_panel, display_specifier, image_position, modifiers):
        return self.image_display_mouse_released_event.fire_any(display_panel, display_specifier, image_position, modifiers)

    def image_display_mouse_position_changed(self, display_panel, display_specifier, image_position, modifiers):
        return self.image_display_mouse_position_changed_event.fire_any(display_panel, display_specifier, image_position, modifiers)

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

    def switch_to_display_content(self, document_controller, display_panel: DisplayPanel, display_panel_type, data_item: DataItem.DataItem=None):
        d = {"type": "image", "display-panel-type": display_panel_type}
        if data_item and display_panel_type != "empty-display-panel":
            d["data_item_uuid"] = str(data_item.uuid)
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
            self.switch_to_display_content(document_controller, display_panel, display_panel_type, display_panel.data_item)

        empty_action = display_type_menu.add_menu_item(_("None"), functools.partial(switch_to_display_content, "empty-display-panel"))
        display_type_menu.add_separator()

        data_item_display_action = display_type_menu.add_menu_item(_("Data Item Display"), functools.partial(switch_to_display_content, "data-display-panel"))
        thumbnail_browser_action = display_type_menu.add_menu_item(_("Thumbnail Browser"), functools.partial(switch_to_display_content, "thumbnail-browser-display-panel"))
        grid_browser_action = display_type_menu.add_menu_item(_("Grid Browser"), functools.partial(switch_to_display_content, "browser-display-panel"))
        display_type_menu.add_separator()

        display_panel_type = display_panel.display_panel_type

        empty_action.checked = display_panel_type == "empty"
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


def preview(ui, display: Display.Display, width: int, height: int) -> DrawingContext.DrawingContext:
    display_type = display.actual_display_type
    display_values = display.get_calculated_display_values(True)
    drawing_context = DrawingContext.DrawingContext()
    display_canvas_item = create_display_canvas_item(display_type, ui.get_font_metrics, None, None, draw_background=False)
    if display_canvas_item:
        with contextlib.closing(display_canvas_item):
            for index, display_ in enumerate(display.child_displays_model.displays):
                display_canvas_item.display_inserted(display_, index)
            display_canvas_item.update_display_values(display, display_values)
            display_canvas_item.update_regions(display, Display.GraphicSelection())

            with drawing_context.saver():
                frame_width, frame_height = width, int(width / display_canvas_item.default_aspect_ratio)
                drawing_context.translate(0, (frame_width - frame_height) * 0.5)
                display_canvas_item.repaint_immediate(drawing_context, Geometry.IntSize(height=frame_height, width=frame_width))

    return drawing_context
