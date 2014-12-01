# standard libraries
import copy
import functools
import gettext
import logging
import os.path
import random
import threading
import traceback
import weakref

# third party libraries

# local libraries
from nion.swift import DataPanel
from nion.swift import FilterPanel
from nion.swift import Task
from nion.swift import Workspace
from nion.swift.model import Connection
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DataItemsBinding
from nion.swift.model import Display
from nion.swift.model import Graphics
from nion.swift.model import ImportExportManager
from nion.swift.model import Operation
from nion.swift.model import Region
from nion.swift.model import Utility
from nion.ui import Dialog
from nion.ui import Geometry
from nion.ui import Process
from nion.ui import Observable

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
        self.ui = ui
        # document_model may be shared between several DocumentControllers, so use reference counting
        # to determine when to close it.
        self.document_model = document_model
        self.document_model.add_ref()
        self.document_window = self.ui.create_document_window()
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
        self.replaced_data_item = None  # used to facilitate display panel functionality to exchange displays
        self.__weak_selected_image_panel = None
        self.weak_data_panel = None
        self.__tool_mode = "pointer"
        self.__periodic_queue = Process.TaskQueue()
        self.__periodic_set = Process.TaskSet()
        self.__selected_data_items = list()  # this will be updated by the data panel when one or more data items are selected
        self.__browser_data_item = None

        # the user has two ways of filtering data items: first by selecting a data group (or none) in the data panel,
        # and next by applying a custom filter to the items from the items resulting in the first selection.
        # data items binding tracks the main list of items selected in the data panel.
        # filtered data items binding tracks the filtered items from those in data items binding.
        self.__data_items_binding = DataItemsBinding.DataItemsInContainerBinding()
        self.__filtered_data_items_binding = DataItemsBinding.DataItemsFilterBinding(self.__data_items_binding)
        self.__last_display_filter = None

        self.filter_controller = FilterPanel.FilterController(self)

        self.console = None
        self.create_menus()
        if workspace_id:  # used only when testing reference counting
            self.__workspace_controller = Workspace.WorkspaceController(self, workspace_id)
            self.__workspace_controller.restore(self.document_model.workspace_uuid)

    def close(self):
        # recognize when we're running as test and finish out periodic operations
        if not self.document_window.has_event_loop:
            self.periodic()
        # menus
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
        self.document_window = None
        # get rid of the bindings
        self.__filtered_data_items_binding.close()
        self.__filtered_data_items_binding = None
        self.filter_controller.close()
        self.filter_controller = None
        self.__data_items_binding.close()
        self.__data_items_binding = None
        # document_model may be shared between several DocumentControllers, so use reference counting
        # to determine when to close it.
        self.document_model.remove_ref()
        self.document_model = None
        self.notify_listeners("document_controller_did_close", self)
        self.ui.destroy_document_window(self)

    def about_to_show(self):
        geometry, state = self.workspace_controller.restore_geometry_state()
        self.document_window.restore(geometry, state)

    def about_to_close(self, geometry, state):
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
            for file_path in recent_workspace_file_paths:
                root_path, file_name = os.path.split(file_path)
                name, ext = os.path.splitext(file_name)
                self.library_menu.add_menu_item(name, lambda file_path=file_path: self.app.switch_library(file_path))
            if len(recent_workspace_file_paths) > 0:
                self.library_menu.add_separator()
            self.library_menu.add_menu_item(_("Other..."), self.app.other_libraries)
            self.library_menu.add_menu_item(_("New..."), self.app.new_library)
            self.library_menu.add_menu_item(_("Clear"), self.app.clear_libraries)

        self.new_action = self.file_menu.add_menu_item(_("New Window"), lambda: self.new_window("library"), key_sequence="new")
        #self.open_action = self.file_menu.add_menu_item(_("Open"), lambda: self.no_operation(), key_sequence="open")
        self.close_action = self.file_menu.add_menu_item(_("Close Window"), lambda: self.document_window.close(), key_sequence="close")
        self.file_menu.add_separator()
        self.new_action = self.file_menu.add_sub_menu(_("Switch Library"), self.library_menu)
        self.file_menu.add_separator()
        self.import_action = self.file_menu.add_menu_item(_("Import..."), lambda: self.import_file())
        self.export_action = self.file_menu.add_menu_item(_("Export..."), lambda: self.export_files())
        #self.file_menu.add_separator()
        #self.save_action = self.file_menu.add_menu_item(_("Save"), lambda: self.no_operation(), key_sequence="save")
        #self.save_as_action = self.file_menu.add_menu_item(_("Save As..."), lambda: self.no_operation(), key_sequence="save-as")
        self.file_menu.add_separator()
        self.add_group_action = self.file_menu.add_menu_item(_("Add Group"), lambda: self.add_group(), key_sequence="Ctrl+Shift+N")
        self.file_menu.add_separator()
        self.quit_action = self.file_menu.add_menu_item(_("Exit"), lambda: self.ui.close(), key_sequence="quit", role="quit")

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
        #self.edit_menu.add_separator()
        #self.properties_action = self.edit_menu.add_menu_item(_("Properties..."), lambda: self.no_operation(), role="preferences")


        # these are temporary menu items, so don't need to assign them to variables, for now
        self.processing_menu.add_menu_item(_("Add Line Region"), lambda: self.add_line_region())
        self.processing_menu.add_menu_item(_("Add Ellipse Region"), lambda: self.add_ellipse_region())
        self.processing_menu.add_menu_item(_("Add Rectangle Region"), lambda: self.add_rectangle_region())
        self.processing_menu.add_menu_item(_("Add Point Region"), lambda: self.add_point_region())
        self.processing_menu.add_menu_item(_("Add Interval Region"), lambda: self.add_interval_region())
        self.processing_menu.add_separator()

        self.processing_menu.add_menu_item(_("FFT"), lambda: self.processing_fft(), key_sequence="Ctrl+F")
        self.processing_menu.add_menu_item(_("Inverse FFT"), lambda: self.processing_ifft(), key_sequence="Ctrl+Shift+F")
        self.processing_menu.add_menu_item(_("Auto Correlate"), lambda: self.processing_auto_correlate())
        self.processing_menu.add_menu_item(_("Cross Correlate"), lambda: self.processing_cross_correlate())
        self.processing_menu.add_menu_item(_("Gaussian Blur"), lambda: self.processing_gaussian_blur())
        self.processing_menu.add_menu_item(_("Resample"), lambda: self.processing_resample())
        self.processing_menu.add_menu_item(_("Crop"), lambda: self.processing_crop())
        self.processing_menu.add_menu_item(_("Slice"), lambda: self.processing_slice())
        self.processing_menu.add_menu_item(_("Pick"), lambda: self.processing_pick())
        self.processing_menu.add_menu_item(_("Projection"), lambda: self.processing_projection())
        self.processing_menu.add_menu_item(_("Line Profile"), lambda: self.processing_line_profile())
        self.processing_menu.add_menu_item(_("Invert"), lambda: self.processing_invert())
        self.processing_menu.add_menu_item(_("Duplicate"), lambda: self.processing_duplicate(), key_sequence="Ctrl+D")
        self.processing_menu.add_menu_item(_("Select"), lambda: self.processing_select())
        self.processing_menu.add_menu_item(_("Snapshot"), lambda: self.processing_snapshot(), key_sequence="Ctrl+Shift+S")
        self.processing_menu.add_menu_item(_("Histogram"), lambda: self.processing_histogram())
        self.processing_menu.add_menu_item(_("Convert to Scalar"), lambda: self.processing_convert_to_scalar())

        # these are temporary menu items, so don't need to assign them to variables, for now
        def fit_to_view():
            if self.selected_image_panel is not None:
                self.selected_image_panel.display_canvas_item.set_fit_mode()
        self.fit_view_action = self.view_menu.add_menu_item(_("Fit to View"), lambda: fit_to_view(), key_sequence="0")
        def fill_view():
            if self.selected_image_panel is not None:
                self.selected_image_panel.display_canvas_item.set_fill_mode()
        self.fill_view_action = self.view_menu.add_menu_item(_("Fill View"), lambda: fill_view(), key_sequence="Shift+0")
        def one_to_one_view():
            if self.selected_image_panel is not None:
                self.selected_image_panel.display_canvas_item.set_one_to_one_mode()
        self.one_to_one_view_action = self.view_menu.add_menu_item(_("1:1 View"), lambda: one_to_one_view(), key_sequence="1")
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
        root_dir = os.path.dirname(os.path.realpath(__file__))
        path_ascend_count = 2
        for i in range(path_ascend_count):
            root_dir = os.path.dirname(root_dir)
        class AboutDialog(Dialog.OkCancelDialog):
            def __init__(self, ui):
                super(AboutDialog, self).__init__(ui, include_cancel=False)
                row = self.ui.create_row_widget()
                logo_button = self.ui.create_push_button_widget()
                image = self.ui.load_rgba_data_from_file(":/Graphics/logo3.png")
                logo_button.icon = image
                column = self.ui.create_column_widget()
                row_one = self.ui.create_row_widget()
                row_one.add_spacing(13)
                row_one.add(self.ui.create_label_widget("Nion Swift {0} {1}".format(version_str, root_dir)))
                row_one.add_spacing(13)
                row_one.add_stretch()
                row_two = self.ui.create_row_widget()
                row_two.add_spacing(13)
                row_two.add(self.ui.create_label_widget("Copyright 2012-2014 Nion Co. All Rights Reserved."))
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
        self.__periodic_queue.put(task)

    def queue_main_thread_task(self, task):
        self.__periodic_queue.put(task)

    def periodic(self):
        #import time
        #t0 = time.time()
        # perform any pending operations
        self.__periodic_queue.perform_tasks()
        self.__periodic_set.perform_tasks()
        #t1 = time.time()
        # workspace
        if self.workspace_controller:
            self.workspace_controller.periodic()
        #t2 = time.time()
        self.filter_controller.periodic()
        #t3 = time.time()
        #logging.debug("t %s %s %s", t1-t0, t2-t1, t3-t2)

    def __get_workspace_controller(self):
        return self.__workspace_controller
    workspace_controller = property(__get_workspace_controller)

    def __get_workspace(self):
        return self.__workspace_controller
    workspace = property(__get_workspace)

    def __get_data_items_binding(self):
        return self.__data_items_binding
    data_items_binding = property(__get_data_items_binding)

    def __get_filtered_data_items_binding(self):
        return self.__filtered_data_items_binding
    filtered_data_items_binding = property(__get_filtered_data_items_binding)

    def update_data_item_binding(self, binding, data_group, filter_id):

        """
            Update the data item binding with a new container, filter, and sorting.

            This is called when the data item binding is created or when the user changes
            the data group or sorting settings.
        """

        def sort_by_date_key(data_item):
            """ A sort key to for the datetime_original field of a data item. """
            return data_item.title + str(data_item.uuid) if data_item.is_live else str(), Utility.get_datetime_from_datetime_item(data_item.datetime_original)

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
                binding.sort_key = sort_by_date_key
                binding.sort_reverse = True
            elif filter_id == "none":  # not intended to be used directly
                binding.container = self.document_model
                def none_filter(data_item):
                    return False
                binding.filter = none_filter
                binding.sort_key = sort_by_date_key
                binding.sort_reverse = True
            else:
                binding.container = self.document_model
                binding.filter = None
                binding.sort_key = sort_by_date_key
                binding.sort_reverse = True

    def create_data_item_binding(self, data_group, filter_id):
        binding = DataItemsBinding.DataItemsInContainerBinding()
        self.update_data_item_binding(binding, data_group, filter_id)
        return binding

    def set_data_group_or_filter(self, data_group, filter_id):
        if self.__data_items_binding is not None:
            self.update_data_item_binding(self.__data_items_binding, data_group, filter_id)

    def __get_display_filter(self):
        return self.__filtered_data_items_binding.filter
    def __set_display_filter(self, display_filter):
        if self.__filtered_data_items_binding is not None:  # during close
            self.__filtered_data_items_binding.filter = display_filter
    display_filter = property(__get_display_filter, __set_display_filter)

    def register_image_panel(self, image_panel):
        pass

    def unregister_image_panel(self, image_panel):
        if self.selected_image_panel == image_panel:
            self.selected_image_panel = None

    def __get_selected_image_panel(self):
        return self.__weak_selected_image_panel() if self.__weak_selected_image_panel else None
    def __set_selected_image_panel(self, selected_image_panel):
        weak_selected_image_panel = weakref.ref(selected_image_panel) if selected_image_panel else None
        if weak_selected_image_panel != self.__weak_selected_image_panel:
            # save the selected panel
            self.__weak_selected_image_panel = weak_selected_image_panel
            # tell the workspace the selected image panel changed so that it can update the focus/selected rings
            self.workspace_controller.selected_image_panel_changed(self.selected_image_panel)
            # notify listeners that the data item has changed. in this case, a changing data item
            # means that which selected data item is selected has changed.
            selected_data_item = selected_image_panel.get_displayed_data_item() if selected_image_panel else None
            self.notify_selected_data_item_changed(selected_data_item)
    selected_image_panel = property(__get_selected_image_panel, __set_selected_image_panel)

    # track the selected data item. this can be called by ui elements when
    # they get focus. the selected data item will stay the same until another ui
    # element gets focus or the data item is removed from the document.
    def notify_selected_data_item_changed(self, selected_data_item):
        self.notify_listeners("selected_data_item_changed", selected_data_item)

    def set_selected_data_items(self, selected_data_items):
        self.__selected_data_items = selected_data_items

    def __get_browser_data_item(self):
        return self.__browser_data_item
    browser_data_item = property(__get_browser_data_item)

    def set_browser_data_item(self, browser_data_item):
        assert browser_data_item is None or isinstance(browser_data_item, DataItem.DataItem)
        self.__browser_data_item = browser_data_item
        self.notify_listeners("browser_data_item_changed", browser_data_item)

    def select_data_item_in_data_panel(self, data_item):
        """
            Select the data item in the data panel. Use the existing group and existing
            filter if data item appears. Otherwise, remove filter and see if it appears.
            Otherwise switch to Library group.
        """
        data_panel = self.find_dock_widget("data-panel").panel
        if data_panel is not None:
            data_panel.update_data_panel_selection(DataPanel.DataPanelSelection(None, data_item, "all"))

    # access the currently selected data item. read only.
    def __get_selected_data_item(self):
        # first check focused data panel
        if self.weak_data_panel:
            data_panel = self.weak_data_panel()
            if data_panel and data_panel.focused:
                return data_panel.data_item
        # if not found, check for focused or selected image panel
        if self.selected_image_panel:
            return self.selected_image_panel.get_displayed_data_item()
        return None
    selected_data_item = property(__get_selected_data_item)

    def __get_selected_display(self):
        """
            Return the selected display.

            The selected display is the display that has keyboard focus.
        """
        data_item = self.selected_data_item
        return data_item.displays[0] if data_item else None
    selected_display = property(__get_selected_display)

    # this can be called from any user interface element that wants to update the cursor info
    # in the data panel. this would typically be from the image or line plot canvas.
    def cursor_changed(self, source, display, pos, image_size):
        self.notify_listeners("cursor_changed", source, display, pos, image_size)

    def __get_tool_mode(self):
        return self.__tool_mode
    def __set_tool_mode(self, tool_mode):
        self.__tool_mode = tool_mode
        if self.__tool_mode == "crop":  # hack until interactive crop tool is implemented
            self.processing_crop()
            self.__tool_mode = "pointer"
        elif self.__tool_mode == "line-profile":  # hack until interactive crop tool is implemented
            self.processing_line_profile()
            self.__tool_mode = "pointer"
    tool_mode = property(__get_tool_mode, __set_tool_mode)

    def new_window(self, workspace_id, data_panel_selection=None):
        # hack to work around Application <-> DocumentController interdependency.
        self.notify_listeners("create_document_controller", self.document_model, workspace_id, data_panel_selection)

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
        self.receive_files(paths)

    def export_file(self):
        # present a loadfile dialog to the user
        data_item = self.selected_data_item
        writers = ImportExportManager.ImportExportManager().get_writers_for_data_item(data_item)
        filter = ";;".join(
            [writer.name + " files (" + " ".join(
                ["*."+extension for extension in writer.extensions])
             + ")" for writer in writers])
        filter += ";;All Files (*.*)"
        export_dir = self.ui.get_persistent_string("export_directory", "")
        path, selected_filter, selected_directory = self.document_window.get_save_file_path(_("Export File"), export_dir, filter)
        self.ui.set_persistent_string("export_directory", selected_directory)
        if path:
            return ImportExportManager.ImportExportManager().write_data_items(self.ui, data_item, path)

    def export_files(self):
        selected_data_items = copy.copy(self.__selected_data_items)
        if len(selected_data_items) > 1:
            directory = self.ui.get_document_location()
            existing_directory, directory = self.ui.get_existing_directory_dialog(_("Choose Export Directory"), directory)
            if directory:
                for index, data_item in enumerate(selected_data_items):
                    try:
                        pixel_dimension_str = "x".join([str(shape_n) for shape_n in data_item.spatial_shape])
                        date_str = Utility.get_datetime_from_datetime_item(data_item.datetime_original).isoformat().replace(':', '')
                        path = os.path.join(directory, "Data_{0}_{1}_{2:05d}.dm3".format(date_str, pixel_dimension_str, index))
                        ImportExportManager.ImportExportManager().write_data_items(self.ui, data_item, path)
                    except Exception as e:
                        logging.debug("Could not export image %s / %s", str(data_item), str(e))
                        traceback.print_exc()
                        traceback.print_stack()
        else:
            self.export_file()

    # this method creates a task. it is thread safe.
    def create_task_context_manager(self, title, task_type, logging=True):
        task = Task.Task(title, task_type)
        task_context_manager = Task.TaskContextManager(self, task, logging)
        self.notify_listeners("task_created", task)
        return task_context_manager

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
        display = self.selected_display
        if display:
            assert isinstance(display, Display.Display)
            data_item = display.data_item
            assert data_item
            region = Region.LineRegion()
            region.start = (0.2, 0.2)
            region.end = (0.8, 0.8)
            data_item.add_region(region)
            graphic = region.graphic
            display.graphic_selection.set(display.drawn_graphics.index(graphic))
            return graphic
        return None

    def add_rectangle_region(self):
        display = self.selected_display
        if display:
            assert isinstance(display, Display.Display)
            data_item = display.data_item
            assert data_item
            region = Region.RectRegion()
            region.bounds = ((0.25,0.25), (0.5,0.5))
            data_item.add_region(region)
            graphic = region.graphic
            display.graphic_selection.set(display.drawn_graphics.index(graphic))
            return graphic
        return None

    def add_ellipse_region(self):
        display = self.selected_display
        if display:
            assert isinstance(display, Display.Display)
            data_item = display.data_item
            assert data_item
            region = Region.EllipseRegion()
            region.bounds = ((0.25,0.25), (0.5,0.5))
            data_item.add_region(region)
            graphic = region.graphic
            display.graphic_selection.set(display.drawn_graphics.index(graphic))
            return graphic
        return None

    def add_point_region(self):
        display = self.selected_display
        if display:
            assert isinstance(display, Display.Display)
            data_item = display.data_item
            assert data_item
            region = Region.PointRegion()
            region.position = (0.5,0.5)
            data_item.add_region(region)
            graphic = region.graphic
            display.graphic_selection.set(display.drawn_graphics.index(graphic))
            return graphic
        return None

    def add_interval_region(self):
        display = self.selected_display
        if display:
            assert isinstance(display, Display.Display)
            data_item = display.data_item
            assert data_item
            region = Region.IntervalRegion()
            region.start = 0.25
            region.end = 0.75
            data_item.add_region(region)
            graphic = region.graphic
            display.graphic_selection.set(display.drawn_graphics.index(graphic))
            return graphic
        return None

    def remove_graphic(self):
        display = self.selected_display
        if display and display.graphic_selection.has_selection():
            graphics = [display.drawn_graphics[index] for index in display.graphic_selection.indexes]
            for graphic in graphics:
                display.remove_drawn_graphic(graphic)
            return True
        return False

    # sets the selected data item in the data panel and an appropriate image panel.
    # use this sparingly, and only in response to user requests such as
    # adding an operation or starting an acquisition.
    # not thread safe
    def set_data_item_selection(self, data_item, source_data_item=None):
        self.notify_listeners("update_data_item_selection", data_item, source_data_item)

    def add_processing_operation_by_id(self, operation_id, prefix=None, suffix=None, in_place=False, select=True, crop_region=None):
        operation = Operation.OperationItem(operation_id)
        assert operation is not None
        return self.add_processing_operation(operation, prefix, suffix, in_place, select, crop_region)

    def add_binary_processing_operation_by_id(self, operation_id, data_item1, data_item2, prefix=None, suffix=None, crop_region1=None, crop_region2=None):
        operation = Operation.OperationItem(operation_id)
        assert operation is not None
        return self.add_binary_processing_operation(operation, data_item1, data_item2, prefix, suffix, crop_region1, crop_region2)

    def add_data_element(self, data_element, source_data_item=None):
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        if data_item:
            self.document_model.append_data_item(data_item)
            self.set_data_item_selection(data_item, source_data_item=source_data_item)
        return data_item

    def add_data(self, data, title=None):
        if title is None:
            r = random.randint(100000,999999)
            r_var = _("Data") + " %d" % r
        data_element = { "data": data, "title": title }
        return self.add_data_element(data_element)

    def display_data_item(self, data_item, source_data_item=None, select=True):
        self.document_model.append_data_item(data_item)
        if select:
            self.set_data_item_selection(data_item, source_data_item=source_data_item)
            self.select_data_item_in_data_panel(data_item)
            self.notify_selected_data_item_changed(data_item)
            inspector_panel = self.find_dock_widget("inspector-panel").panel
            if inspector_panel is not None:
                inspector_panel.request_focus = True

    def add_processing_operation(self, operation, prefix=None, suffix=None, in_place=False, select=True, crop_region=None):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            if in_place:  # in place?
                data_item.set_operation(operation)
                return data_item
            else:
                operation.add_data_source(Operation.DataItemDataSource(data_item))
                new_data_item = DataItem.DataItem()
                new_data_item.title = (prefix if prefix else "") + data_item.title + (suffix if suffix else "")
                new_data_item.set_operation(operation)
                self.display_data_item(new_data_item, source_data_item=data_item, select=select)
                return new_data_item
        return None

    def add_binary_processing_operation(self, operation, data_item1, data_item2, prefix=None, suffix=None, crop_region1=None, crop_region2=None):
        if data_item1 and data_item2:
            new_data_item = DataItem.DataItem()
            new_data_item.title = (prefix if prefix else "") + data_item1.title + (suffix if suffix else "")
            new_data_item.set_operation(operation)
            # new_data_item.add_data_source(Operation.DataItemDataSource(data_item1))
            # new_data_item.add_data_source(Operation.DataItemDataSource(data_item2))
            self.display_data_item(new_data_item, source_data_item=data_item, select=True)
            return new_data_item
        return None

    def __get_crop_region(self, data_item):
        crop_region = None
        if data_item and len(data_item.spatial_shape) == 2:
            display = data_item.displays[0]
            current_index = display.graphic_selection.current_index
            if current_index is not None:
                region = display.drawn_graphics[current_index].region
                if isinstance(region, Region.RectRegion):
                    crop_region = region
        return crop_region

    def processing_fft(self, select=True):
        crop_region = self.__get_crop_region(self.selected_data_item)
        return self.add_processing_operation_by_id("fft-operation", prefix=_("FFT of "), select=select, crop_region=crop_region)

    def processing_ifft(self, select=True):
        return self.add_processing_operation_by_id("inverse-fft-operation", prefix=_("Inverse FFT of "), select=select)

    def processing_auto_correlate(self, select=True):
        crop_region = self.__get_crop_region(self.selected_data_item)
        return self.add_processing_operation_by_id("auto-correlate-operation", prefix=_("Auto Correlate of "), select=select, crop_region=crop_region)

    def processing_cross_correlate(self, select=True):
        selected_data_items = self.__selected_data_items
        if len(selected_data_items) == 2:
            data_item1 = selected_data_items[0]
            data_item2 = selected_data_items[1]
            crop_region1 = self.__get_crop_region(data_item1)
            crop_region2 = self.__get_crop_region(data_item2)
            return self.add_binary_processing_operation_by_id("auto-correlate-operation", data_item1, data_item2, prefix=_("Auto Correlate of "), crop_region1=crop_region1, crop_region2=crop_region2)

    def processing_gaussian_blur(self, select=True):
        return self.add_processing_operation_by_id("gaussian-blur-operation", prefix=_("Gaussian Blur of "), select=select)

    def processing_resample(self, select=True):
        return self.add_processing_operation_by_id("resample-operation", prefix=_("Resample of "), select=select)

    def processing_histogram(self, select=True):
        crop_region = self.__get_crop_region(self.selected_data_item)
        return self.add_processing_operation_by_id("histogram-operation", prefix=_("Histogram of "), select=select, crop_region=crop_region)

    def processing_crop(self, select=True):
        data_item = self.selected_data_item
        if data_item and len(data_item.spatial_shape) == 2:
            crop_region = self.__get_crop_region(data_item)
            bounds = crop_region.bounds if crop_region else (0.25,0.25), (0.5,0.5)
            operation = Operation.OperationItem("crop-operation")
            operation.set_property("bounds", bounds)
            operation.establish_associated_region("crop", data_item, crop_region)  # after setting operation properties
            return self.add_processing_operation(operation, prefix=_("Crop of "), select=select)

    def processing_slice(self, select=True):
        data_item = self.selected_data_item
        if data_item and len(data_item.spatial_shape) == 3:
            operation = Operation.OperationItem("slice-operation")
            operation.set_property("slice", 0)
            return self.add_processing_operation(operation, prefix=_("Slice of "), select=select)

    def processing_pick(self, select=True):
        data_item = self.selected_data_item
        if data_item and len(data_item.spatial_shape) == 3:
            operation = Operation.OperationItem("pick-operation")
            operation.establish_associated_region("pick", data_item)  # after setting operation properties
            pick_data_item = self.add_processing_operation(operation, prefix=_("Pick of "), select=select)
            pick_interval = Region.IntervalRegion()
            pick_data_item.add_region(pick_interval)
            pick_data_item.add_connection(Connection.PropertyConnection(data_item.displays[0], "slice_interval", pick_interval, "interval"))
            return pick_data_item

    def processing_projection(self, select=True):
        data_item = self.selected_data_item
        if data_item and len(data_item.spatial_shape) == 2:
            operation = Operation.OperationItem("projection-operation")
            return self.add_processing_operation(operation, prefix=_("Projection of "), select=select)

    def processing_line_profile(self, select=True):
        data_item = self.selected_data_item
        if data_item:
            operation = Operation.OperationItem("line-profile-operation")
            operation.set_property("start", (0.25,0.25))
            operation.set_property("end", (0.75,0.75))
            operation.establish_associated_region("line", data_item)  # after setting operation properties
            return self.add_processing_operation(operation, prefix=_("Line Profile of "), select=select)
        return None

    def processing_invert(self, select=True):
        return self.add_processing_operation_by_id("invert-operation", suffix=_(" Inverted"), select=select)

    def processing_duplicate(self, select=True):
        data_item = self.selected_data_item
        if data_item:
            new_data_item = DataItem.DataItem()
            new_data_item.title = _("Clone of ") + data_item.title
            new_data_item.add_data_source(Operation.DataItemDataSource(data_item))
            self.document_model.append_data_item(new_data_item)
            if select:
                self.select_data_item_in_data_panel(new_data_item)
                self.notify_selected_data_item_changed(new_data_item)
                inspector_panel = self.find_dock_widget("inspector-panel").panel
                if inspector_panel is not None:
                    inspector_panel.request_focus = True
            return new_data_item
        return None

    def processing_select(self, select=True):
        return self.add_processing_operation_by_id("selector-operation", suffix=" [{0}]".format(0), select=select, in_place=True)

    def processing_snapshot(self, select=True):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            data_item_copy = data_item.snapshot()
            data_item_copy.title = _("Snapshot of ") + data_item.title
            # TODO: put this into existing group if copied from group
            self.document_model.append_data_item(data_item_copy)
            if select:
                self.select_data_item_in_data_panel(data_item_copy)
                self.notify_selected_data_item_changed(data_item_copy)
                inspector_panel = self.find_dock_widget("inspector-panel").panel
                if inspector_panel is not None:
                    inspector_panel.request_focus = True
            return data_item_copy
        return None

    def processing_convert_to_scalar(self, select=True):
        return self.add_processing_operation_by_id("convert-to-scalar-operation", suffix=_(" Gray"), select=select)

    def toggle_filter(self):
        if self.workspace_controller.filter_row.visible:
            self.__last_display_filter = self.display_filter
            self.display_filter = None
        else:
            self.display_filter = self.__last_display_filter
        self.workspace_controller.filter_row.visible = not self.workspace_controller.filter_row.visible

    def prepare_data_item_script(self):
        def find_var():
            while True:
                r = random.randint(100,999)
                r_var = "r%d" % r
                if r_var not in globals():
                    return r_var
            return None
        lines = list()
        weak_data_item = weakref.ref(self.selected_data_item)
        data_item_var = self.__data_item_vars.setdefault(weak_data_item, find_var())
        lines.append("%s = _data_item[uuid.UUID(\"%s\")]" % (data_item_var, self.selected_data_item.uuid))
        logging.debug(lines)
        if self.console:
            self.console.insert_lines(lines)

    def __get_data_item_vars(self):
        return self.__data_item_vars
    data_item_vars = property(__get_data_item_vars)

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
                task.update_progress(_("Starting import."), (0, str()))
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
                                data_item.increment_data_ref_count()
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
                            self.queue_main_thread_task(lambda document_model=self.document_model, data_group=data_group,
                                                               data_items=data_items: insert_data_item(document_model,
                                                                                                       data_group,
                                                                                                       data_items,
                                                                                                       index_ref))

                            # wait for the save event to occur, then release the data ref.
                            for data_item in data_items:
                                if threaded:
                                    data_item_save_event[data_item].wait()
                                else:
                                    self.periodic()  # make sure periodic gets called at least once
                                    while not data_item_save_event[data_item].wait(0.05):
                                        self.periodic()
                                data_item.decrement_data_ref_count()

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

    def show_context_menu_for_data_item(self, container, data_item, gx, gy):
        if data_item:
            menu = self.ui.create_context_menu(self.document_window)
            def delete():
                if container and data_item in container.data_items:
                    container.remove_data_item(data_item)
            def show_source():
                self.select_data_item_in_data_panel(data_item.ordered_data_item_data_sources[0])
            def show_in_new_window():
                self.new_window("data", DataPanel.DataPanelSelection(container, data_item))
            menu.add_menu_item(_("Open in New Window"), show_in_new_window)
            if len(data_item.ordered_data_item_data_sources) == 1:
                # TODO: show_source should handle multiple data sources
                menu.add_menu_item(_("Go to Source"), show_source)
            menu.add_menu_item(_("Delete"), delete)
            dependent_data_items = self.document_model.get_dependent_data_items(data_item)
            if len(dependent_data_items) > 0:
                menu.add_separator()
                for dependent_data_item in dependent_data_items:
                    def show_dependent_data_item(data_item):
                        self.select_data_item_in_data_panel(data_item)
                    menu.add_menu_item("{0} \"{1}\"".format(_("Go to "), dependent_data_item.title), functools.partial(show_dependent_data_item, dependent_data_item))
            menu.popup(gx, gy)


# binding to the selected data item in the document controller
# the selected data item may be in an image panel, in the data panel,
# or in another user interface element. the document controller will
# send selected_data_item_changed when the data item changes.
# this object will listen to the data item to know when its data
# changes or when it gets deleted.
class SelectedDataItemBinding(Observable.Broadcaster):

    def __init__(self, document_controller):
        super(SelectedDataItemBinding, self).__init__()
        self.__weak_data_item = None
        self.display = None
        self.document_controller = document_controller
        # connect self as listener. this will result in calls to selected_data_item_changed
        self.document_controller.add_listener(self)
        # initialize with the existing value
        self.selected_data_item_changed(document_controller.selected_data_item)

    def close(self):
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # disconnect data item
        if self.data_item:
            self.data_item.remove_listener(self)
        self.__weak_data_item = None

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    data_item = property(__get_data_item)

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_data_item_changed(self, data_item):
        old_data_item = self.data_item
        if data_item != old_data_item:
            # attach to the new item
            if data_item:
                data_item.add_listener(self)
            if self.display:
                self.display.remove_listener(self)
            # save the new data item
            self.__weak_data_item = weakref.ref(data_item) if data_item else None
            self.display = data_item.displays[0] if data_item else None
            if self.display:
                self.display.add_listener(self)
            # notify our listeners
            self.notify_listeners("data_item_binding_display_changed", self.display)
            # and detach from the old item
            if old_data_item:
                old_data_item.remove_listener(self)

    # this message is received from the display, if there is one.
    # it is established using add_listener
    # thread safe
    def display_changed(self, display):
        self.notify_listeners("data_item_binding_display_changed", self.display)

    # this message is received from the data item, if there is one.
    # it is established using add_listener
    def data_item_content_changed(self, data_item, changes):
        if data_item == self.data_item:
            self.selected_data_item_content_changed(data_item, changes)

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_data_item_content_changed(self, data_item, changes):
        assert data_item == self.data_item
        self.display_changed(self.display)
