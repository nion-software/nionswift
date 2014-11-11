import threading
import time
import weakref


class DataItemProcessor(object):

    def __init__(self, item, cache_property_name):
        self.__weak_item = weakref.ref(item)
        self.__cache_property_name = cache_property_name
        # the next two fields represent a memory cache -- a cache of the cache values.
        # if self.__cached_value_dirty is None then this first level cache has not yet
        # been initialized.
        self.__cached_value = None
        self.__cached_value_dirty = None

    def close(self):
        pass

    def __get_item(self):
        return self.__weak_item() if self.__weak_item else None
    item = property(__get_item)

    def data_item_changed(self):
        """ Called directly from data item. """
        self.set_cached_value_dirty()

    def item_property_changed(self, key, value):
        """
            Called directly from data item.
            Subclasses should override and call set_cached_value_dirty to add
            property dependencies.
        """
        pass

    def set_cached_value_dirty(self):
        self.item.set_cached_value_dirty(self.__cache_property_name)
        # is the memory cache initialized? only set it dirty if so.
        if self.__cached_value_dirty is not None:
            self.__cached_value_dirty = True

    def get_calculated_data(self, ui, data):
        """ Subclasses must implement. """
        raise NotImplementedError()

    def get_default_data(self):
        return None

    def get_data_item(self):
        """ Subclasses must implement. """
        raise NotImplementedError()

    def get_data(self, ui):
        """Return the data associated with this processor.

        This method is thread safe, however, caller threads may be blocked while processor
        occurs.
        """
        if self.__cached_value_dirty is None:
            # initialize the memory cache.
            self.__cached_value_dirty = self.item.is_cached_value_dirty(self.__cache_property_name)
            self.__cached_value = self.item.get_cached_value(self.__cache_property_name)
        if self.__cached_value_dirty:
            item = self.item  # hold a reference
            data_item = self.get_data_item()
            data = data_item.cached_data  # processors work on the data item's cached data
            if data is not None:  # for data to load and make sure it has data
                try:
                    calculated_data = self.get_calculated_data(ui, data)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    traceback.print_stack()
                    raise
                self.item.set_cached_value(self.__cache_property_name, calculated_data)
                self.__cached_value = calculated_data
                self.__cached_value_dirty = False
            else:
                calculated_data = None
            if calculated_data is None:
                calculated_data = self.get_default_data()
                if calculated_data is not None:
                    # if the default is not None, treat is as valid cached data
                    self.item.set_cached_value(self.__cache_property_name, calculated_data)
                    self.__cached_value = calculated_data
                    self.__cached_value_dirty = False
                else:
                    # otherwise remove everything from the cache
                    self.item.remove_cached_value(self.__cache_property_name)
                    self.__cached_value = None
                    self.__cached_value_dirty = None
        calculated_data = self.__cached_value
        if calculated_data is not None:
            return calculated_data
        return self.get_default_data()
