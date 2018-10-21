# standard libraries
import contextlib
import numpy
import logging
import threading
import unittest

# local libraries
from nion.swift import Application
from nion.swift import DataItemThumbnailWidget
from nion.swift import DocumentController
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.ui import TestUI
from nion.utils import Geometry


class TestDisplayPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_data_item_display_thumbnail_source_produces_data_item_mime_data(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.random.randn(8, 8))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            display_item.display_type = "image"
            thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(app.ui)
            finished = threading.Event()
            def thumbnail_data_changed(data):
                finished.set()
            thumbnail_source.on_thumbnail_data_changed = thumbnail_data_changed
            thumbnail_source.set_display_item(display_item)
            finished.wait(1.0)
            finished.clear()
            finished.wait(1.0)
            mime_data = app.ui.create_mime_data()
            valid, thumbnail = thumbnail_source.populate_mime_data_for_drag(mime_data, Geometry.IntSize(64, 64))
            self.assertTrue(valid)
            self.assertIsNotNone(thumbnail)
            self.assertTrue(mime_data.has_format("text/data_item_uuid"))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
