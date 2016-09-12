# standard libraries
import contextlib
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.ui import TestUI


class TestComputationPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_expression_updates_when_node_is_changed(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            panel = document_controller.find_dock_widget("computation-panel").panel
            data_item1 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("-a")
            computation.create_object("a", document_model.get_object_specifier(data_item1, "data"))
            data_item2.maybe_data_source.set_computation(computation)
            document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item2))
            document_controller.periodic()  # execute queue
            text1 = panel._text_edit_for_testing.text
            data_item2.maybe_data_source.computation.expression = "-a+1"
            document_controller.periodic()  # execute queue
            text2 = panel._text_edit_for_testing.text
            self.assertNotEqual(text2, text1)

    def test_clearing_computation_clears_text_and_unbinds_or_whatever(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            panel = document_controller.find_dock_widget("computation-panel").panel
            data_item1 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("-a")
            computation.create_object("a", document_model.get_object_specifier(data_item1, "data"))
            data_item2.maybe_data_source.set_computation(computation)
            document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item2))
            document_controller.periodic()  # execute queue
            panel._text_edit_for_testing.text = ""
            panel._text_edit_for_testing.on_return_pressed()
            document_controller.periodic()
            self.assertIsNone(data_item2.maybe_data_source.computation)
            text2 = panel._text_edit_for_testing.text
            self.assertFalse(text2)

    def test_invalid_expression_shows_error_and_clears_it(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            panel = document_controller.find_dock_widget("computation-panel").panel
            data_item1 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("-a")
            computation.create_object("a", document_model.get_object_specifier(data_item1, "data"))
            data_item2.maybe_data_source.set_computation(computation)
            document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item2))
            document_controller.periodic()  # let the inspector see the computation
            document_controller.periodic()  # and update the computation
            expression = panel._text_edit_for_testing.text
            self.assertIsNone(panel._error_label_for_testing.text)
            panel._text_edit_for_testing.text = "xyz(a)"
            panel._text_edit_for_testing.on_return_pressed()
            document_model.recompute_all()
            document_controller.periodic()
            self.assertEqual(panel._text_edit_for_testing.text, "xyz(a)")
            self.assertTrue(len(panel._error_label_for_testing.text) > 0)
            panel._text_edit_for_testing.text = expression
            panel._text_edit_for_testing.on_return_pressed()
            document_model.recompute_all()
            document_controller.periodic()
            self.assertEqual(panel._text_edit_for_testing.text, expression)
            self.assertIsNone(panel._error_label_for_testing.text)

    def test_variables_get_updates_when_switching_data_items(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            panel = document_controller.find_dock_widget("computation-panel").panel
            data_item1 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("a + x")
            computation.create_object("a", document_model.get_object_specifier(data_item1, "data"))
            computation.create_variable("x", value_type="integral", value=5)
            data_item2.maybe_data_source.set_computation(computation)
            document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item1))
            document_controller.periodic()  # execute queue
            self.assertEqual(len(panel._sections_for_testing), 0)
            document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item2))
            document_controller.periodic()  # execute queue
            self.assertEqual(len(panel._sections_for_testing), 2)
            document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item1))
            document_controller.periodic()  # execute queue
            self.assertEqual(len(panel._sections_for_testing), 0)

    def disabled_test_expression_updates_when_variable_is_assigned(self):
        raise Exception()

    def disabled_test_computation_panel_provides_help_button(self):
        raise Exception()

    def disabled_test_new_button_create_new_data_item(self):
        raise Exception()

    def disabled_test_invalid_expression_saves_text_for_editing(self):
        raise Exception()

    def disabled_test_knobs_for_computations_appear_in_inspector(self):
        assert False
