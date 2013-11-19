# standard libraries
import copy
import gettext
import logging
import Queue
import random
import threading
import time
import weakref

# third party libraries
# None

# local libraries
from nion.swift.Decorators import queue_main_thread
from nion.swift.Decorators import queue_main_thread_sync
from nion.swift.Decorators import timeit
from nion.swift import DataGroup
from nion.swift import DataItem
from nion.swift import DocumentModel
from nion.swift import Graphics
from nion.swift import Image
from nion.swift import ImportExportManager
from nion.swift import Operation
from nion.swift import Storage
from nion.swift import Task
from nion.swift import Workspace

_ = gettext.gettext


class DocumentController(Storage.Broadcaster):

    # document_window is passed from the application container.
    # the next method to be called will be initialize.
    def __init__(self, ui, document_model, workspace_id=None):
        super(DocumentController, self).__init__()
        self.ui = ui
        self.document_model = document_model
        self.document_model.add_ref()
        self.document_window = self.ui.create_document_window()
        self.document_window.on_periodic = lambda: self.periodic()
        self.document_window.on_about_to_show = lambda: self.about_to_show()
        self.document_window.on_about_to_close = lambda geometry, state: self.about_to_close(geometry, state)
        self.workspace = None
        self.__weak_image_panels = []
        self.__weak_selected_image_panel = None
        self.weak_data_panel = None
        self.__cursor_weak_listeners = []
        self.__delay_queue = Queue.Queue()
        self.__delay_queue_mutex = threading.RLock()
        self.console = None
        self.create_menus()
        if workspace_id:  # used only when testing reference counting
            self.workspace = Workspace.Workspace(self, workspace_id)

    def close(self):
        # recognize when we're running as test and finish out periodic operations
        if not self.document_window.has_event_loop:
            self.periodic()
        # close the workspace before closing the image panels, to save their position
        if self.workspace:
            self.workspace.close()
        for image_panel in [weak_image_panel() for weak_image_panel in self.__weak_image_panels]:
            image_panel.close()
        self.document_window = None
        self.document_model.remove_ref()
        self.window_menu.on_about_to_show = None
        self.notify_listeners("document_controller_did_close", self)

    def about_to_show(self):
        geometry, state = self.workspace.restore_geometry_state()
        self.document_window.restore(geometry, state)

    def about_to_close(self, geometry, state):
        self.workspace.save_geometry_state(geometry, state)
        self.close()

    def register_console(self, console):
        self.console = console

    def unregister_console(self, console):
        self.console = None

    def create_menus(self):

        self.file_menu = self.document_window.add_menu(_("File"))

        self.edit_menu = self.document_window.add_menu(_("Edit"))

        self.processing_menu = self.document_window.add_menu(_("Processing"))

        self.layout_menu = self.document_window.add_menu(_("Layout"))

        self.graphic_menu = self.document_window.add_menu(_("Graphic"))

        self.window_menu = self.document_window.add_menu(_("Window"))

        self.help_menu = self.document_window.add_menu(_("Help"))

        self.new_action = self.file_menu.add_menu_item(_("New"), lambda: self.new_window("library"), key_sequence="new")
        self.open_action = self.file_menu.add_menu_item(_("Open"), lambda: self.no_operation(), key_sequence="open")
        self.close_action = self.file_menu.add_menu_item(_("Close"), lambda: self.document_window.close(), key_sequence="close")
        self.file_menu.add_separator()
        self.import_action = self.file_menu.add_menu_item(_("Import..."), lambda: self.import_file())
        self.export_action = self.file_menu.add_menu_item(_("Export..."), lambda: self.export_file())
        self.file_menu.add_separator()
        self.save_action = self.file_menu.add_menu_item(_("Save"), lambda: self.no_operation(), key_sequence="save")
        self.save_as_action = self.file_menu.add_menu_item(_("Save As..."), lambda: self.no_operation(), key_sequence="save-as")
        self.file_menu.add_separator()
        self.add_smart_group_action = self.file_menu.add_menu_item(_("Add Smart Group"), lambda: self.add_smart_group(), key_sequence="Ctrl+Alt+N")
        self.add_group_action = self.file_menu.add_menu_item(_("Add Group"), lambda: self.add_group(), key_sequence="Ctrl+Shift+N")
        self.add_green_action = self.file_menu.add_menu_item(_("Add Green"), lambda: self.add_green_data_item(), key_sequence="Ctrl+Shift+G")
        self.file_menu.add_separator()
        self.quit_action = self.file_menu.add_menu_item(_("Exit"), lambda: self.ui.close(), key_sequence="quit", role="quit")

        self.undo_action = self.edit_menu.add_menu_item(_("Undo"), lambda: self.no_operation(), key_sequence="undo")
        self.redo_action = self.edit_menu.add_menu_item(_("Redo"), lambda: self.no_operation(), key_sequence="redo")
        self.edit_menu.add_separator()
        self.cut_action = self.edit_menu.add_menu_item(_("Cut"), lambda: self.no_operation(), key_sequence="cut")
        self.copy_action = self.edit_menu.add_menu_item(_("Copy"), lambda: self.no_operation(), key_sequence="copy")
        self.paste_action = self.edit_menu.add_menu_item(_("Paste"), lambda: self.no_operation(), key_sequence="paste")
        self.delete_action = self.edit_menu.add_menu_item(_("Delete"), lambda: self.no_operation(), key_sequence="delete")
        self.select_all_action = self.edit_menu.add_menu_item(_("Select All"), lambda: self.no_operation(), key_sequence="select-all")
        self.edit_menu.add_separator()
        self.script_action = self.edit_menu.add_menu_item(_("Script"), lambda: self.prepare_data_item_script(), key_sequence="Ctrl+Shift+K")
        self.edit_menu.add_separator()
        self.properties_action = self.edit_menu.add_menu_item(_("Properties..."), lambda: self.no_operation(), role="preferences")

        self.processing_menu.add_menu_item(_("FFT"), lambda: self.processing_fft(), key_sequence="Ctrl+F")
        self.processing_menu.add_menu_item(_("Inverse FFT"), lambda: self.processing_ifft(), key_sequence="Ctrl+Shift+F")
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
        self.layout_menu.add_menu_item(_("Layout 1x1"), lambda: self.workspace.change_layout("1x1"), key_sequence="Ctrl+1")
        self.layout_menu.add_menu_item(_("Layout 2x1"), lambda: self.workspace.change_layout("2x1"), key_sequence="Ctrl+2")
        self.layout_menu.add_menu_item(_("Layout 3x1"), lambda: self.workspace.change_layout("3x1"), key_sequence="Ctrl+3")
        self.layout_menu.add_menu_item(_("Layout 2x2"), lambda: self.workspace.change_layout("2x2"), key_sequence="Ctrl+4")
        self.layout_menu.add_menu_item(_("Layout 1x2"), lambda: self.workspace.change_layout("1x2"), key_sequence="Ctrl+5")

        # these are temporary menu items, so don't need to assign them to variables, for now
        self.graphic_menu.add_menu_item(_("Add Line Graphic"), lambda: self.add_line_graphic())
        self.graphic_menu.add_menu_item(_("Add Ellipse Graphic"), lambda: self.add_ellipse_graphic())
        self.graphic_menu.add_menu_item(_("Add Rectangle Graphic"), lambda: self.add_rectangle_graphic())
        self.graphic_menu.add_menu_item(_("Remove Graphic"), lambda: self.remove_graphic())

        self.help_action = self.help_menu.add_menu_item(_("Help"), lambda: self.no_operation(), key_sequence="help")
        self.about_action = self.help_menu.add_menu_item(_("About"), lambda: self.no_operation(), role="about")

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

    def __get_panels(self):
        if self.workspace:
            return [dock_widget.panel for dock_widget in self.workspace.dock_widgets]
        return []
    panels = property(__get_panels)

    delay_queue = property(lambda self: self)

    def queue_main_thread_task(self, task):
        with self.__delay_queue_mutex:
            self.__delay_queue.put(task)

    #@timeit
    def periodic(self):
        # perform any pending operations
        with self.__delay_queue_mutex:
            qsize = self.__delay_queue.qsize()
        while not self.__delay_queue.empty() and qsize > 0:
            try:
                task = self.__delay_queue.get(False)
            except Queue.Empty:
                pass
            else:
                task()
                self.__delay_queue.task_done()
            qsize -= 1
        for panel in self.panels:
            if hasattr(panel, "periodic"):
                start = time.time()
                panel.periodic()
                elapsed = time.time() - start
                if elapsed > 0.05:
                    logging.debug("panel %s %s", panel, elapsed)
                    pass

    @queue_main_thread
    def select_data_item(self, data_group, data_item):
        self.selected_image_panel.data_panel_selection = DataItem.DataItemSpecifier(data_group, data_item)

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
        if not selected_image_panel:
            selected_image_panel = self.workspace.primary_image_panel
        weak_selected_image_panel = weakref.ref(selected_image_panel) if selected_image_panel else None
        if weak_selected_image_panel != self.__weak_selected_image_panel:

            # first un-listen to the old selected panel, if any
            old_selected_image_panel = self.__weak_selected_image_panel() if self.__weak_selected_image_panel else None
            if old_selected_image_panel:
                old_selected_image_panel.remove_listener(self)

            # save the selected panel
            self.__weak_selected_image_panel = weak_selected_image_panel

            # now listen to the new selected panel, if any.
            # this will result in calls to image_panel_data_item_changed.
            if selected_image_panel:
                selected_image_panel.add_listener(self)

            # iterate through the image panels and update their 'focused' property
            for image_panel in [weak_image_panel() for weak_image_panel in self.__weak_image_panels]:
                image_panel.set_selected(image_panel == self.selected_image_panel)

            # notify listeners that the selected image panel has changed.
            self.notify_listeners("selected_image_panel_changed", selected_image_panel)

            # notify listeners that the data item has changed. some listeners will be just interested
            # in the data item itself, not the group/data item combo.
            selected_data_item = selected_image_panel.data_item if selected_image_panel else None
            self.notify_listeners("selected_data_item_changed", selected_data_item, set([DataItem.PANEL]))
    selected_image_panel = property(__get_selected_image_panel, __set_selected_image_panel)

    def __get_selected_data_panel_selection(self):
        data_panel_selection = None
        # first check focused data panel
        if self.weak_data_panel:
            data_panel = self.weak_data_panel()
            if data_panel and data_panel.focused:
                data_panel_selection = data_panel._get_data_panel_selection()
        # if not found, check for focused or selected image panel
        if not data_panel_selection and self.selected_image_panel:
            data_panel_selection = self.selected_image_panel.data_panel_selection
        return data_panel_selection
    selected_data_panel_selection = property(__get_selected_data_panel_selection)

    def __get_selected_data_item(self):
        selected_data_panel_selection = self.selected_data_panel_selection
        return selected_data_panel_selection.data_item if selected_data_panel_selection else None
    selected_data_item = property(__get_selected_data_item)

    def data_panel_selection_changed_from_image_panel(self, data_panel_selection):
        self.notify_listeners("data_panel_selection_changed_from_image_panel", data_panel_selection)

    # this message comes from the selected image panel. the connection is established
    # in __set_selected_image_panel via a call to ImagePanel.addListener.
    # this message can mean that the data itself changed, a property changed, a source
    # changed, or the data item displayed in the image panel changed.
    def image_panel_data_item_changed(self, image_panel, changes):
        data_item = image_panel.data_item if image_panel else None
        self.notify_listeners("selected_data_item_changed", data_item, changes)

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
        for path in paths:
            data_items = ImportExportManager.ImportExportManager().read(self.ui, path)
            for data_item in data_items:
                self.document_model.default_data_group.data_items.append(data_item)

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
            return ImportExportManager.ImportExportManager().write(self.ui, data_item, path)

    # this method creates a task. it is thread safe.
    def create_task_context_manager(self, title, task_type):
        task = Task.Task(title, task_type)
        task_context_manager = Task.TaskContextManager(self, task)
        self.notify_listeners("task_created", task)
        return task_context_manager

    def add_smart_group(self):
        smart_data_group = DataGroup.SmartDataGroup()
        smart_data_group.title = _("Untitled Smart Group")
        self.document_model.data_groups.insert(0, smart_data_group)

    def add_group(self):
        data_group = DataGroup.DataGroup()
        data_group.title = _("Untitled Group")
        self.document_model.data_groups.insert(0, data_group)

    def remove_data_group_from_container(self, data_group, container):
        data_group_empty = isinstance(data_group, DataGroup.SmartDataGroup) or (len(data_group.data_items) == 0 and len(data_group.data_groups) == 0)
        if data_group_empty:
            assert data_group in container.data_groups
            container.data_groups.remove(data_group)

    def add_green_data_item(self):
        color_image_source = DataItem.DataItem()
        color_image_source.title = "Green " + str(random.randint(1,1000000))
        with color_image_source.create_data_accessor() as data_accessor:
            data_accessor.master_data = Image.create_color_image((512, 512), 128, 255, 128)
        self.document_model.default_data_group.data_items.append(color_image_source)

    def add_line_graphic(self):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            graphic = Graphics.LineGraphic()
            graphic.start = (0.2,0.2)
            graphic.end = (0.8,0.8)
            data_item.graphics.append(graphic)
            self.selected_image_panel.graphic_selection.set(data_item.graphics.index(graphic))

    def add_rectangle_graphic(self):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            data_item.graphics.append(graphic)
            self.selected_image_panel.graphic_selection.set(data_item.graphics.index(graphic))

    def add_ellipse_graphic(self):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            graphic = Graphics.EllipseGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            data_item.graphics.append(graphic)
            self.selected_image_panel.graphic_selection.set(data_item.graphics.index(graphic))

    def remove_graphic(self):
        data_item = self.selected_data_item
        if data_item and self.selected_image_panel.graphic_selection.has_selection():
            graphics = [data_item.graphics[index] for index in self.selected_image_panel.graphic_selection.indexes]
            for graphic in graphics:
                data_item.graphics.remove(graphic)

    def remove_operation(self, operation):
        data_item = self.selected_data_item
        if data_item:
            data_item.operations.remove(operation)

    def add_processing_operation(self, data_panel_selection, operation, prefix=None, suffix=None, in_place=False, select=True):
        data_item = data_panel_selection.data_item if data_panel_selection else None
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            if in_place:  # in place?
                data_item.operations.append(operation)
                return data_item
            else:
                new_data_item = DataItem.DataItem()
                new_data_item.title = (prefix if prefix else "") + str(data_item) + (suffix if suffix else "")
                new_data_item.operations.append(operation)
                data_item.data_items.append(new_data_item)
                if select:
                    # incorrect usage of 'data_panel_selection_changed_from_image_panel', fix later
                    self.data_panel_selection_changed_from_image_panel(DataItem.DataItemSpecifier(data_panel_selection.data_group, new_data_item))
                    #self.selected_image_panel.data_panel_selection = DataItem.DataItemSpecifier(data_panel_selection.data_group, new_data_item)
                return new_data_item
        return None

    def processing_fft(self, select=True):
        return self.add_processing_operation(self.selected_data_panel_selection, Operation.FFTOperation(), prefix=_("FFT of "), select=select)

    def processing_ifft(self, select=True):
        return self.add_processing_operation(self.selected_data_panel_selection, Operation.IFFTOperation(), prefix=_("Inverse FFT of "), select=select)

    def processing_gaussian_blur(self, select=True):
        return self.add_processing_operation(self.selected_data_panel_selection, Operation.GaussianBlurOperation(), prefix=_("Gaussian Blur of "), select=select)

    def processing_resample(self, select=True):
        return self.add_processing_operation(self.selected_data_panel_selection, Operation.Resample2dOperation(), prefix=_("Resample of "), select=select)

    def processing_histogram(self, select=True):
        return self.add_processing_operation(self.selected_data_panel_selection, Operation.HistogramOperation(), prefix=_("Histogram of "), select=select)

    def processing_crop(self, select=True):
        data_panel_selection = self.selected_data_panel_selection
        data_item = data_panel_selection.data_item if data_panel_selection else None
        if data_item:
            operation = Operation.Crop2dOperation()
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            data_item.graphics.append(graphic)
            operation.graphic = graphic
            return self.add_processing_operation(data_panel_selection, operation, prefix=_("Crop of "), select=select)

    def processing_line_profile(self, select=True):
        data_panel_selection = self.selected_data_panel_selection
        data_item = data_panel_selection.data_item if data_panel_selection else None
        if data_item:
            operation = Operation.LineProfileOperation()
            graphic = Graphics.LineGraphic()
            graphic.start = (0.25,0.25)
            graphic.end = (0.75,0.75)
            data_item.graphics.append(graphic)
            operation.graphic = graphic
            return self.add_processing_operation(data_panel_selection, operation, prefix=_("Line Profile of "), select=select)
        return None

    def processing_invert(self, select=True):
        return self.add_processing_operation(self.selected_data_panel_selection, Operation.InvertOperation(), suffix=_(" Inverted"), select=select)

    def processing_duplicate(self, select=True):
        data_item = self.selected_data_item
        if data_item:
            new_data_item = DataItem.DataItem()
            new_data_item.title = _("Clone of ") + str(data_item)
            data_item.data_items.append(new_data_item)
            return new_data_item
        return None

    def processing_snapshot(self, select=True):
        data_panel_selection = self.selected_data_panel_selection
        data_item = data_panel_selection.data_item if data_panel_selection else None
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            data_item_copy = copy.deepcopy(data_item)
            data_item_copy.title = _("Copy of ") + str(data_item_copy)
            data_panel_selection.data_group.data_items.append(data_item_copy)
            return data_item_copy
        return None

    def processing_convert_to_scalar(self, select=True):
        return self.add_processing_operation(self.selected_data_panel_selection, Operation.ConvertToScalarOperation(), suffix=_(" Gray"), select=select)

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


# binding to the selected data item in the document controller
class SelectedDataItemBinding(DataItem.DataItemBinding):

    def __init__(self, document_controller):
        super(SelectedDataItemBinding, self).__init__()
        self.document_controller = document_controller
        # connect self as listener. this will result in calls to selected_data_item_changed
        self.document_controller.add_listener(self)
        self.notify_data_item_changed(document_controller.selected_data_item)

    def close(self):
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        super(SelectedDataItemBinding, self).close()

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_data_item_changed(self, data_item, changes):
        self.notify_data_item_changed(data_item)
