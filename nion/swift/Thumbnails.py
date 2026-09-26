"""
    Contains classes related to thumbnail generation.
"""

from __future__ import annotations

# standard libraries
import concurrent.futures
import threading
import time
import typing
import uuid

# third-party libraries
import numpy
import numpy.typing

# local libraries
from nion.swift import DisplayPanel
from nion.swift.model import DisplayInfo
from nion.swift.model import DisplayItem
from nion.swift.model import UISettings
from nion.swift.model import Utility
from nion.ui import Bitmap
from nion.ui import DrawingContext
from nion.ui import UserInterface
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ReferenceCounting
from nion.utils import Stream

_NDArray = numpy.typing.NDArray[typing.Any]


class ThumbnailSource(Stream.ValueStream[Bitmap.Bitmap]):
    """Produce a thumbnail for a display."""
    _executor = concurrent.futures.ThreadPoolExecutor()

    # minimum seconds between the starts of successive recomputes for one display item. a live display item changes
    # every frame, and each recompute holds the interpreter lock for part of its duration, delaying other threads such
    # as acquisition; a thumbnail does not need to update faster than this. matches HistogramProcessor.
    _minimum_recompute_interval = 0.25

    def __init__(self, ui: UserInterface.UserInterface, display_item: DisplayItem.DisplayItem, will_close_fn: typing.Callable[[uuid.UUID], None], *, _suppress_recompute: bool = False) -> None:
        super().__init__()
        self._ui = ui
        self._display_item = display_item
        self.__will_close_fn = will_close_fn
        self.__suppress_recompute = _suppress_recompute

        self.width = 256
        self.height = 256

        self.__display_item = display_item
        # the recompute lock protects the recompute scheduling fields and the cache fields below.
        self.__recompute_lock = threading.RLock()
        self.__recompute_future: typing.Optional[concurrent.futures.Future[typing.Any]] = None
        self.__recompute_timer: threading.Timer | None = None
        self.__recompute_start_time: float | None = None
        self.__is_closing = False
        # incremented each time the thumbnail is marked dirty so that a recompute which started before the change does
        # not mark the result clean, and so that a trailing recompute is scheduled.
        self.__dirty_generation = 0
        # the cache is used to store the thumbnail data persistently. for performance, it is ideal
        # to minimize calling it and instead use the cached value in this class.
        self.__cache = self.__display_item._display_cache
        self.__cache_property_name = "thumbnail_data"
        self.__cache_properties_known = False
        self.__cache_thumbnail_data: typing.Optional[_NDArray] = None
        self.__cache_is_dirty = False

        self.thumbnail_dirty_event = Event.Event()  # for testing

        self.__display_info_stream_action = Stream.ValueStreamAction(self.__display_item.display_info_stream, ReferenceCounting.weak_partial(self.__class__.__display_info_changed, self))

        # initial recompute, if required
        self.__recompute_on_thread()

        self.__display_will_close_listener = display_item.display_item_will_close_event.listen(ReferenceCounting.weak_partial(ThumbnailSource.__display_item_will_close, self))

    def __read_cache_properties(self) -> None:
        if not self.__cache_properties_known:
            self.__cache_thumbnail_data = typing.cast(typing.Optional[_NDArray], self.__cache.get_cached_value(self.__display_item, self.__cache_property_name)) if self.__display_item else None
            self.__cache_is_dirty = self.__cache.is_cached_value_dirty(self.__display_item, self.__cache_property_name) if self.__display_item else False
            self.__cache_properties_known = True
            self.value = Bitmap.Bitmap(rgba_bitmap_data=self.thumbnail_data)

    def __display_info_changed(self, display_info: DisplayInfo.DisplayInfo | None) -> None:
        self.__cache.set_cached_value_dirty(self.__display_item, self.__cache_property_name)
        self.thumbnail_dirty_event.fire()
        with self.__recompute_lock:
            self.__dirty_generation += 1
            self.__cache_is_dirty = True
            self.__cache_properties_known = True
            self.__recompute_on_thread()

    def __recompute_on_thread(self) -> None:
        """Request a recompute on a thread.

        At most one recompute per display item is in flight or scheduled. A request made while one is in flight is
        satisfied by a trailing recompute when it finishes. Successive recomputes start at least the minimum interval
        apart.
        """
        with self.__recompute_lock:
            if self.__recompute_future and not self.__recompute_future.done():
                return
            if self.__recompute_timer:
                return
            self.__schedule_recompute()

    def __schedule_recompute(self) -> None:
        # the caller holds the recompute lock and ensures no recompute is in flight or scheduled.
        if self.__suppress_recompute or self.__is_closing:
            return
        delay = 0.0
        if self.__recompute_start_time is not None:
            delay = self.__recompute_start_time + self._minimum_recompute_interval - time.monotonic()
        if delay > 0.0:
            self.__recompute_timer = threading.Timer(delay, ReferenceCounting.weak_partial(ThumbnailSource.__submit_scheduled_recompute, self))
            self.__recompute_timer.daemon = True
            self.__recompute_timer.start()
        else:
            self.__recompute_future = self._executor.submit(self.__recompute_data_if_needed)

    def __submit_scheduled_recompute(self) -> None:
        # called on the timer thread.
        with self.__recompute_lock:
            self.__recompute_timer = None
            self.__schedule_recompute()

    def __display_item_will_close(self) -> None:
        # the display item is closing, so these messages should not be triggered, but just in case...
        self.__display_item_about_to_close_listener = typing.cast(typing.Any, None)
        self.__display_info_stream_action = typing.cast(typing.Any, None)
        # shut down the thread, if any. avoid deadlock.
        # note: the __display_item still has to be valid to shut down the thread, in case it is still running.
        # clear the display item after shutting down the thread.
        recompute_future: typing.Optional[concurrent.futures.Future[typing.Any]] = None
        with self.__recompute_lock:
            self.__is_closing = True
            if self.__recompute_timer:
                self.__recompute_timer.cancel()
                self.__recompute_timer = None
            if self.__recompute_future and not self.__recompute_future.done():
                self.__recompute_future.cancel()
                recompute_future = self.__recompute_future
        if recompute_future:
            try:
                concurrent.futures.wait([recompute_future], timeout=10.0)
            except concurrent.futures.CancelledError:
                pass
        self.__will_close_fn(self.__display_item.uuid)
        self.__will_close_fn = typing.cast(typing.Any, None)  # break the reference cycle for faster garbage collection
        self.__display_item = typing.cast(typing.Any, None)

    @property
    def thumbnail_data(self) -> typing.Optional[_NDArray]:
        return self.__cache_thumbnail_data

    def __recompute_data_if_needed(self) -> None:
        # called on an executor thread.
        with self.__recompute_lock:
            self.__recompute_start_time = time.monotonic()
            dirty_generation = self.__dirty_generation
        try:
            self.__read_cache_properties()
            if self._is_thumbnail_dirty:
                self.recompute_data()
        finally:
            # if the thumbnail was marked dirty while this recompute was running, schedule a trailing recompute so the
            # thumbnail is brought up to date even if nothing further changes. a failed recompute with no further
            # change is not retried.
            with self.__recompute_lock:
                self.__recompute_future = None
                if self.__cache_is_dirty and self.__dirty_generation != dirty_generation and not self.__recompute_timer:
                    self.__schedule_recompute()

    def recompute_data(self) -> None:
        """Compute the data associated with this processor.

        This method is thread safe and may take a long time to return. It should not be called from
         the UI thread. Upon return, the results will be calculated with the latest data available
         and the cache will not be marked dirty, unless the display item changed during the computation.
        """
        ui = self._ui
        with self.__recompute_lock:
            dirty_generation = self.__dirty_generation
        try:
            display_item = self.__display_item
            display_info = display_item.display_info
            display_calibration_info = display_info.display_calibration_info
            display_data_shape = display_calibration_info.display_data_shape if display_calibration_info else None
            if display_data_shape and len(display_data_shape) == 2:
                pixel_shape = Geometry.IntSize(height=512, width=512)
            else:
                pixel_shape = Geometry.IntSize(height=308, width=512)
            drawing_metrics = UISettings.DrawingMetrics(ui_settings=DisplayPanel.DisplayPanelUISettings(ui), ppi=96.0)
            display_style = UISettings.DisplayStyle()
            drawing_context = DisplayPanel.preview(drawing_metrics, display_style, display_item, pixel_shape)
            thumbnail_drawing_context = DrawingContext.DrawingContext()
            thumbnail_drawing_context.scale(self.width / 512, self.height / 512)
            thumbnail_drawing_context.translate(0, (pixel_shape.width - pixel_shape.height) * 0.5)
            thumbnail_drawing_context.add(drawing_context)
            calculated_data = ui.create_rgba_image(thumbnail_drawing_context, self.width, self.height)
        except Exception as e:
            import traceback
            traceback.print_exc()
            traceback.print_stack()
            raise
        if calculated_data is None:
            calculated_data = numpy.zeros((self.height, self.width), dtype=numpy.uint32)
        with self.__recompute_lock:
            # the thumbnail stays dirty if it was marked dirty after this computation read the display item.
            is_dirty = self.__dirty_generation != dirty_generation
            self.__cache_thumbnail_data = calculated_data
            self.__cache_is_dirty = is_dirty
            self.__cache_properties_known = True
            self.__cache.set_cached_value(self.__display_item, self.__cache_property_name, calculated_data, dirty=is_dirty)
        self.value = Bitmap.Bitmap(rgba_bitmap_data=self.thumbnail_data)

    @property
    def _is_thumbnail_dirty(self) -> bool:
        return self.__cache_is_dirty

    @property
    def _is_valid(self) -> bool:
        return self.__display_item is not None


class ThumbnailManager(metaclass=Utility.Singleton):
    """Manages thumbnail sources for displays."""

    def __init__(self) -> None:
        self.__thumbnail_sources: typing.Dict[uuid.UUID, ThumbnailSource] = dict()
        self.__lock = threading.RLock()

    def reset(self) -> None:
        with self.__lock:
            self.__thumbnail_sources.clear()

    def thumbnail_source_for_display_item(self, ui: UserInterface.UserInterface, display_item: DisplayItem.DisplayItem, *, _suppress_recompute: bool = False) -> ThumbnailSource:
        """Return a shared ThumbnailSource, cached per display item and closed automatically when it closes."""
        with self.__lock:
            thumbnail_source = self.__thumbnail_sources.get(display_item.uuid)
            if not thumbnail_source:
                def will_close_fn(display_item_uuid: uuid.UUID) -> None:
                    with self.__lock:
                        del self.__thumbnail_sources[display_item_uuid]

                thumbnail_source = ThumbnailSource(ui, display_item, will_close_fn, _suppress_recompute=_suppress_recompute)
                self.__thumbnail_sources[display_item.uuid] = thumbnail_source
            else:
                assert thumbnail_source._ui == ui
            return thumbnail_source

    def thumbnail_data_for_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> typing.Optional[_NDArray]:
        with self.__lock:
            thumbnail_source = self.__thumbnail_sources.get(display_item.uuid) if display_item else None
            if thumbnail_source:
                return thumbnail_source.thumbnail_data
            return None
