from __future__ import annotations

# standard libraries
import gettext
import json
import typing
import weakref

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.ui import CanvasItem
from nion.ui import TreeCanvasItem
from nion.utils import Event
from nion.utils import Geometry

if typing.TYPE_CHECKING:
    from nion.data import DataAndMetadata
    from nion.swift import DocumentController
    from nion.swift.model import DataItem
    from nion.swift.model import DisplayItem
    from nion.ui import UserInterface

_ = gettext.gettext


class MetadataModel:
    """Represents metadata. Tracks a display specifier for changes to it and its metadata content.

    Provides read/write access to metadata via the property.

    Provides a metadata_changed event, always fired on UI thread.
    """

    def __init__(self, document_controller: DocumentController.DocumentController) -> None:
        self.__weak_document_controller = weakref.ref(document_controller)
        self.__data_item: typing.Optional[DataItem.DataItem] = None

        # thread safe.
        def display_item_changed(display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
            data_item = display_item.data_item if display_item else None

            def update_data_item() -> None:
                self.__set_data_item(data_item)

            document_controller = self.document_controller
            if document_controller:
                document_controller.add_task("update_data_item" + str(id(self)), update_data_item)

        self.__display_item_changed_event_listener = document_controller.focused_display_item_changed_event.listen(display_item_changed)
        self.__set_data_item(None)
        self.__metadata_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.__metadata: typing.Optional[DataAndMetadata.MetadataType] = None
        self.metadata_changed_event = Event.Event()

    def close(self) -> None:
        document_controller = self.document_controller
        if document_controller:
            document_controller.clear_task("update_data_item" + str(id(self)))
        self.__display_item_changed_event_listener.close()
        self.__display_item_changed_event_listener = typing.cast(typing.Any, None)
        self.__set_data_item(None)

    @property
    def document_controller(self) -> typing.Optional[DocumentController.DocumentController]:
        return self.__weak_document_controller()

    @property
    def metadata(self) -> typing.Optional[DataAndMetadata.MetadataType]:
        return self.__metadata

    def __metadata_changed(self, data_item: typing.Optional[DataItem.DataItem]) -> None:
        metadata = data_item.metadata if data_item else dict()
        assert isinstance(metadata, dict)
        if self.__metadata != metadata:
            self.__metadata = metadata if metadata is not None else dict()
            self.metadata_changed_event.fire(self.__metadata)

    # not thread safe
    def __set_data_item(self, data_item: typing.Optional[DataItem.DataItem]) -> None:
        if self.__data_item != data_item:
            if self.__metadata_changed_event_listener:
                self.__metadata_changed_event_listener.close()
                self.__metadata_changed_event_listener = None
            self.__data_item = data_item
            # update the expression text
            if data_item:
                def metadata_changed() -> None:
                    self.__metadata_changed(data_item)
                self.__metadata_changed_event_listener = data_item.metadata_changed_event.listen(metadata_changed)
            self.__metadata_changed(data_item)


class MetadataEditorTreeDelegate(TreeCanvasItem.TreeCanvasItemDelegate):
    def __init__(self, metadata: DataAndMetadata.MetadataType) -> None:
        self.__metadata = metadata
        self.__expanded_value_paths: typing.Set[str] = set()

    @property
    def metadata(self) -> DataAndMetadata.MetadataType:
        return self.__metadata

    @metadata.setter
    def metadata(self, value: DataAndMetadata.MetadataType) -> None:
        assert isinstance(value, dict)
        self.__metadata = value

    def __is_expanded(self, value_path: TreeCanvasItem._ValuePath) -> bool:
        return json.dumps(value_path) in self.__expanded_value_paths

    def toggle_is_expanded(self, value_path_key: str) -> None:
        if value_path_key in self.__expanded_value_paths:
            self.__expanded_value_paths.remove(value_path_key)
        else:
            self.__expanded_value_paths.add(value_path_key)

    def build_items(self, get_font_metrics_fn: typing.Callable[[str, str], UserInterface.FontMetrics],
                    item_width: typing.Optional[int]) -> typing.Sequence[TreeCanvasItem.TreeItem]:
        items: typing.List[TreeCanvasItem.TreeItem] = list()
        text_font = "normal 12px monospace"

        def visit_value(value_path: TreeCanvasItem._ValuePath, value: typing.Any) -> None:
            if isinstance(value, dict):
                is_expanded = self.__is_expanded(value_path)
                format_str = "{} {{{}}}"
                text_item = CanvasItem.StaticTextCanvasItem(format_str.format(value_path[-1], len(value)))
                text_item.font = text_font
                text_item.size_to_content(get_font_metrics_fn)
                items.append(TreeCanvasItem.TreeItem(text_item, "parent", is_expanded, value_path))
                if is_expanded:
                    visit_dict(value, value_path)
            elif isinstance(value, list) or isinstance(value, tuple):
                is_expanded = self.__is_expanded(value_path)
                format_str = "{} ({})"
                text_item = CanvasItem.StaticTextCanvasItem(format_str.format(value_path[-1], len(value)))
                text_item.font = text_font
                text_item.size_to_content(get_font_metrics_fn)
                items.append(TreeCanvasItem.TreeItem(text_item, "parent", is_expanded, value_path))
                if is_expanded:
                    visit_list(value, value_path)
            else:
                text_item = CanvasItem.StaticTextCanvasItem("{}: {}".format(value_path[-1], value))
                text_item.font = text_font
                text_item.size_to_content(get_font_metrics_fn)
                items.append(TreeCanvasItem.TreeItem(text_item, "child", False, value_path))

        def visit_list(l: typing.Sequence[typing.Any], path: TreeCanvasItem._ValuePath) -> None:
            for index, value in enumerate(l):
                value_path = tuple(path) + (index,)
                visit_value(value_path, value)

        def visit_dict(d: typing.Mapping[str, typing.Any], path: TreeCanvasItem._ValuePath) -> None:
            for key in sorted(d.keys()):
                value = d[key]
                value_path = tuple(path) + (key,)
                visit_value(value_path, value)

        visit_dict(self.__metadata, tuple())

        return items


class MetadataPanel(Panel.Panel):
    """Provide a panel to edit metadata."""

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: typing.Mapping[str, typing.Any]) -> None:
        super().__init__(document_controller, panel_id, _("Metadata"))

        ui = self.ui

        self.__metadata_model = MetadataModel(document_controller)

        delegate = MetadataEditorTreeDelegate(dict())

        metadata_editor_widget = ui.create_canvas_widget()
        metadata_editor_canvas_item = TreeCanvasItem.TreeCanvasItem(ui.get_font_metrics, delegate)
        metadata_editor_widget.canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        metadata_editor_widget.canvas_item.add_canvas_item(metadata_editor_canvas_item)
        metadata_editor_widget.canvas_item.add_stretch()
        self.__metadata_editor_canvas_item = metadata_editor_canvas_item

        column = self.ui.create_column_widget()
        column.add_spacing(6)
        column.add(metadata_editor_widget)
        column.add_spacing(6)

        scroll_area = self.ui.create_scroll_area_widget()
        scroll_area.set_scrollbar_policies("needed", "needed")
        scroll_area.content = column

        def content_height_changed(content_height: int) -> None:
            desired_height = content_height + 12
            metadata_editor_canvas_item.update_sizing(metadata_editor_canvas_item.sizing.with_fixed_height(desired_height))
            metadata_editor_widget.canvas_item.update_layout(Geometry.IntPoint(), scroll_area.size)
            if metadata_editor_canvas_item._has_layout:
                column.size = Geometry.IntSize(height=desired_height, width=column.size.width)

        metadata_editor_canvas_item.on_content_height_changed = content_height_changed

        def metadata_changed(metadata: DataAndMetadata.MetadataType) -> None:
            delegate.metadata = metadata

            def reconstruct_metadata() -> None:
                if self.__metadata_editor_canvas_item:  # use this instead of local variable to handle close properly
                    self.__metadata_editor_canvas_item.reconstruct()

            self.document_controller.queue_task(reconstruct_metadata)

        self.__metadata_changed_event_listener = self.__metadata_model.metadata_changed_event.listen(metadata_changed)

        self.widget = scroll_area

    def close(self) -> None:
        self.__metadata_editor_canvas_item = typing.cast(typing.Any, None)
        self.__metadata_changed_event_listener.close()
        self.__metadata_changed_event_listener = typing.cast(typing.Any, None)
        self.__metadata_model.close()
        self.__metadata_model = typing.cast(typing.Any, None)
        super().close()

    @property
    def _metadata_editor_canvas_item_for_testing(self) -> TreeCanvasItem.TreeCanvasItem:
        return self.__metadata_editor_canvas_item

    @property
    def _metadata_model_for_testing(self) -> MetadataModel:
        return self.__metadata_model
