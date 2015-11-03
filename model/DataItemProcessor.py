# futures
from __future__ import absolute_import

# standard libraries
import threading
import time
import weakref

# TODO: file format: Cache the storage processor output in data item itself rather than separate cache


class DataItemProcessor(object):
    """An abstract base class to facilitate data item processing.

    A data item processor watches for changes to an item such as a data item or a display
     and recomputes a result based on the item's data. For instance, a processor might compute
     the statistics of data, the histogram of a display, or a thumbnail.

    Items should support caching values and some notifications.

    Items should call data_item_changed when they change so that the result data can be marked
     as stale.

    TODO: review whether item_property_changed is necessary

    In addition, items should call item_property_changed when a property changes so that subclasses
     can watch for specific property changes and be marked as stale.

    Clients of processors must be able to receive important notifications such as when a processor
    needs to be recomputed and when its data changes after a recompute. This ability is facilitated
    by the following notifications to the container item.

    processor_needs_recompute(processor)
    processor_data_updated(processor)
    """

    def __init__(self, item, cache_property_name):
        self.__weak_item = weakref.ref(item)
        self.__cache_property_name = cache_property_name
        # the next two fields represent a memory cache -- a cache of the cache values.
        # if self.__cached_value_dirty is None then this first level cache has not yet
        # been initialized. these fields are used for optimization.
        self.__cached_value = None
        self.__cached_value_dirty = None
        self.__cached_value_time = 0
        self.__is_recomputing = False
        self.__is_recomputing_lock = threading.RLock()
        self.__recompute_lock = threading.RLock()

    def close(self):
        pass

    @property
    def item(self):
        """Return the containing item."""
        return self.__weak_item() if self.__weak_item else None

    # thread safe
    def mark_data_dirty(self):
        """ Called from item to indicate its data or metadata has changed."""
        self._set_cached_value_dirty()

    def item_property_changed(self, key, value):
        """Called from item to indicate a property has changed.

        Subclasses can override and call set_cached_value_dirty to add property dependencies.
        """
        pass

    def __initialize_cache(self):
        """Initialize the cache values (cache values are used for optimization)."""
        if self.__cached_value_dirty is None:
            self.__cached_value_dirty = self.item.is_cached_value_dirty(self.__cache_property_name)
            self.__cached_value = self.item.get_cached_value(self.__cache_property_name)
            # import logging
            # logging.debug("loading %s %s %s", self.__cached_value_dirty, self.__cache_property_name, self.item.uuid)

    # thread safe
    def _set_cached_value_dirty(self):
        """Subclasses can use this to mark cache value dirty within item_property_changed."""
        self.item.set_cached_value_dirty(self.__cache_property_name)
        self.__initialize_cache()
        self.__cached_value_dirty = True
        self.item.processor_needs_recompute(self)

    def get_calculated_data(self, ui, data):
        """Subclasses must implement to compute and return results from data."""
        raise NotImplementedError()

    def get_default_data(self):
        """Subclasses can override to return default data."""
        return None

    @property
    def is_data_stale(self):
        """Return whether the data is stale."""
        self.__initialize_cache()
        return self.__cached_value_dirty

    def recompute_if_necessary(self, dispatch, arg):
        """Recompute the data on a thread, if necessary.

        If the data has recently been computed, this call will be rescheduled for the future.

        If the data is currently being computed, it do nothing."""
        if self.is_data_stale:
            with self.__is_recomputing_lock:
                is_recomputing = self.__is_recomputing
                self.__is_recomputing = True
            if is_recomputing:
                pass
            else:
                # the only way to get here is if we're not currently computing
                # this has the side effect of limiting the number of threads that
                # are sleeping.
                def recompute():
                    try:
                        minimum_time = 0.5
                        current_time = time.time()
                        if current_time < self.__cached_value_time + minimum_time:
                            time.sleep(self.__cached_value_time + minimum_time - current_time)
                        self.recompute_data(arg)
                    finally:
                        with self.__is_recomputing_lock:
                            self.__is_recomputing = False
                dispatch(recompute, self.__cache_property_name)

    def recompute_data(self, ui):
        """Compute the data associated with this processor.

        This method is thread safe and may take a long time to return. It should not be called from
         the UI thread. Upon return, the results will be calculated with the latest data available
         and the cache will not be marked dirty.
        """
        self.__initialize_cache()
        with self.__recompute_lock:
            if self.__cached_value_dirty:
                item = self.item  # hold a reference in case it gets closed during execution of this method
                data = item.data_for_processor  # grab the most up to date data
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
                    self.__cached_value_time = time.time()
                    # import logging
                    # logging.debug("updated %s %s %s", self.item.is_cached_value_dirty(self.__cache_property_name), self.__cache_property_name, self.item.uuid)
                else:
                    calculated_data = None
                if calculated_data is None:
                    calculated_data = self.get_default_data()
                    if calculated_data is not None:
                        # if the default is not None, treat is as valid cached data
                        self.item.set_cached_value(self.__cache_property_name, calculated_data)
                        self.__cached_value = calculated_data
                        self.__cached_value_dirty = False
                        self.__cached_value_time = time.time()
                        # import logging
                        # logging.debug("default %s %s %s", self.item.is_cached_value_dirty(self.__cache_property_name), self.__cache_property_name, self.item.uuid)
                    else:
                        # otherwise remove everything from the cache
                        self.item.remove_cached_value(self.__cache_property_name)
                        self.__cached_value = None
                        self.__cached_value_dirty = None
                        self.__cached_value_time = 0
                        # import logging
                        # logging.debug("removed %s %s %s", self.item.is_cached_value_dirty(self.__cache_property_name), self.__cache_property_name, self.item.uuid)
                self.__recompute_lock.release()
                self.item.processor_data_updated(self)
                self.__recompute_lock.acquire()

    def get_data(self, ui):
        """Return the computed data for this processor.

        This method is thread safe but may take a long time to return since it may have to compute
         the results. It should not be called from the UI thread.
        """
        self.recompute_data(ui)
        return self.get_cached_data()

    def get_cached_data(self):
        """Return the cached data for this processor.

        This method is thread safe and always returns quickly, using the cached data.
        """
        self.__initialize_cache()
        calculated_data = self.__cached_value
        if calculated_data is not None:
            return calculated_data
        return self.get_default_data()
