# standard libraries
import contextlib
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import DocumentModel
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.ui import TestUI



class TestFacadeClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=True)
        self.app.workspace_dir = str()

    def tearDown(self):
        pass

    def test_basic_api_methods(self):
        memory_persistent_storage_system = DocumentModel.MemoryPersistentStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0", "~1.0")
            self.assertIsNotNone(api.library)
            self.assertIsNotNone(api.application)
            self.assertIsNotNone(api.create_calibration(1.0, 2.0, "mm"))

    def test_create_data_item_from_data(self):
        memory_persistent_storage_system = DocumentModel.MemoryPersistentStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            data0 = numpy.arange(64).reshape(8, 8)
            data_item = DataItem.DataItem(data0)
            document_model.append_data_item(data_item)
            api = Facade.get_api("~1.0", "~1.0")
            library = api.library
            self.assertEqual(library.data_item_count, 1)
            self.assertEqual(len(library.data_items), 1)
            data1 = numpy.arange(128).reshape(16, 8)
            data2 = numpy.arange(128).reshape(8, 16)
            data3 = numpy.arange(16).reshape(4, 4)
            data_item1_ref = library.create_data_item("one")
            with library.data_ref_for_data_item(data_item1_ref) as data_ref:
                data_ref.data = data1
            data_item2_ref = library.create_data_item_from_data(data2, "two")
            data_and_metadata =  api.create_data_and_metadata(data3)
            data_item3_ref = library.create_data_item_from_data_and_metadata(data_and_metadata, "three")
            self.assertEqual(library.data_item_count, 4)
            self.assertTrue(numpy.array_equal(document_model.data_items[1].maybe_data_source.data_and_metadata.data, data1))
            self.assertTrue(numpy.array_equal(document_model.data_items[2].maybe_data_source.data_and_metadata.data, data2))
            self.assertTrue(numpy.array_equal(document_model.data_items[3].maybe_data_source.data_and_metadata.data, data3))

    def test_data_on_empty_data_item_returns_none(self):
        memory_persistent_storage_system = DocumentModel.MemoryPersistentStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0", "~1.0")
            library = api.library
            data_item1_ref = library.create_data_item("one")
            with library.data_ref_for_data_item(data_item1_ref) as data_ref:
                self.assertIsNone(data_ref.data)

    def test_data_item_data_methods(self):
        memory_persistent_storage_system = DocumentModel.MemoryPersistentStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            data0 = numpy.arange(64).reshape(8, 8)
            data_item = DataItem.DataItem(data0)
            document_model.append_data_item(data_item)
            api = Facade.get_api("~1.0", "~1.0")
            library = api.library
            data1 = numpy.arange(128).reshape(16, 8)
            data_item_ref = library.data_items[0]
            self.assertTrue(numpy.array_equal(data_item_ref.data, data0))
            data_item_ref.set_data(data1)
            self.assertTrue(numpy.array_equal(data_item_ref.data, data1))
            data2 = numpy.arange(128).reshape(8, 16)
            data_item_ref.set_data_and_metadata(api.create_data_and_metadata(data2))
            self.assertTrue(numpy.array_equal(data_item_ref.data, data2))
            self.assertTrue(numpy.array_equal(data_item_ref.data_and_metadata.data, data2))

    def test_data_item_metadata_methods(self):
        memory_persistent_storage_system = DocumentModel.MemoryPersistentStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            data0 = numpy.arange(64).reshape(8, 8)
            data_item = DataItem.DataItem(data0)
            data_item.maybe_data_source.set_intensity_calibration(Calibration.Calibration(0.1, 0.2, "dogs"))
            data_item.maybe_data_source.set_dimensional_calibrations([Calibration.Calibration(0.3, 0.4, "cats"), Calibration.Calibration(0.5, 0.6, "cats")])
            metadata = {"title": "Dogs eat cats."}
            data_item.maybe_data_source.set_metadata(metadata)
            document_model.append_data_item(data_item)
            api = Facade.get_api("~1.0", "~1.0")
            library = api.library
            data_item_ref = library.data_items[0]
            self.assertEqual(data_item_ref.intensity_calibration.units, "dogs")
            self.assertEqual(data_item_ref.dimensional_calibrations[1].units, "cats")
            self.assertEqual(data_item_ref.metadata, metadata)
            data_item_ref.set_intensity_calibration(api.create_calibration(0.11, 0.22, "cats"))
            data_item_ref.set_dimensional_calibrations([api.create_calibration(0.33, 0.44, "mice"), api.create_calibration(0.44, 0.66, "mice")])
            metadata2 = {"title": "Cats eat mice."}
            data_item_ref.set_metadata(metadata2)
            self.assertAlmostEqual(data_item.maybe_data_source.intensity_calibration.offset, 0.11)
            self.assertAlmostEqual(data_item.maybe_data_source.dimensional_calibrations[0].offset, 0.33)
            self.assertEqual(data_item.maybe_data_source.metadata, metadata2)

    def test_data_item_regions(self):
        memory_persistent_storage_system = DocumentModel.MemoryPersistentStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            data_item = DataItem.DataItem(numpy.arange(64).reshape(8, 8))
            document_model.append_data_item(data_item)
            data_item_1d = DataItem.DataItem(numpy.arange(32).reshape(32))
            document_model.append_data_item(data_item_1d)
            api = Facade.get_api("~1.0", "~1.0")
            library = api.library
            data_item_ref = library.data_items[0]
            data_item_1d_ref = library.data_items[1]
            r0 = data_item_ref.add_point_region(0.1, 0.2)
            r1 = data_item_ref.add_rectangle_region(0.3, 0.4, 0.5, 0.6)
            r2 = data_item_ref.add_ellipse_region(0.3, 0.4, 0.5, 0.6)
            r3 = data_item_ref.add_line_region(0.1, 0.2, 0.3, 0.4)
            r4 = data_item_1d_ref.add_interval_region(0.1, 0.2)
            r5 = data_item_1d_ref.add_channel_region(0.5)
            r0.label = "One"
            self.assertEqual(r0.type, "point-region")
            self.assertEqual(r1.type, "rectangle-region")
            self.assertEqual(r2.type, "ellipse-region")
            self.assertEqual(r3.type, "line-region")
            self.assertEqual(r4.type, "interval-region")
            self.assertEqual(r5.type, "channel-region")
            r4.set_property("end", 0.3)
            self.assertAlmostEqual(r4.get_property("end"), 0.3)
            self.assertEqual(len(data_item.maybe_data_source.displays[0].graphics), 4)
            self.assertEqual(len(data_item_1d.maybe_data_source.displays[0].graphics), 2)
            self.assertIsInstance(data_item.maybe_data_source.displays[0].graphics[0], Graphics.PointGraphic)
            self.assertIsInstance(data_item.maybe_data_source.displays[0].graphics[1], Graphics.RectangleGraphic)
            self.assertIsInstance(data_item.maybe_data_source.displays[0].graphics[2], Graphics.EllipseGraphic)
            self.assertIsInstance(data_item.maybe_data_source.displays[0].graphics[3], Graphics.LineGraphic)
            self.assertIsInstance(data_item_1d.maybe_data_source.displays[0].graphics[0], Graphics.IntervalGraphic)
            self.assertIsInstance(data_item_1d.maybe_data_source.displays[0].graphics[1], Graphics.ChannelGraphic)


if __name__ == '__main__':
    unittest.main()
