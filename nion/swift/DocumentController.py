from __future__ import annotations

# standard libraries
import copy
import functools
import gettext
import itertools
import logging
import json
import math
import operator
import os.path
import pathlib
import pkgutil
import sys
import threading
import time
import traceback
import typing
import uuid
import weakref

from nion.data import DataAndMetadata
from nion.swift import ComputationPanel
from nion.swift import ConsoleDialog
from nion.swift import DisplayEditorPanel
from nion.swift import DisplayPanel
from nion.swift import ExportDialog
from nion.swift import FilterPanel
from nion.swift import MimeTypes
from nion.swift import RecorderPanel
from nion.swift import ScriptsDialog
from nion.swift import Task
from nion.swift import Undo
from nion.swift import Workspace
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import ImportExportManager
from nion.swift.model import Processing
from nion.swift.model import Project
from nion.swift.model import Symbolic
from nion.ui import CanvasItem
from nion.ui import Dialog
from nion.ui import PreferencesDialog
from nion.ui import Window
from nion.ui import UserInterface
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel
from nion.utils import Registry
from nion.utils import Selection

if typing.TYPE_CHECKING:
    from nion.swift import Application


_ = gettext.gettext


class DocumentController(Window.Window):
    """Manage a document window."""
    count = 0  # useful for detecting leaks in tests

    def __init__(self, ui, document_model, workspace_id=None, app: "Application.Application" = None):
        super().__init__(ui, app)
        self.__class__.count += 1

        self.__undo_stack = Undo.UndoStack()

        if not app:
            self.event_loop.has_no_pulse = True

        self.__closed = False  # debugging

        self.uuid = uuid.uuid4()

        self.task_created_event = Event.Event()
        self.cursor_changed_event = Event.Event()
        self.tool_mode_changed_event = Event.Event()

        self.__last_activity = None

        # document_model may be shared between several DocumentControllers, so use reference counting
        # to determine when to close it.
        self.document_model = document_model
        self.document_model.add_ref()
        self.title = _("Nion Swift")
        self.__workspace_controller = None
        self.replaced_display_panel_content = None  # used to facilitate display panel functionality to exchange displays
        self.__weak_selected_display_panel = None
        self.__tool_mode = "pointer"
        self.__weak_periodic_listeners = []
        self.__weak_periodic_listeners_mutex = threading.RLock()

        self.selection = Selection.IndexedSelection()
        self.selection.expanded_changed_event = True

        # the user has two ways of filtering data items: first by selecting a data group (or none) in the data panel,
        # and next by applying a custom filter to the items from the items resulting in the first selection.
        # data items model tracks the main list of items selected in the data panel.
        # filtered display items model tracks the filtered items from those in data items model.
        self.__display_items_model = ListModel.FilteredListModel(container=self.document_model, items_key="display_items")
        self.__display_items_model.filter_id = None  # extra tracking field
        self.__filtered_display_items_model = ListModel.FilteredListModel(items_key="display_items", container=self.__display_items_model)
        self.__last_display_filter = ListModel.Filter(True)
        self.filter_changed_event = Event.Event()

        # see set_filter
        with self.__display_items_model.changes():  # change filter and sort together
            self.__display_items_model.container = self.document_model
            self.__display_items_model.filter = ListModel.AndFilter((self.project_filter, self.get_filter_predicate(None)))
            self.__display_items_model.sort_key = DataItem.sort_by_date_key
            self.__display_items_model.sort_reverse = True
            self.__display_items_model.filter_id = None

        def call_soon():
            # call the function (this is guaranteed to be called on the main thread)
            self.document_model.perform_call_soon()

        def queue_call_soon():
            # queue the function on the main thread
            self.queue_task(call_soon)

        # listen for requests from the document model to call a function on the main thread.
        self.__call_soon_event_listener = self.document_model.call_soon_event.listen(queue_call_soon)

        self.document_model.perform_all_call_soon()  # perform any pending items in the queue

        self.filter_controller = FilterPanel.FilterController(self)

        self.focused_display_item_changed_event = Event.Event()
        self.__focused_display_item = None
        self.__selected_display_items: typing.List[DisplayItem.DisplayItem] = list()
        self.__selected_display_item: typing.Optional[DisplayItem.DisplayItem] = None
        self.__selection_changed_listener = self.selection.changed_event.listen(self.__update_selected_display_items)

        self.__consoles = list()

        self._create_menus()
        if workspace_id:  # used only when testing reference counting
            self.__workspace_controller = Workspace.Workspace(self, workspace_id)
            self.__workspace_controller.restore(self.project.workspace_uuid)

        if app:
            for menu_handler in app.menu_handlers:  # use 'handler' to avoid name collision
                menu_handler(self)

    def close(self):
        """Close the document controller.

        This method must be called to shut down the document controller. There are several
        paths by which it can be called, though.

           * User quits application via menu item. The menu item will call back to Application.exit which will close each
             document controller by calling this method.
           * User quits application using dock menu item. The Qt application will call aboutToClose in the document windows
           * User closes document window via menu item.
           * User closes document window via close box.

        The main concept of closing is that it is always triggered by the document window closing. This can be initiated
        from within Python by calling request_close on the document window. When the window closes, either by explicit request
        or by the user clicking a close box, it will invoke the about_to_close method on the document window. At this point,
        the window would still be open, so the about_to_close message can be used to tell the document controller to save anything
        it needs to save and prepare for closing.
        """
        assert self.__closed == False
        self.__closed = True
        self._finish_periodic()  # required to finish periodic operations during tests
        # dialogs
        self._close_dialogs()
        if self.__workspace_controller:
            self.__workspace_controller.close()
            self.__workspace_controller = None
        self.__selection_changed_listener.close()
        self.__selection_changed_listener = None
        self.__call_soon_event_listener.close()
        self.__call_soon_event_listener = None
        self.__filtered_display_items_model.close()
        self.__filtered_display_items_model = None
        self.filter_controller.close()
        self.filter_controller = None
        self.__display_items_model.close()
        self.__display_items_model = None
        # document_model may be shared between several DocumentControllers, so use reference counting
        # to determine when to close it.
        self.document_model.remove_ref()
        self.document_model = None
        self.__class__.count -= 1
        super().close()

    def _register_ui_activity(self):
        self.__last_activity = time.time()

    def about_to_show(self):
        geometry, state = self.workspace_controller.restore_geometry_state()
        self.restore(geometry, state)

    def about_to_close(self, geometry, state):
        if self.workspace_controller:
            self.workspace_controller.save_geometry_state(geometry, state)
        super().about_to_close(geometry, state)

    def register_console(self, console):
        self.__consoles.append(console)

    def unregister_console(self, console):
        self.__consoles.remove(console)

    def _create_menus(self):
        # don't use default implementation

        processing_component_menu_items = list()

        processing_components = list()
        for processing_component in typing.cast(typing.Sequence[Processing.ProcessingBase], Registry.get_components_by_type("processing-component")):
            if "windows" in processing_component.sections:
                processing_components.append(processing_component)
        if processing_components:
            processing_component_menu_items.append({"type": "separator"})
            for processing_component in sorted(processing_components, key=operator.attrgetter("title")):
                processing_component_menu_items.append({"type": "item", "action_id": "processing." + processing_component.processing_id})

        try:
            menu_descriptions = json.loads(pkgutil.get_data(__name__, "resources/menu_config.json").decode("utf8"))
        except Exception as e:
            logging.error("Could not read menu configuration.")

        # hack to build the dynamic filter section until nionui supplies a better way to do this
        for m in menu_descriptions:
            if m["menu_id"] == "processing":
                for sm in m["items"]:
                    if sm.get("menu_id") == "processing_fourier":
                        for i, mi in enumerate(sm["items"]):
                            if mi.get("action_id") == "processing.fourier_filter":
                                for processing_component_menu_item in reversed(processing_component_menu_items):
                                    sm["items"].insert(i + 1, processing_component_menu_item)
                                break

        self.build_menu(None, menu_descriptions)

        self.__data_menu_actions: typing.List[UserInterface.MenuAction] = list()

        self.__dynamic_live_actions: typing.List[UserInterface.MenuAction] = []

        self.__dynamic_view_actions: typing.List[UserInterface.MenuAction] = []

        self.__dynamic_window_actions: typing.List[UserInterface.MenuAction] = []

    def get_menu(self, menu_id):
        assert menu_id.endswith("_menu")
        return getattr(self, menu_id, None)

    def get_or_create_menu(self, menu_id, menu_title, before_menu_id):
        assert menu_id.endswith("_menu")
        assert before_menu_id.endswith("_menu") if before_menu_id is not None else True
        if not hasattr(self, "_" + menu_id):
            before_menu = getattr(self, "_" + before_menu_id) if before_menu_id is not None else None
            menu = self.insert_menu(menu_title, before_menu)
            setattr(self, "_" + menu_id, menu)
        return getattr(self, "_" + menu_id)

    def show_about_box(self):
        version_str = self.app.version_str if self.app else str()
        root_dir = os.path.dirname((os.path.dirname(os.path.abspath(__file__))))
        path_ascend_count = 2
        for i in range(path_ascend_count):
            root_dir = os.path.dirname(root_dir)
        class AboutDialog(Dialog.OkCancelDialog):
            def __init__(self, ui: UserInterface.UserInterface, parent_window: Window.Window):
                super().__init__(ui, include_cancel=False, parent_window=parent_window)
                row = self.ui.create_row_widget()
                logo_column = self.ui.create_column_widget()
                logo_button = self.ui.create_push_button_widget()
                logo_button.icon = CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/logo3.png"))
                logo_column.add_spacing(26)
                logo_column.add(logo_button)
                logo_column.add_stretch()
                column = self.ui.create_column_widget()

                def make_label_row(label: str):
                    row_one = self.ui.create_row_widget()
                    row_one.add_spacing(13)
                    row_one.add(self.ui.create_label_widget(label))
                    row_one.add_spacing(13)
                    row_one.add_stretch()
                    return row_one

                column.add_spacing(26)
                column.add(make_label_row("Nion Swift {0} {1}".format(version_str, root_dir)))
                column.add(make_label_row("Copyright 2012-2019 Nion Co. All Rights Reserved."))
                column.add_spacing(26)
                column.add(make_label_row(sys.base_prefix))
                conda_path = pathlib.Path(sys.base_prefix) / "conda-meta"
                if conda_path.is_dir():
                    needs_spacing = True
                    for package in sorted(path.stem for path in conda_path.glob("*.json")):
                        if any(s in package for s in ["nion", "python", "scipy", "numpy", "pytz", "h5py"]):
                            if needs_spacing:
                                column.add_spacing(26)
                                needs_spacing = False
                            column.add(make_label_row(package))
                column.add_spacing(26)
                column.add_stretch()
                row.add(logo_column)
                row.add(column)
                self.content.add(row)

        about_dialog = AboutDialog(self.ui, self)
        about_dialog.show()

    def find_dock_panel(self, dock_panel_id) -> typing.Optional[UserInterface.DockWidget]:
        """ Return the dock widget by id. """
        return self.workspace_controller._find_dock_panel(dock_panel_id)

    def add_periodic(self, interval: float, listener_fn):
        """Add a listener function and return listener token. Token can be closed or deleted to unlisten."""
        class PeriodicListener:
            def __init__(self, interval: float, listener_fn):
                self.interval = interval
                self.__listener_fn = listener_fn
                # the call function is very performance critical; make it fast by using a property
                # instead of a logic statement each time.
                if callable(listener_fn):
                    self.call = self.__listener_fn
                else:
                    def void(*args, **kwargs):
                        pass
                    self.call = void
                self.next_scheduled_time = time.time() + interval
            def close(self):
                self.__listener_fn = None
                def void(*args, **kwargs):
                    pass
                self.call = void
        listener = PeriodicListener(interval, listener_fn)
        def remove_listener(weak_listener):
            with self.__weak_periodic_listeners_mutex:
                self.__weak_periodic_listeners.remove(weak_listener)
        weak_listener = weakref.ref(listener, remove_listener)
        with self.__weak_periodic_listeners_mutex:
            self.__weak_periodic_listeners.append(weak_listener)
        return listener

    def periodic(self):
        with self.__weak_periodic_listeners_mutex:
            periodic_listeners = copy.copy(self.__weak_periodic_listeners)
        current_time = time.time()
        for weak_periodic_listener in periodic_listeners:
            periodic_listener = weak_periodic_listener()
            if periodic_listener and current_time >= periodic_listener.next_scheduled_time:
                try:
                    periodic_listener.call()
                except Exception as e:
                    import traceback
                    logging.debug("Event Error: %s", e)
                    traceback.print_exc()
                    traceback.print_stack()
                periodic_listener.next_scheduled_time = current_time + periodic_listener.interval
        super().periodic()
        self.document_model.perform_data_item_updates()
        if self.workspace_controller:
            self.workspace_controller.periodic()
        if self.__last_activity is not None and time.time() - self.__last_activity > 60 * 60:
            pass  # self.app.choose_library()

    @property
    def _undo_stack(self):
        return self.__undo_stack

    @property
    def last_undo_command(self) -> typing.Optional[Undo.UndoableCommand]:
        return self.__undo_stack.last_command

    def push_undo_command(self, undo_command: Undo.UndoableCommand) -> None:
        if undo_command:
            self.__undo_stack.push(undo_command)
        else:
            self.__undo_stack.clear()

    def pop_undo_command(self) -> typing.Optional[Undo.UndoableCommand]:
        return self.__undo_stack.pop_command()

    @property
    def workspace_controller(self):
        return self.__workspace_controller

    @property
    def workspace(self):
        return self.__workspace_controller

    def refocus_widget(self, widget):
        display_panel = self.selected_display_panel
        if display_panel:
            display_panel.request_focus()
        else:
            super().refocus_widget(widget)

    def request_refocus(self):
        display_panel = self.selected_display_panel
        if display_panel:
            display_panel.request_focus()

    @property
    def project(self) -> Project.Project:
        return self.document_model._project

    @property
    def display_items_model(self):
        return self.__display_items_model

    @property
    def filtered_display_items_model(self):
        return self.__filtered_display_items_model

    def get_filter_predicate(self, filter_id: typing.Optional[str]) -> ListModel.Filter:
        if filter_id == "latest-session":
            return ListModel.EqFilter("session_id", self.document_model.session_id)
        elif filter_id == "temporary":
            return ListModel.NotEqFilter("category", "persistent")
        elif filter_id == "persistent":
            return ListModel.EqFilter("category", "persistent")
        elif filter_id == "none":  # not intended to be used directly
            return ListModel.Filter(False)
        else:  # "all"
            return ListModel.Filter(True)

    def set_data_group(self, data_group: DataGroup.DataGroup) -> None:
        if self.__display_items_model is not None:
            container = data_group if data_group else self.document_model
            if container != self.__display_items_model.container:
                with self.__display_items_model.changes():  # change filter and sort together
                    self.__display_items_model.container = data_group
                    self.__display_items_model.filter = self.project_filter
                    self.__display_items_model.sort_key = None
                    self.__display_items_model.filter_id = None
                self.filter_changed_event.fire(data_group, self.__display_items_model.filter_id)

    def set_filter(self, filter_id: typing.Optional[str]) -> None:
        if self.__display_items_model is not None:
            if filter_id != self.__display_items_model.filter_id:
                with self.__display_items_model.changes():  # change filter and sort together
                    self.__display_items_model.container = self.document_model
                    self.__display_items_model.filter = ListModel.AndFilter((self.project_filter, self.get_filter_predicate(filter_id)))
                    self.__display_items_model.sort_key = DataItem.sort_by_date_key
                    self.__display_items_model.sort_reverse = True
                    self.__display_items_model.filter_id = filter_id
                self.filter_changed_event.fire(None, filter_id)

    def get_data_group_and_filter_id(self) -> typing.Tuple[typing.Optional[DataGroup.DataGroup], typing.Optional[str]]:
        # used for display panel initialization
        data_group = typing.cast(DataGroup.DataGroup, self.__display_items_model.container) if self.__display_items_model.container != self.document_model else None
        filter_id = self.__display_items_model.filter_id
        return data_group, filter_id

    @property
    def display_filter(self) -> ListModel.Filter:
        return self.__filtered_display_items_model.filter

    @display_filter.setter
    def display_filter(self, display_filter: ListModel.Filter) -> None:
        if self.__filtered_display_items_model is not None:  # during close
            self.__filtered_display_items_model.filter = display_filter

    @property
    def project_filter(self) -> ListModel.Filter:
        return self.project.project_filter

    @property
    def selected_display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        """Return the selected display item.

        The selected display is the display ite that has keyboard focus in the data panel or a display panel.
        """
        return self.__selected_display_item

    @property
    def selected_data_item(self) -> typing.Optional[DataItem.DataItem]:
        selected_display_item = self.selected_display_item
        return selected_display_item.data_item if selected_display_item else None

    @property
    def selected_display_items(self) -> typing.List[DisplayItem.DisplayItem]:
        """Return the selected display items.

        The selected display items are the display items that have keyboard focus in the display panel
         or the data panel.
        """
        return list(self.__selected_display_items)  # copy

    @property
    def selected_data_items(self) -> typing.List[DataItem.DataItem]:
        selected_data_items = list()
        for display_item in self.selected_display_items:
            for data_item in display_item.data_items:
                if not data_item in selected_data_items:
                    selected_data_items.append(data_item)
        return selected_data_items

    # when the focused display panel or focused data panel changes or when the selection in
    # one of those items changes, this is called to figure out the new selected display items
    # and issue notifications if changed. if the selected display panel is not None, it gets
    # gets the display items from the display panel, otherwise it gets them from the data panel.
    def __update_selected_display_items(self) -> None:
        old_selected_display_item = self.__selected_display_item
        display_panel = self.selected_display_panel
        if display_panel:
            self.__selected_display_items = display_panel.display_items
        else:
            self.__selected_display_items = list()
            display_items = self.__filtered_display_items_model.display_items
            for index in self.selection.ordered_indexes:
                self.__selected_display_items.append(display_items[index])
        if len(self.__selected_display_items) == 1:
            self.__selected_display_item = next(iter(self.__selected_display_items))
        else:
            self.__selected_display_item = None
        if self.__selected_display_item != old_selected_display_item:
            self.focused_display_item_changed_event.fire(self.__selected_display_item)

    def select_display_items_in_data_panel(self, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> None:
        filtered_display_items = self.filtered_display_items_model.display_items
        indexes = set()
        for index, display_item in enumerate(filtered_display_items):
            if display_item in display_items:
                indexes.add(index)
        self.selection.set_multiple(indexes)
        if len(display_items) > 0:
            display_item = display_items[0]
            if display_item in filtered_display_items:
                self.selection.anchor_index = filtered_display_items.index(display_item)

    def select_data_items_in_data_panel(self, data_items: typing.Sequence[DataItem.DataItem]) -> None:
        document_model = self.document_model
        associated_display_items = [document_model.get_display_item_for_data_item(data_item) for data_item in data_items]
        self.select_display_items_in_data_panel(associated_display_items)

    # track the selected data item. this can be called by ui elements when
    # they get focus. the selected data item will stay the same until another ui
    # element gets focus or the data item is removed from the document.
    def notify_focused_display_changed(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        if self.__focused_display_item != display_item:
            self.__focused_display_item = display_item
            self.focused_display_item_changed_event.fire(display_item)

    @property
    def focused_display_item(self) -> DisplayItem.DisplayItem:
        """Return the display with keyboard focus."""
        return self.__selected_display_item

    def select_data_item_in_data_panel(self, data_item: DataItem.DataItem) -> None:
        """Select the data item in the data panel."""
        self.select_data_items_in_data_panel([data_item] if data_item else [])

    def select_data_group_in_data_panel(self, data_group: DataGroup.DataGroup, data_item: DataItem.DataItem=None) -> None:
        # used for testing only
        self.set_data_group(data_group)
        self.select_data_item_in_data_panel(data_item)

    def select_filter_in_data_panel(self, filter_id: str) -> None:
        # used for testing only
        self.set_filter(filter_id)

    def delete_display_items(self, display_items: typing.Sequence[DisplayItem.DisplayItem], container=None) -> None:
        container = container if container else self.__display_items_model.container
        if container is self.document_model:
            if display_items:
                command = self.create_remove_display_items_command(display_items)
                command.perform()
                self.push_undo_command(command)
        elif isinstance(container, DataGroup.DataGroup):
            if display_items:
                command = DocumentController.RemoveDataGroupDisplayItemsCommand(self.document_model, container, display_items)
                command.perform()
                self.push_undo_command(command)

    def delete_data_items(self, data_items: typing.Sequence[DataItem.DataItem]) -> None:
        if data_items:
            command = self.create_remove_data_items_command(data_items)
            command.perform()
            self.push_undo_command(command)

    def register_display_panel(self, display_panel: DisplayPanel.DisplayPanel) -> None:
        pass

    def unregister_display_panel(self, display_panel: DisplayPanel.DisplayPanel) -> None:
        if self.selected_display_panel == display_panel:
            self.selected_display_panel = None

    @property
    def selected_display_panel(self) -> typing.Optional[DisplayPanel.DisplayPanel]:
        return self.__weak_selected_display_panel() if self.__weak_selected_display_panel else None

    @selected_display_panel.setter
    def selected_display_panel(self, selected_display_panel: typing.Optional[DisplayPanel.DisplayPanel]) -> None:
        weak_selected_display_panel = weakref.ref(selected_display_panel) if selected_display_panel else None
        if weak_selected_display_panel != self.__weak_selected_display_panel:
            # save the selected panel
            self.__weak_selected_display_panel = weak_selected_display_panel
            # tell the workspace the selected image panel changed so that it can update the focus/selected rings
            self.workspace_controller.selected_display_panel_changed(self.selected_display_panel)
            # update the selected display items
            self.__update_selected_display_items()
        self.__selection_changed_listener.close()
        if self.selected_display_panel:
            self.__selection_changed_listener = self.selected_display_panel.display_items_changed_event.listen(self.__update_selected_display_items)
        else:
            self.__selection_changed_listener = self.selection.changed_event.listen(self.__update_selected_display_items)

    def data_panel_focused(self) -> None:
        # the data panel will call this when it gets keyboard focus.
        # deselect the selected display panel and update the selected display items.
        self.selected_display_panel = None
        self.__update_selected_display_items()

    def next_result_display_panel(self):
        for display_panel in self.workspace.display_panels:
            if display_panel.is_result_panel:
                return display_panel
        return None

    # this can be called from any user interface element that wants to update the cursor info
    # in the data panel. this would typically be from the image or line plot canvas.
    def cursor_changed(self, text_items: typing.List[str]) -> None:
        self.cursor_changed_event.fire(text_items)

    @property
    def tool_mode(self):
        return self.__tool_mode

    @tool_mode.setter
    def tool_mode(self, tool_mode):
        self.__tool_mode = tool_mode
        self.tool_mode_changed_event.fire(tool_mode)

    def _import_folder(self):
        documents_dir = self.ui.get_document_location()
        workspace_dir, directory = self.ui.get_existing_directory_dialog(_("Choose Image Folder"), documents_dir)
        absolute_file_paths = set()
        for root, dirs, files in os.walk(workspace_dir):
            absolute_file_paths.update([os.path.join(root, data_file) for data_file in files])
        readable_file_paths = list()
        readers = ImportExportManager.ImportExportManager().get_readers()
        for file_path in absolute_file_paths:
            root, extension = os.path.splitext(file_path)
            for reader in readers:
                if extension[1:] in reader.extensions:
                    readable_file_paths.append(file_path)
                    break  # skip other readers
        self.receive_files(readable_file_paths)

    def import_file(self):
        # present a loadfile dialog to the user
        readers = ImportExportManager.ImportExportManager().get_readers()
        all_extensions = []
        for reader_extension_list in [reader.extensions for reader in readers]:
            all_extensions.extend(reader_extension_list)
        filter = "All Readable Files (" + " ".join(["*."+extension for extension in all_extensions]) + ")"
        filter += ";;" + ";;".join(
            [reader.name + " files (" + " ".join(
                ["*."+extension for extension in reader.extensions])
             + ")" for reader in readers])
        filter += ";;All Files (*.*)"
        import_dir = self.ui.get_persistent_string("import_directory", "")
        paths, selected_filter, selected_directory = self.get_file_paths_dialog(_("Import File(s)"), import_dir, filter)
        self.ui.set_persistent_string("import_directory", selected_directory)
        self.receive_files(paths, display_panel=self.next_result_display_panel())

    def export_file(self, display_item: DisplayItem.DisplayItem) -> None:
        # present a loadfile dialog to the user
        writers = ImportExportManager.ImportExportManager().get_writers_for_display_item(display_item)
        name_writer_dict = dict()
        for writer in writers:
            writer_key = (writer.name, " ".join(["*." + extension for extension in writer.extensions]))
            name_writer_dict.setdefault(writer_key, writer)
        # make a list of tuples (writer name, writer extensions, writer) from the name_writer_dict
        name_writer_list = (key + (name_writer_dict[key],) for key in sorted(name_writer_dict.keys()))
        filter_line_to_writer_map = dict()
        filter_lines = list()
        for writer_name, writer_extensions, writer in name_writer_list:
            filter_line = writer_name + " files (" + writer_extensions + ")"
            filter_lines.append(filter_line)
            filter_line_to_writer_map[filter_line] = writer
        filter = ";;".join(filter_lines)
        filter += ";;All Files (*.*)"
        export_dir = self.ui.get_persistent_string("export_directory", self.ui.get_document_location())
        export_dir = os.path.join(export_dir, display_item.displayed_title)
        selected_filter = self.ui.get_persistent_string("export_filter")
        path, selected_filter, selected_directory = self.get_save_file_path(_("Export File"), export_dir, filter, selected_filter)
        selected_writer = filter_line_to_writer_map.get(selected_filter)
        if path and not os.path.splitext(path)[1]:
            if selected_writer:
                path = path + os.path.extsep + selected_writer.extensions[0]
        if selected_writer and path:
            self.ui.set_persistent_string("export_directory", selected_directory)
            self.ui.set_persistent_string("export_filter", selected_filter)
            ImportExportManager.ImportExportManager().write_display_item_with_writer(self.ui, selected_writer, display_item, path)

    def export_files(self, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> None:
        if len(display_items) > 1:
            export_dialog = ExportDialog.ExportDialog(self.ui, self)
            export_dialog.on_accept = functools.partial(export_dialog.do_export, display_items)
            export_dialog.show()
        elif len(display_items) == 1:
            self.export_file(display_items[0])

    def export_svg(self, display_item: DisplayItem.DisplayItem) -> None:
        filter = "SVG File (*.svg);;All Files (*.*)"
        export_dir = self.ui.get_persistent_string("export_directory", self.ui.get_document_location())
        export_dir = os.path.join(export_dir, display_item.displayed_title)
        path, selected_filter, selected_directory = self.get_save_file_path(_("Export File"), export_dir, filter, None)
        if path and not os.path.splitext(path)[1]:
            path = path + os.path.extsep + "svg"
        if path:
            self.ui.set_persistent_string("export_directory", selected_directory)

            if display_item.display_data_shape and len(display_item.display_data_shape) == 2:
                display_shape = Geometry.IntSize(height=800, width=800)
            else:
                display_shape = Geometry.IntSize(height=600, width=800)

            drawing_context, shape = DisplayPanel.preview(DisplayPanel.FixedUISettings(), display_item, display_shape.width, display_shape.height)

            view_box = Geometry.IntRect(Geometry.IntPoint(), shape)

            svg = drawing_context.to_svg(shape, view_box)

            temp_filepath = path + ".temp"
            with open(temp_filepath, "w") as fp:
                fp.write(svg)
            os.replace(temp_filepath, path)

    # this method creates a task. it is thread safe.
    def create_task_context_manager(self, title, task_type, logging=True):
        task = Task.Task(title, task_type)  # NOTE: currently, tasks don't get deleted since they are displayed until exit.
        task_context_manager = Task.TaskContextManager(self, task, logging)
        self.task_created_event.fire(task)
        return task_context_manager

    def open_preferences(self):
        if not self.is_dialog_type_open(PreferencesDialog.PreferencesDialog):
            preferences_dialog = PreferencesDialog.PreferencesDialog(self.ui, self.app)
            preferences_dialog.show()

    def new_interactive_script_dialog(self):
        interactive_dialog = ScriptsDialog.RunScriptDialog(self)
        interactive_dialog.show()

    def new_console_dialog(self):
        console_dialog = ConsoleDialog.ConsoleDialog(self)
        console_dialog.show()

    def new_edit_computation_dialog(self) -> None:
        data_item = self.selected_data_item
        if data_item:
            edit_computation_dialog = ComputationPanel.EditComputationDialog(self, data_item)
            edit_computation_dialog.show()

    def new_inspect_computation_dialog(self) -> None:
        document_model = self.document_model
        display_item = self.selected_display_item
        if display_item:
            match_items = set()
            match_items.add(display_item)
            match_items.update(display_item.data_items)
            match_items.update(display_item.graphics)
            computations_set = set()
            for computation in document_model.computations:
                if computation.output_items.intersection(match_items):
                    computations_set.add(computation)
            computations = list(computations_set)
            if len(computations) > 1:
                def handle_selection(computation: typing.Optional[Symbolic.Computation]) -> None:
                    if computation:
                        ComputationPanel.InspectComputationDialog(self, computation)

                Dialog.pose_select_item_pop_up(computations, handle_selection,
                                               window=self, current_item=0,
                                               item_getter=operator.attrgetter("label"))
            else:
                computation = next(iter(computations)) if len(computations) == 1 else None
                ComputationPanel.InspectComputationDialog(self, computation)

    def new_display_editor_dialog(self, display_item: DisplayItem.DisplayItem=None):
        if not display_item:
            display_item = self.selected_display_item
        if display_item:
            edit_display_dialog = DisplayEditorPanel.DisplayEditorDialog(self, display_item)
            edit_display_dialog.show()

    def new_recorder_dialog(self, data_item=None):
        if not data_item:
            data_item = self.selected_data_item
        if data_item:
            recorder_dialog = RecorderPanel.RecorderDialog(self, data_item)
            recorder_dialog.show()

    def __deep_copy(self):
        self._dispatch_any_to_focus_widget("handle_deep_copy")

    def handle_undo(self):
        if self.__undo_stack.can_undo:
            self.__undo_stack.undo()

    def get_undo_menu_item_state(self):
        self.__undo_stack.validate()
        return UserInterface.MenuItemState(title=self.__undo_stack.undo_title, enabled=self.__undo_stack.can_undo, checked=False)

    def handle_redo(self):
        if self.__undo_stack.can_redo:
            self.__undo_stack.redo()

    def get_redo_menu_item_state(self):
        return UserInterface.MenuItemState(title=self.__undo_stack.redo_title, enabled=self.__undo_stack.can_redo, checked=False)

    def handle_copy(self):
        self.copy_selected_graphics()

    def handle_cut(self):
        self.copy_selected_graphics()
        self.remove_selected_graphics()

    def handle_paste(self):
        display_item = self.selected_display_item
        if display_item:
            mime_data = self.ui.clipboard_mime_data()
            graphics = MimeTypes.mime_data_get_graphics(mime_data)
            if graphics:
                display_item.graphic_selection.clear()
                command = DisplayPanel.InsertGraphicsCommand(self, display_item, graphics)
                command.perform()
                self.push_undo_command(command)
                for graphic in graphics:
                    display_item.graphic_selection.add(display_item.graphics.index(graphic))
                return True
            display_item_to_paste = MimeTypes.mime_data_get_display_item(mime_data, self.document_model)
            data_item_to_paste = display_item_to_paste.data_item if display_item else None
            if data_item_to_paste:
                command = DisplayPanel.AppendDisplayDataChannelCommand(self.document_model, display_item, data_item_to_paste)
                command.perform()
                self.push_undo_command(command)
        return False

    def handle_delete(self):
        # delete key gets handled by key handlers, but this method gets called by menu items
        self.remove_selected_graphics()

    class InsertDataGroupDisplayItemsCommand(Undo.UndoableCommand):
        def __init__(self, document_model, data_group: DataGroup.DataGroup, before_index: int, display_items: typing.Sequence[DisplayItem.DisplayItem]):
            super().__init__("Insert Data Items")
            self.__document_model = document_model
            self.__data_group_proxy = data_group.create_proxy()
            self.__before_index = before_index
            self.__display_item_proxies = [display_item.create_proxy() for display_item in display_items]
            self.initialize()

        def close(self):
            self.__document_model = None
            self.__data_group_proxy.close()
            self.__data_group_proxy = None
            self.__before_index = None
            for display_item_proxy in self.__display_item_proxies:
                display_item_proxy.close()
            self.__display_item_proxies = None
            super().close()

        def _get_modified_state(self):
            data_group = self.__data_group_proxy.item
            return data_group.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            data_group = self.__data_group_proxy.item
            data_group.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1, state2) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return state1[0] == state2[0]

        def perform(self) -> None:
            data_group = self.__data_group_proxy.item
            display_items = [display_item_proxy.item for display_item_proxy in self.__display_item_proxies]
            for index, display_item in enumerate(display_items):
                data_group.insert_display_item(self.__before_index + index, display_item)

        def _undo(self) -> None:
            data_group = self.__data_group_proxy.item
            display_items_len = len(self.__display_item_proxies)
            for index in reversed(range(display_items_len)):
                data_group.remove_display_item(data_group.display_items[self.__before_index + index])

        def _redo(self) -> None:
            self.perform()

    def create_insert_data_group_display_items_command(self, data_group: DataGroup.DataGroup, before_index: int, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> InsertDataGroupDisplayItemsCommand:
        return DocumentController.InsertDataGroupDisplayItemsCommand(self.document_model, data_group, before_index, display_items)

    class InsertDataGroupDataItemsCommand(Undo.UndoableCommand):
        def __init__(self, document_controller: "DocumentController", data_group: DataGroup.DataGroup, data_items: typing.Sequence[DataItem.DataItem], index: int):
            super().__init__("Insert Data Items")
            self.__document_controller = document_controller
            self.__data_group_proxy = data_group.create_proxy()
            self.__data_group_indexes = list()
            self.__data_group_display_item_proxies = list()
            self.__data_items = data_items  # only in perform
            self.__display_item_index = index
            self.__display_item_indexes = list()
            self.__undelete_logs = list()
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__data_group_indexes = None
            for display_item_proxy in self.__data_group_display_item_proxies:
                display_item_proxy.close()
            self.__data_group_display_item_proxies = None
            self.__display_item_index = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = None
            self.__data_group_proxy.close()
            self.__data_group_proxy = None
            super().close()

        def _get_modified_state(self):
            data_group = self.__data_group_proxy.item
            return self.__document_controller.document_model.modified_state, data_group.modified_state

        def _set_modified_state(self, modified_state) -> None:
            data_group = self.__data_group_proxy.item
            self.__document_controller.document_model.modified_state, data_group.modified_state = modified_state

        def perform(self):
            document_model = self.__document_controller.document_model
            data_group = self.__data_group_proxy.item
            index = self.__display_item_index
            display_items = list()
            for data_item in self.__data_items:
                document_model.append_data_item(data_item)
                self.__display_item_indexes.append(len(document_model.display_items))
                display_items.append(document_model.get_display_item_for_data_item(data_item))
            for display_item in display_items:
                if not display_item in data_group.display_items:
                    data_group.insert_display_item(index, display_item)
                    self.__data_group_indexes.append(index)
                    self.__data_group_display_item_proxies.append(display_item.project.create_item_proxy(item=display_item))
                    index += 1
            self.__display_items = None

        def _undo(self) -> None:
            document_model = self.__document_controller.document_model
            data_group = self.__data_group_proxy.item
            display_items = [data_group.display_items[index] for index in self.__data_group_indexes]
            for display_item in display_items:
                if display_item in data_group.display_items:
                    data_group.remove_display_item(display_item)
            display_items = [document_model.display_items[index] for index in self.__display_item_indexes]
            for display_item in display_items:
                if display_item in document_model.display_items:
                    self.__undelete_logs.append(document_model.remove_display_item_with_log(display_item, safe=True))

        def _redo(self) -> None:
            data_group = self.__data_group_proxy.item
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            index = self.__display_item_index
            display_items = [display_item_proxy.item for display_item_proxy in reversed(self.__data_group_display_item_proxies)]
            for display_item in display_items:
                if not display_item in data_group.display_items:
                    data_group.insert_display_item(index, display_item)

    class RemoveDataGroupDisplayItemsCommand(Undo.UndoableCommand):
        def __init__(self, document_model, data_group: DataGroup.DataGroup, display_items: typing.Sequence[DisplayItem.DisplayItem]):
            super().__init__("Remove Data Item")
            self.__document_model = document_model
            self.__data_group_proxy = data_group.create_proxy()
            combined = [(data_group.display_items.index(display_item), display_item) for display_item in display_items]
            combined = sorted(combined, key=operator.itemgetter(0), reverse=True)
            self.__display_item_indexes = list(map(operator.itemgetter(0), combined))
            self.__display_item_proxies = [display_item.create_proxy() for index, display_item in combined]
            self.initialize()

        def close(self):
            self.__data_group_proxy.close()
            self.__data_group_proxy = None
            for display_item_proxy in self.__display_item_proxies:
                display_item_proxy.close()
            self.__display_item_proxies = None
            super().close()

        def _get_modified_state(self):
            data_group = self.__data_group_proxy.item
            return data_group.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            data_group = self.__data_group_proxy.item
            data_group.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1, state2) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return state1[0] == state2[0]

        def perform(self) -> None:
            data_group = self.__data_group_proxy.item
            display_items = [data_group.display_items[index] for index in self.__display_item_indexes]
            for display_item in display_items:
                if display_item in data_group.display_items:
                    data_group.remove_display_item(display_item)

        def _undo(self) -> None:
            data_group = self.__data_group_proxy.item
            display_items = [display_item_proxy.item for display_item_proxy in self.__display_item_proxies]
            for index, display_item in zip(self.__display_item_indexes, display_items):
                data_group.insert_display_item(index, display_item)

        def _redo(self) -> None:
            self.perform()

    class RenameDataGroupCommand(Undo.UndoableCommand):
        def __init__(self, document_model, data_group: DataGroup.DataGroup, title: str):
            super().__init__("Rename Data Group")
            self.__document_model = document_model
            self.__data_group_proxy = data_group.create_proxy()
            self.__title = title
            self.__new_title = None
            self.initialize()

        def close(self):
            self.__data_group_proxy.close()
            self.__data_group_proxy = None
            super().close()

        def _get_modified_state(self):
            data_group = self.__data_group_proxy.item
            return data_group.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            data_group = self.__data_group_proxy.item
            data_group.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1, state2) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return state1[0] == state2[0]

        def perform(self) -> None:
            data_group = self.__data_group_proxy.item
            self.__new_title = data_group.title
            data_group.title = self.__title

        def _undo(self) -> None:
            data_group = self.__data_group_proxy.item
            data_group.title = self.__new_title

        def _redo(self) -> None:
            self.perform()

    def create_rename_data_group_command(self, data_group: DataGroup.DataGroup, title: str) -> RenameDataGroupCommand:
        return DocumentController.RenameDataGroupCommand(self.document_model, data_group, title)

    class InsertDataGroupCommand(Undo.UndoableCommand):
        def __init__(self, document_model: DocumentModel.DocumentModel, container: typing.Union[DataGroup.DataGroup, Project.Project], before_index: int, data_group: DataGroup.DataGroup):
            super().__init__("Insert Data Group")
            self.__document_model = document_model
            self.__container_proxy = container.create_proxy()
            self.__before_index = before_index
            self.__data_group_properties = data_group.write_to_dict()
            self.__data_group_proxy = None
            self.initialize()

        def close(self):
            if self.__data_group_proxy:
                self.__data_group_proxy.close()
                self.__data_group_proxy = None
            self.__container_proxy.close()
            self.__container_proxy = None
            super().close()

        def _get_modified_state(self):
            container = self.__container_proxy.item
            return container.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            container = self.__container_proxy.item
            container.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1, state2) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return state1[0] == state2[0]

        def perform(self) -> None:
            container = self.__container_proxy.item
            data_group = DataGroup.DataGroup()
            data_group.read_from_dict(self.__data_group_properties)
            container.insert_item("data_groups", self.__before_index, data_group)
            self.__data_group_proxy = data_group.create_proxy()

        def _undo(self) -> None:
            container = self.__container_proxy.item
            data_group = self.__data_group_proxy.item
            container.remove_item("data_groups", data_group)
            self.__data_group_proxy.close()
            self.__data_group_proxy = None

        def _redo(self) -> None:
            self.perform()

    class RemoveDataGroupCommand(Undo.UndoableCommand):
        def __init__(self, document_model: DocumentModel.DocumentModel, container: typing.Union[DataGroup.DataGroup, Project.Project], data_group: DataGroup.DataGroup):
            super().__init__("Remove Data Group")
            self.__document_model = document_model
            self.__container_proxy = container.create_proxy()
            self.__data_group_proxy = data_group.create_proxy()
            self.__data_group_properties = None
            self.__data_group_index = None
            self.initialize()

        def close(self):
            self.__data_group_proxy.close()
            self.__data_group_proxy = None
            self.__container_proxy.close()
            self.__container_proxy = None
            super().close()

        def _get_modified_state(self):
            container = self.__container_proxy.item
            return container.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            container = self.__container_proxy.item
            container.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1, state2) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return state1[0] == state2[0]

        def perform(self) -> None:
            container = self.__container_proxy.item
            data_group = self.__data_group_proxy.item
            self.__data_group_properties = data_group.write_to_dict()
            self.__data_group_index = container.data_groups.index(data_group)
            container.remove_item("data_groups", data_group)

        def _undo(self) -> None:
            container = self.__container_proxy.item
            data_group = DataGroup.DataGroup()
            data_group.begin_reading()
            data_group.read_from_dict(self.__data_group_properties)
            data_group.finish_reading()
            container.insert_item("data_groups", self.__data_group_index, data_group)

        def _redo(self) -> None:
            self.perform()

    def add_group(self):
        data_group = DataGroup.DataGroup()
        data_group.title = _("Untitled Group")
        command = DocumentController.InsertDataGroupCommand(self.document_model, self.document_model._project, 0, data_group)
        command.perform()
        self.push_undo_command(command)

    def remove_data_group_from_container(self, data_group: DataGroup.DataGroup, container: typing.Union[DataGroup.DataGroup, Project.Project]):
        data_group_empty = len(data_group.display_items) == 0 and len(data_group.data_groups) == 0
        if data_group_empty:
            assert data_group in container.data_groups
            command = DocumentController.RemoveDataGroupCommand(self.document_model, container, data_group)
            command.perform()
            self.push_undo_command(command)

    def add_line_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.LineGraphic()
            graphic.start = (0.2, 0.2)
            graphic.end = (0.8, 0.8)
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_rectangle_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_ellipse_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.EllipseGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_point_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.PointGraphic()
            graphic.position = (0.5,0.5)
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_interval_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.IntervalGraphic()
            graphic.start = 0.25
            graphic.end = 0.75
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_channel_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.ChannelGraphic()
            graphic.position = 0.5
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_spot_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.SpotGraphic()
            graphic.bounds = Geometry.FloatRect.from_center_and_size((0.25, 0.25), (0.25, 0.25))
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_angle_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.WedgeGraphic()
            graphic.start_angle = 0
            graphic.end_angle = (3/4) * math.pi
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_band_pass_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.RingGraphic()
            graphic.radius_1 = 0.15
            graphic.radius_2 = 0.25
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_lattice_graphic(self):
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.LatticeGraphic()
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def __change_graphics_role(self, role: typing.Optional[str]) -> bool:
        display_item = self.selected_display_item
        if display_item:
            if display_item.graphic_selection.has_selection:
                graphics = [display_item.graphics[index] for index in display_item.graphic_selection.indexes]
                graphics = itertools.filterfalse(lambda graphic: isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)), graphics)
                if graphics:
                    command = DisplayPanel.ChangeGraphicsCommand(self.document_model, display_item, graphics, command_id="change_role", is_mergeable=True, role=role)
                    command.perform()
                    self.push_undo_command(command)
                    return True
        return False

    def add_graphic_mask(self) -> bool:
        return self.__change_graphics_role("mask")

    def remove_graphic_mask(self) -> bool:
        return self.__change_graphics_role(None)

    def copy_selected_graphics(self):
        display_item = self.selected_display_item
        if display_item:
            mime_data = self.ui.create_mime_data()

            # copy the data item as an svg

            if display_item.display_data_shape and len(display_item.display_data_shape) == 2:
                display_shape = Geometry.IntSize(height=800, width=800)
            else:
                display_shape = Geometry.IntSize(height=600, width=800)

            drawing_context, shape = DisplayPanel.preview(DisplayPanel.FixedUISettings(), display_item, display_shape.width,
                                                          display_shape.height)

            view_box = Geometry.IntRect(Geometry.IntPoint(), shape)

            svg = drawing_context.to_svg(shape, view_box)

            mime_data.set_data_as_string(MimeTypes.SVG_MIME_TYPE, svg)

            if display_item.graphic_selection.has_selection:
                # copy the graphic on the selected display item
                graphics = [display_item.graphics[index] for index in display_item.graphic_selection.indexes]
                MimeTypes.mime_data_put_graphics(mime_data, graphics)
                self.ui.clipboard_set_mime_data(mime_data)
                return True
            else:
                # copy the selected display item if graphic is not selected
                MimeTypes.mime_data_put_display_item(mime_data, display_item)
                self.ui.clipboard_set_mime_data(mime_data)

        return False

    def remove_selected_graphics(self) -> None:
        display_item = self.selected_display_item
        if display_item:
            if display_item.graphic_selection.has_selection:
                graphics = [display_item.graphics[index] for index in display_item.graphic_selection.indexes]
                if graphics:
                    command = self.create_remove_graphics_command(display_item, graphics)
                    command.perform()
                    self.push_undo_command(command)

    class RemoveGraphicsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", display_item: DisplayItem.DisplayItem, graphics: typing.Sequence[Graphics.Graphic]):
            super().__init__(_("Remove Graphics"))
            self.__document_controller = document_controller
            self.__display_item_proxy = display_item.create_proxy()
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__graphic_indexes = [display_item.graphics.index(graphic) for graphic in graphics]
            self.__undelete_logs = list()
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__display_item_proxy.close()
            self.__display_item_proxy = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__graphic_indexes = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = None
            super().close()

        def perform(self):
            display_item = self.__display_item_proxy.item
            graphics = [display_item.graphics[index] for index in self.__graphic_indexes]
            for graphic in graphics:
                self.__undelete_logs.append(display_item.remove_graphic(graphic, safe=True))

        def _get_modified_state(self):
            display_item = self.__display_item_proxy.item
            return display_item.modified_state, self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state):
            display_item = self.__display_item_proxy.item
            display_item.modified_state, self.__document_controller.document_model.modified_state = modified_state

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self):
            self.perform()
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

        def _compare_modified_states(self, state1, state2) -> bool:
            # after inserting, a computation may be performed and change the document. this ensures that this
            # undo is still enabled after that happens.
            return True

    def create_remove_graphics_command(self, display_item, graphics):
        return DocumentController.RemoveGraphicsCommand(self, display_item, graphics)

    class RemoveDisplayItemsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", display_items: typing.Sequence[DisplayItem.DisplayItem]):
            super().__init__(_("Remove Display Items"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__display_item_indexes = [document_controller.document_model.display_items.index(display_item) for display_item in display_items]
            self.__undelete_logs = list()
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__display_item_indexes = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = None
            super().close()

        def perform(self):
            document_model = self.__document_controller.document_model
            display_items = [document_model.display_items[index] for index in self.__display_item_indexes]
            for display_item in display_items:
                if display_item in document_model.display_items:
                    selected_display_items = self.__document_controller.selected_display_items
                    if display_item in selected_display_items:
                        selected_display_items.remove(display_item)
                    self.__undelete_logs.append(document_model.remove_display_item_with_log(display_item))
                    self.__document_controller.select_display_items_in_data_panel(selected_display_items)

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state):
            self.__document_controller.document_model.modified_state = modified_state

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self):
            self.perform()
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

    def create_remove_display_items_command(self, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> Undo.UndoableCommand:
        return DocumentController.RemoveDisplayItemsCommand(self, display_items)

    class RemoveDataItemsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", data_items: typing.Sequence[DataItem.DataItem]):
            super().__init__(_("Remove Data Items"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__data_item_indexes = [document_controller.document_model.data_items.index(data_item) for data_item in data_items]
            self.__undelete_logs = list()
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__data_item_indexes = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = None
            super().close()

        def perform(self):
            document_model = self.__document_controller.document_model
            data_items = [document_model.data_items[index] for index in self.__data_item_indexes]
            for data_item in data_items:
                if data_item in document_model.data_items:
                    self.__undelete_logs.append(document_model.remove_data_item_with_log(data_item, safe=True))

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state):
            self.__document_controller.document_model.modified_state = modified_state

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self):
            self.perform()
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

    def create_remove_data_items_command(self, data_items: typing.Sequence[DataItem.DataItem]) -> Undo.UndoableCommand:
        return DocumentController.RemoveDataItemsCommand(self, data_items)

    def add_data_element(self, data_element, source_data_item=None):
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        if data_item:
            self.document_model.append_data_item(data_item)
        return data_item

    def add_data(self, data, title=None):
        data_element = { "data": data, "title": title }
        return self.add_data_element(data_element)

    def show_display_item(self, display_item: DisplayItem.DisplayItem, *, source_display_item=None, source_data_item=None, request_focus=True) -> None:
        result_display_panel = self.next_result_display_panel()
        if result_display_panel:
            result_display_panel.set_display_panel_display_item(display_item)
            if request_focus:
                result_display_panel.request_focus()
        self.select_display_items_in_data_panel([display_item])
        if request_focus:
            inspector_panel = self.find_dock_panel("inspector-panel")
            if inspector_panel is not None:
                inspector_panel.request_focus = True

    def _perform_redimension(self, display_item: DisplayItem.DisplayItem, data_descriptor: DataAndMetadata.DataDescriptor) -> None:
        def process() -> DataItem.DataItem:
            new_data_item = self.document_model.get_redimension_new(display_item, display_item.data_item, data_descriptor)
            new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertDataItemCommand)
        if command.data_item:
            self.push_undo_command(command)
            return command.data_item
        else:
            command.close()

    def _perform_squeeze(self, display_item: DisplayItem.DisplayItem) -> None:
        def process() -> DataItem.DataItem:
            new_data_item = self.document_model.get_squeeze_new(display_item, display_item.data_item)
            new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertDataItemCommand)
        if command.data_item:
            self.push_undo_command(command)
            return command.data_item
        else:
            command.close()

    def _menu_about_to_show(self, menu: UserInterface.Menu) -> None:
        if menu.menu_id == "processing_redimension":
            self.__adjust_redimension_data_menu(menu)
        elif menu.menu_id == "display_panel_type":
            self.__about_to_show_display_type_menu(menu)
        elif menu.menu_id == "workspace":
            self.__adjust_workspace_menu(menu)
            super()._menu_about_to_show(menu)
        elif menu.menu_id == "window":
            self.__adjust_window_menu(menu)
            super()._menu_about_to_show(menu)
        else:
            super()._menu_about_to_show(menu)

    def __adjust_window_menu(self, menu: UserInterface.Menu) -> None:
        for dynamic_window_action in self.__dynamic_window_actions:
            menu.remove_action(dynamic_window_action)
        self.__dynamic_window_actions = []
        toggle_actions = [dock_widget.toggle_action for dock_widget in self.workspace_controller.dock_widgets]
        for toggle_action in sorted(toggle_actions, key=operator.attrgetter("title")):
            menu.add_action(toggle_action)
            self.__dynamic_window_actions.append(toggle_action)

    def __adjust_workspace_menu(self, menu: UserInterface.Menu) -> None:
        menu.add_separator()
        for dynamic_view_action in self.__dynamic_view_actions:
            menu.remove_action(dynamic_view_action)
        self.__dynamic_view_actions = []
        for workspace in self.project.workspaces:
            def switch_to_workspace(workspace):
                self.workspace_controller.change_workspace(workspace)
            action = menu.add_menu_item(workspace.name, functools.partial(switch_to_workspace, workspace))
            action.checked = self.project.workspace_uuid == workspace.uuid
            self.__dynamic_view_actions.append(action)

    def __about_to_show_display_type_menu(self, menu: UserInterface.Menu) -> None:
        for dynamic_live_action in self.__dynamic_live_actions:
            menu.remove_action(dynamic_live_action)
        self.__dynamic_live_actions = []
        selected_display_panel = self.selected_display_panel
        if not selected_display_panel:
            return
        self.__dynamic_live_actions.extend(DisplayPanel.DisplayPanelManager().build_menu(menu, self, selected_display_panel))

    def __adjust_redimension_data_menu(self, menu: UserInterface.Menu) -> None:
        for action in self.__data_menu_actions:
            menu.remove_action(action)
        self.__data_menu_actions = list()
        selected_display_panel = self.selected_display_panel
        display_item = selected_display_panel.display_item
        data_item = display_item.data_item if display_item else None
        if data_item:

            def describe_data_descriptor(data_descriptor: DataAndMetadata.DataDescriptor, data_shape: typing.List[int]) -> str:
                if data_descriptor.is_sequence:
                    data_type_name = _("Sequence of {} ".format(data_shape[0]))
                    index = 1
                else:
                    data_type_name = str()
                    index = 0
                if data_descriptor.collection_dimension_count == 1:
                    data_type_name += _("Collection of ") + str(data_shape[index]) + " "
                    index += 1
                elif data_descriptor.collection_dimension_count == 2:
                    data_type_name += str(data_shape[index]) + "x" + str(data_shape[index + 1]) + _(" Collection of ")
                    index += 2
                if data_descriptor.datum_dimension_count == 1:
                    data_type_name += "Spectra of Length " + str(data_shape[index])
                elif data_descriptor.datum_dimension_count == 2:
                    data_type_name += "Images of Shape " + str(data_shape[index]) + "x" + str(data_shape[index + 1])
                return data_type_name

            # add (disabled) existing data type menu item
            data_type_name = describe_data_descriptor(data_item.xdata.data_descriptor, data_item.xdata.data_shape)
            action = menu.add_menu_item(data_type_name, None)
            action.enabled = False
            self.__data_menu_actions.append(action)

            # add redimension menu items if available
            for is_sequence, collection_dims, data_dims in itertools.product((True, False), (0, 1, 2), (1, 2)):
                data_descriptor = DataAndMetadata.DataDescriptor(is_sequence, collection_dims, data_dims)
                if data_descriptor.expected_dimension_count == data_item.xdata.data_descriptor.expected_dimension_count and data_descriptor != data_item.xdata.data_descriptor:
                    data_type_name = describe_data_descriptor(data_descriptor, data_item.xdata.data_shape)
                    action = menu.add_menu_item(_("Redimension to {}").format(data_type_name), functools.partial(self._perform_redimension, display_item, data_descriptor))
                    self.__data_menu_actions.append(action)

            # add squeeze menu item if available
            data_descriptor = data_item.xdata.data_descriptor
            data_shape = list(data_item.xdata.data_shape)
            if 1 in data_shape[data_descriptor.collection_dimension_index_slice] or 1 in data_shape[data_descriptor.sequence_dimension_index_slice] and len(data_shape[data_descriptor.datum_dimension_index_slice]) > 1 and data_shape[data_descriptor.datum_dimension_index_slice].count(1) > 0:
                if data_descriptor.is_sequence and data_shape[data_descriptor.sequence_dimension_index_slice] == 1:
                    data_descriptor.is_sequence = False
                    data_shape = data_shape[1:]
                while data_shape[data_descriptor.collection_dimension_index_slice].count(1) > 0:
                    index = data_shape[data_descriptor.collection_dimension_index_slice].index(1)
                    del data_shape[data_descriptor.collection_dimension_index_slice.start + index]
                    data_descriptor.collection_dimension_count -= 1
                while len(data_shape[data_descriptor.datum_dimension_index_slice]) > 1 and data_shape[data_descriptor.datum_dimension_index_slice].count(1) > 0:
                    index = data_shape[data_descriptor.datum_dimension_index_slice].index(1)
                    del data_shape[data_descriptor.datum_dimension_index_slice.start + index]
                    data_descriptor.datum_dimension_count -= 1
                data_type_name = describe_data_descriptor(data_descriptor, data_shape)
                self.__data_menu_actions.append(menu.add_menu_item(_("Squeeze to {}").format(data_type_name), functools.partial(self._perform_squeeze, display_item)))
        else:
            action = menu.add_menu_item(_("No Data Selected"), None)
            action.enabled = False
            self.__data_menu_actions.append(action)

    def _get_crop_graphic(self, display_item: DisplayItem.DisplayItem) -> typing.Optional[Graphics.Graphic]:
        crop_graphic = None
        data_item = display_item.data_item if display_item else None
        current_index = display_item.graphic_selection.current_index if display_item else None
        graphic = display_item.graphics[current_index] if current_index is not None else None
        if data_item and graphic:
            if data_item.is_datum_1d and isinstance(graphic, Graphics.IntervalGraphic):
                crop_graphic = graphic
            elif data_item.is_datum_2d and isinstance(graphic, Graphics.RectangleTypeGraphic):
                crop_graphic = graphic
        return crop_graphic

    def __get_mask_graphics(self, display_item: DisplayItem.DisplayItem) -> typing.List[Graphics.Graphic]:
        mask_graphics = list()
        data_item = display_item.data_item if display_item else None
        if data_item and len(data_item.dimensional_shape) == 2:
            current_index = display_item.graphic_selection.current_index
            if current_index is not None:
                graphic = display_item.graphics[current_index]
                if hasattr(graphic, 'get_mask'):
                    mask_graphics.append(graphic)
        return mask_graphics

    def processing_crop(self) -> DisplayItem.DisplayItem:
        self.perform_action("processing.crop")
        return self.document_model.display_items[-1]

    def processing_projection(self) -> DisplayItem.DisplayItem:
        self.perform_action("processing.projection_sum")
        return self.document_model.display_items[-1]

    def processing_line_profile(self) -> DisplayItem.DisplayItem:
        self.perform_action("processing.line_profile")
        return self.document_model.display_items[-1]

    def processing_invert(self) -> DisplayItem.DisplayItem:
        self.perform_action("processing.negate")
        return self.document_model.display_items[-1]

    class InsertDataItemCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", data_item_fn: typing.Callable[[], DataItem.DataItem]):
            super().__init__(_("Insert Data Item"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__data_item_proxy = None
            self.__data_item_fn = data_item_fn
            self.__undelete_log = None
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__data_item_fn = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            if self.__undelete_log:
                self.__undelete_log.close()
                self.__undelete_log = None
            if self.__data_item_proxy:
                self.__data_item_proxy.close()
                self.__data_item_proxy = None
            super().close()

        def perform(self):
            data_item = self.__data_item_fn()
            self.__data_item_proxy = data_item.create_proxy() if data_item else None

        @property
        def data_item(self):
            return self.__data_item_proxy.item if self.__data_item_proxy else None

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _compare_modified_states(self, state1, state2) -> bool:
            # after inserting, a computation may be performed and change the document. this ensures that this
            # undo is still enabled after that happens.
            return True

        def _redo(self):
            self.__document_controller.document_model.undelete_all(self.__undelete_log)
            self.__undelete_log.close()
            self.__undelete_log = None
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self):
            data_item = self.data_item
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__undelete_log = self.__document_controller.document_model.remove_data_item_with_log(data_item, safe=True)
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

    def create_insert_data_item_command(self, data_item_fn: typing.Callable[[], DataItem.DataItem]) -> Undo.UndoableCommand:
        return DocumentController.InsertDataItemCommand(self, data_item_fn)

    def _perform_duplicate(self, data_item: DataItem.DataItem) -> None:
        def process() -> DataItem.DataItem:
            new_data_item = self.document_model.copy_data_item(data_item)
            new_data_item.title = _("Clone of ") + data_item.title
            new_data_item.category = data_item.category
            self.select_data_item_in_data_panel(new_data_item)
            inspector_panel = self.find_dock_panel("inspector-panel")
            if inspector_panel is not None:
                inspector_panel.request_focus = True
            display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            self.show_display_item(display_item, source_data_item=data_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        self.push_undo_command(command)

    def processing_duplicate(self):
        data_item = self.selected_data_item
        if data_item:
            self._perform_duplicate(data_item)

    class InsertDisplayItemCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", display_item: DisplayItem.DisplayItem, display_item_fn: typing.Callable[[], DisplayItem.DisplayItem]):
            super().__init__(_("Insert Display Item"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__display_item_proxy = None
            self.__display_item = display_item
            self.__display_item_fn = display_item_fn
            self.__display_item_index = None
            self.__undelete_log = None
            self.initialize()

        def close(self):
            self.__document_controller = None
            if self.__display_item_proxy:
                self.__display_item_proxy.close()
                self.__display_item_proxy = None
            self.__display_item_index = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            if self.__undelete_log:
                self.__undelete_log.close()
                self.__undelete_log = None
            super().close()

        def perform(self):
            document_controller = self.__document_controller
            display_item = self.__display_item
            request_focus = not display_item.is_live
            snapshot_display_item = self.__display_item_fn(display_item)
            if request_focus:
                # see https://github.com/nion-software/nionswift/issues/145
                document_controller.select_display_items_in_data_panel([snapshot_display_item])
                inspector_panel = document_controller.find_dock_panel("inspector-panel")
                if inspector_panel is not None:
                    inspector_panel.request_focus = True
            document_controller.show_display_item(snapshot_display_item, source_display_item=snapshot_display_item, request_focus=request_focus)
            self.__display_item_proxy = display_item.create_proxy() if display_item else None

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _redo(self):
            self.__document_controller.document_model.undelete_all(self.__undelete_log)
            self.__undelete_log.close()
            self.__undelete_log = None
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self):
            display_item = self.__display_item_proxy.item if self.__display_item_proxy else None
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__display_item_index = self.__document_controller.document_model.display_items.index(display_item)
            self.__undelete_log = self.__document_controller.document_model.remove_display_item_with_log(display_item)
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

    def _perform_display_item_snapshot(self, display_item: DisplayItem.DisplayItem) -> None:
        command = DocumentController.InsertDisplayItemCommand(self, display_item, self.document_model.get_display_item_snapshot_new)
        command.perform()
        self.push_undo_command(command)

    def processing_snapshot(self):
        display_item = self.selected_display_item
        if display_item:
            self._perform_display_item_snapshot(display_item)

    def processing_display_copy(self):
        display_item = self.selected_display_item
        if display_item:
            command = DocumentController.InsertDisplayItemCommand(self, display_item, self.document_model.get_display_item_copy_new)
            command.perform()
            self.push_undo_command(command)

    class RemoveDisplayItemCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", display_item: DisplayItem.DisplayItem):
            super().__init__(_("Remove Display Item"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__display_item_index = document_controller.document_model.display_items.index(display_item)
            self.__undelete_logs = list()
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__display_item_index = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = None
            super().close()

        def perform(self):
            document_model = self.__document_controller.document_model
            display_item = document_model.display_items[self.__display_item_index]
            self.__undelete_logs.append(document_model.remove_display_item_with_log(display_item))

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self):
            self.perform()
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

    def processing_display_remove(self):
        display_item = self.selected_display_item
        if display_item:
            command = DocumentController.RemoveDisplayItemCommand(self, display_item)
            command.perform()
            self.push_undo_command(command)

    def processing_computation(self, expression, map: typing.Mapping[str, Symbolic.ComputationItem]=None):
        if map is None:
            map = dict()
            for variable_name, data_item in DocumentModel.MappedItemManager().item_map.items():
                map[variable_name] = Symbolic.make_item(data_item)
        data_item = DataItem.DataItem()
        data_item.ensure_data_source()
        data_item.title = _("Computation on ") + data_item.title
        computation = self.document_model.create_computation(expression)
        names = Symbolic.Computation.parse_names(expression)
        for variable_name, input_item in map.items():
            if variable_name in names:
                computation.create_input_item(variable_name, input_item)
        for item in computation.input_items:
            if isinstance(item, DataItem.DataItem) and item.category == "temporary":
                data_item.category = "temporary"
        self.document_model.append_data_item(data_item)
        self.document_model.set_data_item_computation(data_item, computation)
        display_item = self.document_model.get_display_item_for_data_item(data_item)
        self.show_display_item(display_item)
        return data_item

    def _get_two_data_sources(self):
        """Get two sensible data sources, which may be the same."""
        selected_display_items = self.selected_display_items
        if len(selected_display_items) < 2:
            selected_display_items = list()
            display_item = self.selected_display_item
            if display_item:
                selected_display_items.append(display_item)
        if len(selected_display_items) == 1:
            display_item = selected_display_items[0]
            data_item = display_item.data_item if display_item else None
            if display_item and len(display_item.graphic_selection.indexes) == 2:
                index1 = display_item.graphic_selection.anchor_index
                index2 = list(display_item.graphic_selection.indexes.difference({index1}))[0]
                graphic1 = display_item.graphics[index1]
                graphic2 = display_item.graphics[index2]
                if data_item:
                    if data_item.is_datum_1d and isinstance(graphic1, Graphics.IntervalGraphic) and isinstance(graphic2, Graphics.IntervalGraphic):
                        crop_graphic1 = graphic1
                        crop_graphic2 = graphic2
                    elif data_item.is_datum_2d and isinstance(graphic1, Graphics.RectangleTypeGraphic) and isinstance(graphic2, Graphics.RectangleTypeGraphic):
                        crop_graphic1 = graphic1
                        crop_graphic2 = graphic2
                    else:
                        crop_graphic1 = self._get_crop_graphic(display_item)
                        crop_graphic2 = crop_graphic1
                else:
                    crop_graphic1 = self._get_crop_graphic(display_item)
                    crop_graphic2 = crop_graphic1
            else:
                crop_graphic1 = self._get_crop_graphic(display_item)
                crop_graphic2 = crop_graphic1
            return (display_item, crop_graphic1), (display_item, crop_graphic2)
        if len(selected_display_items) == 2:
            display_item1 = selected_display_items[0]
            crop_graphic1 = self._get_crop_graphic(display_item1)
            display_item2 = selected_display_items[1]
            crop_graphic2 = self._get_crop_graphic(display_item2)
            return (display_item1, crop_graphic1), (display_item2, crop_graphic2)
        return None

    def _perform_processing2(self, display_item1: DisplayItem.DisplayItem, data_item1: DataItem.DataItem, display_item2: DisplayItem.DisplayItem, data_item2: DataItem.DataItem, crop_graphic1: typing.Optional[Graphics.Graphic], crop_graphic2: typing.Optional[Graphics.Graphic], fn) -> typing.Optional[DataItem.DataItem]:
        def process() -> DataItem.DataItem:
            new_data_item = fn(display_item1, data_item1, display_item2, data_item2, crop_graphic1, crop_graphic2)
            new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertDataItemCommand)
        if command.data_item:
            self.push_undo_command(command)
            return command.data_item
        else:
            command.close()
        return None

    def _perform_processing3(self, display_item1: DisplayItem.DisplayItem, data_item1: DataItem.DataItem, display_item2: DisplayItem.DisplayItem, data_item2: DataItem.DataItem, display_item3: DisplayItem.DisplayItem, data_item3: DataItem.DataItem, crop_graphic1: typing.Optional[Graphics.Graphic], crop_graphic2: typing.Optional[Graphics.Graphic], crop_graphic3: typing.Optional[Graphics.Graphic], fn) -> typing.Optional[DataItem.DataItem]:
        def process() -> DataItem.DataItem:
            new_data_item = fn(display_item1, data_item1, display_item2, data_item2, display_item3, data_item3, crop_graphic1, crop_graphic2, crop_graphic3)
            new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertDataItemCommand)
        if command.data_item:
            self.push_undo_command(command)
            return command.data_item
        else:
            command.close()
        return None

    def _perform_processing(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_graphic: typing.Optional[Graphics.Graphic], fn) -> None:
        def process() -> DataItem.DataItem:
            new_data_item = fn(display_item, data_item, crop_graphic)
            if new_data_item:
                new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
                self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertDataItemCommand)
        if command.data_item:
            self.push_undo_command(command)
        else:
            command.close()

    def _perform_processing_select(self, display_item: DisplayItem.DisplayItem, crop_graphic: typing.Optional[Graphics.Graphic], fn) -> None:
        def perform(display_item: DisplayItem.DisplayItem, data_item: typing.Optional[DataItem.DataItem]) -> None:
            if data_item:
                window = typing.cast(DocumentController, self)
                window._perform_processing(display_item, data_item, crop_graphic, fn)

        if display_item.data_item:
            perform(display_item, display_item.data_item)
        else:
            Dialog.pose_select_item_pop_up(display_item.data_items, functools.partial(perform, display_item),
                                           item_getter=operator.attrgetter("title"), window=self)

    def _change_to_previous_workspace(self):
        if self.workspace_controller:
            self.workspace_controller.change_to_previous_workspace()

    def _change_to_next_workspace(self):
        if self.workspace_controller:
            self.workspace_controller.change_to_next_workspace()

    def _create_workspace(self):
        if self.workspace_controller:
            self.workspace_controller.create_workspace()

    def _rename_workspace(self):
        if self.workspace_controller:
            self.workspace_controller.rename_workspace()

    def _remove_workspace(self):
        if self.workspace_controller:
            self.workspace_controller.remove_workspace()

    def _clone_workspace(self):
        if self.workspace_controller:
            self.workspace_controller.clone_workspace()

    def toggle_filter(self):
        if self.workspace_controller.filter_row.visible:
            self.__last_display_filter = self.display_filter
            self.display_filter = ListModel.Filter(True)
        else:
            self.display_filter = self.__last_display_filter
        self.workspace_controller.filter_row.visible = not self.workspace_controller.filter_row.visible

    def prepare_data_item_script(self, *, do_log: bool=True) -> None:
        data_item = self.selected_data_item
        if data_item:
            data_item_var = self.document_model.assign_variable_to_data_item(data_item)
            if do_log: logging.debug("{} = Data Item with UUID {}".format(data_item_var, data_item.uuid))
            for console in self.__consoles:
                console.assign_data_item_var(data_item_var, data_item)

    def copy_uuid(self):
        display_item = self.selected_display_item
        data_item = display_item.data_item if display_item else None
        if display_item:
            current_index = display_item.graphic_selection.current_index
            if current_index is not None:
                graphic = display_item.graphics[current_index]
                uuid_str = str(graphic.uuid)
                self.ui.clipboard_set_text(uuid_str)
                return
        if data_item:
            uuid_str = str(data_item.uuid)
            self.ui.clipboard_set_text(uuid_str)
            return

    def _perform_create_empty_data_item(self) -> None:
        def process() -> DataItem.DataItem:
            new_data_item = DataItem.DataItem()
            new_data_item.title = _("Untitled")
            self.document_model.append_data_item(new_data_item)
            new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        self.push_undo_command(command)

    def create_empty_data_item(self):
        self._perform_create_empty_data_item()

    class InsertDataItemsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: "DocumentController", data_items: typing.Sequence[DataItem.DataItem], index: int, display_panel: DisplayPanel.DisplayPanel=None, *, project: Project.Project = None):
            super().__init__(_("Insert Data Items"))
            self.__document_controller = document_controller
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__data_items = data_items  # only used in perform
            self.__data_item_index = index
            self.__data_item_indexes = list()
            self.__display_panel = display_panel  # only used in perform
            self.__project = project
            self.__undelete_logs = list()
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__data_items = None
            self.__data_item_index = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = None
            super().close()

        def perform(self):
            document_model = self.__document_controller.document_model
            index = self.__data_item_index
            for data_item in self.__data_items:
                # insert will throw an exception if data item already exists in the project
                document_model.insert_data_item(index, data_item, auto_display=True)
                self.__data_item_indexes.append(index)
                index += 1
            if self.__display_panel and self.__data_items:
                display_item = self.__document_controller.document_model.get_display_item_for_data_item(self.__data_items[-1])
                if display_item:
                    self.__display_panel.set_display_panel_display_item(display_item)
                    self.__display_panel.request_focus()

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _redo(self):
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self):
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            document_model = self.__document_controller.document_model
            data_items = [document_model.data_items[index] for index in self.__data_item_indexes]
            for data_item in data_items:
                if data_item in document_model.data_items:
                    self.__undelete_logs.append(document_model.remove_data_item_with_log(data_item, safe=True))
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

    def receive_project_files(self, file_paths: typing.Sequence[pathlib.Path], project: Project.Project, index: int = -1, threaded: bool = True) -> None:
        def receive_files_complete(received_data_items):
            def select_library_all():
                self.select_data_items_in_data_panel([received_data_items[0]])

            if len(received_data_items) > 0:
                self.queue_task(select_library_all)

        self.__receive_files(file_paths, index=index, threaded=threaded, completion_fn=receive_files_complete, project=project)

    # receive files into the document model. data_group and index can optionally
    # be specified. if data_group is specified, the item is added to an arbitrary
    # position in the document model (the end) and at the group at the position
    # specified by the index. if the data group is not specified, the item is added
    # at the index within the document model.
    def receive_files(self, files: typing.Sequence[str], data_group=None, index=-1, threaded=True, completion_fn=None,
                      display_panel: DisplayPanel.DisplayPanel = None, project: Project.Project = None) -> typing.Optional[
        typing.List[DataItem.DataItem]]:
        file_paths = [pathlib.Path(file_path) for file_path in files]
        return self.__receive_files(file_paths, data_group, index, threaded, completion_fn, display_panel, project=project)

    def __receive_files(self, file_paths: typing.Sequence[pathlib.Path],
                        data_group=None,
                        index=-1,
                        threaded=True,
                        completion_fn=None,
                        display_panel: DisplayPanel.DisplayPanel = None, *,
                        project: Project.Project = None) -> typing.Optional[typing.List[DataItem.DataItem]]:
        assert index is not None

        # this function will be called on a thread to receive files in the background.
        def receive_files_on_thread(file_paths: typing.Sequence[pathlib.Path], data_group: typing.Optional[DataGroup.DataGroup], index: int, completion_fn) -> typing.List[DataItem.DataItem]:

            received_data_items = list()

            with self.create_task_context_manager(_("Import Data Items"), "table", logging=threaded) as task:
                task.update_progress(_("Starting import."), (0, len(file_paths)))
                task_data = {"headers": ["Number", "File"]}

                for file_index, file_path in enumerate(file_paths):
                    data = task_data.setdefault("data", list())
                    file_name = file_path.name
                    task_data_entry = [str(file_index + 1), file_name]
                    data.append(task_data_entry)
                    task.update_progress(_("Importing item {}.").format(file_index + 1), (file_index + 1, len(file_paths)), task_data)
                    try:
                        data_items = ImportExportManager.ImportExportManager().read_data_items(self.ui, str(file_path))
                        if data_items:
                            received_data_items.extend(data_items)
                    except Exception as e:
                        logging.debug(f"Could not read image {file_path} / {e}")
                        traceback.print_exc()
                        traceback.print_stack()

                task.update_progress(_("Finishing importing."), (len(file_paths), len(file_paths)))

                if completion_fn:
                    completion_fn(received_data_items)

                return received_data_items

        def receive_files_complete(index, data_items):
            if data_group and isinstance(data_group, DataGroup.DataGroup):
                command = DocumentController.InsertDataGroupDataItemsCommand(self, data_group, data_items, index)
                command.perform()
                self.push_undo_command(command)
            else:
                index = index if index >= 0 else len(self.document_model.data_items)
                command = DocumentController.InsertDataItemsCommand(self, data_items, index, display_panel, project=project)
                command.perform()
                self.push_undo_command(command)
            if callable(completion_fn):
                completion_fn(data_items)

        if threaded:
            def threaded_receive_files_complete(index, data_items):
                self.queue_task(functools.partial(receive_files_complete, index, data_items))

            threading.Thread(target=receive_files_on_thread, args=(file_paths, data_group, index, functools.partial(threaded_receive_files_complete, index))).start()
            return None
        else:
            return receive_files_on_thread(file_paths, data_group, index, functools.partial(receive_files_complete, index))

    def create_context_menu_for_display(self, display_items: typing.List[DisplayItem.DisplayItem]) -> UserInterface.Menu:
        menu = self.create_context_menu()
        action_context = self._get_action_context_for_display_items(display_items, None)
        self.populate_context_menu(menu, action_context)
        return menu

    def populate_context_menu(self, menu: UserInterface.Menu, action_context: DocumentController.ActionContext) -> None:
        self.add_action_to_menu(menu, "display.reveal", action_context)
        self.add_action_to_menu(menu, "file.export", action_context)
        menu.add_separator()
        self.add_action_to_menu(menu, "item.delete", action_context)

        data_item = action_context.data_item

        if data_item:

            source_data_items = self.document_model.get_source_data_items(data_item)
            if len(source_data_items) > 0:
                menu.add_separator()
                for source_data_item in source_data_items:
                    def show_source_data_item(data_item):
                        self.select_data_item_in_data_panel(data_item)

                    truncated_title = self.ui.truncate_string_to_width(str(), source_data_item.title, 280, UserInterface.TruncateModeType.MIDDLE)
                    menu.add_menu_item("{0} \"{1}\"".format(_("Go to Source "), truncated_title),
                                       functools.partial(show_source_data_item, source_data_item))

            dependent_data_items = self.document_model.get_dependent_data_items(data_item)
            if len(dependent_data_items) > 0:
                menu.add_separator()
                for dependent_data_item in dependent_data_items:
                    def show_dependent_data_item(data_item):
                        self.select_data_item_in_data_panel(data_item)

                    truncated_title = self.ui.truncate_string_to_width(str(), dependent_data_item.title, 280, UserInterface.TruncateModeType.MIDDLE)
                    menu.add_menu_item("{0} \"{1}\"".format(_("Go to Dependent "), truncated_title),
                                       functools.partial(show_dependent_data_item, dependent_data_item))

    class ActionContext(Window.ActionContext):
        def __init__(self, application: Application.Application,
                     window: DocumentController,
                     focus_widget: typing.Optional[UserInterface.Widget],
                     display_panel: typing.Optional[DisplayPanel.DisplayPanel],
                     model: DocumentModel.DocumentModel,
                     display_item: typing.Optional[DisplayItem.DisplayItem],
                     display_items: typing.Sequence[DisplayItem.DisplayItem],
                     crop_graphic: typing.Optional[Graphics.Graphic],
                     data_item: typing.Optional[DataItem.DataItem],
                     data_items: typing.Sequence[DataItem.DataItem]):
            super().__init__(application, window, focus_widget)
            self.display_panel = display_panel
            self.model = model
            self.display_item = display_item
            self.display_items = display_items
            self.crop_graphic = crop_graphic
            self.data_item = data_item
            self.data_items = data_items

    def _get_action_context(self) -> ActionContext:
        focus_widget = self.focus_widget
        display_panel = self.selected_display_panel
        model = self.document_model
        display_item = self.selected_display_item
        display_items = self.selected_display_items
        crop_graphic = self._get_crop_graphic(display_item)
        data_item = display_item.data_item if display_item else None
        data_items = self.selected_data_items
        return DocumentController.ActionContext(typing.cast("Application.Application", self.app), self, focus_widget, display_panel, model, display_item, display_items, crop_graphic, data_item, data_items)

    def _get_action_context_for_display_items(self, display_items: typing.Sequence[DisplayItem.DisplayItem], display_panel: typing.Optional[DisplayPanel.DisplayPanel]) -> ActionContext:
        focus_widget = self.focus_widget
        display_panel = display_panel
        model = self.document_model
        display_item = display_items[0] if len(display_items) == 1 else None
        crop_graphic = self._get_crop_graphic(display_item)
        data_item = display_item.data_item if display_item else None
        data_items = display_item.data_items if display_item else list()
        return DocumentController.ActionContext(typing.cast("Application.Application", self.app), self, focus_widget, display_panel, model, display_item, display_items, crop_graphic, data_item, data_items)

    def perform_display_panel_command(self, key) -> bool:
        action_id = Window.get_action_id_for_key("display_panel", key)
        if action_id:
            self.perform_action(action_id)
            return True
        return False


class DeleteItemAction(Window.Action):
    action_id = "item.delete"
    action_name = _("Delete Item")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        selected_display_items = context.display_items
        window.delete_display_items(selected_display_items)
        return Window.ActionResult.FINISHED

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.display_items) > 0

    def get_action_name(self, context: Window.ActionContext) -> str:
        context = typing.cast(DocumentController.ActionContext, context)
        data_item = context.data_item
        display_item = context.display_item
        if data_item and len(context.model.get_display_items_for_data_item(data_item)) == 1:
            return _("Delete Data Item") + f" \"{data_item.title}\""
        elif display_item:
            return _("Delete Display Item") + f" \"{display_item.title}\""
        elif context.display_items:
            return _("Delete Display Items") + f" ({len(context.display_items)})"
        return self.action_name


class DeleteDataItemAction(Window.Action):
    action_id = "item.delete_data_item"
    action_name = _("Delete Data Item")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.delete_data_items(context.data_items)
        return Window.ActionResult.FINISHED

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.data_items) > 0

    def get_action_name(self, context: Window.ActionContext) -> str:
        context = typing.cast(DocumentController.ActionContext, context)
        data_item = context.data_item
        if data_item:
            return _("Delete Data Item") + f" \"{data_item.title}\""
        elif context.data_items:
            return _("Delete Data Items") + f" ({len(context.data_items)})"
        return self.action_name


class ExportAction(Window.Action):
    action_id = "file.export"
    action_name = _("Export...")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        selected_display_item = context.display_item
        selected_display_items = context.display_items
        if len(selected_display_items) > 1:
            window.export_files(selected_display_items)
        elif len(selected_display_items) == 1:
            window.export_file(selected_display_items[0])
        elif selected_display_item:
            window.export_file(selected_display_item)
        return Window.ActionResult.FINISHED

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.display_items) > 0 or context.display_item is not None


class ExportSVGAction(Window.Action):
    action_id = "file.export_svg"
    action_name = _("Export SVG...")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        selected_display_item = window.selected_display_item
        if selected_display_item:
            window.export_svg(selected_display_item)
        return Window.ActionResult.FINISHED


class ImportDataAction(Window.Action):
    action_id = "file.import_data"
    action_name = _("Import Data...")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        window.import_file()
        return Window.ActionResult.FINISHED


class ImportFolderAction(Window.Action):
    action_id = "file.import_folder"
    action_name = _("Import Folder...")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        window._import_folder()
        return Window.ActionResult.FINISHED


Window.register_action(DeleteItemAction())
Window.register_action(DeleteDataItemAction())
Window.register_action(ExportAction())
Window.register_action(ExportSVGAction())
Window.register_action(ImportDataAction())
Window.register_action(ImportFolderAction())



class DataItemRecorderAction(Window.Action):
    action_id = "window.data_item_recorder"
    action_name = _("Data Item Recorder...")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.new_recorder_dialog()
        return Window.ActionResult.FINISHED


class EditComputationAction(Window.Action):
    action_id = "window.edit_computation"
    action_name = _("Edit Computation")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.new_inspect_computation_dialog()
        return Window.ActionResult.FINISHED


class EditDataItemScriptAction(Window.Action):
    action_id = "window.edit_data_item_script"
    action_name = _("Edit Data Item Scripts")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.new_edit_computation_dialog()
        return Window.ActionResult.FINISHED


class EditDisplayScriptAction(Window.Action):
    action_id = "window.edit_display_script"
    action_name = _("Edit Display Script")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.new_display_editor_dialog()
        return Window.ActionResult.FINISHED


class OpenConsoleAction(Window.Action):
    action_id = "window.open_console"
    action_name = _("Python Console...")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.new_console_dialog()
        return Window.ActionResult.FINISHED


class OpenProjectDialogAction(Window.Action):
    action_id = "window.open_project_dialog"
    action_name = _("Project Manager")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.application.open_project_manager()
        return Window.ActionResult.FINISHED


class OpenRunScriptsAction(Window.Action):
    action_id = "window.open_run_scripts"
    action_name = _("Scripts...")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.new_interactive_script_dialog()
        return Window.ActionResult.FINISHED


class ToggleFilterAction(Window.Action):
    action_id = "window.toggle_filter"
    action_name = _("Filter")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.toggle_filter()
        return Window.ActionResult.FINISHED


Window.register_action(DataItemRecorderAction())
Window.register_action(EditComputationAction())
Window.register_action(EditDataItemScriptAction())
Window.register_action(EditDisplayScriptAction())
Window.register_action(OpenConsoleAction())
Window.register_action(OpenProjectDialogAction())
Window.register_action(OpenRunScriptsAction())
Window.register_action(ToggleFilterAction())


class WorkspaceCloneAction(Window.Action):
    action_id = "workspace.clone"
    action_name = _("Clone Workspace")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window._clone_workspace()
        return Window.ActionResult.FINISHED


class WorkspaceNewAction(Window.Action):
    action_id = "workspace.new"
    action_name = _("New Workspace")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window._create_workspace()
        return Window.ActionResult.FINISHED


class WorkspaceNextAction(Window.Action):
    action_id = "workspace.next"
    action_name = _("Next Workspace")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window._change_to_next_workspace()
        return Window.ActionResult.FINISHED


class WorkspacePreviousAction(Window.Action):
    action_id = "workspace.previous"
    action_name = _("Previous Workspace")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window._change_to_previous_workspace()
        return Window.ActionResult.FINISHED


class WorkspaceRemoveAction(Window.Action):
    action_id = "workspace.remove"
    action_name = _("Remove Workspace")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window._remove_workspace()
        return Window.ActionResult.FINISHED


class WorkspaceRenameAction(Window.Action):
    action_id = "workspace.rename"
    action_name = _("Rename Workspace")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window._rename_workspace()
        return Window.ActionResult.FINISHED


class WorkspaceSplitHorizontalAction(Window.Action):
    action_id = "workspace.split_horizontal"
    action_name = _("Split Panel Into Left and Right")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        if workspace_controller:
            command = workspace_controller.insert_display_panel(context.display_panel, "right")
            window.push_undo_command(command)
        return Window.ActionResult.FINISHED


class WorkspaceSplitVerticalAction(Window.Action):
    action_id = "workspace.split_vertical"
    action_name = _("Split Panel Into Top and Bottom")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        if workspace_controller:
            command = workspace_controller.insert_display_panel(context.display_panel, "bottom")
            window.push_undo_command(command)
        return Window.ActionResult.FINISHED


Window.register_action(WorkspaceCloneAction())
Window.register_action(WorkspaceNewAction())
Window.register_action(WorkspaceNextAction())
Window.register_action(WorkspacePreviousAction())
Window.register_action(WorkspaceRemoveAction())
Window.register_action(WorkspaceRenameAction())
Window.register_action(WorkspaceSplitHorizontalAction())
Window.register_action(WorkspaceSplitVerticalAction())


class AddGroupAction(Window.Action):
    action_id = "project.add_group"
    action_name = _("Add Group")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        if context.window:
            window = typing.cast(DocumentController, context.window)
            window.add_group()
        return Window.ActionResult.FINISHED


Window.register_action(AddGroupAction())


class DisplayCopyAction(Window.Action):
    action_id = "display.copy_display"
    action_name = _("Duplicate Display Item")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.processing_display_copy()
        return Window.ActionResult.FINISHED


class DisplayPanelClearAction(Window.Action):

    action_id = "display_panel.clear"
    action_name = _("Clear Display Panel")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        display_panel = context.display_panel
        DisplayPanel.DisplayPanelManager().switch_to_display_content(context.window, display_panel, "empty-display-panel", display_panel.display_item)
        return Window.ActionResult.FINISHED


class DisplayPanelFillViewAction(Window.Action):
    action_id = "display_panel.fill_view"
    action_name = _("Fill View")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        context.display_panel.perform_action("set_fill_mode")
        return Window.ActionResult.FINISHED


class DisplayPanelFitToViewAction(Window.Action):
    action_id = "display_panel.fit_view"
    action_name = _("Fit to View")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        context.display_panel.perform_action("set_fit_mode")
        return Window.ActionResult.FINISHED


class DisplayPanelOneViewAction(Window.Action):
    action_id = "display_panel.1_view"
    action_name = _("1:1 View")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        context.display_panel.perform_action("set_one_to_one_mode")
        return Window.ActionResult.FINISHED


class DisplayPanelShowItemAction(Window.Action):

    action_id = "display_panel.show_item"
    action_name = _("Display Item")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        display_panel = context.display_panel
        DisplayPanel.DisplayPanelManager().switch_to_display_content(context.window, display_panel, "data-display-panel", display_panel.display_item)
        return Window.ActionResult.FINISHED

    def is_checked(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel and context.display_panel.display_panel_type == "data_item"


class DisplayPanelShowGridBrowserAction(Window.Action):

    action_id = "display_panel.show_grid_browser"
    action_name = _("Grid Browser")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        display_panel = context.display_panel
        DisplayPanel.DisplayPanelManager().switch_to_display_content(context.window, display_panel, "browser-display-panel", display_panel.display_item)
        return Window.ActionResult.FINISHED

    def is_checked(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel and context.display_panel.display_panel_type == "grid"


class DisplayPanelShowThumbnailBrowserAction(Window.Action):

    action_id = "display_panel.show_thumbnail_browser"
    action_name = _("Thumbnail Browser")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        display_panel = context.display_panel
        DisplayPanel.DisplayPanelManager().switch_to_display_content(context.window, display_panel, "thumbnail-browser-display-panel", display_panel.display_item)
        return Window.ActionResult.FINISHED

    def is_checked(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel and context.display_panel.display_panel_type == "horizontal"


class DisplayPanelTwoViewAction(Window.Action):
    action_id = "display_panel.2_view"
    action_name = _("2:1 View")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        context.display_panel.perform_action("set_two_to_one_mode")
        return Window.ActionResult.FINISHED


class DisplayRemoveAction(Window.Action):
    action_id = "display.remove_display"
    action_name = _("Delete Display Item")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.processing_display_remove()
        return Window.ActionResult.FINISHED

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.display_items) >= 1

    def get_action_name(self, context: Window.ActionContext) -> str:
        context = typing.cast(DocumentController.ActionContext, context)
        display_item = context.display_item
        if context.display_item:
            return _("Delete Display Item") + f" \"{display_item.title}\""
        elif context.display_items:
            return _("Delete Display Items") + f" ({len(context.display_items)})"
        return self.action_name


class DisplayRevealAction(Window.Action):
    action_id = "display.reveal"
    action_name = _("Reveal in Data Panel")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.select_display_items_in_data_panel([context.display_item])
        return Window.ActionResult.FINISHED

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None


Window.register_action(DisplayCopyAction())
Window.register_action(DisplayPanelClearAction())
Window.register_action(DisplayPanelFitToViewAction())
Window.register_action(DisplayPanelFillViewAction())
Window.register_action(DisplayPanelOneViewAction())
Window.register_action(DisplayPanelShowItemAction())
Window.register_action(DisplayPanelShowGridBrowserAction())
Window.register_action(DisplayPanelShowThumbnailBrowserAction())
Window.register_action(DisplayPanelTwoViewAction())
Window.register_action(DisplayRemoveAction())
Window.register_action(DisplayRevealAction())


class AssignVariableReference(Window.Action):
    action_id = "item.assign_variable_reference"
    action_name = _("Assign Variable Reference")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.prepare_data_item_script()
        return Window.ActionResult.FINISHED


class CopyItemUUIDAction(Window.Action):
    action_id = "item.copy_uuid"
    action_name = _("Copy Item UUID")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.copy_uuid()
        return Window.ActionResult.FINISHED


class CreateDataItemAction(Window.Action):
    action_id = "item.create_data_item"
    action_name = _("Create New Data Item")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.create_empty_data_item()
        return Window.ActionResult.FINISHED


class DuplicateAction(Window.Action):
    action_id = "item.duplicate"
    action_name = _("Duplicate")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.processing_duplicate()
        return Window.ActionResult.FINISHED


class SnapshotAction(Window.Action):
    action_id = "item.snapshot"
    action_name = _("Snapshot")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.processing_snapshot()
        return Window.ActionResult.FINISHED


Window.register_action(AssignVariableReference())
Window.register_action(CopyItemUUIDAction())
Window.register_action(CreateDataItemAction())
Window.register_action(DuplicateAction())
Window.register_action(SnapshotAction())


class AddLineGraphicAction(Window.Action):
    action_id = "graphics.add_line_graphic"
    action_name = _("Add Line Graphic")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.add_line_graphic()
        return Window.ActionResult.FINISHED


class AddEllipseGraphicAction(Window.Action):
    action_id = "graphics.add_ellipse_graphic"
    action_name = _("Add Ellipse Graphic")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.add_ellipse_graphic()
        return Window.ActionResult.FINISHED


class AddRectangleGraphicAction(Window.Action):
    action_id = "graphics.add_rectangle_graphic"
    action_name = _("Add Rectangle Graphic")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.add_rectangle_graphic()
        return Window.ActionResult.FINISHED


class AddPointGraphicAction(Window.Action):
    action_id = "graphics.add_point_graphic"
    action_name = _("Add Point Graphic")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.add_point_graphic()
        return Window.ActionResult.FINISHED


class AddIntervalGraphicAction(Window.Action):
    action_id = "graphics.add_interval_graphic"
    action_name = _("Add Interval Graphic")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.add_interval_graphic()
        return Window.ActionResult.FINISHED


class AddChannelGraphicAction(Window.Action):
    action_id = "graphics.add_channel_graphic"
    action_name = _("Add Channel Graphic")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.add_channel_graphic()
        return Window.ActionResult.FINISHED


class AddGraphicToMaskAction(Window.Action):
    action_id = "graphics.add_graphic_mask"
    action_name = _("Add to Mask")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.add_graphic_mask()
        return Window.ActionResult.FINISHED


class AddSpotGraphicAction(Window.Action):
    action_id = "graphics.add_spot_graphic"
    action_name = _("Add Spot Filter")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.add_spot_graphic()
        return Window.ActionResult.FINISHED


class AddAngleGraphicAction(Window.Action):
    action_id = "graphics.add_angle_graphic"
    action_name = _("Add Angle Filter")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.add_angle_graphic()
        return Window.ActionResult.FINISHED


class AddBandPassGraphicAction(Window.Action):
    action_id = "graphics.add_band_pass_graphic"
    action_name = _("Add Band Pass Filter")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.add_band_pass_graphic()
        return Window.ActionResult.FINISHED


class AddLatticeGraphicAction(Window.Action):
    action_id = "graphics.add_lattice_graphic"
    action_name = _("Add Lattice Filter")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.add_lattice_graphic()
        return Window.ActionResult.FINISHED


class RemoveGraphicFromMaskAction(Window.Action):
    action_id = "graphics.remove_graphic_mask"
    action_name = _("Remove from Mask")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window.remove_graphic_mask()
        return Window.ActionResult.FINISHED


Window.register_action(AddLineGraphicAction())
Window.register_action(AddEllipseGraphicAction())
Window.register_action(AddRectangleGraphicAction())
Window.register_action(AddPointGraphicAction())
Window.register_action(AddIntervalGraphicAction())
Window.register_action(AddChannelGraphicAction())
Window.register_action(AddGraphicToMaskAction())
Window.register_action(AddSpotGraphicAction())
Window.register_action(AddAngleGraphicAction())
Window.register_action(AddBandPassGraphicAction())
Window.register_action(AddLatticeGraphicAction())
Window.register_action(RemoveGraphicFromMaskAction())


class ProcessingAction(Window.Action):

    def invoke_processing(self, context: Window.ActionContext, fn) -> None:
        typing.cast(DocumentController, context.window)._perform_processing_select(context.display_item, context.crop_graphic, fn)

    def invoke_processing2(self, context: Window.ActionContext, fn) -> None:
        data_sources = typing.cast(DocumentController, context.window)._get_two_data_sources()
        if data_sources:
            (display_item1, crop_graphic1), (display_item2, crop_graphic2) = data_sources
            return typing.cast(DocumentController, context.window)._perform_processing2(display_item1, display_item1.data_item, display_item2, display_item2.data_item, crop_graphic1, crop_graphic2, fn)
        return None

    def invoke_processing3(self, context: Window.ActionContext, fn) -> None:
        if context.display_item:
            display_item, crop_graphic = context.display_item, context.crop_graphic
            return typing.cast(DocumentController, context.window)._perform_processing3(display_item, display_item.data_item, display_item, display_item.data_item, display_item, display_item.data_item, crop_graphic, crop_graphic, crop_graphic, fn)
        return None


class AddAction(ProcessingAction):
    action_id = "processing.add"
    action_name = _("Add")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing2(context, context.model.get_add_new)
        return Window.ActionResult.FINISHED


class AutoCorrelateAction(ProcessingAction):
    action_id = "processing.auto_correlate"
    action_name = _("Auto Correlate")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_auto_correlate_new)
        return Window.ActionResult.FINISHED


class CropAction(ProcessingAction):
    action_id = "processing.crop"
    action_name = _("Crop")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_crop_new)
        return Window.ActionResult.FINISHED


class CrossCorrelateAction(ProcessingAction):
    action_id = "processing.cross_correlate"
    action_name = _("Cross Correlate")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing2(context, context.model.get_cross_correlate_new)
        return Window.ActionResult.FINISHED


class DivideAction(ProcessingAction):
    action_id = "processing.divide"
    action_name = _("Divide")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing2(context, context.model.get_divide_new)
        return Window.ActionResult.FINISHED


class ExtractAlphaAction(ProcessingAction):
    action_id = "processing.rgb_alpha"
    action_name = _("Extract Alpha Channel")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing3(context, context.model.get_rgb_alpha_new)
        return Window.ActionResult.FINISHED


class ExtractBlueAction(ProcessingAction):
    action_id = "processing.rgb_blue"
    action_name = _("Extract Blue Channel")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_rgb_blue_new)
        return Window.ActionResult.FINISHED


class ExtractGreenAction(ProcessingAction):
    action_id = "processing.rgb_green"
    action_name = _("Extract Green Channel")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_rgb_green_new)
        return Window.ActionResult.FINISHED


class ExtractLuminanceAction(ProcessingAction):
    action_id = "processing.rgb_luminance"
    action_name = _("Extract Luminance")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_rgb_luminance_new)
        return Window.ActionResult.FINISHED


class ExtractRedAction(ProcessingAction):
    action_id = "processing.rgb_red"
    action_name = _("Extract Red Channel")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_rgb_red_new)
        return Window.ActionResult.FINISHED


class FourierFilterAction(ProcessingAction):
    action_id = "processing.fourier_filter"
    action_name = _("Fourier Filter")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window._perform_processing_select(context.display_item, None, context.model.get_fourier_filter_new)
        return Window.ActionResult.FINISHED


class FFTAction(ProcessingAction):
    action_id = "processing.fft"
    action_name = _("FFT")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_fft_new)
        return Window.ActionResult.FINISHED


class GaussianFilterAction(ProcessingAction):
    action_id = "processing.gaussian_filter"
    action_name = _("Gaussian Filter")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_gaussian_blur_new)
        return Window.ActionResult.FINISHED


class HistogramAction(ProcessingAction):
    action_id = "processing.histogram"
    action_name = _("Histogram")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_histogram_new)
        return Window.ActionResult.FINISHED


class InverseFFTAction(ProcessingAction):
    action_id = "processing.inverse_fft"
    action_name = _("Inverse FFT")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_ifft_new)
        return Window.ActionResult.FINISHED


class LaplaceFilterAction(ProcessingAction):
    action_id = "processing.laplace_filter"
    action_name = _("Laplace Filter")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_laplace_new)
        return Window.ActionResult.FINISHED


class LineProfileAction(ProcessingAction):
    action_id = "processing.line_profile"
    action_name = _("Line Profile")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_line_profile_new)
        return Window.ActionResult.FINISHED


class MaskAction(ProcessingAction):
    action_id = "processing.mask"
    action_name = _("Mask")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_mask_new)
        return Window.ActionResult.FINISHED


class MaskedAction(ProcessingAction):
    action_id = "processing.masked"
    action_name = _("Masked")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_masked_new)
        return Window.ActionResult.FINISHED


class MedianFilterAction(ProcessingAction):
    action_id = "processing.median_filter"
    action_name = _("Median Filter")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_median_filter_new)
        return Window.ActionResult.FINISHED


class MultiplyAction(ProcessingAction):
    action_id = "processing.multiply"
    action_name = _("Multiply")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing2(context, context.model.get_multiply_new)
        return Window.ActionResult.FINISHED


class NegateAction(ProcessingAction):
    action_id = "processing.negate"
    action_name = _("Negate")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_invert_new)
        return Window.ActionResult.FINISHED


class PickAction(ProcessingAction):
    action_id = "processing.pick"
    action_name = _("Pick")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_pick_new)
        return Window.ActionResult.FINISHED


class PickAverageAction(ProcessingAction):
    action_id = "processing.pick_average"
    action_name = _("Pick (Average)")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_pick_region_average_new)
        return Window.ActionResult.FINISHED


class PickSumAction(ProcessingAction):
    action_id = "processing.pick_sum"
    action_name = _("Pick (Sum)")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_pick_region_new)
        return Window.ActionResult.FINISHED


class ProjectionSumAction(ProcessingAction):
    action_id = "processing.projection_sum"
    action_name = _("Projection (Sum)")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_projection_new)
        return Window.ActionResult.FINISHED


class RebinAction(ProcessingAction):
    action_id = "processing.rebin"
    action_name = _("Rebin")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_rebin_new)
        return Window.ActionResult.FINISHED


class ResampleAction(ProcessingAction):
    action_id = "processing.resample"
    action_name = _("Resample")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_resample_new)
        return Window.ActionResult.FINISHED


class ResizeAction(ProcessingAction):
    action_id = "processing.resize"
    action_name = _("Resize")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_resize_new)
        return Window.ActionResult.FINISHED


class RGBAction(ProcessingAction):
    action_id = "processing.make_rgb"
    action_name = _("Make RGB")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing3(context, context.model.get_rgb_new)
        return Window.ActionResult.FINISHED


class ScalarAction(ProcessingAction):
    action_id = "processing.scalar"
    action_name = _("Convert to Scalar")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_convert_to_scalar_new)
        return Window.ActionResult.FINISHED


class SequenceAlignFourierAction(ProcessingAction):
    action_id = "processing.sequence_align_fourier"
    action_name = _("Align (Fourier)")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_sequence_fourier_align_new)
        return Window.ActionResult.FINISHED


class SequenceAlignSplineAction(ProcessingAction):
    action_id = "processing.sequence_align_spline_1"
    action_name = _("Align (Spline 1st Order)")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_sequence_align_new)
        return Window.ActionResult.FINISHED


class SequenceExtractAction(ProcessingAction):
    action_id = "processing.sequence_extract"
    action_name = _("Extract")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_sequence_extract_new)
        return Window.ActionResult.FINISHED


class SequenceIntegrateAction(ProcessingAction):
    action_id = "processing.sequence_integrate"
    action_name = _("Integrate")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_sequence_integrate_new)
        return Window.ActionResult.FINISHED


class SequenceMeasureShiftsAction(ProcessingAction):
    action_id = "processing.sequence_measure_shifts"
    action_name = _("Measure Shifts")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_sequence_measure_shifts_new)
        return Window.ActionResult.FINISHED


class SequenceTrimAction(ProcessingAction):
    action_id = "processing.sequence_trim"
    action_name = _("Trim")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_sequence_trim_new)
        return Window.ActionResult.FINISHED


class SliceSumAction(ProcessingAction):
    action_id = "processing.slice_sum"
    action_name = _("Slice Sum")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.window.document_model.get_slice_sum_new)
        return Window.ActionResult.FINISHED


class SobelFilterAction(ProcessingAction):
    action_id = "processing.sobel_filter"
    action_name = _("Sobel Filter")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_sobel_new)
        return Window.ActionResult.FINISHED


class SubtractAction(ProcessingAction):
    action_id = "processing.subtract"
    action_name = _("Subtract")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing2(context, context.model.get_subtract_new)
        return Window.ActionResult.FINISHED


class SubtractAverageAction(ProcessingAction):
    action_id = "processing.subtract_average"
    action_name = _("Subtract Region Average")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_subtract_region_average_new)
        return Window.ActionResult.FINISHED


class TransformAction(ProcessingAction):
    action_id = "processing.transform"
    action_name = _("Transpose and Flip")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_transpose_flip_new)
        return Window.ActionResult.FINISHED


class UniformFilterAction(ProcessingAction):
    action_id = "processing.uniform_filter"
    action_name = _("Uniform Filter")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        self.invoke_processing(context, context.model.get_uniform_filter_new)
        return Window.ActionResult.FINISHED


class ProcessingComponentAction(ProcessingAction):
    def __init__(self, processing_id: str, title: str):
        self.action_id = "processing." + processing_id
        self.action_name = title
        self.__processing_id = processing_id

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context.window._perform_processing_select(context.display_item, None, functools.partial(context.model.get_processing_new, self.__processing_id))
        return Window.ActionResult.FINISHED


Window.register_action(AddAction())
Window.register_action(AutoCorrelateAction())
Window.register_action(CropAction())
Window.register_action(CrossCorrelateAction())
Window.register_action(DivideAction())
Window.register_action(ExtractAlphaAction())
Window.register_action(ExtractBlueAction())
Window.register_action(ExtractGreenAction())
Window.register_action(ExtractLuminanceAction())
Window.register_action(ExtractRedAction())
Window.register_action(FourierFilterAction())
Window.register_action(FFTAction())
Window.register_action(GaussianFilterAction())
Window.register_action(HistogramAction())
Window.register_action(InverseFFTAction())
Window.register_action(LaplaceFilterAction())
Window.register_action(LineProfileAction())
Window.register_action(MaskAction())
Window.register_action(MaskedAction())
Window.register_action(MedianFilterAction())
Window.register_action(MultiplyAction())
Window.register_action(NegateAction())
Window.register_action(PickAction())
Window.register_action(PickAverageAction())
Window.register_action(PickSumAction())
Window.register_action(ProjectionSumAction())
Window.register_action(RebinAction())
Window.register_action(ResampleAction())
Window.register_action(ResizeAction())
Window.register_action(RGBAction())
Window.register_action(ScalarAction())
Window.register_action(SliceSumAction())
Window.register_action(SequenceAlignFourierAction())
Window.register_action(SequenceAlignSplineAction())
Window.register_action(SequenceExtractAction())
Window.register_action(SequenceIntegrateAction())
Window.register_action(SequenceMeasureShiftsAction())
Window.register_action(SequenceTrimAction())
Window.register_action(SobelFilterAction())
Window.register_action(SubtractAction())
Window.register_action(SubtractAverageAction())
Window.register_action(TransformAction())
Window.register_action(UniformFilterAction())


def component_changed(component, component_types):
    # when a processing component is registered, create a ProcessingComponentAction for the
    # processing component.
    if "processing-component" in component_types:
        processing_component = typing.cast(Processing.ProcessingBase, component)
        Window.register_action(ProcessingComponentAction(processing_component.processing_id, processing_component.title))


component_registered_event_listener = Registry.listen_component_registered_event(component_changed)
Registry.fire_existing_component_registered_events("processing-component")

try:
    action_shortcuts_dict = json.loads(pkgutil.get_data(__name__, "resources/key_config.json").decode("utf8"))
    Window.register_action_shortcuts(action_shortcuts_dict)
except Exception as e:
    logging.error("Could not read key configuration.")
