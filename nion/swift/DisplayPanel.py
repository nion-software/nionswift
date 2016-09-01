# standard libraries
import copy
import functools
import gettext
import math
import operator
import random
import string
import uuid
import weakref

from nion.data import Calibration
from nion.swift import DataPanel
from nion.swift import ImageCanvasItem
from nion.swift import LinePlotCanvasItem
from nion.swift import Panel
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.utils import Event
from nion.utils import Geometry

_ = gettext.gettext


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


class BaseDisplayPanelContent:
    def __init__(self, document_controller):
        assert document_controller is not None

        self.__weak_document_controller = weakref.ref(document_controller)

        self.ui = document_controller.ui
        self.__identifier = None

        self.canvas_item = CanvasItem.CanvasItemComposition()
        self.canvas_item.layout = CanvasItem.CanvasItemColumnLayout()

        def handle_context_menu_event(x, y, gx, gy):
            menu = document_controller.ui.create_context_menu(document_controller.document_window)
            return self.show_context_menu(menu, gx, gy)

        self.__content_canvas_item = DisplayPanelOverlayCanvasItem()
        self.__content_canvas_item.wants_mouse_events = True  # only when display_canvas_item is None
        self.__content_canvas_item.focusable = True
        self.__content_canvas_item.on_focus_changed = lambda focused: self.set_focused(focused)
        self.__content_canvas_item.on_context_menu_event = handle_context_menu_event
        self.__header_canvas_item = Panel.HeaderCanvasItem(display_close_control=True)
        self.__footer_canvas_item = CanvasItem.LayerCanvasItem()
        self.__footer_canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        self.__footer_canvas_item.sizing.collapsible = True

        self.canvas_item.add_canvas_item(self.__header_canvas_item)
        self.canvas_item.add_canvas_item(self.__content_canvas_item)
        self.canvas_item.add_canvas_item(self.__footer_canvas_item)

        self.display_panel_id = None

        self.on_key_pressed = None
        self.on_key_released = None
        self.on_mouse_clicked = None
        self.on_drag_enter = None
        self.on_drag_leave = None
        self.on_drag_move = None
        self.on_drop = None
        self.on_show_context_menu = None
        self.on_begin_drag = None

        def drag_enter(mime_data):
            if self.on_drag_enter:
                return self.on_drag_enter(mime_data)
            return "ignore"

        def drag_leave():
            if self.on_drag_leave:
                return self.on_drag_leave()
            return False

        def drag_move(mime_data, x, y):
            if self.on_drag_move:
                return self.on_drag_move(mime_data, x, y)
            return "ignore"

        def drop(mime_data, region, x, y):
            if self.on_drop:
                return self.on_drop(mime_data, region, x, y)
            return "ignore"

        # list to the content_canvas_item messages and pass them along to listeners of this class.
        self.__content_canvas_item.on_drag_enter = drag_enter
        self.__content_canvas_item.on_drag_leave = drag_leave
        self.__content_canvas_item.on_drag_move = drag_move
        self.__content_canvas_item.on_drop = drop
        self.__content_canvas_item.on_key_pressed = self._handle_key_pressed
        self.__content_canvas_item.on_key_released = self._handle_key_released

        self.on_focused = None
        self.on_close = None

        def close():
            if self.on_close:
                self.on_close()

        self.__header_canvas_item.on_select_pressed = lambda: self._select()
        self.__header_canvas_item.on_drag_pressed = lambda: self._begin_drag()
        self.__header_canvas_item.on_close_clicked = close

    def close(self):
        # self.canvas_item.close()  # the creator of the image panel is responsible for closing the canvas item
        self.canvas_item = None
        self.__content_canvas_item.on_focus_changed = None  # only necessary during tests
        # release references
        self.__weak_document_controller = None
        self.__content_canvas_item = None
        self.__header_canvas_item = None
        self.on_key_pressed = None
        self.on_key_released = None
        self.on_mouse_clicked = None
        self.on_drag_enter = None
        self.on_drag_leave = None
        self.on_drag_move = None
        self.on_drop = None
        self.on_focused = None
        self.on_close = None

    @property
    def identifier(self):
        return self.__identifier

    def set_identifier(self, identifier):
        self.__identifier = identifier
        self.header_canvas_item.label = "#" + self.identifier

    @property
    def document_controller(self):
        return self.__weak_document_controller()

    @property
    def header_canvas_item(self):
        return self.__header_canvas_item

    @property
    def content_canvas_item(self):
        return self.__content_canvas_item

    @property
    def footer_canvas_item(self):
        return self.__footer_canvas_item

    # tasks can be added in two ways, queued or added
    # queued tasks are guaranteed to be executed in the order queued.
    # added tasks are only executed if not replaced before execution.
    # added tasks do not guarantee execution order or execution at all.

    def add_task(self, key, task):
        self.document_controller.add_task(key + str(id(self)), task)

    def clear_task(self, key):
        self.document_controller.clear_task(key + str(id(self)))

    def queue_task(self, task):
        self.document_controller.queue_task(task)

    # save and restore the contents of the image panel

    def save_contents(self):
        d = dict()
        if self.display_panel_id:
            d["display_panel_id"] = str(self.display_panel_id)
        return d

    def restore_contents(self, d):
        display_panel_id = d.get("display_panel_id")
        if display_panel_id:
            self.display_panel_id = display_panel_id

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
        if focused and self.on_focused:
            self.on_focused()

    def _is_focused(self):
        """ Used for testing. """
        return self.__content_canvas_item.focused

    @property
    def data_item(self):
        """Return the data item in this image panel, if any."""
        return None

    @property
    def display_specifier(self):
        """Convenience method."""
        return DataItem.DisplaySpecifier()

    # set the default display for the data item. just a simpler method to call.
    def set_displayed_data_item(self, data_item):
        raise NotImplementedError()

    def _select(self):
        pass

    def _begin_drag(self):
        raise NotImplementedError()

    # from the canvas item directly. dispatches to the display canvas item. if the display canvas item
    # doesn't handle it, gives the display controller a chance to handle it.
    def _handle_key_pressed(self, key):
        if self.on_key_pressed:
            return self.on_key_pressed(key)
        return False

    # from the canvas item directly. dispatches to the display canvas item. if the display canvas item
    # doesn't handle it, gives the display controller a chance to handle it.
    def _handle_key_released(self, key):
        if self.on_key_released:
            return self.on_key_released(key)
        return False

    def perform_action(self, fn, *args, **keywords):
        pass

    def show_context_menu(self, menu, gx, gy):
        if self.on_show_context_menu:
            return self.on_show_context_menu(menu, gx, gy)
        return False


class DataItemDataSourceDisplay:

    def __init__(self, data_item, delegate, display_type, get_font_metrics_fn):
        self.__data_item = data_item
        self.__delegate = delegate
        self.__display_type = display_type
        if self.__display_type == "line_plot":
            self.__display_canvas_item = LinePlotCanvasItem.LinePlotCanvasItem(get_font_metrics_fn, self)
        elif self.__display_type == "image":
            self.__display_canvas_item = ImageCanvasItem.ImageCanvasItem(get_font_metrics_fn, self)
            self.__display_canvas_item.set_fit_mode()
        else:
            raise Exception("Display type not found " + str(self.__display_type))
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        buffered_data_source = display_specifier.buffered_data_source
        display = display_specifier.display
        if buffered_data_source and display:
            def display_graphic_selection_changed(graphic_selection):
                # this message comes from the display when the graphic selection changes
                dimensional_shape = buffered_data_source.dimensional_shape
                displayed_dimensional_calibrations = display.displayed_dimensional_calibrations
                graphics = display.graphics
                self.__display_canvas_item.update_regions(dimensional_shape, displayed_dimensional_calibrations, graphic_selection, graphics)

            def display_changed():
                # called when anything in the data item changes, including things like graphics or the data itself.
                # update the display canvas, etc.
                # thread safe
                self.__update_display(buffered_data_source)
                display_graphic_selection_changed(display.graphic_selection)

            self.__display_changed_event_listener = display.display_changed_event.listen(display_changed)
            self.__display_graphic_selection_changed_event_listener = display.display_graphic_selection_changed_event.listen(display_graphic_selection_changed)

            display_changed()

    def close(self):
        if self.__display_changed_event_listener:
            self.__display_changed_event_listener.close()
            self.__display_changed_event_listener = None
        if self.__display_graphic_selection_changed_event_listener:
            self.__display_graphic_selection_changed_event_listener.close()
            self.__display_graphic_selection_changed_event_listener = None

    @property
    def _data_item(self):
        return self.__data_item

    @property
    def display_canvas_item(self):
        return self.__display_canvas_item

    @classmethod
    def update_display(cls, display_type, display_canvas_item, buffered_data_source):
        assert buffered_data_source is not None
        data_and_metadata = buffered_data_source.data_and_metadata
        if data_and_metadata:
            display = buffered_data_source.displays[0]
            displayed_dimensional_calibrations = display.displayed_dimensional_calibrations
            metadata = data_and_metadata.metadata
            if display_type == "image":
                if len(displayed_dimensional_calibrations) == 0:
                    dimensional_calibration = Calibration.Calibration()
                elif len(displayed_dimensional_calibrations) == 1:
                    dimensional_calibration = displayed_dimensional_calibrations[0]
                else:
                    dimensional_calibration = displayed_dimensional_calibrations[1]
                display_canvas_item.update_image_display_state(lambda: display.preview_2d, display.preview_2d_shape, dimensional_calibration, metadata)
            elif display_type == "line_plot":
                display_properties = {"y_min": display.y_min, "y_max": display.y_max, "y_style": display.y_style, "left_channel": display.left_channel,
                    "right_channel": display.right_channel, "legend_labels": display.legend_labels}
                dimensional_shape = data_and_metadata.dimensional_shape
                displayed_dimensional_calibration = displayed_dimensional_calibrations[-1] if len(displayed_dimensional_calibrations) > 0 else Calibration.Calibration()
                displayed_intensity_calibration = copy.deepcopy(data_and_metadata.intensity_calibration)
                display_canvas_item.update_line_plot_display_state(lambda: display.display_data, dimensional_shape, displayed_intensity_calibration,
                                                                   displayed_dimensional_calibration, metadata, display_properties)

    def __update_display(self, buffered_data_source):
        self.update_display(self.__display_type, self.__display_canvas_item, buffered_data_source)

    def add_index_to_selection(self, index):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display_specifier.display.graphic_selection.add(index)

    def remove_index_from_selection(self, index):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display_specifier.display.graphic_selection.remove(index)

    def set_selection(self, index):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display_specifier.display.graphic_selection.set(index)

    def clear_selection(self):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display_specifier.display.graphic_selection.clear()

    def add_and_select_region(self, region: Graphics.Graphic):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display_specifier.display.add_graphic(region)  # this will also make a drawn graphic
        # hack to select it. it will be the last item.
        display_specifier.display.graphic_selection.set(len(display_specifier.display.graphics) - 1)

    def nudge_selected_graphics(self, mapping, delta):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display = display_specifier.display
        if display:
            all_graphics = display.graphics
            graphics = [graphic for graphic_index, graphic in enumerate(all_graphics) if display.graphic_selection.contains(graphic_index)]
            for graphic in graphics:
                graphic.nudge(mapping, delta)

    def __view_to_selected_graphics(self):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display = display_specifier.display
        if display and self.__display_type == "line_plot":
            data_and_metadata = display_specifier.buffered_data_source.data_and_metadata
            display.view_to_selected_graphics(data_and_metadata)

    def update_graphics(self, widget_mapping, graphic_drag_items, graphic_drag_part, graphic_part_data, graphic_drag_start_pos, pos, modifiers):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        with display_specifier.data_item.data_item_changes():
            for graphic in graphic_drag_items:
                index = display_specifier.display.graphics.index(graphic)
                part_data = (graphic_drag_part, ) + graphic_part_data[index]
                graphic.adjust_part(widget_mapping, graphic_drag_start_pos, Geometry.IntPoint.make(pos), part_data, modifiers)

    @property
    def tool_mode(self):
        return self.__delegate.tool_mode

    @tool_mode.setter
    def tool_mode(self, value):
        self.__delegate.tool_mode = value

    def show_context_menu(self, gx, gy):
        return self.__delegate.show_context_menu(self.__data_item, gx, gy)

    def begin_mouse_tracking(self):
        self.__delegate.begin_data_item_transaction(self.__data_item)

    def end_mouse_tracking(self):
        self.__delegate.end_data_item_transaction(self.__data_item)

    def image_clicked(self, image_position, modifiers):
        return self.__delegate.image_clicked(image_position, modifiers)

    def image_mouse_pressed(self, image_position, modifiers):
        return self.__delegate.image_mouse_pressed(image_position, modifiers)

    def image_mouse_released(self, image_position, modifiers):
        return self.__delegate.image_mouse_released(image_position, modifiers)

    def image_mouse_position_changed(self, image_position, modifiers):
        return self.__delegate.image_mouse_position_changed(image_position, modifiers)

    def delete_key_pressed(self):
        return self.__delegate.remove_selected_graphic()

    def enter_key_pressed(self):
        if self.__display_type == "image":
            display = DataItem.DisplaySpecifier.from_data_item(self.__data_item).display
            display.auto_display_limits()
            return True
        elif self.__display_type == "line_plot":
            self.__view_to_selected_graphics()
        return False

    def cursor_changed(self, pos):
        self.__delegate.cursor_changed(self.__data_item, pos)

    def update_display_properties(self, display_properties):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        for key, value in iter(display_properties.items()):
            setattr(display_specifier.display, key, value)

    def create_rectangle(self, pos):
        bounds = tuple(pos), (0, 0)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display = display_specifier.display
        if display:
            display.graphic_selection.clear()
            region = Graphics.RectangleGraphic()
            region.bounds = bounds
            display.add_graphic(region)
            display.graphic_selection.set(display.graphics.index(region))
            return region
        return None

    def create_ellipse(self, pos):
        bounds = tuple(pos), (0, 0)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display = display_specifier.display
        if display:
            display.graphic_selection.clear()
            region = Graphics.EllipseGraphic()
            region.bounds = bounds
            display.add_graphic(region)
            display.graphic_selection.set(display.graphics.index(region))
            return region
        return None

    def create_line(self, pos):
        pos = tuple(pos)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display = display_specifier.display
        display = display_specifier.display
        if display:
            display.graphic_selection.clear()
            region = Graphics.LineGraphic()
            region.start = pos
            region.end = pos
            display.add_graphic(region)
            display.graphic_selection.set(display.graphics.index(region))
            return region
        return None

    def create_point(self, pos):
        pos = tuple(pos)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display = display_specifier.display
        if display:
            display.graphic_selection.clear()
            region = Graphics.PointGraphic()
            region.position = pos
            display.add_graphic(region)
            display.graphic_selection.set(display.graphics.index(region))
            return region
        return None

    def create_line_profile(self, pos):
        pos = tuple(pos)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display = display_specifier.display
        if display:
            display.graphic_selection.clear()
            line_profile_region = Graphics.LineProfileGraphic()
            line_profile_region.start = pos
            line_profile_region.end = pos
            display.add_graphic(line_profile_region)
            self.__delegate.display_line_profile(self.__data_item, line_profile_region)
            return line_profile_region
        return None

    def create_spot(self, pos):
        bounds = tuple(pos), (0, 0)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display = display_specifier.display
        if display:
            display.graphic_selection.clear()
            region = Graphics.SpotGraphic()
            region.bounds = bounds
            display.add_graphic(region)
            display.graphic_selection.set(display.graphics.index(region))
            return region
        return None

    def create_wedge(self, angle):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        display = display_specifier.display
        if display:
            display.graphic_selection.clear()
            region = Graphics.WedgeGraphic()
            region.end_angle = angle
            region.start_angle = angle + math.pi
            display.add_graphic(region)
            display.graphic_selection.set(display.graphics.index(region))
            return region
        return None


class DataItemDisplayTypeMonitor:
    """Monitor a data item for changes to the display type.

    Provides the display_type_changed(display_type) event.

    Provides the display_type r/o property.
    """

    def __init__(self):
        self.__data_item = None
        self.display_type_changed_event = Event.Event()
        self.__display_changed_event_listener = None
        self.__display_type = None

    def close(self):
        if self.__display_changed_event_listener:
            self.__display_changed_event_listener.close()
            self.__display_changed_event_listener = None

    @property
    def display_type(self):
        return self.__display_type

    def __set_display_type(self, display_type):
        if self.__display_type != display_type:
            self.__display_type = display_type
            self.display_type_changed_event.fire(display_type)

    def set_data_item(self, data_item):
        if self.__display_changed_event_listener:
            self.__display_changed_event_listener.close()
            self.__display_changed_event_listener = None
        self.__data_item = data_item
        display_type = None
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        buffered_data_source = display_specifier.buffered_data_source
        display = display_specifier.display
        if buffered_data_source and display:
            def get_display_type():
                # called when anything in the data item changes, including things like graphics or the data itself.
                # thread safe
                # TODO: handle consistently: if data is not valid, display_type should be cleared and not use whatever was assigned.
                # the way it works now is that if the display_type is already set, then invalid data will have no effect and the
                # display will happily be created with invalid data. the tests test for this behavior. ugh.
                display_type = display.display_type
                valid_data = functools.reduce(operator.mul, display.preview_2d_shape) > 0 if display.preview_2d_shape is not None else False
                if valid_data and not display_type in ("line_plot", "image"):
                    if buffered_data_source.collection_dimension_count == 2 and buffered_data_source.datum_dimension_count == 1:
                        display_type = "image"
                    elif buffered_data_source.datum_dimension_count == 1:
                        display_type = "line_plot"
                    elif buffered_data_source.datum_dimension_count == 2:
                        display_type = "image"
                return display_type

            def display_changed():
                self.__set_display_type(get_display_type())

            self.__display_changed_event_listener = display.display_changed_event.listen(display_changed)

            display_type = get_display_type()

        self.__set_display_type(display_type)


class DataDisplayPanelContent(BaseDisplayPanelContent):

    def __init__(self, document_controller):

        super().__init__(document_controller)

        self.__data_item = None
        self.__display_type_monitor = DataItemDisplayTypeMonitor()
        self.__display_type_changed_event_listener =  self.__display_type_monitor.display_type_changed_event.listen(self.__display_type_changed)
        self.__data_item_metadata_changed_event_listener = None

        # if the data item displayed in this panel gets deleted, remove it from this panel.

        def data_item_deleted(data_item):
            if data_item == self.data_item:
                self.set_displayed_data_item(None)

        document_model = self.document_controller.document_model
        self.__data_item_deleted_event_listener = document_model.data_item_deleted_event.listen(data_item_deleted)

        # the display panel controller is an object which adds and controls additional UI on top of this display.
        self.__display_panel_controller = None

        # the display canvas item delegate is an object that provides the canvas item displaying the data item.
        self.__display_canvas_item_delegate = None

        self.on_image_clicked = None
        self.on_image_mouse_pressed = None
        self.on_image_mouse_released = None
        self.on_image_mouse_position_changed = None

    def close(self):
        # NOTE: the enclosing canvas item should be closed AFTER this close is called.
        self.on_image_clicked = None
        self.on_image_mouse_pressed = None
        self.on_image_mouse_released = None
        self.on_image_mouse_position_changed = None
        self.__set_display_panel_controller(None)
        self.__data_item_deleted_event_listener.close()
        self.__data_item_deleted_event_listener = None
        self.set_displayed_data_item(None)  # required before destructing display thread
        assert not self.__display_canvas_item_delegate
        self.__display_type_changed_event_listener.close()
        self.__display_type_changed_event_listener = None
        self.__display_type_monitor.close()
        self.__display_type_monitor = None
        super().close()

    @property
    def _display_panel_controller_for_test(self):
        return self.__display_panel_controller

    @property
    def _display_canvas_item_delegate(self):
        return self.__display_canvas_item_delegate

    @property
    def _display_canvas_item(self):
        display_canvas_item = self.__display_canvas_item_delegate.display_canvas_item if self.__display_canvas_item_delegate else None
        return display_canvas_item

    # save and restore the contents of the image panel

    def save_contents(self):
        d = super().save_contents()
        if self.__display_panel_controller:
            d["controller_type"] = self.__display_panel_controller.type
            self.__display_panel_controller.save(d)
        data_item = self.data_item
        if data_item:
            d["data_item_uuid"] = str(data_item.uuid)
        return d

    def restore_contents(self, d):
        super().restore_contents(d)
        controller_type = d.get("controller_type")
        self.__set_display_panel_controller(DisplayPanelManager().make_display_panel_controller(controller_type, self, d))
        if not self.__display_panel_controller:
            data_item_uuid_str = d.get("data_item_uuid")
            if data_item_uuid_str:
                data_item = self.document_controller.document_model.get_data_item_by_uuid(uuid.UUID(data_item_uuid_str))
                if data_item:
                    self.set_displayed_data_item(data_item)

    def image_clicked(self, image_position, modifiers):
        if callable(self.on_image_clicked):
            return self.on_image_clicked(image_position, modifiers)
        return False

    def image_mouse_pressed(self, image_position, modifiers):
        if callable(self.on_image_mouse_pressed):
            return self.on_image_mouse_pressed(image_position, modifiers)
        return False

    def image_mouse_released(self, image_position, modifiers):
        if callable(self.on_image_mouse_released):
            return self.on_image_mouse_released(image_position, modifiers)
        return False

    def image_mouse_position_changed(self, image_position, modifiers):
        if callable(self.on_image_mouse_position_changed):
            return self.on_image_mouse_position_changed(image_position, modifiers)
        return False

    def image_panel_get_font_metrics(self, font, text):
        return self.ui.get_font_metrics(font, text)

    @property
    def data_item(self):
        """Return the data item displayed in this image panel. May be None."""
        return self.__data_item

    @property
    def display_specifier(self):
        """Convenience method."""
        return DataItem.DisplaySpecifier.from_data_item(self.__data_item)

    def __set_display_panel_controller(self, display_panel_controller):
        if self.__display_panel_controller:
            self.__display_panel_controller.close()
            self.__display_panel_controller = None
        self.__display_panel_controller = display_panel_controller
        if not display_panel_controller:
            self.header_canvas_item.reset_header_colors()
        self.set_displayed_data_item(self.__data_item)

    def __display_type_changed(self, display_type):
        # called when the display type of the data item changes.
        if self.__display_canvas_item_delegate:
            self.content_canvas_item.remove_canvas_item(self.__display_canvas_item_delegate.display_canvas_item)
            self.__display_canvas_item_delegate.close()
            self.__display_canvas_item_delegate = None
        display_panel_content = self
        if display_type and display_type in ("image", "line_plot"):
            class Delegate:
                @property
                def tool_mode(self):
                    return display_panel_content.document_controller.tool_mode

                @tool_mode.setter
                def tool_mode(self, value):
                    display_panel_content.document_controller.tool_mode = value

                def show_context_menu(self, data_item, gx, gy):
                    document_controller = display_panel_content.document_controller
                    document_model = document_controller.document_model
                    menu = document_controller.create_context_menu_for_data_item(data_item, container=document_model)
                    return display_panel_content.show_context_menu(menu, gx, gy)

                def begin_data_item_transaction(self, data_item):
                    display_panel_content.document_controller.document_model.begin_data_item_transaction(data_item)

                def end_data_item_transaction(self, data_item):
                    display_panel_content.document_controller.document_model.end_data_item_transaction(data_item)

                def image_clicked(self, image_position, modifiers):
                    return display_panel_content.image_clicked(image_position, modifiers)

                def image_mouse_pressed(self, image_position, modifiers):
                    return display_panel_content.image_mouse_pressed(image_position, modifiers)

                def image_mouse_released(self, image_position, modifiers):
                    return display_panel_content.image_mouse_released(image_position, modifiers)

                def image_mouse_position_changed(self, image_position, modifiers):
                    return display_panel_content.image_mouse_position_changed(image_position, modifiers)

                def remove_selected_graphic(self):
                    if display_panel_content.document_controller.remove_graphic():
                        return True
                    return False

                def cursor_changed(self, data_item, pos):
                    display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                    display = display_specifier.display
                    position_text, value_text = str(), str()
                    try:
                        position_text, value_text = display.get_value_and_position_text(pos)
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                    if position_text and value_text:
                        display_panel_content.document_controller.cursor_changed([_("Position: ") + position_text, _("Value: ") + value_text])
                    else:
                        display_panel_content.document_controller.cursor_changed(None)

                def display_line_profile(self, data_item: DataItem.DataItem, line_profile_region: Graphics.LineTypeGraphic):
                    document_controller = display_panel_content.document_controller
                    document_model = document_controller.document_model
                    line_profile_data_item = document_model.get_line_profile_new(data_item, None, line_profile_region)
                    new_display_specifier = DataItem.DisplaySpecifier.from_data_item(line_profile_data_item)
                    document_controller.display_data_item(new_display_specifier)

            self.__display_canvas_item_delegate = DataItemDataSourceDisplay(self.__data_item, Delegate(), display_type, self.ui.get_font_metrics)
            self.content_canvas_item.insert_canvas_item(0, self.__display_canvas_item_delegate.display_canvas_item)
        if self.content_canvas_item:
            self.content_canvas_item.update()

    # sets the data item that this panel displays
    # not thread safe
    def set_displayed_data_item(self, data_item):
        # ensure the display item stays in memory
        # listen for changes to display content and parameters, metadata, or the selection
        # changes to the underlying data will trigger changes in the display content
        if data_item:
            data_item.increment_data_ref_counts()  # ensure data stays in memory while displayed
        # track data item in this class to report changes
        old_data_item = self.__data_item
        if old_data_item:
            old_data_item.decrement_data_ref_counts()  # release old data from memory

        if self.__data_item_metadata_changed_event_listener:
            self.__data_item_metadata_changed_event_listener.close()
            self.__data_item_metadata_changed_event_listener = None

        self.__data_item = data_item

        # workaround an architectural quirk (smell) so that the display_type_changed_event gets generated
        # for the new data even if the display type doesn't change. see test_dragging_header_to_swap_works.
        # the original bug showed up when dragging right-to-left in bottom of 2x2 workspace with two raster
        # images.
        self.__display_type_monitor.set_data_item(None)
        self.__display_type_monitor.set_data_item(data_item)

        def metadata_changed():
            if self.header_canvas_item:  # may be closed
                self.header_canvas_item.title = self.__data_item.displayed_title if self.__data_item else None

        if data_item:
            self.__data_item_metadata_changed_event_listener = data_item.metadata_changed_event.listen(metadata_changed)

        metadata_changed()

        if self.content_canvas_item:  # may be closed
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.content_canvas_item.wants_mouse_events = self.__display_canvas_item_delegate is None
            self.content_canvas_item.selected = display_specifier.display is not None and self._is_selected()

    def _select(self):
        self.content_canvas_item.request_focus()

    # this gets called when the user initiates a drag in the drag control to move the panel around
    def _begin_drag(self):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
        if display_specifier.data_item is not None:
            mime_data = self.ui.create_mime_data()
            mime_data.set_data_as_string("text/data_item_uuid", str(display_specifier.data_item.uuid))
            root_canvas_item = self.canvas_item.root_container
            thumbnail_data = display_specifier.display.thumbnail_data
            on_begin_drag = self.on_begin_drag
            if callable(on_begin_drag):
                on_begin_drag(root_canvas_item.canvas_widget, mime_data, thumbnail_data)

    # from the canvas item directly. dispatches to the display canvas item. if the display canvas item
    # doesn't handle it, gives the display controller a chance to handle it.
    def _handle_key_pressed(self, key):
        display_canvas_item = self.__display_canvas_item_delegate.display_canvas_item if self.__display_canvas_item_delegate else None
        if display_canvas_item and display_canvas_item.key_pressed(key):
            return True
        if self.__display_panel_controller and self.__display_panel_controller.key_pressed(key):
            return True
        return super()._handle_key_pressed(key)

    # from the canvas item directly. dispatches to the display canvas item. if the display canvas item
    # doesn't handle it, gives the display controller a chance to handle it.
    def _handle_key_released(self, key):
        display_canvas_item = self.__display_canvas_item_delegate.display_canvas_item if self.__display_canvas_item_delegate else None
        if display_canvas_item and display_canvas_item.key_released(key):
            return True
        if self.__display_panel_controller and self.__display_panel_controller.key_released(key):
            return True
        return super()._handle_key_released(key)

    def perform_action(self, fn, *args, **keywords):
        display_canvas_item = self.__display_canvas_item_delegate.display_canvas_item if self.__display_canvas_item_delegate else None
        target = display_canvas_item
        if hasattr(target, fn):
            getattr(target, fn)(*args, **keywords)


class EmptyDisplayPanelContent(BaseDisplayPanelContent):

    def __init__(self, document_controller):
        super().__init__(document_controller)

        enclosing_self = self

        class ContextMenuCanvasItem(CanvasItem.EmptyCanvasItem):
            def context_menu_event(self, x, y, gx, gy):
                menu = document_controller.ui.create_context_menu(document_controller.document_window)
                return enclosing_self.show_context_menu(menu, gx, gy)

        empty_canvas_item = ContextMenuCanvasItem()
        self.content_canvas_item.add_canvas_item(empty_canvas_item)

    def save_contents(self):
        d = super().save_contents()
        d["display-panel-type"] = "empty-display-panel"
        return d

    # this gets called when the user initiates a drag in the drag control to move the panel around
    def _begin_drag(self):
        mime_data = self.ui.create_mime_data()
        mime_data.set_data_as_string("text/display_panel_type", "empty-display-panel")
        root_canvas_item = self.canvas_item.root_container
        on_begin_drag = self.on_begin_drag
        if callable(on_begin_drag):
            on_begin_drag(root_canvas_item.canvas_widget, mime_data, None)


class BrowserDisplayPanelContent(BaseDisplayPanelContent):

    def __init__(self, document_controller):
        super().__init__(document_controller)

        dispatch_task = document_controller.document_model.dispatch_task
        ui = document_controller.ui

        self.header_canvas_item.end_header_color = "#FFC"
        self.header_canvas_item.title = _("Browser")
        self.content_canvas_item.focused_style = None
        self.content_canvas_item.selected_style = None

        self.__data_browser_controller = document_controller.data_browser_controller
        self.__selection_changed_event_listener = self.__data_browser_controller.selection_changed_event.listen(self.__data_panel_selection_changed)

        def context_menu_event(display_item, x, y, gx, gy):
            menu = self.__data_browser_controller.create_display_item_context_menu(display_item)
            return self.show_context_menu(menu, gx, gy)

        self.data_grid_controller = DataPanel.DataGridController(document_controller.document_model.dispatch_task, document_controller.add_task, document_controller.clear_task, document_controller.ui, self.__data_browser_controller.selection)
        self.data_grid_controller.on_selection_changed = self.__data_browser_controller.selected_display_items_changed
        self.data_grid_controller.on_context_menu_event = context_menu_event
        self.data_grid_controller.on_display_item_double_clicked = None  # replace current display?
        self.data_grid_controller.on_focus_changed = lambda focused: setattr(self.__data_browser_controller, "focused", focused)
        self.data_grid_controller.on_delete_display_items = self.__data_browser_controller.delete_display_items

        def data_list_drag_started(mime_data, thumbnail_data):
            self.data_grid_controller.canvas_item.root_container.canvas_widget.drag(mime_data, thumbnail_data)

        self.data_grid_controller.on_drag_started = data_list_drag_started

        def data_item_inserted(data_item, before_index):
            display_item = DataPanel.DisplayItem(data_item, dispatch_task, ui)
            self.__display_items.insert(before_index, display_item)
            self.data_grid_controller.display_item_inserted(display_item, before_index)

        def data_item_removed(index):
            self.data_grid_controller.display_item_removed(index)
            self.__display_items[index].close()
            del self.__display_items[index]

        self.__binding = document_controller.filtered_data_items_binding
        self.__binding.inserters[id(self)] = lambda data_item, before_index: self.document_controller.queue_task(functools.partial(data_item_inserted, data_item, before_index))
        self.__binding.removers[id(self)] = lambda data_item, index: self.document_controller.queue_task(functools.partial(data_item_removed, index))

        self.__display_items = list()

        for index, data_item in enumerate(self.__binding.data_items):
            data_item_inserted(data_item, index)

        self.content_canvas_item.add_canvas_item(self.data_grid_controller.canvas_item)

    def close(self):
        del self.__binding.inserters[id(self)]
        del self.__binding.removers[id(self)]
        self.data_grid_controller.close()
        self.data_grid_controller = None
        for display_item in self.__display_items:
            display_item.close()
        self.__display_items = None
        self.__selection_changed_event_listener.close()
        self.__selection_changed_event_listener = None
        super().close()

    @property
    def _display_items_for_test(self):
        return self.__display_items

    def save_contents(self):
        d = super().save_contents()
        d["display-panel-type"] = "browser-display-panel"
        return d

    def __data_panel_selection_changed(self, data_item):
        # update the data item selection by determining the new index of the item, if any.
        data_item_index = -1
        for index in range(len(self.__display_items)):
            if data_item == self.__display_items[index].data_item:
                data_item_index = index
                break
        if data_item_index >= 0:
            self.data_grid_controller.set_selected_index(data_item_index)
        else:
            self.data_grid_controller.selection.clear()

    # this gets called when the user initiates a drag in the drag control to move the panel around
    def _begin_drag(self):
        mime_data = self.ui.create_mime_data()
        mime_data.set_data_as_string("text/display_panel_type", "browser-display-panel")
        root_canvas_item = self.canvas_item.root_container
        on_begin_drag = self.on_begin_drag
        if callable(on_begin_drag):
            on_begin_drag(root_canvas_item.canvas_widget, mime_data, None)


class DisplayPanel:

    def __init__(self, document_controller, d):
        self.__weak_document_controller = weakref.ref(document_controller)
        document_controller.register_display_panel(self)
        self.__display_panel_content = None
        self.__canvas_item = CanvasItem.CanvasItemComposition()
        # self.__canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        self.__canvas_item.wants_mouse_events = True
        self.uuid = uuid.UUID(d.get("uuid", str(uuid.uuid4())))
        self.identifier = d.get("identifier", "".join([random.choice(string.ascii_uppercase) for _ in range(2)]))
        self.__change_display_panel_content(document_controller, d)

    def close(self):
        if self.__display_panel_content:
            self.__display_panel_content.close()
            self.__display_panel_content = None
        self.__document_controller.unregister_display_panel(self)
        self.__weak_document_controller = None

    @property
    def __document_controller(self):
        return self.__weak_document_controller()

    def change_display_panel_content(self, d):
        assert self.__document_controller is not None
        self.__change_display_panel_content(self.__document_controller, d)

    def __change_display_panel_content(self, document_controller, d):
        is_selected = False
        is_focused = False

        if self.__display_panel_content:
            is_selected = self._is_selected()
            is_focused = self._is_focused()
            canvas_item = self.__display_panel_content.canvas_item
            self.__display_panel_content.close()
            self.__canvas_item.remove_canvas_item(canvas_item)

        self.__display_panel_content = DisplayPanelManager().make_display_panel_content(document_controller, d)
        self.__display_panel_content.set_identifier(self.identifier)
        self.__canvas_item.insert_canvas_item(0, self.__display_panel_content.canvas_item)
        self.__canvas_item.refresh_layout(True)

        workspace_controller = document_controller.workspace_controller

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

        def close():
            if len(workspace_controller.display_panels) > 1:
                workspace_controller.remove_display_panel(self)

        def key_pressed(key):
            return DisplayPanelManager().key_pressed(self, key)

        def key_released(key):
            return DisplayPanelManager().key_released(self, key)

        def image_clicked(image_position, modifiers):
            display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
            return DisplayPanelManager().image_display_clicked(self, display_specifier, image_position, modifiers)

        def image_mouse_pressed(image_position, modifiers):
            display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
            return DisplayPanelManager().image_display_mouse_pressed(self, display_specifier, image_position, modifiers)

        def image_mouse_released(image_position, modifiers):
            display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
            return DisplayPanelManager().image_display_mouse_released(self, display_specifier, image_position, modifiers)

        def image_mouse_position_changed(image_position, modifiers):
            display_specifier = DataItem.DisplaySpecifier.from_data_item(self.data_item)
            return DisplayPanelManager().image_display_mouse_position_changed(self, display_specifier, image_position, modifiers)

        def focused():
            document_controller.selected_display_panel = self  # MARK
            document_controller.notify_selected_data_item_changed(self.data_item)

        def show_context_menu(menu, gx, gy):
            def split_vertical():
                if workspace_controller:
                    return workspace_controller.insert_display_panel(self, "bottom")
            def split_horiztonal():
                if workspace_controller:
                    return workspace_controller.insert_display_panel(self, "right")
            menu.add_separator()
            menu.add_menu_item(_("Split Into Top and Bottom"), split_vertical)
            menu.add_menu_item(_("Split Into Left and Right"), split_horiztonal)

            menu.add_separator()
            DisplayPanelManager().build_menu(menu, self)

            menu.popup(gx, gy)
            return True

        def begin_drag(canvas_widget, mime_data, thumbnail_data):
            canvas_widget.drag(mime_data, thumbnail_data, drag_finished_fn=functools.partial(self._drag_finished, document_controller))

        self.__display_panel_content.on_key_pressed = key_pressed
        self.__display_panel_content.on_key_released = key_released
        self.__display_panel_content.on_image_clicked = image_clicked
        self.__display_panel_content.on_image_mouse_pressed = image_mouse_pressed
        self.__display_panel_content.on_image_mouse_released = image_mouse_released
        self.__display_panel_content.on_image_mouse_position_changed = image_mouse_position_changed
        self.__display_panel_content.on_show_context_menu = show_context_menu
        self.__display_panel_content.on_drag_enter = drag_enter
        self.__display_panel_content.on_drag_leave = drag_leave
        self.__display_panel_content.on_drag_move = drag_move
        self.__display_panel_content.on_drop = drop
        self.__display_panel_content.on_begin_drag = begin_drag
        self.__display_panel_content.on_focused = focused
        self.__display_panel_content.on_close = close

        self.__display_panel_content.restore_contents(d)

        self.__display_panel_content.set_selected(is_selected)

        if is_focused:
            self.__display_panel_content.canvas_item.request_focus()

        self.__display_panel_type = d.get("display-panel-type")
        self.__controller_type = d.get("controller_type")

    @property
    def canvas_item(self):
        return self.__canvas_item

    @property
    def display_canvas_item(self):
        return self.__display_panel_content._display_canvas_item

    @property
    def _content_for_test(self):
        """Used for testing."""
        return self.__display_panel_content

    @property
    def display_panel_id(self):
        return self.__display_panel_content.display_panel_id

    @property
    def data_item(self):
        return self.__display_panel_content.data_item

    def save_contents(self):
        d = self.__display_panel_content.save_contents()
        d["uuid"] = str(self.uuid)
        d["identifier"] = self.identifier
        return d

    def _drag_finished(self, document_controller, action):
        if action == "move" and document_controller.replaced_display_panel_content is not None:
            d = document_controller.replaced_display_panel_content
            self.__change_display_panel_content(document_controller, d)
            document_controller.replaced_display_panel_content = None

    def set_selected(self, selected):
        self.__display_panel_content.set_selected(selected)

    def _is_selected(self):
        return self.__display_panel_content._is_selected()

    def set_focused(self, focused):
        self.__display_panel_content.set_focused(focused)

    def _is_focused(self):
        return self.__display_panel_content._is_focused()

    def request_focus(self):
        if self.__display_panel_content:
            self.__display_panel_content.content_canvas_item.request_focus()

    def set_displayed_data_item(self, data_item: DataItem.DataItem, detect_controller: bool=False) -> None:
        if data_item is not None:
            d = {"type": "image", "data_item_uuid": str(data_item.uuid)}
            if detect_controller:
                d2 = DisplayPanelManager().detect_controller(data_item)
                if d2:
                    d.update(d2)
        else:
            d = {"type": "image"}
        self.change_display_panel_content(d)

    @property
    def is_result_panel(self):
        if self.__display_panel_type == "empty-display-panel":
            return True
        if self.__display_panel_type is None and self.__controller_type is not None:  # has a controller, don't use it
            return False
        if self.__display_panel_type is None and self.__display_panel_content.display_specifier.display is None:
            return True
        return False

    def perform_action(self, fn, *args, **keywords):
        if self.__display_panel_content:
            self.__display_panel_content.perform_action(fn, *args, **keywords)


class DisplayPanelManager(metaclass=Utility.Singleton):
    """ Acts as a broker for significant events occurring regarding display panels. Listeners can attach themselves to
    this object and receive messages regarding display panels. For instance, when the user presses a key on an display
    panel that isn't handled directly, listeners will be advised of this event. """

    def __init__(self):
        super().__init__()
        self.__display_panel_controllers = dict()  # maps controller_type to make_fn
        self.__display_controller_factories = dict()
        self.__display_panel_factories = dict()
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

    def register_display_panel_factory(self, factory_id, factory):
        assert factory_id not in self.__display_panel_factories
        self.__display_panel_factories[factory_id] = factory

    def unregister_display_panel_factory(self, factory_id):
        assert factory_id in self.__display_panel_factories
        del self.__display_panel_factories[factory_id]

    def make_display_panel_content(self, document_controller, d):
        display_panel_type = d.get("display-panel-type", "data-display-panel")
        if not display_panel_type in self.__display_panel_factories:
            display_panel_type = "data-display-panel"
        return self.__display_panel_factories.get(display_panel_type)(document_controller)

    def register_display_panel_controller_factory(self, factory_id, factory):
        assert factory_id not in self.__display_controller_factories
        self.__display_controller_factories[factory_id] = factory

    def unregister_display_panel_controller_factory(self, factory_id):
        assert factory_id in self.__display_controller_factories
        del self.__display_controller_factories[factory_id]

    def detect_controller(self, data_item: DataItem.DataItem) -> dict:
        priority = 0
        result = None
        for factory in self.__display_controller_factories.values():
            controller_type = factory.match(data_item)
            if controller_type and factory.priority > priority:
                priority = factory.priority
                result = controller_type
        return result

    def make_display_panel_controller(self, controller_type, display_panel_content, d):
        for factory in self.__display_controller_factories.values():
            display_panel_controller = factory.make_new(controller_type, display_panel_content, d)
            if display_panel_controller:
                return display_panel_controller
        return None

    def build_menu(self, display_type_menu, selected_display_panel):
        """Build the dynamic menu for the selected display panel.

        The user accesses this menu by right-clicking on the display panel.

        The basic menu items are to an empty display panel or a browser display panel.

        After that, each display controller factory is given a chance to add to the menu. The display
        controllers (for instance, a scan acquisition controller), may add its own menu items.
        """
        dynamic_live_actions = list()

        def switch_to_display_content(display_panel_type):
            d = {"type": "image", "display-panel-type": display_panel_type}
            selected_display_panel.change_display_panel_content(d)

        dynamic_live_actions.append(display_type_menu.add_menu_item(_("None"), functools.partial(switch_to_display_content, "empty-display-panel")))
        display_type_menu.add_separator()

        dynamic_live_actions.append(display_type_menu.add_menu_item(_("Browser"), functools.partial(switch_to_display_content, "browser-display-panel")))
        display_type_menu.add_separator()

        for factory in self.__display_controller_factories.values():
            dynamic_live_actions.extend(factory.build_menu(display_type_menu, selected_display_panel))

        return dynamic_live_actions


DisplayPanelManager().register_display_panel_factory("data-display-panel", DataDisplayPanelContent)
DisplayPanelManager().register_display_panel_factory("empty-display-panel", EmptyDisplayPanelContent)
DisplayPanelManager().register_display_panel_factory("browser-display-panel", BrowserDisplayPanelContent)
