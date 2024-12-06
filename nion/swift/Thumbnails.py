"""
    Contains classes related to thumbnail generation.
"""

from __future__ import annotations

# standard libraries
import concurrent.futures
import functools
import threading
import typing
import uuid
import weakref

# third-party libraries
import numpy
import numpy.typing

# local libraries
from nion.swift import DisplayPanel
from nion.swift.model import Utility
from nion.swift.model import DisplayItem
from nion.ui import DrawingContext
from nion.ui import UserInterface
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import ReferenceCounting

_NDArray = numpy.typing.NDArray[typing.Any]


class ThumbnailSource:
    """Produce a thumbnail for a display."""
    _executor = concurrent.futures.ThreadPoolExecutor()

    def __init__(self, ui: UserInterface.UserInterface, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()
        self._ui = ui
        self._display_item = display_item

        self.width = 256
        self.height = 256

        self.thumbnail_updated_event = Event.Event()

        self.__display_item = display_item
        self.__recompute_lock = threading.RLock()
        self.__recompute_future: typing.Optional[concurrent.futures.Future[typing.Any]] = None
        # the cache is used to store the thumbnail data persistently. for performance, it is ideal
        # to minimize calling it and instead use the cached value in this class.
        self.__cache = self.__display_item._display_cache
        self.__cache_property_name = "thumbnail_data"
        self.__cache_properties_known = False
        self.__cache_thumbnail_data: typing.Optional[_NDArray] = None
        self.__cache_is_dirty = False

        self.thumbnail_dirty_event = Event.Event()  # for testing

        self.__display_changed_event_listener = display_item.display_changed_event.listen(ReferenceCounting.weak_partial(ThumbnailSource.__thumbnail_changed, self))
        self.__graphics_changed_event_listener = display_item.graphics_changed_event.listen(ReferenceCounting.weak_partial(ThumbnailSource.__graphics_changed, self))

        # initial recompute, if required
        self.__recompute_on_thread()

        self.__display_will_close_listener = display_item.display_item_will_close_event.listen(ReferenceCounting.weak_partial(ThumbnailSource.__display_item_will_close, self))

    def __read_cache_properties(self) -> None:
        if not self.__cache_properties_known:
            self.__cache_thumbnail_data = typing.cast(typing.Optional[_NDArray], self.__cache.get_cached_value(self.__display_item, self.__cache_property_name)) if self.__display_item else None
            self.__cache_is_dirty = self.__cache.is_cached_value_dirty(self.__display_item, self.__cache_property_name) if self.__display_item else False
            self.__cache_properties_known = True
            self.thumbnail_updated_event.fire()

    def __thumbnail_changed(self) -> None:
        self.__cache.set_cached_value_dirty(self.__display_item, self.__cache_property_name)
        self.thumbnail_dirty_event.fire()
        self.__cache_is_dirty = True
        self.__cache_properties_known = True
        self.__recompute_on_thread()

    def __recompute_on_thread(self) -> None:
        with self.__recompute_lock:
            if not self.__recompute_future or self.__recompute_future.done():
                self.__recompute_future = self._executor.submit(self.__recompute_data_if_needed)

    def __graphics_changed(self, graphic_selection: DisplayItem.GraphicSelection) -> None:
        self.__thumbnail_changed()

    def __display_item_will_close(self) -> None:
        # the display item is closing, so these messages should not be triggered, but just in case...
        self.__display_item_about_to_close_listener = typing.cast(typing.Any, None)
        self.__display_item = typing.cast(typing.Any, None)
        self.__display_changed_event_listener = typing.cast(typing.Any, None)
        self.__graphics_changed_event_listener = typing.cast(typing.Any, None)
        # shut down the thread, if any. avoid deadlock.
        recompute_future: typing.Optional[concurrent.futures.Future[typing.Any]] = None
        with self.__recompute_lock:
            if self.__recompute_future and not self.__recompute_future.done():
                self.__recompute_future.cancel()
                recompute_future = self.__recompute_future
        if recompute_future:
            try:
                concurrent.futures.wait([recompute_future], timeout=10.0)
            except concurrent.futures.CancelledError:
                pass

    @property
    def thumbnail_data(self) -> typing.Optional[_NDArray]:
        return self.__cache_thumbnail_data

    def __recompute_data_if_needed(self) -> None:
        self.__read_cache_properties()
        if self._is_thumbnail_dirty:
            self.recompute_data()

    def recompute_data(self) -> None:
        """Compute the data associated with this processor.

        This method is thread safe and may take a long time to return. It should not be called from
         the UI thread. Upon return, the results will be calculated with the latest data available
         and the cache will not be marked dirty.
        """
        ui = self._ui
        with self.__recompute_lock:
            try:
                display_item = self.__display_item
                if display_item.display_data_shape and len(display_item.display_data_shape) == 2:
                    pixel_shape = Geometry.IntSize(height=512, width=512)
                else:
                    pixel_shape = Geometry.IntSize(height=308, width=512)
                drawing_context = DisplayPanel.preview(DisplayPanel.DisplayPanelUISettings(ui), display_item, pixel_shape)
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
            self.__cache_thumbnail_data = calculated_data
            self.__cache_is_dirty = False
            self.__cache_properties_known = True
            self.__cache.set_cached_value(self.__display_item, self.__cache_property_name, calculated_data)
        self.thumbnail_updated_event.fire()

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

    def clean(self) -> None:
        with self.__lock:
            for uuid, thumbnail_source in list(self.__thumbnail_sources.items()):
                if not thumbnail_source._is_valid:
                    del self.__thumbnail_sources[uuid]

    def thumbnail_source_for_display_item(self, ui: UserInterface.UserInterface, display_item: DisplayItem.DisplayItem) -> ThumbnailSource:
        """Returned ThumbnailSource must be closed."""
        with self.__lock:
            self.clean()
            thumbnail_source = self.__thumbnail_sources.get(display_item.uuid)
            if not thumbnail_source:
                thumbnail_source = ThumbnailSource(ui, display_item)
                self.__thumbnail_sources[display_item.uuid] = thumbnail_source
            else:
                assert thumbnail_source._ui == ui
            return thumbnail_source

    def thumbnail_data_for_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> typing.Optional[_NDArray]:
        with self.__lock:
            self.clean()
            thumbnail_source = self.__thumbnail_sources.get(display_item.uuid) if display_item else None
            if thumbnail_source:
                return thumbnail_source.thumbnail_data
            return None
