from __future__ import annotations

# standard libraries
import asyncio
import concurrent.futures
import gettext
import json
import threading
import time
import typing
import weakref

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.ui import CanvasItem
from nion.ui import DrawingContext
from nion.ui import UserInterface
from nion.ui import TreeCanvasItem
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import Process

if typing.TYPE_CHECKING:
    from nion.data import DataAndMetadata
    from nion.swift import DocumentController
    from nion.swift.model import DataItem
    from nion.swift.model import DisplayItem

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
        self.__property_changed_event_listener: typing.Optional[Event.EventListener] = None
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

    def __metadata_changed(self, data_item: typing.Optional[DataItem.DataItem]) -> None:
        self.metadata_changed_event.fire(data_item)

    # not thread safe
    def __set_data_item(self, data_item: typing.Optional[DataItem.DataItem]) -> None:
        if self.__data_item != data_item:
            if self.__property_changed_event_listener:
                self.__property_changed_event_listener.close()
                self.__property_changed_event_listener = None
            self.__data_item = data_item
            # update the expression text
            if data_item:
                def property_changed(property_name: str) -> None:
                    if property_name == "metadata":
                        self.__metadata_changed(data_item)
                self.__property_changed_event_listener = data_item.property_changed_event.listen(property_changed)
            self.__metadata_changed(data_item)


class MetadataSource(typing.Protocol):
    @property
    def metadata(self) -> DataAndMetadata.MetadataType:
        raise NotImplementedError()


class MetadataEditorTreeDelegate(TreeCanvasItem.TreeCanvasItemDelegate):
    def __init__(self) -> None:
        self.metadata_source: typing.Optional[MetadataSource] = None
        self.__expanded_value_paths: typing.Set[str] = set()

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

        if self.metadata_source:
            visit_dict(self.metadata_source.metadata, tuple())

        return items


class ThreadedCanvasItem(CanvasItem.CanvasItemComposition):
    _executor = concurrent.futures.ThreadPoolExecutor()

    def __init__(self, get_font_metrics_fn: typing.Callable[[str, str], UserInterface.FontMetrics], delegate: TreeCanvasItem.TreeCanvasItemDelegate, content_size_changed_fn: typing.Optional[typing.Callable[[Geometry.IntSize], None]] = None) -> None:
        super().__init__()
        self.__get_font_metrics_fn = get_font_metrics_fn
        self.__delegate = delegate
        self.__metadata_editor_canvas_item: typing.Optional[TreeCanvasItem.TreeCanvasItem] = None
        self.__thread_lock = threading.Lock()
        self.__thread_future: typing.Optional[concurrent.futures.Future[None]] = None
        self.__closing = False
        self.__pending = False
        self.__visible = False
        self.on_content_size_changed = content_size_changed_fn

        self.__draw(DrawingContext.DrawingContext())

        self.wants_mouse_events = True

    def close(self) -> None:
        # wait for display values threads to finish. first notify the thread that we are closing, then wait for it
        # to complete by getting the future and waiting for it to complete. then clear the streams to release any
        # resources (display values).
        self.__closing = True
        with self.__thread_lock:
            thread_future = self.__thread_future
        if thread_future:
            thread_future.result()
        super().close()

    def __draw_thread(self) -> None:
        while not self.__closing:
            with self.__thread_lock:
                pending = self.__pending
                self.__pending = False
            if pending:
                time.sleep(0.05)
                drawing_context = DrawingContext.DrawingContext()
                if not self.__closing:  # cleaner closing behavior, but not perfect.
                    with Process.audit("draw_thread"):
                        self.__draw(drawing_context)
            with self.__thread_lock:
                if not self.__pending or not self.__visible:
                    self.__thread_future = None
                    break

    def __draw(self, drawing_context: DrawingContext.DrawingContext) -> None:
        canvas_bounds = self.canvas_bounds
        if canvas_bounds:
            # start = time.perf_counter_ns()

            metadata_editor_canvas_item = TreeCanvasItem.TreeCanvasItem(self.__get_font_metrics_fn, self.__delegate)
            metadata_editor_canvas_item.on_reconstruct = self._trigger
            metadata_editor_canvas_item.reconstruct()
            # calculate the new preferred size of the metadata editor.
            metadata_editor_canvas_item.size_to_content()
            metadata_editor_canvas_item_size = Geometry.FloatSize(w=metadata_editor_canvas_item.sizing.preferred_width, h=metadata_editor_canvas_item.sizing.preferred_height).to_int_size()

            # modifying the composition is safe until it is added to this composition.
            canvas_item_composition = CanvasItem.CanvasItemComposition()
            canvas_item_composition.wants_mouse_events = True
            canvas_item_composition.layout = CanvasItem.CanvasItemColumnLayout()
            canvas_item_composition.add_canvas_item(metadata_editor_canvas_item)
            canvas_item_composition.add_stretch()
            self.__metadata_editor_canvas_item = metadata_editor_canvas_item

            # the canvas_bounds at this point does not represent the size of the reconstructed metadata editor.
            # so use the explicit size of the metadata editor to lay out the new composition.
            canvas_item_composition.update_layout(self.canvas_origin, metadata_editor_canvas_item_size)
            canvas_item_composition.repaint_immediate(drawing_context, metadata_editor_canvas_item_size)

            canvas_item_composition._set_owner_thread(threading.main_thread())

            self.replace_canvas_items([canvas_item_composition])

            if callable(self.on_content_size_changed):
                if metadata_editor_canvas_item.canvas_size:
                    self.on_content_size_changed(metadata_editor_canvas_item.canvas_size)

            # end = time.perf_counter_ns()
            # print(f"reconstruct {(end - start) / 1000}us")

    def _trigger(self) -> None:
        with self.__thread_lock:
            self.__pending = True  # pending even if not visible.
            if self.root_container and (canvas_widget := getattr(self.root_container, "canvas_widget", None)):
                self.__visible = typing.cast(UserInterface.DockWidget, typing.cast(UserInterface.CanvasWidget, canvas_widget).root_container).visible
                if self.__visible:
                    # only launch thread if visible and not already running.
                    if not self.__thread_future:
                        self.__thread_future = ThreadedCanvasItem._executor.submit(self.__draw_thread)

    # def _repaint_template(self, drawing_context: DrawingContext.DrawingContext, immediate: bool) -> None:
    #     start = time.perf_counter_ns()
    #     super()._repaint_template(drawing_context, immediate)
    #     end = time.perf_counter_ns()
    #     print(f"repaint {(end - start) / 1000}us")


class ThreadHelper:
    def __init__(self, event_loop: asyncio.AbstractEventLoop) -> None:
        self.__event_loop = event_loop
        self.__pending_calls: typing.Dict[str, asyncio.Handle] = dict()

    def close(self) -> None:
        for handle in self.__pending_calls.values():
            handle.cancel()
        self.__pending_calls = dict()

    def call_on_main_thread(self, key: str, func: typing.Callable[[], None]) -> None:
        if threading.current_thread() != threading.main_thread():
            handle = self.__pending_calls.pop(key, None)
            if handle:
                handle.cancel()
            def audited_func() -> None:
                with Process.audit(f"threadhelper.{key}"):
                    func()
            self.__pending_calls[key] = self.__event_loop.call_soon_threadsafe(audited_func)
        else:
            func()


class MetadataPanel(Panel.Panel):
    """Provide a panel to edit metadata."""

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: typing.Mapping[str, typing.Any]) -> None:
        super().__init__(document_controller, panel_id, _("Metadata"))

        ui = self.ui

        self.__metadata_model = MetadataModel(document_controller)
        self.__thread_helper = ThreadHelper(document_controller.event_loop)

        delegate = MetadataEditorTreeDelegate()

        def content_size_changed(content_size: Geometry.IntSize) -> None:
            def _content_height_changed() -> None:
                # start = time.perf_counter_ns()

                # the code below will do the upstream part of the line below. we can't use the line below
                # because it will lay out the children again.
                # metadata_editor_canvas_item.update_layout(Geometry.IntPoint(), content_size)

                # leave the canvas origin alone so the scroll bars are at the same place
                # metadata_editor_canvas_item._set_canvas_origin(Geometry.IntPoint())

                # set the content size and send it on up so the scroll area sees it.
                metadata_editor_canvas_item._set_canvas_size(content_size)
                if callable(metadata_editor_canvas_item.on_layout_updated):
                    metadata_editor_canvas_item.on_layout_updated(metadata_editor_canvas_item.canvas_origin, metadata_editor_canvas_item.canvas_size, False)

                # end = time.perf_counter_ns()
                # print(f"height change {(end - start) / 1000}us")
            self.__thread_helper.call_on_main_thread("_content_height_changed", _content_height_changed)

        metadata_editor_canvas_item = ThreadedCanvasItem(ui.get_font_metrics, delegate, content_size_changed)

        self.__metadata_editor_canvas_item = metadata_editor_canvas_item

        scroll_area_canvas_item = CanvasItem.ScrollAreaCanvasItem(metadata_editor_canvas_item)
        # scroll_area_canvas_item.auto_resize_contents = True
        scroll_group_canvas_item = CanvasItem.CanvasItemComposition()
        vertical_scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(scroll_area_canvas_item)
        horizontal_scroll_bar_canvas_item = CanvasItem.ScrollBarCanvasItem(scroll_area_canvas_item, CanvasItem.Orientation.Horizontal)
        scroll_group_canvas_item.layout = CanvasItem.CanvasItemGridLayout(Geometry.IntSize(width=2, height=2))
        scroll_group_canvas_item.add_canvas_item(scroll_area_canvas_item, Geometry.IntPoint(x=0, y=0))
        scroll_group_canvas_item.add_canvas_item(vertical_scroll_bar_canvas_item, Geometry.IntPoint(x=1, y=0))
        scroll_group_canvas_item.add_canvas_item(horizontal_scroll_bar_canvas_item, Geometry.IntPoint(x=0, y=1))

        metadata_editor_widget = ui.create_canvas_widget()
        metadata_editor_widget.canvas_item.layout = CanvasItem.CanvasItemColumnLayout()
        metadata_editor_widget.canvas_item.add_canvas_item(scroll_group_canvas_item)

        column = self.ui.create_column_widget(properties={"size-policy-horizontal": "expanding", "size-policy-vertical": "expanding"})
        column.add(metadata_editor_widget)

        def metadata_source_changed(metadata_source: MetadataSource) -> None:
            delegate.metadata_source = metadata_source

            def reconstruct_metadata() -> None:
                if self.__metadata_editor_canvas_item:  # use this instead of local variable to handle close properly
                    self.__metadata_editor_canvas_item._trigger()

            self.document_controller.queue_task(reconstruct_metadata)

        self.__metadata_changed_event_listener = self.__metadata_model.metadata_changed_event.listen(metadata_source_changed)

        self.widget = column

    def close(self) -> None:
        self.__thread_helper.close()
        self.__thread_helper = typing.cast(typing.Any, None)
        self.__metadata_editor_canvas_item = typing.cast(typing.Any, None)
        self.__metadata_changed_event_listener.close()
        self.__metadata_changed_event_listener = typing.cast(typing.Any, None)
        self.__metadata_model.close()
        self.__metadata_model = typing.cast(typing.Any, None)
        super().close()

    @property
    def _metadata_editor_canvas_item_for_testing(self) -> TreeCanvasItem.TreeCanvasItem:
        return typing.cast(TreeCanvasItem.TreeCanvasItem, self.__metadata_editor_canvas_item.canvas_items[0].canvas_items[0])

    @property
    def _metadata_model_for_testing(self) -> MetadataModel:
        return self.__metadata_model
