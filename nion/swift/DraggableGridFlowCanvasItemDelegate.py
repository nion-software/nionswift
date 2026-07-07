import typing
import weakref

import numpy

from nion.data import Image

from nion.swift import MimeTypes
from nion.swift import Thumbnails
from nion.swift.model import DisplayItem
from nion.ui import Bitmap
from nion.ui import GridFlowCanvasItem
from nion.ui import UserInterface
from nion.ui import Window
from nion.utils import Geometry
from nion.utils import Selection

_NDArray = numpy.typing.NDArray[typing.Any]  # numpy arrays can have any dtype


if typing.TYPE_CHECKING:
    from nion.swift import DisplayPanel
    from nion.swift import DocumentController
    from nion.swift import Workspace


class DragHandler(typing.Protocol):
    """Protocol for a method that can be called on drag events.

    The default arguments can be specified rather than using a typing.Callable where the names and default values are not visible.
    """
    def __call__(self, mime_data: UserInterface.MimeData, thumbnail: Bitmap.BitmapOrArray | None = None,
                 hot_spot_x: int | None = None, hot_spot_y: int | None = None,
                 drag_finished_fn: typing.Callable[[str], None] | None = None, /) -> None:
        ...


class DraggableGridFlowCanvasItemDelegate(GridFlowCanvasItem.GridFlowCanvasItemDelegate):
    """Delegate for handling the grid canvas item for draggable display items.

    This manages the drag and drop events, context menu events, delete events and item tool tip events.
    T
    """
    def __init__(self, document_controller: DocumentController.DocumentController, selection: Selection.IndexedSelection, drag: DragHandler) -> None:
        self._document_controller_ref = weakref.ref(document_controller)
        self._selection = selection
        self._ui = document_controller.ui
        self._drag = drag

    def item_tool_tip(self, item: typing.Any) -> str | None:
        display_item = typing.cast(DisplayItem.DisplayItem, item)
        return display_item.list_tool_tip_str

    def context_menu_event(self, context_menu_event: GridFlowCanvasItem.GridFlowCanvasItemContextMenuEvent) -> bool:
        document_controller = self._document_controller_ref()
        assert document_controller
        display_items = tuple(typing.cast(DisplayItem.DisplayItem, item) for item in context_menu_event.selected_items)
        menu = document_controller.create_context_menu()
        action_context = document_controller._get_action_context_for_display_items(display_items, None)
        document_controller.populate_context_menu(menu, action_context)
        menu.add_separator()
        document_controller.add_action_to_menu_if_enabled(menu, "workspace.new_workspace_from_selection", action_context)
        menu.add_separator()
        document_controller.add_action_to_menu(menu, "item.delete", action_context)
        menu.popup(context_menu_event.gp.x, context_menu_event.gp.y)
        return True

    def delete_event(self, delete_event: GridFlowCanvasItem.GridFlowCanvasItemDeleteEvent) -> bool:
        document_controller = self._document_controller_ref()
        assert document_controller
        display_items = tuple(typing.cast(DisplayItem.DisplayItem, item) for item in delete_event.selected_items)
        document_controller.delete_display_items(display_items)
        return True

    def drag_started_event(self, drag_started_event: GridFlowCanvasItem.GridFlowCanvasItemDragStartedEvent) -> bool:
        mime_data, thumbnail_data = self._get_mime_data_and_thumbnail_data(drag_started_event)
        if mime_data:
            self._drag(mime_data, thumbnail_data)
            return True
        return False

    def can_drop_mime_data(self, mime_data: UserInterface.MimeData, action: str, drop_index: int | None) -> bool:
        return mime_data.has_file_paths

    def drop_mime_data(self, mime_data: UserInterface.MimeData, action: str, drop_index: int | None) -> str:
        document_controller = self._document_controller_ref()
        assert document_controller
        display_items = document_controller.receive_files(mime_data.file_paths)
        if set(display_items).intersection(set(document_controller.filtered_display_items_model.display_items)):
            document_controller.select_display_items_in_data_panel(display_items)
        return "accept"

    def _get_mime_data_and_thumbnail_data(self, drag_started_event: GridFlowCanvasItem.GridFlowCanvasItemDragStartedEvent) -> typing.Tuple[UserInterface.MimeData | None, _NDArray | None]:
        document_controller = self._document_controller_ref()
        assert document_controller
        mime_data = None
        thumbnail_data = None
        display_item = typing.cast(DisplayItem.DisplayItem, drag_started_event.item)
        display_items = tuple(
            typing.cast(DisplayItem.DisplayItem, item) for item in drag_started_event.selected_items)
        if len(display_items) <= 1 and display_item is not None:
            mime_data = document_controller.ui.create_mime_data()
            MimeTypes.mime_data_put_display_item(mime_data, display_item)
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self._ui, display_item)
            thumbnail_data = thumbnail_source.thumbnail_data
            if thumbnail_data is not None:
                # scaling is very slow
                thumbnail_data = Image.get_rgba_data_from_rgba(
                    Image.scaled(Image.get_rgba_view_from_rgba_data(thumbnail_data),
                                 tuple(Geometry.IntSize(w=80, h=80))))
        elif len(display_items) > 1:
            mime_data = document_controller.ui.create_mime_data()
            MimeTypes.mime_data_put_display_items(mime_data, display_items)
            # Thumbnail preference order: The display item the drag started from, then the anchor item, then the first display item in the list
            if display_item is None:
                anchor_index = self._selection.anchor_index
                if anchor_index is not None:
                    display_item = document_controller.display_items_model.items[anchor_index]
                else:
                    display_item = display_items[0]
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self._ui, display_item)
            thumbnail_data = thumbnail_source.thumbnail_data
        return mime_data, thumbnail_data


class DisplayPanelItemDelegate(DraggableGridFlowCanvasItemDelegate):
    """Delegate for handling a display panel's grid canvas item.

    Manages the dragging and dropping in the display panel while it is in a grid canvas view.
    """
    def __init__(self, document_controller: DocumentController.DocumentController,
                 selection: Selection.IndexedSelection, display_panel: DisplayPanel.DisplayPanel, workspace_controller: Workspace.Workspace | None) -> None:
        super().__init__(document_controller, selection, display_panel.content_canvas_item.drag)
        self._display_panel_ref = weakref.ref(display_panel)
        self._workspace_controller_ref = weakref.ref(workspace_controller) if workspace_controller else lambda : None

    def context_menu_event(self, context_menu_event: GridFlowCanvasItem.GridFlowCanvasItemContextMenuEvent) -> bool:
        display_panel = self._display_panel_ref()
        if display_panel:
            display_panel.handle_context_menu_for_display(context_menu_event.item,
                                                          context_menu_event.selected_items,
                                                          context_menu_event.p.x, context_menu_event.p.y,
                                                          context_menu_event.gp.x, context_menu_event.gp.y)
            return True
        return False

    def key_pressed_event(self, key_event: GridFlowCanvasItem.GridFlowCanvasItemKeyPressedEvent) -> bool:
        document_controller = self._document_controller_ref()
        assert document_controller
        action = Window.get_action_for_key(["display_panel_browser"], key_event.key)
        if action:
            document_controller.perform_action(action)
            return True
        return False

    def mouse_double_clicked_event(self, double_clicked_event: GridFlowCanvasItem.GridFlowCanvasItemDoubleClickedEvent) -> bool:
        display_panel = self._display_panel_ref()
        if display_panel:
            display_panel.cycle_display()
            return True
        return False

    def drag_enter(self, mime_data: UserInterface.MimeData) -> str:
        document_controller = self._document_controller_ref()
        assert document_controller
        display_panel = self._display_panel_ref()
        assert display_panel
        display_canvas_item = display_panel.display_canvas_item if display_panel else None
        if display_canvas_item and hasattr(display_canvas_item, "get_drop_regions_map"):
            # give the display canvas item a chance to provide drop regions based on the display item being dropped
            display_item = None
            if mime_data.has_format(MimeTypes.DISPLAY_PANEL_MIME_TYPE):
                display_item, d = MimeTypes.mime_data_get_panel(mime_data, document_controller.document_model)
            if not display_item:
                display_item = MimeTypes.mime_data_get_display_item(mime_data, document_controller.document_model)
            if display_item:
                display_panel.content_canvas_item.drop_regions_map = getattr(display_canvas_item, "get_drop_regions_map")(display_item)
        else:
            display_panel.content_canvas_item.drop_regions_map = dict()

        workspace_controller = self._workspace_controller_ref()
        if workspace_controller:
            return workspace_controller.handle_drag_enter(display_panel, mime_data)
        return "ignore"

    def drag_leave(self) -> str:
        workspace_controller = self._workspace_controller_ref()
        display_panel = self._display_panel_ref()
        if workspace_controller and display_panel:
            return workspace_controller.handle_drag_leave(display_panel)
        return "ignore"

    def drag_move(self, mime_data: UserInterface.MimeData, x: int, y: int) -> str:
        workspace_controller = self._workspace_controller_ref()
        display_panel = self._display_panel_ref()
        if workspace_controller and display_panel:
            return workspace_controller.handle_drag_move(display_panel, mime_data, x, y)
        return "ignore"

    def wants_drag_event(self, mime_data: UserInterface.MimeData) -> bool:
        workspace_controller = self._workspace_controller_ref()
        if workspace_controller:
            return workspace_controller.should_handle_drag_for_mime_data(mime_data)
        return False

    def drop(self, mime_data: UserInterface.MimeData, region: str, x: int, y: int) -> str:
        workspace_controller = self._workspace_controller_ref()
        display_panel = self._display_panel_ref()
        if workspace_controller and display_panel:
            return workspace_controller.handle_drop(display_panel, mime_data, region, x, y)
        return "ignore"

    def adjust_secondary_focus(self, modifiers: UserInterface.KeyboardModifiers) -> None:
        document_controller = self._document_controller_ref()
        assert document_controller
        display_panel = self._display_panel_ref()
        if not display_panel:
            return
        display_canvas_item = display_panel.display_canvas_item
        if display_canvas_item and display_canvas_item.bypass_multi_select:
            display_canvas_item.bypass_multi_select = False
            document_controller.selected_display_panel = display_panel
        elif modifiers.only_shift:
            document_controller.add_secondary_display_panel(display_panel)
        elif modifiers.only_control:
            document_controller.toggle_secondary_display_panel(display_panel)
