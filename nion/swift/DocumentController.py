# standard libraries
import collections
import copy
import functools
import gettext
import logging
import os.path
import random
import threading
import time
import traceback
import uuid
import weakref

# typing
from typing import List

# third party libraries
# None

# local libraries
from nion.swift import DataPanel
from nion.swift import Decorators
from nion.swift import DisplayPanel
from nion.swift import ExportDialog
from nion.swift import FilterPanel
from nion.swift import ScriptsDialog
from nion.swift import Task
from nion.swift import Workspace
from nion.swift.model import Connection
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DataItemsBinding
from nion.swift.model import ImportExportManager
from nion.swift.model import Operation
from nion.swift.model import Region
from nion.swift.model import Symbolic
from nion.ui import Dialog
from nion.ui import Event
from nion.ui import Observable
from nion.ui import Process
from nion.ui import Selection

_ = gettext.gettext


class DocumentController(Observable.Broadcaster):

    """
    Manage a document window.

    Operations

    Operations can be applied to the selected data item (as selected in a pane or an item in the data panel.

    If an operation can operate on a region and a suitable region is selected, the operation will operate on
    the region.

    If an operation must operate on a region and a suitable region is not selected, a default region will be
    created and the operation will operate on that region.

    If an operation can operate on multiple data items and multiple data items are selected in the data panel,
    the operation will operate on all of them. The data panel will keep track of the primary data item and
    the others will be unordered past that. The same region rules apply.
    """

    # document_window is passed from the application container.
    # the next method to be called will be initialize.
    def __init__(self, ui, document_model, workspace_id=None, app=None):
        super(DocumentController, self).__init__()

        self.__closed = False  # debugging

        self.ui = ui
        self.uuid = uuid.uuid4()

        self.task_created_event = Event.Event()
        self.selected_data_item_changed_event = Event.Event()
        self.cursor_changed_event = Event.Event()
        self.did_close_event = Event.Event()
        self.create_new_document_controller_event = Event.Event()
        self.tool_mode_changed_event = Event.Event()

        # document_model may be shared between several DocumentControllers, so use reference counting
        # to determine when to close it.
        self.document_model = document_model
        self.document_model.add_ref()
        self.document_window = self.ui.create_document_window(_("Nion Swift"))
        self.document_window.on_periodic = self.periodic
        self.document_window.on_queue_task = self.queue_task
        self.document_window.on_add_task = self.add_task
        self.document_window.on_clear_task = self.clear_task
        self.document_window.on_about_to_show = self.about_to_show
        self.document_window.on_about_to_close = self.about_to_close
        if app:
            self.document_window.title = "{0} Workspace - {1}".format(_("Nion Swift"), os.path.splitext(os.path.split(app.workspace_dir)[1])[0])
        self.__workspace_controller = None
        self.app = app
        self.__data_item_vars = dict()  # dictionary mapping weak data items to script window variables
        self.replaced_display_panel_content = None  # used to facilitate display panel functionality to exchange displays
        self.__weak_selected_display_panel = None
        self.__tool_mode = "pointer"
        self.__periodic_queue = Process.TaskQueue()
        self.__periodic_set = Process.TaskSet()
        self.__weak_periodic_listeners = []
        self.__weak_periodic_listeners_mutex = threading.RLock()

        selection = Selection.IndexedSelection()

        # the user has two ways of filtering data items: first by selecting a data group (or none) in the data panel,
        # and next by applying a custom filter to the items from the items resulting in the first selection.
        # data items binding tracks the main list of items selected in the data panel.
        # filtered data items binding tracks the filtered items from those in data items binding.
        self.__data_items_binding = DataItemsBinding.DataItemsInContainerBinding()
        self.__filtered_data_items_binding = DataItemsBinding.DataItemsFilterBinding(self.__data_items_binding, selection)
        self.__last_display_filter = None

        def data_item_will_be_removed(data_item):
            if data_item in self.__filtered_data_items_binding.data_items:
                index = self.__filtered_data_items_binding.data_items.index(data_item)
                if selection.contains(index):
                    selection.remove(index)

        self.__data_item_will_be_removed_event_listener = self.document_model.data_item_will_be_removed_event.listen(data_item_will_be_removed)

        def queued_append_data_item(data_item, is_recording):
            self.queue_task(functools.partial(self.workspace.append_data_item, data_item, is_recording))
            return True

        self.__append_data_item_event_listener = self.document_model.append_data_item_event.listen(queued_append_data_item)

        self.filter_controller = FilterPanel.FilterController(self)

        self.__data_browser_controller = DataPanel.DataBrowserController(self, selection)

        self.console = None
        self.create_menus()
        if workspace_id:  # used only when testing reference counting
            self.__workspace_controller = Workspace.Workspace(self, workspace_id)
            self.__workspace_controller.restore(self.document_model.workspace_uuid)

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
        # recognize when we're running as test and finish out periodic operations
        if not self.document_window.has_event_loop:
            self.periodic()
        # menus
        self.display_type_menu.on_about_to_show = None
        self.view_menu.on_about_to_show = None
        self.window_menu.on_about_to_show = None
        self.file_menu = None
        self.edit_menu = None
        self.processing_menu = None
        self.view_menu = None
        self.window_menu = None
        self.help_menu = None
        self.library_menu = None
        if self.__workspace_controller:
            self.__workspace_controller.close()
            self.__workspace_controller = None
        # get rid of the bindings
        self.__data_item_will_be_removed_event_listener.close()
        self.__data_item_will_be_removed_event_listener = None
        self.__append_data_item_event_listener.close()
        self.__append_data_item_event_listener = None
        self.__filtered_data_items_binding.close()
        self.__filtered_data_items_binding = None
        self.filter_controller.close()
        self.filter_controller = None
        self.__data_items_binding.close()
        self.__data_items_binding = None
        self.__data_browser_controller.close()
        self.__data_browser_controller = None
        # document_model may be shared between several DocumentControllers, so use reference counting
        # to determine when to close it.
        self.document_model.remove_ref()
        self.document_model = None
        self.did_close_event.fire(self)
        self.did_close_event = None
        self.ui.destroy_document_window(self)
        self.__periodic_queue = None
        self.__periodic_set = None

    def about_to_show(self):
        geometry, state = self.workspace_controller.restore_geometry_state()
        self.document_window.restore(geometry, state)

    def about_to_close(self, geometry, state):
        if self.workspace_controller:
            self.workspace_controller.save_geometry_state(geometry, state)
        self.close()

    def register_console(self, console):
        self.console = console

    def unregister_console(self, console):
        self.console = None

    def create_menus(self):

        self.file_menu = self.document_window.add_menu(_("File"))

        self.edit_menu = self.document_window.add_menu(_("Edit"))

        self.processing_menu = self.document_window.add_menu(_("Processing"))

        self.view_menu = self.document_window.add_menu(_("View"))

        self.window_menu = self.document_window.add_menu(_("Window"))

        self.help_menu = self.document_window.add_menu(_("Help"))

        self.library_menu = self.ui.create_sub_menu(self.document_window)

        if self.app:
            recent_workspace_file_paths = self.app.get_recent_workspace_file_paths()
            for file_path in recent_workspace_file_paths[0:10]:
                root_path, file_name = os.path.split(file_path)
                name, ext = os.path.splitext(file_name)
                self.library_menu.add_menu_item(name, lambda file_path=file_path: self.app.switch_library(file_path))
            if len(recent_workspace_file_paths) > 0:
                self.library_menu.add_separator()
            self.library_menu.add_menu_item(_("Choose..."), functools.partial(self.app.choose_library, self.queue_task))
            self.library_menu.add_menu_item(_("Clear"), self.app.clear_libraries)

        self.new_action = self.file_menu.add_menu_item(_("New Window"), lambda: self.new_window_with_data_item("library"), key_sequence="new")
        #self.open_action = self.file_menu.add_menu_item(_("Open"), lambda: self.no_operation(), key_sequence="open")
        self.close_action = self.file_menu.add_menu_item(_("Close Window"), lambda: self.document_window.request_close(), key_sequence="close")
        self.file_menu.add_separator()
        self.new_action = self.file_menu.add_sub_menu(_("Switch Library"), self.library_menu)
        self.file_menu.add_separator()
        self.import_action = self.file_menu.add_menu_item(_("Import..."), lambda: self.import_file())
        def export_files():
            selected_data_items = copy.copy(self.__data_browser_controller.selected_data_items)
            if len(selected_data_items) > 1:
                self.export_files(selected_data_items)
            elif len(selected_data_items) == 1:
                self.export_file(selected_data_items[0])
            elif self.selected_display_specifier.data_item:
                self.export_file(self.selected_display_specifier.data_item)
        self.export_action = self.file_menu.add_menu_item(_("Export..."), export_files)
        #self.file_menu.add_separator()
        #self.save_action = self.file_menu.add_menu_item(_("Save"), lambda: self.no_operation(), key_sequence="save")
        #self.save_as_action = self.file_menu.add_menu_item(_("Save As..."), lambda: self.no_operation(), key_sequence="save-as")
        self.file_menu.add_separator()
        self.add_group_action = self.file_menu.add_menu_item(_("Scripts..."), lambda: self.new_interactive_script_dialog(), key_sequence="Ctrl+R")
        self.file_menu.add_separator()
        self.add_group_action = self.file_menu.add_menu_item(_("Add Group"), lambda: self.add_group(), key_sequence="Ctrl+Shift+N")
        self.file_menu.add_separator()
        self.quit_action = self.file_menu.add_menu_item(_("Exit"), lambda: self.app.exit(), key_sequence="quit", role="quit")

        #self.undo_action = self.edit_menu.add_menu_item(_("Undo"), lambda: self.no_operation(), key_sequence="undo")
        #self.redo_action = self.edit_menu.add_menu_item(_("Redo"), lambda: self.no_operation(), key_sequence="redo")
        #self.edit_menu.add_separator()
        #self.cut_action = self.edit_menu.add_menu_item(_("Cut"), lambda: self.no_operation(), key_sequence="cut")
        #self.copy_action = self.edit_menu.add_menu_item(_("Copy"), lambda: self.no_operation(), key_sequence="copy")
        #self.paste_action = self.edit_menu.add_menu_item(_("Paste"), lambda: self.no_operation(), key_sequence="paste")
        #self.delete_action = self.edit_menu.add_menu_item(_("Delete"), lambda: self.no_operation(), key_sequence="delete")
        #self.select_all_action = self.edit_menu.add_menu_item(_("Select All"), lambda: self.no_operation(), key_sequence="select-all")
        #self.edit_menu.add_separator()
        self.script_action = self.edit_menu.add_menu_item(_("Script"), lambda: self.prepare_data_item_script(), key_sequence="Ctrl+Shift+K")
        self.copy_uuid_action = self.edit_menu.add_menu_item(_("Copy Item UUID"), lambda: self.copy_uuid(), key_sequence="Ctrl+Shift+U")
        self.empty_data_item_action = self.edit_menu.add_menu_item(_("Create New Data Item"), lambda: self.create_empty_data_item())
        #self.edit_menu.add_separator()
        #self.properties_action = self.edit_menu.add_menu_item(_("Properties..."), lambda: self.no_operation(), role="preferences")


        # these are temporary menu items, so don't need to assign them to variables, for now
        self.processing_menu.add_menu_item(_("Add Line Region"), lambda: self.add_line_region())
        self.processing_menu.add_menu_item(_("Add Ellipse Region"), lambda: self.add_ellipse_region())
        self.processing_menu.add_menu_item(_("Add Rectangle Region"), lambda: self.add_rectangle_region())
        self.processing_menu.add_menu_item(_("Add Point Region"), lambda: self.add_point_region())
        self.processing_menu.add_menu_item(_("Add Interval Region"), lambda: self.add_interval_region())
        self.processing_menu.add_separator()

        self.processing_menu.add_menu_item(_("Snapshot"), lambda: self.processing_snapshot(), key_sequence="Ctrl+S")
        self.processing_menu.add_menu_item(_("Duplicate"), lambda: self.processing_duplicate(), key_sequence="Ctrl+D")
        self.processing_menu.add_separator()

        self.processing_menu.add_menu_item(_("FFT"), lambda: self.processing_fft(), key_sequence="Ctrl+F")
        self.processing_menu.add_menu_item(_("Inverse FFT"), lambda: self.processing_ifft(), key_sequence="Ctrl+Shift+F")
        self.processing_menu.add_menu_item(_("Auto Correlate"), lambda: self.processing_auto_correlate())
        self.processing_menu.add_menu_item(_("Cross Correlate"), lambda: self.processing_cross_correlate())
        self.processing_menu.add_separator()

        self.processing_menu.add_menu_item(_("Sobel Filter"), lambda: self.processing_sobel())
        self.processing_menu.add_menu_item(_("Laplace Filter"), lambda: self.processing_laplace())
        self.processing_menu.add_menu_item(_("Gaussian Blur"), lambda: self.processing_gaussian_blur())
        self.processing_menu.add_menu_item(_("Median Filter"), lambda: self.processing_median_filter())
        self.processing_menu.add_menu_item(_("Uniform Filter"), lambda: self.processing_uniform_filter())
        self.processing_menu.add_separator()

        self.processing_menu.add_menu_item(_("Transpose and Flip"), lambda: self.processing_transpose_flip())
        self.processing_menu.add_menu_item(_("Resample"), lambda: self.processing_resample())
        self.processing_menu.add_menu_item(_("Crop"), lambda: self.processing_crop())
        self.processing_menu.add_menu_item(_("Slice"), lambda: self.processing_slice())
        self.processing_menu.add_menu_item(_("Pick"), lambda: self.processing_pick())
        self.processing_menu.add_menu_item(_("Projection"), lambda: self.processing_projection())
        self.processing_menu.add_menu_item(_("Invert"), lambda: self.processing_invert())
        self.processing_menu.add_separator()

        self.processing_menu.add_menu_item(_("Line Profile"), lambda: self.processing_line_profile())
        self.processing_menu.add_menu_item(_("Histogram"), lambda: self.processing_histogram())
        self.processing_menu.add_menu_item(_("Convert to Scalar"), lambda: self.processing_convert_to_scalar())
        self.processing_menu.add_separator()

        self.__dynamic_live_actions = []

        def about_to_show_display_type_menu():
            for dynamic_live_action in self.__dynamic_live_actions:
                self.display_type_menu.remove_action(dynamic_live_action)
            self.__dynamic_live_actions = []

            selected_display_panel = self.selected_display_panel
            if not selected_display_panel:
                return

            self.__dynamic_live_actions.extend(DisplayPanel.DisplayPanelManager().build_menu(self.display_type_menu, selected_display_panel))

        self.display_type_menu = self.ui.create_sub_menu(self.document_window)
        self.display_type_menu.on_about_to_show = about_to_show_display_type_menu

        # these are temporary menu items, so don't need to assign them to variables, for now
        def fit_to_view():
            if self.selected_display_panel is not None:
                self.selected_display_panel.perform_action("set_fit_mode")
        self.fit_view_action = self.view_menu.add_menu_item(_("Fit to View"), lambda: fit_to_view(), key_sequence="0")
        def fill_view():
            if self.selected_display_panel is not None:
                self.selected_display_panel.perform_action("set_fill_mode")
        self.fill_view_action = self.view_menu.add_menu_item(_("Fill View"), lambda: fill_view(), key_sequence="Shift+0")
        def one_to_one_view():
            if self.selected_display_panel is not None:
                self.selected_display_panel.perform_action("set_one_to_one_mode")
        def two_to_one_view():
            if self.selected_display_panel is not None:
                self.selected_display_panel.perform_action("set_two_to_one_mode")
        self.one_to_one_view_action = self.view_menu.add_menu_item(_("1:1 View"), lambda: one_to_one_view(), key_sequence="1")
        self.two_to_one_view_action = self.view_menu.add_menu_item(_("2:1 View"), lambda: two_to_one_view(), key_sequence="2")
        self.view_menu.add_separator()
        self.toggle_filter_action = self.view_menu.add_menu_item(_("Filter"), lambda: self.toggle_filter(), key_sequence="Ctrl+\\")
        self.view_menu.add_separator()
        self.view_menu.add_menu_item(_("Previous Workspace"), lambda: self.workspace_controller.change_to_previous_workspace(), key_sequence="Ctrl+[")
        self.view_menu.add_menu_item(_("Next Workspace"), lambda: self.workspace_controller.change_to_next_workspace(), key_sequence="Ctrl+]")
        self.view_menu.add_separator()
        self.view_menu.add_menu_item(_("New Workspace"), lambda: self.workspace_controller.create_workspace(), key_sequence="Ctrl+Alt+L")
        self.view_menu.add_menu_item(_("Rename Workspace"), lambda: self.workspace_controller.rename_workspace())
        self.view_menu.add_menu_item(_("Remove Workspace"), lambda: self.workspace_controller.remove_workspace())
        self.view_menu.add_separator()
        self.view_menu.add_sub_menu(_("Display Panel Type"), self.display_type_menu)
        self.view_menu.add_separator()

        self.__dynamic_view_actions = []

        def adjust_view_menu():
            for dynamic_view_action in self.__dynamic_view_actions:
                self.view_menu.remove_action(dynamic_view_action)
            self.__dynamic_view_actions = []
            for workspace in self.document_model.workspaces:
                def switch_to_workspace(workspace):
                    self.workspace_controller.change_workspace(workspace)
                action = self.view_menu.add_menu_item(workspace.name, functools.partial(switch_to_workspace, workspace))
                action.checked = self.document_model.workspace_uuid == workspace.uuid
                self.__dynamic_view_actions.append(action)

        self.view_menu.on_about_to_show = adjust_view_menu

        #self.help_action = self.help_menu.add_menu_item(_("Help"), lambda: self.no_operation(), key_sequence="help")
        self.about_action = self.help_menu.add_menu_item(_("About"), lambda: self.show_about_box(), role="about")

        self.window_menu.add_menu_item(_("Minimize"), lambda: self.no_operation())
        self.window_menu.add_menu_item(_("Bring to Front"), lambda: self.no_operation())
        self.window_menu.add_separator()

        self.__dynamic_window_actions = []

        def adjust_window_menu():
            for dynamic_window_action in self.__dynamic_window_actions:
                self.window_menu.remove_action(dynamic_window_action)
            self.__dynamic_window_actions = []
            for dock_widget in self.workspace_controller.dock_widgets:
                toggle_action = dock_widget.toggle_action
                self.window_menu.add_action(toggle_action)
                self.__dynamic_window_actions.append(toggle_action)

        self.window_menu.on_about_to_show = adjust_window_menu

    def get_menu(self, menu_id):
        assert menu_id.endswith("_menu")
        return getattr(self, menu_id, None)

    def get_or_create_menu(self, menu_id, menu_title, before_menu_id):
        assert menu_id.endswith("_menu")
        assert before_menu_id.endswith("_menu") if before_menu_id is not None else True
        if not hasattr(self, menu_id):
            before_menu = getattr(self, before_menu_id) if before_menu_id is not None else None
            menu = self.document_window.insert_menu(menu_title, before_menu)
            setattr(self, menu_id, menu)
        return getattr(self, menu_id)

    def show_about_box(self):
        version_str = self.app.version_str if self.app else str()
        root_dir = os.path.dirname((os.path.dirname(os.path.abspath(__file__))))
        path_ascend_count = 2
        for i in range(path_ascend_count):
            root_dir = os.path.dirname(root_dir)
        class AboutDialog(Dialog.OkCancelDialog):
            def __init__(self, ui):
                super(AboutDialog, self).__init__(ui, include_cancel=False)
                row = self.ui.create_row_widget()
                logo_button = self.ui.create_push_button_widget()
                image = self.ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/logo3.png"))
                logo_button.icon = image
                column = self.ui.create_column_widget()
                row_one = self.ui.create_row_widget()
                row_one.add_spacing(13)
                row_one.add(self.ui.create_label_widget("Nion Swift {0} {1}".format(version_str, root_dir)))
                row_one.add_spacing(13)
                row_one.add_stretch()
                row_two = self.ui.create_row_widget()
                row_two.add_spacing(13)
                row_two.add(self.ui.create_label_widget("Copyright 2012-2016 Nion Co. All Rights Reserved."))
                row_two.add_spacing(13)
                row_two.add_stretch()
                column.add_spacing(26)
                column.add(row_one)
                column.add(row_two)
                column.add_spacing(26)
                column.add_stretch()
                row.add(logo_button)
                row.add(column)
                self.content.add(row)
        AboutDialog(self.ui).show()

    def find_dock_widget(self, dock_widget_id):
        """ Return the dock widget by id. """
        return self.workspace_controller._find_dock_widget(dock_widget_id)

    # tasks can be added in two ways, queued or added
    # queued tasks are guaranteed to be executed in the order queued.
    # added tasks are only executed if not replaced before execution.
    # added tasks do not guarantee execution order or execution at all.

    def add_task(self, key, task):
        self.__periodic_set.add_task(key + str(id(self)), task)

    def clear_task(self, key):
        self.__periodic_set.clear_task(key + str(id(self)))

    def queue_task(self, task):
        assert task
        self.__periodic_queue.put(task)

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
        # import time
        # t0 = time.time()
        # logging.debug("t start %s ", t0)
        # perform any pending operations
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
        self.__periodic_queue.perform_tasks()
        if self.__periodic_queue is None:  # handle special case where we queue'd a close
            return
        self.__periodic_set.perform_tasks()
        # t1 = time.time()
        # workspace
        if self.workspace_controller:
            self.workspace_controller.periodic()
        # t2 = time.time()
        # self.filter_controller.periodic()
        # t3 = time.time()
        # logging.debug("t end %s %s %s", t1-t0, t2-t1, t3-t2)

    @property
    def workspace_controller(self):
        return self.__workspace_controller

    @property
    def workspace(self):
        return self.__workspace_controller

    @property
    def data_items_binding(self):
        return self.__data_items_binding

    @property
    def filtered_data_items_binding(self):
        return self.__filtered_data_items_binding

    @property
    def data_browser_controller(self):
        return self.__data_browser_controller

    def update_data_item_binding(self, binding, data_group, filter_id):

        """
            Update the data item binding with a new container, filter, and sorting.

            This is called when the data item binding is created or when the user changes
            the data group or sorting settings.
        """

        with binding.changes():  # change filter and sort together
            if data_group is not None:
                binding.container = data_group
                binding.filter = None
                binding.sort_key = None
            elif filter_id == "latest-session":
                binding.container = self.document_model
                def latest_session_filter(data_item):
                    return data_item.session_id == self.document_model.session_id
                binding.filter = latest_session_filter
                binding.sort_key = DataItem.sort_by_date_key
                binding.sort_reverse = True
            elif filter_id == "temporary":
                binding.container = self.document_model
                def temporary_filter(data_item):
                    return data_item.category != "persistent"
                binding.filter = temporary_filter
                binding.sort_key = DataItem.sort_by_date_key
                binding.sort_reverse = True
            elif filter_id == "none":  # not intended to be used directly
                binding.container = self.document_model
                def none_filter(data_item):
                    return False
                binding.filter = none_filter
                binding.sort_key = DataItem.sort_by_date_key
                binding.sort_reverse = True
            else:
                binding.container = self.document_model
                def all_filter(data_item):
                    return data_item.category == "persistent"
                binding.filter = all_filter
                binding.sort_key = DataItem.sort_by_date_key
                binding.sort_reverse = True

    def create_data_item_binding(self, data_group, filter_id):
        binding = DataItemsBinding.DataItemsInContainerBinding()
        self.update_data_item_binding(binding, data_group, filter_id)
        return binding

    def set_data_group_or_filter(self, data_group, filter_id):
        if self.__data_items_binding is not None:
            self.update_data_item_binding(self.__data_items_binding, data_group, filter_id)

    @property
    def display_filter(self):
        return self.__filtered_data_items_binding.filter

    @display_filter.setter
    def display_filter(self, display_filter):
        if self.__filtered_data_items_binding is not None:  # during close
            self.__filtered_data_items_binding.filter = display_filter

    def register_display_panel(self, display_panel):
        pass

    def unregister_display_panel(self, display_panel):
        if self.selected_display_panel == display_panel:
            self.selected_display_panel = None

    @property
    def selected_display_panel(self):
        return self.__weak_selected_display_panel() if self.__weak_selected_display_panel else None

    @selected_display_panel.setter
    def selected_display_panel(self, selected_display_panel):
        weak_selected_display_panel = weakref.ref(selected_display_panel) if selected_display_panel else None
        if weak_selected_display_panel != self.__weak_selected_display_panel:
            # save the selected panel
            self.__weak_selected_display_panel = weak_selected_display_panel
            # tell the workspace the selected image panel changed so that it can update the focus/selected rings
            self.workspace_controller.selected_display_panel_changed(self.selected_display_panel)
            # notify listeners that the data item has changed. in this case, a changing data item
            # means that which selected data item is selected has changed.
            data_item = selected_display_panel.data_item if selected_display_panel else None
            self.notify_selected_data_item_changed(data_item)

    # track the selected data item. this can be called by ui elements when
    # they get focus. the selected data item will stay the same until another ui
    # element gets focus or the data item is removed from the document.
    def notify_selected_data_item_changed(self, data_item):
        self.selected_data_item_changed_event.fire(data_item)

    def select_data_item_in_data_panel(self, data_item):
        """
            Select the data item in the data panel. Use the existing group and existing
            filter if data item appears. Otherwise, remove filter and see if it appears.
            Otherwise switch to Library group.
        """
        self.__data_browser_controller.set_data_browser_selection(data_item=data_item)

    @property
    def selected_display_specifier(self):
        """Return the selected display specifier (data_item, data_source, display).

        The selected display is the display that has keyboard focus in the data panel or a display panel.
        """
        # first check for the [focused] data browser
        data_item = self.__data_browser_controller.data_item
        if data_item:
            return DataItem.DisplaySpecifier.from_data_item(data_item)
        # if not found, check for focused or selected image panel
        return DataItem.DisplaySpecifier.from_data_item(self.selected_display_panel.data_item if self.selected_display_panel else None)

    def next_result_display_panel(self):
        for display_panel in self.workspace.display_panels:
            if display_panel.is_result_panel:
                return display_panel
        return None

    # this can be called from any user interface element that wants to update the cursor info
    # in the data panel. this would typically be from the image or line plot canvas.
    def cursor_changed(self, source, data_and_calibration, display_calibrated_values, pos):
        self.cursor_changed_event.fire(source, data_and_calibration, display_calibrated_values, pos)

    @property
    def tool_mode(self):
        return self.__tool_mode

    @tool_mode.setter
    def tool_mode(self, tool_mode):
        self.__tool_mode = tool_mode
        self.tool_mode_changed_event.fire(tool_mode)

    def new_window_with_data_item(self, workspace_id, data_item=None):
        # hack to work around Application <-> DocumentController interdependency.
        self.create_new_document_controller_event.fire(self.document_model, workspace_id, data_item)

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
        paths, selected_filter, selected_directory = self.document_window.get_file_paths_dialog(_("Import File(s)"), import_dir, filter)
        self.ui.set_persistent_string("import_directory", selected_directory)
        def import_complete(data_items):
            if len(data_items) > 0:
                result_display_panel = self.next_result_display_panel()
                if result_display_panel:
                    result_display_panel.set_displayed_data_item(data_items[-1])
                    result_display_panel.request_focus()
        self.receive_files(paths, completion_fn=import_complete)

    def export_file(self, data_item):
        # present a loadfile dialog to the user
        writers = ImportExportManager.ImportExportManager().get_writers_for_data_item(data_item)
        name_writer_set = set()
        for writer in writers:
            name_writer_set.add((writer.name, " ".join(["*." + extension for extension in writer.extensions]), writer))
        name_writer_list = sorted(name_writer_set)
        filter_line_to_writer_map = dict()
        filter_lines = list()
        for writer_name, writer_extensions, writer in name_writer_list:
            filter_line = writer_name + " files (" + writer_extensions + ")"
            filter_lines.append(filter_line)
            filter_line_to_writer_map[filter_line] = writer
        filter = ";;".join(filter_lines)
        filter += ";;All Files (*.*)"
        export_dir = self.ui.get_persistent_string("export_directory", self.ui.get_document_location())
        export_dir = os.path.join(export_dir, data_item.title)
        selected_filter = self.ui.get_persistent_string("export_filter")
        path, selected_filter, selected_directory = self.document_window.get_save_file_path(_("Export File"), export_dir, filter, selected_filter)
        if not os.path.splitext(path)[1]:
            if selected_filter in filter_line_to_writer_map:
                path = path + os.path.extsep + filter_line_to_writer_map[selected_filter].extensions[0]
        if path:
            self.ui.set_persistent_string("export_directory", selected_directory)
            self.ui.set_persistent_string("export_filter", selected_filter)
            return ImportExportManager.ImportExportManager().write_data_items(self.ui, data_item, path)

    def export_files(self, data_items):
        if len(data_items) > 1:
            export_dialog = ExportDialog.ExportDialog(self.ui)
            export_dialog.on_accept = functools.partial(export_dialog.do_export, data_items)
            export_dialog.show()
        elif len(data_items) == 1:
            self.export_file(data_items[0])

    # this method creates a task. it is thread safe.
    def create_task_context_manager(self, title, task_type, logging=True):
        task = Task.Task(title, task_type)
        task_context_manager = Task.TaskContextManager(self, task, logging)
        self.task_created_event.fire(task)
        return task_context_manager

    def new_interactive_script_dialog(self):
        interactive_dialog = ScriptsDialog.RunScriptDialog(self)
        interactive_dialog.show()

    def add_group(self):
        data_group = DataGroup.DataGroup()
        data_group.title = _("Untitled Group")
        self.document_model.insert_data_group(0, data_group)

    def remove_data_group_from_container(self, data_group, container):
        data_group_empty = len(data_group.data_items) == 0 and len(data_group.data_groups) == 0
        if data_group_empty:
            assert data_group in container.data_groups
            container.remove_data_group(data_group)

    def add_line_region(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            buffered_data_source = display_specifier.buffered_data_source
            display = display_specifier.display
            region = Region.LineRegion()
            region.start = (0.2, 0.2)
            region.end = (0.8, 0.8)
            buffered_data_source.add_region(region)
            graphic = region.graphic
            display.graphic_selection.set(display.drawn_graphics.index(graphic))
            return graphic
        return None

    def add_rectangle_region(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            buffered_data_source = display_specifier.buffered_data_source
            display = display_specifier.display
            region = Region.RectRegion()
            region.bounds = ((0.25,0.25), (0.5,0.5))
            buffered_data_source.add_region(region)
            graphic = region.graphic
            display.graphic_selection.set(display.drawn_graphics.index(graphic))
            return graphic
        return None

    def add_ellipse_region(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            buffered_data_source = display_specifier.buffered_data_source
            display = display_specifier.display
            region = Region.EllipseRegion()
            region.bounds = ((0.25,0.25), (0.5,0.5))
            buffered_data_source.add_region(region)
            graphic = region.graphic
            display.graphic_selection.set(display.drawn_graphics.index(graphic))
            return graphic
        return None

    def add_point_region(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            buffered_data_source = display_specifier.buffered_data_source
            display = display_specifier.display
            region = Region.PointRegion()
            region.position = (0.5,0.5)
            buffered_data_source.add_region(region)
            graphic = region.graphic
            display.graphic_selection.set(display.drawn_graphics.index(graphic))
            return graphic
        return None

    def add_interval_region(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            buffered_data_source = display_specifier.buffered_data_source
            display = display_specifier.display
            region = Region.IntervalRegion()
            region.start = 0.25
            region.end = 0.75
            buffered_data_source.add_region(region)
            graphic = region.graphic
            display.graphic_selection.set(display.drawn_graphics.index(graphic))
            return graphic
        return None

    def remove_graphic(self):
        display_specifier = self.selected_display_specifier
        if display_specifier:
            display = display_specifier.display
            if display.graphic_selection.has_selection:
                graphics = [display.drawn_graphics[index] for index in display.graphic_selection.indexes]
                for graphic in graphics:
                    display.remove_drawn_graphic(graphic)
                return True
        return False

    def add_processing_operation_by_id(self, buffered_data_source_specifier, operation_id, prefix=None, suffix=None, crop_region=None):
        operation = Operation.OperationItem(operation_id)
        assert operation is not None
        return self.add_processing_operation(buffered_data_source_specifier, operation, prefix, suffix, crop_region)

    def add_binary_processing_operation_by_id(self, operation_id, display_specifier1, display_specifier2, prefix=None, suffix=None, crop_region1=None, crop_region2=None):
        operation = Operation.OperationItem(operation_id)
        assert operation is not None
        return self.add_binary_processing_operation(operation, display_specifier1, display_specifier2, prefix, suffix, crop_region1, crop_region2)

    def add_data_element(self, data_element, source_data_item=None):
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        if data_item:
            self.document_model.append_data_item(data_item)
        return data_item

    def add_data(self, data, title=None):
        if title is None:
            r = random.randint(100000,999999)
            r_var = _("Data") + " %d" % r
        data_element = { "data": data, "title": title }
        return self.add_data_element(data_element)

    def display_data_item(self, display_specifier, source_data_item=None):
        data_item = display_specifier.data_item
        assert data_item is not None
        result_display_panel = self.next_result_display_panel()
        if result_display_panel:
            result_display_panel.set_displayed_data_item(data_item)
            result_display_panel.request_focus()
        self.select_data_item_in_data_panel(data_item)
        self.notify_selected_data_item_changed(display_specifier.data_item)
        inspector_panel = self.find_dock_widget("inspector-panel").panel
        if inspector_panel is not None:
            inspector_panel.request_focus = True

    def add_processing_operation(self, buffered_data_source_specifier, operation, prefix=None, suffix=None, crop_region=None):
        data_item = buffered_data_source_specifier.data_item
        buffered_data_source = buffered_data_source_specifier.buffered_data_source
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            data_source = Operation.DataItemDataSource(buffered_data_source)
            if crop_region:
                crop_operation = Operation.OperationItem("crop-operation")
                assert crop_region in buffered_data_source.regions
                crop_operation.set_property("bounds", crop_region.bounds)
                crop_operation.establish_associated_region("crop", buffered_data_source, crop_region)
                crop_operation.add_data_source(data_source)
                data_source = crop_operation
            operation.add_data_source(data_source)
            new_data_item = DataItem.DataItem()
            new_data_item.title = (prefix if prefix else "") + data_item.title + (suffix if suffix else "")
            new_data_item.set_operation(operation)
            new_data_item.category = data_item.category
            self.document_model.append_data_item(new_data_item)
            new_display_specifier = DataItem.DisplaySpecifier.from_data_item(new_data_item)
            self.display_data_item(new_display_specifier, source_data_item=data_item)
            return new_display_specifier
        return DataItem.DisplaySpecifier()

    def add_binary_processing_operation(self, operation, buffered_data_source_specifier1, buffered_data_source_specifier2, prefix=None, suffix=None, crop_region1=None, crop_region2=None):
        if buffered_data_source_specifier1.buffered_data_source and buffered_data_source_specifier2.buffered_data_source:
            new_data_item = DataItem.DataItem()
            new_data_item.title = (prefix if prefix else "") + buffered_data_source_specifier1.data_item.title + (suffix if suffix else "")
            new_data_item.set_operation(operation)
            if buffered_data_source_specifier1.data_item.category == "temporary":
                new_data_item.category = "temporary"
            if buffered_data_source_specifier2.data_item.category == "temporary":
                new_data_item.category = "temporary"
            data_source1 = Operation.DataItemDataSource(buffered_data_source_specifier1.buffered_data_source)
            if crop_region1:
                crop_operation = Operation.OperationItem("crop-operation")
                assert crop_region1 in buffered_data_source_specifier1.buffered_data_source.regions
                crop_operation.set_property("bounds", crop_region1.bounds)
                crop_operation.establish_associated_region("crop", buffered_data_source_specifier1.buffered_data_source, crop_region1)
                crop_operation.add_data_source(data_source1)
                data_source1 = crop_operation
            data_source2 = Operation.DataItemDataSource(buffered_data_source_specifier2.buffered_data_source)
            if crop_region2:
                crop_operation = Operation.OperationItem("crop-operation")
                assert crop_region2 in buffered_data_source_specifier2.buffered_data_source.regions
                crop_operation.set_property("bounds", crop_region2.bounds)
                crop_operation.establish_associated_region("crop", buffered_data_source_specifier2.buffered_data_source, crop_region2)
                crop_operation.add_data_source(data_source2)
                data_source2 = crop_operation
            operation.add_data_source(data_source1)
            operation.add_data_source(data_source2)
            self.document_model.append_data_item(new_data_item)
            self.display_data_item(DataItem.DisplaySpecifier.from_data_item(new_data_item), source_data_item=buffered_data_source_specifier1.data_item)
            return new_data_item
        return None

    def __get_crop_region(self, display_specifier):
        crop_region = None
        buffered_data_source = display_specifier.buffered_data_source
        if buffered_data_source and len(buffered_data_source.dimensional_shape) == 2:
            display = display_specifier.display
            current_index = display.graphic_selection.current_index
            if current_index is not None:
                region = display.drawn_graphics[current_index].region
                if isinstance(region, Region.RectRegion):
                    crop_region = region
        return crop_region

    def processing_fft(self):
        display_specifier = self.selected_display_specifier
        crop_region = self.__get_crop_region(display_specifier)
        return self.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "fft-operation", prefix=_("FFT of "), crop_region=crop_region)

    def processing_ifft(self):
        display_specifier = self.selected_display_specifier
        return self.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "inverse-fft-operation", prefix=_("Inverse FFT of "))

    def processing_auto_correlate(self):
        display_specifier = self.selected_display_specifier
        crop_region = self.__get_crop_region(display_specifier)
        return self.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "auto-correlate-operation", prefix=_("Auto Correlate of "), crop_region=crop_region)

    def processing_cross_correlate(self):
        selected_data_items = self.__data_browser_controller.selected_data_items
        if len(selected_data_items) == 2:
            display_specifier1 = DataItem.DisplaySpecifier.from_data_item(selected_data_items[0])
            display_specifier2 = DataItem.DisplaySpecifier.from_data_item(selected_data_items[1])
            crop_region1 = self.__get_crop_region(display_specifier1)
            crop_region2 = self.__get_crop_region(display_specifier2)
            return self.add_binary_processing_operation_by_id("cross-correlate-operation", display_specifier1.buffered_data_source_specifier, display_specifier2.buffered_data_source_specifier, prefix=_("Cross Correlate of "), crop_region1=crop_region1, crop_region2=crop_region2)
        return DataItem.DisplaySpecifier()

    def processing_sobel(self):
        display_specifier = self.selected_display_specifier
        crop_region = self.__get_crop_region(display_specifier)
        return self.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "sobel-operation", prefix=_("Sobel Filter of "), crop_region=crop_region)

    def processing_laplace(self):
        display_specifier = self.selected_display_specifier
        crop_region = self.__get_crop_region(display_specifier)
        return self.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "laplace-operation", prefix=_("Laplace Filter of "), crop_region=crop_region)

    def processing_gaussian_blur(self):
        display_specifier = self.selected_display_specifier
        crop_region = self.__get_crop_region(display_specifier)
        return self.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "gaussian-blur-operation", prefix=_("Gaussian Blur of "), crop_region=crop_region)

    def processing_median_filter(self):
        display_specifier = self.selected_display_specifier
        crop_region = self.__get_crop_region(display_specifier)
        return self.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "median-filter-operation", prefix=_("Median Filter of "), crop_region=crop_region)

    def processing_uniform_filter(self):
        display_specifier = self.selected_display_specifier
        crop_region = self.__get_crop_region(display_specifier)
        return self.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "uniform-filter-operation", prefix=_("Uniform Filter of "), crop_region=crop_region)

    def processing_transpose_flip(self):
        display_specifier = self.selected_display_specifier
        crop_region = self.__get_crop_region(display_specifier)
        return self.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "transpose-flip-operation", prefix=_("Transpose/Flip of "), crop_region=crop_region)

    def processing_resample(self):
        display_specifier = self.selected_display_specifier
        crop_region = self.__get_crop_region(display_specifier)
        return self.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "resample-operation", prefix=_("Resample of "), crop_region=crop_region)

    def processing_histogram(self):
        display_specifier = self.selected_display_specifier
        crop_region = self.__get_crop_region(display_specifier)
        return self.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "histogram-operation", prefix=_("Histogram of "), crop_region=crop_region)

    def processing_crop(self):
        display_specifier = self.selected_display_specifier
        buffered_data_source = display_specifier.buffered_data_source
        if buffered_data_source and len(buffered_data_source.dimensional_shape) == 2:
            crop_region = self.__get_crop_region(display_specifier)
            bounds = crop_region.bounds if crop_region else ((0.25,0.25), (0.5,0.5))
            operation = Operation.OperationItem("crop-operation")
            operation.set_property("bounds", bounds)
            operation.establish_associated_region("crop", buffered_data_source, crop_region)  # after setting operation properties
            return self.add_processing_operation(display_specifier.buffered_data_source_specifier, operation, prefix=_("Crop of "))
        return DataItem.DisplaySpecifier()

    def processing_slice(self):
        buffered_data_source_specifier = self.selected_display_specifier.buffered_data_source_specifier
        buffered_data_source = buffered_data_source_specifier.buffered_data_source
        if buffered_data_source and len(buffered_data_source.dimensional_shape) == 3:
            operation = Operation.OperationItem("slice-operation")
            operation.set_property("slice", 0)
            return self.add_processing_operation(buffered_data_source_specifier, operation, prefix=_("Slice of "))
        return DataItem.DisplaySpecifier()

    def processing_pick(self):
        display_specifier = self.selected_display_specifier
        buffered_data_source_specifier = display_specifier.buffered_data_source_specifier
        buffered_data_source = display_specifier.buffered_data_source
        if buffered_data_source and len(buffered_data_source.dimensional_shape) == 3:
            operation = Operation.OperationItem("pick-operation")
            region = operation.establish_associated_region("pick", buffered_data_source)  # after setting operation properties
            region.label = "Pick"
            pick_display_specifier = self.add_processing_operation(buffered_data_source_specifier, operation, prefix=_("Pick of "))
            pick_interval = Region.IntervalRegion()
            pick_display_specifier.buffered_data_source.add_region(pick_interval)
            pick_display_specifier.data_item.add_connection(Connection.PropertyConnection(display_specifier.display, "slice_interval", pick_interval, "interval"))
            return pick_display_specifier
        return DataItem.DisplaySpecifier()

    def processing_projection(self):
        display_specifier = self.selected_display_specifier
        buffered_data_source_specifier = display_specifier.buffered_data_source_specifier
        buffered_data_source = buffered_data_source_specifier.buffered_data_source
        if buffered_data_source and len(buffered_data_source.dimensional_shape) == 2:
            operation = Operation.OperationItem("projection-operation")
            crop_region = self.__get_crop_region(display_specifier)
            return self.add_processing_operation(buffered_data_source_specifier, operation, prefix=_("Projection of "), crop_region=crop_region)
        return DataItem.DisplaySpecifier()

    def processing_line_profile(self):
        buffered_data_source_specifier = self.selected_display_specifier.buffered_data_source_specifier
        buffered_data_source = buffered_data_source_specifier.buffered_data_source
        if buffered_data_source:
            operation = Operation.OperationItem("line-profile-operation")
            operation.set_property("start", (0.25,0.25))
            operation.set_property("end", (0.75,0.75))
            line_profile_region = operation.establish_associated_region("line", buffered_data_source)  # after setting operation properties
            line_profile_display_specifier = self.add_processing_operation(buffered_data_source_specifier, operation, prefix=_("Line Profile of "))
            line_profile_display_specifier.data_item.add_connection(Connection.IntervalListConnection(line_profile_display_specifier.buffered_data_source, line_profile_region))
            return line_profile_display_specifier
        return DataItem.DisplaySpecifier()

    def processing_invert(self):
        display_specifier = self.selected_display_specifier
        crop_region = self.__get_crop_region(display_specifier)
        return self.add_processing_operation_by_id(display_specifier.buffered_data_source_specifier, "invert-operation", suffix=_(" Inverted"), crop_region=crop_region)

    def processing_duplicate(self):
        data_item = self.selected_display_specifier.data_item
        if data_item:
            new_data_item = copy.deepcopy(data_item)
            new_data_item.title = _("Clone of ") + data_item.title
            new_data_item.category = data_item.category
            self.document_model.append_data_item(new_data_item)
            self.select_data_item_in_data_panel(new_data_item)
            self.notify_selected_data_item_changed(new_data_item)
            inspector_panel = self.find_dock_widget("inspector-panel").panel
            if inspector_panel is not None:
                inspector_panel.request_focus = True
            display_specifier = DataItem.DisplaySpecifier.from_data_item(new_data_item)
            self.display_data_item(display_specifier, source_data_item=data_item)
            return display_specifier
        return DataItem.DisplaySpecifier()

    def processing_snapshot(self):
        data_item = self.selected_display_specifier.data_item
        if data_item:
            data_item_copy = self.get_data_item_snapshot(data_item)
            self.select_data_item_in_data_panel(data_item_copy)
            self.notify_selected_data_item_changed(data_item_copy)
            inspector_panel = self.find_dock_widget("inspector-panel").panel
            if inspector_panel is not None:
                inspector_panel.request_focus = True
            display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item_copy)
            self.display_data_item(display_specifier, source_data_item=data_item)
            return display_specifier
        return DataItem.DisplaySpecifier()

    def get_data_item_snapshot(self, data_item: DataItem.DataItem) -> DataItem.DataItem:
        assert isinstance(data_item, DataItem.DataItem)
        data_item_copy = data_item.snapshot()
        data_item_copy.title = _("Snapshot of ") + data_item.title
        self.document_model.append_data_item(data_item_copy)
        return data_item_copy

    def fix_display_limits(self, display_specifier):
        display = display_specifier.display
        if display:
            display.display_limits = display.data_range

    def build_variable_map(self):
        map = dict()
        for weak_data_item in self.data_item_vars:
            data_item = weak_data_item()
            if data_item:
                map[self.data_item_vars[weak_data_item]] = self.document_model.get_object_specifier(data_item)
        return map

    def processing_computation(self, expression, map=None):
        if map is None:
            map = self.build_variable_map()
        data_item = DataItem.DataItem()
        data_item.title = _("Computation on ") + data_item.title
        computation = self.document_model.create_computation(expression)
        names = Symbolic.Computation.parse_names(expression)
        for variable_name, object_specifier in map.items():
            if variable_name in names:
                computation.create_object(variable_name, object_specifier)
        for variable in computation.variables:
            specifier = variable.specifier
            if specifier:
                object = self.document_model.resolve_object_specifier(variable.specifier)
                if isinstance(object, DataItem.DataItem) and object.category == "temporary":
                    data_item.category = "temporary"
        buffered_data_source = DataItem.BufferedDataSource()
        data_item.append_data_source(buffered_data_source)
        buffered_data_source.set_computation(computation)
        self.document_model.append_data_item(data_item)
        self.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item))
        return data_item

    def processing_cross_correlate_new(self):
        selected_data_items = self.__data_browser_controller.selected_data_items
        if len(selected_data_items) == 2:
            display_specifier1 = DataItem.DisplaySpecifier.from_data_item(selected_data_items[0])
            display_specifier2 = DataItem.DisplaySpecifier.from_data_item(selected_data_items[1])
            crop_region1 = self.__get_crop_region(display_specifier1)
            crop_region2 = self.__get_crop_region(display_specifier2)
            data_item = self.get_cross_correlate_new(display_specifier1.data_item, crop_region1, display_specifier2.data_item, crop_region2)
            if data_item:
                new_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
                self.display_data_item(new_display_specifier)
                return data_item
        return None

    def __processing_new(self, fn):
        display_specifier = self.selected_display_specifier
        crop_region = self.__get_crop_region(display_specifier)
        data_item = fn(display_specifier.data_item, crop_region)
        if data_item:
            new_display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
            self.display_data_item(new_display_specifier)
            return data_item
        return None

    Requirement = collections.namedtuple("Requirement", ["type", "mn", "mx"])

    @staticmethod
    def make_requirement(type, mn=None, mx=None):
        return DocumentController.Requirement(type, mn, mx)

    Source = collections.namedtuple("Source", ["data_item", "crop_region", "name", "label", "use_display_data", "requirements", "regions"])

    @staticmethod
    def make_source(data_item, crop_region=None, name=None, label=None, use_display_data=True, requirements=None, regions=None):
        return DocumentController.Source(data_item, crop_region, name, label, use_display_data, requirements, regions)

    Parameter = collections.namedtuple("Parameter", ["name", "label", "type", "value", "value_default", "value_min", "value_max", "control_type"])

    @staticmethod
    def make_parameter(name, label, type, value, value_default=None, value_min=None, value_max=None, control_type=None):
        return DocumentController.Parameter(name, label, type, value, value_default, value_min, value_max, control_type)

    Region_ = collections.namedtuple("Region", ["name", "type", "label", "region"])

    @staticmethod
    def make_region(name, type, label=None, region=None):
        return DocumentController.Region_(name, type, label, region)

    Connection = collections.namedtuple("Connection", ["type", "src", "src_prop", "dst", "dst_prop"])

    @staticmethod
    def make_connection(type, src=None, src_prop=None, dst=None, dst_prop=None):
        return DocumentController.Connection(type, src, src_prop, dst, dst_prop)

    def __get_processing_new(self, fn_template: str, sources: List, params: List, label: str, prefix: str=None, out_regions=None, connections=None) -> DataItem.DataItem:
        data_items = [source.data_item for source in sources]
        display_specifiers = [DataItem.DisplaySpecifier.from_data_item(data_item) for data_item in data_items]
        buffered_data_sources = [display_specifier.buffered_data_source for display_specifier in display_specifiers]
        for source, buffered_data_source in zip(sources, buffered_data_sources):
            for requirement in source.requirements or list():
                if requirement.type == "dimensionality":
                    dimensionality = len(buffered_data_source.dimensional_shape)
                    if requirement.mn is not None and dimensionality < requirement.mn:
                        return None
                    if requirement.mx is not None and dimensionality > requirement.mx:
                        return None
        if len(buffered_data_sources) > 0 and all(buffered_data_sources):
            new_data_item = DataItem.DataItem()
            prefix = prefix if prefix else "{} of ".format(label)
            new_data_item.title = prefix + data_items[0].title
            new_data_item.category = data_items[0].category
            src_names = list()
            src_texts = list()
            crop_names = list()
            regions = list()
            region_map = dict()
            for i, (source, buffered_data_source) in enumerate(zip(sources, buffered_data_sources)):
                suffix = i if len(sources) > 1 else ""
                src_name = source.name if source.name else "src{}".format(suffix)
                src_text = "{}.{}".format(src_name, "display_data" if source.use_display_data else "data")
                crop_name = "crop_region{}".format(suffix) if source.crop_region else ""
                src_text = src_text if not source.crop_region else "crop({}, {}.bounds)".format(src_text, crop_name)
                src_names.append(src_name)
                src_texts.append(src_text)
                crop_names.append(crop_name)
                for region in source.regions or list():
                    if region.type == "point":
                        if region.region:
                            point_region = region.region
                        else:
                            point_region = Region.PointRegion()
                            point_region.label = region.label
                            buffered_data_source.add_region(point_region)
                        regions.append((region.name, point_region, region.label))
                        region_map[region.name] = point_region
                    elif region.type == "line":
                        if region.region:
                            line_region = region.region
                        else:
                            line_region = Region.LineRegion()
                            line_region.start = 0.25, 0.25
                            line_region.end = 0.75, 0.75
                            buffered_data_source.add_region(line_region)
                        regions.append((region.name, line_region, region.label))
                        region_map[region.name] = line_region
                    elif region.type == "rectangle":
                        if region.region:
                            rect_region = region.region
                        else:
                            rect_region = Region.RectRegion()
                            rect_region.center = 0.5, 0.5
                            rect_region.size = 0.5, 0.5
                            rect_region.label = region.label
                            buffered_data_source.add_region(rect_region)
                        regions.append((region.name, rect_region, region.label))
                        region_map[region.name] = rect_region
            expression = fn_template.format(**dict(zip(src_names, src_texts)))
            computation = self.document_model.create_computation(expression)
            for src_name, display_specifier, source in zip(src_names, display_specifiers, sources):
                computation.create_object(src_name, self.document_model.get_object_specifier(display_specifier.data_item), label=source.label, cascade_delete=True)
            for crop_name, source in zip(crop_names, sources):
                if crop_name:
                    computation.create_object(crop_name, self.document_model.get_object_specifier(source.crop_region), label=_("Crop Region"), cascade_delete=True)
            for region_name, region, region_label in regions:
                computation.create_object(region_name, self.document_model.get_object_specifier(region), label=region_label, cascade_delete=True)
            for param in params:
                computation.create_variable(param.name, param.type, param.value, value_default=param.value_default, value_min=param.value_min, value_max=param.value_max,
                                            control_type=param.control_type, label=param.label)
            computation.label = label
            buffered_data_source = DataItem.BufferedDataSource()
            new_data_item.append_data_source(buffered_data_source)
            buffered_data_source.set_computation(computation)
            self.document_model.append_data_item(new_data_item)
            new_regions = dict()
            for region in out_regions or list():
                if region.type == "interval":
                    interval_region = Region.IntervalRegion()
                    buffered_data_source.add_region(interval_region)
                    new_regions[region.name] = interval_region
            for connection in connections or list():
                if connection.type == "property":
                    if connection.src == "display":
                        # TODO: how to refer to the buffered_data_sources?
                        new_data_item.add_connection(Connection.PropertyConnection(buffered_data_sources[0].displays[0], connection.src_prop, new_regions[connection.dst], connection.dst_prop))
                elif connection.type == "interval_list":
                    new_data_item.add_connection(Connection.IntervalListConnection(buffered_data_source, region_map[connection.dst]))
            return new_data_item
        return None

    def get_fft_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"))
        return self.__get_processing_new("fft({src})", [src], [], _("FFT"))

    def get_ifft_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, None, "src", _("Source"), use_display_data=False)
        return self.__get_processing_new("ifft({src})", [src], [], _("Inverse FFT"))

    def get_auto_correlate_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"))
        return self.__get_processing_new("autocorrelate({src})", [src], [], _("Auto Correlate"))

    def get_cross_correlate_new(self, data_item1: DataItem.DataItem, crop_region1: Region.RectRegion, data_item2: DataItem.DataItem, crop_region2: Region.RectRegion) -> DataItem.DataItem:
        src1 = DocumentController.make_source(data_item1, crop_region1, "src1", _("Source1"))
        src2 = DocumentController.make_source(data_item2, crop_region2, "src2", _("Source2"))
        return self.__get_processing_new("crosscorrelate({src1}, {src2})", [src1, src2], [], _("Cross Correlate"))

    def get_sobel_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"))
        return self.__get_processing_new("sobel({src})", [src], [], _("Sobel"))

    def get_laplace_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"))
        return self.__get_processing_new("laplace({src})", [src], [], _("Laplace"))

    def get_gaussian_blur_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"))
        param = DocumentController.make_parameter("sigma", _("Sigma"), "real", 3, value_default=3, value_min=0, value_max=100, control_type="slider")
        return self.__get_processing_new("gaussian_blur({src}, sigma)", [src], [param], _("Gaussian Blur"))

    def get_median_filter_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"))
        param = DocumentController.make_parameter("filter_size", _("Size"), "integral", 3, value_default=3, value_min=1, value_max=100)
        return self.__get_processing_new("median_filter({src}, filter_size)", [src], [param], _("Median Filter"))

    def get_uniform_filter_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"))
        param = DocumentController.make_parameter("filter_size", _("Size"), "integral", 3, value_default=3, value_min=1, value_max=100)
        return self.__get_processing_new("uniform_filter({src}, filter_size)", [src], [param], _("Uniform Filter"))

    def get_transpose_flip_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"))
        param1 = DocumentController.make_parameter("do_transpose", _("Transpose"), "boolean", False, value_default=False)
        param2 = DocumentController.make_parameter("do_flip_v", _("Flip Vertical"), "boolean", False, value_default=False)
        param3 = DocumentController.make_parameter("do_flip_h", _("Flip Horizontal"), "boolean", False, value_default=False)
        return self.__get_processing_new("transpose_flip({src}, do_transpose, do_flip_v, do_flip_h)", [src], [param1, param2, param3], _("Transpose/Flip"))

    def get_resample_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"))
        param1 = DocumentController.make_parameter("width", _("Width"), "integral", 256, value_default=256, value_min=1)
        param2 = DocumentController.make_parameter("height", _("Height"), "integral", 256, value_default=256, value_min=1)
        return self.__get_processing_new("resample_image({src}, shape(height, width))", [src], [param1, param2], _("Resample"))

    def get_histogram_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"))
        param = DocumentController.make_parameter("bins", _("Bins"), "integral", 256, value_default=256, value_min=2)
        return self.__get_processing_new("histogram({src}, bins)", [src], [param], _("Histogram"))

    def get_invert_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"))
        return self.__get_processing_new("invert({src})", [src], [], _("Invert"))

    def get_convert_to_scalar_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"))
        return self.__get_processing_new("{src}", [src], [], _("Scalar"))

    def get_crop_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        requirement = DocumentController.make_requirement("dimensionality", mn=2, mx=2)
        in_region = DocumentController.make_region("crop_region", "rectangle", _("Crop Region"), crop_region)
        src = DocumentController.make_source(data_item, None, "src", _("Source"), regions=[in_region], requirements=[requirement])
        return self.__get_processing_new("crop({src}, crop_region.bounds)", [src], [], _("Crop"))

    def get_projection_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        requirement = DocumentController.make_requirement("dimensionality", mn=2, mx=2)
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"), use_display_data=False, requirements=[requirement])
        return self.__get_processing_new("project({src})", [src], [], _("Slice"))

    def get_slice_sum_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion) -> DataItem.DataItem:
        requirement = DocumentController.make_requirement("dimensionality", mn=3, mx=3)
        src = DocumentController.make_source(data_item, crop_region, "src", _("Source"), use_display_data=False, requirements=[requirement])
        param1 = DocumentController.make_parameter("center", _("Center"), "integral", 0, value_default=0, value_min=0)
        param2 = DocumentController.make_parameter("width", _("Width"), "integral", 1, value_default=1, value_min=1)
        return self.__get_processing_new("slice_sum({src}, center, width)", [src], [param1, param2], _("Slice"))

    def get_pick_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion, pick_region: Region.PointRegion=None) -> DataItem.DataItem:
        requirement = DocumentController.make_requirement("dimensionality", mn=3, mx=3)
        in_region = DocumentController.make_region("pick_region", "point", _("Pick Point"), pick_region)
        out_region = DocumentController.make_region("interval_region", "interval")
        connection = DocumentController.make_connection("property", src="display", src_prop="slice_interval", dst="interval_region", dst_prop="interval")
        src = DocumentController.make_source(data_item, None, "src", _("Source"), use_display_data=False, regions=[in_region], requirements=[requirement])
        return self.__get_processing_new("pick({src}, pick_region.position)", [src], [], _("Slice"), out_regions=[out_region], connections=[connection])

    def get_line_profile_new(self, data_item: DataItem.DataItem, crop_region: Region.RectRegion, line_region: Region.LineRegion=None) -> DataItem.DataItem:
        in_region = DocumentController.make_region("line_region", "line", _("Line Profile"), line_region)
        connection = DocumentController.make_connection("interval_list", src="data_source", dst="line_region")
        src = DocumentController.make_source(data_item, None, "src", _("Source"), regions=[in_region])
        return self.__get_processing_new("line_profile({src}, line_region.vector, line_region.width)", [src], [], _("Line Profile"), connections=[connection])

    def toggle_filter(self):
        if self.workspace_controller.filter_row.visible:
            self.__last_display_filter = self.display_filter
            self.display_filter = None
        else:
            self.display_filter = self.__last_display_filter
        self.workspace_controller.filter_row.visible = not self.workspace_controller.filter_row.visible

    def assign_r_value_to_data_item(self, data_item):
        def find_var():
            while True:
                r = random.randint(100,999)
                r_var = "r%d" % r
                if r_var not in globals():
                    return r_var
            return None
        weak_data_item = weakref.ref(data_item)
        data_item_var = self.__data_item_vars.setdefault(weak_data_item, find_var())
        weak_data_item().set_r_value(data_item_var)  # this triggers the update of the title
        return data_item_var

    def prepare_data_item_script(self):
        lines = list()
        data_item = self.selected_display_specifier.data_item
        data_item_var = self.assign_r_value_to_data_item(data_item)
        lines.append("%s = _document_model.get_data_item_by_key(uuid.UUID(\"%s\"))" % (data_item_var, data_item.uuid))
        logging.debug(lines)
        if self.console:
            self.console.insert_lines(lines)

    def copy_uuid(self):
        display_specifier = self.selected_display_specifier
        display = display_specifier.display
        data_item = display_specifier.data_item
        if display:
            current_index = display.graphic_selection.current_index
            if current_index is not None:
                region = display.drawn_graphics[current_index].region
                uuid_str = str(region.uuid)
                self.ui.clipboard_set_text(uuid_str)
                return
        if data_item:
            uuid_str = str(data_item.uuid)
            self.ui.clipboard_set_text(uuid_str)
            return

    def create_empty_data_item(self):
        new_data_item = DataItem.DataItem()
        new_data_item.title = _("Untitled")
        self.document_model.append_data_item(new_data_item)
        new_display_specifier = DataItem.DisplaySpecifier.from_data_item(new_data_item)
        self.display_data_item(new_display_specifier)

    @property
    def data_item_vars(self):
        return self.__data_item_vars

    # receive files into the document model. data_group and index can optionally
    # be specified. if data_group is specified, the item is added to an arbitrary
    # position in the document model (the end) and at the group at the position
    # specified by the index. if the data group is not specified, the item is added
    # at the index within the document model.
    def receive_files(self, file_paths, data_group=None, index=-1, threaded=True, completion_fn=None):

        # this function will be called on a thread to receive files in the background.
        def receive_files_on_thread(file_paths, data_group, index, completion_fn):

            received_data_items = list()

            with self.create_task_context_manager(_("Import Data Items"), "table", logging=threaded) as task:
                task.update_progress(_("Starting import."), (0, len(file_paths)))
                task_data = {"headers": ["Number", "File"]}

                class IntRef(object):
                    def __init__(self, value):
                        self.value = value

                    def grab(self):
                        value = self.value
                        self.value += 1
                        return value

                index_ref = IntRef(index)

                for file_index, file_path in enumerate(file_paths):
                    data = task_data.setdefault("data", list())
                    root_path, file_name = os.path.split(file_path)
                    task_data_entry = [str(file_index + 1), file_name]
                    data.append(task_data_entry)
                    task.update_progress(_("Importing item {}.").format(file_index + 1),
                                         (file_index + 1, len(file_paths)), task_data)
                    try:
                        data_items = ImportExportManager.ImportExportManager().read_data_items(self.ui, file_path)

                        if data_items is not None:

                            # when data is read from the import manager, it has not yet been added to the document.
                            # this means that data is still in memory and has not been offloaded.
                            # when it gets added to the document, a write to the database is queued to a background
                            # thread. the background task will write the object in the background.
                            # but the data item itself will unload if the data ref count goes to zero, for instance if
                            # a thumbnail squeezes in before the write occurs.
                            # to prevent this, the data ref count is incremented here and released after the data
                            # is grabbed by the storage machinery.
                            # the data item has an event set up to signal when the data has been grabbed. this method
                            # waits on that event to ensure the data gets written out.
                            # TODO: Recover task if something goes wrong while saving data.

                            # grab a data ref and initialize the data save events
                            data_item_save_event = dict()
                            for data_item in data_items:
                                data_item.increment_data_ref_counts()
                                data_item_save_event[data_item] = threading.Event()

                            def insert_data_item(_document_model, _data_group, _data_items, index_ref):
                                if _data_group and isinstance(_data_group, DataGroup.DataGroup):
                                    for data_item in _data_items:
                                        _document_model.append_data_item(data_item)
                                        if index_ref.value >= 0:
                                            _data_group.insert_data_item(index_ref.grab(), data_item)
                                        else:
                                            _data_group.append_data_item(data_item)
                                        data_item_save_event[data_item].set()
                                else:  # insert into document model only
                                    for data_item in _data_items:
                                        if index_ref.value >= 0:
                                            _document_model.insert_data_item(index_ref.grab(), data_item)
                                        else:
                                            _document_model.append_data_item(data_item)
                                        data_item_save_event[data_item].set()

                            # notice that a lambda function is used to snapshot the first three arguments, but the
                            # index_ref argument is shared with all calls so that the items get inserted in order.
                            self.queue_task(functools.partial(insert_data_item, self.document_model, data_group, data_items, index_ref))

                            # wait for the save event to occur, then release the data ref.
                            for data_item in data_items:
                                if threaded:
                                    data_item_save_event[data_item].wait()
                                else:
                                    self.periodic()  # make sure periodic gets called at least once
                                    while not data_item_save_event[data_item].wait(0.05):
                                        self.periodic()
                                data_item.decrement_data_ref_counts()

                            received_data_items.extend(data_items)

                    except Exception as e:
                        logging.debug("Could not read image %s / %s", file_path, str(e))
                        traceback.print_exc()
                        traceback.print_stack()

                task.update_progress(_("Finishing importing."), (len(file_paths), len(file_paths)))

                if completion_fn:
                    completion_fn(received_data_items)

                return received_data_items

        if threaded:
            threading.Thread(target=receive_files_on_thread, args=(file_paths, data_group, index, completion_fn)).start()
            return None
        else:
            return receive_files_on_thread(file_paths, data_group, index, completion_fn)

    # this helps avoid circular imports
    def create_selected_data_item_binding(self):
        return SelectedDataItemBinding(self)

    def create_context_menu_for_data_item(self, data_item: DataItem.DataItem, container=None):
        menu = self.ui.create_context_menu(self.document_window)
        if data_item:
            if not container:
                container = self.data_items_binding.container
                container = DataGroup.get_data_item_container(container, data_item)

            def delete():
                selected_data_items = copy.copy(self.__data_browser_controller.selected_data_items)
                if not data_item in selected_data_items:
                    container.remove_data_item(data_item)
                else:
                    for selected_data_item in selected_data_items:
                        if container and selected_data_item in container.data_items:
                            container.remove_data_item(selected_data_item)
                            # TODO: avoid calling periodic by reworking thread support in data panel
                            self.periodic()  # keep the display items in data panel consistent.

            def show_in_new_window():
                self.new_window_with_data_item("data", data_item=data_item)

            menu.add_menu_item(_("Open in New Window"), show_in_new_window)

            def show():
                self.select_data_item_in_data_panel(data_item)
            menu.add_menu_item(_("Reveal"), show)

            menu.add_menu_item(_("Delete Data Item"), delete)

            def export_files():
                selected_data_items = copy.copy(self.__data_browser_controller.selected_data_items)
                if data_item in selected_data_items:
                    self.export_files(selected_data_items)
                else:
                    self.export_file(data_item)

            # when exporting, queue the task so that the pop-up is allowed to close before the dialog appears.
            # without queueing, it originally led to a crash (tested in Qt 5.4.1 on Windows 7).
            menu.add_menu_item(_("Export..."),
                               lambda: self.queue_task(export_files))  # queued to avoid pop-up menu issue

            source_data_items = self.document_model.get_source_data_items(data_item)
            if len(source_data_items) > 0:
                menu.add_separator()
                for source_data_item in source_data_items:
                    def show_source_data_item(data_item):
                        self.select_data_item_in_data_panel(data_item)

                    menu.add_menu_item("{0} \"{1}\"".format(_("Go to Source "), source_data_item.title),
                                       functools.partial(show_source_data_item, source_data_item))

            dependent_data_items = self.document_model.get_dependent_data_items(data_item)
            if len(dependent_data_items) > 0:
                menu.add_separator()
                for dependent_data_item in dependent_data_items:
                    def show_dependent_data_item(data_item):
                        self.select_data_item_in_data_panel(data_item)

                    menu.add_menu_item("{0} \"{1}\"".format(_("Go to Dependent "), dependent_data_item.title),
                                       functools.partial(show_dependent_data_item, dependent_data_item))
        return menu

class SelectedDataItemBinding(Observable.Broadcaster):
    """A binding to the selected data item in the document controller.

    The selected data item may be in an image panel, in the data panel, or in another user interface element. The
    document controller will send selected_data item_changed when the data item changes. This object will listen to the
    data item to know when its data changes or when it gets deleted.

    It will fire data_item_changed_event(data_item) when a new data item is selected or when the data item or its
    display mutates internally.
    """
    def __init__(self, document_controller):
        super(SelectedDataItemBinding, self).__init__()
        self.document_controller = document_controller
        self.__data_item = None
        self.__display_changed_event_listener = None
        self.data_item_changed_event = Event.Event()
        self.__selected_data_item_changed_event_listener = self.document_controller.selected_data_item_changed_event.listen(self.__selected_data_item_changed)
        # initialize with the existing value
        self.__selected_data_item_changed(document_controller.selected_display_specifier.data_item)

    def close(self):
        self.__selected_data_item_changed_event_listener.close()
        self.__selected_data_item_changed_event_listener = None
        # disconnect data item
        if self.__display_changed_event_listener:
            self.__display_changed_event_listener.close()
            self.__display_changed_event_listener = None
        # release references
        self.__data_item = None

    @property
    def data_item(self):
        return self.__data_item

    def __selected_data_item_changed(self, data_item):
        if self.__data_item != data_item:
            # disconnect listener from display
            if self.__display_changed_event_listener:
                self.__display_changed_event_listener.close()
                self.__display_changed_event_listener = None
            # save the new state
            self.__data_item = data_item
            # connect listener to display
            display_specifier = DataItem.DisplaySpecifier.from_data_item(self.__data_item)
            def display_changed():
                self.data_item_changed_event.fire(self.__data_item)
            if display_specifier.display:
                self.__display_changed_event_listener = display_specifier.display.display_changed_event.listen(display_changed)
            # notify our listeners
            display_changed()
