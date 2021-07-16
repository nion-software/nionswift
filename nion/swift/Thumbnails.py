"""
    Contains classes related to thumbnail generation.
"""

# standard libraries
import concurrent.futures
import functools
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


class SingleItemDispatcher:
    def __init__(self, *, executor: typing.Optional[concurrent.futures.ThreadPoolExecutor] = None, minimum_period: float = 0.0):
        self.__executor = executor or concurrent.futures.ThreadPoolExecutor()
        self.__minimum_period = minimum_period
        self.__is_dispatching_lock = threading.RLock()
        self.__is_dispatch_pending = False
        self.__dispatch_future: typing.Optional[concurrent.futures.Future] = None
        self.__dispatch_thread_cancel = threading.Event()
        self.__cached_value_time = 0
        self.on_computed: typing.Optional[typing.Callable[[], None]] = None

    def close(self) -> None:
        self.on_computed = None
        recompute_future = self.__dispatch_future  # avoid race by using local
        if recompute_future:
            self.__dispatch_thread_cancel.set()
            concurrent.futures.wait([recompute_future])

    def __dispatch_task(self, fn: typing.Callable[[], None]) -> None:
        while True:
            try:
                if self.__dispatch_thread_cancel.wait(0.05):  # gather changes and helps tests run faster
                    return
                minimum_time = self.__minimum_period
                current_time = time.time()
                if current_time < self.__cached_value_time + minimum_time:
                    if self.__dispatch_thread_cancel.wait(self.__cached_value_time + minimum_time - current_time):
                        return
                self.__is_dispatch_pending = False  # any pending calls up to this point will be realized in the recompute
                fn()
            finally:
                with self.__is_dispatching_lock:
                    # the only way the thread can end is if not pending within lock.
                    # recompute_future can only be set within lock.
                    if not self.__is_dispatch_pending:
                        self.__dispatch_future = None
                        break

    def dispatch(self, fn: typing.Callable[[], None]) -> concurrent.futures.Future:
        # dispatch the function on a thread.
        # if already executing, ensure the thread dispatch again.
        # may be called on the main thread or a thread - must return quickly in both cases.
        with self.__is_dispatching_lock:
            # in case thread is already running, set pending.
            # the only way the thread can end is if not pending within lock.
            # dispatch_future can only be set within lock.
            self.__is_dispatch_pending = True
            if not self.__dispatch_future:
                self.__dispatch_future = self.__executor.submit(self.__dispatch_task, fn)
            return self.__dispatch_future


class ThumbnailProcessor:
    """Processes thumbnails for a display in a thread."""

    def __init__(self, display_item: DisplayItem.DisplayItem):
        self.__display_item = display_item
        self.__recompute_lock = threading.RLock()
        self.__dispatcher = SingleItemDispatcher(minimum_period=0.5)
        self.__display_item_about_to_close_listener = self.__display_item.about_to_close_event.listen(self.__about_to_close_display_item)
        self.__cache = self.__display_item._display_cache
        self.__cache_property_name = "thumbnail_data"
        self.width = 256
        self.height = 256
        self.on_thumbnail_updated = None

    def close(self):
        self.on_thumbnail_updated = None
        if self.__dispatcher:
            self.__dispatcher.close()
        self.__dispatcher = None
        self.__display_item = None

    def __about_to_close_display_item(self) -> None:
        self.close()

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

    def recompute(self, ui: UserInterface.UserInterface) -> None:
        self.__dispatcher.dispatch(functools.partial(self.recompute_data, ui))

    def recompute_data(self, ui: UserInterface.UserInterface) -> None:
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
        if callable(self.on_thumbnail_updated):
            self.on_thumbnail_updated()


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

    def about_to_delete(self) -> None:
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
        super().about_to_delete()

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

                # note: do not add_ref. the _on_will_delete is called when the thumbnail_source is about to
                # delete and takes care of removing it from the global list.
                self.__thumbnail_sources[display_item] = thumbnail_source

                def will_delete(thumbnail_source):
                    self.__thumbnail_sources.pop(thumbnail_source._display_item)

                thumbnail_source._on_will_delete = will_delete
            else:
                assert thumbnail_source._ui == ui
            return thumbnail_source

    def thumbnail_data_for_display_item(self, display_item: DisplayItem.DisplayItem) -> typing.Optional[numpy.ndarray]:
        thumbnail_source = self.__thumbnail_sources.get(display_item) if display_item else None
        if thumbnail_source:
            return thumbnail_source.thumbnail_data
        return None
