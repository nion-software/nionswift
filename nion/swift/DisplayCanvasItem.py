from __future__ import annotations

import abc
import types
import typing

from nion.swift import Undo
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Persistence
from nion.swift.model import Utility
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import UserInterface
from nion.utils import Geometry


class InteractiveTask:
    def __init__(self) -> None:
        pass

    def __enter__(self) -> InteractiveTask:
        return self

    def __exit__(self, exception_type: typing.Optional[typing.Type[BaseException]], value: typing.Optional[BaseException], traceback: typing.Optional[types.TracebackType]) -> typing.Optional[bool]:
        self.close()
        return None

    def close(self) -> None:
        self._close()

    def commit(self) -> None:
        self._commit()

    def _close(self) -> None: ...
    def _commit(self) -> None: ...


class DisplayCanvasItemDelegate(typing.Protocol):

    @property
    def tool_mode(self) -> str: raise NotImplementedError()

    @tool_mode.setter
    def tool_mode(self, value: str) -> None: ...

    def begin_mouse_tracking(self) -> None: ...
    def end_mouse_tracking(self, undo_command: typing.Optional[Undo.UndoableCommand]) -> None: ...
    def delete_key_pressed(self) -> None: ...
    def enter_key_pressed(self) -> None: ...
    def cursor_changed(self, pos: typing.Optional[typing.Tuple[int, ...]]) -> None: ...
    def update_display_properties(self, display_properties: Persistence.PersistentDictType) -> None: ...
    def update_display_data_channel_properties(self, display_data_channel_properties: Persistence.PersistentDictType) -> None: ...
    def create_change_display_command(self, *, command_id: typing.Optional[str] = None, is_mergeable: bool = False) -> Undo.UndoableCommand: ...
    def create_change_graphics_command(self) -> Undo.UndoableCommand: ...
    def create_insert_graphics_command(self, graphics: typing.Sequence[Graphics.Graphic]) -> Undo.UndoableCommand: ...
    def create_move_display_layer_command(self, display_item: DisplayItem.DisplayItem, src_index: int, target_index: int) -> Undo.UndoableCommand: ...
    def push_undo_command(self, command: Undo.UndoableCommand) -> None: ...
    def create_change_display_properties_task(self) -> InteractiveTask: ...
    def create_create_graphic_task(self, graphic_type: str, start_position: Geometry.FloatPoint) -> InteractiveTask: ...
    def create_change_graphics_task(self) -> InteractiveTask: ...
    def add_index_to_selection(self, index: int) -> None: ...
    def remove_index_from_selection(self, index: int) -> None: ...
    def set_selection(self, index: int) -> None: ...
    def clear_selection(self) -> None: ...
    def add_and_select_region(self, region: Graphics.Graphic) -> Undo.UndoableCommand: ...
    def nudge_selected_graphics(self, mapping: Graphics.CoordinateMappingLike, delta: Geometry.FloatSize) -> None: ...
    def nudge_slice(self, delta: int) -> None: ...
    def drag_graphics(self, graphics: typing.Sequence[Graphics.Graphic]) -> None: ...
    def adjust_graphics(self, widget_mapping: Graphics.CoordinateMappingLike, graphic_drag_items: typing.Sequence[Graphics.Graphic], graphic_drag_part: str, graphic_part_data: typing.Dict[int, Graphics.DragPartData], graphic_drag_start_pos: Geometry.FloatPoint, pos: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> None: ...
    def display_clicked(self, modifiers: UserInterface.KeyboardModifiers) -> bool: ...
    def image_clicked(self, image_position: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> bool: ...
    def image_mouse_pressed(self, image_position: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> bool: ...
    def image_mouse_released(self, image_position: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> bool: ...
    def image_mouse_position_changed(self, image_position: Geometry.FloatPoint, modifiers: UserInterface.KeyboardModifiers) -> bool: ...
    def show_display_context_menu(self, gx: int, gy: int) -> bool: ...
    def get_document_model(self) -> DocumentModel.DocumentModel: ...
    def create_rectangle(self, pos: Geometry.FloatPoint) -> Graphics.RectangleGraphic: ...
    def create_ellipse(self, pos: Geometry.FloatPoint) -> Graphics.EllipseGraphic: ...
    def create_line(self, pos: Geometry.FloatPoint) -> Graphics.LineGraphic: ...
    def create_point(self, pos: Geometry.FloatPoint) -> Graphics.PointGraphic: ...
    def create_line_profile(self, pos: Geometry.FloatPoint) -> Graphics.LineProfileGraphic: ...
    def create_spot(self, pos: Geometry.FloatPoint) -> Graphics.SpotGraphic: ...
    def create_wedge(self, angle: float) -> Graphics.WedgeGraphic: ...
    def create_ring(self, radius: float) -> Graphics.RingGraphic: ...
    def create_lattice(self, u_pos: Geometry.FloatSize) -> Graphics.LatticeGraphic: ...


class DisplayCanvasItem(CanvasItem.CanvasItemComposition):
    """Allow display canvas items (tools) to bypass multi-select.

    In cases where only_shift is used in the tool, the tool should bypass multi-select and the result will be as if
    the user clicked in the target display panel without modifiers. For instance, if the user shift-clicks using the
    crop tool to restrict the crop to a square shape, the crop tool should bypass multi-select and the result will be
    as if the user clicked in the target display panel without modifiers, selecting the target panel.
    """
    bypass_multi_select = False

    @property
    def key_contexts(self) -> typing.Sequence[str]:
        """Return key contexts.

        Key contexts provide an ordered list of contexts that are used to determine
        which actions are valid at a given time. The contexts are checked in reverse
        order (i.e. last added have highest precedence).
        """
        return list()

    @property
    def mouse_mapping(self) -> Graphics.CoordinateMappingLike: raise NotImplementedError()

    @abc.abstractmethod
    def add_display_control(self, display_control_canvas_item: CanvasItem.AbstractCanvasItem, role: typing.Optional[str] = None) -> None: ...

    @abc.abstractmethod
    def handle_auto_display(self) -> bool: ...

    def update_display_data_delta(self, display_data_delta: DisplayItem.DisplayDataDelta) -> None: ...


class FrameRateCanvasItem(CanvasItem.AbstractCanvasItem):
    def __init__(self) -> None:
        super().__init__()
        self.__display_frame_rate_id: typing.Optional[str] = None
        self.__display_frame_rate_last_index = 0

    @property
    def display_frame_rate_id(self) -> typing.Optional[str]:
        return self.__display_frame_rate_id

    @display_frame_rate_id.setter
    def display_frame_rate_id(self, value: typing.Optional[str]) -> None:
        self.__display_frame_rate_id = value
        self.update()

    def toggle_display(self, display_frame_rate_id: str) -> None:
        if self.__display_frame_rate_id is None:
            self.__display_frame_rate_id = display_frame_rate_id
        else:
            self.__display_frame_rate_id = None
        self.update()

    def frame_tick(self, frame_index: int) -> None:
        if self.__display_frame_rate_id:
            if frame_index != self.__display_frame_rate_last_index:
                Utility.fps_tick("frame_" + self.__display_frame_rate_id)
                self.__display_frame_rate_last_index = frame_index
            Utility.fps_tick("update_" + self.__display_frame_rate_id)
            self.update()

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        super()._repaint(drawing_context)
        display_frame_rate_id = self.__display_frame_rate_id
        canvas_bounds = self.canvas_bounds
        if canvas_bounds and display_frame_rate_id:
            Utility.fps_tick("display_" + display_frame_rate_id)
            fps = Utility.fps_get("display_" + display_frame_rate_id)
            fps2 = Utility.fps_get("frame_" + display_frame_rate_id)
            fps3 = Utility.fps_get("update_" + display_frame_rate_id)
            with drawing_context.saver():
                font = "normal 11px serif"
                text_pos = canvas_bounds.top_left
                drawing_context.begin_path()
                drawing_context.move_to(text_pos.x, text_pos.y)
                drawing_context.line_to(text_pos.x + 200, text_pos.y)
                drawing_context.line_to(text_pos.x + 200, text_pos.y + 60)
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
                drawing_context.statistics("display")
