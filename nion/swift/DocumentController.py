from __future__ import annotations

# standard libraries
import copy
import contextlib
import dataclasses
import datetime
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
from nion.swift import GeneratorDialog
from nion.swift import ImageCanvasItem
from nion.swift import MimeTypes
from nion.swift import NotificationDialog
from nion.swift import Panel
from nion.swift import ProjectItemsDialog
from nion.swift import RecorderPanel
from nion.swift import ScriptsDialog
from nion.swift import Task
from nion.swift import Undo
from nion.swift import Workspace
from nion.swift.model import Changes
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DisplayItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import ImportExportManager
from nion.swift.model import Notification
from nion.swift.model import Persistence
from nion.swift.model import Processing
from nion.swift.model import Profile
from nion.swift.model import Project
from nion.swift.model import Symbolic
from nion.swift.model import UISettings
from nion.swift.model import Utility
from nion.swift.model import WorkspaceLayout
from nion.ui import CanvasItem
from nion.ui import Dialog
from nion.ui import PreferencesDialog
from nion.ui import Window
from nion.ui import UserInterface
from nion.utils import Color
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ListModel
from nion.utils import Observable
from nion.utils import Process
from nion.utils import Registry
from nion.utils import Selection

if typing.TYPE_CHECKING:
    from nion.swift import Application

_DataSourceTupleType = typing.Tuple[DisplayItem.DisplayItem, typing.Optional[Graphics.Graphic]]
_ProcessingFn = typing.Callable[[DisplayItem.DisplayItem, DataItem.DataItem, typing.Optional[Graphics.Graphic]], typing.Optional[DataItem.DataItem]]
_Processing2Fn = typing.Callable[[DisplayItem.DisplayItem, DataItem.DataItem, DisplayItem.DisplayItem, DataItem.DataItem, typing.Optional[Graphics.Graphic], typing.Optional[Graphics.Graphic]], typing.Optional[DataItem.DataItem]]
_Processing3Fn = typing.Callable[[DisplayItem.DisplayItem, DataItem.DataItem, DisplayItem.DisplayItem, DataItem.DataItem, DisplayItem.DisplayItem, DataItem.DataItem, typing.Optional[Graphics.Graphic], typing.Optional[Graphics.Graphic], typing.Optional[Graphics.Graphic]], typing.Optional[DataItem.DataItem]]

_ = gettext.gettext


def is_graphic_valid_crop_for_data_item(data_item: typing.Optional[DataItem.DataItem], graphic: typing.Optional[Graphics.Graphic]) -> bool:
    if data_item and graphic:
        if data_item.is_datum_1d and isinstance(graphic, Graphics.IntervalGraphic):
            return True
        elif data_item.is_datum_2d and isinstance(graphic, Graphics.RectangleTypeGraphic):
            return True
    return False


PeriodicFn = typing.Callable[[], None]

class PeriodicListener:
    def __init__(self, interval: float, listener_fn: PeriodicFn) -> None:
        self.interval = interval
        # the call function is very performance critical; make it fast by using a property
        # instead of a logic statement each time.
        if callable(listener_fn):
            self.call = listener_fn
        else:
            def void() -> None:
                pass

            self.call = void
        self.next_scheduled_time = time.time() + interval

    def close(self) -> None:
        def void() -> None:
            pass

        self.call = void


class PeriodicMonitor:
    """Periodic monitor.

    Notes about auditing:
    - thread.start
    - call_soon_threadsafe
    - call_on_main_thread
    - event_loop.call_soon
    - event_loop.run_in_executor
    - async def or event_loop.create_task
    - executor.submit
    """

    def __init__(self, ui: UserInterface.UserInterface, slow_duration: float = 0.02) -> None:
        self.__ui = ui
        self.__slow_duration = slow_duration
        self.__start_event = threading.Event()
        self.__start_event_time = 0.0
        self.__end_event = threading.Event()
        self.__cancel = False
        self.__monitor_thread: typing.Optional[threading.Thread] = None

    def start(self) -> None:
        self.__monitor_thread = threading.Thread(target=self.run)
        self.__monitor_thread.start()

    def close(self) -> None:
        self.__cancel = True
        if self.__monitor_thread:
            self.__monitor_thread.join(1.0)
            self.__monitor_thread = None

    def enter(self) -> None:
        Process._audit.clear()
        self.__start_event_time = time.perf_counter()
        self.__start_event.set()

    def exit(self) -> None:
        duration = time.perf_counter() - self.__start_event_time
        if Process._audit_enabled and (duration > self.__slow_duration):
            Process._audit.report()
            print(f"SLOW {int(duration*1000)}ms")
        self.__end_event.set()

    def run(self) -> None:
        while not self.__cancel:
            while not self.__cancel:
                self.__start_event.wait(0.1)
                if self.__start_event.is_set():
                    break
            if not self.__cancel:
                self.__start_event.clear()
                self.__end_event.clear()
                self.__end_event.wait(self.__slow_duration)
            if not self.__cancel and not self.__end_event.is_set():
                import sys, datetime, traceback
                stack = sys._current_frames().get(threading.main_thread().ident or 0)
                if stack:
                    print(f"WRITE HANG {self.__ui.get_data_location()}")
                    with open(os.path.join(self.__ui.get_data_location(), "hang.txt"), 'a') as f:
                        f.write("--------------------------------------\n")
                        f.write("HANG " + str(datetime.datetime.now()) + "\n")
                        f.write("--------------------------------------\n")
                        traceback.print_stack(stack, file=f)
                        f.write("\n")


_PeriodicListenerWeakRef = typing.Callable[[], typing.Optional[PeriodicListener]]


class DocumentController(Window.Window):
    """Manage a document window."""
    count = 0  # useful for detecting leaks in tests

    def __init__(self, ui: UserInterface.UserInterface, document_model: DocumentModel.DocumentModel,
                 workspace_id: typing.Optional[str] = None, app: typing.Optional[Application.Application] = None,
                 project_reference: typing.Optional[Profile.ProjectReference] = None) -> None:
        super().__init__(ui, app)

        self.__periodic_monitor = PeriodicMonitor(ui, 0.010)  # 10 ms
        # self.__periodic_monitor.start()
        # Process._audit_enabled = True

        # self.event_loop.set_debug(True)  # Enable debug
        # self.event_loop.slow_callback_duration = 0.010  # 10 ms

        self.__project_reference = project_reference
        self.__class__.count += 1

        self.__undo_stack = Undo.UndoStack()

        self.__closed = False  # debugging

        self.uuid = uuid.uuid4()

        self.task_created_event = Event.Event()
        self.cursor_changed_event = Event.Event()
        self.tool_mode_changed_event = Event.Event()

        self.__last_activity: typing.Optional[float] = None

        # document_model may be shared between several DocumentControllers, so use reference counting
        # to determine when to close it.
        self.document_model = document_model
        self.document_model.add_ref()
        app_version = getattr(app, "version_str", "")
        self.__base_title = _("Nion Swift") + ((" " + app_version) if app else "")
        self.title = self.__base_title
        if project_reference:
            self.window_file_path = project_reference.path
        self.__workspace_controller: typing.Optional[Workspace.Workspace] = None
        self.__workspace_display_panel_content_changed_event_listener: typing.Optional[Event.EventListener] = None
        self.replaced_display_panel_content_flag = False  # whether to set replaced display panel content
        self.replaced_display_panel_content: typing.Optional[Persistence.PersistentDictType] = None  # used to facilitate display panel functionality to exchange displays
        self.__selected_display_panel: typing.Optional[DisplayPanel.DisplayPanel] = None
        self.__secondary_display_panels: typing.List[DisplayPanel.DisplayPanel] = list()
        self.__tool_mode = "pointer"
        self.__weak_periodic_listeners: typing.List[_PeriodicListenerWeakRef] = list()
        self.__weak_periodic_listeners_mutex = threading.RLock()

        self.selection = Selection.IndexedSelection()
        self.selection.expanded_changed_event = True

        # the user has two ways of filtering data items: first by selecting a data group (or none) in the data panel,
        # and next by applying a custom filter to the items from the items resulting in the first selection.
        # data items model tracks the main list of items selected in the data panel.
        # filtered display items model tracks the filtered items from those in data items model.
        self.__display_items_model = ListModel.FilteredListModel(container=self.document_model, items_key="display_items")
        typing.cast(typing.Any, self.__display_items_model).filter_id = None  # extra tracking field. fix typing in 3.8.
        self.__filtered_display_items_model = ListModel.FilteredListModel(items_key="display_items", container=self.__display_items_model)

        def filtered_display_items_item_removed(selection: Selection.IndexedSelection, key: str, value: DisplayItem.DisplayItem, index: int) -> None:
            selection.remove_index(index)

        self.__filtered_display_items_item_removed_event_listener = self.__filtered_display_items_model.item_removed_event.listen(functools.partial(filtered_display_items_item_removed, self.selection))

        self.__last_display_filter = ListModel.Filter(True)
        self.filter_changed_event = Event.Event()

        # see set_filter
        with self.__display_items_model.changes():  # change filter and sort together
            self.__display_items_model.container = self.document_model
            self.__display_items_model.filter = ListModel.AndFilter((self.project_filter, self.get_filter_predicate(None)))
            self.__display_items_model.sort_key = DisplayItem.sort_by_date_key
            self.__display_items_model.sort_reverse = True
            typing.cast(typing.Any, self.__display_items_model).filter_id = None

        def call_soon() -> None:
            # call the function (this is guaranteed to be called on the main thread)
            self.document_model.perform_call_soon()

        def queue_call_soon() -> None:
            # queue the function on the main thread
            self.queue_task(call_soon)

        # listen for requests from the document model to call a function on the main thread.
        self.__call_soon_event_listener = self.document_model.call_soon_event.listen(queue_call_soon)

        self.document_model.perform_all_call_soon()  # perform any pending items in the queue

        self.filter_controller = FilterPanel.FilterController(self)

        self.focused_display_item_changed_event = Event.Event()
        self.__focused_display_item: typing.Optional[DisplayItem.DisplayItem] = None
        self.__selected_display_items: typing.List[DisplayItem.DisplayItem] = list()
        self.__selected_display_item: typing.Optional[DisplayItem.DisplayItem] = None
        self.__selection_changed_listener = self.selection.changed_event.listen(self.__update_selected_display_items)

        self.__consoles: typing.List[ConsoleDialog.ConsoleDialog] = list()

        self._create_menus()
        if workspace_id:  # used only when testing reference counting
            self.__workspace_controller = Workspace.Workspace(self, workspace_id)
            self.__workspace_controller.restore(self.project.workspace_uuid)

            def handle_workspace_display_panel_content_changed_event(display_panel: DisplayPanel.DisplayPanel) -> None:
                self.__update_selected_display_items()

            self.__workspace_display_panel_content_changed_event_listener = self.__workspace_controller.display_panel_content_changed_event.listen(handle_workspace_display_panel_content_changed_event)

        if app:
            for menu_handler in app.menu_handlers:  # use 'handler' to avoid name collision
                menu_handler(self)

    def close(self) -> None:
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
        self.__periodic_monitor.close()
        self.__periodic_monitor = typing.cast(typing.Any, None)
        self._finish_periodic()  # required to finish periodic operations during tests
        # dialogs
        self._close_dialogs()
        if self.__workspace_controller:
            self.__workspace_controller.close()
            self.__workspace_controller = None
        if self.__workspace_display_panel_content_changed_event_listener:
            self.__workspace_display_panel_content_changed_event_listener.close()
            self.__workspace_display_panel_content_changed_event_listener = None
        self.__undo_stack.close()
        self.__undo_stack = typing.cast(typing.Any, None)
        self.__selection_changed_listener.close()
        self.__selection_changed_listener = typing.cast(typing.Any, None)
        self.__filtered_display_items_item_removed_event_listener.close()
        self.__filtered_display_items_item_removed_event_listener = typing.cast(typing.Any, None)
        self.__call_soon_event_listener.close()
        self.__call_soon_event_listener = typing.cast(typing.Any, None)
        self.__filtered_display_items_model.close()
        self.__filtered_display_items_model = typing.cast(typing.Any, None)
        self.filter_controller.close()
        self.filter_controller = typing.cast(typing.Any, None)
        self.__display_items_model.close()
        self.__display_items_model = typing.cast(typing.Any, None)
        # document_model may be shared between several DocumentControllers, so use reference counting
        # to determine when to close it.
        self.document_model.remove_ref()
        self.document_model = typing.cast(typing.Any, None)
        self.__class__.count -= 1
        super().close()

    def _register_ui_activity(self) -> None:
        self.__last_activity = time.time()

    def about_to_show(self) -> None:
        workspace_controller = self.workspace_controller
        if workspace_controller:
            geometry, state = workspace_controller.restore_geometry_state()
            self.restore(geometry, state)

    def about_to_close(self, geometry: str, state: str) -> None:
        workspace_controller = self.workspace_controller
        if workspace_controller:
            workspace_controller.save_geometry_state(geometry, state)
        super().about_to_close(geometry, state)

    def register_console(self, console: ConsoleDialog.ConsoleDialog) -> None:
        self.__consoles.append(console)

    def unregister_console(self, console: ConsoleDialog.ConsoleDialog) -> None:
        self.__consoles.remove(console)

    @property
    def consoles(self) -> typing.Sequence[ConsoleDialog.ConsoleDialog]:
        return self.__consoles

    def _create_menus(self) -> None:
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

        menu_descriptions: typing.Sequence[Persistence.PersistentDictType] = list()
        try:
            json_bytes = pkgutil.get_data(__name__, "resources/menu_config.json")
            assert json_bytes is not None
            menu_descriptions = typing.cast(typing.Sequence[Persistence.PersistentDictType], json.loads(json_bytes.decode("utf8")))
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

        self.__dynamic_live_actions: typing.List[UserInterface.MenuAction] = list()

        self.__dynamic_view_actions: typing.List[UserInterface.MenuAction] = list()

        self.__dynamic_window_actions: typing.List[UserInterface.MenuAction] = list()

    def get_menu(self, menu_id: str) -> typing.Optional[UserInterface.Menu]:
        assert menu_id.endswith("_menu")
        return typing.cast(typing.Optional[UserInterface.Menu], getattr(self, menu_id, None))

    def get_or_create_menu(self, menu_id: str, menu_title: str, before_menu_id: typing.Optional[str]) -> UserInterface.Menu:
        assert menu_id.endswith("_menu")
        assert before_menu_id.endswith("_menu") if before_menu_id is not None else True
        if not hasattr(self, "_" + menu_id):
            before_menu = getattr(self, "_" + before_menu_id) if before_menu_id is not None else None
            menu = self.insert_menu(menu_title, before_menu)
            setattr(self, "_" + menu_id, menu)
        return typing.cast(UserInterface.Menu, getattr(self, "_" + menu_id))

    def show_about_box(self) -> None:
        typing.cast(typing.Any, self.app).show_about_box(self)

    def find_dock_panel(self, dock_panel_id: str) -> typing.Optional[Panel.Panel]:
        """ Return the dock widget by id. """
        workspace_controller = self.workspace_controller
        if workspace_controller:
            return workspace_controller._find_dock_panel(dock_panel_id)
        return None

    def add_periodic(self, interval: float, listener_fn: PeriodicFn) -> PeriodicListener:
        """Add a listener function and return listener token. Token can be closed or deleted to unlisten."""
        listener = PeriodicListener(interval, listener_fn)

        def remove_listener(weak_listener: _PeriodicListenerWeakRef) -> None:
            with self.__weak_periodic_listeners_mutex:
                self.__weak_periodic_listeners.remove(weak_listener)

        weak_listener = weakref.ref(listener, remove_listener)
        with self.__weak_periodic_listeners_mutex:
            self.__weak_periodic_listeners.append(weak_listener)
        return listener

    def periodic(self) -> None:
        self.__periodic_monitor.enter()
        try:
            with self.__weak_periodic_listeners_mutex:
                periodic_listeners = copy.copy(self.__weak_periodic_listeners)
            current_time = time.time()
            for weak_periodic_listener in periodic_listeners:
                periodic_listener = weak_periodic_listener()
                if periodic_listener and current_time >= periodic_listener.next_scheduled_time:
                    try:
                        with Process.audit(f"periodic_listener.{periodic_listener}"):
                            periodic_listener.call()
                    except Exception as e:
                        import traceback
                        logging.debug("Event Error: %s", e)
                        traceback.print_exc()
                        traceback.print_stack()
                    periodic_listener.next_scheduled_time = current_time + periodic_listener.interval
            super().periodic()
            with Process.audit("perform_data_item_updates"):
                self.document_model.perform_data_item_updates()
            if self.workspace_controller:
                with Process.audit("workspace_controller"):
                    self.workspace_controller.periodic()
            if self.__last_activity is not None and time.time() - self.__last_activity > 60 * 60:
                pass  # self.app.choose_library()
        finally:
            self.__periodic_monitor.exit()

    @property
    def _undo_stack(self) -> Undo.UndoStack:
        return self.__undo_stack

    @property
    def last_undo_command(self) -> typing.Optional[Undo.UndoableCommand]:
        return self.__undo_stack.last_command

    def push_undo_command(self, undo_command: Undo.UndoableCommand) -> None:
        if undo_command:
            self.__undo_stack.push(undo_command)
        else:
            self.__undo_stack.clear()

    def pop_undo_command(self) -> None:
        self.__undo_stack.pop_command()

    @property
    def workspace_controller(self) -> typing.Optional[Workspace.Workspace]:
        return self.__workspace_controller

    @property
    def workspace(self) -> typing.Optional[Workspace.Workspace]:
        return self.__workspace_controller

    def _workspace_changed(self, workspace: WorkspaceLayout.WorkspaceLayout) ->  None:
        title = self.__base_title
        project_title = self.__project_reference.title if self.__project_reference else None
        if project_title:
            title += " - " + project_title
        if workspace and workspace.name:
            title += ": " + workspace.name
        self.title = title

    def refocus_widget(self, widget: UserInterface.Widget) -> None:
        display_panel = self.selected_display_panel
        if display_panel:
            display_panel.request_focus()
        else:
            super().refocus_widget(widget)

    def request_refocus(self) -> None:
        display_panel = self.selected_display_panel
        if display_panel:
            display_panel.request_focus()

    @property
    def project(self) -> Project.Project:
        return self.document_model._project

    @property
    def display_items_model(self) -> ListModel.FilteredListModel:
        return self.__display_items_model

    @property
    def filtered_display_items_model(self) -> ListModel.FilteredListModel:
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

    def set_data_group(self, data_group: typing.Optional[DataGroup.DataGroup]) -> None:
        if self.__display_items_model is not None:
            container = data_group if data_group else self.document_model
            if container != self.__display_items_model.container:
                with self.__display_items_model.changes():  # change filter and sort together
                    self.__display_items_model.container = data_group
                    self.__display_items_model.filter = self.project_filter
                    self.__display_items_model.sort_key = None
                    typing.cast(typing.Any, self.__display_items_model).filter_id = None
                self.filter_changed_event.fire(data_group, self.__display_items_model.filter_id)

    def set_filter(self, filter_id: typing.Optional[str]) -> None:
        if self.__display_items_model is not None:
            if filter_id != self.__display_items_model.filter_id:
                with self.__display_items_model.changes():  # change filter and sort together
                    self.__display_items_model.container = self.document_model
                    self.__display_items_model.filter = ListModel.AndFilter((self.project_filter, self.get_filter_predicate(filter_id)))
                    self.__display_items_model.sort_key = DisplayItem.sort_by_date_key
                    self.__display_items_model.sort_reverse = True
                    typing.cast(typing.Any, self.__display_items_model).filter_id = filter_id
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
    def selected_display_items(self) -> typing.Sequence[DisplayItem.DisplayItem]:
        """Return the selected display items.

        The selected display items are the display items that have keyboard focus in the display panel
         or the data panel.
        """
        return list(self.__selected_display_items)  # copy

    @property
    def selected_data_items(self) -> typing.Sequence[DataItem.DataItem]:
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
            self.__selected_display_items = list(display_panel.display_items)
            for secondary_display_panel in self.__secondary_display_panels:
                self.__selected_display_items.extend(list(secondary_display_panel.display_items))
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
        associated_display_items = list()
        for data_item in data_items:
            display_item = document_model.get_display_item_for_data_item(data_item)
            if display_item:
                associated_display_items.append(display_item)
        self.select_display_items_in_data_panel(associated_display_items)

    # track the selected data item. this can be called by ui elements when
    # they get focus. the selected data item will stay the same until another ui
    # element gets focus or the data item is removed from the document.
    def notify_focused_display_changed(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> None:
        if self.__focused_display_item != display_item:
            self.__focused_display_item = display_item
            self.focused_display_item_changed_event.fire(display_item)

    @property
    def focused_display_item(self) -> typing.Optional[DisplayItem.DisplayItem]:
        """Return the display with keyboard focus."""
        return self.__selected_display_item

    def select_data_item_in_data_panel(self, data_item: typing.Optional[DataItem.DataItem]) -> None:
        """Select the data item in the data panel."""
        self.select_data_items_in_data_panel([data_item] if data_item else [])

    def select_data_group_in_data_panel(self, data_group: DataGroup.DataGroup, data_item: typing.Optional[DataItem.DataItem] = None) -> None:
        # used for testing only
        self.set_data_group(data_group)
        self.select_data_item_in_data_panel(data_item)

    def select_filter_in_data_panel(self, filter_id: str) -> None:
        # used for testing only
        self.set_filter(filter_id)

    def delete_display_items(self, display_items: typing.Sequence[DisplayItem.DisplayItem], container: typing.Optional[Observable.Observable] = None) -> None:
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

    def display_panel_finish_drag(self, display_panel: DisplayPanel.DisplayPanel, action: str) -> None:
        # replaced_display_panel_content should only be set when dragging from another display panel
        # it is used to remove/swap the old content. but we need to be careful that the content doesn't
        # get left around for another drag and cause unexpected behavior.
        if action == "move" and self.replaced_display_panel_content is not None:
            d = self.replaced_display_panel_content
            display_panel.change_display_panel_content(d)
            last_command = self.last_undo_command
            if isinstance(last_command, Workspace.ChangeWorkspaceContentsCommand):
                workspace_controller = self.workspace_controller
                assert workspace_controller
                command = Workspace.ChangeWorkspaceContentsCommand(workspace_controller,
                                                                   _("Replace Display Panel"),
                                                                   last_command._old_workspace_layout)
                self.pop_undo_command()
                self.push_undo_command(command)
        self.replaced_display_panel_content_flag = False
        self.replaced_display_panel_content = None

    @property
    def selected_display_panel(self) -> typing.Optional[DisplayPanel.DisplayPanel]:
        return self.__selected_display_panel

    @selected_display_panel.setter
    def selected_display_panel(self, selected_display_panel: typing.Optional[DisplayPanel.DisplayPanel]) -> None:
        if selected_display_panel != self.__selected_display_panel:
            # save the selected panel
            self.__selected_display_panel = selected_display_panel
            self.__secondary_display_panels.clear()
            # tell the workspace the selected image panel changed so that it can update the focus/selected rings
            self.__update_display_panels()
            self.__update_selected_display_items()

    @property
    def secondary_display_panels(self) -> typing.Sequence[DisplayPanel.DisplayPanel]:
        return self.__secondary_display_panels

    def add_secondary_display_panel(self, display_panel: DisplayPanel.DisplayPanel) -> None:
        if display_panel not in self.__secondary_display_panels:
            self.__secondary_display_panels.append(display_panel)
            self.__update_display_panels()
            self.__update_selected_display_items()

    def remove_secondary_display_panel(self, display_panel: DisplayPanel.DisplayPanel) -> None:
        if display_panel in self.__secondary_display_panels:
            self.__secondary_display_panels.remove(display_panel)
            self.__update_display_panels()
            self.__update_selected_display_items()

    def toggle_secondary_display_panel(self, display_panel: DisplayPanel.DisplayPanel) -> None:
        if display_panel in self.__secondary_display_panels:
            self.__secondary_display_panels.remove(display_panel)
        else:
            self.__secondary_display_panels.append(display_panel)
        self.__update_display_panels()
        self.__update_selected_display_items()

    def clear_secondary_display_panels(self) -> None:
        for display_panel in list(self.__secondary_display_panels):
            self.__secondary_display_panels.remove(display_panel)
        self.__update_display_panels()
        self.__update_selected_display_items()

    def __update_display_panels(self) -> None:
        selected_display_panel = self.selected_display_panel
        workspace_controller = self.workspace_controller
        display_panels = workspace_controller.display_panels if workspace_controller else list()
        for display_panel in display_panels:
            display_panel.set_selected(display_panel == selected_display_panel)
            if display_panel in self.__secondary_display_panels:
                display_panel.set_secondary_index(self.__secondary_display_panels.index(display_panel))
            else:
                display_panel.set_secondary_index(None)

    def data_panel_focused(self) -> None:
        # the data panel will call this when it gets keyboard focus.
        # deselect the selected display panel and update the selected display items.
        self.selected_display_panel = None
        self.__update_selected_display_items()

    def next_result_display_panel(self) -> typing.Optional[DisplayPanel.DisplayPanel]:
        workspace_controller = self.workspace_controller
        display_panels = workspace_controller.display_panels if workspace_controller else list()
        for display_panel in display_panels:
            if display_panel.is_result_panel:
                return display_panel
        return None

    # this can be called from any user interface element that wants to update the cursor info
    # in the data panel. this would typically be from the image or line plot canvas.
    def cursor_changed(self, text_items: typing.Optional[typing.List[str]]) -> None:
        self.cursor_changed_event.fire(text_items)

    @property
    def tool_mode(self) -> str:
        return self.__tool_mode

    @tool_mode.setter
    def tool_mode(self, tool_mode: str) -> None:
        self.__tool_mode = tool_mode
        self.tool_mode_changed_event.fire(tool_mode)

    def _import_folder(self) -> None:
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

    def import_file(self) -> None:
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
        if len(paths) > 0:
            self.ui.set_persistent_string("import_directory", selected_directory)
            self.receive_files(paths, display_panel=self.next_result_display_panel())

    def export_file(self, display_item: DisplayItem.DisplayItem) -> None:
        # present a loadfile dialog to the user
        writers = ImportExportManager.ImportExportManager().get_writers_for_display_item(display_item)
        name_writer_dict: typing.Dict[typing.Tuple[str, str], typing.Any] = dict()  # TODO: fix writer typing
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
        filter_str = ";;".join(filter_lines)
        filter_str += ";;All Files (*.*)"
        export_dir = self.ui.get_persistent_string("export_directory", self.ui.get_document_location())
        export_dir = os.path.join(export_dir, display_item.displayed_title)
        selected_filter = self.ui.get_persistent_string("export_filter")
        path, selected_filter, selected_directory = self.get_save_file_path(_("Export File"), export_dir, filter_str, selected_filter)
        selected_writer = filter_line_to_writer_map.get(selected_filter)
        if path and not os.path.splitext(path)[1]:
            if selected_writer:
                path = path + os.path.extsep + selected_writer.extensions[0]
        if selected_writer and path:
            self.ui.set_persistent_string("export_directory", selected_directory)
            self.ui.set_persistent_string("export_filter", selected_filter)
            ImportExportManager.ImportExportManager().write_display_item_with_writer(selected_writer, display_item, pathlib.Path(path))

    def export_files(self, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> None:
        if len(display_items) > 0:
            ExportDialog.ExportDialog(self.ui, self, display_items)

    def export_svg_file(self, ui_settings: UISettings.UISettings, display_item: DisplayItem.DisplayItem, display_shape: Geometry.IntSize, path: pathlib.Path) -> None:
        # take a snapshot so to modify the display properties for the proper image zoom, position, and canvas mode.
        # ensure that the snapshot is closed when finished.
        display_item_snapshot = display_item.snapshot()
        try:
            # update the zoom, position, and canvas mode for the export. these are neutral values that ensure it will
            # draw at 1:1 scale and centered in the canvas.
            display_properties = display_item_snapshot.display_properties
            display_properties["image_zoom"] = 1.0
            display_properties["image_position"] = (0.5, 0.5)
            display_properties["image_canvas_mode"] = "fit"
            display_item_snapshot.display_properties = display_properties
            # create the drawing context and shape for the preview
            drawing_context, shape = DisplayPanel.preview(ui_settings, display_item_snapshot, display_shape.width, display_shape.height)
            # set up the SVG
            view_box = Geometry.IntRect(Geometry.IntPoint(), shape)
            svg = drawing_context.to_svg(shape, view_box)
            # write the file
            with Utility.AtomicFileWriter(path.with_suffix(".svg")) as fp:
                fp.write(svg)
        finally:
            display_item_snapshot.close()

    def export_svg(self, display_item: DisplayItem.DisplayItem) -> None:
        ExportDialog.ExportSVGDialog(self, display_item)

    # this method creates a task. it is thread safe.
    def create_task_context_manager(self, title: str, task_type: str, logging: bool = True) -> Task.TaskContextManager:
        task = Task.Task(title, task_type)  # NOTE: currently, tasks don't get deleted since they are displayed until exit.
        task_context_manager = Task.TaskContextManager(self, task, logging)
        self.task_created_event.fire(task)
        return task_context_manager

    def open_preferences(self) -> None:
        if not self.is_dialog_type_open(PreferencesDialog.PreferencesDialog) and self.app:
            preferences_dialog = PreferencesDialog.PreferencesDialog(self.ui, self.app)
            preferences_dialog.show()

    def new_console_dialog(self) -> None:
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
            match_items: typing.Set[Persistence.PersistentObject] = set()
            match_items.add(display_item)
            match_items.update(display_item.data_items)
            match_items.update(display_item.graphics)
            computations_set = set()
            for computation in document_model.computations:
                if set(computation.output_items).intersection(match_items):
                    computations_set.add(computation)
                if set(computation.input_items).intersection(match_items):
                    computations_set.add(computation)
            computations = list(computations_set)
            if len(computations) > 1:
                def handle_selection(computation: typing.Optional[Symbolic.Computation]) -> None:
                    if computation:
                        ComputationPanel.InspectComputationDialog(self, computation)

                Dialog.pose_select_item_pop_up(computations, handle_selection,
                                               window=self, current_item=0,
                                               item_getter=operator.attrgetter("label"))
                return
            elif len(computations) == 1:
                ComputationPanel.InspectComputationDialog(self, computations[0])
                return
        Notification.notify(Notification.Notification("nion.inspector.no-target", "\N{WARNING SIGN} Edit Computation",
                                                      "No associated computation",
                                                      "The selected display/data item has no associated computation"))

    def new_display_editor_dialog(self, display_item: typing.Optional[DisplayItem.DisplayItem] = None) -> None:
        if not display_item:
            display_item = self.selected_display_item
        if display_item:
            edit_display_dialog = DisplayEditorPanel.DisplayEditorDialog(self, display_item)
            edit_display_dialog.show()

    def new_recorder_dialog(self, data_item: typing.Optional[DataItem.DataItem] = None) -> None:
        if not data_item:
            data_item = self.selected_data_item
        if data_item:
            recorder_dialog = RecorderPanel.RecorderDialog(self, data_item)
            recorder_dialog.show()

    def open_project_item(self, item: typing.Any) -> None:
        # open the project dialog if not open already and select the object corresponding to or containing the item.
        if not getattr(self, "_project_items_dialog", None):
            self.perform_action("window.project_items_dialog")
        # get the dialog again, which may have been opened
        project_items_dialog = typing.cast(typing.Optional[ProjectItemsDialog.ProjectItemsDialog], getattr(self, "_project_items_dialog", None))
        if project_items_dialog:
            project_items_dialog.open_project_item(item)

    def __deep_copy(self) -> None:
        self._dispatch_any_to_focus_widget("handle_deep_copy")

    def handle_undo(self) -> None:
        if self.__undo_stack.can_undo:
            self.__undo_stack.undo()

    def get_undo_menu_item_state(self) -> UserInterface.MenuItemState:
        self.__undo_stack.validate()
        return UserInterface.MenuItemState(title=self.__undo_stack.undo_title, enabled=self.__undo_stack.can_undo, checked=False)

    def handle_redo(self) -> None:
        if self.__undo_stack.can_redo:
            self.__undo_stack.redo()

    def get_redo_menu_item_state(self) -> UserInterface.MenuItemState:
        return UserInterface.MenuItemState(title=self.__undo_stack.redo_title, enabled=self.__undo_stack.can_redo, checked=False)

    def handle_copy(self) -> None:
        self.copy_selected_graphics()

    def handle_cut(self) -> None:
        self.copy_selected_graphics()
        self.remove_selected_graphics()

    def handle_paste(self) -> bool:
        display_item = self.selected_display_item
        if display_item:
            mime_data = self.ui.clipboard_mime_data()
            graphics = MimeTypes.mime_data_get_graphics(mime_data)
            if graphics:
                display_item.graphic_selection.clear()
                insert_command = DisplayPanel.InsertGraphicsCommand(self, display_item, graphics)
                insert_command.perform()
                self.push_undo_command(insert_command)
                for graphic in graphics:
                    display_item.graphic_selection.add(display_item.graphics.index(graphic))
                return True
            display_item_to_paste = MimeTypes.mime_data_get_display_item(mime_data, self.document_model)
            data_item_to_paste = display_item_to_paste.data_item if display_item_to_paste else None
            if display_item_to_paste and data_item_to_paste:
                append_command = DisplayPanel.AppendDisplayDataChannelCommand(self.document_model, display_item, data_item_to_paste, display_item_to_paste.display_layers[0])
                append_command.perform()
                self.push_undo_command(append_command)
        return False

    def handle_delete(self) -> None:
        # delete key gets handled by key handlers, but this method gets called by menu items
        self.remove_selected_graphics()

    def add_display_data_channel_to_composite(self, target_display_item: DisplayItem.DisplayItem, display_item: DisplayItem.DisplayItem) -> bool:
        # append the display data channel of the display_item to the target_display_item.
        # the display_item must have a single data item.
        # this is used for stacking line plot layers.
        # returns True if success else False.
        data_item = display_item.data_item if display_item else None
        if data_item and target_display_item:
            command = DisplayPanel.AppendDisplayDataChannelCommand(self.document_model, target_display_item, data_item, display_item.display_layers[0])
            command.perform()
            self.push_undo_command(command)
            return True
        return False

    class InsertDisplayItemCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: DocumentController, display_item: DisplayItem.DisplayItem, display_panel: DisplayPanel.DisplayPanel) -> None:
            super().__init__(_("Insert Display Item"))
            self.__document_controller = document_controller
            workspace_controller = self.__document_controller.workspace_controller
            self.__old_workspace_layout: typing.Optional[Persistence.PersistentDictType] = workspace_controller.deconstruct() if workspace_controller else None
            self.__new_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None
            self.__display_item_proxy: typing.Optional[Persistence.PersistentObjectProxy[DisplayItem.DisplayItem]] = None
            self.__display_item = display_item
            self.__display_panel = display_panel
            self.__undelete_log: typing.Optional[Changes.UndeleteLog] = None
            self.initialize()

        def close(self) -> None:
            self.__document_controller = typing.cast(typing.Any, None)
            if self.__display_item_proxy:
                self.__display_item_proxy.close()
                self.__display_item_proxy = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            if self.__undelete_log:
                self.__undelete_log.close()
                self.__undelete_log = None
            self.__display_panel = typing.cast(typing.Any, None)
            super().close()

        def perform(self) -> None:
            display_item = self.__display_item
            self.__display_item_proxy = display_item.create_proxy() if display_item else None
            self.__display_panel.set_display_item(display_item)

        def _get_modified_state(self) -> typing.Any:
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _redo(self) -> None:
            assert self.__undelete_log
            self.__document_controller.document_model.undelete_all(self.__undelete_log)
            self.__undelete_log.close()
            self.__undelete_log = None
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            assert self.__new_workspace_layout is not None
            workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self) -> None:
            display_item = self.__display_item_proxy.item if self.__display_item_proxy else None
            assert display_item
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            self.__new_workspace_layout = workspace_controller.deconstruct()
            self.__undelete_log = self.__document_controller.document_model.remove_display_item_with_log(display_item)
            assert self.__old_workspace_layout is not None
            workspace_controller.reconstruct(self.__old_workspace_layout)

    def add_display_data_channel_to_or_create_composite(self, target_display_item: DisplayItem.DisplayItem, display_item: DisplayItem.DisplayItem, display_panel: DisplayPanel.DisplayPanel) -> typing.Optional[DisplayItem.DisplayItem]:
        data_item = display_item.data_item if display_item else None
        if data_item and target_display_item:
            if target_display_item.display_data_channel:
                new_display_item = target_display_item.snapshot()
                self.document_model.append_display_item(new_display_item)
                display_layer = copy.deepcopy(display_item.display_layers[0])
                with contextlib.closing(display_layer):
                    display_layer_color_str = display_layer.fill_color or display_layer.stroke_color or DisplayItem.DisplayItem.DEFAULT_COLORS[0]
                    display_layer_color_str = target_display_item.get_unique_display_layer_color(Color.Color(display_layer_color_str))
                    display_layer.fill_color = None
                    display_layer.stroke_color = display_layer_color_str
                    display_layer_properties = display_layer.get_display_layer_properties()
                new_display_item.append_display_data_channel_for_data_item(data_item, display_layer_properties)
                command = DocumentController.InsertDisplayItemCommand(self, new_display_item, display_panel)
                command.perform()
                self.push_undo_command(command)
                return new_display_item
            elif self.add_display_data_channel_to_composite(target_display_item, display_item):
                return target_display_item
        return None

    class InsertDataGroupDisplayItemsCommand(Undo.UndoableCommand):
        def __init__(self, document_model: DocumentModel.DocumentModel, data_group: DataGroup.DataGroup, before_index: int, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> None:
            super().__init__("Insert Data Items")
            self.__document_model = document_model
            self.__data_group_proxy = data_group.create_proxy()
            self.__before_index = before_index
            self.__display_item_proxies = [display_item.create_proxy() for display_item in display_items]
            self.initialize()

        def close(self) -> None:
            self.__document_model = typing.cast(typing.Any, None)
            self.__data_group_proxy.close()
            self.__data_group_proxy = typing.cast(typing.Any, None)
            for display_item_proxy in self.__display_item_proxies:
                display_item_proxy.close()
            self.__display_item_proxies = typing.cast(typing.Any, None)
            super().close()

        def _get_modified_state(self) -> typing.Any:
            data_group = self.__data_group_proxy.item
            assert data_group
            return data_group.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            data_group = self.__data_group_proxy.item
            assert data_group
            data_group.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return bool(state1[0] == state2[0])

        def perform(self) -> None:
            data_group = self.__data_group_proxy.item
            assert data_group
            display_items = [display_item_proxy.item for display_item_proxy in self.__display_item_proxies]
            for index, display_item in enumerate(display_items):
                if display_item:
                    data_group.insert_display_item(self.__before_index + index, display_item)

        def _undo(self) -> None:
            data_group = self.__data_group_proxy.item
            assert data_group
            display_items_len = len(self.__display_item_proxies)
            for index in reversed(range(display_items_len)):
                data_group.remove_display_item(data_group.display_items[self.__before_index + index])

        def _redo(self) -> None:
            self.perform()

    def create_insert_data_group_display_items_command(self, data_group: DataGroup.DataGroup, before_index: int, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> InsertDataGroupDisplayItemsCommand:
        return DocumentController.InsertDataGroupDisplayItemsCommand(self.document_model, data_group, before_index, display_items)

    class InsertDataGroupDataItemsCommand(Undo.UndoableCommand):
        def __init__(self, document_controller: DocumentController, data_group: DataGroup.DataGroup, data_items: typing.Sequence[DataItem.DataItem], index: int) -> None:
            super().__init__("Insert Data Items")
            self.__document_controller = document_controller
            self.__data_group_proxy = data_group.create_proxy()
            self.__data_group_indexes: typing.List[int] = list()
            self.__data_group_display_item_proxies: typing.List[Persistence.PersistentObjectProxy[DisplayItem.DisplayItem]] = list()
            self.__data_items = data_items  # only in perform
            self.__display_item_index = index
            self.__display_item_indexes: typing.List[int] = list()
            self.__undelete_logs: typing.List[Changes.UndeleteLog] = list()
            self.initialize()

        def close(self) -> None:
            self.__document_controller = typing.cast(typing.Any, None)
            self.__data_group_indexes = typing.cast(typing.Any, None)
            for display_item_proxy in self.__data_group_display_item_proxies:
                display_item_proxy.close()
            self.__data_group_display_item_proxies = typing.cast(typing.Any, None)
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = typing.cast(typing.Any, None)
            self.__data_group_proxy.close()
            self.__data_group_proxy = typing.cast(typing.Any, None)
            super().close()

        def _get_modified_state(self) -> typing.Any:
            data_group = self.__data_group_proxy.item
            assert data_group
            return self.__document_controller.document_model.modified_state, data_group.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            data_group = self.__data_group_proxy.item
            assert data_group
            self.__document_controller.document_model.modified_state, data_group.modified_state = modified_state

        def perform(self) -> None:
            document_model = self.__document_controller.document_model
            data_group = self.__data_group_proxy.item
            assert data_group
            index = self.__display_item_index
            display_items: typing.List[DisplayItem.DisplayItem] = list()
            for data_item in self.__data_items:
                document_model.append_data_item(data_item)
                self.__display_item_indexes.append(len(document_model.display_items))
                maybe_display_item = document_model.get_display_item_for_data_item(data_item)
                if maybe_display_item:
                    display_items.append(maybe_display_item)
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
            assert data_group
            display_items = [data_group.display_items[index] for index in self.__data_group_indexes]
            for display_item in display_items:
                if display_item in data_group.display_items:
                    data_group.remove_display_item(display_item)
            display_items = [document_model.display_items[index] for index in self.__display_item_indexes]
            for display_item in display_items:
                if display_item in document_model.display_items:
                    self.__undelete_logs.append(document_model.remove_display_item_with_log(display_item))

        def _redo(self) -> None:
            data_group = self.__data_group_proxy.item
            assert data_group
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            index = self.__display_item_index
            display_items = [display_item_proxy.item for display_item_proxy in reversed(self.__data_group_display_item_proxies)]
            for display_item in display_items:
                if display_item and not display_item in data_group.display_items:
                    data_group.insert_display_item(index, display_item)

    class RemoveDataGroupDisplayItemsCommand(Undo.UndoableCommand):
        def __init__(self, document_model: DocumentModel.DocumentModel, data_group: DataGroup.DataGroup, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> None:
            super().__init__("Remove Data Item")
            self.__document_model = document_model
            self.__data_group_proxy = data_group.create_proxy()
            combined = [(data_group.display_items.index(display_item), display_item) for display_item in display_items]
            combined = sorted(combined, key=operator.itemgetter(0), reverse=True)
            self.__display_item_indexes = list(map(operator.itemgetter(0), combined))
            self.__display_item_proxies = [display_item.create_proxy() for index, display_item in combined]
            self.initialize()

        def close(self) -> None:
            self.__data_group_proxy.close()
            self.__data_group_proxy = typing.cast(typing.Any, None)
            for display_item_proxy in self.__display_item_proxies:
                display_item_proxy.close()
            self.__display_item_proxies = typing.cast(typing.Any, None)
            super().close()

        def _get_modified_state(self) -> typing.Any:
            data_group = self.__data_group_proxy.item
            assert data_group
            return data_group.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            data_group = self.__data_group_proxy.item
            assert data_group
            data_group.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return bool(state1[0] == state2[0])

        def perform(self) -> None:
            data_group = self.__data_group_proxy.item
            assert data_group
            display_items = [data_group.display_items[index] for index in self.__display_item_indexes]
            for display_item in display_items:
                if display_item in data_group.display_items:
                    data_group.remove_display_item(display_item)

        def _undo(self) -> None:
            data_group = self.__data_group_proxy.item
            assert data_group
            display_items = [display_item_proxy.item for display_item_proxy in self.__display_item_proxies]
            for index, display_item in zip(self.__display_item_indexes, display_items):
                if display_item:
                    data_group.insert_display_item(index, display_item)

        def _redo(self) -> None:
            self.perform()

    class RenameDataGroupCommand(Undo.UndoableCommand):
        def __init__(self, document_model: DocumentModel.DocumentModel, data_group: DataGroup.DataGroup, title: str) -> None:
            super().__init__("Rename Data Group")
            self.__document_model = document_model
            self.__data_group_proxy = data_group.create_proxy()
            self.__title = title
            self.__new_title = str()
            self.initialize()

        def close(self) -> None:
            self.__data_group_proxy.close()
            self.__data_group_proxy = typing.cast(typing.Any, None)
            super().close()

        def _get_modified_state(self) -> typing.Any:
            data_group = self.__data_group_proxy.item
            assert data_group
            return data_group.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            data_group = self.__data_group_proxy.item
            assert data_group
            data_group.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return bool(state1[0] == state2[0])

        def perform(self) -> None:
            data_group = self.__data_group_proxy.item
            assert data_group
            self.__new_title = data_group.title
            data_group.title = self.__title

        def _undo(self) -> None:
            data_group = self.__data_group_proxy.item
            assert data_group
            data_group.title = self.__new_title

        def _redo(self) -> None:
            self.perform()

    def create_rename_data_group_command(self, data_group: DataGroup.DataGroup, title: str) -> RenameDataGroupCommand:
        return DocumentController.RenameDataGroupCommand(self.document_model, data_group, title)

    class InsertDataGroupCommand(Undo.UndoableCommand):
        def __init__(self, document_model: DocumentModel.DocumentModel, container: typing.Union[DataGroup.DataGroup, Project.Project], before_index: int, data_group: DataGroup.DataGroup) -> None:
            super().__init__("Insert Data Group")
            self.__document_model = document_model
            self.__container_proxy = container.create_proxy()
            self.__before_index = before_index
            self.__data_group_properties = data_group.write_to_dict()
            self.__data_group_proxy: typing.Optional[Persistence.PersistentObjectProxy[DataGroup.DataGroup]] = None
            self.initialize()
            data_group.close()  # clean up

        def close(self) -> None:
            if self.__data_group_proxy:
                self.__data_group_proxy.close()
                self.__data_group_proxy = None
            self.__container_proxy.close()
            self.__container_proxy = typing.cast(typing.Any, None)
            super().close()

        def _get_modified_state(self) -> typing.Any:
            container = self.__container_proxy.item
            assert container
            return container.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            container = self.__container_proxy.item
            assert container
            container.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return bool(state1[0] == state2[0])

        def perform(self) -> None:
            container = self.__container_proxy.item
            assert container
            data_group = DataGroup.DataGroup()
            assert data_group
            data_group.read_from_dict(self.__data_group_properties)
            container.insert_item("data_groups", self.__before_index, data_group)
            self.__data_group_proxy = data_group.create_proxy()

        def _undo(self) -> None:
            assert self.__data_group_proxy
            container = self.__container_proxy.item
            assert container
            data_group = self.__data_group_proxy.item
            assert data_group
            container.remove_item("data_groups", data_group)
            self.__data_group_proxy.close()
            self.__data_group_proxy = None

        def _redo(self) -> None:
            self.perform()

    class RemoveDataGroupCommand(Undo.UndoableCommand):
        def __init__(self, document_model: DocumentModel.DocumentModel, container: typing.Union[DataGroup.DataGroup, Project.Project], data_group: DataGroup.DataGroup) -> None:
            super().__init__("Remove Data Group")
            self.__document_model = document_model
            self.__container_proxy = container.create_proxy()
            self.__data_group_proxy = data_group.create_proxy()
            self.__data_group_properties: typing.Optional[Persistence.PersistentDictType] = None
            self.__data_group_index: typing.Optional[int] = None
            self.initialize()

        def close(self) -> None:
            self.__data_group_proxy.close()
            self.__data_group_proxy = typing.cast(typing.Any, None)
            self.__container_proxy.close()
            self.__container_proxy = typing.cast(typing.Any, None)
            super().close()

        def _get_modified_state(self) -> typing.Any:
            container = self.__container_proxy.item
            assert container
            return container.modified_state, self.__document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            container = self.__container_proxy.item
            assert container
            container.modified_state, self.__document_model.modified_state = modified_state

        def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
            # override to allow the undo command to track state; but only use part of the state for comparison
            return bool(state1[0] == state2[0])

        def perform(self) -> None:
            container = self.__container_proxy.item
            assert container
            data_group = self.__data_group_proxy.item
            assert data_group
            self.__data_group_properties = data_group.write_to_dict()
            self.__data_group_index = container.data_groups.index(data_group)
            container.remove_item("data_groups", data_group)

        def _undo(self) -> None:
            container = self.__container_proxy.item
            assert container
            data_group = DataGroup.DataGroup()
            assert data_group
            data_group.begin_reading()
            if self.__data_group_properties:
                data_group.read_from_dict(self.__data_group_properties)
            data_group.finish_reading()
            assert self.__data_group_index is not None
            container.insert_item("data_groups", self.__data_group_index, data_group)

        def _redo(self) -> None:
            self.perform()

    def add_group(self) -> None:
        data_group = DataGroup.DataGroup()
        data_group.title = _("Untitled Group")
        command = DocumentController.InsertDataGroupCommand(self.document_model, self.document_model._project, 0, data_group)
        command.perform()
        self.push_undo_command(command)

    def remove_data_group_from_container(self, data_group: DataGroup.DataGroup, container: typing.Union[DataGroup.DataGroup, Project.Project]) -> None:
        data_group_empty = len(data_group.display_items) == 0 and len(data_group.data_groups) == 0
        if data_group_empty:
            assert data_group in container.data_groups
            command = DocumentController.RemoveDataGroupCommand(self.document_model, container, data_group)
            command.perform()
            self.push_undo_command(command)

    def add_line_graphic(self) -> typing.Optional[Graphics.Graphic]:
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.LineGraphic()
            graphic.start = Geometry.FloatPoint(0.2, 0.2)
            graphic.end = Geometry.FloatPoint(0.8, 0.8)
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_rectangle_graphic(self) -> typing.Optional[Graphics.Graphic]:
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = Geometry.FloatRect(Geometry.FloatPoint(0.25,0.25), Geometry.FloatSize(0.5,0.5))
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_ellipse_graphic(self) -> typing.Optional[Graphics.Graphic]:
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.EllipseGraphic()
            graphic.bounds = Geometry.FloatRect(Geometry.FloatPoint(0.25,0.25), Geometry.FloatSize(0.5,0.5))
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_point_graphic(self) -> typing.Optional[Graphics.Graphic]:
        display_item = self.selected_display_item
        if display_item:
            graphic = Graphics.PointGraphic()
            graphic.position = Geometry.FloatPoint(0.5,0.5)
            command = DisplayPanel.InsertGraphicsCommand(self, display_item, [graphic])
            command.perform()
            self.push_undo_command(command)
            display_item.graphic_selection.set(display_item.graphics.index(graphic))
            return graphic
        return None

    def add_interval_graphic(self) -> typing.Optional[Graphics.Graphic]:
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

    def add_channel_graphic(self) -> typing.Optional[Graphics.Graphic]:
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

    def add_spot_graphic(self) -> typing.Optional[Graphics.Graphic]:
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

    def add_angle_graphic(self) -> typing.Optional[Graphics.Graphic]:
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

    def add_band_pass_graphic(self) -> typing.Optional[Graphics.Graphic]:
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

    def add_lattice_graphic(self) -> typing.Optional[Graphics.Graphic]:
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
                graphics = list(itertools.filterfalse(lambda graphic: isinstance(graphic, (Graphics.SpotGraphic, Graphics.WedgeGraphic, Graphics.RingGraphic, Graphics.LatticeGraphic)), graphics))
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

    def copy_selected_graphics(self) -> bool:
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
        self.perform_action("display_panel.delete_graphics")

    class RemoveGraphicsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: DocumentController, display_item: DisplayItem.DisplayItem, graphics: typing.Sequence[Graphics.Graphic]) -> None:
            super().__init__(_("Remove Graphics"))
            self.__document_controller = document_controller
            self.__display_item_proxy = display_item.create_proxy()
            workspace_controller = self.__document_controller.workspace_controller
            self.__old_workspace_layout: typing.Optional[Persistence.PersistentDictType] = workspace_controller.deconstruct() if workspace_controller else None
            self.__new_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None
            self.__graphic_indexes = [display_item.graphics.index(graphic) for graphic in graphics]
            self.__undelete_logs: typing.List[Changes.UndeleteLog] = list()
            self.initialize()

        def close(self) -> None:
            self.__document_controller = typing.cast(typing.Any, None)
            self.__display_item_proxy.close()
            self.__display_item_proxy = typing.cast(typing.Any, None)
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__graphic_indexes = typing.cast(typing.Any, None)
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = typing.cast(typing.Any, None)
            super().close()

        def perform(self) -> None:
            display_item = self.__display_item_proxy.item
            if display_item:
                graphics = [display_item.graphics[index] for index in self.__graphic_indexes]
                for graphic in graphics:
                    self.__undelete_logs.append(display_item.remove_graphic(graphic, safe=True))

        def _get_modified_state(self) -> typing.Any:
            display_item = self.__display_item_proxy.item
            assert display_item
            return display_item.modified_state, self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            display_item = self.__display_item_proxy.item
            assert display_item
            display_item.modified_state, self.__document_controller.document_model.modified_state = modified_state

        def _undo(self) -> None:
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            self.__new_workspace_layout = workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            assert self.__old_workspace_layout is not None
            workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self) -> None:
            self.perform()
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            assert self.__new_workspace_layout is not None
            workspace_controller.reconstruct(self.__new_workspace_layout)

        def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
            # after inserting, a computation may be performed and change the document. this ensures that this
            # undo is still enabled after that happens.
            return True

    def create_remove_graphics_command(self, display_item: DisplayItem.DisplayItem, graphics: typing.Sequence[Graphics.Graphic]) -> DocumentController.RemoveGraphicsCommand:
        return DocumentController.RemoveGraphicsCommand(self, display_item, graphics)

    class RemoveDisplayItemsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: DocumentController, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> None:
            super().__init__(_("Remove Display Items"))
            self.__document_controller = document_controller
            workspace_controller = self.__document_controller.workspace_controller
            self.__old_workspace_layout: typing.Optional[Persistence.PersistentDictType] = workspace_controller.deconstruct() if workspace_controller else None
            self.__new_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None
            self.__display_item_indexes = [document_controller.document_model.display_items.index(display_item) for display_item in display_items]
            self.__undelete_logs: typing.List[Changes.UndeleteLog] = list()
            self.initialize()

        def close(self) -> None:
            self.__document_controller = typing.cast(typing.Any, None)
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__display_item_indexes = typing.cast(typing.Any, None)
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = typing.cast(typing.Any, None)
            super().close()

        def perform(self) -> None:
            document_model = self.__document_controller.document_model
            display_items = [document_model.display_items[index] for index in self.__display_item_indexes]
            for display_item in display_items:
                if display_item in document_model.display_items:
                    selected_display_items = list(self.__document_controller.selected_display_items)
                    if display_item in selected_display_items:
                        selected_display_items.remove(display_item)
                    self.__undelete_logs.append(document_model.remove_display_item_with_log(display_item))
                    self.__document_controller.select_display_items_in_data_panel(selected_display_items)

        def _get_modified_state(self) -> typing.Any:
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _undo(self) -> None:
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            self.__new_workspace_layout = workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            assert self.__old_workspace_layout is not None
            workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self) -> None:
            self.perform()
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            assert self.__new_workspace_layout is not None
            workspace_controller.reconstruct(self.__new_workspace_layout)

    def create_remove_display_items_command(self, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> Undo.UndoableCommand:
        return DocumentController.RemoveDisplayItemsCommand(self, display_items)

    class RemoveDataItemsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: DocumentController, data_items: typing.Sequence[DataItem.DataItem]) -> None:
            super().__init__(_("Remove Data Items"))
            self.__document_controller = document_controller
            workspace_controller = self.__document_controller.workspace_controller
            self.__old_workspace_layout: typing.Optional[Persistence.PersistentDictType] = workspace_controller.deconstruct() if workspace_controller else None
            self.__new_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None
            self.__data_item_indexes = [document_controller.document_model.data_items.index(data_item) for data_item in data_items]
            self.__undelete_logs: typing.List[Changes.UndeleteLog] = list()
            self.initialize()

        def close(self) -> None:
            self.__document_controller = typing.cast(typing.Any, None)
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__data_item_indexes = typing.cast(typing.Any, None)
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = typing.cast(typing.Any, None)
            super().close()

        def perform(self) -> None:
            document_model = self.__document_controller.document_model
            data_items = [document_model.data_items[index] for index in self.__data_item_indexes]
            for data_item in data_items:
                if data_item in document_model.data_items:
                    self.__undelete_logs.append(document_model.remove_data_item_with_log(data_item, safe=True))

        def _get_modified_state(self) -> typing.Any:
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _undo(self) -> None:
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            self.__new_workspace_layout = workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            assert self.__old_workspace_layout is not None
            workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self) -> None:
            self.perform()
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            assert self.__new_workspace_layout is not None
            workspace_controller.reconstruct(self.__new_workspace_layout)

    def create_remove_data_items_command(self, data_items: typing.Sequence[DataItem.DataItem]) -> Undo.UndoableCommand:
        return DocumentController.RemoveDataItemsCommand(self, data_items)

    def add_data_element(self, data_element: ImportExportManager.DataElementType, source_data_item: typing.Optional[DataItem.DataItem] = None) -> DataItem.DataItem:
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        if data_item:
            self.document_model.append_data_item(data_item)
        return data_item

    def add_data(self, data: DataAndMetadata._ImageDataType, title: typing.Optional[str] = None) -> DataItem.DataItem:
        data_element = { "data": data, "title": title }
        return self.add_data_element(data_element)

    def show_display_item(self, display_item: DisplayItem.DisplayItem, *,
                          source_display_item: typing.Optional[DisplayItem.DisplayItem] = None,
                          source_data_item: typing.Optional[DataItem.DataItem] = None,
                          request_focus: bool = True) -> None:
        # when a new item is shown, call this to find a display panel for it.
        # request focus can be passed as False to avoid focusing on the new
        # item, as may be preferred during live acquisition (snapshot).
        # previously, the inspector was also focused; this has been removed for
        # consistency. see https://github.com/nion-software/nionswift/issues/257.
        result_display_panel = self.next_result_display_panel()
        if result_display_panel:
            result_display_panel.set_display_panel_display_item(display_item)
            if request_focus:
                result_display_panel.request_focus()
        self.select_display_items_in_data_panel([display_item])

    def _perform_redimension(self, display_item: DisplayItem.DisplayItem, data_descriptor: DataAndMetadata.DataDescriptor) -> None:
        def process() -> DataItem.DataItem:
            assert display_item.data_item
            new_data_item = self.document_model.get_redimension_new(display_item, display_item.data_item, data_descriptor)
            assert new_data_item
            new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            assert new_display_item
            self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertDataItemCommand)
        if command.data_item:
            self.push_undo_command(command)
        else:
            command.close()

    def _perform_squeeze(self, display_item: DisplayItem.DisplayItem) -> None:
        def process() -> DataItem.DataItem:
            assert display_item.data_item
            new_data_item = self.document_model.get_squeeze_new(display_item, display_item.data_item)
            assert new_data_item
            new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            assert new_display_item
            self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertDataItemCommand)
        if command.data_item:
            self.push_undo_command(command)
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
        workspace_controller = self.workspace_controller
        assert workspace_controller
        toggle_actions = [dock_widget.toggle_action for dock_widget in workspace_controller.dock_widgets]
        for toggle_action in sorted(toggle_actions, key=operator.attrgetter("title")):
            menu.add_action(toggle_action)
            self.__dynamic_window_actions.append(toggle_action)

    def __adjust_workspace_menu(self, menu: UserInterface.Menu) -> None:
        menu.add_separator()
        for dynamic_view_action in self.__dynamic_view_actions:
            menu.remove_action(dynamic_view_action)
        self.__dynamic_view_actions = []
        for workspace in self.project.sorted_workspaces:
            def switch_to_workspace(workspace: WorkspaceLayout.WorkspaceLayout) -> None:
                workspace_controller = self.workspace_controller
                assert workspace_controller
                workspace_controller.change_workspace(workspace)

            workspace_timestamp = workspace.timestamp_for_sorting
            local_modified_datetime = workspace_timestamp + datetime.timedelta(minutes=Utility.local_utcoffset_minutes(workspace_timestamp))
            workspace_modified_str = local_modified_datetime.strftime('%Y-%m-%d')
            if local_modified_datetime.date() == datetime.date.today():
                workspace_modified_str = _("Today")
            elif local_modified_datetime.date() == datetime.date.today() - datetime.timedelta(days=1):
                workspace_modified_str = _("Yesterday")

            action = menu.add_menu_item(f"{workspace.name} ({workspace_modified_str})", functools.partial(switch_to_workspace, workspace))
            action.checked = self.project.workspace_uuid == workspace.uuid
            self.__dynamic_view_actions.append(action)

    def __about_to_show_display_type_menu(self, menu: UserInterface.Menu) -> None:
        for dynamic_live_action in self.__dynamic_live_actions:
            menu.remove_action(dynamic_live_action)
        dynamic_live_actions: typing.List[UserInterface.MenuAction] = list()
        selected_display_panel = self.selected_display_panel
        if selected_display_panel:
            dynamic_live_actions.extend(DisplayPanel.DisplayPanelManager().build_menu(menu, self, selected_display_panel))
        self.__dynamic_live_actions = dynamic_live_actions

    def __adjust_redimension_data_menu(self, menu: UserInterface.Menu) -> None:
        for action in self.__data_menu_actions:
            menu.remove_action(action)
        self.__data_menu_actions = list()
        selected_display_panel = self.selected_display_panel
        display_item = selected_display_panel.display_item if selected_display_panel else None
        data_item = display_item.data_item if display_item else None
        if data_item:

            def describe_data_descriptor(data_descriptor: DataAndMetadata.DataDescriptor, data_shape: typing.Sequence[int]) -> str:
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

            data_item_xdata = data_item.xdata

            # add (disabled) existing data type menu item
            if data_item_xdata:
                data_type_name = describe_data_descriptor(data_item_xdata.data_descriptor, data_item_xdata.data_shape)
                action = menu.add_menu_item(data_type_name, lambda: None)
                action.enabled = False
                self.__data_menu_actions.append(action)

            # add redimension menu items if available
            if data_item_xdata:
                for is_sequence, collection_dims, data_dims in itertools.product((True, False), (0, 1, 2), (1, 2)):
                    data_descriptor = DataAndMetadata.DataDescriptor(is_sequence, collection_dims, data_dims)
                    if data_descriptor.expected_dimension_count == data_item_xdata.data_descriptor.expected_dimension_count and data_descriptor != data_item_xdata.data_descriptor:
                        data_type_name = describe_data_descriptor(data_descriptor, data_item_xdata.data_shape)
                        action = menu.add_menu_item(_("Redimension to {}").format(data_type_name), functools.partial(self._perform_redimension, display_item, data_descriptor))
                        self.__data_menu_actions.append(action)

            # add squeeze menu item if available
            if data_item_xdata:
                data_descriptor = data_item_xdata.data_descriptor
                data_shape = list(data_item_xdata.data_shape)
                if 1 in data_shape[data_descriptor.collection_dimension_index_slice] or 1 in data_shape[data_descriptor.sequence_dimension_index_slice] and len(data_shape[data_descriptor.datum_dimension_index_slice]) > 1 and data_shape[data_descriptor.datum_dimension_index_slice].count(1) > 0:
                    if data_descriptor.is_sequence and typing.cast(int, data_shape[data_descriptor.sequence_dimension_index_slice]) == 1:
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
            action = menu.add_menu_item(_("No Data Selected"), lambda: None)
            action.enabled = False
            self.__data_menu_actions.append(action)

    def _get_crop_graphic(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> typing.Optional[Graphics.Graphic]:
        data_item = display_item.data_item if display_item else None
        current_index = display_item.graphic_selection.current_index if display_item else None
        graphic = display_item.graphics[current_index] if display_item and (current_index is not None) else None
        return graphic if is_graphic_valid_crop_for_data_item(data_item, graphic) else None

    def __get_mask_graphics(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> typing.Sequence[Graphics.Graphic]:
        mask_graphics = list()
        data_item = display_item.data_item if display_item else None
        if display_item and data_item and len(data_item.dimensional_shape) == 2:
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

        def __init__(self, document_controller: DocumentController, data_item_fn: typing.Callable[[], typing.Optional[DataItem.DataItem]]) -> None:
            super().__init__(_("Insert Data Item"))
            self.__document_controller = document_controller
            workspace_controller = self.__document_controller.workspace_controller
            self.__old_workspace_layout: typing.Optional[Persistence.PersistentDictType] = workspace_controller.deconstruct() if workspace_controller else None
            self.__new_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None
            self.__data_item_proxy: typing.Optional[Persistence.PersistentObjectProxy[DataItem.DataItem]] = None
            self.__data_item_fn = data_item_fn
            self.__undelete_log: typing.Optional[Changes.UndeleteLog] = None
            self.initialize()

        def close(self) -> None:
            self.__document_controller = typing.cast(typing.Any, None)
            self.__data_item_fn = typing.cast(typing.Any, None)
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            if self.__undelete_log:
                self.__undelete_log.close()
                self.__undelete_log = None
            if self.__data_item_proxy:
                self.__data_item_proxy.close()
                self.__data_item_proxy = None
            super().close()

        def perform(self) -> None:
            data_item = self.__data_item_fn()
            self.__data_item_proxy = data_item.create_proxy() if data_item else None

        @property
        def data_item(self) -> typing.Optional[DataItem.DataItem]:
            return self.__data_item_proxy.item if self.__data_item_proxy else None

        def _get_modified_state(self) -> typing.Any:
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _compare_modified_states(self, state1: typing.Any, state2: typing.Any) -> bool:
            # after inserting, a computation may be performed and change the document. this ensures that this
            # undo is still enabled after that happens.
            return True

        def _redo(self) -> None:
            assert self.__undelete_log
            self.__document_controller.document_model.undelete_all(self.__undelete_log)
            self.__undelete_log.close()
            self.__undelete_log = None
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            assert self.__new_workspace_layout is not None
            workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self) -> None:
            data_item = self.data_item
            assert data_item
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            self.__new_workspace_layout = workspace_controller.deconstruct()
            self.__undelete_log = self.__document_controller.document_model.remove_data_item_with_log(data_item, safe=True)
            assert self.__old_workspace_layout is not None
            workspace_controller.reconstruct(self.__old_workspace_layout)

    def create_insert_data_item_command(self, data_item_fn: typing.Callable[[], typing.Optional[DataItem.DataItem]]) -> Undo.UndoableCommand:
        return DocumentController.InsertDataItemCommand(self, data_item_fn)

    def _perform_duplicate(self, data_item: DataItem.DataItem) -> None:
        def process() -> DataItem.DataItem:
            new_data_item = self.document_model.copy_data_item(data_item)
            display_item = self.document_model.get_display_item_for_data_item(new_data_item)
            assert display_item
            self.show_display_item(display_item, source_data_item=data_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        self.push_undo_command(command)

    def processing_duplicate(self) -> None:
        data_item = self.selected_data_item
        if data_item:
            self._perform_duplicate(data_item)

    class InsertAndShowDisplayItemCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: DocumentController, display_item: DisplayItem.DisplayItem, display_item_fn: typing.Callable[[DisplayItem.DisplayItem], DisplayItem.DisplayItem]) -> None:
            super().__init__(_("Insert Display Item"))
            self.__document_controller = document_controller
            workspace_controller = self.__document_controller.workspace_controller
            self.__old_workspace_layout: typing.Optional[Persistence.PersistentDictType] = workspace_controller.deconstruct() if workspace_controller else None
            self.__new_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None
            self.__display_item_proxy: typing.Optional[Persistence.PersistentObjectProxy[DisplayItem.DisplayItem]] = None
            self.__display_item = display_item
            self.__display_item_fn = display_item_fn
            self.__undelete_log: typing.Optional[Changes.UndeleteLog] = None
            self.initialize()

        def close(self) -> None:
            self.__document_controller = typing.cast(typing.Any, None)
            if self.__display_item_proxy:
                self.__display_item_proxy.close()
                self.__display_item_proxy = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            if self.__undelete_log:
                self.__undelete_log.close()
                self.__undelete_log = None
            super().close()

        def perform(self) -> None:
            # regarding focus, see https://github.com/nion-software/nionswift/issues/145
            document_controller = self.__document_controller
            display_item = self.__display_item
            request_focus = not display_item.is_live
            snapshot_display_item = self.__display_item_fn(display_item)
            document_controller.show_display_item(snapshot_display_item, source_display_item=snapshot_display_item, request_focus=request_focus)
            self.__display_item_proxy = display_item.create_proxy() if display_item else None

        def _get_modified_state(self) -> typing.Any:
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _redo(self) -> None:
            assert self.__undelete_log
            self.__document_controller.document_model.undelete_all(self.__undelete_log)
            self.__undelete_log.close()
            self.__undelete_log = None
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            assert self.__new_workspace_layout is not None
            workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self) -> None:
            display_item = self.__display_item_proxy.item if self.__display_item_proxy else None
            assert display_item
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            self.__new_workspace_layout = workspace_controller.deconstruct()
            self.__undelete_log = self.__document_controller.document_model.remove_display_item_with_log(display_item)
            assert self.__old_workspace_layout is not None
            workspace_controller.reconstruct(self.__old_workspace_layout)

    def _perform_display_item_snapshot(self, display_item: DisplayItem.DisplayItem) -> None:
        command = DocumentController.InsertAndShowDisplayItemCommand(self, display_item, self.document_model.get_display_item_snapshot_new)
        command.perform()
        self.push_undo_command(command)

    def processing_snapshot(self) -> None:
        display_item = self.selected_display_item
        if display_item:
            self._perform_display_item_snapshot(display_item)

    def processing_display_copy(self, display_item: DisplayItem.DisplayItem) -> None:
        command = DocumentController.InsertAndShowDisplayItemCommand(self, display_item, self.document_model.get_display_item_copy_new)
        command.perform()
        self.push_undo_command(command)

    def processing_display_snapshot(self, display_item: DisplayItem.DisplayItem) -> None:
        command = DocumentController.InsertAndShowDisplayItemCommand(self, display_item, self.document_model.get_display_snapshot_new)
        command.perform()
        self.push_undo_command(command)

    class RemoveDisplayItemCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: DocumentController, display_item: DisplayItem.DisplayItem) -> None:
            super().__init__(_("Remove Display Item"))
            self.__document_controller = document_controller
            workspace_controller = self.__document_controller.workspace_controller
            self.__old_workspace_layout: typing.Optional[Persistence.PersistentDictType] = workspace_controller.deconstruct() if workspace_controller else None
            self.__new_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None
            self.__display_item_index = document_controller.document_model.display_items.index(display_item)
            self.__undelete_logs: typing.List[Changes.UndeleteLog] = list()
            self.initialize()

        def close(self) -> None:
            self.__document_controller = typing.cast(typing.Any, None)
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = typing.cast(typing.Any, None)
            super().close()

        def perform(self) -> None:
            document_model = self.__document_controller.document_model
            display_item = document_model.display_items[self.__display_item_index]
            self.__undelete_logs.append(document_model.remove_display_item_with_log(display_item))

        def _get_modified_state(self) -> typing.Any:
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _undo(self) -> None:
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            self.__new_workspace_layout = workspace_controller.deconstruct()
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            assert self.__old_workspace_layout is not None
            workspace_controller.reconstruct(self.__old_workspace_layout)

        def _redo(self) -> None:
            self.perform()
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            assert self.__new_workspace_layout is not None
            workspace_controller.reconstruct(self.__new_workspace_layout)

    def processing_display_remove(self) -> None:
        display_item = self.selected_display_item
        if display_item:
            command = DocumentController.RemoveDisplayItemCommand(self, display_item)
            command.perform()
            self.push_undo_command(command)

    def processing_computation(self, expression: str, map: typing.Optional[typing.Mapping[str, Symbolic.ComputationItem]] = None) -> DataItem.DataItem:
        if map is None:
            new_map: typing.Dict[str, Symbolic.ComputationItem] = dict()
            for variable_name, display_item in DocumentModel.MappedItemManager().item_map.items():
                # add r_vars that can be evaluated to data_item, for backward compatibility
                if isinstance(display_item, DisplayItem.DisplayItem) and display_item.data_item:
                    new_map[variable_name] = Symbolic.make_item(display_item.data_item)
            map = new_map
        data_item = DataItem.DataItem()
        data_item.title = _("Computation")
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
        new_display_item = self.document_model.get_display_item_for_data_item(data_item)
        assert new_display_item
        self.show_display_item(new_display_item)
        return data_item

    def _get_n_data_sources(self, n: int) -> typing.Tuple[_DataSourceTupleType, ...]:
        """Get n sensible data sources, which may be the same.

        If one display item is selected and the number of crops equals n, return a data
        source for each display item, crop region combo (data source).

        If one display item is selected and the number of crops is not equal to n, return
        a data source, optionally with any single crop region.

         If more than one display item is selected, return up to n or the selected ones if
         with the first one padded out to n if less than n.
        """
        selected_display_items = self.selected_display_items
        if len(selected_display_items) == 1:
            display_item = selected_display_items[0]
            if display_item and len(display_item.graphic_selection.indexes) == n:
                data_item = display_item.data_item if display_item else None
                index1 = display_item.graphic_selection.anchor_index or 0
                graphics: typing.List[Graphics.Graphic] = [display_item.graphics[index1]]
                for index in list(display_item.graphic_selection.indexes.difference({index1})):
                    graphics.append(display_item.graphics[index])
                crop_graphics = [graphic if is_graphic_valid_crop_for_data_item(data_item, graphic) else None for graphic in graphics]
            else:
                crop_graphics = [self._get_crop_graphic(display_item) for _ in range(n)]
            return tuple(zip((display_item, ) * n, crop_graphics))
        if 1 <= len(selected_display_items) <= n:
            selected_display_items = ([selected_display_items[0]] * (n - len(selected_display_items) + 1)) + list(selected_display_items)[1:]
            return tuple(zip(selected_display_items, (self._get_crop_graphic(display_item) for display_item in selected_display_items)))
        return tuple()

    def _get_two_data_sources(self) -> typing.Tuple[_DataSourceTupleType, _DataSourceTupleType]:
        """Get two sensible data sources, which may be the same."""
        return typing.cast(typing.Tuple[_DataSourceTupleType, _DataSourceTupleType], self._get_n_data_sources(2))

    def _perform_processing2(self, display_item1: DisplayItem.DisplayItem, data_item1: DataItem.DataItem, display_item2: DisplayItem.DisplayItem, data_item2: DataItem.DataItem, crop_graphic1: typing.Optional[Graphics.Graphic], crop_graphic2: typing.Optional[Graphics.Graphic], fn: _Processing2Fn) -> typing.Optional[DataItem.DataItem]:
        def process() -> typing.Optional[DataItem.DataItem]:
            new_data_item = fn(display_item1, data_item1, display_item2, data_item2, crop_graphic1, crop_graphic2)
            if new_data_item:
                new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
                assert new_display_item
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

    def _perform_processing3(self, display_item1: DisplayItem.DisplayItem, data_item1: DataItem.DataItem, display_item2: DisplayItem.DisplayItem, data_item2: DataItem.DataItem, display_item3: DisplayItem.DisplayItem, data_item3: DataItem.DataItem, crop_graphic1: typing.Optional[Graphics.Graphic], crop_graphic2: typing.Optional[Graphics.Graphic], crop_graphic3: typing.Optional[Graphics.Graphic], fn: _Processing3Fn) -> typing.Optional[DataItem.DataItem]:
        def process() -> typing.Optional[DataItem.DataItem]:
            new_data_item = fn(display_item1, data_item1, display_item2, data_item2, display_item3, data_item3, crop_graphic1, crop_graphic2, crop_graphic3)
            if new_data_item:
                new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
                assert new_display_item
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

    def _perform_processing(self, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_graphic: typing.Optional[Graphics.Graphic], fn: _ProcessingFn) -> None:
        def process() -> typing.Optional[DataItem.DataItem]:
            new_data_item = fn(display_item, data_item, crop_graphic)
            if new_data_item:
                new_display_item = self.document_model.get_display_item_for_data_item(new_data_item)
                assert new_display_item
                self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        assert isinstance(command, DocumentController.InsertDataItemCommand)
        if command.data_item:
            self.push_undo_command(command)
        else:
            command.close()

    def _perform_processing_select(self, display_item: DisplayItem.DisplayItem, crop_graphic: typing.Optional[Graphics.Graphic], fn: _ProcessingFn) -> None:
        def perform(display_item: DisplayItem.DisplayItem, data_item: typing.Optional[DataItem.DataItem]) -> None:
            if data_item:
                self._perform_processing(display_item, data_item, crop_graphic, fn)

        if display_item.data_item:
            perform(display_item, display_item.data_item)
        else:
            Dialog.pose_select_item_pop_up(display_item.data_items, functools.partial(perform, display_item),
                                           item_getter=operator.attrgetter("title"), window=self)

    def toggle_filter(self) -> None:
        workspace_controller = self.workspace_controller
        assert workspace_controller
        if workspace_controller.filter_row.visible:
            self.__last_display_filter = self.display_filter
            self.display_filter = ListModel.Filter(True)
        else:
            self.display_filter = self.__last_display_filter
        workspace_controller.filter_row.visible = not workspace_controller.filter_row.visible

    def copy_uuid(self) -> None:
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
            assert new_display_item
            self.show_display_item(new_display_item)
            return new_data_item
        command = self.create_insert_data_item_command(process)
        command.perform()
        self.push_undo_command(command)

    def create_empty_data_item(self) -> None:
        self._perform_create_empty_data_item()

    class InsertDataItemsCommand(Undo.UndoableCommand):

        def __init__(self, document_controller: DocumentController, data_items: typing.Sequence[DataItem.DataItem],
                     index: int, display_panel: typing.Optional[DisplayPanel.DisplayPanel] = None, *,
                     project: typing.Optional[Project.Project] = None) -> None:
            super().__init__(_("Insert Data Items"))
            self.__document_controller = document_controller
            workspace_controller = self.__document_controller.workspace_controller
            self.__old_workspace_layout: typing.Optional[Persistence.PersistentDictType] = workspace_controller.deconstruct() if workspace_controller else None
            self.__new_workspace_layout: typing.Optional[Persistence.PersistentDictType] = None
            self.__data_items = data_items  # only used in perform
            self.__data_item_index = index
            self.__data_item_indexes: typing.List[int] = list()
            self.__display_panel = display_panel  # only used in perform
            self.__project = project
            self.__undelete_logs: typing.List[Changes.UndeleteLog] = list()
            self.initialize()

        def close(self) -> None:
            self.__document_controller = typing.cast(typing.Any, None)
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            self.__data_items = typing.cast(typing.Any, None)
            self.__data_item_index = typing.cast(typing.Any, None)
            for undelete_log in self.__undelete_logs:
                undelete_log.close()
            self.__undelete_logs = typing.cast(typing.Any, None)
            super().close()

        def perform(self) -> None:
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

        def _get_modified_state(self) -> typing.Any:
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state: typing.Any) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _redo(self) -> None:
            for undelete_log in reversed(self.__undelete_logs):
                self.__document_controller.document_model.undelete_all(undelete_log)
                undelete_log.close()
            self.__undelete_logs.clear()
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            assert self.__new_workspace_layout is not None
            workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self) -> None:
            workspace_controller = self.__document_controller.workspace_controller
            assert workspace_controller
            self.__new_workspace_layout = workspace_controller.deconstruct()
            document_model = self.__document_controller.document_model
            data_items = [document_model.data_items[index] for index in self.__data_item_indexes]
            for data_item in data_items:
                if data_item in document_model.data_items:
                    self.__undelete_logs.append(document_model.remove_data_item_with_log(data_item, safe=True))
            assert self.__old_workspace_layout is not None
            workspace_controller.reconstruct(self.__old_workspace_layout)

    def receive_project_files(self, file_paths: typing.Sequence[pathlib.Path], project: Project.Project, index: int = -1, threaded: bool = True) -> None:
        def receive_files_complete(received_data_items: typing.Sequence[DataItem.DataItem]) -> None:
            def select_library_all() -> None:
                self.select_data_items_in_data_panel([received_data_items[0]])

            if len(received_data_items) > 0:
                self.queue_task(select_library_all)

        self.__receive_files(file_paths, index=index, threaded=threaded, completion_fn=receive_files_complete, project=project)

    # receive files into the document model. data_group and index can optionally
    # be specified. if data_group is specified, the item is added to an arbitrary
    # position in the document model (the end) and at the group at the position
    # specified by the index. if the data group is not specified, the item is added
    # at the index within the document model.
    def receive_files(self, files: typing.Sequence[str],
                      data_group: typing.Optional[DataGroup.DataGroup] = None,
                      index: int = -1,
                      threaded: bool = True,
                      completion_fn: typing.Optional[typing.Callable[[typing.Sequence[DataItem.DataItem]], None]] = None,
                      display_panel: typing.Optional[DisplayPanel.DisplayPanel] = None,
                      project: typing.Optional[Project.Project] = None) -> typing.Optional[typing.Sequence[DataItem.DataItem]]:
        file_paths = [pathlib.Path(file_path) for file_path in files]
        return self.__receive_files(file_paths, data_group, index, threaded, completion_fn, display_panel, project=project)

    def __receive_files(self, file_paths: typing.Sequence[pathlib.Path],
                        data_group: typing.Optional[DataGroup.DataGroup] = None,
                        index: int = -1,
                        threaded: bool = True,
                        completion_fn: typing.Optional[typing.Callable[[typing.Sequence[DataItem.DataItem]], None]] = None,
                        display_panel: typing.Optional[DisplayPanel.DisplayPanel] = None, *,
                        project: typing.Optional[Project.Project] = None) -> typing.Optional[typing.Sequence[DataItem.DataItem]]:
        assert index is not None

        # this function will be called on a thread to receive files in the background.
        def receive_files_on_thread(file_paths: typing.Sequence[pathlib.Path],
                                    data_group: typing.Optional[DataGroup.DataGroup], index: int,
                                    completion_fn: typing.Optional[typing.Callable[[typing.Sequence[DataItem.DataItem]], None]]) -> typing.Sequence[DataItem.DataItem]:

            received_data_items: typing.List[DataItem.DataItem] = list()

            with self.create_task_context_manager(_("Import Data Items"), "table", logging=threaded) as task:
                task.update_progress(_("Starting import."), (0, len(file_paths)))
                task_data: typing.Dict[str, typing.Any] = {"headers": ["Number", "File"]}

                for file_index, file_path in enumerate(file_paths):
                    data: typing.List[typing.List[str]] = task_data.setdefault("data", list())
                    file_name = file_path.name
                    task_data_entry = [str(file_index + 1), file_name]
                    data.append(task_data_entry)
                    task.update_progress(_("Importing item {}.").format(file_index + 1), (file_index + 1, len(file_paths)), task_data)
                    try:
                        data_items = ImportExportManager.ImportExportManager().read_data_items(file_path)
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

        def receive_files_complete(index: int, data_items: typing.Sequence[DataItem.DataItem]) -> None:
            command: Undo.UndoableCommand

            for data_item in data_items:
                data_item.uuid = uuid.uuid4()

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
            def threaded_receive_files_complete(index: int, data_items: typing.Sequence[DataItem.DataItem]) -> None:
                self.queue_task(functools.partial(receive_files_complete, index, data_items))

            threading.Thread(target=receive_files_on_thread, args=(file_paths, data_group, index, functools.partial(threaded_receive_files_complete, index))).start()
            return None
        else:
            return receive_files_on_thread(file_paths, data_group, index, functools.partial(receive_files_complete, index))

    def create_context_menu_for_display(self, display_items: typing.List[DisplayItem.DisplayItem]) -> UserInterface.Menu:
        # only used in tests
        menu = self.create_context_menu()
        action_context = self._get_action_context_for_display_items(display_items, None)
        self.populate_context_menu(menu, action_context)
        menu.add_separator()
        self.add_action_to_menu(menu, "item.delete", action_context)
        return menu

    def populate_context_menu(self, menu: UserInterface.Menu, action_context: DocumentController.ActionContext) -> None:
        self.add_action_to_menu_if_enabled(menu, "display.reveal", action_context)
        self.add_action_to_menu_if_enabled(menu, "file.export", action_context)

        data_item = action_context.data_item
        if data_item:
            source_data_items = self.document_model.get_source_data_items(data_item)
            if len(source_data_items) > 0:
                menu.add_separator()
                for source_data_item in source_data_items:
                    def show_source_data_item(data_item: DataItem.DataItem) -> None:
                        self.select_data_item_in_data_panel(data_item)

                    truncated_title = self.ui.truncate_string_to_width(str(), source_data_item.title, 280,
                                                                       UserInterface.TruncateModeType.MIDDLE)
                    menu.add_menu_item("{0} \"{1}\"".format(_("Go to Source "), truncated_title),
                                       functools.partial(show_source_data_item, source_data_item))
            dependent_data_items = self.document_model.get_dependent_data_items(data_item)
            if len(dependent_data_items) > 0:
                menu.add_separator()
                for dependent_data_item in dependent_data_items:
                    def show_dependent_data_item(data_item: DataItem.DataItem) -> None:
                        self.select_data_item_in_data_panel(data_item)

                    truncated_title = self.ui.truncate_string_to_width(str(), dependent_data_item.title, 280,
                                                                       UserInterface.TruncateModeType.MIDDLE)
                    menu.add_menu_item("{0} \"{1}\"".format(_("Go to Dependent "), truncated_title),
                                       functools.partial(show_dependent_data_item, dependent_data_item))

    class ActionContext(Window.ActionContext):
        """Action contact.

        The display_panel field is set if a single display panel has keyboard focus and there are no secondary selected
        display panels. This is used for actions that apply to a single display panel but not multiple.

        The display_panels field is the list of primary and secondary display panels this is used for actions that apply
        to a list of display panels actions can check the length of display_panels for specific cases

        The display_item field is set if a single display item is selected in a display panel, display panel browser,
        display panel browser, or data panel browser.

        The display_items field is set if multiple display items are selected in a in a display panel browser, or if
        multiple display panels are selected with display items, etc.

        The data_item field is set if the display_item field is set and the display_item contains a single data item.

        The data_items field is set with the data items present in the display_items field.
        """
        def __init__(self,
                     application: Application.Application,
                     window: DocumentController,
                     focus_widget: typing.Optional[UserInterface.Widget],
                     display_panel: typing.Optional[DisplayPanel.DisplayPanel],
                     display_panels: typing.List[DisplayPanel.DisplayPanel],
                     selected_display_panel: typing.Optional[DisplayPanel.DisplayPanel],
                     model: DocumentModel.DocumentModel,
                     display_item: typing.Optional[DisplayItem.DisplayItem],
                     display_items: typing.Sequence[DisplayItem.DisplayItem],
                     crop_graphic: typing.Optional[Graphics.Graphic],
                     selected_graphics: typing.Sequence[Graphics.Graphic],
                     data_item: typing.Optional[DataItem.DataItem],
                     data_items: typing.Sequence[DataItem.DataItem]) -> None:
            super().__init__(application, window, focus_widget)
            self.display_panel = display_panel
            self.display_panels = display_panels
            self.selected_display_panel = selected_display_panel
            self.model = model
            self.display_item = display_item
            self.display_items = display_items
            self.crop_graphic = crop_graphic
            self.selected_graphics = list(selected_graphics)
            self.data_item = data_item
            self.data_items = data_items

    def _get_action_context(self) -> ActionContext:
        focus_widget = self.focus_widget
        selected_display_panel = self.selected_display_panel
        display_panel = self.selected_display_panel if not self.__secondary_display_panels else None
        display_panels = ([self.__selected_display_panel] if self.__selected_display_panel else list()) + self.__secondary_display_panels
        model = self.document_model
        display_item = self.selected_display_item
        display_items = self.selected_display_items
        crop_graphic = self._get_crop_graphic(display_item)
        data_item = display_item.data_item if display_item else None
        data_items = list()
        for display_item_1 in display_items:
            for data_item_1 in display_item_1.data_items:
                if not data_item_1 in data_items:
                    data_items.append(data_item_1)
        selected_graphics = display_item.selected_graphics if display_item else list()
        return DocumentController.ActionContext(typing.cast("Application.Application", self.app), self, focus_widget,
                                                display_panel, display_panels, selected_display_panel, model,
                                                display_item, display_items, crop_graphic, selected_graphics, data_item,
                                                data_items)

    def _get_action_context_for_display_items(self, display_items: typing.Sequence[DisplayItem.DisplayItem], display_panel: typing.Optional[DisplayPanel.DisplayPanel]) -> ActionContext:
        focus_widget = self.focus_widget
        model = self.document_model
        # the logic here is if a single display panel is focused and the user context clicks on another one, then use
        # the one that was context clicked. if multiple display panels are selected and the user context clicks on one
        # of the selected ones, use the selected ones. if multiple display panels are selected and the user context
        # clicks on an unselected one, then there is no display panel selected.
        selected_display_panel = self.__selected_display_panel
        used_display_panel = None
        used_display_panels: typing.List[DisplayPanel.DisplayPanel] = list()
        if display_panel:
            if self.__secondary_display_panels:
                if display_panel == self.__selected_display_panel or display_panel in self.__secondary_display_panels:
                    used_display_panels = [self.__selected_display_panel] if self.__selected_display_panel else list()
                    used_display_panels.extend(self.__secondary_display_panels)
            else:
                used_display_panel = display_panel
                used_display_panels.append(display_panel)
        # the logic here is if no display panel is passed in or if a single display panel is selected, use the display
        # items that are passed in. otherwise, use the aggregate display items from the selected display panels.
        used_display_item = None
        used_display_items: typing.List[DisplayItem.DisplayItem] = list()
        if not display_panel or used_display_panel:
            used_display_items = list(display_items)
            used_display_item = used_display_items[0] if len(used_display_items) == 1 else None
        else:
            for display_panel_1 in used_display_panels:
                display_item_1 = display_panel_1.display_item
                if display_item_1 and display_item_1 not in used_display_items:
                    used_display_items.append(display_item_1)
        crop_graphic = self._get_crop_graphic(used_display_item)
        used_data_item = used_display_item.data_item if used_display_item else None
        used_data_items = list()
        for display_item_1 in used_display_items:
            for data_item_1 in display_item_1.data_items:
                if not data_item_1 in used_data_items:
                    used_data_items.append(data_item_1)
        selected_graphics = used_display_item.selected_graphics if used_display_item else list()
        selected_display_panel = selected_display_panel or (display_panel if len(used_display_panels) == 1 else None)
        return DocumentController.ActionContext(typing.cast("Application.Application", self.app), self, focus_widget,
                                                used_display_panel, used_display_panels, selected_display_panel, model,
                                                used_display_item, used_display_items, crop_graphic, selected_graphics,
                                                used_data_item, used_data_items)


class GraphicFactoryBase:
    def create_graphic_in_display_item(self, window: DocumentController, display_item: DisplayItem.DisplayItem, graphic_properties: typing.Mapping[str, typing.Any]) -> Graphics.Graphic:
        graphic = self.create_graphic(graphic_properties)
        display_item.graphic_selection.clear()
        display_item.add_graphic(graphic)
        display_item.graphic_selection.set(display_item.graphics.index(graphic))
        return graphic

    def get_graphic_properties_from_position(self, display_item: DisplayItem.DisplayItem, pos: Geometry.FloatPoint) -> typing.Mapping[str, typing.Any]:
        raise NotImplementedError()

    def create_graphic(self, graphic_properties: typing.Mapping[str, typing.Any]) -> Graphics.Graphic:
        raise NotImplementedError()

    def _get_calibrated_origin_image_norm(self, display_item: DisplayItem.DisplayItem) -> Geometry.FloatPoint:
        display_data_channel = display_item.display_data_channel
        assert display_data_channel
        display_values = display_data_channel.get_latest_computed_display_values()
        assert display_values
        element_data_and_metadata = display_values.element_data_and_metadata
        assert element_data_and_metadata
        data_shape = element_data_and_metadata.datum_dimension_shape
        mapping = ImageCanvasItem.ImageCanvasItemMapping.make(data_shape, Geometry.IntRect.unit_rect(), element_data_and_metadata.datum_dimensional_calibrations)
        assert mapping
        calibrated_origin_image_norm = mapping.calibrated_origin_image_norm
        assert calibrated_origin_image_norm
        return calibrated_origin_image_norm


class LineGraphicFactory(GraphicFactoryBase):
    def get_graphic_properties_from_position(self, display_item: DisplayItem.DisplayItem, pos: Geometry.FloatPoint) -> typing.Mapping[str, typing.Any]:
        return {
            "start": pos.as_tuple(),
            "end": pos.as_tuple()
        }

    def create_graphic(self, graphic_properties: typing.Mapping[str, typing.Any]) -> Graphics.LineGraphic:
        graphic = Graphics.LineGraphic()
        graphic.start = graphic_properties.get("start", (0.2, 0.2))
        graphic.end = graphic_properties.get("end", (0.8, 0.8))
        return graphic


class RectangleGraphicFactory(GraphicFactoryBase):
    def get_graphic_properties_from_position(self, display_item: DisplayItem.DisplayItem, pos: Geometry.FloatPoint) -> typing.Mapping[str, typing.Any]:
        return {
            "bounds": (pos.as_tuple(), (0.0, 0.0)),
        }

    def create_graphic(self, graphic_properties: typing.Mapping[str, typing.Any]) -> Graphics.RectangleGraphic:
        graphic = Graphics.RectangleGraphic()
        graphic.bounds = graphic_properties.get("bounds", ((0.25, 0.25), (0.5, 0.5)))
        return graphic


class EllipseGraphicFactory(GraphicFactoryBase):
    def get_graphic_properties_from_position(self, display_item: DisplayItem.DisplayItem, pos: Geometry.FloatPoint) -> typing.Mapping[str, typing.Any]:
        return {
            "bounds": (pos.as_tuple(), (0.0, 0.0)),
        }

    def create_graphic(self, graphic_properties: typing.Mapping[str, typing.Any]) -> Graphics.EllipseGraphic:
        graphic = Graphics.EllipseGraphic()
        graphic.bounds = graphic_properties.get("bounds", ((0.25, 0.25), (0.5, 0.5)))
        return graphic


class PointGraphicFactory(GraphicFactoryBase):
    def get_graphic_properties_from_position(self, display_item: DisplayItem.DisplayItem, pos: Geometry.FloatPoint) -> typing.Mapping[str, typing.Any]:
        return {
            "position": pos.as_tuple(),
        }

    def create_graphic(self, graphic_properties: typing.Mapping[str, typing.Any]) -> Graphics.PointGraphic:
        graphic = Graphics.PointGraphic()
        graphic.position = graphic_properties.get("position", (0.5, 0.5))
        return graphic


class LineProfileGraphicFactory(GraphicFactoryBase):
    def get_graphic_properties_from_position(self, display_item: DisplayItem.DisplayItem, pos: Geometry.FloatPoint) -> typing.Mapping[str, typing.Any]:
        return {
            "start": pos.as_tuple(),
            "end": pos.as_tuple()
        }

    def create_graphic_in_display_item(self, window: DocumentController, display_item: DisplayItem.DisplayItem, graphic_properties: typing.Mapping[str, typing.Any]) -> Graphics.Graphic:
        graphic = super().create_graphic_in_display_item(window, display_item, graphic_properties)
        data_item = display_item.data_item
        assert data_item
        document_model = window.document_model
        line_profile_data_item = document_model.get_line_profile_new(display_item, data_item, None, graphic)
        assert line_profile_data_item
        line_profile_display_item = document_model.get_display_item_for_data_item(line_profile_data_item)
        assert line_profile_display_item
        window.show_display_item(line_profile_display_item)
        return graphic

    def create_graphic(self, graphic_properties: typing.Mapping[str, typing.Any]) -> Graphics.LineProfileGraphic:
        graphic = Graphics.LineProfileGraphic()
        graphic.start = graphic_properties.get("start", (0.2, 0.2))
        graphic.end = graphic_properties.get("end", (0.8, 0.8))
        graphic.width = graphic_properties.get("width", 1.0)
        return graphic


class SpotGraphicFactory(GraphicFactoryBase):
    def get_graphic_properties_from_position(self, display_item: DisplayItem.DisplayItem, pos: Geometry.FloatPoint) -> typing.Mapping[str, typing.Any]:
        return {
            "bounds": Geometry.FloatRect.from_center_and_size(pos - self._get_calibrated_origin_image_norm(display_item), Geometry.FloatSize()).as_tuple()
        }

    def create_graphic(self, graphic_properties: typing.Mapping[str, typing.Any]) -> Graphics.SpotGraphic:
        graphic = Graphics.SpotGraphic()
        graphic.bounds = graphic_properties.get("bounds", ((0.25, 0.25), (0.25, 0.25)))
        return graphic


class WedgeGraphicFactory(GraphicFactoryBase):
    def get_graphic_properties_from_position(self, display_item: DisplayItem.DisplayItem, pos: Geometry.FloatPoint) -> typing.Mapping[str, typing.Any]:
        angle = math.pi - math.atan2(0.5 - pos.y, 0.5 - pos.x)
        return {
            "end_angle": angle,
            "start_angle": angle + math.pi
        }

    def create_graphic(self, graphic_properties: typing.Mapping[str, typing.Any]) -> Graphics.WedgeGraphic:
        graphic = Graphics.WedgeGraphic()
        graphic.start_angle = graphic_properties.get("start_angle", 0)
        graphic.end_angle = graphic_properties.get("end_angle", (3 / 4) * math.pi)
        return graphic


class RingGraphicFactory(GraphicFactoryBase):
    def get_graphic_properties_from_position(self, display_item: DisplayItem.DisplayItem, pos: Geometry.FloatPoint) -> typing.Mapping[str, typing.Any]:
        radius = math.sqrt((pos.y - 0.5) ** 2 + (pos.x - 0.5) ** 2)
        return {
            "radius_1": radius,
        }


    def create_graphic(self, graphic_properties: typing.Mapping[str, typing.Any]) -> Graphics.RingGraphic:
        graphic = Graphics.RingGraphic()
        graphic.radius_1 = graphic_properties.get("radius_1", 0.15)
        graphic.radius_2 = graphic_properties.get("radius_2", 0.25)
        return graphic


class LatticeGraphicFactory(GraphicFactoryBase):
    def get_graphic_properties_from_position(self, display_item: DisplayItem.DisplayItem, pos: Geometry.FloatPoint) -> typing.Mapping[str, typing.Any]:
        u_pos = pos - self._get_calibrated_origin_image_norm(display_item)
        v_pos = Geometry.FloatPoint(-u_pos.x, -u_pos.y)  # rotated 90
        return {
            "u_pos": u_pos.as_tuple(),
            "v_pos": v_pos.as_tuple(),
            "radius": 0.1
        }

    def create_graphic(self, graphic_properties: typing.Mapping[str, typing.Any]) -> Graphics.LatticeGraphic:
        graphic = Graphics.LatticeGraphic()
        graphic.u_pos = graphic_properties.get("u_pos", (0.0, 0.25))
        graphic.v_pos = graphic_properties.get("v_pos", (-0.25, 0.0))
        return graphic


graphic_factory_table: typing.Mapping[str, GraphicFactoryBase] = {
    "line-graphic": LineGraphicFactory(),
    "rectangle-graphic": RectangleGraphicFactory(),
    "ellipse-graphic": EllipseGraphicFactory(),
    "point-graphic": PointGraphicFactory(),
    "line-profile-graphic": LineProfileGraphicFactory(),
    "spot-graphic": SpotGraphicFactory(),
    "wedge-graphic": WedgeGraphicFactory(),
    "ring-graphic": RingGraphicFactory(),
    "lattice-graphic": LatticeGraphicFactory(),
}


class DeleteItemAction(Window.Action):
    action_id = "item.delete"
    action_name = _("Delete Item")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        if context.display_item:
            window.delete_display_items([context.display_item])
        else:
            window.delete_display_items(context.display_items)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.display_items) > 0

    def get_action_name(self, context: Window.ActionContext) -> str:
        context = typing.cast(DocumentController.ActionContext, context)
        data_item = context.data_item
        display_item = context.display_item
        if data_item and len(context.model.get_display_items_for_data_item(data_item)) == 1:
            displayed_title = display_item.displayed_title if display_item else data_item.title
            return _("Delete Data Item") + f" \"{displayed_title}\""
        elif display_item:
            return _("Delete Display Item") + f" \"{display_item.displayed_title}\""
        elif context.display_items:
            return _("Delete Display Items") + f" ({len(context.display_items)})"
        return self.action_name


class DeleteDataItemAction(Window.Action):
    action_id = "item.delete_data_item"
    action_name = _("Delete Data Item")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        if context.data_item:
            window.delete_data_items([context.data_item])
        else:
            window.delete_data_items(context.data_items)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.data_items) > 0 or context.data_item is not None

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

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        selected_display_item = context.display_item
        selected_display_items = context.display_items
        if len(selected_display_items) > 0:
            window.export_files(selected_display_items)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.display_items) > 0 or context.display_item is not None


class ExportSVGAction(Window.Action):
    action_id = "file.export_svg"
    action_name = _("Export SVG...")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        selected_display_item = window.selected_display_item
        if selected_display_item:
            window.export_svg(selected_display_item)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.display_items) > 0 or context.display_item is not None


class ImportDataAction(Window.Action):
    action_id = "file.import_data"
    action_name = _("Import Data...")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        window.import_file()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class ImportFolderAction(Window.Action):
    action_id = "file.import_folder"
    action_name = _("Import Folder...")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        window._import_folder()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


Window.register_action(DeleteItemAction())
Window.register_action(DeleteDataItemAction())
Window.register_action(ExportAction())
Window.register_action(ExportSVGAction())
Window.register_action(ImportDataAction())
Window.register_action(ImportFolderAction())



class DataItemRecorderAction(Window.Action):
    action_id = "window.data_item_recorder"
    action_name = _("Data Item Recorder...")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        window.new_recorder_dialog()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class EditComputationAction(Window.Action):
    action_id = "window.edit_computation"
    action_name = _("Edit Computation")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        window.new_inspect_computation_dialog()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class EditDataItemScriptAction(Window.Action):
    action_id = "window.edit_data_item_script"
    action_name = _("Edit Data Item Scripts")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        window.new_edit_computation_dialog()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class EditDisplayScriptAction(Window.Action):
    action_id = "window.edit_display_script"
    action_name = _("Edit Display Script")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        window.new_display_editor_dialog()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class GenerateDataAction(Window.Action):
    action_id = "window.generate_data_dialog"
    action_name = _("Generate Data...")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        dialog = GeneratorDialog.GenerateDataDialog(window)
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class ProjectItemsDialogAction(Window.Action):
    action_id = "window.project_items_dialog"
    action_name = _("Project Items...")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()

    def invoke(self, context_: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context_)
        window = typing.cast(DocumentController, context.window)
        ProjectItemsDialog.make_project_items_dialog(window)
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class OpenConsoleAction(Window.Action):
    action_id = "window.open_console"
    action_name = _("Python Console...")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        window.new_console_dialog()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class OpenNotificationsAction(Window.Action):
    action_id = "window.open_notifications"
    action_name = _("Notifications...")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        NotificationDialog.open_notification_dialog()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class OpenProjectDialogAction(Window.Action):
    action_id = "window.open_project_dialog"
    action_name = _("Project Manager")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        application = typing.cast(Application.Application, context.application)
        application.open_project_manager()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class OpenRunScriptsAction(Window.Action):
    action_id = "window.open_run_scripts"
    action_name = _("Scripts...")

    # this performs a UI action, but use execute anyway since it has no parameters
    # and is useful to call from a script.
    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        interactive_dialog = ScriptsDialog.RunScriptDialog(window)
        interactive_dialog.show()
        if script_path := context.parameters.get("script_path", str()):
            interactive_dialog.run_script(script_path)
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class OpenTitleEditAction(Window.Action):
    action_id = "window.open_title_edit"
    action_name = _("Edit Title")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        display_item = typing.cast(DisplayItem.DisplayItem, context.display_item)
        if window and display_item:
            from nion.swift import DisplayEditPopup
            size = Geometry.IntSize(width=400, height=40)
            display_panel = context.display_panel
            global_pos: typing.Optional[Geometry.IntPoint] = None
            if display_panel:
                header_canvas_item = display_panel.header_canvas_item
                canvas_bounds = header_canvas_item.canvas_bounds
                assert canvas_bounds
                pos = Geometry.IntPoint(x=canvas_bounds.center.x - size.width // 2, y=canvas_bounds.top)
                global_pos = header_canvas_item.map_to_global(pos)
            DisplayEditPopup.pose_title_edit_popup(window, display_item, global_pos, size)
            return Window.ActionResult(Window.ActionStatus.FINISHED)
        return Window.ActionResult(Window.ActionStatus.PASS)


class ToggleFilterAction(Window.Action):
    action_id = "window.toggle_filter"
    action_name = _("Filter")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        window = typing.cast(DocumentController, context.window)
        window.toggle_filter()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


Window.register_action(DataItemRecorderAction())
Window.register_action(EditComputationAction())
Window.register_action(EditDataItemScriptAction())
Window.register_action(EditDisplayScriptAction())
Window.register_action(GenerateDataAction())
Window.register_action(OpenConsoleAction())
Window.register_action(OpenNotificationsAction())
Window.register_action(OpenProjectDialogAction())
Window.register_action(OpenRunScriptsAction())
Window.register_action(OpenTitleEditAction())
Window.register_action(ProjectItemsDialogAction())
Window.register_action(ToggleFilterAction())


class SetToolModeAction(Window.Action):
    def __init__(self, tool_mode: str, tool_name: str, tool_icon_filename: str, tool_tip: str) -> None:
        super().__init__()
        tool_mode_id = tool_mode.replace("_", "-")
        self.action_id = f"window.set_tool_mode.{tool_mode_id}"
        base_action_name = _("Set Tool Mode")
        self.action_name = f"{base_action_name} ({tool_name})"
        self.tool_mode = tool_mode
        self.tool_icon = pkgutil.get_data(__name__, "resources/" + tool_icon_filename)
        self.tool_tip = tool_tip

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.tool_mode = self.tool_mode
        return Window.ActionResult(Window.ActionStatus.FINISHED)


Window.register_action(SetToolModeAction("pointer", _("Pointer"), "pointer_icon.png", _("Pointer tool for selecting graphics")))
Window.register_action(SetToolModeAction("hand", _("Hand"), "hand_icon.png", _("Hand tool for dragging images within panel")))
Window.register_action(SetToolModeAction("line", _("Line"), "line_icon.png", _("Line tool for making line regions on images")))
Window.register_action(SetToolModeAction("ellipse", _("Ellipse"), "ellipse_icon.png", _("Ellipse tool for making ellipse regions on images")))
Window.register_action(SetToolModeAction("rectangle", _("Rectangle"), "rectangle_icon.png", _("Rectangle tool for making rectangle regions on images")))
Window.register_action(SetToolModeAction("point", _("Point"), "point_icon.png", _("Point tool for making point regions on images")))
Window.register_action(SetToolModeAction("line-profile", _("Line Profile"), "line_profile_icon.png", _("Line profile tool for making line profiles on images")))
Window.register_action(SetToolModeAction("interval", _("Interval"), "interval_icon.png", _("Interval tool for making intervals on line plots")))
Window.register_action(SetToolModeAction("spot", _("Spot"), "spot_icon.png", _("Spot tool for creating spot masks")))
Window.register_action(SetToolModeAction("wedge", _("Wedge"), "wedge_icon.png", _("Wedge tool for creating wedge masks")))
Window.register_action(SetToolModeAction("ring", _("Ring"), "annular_ring.png", _("Ring tool for creating ring masks")))
Window.register_action(SetToolModeAction("lattice", _("Lattice"), "lattice_icon.png", _("Lattice tool for creating periodic lattice masks")))
Window.register_action(SetToolModeAction("zoom-in", _("Zoom In"), "mag_glass_in.png", _("Zoom in on image")))
Window.register_action(SetToolModeAction("zoom-out", _("Zoom Out"), "mag_glass_out.png", _("Zoom out on image")))

class WorkspaceChangeSplits(Window.Action):
    # this is for internal testing only. since it requires passing the splitter and splits,
    # it is a non-standard action.

    action_id = "workspace.set_splits"
    action_name = _("Change Splits")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        if workspace_controller:
            splitter_canvas_item = typing.cast(CanvasItem.SplitterCanvasItem, context.parameters["splitter"])
            splits = context.parameters["splits"]
            command = Workspace.ChangeWorkspaceContentsCommand(workspace_controller, _("Change Splits"))
            splitter_canvas_item.splits = splits
            workspace_controller._sync_layout()
            window.push_undo_command(command)
            return Window.ActionResult(Window.ActionStatus.FINISHED)
        raise ValueError("Missing workspace controller")

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        raise NotImplementedError()


class WorkspaceCloneAction(Window.Action):
    action_id = "workspace.clone"
    action_name = _("Clone Workspace")
    action_parameters = [
        Window.ActionStringProperty("name")
    ]

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        text = self.get_string_property(context, "name")
        if text:
            assert workspace_controller
            command = Workspace.CloneWorkspaceCommand(workspace_controller, text)
            command.perform()
            window.push_undo_command(command)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        if workspace_controller:
            def clone_clicked(text: str) -> None:
                if text:
                    self.set_string_property(context, "name", text)
                    self.execute(context)
            workspace_controller.pose_get_string_message_box(caption=_("Enter name for the workspace"),
                                                             text=workspace_controller._workspace.name,
                                                             accepted_fn=clone_clicked, accepted_text=_("Clone"),
                                                             message_box_id="clone_workspace")
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class WorkspaceNewAction(Window.Action):
    """Create a new workspace in the project."""
    action_id = "workspace.new"
    action_name = _("New Workspace")
    action_parameters = [
        Window.ActionStringProperty("name")
    ]

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        text = self.get_string_property(context, "name")
        if text:
            assert workspace_controller
            command = Workspace.CreateWorkspaceCommand(workspace_controller, text)
            command.perform()
            window.push_undo_command(command)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        if workspace_controller:
            def create_clicked(text: str) -> None:
                if text:
                    self.set_string_property(context, "name", text)
                    self.execute(context)
            workspace_controller.pose_get_string_message_box(caption=_("Enter name for the workspace"),
                                                             text=_("Workspace"),
                                                             accepted_fn=create_clicked, accepted_text=_("Create"),
                                                             message_box_id="create_workspace")
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class WorkspaceNextAction(Window.Action):
    action_id = "workspace.next"
    action_name = _("Next Workspace")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        if workspace_controller:
            workspace_controller.change_to_next_workspace()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class WorkspacePreviousAction(Window.Action):
    action_id = "workspace.previous"
    action_name = _("Previous Workspace")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        if workspace_controller:
            workspace_controller.change_to_previous_workspace()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class WorkspaceRemoveAction(Window.Action):
    action_id = "workspace.remove"
    action_name = _("Remove Workspace")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        assert workspace_controller
        if len(workspace_controller._project.workspaces) > 1:
            command = Workspace.RemoveWorkspaceCommand(workspace_controller)
            command.perform()
            window.push_undo_command(command)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        if workspace_controller:
            def confirm_clicked() -> None:
                self.execute(context)

            caption = _(f"Remove workspace '{workspace_controller._workspace.name}'?")
            workspace_controller.pose_confirmation_message_box(caption, confirm_clicked,
                                                               accepted_text=_("Remove Workspace"),
                                                               message_box_id="remove_workspace")
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class WorkspaceRenameAction(Window.Action):
    action_id = "workspace.rename"
    action_name = _("Rename Workspace")
    action_parameters = [
        Window.ActionStringProperty("name")
    ]

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        text = self.get_string_property(context, "name")
        if text:
            assert workspace_controller
            command = Workspace.RenameWorkspaceCommand(workspace_controller, text)
            command.perform()
            window.push_undo_command(command)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        if workspace_controller:
            def rename_clicked(text: str) -> None:
                if text:
                    self.set_string_property(context, "name", text)
                    self.execute(context)
            workspace_controller.pose_get_string_message_box(caption=_("Enter new name for workspace"),
                                                             text=workspace_controller._workspace.name,
                                                             accepted_fn=rename_clicked, accepted_text=_("Rename"),
                                                             message_box_id="rename_workspace")
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class WorkspaceResetAction(Window.Action):
    action_id = "workspace.1x1"
    action_name = _("Reset Workspace")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/workspace_1x1.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        if workspace_controller:
            workspace_1x1 = workspace_controller.new_workspace(layout={'type': 'image', 'selected': True})
            workspace_controller.change_workspace(workspace_1x1)
            return Window.ActionResult(Window.ActionStatus.FINISHED)
        raise ValueError("Missing workspace controller")


class WorkspaceSplitAction(Window.Action):
    action_id = "workspace.split"
    action_name = _("Split Display Panel")
    action_parameters = [
        Window.ActionIntegerProperty("horizontal_count"),
        Window.ActionIntegerProperty("vertical_count")
    ]

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        display_panels = context.display_panels
        selected_display_panel = context.selected_display_panel
        if workspace_controller and display_panels and selected_display_panel:
            h = self.get_int_property(context, "horizontal_count")
            v = self.get_int_property(context, "vertical_count")
            h = max(1, min(8, h))
            v = max(1, min(8, v))
            display_panels = workspace_controller.apply_layouts(selected_display_panel, display_panels, h, v)
            action_result = Window.ActionResult(Window.ActionStatus.FINISHED)
            action_result.results["display_panels"] = list(display_panels)
            return action_result
        raise ValueError("Missing workspace controller")

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None


class WorkspaceSplitHorizontalAction(WorkspaceSplitAction):
    action_id = "workspace.split_horizontal"
    action_name = _("Split Panel Into Left and Right")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/workspace_split_vertical.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        self.set_int_property(context, "horizontal_count", 2)
        self.set_int_property(context, "vertical_count", 1)
        return super().execute(context)


class WorkspaceSplitVerticalAction(WorkspaceSplitAction):
    action_id = "workspace.split_vertical"
    action_name = _("Split Panel Into Top and Bottom")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/workspace_split_horizontal.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        self.set_int_property(context, "horizontal_count", 1)
        self.set_int_property(context, "vertical_count", 2)
        return super().execute(context)


class WorkspaceSplit2x2Action(WorkspaceSplitAction):
    action_id = "workspace.split_2x2"
    action_name = _("Split Panel 2x2")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/workspace_split_2x2.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        self.set_int_property(context, "horizontal_count", 2)
        self.set_int_property(context, "vertical_count", 2)
        return super().execute(context)


class WorkspaceSplit3x2Action(WorkspaceSplitAction):
    action_id = "workspace.split_3x2"
    action_name = _("Split Panel 3x2")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/workspace_split_3x2.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        self.set_int_property(context, "horizontal_count", 3)
        self.set_int_property(context, "vertical_count", 2)
        return super().execute(context)


class WorkspaceSplit3x3Action(WorkspaceSplitAction):
    action_id = "workspace.split_3x3"
    action_name = _("Split Panel 3x3")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/workspace_split_3x3.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        self.set_int_property(context, "horizontal_count", 3)
        self.set_int_property(context, "vertical_count", 3)
        return super().execute(context)


class WorkspaceSplit4x3Action(WorkspaceSplitAction):
    action_id = "workspace.split_4x3"
    action_name = _("Split Panel 4x3")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/workspace_split_4x3.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        self.set_int_property(context, "horizontal_count", 4)
        self.set_int_property(context, "vertical_count", 3)
        return super().execute(context)


class WorkspaceSplit4x4Action(WorkspaceSplitAction):
    action_id = "workspace.split_4x4"
    action_name = _("Split Panel 4x4")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/workspace_split_4x4.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        self.set_int_property(context, "horizontal_count", 4)
        self.set_int_property(context, "vertical_count", 4)
        return super().execute(context)


class WorkspaceSplit5x4Action(WorkspaceSplitAction):
    action_id = "workspace.split_5x4"
    action_name = _("Split Panel 5x4")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/workspace_split_5x4.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        self.set_int_property(context, "horizontal_count", 5)
        self.set_int_property(context, "vertical_count", 4)
        return super().execute(context)


Window.register_action(WorkspaceChangeSplits())
Window.register_action(WorkspaceCloneAction())
Window.register_action(WorkspaceNewAction())
Window.register_action(WorkspaceNextAction())
Window.register_action(WorkspacePreviousAction())
Window.register_action(WorkspaceRemoveAction())
Window.register_action(WorkspaceRenameAction())
Window.register_action(WorkspaceResetAction())
Window.register_action(WorkspaceSplitHorizontalAction())
Window.register_action(WorkspaceSplitVerticalAction())
Window.register_action(WorkspaceSplitAction())
Window.register_action(WorkspaceSplit2x2Action())
Window.register_action(WorkspaceSplit3x2Action())
Window.register_action(WorkspaceSplit3x3Action())
Window.register_action(WorkspaceSplit4x3Action())
Window.register_action(WorkspaceSplit4x4Action())
Window.register_action(WorkspaceSplit5x4Action())


class AddGroupAction(Window.Action):
    action_id = "project.add_group"
    action_name = _("Add Group")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        if context.window:
            window = typing.cast(DocumentController, context.window)
            window.add_group()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


Window.register_action(AddGroupAction())


class DisplayCopyAction(Window.Action):
    action_id = "display.copy_display"
    action_name = _("Duplicate Display Item")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        display_item = typing.cast(DisplayItem.DisplayItem, context.display_item)
        window.processing_display_copy(display_item)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None


class DisplayPanelCenterGraphicsAction(Window.Action):
    action_id = "display_panel.center_graphics"
    action_name = _("Move Graphic to Center")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        display_item = window.selected_display_item
        if display_item:
            if display_item.graphic_selection.has_selection:
                graphics = [display_item.graphics[index] for index in display_item.graphic_selection.indexes]
                if graphics:
                    def reset_position(graphic: Graphics.Graphic) -> None:
                        graphic.reset_position()

                    command = DisplayPanel.ChangeGraphicsCommand(window.document_model,
                                                                 display_item, graphics,
                                                                 title=DisplayPanelCenterGraphicsAction.action_name,
                                                                 command_id="move_graphic_to_center", is_mergeable=True,
                                                                 modify_fn=reset_position)
                    command.perform()
                    window.push_undo_command(command)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        display_item = window.selected_display_item
        return display_item is not None and display_item.graphic_selection.has_selection


class DisplayPanelClearAction(Window.Action):
    action_id = "display_panel.clear"
    action_name = _("Clear Display Panel Contents")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/workspace_clear.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        assert  workspace_controller
        if context.display_panel:
            workspace_controller.clear_display_panels([context.display_panel])
        else:
            workspace_controller.clear_display_panels(context.display_panels)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.display_items) > 0 or context.display_item is not None


class DisplayPanelCloseAction(Window.Action):
    action_id = "display_panel.close"
    action_name = _("Close Display Panel")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/workspace_close.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        assert workspace_controller
        if context.display_panel:
            workspace_controller.close_display_panels([context.display_panel])
        else:
            workspace_controller.close_display_panels(context.display_panels)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.display_panels) > 0 or context.display_panel is not None


class DisplayPanelCycleAction(Window.Action):
    action_id = "display_panel.cycle_display"
    action_name = _("Cycle Display Browser")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        display_panel = context.display_panel
        if display_panel:
            display_panel.cycle_display()
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.display_panels) > 0 or context.display_panel is not None


class DisplayPanelDeleteGraphicsAction(Window.Action):
    action_id = "display_panel.delete_graphics"
    action_name = _("Delete Selected Graphics")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        display_item = window.selected_display_item
        if display_item:
            if display_item.graphic_selection.has_selection:
                graphics = [display_item.graphics[index] for index in display_item.graphic_selection.indexes]
                if graphics:
                    command = window.create_remove_graphics_command(display_item, graphics)
                    command.perform()
                    window.push_undo_command(command)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        display_item = window.selected_display_item
        return display_item is not None and display_item.graphic_selection.has_selection


class DisplayPanelSelectSiblings(Window.Action):
    action_id = "display_panel.select_siblings"
    action_name = _("Select More Display Panels")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/workspace_select_all.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        assert workspace_controller
        if context.display_panel:
            workspace_controller.select_sibling_display_panels([context.display_panel])
        else:
            workspace_controller.select_sibling_display_panels(context.display_panels)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.display_panels) > 0 or context.display_panel is not None


class DisplayPanelShowItemAction(Window.Action):

    action_id = "display_panel.show_item"
    action_name = _("Display Item")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        display_panel = context.display_panel
        if workspace_controller and display_panel:
            workspace_controller.switch_to_display_content(display_panel, "data-display-panel", display_panel.display_item)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_checked(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None and context.display_panel.display_panel_type in ("data_item", "empty")

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None


class DisplayPanelShowGridBrowserAction(Window.Action):

    action_id = "display_panel.show_grid_browser"
    action_name = _("Grid Browser")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        display_panel = context.display_panel
        if workspace_controller and display_panel:
            workspace_controller.switch_to_display_content(display_panel, "browser-display-panel", display_panel.display_item)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_checked(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None and context.display_panel.display_panel_type == "grid"

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None


class DisplayPanelShowThumbnailBrowserAction(Window.Action):

    action_id = "display_panel.show_thumbnail_browser"
    action_name = _("Thumbnail Browser")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        workspace_controller = window.workspace_controller
        display_panel = context.display_panel
        if workspace_controller and display_panel:
            workspace_controller.switch_to_display_content(display_panel, "thumbnail-browser-display-panel", display_panel.display_item)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_checked(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None and context.display_panel.display_panel_type == "horizontal"

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None


class DisplayRemoveAction(Window.Action):
    action_id = "display.remove_display"
    action_name = _("Delete Display Item")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.processing_display_remove()
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return len(context.display_items) > 0 or context.display_item is not None

    def get_action_name(self, context: Window.ActionContext) -> str:
        context = typing.cast(DocumentController.ActionContext, context)
        display_item = context.display_item
        if display_item:
            return _("Delete Display Item") + f" \"{display_item.displayed_title}\""
        elif context.display_items:
            return _("Delete Display Items") + f" ({len(context.display_items)})"
        return self.action_name


class DisplayRevealAction(Window.Action):
    action_id = "display.reveal"
    action_name = _("Reveal in Data Panel")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        if context.display_panel and context.display_item:
            window.select_display_items_in_data_panel([context.display_item])
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None


class DisplaySnapshotAction(Window.Action):
    action_id = "display.snapshot_display"
    action_name = _("Snapshot Display")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        display_item = typing.cast(DisplayItem.DisplayItem, context.display_item)
        window.processing_display_snapshot(display_item)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None


class DisplayToggleFrameRateAction(Window.Action):
    action_id = "display_panel.toggle_frame_rate"
    action_name = _("Toggle Frame Rate Overlay")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        if context.display_panel:
            context.display_panel.perform_action("toggle_frame_rate")
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None


class DisplayToggleLatencyAction(Window.Action):
    action_id = "display_panel.toggle_latency"
    action_name = _("Toggle Latency Overlay")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        if context.display_panel:
            context.display_panel.perform_action("toggle_latency")
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None


Window.register_action(DisplayCopyAction())
Window.register_action(DisplayPanelCenterGraphicsAction())
Window.register_action(DisplayPanelClearAction())
Window.register_action(DisplayPanelCloseAction())
Window.register_action(DisplayPanelCycleAction())
Window.register_action(DisplayPanelDeleteGraphicsAction())
Window.register_action(DisplayPanelSelectSiblings())
Window.register_action(DisplayPanelShowItemAction())
Window.register_action(DisplayPanelShowGridBrowserAction())
Window.register_action(DisplayPanelShowThumbnailBrowserAction())
Window.register_action(DisplayRemoveAction())
Window.register_action(DisplayRevealAction())
Window.register_action(DisplaySnapshotAction())
Window.register_action(DisplayToggleFrameRateAction())
Window.register_action(DisplayToggleLatencyAction())


class LineProfileGraphicAction(Window.Action):
    def __init__(self, action_id: str, action_name: str, delta: float) -> None:
        super().__init__()
        self.action_id = action_id
        self.action_name = action_name
        self.__delta = delta

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        display_panel = context.display_panel
        display_item = context.display_item
        if display_panel and display_item and len(context.selected_graphics) == 1:
            graphic = context.selected_graphics[0]
            if isinstance(graphic, Graphics.LineProfileGraphic):
                new_width = max(graphic.width + self.__delta, 1.0)
                command = DisplayPanel.ChangeGraphicsCommand(context.model, display_item, [graphic], title=_("Change Line Profile Width"), command_id="change_line_profile_width", is_mergeable=True, width=new_width)
                command.perform()
                window.push_undo_command(command)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        if not context.display_panel:
            return False
        graphic_type_set = {graphic.type for graphic in context.selected_graphics}
        return len(graphic_type_set) == 1 and list(graphic_type_set)[0] == "line-profile"


class RasterDisplayCreateGraphicAction(Window.Action):
    action_id = "raster_display.add_graphic"
    action_name = _("Create Graphic")

    def __init__(self) -> None:
        super().__init__()

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        display_item = context.display_item
        if context.display_panel and display_item:
            graphic_type = context.parameters["graphic_type"]
            graphic_properties = context.parameters.get("graphic_properties", dict[str, typing.Any]())
            graphic = graphic_factory_table[graphic_type].create_graphic_in_display_item(window, display_item, graphic_properties)
            command = context.display_panel.create_insert_graphics_command([graphic])
            command.perform()
            window.push_undo_command(command)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None and context.display_item.used_display_type == "image"


class RasterDisplayFillViewAction(Window.Action):
    action_id = "raster_display.fill_view"
    action_name = _("Fill View")
    action_tool_tip = _("Zoom to fill enclosing space")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/fill_icon.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        if context.display_panel:
            context.display_panel.perform_action("set_fill_mode")
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None and context.display_item.used_display_type == "image"


class RasterDisplayFitToViewAction(Window.Action):
    action_id = "raster_display.fit_view"
    action_name = _("Fit to View")
    action_tool_tip = _("Zoom to fit to enclosing space")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/fit_icon.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        if context.display_panel:
            context.display_panel.perform_action("set_fit_mode")
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None and context.display_item.used_display_type == "image"


class RasterDisplayOneViewAction(Window.Action):
    action_id = "raster_display.1_view"
    action_name = _("1:1 View")
    action_tool_tip = _("Zoom to one image pixel per screen pixel")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/1x1_icon.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        if context.display_panel:
            context.display_panel.perform_action("set_one_to_one_mode")
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None and context.display_item.used_display_type == "image"


class RasterDisplayTwoViewAction(Window.Action):
    action_id = "raster_display.2_view"
    action_name = _("2:1 View")
    action_tool_tip = _("Zoom to two image pixels per screen pixel")
    action_command_icon_png = pkgutil.get_data(__name__, "resources/2x1_icon.png")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        if context.display_panel:
            context.display_panel.perform_action("set_two_to_one_mode")
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None and context.display_item.used_display_type == "image"


class RasterDisplaySetDisplayPropertiesAction(Window.Action):
    action_id = "raster_display.set_display_properties"
    action_name = _("Set Display Properties")

    def __init__(self) -> None:
        super().__init__()

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        if context.display_panel:
            display_properties = context.parameters["display_properties"]
            command = context.display_panel.create_change_display_command()
            context.display_panel.update_display_properties(display_properties)
            command.perform()
            window.push_undo_command(command)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None and context.display_item.used_display_type == "image"


class RasterDisplayZoomOutAction(Window.Action):
    action_id = "raster_display.zoom_out"
    action_name = _("Zoom Out")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        if context.display_panel:
            context.display_panel.perform_action("zoom_out")
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None and context.display_item.used_display_type == "image"


class RasterDisplayZoomInAction(Window.Action):
    action_id = "raster_display.zoom_in"
    action_name = _("Zoom In")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        if context.display_panel:
            context.display_panel.perform_action("zoom_in")
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None and context.display_item.used_display_type == "image"


class RasterDisplayAutoDisplayAction(Window.Action):
    action_id = "raster_display.auto_display"
    action_name = _("Auto Adjust Display")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        display_panel = context.display_panel
        if display_panel:
            display_panel.handle_auto_display()
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None


class RasterDisplayMoveAction(Window.Action):
    def __init__(self, action_id: str, action_name: str, delta: Geometry.FloatSize) -> None:
        super().__init__()
        self.action_id = action_id
        self.action_name = action_name
        self.__delta = delta

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        display_panel = context.display_panel
        if display_panel:
            display_canvas_item = display_panel.display_canvas_item
            if isinstance(display_canvas_item, ImageCanvasItem.ImageCanvasItem):
                display_canvas_item.apply_move_command(self.__delta)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None and isinstance(context.display_panel.display_canvas_item, ImageCanvasItem.ImageCanvasItem)


class RasterDisplayMoveGraphicsAction(Window.Action):
    def __init__(self, action_id: str, action_name: str, delta: Geometry.FloatPoint) -> None:
        super().__init__()
        self.action_id = action_id
        self.action_name = action_name
        self.__delta = delta

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        display_panel = context.display_panel
        if display_panel:
            display_canvas_item = display_panel.display_canvas_item
            if display_canvas_item:
                display_panel.nudge_selected_graphics(display_canvas_item.mouse_mapping, self.__delta.as_size())
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None and context.display_panel.display_canvas_item is not None


class RasterDisplayNudgeSliceAction(Window.Action):
    def __init__(self, action_id: str, action_name: str, delta: int) -> None:
        super().__init__()
        self.action_id = action_id
        self.action_name = action_name
        self.__delta = delta

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        display_panel = context.display_panel
        if display_panel:
            display_panel.nudge_slice(self.__delta)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None and context.display_panel.display_canvas_item is not None


class RasterDisplaySetDisplayLimitsAction(Window.Action):
    action_id = "raster_display.set_display_limits"
    action_name = _("Set Display Limits")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        display_item = context.display_item
        display_data_channel = display_item.display_data_channel if display_item else None
        if display_data_channel:
            display_limits = context.parameters["display_limits"]
            command = DisplayPanel.ChangeDisplayDataChannelCommand(context.model,
                                                                   display_data_channel,
                                                                   display_limits=display_limits,
                                                                   title=_("Change Display Limits"))
            command.perform()
            window.push_undo_command(command)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None and context.display_item.used_display_type == "image"


Window.register_action(LineProfileGraphicAction("line_profile.expand", _("Expand Line Profile Width"), 1.0))
Window.register_action(LineProfileGraphicAction("line_profile.contract", _("Contract Line Profile Width"), -1.0))
Window.register_action(RasterDisplayCreateGraphicAction())
Window.register_action(RasterDisplayFitToViewAction())
Window.register_action(RasterDisplayFillViewAction())
Window.register_action(RasterDisplayOneViewAction())
Window.register_action(RasterDisplayTwoViewAction())
Window.register_action(RasterDisplaySetDisplayPropertiesAction())
Window.register_action(RasterDisplayZoomOutAction())
Window.register_action(RasterDisplayZoomInAction())
Window.register_action(RasterDisplayAutoDisplayAction())
Window.register_action(RasterDisplayMoveGraphicsAction("raster_display.nudge_graphics_left", _("Nudge Graphics Left"), Geometry.FloatPoint(x=-1, y=0)))
Window.register_action(RasterDisplayMoveGraphicsAction("raster_display.nudge_graphics_right", _("Nudge Graphics Right"), Geometry.FloatPoint(x=1, y=0)))
Window.register_action(RasterDisplayMoveGraphicsAction("raster_display.nudge_graphics_up", _("Nudge Graphics Up"), Geometry.FloatPoint(x=0, y=-1)))
Window.register_action(RasterDisplayMoveGraphicsAction("raster_display.nudge_graphics_down", _("Nudge Graphics Down"), Geometry.FloatPoint(x=0, y=1)))
Window.register_action(RasterDisplayMoveGraphicsAction("raster_display.move_graphics_left", _("Move Graphics Left"), Geometry.FloatPoint(x=-10, y=0)))
Window.register_action(RasterDisplayMoveGraphicsAction("raster_display.move_graphics_right", _("Move Graphics Right"), Geometry.FloatPoint(x=10, y=0)))
Window.register_action(RasterDisplayMoveGraphicsAction("raster_display.move_graphics_up", _("Move Graphics Up"), Geometry.FloatPoint(x=0, y=-10)))
Window.register_action(RasterDisplayMoveGraphicsAction("raster_display.move_graphics_down", _("Move Graphics Down"), Geometry.FloatPoint(x=0, y=10)))
Window.register_action(RasterDisplayMoveAction("raster_display.nudge_left", _("Nudge Display Left"), Geometry.FloatSize(width=10, height=0)))
Window.register_action(RasterDisplayMoveAction("raster_display.nudge_right", _("Nudge Display Right"), Geometry.FloatSize(width=-10, height=0)))
Window.register_action(RasterDisplayMoveAction("raster_display.nudge_up", _("Nudge Display Up"), Geometry.FloatSize(width=0, height=10)))
Window.register_action(RasterDisplayMoveAction("raster_display.nudge_down", _("Nudge Display Down"), Geometry.FloatSize(width=0, height=-10)))
Window.register_action(RasterDisplayMoveAction("raster_display.move_left", _("Move Display Left"), Geometry.FloatSize(width=100, height=0)))
Window.register_action(RasterDisplayMoveAction("raster_display.move_right", _("Move Display Right"), Geometry.FloatSize(width=-100, height=0)))
Window.register_action(RasterDisplayMoveAction("raster_display.move_up", _("Move Display Up"), Geometry.FloatSize(width=0, height=100)))
Window.register_action(RasterDisplayMoveAction("raster_display.move_down", _("Move Display Down"), Geometry.FloatSize(width=0, height=-100)))
Window.register_action(RasterDisplayNudgeSliceAction("raster_display.nudge_slice_left", _("Nudge Slice Left"), -1))
Window.register_action(RasterDisplayNudgeSliceAction("raster_display.nudge_slice_right", _("Nudge Slice Right"), 1))
Window.register_action(RasterDisplaySetDisplayLimitsAction())


class LinePlotDisplayAutoDisplayAction(Window.Action):
    action_id = "line_plot_display.auto_display"
    action_name = _("Auto Adjust Display")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        display_panel = context.display_panel
        if display_panel:
            display_panel.handle_auto_display()
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None


class LinePlotDisplayMoveGraphicsAction(Window.Action):
    def __init__(self, action_id: str, action_name: str, delta: Geometry.FloatPoint) -> None:
        super().__init__()
        self.action_id = action_id
        self.action_name = action_name
        self.__delta = delta

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        display_panel = context.display_panel
        if display_panel:
            display_canvas_item = display_panel.display_canvas_item
            if display_canvas_item:
                display_panel.nudge_selected_graphics(display_canvas_item.mouse_mapping, self.__delta.as_size())
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_panel is not None and context.display_panel.display_canvas_item is not None


Window.register_action(LinePlotDisplayAutoDisplayAction())
Window.register_action(LinePlotDisplayMoveGraphicsAction("line_plot_display.nudge_graphics_left", _("Nudge Graphics Left"), Geometry.FloatPoint(x=-1, y=0)))
Window.register_action(LinePlotDisplayMoveGraphicsAction("line_plot_display.nudge_graphics_right", _("Nudge Graphics Right"), Geometry.FloatPoint(x=1, y=0)))
Window.register_action(LinePlotDisplayMoveGraphicsAction("line_plot_display.move_graphics_left", _("Move Graphics Left"), Geometry.FloatPoint(x=-10, y=0)))
Window.register_action(LinePlotDisplayMoveGraphicsAction("line_plot_display.move_graphics_right", _("Move Graphics Right"), Geometry.FloatPoint(x=10, y=0)))


class AssignVariableReference(Window.Action):
    action_id = "item.assign_variable_reference"
    action_name = _("Assign Variable Reference")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        display_item = context.display_item
        if display_item:
            r_var = context.model.assign_variable_to_display_item(display_item)
            logging.debug("{} = Display Item with UUID {}".format(r_var, display_item.uuid))
            for console in window.consoles:
                console.assign_item_var(r_var, display_item)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.display_item is not None


class CopyItemUUIDAction(Window.Action):
    action_id = "item.copy_uuid"
    action_name = _("Copy Item UUID")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.copy_uuid()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class CreateDataItemAction(Window.Action):
    action_id = "item.create_data_item"
    action_name = _("Create New Data Item")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.create_empty_data_item()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class DuplicateAction(Window.Action):
    action_id = "item.duplicate"
    action_name = _("Duplicate")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.processing_duplicate()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class SnapshotAction(Window.Action):
    action_id = "item.snapshot"
    action_name = _("Snapshot")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.processing_snapshot()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


Window.register_action(AssignVariableReference())
Window.register_action(CopyItemUUIDAction())
Window.register_action(CreateDataItemAction())
Window.register_action(DuplicateAction())
Window.register_action(SnapshotAction())


class AddLineGraphicAction(Window.Action):
    action_id = "graphics.add_line_graphic"
    action_name = _("Add Line Graphic")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.add_line_graphic()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class AddEllipseGraphicAction(Window.Action):
    action_id = "graphics.add_ellipse_graphic"
    action_name = _("Add Ellipse Graphic")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.add_ellipse_graphic()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class AddRectangleGraphicAction(Window.Action):
    action_id = "graphics.add_rectangle_graphic"
    action_name = _("Add Rectangle Graphic")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.add_rectangle_graphic()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class AddPointGraphicAction(Window.Action):
    action_id = "graphics.add_point_graphic"
    action_name = _("Add Point Graphic")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.add_point_graphic()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class AddIntervalGraphicAction(Window.Action):
    action_id = "graphics.add_interval_graphic"
    action_name = _("Add Interval Graphic")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.add_interval_graphic()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class AddChannelGraphicAction(Window.Action):
    action_id = "graphics.add_channel_graphic"
    action_name = _("Add Channel Graphic")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.add_channel_graphic()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class AddGraphicToMaskAction(Window.Action):
    action_id = "graphics.add_graphic_mask"
    action_name = _("Add to Mask")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.add_graphic_mask()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class AddSpotGraphicAction(Window.Action):
    action_id = "graphics.add_spot_graphic"
    action_name = _("Add Spot Filter")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.add_spot_graphic()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class AddAngleGraphicAction(Window.Action):
    action_id = "graphics.add_angle_graphic"
    action_name = _("Add Angle Filter")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.add_angle_graphic()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class AddBandPassGraphicAction(Window.Action):
    action_id = "graphics.add_band_pass_graphic"
    action_name = _("Add Band Pass Filter")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.add_band_pass_graphic()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class AddLatticeGraphicAction(Window.Action):
    action_id = "graphics.add_lattice_graphic"
    action_name = _("Add Lattice Filter")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.add_lattice_graphic()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class RemoveGraphicFromMaskAction(Window.Action):
    action_id = "graphics.remove_graphic_mask"
    action_name = _("Remove from Mask")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        window.remove_graphic_mask()
        return Window.ActionResult(Window.ActionStatus.FINISHED)


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

    def execute_processing(self, context: Window.ActionContext, fn: _ProcessingFn) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        if context.display_item and context.data_item:
            typing.cast(DocumentController, context.window)._perform_processing(context.display_item,
                                                                                context.data_item,
                                                                                context.crop_graphic, fn)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def invoke_processing(self, context: Window.ActionContext, fn: _ProcessingFn) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        if context.display_item:
            typing.cast(DocumentController, context.window)._perform_processing_select(context.display_item,
                                                                                       context.crop_graphic, fn)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def execute_processing2(self, context: Window.ActionContext, fn: _Processing2Fn) -> Window.ActionResult:
        return self.invoke_processing2(context, fn)

    def invoke_processing2(self, context: Window.ActionContext, fn: _Processing2Fn) -> Window.ActionResult:
        data_sources = typing.cast(DocumentController, context.window)._get_two_data_sources()
        if data_sources:
            (display_item1, crop_graphic1), (display_item2, crop_graphic2) = data_sources
            data_item1 = display_item1.data_item
            data_item2 = display_item2.data_item
            if data_item1 and data_item2:
                typing.cast(DocumentController, context.window)._perform_processing2(display_item1, data_item1,
                                                                                     display_item2, data_item2,
                                                                                     crop_graphic1, crop_graphic2, fn)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def execute_processing3(self, context: Window.ActionContext, fn: _Processing3Fn) -> Window.ActionResult:
        return self.invoke_processing3(context, fn)

    def invoke_processing3(self, context: Window.ActionContext, fn: _Processing3Fn) -> Window.ActionResult:
        data_sources = typing.cast(DocumentController, context.window)._get_n_data_sources(3)
        if data_sources:
            (display_item1, crop_graphic1), (display_item2, crop_graphic2), (display_item3, crop_graphic3) = data_sources
            data_item1 = display_item1.data_item
            data_item2 = display_item2.data_item
            data_item3 = display_item3.data_item
            if data_item1 and data_item2 and data_item3:
                typing.cast(DocumentController, context.window)._perform_processing3(display_item1, data_item1,
                                                                                     display_item2, data_item2,
                                                                                     display_item3, data_item3,
                                                                                     crop_graphic1, crop_graphic2,
                                                                                     crop_graphic3, fn)
        return Window.ActionResult(Window.ActionStatus.FINISHED)


class AddAction(ProcessingAction):
    action_id = "processing.add"
    action_name = _("Add")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing2(context, context.model.get_add_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing2(context, context.model.get_add_new)


class AutoCorrelateAction(ProcessingAction):
    action_id = "processing.auto_correlate"
    action_name = _("Auto Correlate")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_auto_correlate_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_auto_correlate_new)


class CropAction(ProcessingAction):
    action_id = "processing.crop"
    action_name = _("Crop")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_crop_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_crop_new)


class CrossCorrelateAction(ProcessingAction):
    action_id = "processing.cross_correlate"
    action_name = _("Cross Correlate")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing2(context, context.model.get_cross_correlate_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing2(context, context.model.get_cross_correlate_new)


class DivideAction(ProcessingAction):
    action_id = "processing.divide"
    action_name = _("Divide")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing2(context, context.model.get_divide_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing2(context, context.model.get_divide_new)


class ExtractAlphaAction(ProcessingAction):
    action_id = "processing.rgb_alpha"
    action_name = _("Extract Alpha Channel")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_rgb_alpha_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_rgb_alpha_new)


class ExtractBlueAction(ProcessingAction):
    action_id = "processing.rgb_blue"
    action_name = _("Extract Blue Channel")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_rgb_blue_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_rgb_blue_new)


class ExtractGreenAction(ProcessingAction):
    action_id = "processing.rgb_green"
    action_name = _("Extract Green Channel")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_rgb_green_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_rgb_green_new)


class ExtractLuminanceAction(ProcessingAction):
    action_id = "processing.rgb_luminance"
    action_name = _("Extract Luminance")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_rgb_luminance_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_rgb_luminance_new)


class ExtractRedAction(ProcessingAction):
    action_id = "processing.rgb_red"
    action_name = _("Extract Red Channel")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_rgb_red_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_rgb_red_new)


class FourierFilterAction(ProcessingAction):
    action_id = "processing.fourier_filter"
    action_name = _("Fourier Filter")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        if context.display_item and context.data_item:
            window._perform_processing(context.display_item, context.data_item, None, context.model.get_fourier_filter_new)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        if context.display_item:
            window._perform_processing_select(context.display_item, None, context.model.get_fourier_filter_new)
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.data_item is not None


class FFTAction(ProcessingAction):
    action_id = "processing.fft"
    action_name = _("FFT")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_fft_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_fft_new)


class GaussianFilterAction(ProcessingAction):
    action_id = "processing.gaussian_filter"
    action_name = _("Gaussian Filter")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_gaussian_blur_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_gaussian_blur_new)


class HistogramAction(ProcessingAction):
    action_id = "processing.histogram"
    action_name = _("Histogram")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_histogram_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_histogram_new)


class InverseFFTAction(ProcessingAction):
    action_id = "processing.inverse_fft"
    action_name = _("Inverse FFT")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_ifft_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_ifft_new)


class LaplaceFilterAction(ProcessingAction):
    action_id = "processing.laplace_filter"
    action_name = _("Laplace Filter")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_laplace_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_laplace_new)


class LineProfileAction(ProcessingAction):
    action_id = "processing.line_profile"
    action_name = _("Line Profile")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_line_profile_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_line_profile_new)


class MaskAction(ProcessingAction):
    action_id = "processing.mask"
    action_name = _("Mask")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_mask_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_mask_new)


class MaskedAction(ProcessingAction):
    action_id = "processing.masked"
    action_name = _("Masked")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_masked_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_masked_new)


class MedianFilterAction(ProcessingAction):
    action_id = "processing.median_filter"
    action_name = _("Median Filter")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_median_filter_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_median_filter_new)


class MultiplyAction(ProcessingAction):
    action_id = "processing.multiply"
    action_name = _("Multiply")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing2(context, context.model.get_multiply_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing2(context, context.model.get_multiply_new)


class NegateAction(ProcessingAction):
    action_id = "processing.negate"
    action_name = _("Negate")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_invert_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_invert_new)


class PickAction(ProcessingAction):
    action_id = "processing.pick"
    action_name = _("Pick")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_pick_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_pick_new)


class PickAverageAction(ProcessingAction):
    action_id = "processing.pick_average"
    action_name = _("Pick (Average)")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_pick_region_average_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_pick_region_average_new)


class PickSumAction(ProcessingAction):
    action_id = "processing.pick_sum"
    action_name = _("Pick (Sum)")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_pick_region_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_pick_region_new)


class PowerSpectrumAction(ProcessingAction):
    action_id = "processing.power_spectrum"
    action_name = _("Radial Power Spectrum")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_power_spectrum_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_power_spectrum_new)


class ProjectionSumAction(ProcessingAction):
    action_id = "processing.projection_sum"
    action_name = _("Projection (Sum)")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_projection_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_projection_new)


class RadialProfileAction(ProcessingAction):
    action_id = "processing.radial_profile"
    action_name = _("Radial Profile")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_radial_profile_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_radial_profile_new)


class RebinAction(ProcessingAction):
    action_id = "processing.rebin"
    action_name = _("Rebin")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_rebin_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_rebin_new)


class ResampleAction(ProcessingAction):
    action_id = "processing.resample"
    action_name = _("Resample")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_resample_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_resample_new)


class ResizeAction(ProcessingAction):
    action_id = "processing.resize"
    action_name = _("Resize")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_resize_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_resize_new)


class RGBAction(ProcessingAction):
    action_id = "processing.make_rgb"
    action_name = _("Make RGB")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing3(context, context.model.get_rgb_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing3(context, context.model.get_rgb_new)


class ScalarAction(ProcessingAction):
    action_id = "processing.scalar"
    action_name = _("Convert to Scalar")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_convert_to_scalar_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_convert_to_scalar_new)


class SequenceAlignFourierAction(ProcessingAction):
    action_id = "processing.sequence_align_fourier"
    action_name = _("Align Sequence/Collection (Fourier)")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_sequence_fourier_align_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_sequence_fourier_align_new)


class SequenceAlignSplineAction(ProcessingAction):
    action_id = "processing.sequence_align_spline_1"
    action_name = _("Align Sequence/Collection (Spline 1st Order)")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_sequence_align_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_sequence_align_new)


class SequenceExtractAction(ProcessingAction):
    action_id = "processing.sequence_extract"
    action_name = _("Extract")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_sequence_extract_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_sequence_extract_new)


class SequenceIntegrateAction(ProcessingAction):
    action_id = "processing.sequence_integrate"
    action_name = _("Integrate")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_sequence_integrate_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_sequence_integrate_new)


class SequenceMeasureShiftsAction(ProcessingAction):
    action_id = "processing.sequence_measure_shifts"
    action_name = _("Measure Shifts")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_sequence_measure_shifts_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_sequence_measure_shifts_new)


class SequenceTrimAction(ProcessingAction):
    action_id = "processing.sequence_trim"
    action_name = _("Trim")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_sequence_trim_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_sequence_trim_new)


class SliceSumAction(ProcessingAction):
    action_id = "processing.slice_sum"
    action_name = _("Slice Sum")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_slice_sum_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_slice_sum_new)


class SobelFilterAction(ProcessingAction):
    action_id = "processing.sobel_filter"
    action_name = _("Sobel Filter")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_sobel_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_sobel_new)


class SubtractAction(ProcessingAction):
    action_id = "processing.subtract"
    action_name = _("Subtract")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing2(context, context.model.get_subtract_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing2(context, context.model.get_subtract_new)


class SubtractAverageAction(ProcessingAction):
    action_id = "processing.subtract_average"
    action_name = _("Subtract Region Average")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_subtract_region_average_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_subtract_region_average_new)


@dataclasses.dataclass
class TransformConfig:
    flip_h: bool = False
    flip_v: bool = False
    transpose: bool = False


class TransformAction(ProcessingAction):
    action_id = "processing.transform"
    action_name = _("Transpose and Flip")

    # define a general processing function which sets variables for transpose and flip
    def __processing_fn(self, context: DocumentController.ActionContext, transform_config: TransformConfig, display_item: DisplayItem.DisplayItem, data_item: DataItem.DataItem, crop_region: typing.Optional[Graphics.Graphic]=None) -> typing.Optional[DataItem.DataItem]:
        new_data_item = context.model.get_transpose_flip_new(display_item, data_item, crop_region)
        if new_data_item:
            computation = context.model.get_data_item_computation(new_data_item)
            assert computation
            computation.set_input_value("do_flip_h", transform_config.flip_h)
            computation.set_input_value("do_flip_v", transform_config.flip_v)
            computation.set_input_value("do_transpose", transform_config.transpose)
        return new_data_item

    def _get_default_transform_config(self) -> TransformConfig:
        return TransformConfig()

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, functools.partial(self.__processing_fn, context, self._get_default_transform_config()))

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, functools.partial(self.__processing_fn, context, self._get_default_transform_config()))


class FlipHorizontalAction(TransformAction):
    action_id = "processing.flip_horizontal"
    action_name = _("Flip Horizontal")

    def _get_default_transform_config(self) -> TransformConfig:
        return TransformConfig(flip_h=True)


class FlipVerticalAction(TransformAction):
    action_id = "processing.flip_vertical"
    action_name = _("Flip Vertical")

    def _get_default_transform_config(self) -> TransformConfig:
        return TransformConfig(flip_v=True)


class RotateLeftAction(TransformAction):
    action_id = "processing.rotate_left"
    action_name = _("Rotate Left")

    def _get_default_transform_config(self) -> TransformConfig:
        return TransformConfig(flip_v=True, transpose=True)


class RotateRightAction(TransformAction):
    action_id = "processing.rotate_right"
    action_name = _("Rotate Right")

    def _get_default_transform_config(self) -> TransformConfig:
        return TransformConfig(flip_h=True, transpose=True)


class UniformFilterAction(ProcessingAction):
    action_id = "processing.uniform_filter"
    action_name = _("Uniform Filter")

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.execute_processing(context, context.model.get_uniform_filter_new)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        return self.invoke_processing(context, context.model.get_uniform_filter_new)


class ProcessingComponentAction(ProcessingAction):
    def __init__(self, processing_id: str, title: str) -> None:
        super().__init__()
        self.action_id = "processing." + processing_id
        self.action_name = title
        self.__processing_id = processing_id

    def execute(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        if context.display_item and context.data_item:
            window._perform_processing(context.display_item, context.data_item, None, functools.partial(context.model.get_processing_new, self.__processing_id))
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def invoke(self, context: Window.ActionContext) -> Window.ActionResult:
        context = typing.cast(DocumentController.ActionContext, context)
        window = typing.cast(DocumentController, context.window)
        if context.display_item:
            window._perform_processing_select(context.display_item, None, functools.partial(context.model.get_processing_new, self.__processing_id))
        return Window.ActionResult(Window.ActionStatus.FINISHED)

    def is_enabled(self, context: Window.ActionContext) -> bool:
        context = typing.cast(DocumentController.ActionContext, context)
        return context.data_item is not None


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
Window.register_action(FlipHorizontalAction())
Window.register_action(FlipVerticalAction())
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
Window.register_action(PowerSpectrumAction())
Window.register_action(ProjectionSumAction())
Window.register_action(RadialProfileAction())
Window.register_action(RebinAction())
Window.register_action(ResampleAction())
Window.register_action(ResizeAction())
Window.register_action(RGBAction())
Window.register_action(RotateLeftAction())
Window.register_action(RotateRightAction())
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


def component_changed(component: typing.Any, component_types: typing.Set[str]) -> None:
    # when a processing component is registered, create a ProcessingComponentAction for the
    # processing component.
    if "processing-component" in component_types:
        processing_component = typing.cast(Processing.ProcessingBase, component)
        Window.register_action(ProcessingComponentAction(processing_component.processing_id, processing_component.title))


component_registered_event_listener = Registry.listen_component_registered_event(component_changed)
Registry.fire_existing_component_registered_events("processing-component")

try:
    data = pkgutil.get_data(__name__, "resources/key_config.json")
    assert data is not None
    action_shortcuts_dict = json.loads(data.decode("utf8"))
    Window.register_action_shortcuts(action_shortcuts_dict)
except Exception as e:
    logging.error("Could not read key configuration.")
