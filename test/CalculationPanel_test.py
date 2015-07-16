# futures
from __future__ import absolute_import

# standard libraries
import unittest

# third party libraries
# None

# local libraries
from nion.swift import Application
from nion.ui import Test


class TestCalculationPanelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def disabled_test_expression_updates_when_variable_is_assigned(self):
        raise Exception()

    def disabled_test_expression_udpates_when_node_is_changed(self):
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
