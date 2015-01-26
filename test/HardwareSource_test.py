import datetime
import logging
import threading
import time
import unittest

import numpy as np

from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import HardwareSource
from nion.swift.model import ImportExportManager
from nion.swift import Application
from nion.swift import DocumentController
from nion.ui import Test


class SimpleHardwareSource(HardwareSource.HardwareSource):

    def __init__(self, sleep=0.05):
        super(SimpleHardwareSource, self).__init__("simple_hardware_source", "SimpleHardwareSource")
        self.properties = None
        self.sleep = sleep
        self.event = threading.Event()
        self.image = np.zeros(256)

    def make_data_element(self):
        return {"version": 1, "data": self.image,
            "properties": {"exposure": 0.5, "extra_high_tension": 140000, "hardware_source": "hardware source",
                "hardware_source_id": "simple_hardware_source"}}

    def acquire_data_elements(self):
        self.image += 1.0
        time.sleep(self.sleep)
        data_element = self.make_data_element()
        self.event.set()
        return [data_element]

    def set_from_properties(self, properties):
        self.properties = properties


class DummyWorkspaceController(object):

    def __init__(self, document_model):
        self.document_controller = self  # hack so that document_controller.document_model works
        self.document_model = document_model

    def did_stop_playing(self, hardware_source):
        pass

    def will_start_playing(self, hardware_source):
        pass

    def sync_channels_to_data_items(self, channels, hardware_source):
        data_item_set = {}
        for channel in channels:
            data_item_set[channel] = DataItem.DataItem()
        return data_item_set


class TestHardwareSourceClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_registering_and_unregistering_works_as_expected(self):
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(source)
        self.assertEqual(len(hardware_source_manager.hardware_sources), 1)
        p = hardware_source_manager.create_port_for_hardware_source_id("simple_hardware_source")
        self.assertIsNotNone(p)
        p.close()
        hardware_source_manager.unregister_hardware_source(source)
        p = hardware_source_manager.create_port_for_hardware_source_id("simple_hardware_source")
        self.assertIsNone(p)

    def test_hardware_source_aliases_works(self):
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(source)
        hardware_source_manager.make_instrument_alias(source.hardware_source_id, "testalias", "Test1")
        hardware_source_manager.make_instrument_alias(source.hardware_source_id, "testalias2", "Test2")
        hardware_source_manager.make_instrument_alias("testalias", "testalias3", "Test3")
        hardware_source_manager.make_instrument_alias("testalias2", "testalias4", "Test4")
        port = hardware_source_manager.create_port_for_hardware_source_id("testalias")
        self.assertEqual(port.hardware_source.hardware_source_id, source.hardware_source_id)
        port.close()
        port = hardware_source_manager.create_port_for_hardware_source_id("testalias2")
        port.hardware_source.hardware_source_id
        source.hardware_source_id
        self.assertEqual(port.hardware_source.hardware_source_id, source.hardware_source_id)
        port.close()
        port = hardware_source_manager.create_port_for_hardware_source_id("testalias3")
        self.assertEqual(port.hardware_source.hardware_source_id, source.hardware_source_id)
        port.close()
        hardware_source_manager.unregister_hardware_source(source)

    def test_events(self):
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(source)
        self.assertEqual(len(hardware_source_manager.hardware_sources), 1)
        p = hardware_source_manager.create_port_for_hardware_source_id("simple_hardware_source")
        def handle_new_data_elements(images):
            pass
        p.on_new_data_elements = handle_new_data_elements
        while source.frame_index < 4:
            time.sleep(0.01)
        tl_pixel = p.get_last_data_elements()[0]["data"][0]
        # print "got %d images in 1s"%tl_pixel
        self.assertTrue(3.0 < tl_pixel < 7.0)
        p.close()
        hardware_source_manager.unregister_hardware_source(source)

    def test_setting_current_snapshot_succeeds_and_does_not_leak_memory(self):
        # stopping acquisition should not clear session
        document_model = DocumentModel.DocumentModel()
        workspace_controller = DummyWorkspaceController(document_model)
        source = SimpleHardwareSource(0.01)
        self.assertEqual(source.frame_index, 0)
        source.start_playing(workspace_controller)
        while source.frame_index < 3:
            time.sleep(0.01)
        source.abort_playing()
        source.data_buffer.current_snapshot = 0
        source.close()

    def test_simple_hardware_start_and_wait_acquires_data(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(source)
        self.assertEqual(len(document_model.data_items), 0)
        hardware_source = hardware_source_manager.get_hardware_source_for_hardware_source_id("simple_hardware_source")
        hardware_source.start_playing(document_controller.workspace_controller)
        self.assertTrue(hardware_source.is_playing)
        start_time = time.time()
        while source.frame_index < 4:
            hardware_source.periodic()
            time.sleep(0.01)
            self.assertTrue(time.time() - start_time < 3.0)
        hardware_source.abort_playing()
        self.assertFalse(hardware_source.is_playing)
        document_controller.periodic()  # data items queued to be added from background thread get added here
        self.assertEqual(len(document_model.data_items), 1)
        document_controller.close()

    def test_simple_hardware_start_and_stop_actually_stops_acquisition(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(source)
        hardware_source = hardware_source_manager.get_hardware_source_for_hardware_source_id("simple_hardware_source")
        hardware_source.event.clear()
        hardware_source.start_playing(document_controller.workspace_controller)
        # we're waiting on the hardware source to trigger a finish event, but the acquisition
        # machinery still needs to process the result. that's the reason for the extra delays
        # below after the event is triggered.
        hardware_source.event.wait()    # wait for first frame
        time.sleep(0.05)                # and some processing time
        hardware_source.event.clear()
        self.assertTrue(hardware_source.is_playing)
        hardware_source.stop_playing()
        hardware_source.event.wait()    # wait for frame to finish
        time.sleep(0.05)                # and some processing time
        hardware_source.periodic()      # required to go to 'stop' state. cem 9/14.
        self.assertFalse(hardware_source.is_playing)
        document_controller.close()

    def test_simple_hardware_start_and_abort_works_as_expected(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(source)
        hardware_source = hardware_source_manager.get_hardware_source_for_hardware_source_id("simple_hardware_source")
        hardware_source.start_playing(document_controller.workspace_controller)
        self.assertTrue(hardware_source.is_playing)
        hardware_source.abort_playing()
        self.assertFalse(hardware_source.is_playing)
        document_controller.close()

    def test_standard_data_element_constructs_metadata_with_hardware_source_as_dict(self):
        data_element = SimpleHardwareSource().make_data_element()
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        metadata = data_item.data_sources[0].metadata
        self.assertTrue(isinstance(metadata.get("hardware_source"), dict))

    def test_updating_existing_data_item_updates_creation_even_if_an_updated_date_is_not_supplied(self):
        data_element = SimpleHardwareSource().make_data_element()
        data_item = ImportExportManager.create_data_item_from_data_element(data_element)
        data_item.created = datetime.datetime(2000, 06, 30)
        ImportExportManager.update_data_item_from_data_element(data_item, data_element)
        self.assertEqual(data_item.created.year, datetime.datetime.utcnow().year)

if __name__ == '__main__':
    unittest.main()
