# futures
from __future__ import absolute_import

# standard libraries
import os
import unittest

# local libraries
from nion.swift import Decorators


class TestDecoratorsClass(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_relative_file(self):
        f = Decorators.relative_file(__file__, "test.dat")
        self.assertEqual(os.path.basename(f), "test.dat")
        self.assertEqual(os.path.dirname(os.path.abspath(__file__)), os.path.dirname(f))