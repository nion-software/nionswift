import unittest
import time

import numpy as np

from nion.swift import HardwareSource


class SimpleHardwareSource(HardwareSource.HardwareSource):

    def acquire_data_elements(self):
        SimpleHardwareSource.image += 1.0
        time.sleep(0.2)
        data_element = { "data": SimpleHardwareSource.image }
        return [data_element]

    def __str__(self):
        return "SimpleHardwareSource"

SimpleHardwareSource.image = np.zeros(256)


class TestHardwareSourceClass(unittest.TestCase):

    def test_registration(self):
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(source)
        self.assertEqual(len(hardware_source_manager._hardware_ports), 1)
        p = hardware_source_manager.create_port_for_name("TestCase", "SimpleHardwareSource")
        self.assertIsNotNone(p)
        p.close()
        hardware_source_manager.unregister_hardware_source(source)
        p = hardware_source_manager.create_port_for_name("TestCase", "SimpleHardwareSource")
        self.assertIsNone(p)

    def test_alias(self):
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(source)
        hardware_source_manager.make_hardware_source_alias("testalias", source)
        hardware_source_manager.make_hardware_source_alias("testalias2", source, "DiffProps", 0)
        p = hardware_source_manager.create_port_for_name("TestCase", "testalias")
        self.assertIsNotNone(p)
        p.close()
        p = hardware_source_manager.create_port_for_name("TestCase", "testalias2")
        self.assertIsNotNone(p)
        p.close()

    def test_events(self):
        SimpleHardwareSource.image = np.zeros(256)
        hardware_source_manager = HardwareSource.HardwareSourceManager()
        hardware_source_manager._reset()
        source = SimpleHardwareSource()
        hardware_source_manager.register_hardware_source(source)
        self.assertEqual(len(hardware_source_manager._hardware_ports), 1)
        p = hardware_source_manager.create_port_for_name("TestCase", "SimpleHardwareSource")
        def handle_new_data_elements(images):
            pass
        p.on_new_data_elements = handle_new_data_elements
        time.sleep(1) # wait for a second, we should have 4-6 images after this
        tl_pixel = p.get_last_data_elements()[0]["data"][0]
        #print "got %d images in 1s"%tl_pixel
        self.assertTrue(3.0 < tl_pixel < 7.0)
        p.close()

if __name__ == '__main__':
    unittest.main()
