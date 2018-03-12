# standard libraries
import contextlib
import unittest

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import DocumentModel
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.ui import TestUI
from nion.utils import Geometry


Facade.initialize()


class TestFacadeClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=True)
        self.app.workspace_dir = str()

    def tearDown(self):
        pass

    def test_basic_api_methods(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0", "~1.0")
            self.assertIsNotNone(api.library)
            self.assertIsNotNone(api.application)
            self.assertIsNotNone(api.create_calibration(1.0, 2.0, "mm"))

    def test_create_data_item_from_data(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
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
            self.assertTrue(numpy.array_equal(document_model.data_items[1].data, data1))
            self.assertTrue(numpy.array_equal(document_model.data_items[2].data, data2))
            self.assertTrue(numpy.array_equal(document_model.data_items[3].data, data3))

    def test_library_and_data_items_can_be_compared_for_equality(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((2, 2)))
            document_model.append_data_item(data_item2)
            api = Facade.get_api("~1.0", "~1.0")
            self.assertEqual(api.library, api.library)
            self.assertEqual(api.library.data_items, api.library.data_items)

    def test_graphic_is_invalid_if_source_is_removed(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0", "~1.0")
            library = api.library
            data_item = library.create_data_item_from_data(numpy.zeros((16, 16)))
            self.assertEqual(len(Facade.Graphic.instances), 0)
            graphic = data_item.add_point_region(10, 10)
            self.assertEqual(len(Facade.Graphic.instances), 1)
            graphic = None
            self.assertEqual(len(Facade.Graphic.instances), 0)

    def test_create_data_item_from_data_as_sequence(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0", "~1.0")
            library = api.library
            data_and_metadata =  DataAndMetadata.new_data_and_metadata(numpy.zeros((8, 4, 5)), data_descriptor=DataAndMetadata.DataDescriptor(True, 0, 2))
            data_item = library.create_data_item_from_data_and_metadata(data_and_metadata, "three")
            self.assertEqual(library.data_item_count, 1)
            self.assertTrue(document_model.data_items[0].is_sequence)

    def test_data_on_empty_data_item_returns_none(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0", "~1.0")
            library = api.library
            data_item1_ref = library.create_data_item("one")
            with library.data_ref_for_data_item(data_item1_ref) as data_ref:
                self.assertIsNone(data_ref.data)

    def test_data_item_data_methods(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
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
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            data0 = numpy.arange(64).reshape(8, 8)
            data_item = DataItem.DataItem(data0)
            data_item.set_intensity_calibration(Calibration.Calibration(0.1, 0.2, "dogs"))
            data_item.set_dimensional_calibrations([Calibration.Calibration(0.3, 0.4, "cats"), Calibration.Calibration(0.5, 0.6, "cats")])
            metadata = {"title": "Dogs eat cats."}
            data_item.metadata = metadata
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
            self.assertAlmostEqual(data_item.intensity_calibration.offset, 0.11)
            self.assertAlmostEqual(data_item.dimensional_calibrations[0].offset, 0.33)
            self.assertEqual(data_item.metadata, metadata2)

    def test_data_item_regions(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
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
            self.assertEqual(len(data_item.displays[0].graphics), 4)
            self.assertEqual(len(data_item_1d.displays[0].graphics), 2)
            self.assertIsInstance(data_item.displays[0].graphics[0], Graphics.PointGraphic)
            self.assertIsInstance(data_item.displays[0].graphics[1], Graphics.RectangleGraphic)
            self.assertIsInstance(data_item.displays[0].graphics[2], Graphics.EllipseGraphic)
            self.assertIsInstance(data_item.displays[0].graphics[3], Graphics.LineGraphic)
            self.assertIsInstance(data_item_1d.displays[0].graphics[0], Graphics.IntervalGraphic)
            self.assertIsInstance(data_item_1d.displays[0].graphics[1], Graphics.ChannelGraphic)

    def test_display_data_panel_reuses_existing_display(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            # configure data item
            data_item = DataItem.DataItem(numpy.arange(64).reshape(8, 8))
            document_model.append_data_item(data_item)
            # configure workspace
            d = {"type": "splitter", "orientation": "vertical", "splits": [0.5, 0.5], "children": [
                {"type": "image", "uuid": "0569ca31-afd7-48bd-ad54-5e2bb9f21102", "identifier": "a", "selected": True},
                {"type": "image", "uuid": "acd77f9f-2f6f-4fbf-af5e-94330b73b997", "identifier": "b"}]}
            workspace_2x1 = document_controller.workspace_controller.new_workspace("2x1", d)
            document_controller.workspace_controller.change_workspace(workspace_2x1)
            root_canvas_item = document_controller.workspace_controller.image_row.children[0]._root_canvas_item()
            root_canvas_item.layout_immediate(Geometry.IntSize(width=640, height=480))
            self.assertIsNone(document_controller.workspace_controller.display_panels[0].data_item)
            self.assertIsNone(document_controller.workspace_controller.display_panels[1].data_item)
            # test display_data_item
            api = Facade.get_api("~1.0", "~1.0")
            library = api.library
            document_controller_ref = api.application.document_controllers[0]
            data_item_ref = library.data_items[0]
            # display data item and verify it is displayed
            display_panal_ref = document_controller_ref.display_data_item(data_item_ref)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item_ref._data_item)
            self.assertIsNone(document_controller.workspace_controller.display_panels[1].data_item)
            self.assertEqual(document_controller.workspace_controller.display_panels[0], display_panal_ref._display_panel)
            # display data item again and verify it is displayed only once
            display_panal_ref = document_controller_ref.display_data_item(data_item_ref)
            self.assertEqual(document_controller.workspace_controller.display_panels[0].data_item, data_item_ref._data_item)
            self.assertIsNone(document_controller.workspace_controller.display_panels[1].data_item)
            self.assertEqual(document_controller.workspace_controller.display_panels[0], display_panal_ref._display_panel)

    def test_target_data_item_returns_none_if_panel_is_empty(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            # configure workspace
            workspace_1x1 = document_controller.document_model.workspaces[0]
            document_controller.workspace_controller.change_workspace(workspace_1x1)
            display_panel = document_controller.selected_display_panel

            api = Facade.get_api("~1.0", "~1.0")
            # the display is already filled. display panel should be None.
            self.assertIsNone(api.application.document_windows[0].target_data_item)

    def test_display_data_item_returns_none_if_no_panel_available(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            # configure data item
            data_item1 = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((8, 8)))
            document_model.append_data_item(data_item2)
            # configure workspace
            workspace_1x1 = document_controller.document_model.workspaces[0]
            document_controller.workspace_controller.change_workspace(workspace_1x1)
            display_panel = document_controller.selected_display_panel

            api = Facade.get_api("~1.0", "~1.0")
            library = api.library
            data_item1_ref = library.data_items[0]
            data_item2_ref = library.data_items[1]
            # first data item gets displayed because there is an empty display panel.
            self.assertEqual(api.application.document_windows[0].display_data_item(data_item1_ref)._display_panel, display_panel)
            # the display is already filled. display panel should be None.
            self.assertIsNone(api.application.document_windows[0].display_data_item(data_item2_ref))
            # redisplay returns existing display panel.
            self.assertEqual(api.application.document_windows[0].display_data_item(data_item1_ref)._display_panel, display_panel)

    def test_lookup_unknown_instrument_or_hardware_source_returns_none(self):
        api = Facade.get_api("~1.0", "~1.0")
        self.assertIsNone(api.get_hardware_source_by_id("nonexistent_hardware", "~1.0"))
        self.assertIsNone(api.get_instrument_by_id("nonexistent_instrument", "~1.0"))

    def test_create_data_item_from_data_copies_data(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0", "~1.0")
            data = numpy.random.randn(2, 2)
            data_item = api.library.create_data_item_from_data(data)
            data[:, :] = numpy.random.randn(2, 2)
            self.assertFalse(numpy.array_equal(data, data_item.data))

    def test_create_data_item_from_xdata_copies_data(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0", "~1.0")
            data = numpy.random.randn(2, 2)
            xdata = api.create_data_and_metadata_from_data(data)
            data_item = api.library.create_data_item_from_data_and_metadata(xdata)
            data[:, :] = numpy.random.randn(2, 2)
            self.assertFalse(numpy.array_equal(data, data_item.data))

    def test_create_empty_data_item_and_set_data_copies_data(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0", "~1.0")
            data = numpy.random.randn(2, 2)
            data_item = api.library.create_data_item()
            data_item.set_data(data)
            data[:, :] = numpy.random.randn(2, 2)
            self.assertFalse(numpy.array_equal(data, data_item.data))

    def test_create_empty_data_item_and_set_xdata_copies_data(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_system=memory_persistent_storage_system)
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0", "~1.0")
            data = numpy.random.randn(2, 2)
            data_item = api.library.create_data_item()
            data_item.xdata = api.create_data_and_metadata_from_data(data)
            data[:, :] = numpy.random.randn(2, 2)
            self.assertFalse(numpy.array_equal(data, data_item.data))

    class Computation1:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src):
            self.__src = src

        def commit(self):
            graphic = self.computation.get_result("graphic")
            if not graphic:
                graphic = self.__src.add_point_region(0.5, 0.5)
                self.computation.set_result("graphic", graphic)

    def test_register_library_computation_and_execute_it(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0")
            api.register_computation_type("computation1", self.Computation1)
            data = numpy.random.randn(2, 2)
            data_item = api.library.create_data_item()
            data_item.set_data(data)
            api.library.create_computation("computation1", inputs={"src": data_item}, outputs={"graphic": None})
            document_model.recompute_all()
            self.assertEqual(len(data_item.graphics), 1)

    class Computation2:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src, value):
            self.__src = src
            self.__value = value

        def commit(self):
            graphic = self.computation.get_result("graphic")
            if not graphic:
                graphic = self.__src.add_point_region(0.5, 0.5)
                self.computation.set_result("graphic", graphic)
            graphic.label = str(self.__value)

    def test_register_library_computation_with_variable_and_execute_it(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0")
            api.register_computation_type("computation2", self.Computation2)
            data = numpy.random.randn(2, 2)
            data_item = api.library.create_data_item()
            data_item.set_data(data)
            computation = api.library.create_computation("computation2", inputs={"src": data_item, "value": "label"}, outputs={"graphic": None})
            document_model.recompute_all()
            self.assertEqual(len(data_item.graphics), 1)
            self.assertEqual(data_item.graphics[0].label, "label")
            computation.set_input_value("value", "label2")
            document_model.recompute_all()
            self.assertEqual(len(data_item.graphics), 1)
            self.assertEqual(data_item.graphics[0].label, "label2")

    class Computation3:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src):
            self.__data = src.data
            self.__src = src

        def commit(self):
            dst = self.computation.get_result("dst")
            dst.set_data(self.__data)

    def test_library_computation_change_object_input(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0")
            api.register_computation_type("computation3", self.Computation3)
            data1 = numpy.ones((2, 2)) * 1
            data_item1 = api.library.create_data_item()
            data_item1.set_data(data1)
            data2 = numpy.ones((2, 2)) * 2
            data_item2 = api.library.create_data_item()
            data_item2.set_data(data2)
            dst_data_item = api.library.create_data_item()
            computation = api.library.create_computation("computation3", inputs={"src": data_item1}, outputs={"dst": dst_data_item})
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(dst_data_item.data, data1))
            computation.set_input_value("src", data_item2)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(dst_data_item.data, data2))

    class Computation4:
        def __init__(self, computation, **kwargs):
            self.computation = computation

        def execute(self, src):
            assert isinstance(src, Facade.DataSource)
            self.__data = src.data
            self.__src = src

        def commit(self):
            dst = self.computation.get_result("dst")
            dst.set_data(self.__data)

    def test_library_computation_change_object_data_source_input(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = self.app.create_document_controller(document_model, "library")
        with contextlib.closing(document_controller):
            api = Facade.get_api("~1.0")
            api.register_computation_type("computation4", self.Computation4)
            data1 = numpy.ones((2, 2)) * 1
            data_item1 = api.library.create_data_item()
            data_item1.set_data(data1)
            data2 = numpy.ones((2, 2)) * 2
            data_item2 = api.library.create_data_item()
            data_item2.set_data(data2)
            dst_data_item = api.library.create_data_item()
            computation = api.library.create_computation("computation4", inputs={"src": {"object": data_item1, "type": "data_source"}}, outputs={"dst": dst_data_item})
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(dst_data_item.data, data1))
            computation.set_input_value("src", {"object": data_item2, "type": "data_source"})
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(dst_data_item.data, data2))


if __name__ == '__main__':
    unittest.main()
