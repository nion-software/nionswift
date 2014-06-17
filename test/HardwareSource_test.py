import unittest
import time

import numpy as np

from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import HardwareSource
from nion.swift.model import Storage


class SimpleHardwareSource(HardwareSource.HardwareSource):

    def __init__(self, sleep=0.2):
        super(SimpleHardwareSource, self).__init__("simple_hardware_source", "SimpleHardwareSource")
        self.properties = None
        self.sleep = sleep

    def acquire_data_elements(self):
        SimpleHardwareSource.image += 1.0
        time.sleep(self.sleep)
        data_element = { "version": 1, "data": SimpleHardwareSource.image }
        return [data_element]

    def set_from_properties(self, properties):
        self.properties = properties


SimpleHardwareSource.image = np.zeros(256)


class DummyWorkspaceController(object):

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

    def test_registration(self):
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

    def test_alias(self):
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(source)
        hardware_source_manager.make_hardware_source_alias(source.hardware_source_id, "testalias", "Test1")
        hardware_source_manager.make_hardware_source_alias(source.hardware_source_id, "testalias2", "Test2")
        hardware_source_manager.make_hardware_source_alias("testalias", "testalias3", "Test3")
        hardware_source_manager.make_hardware_source_alias("testalias2", "testalias4", "Test4")
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
        SimpleHardwareSource.image = np.zeros(256)
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(source)
        self.assertEqual(len(hardware_source_manager.hardware_sources), 1)
        p = hardware_source_manager.create_port_for_hardware_source_id("simple_hardware_source")
        def handle_new_data_elements(images):
            pass
        p.on_new_data_elements = handle_new_data_elements
        time.sleep(1) # wait for a second, we should have 4-6 images after this
        tl_pixel = p.get_last_data_elements()[0]["data"][0]
        # print "got %d images in 1s"%tl_pixel
        self.assertTrue(3.0 < tl_pixel < 7.0)
        p.close()
        hardware_source_manager.unregister_hardware_source(source)

    def test_setting_current_snapshot_succeeds_and_does_not_leak_memory(self):
        # stopping acquisition should not clear session
        datastore = Storage.DictDatastore()
        document_model = DocumentModel.DocumentModel(datastore)
        workspace_controller = DummyWorkspaceController()
        source = SimpleHardwareSource(0.01)
        self.assertEqual(source.frame_index, 0)
        source.start_playing(workspace_controller)
        while source.frame_index < 3:
            time.sleep(0.01)
        source.abort_playing()
        source.data_buffer.current_snapshot = 0
        source.close()

if __name__ == '__main__':
    unittest.main()
