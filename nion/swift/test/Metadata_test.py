# standard libraries
import contextlib
import copy
import datetime
import functools
import gc
import logging
import math
import threading
import time
import typing
import unittest
import weakref

# third party libraries
import numpy

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Application
from nion.swift.model import DataItem
from nion.swift.model import Metadata
from nion.swift.test import TestContext
from nion.ui import TestUI


def create_memory_profile_context() -> TestContext.MemoryProfileContext:
    return TestContext.MemoryProfileContext()


class TestDataItemClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        TestContext.end_leaks(self)

    def test_metadata_value_data_item_methods(self) -> None:
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((4, 4), float))
            document_model.append_data_item(data_item)
            # test a metadata value
            self.assertFalse(data_item.has_metadata_value("stem.high_tension"))
            data_item.set_metadata_value("stem.high_tension", 100000.0)
            self.assertEqual(100000.0, data_item.metadata["instrument"]["high_tension"])
            self.assertTrue(data_item.has_metadata_value("stem.high_tension"))
            self.assertEqual(100000.0, data_item.get_metadata_value("stem.high_tension"))
            data_item.delete_metadata_value("stem.high_tension")
            self.assertFalse(data_item.has_metadata_value("stem.high_tension"))
            # test a session metadata value
            self.assertFalse(data_item.has_metadata_value("stem.session.sample"))
            data_item.set_metadata_value("stem.session.sample", "Unobtainium")
            self.assertEqual("Unobtainium", data_item.session_metadata["sample"])
            self.assertTrue(data_item.has_metadata_value("stem.session.sample"))
            self.assertEqual("Unobtainium", data_item.get_metadata_value("stem.session.sample"))
            data_item.delete_metadata_value("stem.session.sample")
            self.assertFalse(data_item.has_metadata_value("stem.session.sample"))

    def test_metadata_value_xdata_methods(self) -> None:
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((4, 4), float))
            document_model.append_data_item(data_item)
            xdata = data_item.xdata
            self.assertFalse(Metadata.has_metadata_value(xdata, "stem.high_tension"))
            Metadata.set_metadata_value(xdata, "stem.high_tension", 100000.0)
            self.assertEqual(100000.0, xdata.metadata["instrument"]["high_tension"])
            self.assertTrue(Metadata.has_metadata_value(xdata, "stem.high_tension"))
            self.assertEqual(100000.0, Metadata.get_metadata_value(xdata, "stem.high_tension"))
            Metadata.delete_metadata_value(xdata, "stem.high_tension")
            self.assertFalse(Metadata.has_metadata_value(xdata, "stem.high_tension"))
            # test a session metadata value
            self.assertFalse(Metadata.has_metadata_value(xdata, "stem.session.sample"))
            Metadata.set_metadata_value(xdata, "stem.session.sample", "Unobtainium")
            self.assertEqual("Unobtainium", xdata.metadata["session_metadata"]["sample"])
            self.assertTrue(Metadata.has_metadata_value(xdata, "stem.session.sample"))
            self.assertEqual("Unobtainium", Metadata.get_metadata_value(xdata, "stem.session.sample"))
            Metadata.delete_metadata_value(xdata, "stem.session.sample")
            self.assertFalse(Metadata.has_metadata_value(xdata, "stem.session.sample"))

    def test_metadata_value_dict_methods(self) -> None:
        with TestContext.create_memory_context() as test_context:
            document_model = test_context.create_document_model()
            data_item = DataItem.DataItem(numpy.zeros((4, 4), float))
            document_model.append_data_item(data_item)
            d = dict()
            self.assertFalse(Metadata.has_metadata_value(d, "stem.high_tension"))
            Metadata.set_metadata_value(d, "stem.high_tension", 100000.0)
            self.assertEqual(100000.0, d["instrument"]["high_tension"])
            self.assertTrue(Metadata.has_metadata_value(d, "stem.high_tension"))
            self.assertEqual(100000.0, Metadata.get_metadata_value(d, "stem.high_tension"))
            Metadata.delete_metadata_value(d, "stem.high_tension")
            self.assertFalse(Metadata.has_metadata_value(d, "stem.high_tension"))
            # test a session metadata value
            self.assertFalse(Metadata.has_metadata_value(d, "stem.session.sample"))
            Metadata.set_metadata_value(d, "stem.session.sample", "Unobtainium")
            self.assertEqual("Unobtainium", d["session_metadata"]["sample"])
            self.assertTrue(Metadata.has_metadata_value(d, "stem.session.sample"))
            self.assertEqual("Unobtainium", Metadata.get_metadata_value(d, "stem.session.sample"))
            Metadata.delete_metadata_value(d, "stem.session.sample")
            self.assertFalse(Metadata.has_metadata_value(d, "stem.session.sample"))


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
