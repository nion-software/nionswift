# futures
from __future__ import absolute_import

# standard libraries
import logging
import unittest

# third party libraries
# None

# local libraries
from nion.swift import FilterPanel


class TestFilterPanelClass(unittest.TestCase):

    def setUp(self):
        self.t = FilterPanel.TreeNode()
        self.t.insert_value(["1969", "02"], "Chris")
        self.t.insert_value(["1965", "12"], "Hans")
        self.t.insert_value(["1970", "02"], "Lara")
        self.t.insert_value(["2000", "06"], "Julian")
        self.t.insert_value(["2000", "03"], "Holden")
        self.t.insert_value(["2000", "06"], "Tristan")
        self.t.insert_value(["2000", "06"], "Skywalker")

    def tearDown(self):
        pass

    def test_basic_tree_construction(self):
        self.assertEqual(self.t.count, 7)
        self.assertEqual(self.t.children[1].key, "1969")
        self.assertEqual(self.t.children[1].count, 1)
        self.assertEqual(self.t.children[3].key, "2000")
        self.assertEqual(self.t.children[3].count, 4)
        self.assertEqual(self.t.children[3].children[1].key, "06")
        self.assertEqual(self.t.children[3].children[1].count, 3)

    def test_remove_value_updates_counts(self):
        self.t.remove_value(None, "Skywalker")
        self.assertEqual(self.t.count, 6)
        self.assertEqual(self.t.children[3].key, "2000")
        self.assertEqual(self.t.children[3].count, 3)
        self.assertEqual(self.t.children[3].children[1].key, "06")
        self.assertEqual(self.t.children[3].children[1].count, 2)

    def test_remove_value_removes_empty_nodes(self):
        self.assertEqual(self.t.children[0].key, "1965")
        self.t.remove_value(None, "Hans")
        self.assertEqual(self.t.count, 6)
        self.assertEqual(self.t.children[0].key, "1969")


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
