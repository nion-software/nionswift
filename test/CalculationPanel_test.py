# futures
from __future__ import absolute_import

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
from nion.swift.model import Symbolic
from nion.ui import Test


class TestCalculationPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def disabled_test_expression_updates_when_variable_is_assigned(self):
        raise Exception()

    def test_expression_updates_when_node_is_changed(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        panel = document_controller.find_dock_widget("calculation-panel").panel
        data_item1 = DataItem.DataItem(numpy.zeros((10, 10)))
        document_model.append_data_item(data_item1)
        data_item2 = DataItem.DataItem(numpy.zeros((10, 10)))
        document_model.append_data_item(data_item2)
        map = {"a": document_model.get_object_specifier(data_item1)}
        computation = Symbolic.Computation()
        computation.parse_expression(document_model, "-a", map)
        data_item2.maybe_data_source.set_computation(computation)
        document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item2))
        document_controller.periodic()  # execute queue
        text1 = panel._text_edit_for_testing.text
        self.assertEqual(text1, computation.reconstruct(document_controller.build_variable_map()))
        data_item2.maybe_data_source.computation.parse_expression(document_model, "-a+1", map)
        document_controller.periodic()  # execute queue
        text2 = panel._text_edit_for_testing.text
        self.assertEqual(text2, computation.reconstruct(document_controller.build_variable_map()))
        self.assertNotEqual(text2, text1)

    def disabled_test_clearing_computation_clears_text_and_unbinds_or_whatever(self):
        raise Exception()

    def disabled_test_calculation_panel_provides_help_button(self):
        raise Exception()

    def disabled_test_invalid_expression_shows_error(self):
        raise Exception()

    def disabled_test_new_button_create_new_data_item(self):
        raise Exception()

    def disabled_test_invalid_expression_saves_text_for_editing(self):
        raise Exception()

    def disabled_test_knobs_for_computations_appear_in_inspector(self):
        assert False
