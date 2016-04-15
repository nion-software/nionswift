# standard libraries
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
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DataItemsBinding
from nion.swift.model import DocumentModel
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
        self.import_folder_action = self.file_menu.add_menu_item(_("Import Folder..."), self.__import_folder)
        self.import_action = self.file_menu.add_menu_item(_("Import Data..."), self.import_file)
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

        self.processing_menu.add_menu_item(_("FFT"), lambda: self.__processing_new(self.document_model.get_fft_new), key_sequence="Ctrl+F")
        self.processing_menu.add_menu_item(_("Inverse FFT"), lambda: self.__processing_new(self.document_model.get_ifft_new), key_sequence="Ctrl+Shift+F")
        self.processing_menu.add_menu_item(_("Auto Correlate"), lambda: self.__processing_new(self.document_model.get_auto_correlate_new))
        self.processing_menu.add_menu_item(_("Cross Correlate"), lambda: self.processing_cross_correlate_new())
        self.processing_menu.add_separator()

        self.processing_menu.add_menu_item(_("Sobel Filter"), lambda: self.__processing_new(self.document_model.get_sobel_new))
        self.processing_menu.add_menu_item(_("Laplace Filter"), lambda: self.__processing_new(self.document_model.get_laplace_new))
        self.processing_menu.add_menu_item(_("Gaussian Blur"), lambda: self.__processing_new(self.document_model.get_gaussian_blur_new))
        self.processing_menu.add_menu_item(_("Median Filter"), lambda: self.__processing_new(self.document_model.get_median_filter_new))
        self.processing_menu.add_menu_item(_("Uniform Filter"), lambda: self.__processing_new(self.document_model.get_uniform_filter_new))
        self.processing_menu.add_separator()

        self.processing_menu.add_menu_item(_("Transpose and Flip"), lambda: self.__processing_new(self.document_model.get_transpose_flip_new))
        self.processing_menu.add_menu_item(_("Resample"), lambda: self.__processing_new(self.document_model.get_resample_new))
        self.processing_menu.add_menu_item(_("Crop"), lambda: self.__processing_new(self.document_model.get_crop_new))
        self.processing_menu.add_menu_item(_("Slice Sum"), lambda: self.__processing_new(self.document_model.get_slice_sum_new))
        self.processing_menu.add_menu_item(_("Pick"), lambda: self.__processing_new(self.document_model.get_pick_new))
        self.processing_menu.add_menu_item(_("Pick Region"), lambda: self.__processing_new(self.document_model.get_pick_region_new))
        self.processing_menu.add_menu_item(_("Projection"), lambda: self.processing_projection())
        self.processing_menu.add_menu_item(_("Invert"), lambda: self.__processing_new(self.document_model.get_invert_new))
        self.processing_menu.add_separator()

        self.processing_menu.add_menu_item(_("Line Profile"), lambda: self.__processing_new(self.document_model.get_line_profile_new))
        self.processing_menu.add_menu_item(_("Histogram"), lambda: self.__processing_new(self.document_model.get_histogram_new))
        self.processing_menu.add_menu_item(_("Convert to Scalar"), lambda: self.__processing_new(self.document_model.get_convert_to_scalar_new))
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

    def __import_folder(self):
        import json
        from nion.swift.model import Cache
        documents_dir = self.ui.get_document_location()
        workspace_dir, directory = self.ui.get_existing_directory_dialog(_("Choose Library Folder"), documents_dir)
        library_filename = "Nion Swift Workspace.nslib"
        cache_filename = "Nion Swift Cache.nscache"
        library_path = os.path.join(workspace_dir, library_filename)
        cache_path = os.path.join(workspace_dir, cache_filename)
        data_path = os.path.join(workspace_dir, "Nion Swift Data")
        if not os.path.exists(library_path):
            with open(library_path, "w") as fp:
                json.dump({}, fp)
            storage_cache = Cache.DbStorageCache(cache_path)
            file_persistent_storage_system = DocumentModel.FilePersistentStorageSystem([data_path])
            library_storage = DocumentModel.FilePersistentStorage(library_path)
            document_model = DocumentModel.DocumentModel(library_storage=library_storage, persistent_storage_systems=[file_persistent_storage_system], storage_cache=storage_cache,
                                                         ignore_older_files=True)

            def import_complete(data_items):
                document_model.close()
                self.app.switch_library(workspace_dir)

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

            self.receive_files(document_model, readable_file_paths, completion_fn=lambda data_items: self.queue_task(functools.partial(import_complete, data_items)))
        else:
            self.app.switch_library(workspace_dir)

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
        self.receive_files(self.document_model, paths, completion_fn=import_complete)

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
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_fft_new))

    def processing_ifft(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_ifft_new))

    def processing_gaussian_blur(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_gaussian_blur_new))

    def processing_resample(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_resample_new))

    def processing_crop(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_crop_new))

    def processing_slice(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_slice_sum_new))

    def processing_projection(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_projection_new))

    def processing_line_profile(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_line_profile_new))

    def processing_invert(self):
        return DataItem.DisplaySpecifier.from_data_item(self.__processing_new(self.document_model.get_invert_new))

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
            data_item = self.document_model.get_cross_correlate_new(display_specifier1.data_item, display_specifier2.data_item, crop_region1, crop_region2)
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
    def receive_files(self, document_model, file_paths, data_group=None, index=-1, threaded=True, completion_fn=None):

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
                            self.queue_task(functools.partial(insert_data_item, document_model, data_group, data_items, index_ref))

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

class SelectedDataItemBinding:
    """A binding to the selected data item in the document controller.

    The selected data item may be in an image panel, in the data panel, or in another user interface element. The
    document controller will send selected_data item_changed when the data item changes. This object will listen to the
    data item to know when its data changes or when it gets deleted.

    It will fire data_item_changed_event(data_item) when a new data item is selected or when the data item or its
    display mutates internally.
    """
    def __init__(self, document_controller):
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
