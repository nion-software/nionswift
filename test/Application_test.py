# standard libraries
import datetime
import logging
import os
import shutil
import unittest
import uuid

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift.model import Storage


class TestApplicationClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_ndata2_handler_basic_functionality(self):
        now = datetime.datetime.now()
        current_working_directory = os.getcwd()
        data_dir = os.path.join(current_working_directory, "__Test")
        Storage.db_make_directory_if_needed(data_dir)
        try:
            h = Application.Ndata2Handler(data_dir)
            p = {u"abc": 1, u"def": u"bcd", u"uuid": unicode(uuid.uuid4())}
            h.write_properties("abc", p, now)
            self.assertEqual(h.read_properties("abc")[1], p)
            self.assertIsNone(h.read_data("abc"))
            h.write_data("abc", numpy.zeros((4,4), dtype=numpy.float64), now)
            self.assertEqual(h.read_properties("abc")[1], p)
            d = h.read_data("abc")
            self.assertEqual(d.shape, (4, 4))
            self.assertEqual(d.dtype, numpy.float64)
            h.write_data("abc", numpy.zeros((12,12), dtype=numpy.float32), now)
            self.assertEqual(h.read_properties("abc")[1], p)
            d = h.read_data("abc")
            self.assertEqual(d.shape, (12, 12))
            self.assertEqual(d.dtype, numpy.float32)
        finally:
            #logging.debug("rmtree %s", data_dir)
            shutil.rmtree(data_dir)

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
