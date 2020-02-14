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
from nion.swift import MimeTypes
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Profile
from nion.swift.model import Symbolic
from nion.ui import TestUI


Facade.initialize()


def create_memory_profile_context() -> Profile.MemoryProfileContext:
    return Profile.MemoryProfileContext()


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
            computation.create_input_item("a", Symbolic.make_item(data_item1))
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
            computation.create_input_item("a", Symbolic.make_item(data_item1))
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
            computation.create_input_item("a", Symbolic.make_item(data_item1))
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
            computation.create_input_item("a", Symbolic.make_item(data_item1))
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
            computation.create_input_item("a", Symbolic.make_item(data_item1))
            computation.create_variable("x", value_type="integral", value=5)
            document_model.set_data_item_computation(data_item2, computation)
            panel1 = ComputationPanel.EditComputationDialog(document_controller, data_item1)
            with contextlib.closing(panel1):
                document_controller.periodic()  # execute queue
                self.assertEqual(len(panel1._sections_for_testing), 0)
                panel2 = ComputationPanel.EditComputationDialog(document_controller, data_item2)
                with contextlib.closing(panel2):
                    document_controller.periodic()  # execute queue
                    self.assertEqual(len(panel2._sections_for_testing), 2)
                    document_controller.periodic()  # execute queue
                    self.assertEqual(len(panel1._sections_for_testing), 0)

    def test_change_variable_command_resulting_in_error_undo_redo(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            # setup
            data_item1 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item2)
            data_item3 = DataItem.DataItem(numpy.zeros((10, )))
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation("target.xdata = a.xdata[1] + x")
            variable = computation.create_input_item("a", Symbolic.make_item(data_item2))
            computation.create_variable("x", value_type="integral", value=5)
            document_model.set_data_item_computation(data_item1, computation)
            # verify setup
            self.assertEqual(data_item2, computation.get_input("a"))
            document_model.recompute_all()
            document_controller.periodic()
            # change variable
            variable_specifier = document_model.get_object_specifier(data_item3)
            properties = {"variable_type": "data_item", "specifier": variable_specifier}
            command = ComputationPanel.ComputationModel.ChangeVariableCommand(document_controller.document_model, computation, variable, **properties)
            command.perform()
            document_controller.push_undo_command(command)
            # verify change and trigger error
            self.assertEqual(data_item3, computation.get_input("a"))
            document_model.recompute_all()
            document_controller.periodic()
            self.assertIsNotNone(computation.error_text)
            # undo and verify
            document_controller.handle_undo()
            self.assertEqual(data_item2, computation.get_input("a"))
            document_model.recompute_all()
            document_controller.periodic()
            self.assertIsNone(computation.error_text)
            # redo and verify
            document_controller.handle_redo()
            document_model.recompute_all()
            document_controller.periodic()
            self.assertEqual(data_item3, computation.get_input("a"))
            self.assertIsNotNone(computation.error_text)

    def test_change_variable_command_resulting_in_creating_data_item_undo_redo(self):
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        with contextlib.closing(document_controller):
            # setup
            data_item1 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item1)
            data_item2 = DataItem.DataItem(numpy.zeros((10, 10)))
            document_model.append_data_item(data_item2)
            data_item3 = DataItem.DataItem(numpy.zeros((10, )))
            document_model.append_data_item(data_item3)
            computation = document_model.create_computation("target.xdata = a.xdata[1] + x")
            variable = computation.create_input_item("a", Symbolic.make_item(data_item3))
            computation.create_variable("x", value_type="integral", value=5)
            document_model.set_data_item_computation(data_item1, computation)
            # verify setup
            self.assertEqual(data_item3, computation.get_input("a"))
            document_model.recompute_all()
            document_controller.periodic()
            self.assertIsNotNone(computation.error_text)
            # change variable
            variable_specifier = document_model.get_object_specifier(data_item2)
            properties = {"variable_type": "data_item", "specifier": variable_specifier}
            command = ComputationPanel.ComputationModel.ChangeVariableCommand(document_controller.document_model, computation, variable, **properties)
            command.perform()
            document_controller.push_undo_command(command)
            # verify change and trigger computation
            self.assertEqual(data_item2, computation.get_input("a"))
            document_model.recompute_all()
            document_controller.periodic()
            self.assertIsNone(computation.error_text)
            # undo and verify
            document_controller.handle_undo()
            self.assertEqual(data_item3, computation.get_input("a"))
            document_model.recompute_all()
            document_controller.periodic()
            self.assertIsNotNone(computation.error_text)
            # redo and verify
            document_controller.handle_redo()
            document_model.recompute_all()
            document_controller.periodic()
            self.assertEqual(data_item2, computation.get_input("a"))
            self.assertIsNone(computation.error_text)

    def test_dropping_data_source_from_different_project_works(self):
        # create three data items, two in the first project, one in the second project.
        # create the computation with the first two. then simulate a drag and drop from
        # the second project. recompute and make sure no error occur.
        with create_memory_profile_context() as profile_context:
            profile = profile_context.create_profile()
            profile.add_project_memory()
            document_model = DocumentModel.DocumentModel(profile=profile)
            document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
            with contextlib.closing(document_controller):
                data1 = ((numpy.abs(numpy.random.randn(8, 8)) + 1) * 10).astype(numpy.uint32)
                data2 = ((numpy.abs(numpy.random.randn(8, 8)) + 1) * 10).astype(numpy.uint32)
                data3 = ((numpy.abs(numpy.random.randn(8, 8)) + 1) * 10).astype(numpy.uint32)
                data_item1 = DataItem.DataItem(data1)
                data_item2 = DataItem.DataItem(data2)
                data_item3 = DataItem.DataItem(data3)
                document_model.append_data_item(data_item1, project=document_model.profile.projects[0])
                document_model.append_data_item(data_item2, project=document_model.profile.projects[0])
                document_model.append_data_item(data_item3, project=document_model.profile.projects[1])
                display_item1 = document_model.get_display_item_for_data_item(data_item1)
                display_item2 = document_model.get_display_item_for_data_item(data_item2)
                display_item3 = document_model.get_display_item_for_data_item(data_item3)
                document_controller.select_display_items_in_data_panel([display_item1, display_item2])
                document_controller.processing_cross_correlate_new()
                computation = document_model.computations[-1]
                document_model.recompute_all()
                self.assertIsNone(document_model.computations[0].error_text)
                mime_data = self.app.ui.create_mime_data()
                MimeTypes.mime_data_put_data_source(mime_data, display_item3, None)
                ComputationPanel.drop_mime_data(document_controller, computation, computation.variables[1], mime_data, 0, 0)
                document_model.recompute_all()
                self.assertIsNone(document_model.computations[0].error_text)

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
