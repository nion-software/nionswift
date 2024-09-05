from __future__ import annotations

# standard libraries
import threading
import typing

# third party libraries
# None

# local libraries
from nion.swift import DisplayCanvasItem
from nion.swift.model import UISettings
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.utils import Geometry

if typing.TYPE_CHECKING:
    from nion.data import DataAndMetadata
    from nion.swift.model import DisplayItem
    from nion.swift.model import Graphics
    from nion.swift.model import Persistence
    from nion.swift import Undo
    from nion.ui import UserInterface


class DisplayScriptCanvasItemDelegate(typing.Protocol):
    # interface must be implemented by the delegate

    def begin_mouse_tracking(self) -> None: ...

    def end_mouse_tracking(self, undo_command: typing.Optional[Undo.UndoableCommand]) -> None: ...

    def delete_key_pressed(self) -> None: ...

    def enter_key_pressed(self) -> None: ...

    def cursor_changed(self, pos: typing.Optional[typing.Tuple[int, ...]]) -> None: ...

    def show_display_context_menu(self, gx: int, gy: int) -> bool: ...

    @property
    def tool_mode(self) -> str: return str()


class DrawingContextCanvasItem(CanvasItem.AbstractCanvasItem):
    def __init__(self) -> None:
        super().__init__()
        self.__drawing_context: typing.Optional[DrawingContext.DrawingContext] = None

    def set_drawing_context(self, drawing_context: DrawingContext.DrawingContext) -> None:
        self.__drawing_context = drawing_context
        self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        if self.__drawing_context:
            drawing_context.add(self.__drawing_context)


class ScriptDisplayCanvasItem(DisplayCanvasItem.DisplayCanvasItem):
    """Display a custom display using a script.

    Callers are expected to pass in a font metrics function and a delegate.
    """

    def __init__(self, ui_settings: UISettings.UISettings, delegate: typing.Optional[DisplayCanvasItem.DisplayCanvasItemDelegate]) -> None:
        super().__init__()

        self.__ui_settings = ui_settings
        self.delegate = delegate

        self.__display_xdata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
        self.__display_script: typing.Optional[str] = None

        self.__closing_lock = threading.RLock()
        self.__closed = False

        self.__drawing_context_canvas_item = DrawingContextCanvasItem()

        # canvas items get added back to front
        # create the child canvas items
        # the background first.
        self.add_canvas_item(CanvasItem.BackgroundCanvasItem())
        self.add_canvas_item(self.__drawing_context_canvas_item)

        # frame rate
        self.__display_frame_rate_id: typing.Optional[str] = None
        self.__display_frame_rate_last_index = 0

    def close(self) -> None:
        # call super
        with self.__closing_lock:
            self.__closed = True
        super().close()

    def add_display_control(self, display_control_canvas_item: CanvasItem.AbstractCanvasItem, role: typing.Optional[str] = None) -> None:
        display_control_canvas_item.close()

    def update_display_data_delta(self, display_data_delta: DisplayItem.DisplayDataDelta) -> None:
        if display_data_delta.display_values_list_changed:
            display_xdata: typing.Optional[DataAndMetadata.DataAndMetadata] = None
            if display_data_delta.display_values_list:
                display_values = display_data_delta.display_values_list[0]
                if display_values:
                    display_xdata = display_values.data_and_metadata
            self.__display_xdata = display_xdata
        if display_data_delta.display_values_list_changed or display_data_delta.display_calibration_info_changed or display_data_delta.display_layers_list_changed or display_data_delta.display_properties_changed:
            self.__display_script = display_data_delta.display_properties.get("display_script")
        self.__update_display_info()
        self.update()

    def handle_auto_display(self) -> bool:
        # enter key has been pressed
        return False

    def __update_display_info(self) -> None:
        data_and_metadata = self.__display_xdata
        display_script = self.__display_script
        if data_and_metadata and display_script:
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
                    g: typing.Dict[str, typing.Any] = dict()
                    drawing_context = DrawingContext.DrawingContext()
                    g["drawing_context"] = drawing_context
                    g["display_data_and_metadata"] = data_and_metadata
                    g["bounds"] = rect
                    g["get_font_metrics_fn"] = self.__ui_settings.get_font_metrics
                    l: typing.Dict[str, typing.Any] = dict()
                    try:
                        # print(code)
                        compiled = compile(display_script, "expr", "exec")
                        exec(compiled, g, l)
                    except Exception as e:
                        # import sys, traceback
                        # traceback.print_exc()
                        # traceback.format_exception(*sys.exc_info())
                        print(str(e) or "Unable to evaluate display script.")  # a stack trace would be too much information right now

                    self.__drawing_context_canvas_item.set_drawing_context(drawing_context)

    def mouse_entered(self) -> bool:
        if super().mouse_entered():
            return True
        self.__mouse_in = True
        return True

    def mouse_exited(self) -> bool:
        if super().mouse_exited():
            return True
        self.__mouse_in = False
        self.__update_cursor_info()
        if self.delegate:  # allow display to work without delegate
            # whenever the cursor exits, clear the cursor display
            self.delegate.cursor_changed(None)
        return True

    def mouse_double_clicked(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_clicked(x, y, modifiers):
            return True
        delegate = self.delegate
        if delegate and delegate.tool_mode == "pointer":
            pass  # pos = Geometry.IntPoint(x=x, y=y)
        return False

    def mouse_position_changed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_position_changed(x, y, modifiers):
            return True
        delegate = self.delegate
        if delegate and delegate.tool_mode == "pointer":
            self.cursor_shape = "arrow"
        self.__last_mouse = Geometry.IntPoint(x=x, y=y)
        self.__update_cursor_info()
        return True

    def mouse_pressed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_pressed(x, y, modifiers):
            return True
        delegate = self.delegate
        if delegate:
            delegate.begin_mouse_tracking()
            if delegate.tool_mode == "pointer":
                pass
        return False

    def mouse_released(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if super().mouse_released(x, y, modifiers):
            return True
        return False

    def context_menu_event(self, x: int, y: int, gx: int, gy: int) -> bool:
        delegate = self.delegate
        if delegate:
            return delegate.show_display_context_menu(gx, gy)
        return False

    @property
    def key_contexts(self) -> typing.Sequence[str]:
        return ["display_panel"]

    def __update_cursor_info(self) -> None:
        delegate = self.delegate
        if delegate and self.__mouse_in and self.__last_mouse:
            pass  # self.delegate.cursor_changed(pos_1d)
