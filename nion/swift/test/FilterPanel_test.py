# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import FilterPanel
from nion.swift.model import DataItem
from nion.swift.test import TestContext
from nion.ui import TestUI


class TestFilterPanelClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)
        self.t = FilterPanel.TreeNode()
        self.t.insert_value(["1969", "02"], "Chris")
        self.t.insert_value(["1965", "12"], "Hans")
        self.t.insert_value(["1970", "02"], "Lara")
        self.t.insert_value(["2000", "06"], "Julian")
        self.t.insert_value(["2000", "03"], "Holden")
        self.t.insert_value(["2000", "06"], "Tristan")
        self.t.insert_value(["2000", "06"], "Skywalker")

    def tearDown(self):
        TestContext.end_leaks(self)

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

    def test_setting_text_filter_updates_filter_display_items(self):
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item1 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item1.title = "abc"
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.random.randn(4, 4))
            data_item2.title = "def"
            document_model.append_data_item(data_item2)
            document_controller.filter_controller.text_filter_changed("abc")
            display_items = document_controller.filtered_display_items_model.items
            self.assertEqual(1, len(display_items))
            self.assertEqual(data_item1, display_items[0].data_item)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
