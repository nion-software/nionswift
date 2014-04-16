"""
    Contains classes related to display of data items.
"""

# standard libraries
import gettext
import weakref

# third party libraries
# None

# local libraries
from nion.swift.model import Storage

_ = gettext.gettext


class Display(Storage.StorageBase):

    def __init__(self):
        super(Display, self).__init__()
        self.storage_properties += ["properties"]
        self.storage_relationships += ["graphics"]
        self.storage_type = "display"
        # self.register_dependent_key("data_range", "display_range")
        # self.register_dependent_key("display_limits", "display_range")
        self.__weak_data_item = None
        self.__properties = dict()
        self.__graphics = Storage.MutableRelationship(self, "graphics")
        self.__drawn_graphics = Model.ListModel(self, "drawn_graphics")

    def about_to_delete(self):
        for graphic in copy.copy(self.graphics):
            self.remove_graphic(graphic)
        self._set_data_item(None)

    @classmethod
    def build(cls, datastore, item_node, uuid_):
        properties = datastore.get_property(item_node, "properties")
        graphics = datastore.get_items(item_node, "graphics")
        display = cls()
        display.__properties = properties if properties else dict()
        display.extend_graphics(graphics)
        return display

    def __deepcopy__(self, memo):
        display_copy = DataItem()
        with display_copy.property_changes() as property_accessor:
            property_accessor.properties.clear()
            property_accessor.properties.update(self.properties)
        for graphic in self.graphics:
            display_copy.append_graphic(copy.deepcopy(graphic, memo))
        memo[id(self)] = display_copy
        return display_copy

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    data_item = property(__get_data_item)

    def _set_data_item(self, data_item):
        if self.data_item:
            self.data_item.remove_observer(self)
            self.data_item.remove_ref()
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
        if self.data_item:
            self.data_item.add_ref()
            self.data_item.add_observer(self)

    def __get_properties(self):
        return self.__properties.copy()
    properties = property(__get_properties)

    def __grab_properties(self):
        return self.__properties
    def __release_properties(self):
        self.notify_set_property("properties", self.__properties)
        self.notify_listeners("display_changed", self)

    def property_changes(self):
        grab_properties = DataItem.__grab_properties
        release_properties = DataItem.__release_properties
        class PropertyChangeContextManager(object):
            def __init__(self, data_item):
                self.__data_item = data_item
            def __enter__(self):
                return self
            def __exit__(self, type, value, traceback):
                release_properties(self.__data_item)
            def __get_properties(self):
                return grab_properties(self.__data_item)
            properties = property(__get_properties)
        return PropertyChangeContextManager(self)

    def get_processed_data(self, processor_id, ui, completion_fn):
        return self.data_item.get_processor(processor_id).get_data(ui, completion_fn)

    def __get_drawn_graphics(self):
        return self.data_item.drawn_graphics
    drawn_graphics = property(__get_drawn_graphics)

    def __get_display_calibrated_values(self):
        return self.data_item.display_calibrated_values
    def __set_display_calibrated_values(self, display_calibrated_values):
        self.data_item.display_calibrated_values = display_calibrated_values
    display_calibrated_values = property(__get_display_calibrated_values, __set_display_calibrated_values)

    def __get_display_limits(self):
        return self.data_item.display_limits
    def __set_display_limits(self, display_limits):
        self.data_item.display_limits = display_limits
    display_limits = property(__get_display_limits, __set_display_limits)

    def __get_data_range(self):
        return self.data_item.data_range
    data_range = property(__get_data_range)

    def __get_display_range(self):
        return self.data_item.display_range
    def __set_display_range(self, display_range):
        self.data_item.display_range = display_range
    display_range = property(__get_display_range) ##, __set_display_range)

    # message sent from data item. established using add/remove observer.
    def property_changed(self, sender, property, value):
        if property in ("data_range", "display_calibrated_values", "display_range"):
            self.notify_set_property(property, value)

    # message sent from data item. established using add/remove observer.
    def item_inserted(self, sender, key, object, before_index):
        if key in ("drawn_graphics"):
            self.notify_insert_item(key, object, before_index)

    # message sent from data item. established using add/remove observer.
    def item_removed(self, container, key, object, index):
        if key in ("drawn_graphics"):
            self.notify_remove_item(key, object, index)

    def notify_insert_item(self, key, value, before_index):
        super(Display, self).notify_insert_item(key, value, before_index)
        if key == "graphics":
            self.__drawn_graphics.insert(before_index, value)
            value.add_listener(self)
            self.data_item.display_changed(self)

    def notify_remove_item(self, key, value, index):
        super(Display, self).notify_remove_item(key, value, index)
        if key == "graphics":
            del self.__drawn_graphics[index]
            value.remove_listener(self)
            self.data_item.display_changed(self)

    // display changed needs to be called when the data changes. ugh. necessary for image panel.

    # this is called from the data item when an operation is inserted into one of
    # its child data items. this method updates the drawn graphics list.
    def operation_inserted_into_child_data_item(self, child_data_item, child_operation_item):
        # first count the graphics intrinsic to this object.
        index = len(self.graphics)
        # now cycle through each data item.
        for data_item in self.data_item.data_items:
            # and each operation within that data item.
            for operation_item in data_item.operations:
                operation_graphics = operation_item.graphics
                # if this is the match operation, do the insert
                if data_item == child_data_item and operation_item == child_operation_item:
                    for operation_graphic in reversed(operation_graphics):
                        operation_graphic.add_listener(self)
                        self.__drawn_graphics.insert(index, operation_graphic)
                        return  # done
                # otherwise count up the graphics and continue
                index += len(operation_graphics)

    def operation_removed_from_child_data_item(self, operation_item):
        # removal is easier since we don't need an insert point
        for operation_graphic in operation_item.graphics:
            operation_graphic.remove_listener(self)
            self.__drawn_graphics.remove(operation_graphic)

    def __get_graphics(self):
        """ A copy of the graphics """
        return copy.copy(self.__graphics)
    graphics = property(__get_graphics)

    def insert_graphic(self, index, graphic):
        """ Insert a graphic before the index """
        self.__graphics.insert(index, graphic)

    def append_graphic(self, graphic):
        """ Append a graphic """
        self.__graphics.append(graphic)

    def remove_graphic(self, graphic):
        """ Remove a graphic """
        self.__graphics.remove(graphic)

    def extend_graphics(self, graphics):
        """ Extend the graphics array with the list of graphics """
        self.__graphics.extend(graphics)

    # drawn graphics and the regular graphic items, plus those derived from the operation classes
    def __get_drawn_graphics(self):
        """ List of drawn graphics """
        return self.__drawn_graphics
    drawn_graphics = property(__get_drawn_graphics)

    def remove_drawn_graphic(self, drawn_graphic):
        """ Remove a drawn graphic which might be intrinsic or a graphic associated with an operation on a child """
        if drawn_graphic in self.__graphics:
            self.__graphics.remove(drawn_graphic)
        else:  # a synthesized graphic
            # cycle through each data item.
            for data_item in self.data_items:
                # and each operation within that data item.
                for operation_item in data_item.operations:
                    operation_graphics = operation_item.graphics
                    if drawn_graphic in operation_graphics:
                        self.data_items.remove(data_item)

    # this message comes from the graphic. the connection is established when a graphic
    # is added or removed from this object.
    def graphic_changed(self, graphic):
        self.data_item.display_changed(self)
