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
        self.__weak_data_item = weakref.ref(data_item)

    def __get_data_item(self):
        return self.__weak_data_item() if self.__weak_data_item else None
    data_item = property(__get_data_item)

    def get_processed_data(self, processor_id, ui, completion_fn):
        return self.data_item.get_processor(processor_id).get_data(ui, completion_fn)

    def __get_display_limits(self):
        return self.data_item.display_limits
    def __set_display_limits(self, display_limits):
        self.data_item.display_limits = display_limits
    display_limits = property(__get_display_limits, __set_display_limits)

    def __get_display_range(self):
        return self.data_item.display_range
    display_range = property(__get_display_range)
