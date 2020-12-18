# standard libraries
import numpy
import logging
import threading
import unittest

# local libraries
from nion.swift import Application
from nion.swift import DataItemThumbnailWidget
from nion.swift import MimeTypes
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
            finished = threading.Event()
            def thumbnail_data_changed(data):
                finished.set()
            thumbnail_source.on_thumbnail_data_changed = thumbnail_data_changed
            thumbnail_source.set_display_item(display_item)
            finished.wait(1.0)
            finished.clear()
            finished.wait(1.0)
            mime_data = document_controller.ui.create_mime_data()
            valid, thumbnail = thumbnail_source.populate_mime_data_for_drag(mime_data, Geometry.IntSize(64, 64))
            self.assertTrue(valid)
            self.assertIsNotNone(thumbnail)
            self.assertTrue(mime_data.has_format(MimeTypes.DISPLAY_ITEM_MIME_TYPE))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
