import unittest
import time

import numpy as np

from nion.swift import HardwareSource as HardwareSource


class SimpleHWSource(HardwareSource.HardwareSource):
    def acquire(self):
        SimpleHWSource.image += 1.0
        time.sleep(0.2)
        return [SimpleHWSource.image]

    def __str__(self):
        return "SimpleHWSource"
SimpleHWSource.image = np.zeros(256)


class TestHardwareSourceClass(unittest.TestCase):
    def test_registration(self):
        man = HardwareSource.HardwareSourceManager()
        man._reset()
        source = SimpleHWSource()
        man.register_hardware_source(source)
        self.assertEqual(len(man._all_hw_ports), 1)
        p = man.create_port_for_name("TestCase", "SimpleHWSource")
        self.assertIsNotNone(p)
        p.close()
        man.unregister_hardware_source(source)
        p = man.create_port_for_name("TestCase", "SimpleHWSource")
        self.assertIsNone(p)

    def test_alias(self):
        man = HardwareSource.HardwareSourceManager()
        man._reset()
        source = SimpleHWSource()
        man.register_hardware_source(source)
        man.make_hardware_source_alias("testalias", source)
        man.make_hardware_source_alias("testalias2", source, "DiffProps", 0)
        p = man.create_port_for_name("TestCase", "testalias")
        self.assertIsNotNone(p)
        p.close()
        p = man.create_port_for_name("TestCase", "testalias2")
        self.assertIsNotNone(p)
        p.close()

    def test_events(self):
        SimpleHWSource.image = np.zeros(256)
        man = HardwareSource.HardwareSourceManager()
        man._reset()
        source = SimpleHWSource()
        man.register_hardware_source(source)
        self.assertEqual(len(man._all_hw_ports), 1)
        p = man.create_port_for_name("TestCase", "SimpleHWSource")
        def newims(images):
            pass

        p.on_new_images = newims
        time.sleep(1) # wait for a second, we should have 4-6 images after this
        tl_pixel = p.get_last_images()[0][0]
        #print "got %d images in 1s"%tl_pixel
        self.assertTrue(3.0 < tl_pixel < 7.0)
        p.close()

if __name__ == '__main__':
    unittest.main()
