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

    def test_data_item_display_thumbnail_source_produces_library_item_mime_data(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.random.randn(8, 8))
            data_item.displays[0].display_type = "image"
            document_model.append_data_item(data_item)
            thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(app.ui)
            finished = threading.Event()
            def thumbnail_data_changed(data):
                finished.set()
            thumbnail_source.on_thumbnail_data_changed = thumbnail_data_changed
            thumbnail_source.set_display(data_item.displays[0])
            finished.wait(1.0)
            finished.clear()
            finished.wait(1.0)
            mime_data = app.ui.create_mime_data()
            valid, thumbnail = thumbnail_source.populate_mime_data_for_drag(mime_data, Geometry.IntSize(64, 64))
            self.assertTrue(valid)
            self.assertIsNotNone(thumbnail)
            self.assertTrue(mime_data.has_format("text/library_item_uuid"))
            self.assertTrue(mime_data.has_format("text/data_item_uuid"))

    def test_composition_display_thumbnail_source_produces_library_item_mime_data(self):
        app = Application.Application(TestUI.UserInterface(), set_global=False)
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.random.randn(8, 8))
            data_item1.displays[0].display_type = "image"
            document_model.append_data_item(data_item1)
            composite_item = DataItem.CompositeLibraryItem()
            document_model.append_data_item(composite_item)
            composite_item.append_data_item(data_item1)
            thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(app.ui)
            finished = threading.Event()
            def thumbnail_data_changed(data):
                finished.set()
            thumbnail_source.on_thumbnail_data_changed = thumbnail_data_changed
            thumbnail_source.set_display(composite_item.displays[0])
            finished.wait(1.0)
            finished.clear()
            finished.wait(1.0)
            mime_data = app.ui.create_mime_data()
            valid, thumbnail = thumbnail_source.populate_mime_data_for_drag(mime_data, Geometry.IntSize(64, 64))
            self.assertTrue(valid)
            self.assertIsNotNone(thumbnail)
            self.assertTrue(mime_data.has_format("text/library_item_uuid"))
            self.assertFalse(mime_data.has_format("text/data_item_uuid"))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
