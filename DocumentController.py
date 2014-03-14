# standard libraries
import collections
import datetime
import functools
import gettext
import logging
import os.path
import random
import threading
import time
import traceback
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import DataGroup
from nion.swift import DataItem
from nion.swift import DataItemsBinding
from nion.swift import DataPanel
from nion.swift import DocumentModel
from nion.swift import Graphics
from nion.swift import ImportExportManager
from nion.swift import OperationItem
from nion.swift import Storage
from nion.swift import Task
from nion.swift import Utility
from nion.swift import Workspace
from nion.ui import Dialog
from nion.ui import Process
from nion.ui import Observable

_ = gettext.gettext


class DocumentController(Observable.Broadcaster):

    # document_window is passed from the application container.
    # the next method to be called will be initialize.
    def __init__(self, ui, document_model, workspace_id=None, app=None):
        super(DocumentController, self).__init__()
        self.ui = ui
        self.document_model = document_model
        self.document_model.add_ref()
        self.document_window = self.ui.create_document_window()
        self.document_window.on_periodic = lambda: self.periodic()
        self.document_window.on_about_to_show = lambda: self.about_to_show()
        self.document_window.on_about_to_close = lambda geometry, state: self.about_to_close(geometry, state)
        self.document_window.on_activation_changed = lambda activated: self.activation_changed(activated)
        self.workspace = None
        self.app = app
        self.replaced_data_item = None
        self.__weak_image_panels = []
        self.__weak_selected_image_panel = None
        self.weak_data_panel = None
        self.__tool_mode = "pointer"
        self.__periodic_queue = Process.TaskQueue()

        # the user has two ways of filtering data items: first by selecting a data group (or none) in the data panel,
        # and next by applying a custom filter to the items from the items resulting in the first selection.
        # data items binding tracks the main list of items selected in the data panel.
        # filtered data items binding tracks the filtered items from those in data items binding.
        self.__data_items_binding = DataItemsBinding.DataItemsInContainerBinding()
        self.__filtered_data_items_binding = DataItemsBinding.DataItemsFilterBinding(self.__data_items_binding)

        self.recent_data_items_container = DataItemsBinding.DataItemQueueContainer()

        self.console = None
        self.create_menus()
        if workspace_id:  # used only when testing reference counting
            self.workspace = Workspace.Workspace(self, workspace_id)

    def close(self):
        # recognize when we're running as test and finish out periodic operations
        if not self.document_window.has_event_loop:
            self.periodic()
        # get rid of the bindings first to improve performance
        self.__filtered_data_items_binding.close()
        self.__filtered_data_items_binding = None
        self.__data_items_binding.close()
        self.__data_items_binding = None
        # close the workspace before closing the image panels, to save their position
        if self.workspace:
            self.workspace.close()
        for image_panel in [weak_image_panel() for weak_image_panel in self.__weak_image_panels]:
            image_panel.close()
        self.document_window = None
        self.document_model.remove_ref()
        self.document_model = None
        self.window_menu.on_about_to_show = None
        self.notify_listeners("document_controller_did_close", self)

    def about_to_show(self):
        geometry, state = self.workspace.restore_geometry_state()
        self.document_window.restore(geometry, state)

    def about_to_close(self, geometry, state):
        self.workspace.save_geometry_state(geometry, state)
        self.close()

    def activation_changed(self, activated):
        if self.document_model and self.document_model.session:
            self.document_model.session.document_controller_activation_changed(self, activated)

    def register_console(self, console):
        self.console = console

    def unregister_console(self, console):
        self.console = None

    def create_menus(self):

        self.file_menu = self.document_window.add_menu(_("File"))

        self.edit_menu = self.document_window.add_menu(_("Edit"))

        self.processing_menu = self.document_window.add_menu(_("Processing"))

        self.view_menu = self.document_window.add_menu(_("View"))

        self.graphic_menu = self.document_window.add_menu(_("Graphic"))

        self.window_menu = self.document_window.add_menu(_("Window"))

        self.help_menu = self.document_window.add_menu(_("Help"))

        self.new_action = self.file_menu.add_menu_item(_("New"), lambda: self.new_window("library"), key_sequence="new")
        #self.open_action = self.file_menu.add_menu_item(_("Open"), lambda: self.no_operation(), key_sequence="open")
        self.close_action = self.file_menu.add_menu_item(_("Close"), lambda: self.document_window.close(), key_sequence="close")
        self.file_menu.add_separator()
        self.import_action = self.file_menu.add_menu_item(_("Import..."), lambda: self.import_file())
        self.export_action = self.file_menu.add_menu_item(_("Export..."), lambda: self.export_file())
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

        self.processing_menu.add_menu_item(_("FFT"), lambda: self.processing_fft(), key_sequence="Ctrl+F")
        self.processing_menu.add_menu_item(_("Inverse FFT"), lambda: self.processing_ifft(), key_sequence="Ctrl+Shift+F")
        self.processing_menu.add_menu_item(_("Double Gaussian Filter"), lambda: self.processing_double_gaussian_filter())
        self.processing_menu.add_menu_item(_("Gaussian Blur"), lambda: self.processing_gaussian_blur())
        self.processing_menu.add_menu_item(_("Resample"), lambda: self.processing_resample())
        self.processing_menu.add_menu_item(_("Crop"), lambda: self.processing_crop())
        self.processing_menu.add_menu_item(_("Line Profile"), lambda: self.processing_line_profile())
        self.processing_menu.add_menu_item(_("Invert"), lambda: self.processing_invert())
        self.processing_menu.add_menu_item(_("Duplicate"), lambda: self.processing_duplicate(), key_sequence="Ctrl+D")
        self.processing_menu.add_menu_item(_("Snapshot"), lambda: self.processing_snapshot(), key_sequence="Ctrl+Shift+S")
        self.processing_menu.add_menu_item(_("Histogram"), lambda: self.processing_histogram())
        self.processing_menu.add_menu_item(_("Convert to Scalar"), lambda: self.processing_convert_to_scalar())

        # these are temporary menu items, so don't need to assign them to variables, for now
        def fit_to_view():
            if self.selected_image_panel is not None:
                self.selected_image_panel.image_canvas_item.set_fit_mode()
        self.fit_view_action = self.view_menu.add_menu_item(_("Fit to View"), lambda: fit_to_view(), key_sequence="0")
        def fill_view():
            if self.selected_image_panel is not None:
                self.selected_image_panel.image_canvas_item.set_fill_mode()
        self.fill_view_action = self.view_menu.add_menu_item(_("Fill View"), lambda: fill_view(), key_sequence="Shift+0")
        def one_to_one_view():
            if self.selected_image_panel is not None:
                self.selected_image_panel.image_canvas_item.set_one_to_one_mode()
        self.one_to_one_view_action = self.view_menu.add_menu_item(_("1:1 View"), lambda: one_to_one_view(), key_sequence="1")
        self.view_menu.add_separator()
        self.view_menu.add_menu_item(_("Previous Layout"), lambda: self.workspace.change_to_previous_layout(), key_sequence="Ctrl+[")
        self.view_menu.add_menu_item(_("Next Layout"), lambda: self.workspace.change_to_next_layout(), key_sequence="Ctrl+]")

        self.view_menu.add_separator()
        self.view_menu.add_menu_item(_("Layout 1x1"), lambda: self.workspace.change_layout("1x1"), key_sequence="Ctrl+1")
        self.view_menu.add_menu_item(_("Layout 2x1"), lambda: self.workspace.change_layout("2x1"), key_sequence="Ctrl+2")
        self.view_menu.add_menu_item(_("Layout 3x1"), lambda: self.workspace.change_layout("3x1"), key_sequence="Ctrl+3")
        self.view_menu.add_menu_item(_("Layout 2x2"), lambda: self.workspace.change_layout("2x2"), key_sequence="Ctrl+4")
        self.view_menu.add_menu_item(_("Layout 1x2"), lambda: self.workspace.change_layout("1x2"), key_sequence="Ctrl+5")
        self.view_menu.add_menu_item(_("Layout 3x2"), lambda: self.workspace.change_layout("3x2"), key_sequence="Ctrl+6")
        #self.view_menu.add_menu_item(_("Layout 2x3"), lambda: self.workspace.change_layout("2x3"), key_sequence="Ctrl+7")
        #self.view_menu.add_menu_item(_("Layout 4x2"), lambda: self.workspace.change_layout("4x2"), key_sequence="Ctrl+8")
        #self.view_menu.add_menu_item(_("Layout 2x4"), lambda: self.workspace.change_layout("2x4"), key_sequence="Ctrl+9")

        self.view_menu.add_separator()
        self.toggle_filter_action = self.view_menu.add_menu_item(_("Filter"), lambda: self.toggle_filter(), key_sequence="Ctrl+\\")

        # these are temporary menu items, so don't need to assign them to variables, for now
        self.graphic_menu.add_menu_item(_("Add Line Graphic"), lambda: self.add_line_graphic())
        self.graphic_menu.add_menu_item(_("Add Ellipse Graphic"), lambda: self.add_ellipse_graphic())
        self.graphic_menu.add_menu_item(_("Add Rectangle Graphic"), lambda: self.add_rectangle_graphic())

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
            for dock_widget in self.workspace.dock_widgets:
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
                row_one.add(self.ui.create_label_widget("Nion Swift {0}".format(version_str)))
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

    def __get_panels(self):
        if self.workspace:
            # TODO: accessing the panel via the dock widget is deprecated
            return [dock_widget.panel for dock_widget in self.workspace.dock_widgets]
        return []
    panels = property(__get_panels)

    def queue_main_thread_task(self, task):
        self.__periodic_queue.put(task)

    def periodic(self):
        # perform any pending operations
        self.__periodic_queue.perform_tasks()
        if self.document_model and self.document_model.session:
            # for sessions
            self.document_model.session.periodic()
        # workspace
        if self.workspace:
            self.workspace.periodic()
        for image_panel in [weak_image_panel() for weak_image_panel in self.__weak_image_panels]:
            image_panel.periodic()
        if self.__data_items_binding:
            self.__data_items_binding.periodic()
        if self.__filtered_data_items_binding:
            self.__filtered_data_items_binding.periodic()

    def __get_data_items_binding(self):
        return self.__data_items_binding
    data_items_binding = property(__get_data_items_binding)

    def __get_filtered_data_items_binding(self):
        return self.__filtered_data_items_binding
    filtered_data_items_binding = property(__get_filtered_data_items_binding)

    def update_data_item_binding(self, binding, data_group, filter_id):
        with binding.changes():  # change filter and sort together
            if data_group is not None:
                binding.container = data_group
                binding.flat = False
                binding.filter = None
                binding.sort = DataItemsBinding.sort_natural
            elif filter_id == "latest-session":
                binding.container = self.document_model
                binding.flat = False
                def latest_session_filter(data_item):
                    return data_item.session_id == self.document_model.session.session_id
                binding.filter = latest_session_filter
                binding.sort = DataItemsBinding.sort_by_date_desc
            elif filter_id == "recent":
                binding.container = self.recent_data_items_container
                binding.flat = True
                binding.filter = None
                binding.sort = DataItemsBinding.sort_natural
            elif filter_id == "none":  # not intended to be used directly
                binding.container = self.document_model
                binding.flat = False
                def none_filter(data_item):
                    return False
                binding.filter = none_filter
                binding.sort = DataItemsBinding.sort_natural
            else:
                binding.container = self.document_model
                binding.flat = False
                binding.filter = None
                binding.sort = DataItemsBinding.sort_natural

    def create_data_item_binding(self, data_group, filter_id):
        binding = DataItemsBinding.DataItemsInContainerBinding()
        self.update_data_item_binding(binding, data_group, filter_id)
        return binding

    def set_data_group_or_filter(self, data_group, filter_id):
        if self.__data_items_binding is not None:
            # this is done in two steps, as an ugly ugly hack.
            # TODO: Fix the filter update hack.
            # the purpose is to clear out the data items in the filtered data items binding
            # so that the level gets recalculated. otherwise the data panel simply re-uses
            # the existing data item and level. this is a bad design.
            with self.__filtered_data_items_binding.changes():
                self.update_data_item_binding(self.__data_items_binding, None, "none")
            with self.__filtered_data_items_binding.changes():
                self.update_data_item_binding(self.__data_items_binding, data_group, filter_id)

    def __get_display_filter(self):
        return self.__filtered_data_items_binding.filter
    def __set_display_filter(self, display_filter):
        self.__filtered_data_items_binding.filter = display_filter
    display_filter = property(__get_display_filter, __set_display_filter)

    def register_image_panel(self, image_panel):
        weak_image_panel = weakref.ref(image_panel)
        self.__weak_image_panels.append(weak_image_panel)

    def unregister_image_panel(self, image_panel):
        if self.selected_image_panel == image_panel:
            self.selected_image_panel = None
        weak_image_panel = weakref.ref(image_panel)
        self.__weak_image_panels.remove(weak_image_panel)

    def __get_selected_image_panel(self):
        return self.__weak_selected_image_panel() if self.__weak_selected_image_panel else None
    def __set_selected_image_panel(self, selected_image_panel):
        assert type(selected_image_panel).__name__ == "ImagePanel" if selected_image_panel else True  # avoid circular import
        if not selected_image_panel:
            selected_image_panel = self.workspace.primary_image_panel
        weak_selected_image_panel = weakref.ref(selected_image_panel) if selected_image_panel else None
        if weak_selected_image_panel != self.__weak_selected_image_panel:
            # save the selected panel
            self.__weak_selected_image_panel = weak_selected_image_panel
            # iterate through the image panels and update their 'focused' property
            for image_panel in [weak_image_panel() for weak_image_panel in self.__weak_image_panels]:
                image_panel.set_selected(image_panel == self.selected_image_panel)
            # notify listeners that the data item has changed. in this case, a changing data item
            # means that which selected data item is selected has changed.
            selected_data_item = selected_image_panel.data_item if selected_image_panel is not None else None
            self.set_selected_data_item(selected_data_item)
    selected_image_panel = property(__get_selected_image_panel, __set_selected_image_panel)

    # track the selected data item. this can be called by ui elements when
    # they get focus. the selected data item will stay the same until another ui
    # element gets focus or the data item is removed from the document.
    def set_selected_data_item(self, selected_data_item):
        self.notify_listeners("selected_data_item_changed", selected_data_item)

    def sync_data_item(self, data_item):
        """
            Select the data item in the data panel. Use the existing group and existing
            filter if data item appears. Otherwise, remove filter and see if it appears.
            Otherwise switch to Library group.
        """
        data_panel = self.workspace.find_dock_widget("data-panel").panel
        if data_panel is not None:
            # first find the master data item if data item is not a master
            master_data_item = data_item
            while master_data_item.has_data_source:
                master_data_item = master_data_item.data_source
            if master_data_item in self.__data_items_binding.data_items:
                data_panel.update_data_item_selection(data_item)
            else:
                data_panel.update_data_panel_selection(DataPanel.DataPanelSelection(None, data_item, "all"))

    def note_new_recent_data_item(self, data_item):
        """ Register a data item into the most recent used list. """
        assert data_item is not None
        assert isinstance(data_item, DataItem.DataItem)
        self.recent_data_items_container.insert_data_item(data_item)

    def __get_recent_data_items(self):
        """ Return up to the most recent data items that the user has placed in display panels. """
        return self.recent_data_items_container.data_items
    recent_data_items = property(__get_recent_data_items)

    # access the currently selected data item. read only.
    def __get_selected_data_item(self):
        # first check focused data panel
        if self.weak_data_panel:
            data_panel = self.weak_data_panel()
            if data_panel and data_panel.focused:
                return data_panel.data_item
        # if not found, check for focused or selected image panel
        if self.selected_image_panel:
            return self.selected_image_panel.data_item
        return None
    selected_data_item = property(__get_selected_data_item)

    # this can be called from any user interface element that wants to update the cursor info
    # in the data panel. this would typically be from the image or line plot canvas.
    def cursor_changed(self, source, data_item, pos, selected_graphics, image_size):
        self.notify_listeners("cursor_changed", source, data_item, pos, selected_graphics, image_size)

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

    # this method creates a task. it is thread safe.
    def create_task_context_manager(self, title, task_type, logging=True):
        task = Task.Task(title, task_type)
        task_context_manager = Task.TaskContextManager(self, task, logging)
        self.notify_listeners("task_created", task)
        return task_context_manager

    def add_group(self):
        data_group = DataGroup.DataGroup()
        data_group.title = _("Untitled Group")
        self.document_model.data_groups.insert(0, data_group)

    def remove_data_group_from_container(self, data_group, container):
        data_group_empty = len(data_group.data_items) == 0 and len(data_group.data_groups) == 0
        if data_group_empty:
            assert data_group in container.data_groups
            container.data_groups.remove(data_group)

    def add_line_graphic(self):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            graphic = Graphics.LineGraphic()
            graphic.start = (0.2,0.2)
            graphic.end = (0.8,0.8)
            data_item.append_graphic(graphic)
            self.selected_image_panel.graphic_selection.set(data_item.drawn_graphics.index(graphic))
            return graphic
        return None

    def add_rectangle_graphic(self):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            data_item.append_graphic(graphic)
            self.selected_image_panel.graphic_selection.set(data_item.drawn_graphics.index(graphic))
            return graphic
        return None

    def add_ellipse_graphic(self):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            graphic = Graphics.EllipseGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            data_item.append_graphic(graphic)
            self.selected_image_panel.graphic_selection.set(data_item.drawn_graphics.index(graphic))
            return graphic
        return None

    def remove_graphic(self):
        data_item = self.selected_data_item
        if data_item and self.selected_image_panel.graphic_selection.has_selection():
            graphics = [data_item.drawn_graphics[index] for index in self.selected_image_panel.graphic_selection.indexes]
            for graphic in graphics:
                data_item.remove_drawn_graphic(graphic)

    def remove_operation(self, operation):
        data_item = self.selected_data_item
        if data_item:
            data_item.operations.remove(operation)

    # sets the selected data item in the data panel and an appropriate image panel.
    # use this sparingly, and only in response to user requests such as
    # adding an operation or starting an acquisition.
    # not thread safe
    def set_data_item_selection(self, data_item, source_data_item=None):
        self.notify_listeners("update_data_item_selection", data_item, source_data_item)
        # now attempt to display the data item in an image panel
        if not source_data_item:
            self.workspace.display_data_item(data_item)
        else:
            self.workspace.display_data_item(data_item, source_data_item)

    def add_processing_operation_by_id(self, operation_id, prefix=None, suffix=None, in_place=False, select=True):
        operation = OperationItem.OperationItem(operation_id)
        assert operation is not None
        self.add_processing_operation(operation, prefix, suffix, in_place, select)

    def add_data_element(self, data_element, source_data_item=None):
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        if data_item:
            self.document_model.append_data_item(data_item)
            self.set_data_item_selection(data_item, source_data_item=source_data_item)
        return data_item

    def add_processing_operation(self, operation, prefix=None, suffix=None, in_place=False, select=True):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            if in_place:  # in place?
                data_item.operations.append(operation)
                return data_item
            else:
                new_data_item = DataItem.DataItem()
                new_data_item.title = (prefix if prefix else "") + data_item.title + (suffix if suffix else "")
                new_data_item.operations.append(operation)
                data_item.data_items.append(new_data_item)
                if select:
                    self.set_data_item_selection(new_data_item, source_data_item=data_item)
                return new_data_item
        return None

    def processing_fft(self, select=True):
        return self.add_processing_operation_by_id("fft-operation", prefix=_("FFT of "), select=select)

    def processing_ifft(self, select=True):
        return self.add_processing_operation_by_id("inverse-fft-operation", prefix=_("Inverse FFT of "), select=select)

    def processing_double_gaussian_filter(self, select=True):
        return self.add_processing_operation_by_id("double-gaussian-filter-operation", prefix=_("Double Gaussian Filter of "), select=select)

    def processing_gaussian_blur(self, select=True):
        return self.add_processing_operation_by_id("gaussian-blur-operation", prefix=_("Gaussian Blur of "), select=select)

    def processing_resample(self, select=True):
        return self.add_processing_operation_by_id("resample-operation", prefix=_("Resample of "), select=select)

    def processing_histogram(self, select=True):
        return self.add_processing_operation_by_id("histogram-operation", prefix=_("Histogram of "), select=select)

    def processing_crop(self, select=True):
        data_item = self.selected_data_item
        if data_item:
            operation = OperationItem.OperationItem("crop-operation")
            operation.set_property("bounds", ((0.25,0.25), (0.5,0.5)))
            return self.add_processing_operation(operation, prefix=_("Crop of "), select=select)

    def processing_line_profile(self, select=True):
        data_item = self.selected_data_item
        if data_item:
            operation = OperationItem.OperationItem("line-profile-operation")
            operation.set_property("start", (0.25,0.25))
            operation.set_property("end", (0.75,0.75))
            return self.add_processing_operation(operation, prefix=_("Line Profile of "), select=select)
        return None

    def processing_invert(self, select=True):
        return self.add_processing_operation_by_id("invert-operation", suffix=_(" Inverted"), select=select)

    def processing_duplicate(self, select=True):
        data_item = self.selected_data_item
        if data_item:
            new_data_item = DataItem.DataItem()
            new_data_item.title = _("Clone of ") + data_item.title
            data_item.data_items.append(new_data_item)
            return new_data_item
        return None

    def processing_snapshot(self, select=True):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            data_item_copy = data_item.snapshot()
            data_item_copy.title = _("Snapshot of ") + data_item.title
            # TODO: put this into existing group if copied from group
            self.document_model.append_data_item(data_item_copy)
            return data_item_copy
        return None

    def processing_convert_to_scalar(self, select=True):
        return self.add_processing_operation_by_id("convert-to-scalar-operation", suffix=_(" Gray"), select=select)

    def toggle_filter(self):
        self.workspace.filter_row.visible = not self.workspace.filter_row.visible

    def prepare_data_item_script(self):
        def find_var():
            while True:
                r = random.randint(100,999)
                r_var = "r%d" % r
                if r_var not in globals():
                    return r_var
            return None
        lines = list()
        lines.append("%s = _data_item[uuid.UUID(\"%s\")]" % (find_var(), self.selected_data_item.uuid))
        logging.debug(lines)
        if self.console:
            self.console.insert_lines(lines)

    # receive files into the document model. data_group and index can optionally
    # be specified. if data_group is specified, the item is added to an arbitrary
    # position in the document model (the end) and at the group at the position
    # specified by the index. if the data group is not specified, the item is added
    # at the index within the document model.
    def receive_files(self, file_paths, data_group=None, index=-1, external=False, threaded=True, completion_fn=None):

        # this function will be called on a thread to receive files in the background.
        def receive_files_on_thread(file_paths, data_group, index, external, completion_fn):

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
                        data_items = ImportExportManager.ImportExportManager().read_data_items(self.ui, file_path,
                                                                                               external=external)

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

                            # grab a data ref
                            for data_item in data_items:
                                data_item.increment_data_ref_count()

                            def insert_data_item(_document_model, _data_group, _data_items, index_ref):
                                if _data_group and isinstance(_data_group, DataGroup.DataGroup):
                                    for data_item in _data_items:
                                        _document_model.append_data_item(data_item)
                                        if index_ref.value >= 0:
                                            _data_group.insert_data_item(index_ref.grab(), data_item)
                                        else:
                                            _data_group.append_data_item(data_item)
                                else:  # insert into document model only
                                    for data_item in _data_items:
                                        if index_ref.value >= 0:
                                            _document_model.insert_data_item(index_ref.grab(), data_item)
                                        else:
                                            _document_model.append_data_item(data_item)

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
                                    data_item.master_data_save_event.wait()
                                else:
                                    while not data_item.master_data_save_event.wait(0.05):
                                        self.periodic()
                                data_item.decrement_data_ref_count()

                            received_data_items.extend(data_items)

                    except Exception as e:
                        logging.debug("Could not read image %s", file_path)
                        traceback.print_exc()
                        logging.debug("Error: %s", e)

                task.update_progress(_("Finishing importing."), (len(file_paths), len(file_paths)))

                if completion_fn:
                    completion_fn(received_data_items)

                return received_data_items

        if threaded:
            threading.Thread(target=receive_files_on_thread, args=(file_paths, data_group, index, external, completion_fn)).start()
            return None
        else:
            return receive_files_on_thread(file_paths, data_group, index, external, completion_fn)

    # this helps avoid circular imports
    def create_selected_data_item_binding(self):
        return SelectedDataItemBinding(self)


# binding to the selected data item in the document controller
# the selected data item may be in an image panel, in the data panel,
# or in another user interface element. the document controller will
# send selected_data_item_changed when the data item changes.
# this object will listen to the data item to know when its data
# changes or when it gets deleted.
class SelectedDataItemBinding(DataItem.DataItemBinding):

    def __init__(self, document_controller):
        super(SelectedDataItemBinding, self).__init__()
        self.document_controller = document_controller
        # connect self as listener. this will result in calls to selected_data_item_changed
        self.document_controller.add_listener(self)
        self.notify_data_item_binding_data_item_changed(document_controller.selected_data_item)
        self.__data_item = None

    def close(self):
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # disconnect data item
        if self.__data_item:
            self.__data_item.remove_ref()
            self.__data_item.remove_listener(self)
        # super
        super(SelectedDataItemBinding, self).close()

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_data_item_changed(self, data_item):
        if data_item != self.__data_item:
            if data_item:
                data_item.add_ref()
                data_item.add_listener(self)
            self.notify_data_item_binding_data_item_changed(data_item)
            if self.__data_item:
                self.__data_item.remove_ref()
                self.__data_item.remove_listener(self)
            self.__data_item = data_item

    def data_item_content_changed(self, data_item, changes):
        if data_item == self.__data_item:
            self.selected_data_item_content_changed(data_item, changes)

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_data_item_content_changed(self, data_item, changes):
        self.notify_data_item_binding_data_item_content_changed(data_item, changes)
