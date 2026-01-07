# standard libraries
import pathlib
import typing
import unittest

# local libraries
from nion.swift import ExportDialog
from nion.swift.test import TestContext


class TestExportDialog(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()

    def tearDown(self):
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def test_model(self):
        model = ExportDialog.ExportDialogViewModel(
            title=True,
            date=False,
            dimensions=False,
            sequence=False,
            writer=None,
            prefix=None,
            directory=None)
        # initial case - no directory
        self.assertIsNotNone(model.directory_warning.value)
        self.assertFalse(model.export_button_enabled.value)
        self.assertIsNotNone(model.export_button_tool_tip.value)
        # directory case
        model.directory.value = str(pathlib.Path.cwd())
        self.assertFalse(model.directory_warning.value)
        self.assertTrue(model.export_button_enabled.value)
        self.assertFalse(model.export_button_tool_tip.value)
        # bad prefix case
        model.prefix.value = "bad/prefix"
        self.assertIsNotNone(model.directory_warning.value)
        self.assertFalse(model.export_button_enabled.value)
        self.assertIsNotNone(model.export_button_tool_tip.value)


if __name__ == '__main__':
    unittest.main()
