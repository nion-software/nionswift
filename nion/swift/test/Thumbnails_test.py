# standard libraries
import contextlib
import logging
import threading
import time
import typing
import unittest
import uuid

import numpy

# local libraries
from nion.swift import DataItemThumbnailWidget
from nion.swift import MimeTypes
from nion.swift import Thumbnails
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.test import TestContext
from nion.ui import Bitmap
from nion.ui import DrawingContext
from nion.ui import TestUI
from nion.utils import Geometry
from nion.utils import Stream


class TestThumbnailsClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()

    def tearDown(self):
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def test_data_item_display_thumbnail_source_produces_data_item_mime_data(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.random.randn(8, 8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "image"
            thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(document_controller.ui)
            with contextlib.closing(thumbnail_source):
                finished = threading.Event()
                thumbnail_source.set_display_item(display_item)  # this will trigger changed callback with None
                def thumbnail_bitmap_changed(bitmap: Bitmap.Bitmap | None) -> None:
                    if bitmap.rgba_bitmap_data is not None:
                        finished.set()
                thumbnail_source.on_thumbnail_bitmap_changed = thumbnail_bitmap_changed  # watch for actual data
                # the thumbnail is sent on the main thread, so run the event loop while waiting.
                end_time = time.monotonic() + 1.0
                while not finished.is_set() and time.monotonic() < end_time:
                    document_controller.periodic()
                    time.sleep(0.01)
                mime_data = document_controller.ui.create_mime_data()
                valid, thumbnail = thumbnail_source.populate_mime_data_for_drag(mime_data, Geometry.IntSize(64, 64))
                self.assertTrue(valid)
                self.assertIsNotNone(thumbnail)
                self.assertTrue(mime_data.has_format(MimeTypes.DISPLAY_ITEM_MIME_TYPE))

    def test_thumbnail_marked_dirty_when_display_layers_change(self):
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.ones((8,)))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self._test_setup.app.ui, display_item)
            thumbnail_source.recompute_data()
            thumbnail_source.thumbnail_data
            # here the data should be computed and the thumbnail should not be dirty
            self.assertFalse(display_item._display_cache.is_cached_value_dirty(display_item, "thumbnail_data"))
            # now the source data changes and the inverted data needs computing.
            # the thumbnail should also be dirty.
            thumbnail_dirty = False

            def handle_thumbnail_dirty() -> None:
                nonlocal thumbnail_dirty
                thumbnail_dirty = True

            listener = thumbnail_source.thumbnail_dirty_event.listen(handle_thumbnail_dirty)
            display_item._set_display_layer_property(0, "fill_color", "teal")
            document_model.recompute_all()
            # this is a race condition. the thumbnail thread may clear the dirty flag before we check it.
            # so use the event instead.
            self.assertTrue(thumbnail_dirty)

    def test_thumbnail_shows_final_data_when_data_changes_during_recompute_and_then_stops(self):
        # a user looking at the thumbnail after acquisition stops must see the last frame, even if that frame arrived
        # while the previous thumbnail was being computed and nothing changed afterwards.

        class DataValueUserInterface(TestUI.UserInterface):
            """A user interface which renders a thumbnail filled with the first value of the drawn data.

            While the gate is closed, rendering signals that it has started and then waits for the gate to open.
            """

            def __init__(self) -> None:
                super().__init__()
                self.gate = threading.Event()
                self.gate.set()
                self.render_started = threading.Event()

            def create_rgba_image(self, drawing_context: DrawingContext.DrawingContext, width: int, height: int) -> DrawingContext.RGBA32Type | None:
                value = next((int(command[3][0, 0]) for command in drawing_context.commands if command[0] == "data"), 0)
                if not self.gate.is_set():
                    self.render_started.set()
                    self.gate.wait(10.0)
                return numpy.full((height, width), value, dtype=numpy.uint32)

        def wait_for_thumbnail_value(thumbnail_source: Thumbnails.ThumbnailSource, value: int) -> int | None:
            end_time = time.monotonic() + 5.0
            while time.monotonic() < end_time:
                thumbnail_data = thumbnail_source.thumbnail_data
                if thumbnail_data is not None and thumbnail_data[0, 0] == value:
                    break
                time.sleep(0.01)
            thumbnail_data = thumbnail_source.thumbnail_data
            return int(thumbnail_data[0, 0]) if thumbnail_data is not None else None

        ui = DataValueUserInterface()
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.full((8, 8), 1, dtype=numpy.float32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(ui, display_item)
            self.assertEqual(1, wait_for_thumbnail_value(thumbnail_source, 1))
            # hold the next recompute in the middle of rendering the second frame, deliver the third frame, then let it finish.
            ui.gate.clear()
            data_item.set_data(numpy.full((8, 8), 2, dtype=numpy.float32))
            self.assertTrue(ui.render_started.wait(5.0))
            data_item.set_data(numpy.full((8, 8), 3, dtype=numpy.float32))
            ui.gate.set()
            self.assertEqual(3, wait_for_thumbnail_value(thumbnail_source, 3))

    def test_thumbnail_computed_on_thread_is_sent_on_main_thread(self):
        # listeners such as the data panel update canvas items when a thumbnail arrives; doing so from the thread
        # computing the thumbnail races with the main thread and can fail while items are being removed.
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.ones((8, 8), dtype=numpy.float32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(document_controller.ui, display_item)
            sending_threads = list[threading.Thread]()

            def handle_thumbnail(thumbnail_bitmap: Bitmap.Bitmap | None) -> None:
                sending_threads.append(threading.current_thread())

            thumbnail_source_action = Stream.ValueStreamAction(thumbnail_source, handle_thumbnail)
            # changing the data recomputes the thumbnail on a thread.
            data_item.set_data(numpy.full((8, 8), 2, dtype=numpy.float32))
            end_time = time.monotonic() + 5.0
            while not sending_threads and time.monotonic() < end_time:
                document_controller.periodic()
                time.sleep(0.01)
            self.assertTrue(sending_threads)
            self.assertEqual({threading.current_thread()}, set(sending_threads))

    def test_thumbnail_from_cache_is_not_redrawn_after_reload_with_threaded_display(self):
        # reloading a project shows each cached thumbnail without drawing it again.

        class DataValueUserInterface(TestUI.UserInterface):
            """A user interface which renders a thumbnail filled with the first value of the drawn data."""

            def create_rgba_image(self, drawing_context: DrawingContext.DrawingContext, width: int, height: int) -> DrawingContext.RGBA32Type | None:
                value = next((int(command[3][0, 0]) for command in drawing_context.commands if command[0] == "data"), 0)
                return numpy.full((height, width), value, dtype=numpy.uint32)

        def run_event_loop_until(document_model: DocumentModel.DocumentModel, condition: typing.Callable[[], bool]) -> None:
            end_time = time.monotonic() + 5.0
            while not condition() and time.monotonic() < end_time:
                document_model.event_loop.stop()
                document_model.event_loop.run_forever()
                time.sleep(0.01)

        ui = DataValueUserInterface()
        with TestContext.MemoryProfileContext(threaded_display=True) as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.full((8, 8), 1, dtype=numpy.float32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(ui, display_item)
                run_event_loop_until(document_model, lambda: thumbnail_source.thumbnail_data is not None and not thumbnail_source._is_thumbnail_dirty)
                self.assertFalse(thumbnail_source._is_thumbnail_dirty)
                thumbnail_source = None
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                display_item = document_model.display_items[0]
                thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(ui, display_item)
                dirty_count = 0

                def handle_thumbnail_dirty() -> None:
                    nonlocal dirty_count
                    dirty_count += 1

                thumbnail_dirty_listener = thumbnail_source.thumbnail_dirty_event.listen(handle_thumbnail_dirty)
                run_event_loop_until(document_model, lambda: thumbnail_source.thumbnail_data is not None)
                for _ in range(10):
                    document_model.event_loop.stop()
                    document_model.event_loop.run_forever()
                self.assertEqual(0, dirty_count)
                self.assertFalse(thumbnail_source._is_thumbnail_dirty)
                self.assertEqual(1, int(thumbnail_source.thumbnail_data[0, 0]))
                thumbnail_dirty_listener = None
                thumbnail_source = None

    def test_thumbnail_from_cache_does_not_read_data_after_reload(self):
        # reloading a project shows each cached thumbnail without reading the data, which would make loading slow.

        def run_event_loop_until(document_model: DocumentModel.DocumentModel, condition: typing.Callable[[], bool]) -> None:
            end_time = time.monotonic() + 5.0
            while not condition() and time.monotonic() < end_time:
                document_model.event_loop.stop()
                document_model.event_loop.run_forever()
                time.sleep(0.01)

        ui = TestUI.UserInterface()
        with TestContext.MemoryProfileContext(threaded_display=True) as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.full((8, 8), 1, dtype=numpy.float32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(ui, display_item)
                run_event_loop_until(document_model, lambda: thumbnail_source.thumbnail_data is not None and not thumbnail_source._is_thumbnail_dirty)
                self.assertFalse(thumbnail_source._is_thumbnail_dirty)
                thumbnail_source = None
            data_read_count = 0

            def handle_data_read(data_item_uuid: uuid.UUID) -> None:
                nonlocal data_read_count
                data_read_count += 1

            data_read_listener = profile_context._test_data_read_event.listen(handle_data_read)
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                display_item = document_model.display_items[0]
                thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(ui, display_item)
                run_event_loop_until(document_model, lambda: thumbnail_source.thumbnail_data is not None)
                for _ in range(10):
                    document_model.event_loop.stop()
                    document_model.event_loop.run_forever()
                self.assertIsNotNone(thumbnail_source.thumbnail_data)
                self.assertEqual(0, data_read_count)
                thumbnail_source = None
            data_read_listener = None

    def test_thumbnail_drawn_after_reload_reads_data_once(self):
        # drawing a thumbnail which is not cached reads the data once, since reading it is slow.

        def run_event_loop_until(document_model: DocumentModel.DocumentModel, condition: typing.Callable[[], bool]) -> None:
            end_time = time.monotonic() + 5.0
            while not condition() and time.monotonic() < end_time:
                document_model.event_loop.stop()
                document_model.event_loop.run_forever()
                time.sleep(0.01)

        ui = TestUI.UserInterface()
        with TestContext.MemoryProfileContext(threaded_display=True) as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                document_model.append_data_item(DataItem.DataItem(numpy.full((8, 8), 1, dtype=numpy.float32)))
            data_read_count = 0

            def handle_data_read(data_item_uuid: uuid.UUID) -> None:
                nonlocal data_read_count
                data_read_count += 1

            data_read_listener = profile_context._test_data_read_event.listen(handle_data_read)
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                display_item = document_model.display_items[0]
                thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(ui, display_item)
                run_event_loop_until(document_model, lambda: thumbnail_source.thumbnail_data is not None and not thumbnail_source._is_thumbnail_dirty)
                self.assertFalse(thumbnail_source._is_thumbnail_dirty)
                self.assertEqual(1, data_read_count)
                thumbnail_source = None
            data_read_listener = None

    def test_thumbnail_is_redrawn_after_reload_when_data_changed_without_thumbnail(self):
        # data changed while its thumbnail is not shown, such as by a script, shows the new data after a reload.

        class DataValueUserInterface(TestUI.UserInterface):
            """A user interface which renders a thumbnail filled with the first value of the drawn data."""

            def create_rgba_image(self, drawing_context: DrawingContext.DrawingContext, width: int, height: int) -> DrawingContext.RGBA32Type | None:
                value = next((int(command[3][0, 0]) for command in drawing_context.commands if command[0] == "data"), 0)
                return numpy.full((height, width), value, dtype=numpy.uint32)

        def wait_for_thumbnail_value(thumbnail_source: Thumbnails.ThumbnailSource, value: int) -> int | None:
            end_time = time.monotonic() + 5.0
            while time.monotonic() < end_time:
                thumbnail_data = thumbnail_source.thumbnail_data
                if thumbnail_data is not None and thumbnail_data[0, 0] == value:
                    break
                time.sleep(0.01)
            thumbnail_data = thumbnail_source.thumbnail_data
            return int(thumbnail_data[0, 0]) if thumbnail_data is not None else None

        ui = DataValueUserInterface()
        with TestContext.create_memory_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.full((8, 8), 1, dtype=numpy.float32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(ui, display_item)
                self.assertEqual(1, wait_for_thumbnail_value(thumbnail_source, 1))
                thumbnail_source = None
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                document_model.data_items[0].set_data(numpy.full((8, 8), 2, dtype=numpy.float32))
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                display_item = document_model.display_items[0]
                thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(ui, display_item)
                self.assertEqual(2, wait_for_thumbnail_value(thumbnail_source, 2))
                thumbnail_source = None

    def test_thumbnail_from_cache_is_not_redrawn_after_reload_when_display_layers_get_new_identity(self):
        # display layers get a new identity each time a project is loaded; the thumbnails are still shown from the cache
        # without drawing them again.

        class DrawCountingUserInterface(TestUI.UserInterface):
            """A user interface which counts the thumbnails it draws."""

            def __init__(self) -> None:
                super().__init__()
                self.draw_count = 0

            def create_rgba_image(self, drawing_context: DrawingContext.DrawingContext, width: int, height: int) -> DrawingContext.RGBA32Type | None:
                self.draw_count += 1
                return numpy.zeros((height, width), dtype=numpy.uint32)

        def wait_for_thumbnail(thumbnail_source: Thumbnails.ThumbnailSource) -> None:
            end_time = time.monotonic() + 5.0
            while (thumbnail_source.thumbnail_data is None or thumbnail_source._is_thumbnail_dirty) and time.monotonic() < end_time:
                time.sleep(0.01)

        ui = DrawCountingUserInterface()
        with TestContext.create_memory_context() as profile_context:
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                data_item = DataItem.DataItem(numpy.ones((8, 8), dtype=numpy.float32))
                document_model.append_data_item(data_item)
                display_item = document_model.get_display_item_for_data_item(data_item)
                thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(ui, display_item)
                wait_for_thumbnail(thumbnail_source)
                thumbnail_source = None
            self.assertEqual(1, ui.draw_count)
            document_model = profile_context.create_document_model(auto_close=False)
            with document_model.ref():
                display_item = document_model.display_items[0]
                thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(ui, display_item)
                wait_for_thumbnail(thumbnail_source)
                thumbnail_source = None
            self.assertEqual(1, ui.draw_count)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
