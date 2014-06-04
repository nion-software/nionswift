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

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
