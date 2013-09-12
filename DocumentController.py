# standard libraries
import collections
import copy
import gettext
import logging
import numbers
import os
import Queue
import random
import threading
import uuid
import weakref

# third party libraries
import scipy

# local libraries
from nion.swift.Decorators import queue_main_thread
from nion.swift.Decorators import queue_main_thread_sync
from nion.swift.Decorators import relative_file
from nion.swift.Decorators import singleton
from nion.swift import DataGroup
from nion.swift import DataItem
from nion.swift import DataPanel
from nion.swift import Graphics
from nion.swift import Image
from nion.swift import ImagePanel
from nion.swift import Inspector
from nion.swift import Menu
from nion.swift import Operation
from nion.swift import Panel
from nion.swift import Storage
from nion.swift import UserInterface
from nion.swift import Workspace

_ = gettext.gettext


class DocumentController(Storage.StorageBase):

    # document_window is passed from the application container.
    # the next method to be called will be initialize.
    def __init__(self, application, document_window, storage_writer, storage_reader=None, _create_workspace=True):
        super(DocumentController, self).__init__()
        self.__weak_application = weakref.ref(application)
        self.ui = application.ui
        self.document_window = document_window
        self.menu_manager = Menu.MenuManager(self.ui)  # used only on Windows
        self.workspace = None
        self.__weak_image_panels = []
        self.__weak_selected_image_panel = None
        self.__cursor_weak_listeners = []
        self.__counted_data_items = collections.Counter()
        self.delay_queue = Queue.Queue()
        self.storage_writer = storage_writer
        self.storage_relationships += ["data_groups"]
        self.storage_type = "document"
        self.data_groups = Storage.MutableRelationship(self, "data_groups")
        self.application.register_document_window(self)
        if storage_reader:
            storage_writer.disconnected = True
            need_rewrite = self.read(storage_reader)
            storage_writer.disconnected = False
            # the structure of the document might have changed; rewrite
            # TODO: formalized db migration
            if need_rewrite:
                logging.debug("Rewriting database")
                self.rewrite()
        else:
            storage_writer.set_root(self)
            self.write()
        if _create_workspace:  # used only when testing reference counting
            self.workspace = Workspace.Workspace(self)
            self.selected_image_panel = None  # this has the effect of setting default image panel

    def __get_application(self):
        return self.__weak_application()
    application = property(__get_application)
    app = property(__get_application)

    def close(self):
        # this isn't ideal since this effectively binds one workspace per document window.
        # TODO: revisit Workspace vs. DocumentController lifetimes
        if self.workspace:
            self.workspace.close()
        self.storage_writer.disconnected = True
        for data_group in copy.copy(self.data_groups):
            self.data_groups.remove(data_group)
        self.application.unregister_document_window(self)

    def reset(self, storage_writer):
        for data_group in copy.copy(self.data_groups):
            self.data_groups.remove(data_group)
        assert len(self.data_groups) == 0
        self.workspace.reset()
        self.storage_writer = storage_writer
        self.storage_writer.set_root(self)
        self.write()

    def read(self, storage_reader):
        need_rewrite = False
        parent_node, uuid = storage_reader.find_root_node("document")
        self._set_uuid(uuid)
        data_groups = storage_reader.get_items(parent_node, "data_groups")
        self.data_groups.extend(data_groups)
        if len(self.data_groups) == 0:
            data_group = DataGroup.DataGroup()
            data_group.title = _("Data")
            self.data_groups.append(data_group)
            need_rewrite = True
        if storage_reader.has_relationship(parent_node, "data_items"):
            data_items = storage_reader.get_items(parent_node, "data_items")
            self.default_data_group.data_items.extend(data_items)
            need_rewrite = True
        return need_rewrite

    def create_default_data_groups(self):
        # ensure there is at least one group
        if len(self.data_groups) < 1:
            data_group = DataGroup.DataGroup()
            data_group.title = _("Library")
            self.data_groups.append(data_group)

    def create_test_images(self):
        # for testing, add a checkerboard image data item
        checkerboard_image_source = DataItem.DataItem()
        checkerboard_image_source.title = "Checkerboard"
        checkerboard_image_source.master_data = Image.createCheckerboard((512, 512))
        self.default_data_group.data_items.append(checkerboard_image_source)
        # for testing, add a color image data item
        color_image_source = DataItem.DataItem()
        color_image_source.title = "Green Color"
        color_image_source.master_data = Image.createColor((512, 512), 128, 255, 128)
        self.default_data_group.data_items.append(color_image_source)
        # for testing, add a color image data item
        lena_image_source = DataItem.DataItem()
        lena_image_source.title = "Lena"
        lena_image_source.master_data = scipy.misc.lena()
        self.default_data_group.data_items.append(lena_image_source)

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

    def __get_default_data_group(self):
        for data_group in self.data_groups:
            if isinstance(data_group, DataGroup.DataGroup):
                return data_group
        return None
    default_data_group = property(__get_default_data_group)

    # override from StorageBase.
    def notify_insert_item(self, key, value, before_index):
        super(DocumentController, self).notify_insert_item(key, value, before_index)
        if key == "data_groups":
            data_group = value
            self.update_counted_data_items(data_group.counted_data_items)
            # initialize data group with current set of data (used for smart data groups)
            if hasattr(data_group, "update_counted_data_items_for_filter"):
                data_group.update_counted_data_items_for_filter(self.counted_data_items)
    # override from StorageBase
    def notify_remove_item(self, key, value, index):
        super(DocumentController, self).notify_remove_item(key, value, index)
        if key == "data_groups":
            self.subtract_counted_data_items(value.counted_data_items)

    def __get_counted_data_items(self):
        return self.__counted_data_items
    counted_data_items = property(__get_counted_data_items)

    def update_counted_data_items(self, counted_data_items):
        self.__counted_data_items.update(counted_data_items)
        self.notify_parents("update_counted_data_items", counted_data_items)
        for data_group in self.data_groups:
            if hasattr(data_group, "update_counted_data_items_for_filter"):
                data_group.update_counted_data_items_for_filter(counted_data_items)
    def subtract_counted_data_items(self, counted_data_items):
        self.__counted_data_items.subtract(counted_data_items)
        self.__counted_data_items += collections.Counter()  # strip empty items
        self.notify_parents("subtract_counted_data_items", counted_data_items)
        for data_group in self.data_groups:
            if hasattr(data_group, "subtract_counted_data_items_for_filter"):
                data_group.subtract_counted_data_items_for_filter(counted_data_items)

    # watch for property changes to data items so that smart filters get updated.
    # tell any data groups to update their filter.
    def data_item_property_changed(self, data_item, property, value):
        self.notify_parents("data_item_property_changed", data_item, property, value)
        for data_group in self.data_groups:
            if hasattr(data_group, "adjust_data_item_for_filter"):
                data_group.adjust_data_item_for_filter(data_item, property, value)

    # TODO: what about thread safety for these classes?

    class _DataAccessorIter(object):
        def __init__(self, iter):
            self.iter = iter
        def __iter__(self):
            return self
        def next(self):
            data_item = self.iter.next()
            return data_item.image if data_item else None

    class DataAccessor(object):
        def __init__(self, document_controller):
            self.__document_controller_weakref = weakref.ref(document_controller)
        def __get_document_controller(self):
            return self.__document_controller_weakref()
        document_controller = property(__get_document_controller)
        # access by bracket notation
        def __len__(self):
            return self.document_controller.get_data_item_count()
        def __getitem__(self, key):
            data = self.document_controller.get_data_by_key(key)
            if data is None:
                raise KeyError
            return data
        def __setitem__(self, key, value):
            return self.document_controller.set_data_by_key(key, value)
        def __delitem__(self, key):
            data_item = self.document_controller.get_data_item_by_key(key)
            if data_item:
                self.document_controller.all_data_items.remove(data_item)
        def __iter__(self):
            return DocumentController._DataAccessorIter(self.document_controller.get_flat_data_item_generator())
        def uuid_keys(self):
            return [data_item.uuid for data_item in self.document_controller.data_items_by_key]
        def title_keys(self):
            return [str(data_item) for data_item in self.document_controller.data_items_by_key]
        def keys(self):
            return self.uuid_keys()

    # TODO: get rid of this. it is used in HardwareSource.py and this functionality
    # should be thread safe by default.
    @queue_main_thread_sync
    def add_data_item_on_main_thread(self, data_group, data_item):
        data_group.data_items.append(data_item)

    @queue_main_thread
    def select_data_item(self, data_group, data_item):
        self.selected_image_panel.data_panel_selection = DataPanel.DataItemSpecifier(data_group, data_item)

    # TODO: get rid of this
    @queue_main_thread_sync
    def remove_data_item_on_main_thread(self, data_group, data_item):
        data_group.data_items.remove(data_item)

    # Return a generator over all data items
    def get_flat_data_item_generator(self):
        return DataGroup.get_flat_data_item_generator_in_container(self)

    # Return a generator over all data groups
    def get_flat_data_group_generator(self):
        return DataGroup.get_flat_data_group_generator_in_container(self)

    def get_data_group_by_uuid(self, uuid):
        for data_group in DataGroup.get_flat_data_group_generator_in_container(self):
            if data_group.uuid == uuid:
                return data_group
        return None

    def get_data_item_count(self):
        return len(list(self.get_flat_data_item_generator()))

    # access data item by key (title, uuid, index)
    def get_data_item_by_key(self, key):
        if isinstance(key, numbers.Integral):
            return list(self.get_flat_data_item_generator())[key]
        if isinstance(key, uuid.UUID):
            return self.get_data_item_by_uuid(key)
        return self.get_data_item_by_title(str(key))
    def get_data_by_key(self, key):
        data_item = self.get_data_item_by_key(key)
        return data_item.image if data_item else None
    def set_data_by_key(self, key, data):
        data_item = self.get_data_item_by_key(key)
        if data_item:
            data_item.master_data = data
        else:
            if isinstance(key, numbers.Integral):
                raise IndexError
            if isinstance(key, uuid.UUID):
                raise KeyError
            data_item = DataItem.DataItem()
            data_item.title = str(key)
            data_item.master_data = data
            self.default_data_group.data_items.append(data_item)
        return data_item

    # access data items by title
    def get_data_item_by_title(self, title):
        for data_item in self.get_flat_data_item_generator():
            if str(data_item) == title:
                return data_item
        return None
    def get_data_by_title(self, title):
        data_item = self.get_data_item_by_title(title)
        return data_item.image if data_item else None
    def set_data_by_title(self, title, data):
        data_item = self.get_data_item_by_title(title)
        if data_item:
            data_item.data = data
        else:
            data_item = DataItem.DataItem()
            data_item.title = title
            data_item.master_data = data
            self.default_data_group.data_items.append(data_item)
        return data_item

    # access data items by index
    def get_data_item_by_index(self, index):
        return list(self.get_flat_data_item_generator())[index]
    def get_data_by_index(self, index):
        data_item = self.get_data_item_by_index(index)
        return data_item.image if data_item else None
    def set_data_by_index(self, index, data):
        data_item = self.get_data_item_by_index(index)
        if data_item:
            data_item.master_data = data
        else:
            raise IndexError
    def get_index_for_data_item(self, data_item):
        return list(self.get_flat_data_item_generator()).index(data_item)

    # access data items by uuid
    def get_data_item_by_uuid(self, uuid):
        for data_item in self.get_flat_data_item_generator():
            if data_item.uuid == uuid:
                return data_item
        return None
    def get_data_by_uuid(self, uuid):
        data_item = self.get_data_item_by_uuid(uuid)
        return data_item.image if data_item else None
    def set_data_by_uuid(self, uuid, data):
        data_item = self.get_data_item_by_uuid(uuid)
        if data_item:
            data_item.master_data = data
        else:
            raise KeyError

    def register_image_panel(self, image_panel):
        weak_image_panel = weakref.ref(image_panel)
        self.__weak_image_panels.append(weak_image_panel)

    def unregister_image_panel(self, image_panel):
        if self.selected_image_panel == image_panel:
            self.selected_image_panel = None
        weak_image_panel = weakref.ref(image_panel)
        self.__weak_image_panels.remove(weak_image_panel)

    def find_panel(self, panel_id):
        return self.workspace.find_panel(panel_id)

    def __get_selected_image_panel(self):
        return self.__weak_selected_image_panel() if self.__weak_selected_image_panel else None
    def __set_selected_image_panel(self, selected_image_panel):
        if not selected_image_panel:
            tab = self.find_panel("primary-image")
            selected_image_panel = tab.content if tab else None
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

    def addToolbarButton(self, id, title, callback):
        self.find_panel("button-list-panel").addButton(id, title, callback)
    def removeToolbarButton(self, id):
        self.find_panel("button-list-panel").removeButton(id)

    def add_smart_group(self):
        smart_data_group = DataGroup.SmartDataGroup()
        smart_data_group.title = _("Untitled Smart Group")
        self.data_groups.insert(0, smart_data_group)

    def add_group(self):
        data_group = DataGroup.DataGroup()
        data_group.title = _("Untitled Group")
        self.data_groups.insert(0, data_group)

    def remove_data_group_from_parent(self, data_group, parent):
        data_group_empty = isinstance(data_group, DataGroup.SmartDataGroup) or (len(data_group.data_items) == 0 and len(data_group.data_groups) == 0)
        if data_group_empty:
            assert data_group in parent.data_groups
            parent.data_groups.remove(data_group)

    def add_green_data_item(self):
        color_image_source = DataItem.DataItem()
        color_image_source.title = "Green " + str(random.randint(1,1000000))
        color_image_source.master_data = Image.createColor((512, 512), 128, 255, 128)
        self.default_data_group.data_items.append(color_image_source)

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
                self.selected_image_panel.data_panel_selection = DataPanel.DataItemSpecifier(data_panel_selection.data_group, new_data_item)

    def processing_fft(self):
        self.add_processing_operation(Operation.FFTOperation(), prefix=_("FFT of "))

    def processing_ifft(self):
        self.add_processing_operation(Operation.IFFTOperation(), prefix=_("Inverse FFT of "))

    def processing_gaussian_blur(self):
        self.add_processing_operation(Operation.GaussianBlurOperation(), prefix=_("Gaussian Blur of "))

    def processing_resample(self):
        self.add_processing_operation(Operation.ResampleOperation(), prefix=_("Resample of "))

    def processing_histogram(self):
        self.add_processing_operation(Operation.HistogramOperation(), prefix=_("Histogram of "))

    def processing_crop(self):
        data_panel_selection = self.selected_image_panel.data_panel_selection if self.selected_image_panel else None
        data_item = data_panel_selection.data_item if data_panel_selection else None
        if data_item:
            operation = Operation.CropOperation()
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
            self.default_data_group.data_items.append(data_item_copy)

    def add_custom_processing_operation(self, data_item, fn, title=None):
        class ZOperation(Operation.Operation):
            def __init__(self, fn):
                description = []
                Operation.Operation.__init__(self, title if title else _("Processing"), description)
                self.fn = fn
            def process_data_copy(self, data_array):
                return self.fn(data_array)
        self.add_processing_operation(ZOperation(fn))

    def test_storage_log(self):
        self.storage_writer.log()

    def test_storage_read(self):
        storage_reader = Storage.DictStorageReader()
        storage_reader.load_file("/Users/cmeyer/Developer/Nion/NionImaging/data.p")
        self.reset(Storage.DictStorageWriter())
        self.read(storage_reader)

    def test_storage_write(self):
        self.storage_writer.save_file("/Users/cmeyer/Developer/Nion/NionImaging/data.p")

    def test_storage_reset(self):
        self.reset(Storage.DictStorageWriter())
