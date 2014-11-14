# standard libraries
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.test import DocumentController_test
from nion.ui import Geometry
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
        self.assertEqual(document_controller.workspace.layout_id, "1x1")
        document_controller.workspace.change_to_next_layout()
        self.assertEqual(document_controller.workspace.layout_id, "3x1")
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
        self.assertEqual(document_controller.workspace.layout_id, "3x1")
        document_controller.workspace.change_to_next_layout()
        self.assertEqual(document_controller.workspace.layout_id, "1x1")
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

    def test_image_panel_focused_when_clicked(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
        data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
        document_model.append_data_item(data_item1)
        document_model.append_data_item(data_item2)
        document_controller.workspace.change_layout("2x1")
        root_canvas_item = document_controller.workspace.image_row.children[0]._root_canvas_item()
        root_canvas_item.update_layout(Geometry.IntPoint(), Geometry.IntSize(width=640, height=480))
        # click in first panel
        modifiers = Test.KeyboardModifiers()
        root_canvas_item.canvas_widget.on_mouse_clicked(160, 240, modifiers)
        self.assertTrue(document_controller.workspace.image_panels[0]._is_focused())
        self.assertTrue(document_controller.workspace.image_panels[0]._is_selected())
        self.assertFalse(document_controller.workspace.image_panels[1]._is_focused())
        self.assertFalse(document_controller.workspace.image_panels[1]._is_selected())
        # now click the second panel
        root_canvas_item.canvas_widget.on_mouse_clicked(480, 240, modifiers)
        self.assertFalse(document_controller.workspace.image_panels[0]._is_focused())
        self.assertFalse(document_controller.workspace.image_panels[0]._is_selected())
        self.assertTrue(document_controller.workspace.image_panels[1]._is_focused())
        self.assertTrue(document_controller.workspace.image_panels[1]._is_selected())
        # and back to the first panel
        modifiers = Test.KeyboardModifiers()
        root_canvas_item.canvas_widget.on_mouse_clicked(160, 240, modifiers)
        self.assertTrue(document_controller.workspace.image_panels[0]._is_focused())
        self.assertTrue(document_controller.workspace.image_panels[0]._is_selected())
        self.assertFalse(document_controller.workspace.image_panels[1]._is_focused())
        self.assertFalse(document_controller.workspace.image_panels[1]._is_selected())

    def test_workspace_construct_and_deconstruct_result_in_matching_descriptions(self):
        # setup
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        data_item1 = DataItem.DataItem(numpy.zeros((256), numpy.double))
        data_item2 = DataItem.DataItem(numpy.zeros((256), numpy.double))
        document_model.append_data_item(data_item1)
        document_model.append_data_item(data_item2)
        document_controller.workspace.change_layout("2x1")
        root_canvas_item = document_controller.workspace.image_row.children[0]._root_canvas_item()
        root_canvas_item.update_layout(Geometry.IntPoint(), Geometry.IntSize(width=640, height=480))
        # deconstruct
        desc1 = document_controller.workspace._get_default_layout("2x1")[1]
        desc2 = document_controller.workspace._deconstruct(root_canvas_item.canvas_items[0])
        self.assertEqual(desc1, desc2)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
