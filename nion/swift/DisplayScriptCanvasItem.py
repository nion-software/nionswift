# standard libraries
import threading

# third party libraries
# None

# local libraries
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.utils import Geometry


class DisplayScriptCanvasItemDelegate:
    # interface must be implemented by the delegate

    def begin_mouse_tracking(self) -> None: ...

    def end_mouse_tracking(self, undo_command) -> None: ...

    def delete_key_pressed(self) -> None: ...

    def enter_key_pressed(self) -> None: ...

    def cursor_changed(self, pos): ...

    def show_display_context_menu(self, gx, gy) -> bool: ...

    @property
    def tool_mode(self) -> str: return str()


class DisplayScriptCanvasItem(CanvasItem.LayerCanvasItem):
    """Display a custom display using a script.

    Callers are expected to pass in a font metrics function and a delegate.
    """

    def __init__(self, get_font_metrics_fn, delegate, event_loop, draw_background: bool=True):
        super().__init__()

        self.__get_font_metrics_fn = get_font_metrics_fn
        self.delegate = delegate

        self.__drawing_context_lock = threading.RLock()
        self.__drawing_context = DrawingContext.DrawingContext()

        self.__display_data = None
        self.__display_script = None

        self.__closing_lock = threading.RLock()
        self.__closed = False

        self.__data = None
        self.__last_data = None

        # canvas items get added back to front
        # create the child canvas items
        # the background
        self.add_canvas_item(CanvasItem.BackgroundCanvasItem())

        # frame rate
        self.__display_frame_rate_id = None
        self.__display_frame_rate_last_index = 0

    def close(self):
        # call super
        with self.__closing_lock:
            self.__closed = True
        super().close()

    @property
    def default_aspect_ratio(self):
        return 1.0

    def display_inserted(self, display, index):
        pass

    def display_removed(self, display, index):
        pass

    def display_rgba_changed(self, display, display_values):
        # when the display rgba data changes, no need to do anything
        pass

    def display_data_and_metadata_changed(self, display, display_values):
        # when the data changes, update the display.
        self.update_display_values(display, display_values)

    def update_display_values(self, display, display_values):
        self.__display_data = display.data_and_metadata_for_display_panel
        self.__display_script = display.display_script
        self.update()

    def update_regions(self, display, graphic_selection):
        pass

    def handle_auto_display(self, display) -> bool:
        # enter key has been pressed
        return False

    def _inserted(self, container):
        # make sure we get 'prepare_render' calls
        self.register_prepare_canvas_item(self)

    def _removed(self, container):
        # turn off 'prepare_render' calls
        self.unregister_prepare_canvas_item(self)

    def prepare_render(self):
        data_and_metadata = self.__display_data
        display_script = self.__display_script
        if data_and_metadata:
            # this method may trigger a layout of its parent scroll area. however, the parent scroll
            # area may already be closed. this is a stop-gap guess at a solution - the basic idea being
            # that this object is not closeable while this method is running; and this method should not
            # run if the object is already closed.
            with self.__closing_lock:
                if self.__closed:
                    return
                assert not self.__closed
                # Update the display state.
                rect = self.canvas_bounds
                if rect is not None:
                    g = dict()
                    drawing_context = DrawingContext.DrawingContext()
                    g["drawing_context"] = drawing_context
                    g["display_data_and_metadata"] = data_and_metadata
                    g["bounds"] = rect
                    g["get_font_metrics_fn"] = self.__get_font_metrics_fn
                    l = dict()
                    try:
                        # print(code)
                        compiled = compile(display_script, "expr", "exec")
                        exec(compiled, g, l)
                    except Exception as e:
                        # import sys, traceback
                        # traceback.print_exc()
                        # traceback.format_exception(*sys.exc_info())
                        print(str(e) or "Unable to evaluate display script.")  # a stack trace would be too much information right now

                    with self.__drawing_context_lock:
                        self.__drawing_context = drawing_context

    def _repaint(self, drawing_context):
        super()._repaint(drawing_context)

        with self.__drawing_context_lock:
            drawing_context.add(self.__drawing_context)

        if self.__display_frame_rate_id:
            Utility.fps_tick("display_"+self.__display_frame_rate_id)

        if self.__display_frame_rate_id:
            fps = Utility.fps_get("display_"+self.__display_frame_rate_id)
            fps2 = Utility.fps_get("frame_"+self.__display_frame_rate_id)
            fps3 = Utility.fps_get("update_"+self.__display_frame_rate_id)

            rect = self.canvas_bounds

            with drawing_context.saver():
                font = "normal 11px serif"
                text_pos = Geometry.IntPoint(y=rect[0][0], x=rect[0][1] + rect[1][1] - 100)
                drawing_context.begin_path()
                drawing_context.move_to(text_pos.x, text_pos.y)
                drawing_context.line_to(text_pos.x + 120, text_pos.y)
                drawing_context.line_to(text_pos.x + 120, text_pos.y + 60)
                drawing_context.line_to(text_pos.x, text_pos.y + 60)
                drawing_context.close_path()
                drawing_context.fill_style = "rgba(255, 255, 255, 0.6)"
                drawing_context.fill()
                drawing_context.font = font
                drawing_context.text_baseline = "middle"
                drawing_context.text_align = "left"
                drawing_context.fill_style = "#000"
                drawing_context.fill_text("display:" + fps, text_pos.x + 8, text_pos.y + 10)
                drawing_context.fill_text("frame:" + fps2, text_pos.x + 8, text_pos.y + 30)
                drawing_context.fill_text("update:" + fps3, text_pos.x + 8, text_pos.y + 50)

    def mouse_entered(self):
        if super().mouse_entered():
            return True
        self.__mouse_in = True
        return True

    def mouse_exited(self):
        if super().mouse_exited():
            return True
        self.__mouse_in = False
        self.__update_cursor_info()
        if self.delegate:  # allow display to work without delegate
            # whenever the cursor exits, clear the cursor display
            self.delegate.cursor_changed(None)
        return True

    def mouse_double_clicked(self, x, y, modifiers):
        if super().mouse_clicked(x, y, modifiers):
            return True
        if self.delegate.tool_mode == "pointer":
            pass  # pos = Geometry.IntPoint(x=x, y=y)
        return False

    def mouse_position_changed(self, x, y, modifiers):
        if super().mouse_position_changed(x, y, modifiers):
            return True
        if self.delegate.tool_mode == "pointer":
            self.cursor_shape = "arrow"
        self.__last_mouse = Geometry.IntPoint(x=x, y=y)
        self.__update_cursor_info()
        return True

    def mouse_pressed(self, x, y, modifiers):
        if super().mouse_pressed(x, y, modifiers):
            return True
        self.delegate.begin_mouse_tracking()
        if self.delegate.tool_mode == "pointer":
            pass
        return False

    def mouse_released(self, x, y, modifiers):
        if super().mouse_released(x, y, modifiers):
            return True
        return False

    def context_menu_event(self, x, y, gx, gy):
        return self.delegate.show_display_context_menu(gx, gy)

    # ths message comes from the widget
    def key_pressed(self, key):
        if super().key_pressed(key):
            return True
        # only handle keys if we're directly embedded in an image panel
        if key.is_delete:
            self.delegate.delete_key_pressed()
            return True
        if key.is_enter_or_return:
            self.delegate.enter_key_pressed()
            return True
        if key.key == 70 and key.modifiers.shift and key.modifiers.alt:
            if self.__display_frame_rate_id is None:
                self.__display_frame_rate_id = str(id(self))
            else:
                self.__display_frame_rate_id = None
            return True
        return False

    def __update_cursor_info(self):
        if not self.delegate:  # allow display to work without delegate
            return
        if self.__mouse_in and self.__last_mouse:
            pass  # self.delegate.cursor_changed(pos_1d)
