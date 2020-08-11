"""
    Contains classes related to thumbnail generation.
"""

# standard libraries
import concurrent.futures
import threading
import time
import typing

# third-party libraries
import numpy

# local libraries
from nion.swift import DisplayPanel
from nion.swift.model import Utility
from nion.swift.model import DisplayItem
from nion.ui import DrawingContext
from nion.ui import UserInterface
from nion.utils import Event
from nion.utils import ReferenceCounting


class ThumbnailProcessor:
    """Processes thumbnails for a display in a thread."""
    _executor = concurrent.futures.ThreadPoolExecutor()

    def __init__(self, display_item: DisplayItem.DisplayItem):
        self.__display_item = display_item
        self.__display_item_about_to_close_listener = self.__display_item.about_to_close_event.listen(self.__about_to_close_display_item)
        self.__cache = self.__display_item._display_cache
        self.__cache_property_name = "thumbnail_data"
        self.__cached_value_time = 0
        self.__is_recomputing_lock = threading.RLock()
        self.__is_recompute_pending = False
        self.width = 512
        self.height = 512
        self.on_thumbnail_updated = None
        self.__recompute_future = None
        self.__recompute_lock = threading.RLock()
        self.__recompute_thread_cancel = threading.Event()

    def close(self):
        self.on_thumbnail_updated = None
        recompute_future = self.__recompute_future  # avoid race by using local
        if recompute_future:
            self.__recompute_thread_cancel.set()
            concurrent.futures.wait([recompute_future])

    def __about_to_close_display_item(self) -> None:
        recompute_future = self.__recompute_future  # avoid race by using local
        if recompute_future:
            self.__recompute_thread_cancel.set()
            concurrent.futures.wait([recompute_future])
        self.__display_item = None

    # used internally and for testing
    @property
    def _is_cached_value_dirty(self):
        return self.__cache.is_cached_value_dirty(self.__display_item, self.__cache_property_name)

    # thread safe
    def mark_data_dirty(self):
        """ Called from item to indicate its data or metadata has changed."""
        self.__cache.set_cached_value_dirty(self.__display_item, self.__cache_property_name)

    def __get_cached_value(self) -> typing.Optional[numpy.ndarray]:
        return self.__cache.get_cached_value(self.__display_item, self.__cache_property_name)

    def __recompute_task(self, ui: UserInterface.UserInterface) -> None:
        while True:
            try:
                if self.__recompute_thread_cancel.wait(0.05):  # gather changes and helps tests run faster
                    return
                minimum_time = 0.5
                current_time = time.time()
                if current_time < self.__cached_value_time + minimum_time:
                    if self.__recompute_thread_cancel.wait(self.__cached_value_time + minimum_time - current_time):
                        return
                self.__is_recompute_pending = False  # any pending calls up to this point will be realized in the recompute
                self.recompute_data(ui)
            finally:
                with self.__is_recomputing_lock:
                    # the only way the thread can end is if not pending within lock.
                    # recompute_future can only be set within lock.
                    if not self.__is_recompute_pending:
                        self.__recompute_future = None
                        break

    def recompute(self, ui: UserInterface.UserInterface) -> None:
        # recompute the thumbnail data on a thread.
        # if already computing, ensure the thread recomputes again.
        # may be called on the main thread or a thread - must return quickly in both cases.
        with self.__is_recomputing_lock:
            # in case thread is already running, set pending.
            # the only way the thread can end is if not pending within lock.
            # recompute_future can only be set within lock.
            self.__is_recompute_pending = True
            if not self.__recompute_future:
                self.__recompute_future = ThumbnailProcessor._executor.submit(self.__recompute_task, ui)

    def recompute_data(self, ui):
        """Compute the data associated with this processor.

        This method is thread safe and may take a long time to return. It should not be called from
         the UI thread. Upon return, the results will be calculated with the latest data available
         and the cache will not be marked dirty.
        """
        with self.__recompute_lock:
            try:
                calculated_data = self.__get_calculated_data(ui)
            except Exception as e:
                import traceback
                traceback.print_exc()
                traceback.print_stack()
                raise
            if calculated_data is None:
                calculated_data = numpy.zeros((self.height, self.width), dtype=numpy.uint32)
            self.__cache.set_cached_value(self.__display_item, self.__cache_property_name, calculated_data)
            self.__cached_value_time = time.time()
        if callable(self.on_thumbnail_updated):
            self.on_thumbnail_updated()

    def get_cached_data(self):
        """Return the cached data for this processor.

        This method is thread safe and always returns quickly, using the cached data.
        """
        return self.__get_cached_value()

    def __get_calculated_data(self, ui):
        drawing_context, shape = DisplayPanel.preview(DisplayPanel.DisplayPanelUISettings(ui), self.__display_item, 512, 512)
        thumbnail_drawing_context = DrawingContext.DrawingContext()
        thumbnail_drawing_context.scale(self.width / 512, self.height / 512)
        thumbnail_drawing_context.translate(0, (shape[1] - shape[0]) * 0.5)
        thumbnail_drawing_context.add(drawing_context)
        return ui.create_rgba_image(thumbnail_drawing_context, self.width, self.height)


class ThumbnailSource(ReferenceCounting.ReferenceCounted):
    """Produce a thumbnail for a display."""

    def __init__(self, ui, display_item: DisplayItem.DisplayItem):
        super().__init__()
        self._ui = ui
        self._display_item = display_item

        self.thumbnail_updated_event = Event.Event()
        self.__thumbnail_processor = ThumbnailProcessor(display_item)
        self._on_will_delete = None

        def thumbnail_changed():
            thumbnail_processor = self.__thumbnail_processor
            if thumbnail_processor:
                thumbnail_processor.mark_data_dirty()
                thumbnail_processor.recompute(ui)

        self.__display_changed_event_listener = display_item.display_changed_event.listen(thumbnail_changed)

        def thumbnail_updated():
            self.thumbnail_updated_event.fire()

        self.__thumbnail_processor.on_thumbnail_updated = thumbnail_updated

        # initial recompute, if required
        if self.__thumbnail_processor._is_cached_value_dirty:
            self.__thumbnail_processor.recompute(ui)

        def display_item_will_close():
            if self.__thumbnail_processor:
                self.__thumbnail_processor.close()
                self.__thumbnail_processor = None

        self.__display_will_close_listener = display_item.about_to_be_removed_event.listen(display_item_will_close)

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

    def thumbnail_source_for_display_item(self, ui, display_item: DisplayItem.DisplayItem) -> ThumbnailSource:
        """Returned ThumbnailSource must be closed."""
        with self.__lock:
            thumbnail_source = self.__thumbnail_sources.get(display_item)
            if not thumbnail_source:
                thumbnail_source = ThumbnailSource(ui, display_item)
                self.__thumbnail_sources[display_item] = thumbnail_source

                def will_delete(thumbnail_source):
                    del self.__thumbnail_sources[thumbnail_source._display_item]

                thumbnail_source._on_will_delete = will_delete
            else:
                assert thumbnail_source._ui == ui
            return thumbnail_source.add_ref()

    def thumbnail_data_for_display_item(self, display_item: DisplayItem.DisplayItem) -> typing.Optional[numpy.ndarray]:
        thumbnail_source = self.__thumbnail_sources.get(display_item) if display_item else None
        if thumbnail_source:
            return thumbnail_source.thumbnail_data
        return None
