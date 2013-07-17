import os
import unittest
import weakref

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