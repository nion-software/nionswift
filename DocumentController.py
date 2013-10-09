# standard libraries
import gettext
import logging
import Queue
import random
import weakref

# third party libraries
# None

# local libraries
from nion.swift.Decorators import queue_main_thread
from nion.swift.Decorators import queue_main_thread_sync
from nion.swift import DataGroup
from nion.swift import DataItem
from nion.swift import DocumentModel
from nion.swift import Graphics
from nion.swift import Image
from nion.swift import Operation
from nion.swift import Workspace

_ = gettext.gettext


class DocumentController(object):

    # document_window is passed from the application container.
    # the next method to be called will be initialize.
    def __init__(self, ui, document_model, _create_workspace=True):
        super(DocumentController, self).__init__()
        self.ui = ui
        self.document_model = document_model
        self.document_model.add_ref()
        self.document_window = self.ui.create_document_window()
        self.document_window.on_periodic = lambda: self.periodic()
        self.document_window.on_about_to_close = lambda: self.close()
        self.workspace = None
        self.__weak_listeners = []
        self.__weak_image_panels = []
        self.__weak_selected_image_panel = None
        self.__cursor_weak_listeners = []
        self.delay_queue = Queue.Queue()
        self.create_menus()
        if _create_workspace:  # used only when testing reference counting
            self.workspace = Workspace.Workspace(self)

    def __del__(self):
        # There should not be listeners or references at this point.
        assert len(self.__weak_listeners) == 0, 'DocumentController still has listeners'

    def close(self):
        # recognize when we're running as test and finish out periodic operations
        if not self.document_window.has_event_loop:
            self.periodic()
        for image_panel in [weak_image_panel() for weak_image_panel in self.__weak_image_panels]:
            image_panel.close()
        self.document_window = None
        if self.workspace:
            self.workspace.close()
        self.document_model.remove_ref()
        self.notify_listeners("document_controller_did_close", self)

    # Add a listener. Listeners will receive data_item_changed message when this
    # DataItem is notified of a change via the notify_data_item_changed() method.
    def add_listener(self, listener):
        assert listener is not None
        self.__weak_listeners.append(weakref.ref(listener))

    # Remove a listener.
    def remove_listener(self, listener):
        assert listener is not None
        self.__weak_listeners.remove(weakref.ref(listener))

    # Return a copy of listeners array
    def get_weak_listeners(self):
        return self.__weak_listeners  # TODO: Return a copy
    def __get_listeners(self):
        return [weak_listener() for weak_listener in self.__weak_listeners]
    listeners = property(__get_listeners)

    # Send a message to the listeners
    def notify_listeners(self, fn, *args, **keywords):
        for listener in self.listeners:
            if hasattr(listener, fn):
                getattr(listener, fn)(*args, **keywords)

    def create_menus(self):

        self.file_menu = self.document_window.add_menu(_("File"))

        self.edit_menu = self.document_window.add_menu(_("Edit"))

        self.processing_menu = self.document_window.add_menu(_("Processing"))

        self.layout_menu = self.document_window.add_menu(_("Layout"))

        self.graphic_menu = self.document_window.add_menu(_("Graphic"))

        self.window_menu = self.document_window.add_menu(_("Window"))

        self.help_menu = self.document_window.add_menu(_("Help"))

        self.new_action = self.file_menu.add_menu_item(_("New"), lambda: self.new_window(), key_sequence="new")
        self.open_action = self.file_menu.add_menu_item(_("Open"), lambda: self.no_operation(), key_sequence="open")
        self.close_action = self.file_menu.add_menu_item(_("Close"), lambda: self.document_window.close(), key_sequence="close")
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

    def periodic(self):
        # perform any pending operations
        while not self.delay_queue.empty():
            try:
                task = self.delay_queue.get(False)
            except Queue.Empty:
                pass
            else:
                task()
                self.delay_queue.task_done()

    # TODO: get rid of this. it is used in HardwareSource.py and this functionality
    # should be thread safe by default.
    @queue_main_thread_sync
    def add_data_item_on_main_thread(self, data_group, data_item):
        data_group.data_items.append(data_item)

    @queue_main_thread
    def select_data_item(self, data_group, data_item):
        self.selected_image_panel.data_panel_selection = DataItem.DataItemSpecifier(data_group, data_item)

    # TODO: get rid of this
    @queue_main_thread_sync
    def remove_data_item_on_main_thread(self, data_group, data_item):
        data_group.data_items.remove(data_item)

    # TODO: move this to document model once document model is thread safe
    def sync_channels_to_data_items(self, channels, data_group, prefix):
        data_item_set = {}
        for channel in channels:
            data_item_name = "%s.%s" % (prefix, channel)
            # only use existing data item if it has a data buffer that matches
            data_item = DataGroup.get_data_item_in_container_by_title(data_group, data_item_name)
            if not data_item:
                data_item = DataItem.DataItem()
                data_item.title = data_item_name
                # the following function call needs to happen on the main thread,
                # but it also needs to be synchronized to finish before returning
                # from this method. add_data_item_on_main_thread does that.
                self.add_data_item_on_main_thread(data_group, data_item)
            data_item_set[channel] = data_item
        return data_item_set

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
                image_panel.set_focused(image_panel == self.selected_image_panel)

            # notify listeners that the selected image panel has changed.
            self.notify_listeners("selected_image_panel_changed", selected_image_panel)

            # notify listeners that the data item has changed. some listeners will be just interested
            # in the data item itself, not the group/data item combo.
            selected_data_item = selected_image_panel.data_item if selected_image_panel else None
            self.notify_listeners("selected_data_item_changed", selected_data_item, {"property": "panel"})
    selected_image_panel = property(__get_selected_image_panel, __set_selected_image_panel)

    def __get_selected_data_item(self):
        selected_image_panel = self.selected_image_panel
        return selected_image_panel.data_item if selected_image_panel else None
    selected_data_item = property(__get_selected_data_item)

    def data_panel_selection_changed_from_image_panel(self, data_panel_selection):
        self.notify_listeners("data_panel_selection_changed_from_image_panel", data_panel_selection)

    # this message comes from the selected image panel. the connection is established
    # in __set_selected_image_panel via a call to ImagePanel.addListener.
    def image_panel_data_item_changed(self, image_panel, info):
        data_item = image_panel.data_item if image_panel else None
        self.notify_listeners("selected_data_item_changed", data_item, info)

    def new_window(self):
        # hack to work around Application <-> DocumentController interdependency.
        self.notify_listeners("create_document_controller", self.document_model)

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
        color_image_source.master_data = Image.createColor((512, 512), 128, 255, 128)
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

    def add_processing_operation(self, operation, prefix=None, suffix=None, in_place=False):
        data_panel_selection = self.selected_image_panel.data_panel_selection if self.selected_image_panel else None
        data_item = data_panel_selection.data_item if data_panel_selection else None
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            if in_place:  # in place?
                data_item.operations.append(operation)
            else:
                new_data_item = DataItem.DataItem()
                new_data_item.title = (prefix if prefix else "") + str(data_item) + (suffix if suffix else "")
                new_data_item.operations.append(operation)
                data_item.data_items.append(new_data_item)
                self.selected_image_panel.data_panel_selection = DataItem.DataItemSpecifier(data_panel_selection.data_group, new_data_item)

    def processing_fft(self):
        self.add_processing_operation(Operation.FFTOperation(), prefix=_("FFT of "))

    def processing_ifft(self):
        self.add_processing_operation(Operation.IFFTOperation(), prefix=_("Inverse FFT of "))

    def processing_gaussian_blur(self):
        self.add_processing_operation(Operation.GaussianBlurOperation(), prefix=_("Gaussian Blur of "))

    def processing_resample(self):
        self.add_processing_operation(Operation.Resample2dOperation(), prefix=_("Resample of "))

    def processing_histogram(self):
        self.add_processing_operation(Operation.HistogramOperation(), prefix=_("Histogram of "))

    def processing_crop(self):
        data_panel_selection = self.selected_image_panel.data_panel_selection if self.selected_image_panel else None
        data_item = data_panel_selection.data_item if data_panel_selection else None
        if data_item:
            operation = Operation.Crop2dOperation()
            graphic = Graphics.RectangleGraphic()
            graphic.bounds = ((0.25,0.25), (0.5,0.5))
            data_item.graphics.append(graphic)
            operation.graphic = graphic
            self.add_processing_operation(operation, prefix=_("Crop of "))

    def processing_line_profile(self):
        data_panel_selection = self.selected_image_panel.data_panel_selection if self.selected_image_panel else None
        data_item = data_panel_selection.data_item if data_panel_selection else None
        if data_item:
            operation = Operation.LineProfileOperation()
            graphic = Graphics.LineGraphic()
            graphic.start = (0.25,0.25)
            graphic.end = (0.75,0.75)
            data_item.graphics.append(graphic)
            operation.graphic = graphic
            self.add_processing_operation(operation, prefix=_("Line Profile of "))

    def processing_invert(self):
        self.add_processing_operation(Operation.InvertOperation(), suffix=_(" Inverted"))

    def processing_duplicate(self):
        data_item = self.selected_data_item
        if data_item:
            new_data_item = DataItem.DataItem()
            new_data_item.title = _("Clone of ") + str(data_item)
            data_item.data_items.append(new_data_item)

    def processing_snapshot(self):
        data_item = self.selected_data_item
        if data_item:
            assert isinstance(data_item, DataItem.DataItem)
            data_item_copy = data_item.copy()
            data_item_copy.title = _("Copy of ") + str(data_item_copy)
            self.document_model.default_data_group.data_items.append(data_item_copy)

    def processing_convert_to_scalar(self):
        self.add_processing_operation(Operation.ConvertToScalarOperation(), suffix=_(" Gray"))

    def add_custom_processing_operation(self, data_item, fn, title=None):
        class ZOperation(Operation.Operation):
            def __init__(self, fn):
                description = []
                Operation.Operation.__init__(self, title if title else _("Processing"), description)
                self.fn = fn
            def process_data_copy(self, data_array):
                return self.fn(data_array)
        self.add_processing_operation(ZOperation(fn))
