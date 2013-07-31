# standard libraries
import gettext
import logging
import os
import random
import uuid
import weakref

# third party libraries
import numpy

# local libraries
import Application
import DataItem
from Decorators import queue_main_thread
from Decorators import relative_file
import DocumentController
import Image
import Panel
import UserInterface

_ = gettext.gettext


"""
    When the user changes image panels, the data panel must update itself to reflect what
    is selected in the image panel. It does this by receiving the selected_image_panel_changed
    message.

    When the user selects a new data item or group, the data panel must notify the selected
    image panel. It does this in the itemChanged method.
"""


# TODO: The selection will change when the user changes focused image panel
# TODO: If the user selects a different data item, it needs to be associated with focused image panel
# TODO: Data panel has two selections: a folder and a data item
# TODO: Each folder remembers its data item selection (or has an algorithm if selected item was deleted)
# TODO: User can delete items from just that folder (delete), or from all folders (shift-delete)
# TODO: Image panel should retain the folder/data item combination, not just the data item.
# TODO: User needs to be able to select folder. But what happens when they do?
#       What if image panel selection becomes just a folder, it displays a blank, but retains the selection
# TODO: What happens when a group/item selected in a different image panel is deleted?


# persistently store a data panel selection
class DataItemSpecifier(object):
    def __init__(self, data_group=None, data_item=None):
        self.__data_group = data_group
        self.__data_item = data_item
        self.__data_item_container = self.__search_container(data_item, data_group) if data_group and data_item else None
        assert data_item is None or data_item in self.__data_item_container.data_items
    def __get_data_group(self):
        return self.__data_group
    data_group = property(__get_data_group)
    def __get_data_item(self):
        return self.__data_item
    data_item = property(__get_data_item)
    def __search_container(self, data_item, container):
        if hasattr(container, "data_items"):
            if data_item in container.data_items:
                return container
            for child_data_item in container.data_items:
                child_container = self.__search_container(data_item, child_data_item)
                if child_container:
                    return child_container
        if hasattr(container, "data_groups"):
            for data_group in container.data_groups:
                child_container = self.__search_container(data_item, data_group)
                if child_container:
                    return child_container
        return None
    def __get_data_item_container(self):
        return self.__data_item_container
    data_item_container = property(__get_data_item_container)
    def __str__(self):
        return "(%s,%s)" % (str(self.data_group), str(self.data_item))


class DataPanel(Panel.Panel):

    # a tree model of the data groups
    class DataGroupModel(UserInterface.ItemModel):

        def __init__(self, document_controller, data_panel):
            super(DataPanel.DataGroupModel, self).__init__(document_controller, ["display", "edit"])
            self.document_controller.add_observer(self)
            self.mapping = {document_controller: self.root}
            self._index = -1
            self._parent_row = -1
            self._parent_id = 0
            self.__block_image_panel_update = False
            self.__weak_data_panel = weakref.ref(data_panel)
            # add items that already exist
            data_groups = document_controller.data_groups
            for index, data_group in enumerate(data_groups):
                self.item_inserted(document_controller, "data_groups", data_group, index)

        def close(self):
            # TODO: unlisten to everything
            self.document_controller.remove_observer(self)
            super(DataPanel.DataGroupModel, self).close()

        def log(self, parent_id=-1, indent=""):
            parent_id = parent_id if parent_id >= 0 else self.root.id
            for index, child in enumerate(self.itemFromId(parent_id).children):
                value = child.data["display"] if "display" in child.data else "---"
                logging.debug(indent + str(index) + ": (" + str(child.id) + ") " + value)
                self.log(child.id, indent + "  ")

        def __get_data_panel(self):
            return self.__weak_data_panel()
        data_panel = property(__get_data_panel)

        def __append_data_item_flat(self, container, data_items):
            if isinstance(container, DataItem.DataItem):
                data_items.append(container)
            for child_data_item in container.data_items:
                self.__append_data_item_flat(child_data_item, data_items)

        def __get_data_items_flat(self):
            data_items = []
            if self.data_group:
                for data_item in self.data_group.data_items:
                    self.__append_data_item_flat(data_item, data_items)
            return data_items

        def __get_data_item_count_flat(self, container):
            data_items = []
            self.__append_data_item_flat(container, data_items)
            return len(data_items)

        def item_inserted(self, container, key, object, before_index):
            if key == "data_groups":
                # manage the item model
                parent_item = self.mapping[container]
                self.beginInsert(before_index, before_index, parent_item.row, parent_item.id)
                count = self.__get_data_item_count_flat(object)
                properties = {
                    "display": str(object) + (" (%i)" % count),
                    "edit": object.title,
                    "data_group": object
                }
                item = self.createItem(properties)
                parent_item.insertChild(before_index, item)
                self.mapping[object] = item
                object.add_observer(self)
                object.add_listener(self)
                object.add_ref()
                self.endInsert()
                # recursively insert items that already exist
                data_groups = object.data_groups
                for index, child_data_group in enumerate(data_groups):
                    self.item_inserted(object, "data_groups", child_data_group, index)

        def item_removed(self, container, key, object, index):
            if key == "data_groups":
                assert isinstance(object, DocumentController.DataGroup)
                # get parent and item
                parent_item = self.mapping[container]
                # manage the item model
                self.beginRemove(index, index, parent_item.row, parent_item.id)
                object.remove_listener(self)
                object.remove_observer(self)
                object.remove_ref()
                parent_item.removeChild(parent_item.children[index])
                self.mapping.pop(object)
                self.endRemove()

        def __item_for_data_group(self, data_group):
            matched_items = []
            def match_item(parent, index, item):
                if "data_group" in item.data:
                    if item.data["data_group"] == data_group:
                        matched_items.append(item)
                        return True
                return False
            self.traverse(match_item)
            assert len(matched_items) == 1
            return matched_items[0]

        def __update_item_count(self, data_group):
            assert isinstance(data_group, DocumentController.DataGroup) or isinstance(data_group, DocumentController.SmartDataGroup)
            count = self.__get_data_item_count_flat(data_group)
            item = self.__item_for_data_group(data_group)
            item.data["display"] = str(data_group) + (" (%i)" % count)
            item.data["edit"] = data_group.title
            self.dataChanged(item.row, item.parent.row, item.parent.id)

        def property_changed(self, data_group, key, value):
            if key == "title":
                self.__update_item_count(data_group)

        # this method if called when one of our listened to items changes
        def data_item_inserted(self, container, data_item, before_index):
            self.__update_item_count(container)

        # this method if called when one of our listened to items changes
        def data_item_removed(self, container, data_item, index):
            self.__update_item_count(container)

        def item_key_press(self, text, modifiers, index, parent_row, parent_id):
            data_group = self.itemValue("data_group", None, self.itemId(index, parent_id))
            if data_group and len(data_group.data_items) == 0 and len(data_group.data_groups) == 0:
                if len(text) == 1 and ord(text[0]) == 127:
                    parent_item = self.itemFromId(self._parent_id)
                    if "data_group" in parent_item.data:
                        parent_item.data["data_group"].data_groups.remove(data_group)
                    else:
                        self.document_controller.data_groups.remove(data_group)
            return False

        def item_set_data(self, data, index, parent_row, parent_id):
            data_group = self.itemValue("data_group", None, self.itemId(index, parent_id))
            if data_group:
                data_group.title = data
                return True
            return False

        def __get_data_group_of_parent(self, parent_row, parent_id):
            parent_item = self.itemFromId(parent_id)
            return parent_item.data["data_group"] if "data_group" in parent_item.data else None

        def item_drop_mime_data(self, mime_data, action, row, parent_row, parent_id):
            data_group = self.__get_data_group_of_parent(parent_row, parent_id)
            container = self.document_controller if parent_row < 0 and parent_id == 0 else data_group
            if data_group and mime_data.has_file_paths:
                if row >= 0:  # only accept drops ONTO items, not BETWEEN items
                    return self.NONE
                if self.data_panel.receiveFiles(data_group, len(data_group.data_items), mime_data.file_paths):
                    return self.COPY
            if data_group and mime_data.has_format("text/data_item_uuid"):
                if row >= 0:  # only accept drops ONTO items, not BETWEEN items
                    return self.NONE
                # if the data item exists in this document, then it is copied to the
                # target group. if it doesn't exist in this document, then it is coming
                # from another document and can't be handled here.
                data_item_uuid = uuid.UUID(mime_data.data_as_string("text/data_item_uuid"))
                data_item = self.document_controller.get_data_item_by_key(data_item_uuid)
                if data_item:
                    data_item_copy = data_item.copy()
                    data_group.data_items.append(data_item_copy)
                    return action
                return self.NONE
            if mime_data.has_format("text/data_group_uuid"):
                data_group_uuid = uuid.UUID(mime_data.data_as_string("text/data_group_uuid"))
                data_group = self.document_controller.get_data_group_by_uuid(data_group_uuid)
                if data_group:
                    data_group_copy = data_group.copy()
                    if row >= 0:
                        container.data_groups.insert(row, data_group_copy)
                    else:
                        container.data_groups.append(data_group_copy)
                    return action
            return self.NONE

        def item_mime_data(self, row, parent_row, parent_id):
            parent_item = self.itemFromId(self._parent_id)
            data_group = self.itemValue("data_group", None, self.itemId(self._index, self._parent_id))
            if data_group:
                mime_data = self.ui.create_mime_data()
                mime_data.set_data_as_string("text/data_group_uuid", str(data_group.uuid))
                return mime_data
            return None

        def remove_rows(self, row, count, parent_row, parent_id):
            data_group = self.__get_data_group_of_parent(parent_row, parent_id)
            container = self.document_controller if parent_row < 0 and parent_id == 0 else data_group
            for i in range(count):
                del container.data_groups[row]
            return True

        def __get_data_panel_selection(self):
            parent_item = self.itemFromId(self._parent_id)
            data_group = self.itemValue("data_group", None, self.itemId(self._index, self._parent_id))
            return DataItemSpecifier(data_group)
        data_panel_selection = property(__get_data_panel_selection)

        def set_block_image_panel_update(self, block):
            old_block_image_panel_update = self.__block_image_panel_update
            self.__block_image_panel_update = block
            return old_block_image_panel_update

        def item_changed(self, index, parent_row, parent_id):
            # record the change
            self._index = index
            self._parent_row = parent_row
            self._parent_id = parent_id
            # update the selected image panel
            if not self.__block_image_panel_update:
                image_panel = self.document_controller.selected_image_panel
                if image_panel:
                    image_panel.data_panel_selection = self.data_panel_selection

        def __get_supported_drop_actions(self):
            return self.DRAG | self.DROP
        supported_drop_actions = property(__get_supported_drop_actions)

        def __get_mime_types_for_drop(self):
            return ["text/uri-list", "text/data_item_uuid", "text/data_group_uuid"]
        mime_types_for_drop = property(__get_mime_types_for_drop)

    # a list model of the data items. data items are actually hierarchical in nature,
    # but we don't use a tree view since the hierarchy is always visible and represented
    # by indent level. this means that we must track changes to the data group that we're
    # inspecting and translate the hierarchy into a linear indexing scheme.
    class DataItemModel(UserInterface.ListModel):

        def __init__(self, document_controller):
            super(DataPanel.DataItemModel, self).__init__(document_controller, ["uuid", "level", "display", "display2", "graphic_url"])
            self.__data_group = None
            self._index = -1
            self.__block_item_changed = False

        def close(self):
            # TODO: unlisten to everything
            self.data_group = None
            super(DataPanel.DataItemModel, self).close()

        def log(self):
            for index, item in enumerate(self.model):
                value = item["display"] if "display" in item else "---"
                level = item["level"]
                logging.debug("  " * level + str(index) + ":" + value)

        def __append_data_item_flat(self, data_item, data_items):
            data_items.append(data_item)
            for child_data_item in data_item.data_items:
                self.__append_data_item_flat(child_data_item, data_items)

        def __get_data_items_flat(self):
            data_items = []
            if self.data_group:
                for data_item in self.data_group.data_items:
                    self.__append_data_item_flat(data_item, data_items)
            return data_items

        def __get_data_item_count_flat(self, data_item):
            data_items = []
            self.__append_data_item_flat(data_item, data_items)
            return len(data_items)

        # this method if called when one of our listened to items changes
        def data_item_inserted(self, container, data_item, before_index):
            data_items_flat = self.__get_data_items_flat()
            before_data_item = container.get_storage_relationship("data_items", before_index)
            before_index_flat = data_items_flat.index(before_data_item)
            level = self.model[data_items_flat.index(container)]["level"]+1 if container in data_items_flat else 0
            # register the thumbnail provider
            self.ui.DocumentWindow_registerThumbnailProvider(self.document_controller.document_window, str(data_item.uuid), data_item)
            # add the listener. this will result in calls to data_item_changed
            data_item.add_listener(self)
            # begin observing
            data_item.add_observer(self)
            data_item.add_ref()
            # do the insert
            data_shape = data_item.data.shape if data_item and data_item.data is not None else None
            data_shape_str = " x ".join([str(d) for d in data_shape]) if data_shape else ""
            graphic_url = "image://thumb/"+str(data_item.uuid)+"/"+str(random.randint(0,1000000))
            properties = {"uuid": str(data_item.uuid), "level": level, "display": str(data_item), "display2": data_shape_str, "graphic_url": graphic_url}
            self.beginInsert(before_index_flat, before_index_flat)
            self.model.insert(before_index_flat, properties)
            self.endInsert()
            # recursively insert items that already exist
            for index, child_data_item in enumerate(data_item.data_items):
                self.data_item_inserted(data_item, child_data_item, index)

        # this method if called when one of our listened to items changes
        def data_item_removed(self, container, data_item, index):
            assert isinstance(data_item, DataItem.DataItem)
            # recursively remove child items
            for index in reversed(range(len(data_item.data_items))):
                self.data_item_removed(data_item, data_item.data_items[index], index)
            # now figure out which index was removed
            index_flat = 0
            for item in self.model:
                if uuid.UUID(item["uuid"]) == data_item.uuid:
                    break
                index_flat = index_flat + 1
            assert index_flat < len(self.model)
            # manage the item model
            self.beginRemove(index_flat, index_flat)
            del self.model[index_flat]
            self.endRemove()
            # unregister the thumbnail provider
            self.ui.DocumentWindow_unregisterThumbnailProvider(self.document_controller.document_window, str(data_item.uuid))
            # remove the listener.
            data_item.remove_listener(self)
            # remove the observer.
            data_item.remove_observer(self)
            data_item.remove_ref()

        # used for queue_main_thread decorator
        delay_queue = property(lambda self: self.document_controller.delay_queue)
        # data_item_changed is received from data items tracked in this model.
        # the connection is established in add_data_item using add_listener.
        @queue_main_thread
        def data_item_changed(self, data_item, info):
            # update the url so that it gets reloaded
            data_items_flat = self.__get_data_items_flat()
            # we might be receiving this message for an item that is no longer in the list
            # if the item updates and the user switches panels. check and skip it if so.
            if data_item in data_items_flat:
                index = data_items_flat.index(data_item)
                properties = self.model[index]
                properties["graphic_url"] = "image://thumb/"+str(data_item.uuid)+"/"+str(random.randint(0,1000000))
                self.dataChanged()

        def __get_data_item_container(self, container, query_data_item):
            if hasattr(container, "data_items") and query_data_item in container.data_items:
                return container
            if hasattr(container, "data_groups"):
                for data_group in container.data_groups:
                    container = self.__get_data_item_container(data_group, query_data_item)
                    if container:
                        return container
            if hasattr(container, "data_items"):
                for data_item in container.data_items:
                    container = self.__get_data_item_container(data_item, query_data_item)
                    if container:
                        return container
            return None

        def itemKeyPress(self, index, text, raw_modifiers):
            data_item = self.__get_data_items_flat()[index] if index >= 0 else None
            if data_item:
                if len(text) == 1 and ord(text[0]) == 127:
                    container = self.__get_data_item_container(self.document_controller, data_item)
                    assert data_item in container.data_items
                    container.data_items.remove(data_item)
            return False

        def itemChanged(self, index):
            if not self.__block_item_changed:
                self._index = index
                data_item = self.__get_data_items_flat()[index] if index >= 0 else None
                # update the selected image panel
                image_panel = self.document_controller.selected_image_panel
                if image_panel:
                    image_panel.data_panel_selection = DataItemSpecifier(self.data_group, data_item)

        def itemClicked(self, index):
            return False

        def itemDoubleClicked(self, index):
            return False

        def __get_data_group(self):
            return self.__data_group
        def __set_data_group(self, data_group):
            if data_group != self.__data_group:
                old_block_item_changed = self.__block_item_changed
                self.__block_item_changed = True
                if self.__data_group:
                    # no longer watch for changes
                    self.__data_group.remove_listener(self)
                    # remove existing items
                    data_items = self.__data_group.data_items
                    for index in reversed(range(len(data_items))):
                        self.data_item_removed(self.__data_group, data_items[index], index)
                self.__data_group = data_group
                if self.__data_group:
                    # add new items
                    for index, child_data_item in enumerate(self.__data_group.data_items):
                        self.data_item_inserted(self.__data_group, child_data_item, index)
                    # watch fo changes
                    self.__data_group.add_listener(self)
                self.__block_item_changed = old_block_item_changed
        data_group = property(__get_data_group, __set_data_group)

        def get_data_item_index(self, data_item):
            data_items_flat = self.__get_data_items_flat()
            index = data_items_flat.index(data_item) if data_item in data_items_flat else -1
            return index

        def __get_data_panel_selection(self):
            data_item = self.__get_data_items_flat()[self._index] if self._index >= 0 else None
            return DataItemSpecifier(self.data_group, data_item)
        data_panel_selection = property(__get_data_panel_selection)

    def __init__(self, document_controller, panel_id):
        Panel.Panel.__init__(self, document_controller, panel_id, _("Data Items"))

        self.data_group_model = DataPanel.DataGroupModel(document_controller, self)
        self.data_item_model = DataPanel.DataItemModel(document_controller)

        self.data_group_widget = self.loadIntrinsicWidget("pytree")
        self.ui.PyTreeWidget_setModel(self.data_group_widget, self.data_group_model.py_item_model)
        self.ui.Widget_setWidgetProperty(self.data_group_widget, "min-height", 80)
        self.ui.Widget_setWidgetProperty(self.data_group_widget, "stylesheet", "border: none; background-color: '#EEEEEE'")

        # set up the qml view
        context_properties = { "browser_model": self.data_item_model.py_list_model }
        qml_filename = relative_file(__file__, "DataListView.qml")
        self.data_item_widget = self.ui.DocumentWindow_loadQmlWidget(self.document_controller.document_window, qml_filename, self, context_properties)
        self.ui.Widget_setWidgetProperty(self.data_item_widget, "min-height", 240)

        self.__block_current_item_changed = False

        self.widget = self.ui.Widget_loadIntrinsicWidget("column")
        self.ui.Widget_addWidget(self.widget, self.data_group_widget)
        self.ui.Widget_addWidget(self.widget, self.data_item_widget)
        self.ui.Widget_setWidgetProperty(self.widget, "spacing", 2)
        self.ui.Widget_setWidgetProperty(self.widget, "stylesheet", "background-color: '#FFF'")

        # connect self as listener. this will result in calls to selected_image_panel_changed
        self.document_controller.add_listener(self)

    def close(self):
        self.update_data_panel_selection(DataItemSpecifier())
        # clear browser model from the qml view
        self.setContextProperty("browser_model", None)
        # close the models
        self.data_item_model.close()
        self.data_group_model.close()
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # finish closing
        Panel.Panel.close(self)

    def update_data_panel_selection(self, data_panel_selection):
        old_block_current_item_changed = self.__block_current_item_changed
        self.__block_current_item_changed = True
        data_group = data_panel_selection.data_group
        data_item = data_panel_selection.data_item
        item = None
        data_group_item = self.data_group_model.mapping.get(data_group)
        parent_item = data_group_item.parent if data_group_item else self.data_group_model.root
        assert parent_item is not None
        for child in parent_item.children:
            child_data_group = child.data.get("data_group")
            if child_data_group == data_group:
                item = child
                break
        if item:
            self.data_group_model._index = item.row
            self.data_group_model._parent_row = item.parent.row
            self.data_group_model._parent_id = item.parent.id
            self.set_group_current_row(item.row, item.parent.row, item.parent.id)
        else:
            self.data_group_model._index = -1
            self.data_group_model._parent_row = -1
            self.data_group_model._parent_id = 0
            self.set_group_current_row(-1, -1, 0)
        self.data_item_model.data_group = data_group
        self.data_item_model._index = self.data_item_model.get_data_item_index(data_item)
        # update the qml
        prev_current_index = self.ui.Widget_getWidgetProperty(self.data_item_widget, "currentIndex")
        if prev_current_index != self.data_item_model._index:
            self.ui.Widget_setWidgetProperty(self.data_item_widget, "currentIndex", self.data_item_model._index)
        self.__block_current_item_changed = old_block_current_item_changed

    # used for queue_main_thread decorator
    delay_queue = property(lambda self: self.document_controller.delay_queue)

    @queue_main_thread
    def set_group_current_row(self, index, parent_row, parent_id):
        old = self.data_group_model.set_block_image_panel_update(True)
        self.ui.PyTreeWidget_setCurrentRow(self.data_group_widget, index, parent_row, parent_id)
        self.data_group_model.set_block_image_panel_update(old)

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_image_panel_changed(self, image_panel):
        data_panel_selection = image_panel.data_panel_selection if image_panel else DataItemSpecifier()
        self.update_data_panel_selection(data_panel_selection)

    def data_panel_selection_changed_from_image_panel(self, data_panel_selection):
        self.update_data_panel_selection(data_panel_selection)

    # these messages come straight from DataListView.qml via explicit invocation.
    # the message is generated when the user clicks on an new item.
    def dataListCurrentIndexChanged(self, current_index):
        if not self.__block_current_item_changed:
            self.data_item_model.itemChanged(current_index)
    # the message is generated when the user presses a key.
    def keyPressed(self, text, key, raw_modifiers):
        return self.data_item_model.itemKeyPress(self.data_item_model._index, text, raw_modifiers)

    def receiveUrls(self, index, urls):
        data_group = self.data_item_model.data_group
        file_paths = [self.ui.Core_URLToPath(url) for url in urls]
        return self.receiveFiles(data_group, index, file_paths)

    def receiveFiles(self, data_group, index, file_paths):
        if data_group and isinstance(data_group, DocumentController.DataGroup):
            first_data_item = None
            for file_path in file_paths:
                try:
                    raw_image = self.ui.readImageToPyArray(file_path)
                    rgba_image = Image.rgbView(raw_image)
                    if numpy.array_equal(rgba_image[..., 0],rgba_image[..., 1]) and numpy.array_equal(rgba_image[..., 1],rgba_image[..., 2]):
                        image_data = numpy.zeros(raw_image.shape, numpy.uint32)
                        image_data[:, :] = numpy.mean(rgba_image, 2)
                    else:
                        image_data = rgba_image
                    data_item = DataItem.DataItem()
                    data_item.title = os.path.basename(file_path)
                    data_item.master_data = image_data
                    if index >= 0:
                        data_group.data_items.insert(index, data_item)
                    else:
                        data_group.data_items.append(data_item)
                    if not first_data_item:
                        first_data_item = data_item
                except Exception as e:
                    logging.debug("Could not read image %s", file_path)
            if first_data_item:
                # select the first item/group
                image_panel = self.document_controller.selected_image_panel
                if image_panel:
                    image_panel.data_panel_selection = DataItemSpecifier(data_group, first_data_item)
                return True
        return False

    def copyItem(self, uuid_str, source_index, drop_index):
        data_group = self.data_item_model.data_group
        if data_group and isinstance(data_group, DocumentController.DataGroup):
            data_item = data_group.data_items[source_index]
            assert data_item.uuid == uuid.UUID(uuid_str)
            data_item_copy = data_item.copy()
            assert data_item_copy.uuid != uuid.UUID(uuid_str)
            if drop_index >= 0:
                data_group.data_items.insert(drop_index, data_item_copy)
            else:
                data_group.data_items.append(data_item_copy)

    def deleteItemByUuid(self, uuid_str):
        data_group = self.data_item_model.data_group
        if data_group and isinstance(data_group, DocumentController.DataGroup):
            for data_item in data_group.data_items:
                if data_item.uuid == uuid.UUID(uuid_str):
                    data_group.data_items.remove(data_item)
                    break
