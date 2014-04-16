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

    def __init__(self, data_item):
        super(Display, self).__init__()
        self.storage_type = "display"
        self.__weak_data_item = None
        self.__set_data_item(data_item)

    def about_to_delete(self):
        self.__set_data_item(None)

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    def __set_data_item(self, data_item):
        if self.data_item:
            self.data_item.remove_observer(self)
        self.__weak_data_item = weakref.ref(data_item) if data_item else None
        if self.data_item:
            self.data_item.add_observer(self)
    data_item = property(__get_data_item)

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
