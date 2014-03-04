# standard libraries
import logging
import unittest

# third party libraries
# None

# local libraries
from nion.swift import Application
from nion.swift import DataItem
from nion.swift import Workspace
from nion.swift.test import DocumentController_test
from nion.ui import UserInterface
from nion.ui import Test


class TestWorkspaceClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_basic_change_layout_results_in_correct_image_panel_count(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        document_controller.workspace.change_layout("1x1")
        self.assertEqual(len(document_controller.workspace.image_panels), 1)
        document_controller.workspace.change_layout("1x1")
        self.assertEqual(len(document_controller.workspace.image_panels), 1)
        document_controller.workspace.change_layout("2x1")
        self.assertEqual(len(document_controller.workspace.image_panels), 2)
        document_controller.workspace.change_layout("3x1")
        self.assertEqual(len(document_controller.workspace.image_panels), 3)
        document_controller.workspace.change_layout("2x2")
        self.assertEqual(len(document_controller.workspace.image_panels), 4)
        document_controller.workspace.change_layout("3x2")
        self.assertEqual(len(document_controller.workspace.image_panels), 6)
        document_controller.workspace.change_layout("1x2")
        self.assertEqual(len(document_controller.workspace.image_panels), 2)
        document_controller.workspace.change_layout("1x1")
        self.assertEqual(len(document_controller.workspace.image_panels), 1)

    def test_change_layout_1x1_to_3x1_should_choose_different_data_items(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        document_controller.workspace.change_layout("1x1")
        self.assertEqual(document_controller.workspace.image_panels[0].data_item, document_controller.document_model.data_items[0])
        document_controller.workspace.change_layout("3x1")
        self.assertEqual(document_controller.workspace.image_panels[0].data_item, document_controller.document_model.data_items[0])
        self.assertEqual(document_controller.workspace.image_panels[1].data_item, document_controller.document_model.data_items[1])
        self.assertEqual(document_controller.workspace.image_panels[2].data_item, document_controller.document_model.data_items[2])

    def test_change_layout_1x1_to_3x1_should_choose_derived_data_if_present(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        derived_data_item = DataItem.DataItem()
        document_controller.document_model.data_items[0].data_items.append(derived_data_item)
        document_controller.workspace.change_layout("1x1")
        self.assertEqual(document_controller.workspace.image_panels[0].data_item, document_controller.document_model.data_items[0])
        document_controller.workspace.change_layout("3x1")
        self.assertEqual(document_controller.workspace.image_panels[0].data_item, document_controller.document_model.data_items[0])
        self.assertEqual(document_controller.workspace.image_panels[1].data_item, derived_data_item)
        self.assertEqual(document_controller.workspace.image_panels[2].data_item, document_controller.document_model.data_items[1])

    def test_change_layout_1x1_to_3x1_should_choose_preferred_data_if_present(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        derived_data_item = DataItem.DataItem()
        document_controller.document_model.data_items[0].data_items.append(derived_data_item)
        document_controller.workspace.change_layout("1x1")
        self.assertEqual(document_controller.workspace.image_panels[0].data_item, document_controller.document_model.data_items[0])
        preferred_data_items = (derived_data_item, document_controller.document_model.data_items[2], document_controller.document_model.data_items[0])
        document_controller.workspace.change_layout("3x1", preferred_data_items)
        self.assertEqual(document_controller.workspace.image_panels[0].data_item, derived_data_item)
        self.assertEqual(document_controller.workspace.image_panels[1].data_item, document_controller.document_model.data_items[2])
        self.assertEqual(document_controller.workspace.image_panels[2].data_item, document_controller.document_model.data_items[0])

    def test_change_layout_1x1_to_3x1_should_choose_preferred_data_if_present_then_already_displayed_data(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        derived_data_item = DataItem.DataItem()
        document_controller.document_model.data_items[0].data_items.append(derived_data_item)
        document_controller.workspace.change_layout("1x1")
        document_controller.workspace.image_panels[0].data_item = document_controller.document_model.data_items[1]
        self.assertEqual(document_controller.workspace.image_panels[0].data_item, document_controller.document_model.data_items[1])
        preferred_data_items = (derived_data_item, document_controller.document_model.data_items[2])
        document_controller.workspace.change_layout("3x1", preferred_data_items)
        self.assertEqual(document_controller.workspace.image_panels[0].data_item, derived_data_item)
        self.assertEqual(document_controller.workspace.image_panels[1].data_item, document_controller.document_model.data_items[2])
        self.assertEqual(document_controller.workspace.image_panels[2].data_item, document_controller.document_model.data_items[1])

    def test_change_layout_to_1x1_should_always_choose_selected_data(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        document_controller.workspace.change_layout("3x1")
        document_controller.selected_image_panel = document_controller.workspace.image_panels[1]
        self.assertEqual(document_controller.selected_image_panel.data_item, document_controller.document_model.data_items[1])
        document_controller.workspace.change_layout("1x1")
        self.assertEqual(document_controller.workspace.image_panels[0].data_item, document_controller.document_model.data_items[1])

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
