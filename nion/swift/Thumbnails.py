"""
    Contains classes related to thumbnail generation.
"""

# standard libraries
import threading
import time

# third-party libraries
import numpy

# local libraries
from nion.swift import DisplayPanel
from nion.swift.model import Utility
from nion.swift.model.Display import Display
from nion.ui import DrawingContext
from nion.utils import Event
from nion.utils import ReferenceCounting


class ThumbnailProcessor:
    """Processes thumbnails for a display in a thread."""

    def __init__(self, display):
        self.__display = display
        self.__cache = display._display_cache
        self.__cache_property_name = "thumbnail_data"
        # the next two fields represent a memory cache -- a cache of the cache values.
        # if self.__cached_value_dirty is None then this first level cache has not yet
        # been initialized. these fields are used for optimization.
        self.__cached_value = None
        self.__cached_value_dirty = None
        self.__cached_value_time = 0
        self.__is_recomputing = False
        self.__is_recomputing_lock = threading.RLock()
        self.width = 72
        self.height = 72
        self.on_thumbnail_updated = None
        self.__recompute_thread = None
        self.__recompute_lock = threading.RLock()
        self.__recompute_thread_cancel = threading.Event()

    def close(self):
        self.on_thumbnail_updated = None
        with self.__is_recomputing_lock:
            if self.__recompute_thread:
                self.__recompute_thread_cancel.set()
                self.__recompute_thread.join()

    # used for testing
    @property
    def _is_cached_value_dirty(self):
        return self.__cached_value_dirty

    # thread safe
    def mark_data_dirty(self):
        """ Called from item to indicate its data or metadata has changed."""
        self.__cache.set_cached_value_dirty(self.__display, self.__cache_property_name)
        self.__initialize_cache()
        self.__cached_value_dirty = True

    def __initialize_cache(self):
        """Initialize the cache values (cache values are used for optimization)."""
        if self.__cached_value_dirty is None:
            self.__cached_value_dirty = self.__cache.is_cached_value_dirty(self.__display, self.__cache_property_name)
            self.__cached_value = self.__cache.get_cached_value(self.__display, self.__cache_property_name)

    def recompute_if_necessary(self, ui):
        """Recompute the data on a thread, if necessary.

        If the data has recently been computed, this call will be rescheduled for the future.

        If the data is currently being computed, it do nothing."""
        self.__initialize_cache()
        if self.__cached_value_dirty:
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
                        if self.__recompute_thread_cancel.wait(0.01):  # helps tests run faster
                            return
                        minimum_time = 0.5
                        current_time = time.time()
                        if current_time < self.__cached_value_time + minimum_time:
                            if self.__recompute_thread_cancel.wait(self.__cached_value_time + minimum_time - current_time):
                                return
                        self.recompute_data(ui)
                    finally:
                        self.__is_recomputing = False
                        self.__recompute_thread = None
                with self.__is_recomputing_lock:
                    self.__recompute_thread = threading.Thread(target=recompute)
                    self.__recompute_thread.start()

    def recompute_data(self, ui):
        """Compute the data associated with this processor.

        This method is thread safe and may take a long time to return. It should not be called from
         the UI thread. Upon return, the results will be calculated with the latest data available
         and the cache will not be marked dirty.
        """
        self.__initialize_cache()
        with self.__recompute_lock:
            if self.__cached_value_dirty:
                try:
                    calculated_data = self.get_calculated_data(ui)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    traceback.print_stack()
                    raise
                self.__cache.set_cached_value(self.__display, self.__cache_property_name, calculated_data)
                self.__cached_value = calculated_data
                self.__cached_value_dirty = False
                self.__cached_value_time = time.time()
            else:
                calculated_data = None
            if calculated_data is None:
                calculated_data = self.get_default_data()
                if calculated_data is not None:
                    # if the default is not None, treat is as valid cached data
                    self.__cache.set_cached_value(self.__display, self.__cache_property_name, calculated_data)
                    self.__cached_value = calculated_data
                    self.__cached_value_dirty = False
                    self.__cached_value_time = time.time()
                else:
                    # otherwise remove everything from the cache
                    self.__cache.remove_cached_value(self.__display, self.__cache_property_name)
                    self.__cached_value = None
                    self.__cached_value_dirty = None
                    self.__cached_value_time = 0
            self.__recompute_lock.release()
            if callable(self.on_thumbnail_updated):
                self.on_thumbnail_updated()
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
        return self.__cached_value

    def get_calculated_data(self, ui):
        drawing_context = DisplayPanel.preview(ui, self.__display, 512, 512)
        thumbnail_drawing_context = DrawingContext.DrawingContext()
        thumbnail_drawing_context.scale(self.width / 512, self.height / 512)
        thumbnail_drawing_context.add(drawing_context)
        return ui.create_rgba_image(thumbnail_drawing_context, self.width, self.height)

    def get_default_data(self):
        return numpy.zeros((self.height, self.width), dtype=numpy.uint32)


class ThumbnailSource(ReferenceCounting.ReferenceCounted):
    """Produce a thumbnail for a display."""

    def __init__(self, ui, display: Display):
        super().__init__()
        self._ui = ui
        self._display = display

        self.thumbnail_updated_event = Event.Event()
        self.__thumbnail_processor = ThumbnailProcessor(display)
        self._on_will_delete = None

        def thumbnail_changed():
            thumbnail_processor = self.__thumbnail_processor
            if thumbnail_processor:
                thumbnail_processor.mark_data_dirty()
                thumbnail_processor.recompute_if_necessary(ui)

        no_cached_data = self.__thumbnail_processor.get_cached_data() is None

        self.__next_calculated_display_values_listener = display.add_calculated_display_values_listener(thumbnail_changed, send=no_cached_data)
        self.__display_changed_event_listener = display.display_changed_event.listen(thumbnail_changed)

        def thumbnail_updated():
            self.thumbnail_updated_event.fire()

        self.__thumbnail_processor.on_thumbnail_updated = thumbnail_updated

        self.__thumbnail_processor.recompute_if_necessary(ui)

        def display_will_close():
            if self.__thumbnail_processor:
                self.__thumbnail_processor.close()
                self.__thumbnail_processor = None

        self.__display_will_close_listener = display.about_to_be_removed_event.listen(display_will_close)

    def close(self):
        self.remove_ref()

    def about_to_delete(self):
        self.__display_will_close_listener.close()
        self.__display_will_close_listener = None
        if self.__thumbnail_processor:
            self.__thumbnail_processor.close()
            self.__thumbnail_processor = None
        if self.__display_changed_event_listener:
            self.__display_changed_event_listener.close()
            self.__display_changed_event_listener = None
        if self.__next_calculated_display_values_listener:
            self.__next_calculated_display_values_listener.close()
            self.__next_calculated_display_values_listener = None
        self._on_will_delete(self)
        self._on_will_delete = None

    @property
    def thumbnail_data(self):
        return self.__thumbnail_processor.get_cached_data() if self.__thumbnail_processor else None

    def recompute_data(self):
        self.__thumbnail_processor.recompute_data(self._ui)

    # used for testing
    @property
    def _is_thumbnail_dirty(self):
        return self.__thumbnail_processor._is_cached_value_dirty


class ThumbnailManager(metaclass=Utility.Singleton):
    """Manages thumbnail sources for displays."""

    def __init__(self):
        self.__thumbnail_sources = dict()
        self.__lock = threading.RLock()

    def thumbnail_source_for_display(self, ui, display: Display) -> ThumbnailSource:
        """Returned ThumbnailSource must be closed."""
        with self.__lock:
            thumbnail_source = self.__thumbnail_sources.get(display)
            if not thumbnail_source:
                thumbnail_source = ThumbnailSource(ui, display)
                self.__thumbnail_sources[display] = thumbnail_source

                def will_delete(thumbnail_source):
                    del self.__thumbnail_sources[thumbnail_source._display]

                thumbnail_source._on_will_delete = will_delete
            else:
                assert thumbnail_source._ui == ui
            return thumbnail_source.add_ref()

    def thumbnail_data_for_display(self, display: Display) -> numpy.ndarray:
        thumbnail_source = self.__thumbnail_sources.get(display) if display else None
        if thumbnail_source:
            return thumbnail_source.thumbnail_data
        return None
