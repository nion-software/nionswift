import unittest
import time

import numpy as np

from nion.swift import HardwareSource


class SimpleHardwareSource(HardwareSource.HardwareSource):

    def __init__(self):
        super(SimpleHardwareSource, self).__init__("simple_hardware_source", "SimpleHardwareSource")
        self.properties = None

    def acquire_data_elements(self):
        SimpleHardwareSource.image += 1.0
        time.sleep(0.2)
        data_element = { "data": SimpleHardwareSource.image }
        return [data_element]

    def set_from_properties(self, properties):
        self.properties = properties


SimpleHardwareSource.image = np.zeros(256)


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
        hardware_source_manager.make_hardware_source_alias(source.hardware_source_id, "testalias2", "Test2", { "param": 50 }, 0)
        hardware_source_manager.make_hardware_source_alias("testalias", "testalias3", "Test3")
        hardware_source_manager.make_hardware_source_alias("testalias2", "testalias4", "Test4")
        port = hardware_source_manager.create_port_for_hardware_source_id("testalias")
        self.assertEqual(port.hardware_source.hardware_source_id, source.hardware_source_id)
        self.assertIsNone(port.properties)
        self.assertIsNone(port.filter)
        port.close()
        port = hardware_source_manager.create_port_for_hardware_source_id("testalias2")
        self.assertEqual(port.hardware_source.hardware_source_id, source.hardware_source_id)
        self.assertEqual(port.properties, { "param": 50 })
        self.assertEqual(port.filter, (0, ))
        port.close()
        port = hardware_source_manager.create_port_for_hardware_source_id("testalias3")
        self.assertEqual(port.hardware_source.hardware_source_id, source.hardware_source_id)
        self.assertIsNone(port.properties)
        self.assertIsNone(port.filter)
        port.close()

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

if __name__ == '__main__':
    unittest.main()
