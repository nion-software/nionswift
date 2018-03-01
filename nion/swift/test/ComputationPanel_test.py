# standard libraries
import contextlib
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import ComputationPanel
from nion.swift import DocumentController
from nion.swift import Facade
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.ui import TestUI


Facade.initialize()


class TestComputationPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_expression_updates_when_node_is_changed(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("target.xdata = -a.xdata")
            computation.create_object("a", document_model.get_object_specifier(data_item1))
            document_model.set_data_item_computation(data_item2, computation)
            panel = ComputationPanel.EditComputationDialog(document_controller, data_item2)
            document_controller.periodic()  # execute queue
            text1 = panel._text_edit_for_testing.text
            document_model.get_data_item_computation(data_item2).expression = "target.xdata = -a.xdata + 1"
            document_controller.periodic()  # execute queue
            text2 = panel._text_edit_for_testing.text
            self.assertNotEqual(text2, text1)

    def test_clearing_computation_clears_text_and_unbinds_or_whatever(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("target.xdata = -a.xdata")
            computation.create_object("a", document_model.get_object_specifier(data_item1))
            document_model.set_data_item_computation(data_item2, computation)
            panel = ComputationPanel.EditComputationDialog(document_controller, data_item2)
            document_controller.periodic()  # execute queue
            panel._text_edit_for_testing.text = ""
            panel._update_button.on_clicked()
            document_controller.periodic()
            self.assertIsNone(document_model.get_data_item_computation(data_item2))
            text2 = panel._text_edit_for_testing.text
            self.assertFalse(text2)

    def test_invalid_expression_shows_error_and_clears_it(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("target.xdata = -a.xdata")
            computation.create_object("a", document_model.get_object_specifier(data_item1))
            document_model.set_data_item_computation(data_item2, computation)
            panel = ComputationPanel.EditComputationDialog(document_controller, data_item2)
            document_controller.periodic()  # let the inspector see the computation
            document_controller.periodic()  # and update the computation
            expression = panel._text_edit_for_testing.text
            self.assertIsNone(panel._error_label_for_testing.text)
            panel._text_edit_for_testing.text = "target.xdata = xyz(a.xdata)"
            panel._update_button.on_clicked()
            # the sequence of periodic/recompute_all is intentional, to test various computation states
            document_controller.periodic()
            document_model.recompute_all()
            document_model.recompute_all()
            document_controller.periodic()
            self.assertEqual(panel._text_edit_for_testing.text, "target.xdata = xyz(a.xdata)")
            self.assertTrue(len(panel._error_label_for_testing.text) > 0)
            panel._text_edit_for_testing.text = expression
            panel._update_button.on_clicked()
            # the sequence of periodic/recompute_all is intentional, to test various computation states
            document_controller.periodic()
            document_model.recompute_all()
            document_model.recompute_all()
            document_controller.periodic()
            self.assertEqual(panel._text_edit_for_testing.text, expression)
            self.assertIsNone(panel._error_label_for_testing.text)

    def test_error_text_cleared_after_invalid_script_becomes_valid(self):
        # similar to test_invalid_expression_shows_error_and_clears_it except periodic occurs before recompute at end
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("target.xdata = -a.xdata")
            computation.create_object("a", document_model.get_object_specifier(data_item1))
            document_model.set_data_item_computation(data_item2, computation)
            panel = ComputationPanel.EditComputationDialog(document_controller, data_item2)
            document_controller.periodic()  # let the inspector see the computation
            document_controller.periodic()  # and update the computation
            expression = panel._text_edit_for_testing.text
            self.assertIsNone(panel._error_label_for_testing.text)
            panel._text_edit_for_testing.text = "target.xdata = xyz(a.xdata)"
            panel._update_button.on_clicked()
            # the sequence of periodic/recompute_all is intentional, to test various computation states
            document_controller.periodic()
            document_model.recompute_all()
            document_model.recompute_all()
            document_controller.periodic()
            self.assertEqual(panel._text_edit_for_testing.text, "target.xdata = xyz(a.xdata)")
            self.assertTrue(len(panel._error_label_for_testing.text) > 0)
            panel._text_edit_for_testing.text = expression
            panel._update_button.on_clicked()
            # the sequence of periodic/recompute_all is intentional, to test various computation states
            document_controller.periodic()
            document_model.recompute_all()
            document_model.recompute_all()
            document_controller.periodic()
            self.assertEqual(panel._text_edit_for_testing.text, expression)
            self.assertIsNone(panel._error_label_for_testing.text)

    def test_variables_get_updates_when_switching_data_items(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            data_item1 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item2)
            computation = document_model.create_computation("target.xdata = a.xdata + x")
            computation.create_object("a", document_model.get_object_specifier(data_item1))
            computation.create_variable("x", value_type="integral", value=5)
            document_model.set_data_item_computation(data_item2, computation)
            panel1 = ComputationPanel.EditComputationDialog(document_controller, data_item1)
            document_controller.periodic()  # execute queue
            self.assertEqual(len(panel1._sections_for_testing), 0)
            panel2 = ComputationPanel.EditComputationDialog(document_controller, data_item2)
            document_controller.periodic()  # execute queue
            self.assertEqual(len(panel2._sections_for_testing), 2)
            document_controller.periodic()  # execute queue
            self.assertEqual(len(panel1._sections_for_testing), 0)

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
