# standard libraries
import contextlib
import logging
import threading
import time
import typing
import unittest

import numpy

# local libraries
from nion.swift import DataItemThumbnailWidget
from nion.swift import MimeTypes
from nion.swift import Thumbnails
from nion.swift.model import DataItem
from nion.swift.test import TestContext
from nion.ui import Bitmap
from nion.ui import DrawingContext
from nion.ui import TestUI
from nion.utils import Geometry


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
                finished.wait(1.0)
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


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
