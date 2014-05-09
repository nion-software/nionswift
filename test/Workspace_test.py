# standard libraries
import logging
import unittest

# third party libraries
# None

# local libraries
from nion.swift import Application
from nion.swift.model import DataItem
from nion.swift.test import DocumentController_test
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
        self.assertEqual(document_controller.workspace.image_panels[0].get_displayed_data_item(), document_controller.document_model.data_items[0])
        document_controller.workspace.change_layout("3x1")
        self.assertEqual(document_controller.workspace.image_panels[0].get_displayed_data_item(), document_controller.document_model.data_items[0])
        self.assertEqual(document_controller.workspace.image_panels[1].get_displayed_data_item(), document_controller.document_model.data_items[1])
        self.assertEqual(document_controller.workspace.image_panels[2].get_displayed_data_item(), document_controller.document_model.data_items[2])

    def test_change_layout_1x1_to_3x1_should_choose_derived_data_if_present(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        derived_data_item = DataItem.DataItem()
        derived_data_item.add_data_source(document_controller.document_model.data_items[0])
        document_controller.document_model.append_data_item(derived_data_item)
        document_controller.workspace.change_layout("1x1")
        self.assertEqual(document_controller.workspace.image_panels[0].get_displayed_data_item(), document_controller.document_model.data_items[0])
        document_controller.workspace.change_layout("3x1")
        self.assertEqual(document_controller.workspace.image_panels[0].get_displayed_data_item(), document_controller.document_model.data_items[0])
        self.assertEqual(document_controller.workspace.image_panels[1].get_displayed_data_item(), derived_data_item)
        self.assertEqual(document_controller.workspace.image_panels[2].get_displayed_data_item(), document_controller.document_model.data_items[1])

    def test_change_layout_1x1_to_3x1_should_choose_preferred_data_if_present(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        derived_data_item = DataItem.DataItem()
        derived_data_item.add_data_source(document_controller.document_model.data_items[0])
        document_controller.document_model.append_data_item(derived_data_item)
        document_controller.workspace.change_layout("1x1")
        self.assertEqual(document_controller.workspace.image_panels[0].get_displayed_data_item(), document_controller.document_model.data_items[0])
        preferred_data_items = (derived_data_item, document_controller.document_model.data_items[2], document_controller.document_model.data_items[0])
        document_controller.workspace.change_layout("3x1", preferred_data_items)
        self.assertEqual(document_controller.workspace.image_panels[0].get_displayed_data_item(), derived_data_item)
        self.assertEqual(document_controller.workspace.image_panels[1].get_displayed_data_item(), document_controller.document_model.data_items[2])
        self.assertEqual(document_controller.workspace.image_panels[2].get_displayed_data_item(), document_controller.document_model.data_items[0])

    def test_change_layout_1x1_to_3x1_should_choose_preferred_data_if_present_then_already_displayed_data(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        derived_data_item = DataItem.DataItem()
        derived_data_item.add_data_source(document_controller.document_model.data_items[0])
        document_controller.document_model.append_data_item(derived_data_item)
        document_controller.workspace.change_layout("1x1")
        document_controller.workspace.image_panels[0].set_displayed_data_item(document_controller.document_model.data_items[1])
        self.assertEqual(document_controller.workspace.image_panels[0].get_displayed_data_item(), document_controller.document_model.data_items[1])
        preferred_data_items = (derived_data_item, document_controller.document_model.data_items[2])
        document_controller.workspace.change_layout("3x1", preferred_data_items)
        self.assertEqual(document_controller.workspace.image_panels[0].get_displayed_data_item(), derived_data_item)
        self.assertEqual(document_controller.workspace.image_panels[1].get_displayed_data_item(), document_controller.document_model.data_items[2])
        self.assertEqual(document_controller.workspace.image_panels[2].get_displayed_data_item(), document_controller.document_model.data_items[1])

    def test_change_layout_to_1x1_should_always_choose_selected_data(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        document_controller.workspace.change_layout("3x1")
        document_controller.selected_image_panel = document_controller.workspace.image_panels[1]
        self.assertEqual(document_controller.selected_image_panel.get_displayed_data_item(), document_controller.document_model.data_items[1])
        document_controller.workspace.change_layout("1x1")
        self.assertEqual(document_controller.workspace.image_panels[0].get_displayed_data_item(), document_controller.document_model.data_items[1])

    def test_change_layout_3x1_to_1x1_to_previous_should_remember_3x1(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        derived_data_item = DataItem.DataItem()
        derived_data_item.add_data_source(document_controller.document_model.data_items[0])
        document_controller.document_model.append_data_item(derived_data_item)
        preferred_data_items = (derived_data_item, document_controller.document_model.data_items[2], document_controller.document_model.data_items[1])
        document_controller.workspace.change_layout("3x1", preferred_data_items)
        document_controller.workspace.change_layout("1x1")
        document_controller.workspace.change_to_previous_layout()
        self.assertEqual(document_controller.workspace.image_panels[0].get_displayed_data_item(), preferred_data_items[0])
        self.assertEqual(document_controller.workspace.image_panels[1].get_displayed_data_item(), preferred_data_items[1])
        self.assertEqual(document_controller.workspace.image_panels[2].get_displayed_data_item(), preferred_data_items[2])

    def test_change_layout_1x1_to_3x1_to_previous_to_next_should_remember_3x1(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        derived_data_item = DataItem.DataItem()
        derived_data_item.add_data_source(document_controller.document_model.data_items[0])
        document_controller.document_model.append_data_item(derived_data_item)
        preferred_data_items = (derived_data_item, document_controller.document_model.data_items[2], document_controller.document_model.data_items[1])
        document_controller.workspace.change_layout("1x1")
        document_controller.workspace.change_layout("3x1", preferred_data_items)
        document_controller.workspace.change_to_previous_layout()
        self.assertEqual(document_controller.workspace.current_layout_id, "1x1")
        document_controller.workspace.change_to_next_layout()
        self.assertEqual(document_controller.workspace.current_layout_id, "3x1")
        self.assertEqual(document_controller.workspace.image_panels[0].get_displayed_data_item(), preferred_data_items[0])
        self.assertEqual(document_controller.workspace.image_panels[1].get_displayed_data_item(), preferred_data_items[1])
        self.assertEqual(document_controller.workspace.image_panels[2].get_displayed_data_item(), preferred_data_items[2])

    def test_change_layout_3x1_to_1x1_to_previous_to_next_should_remember_1x1(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        derived_data_item = DataItem.DataItem()
        derived_data_item.add_data_source(document_controller.document_model.data_items[0])
        document_controller.document_model.append_data_item(derived_data_item)
        preferred_data_items = (derived_data_item, document_controller.document_model.data_items[2], document_controller.document_model.data_items[1])
        document_controller.workspace.change_layout("3x1", preferred_data_items)
        document_controller.selected_image_panel = document_controller.workspace.image_panels[1]
        document_controller.workspace.change_layout("1x1")
        document_controller.workspace.change_to_previous_layout()
        self.assertEqual(document_controller.workspace.current_layout_id, "3x1")
        document_controller.workspace.change_to_next_layout()
        self.assertEqual(document_controller.workspace.current_layout_id, "1x1")
        self.assertEqual(document_controller.workspace.image_panels[0].get_displayed_data_item(), document_controller.document_model.data_items[2])

    def test_add_processing_in_4x4_bottom_left_puts_processed_image_in_empty_bottom_right(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        derived_data_item = DataItem.DataItem()
        derived_data_item.add_data_source(document_controller.document_model.data_items[0])
        document_controller.document_model.append_data_item(derived_data_item)
        document_controller.workspace.change_layout("2x2")
        document_controller.workspace.image_panels[3].set_displayed_data_item(None)
        document_controller.selected_image_panel = document_controller.workspace.image_panels[2]
        source_data_item = document_controller.workspace.image_panels[2].get_displayed_data_item()
        derived_data_item2 = DataItem.DataItem()
        derived_data_item2.add_data_source(source_data_item)
        document_controller.document_model.append_data_item(derived_data_item2)
        document_controller.workspace.display_data_item(derived_data_item2, source_data_item)
        self.assertEqual(document_controller.workspace.image_panels[2].get_displayed_data_item(), source_data_item)
        self.assertEqual(document_controller.workspace.image_panels[3].get_displayed_data_item(), derived_data_item2)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
