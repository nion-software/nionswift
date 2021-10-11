"""
    Contains classes related to thumbnail generation.
"""

from __future__ import annotations

# standard libraries
import functools
import threading
import typing
import uuid
import weakref

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
from nion.utils import ThreadPool

_NDArray = typing.Any  # numpy 1.21+
_ThumbnailSourceWeakRef = typing.Any  # Python 3.9+


class ThumbnailProcessor:
    """Processes thumbnails for a display in a thread."""

    def __init__(self, display_item: DisplayItem.DisplayItem):
        self.__display_item = display_item
        self.__recompute_lock = threading.RLock()
        self.__dispatcher = ThreadPool.SingleItemDispatcher(minimum_period=0.5)
        self.__display_item_about_to_close_listener = self.__display_item.about_to_close_event.listen(self.__about_to_close_display_item)
        self.__cache = self.__display_item._display_cache
        self.__cache_property_name = "thumbnail_data"
        self.width = 256
        self.height = 256
        self.on_thumbnail_updated: typing.Optional[typing.Callable[[], None]] = None

    def close(self) -> None:
        self.on_thumbnail_updated = None
        self.__dispatcher.close()
        self.__dispatcher = typing.cast(typing.Any, None)
        self.__display_item = typing.cast(typing.Any, None)
        self.__display_item_about_to_close_listener.close()
        self.__display_item_about_to_close_listener = typing.cast(typing.Any, None)

    def __about_to_close_display_item(self) -> None:
        self.close()

    # used internally and for testing
    @property
    def _is_cached_value_dirty(self) -> bool:
        return self.__cache.is_cached_value_dirty(self.__display_item, self.__cache_property_name)

    # thread safe
    def mark_data_dirty(self) -> None:
        """ Called from item to indicate its data or metadata has changed."""
        self.__cache.set_cached_value_dirty(self.__display_item, self.__cache_property_name)

    def __get_cached_value(self) -> typing.Optional[_NDArray]:
        return self.__cache.get_cached_value(self.__display_item, self.__cache_property_name)

    def get_cached_data(self) -> typing.Optional[_NDArray]:
        """Return the cached data for this processor.

        This method is thread safe and always returns quickly, using the cached data.
        """
        return self.__get_cached_value()

    def __get_calculated_data(self, ui: UserInterface.UserInterface) -> typing.Optional[DrawingContext.RGBA32Type]:
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

    def __init__(self, ui: UserInterface.UserInterface, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()
        self._ui = ui
        self._display_item = display_item

        self.thumbnail_updated_event = Event.Event()
        self.__thumbnail_processor = ThumbnailProcessor(display_item)

        def thumbnail_changed() -> None:
            thumbnail_processor = self.__thumbnail_processor
            if thumbnail_processor:
                thumbnail_processor.mark_data_dirty()
                thumbnail_processor.recompute(ui)

        self.__display_changed_event_listener = display_item.display_changed_event.listen(thumbnail_changed)

        def thumbnail_updated() -> None:
            self.thumbnail_updated_event.fire()

        self.__thumbnail_processor.on_thumbnail_updated = thumbnail_updated

        # initial recompute, if required
        if self.__thumbnail_processor._is_cached_value_dirty:
            self.__thumbnail_processor.recompute(ui)

        def display_item_will_close() -> None:
            if self.__thumbnail_processor:
                self.__thumbnail_processor.close()
                self.__thumbnail_processor = typing.cast(typing.Any, None)

        self.__display_will_close_listener = display_item.about_to_be_removed_event.listen(display_item_will_close)

    def about_to_delete(self) -> None:
        self.__display_will_close_listener.close()
        self.__display_will_close_listener = typing.cast(typing.Any, None)
        if self.__thumbnail_processor:
            self.__thumbnail_processor.close()
            self.__thumbnail_processor = typing.cast(typing.Any, None)
        self.__display_changed_event_listener.close()
        self.__display_changed_event_listener = typing.cast(typing.Any, None)
        super().about_to_delete()

    def add_ref(self) -> ThumbnailSource:
        super().add_ref()
        return self

    @property
    def thumbnail_data(self) -> typing.Optional[_NDArray]:
        return self.__thumbnail_processor.get_cached_data() if self.__thumbnail_processor else None

    def recompute_data(self) -> None:
        self.__thumbnail_processor.recompute_data(self._ui)

    # used for testing
    @property
    def _is_thumbnail_dirty(self) -> bool:
        return self.__thumbnail_processor._is_cached_value_dirty


class ThumbnailManager(metaclass=Utility.Singleton):
    """Manages thumbnail sources for displays."""

    def __init__(self) -> None:
        self.__thumbnail_sources: typing.Dict[uuid.UUID, _ThumbnailSourceWeakRef] = dict()
        self.__lock = threading.RLock()

    def thumbnail_sources(self) -> typing.Dict[uuid.UUID, _ThumbnailSourceWeakRef]:
        return self.__thumbnail_sources

    def thumbnail_source_for_display_item(self, ui: UserInterface.UserInterface, display_item: DisplayItem.DisplayItem) -> ThumbnailSource:
        """Returned ThumbnailSource must be closed."""
        with self.__lock:
            thumbnail_source_ref = self.__thumbnail_sources.get(display_item.uuid)
            thumbnail_source = thumbnail_source_ref() if thumbnail_source_ref else None
            if not thumbnail_source:
                thumbnail_source = ThumbnailSource(ui, display_item)
                self.__thumbnail_sources[display_item.uuid] = weakref.ref(thumbnail_source)
                weakref.finalize(thumbnail_source, self.__thumbnail_sources.pop, display_item.uuid)
            else:
                assert thumbnail_source._ui == ui
            return typing.cast(ThumbnailSource, thumbnail_source)

    def thumbnail_data_for_display_item(self, display_item: typing.Optional[DisplayItem.DisplayItem]) -> typing.Optional[_NDArray]:
        with self.__lock:
            thumbnail_source_ref = self.__thumbnail_sources.get(display_item.uuid) if display_item else None
            thumbnail_source = thumbnail_source_ref() if thumbnail_source_ref else None
            if thumbnail_source:
                return thumbnail_source.thumbnail_data
            return None
