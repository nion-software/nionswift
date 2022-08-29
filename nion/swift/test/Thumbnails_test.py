# standard libraries
import contextlib

import numpy
import logging
import threading
import unittest

# local libraries
from nion.swift import Application
from nion.swift import DataItemThumbnailWidget
from nion.swift import MimeTypes
from nion.swift import Thumbnails
from nion.swift.model import DataItem
from nion.swift.test import TestContext
from nion.ui import TestUI
from nion.utils import Geometry


class TestThumbnailsClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
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
                def thumbnail_data_changed(data):
                    finished.set()
                thumbnail_source.on_thumbnail_data_changed = thumbnail_data_changed  # watch for actual data
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
            thumbnail_source = Thumbnails.ThumbnailManager().thumbnail_source_for_display_item(self.app.ui, display_item)
            with thumbnail_source.ref():
                thumbnail_source.recompute_data()
                thumbnail_source.thumbnail_data
                # here the data should be computed and the thumbnail should not be dirty
                self.assertFalse(display_item._display_cache.is_cached_value_dirty(display_item, "thumbnail_data"))
                # now the source data changes and the inverted data needs computing.
                # the thumbnail should also be dirty.
                print(display_item.display_layers[0].fill_color)
                display_item._set_display_layer_property(0, "fill_color", "teal")
                print(display_item.display_layers[0].fill_color)
                document_model.recompute_all()
                self.assertTrue(display_item._display_cache.is_cached_value_dirty(display_item, "thumbnail_data"))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
